"""Tests des couches de lignes (réseau routier RTSS et réseau ferroviaire).

Fixtures : entités réelles du WFS du MTMD. Le flux réel ne contient aucun MultiLineString : celui des
fixtures est composé de deux segments réels voisins, pour tester ce cas.
"""
import json
import math
import re
from pathlib import Path

import pytest

from etl import reseaux

FIX = Path(__file__).parent / "fixtures"


def _geojson(nom):
    return json.loads((FIX / f"{nom}.geojson").read_text(encoding="utf-8"))


def _payload(cle, nom, tol=reseaux.TOLERANCE_M):
    cfg = reseaux.COUCHES[cle]
    entrees = reseaux.PARSEURS[cle](_geojson(nom))
    return reseaux.construire_payload(entrees, cfg["classes"], cfg["titre"], cfg["attribution"], tol,
                                      generated="2026-10-11")


def _decode(payload):
    return [reseaux.decoder_ligne(x) for x in payload["lines"]]


# --- Douglas-Peucker ------------------------------------------------------------------------------
def test_dp_ligne_droite_deux_points():
    pts = [(float(i), 2.0 * i) for i in range(50)]
    assert reseaux.douglas_peucker(pts, 0.1) == [pts[0], pts[-1]]


def test_dp_coin_conserve():
    pts = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 5.0), (10.0, 10.0)]
    assert reseaux.douglas_peucker(pts, 0.5) == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]


def test_dp_tolerance_respectee():
    # sinusoïde bruitée : chaque point supprimé reste à ≤ tol de la ligne simplifiée
    pts = [(float(i), 3.0 * math.sin(i / 7) + (i % 3) * 0.2) for i in range(200)]
    tol = 0.8
    s = reseaux.douglas_peucker(pts, tol)
    assert 2 < len(s) < len(pts)
    assert s[0] == pts[0] and s[-1] == pts[-1]
    for p in pts:
        assert min(reseaux._dist_segment(p, a, b) for a, b in zip(s, s[1:])) <= tol + 1e-9


def test_dp_courtes_lignes_inchangees():
    assert reseaux.douglas_peucker([(0.0, 0.0)], 1) == [(0.0, 0.0)]
    assert reseaux.douglas_peucker([(0.0, 0.0), (1.0, 1.0)], 1) == [(0.0, 0.0), (1.0, 1.0)]


def test_simplifier_entiers_en_metres():
    # 41 points alignés vers l'est (latitude 46,8°) avec un écart de 3 unités (≈ 3,3 m) en latitude
    base = round(46.8 * reseaux.ECHELLE)
    pts = [(base + (3 if i == 20 else 0), -7_100_000 + 10 * i) for i in range(41)]
    assert len(reseaux.simplifier(pts, 10)) == 2           # tolérance 10 m : l'écart disparaît
    assert (base + 3, -7_100_000 + 200) in reseaux.simplifier(pts, 1)      # tolérance 1 m : le sommet est conservé


def test_quantifier_ordre_lat_lon_et_doublons():
    pts = reseaux.quantifier([[-71.123456, 46.5], [-71.123458, 46.5], [-71.2, 46.6]])
    assert pts == [(4_650_000, -7_112_346), (4_660_000, -7_120_000)]


# --- Encodage delta -------------------------------------------------------------------------------
def test_encodage_delta_aller_retour():
    pts = [(4_650_000, -7_112_346), (4_650_012, -7_112_300), (4_649_990, -7_112_390), (4_649_990, -7_112_000)]
    ligne = reseaux.encoder_ligne(2, 17, 1, pts)
    assert ligne == [2, 17, 1, 4_650_000, -7_112_346, 12, 46, -22, -90, 0, 390]
    assert reseaux.decoder_ligne(ligne) == (2, 17, 1, pts)


def test_fusion_bout_a_bout_et_inversion():
    cle = (0, 0, 0)
    lignes = {0: (cle, [(0, 0), (0, 10)]), 1: (cle, [(0, 20), (0, 10)]),       # 1 est inversée
              2: ((1, 0, 0), [(0, 20), (0, 30)]),                              # autre classe : jamais jointe
              3: (cle, [(5, 5), (5, 9)])}
    out = reseaux.fusionner(lignes)
    assert len(out) == 3
    jointe = next(p for c, p in out if c == cle and len(p) == 3)
    assert jointe in ([(0, 0), (0, 10), (0, 20)], [(0, 20), (0, 10), (0, 0)])


# --- Parsing des fixtures -------------------------------------------------------------------------
def test_rtss_classes_libelles_et_multilinestring():
    entrees = reseaux.parse_rtss(_geojson("rtss_mini"))
    assert len(entrees) == 6                                   # 5 entités, dont un MultiLineString à 2 parties
    par = [(c, l) for c, l, *_ in entrees]
    assert ("Autoroute", "Autoroute 20") in par
    assert par.count(("Nationale", "Route 117")) == 2
    assert ("Collectrice", "Route 216") in par
    assert ("Sans classe", "Autoroute 20") in par             # bretelle d'une autoroute : numéro d'autoroute
    assert any(c == "Accès aux ressources" for c, _ in par)
    rssce = {(c, l) for c, l, flag, _ in entrees if flag}     # RSSCE estimé : autoroutes, bretelles, 117
    assert rssce == {("Autoroute", "Autoroute 20"), ("Sans classe", "Autoroute 20"), ("Nationale", "Route 117")}


def test_drapeau_rssce():
    assert reseaux.drapeau_rssce({"des_clasf_": "Autoroute", "num_route": "00020"}) == 1
    assert reseaux.drapeau_rssce({"des_clasf_": "Sans classe", "num_route": "00020"}, {20}) == 1
    assert reseaux.drapeau_rssce({"des_clasf_": "Sans classe", "num_route": "00020"}) == 0
    assert reseaux.drapeau_rssce({"des_clasf_": "Nationale", "num_route": "00175"}) == 1
    assert reseaux.drapeau_rssce({"des_clasf_": "Nationale", "num_route": "00132"}) == 0
    assert reseaux.drapeau_rssce({"des_clasf_": "Régionale", "num_route": "00117"}) == 0


def test_rail_classes_et_libelles():
    entrees = reseaux.parse_rail(_geojson("rail_mini"))
    assert len(entrees) == 5
    par = [(c, l) for c, l, *_ in entrees]
    assert ("Voyageurs (seul ou mixte)", "Immeuble VDS · subdivision St-Hyacinthe") in par
    assert par.count(("Marchandises", "Canadien National · subdivision Montreal")) == 2
    assert ("Abandonné", "Chemin de fer Canadien Pacifique Kansas City · subdivision Adirondack") in par
    assert ("Voyageurs (seul ou mixte)", "Canadien National · subdivision La Tuque") in par
    assert all(flag == 0 for _, _, flag, _ in entrees)


# --- Forme du payload -----------------------------------------------------------------------------
@pytest.mark.parametrize("cle,nom", [("rtss", "rtss_mini"), ("rail", "rail_mini")])
def test_forme_payload(cle, nom):
    p = _payload(cle, nom)
    assert list(p) == ["generated", "titre", "attribution", "classes", "labels", "lines", "_effectifs"]
    assert p["generated"] == "2026-10-11"
    assert p["attribution"].endswith("(CC-BY 4.0)")
    assert all({"label", "color", "weight"} <= set(c) <= {"label", "color", "weight", "dash"} for c in p["classes"])
    assert all(re.fullmatch(r"#[0-9a-f]{6}", c["color"]) for c in p["classes"])
    assert len(p["labels"]) == len(set(p["labels"]))             # dédupliqués
    assert p["lines"]
    for ligne in p["lines"]:
        assert all(isinstance(v, int) for v in ligne)
        assert len(ligne) >= 7 and len(ligne) % 2 == 1           # 3 en-têtes + paires lat/lon, au moins 2 points
        classe, libelle, flag, pts = reseaux.decoder_ligne(ligne)
        assert 0 <= classe < len(p["classes"]) and 0 <= libelle < len(p["labels"]) and flag in (0, 1)
        assert all(4_000_000 < lat < 6_500_000 and -8_100_000 < lon < -5_600_000 for lat, lon in pts)  # lat, lon


def test_classes_vides_retirees_et_ordre_de_dessin():
    p = _payload("rtss", "rtss_mini")
    assert [c["label"] for c in p["classes"]] == ["Autoroute", "Nationale", "Collectrice", "Accès aux ressources",
                                                  "Sans classe"]
    ordre = [x[0] for x in p["lines"]]
    assert ordre == sorted(ordre, reverse=True)                  # classes secondaires d'abord


def test_simplification_reduit_les_points():
    entrees = reseaux.parse_rtss(_geojson("rtss_mini"))
    fin = _payload("rtss", "rtss_mini", tol=10)
    brut = _payload("rtss", "rtss_mini", tol=0)
    pts_fin = sum(len(d[3]) for d in _decode(fin))
    pts_brut = sum(len(d[3]) for d in _decode(brut))
    assert pts_fin <= pts_brut
    # nombre de points sans simplification = points quantifiés des parties (hors fusions)
    assert pts_brut <= sum(len(reseaux.quantifier(c)) for *_, c in entrees)


def test_ecriture_js(tmp_path, monkeypatch):
    monkeypatch.setattr(reseaux, "DATA_DIR", tmp_path)
    bilan = reseaux.ecrire("rail", _payload("rail", "rail_mini"))
    texte = (tmp_path / "couche-rail.js").read_text(encoding="utf-8")
    prefixe = "window.PQ_COUCHES=window.PQ_COUCHES||{};window.PQ_COUCHES.rail="
    assert texte.startswith(prefixe) and texte.endswith(";\n")
    obj = json.loads(texte[len(prefixe):-2])
    assert "_effectifs" not in obj and obj["titre"] == "Réseau ferroviaire"
    assert ", " not in texte[len(prefixe):-2].replace("Immeuble VDS", "")   # JSON compact (pas d'espaces)
    assert bilan["lignes"] == len(obj["lines"]) and bilan["bytes"] == (tmp_path / "couche-rail.js").stat().st_size


def test_run_couche_inconnue():
    with pytest.raises(ValueError):
        reseaux.run(only=["metro"], fetch=False)


# --- Ponts ferroviaires ---------------------------------------------------------------------------
DEG = 1e-5            # ≈ 1,11 m en latitude, 0,76 m en longitude à 47° N
CN = ("Canadien National", "CN")
CPKC = ("Chemin de fer Canadien Pacifique Kansas City", "CPKC")


def _seg(lon0, lon1, lat=47.0, n=3, exploitant=CN, prop=None, typ="Pont"):
    """Entité du WFS ferroviaire : segment est-ouest de `n` points entre deux longitudes."""
    coords = [[lon0 + (lon1 - lon0) * i / (n - 1), lat] for i in range(n)]
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"typstruc": typ, "nmfrexploi": exploitant[0], "siglexploi": exploitant[1],
                           "nmfrpropr": prop if prop is not None else exploitant[0], "etat": "Opérationnel",
                           "typeutilis": "Marchandises", "nomsubdiv1": ""}}


def _fc(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def _ponts(*features, osm=None):
    p = reseaux.construire_ponts(_fc(*features), osm)
    return p, [reseaux.decoder_pont(x) for x in p["ponts"]]


def test_longueur_geodesique_valeurs_connues():
    # 1° de latitude / de longitude à 45° N (ellipsoïde WGS84) : 111,132 km / 78,847 km
    assert reseaux.longueur_geodesique_m([[-71.0, 44.5], [-71.0, 45.5]]) == pytest.approx(111_132, rel=1e-4)
    assert reseaux.longueur_geodesique_m([[-71.5, 45.0], [-70.5, 45.0]]) == pytest.approx(78_847, rel=1e-4)
    assert reseaux.longueur_geodesique_m([[-71.0, 45.0]]) == 0


def test_groupe_pont_table_explicite():
    g = reseaux.groupe_pont
    assert g("Canadien National", "CN") == 0
    assert g("CANADIEN NATIONAL", "") == 0
    assert g("Chemin de fer Canadien Pacifique Kansas City", "CPKC") == 1
    assert g("Chemin de fer Canadien Pacifique Kansas City", "") == 1
    assert g("Nom inattendu du CN", "CN") == 0                       # le sigle sert si le nom n'est pas dans la table
    assert g("Chemins de fer Québec-Gatineau inc.", "CFQG", "Genesee & Wyoming Canada Inc.") == 2
    assert g("Ottawa Valley Railway", "CP/OVR", "Chemin de fer Canadien Pacifique Kansas City") == 2   # l'exploitant décide
    assert g("Aucun", "", "Canadien National") == 0                  # exploitant absent → propriétaire
    assert g("", "", "Chemin de fer Canadien Pacifique Kansas City") == 1
    assert g("Inconnu", "", "Municipalité de La Pêche") == 2
    assert g("", "", "") == 2


def test_parse_ponts_exclut_tunnels_et_voies():
    ponts = reseaux.parse_ponts(_fc(_seg(-71.0, -70.999), _seg(-70.99, -70.989, typ="Tunnel"),
                                    _seg(-70.98, -70.979, typ=""), _seg(-70.97, -70.969, typ="Pont mobile")))
    assert [p["mobile"] for p in ponts] == [False, True]


def test_fusion_segments_contigus_longueur_et_mobile():
    # 3 segments bout à bout (le 2e à 1,4 m du 1er, le 3e inversé) = un pont ; un 4e à 3,8 m = un autre pont
    a, b, c, d = (_seg(-71.000, -70.999), _seg(-70.999 + 1.9e-5, -70.998), _seg(-70.997, -70.998, typ="Pont mobile"),
                  _seg(-70.997 - 5e-5, -70.996))
    p, ponts = _ponts(a, b, c, d)
    assert len(ponts) == 2
    attendu = round(sum(reseaux.longueur_geodesique_m(f["geometry"]["coordinates"]) for f in (a, b, c)))
    seul = round(reseaux.longueur_geodesique_m(d["geometry"]["coordinates"]))
    assert sorted(x["longueur"] for x in ponts) == sorted([attendu, seul])
    gros = next(x for x in ponts if x["longueur"] == attendu)
    assert gros["mobile"] == 1 and gros["longueur"] == pytest.approx(3 * 76, abs=3)       # 3 × 0,001° à 47° N
    assert next(x for x in ponts if x is not gros)["mobile"] == 0
    # géométrie jointe bout à bout, de l'ouest vers l'est ou l'inverse, sans va-et-vient
    lons = [lon for _, lon in gros["pts"]]
    assert lons == sorted(lons) or lons == sorted(lons, reverse=True)


def test_fusion_jamais_entre_exploitants_differents():
    p, ponts = _ponts(_seg(-71.000, -70.999, exploitant=CN), _seg(-70.999, -70.998, exploitant=CPKC))
    assert sorted(x["groupe"] for x in ponts) == [0, 1]


def test_fusion_aiguillage_donne_une_chaine_par_branche():
    # trois segments qui se rejoignent au même nœud (en Y) : ni va-et-vient ni chaîne à jonction
    centre = (-70.999, 47.0)
    branches = [(centre, (-71.000, 47.0005)), (centre, (-71.000, 46.9995)), (centre, (-70.998, 47.0))]
    feats = [{"type": "Feature", "properties": _seg(0, 1)["properties"],
              "geometry": {"type": "LineString", "coordinates": [list(a), list(b)]}} for a, b in branches]
    _, ponts = _ponts(*feats)
    assert len(ponts) == 3
    assert sum(x["longueur"] for x in ponts) == pytest.approx(
        sum(reseaux.longueur_geodesique_m(f["geometry"]["coordinates"]) for f in feats), abs=2)


def test_proprietaire_dominant_et_etiquettes_inconnues():
    p, ponts = _ponts(_seg(-71.0, -70.999, prop="Petit propriétaire"),
                      _seg(-70.999, -70.99, prop="Grand propriétaire"),                  # 9 fois plus long
                      _seg(-70.5, -70.499, exploitant=("Aucun", ""), prop="Inconnu"))
    labels = p["ponts_labels"]
    longue = next(x for x in ponts if x["groupe"] == 0)
    assert labels[longue["proprietaire"]] == "Grand propriétaire"
    inconnue = next(x for x in ponts if x["groupe"] == 2)
    assert labels[inconnue["exploitant"]] == "Exploitant inconnu"
    assert labels[inconnue["proprietaire"]] == "Propriétaire inconnu"


def test_forme_ponts_et_encodage():
    p, ponts = _ponts(_seg(-71.0, -70.999, n=5), _seg(-70.5, -70.499, exploitant=CPKC))
    assert set(p) == {"ponts", "ponts_labels", "ponts_groupes", "ponts_attribution"}
    assert p["ponts_groupes"][:2] == ["CN", "CPKC"]
    assert "OpenStreetMap" in p["ponts_attribution"] and "ODbL" in p["ponts_attribution"]
    assert len(p["ponts_labels"]) == len(set(p["ponts_labels"]))
    for brut, x in zip(p["ponts"], ponts):
        assert all(v is None or isinstance(v, int) for v in brut)
        assert len(brut) >= 10 and len(brut) % 2 == 0                   # 6 champs + lat0, lon0 + au moins 1 delta
        assert x["groupe"] in (0, 1, 2) and x["mobile"] in (0, 1) and x["nom"] is None
        assert 0 <= x["exploitant"] < len(p["ponts_labels"]) and 0 <= x["proprietaire"] < len(p["ponts_labels"])
        assert len(x["pts"]) >= 2
        assert all(4_000_000 < lat < 6_500_000 and -8_100_000 < lon < -5_600_000 for lat, lon in x["pts"])
    assert [x["groupe"] for x in ponts] == [0, 1]                       # trié par groupe
    cn = ponts[0]
    assert cn["pts"][0] == (4_700_000, -7_100_000) and cn["pts"][-1] == (4_700_000, -7_099_900)   # lat, lon en 1e-5°
    assert cn["longueur"] == round(reseaux.longueur_geodesique_m(_seg(-71.0, -70.999, n=5)["geometry"]["coordinates"]))


def test_simplification_legere_des_ponts():
    f = _seg(-71.0, -70.999, n=40)                 # 40 points alignés → 2 points
    f["geometry"]["coordinates"][20][1] += 0.5e-5  # un écart de 0,55 m, sous la tolérance de 2 m
    _, ponts = _ponts(f)
    assert len(ponts[0]["pts"]) == 2
    assert ponts[0]["longueur"] == round(reseaux.longueur_geodesique_m(f["geometry"]["coordinates"]))   # longueur d'origine


def _osm(nom_tags, lat=47.0, lon0=-71.0, lon1=-70.999):
    return {"type": "way", "id": 1, "tags": {"railway": "rail", "bridge": "yes", **nom_tags},
            "geometry": [{"lat": lat, "lon": lon0}, {"lat": lat, "lon": lon1}]}


def test_nom_pont_osm_ignore_les_subdivisions():
    f = reseaux.nom_pont_osm
    assert f({"bridge:name": "Pont de Québec", "name": "Subdivision Bridge"}) == "Pont de Québec"
    assert f({"name": "Pont Mitchell"}) == "Pont Mitchell"
    assert f({"name": "Rivière Bridge"}) == "Rivière Bridge"
    assert f({"name": "Subdivision Parc"}) is None
    assert f({"name": "Subdivision Bridge"}) is None            # « Bridge » ici est le nom d'une subdivision
    assert f({"name": "Voie d'évitement Lacadie"}) is None
    assert f({}) is None


def test_noms_osm_dans_le_rayon_de_30_m():
    pont = _seg(-71.0, -70.999)
    osm = [_osm({"bridge:name": "Pont Proche"}, lat=47.0 + 20 * DEG),                 # ≈ 22 m au nord du milieu
           _osm({"bridge:name": "Pont Loin"}, lat=47.0 + 40 * DEG, lon0=-70.9, lon1=-70.899),
           _osm({"name": "Subdivision Parc"}, lat=47.0)]                              # sur place, mais pas un nom de pont
    p, ponts = _ponts(pont, osm=osm)
    assert p["ponts_labels"][ponts[0]["nom"]] == "Pont Proche"
    p, ponts = _ponts(pont, osm=[_osm({"bridge:name": "Trop loin"}, lat=47.0 + 30 * DEG)])    # ≈ 33 m
    assert ponts[0]["nom"] is None
    p, ponts = _ponts(pont, osm=[])
    assert ponts[0]["nom"] is None


def test_nom_osm_le_plus_proche_gagne():
    osm = [_osm({"bridge:name": "Pont B"}, lat=47.0 + 25 * DEG), _osm({"bridge:name": "Pont A"}, lat=47.0 + 5 * DEG)]
    p, ponts = _ponts(_seg(-71.0, -70.999), osm=osm)
    assert p["ponts_labels"][ponts[0]["nom"]] == "Pont A"


def _relire_rail(tmp_path):
    texte = (tmp_path / "couche-rail.js").read_text(encoding="utf-8")
    return json.loads(texte.split("rail=", 1)[1].rstrip()[:-1])


def test_run_rail_ajoute_les_ponts_sans_changer_les_lignes(tmp_path, monkeypatch):
    brut = _geojson("rail_mini")
    brut["features"] += [_seg(-71.0, -70.999), _seg(-70.5, -70.499, typ="Tunnel")]
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "rail.geojson").write_text(json.dumps(brut), encoding="utf-8")
    (tmp_path / "raw" / reseaux.RAW_OSM_RAIL).write_text(
        json.dumps({"elements": [_osm({"bridge:name": "Pont Test"}, lat=47.0)]}), encoding="utf-8")
    monkeypatch.setattr(reseaux, "DATA_DIR", tmp_path)
    monkeypatch.setattr(reseaux, "RAW_DIR", tmp_path / "raw")
    bilan, = reseaux.run(only=["rail"], fetch=False)
    obj = _relire_rail(tmp_path)
    sans_ponts = reseaux.construire_payload(reseaux.parse_rail(brut), reseaux.CLASSES_RAIL, "Réseau ferroviaire",
                                            "Réseau ferroviaire : MTMD / Données Québec (CC-BY 4.0)")
    assert obj["lines"] == sans_ponts["lines"] and obj["labels"] == sans_ponts["labels"]      # `lines` inchangé
    deja = len(reseaux.fusionner_ponts(reseaux.parse_ponts(_geojson("rail_mini"))))           # 1 pont dans la fixture
    assert bilan["ponts"] == deja + 1 == len(obj["ponts"]) and bilan["ponts_nommes"] == 1     # tunnel exclu
    assert "Pont Test" in [obj["ponts_labels"][x[4]] for x in obj["ponts"] if x[4] is not None]
    (tmp_path / "raw" / reseaux.RAW_OSM_RAIL).unlink()                                         # sans cache OSM : pas de nom
    reseaux.run(only=["rail"], fetch=False)
    assert all(x[4] is None for x in _relire_rail(tmp_path)["ponts"])
