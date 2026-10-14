"""Débits de circulation du MTMD (Données Québec « debit-de-circulation », CC-BY 4.0) et
appariement aux structures.

Source : WFS `ms:circulation_routier` en GeoJSON (une section de trafic = une polyligne, DJMA/DJME/DJMH
et % de camions sur 10 ans). Dictionnaire :
https://www.donneesquebec.ca/recherche/dataset/c77c495a-2a4c-447e-9184-25722289007f/resource/782087a6-3f53-4591-b9e2-07af432a1379/download/debit_circulation_dictionnaire.pdf

Sortie `data/debits.js` : `window.PQ_DEBITS={...};` avec
  years    : années, la plus récente d'abord ;
  source   : page du jeu de données (citée dans la fiche ; les classeurs .xlsx ne sont pas proposés) ;
  sections : uniquement les sections appariées à au moins une structure ; chaque série (djma, djme, djmh, cam)
             a la longueur de `years` (null = non disponible), ou vaut null si aucune année n'a de valeur ;
  match    : par n° de structure → {"sur":[sections], "sous":[sections], "approx":0..3, "dsur":m, "dsous":m}
             (`dsur`/`dsous` absents quand `sur`/`sous` est vide) ; une structure sans aucune section est omise.
             `sur` = route portée, `sous` = route franchie ; `approx` = bits 1 (portée) et 2 (franchie) : section
             retenue sans concordance de n° de route (plus proche section à < 40 m).

Garde-fous (v0.5.2) : une section portée n'est retenue que si son DJMA est cohérent avec celui de la fiche de
la structure (facteur ≤ 8 avec concordance de n°, ≤ 3 en repli géométrique ; repli refusé si la fiche n'a pas
de DJMA), et les libellés « Accès route 175 », « Chemin de desserte (A-20) » ne désignent pas la route citée.
"""
import argparse
import math
import re
import sqlite3
import sys
from datetime import date

from . import net
from .config import DATA_DIR, DB_PATH, RAW_DIR

SOURCE = "debits"
OUT_PATH = DATA_DIR / "debits.js"
RAW_NAME = "debits_circulation.geojson"
URL = (
    "https://ws.mapserver.transports.gouv.qc.ca/swtq?service=wfs&version=2.0.0&request=getfeature"
    "&typename=ms:circulation_routier&srsname=EPSG:4326&outputformat=geojson"
)
ATTRIBUTION = "Débits de circulation : MTMD / Données Québec (CC-BY 4.0)"
SOURCE_PAGE = "https://www.donneesquebec.ca/recherche/dataset/debit-de-circulation"

# Rayons de recherche (m)
R_SUR = 150            # section portée, n° de route concordant
R_SOUS = 200           # section franchie, n° de route concordant
R_APPROX = 40          # repli sans concordance de n° de route
EXTRA_M = 20           # sections supplémentaires (autre chaussée, section voisine) : distance ≤ minimum + 20 m
MAX_SECTIONS = 3
FACTEUR_NUM = 8        # écart max. de DJMA (section / fiche) quand le n° de route concorde
FACTEUR_APPROX = 3     # écart max. en repli géométrique (et DJMA de la fiche exigé)
CELL = 0.01            # taille des cellules de l'index spatial (degrés)
M_PAR_DEG = 111_195.0  # mètres par degré de latitude

# --- Numéros de route ---------------------------------------------------------------
# « Autoroute 40 », « Route 132 », « rte 138 », « A-73 Nord », « R-161 », « l'A-40 ».
_RE_MOT = re.compile(r"(?<![\wÀ-ÿ])(?:autoroute|route|rte)\s*[-.]?\s*(\d{1,3})(?!\d)", re.I)
_RE_LETTRE = re.compile(r"(?<![\wÀ-ÿ])[AR]\s*-\s*(\d{1,3})(?!\d)", re.I)
_RE_RTSS = re.compile(r"^(\d{5})-\d{2}-\d{3}-")


_RE_ANCIEN = re.compile(r"anciens?(?:ne)?\s*$", re.I)
# Chemin d'accès ou de desserte : la route citée est celle qu'il dessert, pas la voie portée
_RE_ACCES = re.compile(r"^\s*(?:chemin\s+d\W?\s*)?acc[eè]s\b|desserte", re.I)


def route_numbers(texte: str | None) -> list[int]:
    """N° de route cités dans un libellé, dans l'ordre d'apparition, sans doublon
    (« Ancienne route 138 » est ignorée : ce n'est plus la route 138 ; « Accès route 175 » ou
    « Chemin de desserte (A-20) » non plus : ce sont des chemins qui y mènent)."""
    if not texte or _RE_ACCES.search(texte):
        return []
    trouves = sorted(
        [(m.start(), int(m.group(1))) for rx in (_RE_MOT, _RE_LETTRE) for m in rx.finditer(texte)
         if not _RE_ANCIEN.search(texte[:m.start()])])
    out: list[int] = []
    for _, n in trouves:
        if n and n not in out:
            out.append(n)
    return out


def rtss_route(rtss: str | None) -> int | None:
    """« 00345-01-023-000C » → 345. Les codes ≥ 1000 (routes locales) ne sont pas des n° de route."""
    m = _RE_RTSS.match(rtss or "")
    if not m:
        return None
    n = int(m.group(1))
    return n if 0 < n < 1000 else None


# --- Géométrie ----------------------------------------------------------------------
def dist_point_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance (même unité que les entrées, plan cartésien) du point P au segment AB."""
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / n))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def dist_point_ligne_m(lat: float, lon: float, ligne: list[tuple[float, float]]) -> float:
    """Distance en mètres d'un point (lat, lon) à une polyligne [(lon, lat)…], projection équirectangulaire locale."""
    ky = M_PAR_DEG
    kx = M_PAR_DEG * math.cos(math.radians(lat))
    pts = [((x - lon) * kx, (y - lat) * ky) for x, y in ligne]
    if len(pts) == 1:
        return math.hypot(*pts[0])
    return min(dist_point_segment(0.0, 0.0, *a, *b) for a, b in zip(pts, pts[1:]))


class Index:
    """Index spatial en grille : cellule (lat, lon) de CELL degrés → segments des sections."""

    def __init__(self):
        self.cells: dict[tuple[int, int], list[tuple]] = {}

    def add_ligne(self, sec: int, ligne: list[tuple[float, float]]) -> None:
        pts = [(float(p[0]), float(p[1])) for p in ligne]
        if len(pts) == 1:
            pts = pts * 2
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            seg = (sec, ax, ay, bx, by)
            for i in range(math.floor(min(ay, by) / CELL), math.floor(max(ay, by) / CELL) + 1):
                for j in range(math.floor(min(ax, bx) / CELL), math.floor(max(ax, bx) / CELL) + 1):
                    self.cells.setdefault((i, j), []).append(seg)

    def near(self, lat: float, lon: float, rayon_m: float) -> dict[int, float]:
        """{section: distance minimale en m} pour les sections à ≤ rayon_m du point."""
        ky = M_PAR_DEG
        kx = M_PAR_DEG * math.cos(math.radians(lat))
        dlat, dlon = rayon_m / ky, rayon_m / kx
        out: dict[int, float] = {}
        for i in range(math.floor((lat - dlat) / CELL), math.floor((lat + dlat) / CELL) + 1):
            for j in range(math.floor((lon - dlon) / CELL), math.floor((lon + dlon) / CELL) + 1):
                for sec, ax, ay, bx, by in self.cells.get((i, j), ()):
                    d = dist_point_segment(0.0, 0.0, (ax - lon) * kx, (ay - lat) * ky,
                                           (bx - lon) * kx, (by - lat) * ky)
                    if d <= rayon_m and d < out.get(sec, 1e18):
                        out[sec] = d
        return out


# --- Lecture du GeoJSON -------------------------------------------------------------
_RE_TXT = re.compile(r"^\s*(\d{4})\s+DJMA:(\S*)\s*/\s*DJME:(\S*)\s*/\s*DJMH:(\S*)\s*/\s*%cam:(\S*)")
TEXT_COLS = ["annee_en_cours"] + [f"annee{k}" for k in range(2, 11)]


def _val(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _compact(f: float | None, nd: int = 0):
    if f is None:
        return None
    f = round(f, nd)
    return int(f) if f == int(f) else f


def parse_annee_txt(txt: str | None) -> dict | None:
    """« 2025 DJMA:1780 / DJME:1920 / DJMH:1600 / %cam: / 30e h:210 » → {année, djma, djme, djmh, cam}."""
    m = _RE_TXT.match(txt or "")
    if not m:
        return None
    return {"annee": int(m.group(1)), "djma": _val(m.group(2)), "djme": _val(m.group(3)),
            "djmh": _val(m.group(4)), "cam": _val(m.group(5))}


def _lignes(geom: dict | None) -> list[list[tuple[float, float]]]:
    if not geom:
        return []
    if geom["type"] == "LineString":
        return [[tuple(p[:2]) for p in geom["coordinates"]]]
    if geom["type"] == "MultiLineString":
        return [[tuple(p[:2]) for p in ligne] for ligne in geom["coordinates"]]
    return []


def parse_feature(feat: dict) -> dict:
    """Entité GeoJSON → section : séries indexées par année + géométrie."""
    p = feat["properties"]
    series: dict[str, dict[int, float]] = {"djma": {}, "djme": {}, "djmh": {}, "cam": {}}
    annees: set[int] = set()
    for k in range(1, 11):
        annee = _val(p.get(f"djma_annee_{k}"))
        if annee is None:
            continue
        annee = int(annee)
        annees.add(annee)
        for t in series:
            v = _val(p.get(f"val_{t}_annee_{k}"))
            if v is not None:
                series[t][annee] = v
    for col in TEXT_COLS:                               # repli : texte récapitulatif de l'année
        a = parse_annee_txt(p.get(col))
        if a:
            annees.add(a["annee"])                      # sinon un payload alimenté par ce seul repli perd ses années
            for t in series:
                if a[t] is not None and a["annee"] not in series[t]:
                    series[t][a["annee"]] = a[t]
    # DJMA/DJME/DJMH ≤ 1 = « ND » (non disponible) dans les sources du MTMD
    for t in ("djma", "djme", "djmh"):
        series[t] = {a: v for a, v in series[t].items() if v > 1}
    rtss = (p.get("rtss_debut") or "").strip() or None
    debut = (p.get("des_debut_sous_route") or "").strip()
    return {
        "num": p["num_sectn_trafc"],
        "de": debut or None,
        "a": (p.get("des_fin_sous_route") or "").strip() or None,
        "rtss": rtss if _RE_RTSS.match(rtss or "") else None,       # exclut « Segment non inv. 134 »
        "routes_rtss": {r for r in [rtss_route(rtss)] if r},
        "routes_desc": set(route_numbers(debut)),
        "series": series,
        "annees": annees,
        "lignes": _lignes(feat.get("geometry")),
    }


def parse(content: bytes | str) -> list[dict]:
    import json
    data = json.loads(content)
    return [parse_feature(f) for f in data["features"]]


# --- Appariement --------------------------------------------------------------------
def _choisir(near: dict[int, float], sections: list[dict], nums: set[int], rayon: float,
             ok=lambda i: True) -> tuple[list[int], float] | None:
    """Sections dont le n° de route concorde (rtss d'abord, puis libellé) et acceptées par `ok`,
    la plus proche en tête."""
    if not nums:
        return None
    for cle in ("routes_rtss", "routes_desc"):
        c = sorted((d, i) for i, d in near.items() if d <= rayon and nums & sections[i][cle] and ok(i))
        if c:
            return [i for d, i in c if d <= c[0][0] + EXTRA_M][:MAX_SECTIONS], c[0][0]
    return None


def djma_recent(section: dict) -> float | None:
    """DJMA de l'année la plus récente renseignée de la section, ou None."""
    v = (section.get("series") or {}).get("djma") or {}
    return v[max(v)] if v else None


def djma_coherent(section: dict, djma_fiche: float | None, facteur: float) -> bool | None:
    """True / False si le DJMA de la section est à un facteur ≤ `facteur` de celui de la fiche de la structure ;
    None si l'un des deux manque (DJMA ≤ 1 = « ND » dans les fiches)."""
    s = djma_recent(section)
    if not s or not djma_fiche or djma_fiche <= 1:
        return None
    return 1 / facteur <= s / djma_fiche <= facteur


def apparier(index: Index, sections: list[dict], *, route: str | None, obstacle: str | None,
             obstacle_route: bool, lat: float, lon: float, djma: float | None = None) -> dict | None:
    """Sections de trafic portée (`sur`) et franchie (`sous`) par une structure, ou None.
    `djma` = DJMA de la fiche de la structure (voie portée), pour écarter les sections incohérentes."""
    near = index.near(lat, lon, max(R_SUR, R_SOUS))
    if not near:
        return None
    approx = 0
    sur, d_sur, sous, d_sous = [], None, [], None
    # 1. concordance de n° de route (portée, puis franchie) ; portée : DJMA non contradictoire avec la fiche
    r = _choisir(near, sections, set(route_numbers(route)), R_SUR,
                 ok=lambda i: djma_coherent(sections[i], djma, FACTEUR_NUM) is not False)
    if r:
        sur, d_sur = r
    nums_o = set(route_numbers(obstacle)) if obstacle_route else set()
    r = _choisir(near, sections, nums_o, R_SOUS)
    if r:
        sous, d_sous = r
    # 2. replis sans concordance (< 40 m) : jamais la section déjà retenue pour l'autre voie.
    #    Portée : seulement si la fiche a un DJMA et qu'il concorde (sinon, mieux vaut rien qu'une autre route).
    if not sur:
        proches = sorted((d, i) for i, d in near.items() if d <= R_APPROX and i not in sous
                         and djma_coherent(sections[i], djma, FACTEUR_APPROX))
        if proches:
            d_sur, sur, approx = proches[0][0], [proches[0][1]], approx | 1
    if obstacle_route and not nums_o:                   # route franchie sans n° : autre section proche
        nums_sur = set().union(*(sections[i]["routes_rtss"] for i in sur)) if sur else set()
        proches = sorted((d, i) for i, d in near.items() if d <= R_APPROX and i not in sur
                         and not (nums_sur and nums_sur & sections[i]["routes_rtss"]))
        if proches:
            d_sous, sous, approx = proches[0][0], [proches[0][1]], approx | 2
    if not sur and not sous:
        return None
    m = {"sur": sur, "sous": sous, "approx": approx}
    if sur:
        m["dsur"] = round(d_sur)
    if sous:
        m["dsous"] = round(d_sous)
    return m


def charger_structures(db_path=DB_PATH) -> list[dict]:
    """Structures géolocalisées (lecture seule) avec indicateur « l'obstacle est une route »."""
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT s.num_dossr, s.route, s.obstacle, s.lat, s.lon, d.obstacle_type_voie, d.djma "
            "FROM structure s LEFT JOIN structure_detail d USING (num_dossr) "
            "WHERE s.lat IS NOT NULL AND s.lon IS NOT NULL ORDER BY s.num_dossr").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["obstacle_numerote"] = bool(route_numbers(d["obstacle"]))
        d["obstacle_route"] = d["obstacle_type_voie"] == "Route standard" or d["obstacle_numerote"]
        out.append(d)
    return out


def construire(sections: list[dict], structures: list[dict]) -> tuple[dict, dict]:
    """→ (match par n° de structure, statistiques d'appariement)."""
    index = Index()
    for i, s in enumerate(sections):
        for ligne in s["lignes"]:
            index.add_ligne(i, ligne)
    match, st = {}, dict(structures=len(structures), avec_sur=0, avec_sous=0, approx=0, obstacle_route=0,
                         obstacle_route_avec_sous=0, obstacle_numerote=0, obstacle_numerote_avec_sous=0,
                         sur_approx=0, sous_approx=0)
    for s in structures:
        m = apparier(index, sections, route=s["route"], obstacle=s["obstacle"],
                     obstacle_route=s["obstacle_route"], lat=s["lat"], lon=s["lon"], djma=s.get("djma"))
        if s["obstacle_route"]:
            st["obstacle_route"] += 1
        if s["obstacle_numerote"]:
            st["obstacle_numerote"] += 1
        if not m:
            continue
        match[s["num_dossr"]] = m
        st["avec_sur"] += bool(m["sur"])
        st["avec_sous"] += bool(m["sous"])
        st["approx"] += bool(m["approx"])
        if s["obstacle_route"] and m["sous"]:
            st["obstacle_route_avec_sous"] += 1
        if s["obstacle_numerote"] and m["sous"]:
            st["obstacle_numerote_avec_sous"] += 1
    return match, st


# --- Sortie -------------------------------------------------------------------------
def _serie(valeurs: dict[int, float], years: list[int], nd: int):
    """Liste alignée sur `years` (null = absent) ; null si aucune année n'a de valeur (économie de place)."""
    if not valeurs:
        return None
    return [_compact(valeurs.get(a), nd) for a in years]


def build_payload(sections: list[dict], match: dict, today: str | None = None) -> dict:
    years = sorted({a for s in sections for a in s["annees"]}, reverse=True)
    utilises = sorted({i for m in match.values() for i in m["sur"] + m["sous"]},
                      key=lambda i: sections[i]["num"])
    out_sections = {}
    for i in utilises:
        s = sections[i]
        out_sections[s["num"]] = {
            "de": s["de"], "a": s["a"], "rtss": s["rtss"],
            **{t: _serie(s["series"][t], years, 1 if t == "cam" else 0) for t in ("djma", "djme", "djmh", "cam")},
        }
    out_match = {}
    for num, m in sorted(match.items()):
        o = dict(m)
        o["sur"] = [sections[i]["num"] for i in m["sur"]]
        o["sous"] = [sections[i]["num"] for i in m["sous"]]
        out_match[num] = o
    return {"generated": today or date.today().isoformat(), "attribution": ATTRIBUTION, "source": SOURCE_PAGE,
            "years": years, "sections": out_sections, "match": out_match}


def write(payload: dict, path=OUT_PATH) -> int:
    import json
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(f"window.PQ_DEBITS={body};\n", encoding="utf-8")
    return path.stat().st_size


def run(fetch: bool = True) -> dict:
    if fetch:
        r = net.get(net.session(), URL, timeout=600)
        net.save_raw(RAW_NAME, r.content)
        content = r.content
    else:
        content = (RAW_DIR / RAW_NAME).read_bytes()
    sections = parse(content)
    structures = charger_structures()
    match, st = construire(sections, structures)
    payload = build_payload(sections, match)
    size = write(payload)
    n_or, n_on = st["obstacle_route"], st["obstacle_numerote"]
    return {
        "path": OUT_PATH, "rows": len(payload["sections"]), "bytes": size,
        "sections_source": len(sections), "structures": st["structures"],
        "avec_sur": st["avec_sur"], "taux_sur": round(st["avec_sur"] / st["structures"], 4),
        "avec_sous": st["avec_sous"],
        "obstacle_route": n_or, "obstacle_route_avec_sous": st["obstacle_route_avec_sous"],
        "taux_sous": round(st["obstacle_route_avec_sous"] / n_or, 4) if n_or else None,
        "obstacle_numerote": n_on, "obstacle_numerote_avec_sous": st["obstacle_numerote_avec_sous"],
        "taux_sous_numerote": round(st["obstacle_numerote_avec_sous"] / n_on, 4) if n_on else None,
        "approx": st["approx"],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-fetch", action="store_true", help="relit data/raw/ au lieu de télécharger")
    args = ap.parse_args(argv)
    res = run(fetch=not args.no_fetch)
    print(f"{res['path']} : {res['rows']} sections appariées sur {res['sections_source']}, "
          f"{res['bytes'] / 1e6:.2f} Mo")
    print(f"structures : {res['structures']} ; avec section portée : {res['avec_sur']} ({res['taux_sur']:.1%})")
    print(f"obstacle = route : {res['obstacle_route']} ; avec section franchie : "
          f"{res['obstacle_route_avec_sous']} ({res['taux_sous']:.1%}) ; "
          f"dont n° détectable : {res['obstacle_numerote_avec_sous']}/{res['obstacle_numerote']} "
          f"({res['taux_sous_numerote']:.1%}) ; structures approximatives : {res['approx']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
