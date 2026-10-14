"""Tests du parseur WFS (fixture : 4 lignes réelles du flux CSV)."""
import json
from pathlib import Path

from etl import wfs

FIXTURE = Path(__file__).parent / "fixtures" / "wfs_extrait.csv"


def _rows():
    return {r["num_dossr"]: r for r in wfs.parse(FIXTURE.read_bytes())}


def test_ligne_connue():
    r = _rows()["00009"]
    assert r["ide_strct"] == 211038
    assert (r["type_code"], r["type_libelle"]) == (41, "Pont à poutres en béton armé")
    assert r["route"] == "Route 113" and r["obstacle"] == "Rivière Taschereau"
    assert r["annee_construction"] == 1967 and r["nb_voies"] == 2
    assert (r["longueur_m"], r["largeur_m"]) == (54.9, 11.1)          # mm → m
    assert (r["lat"], r["lon"]) == (48.861117, -77.138884)
    assert (r["cod_respn"], r["route_principale"], r["deficient_etat"], r["deficient_fonct"]) == (10, 1, 1, 0)
    assert r["nom"] is None                                            # chaîne vide → None


def test_numero_avec_suffixe_et_raw_json():
    rows = _rows()
    assert "00024A" in rows
    assert json.loads(rows["00024A"]["raw_json"])["num_dossr"] == "00024A"
    assert len(rows) == 4
