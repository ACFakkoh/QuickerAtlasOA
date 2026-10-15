"""Tests de `etl.sismique` : projection, ZIP à distance, TIN, encodage, découpage en fichiers, rasters et
VALIDATION de l'interpolation contre les réponses de l'API de RNCan (fixture autonome + données réelles si présentes)."""
import io
import json
import math
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest

from etl import sismique as s

FIXTURES = Path(__file__).parent / "fixtures"
CACHE_API = Path(__file__).resolve().parent.parent / "prototypes" / "sismique" / "cache"


# --- Projection ----------------------------------------------------------------------------------
def test_lcc_retrouve_les_noeuds_du_fichier():
    # nœuds du CSV officiel (x, y arrondis à 0,1 m ; lat/lon arrondis à 0,001° mais calculés depuis x, y)
    for lat, lon, x, y in [(49.196, -133.935, -2661811.2, 2000070.6), (47.29, -131.814, -2650214.6, 1735475.8)]:
        px, py = s.lcc(lat, lon)
        assert abs(px - x) < 0.2 and abs(py - y) < 0.2


def test_lcc_accepte_les_tableaux():
    x, y = s.lcc(np.array([45.0, 46.0]), np.array([-73.0, -72.0]))
    assert x.shape == (2,) and y.shape == (2,)
    assert abs(float(x[0]) - float(s.lcc(45.0, -73.0)[0])) < 1e-6


# --- ZIP à distance ------------------------------------------------------------------------------
def _zip_en_memoire():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dossier/", b"")
        z.writestr("dossier/a.csv", b"Index,Longitude\n" + b"x,1\n" * 500)
        z.writestr("dossier/b.csv", b"autre contenu " * 100)
    return buf.getvalue()


def test_lire_repertoire_et_membres_par_plages():
    zbytes = _zip_en_memoire()
    appels = []

    def lire(a, b):
        appels.append((a, b))
        return zbytes[a:b + 1]

    rep = s.lire_repertoire_zip(lire, len(zbytes))
    assert {"dossier/a.csv", "dossier/b.csv"} <= set(rep)
    ent = rep["dossier/b.csv"]
    assert ent["meth"] == 8 and ent["us"] == len(b"autre contenu " * 100)
    brut = s.lire_membre_brut(lire, ent)
    assert len(brut) == ent["cs"]
    assert s.inflater(brut, ent) == b"autre contenu " * 100
    assert max(b - a for a, b in appels) < len(zbytes) or len(zbytes) < 70_000   # jamais le fichier entier à la fois


def test_inflater_detecte_la_corruption():
    zbytes = _zip_en_memoire()
    rep = s.lire_repertoire_zip(lambda a, b: zbytes[a:b + 1], len(zbytes))
    ent = dict(rep["dossier/a.csv"])
    brut = s.lire_membre_brut(lambda a, b: zbytes[a:b + 1], ent)
    with pytest.raises(ValueError):
        s.inflater(brut, {**ent, "crc": ent["crc"] ^ 1})


# --- Lecture CSV ---------------------------------------------------------------------------------
def _ligne(idx, lon, lat, poe, base):
    sa = [base + k / 100 for k in range(9)]
    return f"{idx},{lon},{lat},0,0,XC,{poe}," + ",".join(str(v) for v in sa) + f",{base + 1},{base + 2}\n"


def test_parse_noeuds_filtre_bbox_et_probabilites():
    texte = "Index,Longitude,Latitude,x,y,sd,poe,Sa...\n"
    for poe in ("2.0", "2.5", "5.0", "10.0"):
        texte += _ligne("n1", -73.0, 45.5, poe, float(poe))
    texte += _ligne("loin", -130.0, 49.0, "2.0", 1.0)
    nd = s.parse_noeuds(texte.encode())
    assert set(nd) == {"n1"}
    v = nd["n1"]["v"]
    assert v.shape == (3, 11) and not np.isnan(v).any()
    assert v[0, s.MESURES.index("pga")] == 3.0 and v[0, s.MESURES.index("pgv")] == 4.0   # poe 2 % : base 2
    assert v[2, s.MESURES.index("sa0p05")] == 10.0                                         # poe 10 %
    assert v[1, s.MESURES.index("sa10p0")] == pytest.approx(5.08)


def test_parse_triangles_ne_garde_que_les_sommets_connus():
    texte = b"Triangle_Index,Vertex1_Index,Vertex2_Index,Vertex3_Index\nt1,a,b,c\nt2,a,b,z\n"
    assert s.parse_triangles(texte, {"a", "b", "c"}) == [("a", "b", "c")]


# --- TIN et interpolation ------------------------------------------------------------------------
def _petit_maillage():
    """Carré de 10 km de côté coupé en 2 triangles, champ linéaire v = 1 + 2x + 3y (mesures et classes décalées)."""
    xy = np.array([[0, 0], [10000, 0], [10000, 10000], [0, 10000]], dtype=float)
    base = 1 + 2e-4 * xy[:, 0] + 3e-4 * xy[:, 1]
    vals = np.zeros((5, 4, 3, 11))
    for c in range(5):
        for p in range(3):
            for m in range(11):
                vals[c, :, p, m] = base * (c + 1) + p * 10 + m * 100
    return s.Maillage(xy, np.zeros((4, 2)), np.array([[0, 1, 2], [0, 2, 3]]), vals)


def test_barycentrique_et_interpolation_exacte_d_un_champ_lineaire():
    m = _petit_maillage()
    for x, y in [(2500.0, 1000.0), (1000.0, 9000.0), (5000.0, 5000.0), (0.0, 0.0), (10000.0, 10000.0)]:
        t, w = m.localiser(x, y)
        assert sum(w) == pytest.approx(1) and min(w) >= -1e-9
        v = m.interpoler([t], [w])[0]
        attendu = 1 + 2e-4 * x + 3e-4 * y
        assert v[0, 0, 0] == pytest.approx(attendu)
        assert v[4, 2, 10] == pytest.approx(attendu * 5 + 20 + 1000)


def test_localiser_hors_reseau():
    assert _petit_maillage().localiser(-5.0, 100.0) is None
    assert _petit_maillage().localiser(5000.0, 20000.0) is None


def test_calculer_encode_et_ecarte_les_points_hors_reseau():
    m = _petit_maillage()
    x, y = s.lcc(45.0, -73.0)
    m2 = s.Maillage(m.xy + np.array([float(x), float(y)]), m.lonlat, m.tri, m.vals)
    out, manq = s.calculer(m2, [("A1", 45.0, -73.0), ("B2", 10.0, -73.0)], None)
    assert manq == ["B2"] and list(out) == ["A1"]
    assert len(out["A1"]) == 1 + s.NB_VAL and out["A1"][0] == 0


# --- Encodage ------------------------------------------------------------------------------------
def test_encodage_au_moins_trois_chiffres_significatifs():
    v = np.geomspace(0.001, 5.0, 4000)
    err = np.abs(s.decoder(s.encoder(v)) - v) / v
    assert err.max() < 0.00125                       # moins de 0,125 % : > 3 chiffres significatifs
    assert s.decoder(s.encoder(0.4624)) == pytest.approx(0.4624, rel=0.00125)


def test_encodage_plancher_et_entiers():
    assert int(s.encoder(0.0)) == 0 and int(s.encoder(1e-5)) == 0 and int(s.encoder(1e-4)) == 0
    assert int(s.encoder(1.0)) == 4000 and int(s.encoder(10.0)) == 5000
    assert s.encoder(np.array([0.5, 2.0])).dtype.kind == "i"


def test_index_val():
    assert s.index_val(0, 0, 0) == 0 and s.index_val(4, 2, 10) == s.NB_VAL - 1 == 164
    assert s.index_val(1, 0, 0) == 33 and s.index_val(0, 1, 0) == 11


# --- Découpage en fichiers -----------------------------------------------------------------------
# Mêmes valeurs dans tests/js/sismique_smoke.mjs (parité Python / JavaScript).
SHARDS_REF = {"00002": "65", "00003": "2a", "03226": "62", "13247A": "77", "14346C": "58", "14949N": "2e",
              "99999": "68", "1": "04", "ABC": "03", "X-1": "6d"}


def test_shard_of_valeurs_de_reference():
    assert {n: s.shard_of(n) for n in SHARDS_REF} == SHARDS_REF


def test_shard_of_deterministe_equilibre_et_ascii():
    nums = [f"{i:05d}" for i in range(1, 11800)]
    cles = [s.shard_of(n) for n in nums]
    assert cles == [s.shard_of(n) for n in nums]
    assert all(len(c) == 2 and 0 <= int(c, 16) < s.N_SHARDS for c in cles)
    comptes = {c: cles.count(c) for c in set(cles)}
    assert len(comptes) == s.N_SHARDS and max(comptes.values()) < 1.4 * len(nums) / s.N_SHARDS
    with pytest.raises(ValueError):
        s.shard_of("é1")


def _charger_js(chemin: Path):
    t = chemin.read_text(encoding="utf-8")
    return json.loads(t[t.index("']=") + 3:].rstrip().rstrip(";"))


def test_ecrire_shards(tmp_path):
    donnees = {n: [i % 6] + [1000 + i] * s.NB_VAL for i, n in enumerate(SHARDS_REF)}
    info = s.ecrire_shards(donnees, tmp_path, today="2026-10-14")
    fichiers = sorted(tmp_path.glob("s-*.js"))
    assert len(fichiers) == s.N_SHARDS and (tmp_path / "meta.js").exists()
    t = fichiers[0].read_text(encoding="utf-8")
    assert t.startswith("(window.PQ_SISMIQUE=window.PQ_SISMIQUE||{})['00']=") and t.endswith(";\n")
    trouves = {}
    for f in fichiers:
        d = _charger_js(f)
        assert d["_"] == {"fmt": s.FORMAT, "gen": "2026-10-14"}
        for n, v in d.items():
            if n != "_":
                assert f.name == f"s-{s.shard_of(n)}.js"
                trouves[n] = v
    assert trouves == donnees and info["bytes"] > 0
    m = json.loads((tmp_path / "meta.js").read_text(encoding="utf-8").split("=", 1)[1].rstrip().rstrip(";"))
    assert m["doi"] == s.DOI and m["mesures"][0] == "pga" and m["echelle"]["v"].startswith("1e-4")


# --- Classes de site du Québec (Rosset et al. 2025) ----------------------------------------------
SEUILS_VS30 = {"A": (1500, 1e9), "B": (760, 1500), "C": (360, 760), "D": (180, 360), "E": (0, 180)}


def test_tableau3_classes_coherentes_avec_le_vs30():
    """Chaque classe du tableau 3 correspond au Vs30 moyen pondéré publié (seuils du CNBC)."""
    assert len(s.TABLEAU3) == 21
    for code, (_, vs, cl) in s.TABLEAU3.items():
        lo, hi = SEUILS_VS30[cl]
        assert lo <= vs < hi, (code, vs, cl)
    # valeurs de l'article : glissements D, roc A, argile marine profonde C, till B
    assert [s.TABLEAU3[c][2] for c in ("Cg", "R", "MGa", "T", "Ap", "A")] == list("DACBBC")


def test_code_vers_classe_alias_et_codes_non_classes():
    assert s.code_vers_classe("R") == 1 and s.code_vers_classe("Cg") == 4 and s.code_vers_classe("MGa") == 3
    assert s.code_vers_classe("Qa") == s.code_vers_classe("Q") == 2          # Q de l'article = Qa du SIGEOM
    for c in ("Qf", "Ce", "Gxi", "H", "Ac", "zz"):
        assert s.code_vers_classe(c) == s.NON_CLASSE
    assert s.code_vers_classe("L") == s.EAU and s.TABLEAU3["L"][2] == "B"     # lacs : figure 10 en bleu
    assert set(s.CODES_SIGEOM) >= set(s.TABLEAU3) - {"Q"}                     # tout le tableau est cartographiable


def test_couleurs_sigeom_distinctes_et_couleurs_de_l_article():
    cols = list(s.COULEURS_SIGEOM.values())
    assert len(cols) == len(set(cols)) == len(s.CODES_SIGEOM) == 26          # décodage sans ambiguïté
    assert [c[0] for c in s.CLASSES_QC] == list("ABCD")
    assert [c[2] for c in s.CLASSES_QC] == ["#36bf29", "#2306ff", "#e4ff04", "#cf15d8"]   # figure 10 de l'article


def test_tuiles_couvrent_la_grille_sans_recouvrement():
    g = s.grille_qc_vide()
    assert (g["nx"], g["ny"]) == (7600, 8900)
    couvert = np.zeros((g["ny"], g["nx"]), np.int8)
    for ti, tj, (o, sd, e, n), w, h in s.tuiles(g):
        couvert[ti * s.TUILE:ti * s.TUILE + h, tj * s.TUILE:tj * s.TUILE + w] += 1
        assert e - o == pytest.approx(w * g["dlon"]) and n - sd == pytest.approx(h * g["dlat"])
        assert n == pytest.approx(g["north"] - ti * s.TUILE * g["dlat"]) and o == pytest.approx(g["west"] + tj * s.TUILE * g["dlon"])
    assert (couvert == 1).all()
    u = s.url_tuile((-74.0, 45.0, -73.0, 46.0), 10, 20)
    assert "antialias%3Anone" in u and "SRS=EPSG%3A4269" in u and "BBOX=-74.000000000%2C45.000000000" in u


def test_decoder_tuile_couleurs_exactes_et_transparence():
    codes = s.CODES_SIGEOM
    rgba = np.zeros((2, 3, 4), np.uint8)
    for k, (j, i) in enumerate([(0, 0), (0, 1), (1, 2)]):
        rgba[j, i, :3] = s.hex_rgb(s.COULEURS_SIGEOM[codes[k * 5]])
        rgba[j, i, 3] = 255
    rgba[1, 0] = (255, 255, 255, 0)                                          # transparent : aucun polygone
    rgba[1, 1] = (*s.hex_rgb(s.COULEURS_SIGEOM["R"])[:2], 3, 255)            # couleur presque exacte
    v, inconnus = s.decoder_tuile(rgba)
    assert v[0, 0] == 1 and v[0, 1] == 6 and v[1, 2] == 11 and v[1, 0] == 0
    assert codes[v[1, 1] - 1] == "R" and inconnus == 1


def _grille_test():
    codes = list(s.CODES_SIGEOM)
    k = {c: codes.index(c) + 1 for c in codes}
    v = np.array([[0, k["R"], k["T"], k["MGa"]],
                  [k["Cg"], k["Qf"], k["Qa"], 0]], np.uint8)
    return {"north": 46.0, "west": -74.0, "dlat": 0.002, "dlon": 0.003, "nx": 4, "ny": 2, "codes": codes, "v": v}


def test_classe_et_code_d_une_cellule():
    g = _grille_test()
    assert s.code_qc(g, 45.999, -73.9985) is None and s.classe_qc(g, 45.999, -73.9985) == 0     # aucun polygone
    assert s.code_qc(g, 45.999, -73.9955) == "R" and s.classe_qc(g, 45.999, -73.9955) == 1
    assert s.classe_qc(g, 45.999, -73.9925) == 2 and s.classe_qc(g, 45.999, -73.9895) == 3
    assert s.classe_qc(g, 45.997, -73.9985) == 4                                                 # Cg → D
    assert s.code_qc(g, 45.997, -73.9955) == "Qf" and s.classe_qc(g, 45.997, -73.9955) == 0      # non classé
    assert s.classe_qc(g, 45.997, -73.9925) == 2                                                 # Qa → B
    assert s.classe_qc(g, 47.0, -73.99) == 0 and s.classe_qc(g, 45.999, -72.0) == 0              # hors grille
    cl = s.classes_de_grille(g)
    assert cl.tolist() == [[0, 1, 2, 3], [4, s.NON_CLASSE, 2, 0]]
    assert s.classes_structures([("a", 45.999, -73.9955), ("b", 45.997, -73.9955), ("c", 45.0, -73.0)], g) == {"a": 1}


def test_ecrire_et_relire_la_grille(tmp_path):
    g = _grille_test()
    s.ecrire_grille_qc(g, tmp_path, today="2026-10-15")
    r = s.charger_grille_qc(tmp_path)
    assert (r["v"] == g["v"]).all() and r["codes"] == g["codes"] and r["generated"] == "2026-10-15"
    assert r["comptes_classes"]["A"] == 1 and r["comptes_classes"]["non classé"] == 1 and r["alias"] == {"Qa": "Q"}
    assert r["comptes_classes"]["eau"] == 0 and "L" in r["eau"]
    assert r["url"] == s.URL_ARTICLE and "Geotechnics 5(2):24" in r["source"]


def test_ecrire_classes_site(tmp_path):
    f = tmp_path / "classes-site.js"
    s.ecrire_classes_site({"00002": 2, "13247A": 4, "00010": 1}, f, today="2026-10-15")
    t = f.read_text(encoding="utf-8")
    assert t.startswith("window.PQ_CLASSE_SITE={") and t.endswith(";\n")
    d = json.loads(t.split("=", 1)[1].rstrip().rstrip(";"))
    assert d["_"]["url"] == s.URL_ARTICLE and d["_"]["generated"] == "2026-10-15" and d["_"]["source"]
    assert {k: v for k, v in d.items() if k != "_"} == {"00002": "B", "00010": "A", "13247A": "D"}


def test_png_classes_qc_majorite_et_transparence(tmp_path):
    from PIL import Image
    codes = list(s.CODES_SIGEOM)
    k = {c: codes.index(c) + 1 for c in codes}
    v = np.zeros((40, 60), np.uint8)
    v[:, :20] = k["R"]                       # A
    v[:, 20:40] = k["MGa"]                   # C
    v[:, 40:] = k["Qf"]                      # non classé → transparent
    g = {"north": 46.0, "west": -74.0, "dlat": 0.002, "dlon": 0.003, "nx": 60, "ny": 40, "codes": codes, "v": v}
    info = s.png_classes_qc(g, tmp_path / "c.png", largeur=30)
    im = Image.open(tmp_path / "c.png").convert("RGBA")
    assert im.size == (30, info["h"]) and info["bounds"] == [[45.92, -74.0], [46.0, -73.82]]
    y = info["h"] // 2
    assert im.getpixel((2, y))[:3] == s.hex_rgb("#36bf29") and im.getpixel((2, y))[3] == 255
    assert im.getpixel((15, y))[:3] == s.hex_rgb("#e4ff04")
    assert im.getpixel((25, y))[3] == 0
    assert info["classes"][0] == 10 * info["h"] and info["classes"][2] == 10 * info["h"]


def test_masque_quebec_bouche_les_lacs():
    v = np.zeros((100, 100), np.uint8)
    v[10:90, 10:90] = 1
    v[40:60, 40:60] = 0                      # lac intérieur sans polygone
    g = {"north": 46.0, "west": -74.0, "dlat": 0.01, "dlon": 0.01, "nx": 100, "ny": 100, "v": v}
    lats = 46.0 - (np.arange(100) + 0.5) * 0.01
    lons = -74.0 + (np.arange(100) + 0.5) * 0.01
    m = s.masque_quebec(g, lats, lons, marge_px=0)
    assert m[50, 50] and m[15, 15] and not m[5, 5] and not m[95, 50]
    assert s.masque_quebec(g, lats, lons, marge_px=2)[8, 50]


GRILLE_OK = (s.DONNEES / s.GRILLE_QC_JSON).exists() and (s.DONNEES / s.GRILLE_QC_PNG).exists()


@pytest.mark.skipif(not GRILLE_OK, reason="grille versionnée absente (python -m etl.sismique)")
def test_grille_qc_embarquee():
    g = s.charger_grille_qc()
    assert (g["nx"], g["ny"]) == (7600, 8900) and g["codes"] == list(s.CODES_SIGEOM)
    cl = s.classes_de_grille(g)
    n = {k: int((cl == k).sum()) for k in range(7)}
    assert n[1] > 1e6 and n[2] > 1e6 and n[3] > 1e5 and n[4] > 0 and n[5] == 0     # pas de classe E dans l'article
    # roc du Bouclier (A ou B) à Chibougamau, argile de la mer de Champlain (C) à Saint-Hyacinthe
    assert s.classe_qc(g, 45.62, -72.95) == 3
    assert s.classe_qc(g, 49.91, -74.37) in (1, 2)
    # Montréal est couverte (la couche de Montréal de 2023 est retirée)
    assert s.code_qc(g, 45.52, -73.62) is not None


# --- Rasters Web Mercator ------------------------------------------------------------------------
def test_grille_mercator_lignes_regulieres_en_y_mercator():
    lats, lons = s.grille_mercator(45.0, -80.0, 60.0, -57.0, 400)
    y = s.merc_y(lats)
    assert np.allclose(np.diff(y), np.diff(y)[0])                       # pas constant en Mercator…
    assert not np.allclose(np.diff(lats), np.diff(lats)[0])             # … donc pas en latitude
    assert abs(len(lats) / len(lons) - (y[0] - y[-1]) / math.radians(23.0)) < 0.01
    assert lats[0] < 60.0 and lats[-1] > 45.0 and lons[0] > -80.0 and lons[-1] < -57.0


def test_indice_pixel_inverse_de_grille_mercator():
    sud, ouest, nord, est = 45.0, -80.0, 60.0, -57.0
    lats, lons = s.grille_mercator(sud, ouest, nord, est, 300)
    i, j = s.indice_pixel(lats, lons, sud, ouest, nord, est, len(lons), len(lats))
    assert np.allclose(i, np.arange(len(lats)), atol=1e-6) and np.allclose(j, np.arange(len(lons)), atol=1e-6)


def test_rasteriser_champ_lineaire_dans_la_projection_du_fichier():
    """Deux triangles couvrant ≈ Montréal ; champ = a·x + b·y aux nœuds → même champ en tout pixel."""
    lon = np.array([-74.0, -73.0, -73.0, -74.0])
    lat = np.array([45.0, 45.0, 46.0, 46.0])
    x, y = s.lcc(lat, lon)
    xy = np.column_stack([x, y])
    mail = s.Maillage(xy, np.column_stack([lon, lat]), np.array([[0, 1, 2], [0, 2, 3]]), np.zeros((5, 4, 3, 11)))
    champ = lambda X, Y: 1e-6 * (X - x[0]) + 2e-6 * (Y - y[0])
    bornes = (45.1, -73.9, 45.9, -73.1)
    lats, lons = s.grille_mercator(*bornes, 120)
    out = s.rasteriser(mail, champ(xy[:, 0], xy[:, 1]), lats, lons, bornes)
    X, Y = s.lcc(lats[:, None] * np.ones((1, len(lons))), lons[None, :] * np.ones((len(lats), 1)))
    assert not np.isnan(out).any()
    assert np.abs(out - champ(X, Y)).max() < 1e-6
    # hors du réseau : NaN
    lats2, lons2 = s.grille_mercator(46.2, -73.9, 46.5, -73.1, 20)
    assert np.isnan(s.rasteriser(mail, champ(xy[:, 0], xy[:, 1]), lats2, lons2, (46.2, -73.9, 46.5, -73.1))).all()


def test_masque_proximite_rayon_en_kilometres():
    bornes = (45.0, -74.0, 46.0, -72.0)
    lats, lons = s.grille_mercator(*bornes, 400)
    m = s.masque_proximite([(45.5, -73.0)], bornes, len(lons), len(lats), rayon_km=20)
    i, j = s.indice_pixel(45.5, -73.0, *bornes, len(lons), len(lats))
    assert m[int(round(float(i))), int(round(float(j)))]
    # largeur du disque en km : ≈ 40 km (à 45,5 °N, 1° de longitude = 78 km)
    ligne = np.where(m[int(round(float(i)))])[0]
    km = (ligne[-1] - ligne[0] + 1) * (2.0 / len(lons)) * 78.0
    assert 37 < km < 43
    assert m.sum() < 0.1 * m.size


def test_palette_pga_clarte_monotone_et_nombre_de_couleurs():
    assert len(s.PGA_COULEURS) == len(s.PGA_BREAKS) + 1 and s.PGA_BREAKS == sorted(s.PGA_BREAKS)
    L = [s.luminance(c) for c in s.PGA_COULEURS]
    assert all(a > b + 3 for a, b in zip(L, L[1:])), L              # clarté strictement décroissante (daltonisme)
    # les classes de site gardent les couleurs de l'article (demande explicite), pas une rampe de clarté


def test_couche_contrat_avec_la_carte():
    c = s.couche({"bounds": [[44, -80], [63, -57]], "province": True}, {"bounds": [[44.9, -79.8], [62.7, -57.0]]},
                 today="2026-10-15")
    p = c["pga"]
    assert p["img"] == "data/sismique/pga-c-2pc.png" and len(p["colors"]) == len(p["breaks"]) + 1
    assert all(k in p for k in ("bounds", "titre", "source", "licence", "doi", "avertissement"))
    assert "50 km" not in p["avertissement"] and "territoire québécois" in p["avertissement"]
    k = c["classes"]
    assert k["img"] == "data/sismique/classes-qc.png" and k["bounds"] == [[44.9, -79.8], [62.7, -57.0]]
    assert [x["k"] for x in k["classes"]] == list("ABCD") and all(x["label"] and x["color"].startswith("#") for x in k["classes"])
    assert k["url"] == "https://www.mdpi.com/2673-7094/5/2/24" and k["source"] == "Rosset et al. (2025), Geotechnics 5(2):24"
    assert all(k.get(x) for x in ("titre", "avertissement")) and "mtl" not in c
    # repli sans grille du Québec : ancien masque de 50 km
    assert "50 km" in s.couche({"bounds": [[44, -80], [59, -56]], "province": False}, None)["pga"]["avertissement"]


# --- VALIDATION contre l'API de RNCan ------------------------------------------------------------
def test_validation_fixture_interpolation_vs_api():
    """46 ouvrages (11 exemples + 35 de Montréal) × 5 classes × 2, 5 et 10 % : interpolation des 3 sommets du triangle
    (fixture autonome) contre les valeurs de l'API (3 chiffres significatifs, donc ≈ 0,5 % de bruit d'arrondi)."""
    fx = json.loads((FIXTURES / "sismique_validation.json").read_text(encoding="utf-8"))
    assert len(fx["points"]) == 46 and fx["mesures"] == ["pga", "sa0p2", "sa1p0"]
    err = {m: [] for m in fx["mesures"]}
    for p in fx["points"]:
        x, y = s.lcc(p["lat"], p["lon"])
        a, b, c = p["sommets"]
        w = s.coords_barycentriques(float(x), float(y), a["x"], a["y"], b["x"], b["y"], c["x"], c["y"])
        assert min(w) >= -1e-9
        for ci in range(5):
            for pi in range(3):
                for mi, m in enumerate(fx["mesures"]):
                    v = sum(wk * sk["v"][ci][pi][mi] for wk, sk in zip(w, (a, b, c)))
                    ref = p["api"][ci][pi][mi]
                    err[m].append(abs(v - ref) / ref)
    for m, e in err.items():
        assert len(e) == 46 * 15
        assert max(e) < 0.01, (m, max(e))                  # mesuré : ≈ 0,5 % (arrondi à 3 chiffres de l'API)


RAW_OK = all((s.RAW_SISMIQUE / f"{k}.csv.deflate").exists() for k in s.noms_membres())


@pytest.fixture(scope="module")
def mail():
    return s.charger_maillage()


@pytest.mark.skipif(not RAW_OK, reason="grille officielle absente de data/raw/sismique (python -m etl.sismique)")
class TestDonneesReelles:
    def test_maillage_du_quebec(self, mail):
        assert 6000 < len(mail.xy) < 8000 and 12000 < len(mail.tri) < 15000
        assert mail.vals.shape == (5, len(mail.xy), 3, 11)
        assert (mail.vals[:, :, :, :] > 0).all()
        # l'aléa augmente avec la probabilité (2 % > 5 % > 10 %) à chaque nœud et pour chaque classe
        assert (mail.vals[:, :, 0] >= mail.vals[:, :, 1]).all() and (mail.vals[:, :, 1] >= mail.vals[:, :, 2]).all()

    @pytest.mark.skipif(not (CACHE_API / "exemples.json").exists(), reason="réponses de l'API absentes")
    def test_validation_complete_contre_les_reponses_de_l_api(self, mail):
        res = s.comparer_api(mail, s.points_validation(CACHE_API), s.MESURES)
        assert res.pop("hors_reseau") == 0
        for m in ("pga", "sa0p2", "sa1p0"):
            assert res[m]["max"] < 0.01, (m, res[m])
        assert all(r["max"] < 0.01 and r["n"] == 690 for r in res.values())

    def test_ouvrage_exemple(self, mail):
        # pont Honoré-Mercier (03226), classe C, 2 % : PGA 0,463 g, Sa(0,2) 0,845 g, Sa(1,0) 0,259 g (API) ;
        # k = classe de site fournie (ici absente : 0)
        out, manq = s.calculer(mail, [("03226", 45.41752, -73.65429)], {})
        q = out["03226"]
        v = lambda mi: float(s.decoder(q[1 + s.index_val(2, 0, mi)]))
        assert not manq
        assert v(0) == pytest.approx(0.463, rel=0.01) and v(4) == pytest.approx(0.845, rel=0.01)
        assert v(7) == pytest.approx(0.259, rel=0.01)
        assert q[0] == 0
        # la classe estimée est recopiée telle quelle en tête de l'entrée
        out, _ = s.calculer(mail, [("x", 45.5, -73.6)], {"x": 3})
        assert out["x"][0] == 3

    def test_raster_pga_coherent_avec_l_interpolation_aux_structures(self, mail):
        """La classe de couleur d'un pixel proche d'un ouvrage = celle du PGA (C, 2 %) interpolé à cet ouvrage."""
        pts = [("a", 45.41752, -73.65429), ("b", 47.65, -70.15), ("c", 48.43, -71.07), ("d", 46.81, -71.2)]
        bornes = (44.4, -80.4, 59.3, -56.2)
        lats, lons = s.grille_mercator(*bornes, 1400)
        champ = s.rasteriser(mail, mail.vals[2, :, 0, 0], lats, lons, bornes)
        for _, lat, lon in pts:
            x, y = s.lcc(lat, lon)
            t, w = mail.localiser(float(x), float(y))
            attendu = float(mail.interpoler([t], [w])[0, 2, 0, 0])
            i, j = s.indice_pixel(lat, lon, *bornes, len(lons), len(lats))
            v = champ[int(round(float(i))), int(round(float(j)))]
            assert abs(v - attendu) / attendu < 0.03          # un pixel de ≈ 1,3 km sur un champ qui varie de ≈ 1 %/km
