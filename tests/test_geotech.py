"""Tests de la couche géotechnique (fixtures : lignes réelles des deux flux CSV WFS)."""
import json
from pathlib import Path

from etl import geotech

FIX = Path(__file__).parent / "fixtures"


def _lire(nom):
    return geotech.parse((FIX / nom).read_bytes())


def _sondages():
    return {(r["site"], r["sondage"]): r for r in _lire("geotech_sondages_extrait.csv")}


def _bdg():
    return {r["site"] + "|" + r["sondage"]: r for r in _lire("geotech_bdg_extrait.csv")}


def test_parse_sondage_accents_et_degres_entiers():
    r = _sondages()[("21390-02(017)15", "C-01")]
    assert r["type"] == "Piézocône"                       # UTF-8 (avec BOM) correctement décodé
    assert (r["lat"], r["lon"]) == (4874890, -7940215)     # degrés × 1e5
    assert (r["prof"], r["z"]) == (24.47, 268.9)
    assert r["hyperlien"].endswith("/21390-02(017)15_C-01.pdf")


def test_z_ignore_si_reference_arbitraire():
    assert _sondages()[("0015-03-090(055)15-1", "F-01")]["z"] is None
    assert _sondages()[("21390-02(017)15", "C-03")]["z"] == 266.77


def test_bdg_nombres_compacts_et_types_harmonises():
    b = _bdg()
    r = b["BDG_MRN_75_A|75-00507-A"]
    assert (r["prof"], r["z"]) == (32, 22)                 # 32.000000000000000 → 32 (entier)
    assert r["lat"] == 4574950
    assert b["BDG_MRN_80_B|80-09222-B"]["type"] == "Sondage indéterminé"      # TYPE vide
    assert b["BDG_MRN_81_1|81-03317-1"]["type"] == "Scissomètre in situ"        # « in-situ » harmonisé


def test_payload_structure_et_urls():
    p = geotech.build_payload([(0, _lire("geotech_sondages_extrait.csv")), (1, _lire("geotech_bdg_extrait.csv"))],
                              today="2026-01-02")
    assert p["generated"] == "2026-01-02"
    assert p["fields"] == ["lat", "lon", "type", "site", "sondage", "prof", "z", "url", "bdg"]
    assert len(p["points"]) == 9 and len(p["types"]) == len(set(p["types"]))
    assert p["urlBase"][0].endswith("/SiteInvGeo/Geotech/") and p["urlBase"][1].endswith("/Geotech_BDG/")
    par_cle = {tuple(pt[3:5]): pt for pt in p["points"]}
    pt = par_cle[("21390-02(017)15", "C-01")]
    assert p["types"][pt[2]] == "Piézocône" and pt[7] == 1 and pt[8] == 0     # URL par défaut
    assert par_cle[("BDG_MRN_75_A", "75-00507-A")][8] == 1
    assert all(len(pt) == len(p["fields"]) for pt in p["points"])
    assert all(pt[7] in (1, None) or isinstance(pt[7], str) for pt in p["points"])


def test_url_atypique_conservee():
    ligne = {"lat": 1, "lon": 2, "type": "Forage", "site": "S", "sondage": "1", "prof": 1, "z": None,
             "hyperlien": "https://h/Geotech/autre_nom.pdf"}
    p = geotech.build_payload([(0, [ligne])], today="2026-01-02")
    assert p["points"][0][7] == "autre_nom.pdf"


def test_ecriture_js_compact(tmp_path):
    p = geotech.build_payload([(0, _lire("geotech_sondages_extrait.csv"))], today="2026-01-02")
    out = tmp_path / "couche.js"
    taille = geotech.write(p, out)
    txt = out.read_text(encoding="utf-8")
    assert taille == out.stat().st_size
    pref = "window.PQ_COUCHES=window.PQ_COUCHES||{};window.PQ_COUCHES.geotech="
    assert txt.startswith(pref) and txt.endswith(";\n")
    corps = txt[len(pref):-2]
    assert '"points":[[' in corps and '", "' not in corps and '": ' not in corps     # séparateurs compacts
    assert json.loads(corps)["points"][0][2] in range(len(p["types"]))
