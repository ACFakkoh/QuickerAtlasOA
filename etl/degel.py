"""Zones de dégel du MTMD (limites de charge en période de dégel) : polygones des zones 1, 2 et 3.

Source : WFS du MTMD (couche `ms:zone_degel`, jeu « Zone de dégel » de Données Québec, CC BY 4.0), en WGS 84.
Chaque zone porte ses dates officielles de la dernière période de dégel (début, fin), mises à jour chaque année
par le MTMD ; la géométrie date de 2022.

Les contours (≈ 1 Mo) sont simplifiés (Douglas-Peucker, tolérance TOL_M) et quantifiés à 1e-4 degré (≈ 10 m),
assez fin pour la carte provinciale, où la couche sert de repère.

Sortie : `data/couche-degel.js` :

    window.PQ_COUCHES.degel = {"generated": "...", "source": "...", "attribution": "...",
      "zones": [{"num": 1, "nom": "Zone 1", "partie": "Partie sud du Québec", "debut": "2026-03-16", "fin": "2026-05-15",
                 "maj": "2022-03-04", "anneaux": [[[lat_e4, lon_e4], ...], ...]}, ...]}

Usage : python -m etl.degel [--no-fetch]
"""
import argparse
import json
import logging
import math
import re
import sys
from datetime import date

from . import net
from .config import DATA_DIR, RAW_DIR, WFS_BASE
from .reseaux import douglas_peucker

log = logging.getLogger("etl.degel")

SOURCE = "degel"
URL = (f"{WFS_BASE}?service=wfs&version=2.0.0&request=getfeature&typename=ms:zone_degel"
       "&srsname=EPSG:4326&outputformat=geojson")
PAGE = "https://www.donneesquebec.ca/recherche/dataset/zone-de-degel"
ATTRIBUTION = "Zones de dégel : MTMD, Données Québec (CC BY 4.0)"
RAW = RAW_DIR / "zone_degel.geojson"
OUT = DATA_DIR / "couche-degel.js"
ECHELLE = 10_000                    # 1e-4 degré ≈ 11 m en latitude
TOL_M = 150.0                       # simplification : invisible à l'échelle de la province
M_PAR_DEGRE = 111_320
AIRE_MIN_KM2 = 0.5                  # îlots plus petits omis


def _date(v) -> str | None:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(v or ""))
    return m.group(1) if m else None


def _anneaux(geom: dict | None):
    if not geom:
        return
    if geom["type"] == "Polygon":
        yield from geom["coordinates"]
    elif geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            yield from poly


def aire_km2(pts: list[tuple[float, float]]) -> float:
    """Aire approchée d'un anneau [(lat, lon)…] (formule du lacet, longitude corrigée par cos(latitude))."""
    if len(pts) < 3:
        return 0.0
    k = math.cos(math.radians(sum(p[0] for p in pts) / len(pts)))
    s = sum(pts[i - 1][1] * pts[i][0] - pts[i][1] * pts[i - 1][0] for i in range(len(pts)))
    return abs(s) / 2 * k * (M_PAR_DEGRE / 1000) ** 2


def simplifier_anneau(coords, tol_m: float = TOL_M) -> list[list[int]]:
    """[[lon, lat]…] (fermé) → [[lat_e4, lon_e4]…] simplifié, sans le point de fermeture ; [] si l'anneau disparaît."""
    pts = [(lat, lon) for lon, lat in coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3 or aire_km2(pts) < AIRE_MIN_KM2:
        return []
    k = math.cos(math.radians(sum(p[0] for p in pts) / len(pts)))
    # anneau fermé : on coupe en deux au point le plus éloigné du premier, pour que DP garde la forme
    loin = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + ((pts[i][1] - pts[0][1]) * k) ** 2)
    out = []
    for morceau in (pts[:loin + 1], pts[loin:] + [pts[0]]):
        plan = [(la, lo * k) for la, lo in morceau]
        garde = set(map(id, douglas_peucker(plan, tol_m / M_PAR_DEGRE)))
        out += [morceau[i] for i, q in enumerate(plan) if id(q) in garde][:-1]
    q = []
    for la, lo in out:
        p = [round(la * ECHELLE), round(lo * ECHELLE)]
        if not q or q[-1] != p:
            q.append(p)
    return q if len(q) >= 3 else []


def parse(geojson: dict) -> list[dict]:
    zones = []
    for f in geojson.get("features", []):
        pr = f.get("properties") or {}
        try:
            num = int(float(pr.get("num_zone")))
        except (TypeError, ValueError):
            continue
        anneaux = [a for a in (simplifier_anneau(c) for c in _anneaux(f.get("geometry"))) if a]
        if anneaux:
            zones.append({"num": num, "nom": pr.get("zone") or f"Zone {num}", "partie": pr.get("nom_partie_zone"),
                          "debut": _date(pr.get("dat_debut_zone")), "fin": _date(pr.get("dat_fin_zone")),
                          "maj": _date(pr.get("dat_maj")), "anneaux": anneaux})
    return sorted(zones, key=lambda z: z["num"])


def run(fetch: bool = True) -> dict:
    if fetch:
        r = net.get(net.session(), URL, timeout=180)
        RAW.parent.mkdir(parents=True, exist_ok=True)
        RAW.write_bytes(r.content)
    zones = parse(json.loads(RAW.read_bytes().decode("utf-8")))
    if len(zones) != 3:
        raise RuntimeError(f"zones de dégel : {len(zones)} zones lues (3 attendues)")
    payload = {"generated": date.today().isoformat(), "source": PAGE, "attribution": ATTRIBUTION, "echelle": ECHELLE, "zones": zones}
    corps = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(f"window.PQ_COUCHES=window.PQ_COUCHES||{{}};window.PQ_COUCHES.degel={corps};\n", encoding="utf-8", newline="\n")
    return {"path": OUT, "bytes": OUT.stat().st_size, "rows": len(zones),
            "points": sum(len(a) for z in zones for a in z["anneaux"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m etl.degel", description=__doc__.splitlines()[0])
    ap.add_argument("--no-fetch", action="store_true", help="relit data/raw/zone_degel.geojson au lieu de télécharger")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    r = run(fetch=not args.no_fetch)
    print(f"{r['path']} : {r['rows']} zones, {r['points']} sommets, {r['bytes'] / 1e3:.0f} Ko")
    return 0


if __name__ == "__main__":
    sys.exit(main())
