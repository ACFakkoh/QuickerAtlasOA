"""Aléa sismique CanSHM6 (CNBC 2020) interpolé à chaque structure du MTMD, plus deux couches raster pour la carte.

Source : Kolaj M., Halchuk S., Adams J. (2023), « Sixth-generation seismic hazard model of Canada: grid values of
mean hazard to be used with the 2020 National Building Code of Canada », Commission géologique du Canada, Dossier
public 8950, doi:10.4095/331497, Licence du gouvernement ouvert – Canada. Le CNBC 2025 reprend le même aléa.

Le ZIP officiel (`gid_331497.zip`, 232 Mo) n'est PAS téléchargé en entier : on lit son répertoire central par requêtes
HTTP `Range`, puis seulement les membres utiles, inflatés avec zlib (deflate brut) :
  - `AppendixB/NBCC2020_CanadaSHM6_X{A..E}.csv` : 5 classes de site, ≈ 11,4 Mo compressés chacune ;
  - `AppendixC/NBCC2020_CanadaSHM6_Grid.csv` : le réseau de triangles (TIN) qui relie les 34 733 nœuds.
Les copies brutes sont gardées dans `data/raw/sismique/` (non versionné) ; `--no-fetch` les relit sans réseau.

Méthode (celle de l'outil officiel) : les nœuds forment un TIN en projection conique conforme de Lambert (x, y du
fichier) ; la valeur en un point est l'interpolation barycentrique linéaire des trois sommets du triangle qui le
contient. On ne garde que les nœuds du Québec (+ marge) et les probabilités 2, 5 et 10 % en 50 ans.

Sorties (chargées à la demande par `js/sismique.js` et par la carte, via `<script src>`) :
  - `data/sismique/s-<clé>.js`  : `(window.PQ_SISMIQUE = window.PQ_SISMIQUE || {})['<clé>'] = {"_": {...}, "<n°>": [...]};`
    une entrée par structure : `[k, q0, q1, …, q164]` où `k` = classe de site estimée à Montréal (0 aucune, 1..5 = A..E,
    grille de Rosset et al. 2023) et `q` = 165 entiers, rangés classe (A..E) → probabilité (2, 5, 10 %) → mesure
    (`MESURES`, 11 valeurs). Index : `((classe × 3 + proba) × 11 + mesure)`.
    Échelle LOGARITHMIQUE : `q = round(1000 × log10(v / 1e-4))`, donc `v = 1e-4 × 10^(q/1000)` (g ; PGV en m/s) ;
    pas de 0,23 % (au moins 3 chiffres significatifs pour toute valeur ≥ 0,001), `q = 0` ↔ v ≤ 0,0001.
  - `data/sismique/meta.js`      : `window.PQ_SISMIQUE_META = {...}` (source, DOI, licence, date, échelle, colonnes) ;
  - `data/couche-sismique.js`    : `(window.PQ_COUCHES = …).sismique = {pga: {...}, mtl: {...}}` ;
  - `data/sismique/pga-c-2pc.png` et `data/sismique/classes-mtl.png` : rasters rééchantillonnés en lignes Web Mercator
    (EPSG:3857), comme `L.imageOverlay` les étire.

Classes de site de Montréal : `etl/donnees/classes_site_mtl.json` (grille 308 × 212, maille 0,004°, reconstituée de la
figure 10 de Rosset P., Takahashi A., Chouinard L. (2023), Geosciences 13(9):256, CC BY 4.0). Elle est versionnée
avec le module (et non dans `data/raw/`, qui est ignoré par git).

Découpage : `shard_of(num)` = FNV-1a 32 bits du n° de structure (ASCII) modulo `N_SHARDS`, écrit en hexadécimal sur 2 caractères.
La même fonction existe dans `js/sismique.js` (`shardOf`) ; `tests/js/sismique_smoke.mjs` vérifie la parité.
"""
import argparse
import json
import logging
import math
import sqlite3
import struct
import sys
import zlib
from datetime import date
from pathlib import Path

import numpy as np

from . import net
from .config import DATA_DIR, DB_PATH, RAW_DIR

SOURCE = "sismique"
log = logging.getLogger(__name__)

URL_ZIP = ("https://ostr-backend-prod.azure.cloud.nrcan-rncan.gc.ca/server/api/core/bitstreams/"
           "c36e469b-89ab-4ef9-a874-903def23bab4/content")
DOI = "10.4095/331497"
TITRE_SOURCE = ("Kolaj M., Halchuk S., Adams J. (2023), Sixth-generation seismic hazard model of Canada: grid values of "
                "mean hazard to be used with the 2020 National Building Code of Canada. CGC, Dossier public 8950")
LICENCE = "Licence du gouvernement ouvert – Canada"
SOURCE_MTL = ("Rosset P., Takahashi A., Chouinard L. (2023), Vs30 Mapping of the Greater Montreal Region Using Multiple "
              "Data Sources, Geosciences 13(9):256, doi:10.3390/geosciences13090256, CC BY 4.0 — grille reconstituée "
              "à partir de la figure 10")

RAW_SISMIQUE = RAW_DIR / "sismique"
OUT_DIR = DATA_DIR / "sismique"
OUT_COUCHE = DATA_DIR / "couche-sismique.js"
GRILLE_MTL = Path(__file__).resolve().parent / "donnees" / "classes_site_mtl.json"
PNG_PGA = "pga-c-2pc.png"
PNG_MTL = "classes-mtl.png"

CLASSES = "ABCDE"
POES = (2.0, 5.0, 10.0)                     # probabilités de dépassement en 50 ans retenues (%)
MESURES = ("pga", "pgv", "sa0p05", "sa0p1", "sa0p2", "sa0p3", "sa0p5", "sa1p0", "sa2p0", "sa5p0", "sa10p0")
NB_VAL = len(CLASSES) * len(POES) * len(MESURES)          # 165 entiers par structure
# colonnes du CSV de l'annexe B : Index, Longitude, Latitude, x, y, désignation, poe, Sa(0,05…10) ×9, PGA, PGV
COL_CSV = {"pga": 16, "pgv": 17, "sa0p05": 7, "sa0p1": 8, "sa0p2": 9, "sa0p3": 10, "sa0p5": 11, "sa1p0": 12,
           "sa2p0": 13, "sa5p0": 14, "sa10p0": 15}
V_REF = 1e-4                                # q = round(1000 × log10(v / V_REF))
PAS_LOG = 1000
N_SHARDS = 120                              # 120 fichiers de ≈ 70 à 100 Ko (clé hexadécimale sur 2 caractères)
FORMAT = 1

# Nœuds retenus : Québec (45 à 62,6 °N, 79,8 à 57,1 °O) + marge de ≈ 1,5° ; 34 733 nœuds → ≈ 6 500 par classe.
BBOX_QC = {"lat": (43.5, 64.0), "lon": (-81.5, -55.5)}
MASQUE_KM = 50                              # les rasters ne couvrent que le voisinage des structures du MTMD

# Projection du fichier (x, y) : conique conforme de Lambert, parallèles 49 et 77, méridien -95, GRS80.
# L'ordonnée du fichier est décalée d'une constante (1 137 169,78 m), ajustée sur les 34 733 nœuds (écart < 0,1 m).
LCC_A, LCC_F = 6378137.0, 1 / 298.257222101
LCC_P1, LCC_P2, LCC_LAT0, LCC_LON0 = 49.0, 77.0, 49.0, -95.0
LCC_FN = 1137169.78

# Palette séquentielle (magma) à clarté L* strictement décroissante du plus faible au plus fort : sûre en daltonisme.
PGA_BREAKS = [0.05, 0.10, 0.20, 0.30, 0.45, 0.70, 1.00]
PGA_COULEURS = ["#fcfdbf", "#fed395", "#fd9f6c", "#f4685c", "#d3436e", "#a3307e", "#6f1f81", "#3b0f70"]
# Classes de site : YlGnBu, clarté décroissante de A à E, sans motifs.
CLASSES_MTL = [
    ("A", "A — roc dur (Vs30 > 1500 m/s)", "#ffffb2"),
    ("B", "B — roc (Vs30 760 à 1500 m/s)", "#a1dab4"),
    ("C", "C — sol très dense et roc mou (Vs30 360 à 760 m/s)", "#41b6c4"),
    ("D", "D — sol raide (Vs30 180 à 360 m/s)", "#2c7fb8"),
    ("E", "E — sol meuble (Vs30 < 180 m/s)", "#253494"),
]
LARGEUR_PGA = 1400


# --- Projection ----------------------------------------------------------------------------------
def _lcc_const():
    e = math.sqrt(2 * LCC_F - LCC_F ** 2)

    def m(p):
        s = math.sin(math.radians(p))
        return math.cos(math.radians(p)) / math.sqrt(1 - e * e * s * s)

    def t(p):
        s = math.sin(math.radians(p))
        return math.tan(math.pi / 4 - math.radians(p) / 2) / (((1 - e * s) / (1 + e * s)) ** (e / 2))

    n = (math.log(m(LCC_P1)) - math.log(m(LCC_P2))) / (math.log(t(LCC_P1)) - math.log(t(LCC_P2)))
    f = m(LCC_P1) / (n * t(LCC_P1) ** n)
    return e, n, LCC_A * f, LCC_A * f * t(LCC_LAT0) ** n


def lcc(lat, lon):
    """(lat, lon) en degrés (scalaires ou tableaux numpy) → (x, y) en mètres dans la projection du fichier."""
    e, n, af, r0 = _lcc_const()
    phi = np.radians(np.asarray(lat, dtype=float))
    s = np.sin(phi)
    t = np.tan(np.pi / 4 - phi / 2) / (((1 - e * s) / (1 + e * s)) ** (e / 2))
    r = af * t ** n
    th = n * np.radians(np.asarray(lon, dtype=float) - LCC_LON0)
    return r * np.sin(th), LCC_FN + r0 - r * np.cos(th)


# --- Lecture du ZIP à distance -------------------------------------------------------------------
def lire_repertoire_zip(lire, taille: int) -> dict[str, dict]:
    """Répertoire central d'un ZIP lu par plages : {nom: {off, cs, us, crc, meth}}.
    `lire(a, b)` renvoie les octets [a, b] du fichier ; `taille` = longueur totale (ZIP64 non géré : inutile ici)."""
    queue = lire(max(0, taille - 70_000), taille - 1)
    i = queue.rfind(b"PK\x05\x06")
    if i < 0:
        raise ValueError("fin de répertoire ZIP introuvable")
    n_ent, taille_cd, off_cd = struct.unpack("<HII", queue[i + 10:i + 20])
    cd = lire(off_cd, off_cd + taille_cd - 1)
    out, p = {}, 0
    for _ in range(n_ent):
        if cd[p:p + 4] != b"PK\x01\x02":
            raise ValueError("entrée de répertoire ZIP invalide")
        meth = struct.unpack("<H", cd[p + 10:p + 12])[0]
        crc, cs, us, nl, el, cl = struct.unpack("<IIIHHH", cd[p + 16:p + 34])
        off = struct.unpack("<I", cd[p + 42:p + 46])[0]
        nom = cd[p + 46:p + 46 + nl].decode("utf-8", "replace")
        out[nom] = {"off": off, "cs": cs, "us": us, "crc": crc, "meth": meth}
        p += 46 + nl + el + cl
    return out


def lire_membre_brut(lire, ent: dict) -> bytes:
    """Octets compressés (deflate brut) d'un membre : saute l'en-tête local (30 octets + nom + extra)."""
    h = lire(ent["off"], ent["off"] + 29)
    nl, el = struct.unpack("<HH", h[26:30])
    debut = ent["off"] + 30 + nl + el
    return lire(debut, debut + ent["cs"] - 1)


def inflater(brut: bytes, ent: dict | None = None) -> bytes:
    """Deflate brut → octets ; vérifie taille et CRC32 quand l'entrée du répertoire est fournie."""
    t = zlib.decompress(brut, -15)
    if ent is not None and (len(t) != ent["us"] or zlib.crc32(t) != ent["crc"]):
        raise ValueError("membre ZIP corrompu (taille ou CRC32)")
    return t


def _lecteur_http(s):
    def lire(a, b):
        r = net.get(s, URL_ZIP, timeout=600, headers={"Range": f"bytes={a}-{b}"})
        if r.status_code != 206:
            raise RuntimeError(f"le serveur ne gère pas les plages d'octets (HTTP {r.status_code})")
        return r.content
    return lire


def noms_membres() -> dict[str, str]:
    """Nom local (sans extension) → chemin du membre dans le ZIP."""
    d = {c: f"Appendices/AppendixB/NBCC2020_CanadaSHM6_X{c}.csv" for c in CLASSES}
    d["Grid"] = "Appendices/AppendixC/NBCC2020_CanadaSHM6_Grid.csv"
    return d


def telecharger(raw_dir: Path = RAW_SISMIQUE) -> list[str]:
    """Télécharge (par plages) les membres absents de `raw_dir` ; renvoie les noms téléchargés."""
    manquants = {k: v for k, v in noms_membres().items() if not (raw_dir / f"{k}.csv.deflate").exists()}
    if not manquants:
        return []
    s = net.session()
    lire = _lecteur_http(s)
    n = int(net.get(s, URL_ZIP, timeout=60, headers={"Range": "bytes=0-0"}).headers["Content-Range"].split("/")[1])
    rep = lire_repertoire_zip(lire, n)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for k, chemin in manquants.items():
        ent = rep[chemin]
        brut = lire_membre_brut(lire, ent)
        inflater(brut, ent)                                  # vérifie avant d'écrire
        (raw_dir / f"{k}.csv.deflate").write_bytes(brut)
        log.info("sismique : %s téléchargé (%.1f Mo compressés)", chemin.rsplit("/", 1)[-1], len(brut) / 1e6)
    return list(manquants)


# --- Lecture des nœuds et du TIN -----------------------------------------------------------------
def dans_bbox(lat: float, lon: float, bbox: dict = BBOX_QC) -> bool:
    return bbox["lat"][0] <= lat <= bbox["lat"][1] and bbox["lon"][0] <= lon <= bbox["lon"][1]


def parse_noeuds(texte: bytes, bbox: dict = BBOX_QC) -> dict[str, dict]:
    """CSV d'une classe de site → {index: {lon, lat, x, y, v: tableau (3 probabilités, 11 mesures)}}.
    Ne garde que les nœuds dans `bbox` et les probabilités de `POES`."""
    poes = {repr(p).encode(): i for i, p in enumerate(POES)}            # b'2.0', b'5.0', b'10.0'
    cols = [COL_CSV[m] for m in MESURES]
    out: dict[str, dict] = {}
    for ligne in texte.split(b"\n")[1:]:
        p = ligne.split(b",")
        if len(p) < 18 or p[6] not in poes:
            continue
        lon, lat = float(p[1]), float(p[2])
        if not dans_bbox(lat, lon, bbox):
            continue
        idx = p[0].decode()
        nd = out.get(idx)
        if nd is None:
            nd = out[idx] = {"lon": lon, "lat": lat, "x": float(p[3]), "y": float(p[4]),
                             "v": np.full((len(POES), len(MESURES)), np.nan)}
        nd["v"][poes[p[6]]] = [float(p[c]) for c in cols]
    return out


def parse_triangles(texte: bytes, gardes) -> list[tuple[str, str, str]]:
    """CSV du TIN → triangles dont les trois sommets sont dans `gardes` (ensemble d'index de nœuds)."""
    out = []
    for ligne in texte.split(b"\n")[1:]:
        p = ligne.strip().split(b",")
        if len(p) < 4:
            continue
        a, b, c = p[1].decode(), p[2].decode(), p[3].decode()
        if a in gardes and b in gardes and c in gardes:
            out.append((a, b, c))
    return out


class Maillage:
    """TIN du Québec : coordonnées (x, y) des nœuds, triangles (indices de nœuds) et valeurs par classe.

    `xy` (n, 2) ; `lonlat` (n, 2) ; `tri` (m, 3) entiers ; `vals` (5 classes, n, 3 probabilités, 11 mesures)."""

    def __init__(self, xy, lonlat, tri, vals, pas: float = 20_000.0):
        self.xy, self.lonlat, self.tri, self.vals, self.pas = xy, lonlat, tri, vals, pas
        self.cases: dict[tuple[int, int], list[int]] = {}
        for t, (a, b, c) in enumerate(tri):
            xs, ys = xy[[a, b, c], 0], xy[[a, b, c], 1]
            for i in range(math.floor(xs.min() / pas), math.floor(xs.max() / pas) + 1):
                for j in range(math.floor(ys.min() / pas), math.floor(ys.max() / pas) + 1):
                    self.cases.setdefault((i, j), []).append(t)

    def localiser(self, x: float, y: float):
        """(x, y) → (triangle, poids barycentriques) ou None hors du réseau."""
        for t in self.cases.get((math.floor(x / self.pas), math.floor(y / self.pas)), ()):
            w = coords_barycentriques(x, y, *self.xy[self.tri[t]].ravel())
            if min(w) >= -1e-9:
                return t, w
        return None

    def interpoler(self, tris, poids):
        """Triangles (k,) et poids (k, 3) → valeurs (k, 5 classes, 3 probabilités, 11 mesures)."""
        tris, poids = np.asarray(tris), np.asarray(poids, dtype=float)
        sommets = self.tri[tris]                                   # (k, 3)
        return np.einsum("kj,ckjpm->kcpm", poids, self.vals[:, sommets])


def coords_barycentriques(x, y, x1, y1, x2, y2, x3, y3) -> tuple[float, float, float]:
    """Coordonnées barycentriques de (x, y) dans le triangle (1, 2, 3)."""
    d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    l1 = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / d
    l2 = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / d
    return l1, l2, 1 - l1 - l2


def construire_maillage(textes: dict[str, bytes], bbox: dict = BBOX_QC) -> Maillage:
    """`textes` = {'A'…'E': CSV, 'Grid': CSV} (octets décompressés) → `Maillage` du Québec."""
    par_classe = [parse_noeuds(textes[c], bbox) for c in CLASSES]
    ref = par_classe[0]
    for c, nd in zip(CLASSES, par_classe):
        if nd.keys() != ref.keys():
            raise ValueError(f"nœuds différents pour la classe {c}")
    ids = sorted(ref)
    pos = {i: k for k, i in enumerate(ids)}
    xy = np.array([[ref[i]["x"], ref[i]["y"]] for i in ids])
    lonlat = np.array([[ref[i]["lon"], ref[i]["lat"]] for i in ids])
    vals = np.stack([np.stack([nd[i]["v"] for i in ids]) for nd in par_classe])
    if np.isnan(vals).any():
        raise ValueError("valeurs manquantes dans les nœuds (probabilité absente)")
    tri = np.array([[pos[a], pos[b], pos[c]] for a, b, c in parse_triangles(textes["Grid"], set(ids))], dtype=int)
    return Maillage(xy, lonlat, tri, vals)


def charger_maillage(raw_dir: Path = RAW_SISMIQUE) -> Maillage:
    textes = {}
    for k in noms_membres():
        f = raw_dir / f"{k}.csv.deflate"
        if not f.exists():
            raise FileNotFoundError(f"{f} absent : lancer `python -m etl.sismique` sans --no-fetch")
        textes[k] = inflater(f.read_bytes())
    return construire_maillage(textes)


# --- Encodage ------------------------------------------------------------------------------------
def encoder(v):
    """Valeur(s) (g ou m/s) → entier(s) : round(1000 × log10(v / 1e-4)), 0 pour v ≤ 1e-4."""
    a = np.asarray(v, dtype=float)
    return np.rint(PAS_LOG * np.log10(np.maximum(a, V_REF) / V_REF)).astype(int)


def decoder(q):
    """Entier(s) → valeur(s) : 1e-4 × 10^(q/1000)."""
    return V_REF * 10.0 ** (np.asarray(q, dtype=float) / PAS_LOG)


def index_val(classe: int, proba: int, mesure: int) -> int:
    """Rang d'une valeur dans les 165 entiers d'une structure."""
    return (classe * len(POES) + proba) * len(MESURES) + mesure


def shard_of(num: str) -> str:
    """Clé de fichier (2 caractères hexadécimaux) d'un n° de structure : FNV-1a 32 bits (octets ASCII) modulo N_SHARDS."""
    if not num.isascii():
        raise ValueError(f"n° de structure non ASCII : {num!r}")
    h = 0x811C9DC5
    for b in num.encode("ascii"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return f"{h % N_SHARDS:02x}"


# --- Classes de site de Montréal -----------------------------------------------------------------
def charger_grille_mtl(chemin: Path = GRILLE_MTL) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))


def classe_mtl(g: dict, lat: float, lon: float) -> int:
    """Classe de site estimée (1..5 = A..E) dans la grille de Rosset et al. 2023, 0 hors grille ou sans valeur."""
    j = math.floor((g["north"] - lat) / g["step"])
    i = math.floor((lon - g["west"]) / g["step"])
    if 0 <= j < g["ny"] and 0 <= i < g["nx"]:
        return "0ABCDE".index(g["rows"][j][i])
    return 0


# --- Structures ----------------------------------------------------------------------------------
def charger_structures(db_path=DB_PATH) -> list[tuple[str, float, float]]:
    """Structures géolocalisées de l'inventaire : [(num_dossr, lat, lon)…] triées par n°."""
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        return conn.execute("SELECT num_dossr, lat, lon FROM structure WHERE lat IS NOT NULL AND lon IS NOT NULL "
                            "ORDER BY num_dossr").fetchall()
    finally:
        conn.close()


def calculer(mail: Maillage, structures, grille_mtl: dict | None = None):
    """Structures [(num, lat, lon)…] → ({num: [k, q…165]}, [nums hors réseau])."""
    xs, ys = lcc([s[1] for s in structures], [s[2] for s in structures])
    trouves, tris, poids, manquants = [], [], [], []
    for s, x, y in zip(structures, xs, ys):
        r = mail.localiser(float(x), float(y))
        if r is None:
            manquants.append(s[0])
            continue
        trouves.append(s)
        tris.append(r[0])
        poids.append(r[1])
    out: dict[str, list[int]] = {}
    if trouves:
        q = encoder(mail.interpoler(tris, poids)).reshape(len(trouves), NB_VAL)
        for s, ligne in zip(trouves, q):
            k = classe_mtl(grille_mtl, s[1], s[2]) if grille_mtl else 0
            out[s[0]] = [k] + [int(v) for v in ligne]
    return out, manquants


# --- Écriture des fichiers JS --------------------------------------------------------------------
def meta(today: str | None = None) -> dict:
    return {
        "format": FORMAT, "generated": today or date.today().isoformat(),
        "source": TITRE_SOURCE, "doi": DOI, "licence": LICENCE,
        "note": "Aléa moyen CanSHM6 du CNBC 2020 (repris par le CNBC 2025), valeurs aux nœuds interpolées dans le TIN officiel.",
        "classes": list(CLASSES), "poes": [int(p) for p in POES], "mesures": list(MESURES),
        "unites": {"pga": "g", "pgv": "m/s", "sa": "g"},
        "ordre": "classe (A..E) > probabilité (2, 5, 10 % en 50 ans) > mesure ; index = ((classe × 3 + proba) × 11 + mesure)",
        "echelle": {"q": "round(1000 × log10(v / 1e-4))", "v": "1e-4 × 10^(q/1000)", "pas_relatif": 0.0023,
                    "zero": "q = 0 : valeur ≤ 0,0001"},
        "shard": f"FNV-1a 32 bits des octets ASCII du n°, modulo {N_SHARDS}, en hexadécimal sur 2 caractères",
        "classeMtl": {"0": None, "1..5": "A..E", "source": SOURCE_MTL},
    }


def ecrire_js(chemin: Path, expr: str, valeur) -> int:
    corps = json.dumps(valeur, ensure_ascii=False, separators=(",", ":"))
    chemin.write_text(f"{expr}={corps};\n", encoding="utf-8")
    return chemin.stat().st_size


def ecrire_shards(donnees: dict[str, list[int]], out_dir: Path = OUT_DIR, today: str | None = None) -> dict:
    """Écrit `s-<clé>.js` pour chaque clé de `shard_of` et `meta.js` ; supprime les anciens fichiers `s-*.js`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for vieux in out_dir.glob("s-*.js"):
        vieux.unlink()
    lots: dict[str, dict] = {f"{k:02x}": {} for k in range(N_SHARDS)}
    for num in sorted(donnees):
        lots[shard_of(num)][num] = donnees[num]
    tailles = {}
    for cle, lot in lots.items():
        tailles[cle] = ecrire_js(out_dir / f"s-{cle}.js",
                                 f"(window.PQ_SISMIQUE=window.PQ_SISMIQUE||{{}})['{cle}']",
                                 {"_": {"fmt": FORMAT, "gen": today or date.today().isoformat()}, **lot})
    t_meta = ecrire_js(out_dir / "meta.js", "window.PQ_SISMIQUE_META", meta(today))
    return {"tailles": tailles, "meta": t_meta, "bytes": sum(tailles.values()) + t_meta}


# --- Rasters Web Mercator ------------------------------------------------------------------------
def merc_y(lat):
    """Latitude (degrés) → ordonnée Web Mercator sans unité (rayon 1)."""
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def lat_depuis_merc(y):
    return np.degrees(2 * np.arctan(np.exp(y)) - np.pi / 2)


def grille_mercator(sud: float, ouest: float, nord: float, est: float, largeur: int):
    """Centres de pixels d'une image qui couvre [sud, nord] × [ouest, est] avec des lignes régulières en Web Mercator.
    Renvoie (lats (h,), lons (w,))."""
    ytop, ybot = float(merc_y(nord)), float(merc_y(sud))
    haut = max(1, round(largeur * (ytop - ybot) / math.radians(est - ouest)))
    lons = ouest + (np.arange(largeur) + 0.5) / largeur * (est - ouest)
    lats = lat_depuis_merc(ytop - (np.arange(haut) + 0.5) / haut * (ytop - ybot))
    return lats, lons


def indice_pixel(lat, lon, sud, ouest, nord, est, largeur, haut):
    """Inverse de `grille_mercator` : (lat, lon) → (ligne, colonne) fractionnaires du pixel."""
    ytop, ybot = float(merc_y(nord)), float(merc_y(sud))
    return ((ytop - merc_y(lat)) / (ytop - ybot) * haut - 0.5,
            (np.asarray(lon, dtype=float) - ouest) / (est - ouest) * largeur - 0.5)


def rasteriser(mail: Maillage, valeurs, lats, lons, bornes) -> np.ndarray:
    """Interpole `valeurs` (n nœuds,) dans le TIN sur la grille de pixels (lats × lons) ; NaN hors triangles.
    Chaque pixel reçoit les coordonnées barycentriques exactes (x, y du fichier), comme pour les structures."""
    haut, large = len(lats), len(lons)
    X, Y = lcc(lats[:, None] * np.ones((1, large)), lons[None, :] * np.ones((haut, 1)))
    out = np.full((haut, large), np.nan)
    sud, ouest, nord, est = bornes
    rows, cols = indice_pixel(mail.lonlat[:, 1], mail.lonlat[:, 0], sud, ouest, nord, est, large, haut)
    for t, (a, b, c) in enumerate(mail.tri):
        r0 = max(0, int(math.floor(min(rows[[a, b, c]]))) - 2)
        r1 = min(haut, int(math.ceil(max(rows[[a, b, c]]))) + 3)
        c0 = max(0, int(math.floor(min(cols[[a, b, c]]))) - 2)
        c1 = min(large, int(math.ceil(max(cols[[a, b, c]]))) + 3)
        if r0 >= r1 or c0 >= c1:
            continue
        (x1, y1), (x2, y2), (x3, y3) = mail.xy[a], mail.xy[b], mail.xy[c]
        l1, l2, l3 = coords_barycentriques(X[r0:r1, c0:c1], Y[r0:r1, c0:c1], x1, y1, x2, y2, x3, y3)
        dedans = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
        sub = out[r0:r1, c0:c1]
        m = dedans & np.isnan(sub)
        if m.any():
            sub[m] = (l1 * valeurs[a] + l2 * valeurs[b] + l3 * valeurs[c])[m]
    return out


def masque_proximite(points, bornes, largeur, haut, rayon_km: float = MASQUE_KM) -> np.ndarray:
    """Masque booléen (haut, largeur) : vrai à moins de `rayon_km` d'un point [(lat, lon)…] (disques en pixels)."""
    sud, ouest, nord, est = bornes
    m = np.zeros((haut, largeur), dtype=bool)
    m_par_px_eq = math.radians(est - ouest) * 6378137.0 / largeur       # taille d'un pixel à l'équateur (Mercator)
    for lat, lon in points:
        r = rayon_km * 1000 / (m_par_px_eq * math.cos(math.radians(lat)))
        i, j = indice_pixel(lat, lon, sud, ouest, nord, est, largeur, haut)
        i, j, ri = float(i), float(j), int(math.ceil(r))
        r0, r1 = max(0, int(i) - ri), min(haut, int(i) + ri + 2)
        c0, c1 = max(0, int(j) - ri), min(largeur, int(j) + ri + 2)
        if r0 >= r1 or c0 >= c1:
            continue
        yy, xx = np.ogrid[r0:r1, c0:c1]
        m[r0:r1, c0:c1] |= (yy - i) ** 2 + (xx - j) ** 2 <= r * r
    return m


def hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def ecrire_png_indexe(chemin: Path, indices: np.ndarray, couleurs: list[str]) -> int:
    """Image à palette : indice 0 = transparent, k ≥ 1 = `couleurs[k-1]`."""
    from PIL import Image
    img = Image.fromarray(indices.astype(np.uint8), "P")
    pal = [0, 0, 0]
    for c in couleurs:
        pal += list(hex_rgb(c))
    img.putpalette(pal)
    img.save(chemin, optimize=True, transparency=0)
    return chemin.stat().st_size


def luminance(h: str) -> float:
    """Clarté L* (CIE) d'une couleur sRGB « #rrggbb »."""
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in hex_rgb(h))
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return 116 * (y ** (1 / 3) if y > 0.008856 else 7.787 * y + 16 / 116) - 16


def png_pga(mail: Maillage, structures, chemin: Path, largeur: int = LARGEUR_PGA) -> dict:
    """Raster du PGA, classe de site C, 2 % en 50 ans, par classes discrètes, masqué à 50 km des structures."""
    pts = [(s[1], s[2]) for s in structures]
    lats_s, lons_s = [p[0] for p in pts], [p[1] for p in pts]
    marge = MASQUE_KM / 111.0 + 0.1
    sud, nord = math.floor((min(lats_s) - marge) * 10) / 10, math.ceil((max(lats_s) + marge) * 10) / 10
    ouest, est = math.floor((min(lons_s) - marge * 1.6) * 10) / 10, math.ceil((max(lons_s) + marge * 1.6) * 10) / 10
    bornes = (sud, ouest, nord, est)
    lats, lons = grille_mercator(sud, ouest, nord, est, largeur)
    champ = rasteriser(mail, mail.vals[CLASSES.index("C"), :, 0, MESURES.index("pga")], lats, lons, bornes)
    ok = ~np.isnan(champ) & masque_proximite(pts, bornes, len(lons), len(lats))
    idx = np.where(ok, 1 + np.digitize(np.nan_to_num(champ), PGA_BREAKS), 0)
    taille = ecrire_png_indexe(chemin, idx, PGA_COULEURS)
    return {"bounds": [[sud, ouest], [nord, est]], "bytes": taille, "w": len(lons), "h": len(lats),
            "classes": [int((idx == k).sum()) for k in range(1, len(PGA_COULEURS) + 1)]}


def png_classes_mtl(g: dict, chemin: Path, px_par_maille: int = 4) -> dict:
    """Raster des classes de site de Montréal (A..E), sans motifs, rééchantillonné en lignes Web Mercator
    (plus proche voisin : une maille garde sa classe)."""
    sud, ouest = g["north"] - g["ny"] * g["step"], g["west"]
    nord, est = g["north"], g["west"] + g["nx"] * g["step"]
    lats, lons = grille_mercator(sud, ouest, nord, est, g["nx"] * px_par_maille)
    j = np.floor((g["north"] - lats) / g["step"]).astype(int).clip(0, g["ny"] - 1)
    i = np.floor((lons - g["west"]) / g["step"]).astype(int).clip(0, g["nx"] - 1)
    cles = np.array([[ "0ABCDE".index(ch) for ch in row] for row in g["rows"]], dtype=np.uint8)
    idx = cles[j[:, None], i[None, :]]
    taille = ecrire_png_indexe(chemin, idx, [c[2] for c in CLASSES_MTL])
    return {"bounds": [[sud, ouest], [nord, est]], "bytes": taille, "w": len(lons), "h": len(lats)}


def couche(pga: dict, mtl: dict, today: str | None = None) -> dict:
    """Contenu de `window.PQ_COUCHES.sismique`."""
    return {
        "generated": today or date.today().isoformat(),
        "pga": {
            "img": f"data/sismique/{PNG_PGA}", "bounds": pga["bounds"], "breaks": PGA_BREAKS, "colors": PGA_COULEURS,
            "unite": "g",
            "titre": "PGA (g), classe de site C, probabilité de dépassement de 2 % en 50 ans",
            "source": "Aléa moyen CanSHM6 du CNBC 2020 (repris par le CNBC 2025) : " + TITRE_SOURCE,
            "licence": LICENCE, "doi": DOI,
            "avertissement": "Valeurs de l'outil du CNBC, interpolées dans le réseau officiel ; pas des valeurs de calcul "
                             "d'un pont (la norme CSA S6 fait foi). Couche limitée à 50 km des structures du MTMD.",
        },
        "mtl": {
            "img": f"data/sismique/{PNG_MTL}", "bounds": mtl["bounds"],
            "classes": [{"k": k, "label": lab, "color": col} for k, lab, col in CLASSES_MTL],
            "titre": "Classes de site estimées, région de Montréal",
            "source": SOURCE_MTL, "licence": "CC BY 4.0", "doi": "10.3390/geosciences13090256",
            "avertissement": "Estimation par interpolation (maille ≈ 310 × 445 m, ± 100 m) ; ne remplace pas une mesure "
                             "de Vs30 au site.",
        },
    }


# --- Validation contre l'API de RNCan ------------------------------------------------------------
def points_validation(dossier: Path) -> list[dict]:
    """Points de référence des réponses de l'API gardées dans `dossier` (prototypes/sismique/cache) :
    [{num, lat, lon, classes: {A: [lignes de l'API…]}}] pour les 11 exemples et les 35 ouvrages de Montréal."""
    pts = []
    ex = json.loads((dossier / "exemples.json").read_text(encoding="utf-8"))
    for num, e in ex.items():
        pts.append({"num": num, "lat": e["ouvrage"]["lat"], "lon": e["ouvrage"]["lon"], "classes": e["classes"]})
    for m in json.loads((dossier / "montreal_complet.json").read_text(encoding="utf-8")):
        if m.get("classes"):
            pts.append({"num": m["num"], "lat": m["lat"], "lon": m["lon"], "classes": m["classes"]})
    return pts


def comparer_api(mail: Maillage, points: list[dict], mesures=("pga", "sa0p2", "sa1p0")) -> dict:
    """Compare l'interpolation aux valeurs de l'API (3 chiffres significatifs) pour les probabilités 2, 5 et 10 %.
    Renvoie {mesure: {max, moy, n}} d'erreurs relatives, plus {'hors_reseau': n}."""
    xs, ys = lcc([p["lat"] for p in points], [p["lon"] for p in points])
    err = {m: [] for m in mesures}
    hors = 0
    for p, x, y in zip(points, xs, ys):
        r = mail.localiser(float(x), float(y))
        if r is None:
            hors += 1
            continue
        v = mail.interpoler([r[0]], [r[1]])[0]                    # (5, 3, 11)
        for ci, c in enumerate(CLASSES):
            for lig in p["classes"][c]:
                if lig["poe50"] not in POES:
                    continue
                pi = POES.index(lig["poe50"])
                for m in mesures:
                    ref = lig[m]
                    err[m].append(abs(v[ci, pi, MESURES.index(m)] - ref) / ref)
    res = {m: {"max": max(e), "moy": sum(e) / len(e), "n": len(e)} for m, e in err.items() if e}
    res["hors_reseau"] = hors
    return res


def exporter_fixture_validation(mail: Maillage, points: list[dict], chemin: Path) -> int:
    """Fixture autonome des tests : pour chaque point de référence, les 3 sommets du triangle (x, y, valeurs
    2/5/10 % des 5 classes pour pga, sa0p2, sa1p0) et les valeurs de l'API."""
    mes = ("pga", "sa0p2", "sa1p0")
    xs, ys = lcc([p["lat"] for p in points], [p["lon"] for p in points])
    out = []
    for p, x, y in zip(points, xs, ys):
        r = mail.localiser(float(x), float(y))
        if r is None:
            continue
        sommets = [{"x": float(mail.xy[n][0]), "y": float(mail.xy[n][1]),
                    "v": [[[float(mail.vals[c, n, pi, MESURES.index(m)]) for m in mes] for pi in range(3)]
                          for c in range(5)]} for n in mail.tri[r[0]]]
        api = [[[next(l[m] for l in p["classes"][c] if l["poe50"] == poe) for m in mes] for poe in POES]
               for c in CLASSES]
        out.append({"num": p["num"], "lat": p["lat"], "lon": p["lon"], "sommets": sommets, "api": api})
    chemin.write_text(json.dumps({"mesures": list(mes), "poes": [int(p) for p in POES], "points": out},
                                 separators=(",", ":")), encoding="utf-8")
    return len(out)


# --- Exécution -----------------------------------------------------------------------------------
def run(fetch: bool = True, raw_dir: Path = RAW_SISMIQUE) -> list[dict]:
    if fetch:
        telecharger(raw_dir)
    mail = charger_maillage(raw_dir)
    log.info("sismique : %d nœuds, %d triangles (Québec + marge)", len(mail.xy), len(mail.tri))
    structures = charger_structures()
    grille_mtl = charger_grille_mtl()
    donnees, manquants = calculer(mail, structures, grille_mtl)
    if manquants:
        log.warning("sismique : %d structures hors du réseau de l'aléa : %s", len(manquants), ", ".join(manquants[:10]))
    sh = ecrire_shards(donnees)
    pga = png_pga(mail, structures, OUT_DIR / PNG_PGA)
    mtl = png_classes_mtl(grille_mtl, OUT_DIR / PNG_MTL)
    size = ecrire_js(OUT_COUCHE, "(window.PQ_COUCHES=window.PQ_COUCHES||{}).sismique", couche(pga, mtl))
    t = sh["tailles"]
    return [
        {"path": OUT_DIR, "rows": len(donnees), "bytes": sh["bytes"], "manquants": len(manquants),
         "max_shard": max(t.values()), "min_shard": min(t.values()), "shards": len(t)},
        {"path": OUT_DIR / PNG_PGA, "bytes": pga["bytes"], "w": pga["w"], "h": pga["h"]},
        {"path": OUT_DIR / PNG_MTL, "bytes": mtl["bytes"], "w": mtl["w"], "h": mtl["h"]},
        {"path": OUT_COUCHE, "bytes": size},
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-fetch", action="store_true", help="relit data/raw/sismique/ au lieu de télécharger")
    ap.add_argument("--valider", metavar="DOSSIER", nargs="?", const="prototypes/sismique/cache",
                    help="compare à l'API de RNCan (réponses gardées dans DOSSIER) au lieu d'écrire les fichiers")
    ap.add_argument("--fixture", metavar="FICHIER",
                    help="écrit la fixture de validation autonome des tests (avec --valider)")
    args = ap.parse_args(argv)
    for flux in (sys.stdout, sys.stderr):        # console Windows redirigée (cp1252) : accents, « × »
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    if args.valider:
        if not args.no_fetch:
            telecharger()
        mail = charger_maillage()
        pts = points_validation(Path(args.valider))
        res = comparer_api(mail, pts, MESURES)
        print(f"{len(pts)} points de l'API ; hors réseau : {res.pop('hors_reseau')}")
        for m, r in res.items():
            print(f"  {m:7s} erreur relative max {r['max'] * 100:5.2f} %  moyenne {r['moy'] * 100:5.2f} %  (n = {r['n']})")
        if args.fixture:
            print(exporter_fixture_validation(mail, pts, Path(args.fixture)), "points écrits dans", args.fixture)
        return 0
    for res in run(fetch=not args.no_fetch):
        print(f"{res['path']} : {res['bytes'] / 1e6:.2f} Mo" + (f", {res['rows']} structures, {res['shards']} fichiers "
              f"({res['min_shard'] / 1e3:.0f} à {res['max_shard'] / 1e3:.0f} Ko), {res['manquants']} hors réseau"
              if "rows" in res else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
