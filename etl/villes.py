"""Structures routières municipales : Ville de Montréal et Ville de Sherbrooke (données ouvertes, CC-BY 4.0).

Deux couches de points, chacune dans son fichier `data/couche-*.js` :
  - `data/couche-mtl.js`        « Inventaire des actifs de voirie – Structures routières » (édition 2021, ~580 points) ;
  - `data/couche-sherbrooke.js` « Ouvrages routiers » (~24 points).

Format de sortie (compact, chargé par `<script src>` → fonctionne en `file://`) :
  window.PQ_COUCHES=window.PQ_COUCHES||{};window.PQ_COUCHES.mtl={...};
avec `points` = liste d'objets dont seules les clés non nulles sont écrites :
  - Montréal : lat, lon, num, ide, type, tc (code de type MTMD), fam (famille MTMD), groupe, route, obstacle,
    obst (classe d'obstacle, comme pour le MTMD), annee, icg (indice de la Ville, 1 décimale), cat (catégorie ICG),
    insp (date d'inspection générale), stab / smur (superficies tablier / mur, m²), charge, affichage, gestion,
    centre, inspection, rapport, mtmd, dup ;
  - Sherbrooke : lat, lon, id, nom, soustype, fam (déduite du nom : « Pont … », « Ponceau … »), mtmd, dup.
`mtmd` = n° de la structure du MTMD la plus proche (à moins de 30 m), pour relier la fiche de l'inventaire provincial ;
`dup` = 1 quand c'est très probablement le même ouvrage (même famille, ou famille inconnue d'un côté) : le
visualiseur ne le compte alors qu'une fois, sous son n° du MTMD.

Depuis la v0.5.2, les ouvrages sont aussi enregistrés dans la table `ouvrage_ville` de la base SQLite.
"""
import argparse
import json
import logging
import math
import re
import sqlite3
import sys
import unicodedata
from datetime import date

from . import db, net
from .build import classe_obstacle
from .config import DATA_DIR, DB_PATH, RAW_DIR

SOURCE = "villes"
log = logging.getLogger(__name__)

URL_MTL = ("https://donnees.montreal.ca/fr/dataset/74143072-dd9a-4309-95b4-da9a81a96d52/resource/"
           "81b60248-8e94-4dd2-ad4b-66f22daf8c9b/download/2021-liste-structure-donnees-ouvertes.geojson")
PAGE_MTL = "https://donnees.montreal.ca/dataset/structure-routiere"
URL_SHERBROOKE = ("https://services3.arcgis.com/qsNXG7LzoUbR4c1C/arcgis/rest/services/OuvrageRoutier/"
                  "FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=geojson")
PAGE_SHERBROOKE = "https://donneesquebec.ca/recherche/dataset/7dc8adc25f25438a86efe6ee4e68731b_0"

RAW_MTL = "villes_mtl.geojson"
RAW_SHERBROOKE = "villes_sherbrooke.geojson"
OUT_MTL = DATA_DIR / "couche-mtl.js"
OUT_SHERBROOKE = DATA_DIR / "couche-sherbrooke.js"

AVERTISSEMENT_MTL = "Données diffusées à titre informatif par la Ville ; ne pas utiliser pour des calculs d'ingénierie."
DISTANCE_MAX_M = 30                # rayon d'appariement avec l'inventaire du MTMD
M_PAR_DEGRE = 111_320.0            # mètres par degré de latitude (approximation équirectangulaire)

# Coquilles de la source dans les libellés de type (« voûté » publié « voà»té »).
CORRECTIONS_TYPE = {"à»": "û"}

# Clés de sortie d'un point de Montréal, dans l'ordre d'écriture.
CHAMPS_MTL = ["lat", "lon", "num", "ide", "type", "tc", "fam", "groupe", "route", "obstacle", "obst", "annee", "icg",
              "cat", "insp", "stab", "smur", "charge", "affichage", "gestion", "centre", "inspection", "rapport",
              "mtmd", "dup"]
_FAM_PAR_NOM = [("ponceau", re.compile(r"^ponceau", re.I)), ("pont", re.compile(r"^(pont|passerelle|viaduc|[ée]changeur)", re.I)),
                ("mur", re.compile(r"^mur", re.I)), ("tunnel", re.compile(r"^tunnel", re.I))]


def famille_par_nom(nom: str | None) -> str | None:
    """« Pont College » → pont ; « Ponceau … » → ponceau (Sherbrooke ne publie pas le type)."""
    for fam, rx in _FAM_PAR_NOM:
        if rx.search(nom or ""):
            return fam
    return None


# --- Nettoyage -----------------------------------------------------------------------------------
def nettoyer(v):
    """Texte → espaces insécables et blancs multiples ramenés à une seule espace ; vide → None."""
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


def cle_type(libelle: str | None) -> str:
    """Clé de comparaison d'un libellé de type : NFKC, blancs réduits, minuscules (casefold)."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", libelle or "")).strip().casefold()


def type_lookup(pairs: list[tuple[int, str, str | None]]) -> dict:
    """[(code, libellé, famille ou None)…] → {clé de libellé: (code, famille)}.
    Un libellé partagé par plusieurs codes (ex. 35 / 47) garde le plus petit code ; la famille vient
    des paires qui en portent une (table `type_structure`)."""
    famille = {code: fam for code, _, fam in pairs if fam}
    lookup: dict[str, tuple[int, str | None]] = {}
    for code, libelle, _ in sorted(pairs, key=lambda p: p[0]):
        k = cle_type(libelle)
        if k and k not in lookup:
            lookup[k] = (code, famille.get(code))
    return lookup


def charger_types(db_path=DB_PATH) -> dict:
    """Table de correspondance libellé → (code, famille), depuis `type_structure` et `wfs_structure`."""
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        pairs = conn.execute(
            "SELECT code, libelle, famille FROM type_structure "
            "UNION SELECT DISTINCT type_code, type_libelle, NULL FROM wfs_structure "
            "WHERE type_code IS NOT NULL AND type_libelle IS NOT NULL").fetchall()
    finally:
        conn.close()
    return type_lookup(pairs)


def charger_structures_mtmd(db_path=DB_PATH) -> list[tuple[str, float, float, str | None]]:
    """Structures géolocalisées de l'inventaire du MTMD : [(num_dossr, lat, lon, famille)…]."""
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        return conn.execute("SELECT num_dossr, lat, lon, famille FROM structure "
                            "WHERE lat IS NOT NULL AND lon IS NOT NULL").fetchall()
    finally:
        conn.close()


# --- Appariement géographique --------------------------------------------------------------------
def nearest_mtmd(points: list[tuple[float, float]], mtmd_rows, max_m: float = DISTANCE_MAX_M) -> list[str | None]:
    """[(lat, lon)…] → n° de la structure du MTMD la plus proche à `max_m` mètres ou moins (None sinon).
    `mtmd_rows` = [(num_dossr, lat, lon[, famille])…] ; distance équirectangulaire, index en grille de `max_m`."""
    pas = max(max_m, 1) / M_PAR_DEGRE                  # côté d'une cellule, en degrés
    grille: dict[tuple[int, int], list[tuple[str, float, float]]] = {}
    for num, lat, lon, *_ in mtmd_rows:
        grille.setdefault((math.floor(lat / pas), math.floor(lon / pas)), []).append((num, lat, lon))
    res = []
    for lat, lon in points:
        ci, cj = math.floor(lat / pas), math.floor(lon / pas)
        kx = math.cos(math.radians(lat)) * M_PAR_DEGRE
        # une cellule fait `max_m` en latitude mais moins en longitude : on élargit selon cos(lat)
        dj = math.ceil(1 / max(math.cos(math.radians(lat)), 0.05))
        best, best_d = None, max_m
        for i in range(ci - 1, ci + 2):
            for j in range(cj - dj, cj + dj + 1):
                for num, la, lo in grille.get((i, j), ()):
                    d = math.hypot((la - lat) * M_PAR_DEGRE, (lo - lon) * kx)
                    if d <= best_d:
                        best, best_d = num, d
        res.append(best)
    return res


# --- Analyse des sources -------------------------------------------------------------------------
def _nombre(v, nd: int | None = None):
    """Nombre JSON → int si entier, sinon float arrondi à `nd` décimales ; vide → None."""
    if v is None or v == "":
        return None
    f = float(v)
    if nd is not None:
        f = round(f, nd)
    return int(f) if f == int(f) and nd is None else f


def _coords(f: dict, props: dict) -> tuple[float, float] | None:
    g = f.get("geometry") or {}
    c = g.get("coordinates")
    if g.get("type") == "Point" and c and len(c) >= 2:
        return float(c[1]), float(c[0])
    if props.get("Latitude") is not None and props.get("Longitude") is not None:
        return float(props["Latitude"]), float(props["Longitude"])
    return None


def parse_mtl(content: bytes, lookup: dict | None = None) -> tuple[list[dict], list[str]]:
    """GeoJSON de Montréal → (points triés par n° de structure, libellés de type sans code MTMD).
    Les points n'ont que les clés non nulles ; `mtmd` est ajouté plus tard par `rattacher_mtmd`."""
    lookup = lookup or {}
    points, inconnus = [], set()
    for f in json.loads(content.decode("utf-8-sig"))["features"]:
        p = {k: nettoyer(v) for k, v in (f.get("properties") or {}).items()}
        pos = _coords(f, p)
        if pos is None:
            continue
        typ = p.get("Type structure")
        for faux, juste in CORRECTIONS_TYPE.items():
            typ = typ.replace(faux, juste) if typ else typ
        tc, fam = lookup.get(cle_type(typ), (None, None)) if typ else (None, None)
        if typ and tc is None:
            inconnus.add(typ)
        centre = re.sub(r"^\d+\s*-\s*", "", p["Centre de services"]) if p.get("Centre de services") else None
        rapport = p.get("lien_vers_rapport")
        pt = {
            "lat": round(pos[0], 6), "lon": round(pos[1], 6),
            "num": p.get("No structure"), "ide": _nombre(p.get("IDE_STRCT")),
            "type": typ, "tc": tc, "fam": fam, "groupe": p.get("Groupe"),
            "route": p.get("Nom route"), "obstacle": p.get("Nom obstacle"),
            "obst": classe_obstacle(None, p.get("Nom obstacle")),
            "annee": _nombre(p.get("Année de construction")), "icg": _nombre(p.get("ICG"), 1),
            "cat": None if p.get("Catégorie ICG") is None else str(p["Catégorie ICG"]),
            "insp": p.get("Date Insp. Générale Fermee"),
            "stab": _nombre(p.get("Superficie du tablier")), "smur": _nombre(p.get("Superficie du mur")),
            "charge": p.get("Charg. conception"), "affichage": p.get("Affichage sur place"),
            "gestion": p.get("Responsablilté de gestion"), "centre": centre,
            "inspection": p.get("Role VM Inspection"),
            "rapport": None if rapport in (None, "Non disponible") else rapport,
        }
        points.append({k: pt[k] for k in CHAMPS_MTL if pt.get(k) is not None})
    points.sort(key=lambda p: (p.get("num") or "", p["lat"], p["lon"]))
    return points, sorted(inconnus)


def parse_sherbrooke(content: bytes) -> list[dict]:
    """GeoJSON de Sherbrooke → points {lat, lon, id, nom, soustype} (clés non nulles seulement)."""
    points = []
    for f in json.loads(content.decode("utf-8-sig"))["features"]:
        p = {k: nettoyer(v) for k, v in (f.get("properties") or {}).items()}
        pos = _coords(f, p)
        if pos is None:
            continue
        pt = {"lat": round(pos[0], 6), "lon": round(pos[1], 6), "id": p.get("ID"), "nom": p.get("NOM"),
              "soustype": p.get("SOUSTYPE"), "fam": famille_par_nom(p.get("NOM"))}
        points.append({k: v for k, v in pt.items() if v is not None})
    points.sort(key=lambda p: (str(p.get("id", "")), p["lat"], p["lon"]))
    return points


def rattacher_mtmd(points: list[dict], mtmd_rows, max_m: float = DISTANCE_MAX_M) -> int:
    """Ajoute `mtmd` aux points appariés (à `max_m` m ou moins), et `dup` = 1 quand les familles concordent
    (ou que l'une est inconnue) : même ouvrage. Renvoie le nombre d'appariements."""
    nums = nearest_mtmd([(p["lat"], p["lon"]) for p in points], mtmd_rows, max_m)
    fam_mtmd = {r[0]: r[3] for r in mtmd_rows if len(r) > 3}
    n = 0
    for p, num in zip(points, nums):
        if num is not None:
            p["mtmd"] = num
            fm = fam_mtmd.get(num)
            if not p.get("fam") or not fm or p["fam"] == fm:
                p["dup"] = 1
            n += 1
    return n


# --- Base SQLite ---------------------------------------------------------------------------------
def lignes_db(cle: str, points: list[dict]) -> list[dict]:
    """Points d'une couche → lignes de la table `ouvrage_ville`."""
    out = []
    for p in points:
        ident = p.get("num") if cle == "mtl" else p.get("id")
        out.append({
            "source": cle, "id": str(ident if ident is not None else f"{p['lat']},{p['lon']}"),
            "num": p.get("num") if cle == "mtl" else (None if p.get("id") is None else str(p["id"])),
            "nom": p.get("nom") or (" / ".join(x for x in (p.get("route"), p.get("obstacle")) if x) or None),
            "type_code": p.get("tc"), "type_libelle": p.get("type") or p.get("soustype"), "famille": p.get("fam"),
            "route": p.get("route"), "obstacle": p.get("obstacle"), "obstacle_classe": p.get("obst"),
            "annee_construction": p.get("annee"), "icg_ville": p.get("icg"), "cat_icg": p.get("cat"),
            "inspection_generale": p.get("insp"), "gestion": p.get("gestion"), "lat": p["lat"], "lon": p["lon"],
            "num_dossr_mtmd": p.get("mtmd"), "doublon": p.get("dup", 0),
            "raw_json": json.dumps(p, ensure_ascii=False),
        })
    return out


def enregistrer(conn, cle: str, points: list[dict]) -> int:
    """Remplace les lignes de la source `cle` dans `ouvrage_ville` ; renvoie le nombre de lignes."""
    rows = lignes_db(cle, points)
    with conn:
        conn.execute("DELETE FROM ouvrage_ville WHERE source = ?", (cle,))
        if rows:
            cols = list(rows[0])
            conn.executemany(f"INSERT OR REPLACE INTO ouvrage_ville ({', '.join(cols)}) VALUES "
                             f"({', '.join('?' * len(cols))})", ([r[c] for c in cols] for r in rows))
    return len(rows)


# --- Sortie --------------------------------------------------------------------------------------
def build_payload_mtl(points: list[dict], today: str | None = None) -> dict:
    return {
        "generated": today or date.today().isoformat(),
        "titre": "Structures routières — Ville de Montréal",
        "gestionnaire": "Ville de Montréal",
        "edition": "2021",
        "attribution": "Structures routières : Ville de Montréal (CC-BY 4.0)",
        "source": PAGE_MTL,
        "avertissement": AVERTISSEMENT_MTL,
        "points": points,
    }


def build_payload_sherbrooke(points: list[dict], today: str | None = None) -> dict:
    return {
        "generated": today or date.today().isoformat(),
        "titre": "Ouvrages routiers — Ville de Sherbrooke",
        "gestionnaire": "Ville de Sherbrooke",
        "edition": None,
        "attribution": "Ouvrages routiers : Ville de Sherbrooke (CC-BY 4.0)",
        "source": PAGE_SHERBROOKE,
        "avertissement": None,
        "points": points,
    }


def write(payload: dict, cle: str, path) -> int:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(
        f"window.PQ_COUCHES=window.PQ_COUCHES||{{}};window.PQ_COUCHES.{cle}={body};\n", encoding="utf-8")
    return path.stat().st_size


def run(fetch: bool = True) -> list[dict]:
    if fetch:
        s = net.session()
        mtl = net.get(s, URL_MTL, timeout=300).content
        net.save_raw(RAW_MTL, mtl)
        sherbrooke = net.get(s, URL_SHERBROOKE, timeout=300).content
        net.save_raw(RAW_SHERBROOKE, sherbrooke)
    else:
        mtl = (RAW_DIR / RAW_MTL).read_bytes()
        sherbrooke = (RAW_DIR / RAW_SHERBROOKE).read_bytes()

    try:
        lookup, mtmd_rows = charger_types(), charger_structures_mtmd()
    except sqlite3.Error:
        log.warning("villes : base %s illisible, codes de type et liens MTMD omis", DB_PATH.name)
        lookup, mtmd_rows = {}, []

    pts_mtl, inconnus = parse_mtl(mtl, lookup)
    if inconnus:
        log.warning("villes : %d libellés de type sans code MTMD : %s", len(inconnus), "; ".join(inconnus))
    pts_sh = parse_sherbrooke(sherbrooke)
    liens_mtl = rattacher_mtmd(pts_mtl, mtmd_rows)
    liens_sh = rattacher_mtmd(pts_sh, mtmd_rows)

    try:                                                   # copie dans la base (table ouvrage_ville)
        conn = db.connect()
        try:
            t0 = db.now()
            for cle, pts in (("mtl", pts_mtl), ("sherbrooke", pts_sh)):
                n = enregistrer(conn, cle, pts)
                db.record_run(conn, f"ville_{cle}", t0, status="ok", rows=n)
        finally:
            conn.close()
    except sqlite3.Error:
        log.warning("villes : écriture dans %s impossible", DB_PATH.name)

    res = []
    for cle, chemin, payload, liens, extra in (
            ("mtl", OUT_MTL, build_payload_mtl(pts_mtl), liens_mtl,
             {"avec_tc": sum(1 for p in pts_mtl if "tc" in p), "types_inconnus": inconnus}),
            ("sherbrooke", OUT_SHERBROOKE, build_payload_sherbrooke(pts_sh), liens_sh, {})):
        size = write(payload, cle, chemin)
        res.append({"path": chemin, "rows": len(payload["points"]), "bytes": size, "mtmd": liens, **extra})
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-fetch", action="store_true", help="relit data/raw/ au lieu de télécharger")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for res in run(fetch=not args.no_fetch):
        print(f"{res['path']} : {res['rows']} points ({res['mtmd']} liés au MTMD), {res['bytes'] / 1e6:.2f} Mo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
