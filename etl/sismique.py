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

Classes de site du Québec : Rosset P., Elrawy A., Nadarajah S., Chouinard L. (2025), « Vs30 Derived from Geology: An
Attempt in the Province of Quebec, Canada », Geotechnics 5(2):24, doi:10.3390/geotechnics5020024, CC BY 4.0. L'article
ne publie pas de grille (« données incluses dans l'article ») ; on refait sa méthode : son tableau 3 (Vs30 moyen pondéré
→ classe du CNBC par code de dépôt) appliqué à son intrant, la carte des dépôts de surface du SIGEOM (MRNF, CC BY 4.0),
couche « Zones morpho-sédimentologiques générales » (champ CODE_DEPOT ; Q de l'article = Qa du SIGEOM). Les codes absents
du tableau (Qf, Ce, Gxi, H, Ac) restent inconnus. La couche est lue par le WMS du MRNF en tuiles PNG non lissées (une
couleur officielle par code, toutes distinctes), sur une grille lat/lon de 0,002° × 0,003° (≈ 220 m) :
`etl/donnees/classes_site_qc.{png,json}` (codes de dépôt, versionnés ; les tuiles brutes vont dans data/raw/sismique/sigeom/).

Sorties (chargées à la demande par `js/sismique.js` et par la carte, via `<script src>`) :
  - `data/sismique/s-<clé>.js`  : `(window.PQ_SISMIQUE = window.PQ_SISMIQUE || {})['<clé>'] = {"_": {...}, "<n°>": [...]};`
    une entrée par structure : `[k, q0, q1, …, q164]` où `k` = classe de site estimée (0 inconnue, 1..5 = A..E, grille
    du Québec ci-dessus) et `q` = 165 entiers, rangés classe (A..E) → probabilité (2, 5, 10 %) → mesure
    (`MESURES`, 11 valeurs). Index : `((classe × 3 + proba) × 11 + mesure)`.
    Échelle LOGARITHMIQUE : `q = round(1000 × log10(v / 1e-4))`, donc `v = 1e-4 × 10^(q/1000)` (g ; PGV en m/s) ;
    pas de 0,23 % (au moins 3 chiffres significatifs pour toute valeur ≥ 0,001), `q = 0` ↔ v ≤ 0,0001.
  - `data/sismique/meta.js`      : `window.PQ_SISMIQUE_META = {...}` (source, DOI, licence, date, échelle, colonnes) ;
  - `data/couche-sismique.js`    : `(window.PQ_COUCHES = …).sismique = {pga: {...}, classes: {...}}` ;
  - `data/classes-site.js`       : `window.PQ_CLASSE_SITE = {"_": {source, url, generated}, "<n°>": "B", …}` (structures
    situées dans une cellule classée) ;
  - `data/sismique/pga-c-2pc.png` (tout le Québec) et `data/sismique/classes-qc.png` : rasters rééchantillonnés en lignes
    Web Mercator (EPSG:3857), comme `L.imageOverlay` les étire.
(v0.6.0 : la grille des classes de Montréal, Rosset et al. 2023, est retirée : la carte du Québec la couvre.)

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

RAW_SISMIQUE = RAW_DIR / "sismique"

# Dépôts de surface du Québec, intrant de Rosset et al. 2025 : SIGEOM (MRNF), Géologie du Quaternaire, couche « Zones
# morpho-sédimentologiques générales » (CC BY 4.0). Le ZIP officiel (1,5 Go) n'est servi qu'à ≈ 20 Ko/s : la couche
# est lue par le WMS du MRNF, en tuiles PNG rendues SANS lissage au style officiel (une couleur de remplissage par code).
URL_WMS_SIGEOM = "https://servicesvectoriels.atlas.gouv.qc.ca/IDS_SGM_WMS/service.svc/get"
COUCHE_WMS_SIGEOM = "SGM:Zones_morpho_sedimentologiques_qc"
RAW_SIGEOM = RAW_SISMIQUE / "sigeom"
TUILE = 2048                                # pixels par côté de tuile WMS
# Couleur de remplissage officielle (attribut COUL_REMPL_HEXA du WFS, relevé le 2026-10-15) : toutes distinctes.
COULEURS_SIGEOM = {
    "R": "#ff0000", "T": "#26ff26", "O": "#cccccc", "L": "#e680cc", "Gx": "#ff8026", "Tf": "#26b266",
    "Go": "#ffcc26", "MGb": "#b2e6ff", "LGb": "#ccb2ff", "MGa": "#66e6ff", "A": "#ffff00", "Qf": "#b24c00",
    "Qa": "#b28066", "LGa": "#cc99ff", "MGd": "#9999ff", "C": "#e6e6b2", "Ed": "#e6ccb2", "LGd": "#994ce6",
    "GxT": "#ff6600", "Ce": "#e6cc00", "Gs": "#ffcc80", "Ap": "#ffffb2", "Gxi": "#e69926", "Cg": "#e6e626",
    "H": "#be8c8c", "Ac": "#e6ff00",
}
CODES_SIGEOM = tuple(COULEURS_SIGEOM)
OUT_DIR = DATA_DIR / "sismique"
OUT_COUCHE = DATA_DIR / "couche-sismique.js"
DONNEES = Path(__file__).resolve().parent / "donnees"
PNG_PGA = "pga-c-2pc.png"
PNG_QC = "classes-qc.png"
OUT_CLASSES = DATA_DIR / "classes-site.js"

# Classes de site du Québec : Rosset P., Elrawy A., Nadarajah S., Chouinard L. (2025), Geotechnics 5(2):24, CC BY 4.0.
URL_ARTICLE = "https://www.mdpi.com/2673-7094/5/2/24"
DOI_ARTICLE = "10.3390/geotechnics5020024"
SOURCE_QC_COURTE = "Rosset et al. (2025), Geotechnics 5(2):24"
SOURCE_QC = ("Rosset P., Elrawy A., Nadarajah S., Chouinard L. (2025), Vs30 Derived from Geology: An Attempt in the "
             "Province of Quebec, Canada, Geotechnics 5(2):24, doi:10.3390/geotechnics5020024, CC BY 4.0 — tableau 3 "
             "appliqué à la carte des dépôts de surface du SIGEOM (MRNF, CC BY 4.0)")
# Tableau 3 de l'article : code de dépôt du SIGEOM → (description, Vs30 moyen pondéré (m/s), classe de site du CNBC).
# Les codes absents du tableau (Qa, Qf, Ce, Gxi, H, Ac, …) restent « inconnus », comme la catégorie grise de la figure 10.
TABLEAU3 = {
    "Ed": ("Sédiments éoliens", 604, "C"),
    "O": ("Sédiments organiques indifférenciés", 659, "C"),
    "C": ("Dépôts de pente indifférenciés", 525, "C"),
    "Cg": ("Dépôts de glissement de terrain", 260, "D"),
    "A": ("Alluvions indifférenciées", 537, "C"),
    "Ap": ("Alluvions actuelles", 813, "B"),
    "L": ("Sédiments lacustres", 1212, "B"),
    "MGa": ("Sédiments glaciomarins d'eau profonde, fins", 615, "C"),
    "MGb": ("Sédiments glaciomarins littoraux et prélittoraux", 826, "B"),
    "MGd": ("Sédiments glaciomarins deltaïques et prodeltaïques", 531, "C"),
    "LGa": ("Sédiments glaciolacustres d'eau profonde, fins", 1026, "B"),
    "LGb": ("Sédiments glaciolacustres littoraux et prélittoraux", 556, "C"),
    "LGd": ("Sédiments glaciolacustres deltaïques et prodeltaïques", 535, "C"),
    "Go": ("Sédiments proglaciaires d'épandage subaérien", 1063, "B"),
    "Gs": ("Sédiments proglaciaires d'épandage subaquatique", 1017, "B"),
    "Gx": ("Sédiments juxtaglaciaires", 942, "B"),
    "GxT": ("Sédiments de moraine frontale", 832, "B"),
    "T": ("Till indifférencié", 1185, "B"),
    "Tf": ("Till de fusion ou d'ablation", 1097, "B"),
    "Q": ("Formation quaternaire ancienne altérée", 1416, "B"),
    "R": ("Substratum rocheux indifférencié", 1657, "A"),
}
# Couleurs de la figure 10 de l'article (pastilles de la légende, médiane des pixels) ; E n'y figure pas.
CLASSES_QC = [
    ("A", "A — roc dur (Vs30 > 1500 m/s)", "#36bf29"),
    ("B", "B — roc (Vs30 760 à 1500 m/s)", "#2306ff"),
    ("C", "C — sol très dense et roc mou (Vs30 360 à 760 m/s)", "#e4ff04"),
    ("D", "D — sol raide (Vs30 180 à 360 m/s)", "#cf15d8"),
]
# Grille versionnée (lat/lon, maille ≈ 330 m) : etl/donnees/classes_site_qc.{json,png}
GRILLE_QC_JSON = "classes_site_qc.json"
GRILLE_QC_PNG = "classes_site_qc.png"
NON_CLASSE = 6                              # valeur de classe : dépôt cartographié mais absent du tableau 3
EAU = 7                                     # valeur de classe : plan d'eau (transparent, sans classe)
# « L » (sédiment lacustre actuel) couvre, dans la carte GÉNÉRALE, les lacs eux-mêmes : la figure 10 de l'article les
# recouvre de bleu (sur 3,5 millions de pixels classés de la figure, 42 seulement tombent sur un L). On suit la figure.
CODES_EAU = ("L",)
ALIAS_TABLEAU3 = {"Qa": "Q"}                # « Formation quaternaire ancienne altérée » : Q dans l'article, Qa au SIGEOM
# Grille lat/lon du Québec (45 à 62,6 °N, 79,8 à 57,1 °O), maille de 0,002° × 0,003° (≈ 222 × 214 m à 50 °N)
BORNES_QC = (44.9, -79.8, 62.7, -57.0)      # (sud, ouest, nord, est)
PAS_QC = (0.002, 0.003)                     # (dlat, dlon) en degrés
LARGEUR_QC = 3200                           # largeur (px) du raster Web Mercator de la carte

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
MASQUE_KM = 50                              # repli du PGA sans grille du Québec : voisinage des structures (km)

# Projection du fichier (x, y) : conique conforme de Lambert, parallèles 49 et 77, méridien -95, GRS80.
# L'ordonnée du fichier est décalée d'une constante (1 137 169,78 m), ajustée sur les 34 733 nœuds (écart < 0,1 m).
LCC_A, LCC_F = 6378137.0, 1 / 298.257222101
LCC_P1, LCC_P2, LCC_LAT0, LCC_LON0 = 49.0, 77.0, 49.0, -95.0
LCC_FN = 1137169.78

# Palette séquentielle (magma) à clarté L* strictement décroissante du plus faible au plus fort : sûre en daltonisme.
PGA_BREAKS = [0.05, 0.10, 0.20, 0.30, 0.45, 0.70, 1.00]
PGA_COULEURS = ["#fcfdbf", "#fed395", "#fd9f6c", "#f4685c", "#d3436e", "#a3307e", "#6f1f81", "#3b0f70"]
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


# --- Classes de site du Québec (Rosset et al. 2025) ----------------------------------------------
def code_vers_classe(code: str) -> int:
    """Code de dépôt du SIGEOM → classe de site (1..5 = A..E) du tableau 3 de Rosset et al. 2025 ; EAU pour les codes
    qui, dans la carte générale, couvrent les plans d'eau (figure 10 : recouverts de bleu) ; NON_CLASSE si absent."""
    if code in CODES_EAU:
        return EAU
    t = TABLEAU3.get(ALIAS_TABLEAU3.get(code, code))
    return CLASSES.index(t[2]) + 1 if t else NON_CLASSE


def grille_qc_vide(bornes=BORNES_QC, pas=PAS_QC) -> dict:
    """Géométrie de la grille du Québec : {north, west, dlat, dlon, nx, ny} (lignes du nord au sud)."""
    sud, ouest, nord, est = bornes
    dlat, dlon = pas
    return {"north": nord, "west": ouest, "dlat": dlat, "dlon": dlon,
            "nx": int(round((est - ouest) / dlon)), "ny": int(round((nord - sud) / dlat))}


def tuiles(g: dict, taille: int = TUILE):
    """Tuiles WMS alignées sur la grille : [(ligne, colonne, bbox (ouest, sud, est, nord), largeur, hauteur)…]."""
    out = []
    for ti in range(math.ceil(g["ny"] / taille)):
        for tj in range(math.ceil(g["nx"] / taille)):
            h, w = min(taille, g["ny"] - ti * taille), min(taille, g["nx"] - tj * taille)
            nord = g["north"] - ti * taille * g["dlat"]
            ouest = g["west"] + tj * taille * g["dlon"]
            out.append((ti, tj, (round(ouest, 9), round(nord - h * g["dlat"], 9), round(ouest + w * g["dlon"], 9),
                                 round(nord, 9)), w, h))
    return out


def url_tuile(bbox, w: int, h: int) -> str:
    """GetMap WMS 1.1.1 (EPSG:4269, axes lon/lat) au style officiel, SANS lissage : une couleur exacte par code de dépôt."""
    from urllib.parse import urlencode
    return URL_WMS_SIGEOM + "?" + urlencode({
        "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "LAYERS": COUCHE_WMS_SIGEOM, "STYLES": "",
        "SRS": "EPSG:4269", "BBOX": ",".join(f"{v:.9f}" for v in bbox), "WIDTH": str(w), "HEIGHT": str(h),
        "FORMAT": "image/png", "TRANSPARENT": "TRUE", "FORMAT_OPTIONS": "antialias:none"})


def telecharger_tuiles(g: dict | None = None, raw_dir: Path = RAW_SIGEOM, essais: int = 4) -> list[str]:
    """Tuiles PNG de la couche générale du SIGEOM (reprise : les tuiles déjà présentes ne sont pas redemandées)."""
    import time
    g = g or grille_qc_vide()
    (raw_dir / "wms").mkdir(parents=True, exist_ok=True)
    s, faites = net.session(), []
    for ti, tj, bbox, w, h in tuiles(g):
        f = raw_dir / "wms" / f"t-{ti:02d}-{tj:02d}.png"
        if f.exists():
            continue
        for k in range(essais):
            try:
                r = net.get(s, url_tuile(bbox, w, h), timeout=900)
                if not r.headers.get("Content-Type", "").startswith("image/png"):
                    raise RuntimeError(f"réponse inattendue : {r.content[:200]!r}")
                break
            except Exception as e:                         # serveur lent, coupures : on réessaie
                if k == essais - 1:
                    raise
                log.warning("sismique : tuile %s, nouvel essai (%s)", f.name, e)
                time.sleep(10 * (k + 1))
        f.with_name(f.name + ".part").write_bytes(r.content)
        f.with_name(f.name + ".part").replace(f)
        faites.append(f.name)
        log.info("sismique : tuile SIGEOM %s (%d × %d px, %.0f Ko)", f.name, w, h, len(r.content) / 1e3)
    return faites


def decoder_tuile(rgba: np.ndarray, codes=CODES_SIGEOM) -> tuple[np.ndarray, int]:
    """Pixels RGBA d'une tuile → indices de code (0 transparent, k = codes[k-1]) et nombre de pixels de couleur inconnue
    (ils reçoivent l'indice du code le plus proche en couleur ; il n'y en a aucun avec le rendu sans lissage)."""
    pal = np.array([hex_rgb(COULEURS_SIGEOM[c]) for c in codes], dtype=np.int32)
    cle = (rgba[..., 0].astype(np.int32) << 16) | (rgba[..., 1].astype(np.int32) << 8) | rgba[..., 2]
    u, inv = np.unique(cle, return_inverse=True)
    rgb_u = np.stack([u >> 16, (u >> 8) & 255, u & 255], axis=1)
    d = ((rgb_u[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2)
    idx_u = d.argmin(axis=1) + 1
    exact = d.min(axis=1) == 0
    out = idx_u[inv].reshape(cle.shape).astype(np.uint8)
    opaque = rgba[..., 3] > 127
    out[~opaque] = 0
    inconnus = int((opaque & ~exact[inv].reshape(cle.shape)).sum())
    return out, inconnus


def assembler_grille(g: dict | None = None, raw_dir: Path = RAW_SIGEOM) -> dict:
    """Grille des codes de dépôt (uint8, 0 = aucun polygone) à partir des tuiles téléchargées."""
    from PIL import Image
    g = dict(g or grille_qc_vide())
    v = np.zeros((g["ny"], g["nx"]), np.uint8)
    inconnus = 0
    for ti, tj, _, w, h in tuiles(g):
        f = raw_dir / "wms" / f"t-{ti:02d}-{tj:02d}.png"
        if not f.exists():
            raise FileNotFoundError(f"{f} absent : lancer `python -m etl.sismique` sans --no-fetch")
        rgba = np.asarray(Image.open(f).convert("RGBA"))
        if rgba.shape[:2] != (h, w):
            raise ValueError(f"{f.name} : {rgba.shape[1]} × {rgba.shape[0]} px au lieu de {w} × {h}")
        t, n = decoder_tuile(rgba)
        v[ti * TUILE:ti * TUILE + h, tj * TUILE:tj * TUILE + w] = t
        inconnus += n
    g.update({"codes": list(CODES_SIGEOM), "v": v, "inconnus": inconnus})
    return g


def classes_de_grille(g: dict) -> np.ndarray:
    """Tableau (ny, nx) des classes : 0 aucun polygone, 1..5 = A..E, NON_CLASSE = dépôt absent du tableau 3, EAU = lac."""
    lut = np.array([0] + [code_vers_classe(c) for c in g["codes"]], dtype=np.uint8)
    return lut[g["v"]]


def ecrire_grille_qc(g: dict, dossier: Path = DONNEES, today: str | None = None) -> int:
    """Grille versionnée : PNG à palette (indice k = code de dépôt `codes[k-1]`, couleurs officielles du SIGEOM ;
    0 = aucun polygone, transparent) + métadonnées JSON (géométrie, codes, tableau 3, comptes)."""
    from PIL import Image
    img = Image.fromarray(g["v"], "P")
    img.putpalette([255, 255, 255] + [x for c in g["codes"] for x in hex_rgb(COULEURS_SIGEOM[c])])
    img.save(dossier / GRILLE_QC_PNG, optimize=True, transparency=0)
    cl = classes_de_grille(g)
    meta = {k: g[k] for k in ("north", "west", "dlat", "dlon", "nx", "ny")}
    meta.update({
        "generated": today or date.today().isoformat(),
        "codes": g["codes"],
        "valeurs": "indice de pixel du PNG : 0 = aucun polygone (hors Québec, mer) ; k = codes[k-1]",
        "regle": "rendu WMS sans lissage : le pixel prend le code du polygone qui contient son centre",
        "intrant": f"SIGEOM (MRNF), Géologie du Quaternaire, couche {COUCHE_WMS_SIGEOM} (zones morpho-sédimentologiques "
                   f"générales), service {URL_WMS_SIGEOM}, CC BY 4.0",
        "source": SOURCE_QC, "url": URL_ARTICLE, "doi": DOI_ARTICLE,
        "tableau3": {k: {"depot": d, "vs30": vs, "classe": c} for k, (d, vs, c) in TABLEAU3.items()},
        "alias": ALIAS_TABLEAU3,
        "eau": {c: "plan d'eau dans la carte générale : sans classe, transparent (comme la figure 10)" for c in CODES_EAU},
        "comptes_codes": {c: int((g["v"] == k + 1).sum()) for k, c in enumerate(g["codes"])},
        "comptes_classes": {lab: int((cl == k).sum()) for k, lab in enumerate(["aucun"] + list(CLASSES) + ["non classé", "eau"])},
    })
    (dossier / GRILLE_QC_JSON).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return (dossier / GRILLE_QC_PNG).stat().st_size


def charger_grille_qc(dossier: Path = DONNEES) -> dict:
    """Grille versionnée des codes de dépôt du Québec (voir `ecrire_grille_qc`)."""
    from PIL import Image
    g = json.loads((dossier / GRILLE_QC_JSON).read_text(encoding="utf-8"))
    g["v"] = np.asarray(Image.open(dossier / GRILLE_QC_PNG))
    if g["v"].shape != (g["ny"], g["nx"]):
        raise ValueError("grille des classes du Québec : dimensions incohérentes")
    return g


def code_qc(g: dict, lat: float, lon: float) -> str | None:
    """Code de dépôt de la cellule qui contient (lat, lon), None hors grille ou sans polygone."""
    j = math.floor((g["north"] - lat) / g["dlat"])
    i = math.floor((lon - g["west"]) / g["dlon"])
    if 0 <= j < g["ny"] and 0 <= i < g["nx"] and g["v"][j, i]:
        return g["codes"][int(g["v"][j, i]) - 1]
    return None


def classe_qc(g: dict, lat: float, lon: float) -> int:
    """Classe (1..5 = A..E) de la cellule qui contient (lat, lon) ; 0 hors grille, sans polygone ou dépôt non classé."""
    c = code_qc(g, lat, lon)
    k = code_vers_classe(c) if c else 0
    return k if 1 <= k <= 5 else 0


def classes_structures(structures, g: dict) -> dict[str, int]:
    """{n°: classe 1..5} des structures situées dans une cellule classée de la grille du Québec."""
    out = {}
    for num, lat, lon in structures:
        k = classe_qc(g, lat, lon)
        if k:
            out[num] = k
    return out


def ecrire_classes_site(classes: dict[str, int], chemin: Path = OUT_CLASSES, today: str | None = None) -> int:
    """`data/classes-site.js` : window.PQ_CLASSE_SITE = {"_": {source, url, generated}, "<n°>": "B", …}."""
    corps = {"_": {"source": SOURCE_QC, "url": URL_ARTICLE, "generated": today or date.today().isoformat()}}
    corps.update({n: CLASSES[k - 1] for n, k in sorted(classes.items())})
    return ecrire_js(chemin, "window.PQ_CLASSE_SITE", corps)


def png_classes_qc(g: dict, chemin: Path, largeur: int = LARGEUR_QC) -> dict:
    """Raster Web Mercator des classes du Québec (classe MAJORITAIRE des cellules de la grille sous chaque pixel ;
    transparent : aucun polygone, dépôt non classé, lac)."""
    sud, ouest = g["north"] - g["ny"] * g["dlat"], g["west"]
    nord, est = g["north"], g["west"] + g["nx"] * g["dlon"]
    lats, lons = grille_mercator(sud, ouest, nord, est, largeur)
    cl = classes_de_grille(g)
    cl[cl > len(CLASSES_QC)] = 0                        # E (absente de l'article), non classé et eau : transparents
    # bornes des pixels en indices de cellules (le pixel Mercator couvre 1 à 3 cellules par axe)
    ytop, ybot = float(merc_y(nord)), float(merc_y(sud))
    h = len(lats)
    lat_b = lat_depuis_merc(ytop - np.arange(h + 1) / h * (ytop - ybot))
    j_b = np.clip(np.round((g["north"] - lat_b) / g["dlat"]).astype(int), 0, g["ny"])
    i_b = np.clip(np.round(np.arange(largeur + 1) / largeur * g["nx"]).astype(int), 0, g["nx"])
    # votes : somme cumulée 2D par classe, puis classe la plus fréquente (égalité : la plus défavorable)
    votes = np.zeros((len(CLASSES_QC) + 1, h, largeur), np.int32)
    for k in range(1, len(CLASSES_QC) + 1):
        s = np.zeros((g["ny"] + 1, g["nx"] + 1), np.int32)
        s[1:, 1:] = np.cumsum(np.cumsum(cl == k, axis=0, dtype=np.int32), axis=1, dtype=np.int32)
        a, b = j_b[:-1], np.maximum(j_b[1:], j_b[:-1] + 1)
        c, d = i_b[:-1], np.maximum(i_b[1:], i_b[:-1] + 1)
        votes[k] = s[b][:, d] - s[a][:, d] - s[b][:, c] + s[a][:, c]
    s0 = np.zeros((g["ny"] + 1, g["nx"] + 1), np.int32)
    s0[1:, 1:] = np.cumsum(np.cumsum(cl == 0, axis=0, dtype=np.int32), axis=1, dtype=np.int32)
    votes[0] = s0[b][:, d] - s0[a][:, d] - s0[b][:, c] + s0[a][:, c]
    rang = votes * 8 + np.arange(len(CLASSES_QC) + 1)[:, None, None]       # égalité → indice le plus haut
    idx = rang.argmax(axis=0).astype(np.uint8)
    taille = ecrire_png_indexe(chemin, idx, [c[2] for c in CLASSES_QC])
    return {"bounds": [[round(sud, 6), round(ouest, 6)], [round(nord, 6), round(est, 6)]], "bytes": taille,
            "w": largeur, "h": h, "classes": [int((idx == k).sum()) for k in range(1, len(CLASSES_QC) + 1)]}


def masque_quebec(g: dict, lats, lons, marge_px: int = 2) -> np.ndarray:
    """Masque (h, w) du territoire québécois sur une grille de pixels : présence d'au moins une cellule cartographiée
    par le SIGEOM sous le pixel, trous intérieurs (lacs) bouchés, puis dilatation de `marge_px` pixels."""
    from scipy import ndimage
    lats, lons = np.asarray(lats), np.asarray(lons)
    k = max(1, int(round(abs(lons[1] - lons[0]) / g["dlon"])))
    couvert = g["v"] > 0
    if k > 1:
        couvert = ndimage.maximum_filter(couvert, size=k)
    j = np.floor((g["north"] - lats) / g["dlat"]).astype(int)
    i = np.floor((lons - g["west"]) / g["dlon"]).astype(int)
    jok, iok = (j >= 0) & (j < g["ny"]), (i >= 0) & (i < g["nx"])
    m = np.zeros((len(lats), len(lons)), bool)
    m[np.ix_(jok, iok)] = couvert[np.ix_(j[jok], i[iok])]
    m = ndimage.binary_fill_holes(m)
    return ndimage.binary_dilation(m, iterations=marge_px) if marge_px else m


# --- Structures ----------------------------------------------------------------------------------
def charger_structures(db_path=DB_PATH) -> list[tuple[str, float, float]]:
    """Structures géolocalisées de l'inventaire : [(num_dossr, lat, lon)…] triées par n°."""
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        return conn.execute("SELECT num_dossr, lat, lon FROM structure WHERE lat IS NOT NULL AND lon IS NOT NULL "
                            "ORDER BY num_dossr").fetchall()
    finally:
        conn.close()


def calculer(mail: Maillage, structures, classes: dict[str, int] | None = None):
    """Structures [(num, lat, lon)…] → ({num: [k, q…165]}, [nums hors réseau]) ; k = classe de site estimée
    (`classes[num]`, 1..5 = A..E, 0 inconnue)."""
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
            out[s[0]] = [(classes or {}).get(s[0], 0)] + [int(v) for v in ligne]
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
        "classeSite": {"0": None, "1..5": "A..E", "source": SOURCE_QC, "url": URL_ARTICLE},
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


def png_pga(mail: Maillage, structures, chemin: Path, largeur: int = LARGEUR_PGA, grille_qc: dict | None = None) -> dict:
    """Raster du PGA, classe de site C, 2 % en 50 ans, par classes discrètes.
    Avec `grille_qc` : tout le territoire québécois (couverture de la carte du SIGEOM, lacs compris) ; sinon, ancien
    comportement : voisinage de 50 km des structures."""
    if grille_qc is not None:
        g = grille_qc
        sud = math.floor((g["north"] - g["ny"] * g["dlat"]) * 10) / 10
        nord, ouest = math.ceil(g["north"] * 10) / 10, math.floor(g["west"] * 10) / 10
        est = math.ceil((g["west"] + g["nx"] * g["dlon"]) * 10) / 10
    else:
        lats_s, lons_s = [s[1] for s in structures], [s[2] for s in structures]
        marge = MASQUE_KM / 111.0 + 0.1
        sud, nord = math.floor((min(lats_s) - marge) * 10) / 10, math.ceil((max(lats_s) + marge) * 10) / 10
        ouest, est = math.floor((min(lons_s) - marge * 1.6) * 10) / 10, math.ceil((max(lons_s) + marge * 1.6) * 10) / 10
    bornes = (sud, ouest, nord, est)
    lats, lons = grille_mercator(sud, ouest, nord, est, largeur)
    champ = rasteriser(mail, mail.vals[CLASSES.index("C"), :, 0, MESURES.index("pga")], lats, lons, bornes)
    if grille_qc is not None:
        zone = masque_quebec(grille_qc, lats, lons)
    else:
        zone = masque_proximite([(s[1], s[2]) for s in structures], bornes, len(lons), len(lats))
    ok = ~np.isnan(champ) & zone
    idx = np.where(ok, 1 + np.digitize(np.nan_to_num(champ), PGA_BREAKS), 0)
    taille = ecrire_png_indexe(chemin, idx, PGA_COULEURS)
    return {"bounds": [[sud, ouest], [nord, est]], "bytes": taille, "w": len(lons), "h": len(lats),
            "classes": [int((idx == k).sum()) for k in range(1, len(PGA_COULEURS) + 1)],
            "province": grille_qc is not None}


def couche(pga: dict, qc: dict | None, today: str | None = None) -> dict:
    """Contenu de `window.PQ_COUCHES.sismique` : `pga` (toute la province) et `classes` (Québec, Rosset et al. 2025)."""
    zone = ("Couche étendue à tout le territoire québécois couvert par la carte des dépôts du SIGEOM (lacs compris)."
            if pga.get("province", True) else "Couche limitée à 50 km des structures du MTMD.")
    out = {
        "generated": today or date.today().isoformat(),
        "pga": {
            "img": f"data/sismique/{PNG_PGA}", "bounds": pga["bounds"], "breaks": PGA_BREAKS, "colors": PGA_COULEURS,
            "unite": "g",
            "titre": "PGA (g), classe de site C, probabilité de dépassement de 2 % en 50 ans",
            "source": "Aléa moyen CanSHM6 du CNBC 2020 (repris par le CNBC 2025) : " + TITRE_SOURCE,
            "licence": LICENCE, "doi": DOI,
            "avertissement": "Valeurs de l'outil du CNBC, interpolées dans le réseau officiel ; pas des valeurs de calcul "
                             "d'un pont (la norme CSA S6 fait foi). " + zone,
        },
    }
    if qc is not None:
        out["classes"] = {
            "img": f"data/sismique/{PNG_QC}", "bounds": qc["bounds"],
            "classes": [{"k": k, "label": lab, "color": col} for k, lab, col in CLASSES_QC],
            "titre": "Classes de site sismique estimées (Vs30) d'après la géologie de surface, Québec",
            "source": SOURCE_QC_COURTE, "url": URL_ARTICLE, "doi": DOI_ARTICLE, "licence": "CC BY 4.0",
            "avertissement": "Estimation à l'échelle régionale : chaque type de dépôt de surface de la carte générale du "
                             "SIGEOM reçoit la classe de son Vs30 moyen (tableau 3 de l'article, écart type de 130 à "
                             "970 m/s, soit souvent ± 1 classe). Ce n'est pas une étude de site : une mesure de Vs30 ou un "
                             "forage fait foi. Transparent : eau, dépôts non classés par l'article, hors carte.",
        }
    return out


# --- Validation contre la figure 10 de l'article -------------------------------------------------
# Figure 10 (p. 13 du PDF) : 45 à 49,6 °N, 76,6 à 69,9 °O, en plate carrée ; graduations tous les 1° marquées par
# l'alternance noir / blanc des barres du cadre. Couleurs : légende de la figure, eau = bleu clair.
FIG10_COULEURS = {1: "#36bf29", 2: "#2306ff", 3: "#e4ff04", 4: "#cf15d8", 7: "#c0d4ec"}     # 7 = eau


def image_figure10(pdf: Path) -> np.ndarray:
    """Image RGB de la figure 10 (deux images jointes verticalement dans le PDF de l'article)."""
    import fitz                                    # PyMuPDF, seulement pour cette validation
    d = fitz.open(pdf)
    parts = []
    for info in sorted(d[12].get_image_info(xrefs=True), key=lambda i: i["bbox"][1]):
        pix = fitz.Pixmap(d, info["xref"])
        parts.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3])
    return np.vstack(parts)


def _transitions(p, off: int) -> list[float]:
    """Abscisses (sous-pixel) où un profil de gris franchit 128."""
    return [off + i + (128 - p[i]) / (p[i + 1] - p[i]) + 0.5 for i in range(len(p) - 1) if (p[i] - 128) * (p[i + 1] - 128) < 0]


def georef_figure10(img: np.ndarray) -> dict:
    """Graduations des 4 barres du cadre → x = a + b·lon, y = c + d·lat, ajustés par moindres carrés avec un terme ±e
    qui absorbe l'épaisseur du trait (les segments noirs paraissent plus larges que les blancs). Renvoie aussi les résidus."""
    gris = img.astype(float).mean(axis=2)
    moy = lambda profils: np.mean([p for p in profils if len(p) == len(profils[len(profils) // 2])], axis=0)
    haut = moy([_transitions(gris[r, 300:3360], 300) for r in range(88, 103)])
    bas = moy([_transitions(gris[r, 300:3360], 300) for r in range(2347, 2362)])
    gauche = moy([_transitions(gris[200:2330, c], 200) for c in range(138, 152)])
    droite = moy([_transitions(gris[200:2330, c], 200) for c in range(3393, 3408)])
    out = {}
    for nom, pos, deg in (("x", np.concatenate([haut, bas]), np.tile(np.arange(-76, -69), 2)),
                          ("y", np.concatenate([gauche, droite]), np.tile(np.arange(49, 44, -1), 2))):
        alt = np.array([1.0 if (k % (len(pos) // 2)) % 2 == 0 else -1.0 for k in range(len(pos))])
        A = np.column_stack([np.ones(len(pos)), deg, alt])
        coef, *_ = np.linalg.lstsq(A, pos, rcond=None)
        res = pos - A @ coef
        out[nom] = {"a": float(coef[0]), "b": float(coef[1]), "trait": float(coef[2]),
                    "residus_px": [round(float(r), 3) for r in res], "rms_px": float(np.sqrt((res ** 2).mean())),
                    "n": int(len(pos))}
    return out


def classer_figure10(img: np.ndarray, tol: float = 60.0) -> np.ndarray:
    """Pixels → 1..4 (A..D), 7 (eau) ou 0 (autre : blanc, gris « inconnu », traits, texte) par couleur la plus proche."""
    pal = np.array([hex_rgb(c) for c in FIG10_COULEURS.values()], np.int32)
    cles = np.array(list(FIG10_COULEURS), np.uint8)
    out = np.zeros(img.shape[:2], np.uint8)
    for r in range(0, img.shape[0], 256):                       # par bandes : mémoire bornée
        d = ((img[r:r + 256, :, None, :].astype(np.int32) - pal[None, None]) ** 2).sum(axis=3)
        out[r:r + 256] = np.where(d.min(axis=2) < tol ** 2, cles[d.argmin(axis=2)], 0)
    return out


def comparer_figure10(g: dict, pdf: Path, decalages=range(-3, 4)) -> dict:
    """Accord entre la figure 10 (pixels A..D hors légende) et la grille reconstituée, au géoréférencement ajusté puis
    décalé de quelques pixels (le maximum doit tomber à 0 si le géoréférencement est juste)."""
    img = image_figure10(pdf)
    geo = georef_figure10(img)
    fig = classer_figure10(img)
    gx, gy = geo["x"], geo["y"]
    # zone utile : intérieur du cadre, hors légende (coin nord-ouest), échelle (sud-ouest) et flèche du nord
    m = np.zeros(fig.shape, bool)
    m[115:2330, 160:3380] = True
    m[115:720, 160:720] = False                                                  # légende
    m[2140:2330, 160:700] = False                                                # échelle graphique
    m[115:330, 3150:3380] = False                                                # flèche du nord
    cl = classes_de_grille(g)
    yy, xx = np.nonzero(m & (fig >= 1) & (fig <= 4))
    res = {"georef": geo, "decalages": {}}
    for dx in decalages:
        lon = (xx + 0.5 + dx - gx["a"]) / gx["b"]
        lat = (yy + 0.5 - gy["a"]) / gy["b"]
        j = np.floor((g["north"] - lat) / g["dlat"]).astype(int).clip(0, g["ny"] - 1)
        i = np.floor((lon - g["west"]) / g["dlon"]).astype(int).clip(0, g["nx"] - 1)
        notre = cl[j, i]
        f = fig[yy, xx]
        res["decalages"][dx] = float((notre == f).mean())
        if dx == 0:
            mat = np.zeros((5, 8), int)                    # lignes : figure A..D (1..4) ; colonnes : nous 0..7
            np.add.at(mat, (f, notre), 1)
            res["matrice"] = mat[1:].tolist()
            res["n"] = int(len(f))
            res["accord"] = float((notre == f).mean())
            v = g["v"][j, i]
            res["par_code"] = {c: {lab: int(((v == k + 1) & (f == q)).sum()) for q, lab in zip(range(1, 5), "ABCD")}
                               for k, c in enumerate(g["codes"]) if (v == k + 1).any()}
    # eau de la figure : codes du SIGEOM dessous
    yy, xx = np.nonzero(m & (fig == 7))
    lon, lat = (xx + 0.5 - gx["a"]) / gx["b"], (yy + 0.5 - gy["a"]) / gy["b"]
    j = np.floor((g["north"] - lat) / g["dlat"]).astype(int).clip(0, g["ny"] - 1)
    i = np.floor((lon - g["west"]) / g["dlon"]).astype(int).clip(0, g["nx"] - 1)
    v = g["v"][j, i]
    res["eau"] = {("aucun" if k == 0 else g["codes"][k - 1]): int((v == k).sum()) for k in np.unique(v)}
    return res


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
        telecharger_tuiles()
    mail = charger_maillage(raw_dir)
    log.info("sismique : %d nœuds, %d triangles (Québec + marge)", len(mail.xy), len(mail.tri))
    structures = charger_structures()
    # grille du Québec : reconstruite des tuiles WMS si elles sont là, sinon relue dans etl/donnees (versionnée)
    try:
        g = assembler_grille()
        if g["inconnus"]:
            log.warning("sismique : %d pixels de couleur inconnue dans les tuiles du SIGEOM", g["inconnus"])
        t_grille = ecrire_grille_qc(g)
        log.info("sismique : grille des dépôts du Québec écrite (%.1f Mo)", t_grille / 1e6)
    except FileNotFoundError as e:
        log.info("sismique : %s ; grille versionnée relue", e)
        g = charger_grille_qc()
    classes = classes_structures(structures, g)
    t_classes = ecrire_classes_site(classes)
    donnees, manquants = calculer(mail, structures, classes)
    if manquants:
        log.warning("sismique : %d structures hors du réseau de l'aléa : %s", len(manquants), ", ".join(manquants[:10]))
    sh = ecrire_shards(donnees)
    pga = png_pga(mail, structures, OUT_DIR / PNG_PGA, grille_qc=g)
    qc = png_classes_qc(g, OUT_DIR / PNG_QC)
    vieux = OUT_DIR / "classes-mtl.png"                 # ancienne couche de Montréal (v0.5.6), remplacée
    if vieux.exists():
        vieux.unlink()
    size = ecrire_js(OUT_COUCHE, "(window.PQ_COUCHES=window.PQ_COUCHES||{}).sismique", couche(pga, qc))
    t = sh["tailles"]
    return [
        {"path": OUT_DIR, "rows": len(donnees), "bytes": sh["bytes"], "manquants": len(manquants),
         "max_shard": max(t.values()), "min_shard": min(t.values()), "shards": len(t)},
        {"path": OUT_DIR / PNG_PGA, "bytes": pga["bytes"], "w": pga["w"], "h": pga["h"]},
        {"path": OUT_DIR / PNG_QC, "bytes": qc["bytes"], "w": qc["w"], "h": qc["h"]},
        {"path": OUT_CLASSES, "bytes": t_classes, "classees": len(classes),
         "par_classe": {c: sum(1 for k in classes.values() if k == i + 1) for i, c in enumerate(CLASSES)}},
        {"path": OUT_COUCHE, "bytes": size},
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-fetch", action="store_true", help="relit data/raw/sismique/ au lieu de télécharger")
    ap.add_argument("--valider", metavar="DOSSIER", nargs="?", const="prototypes/sismique/cache",
                    help="compare à l'API de RNCan (réponses gardées dans DOSSIER) au lieu d'écrire les fichiers")
    ap.add_argument("--fixture", metavar="FICHIER",
                    help="écrit la fixture de validation autonome des tests (avec --valider)")
    ap.add_argument("--figure", metavar="PDF",
                    help="compare la grille des classes à la figure 10 du PDF de Rosset et al. 2025 (géoréférencement, "
                         "accord) au lieu d'écrire les fichiers")
    args = ap.parse_args(argv)
    for flux in (sys.stdout, sys.stderr):        # console Windows redirigée (cp1252) : accents, « × »
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    if args.figure:
        res = comparer_figure10(charger_grille_qc(), Path(args.figure))
        for k, v in res["georef"].items():
            print(f"{k} = {v['a']:.2f} + {v['b']:.4f} × degré ± {v['trait']:.2f} px (trait) ; résidus RMS {v['rms_px']:.3f} px "
                  f"(n = {v['n']}) : {v['residus_px']}")
        print(f"accord figure / grille : {res['accord'] * 100:.1f} % sur {res['n']} pixels classés A à D")
        print("décalage en x (px) → accord :", {k: round(v * 100, 1) for k, v in res["decalages"].items()})
        print("matrice (lignes figure A..D ; colonnes grille 0 aucun, A..E, 6 non classé) :")
        for lab, ligne in zip("ABCD", res["matrice"]):
            print(f"  {lab} {ligne[:7]}")
        print("par code (pixels de la figure A/B/C/D) :")
        for c, v in sorted(res["par_code"].items(), key=lambda kv: -sum(kv[1].values())):
            print(f"  {c:4s} {v}")
        print("eau de la figure, code du SIGEOM dessous :", dict(sorted(res["eau"].items(), key=lambda kv: -kv[1])))
        return 0
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
              if "rows" in res else "") + (f", {res['classees']} structures classées {res['par_classe']}"
              if "classees" in res else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
