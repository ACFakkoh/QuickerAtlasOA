"""Tests des couches municipales (fixtures : entités réelles des GeoJSON de Montréal et de Sherbrooke)."""
import json
import math
from pathlib import Path

from etl import villes

FIX = Path(__file__).parent / "fixtures"

PAIRES = [
    (35, "Portique en béton armé", "pont"),
    (36, "Portique en béton armé sous remblai", "pont"),
    (44, "Pont à poutres en acier", "pont"),
    (47, "Portique en béton armé", "pont"),        # même libellé complet que 35 dans type_structure
    (97, "Mur", "mur"),
    (35, "Portique en béton armé", None),          # libellés abrégés du WFS : pas de famille
    (36, "Port. béton armé, ss remblai", None),
    (47, "Portique en béton", None),
]


def _mtl(lookup=None):
    return villes.parse_mtl((FIX / "villes_mtl_extrait.geojson").read_bytes(), lookup)


def _lookup():
    return villes.type_lookup(PAIRES)


def test_cle_type_normalise_insecables_casse_et_espaces():
    assert villes.cle_type("Pont à\u00a0 poutres en acier") == villes.cle_type("  PONT À POUTRES   en acier ")
    assert villes.cle_type(None) == ""


def test_type_lookup_garde_le_plus_petit_code_et_la_famille():
    lk = _lookup()
    assert lk[villes.cle_type("Portique en béton armé")] == (35, "pont")        # 35 et 47 → 35
    assert lk[villes.cle_type("Port. béton armé, ss remblai")] == (36, "pont")   # libellé abrégé du WFS
    assert lk[villes.cle_type("Portique en béton")] == (47, "pont")
    assert lk[villes.cle_type("Mur")] == (97, "mur")
    assert villes.cle_type("Pont inconnu") not in lk


def test_parse_mtl_cas_nominal_et_valeurs_nulles_omises():
    pts, inconnus = _mtl(_lookup())
    assert [p["num"] for p in pts] == ["81-01102", "81-01103A", "81-01201B"]     # trié par n°
    p = pts[0]
    assert (p["lat"], p["lon"]) == (45.60165, -73.614609)
    assert p["type"] == "Pont à dalle pleine en béton armé"                      # insécable / doubles espaces
    assert p["obstacle"] == "boulevard Lacordaire"                                # espaces de fin retirées
    assert p["centre"] == "Arrondissement Saint-Léonard" and p["annee"] == 1969 and p["stab"] == 451
    assert p["charge"] == "98-Autre" and p["ide"] == 6027781
    for absent in ("icg", "cat", "insp", "rapport", "groupe", "smur", "tc", "fam", "mtmd"):
        assert absent not in p                                                    # nul ou « Non disponible »
    assert inconnus == ["Pont à dalle pleine en béton armé", "Pont à dalle évidée en béton armé"]


def test_parse_mtl_mur_et_icg():
    pts, inconnus = _mtl(_lookup())
    mur = pts[2]
    assert (mur["type"], mur["tc"], mur["fam"]) == ("Mur", 97, "mur")
    assert (mur["icg"], mur["cat"], mur["insp"], mur["smur"]) == (98.4, "4", "2019-07-03", 177)
    assert mur["rapport"].endswith("81-01201B_inspection_generale_web.pdf")
    assert "stab" not in mur and "affichage" not in mur and "charge" not in mur
    assert mur["route"] == "Avenue Bourget, côté Est"
    pont = pts[1]
    assert pont["groupe"] == "P.I. Langelier / Aut. 40" and pont["icg"] == 100.0 and pont["cat"] == "4"


def test_parse_mtl_types_inconnus_signales():
    pts, inconnus = _mtl({})
    assert all("tc" not in p and "fam" not in p for p in pts)
    assert "Mur" in inconnus and len(inconnus) == 3


def test_parse_mtl_corrige_la_coquille_voute():
    contenu = json.dumps({"features": [{"geometry": {"type": "Point", "coordinates": [-73.6, 45.5]},
                                        "properties": {"No structure": "X", "Type structure": "Ponceau voà»té en béton armé"}}]})
    lk = villes.type_lookup([(19, "Ponceau voûté en béton armé", "ponceau")])
    pts, inconnus = villes.parse_mtl(contenu.encode("utf-8"), lk)
    assert pts[0]["type"] == "Ponceau voûté en béton armé" and pts[0]["tc"] == 19 and inconnus == []


def test_fixture_contient_bien_des_insecables():
    assert "\u00a0" in (FIX / "villes_mtl_extrait.geojson").read_text(encoding="utf-8")


def test_parse_sherbrooke():
    pts = villes.parse_sherbrooke((FIX / "villes_sherbrooke_extrait.geojson").read_bytes())
    assert len(pts) == 2
    assert pts[0] == {"lat": 45.386695, "lon": -71.955639, "id": 486, "nom": "Pont Gingues",
                      "soustype": "Ouvrage routier", "fam": "pont"}               # trié par ID
    assert pts[1]["nom"] == "Échangeur Darche" and "OBJECTID" not in pts[1]


def test_famille_par_nom():
    assert villes.famille_par_nom("Pont College") == "pont"
    assert villes.famille_par_nom("Ponceau du Ruisseau") == "ponceau"            # « Ponceau » avant « Pont »
    assert villes.famille_par_nom("Échangeur Darche") == "pont"
    assert villes.famille_par_nom("Mur rue King") == "mur"
    assert villes.famille_par_nom("Ouvrage 12") is None and villes.famille_par_nom(None) is None


def test_parse_mtl_classe_d_obstacle():
    pts, _ = _mtl(_lookup())
    assert pts[0]["obstacle"] == "boulevard Lacordaire" and pts[0]["obst"] == "Route"


def _decale(lat, lon, dnord_m=0.0, dest_m=0.0):
    return lat + dnord_m / villes.M_PAR_DEGRE, lon + dest_m / (villes.M_PAR_DEGRE * math.cos(math.radians(lat)))


def test_nearest_mtmd_dans_et_hors_du_rayon():
    base = (45.5, -73.6)
    mtmd = [("A", *_decale(*base, dnord_m=20)), ("B", *_decale(*base, dest_m=45)), ("C", 46.0, -72.0)]
    pts = [base, _decale(*base, dest_m=100), _decale(*base, dest_m=45)]
    assert villes.nearest_mtmd(pts, mtmd) == ["A", None, "B"]
    assert villes.nearest_mtmd([base], mtmd, max_m=10) == [None]
    assert villes.nearest_mtmd([base], []) == [None]


def test_nearest_mtmd_choisit_le_plus_proche():
    base = (45.5, -73.6)
    mtmd = [("LOIN", *_decale(*base, dest_m=25)), ("PRES", *_decale(*base, dest_m=-5, dnord_m=3))]
    assert villes.nearest_mtmd([base], mtmd) == ["PRES"]


def test_rattacher_mtmd_ajoute_la_cle_seulement_si_apparie():
    pts = [{"lat": 45.5, "lon": -73.6}, {"lat": 45.6, "lon": -73.7}]
    assert villes.rattacher_mtmd(pts, [("X", 45.5, -73.6)]) == 1
    assert pts[0]["mtmd"] == "X" and "mtmd" not in pts[1]
    assert pts[0]["dup"] == 1 and "dup" not in pts[1]                            # famille inconnue : même ouvrage


def test_rattacher_mtmd_doublon_selon_la_famille():
    pts = [{"lat": 45.5, "lon": -73.6, "fam": "pont"}, {"lat": 45.6, "lon": -73.7, "fam": "mur"}]
    mtmd = [("P", 45.5, -73.6, "pont"), ("Q", 45.6, -73.7, "pont")]
    assert villes.rattacher_mtmd(pts, mtmd) == 2
    assert pts[0]["dup"] == 1                                                     # pont ↔ pont : même ouvrage
    assert pts[1]["mtmd"] == "Q" and "dup" not in pts[1]                          # mur près d'un pont : distincts


def test_enregistrer_dans_la_base():
    import sqlite3
    from etl import db
    conn = sqlite3.connect(":memory:")
    conn.executescript(db.SCHEMA)
    pts, _ = _mtl(_lookup())
    pts[0]["mtmd"], pts[0]["dup"] = "07108", 1
    assert villes.enregistrer(conn, "mtl", pts) == 3
    assert villes.enregistrer(conn, "mtl", pts) == 3                              # remplace, sans doublon
    villes.enregistrer(conn, "sherbrooke", [{"lat": 45.3, "lon": -71.8, "id": 11050, "nom": "Pont College",
                                             "fam": "pont"}])
    rows = conn.execute("SELECT source, id, num, nom, famille, num_dossr_mtmd, doublon FROM ouvrage_ville"
                        " ORDER BY source, id").fetchall()
    assert len(rows) == 4
    assert rows[0][:3] == ("mtl", "81-01102", "81-01102") and rows[0][5:] == ("07108", 1)
    assert rows[3] == ("sherbrooke", "11050", "11050", "Pont College", "pont", None, 0)


def test_payloads():
    pts, _ = _mtl(_lookup())
    p = villes.build_payload_mtl(pts, today="2026-01-02")
    assert p["generated"] == "2026-01-02" and p["edition"] == "2021" and p["gestionnaire"] == "Ville de Montréal"
    assert p["titre"] == "Structures routières — Ville de Montréal"
    assert p["attribution"] == "Structures routières : Ville de Montréal (CC-BY 4.0)"
    assert p["source"] == "https://donnees.montreal.ca/dataset/structure-routiere"
    assert p["avertissement"].startswith("Données diffusées à titre informatif") and len(p["points"]) == 3
    s = villes.build_payload_sherbrooke([], today="2026-01-02")
    assert s["titre"] == "Ouvrages routiers — Ville de Sherbrooke" and s["edition"] is None
    assert s["avertissement"] is None and s["attribution"] == "Ouvrages routiers : Ville de Sherbrooke (CC-BY 4.0)"


def test_ecriture_js_compact(tmp_path):
    pts, _ = _mtl(_lookup())
    p = villes.build_payload_mtl(pts, today="2026-01-02")
    out = tmp_path / "couche.js"
    taille = villes.write(p, "mtl", out)
    txt = out.read_text(encoding="utf-8")
    assert taille == out.stat().st_size
    pref = "window.PQ_COUCHES=window.PQ_COUCHES||{};window.PQ_COUCHES.mtl="
    assert txt.startswith(pref) and txt.endswith(";\n")
    corps = txt[len(pref):-2]
    assert '": ' not in corps and '", "' not in corps and "Montréal" in corps    # compact, UTF-8 non échappé
    assert json.loads(corps)["points"][0]["num"] == "81-01102"
    villes.write(villes.build_payload_sherbrooke([]), "sherbrooke", out)
    assert out.read_text(encoding="utf-8").startswith("window.PQ_COUCHES=window.PQ_COUCHES||{};window.PQ_COUCHES.sherbrooke=")
