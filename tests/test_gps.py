"""Tests du parseur GPS.csv (fixture : 5 lignes réelles encodées en cp1252)."""
import logging
from pathlib import Path

from etl import gps

FIXTURE = Path(__file__).parent / "fixtures" / "gps_extrait.csv"
COLONNES = {"id", "lat", "lon", "nom", "route", "obstacle", "limite_charge", "annee", "num_dossr"}


def _rows():
    return gps.parse(FIXTURE.read_bytes())


def test_nombre_de_lignes_et_colonnes():
    rows = _rows()
    assert [r["id"] for r in rows] == [1, 2, 3, 4, 5]        # l'en-tête n'est pas compté
    assert all(set(r) == COLONNES for r in rows)
    assert all(r["num_dossr"] is None for r in rows)


def test_ligne_standard_cp1252():
    r = _rows()[0]
    assert r["lon"] == -71.53646 and r["lat"] == 46.460333
    assert r["nom"] == "Pont à poutres en béton précontraint préfabriquées"
    assert r["route"] == "Route 116"
    assert r["obstacle"] == "Rivière Henri"
    assert r["limite_charge"] == "Aucun affichage"
    assert r["annee"] == 2012


def test_description_avec_guillemets_parasites():
    r = _rows()[1]
    assert r["nom"] == "Pont de l'Île-aux-Tourtes"
    assert r["route"] == "Autoroute 40"
    assert r["obstacle"] == "Vir en U Aut. 40 O vers E"
    assert r["limite_charge"] == "Aucun affichage"
    assert r["annee"] == 1965


def test_point_virgule_dans_la_valeur():
    r = _rows()[2]
    assert r["route"] == "Raccordement A-40 Est ; A-15 Nord"
    assert r["obstacle"] == "Rue De Beauharnois"
    assert r["annee"] == 2012


def test_limite_de_charge_variee():
    assert _rows()[3]["limite_charge"] == "Tonnage réduit"


def test_champ_vide_et_partie_manquante():
    r = _rows()[4]
    assert r["nom"] == "Mur" and r["obstacle"] is None and r["annee"] == 2011
    # étiquettes manquantes / ordre inattendu : lecture par clés, pas par position
    (p,) = gps.parse("1;2;Pont;Limite de charge : Pont fermé ; Route : R1\n")
    assert p["limite_charge"] == "Pont fermé" and p["route"] == "R1"
    assert p["obstacle"] is None and p["annee"] is None


def test_lignes_illisibles_ignorees():
    assert gps.parse("Longitude;Latitude;Name;Description;;;;;\n\nabc;def;X;Route : R\n") == []


def test_utf8_accepte(caplog):
    (p,) = gps.parse("-71,5;46,4;Pont à dalle;Route : Chemin é ; Année de construction : 1999;;".encode("utf-8"))
    assert p["lon"] == -71.5 and p["nom"] == "Pont à dalle" and p["annee"] == 1999


def test_trouve_url_csv_dans_la_page_apex():
    html = '<a href="/ords/pes/APEX_PES.P_PESB_GENRT_CSV?p_vc_DT=&p_vc_ROUTE=&p_vc_OPT_CHARGE=">(format .csv)</a>'
    assert gps._trouve_url_csv(html, "https://www.diffusion.transports.gouv.qc.ca/ords/pes/f?p=DIFF:DSI::::::") == (
        "https://www.diffusion.transports.gouv.qc.ca/ords/pes/APEX_PES.P_PESB_GENRT_CSV?p_vc_DT=&p_vc_ROUTE=&p_vc_OPT_CHARGE="
    )


def test_repli_local_si_telechargement_echoue(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("réseau coupé")
    monkeypatch.setattr(gps.net, "get", boom)
    with caplog.at_level(logging.WARNING):
        rows = gps.collect(None)
    assert len(rows) > 9000
    assert "repli" in caplog.text


def test_format_en_ligne_guillemets_et_separateur_slash():
    """Variante réellement servie par APEX : champs entre guillemets, séparateur « / »."""
    rows = gps.parse((Path(__file__).parent / "fixtures" / "gps_en_ligne.csv").read_bytes())
    assert [r["id"] for r in rows] == [1, 2, 3, 4]
    r = rows[0]
    assert r["nom"] == "Pont à poutres en béton précontraint préfabriquées"
    assert (r["route"], r["obstacle"], r["limite_charge"], r["annee"]) == (
        "Route 116", "Rivière Henri", "Aucun affichage", 2012)
    assert rows[1]["route"] == "Raccordement A-40 Est / A-15 Nord"      # « / » interne conservé
    assert rows[2]["limite_charge"] == "Tonnage réduit"
    assert rows[3]["obstacle"] is None
