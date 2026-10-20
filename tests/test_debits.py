"""Tests des débits de circulation : parsing, n° de route, géométrie, appariement."""
import json
from pathlib import Path

import pytest

from etl import debits

FIX = Path(__file__).parent / "fixtures" / "debits_extrait.geojson"


def _sections():
    return {s["num"]: s for s in debits.parse(FIX.read_bytes())}


# --- n° de route ----------------------------------------------------------------------
@pytest.mark.parametrize("texte, attendu", [
    ("Autoroute 40", [40]),
    ("Autoroute 40 Ouest", [40]),
    ("Route 132", [132]),
    ("A-73 Nord", [73]),
    ("Bretelle d'accès à l'A-40 Ouest", [40]),
    ("R-161, rue de la Plaisance", [161]),
    ("rte 138", [138]),
    ("Racc. A-15 S / A-40 E", [15, 40]),
    ("Ancienne Route 138", []),
    ("9e Rang Est", []),
    ("Route du Nord", []),
    ("Boulevard des Prairies / Montée Gobeil", []),
    ("Accès route 175 (passage anticervidés)", []),              # chemin qui mène à la 175, pas la 175
    ("Chemin d'accès R-299", []),
    ("Chemin de desserte (A-20)", []),
    ("Boulevard Saguenay (route 372)", [372]),
    ("", []),
    (None, []),
])
def test_route_numbers(texte, attendu):
    assert debits.route_numbers(texte) == attendu


def test_rtss_route():
    assert debits.rtss_route("00345-01-023-000C") == 345
    assert debits.rtss_route("00073-03-205-32A0") == 73
    assert debits.rtss_route("49520-01-000-000C") is None        # code de route locale, pas un n° de route
    assert debits.rtss_route("Segment non inv. 134") is None
    assert debits.rtss_route(None) is None


# --- parsing --------------------------------------------------------------------------
def test_parse_section_publiee():
    s = _sections()["0034540000"]
    assert s["de"].startswith("chemin St-Martin") and s["rtss"] == "00345-01-023-000C"
    assert s["routes_rtss"] == {345}
    assert s["series"]["djma"][2025] == 1780 and s["series"]["djme"][2025] == 1920
    assert s["series"]["djmh"][2025] == 1600 and s["series"]["djma"][2023] == 1980
    assert s["annees"] == set(range(2016, 2026))
    assert "xlsx" not in s                                          # classeurs non proposés (v0.5.2)
    assert len(s["lignes"]) == 1 and len(s["lignes"][0]) == 4


def test_parse_pourcentage_camions_et_multiligne():
    s = _sections()["0003002000"]
    assert s["series"]["cam"][2025] == 15.48 and s["series"]["cam"][2023] == 15.64
    assert s["routes_desc"] == {40, 30}
    assert len(s["lignes"]) == 2                                   # MultiLineString


def test_parse_segment_non_inventorie_et_valeurs_absentes():
    s = _sections()["S001346880"]
    assert s["rtss"] is None and s["routes_rtss"] == set()
    assert s["series"]["djma"] == {}


def test_parse_annee_txt():
    a = debits.parse_annee_txt("2025 DJMA:1780 / DJME:1920 / DJMH:1600 / %cam: / 30e h:210")
    assert a == {"annee": 2025, "djma": 1780, "djme": 1920, "djmh": 1600, "cam": None}
    a = debits.parse_annee_txt("2023 DJMA:1000 / DJME:1080 / DJMH:900 / %cam:11")
    assert a["annee"] == 2023 and a["cam"] == 11
    assert debits.parse_annee_txt("2025 DJMA: / DJME: / DJMH: / %cam: / 30e h:")["djma"] is None
    assert debits.parse_annee_txt("n'importe quoi") is None


# --- géométrie ------------------------------------------------------------------------
def test_dist_point_segment():
    assert debits.dist_point_segment(5, 3, 0, 0, 10, 0) == 3          # projection à l'intérieur
    assert debits.dist_point_segment(-4, 3, 0, 0, 10, 0) == 5         # extrémité A (3-4-5)
    assert debits.dist_point_segment(13, 4, 0, 0, 10, 0) == 5         # extrémité B
    assert debits.dist_point_segment(1, 1, 2, 2, 2, 2) == pytest.approx(2 ** 0.5)   # segment dégénéré


def test_dist_point_ligne_m():
    # 0,001° de latitude ≈ 111,2 m ; ligne est-ouest passant 0,001° au sud du point
    ligne = [(-71.01, 46.999), (-70.99, 46.999)]
    assert debits.dist_point_ligne_m(47.0, -71.0, ligne) == pytest.approx(111.2, abs=0.5)
    assert debits.dist_point_ligne_m(47.0, -71.02, ligne) > 700       # hors de la ligne → distance à l'extrémité


# --- appariement sur un mini cas synthétique ------------------------------------------
def _sec(num, rtss_n, desc, ligne, djma=None):
    return {"num": num, "routes_rtss": {rtss_n} if rtss_n else set(),
            "routes_desc": set(debits.route_numbers(desc)), "lignes": [ligne],
            "series": {"djma": {2025: djma} if djma else {}}}


M = 0.00001                      # ≈ 1,11 m de latitude
LAT, LON = 47.0, -71.0


def _mini():
    """Route 138 est-ouest passant au point (DJMA 5 000) ; Autoroute 40 nord-sud ≈ 30 m à l'est (30 000) ;
    route locale ≈ 22 m au nord (800)."""
    secs = [
        _sec("R138", 138, "R-138", [(LON - 0.01, LAT), (LON + 0.01, LAT)], 5000),
        _sec("A40", 40, "A-40 Nord", [(LON + 0.0004, LAT - 0.01), (LON + 0.0004, LAT + 0.01)], 30000),
        _sec("LOC", None, "rue des Érables", [(LON - 0.01, LAT + 22 * M), (LON + 0.01, LAT + 22 * M)], 800),
        _sec("LOIN", 138, "R-138", [(LON - 0.01, LAT + 0.01), (LON + 0.01, LAT + 0.01)], 5000),    # ≈ 1,1 km
    ]
    idx = debits.Index()
    for i, s in enumerate(secs):
        for ligne in s["lignes"]:
            idx.add_ligne(i, ligne)
    return idx, secs


def _apparier(idx, secs, **kw):
    kw.setdefault("lat", LAT)
    kw.setdefault("lon", LON)
    return debits.apparier(idx, secs, **kw)


def _nums(secs, ids):
    return [secs[i]["num"] for i in ids]


def test_index_near():
    idx, secs = _mini()
    near = idx.near(LAT, LON, 200)
    assert set(_nums(secs, near)) == {"R138", "A40", "LOC"}           # LOIN (1,1 km) exclue
    assert near[0] < 1 and 25 < near[1] < 35 and 20 < near[2] < 25


def test_apparier_route_portee_et_franchie():
    idx, secs = _mini()
    m = _apparier(idx, secs, route="Route 138", obstacle="Autoroute 40", obstacle_route=True)
    assert _nums(secs, m["sur"]) == ["R138"] and m["dsur"] == 0
    assert _nums(secs, m["sous"]) == ["A40"] and 25 < m["dsous"] < 35
    assert m["approx"] == 0


def test_apparier_numero_prioritaire_sur_la_proximite():
    idx, secs = _mini()
    # route 40 portée : la section 40 est à 30 m alors que la 138 est à 0 m → on retient la 40
    m = _apparier(idx, secs, route="Autoroute 40 Nord", obstacle="Rivière X", obstacle_route=False)
    assert _nums(secs, m["sur"]) == ["A40"] and m["sous"] == [] and m["approx"] == 0


def test_apparier_repli_approximatif_sans_numero():
    idx, secs = _mini()
    # DJMA de la fiche (4 500) cohérent avec la section la plus proche (5 000) : repli accepté
    m = _apparier(idx, secs, route="Rue Principale", obstacle="Ruisseau", obstacle_route=False, djma=4500)
    assert _nums(secs, m["sur"]) == ["R138"] and m["approx"] == 1     # bit 1 = portée approximative


def test_apparier_repli_refuse_sans_djma_ou_incoherent():
    idx, secs = _mini()
    # fiche sans DJMA : on n'attribue pas les débits d'une autre route (bogue v0.5.1, structure 19359)
    assert _apparier(idx, secs, route="Rue Principale", obstacle="Fossé", obstacle_route=False) is None
    # DJMA de la fiche 10 véh./j : aucune section proche n'est plausible
    assert _apparier(idx, secs, route="Rue Principale", obstacle="Fossé", obstacle_route=False, djma=10) is None
    # « ND » (DJMA = 1) équivaut à l'absence de DJMA
    assert _apparier(idx, secs, route="Rue Principale", obstacle="Fossé", obstacle_route=False, djma=1) is None


def test_apparier_numero_concordant_mais_djma_incoherent():
    idx, secs = _mini()
    # n° concordant, mais 5 000 véh./j sur la section contre 10 dans la fiche → écarté (autre voie)
    m = _apparier(idx, secs, route="Route 138", obstacle="Fossé", obstacle_route=False, djma=10)
    assert m is None
    # écart ≤ 8 : retenu
    m = _apparier(idx, secs, route="Route 138", obstacle="Fossé", obstacle_route=False, djma=1000)
    assert _nums(secs, m["sur"]) == ["R138"] and m["approx"] == 0


def test_apparier_chemin_d_acces():
    idx, secs = _mini()
    m = _apparier(idx, secs, route="Accès route 138 (passage anticervidés)", obstacle="Fossé",
                  obstacle_route=False, djma=10)
    assert m is None


def test_djma_coherent():
    sec = {"series": {"djma": {2024: 900, 2025: 1000}}}
    assert debits.djma_recent(sec) == 1000
    assert debits.djma_coherent(sec, 400, 3) is True
    assert debits.djma_coherent(sec, 300, 3) is False
    assert debits.djma_coherent(sec, None, 3) is None and debits.djma_coherent(sec, 1, 3) is None
    assert debits.djma_coherent({"series": {"djma": {}}}, 500, 3) is None


def test_apparier_route_franchie_ne_sert_pas_de_repli_pour_la_portee():
    idx, secs = _mini()
    # route portée sans n° ; route franchie « Route 138 » (0 m) : la portée ne peut pas être la 138
    m = _apparier(idx, secs, route="Rue Principale", obstacle="Route 138", obstacle_route=True, djma=900)
    assert _nums(secs, m["sous"]) == ["R138"] and "R138" not in _nums(secs, m["sur"])
    assert _nums(secs, m["sur"]) == ["LOC"] and m["approx"] == 1


def test_apparier_route_franchie_sans_numero():
    idx, secs = _mini()
    m = _apparier(idx, secs, route="Route 138", obstacle="Rue des Érables", obstacle_route=True)
    # plus proche autre section (hors route 138) à < 40 m : LOC (22 m) avant A-40 (30 m)
    assert _nums(secs, m["sous"]) == ["LOC"] and m["approx"] == 2                # bit 2 = franchie approximative


def test_apparier_hors_rayon():
    idx, secs = _mini()
    assert _apparier(idx, secs, route="Route 138", obstacle=None, obstacle_route=False, lat=LAT + 0.05) is None


def test_construire_et_taux():
    idx, secs = _mini()
    structures = [
        {"num_dossr": "00001", "route": "Route 138", "obstacle": "Autoroute 40", "lat": LAT, "lon": LON,
         "obstacle_route": True, "obstacle_numerote": True},
        {"num_dossr": "00002", "route": "Route 138", "obstacle": "Ruisseau", "lat": LAT + 0.2, "lon": LON,
         "obstacle_route": False, "obstacle_numerote": False},
    ]
    match, st = debits.construire(secs, structures)
    assert list(match) == ["00001"]
    assert st["avec_sur"] == 1 and st["avec_sous"] == 1 and st["obstacle_route"] == 1
    assert st["obstacle_route_avec_sous"] == 1 and st["approx"] == 0


def test_build_payload_compact():
    idx, secs = _mini()
    for i, s in enumerate(secs):
        s.update(de=s["num"], a=None, rtss=None, annees={2025, 2024},
                 series={"djma": {2025: 1000.0} if i == 0 else {}, "djme": {}, "djmh": {}, "cam": {}})
    m = _apparier(idx, secs, route="Route 138", obstacle="Autoroute 40", obstacle_route=True)
    p = debits.build_payload(secs, {"00001": m}, today="2026-01-02")
    assert p["years"] == [2025, 2024] and set(p["sections"]) == {"R138", "A40"}
    assert p["sections"]["R138"]["djma"] == [1000, None] and p["sections"]["A40"]["djma"] is None
    assert p["match"]["00001"] == {"sur": ["R138"], "sous": ["A40"], "approx": 0, "dsur": 0, "dsous": m["dsous"]}
    assert p["source"].startswith("https://www.donneesquebec.ca/") and "xlsxBase" not in p
    assert all("xlsx" not in s for s in p["sections"].values())
    assert json.dumps(p)           # sérialisable


def test_repli_textuel_ajoute_l_annee():
    """Audit v0.5.5 n° 11 : une année lue seulement dans le texte récapitulatif compte dans les années exportées."""
    feat = {"properties": {"num_sectn_trafc": "X1", "annee_en_cours": "2025 DJMA:1780 / DJME:1920 / DJMH:1600 / %cam:5"},
            "geometry": {"type": "LineString", "coordinates": [[-71.0, 46.0], [-71.001, 46.001]]}}
    s = debits.parse_feature(feat)
    assert s["annees"] == {2025} and s["series"]["djma"] == {2025: 1780}



# --- Audit v0.6.4 : débits sur / sous -------------------------------------------------
def test_v064_numero_de_la_limite_ignore():
    """Le début d'une section de l'A-40 nommé « R-138 » (sa limite) ne fait pas de cette section la route 138."""
    idx, secs = _mini()
    secs[0]["routes_rtss"] = set()                       # la 138 sans n° RTSS : seul le libellé citerait 138…
    secs[1]["routes_desc"] = {138}                       # …et l'A-40 commence à la 138
    m = _apparier(idx, secs, route="Autoroute 40", obstacle="Route 138", obstacle_route=True)
    assert _nums(secs, m["sur"]) == ["A40"] and "A40" not in _nums(secs, m["sous"])


def test_v064_meme_section_jamais_sur_et_sous():
    idx, secs = _mini()
    # A-40 au-dessus d'un raccordement de l'A-40 : le n° commun désigne la voie portée, rien sous
    m = _apparier(idx, secs, route="Autoroute 40", obstacle="Autoroute 40 Sud", obstacle_route=True)
    assert _nums(secs, m["sur"]) == ["A40"] and m["sous"] == []
    assert not set(m["sur"]) & set(m["sous"])


def test_v064_bretelles_sans_debits_de_l_autoroute():
    idx, secs = _mini()
    # bretelle ou voie de service : pas les débits de l'A-40 voisine, ni dessus ni dessous
    for route in ("Bretelle de l'A-40 Nord vers R-138", "Voie de service A-40 Nord", "Échangeur A-40 vers R-138"):
        m = _apparier(idx, secs, route=route, obstacle="Ruisseau", obstacle_route=False, djma=30000)
        assert m is None or "A40" not in _nums(secs, m["sur"])
    m = _apparier(idx, secs, route="Route 138", obstacle="Racc. A-40 N / R-138 E", obstacle_route=True)
    assert _nums(secs, m["sur"]) == ["R138"] and m["sous"] == []
    # route franchie sans n° sous une bretelle de l'A-40 : la section de l'A-40 n'est pas l'obstacle
    m = _apparier(idx, secs, route="Bretelle A-40 Nord", obstacle="Rue des Érables", obstacle_route=True)
    assert m is None or "A40" not in _nums(secs, m["sous"])


def test_v064_section_portee_la_plus_coherente_en_tete():
    idx, secs = _mini()
    secs.append(_sec("R138B", 138, "R-138", [(LON - 0.01, LAT + 10 * M), (LON + 0.01, LAT + 10 * M)], 900))
    idx.add_ligne(len(secs) - 1, secs[-1]["lignes"][0])
    m = _apparier(idx, secs, route="Route 138", obstacle="Fossé", obstacle_route=False, djma=1000)
    assert _nums(secs, m["sur"])[0] == "R138B" and m["dsur"] == 0     # 900 ≈ 1 000 (fiche) passe devant 5 000
