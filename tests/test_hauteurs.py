"""Tests du parseur des hauteurs libres (fixture : extrait réel du service OData)."""
import json
from pathlib import Path

from etl import db, hauteurs

FIXTURE = Path(__file__).parent / "fixtures" / "hauteurs_odata.json"
COLONNES = {
    "num_ref", "num_dossr", "route", "seq", "municipalite", "obstacle",
    "dir_so", "hauteur_so_m", "dir_ne", "hauteur_ne_m", "detail_url",
}


def _rows(**kw):
    return {r["num_ref"]: r for r in hauteurs.parse(FIXTURE.read_bytes(), **kw)}


def test_colonnes_conformes_au_schema():
    for r in hauteurs.parse(FIXTURE.read_bytes()):
        assert set(r) == COLONNES
    # ces colonnes existent bien dans la table du schéma
    bloc = db.SCHEMA.split("CREATE TABLE IF NOT EXISTS hauteur_libre")[1].split(");")[0]
    assert all(c in bloc for c in COLONNES)


def test_ligne_standard_avec_suffixe():
    r = _rows()["14240FA"]
    assert r["num_dossr"] == "14240FA"
    assert r["route"] == "10" and r["seq"] == 1
    assert r["municipalite"] == "Montréal"
    assert r["obstacle"] == "Entrée du tunnel Ville-Marie"
    assert (r["dir_so"], r["hauteur_so_m"]) == ("Ouest", 4.3)
    assert (r["dir_ne"], r["hauteur_ne_m"]) == ("Est", 4.4)
    assert r["detail_url"] == (
        "https://www.transports.gouv.qc.ca/fr/entreprises-partenaires/ent-camionnage/"
        "hauteurs-libres/Pages/DHL-Details.aspx?ref=14240FA"
    )


def test_reference_numerique_pure():
    r = _rows()["16079"]
    assert r["num_dossr"] == "16079"
    assert r["hauteur_so_m"] == 4.51 and r["hauteur_ne_m"] == 4.2


def test_sentinelle_moins_un_et_null_deviennent_none():
    rows = _rows()
    assert rows["09730"]["hauteur_so_m"] is None and rows["09730"]["hauteur_ne_m"] == 5.75
    assert rows["14870G1"]["hauteur_so_m"] == 4.42 and rows["14870G1"]["hauteur_ne_m"] is None
    assert rows["14870G1"]["num_dossr"] == "14870G1"        # suffixe conservé
    assert rows["09773"]["hauteur_so_m"] is None and rows["09773"]["hauteur_ne_m"] == 4.82


def test_doublons_de_num_ref_un_seul_garde():
    brut = hauteurs.parse(FIXTURE.read_bytes(), dedupe=False)
    assert [r["num_ref"] for r in brut].count("01542") == 3
    dedup = hauteurs.parse(FIXTURE.read_bytes())
    refs = [r["num_ref"] for r in dedup]
    assert len(refs) == len(set(refs)) == 6
    # hauteurs égales → on garde la première ligne de la source
    r = next(r for r in dedup if r["num_ref"] == "01542")
    assert r["route"] == "10" and r["seq"] == 2 and r["obstacle"] == "Pont Victoria"


def test_doublon_garde_la_hauteur_la_plus_basse():
    items = json.loads(FIXTURE.read_bytes())["value"]
    a = dict(items[0], Route="A", HauteurSO=4.5, HauteurNE=4.6)
    b = dict(items[0], Route="B", HauteurSO=4.1, HauteurNE=4.9)
    (r,) = hauteurs.parse(json.dumps({"value": [a, b]}))
    assert r["route"] == "B"


def test_valeurs_textuelles_et_vides():
    assert hauteurs._hauteur("4,30") == 4.3
    assert hauteurs._hauteur("-") is None
    assert hauteurs._hauteur("") is None
    assert hauteurs._hauteur(0) is None
    assert hauteurs._txt("  ") is None
