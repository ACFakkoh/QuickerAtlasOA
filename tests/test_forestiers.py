"""Tests de la couche « Ponts forestiers (MRNF) » (fixture : entités réelles d'AQréseau+, version AQ20260701).

La fixture contient aussi deux cas fabriqués : un objet sans géométrie et un objet au statut inattendu
(« ? ») dont le statut se déduit de la couche, avec des blancs autour du dossier et de la capacité.
"""
import json
import math
import subprocess
from pathlib import Path

import pytest

from etl import forestiers

FIX = Path(__file__).parent / "fixtures"
M_PAR_DEG = 111_320.0


def _geojson():
    return json.loads((FIX / "forestiers_extrait.geojson").read_text(encoding="utf-8"))


def _ponts(couche=1):
    return forestiers.parse_geojson(_geojson(), couche)


def _par_dossier(ponts):
    return {p["dossier"]: p for p in ponts if p["dossier"]}


# --- Analyse -------------------------------------------------------------------------------------
def test_parse_cas_nominal_et_objets_sans_geometrie_ignores():
    ponts = _ponts()
    assert len(ponts) == 10                                   # 11 objets, dont un sans géométrie
    p = _par_dossier(ponts)["H024-025"]
    assert (p["src"], p["st"], p["cap"], p["version"]) == ("DGIG", 0, "50-90-120", "AQ20260701")
    assert p["lat"] == pytest.approx(48.8236, abs=1e-6) and p["lon"] == pytest.approx(-71.753424, abs=1e-6)  # lat avant lon


def test_parse_statuts_dossiers_et_capacites_normalises():
    par = _par_dossier(_ponts())
    assert par["R0952-13"]["st"] == 1 and par["R0952-13"]["cap"] == "5-5-5"
    assert par["H011-163"]["st"] == 2 and par["H011-163"]["cap"] == "0-0-0"          # fermé : « 0-0-0 » conservé
    assert par["H012-186"]["cap"] == "0-0-0-0"                                       # 4 valeurs : tel que publié
    assert par["H033-204"]["cap"] is None                                            # « -- » = inconnue
    assert par["5133058"]["cap"] is None                                             # « INC » = inconnue
    sans_dossier = [p for p in _ponts() if p["dossier"] is None]
    assert len(sans_dossier) == 1 and sans_dossier[0]["src"] == "AQ" and sans_dossier[0]["cap"] is None


def test_parse_statut_inattendu_repli_sur_la_couche_et_blancs_retires():
    for couche, st in ((1, 0), (2, 1), (3, 2)):
        p = _par_dossier(_ponts(couche))["H000-001"]
        assert p["st"] == st
        assert p["cap"] == "30-50-60"                       # espaces retirés


def test_normalisations():
    assert forestiers.normaliser_cap("INC") is None and forestiers.normaliser_cap("inc") is None
    assert forestiers.normaliser_cap("--") is None and forestiers.normaliser_cap("") is None
    assert forestiers.normaliser_cap(None) is None
    assert forestiers.normaliser_cap("0-0-0") == "0-0-0" and forestiers.normaliser_cap(" 30-48-60 ") == "30-48-60"
    assert forestiers.normaliser_dossier("  ") is None and forestiers.normaliser_dossier(None) is None
    assert forestiers.normaliser_dossier("H024-025") == "H024-025"
    assert forestiers.normaliser_source("S�paq") == "Sépaq" and forestiers.normaliser_source("Sépaq") == "Sépaq"
    assert forestiers.normaliser_source("ROUTARD") == "ROUTARD"


# --- Doublons avec le MTMD -----------------------------------------------------------------------
def _decale(lat, lon, dnord_m=0.0, dest_m=0.0):
    return lat + dnord_m / M_PAR_DEG, lon + dest_m / (M_PAR_DEG * math.cos(math.radians(lat)))


def test_hors_mtmd_seuil_de_30_m():
    ponts = _ponts()
    cibles = {p["dossier"]: p for p in ponts if p["dossier"] in ("H024-025", "H033-090", "R0952-13")}
    mtmd = [("00001", *_decale(cibles["H024-025"]["lat"], cibles["H024-025"]["lon"], dnord_m=10), "pont"),   # 10 m
            ("00002", *_decale(cibles["H033-090"]["lat"], cibles["H033-090"]["lon"], dest_m=29), "pont"),    # 29 m
            ("00003", *_decale(cibles["R0952-13"]["lat"], cibles["R0952-13"]["lon"], dnord_m=31), "pont")]   # 31 m
    gardes = {p["dossier"] for p in forestiers.hors_mtmd(ponts, mtmd) if p["dossier"]}
    assert "H024-025" not in gardes and "H033-090" not in gardes          # doublons : déjà dans l'atlas
    assert "R0952-13" in gardes                                           # à 31 m : un autre pont
    assert len(forestiers.hors_mtmd(ponts, mtmd)) == len(ponts) - 2
    assert len(forestiers.hors_mtmd(ponts, [])) == len(ponts)             # aucun ouvrage du MTMD : tout est gardé


# --- Charge utile et encodage --------------------------------------------------------------------
def test_forme_du_payload():
    p = forestiers.construire_payload(_ponts(), generated="2026-10-14")
    assert list(p) == ["generated", "version", "titre", "attribution", "source", "avertissement", "srcs", "srcLabels",
                       "sts", "points"]
    assert p["generated"] == "2026-10-14" and p["version"] == "AQ20260701"
    assert p["titre"] == "Ponts forestiers (MRNF)"
    assert p["attribution"] == "Adresses Québec / AQréseau+ — MRNF, CC-BY 4.0"
    assert p["avertissement"].startswith("Aucune valeur légale") and p["source"].startswith("https://")
    assert p["sts"] == ["Ouvert", "Inconnu", "Fermé"]
    assert p["srcs"] == ["ROUTARD", "AQ", "AQ_FO", "DGIG", "Sépaq", "BDTQ"]            # ordre d'affichage, présentes seulement
    assert set(p["srcLabels"]) == set(p["srcs"])
    assert len(p["points"]) == 10


def test_points_entiers_tries_et_indices_valides():
    p = forestiers.construire_payload(_ponts())
    for lat, lon, src, st, dossier, cap in p["points"]:
        assert isinstance(lat, int) and isinstance(lon, int)
        assert 4_000_000 < lat < 6_500_000 and -8_100_000 < lon < -5_600_000        # degrés × 1e5, lat puis lon
        assert 0 <= src < len(p["srcs"]) and 0 <= st < len(p["sts"])
        assert dossier is None or isinstance(dossier, str)
        assert cap is None or isinstance(cap, str)
    assert [r[:2] for r in p["points"]] == sorted(r[:2] for r in p["points"])
    h = next(r for r in p["points"] if r[4] == "H024-025")
    assert h == [4_882_360, -7_175_342, p["srcs"].index("DGIG"), 0, "H024-025", "50-90-120"]
    assert next(r for r in p["points"] if r[4] == "H011-163")[3] == 2                # fermé


def test_sources_non_documentees_marquees():
    p = forestiers.construire_payload(_ponts())
    assert "signification non documentée" in p["srcLabels"]["DGIG"]
    assert "signification non documentée" not in p["srcLabels"]["Sépaq"]
    inconnue = forestiers.construire_payload([{**_ponts()[0], "src": "NOUVEAU"}])
    assert inconnue["srcs"] == ["NOUVEAU"] and "signification non documentée" in inconnue["srcLabels"]["NOUVEAU"]


def test_ecriture_js_compacte_et_encodage_utf8(tmp_path):
    payload = forestiers.construire_payload(_ponts(), generated="2026-10-14")
    taille = forestiers.ecrire(payload, tmp_path / "couche-forestiers.js")
    octets = (tmp_path / "couche-forestiers.js").read_bytes()
    assert taille == len(octets)
    texte = octets.decode("utf-8")                                      # UTF-8 valide, accents intacts
    prefixe = "window.PQ_COUCHES=window.PQ_COUCHES||{};window.PQ_COUCHES.forestiers="
    assert texte.startswith(prefixe) and texte.endswith(";\n")
    corps = texte[len(prefixe):-2]
    assert json.loads(corps) == payload
    assert "Sépaq" in corps and "Adresses Québec" in corps and "\\u" not in corps   # ensure_ascii=False
    assert ", " not in corps.split('"points":')[1]                       # points sans espaces (JSON compact)


# --- Cache et téléchargement ---------------------------------------------------------------------
def _ecrire_pages(dossier, **pages):
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, geojson in pages.items():
        (dossier / f"{nom}.geojson").write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")


def test_charger_cache_lit_les_pages_et_ignore_les_doublons_d_objectid(tmp_path):
    g = _geojson()
    _ecrire_pages(tmp_path, aq_pont1_0=g, aq_pont1_2000=g, aq_pont2_0=g)          # page 2000 = copie de la page 0
    ponts = forestiers.charger_cache(tmp_path)
    assert len(ponts) == 20                                                       # 10 (couche 1) + 10 (couche 2)
    assert {p["oid"][0] for p in ponts} == {1, 2}


def test_charger_cache_absent(tmp_path):
    with pytest.raises(FileNotFoundError):
        forestiers.charger_cache(tmp_path / "vide")


def _faux_curl(pages, appels):
    """Simule curl : `pages[(couche, décalage)]` = nombre d'objets servis."""
    def faux(url, params):
        couche = int(url.rstrip("/").split("/")[-2])
        n = pages[(couche, params["resultOffset"])]
        appels.append((couche, params["resultOffset"]))
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [-71.0, 47.0 + i * 1e-4]},
                  "properties": {"Source": "AQ", "Stat_Pont": "O", "Dossi_Pont": None, "Cap_Port": "INC",
                                 "Version": "AQ1", "OBJECTID": params["resultOffset"] + i}} for i in range(n)]
        return json.dumps({"type": "FeatureCollection", "features": feats,
                           **({"exceededTransferLimit": True} if n == forestiers.TAILLE_PAGE else {})})
    return faux


def test_telecharger_couche_pagine_jusqu_a_la_derniere_page(monkeypatch):
    monkeypatch.setattr(forestiers, "TAILLE_PAGE", 3)
    monkeypatch.setattr(forestiers, "PAUSE_S", 0)
    appels = []
    monkeypatch.setattr(forestiers, "_curl", _faux_curl({(1, 0): 3, (1, 3): 3, (1, 6): 1}, appels))
    pages = forestiers.telecharger_couche(1)
    assert list(pages) == [0, 3, 6] and appels == [(1, 0), (1, 3), (1, 6)]


def test_telecharger_et_ecrire_cache_remplace_les_anciennes_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(forestiers, "PAUSE_S", 0)
    appels = []
    monkeypatch.setattr(forestiers, "_curl", _faux_curl({(1, 0): 2, (2, 0): 1, (3, 0): 0}, appels))
    pages = forestiers.telecharger()
    assert sorted(pages) == [1, 2, 3]
    _ecrire_pages(tmp_path, aq_pont1_0={}, aq_pont1_2000={}, aq_pont1_4000={})            # pages d'une ancienne version
    forestiers.ecrire_cache(pages, tmp_path)
    assert sorted(f.name for f in tmp_path.iterdir()) == ["aq_pont1_0.geojson", "aq_pont2_0.geojson", "aq_pont3_0.geojson"]
    assert len(forestiers.charger_cache(tmp_path)) == 3


def test_curl_reessaie_puis_abandonne(monkeypatch):
    monkeypatch.setattr(forestiers.time, "sleep", lambda s: None)
    reponses = iter([b"<html>reset</html>", b'{"error":{"code":500}}', '{"features":[]}'.encode()])

    def faux_run(cmd, **kw):
        assert cmd[0] == "curl" and "-A" in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=next(reponses), stderr=b"")
    monkeypatch.setattr(forestiers.subprocess, "run", faux_run)
    assert json.loads(forestiers._curl("https://exemple.test/q", {"f": "geojson"})) == {"features": []}
    monkeypatch.setattr(forestiers.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 35, b"", b""))
    with pytest.raises(forestiers.ErreurReseau):
        forestiers._curl("https://exemple.test/q", {})


def test_decoder_utf8_puis_cp1252():
    assert forestiers._decoder("Sépaq".encode("utf-8")) == "Sépaq"
    assert forestiers._decoder("Sépaq".encode("cp1252")) == "Sépaq"


# --- Orchestration -------------------------------------------------------------------------------
@pytest.fixture
def espace(tmp_path, monkeypatch):
    monkeypatch.setattr(forestiers, "DOSSIER_RAW", tmp_path / "raw")
    monkeypatch.setattr(forestiers, "OUT", tmp_path / "couche-forestiers.js")
    monkeypatch.setattr(forestiers, "PAUSE_S", 0)
    _ecrire_pages(tmp_path / "raw", aq_pont1_0=_geojson())
    return tmp_path


def test_run_hors_ligne_ecrit_la_couche(espace, monkeypatch):
    p = _ponts()[0]
    monkeypatch.setattr(forestiers, "charger_mtmd", lambda: [("00001", p["lat"], p["lon"], None)])
    bilan = forestiers.run(fetch=False)
    assert bilan["total_aq"] == 10 and bilan["rows"] == 9 and bilan["doublons"] == 1
    assert sum(bilan["par_source"].values()) == 9 and sum(bilan["par_statut"].values()) == 9
    obj = json.loads((espace / "couche-forestiers.js").read_text(encoding="utf-8").split("forestiers=", 1)[1].rstrip()[:-1])
    assert len(obj["points"]) == 9 and bilan["bytes"] == (espace / "couche-forestiers.js").stat().st_size


def test_run_serveur_injoignable_conserve_le_fichier_precedent(espace, monkeypatch):
    (espace / "couche-forestiers.js").write_text("ancien", encoding="utf-8")

    def panne():
        raise forestiers.ErreurReseau("reset")
    monkeypatch.setattr(forestiers, "telecharger", panne)
    bilan = forestiers.run(fetch=True)
    assert bilan["conserve"] is True and (espace / "couche-forestiers.js").read_text(encoding="utf-8") == "ancien"
    assert len(list((espace / "raw").iterdir())) == 1                       # cache intact


def test_run_serveur_injoignable_sans_fichier_precedent_leve(espace, monkeypatch):
    def panne():
        raise forestiers.ErreurReseau("reset")
    monkeypatch.setattr(forestiers, "telecharger", panne)
    with pytest.raises(forestiers.ErreurReseau):
        forestiers.run(fetch=True)
