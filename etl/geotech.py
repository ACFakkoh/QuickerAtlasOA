"""Sites d'investigation géotechnique du MTMD (Données Québec, CC-BY 4.0).

Deux couches WFS fusionnées en un seul fichier `data/couche-geotech.js` :
  - `ms:site_inv_geotech_p`     sondages géotechniques (~7 700 points) ;
  - `ms:site_inv_geotech_bdg_p` sondages de la Banque de données géotechniques (~10 500 points).

Format de sortie (compact, chargé par `<script src>` → fonctionne en `file://`) :
  window.PQ_COUCHES=window.PQ_COUCHES||{};window.PQ_COUCHES.geotech={...};
avec `fields` = ["lat","lon","type","site","sondage","prof","z","url","bdg"] et pour chaque point :
  - lat, lon : entiers, degrés × 1e5 (~1 m) ;
  - type     : index dans `types` ;
  - prof     : profondeur maximale du sondage (m) ;
  - z        : altitude du collet (m), null si la référence verticale est arbitraire/indéterminée ;
  - url      : 1  → rapport PDF à l'adresse par défaut `urlBase[bdg] + site + "_" + sondage + ".pdf"`
               (encoder avec encodeURI) ;
               "nom.pdf" → nom de fichier atypique à ajouter à `urlBase[bdg]` ;
               null → pas de rapport ;
  - bdg      : 0 = couche des sondages, 1 = couche BDG.
"""
import argparse
import csv
import io
import json
import sys
from datetime import date

from . import net
from .config import DATA_DIR, RAW_DIR

SOURCE = "geotech"
OUT_PATH = DATA_DIR / "couche-geotech.js"

WFS = "https://ws.mapserver.transports.gouv.qc.ca/swtq?service=wfs&version=2.0.0&request=getfeature"
LAYERS = [
    # (typename WFS, fichier brut, drapeau bdg)
    ("ms:site_inv_geotech_p", "geotech_sondages.csv", 0),
    ("ms:site_inv_geotech_bdg_p", "geotech_bdg.csv", 1),
]

TITRE = "Sondages géotechniques"
ATTRIBUTION = "Sites d'investigation géotechnique : MTMD / Données Québec (CC-BY 4.0)"
FIELDS = ["lat", "lon", "type", "site", "sondage", "prof", "z", "url", "bdg"]

# Libellés harmonisés entre les deux couches (même type, orthographes différentes ; vide = indéterminé).
TYPE_ALIAS = {
    "Scissomètre in-situ": "Scissomètre in situ",
    "": "Sondage indéterminé",
}
# Références verticales où Z n'est pas une altitude exploitable.
REF_Z_INUTILISABLE = {"Arbitraire", "Indéterminée"}


def url_layer(typename: str) -> str:
    return f"{WFS}&typename={typename}&outputformat=csv"


def _num(v: str | None, nd: int = 2):
    """« 32.000000 » → 32 ; « 24.470 » → 24.47 ; vide → None."""
    v = (v or "").strip()
    if not v:
        return None
    f = round(float(v), nd)
    return int(f) if f == int(f) else f


def _deg5(v: str) -> int:
    return round(float(v) * 1e5)


def _base(hyperlien: str) -> str:
    return hyperlien.rsplit("/", 1)[0] + "/" if "/" in hyperlien else ""


def parse(content: bytes) -> list[dict]:
    """CSV d'une couche → lignes normalisées (les lignes sans coordonnées sont ignorées)."""
    rows = []
    for r in csv.DictReader(io.StringIO(content.decode("utf-8-sig"))):
        if not (r.get("Latitude") or "").strip() or not (r.get("Longitude") or "").strip():
            continue
        typ = (r.get("TYPE") or "").strip()
        rows.append({
            "lat": _deg5(r["Latitude"]),
            "lon": _deg5(r["Longitude"]),
            "type": TYPE_ALIAS.get(typ, typ),
            "site": (r.get("NO_SITE") or "").strip(),
            "sondage": (r.get("NO_SONDAGE") or "").strip(),
            "prof": _num(r.get("PROF_MAX")),
            "z": None if (r.get("REF_Z") or "").strip() in REF_Z_INUTILISABLE else _num(r.get("Z")),
            "hyperlien": (r.get("HYPERLIEN") or "").strip(),
        })
    return rows


def build_payload(couches: list[tuple[int, list[dict]]], today: str | None = None) -> dict:
    """`couches` = [(drapeau bdg, lignes parse())…] → objet JSON de la couche."""
    types: list[str] = []
    t_idx: dict[str, int] = {}
    bases = ["", ""]
    points = []
    for bdg, rows in couches:
        for r in rows:
            if r["hyperlien"] and not bases[bdg]:
                bases[bdg] = _base(r["hyperlien"])
        for r in rows:
            if r["type"] not in t_idx:
                t_idx[r["type"]] = len(types)
                types.append(r["type"])
            h = r["hyperlien"]
            if not h:
                url = None
            else:
                nom = h[len(bases[bdg]):] if h.startswith(bases[bdg]) else h
                url = 1 if nom == f"{r['site']}_{r['sondage']}.pdf" else nom
            points.append([r["lat"], r["lon"], t_idx[r["type"]], r["site"], r["sondage"],
                           r["prof"], r["z"], url, bdg])
    points.sort(key=lambda p: (p[0], p[1]))
    return {
        "generated": today or date.today().isoformat(),
        "titre": TITRE,
        "attribution": ATTRIBUTION,
        "types": types,
        "urlBase": bases,
        "fields": FIELDS,
        "points": points,
    }


def write(payload: dict, path=OUT_PATH) -> int:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(
        f"window.PQ_COUCHES=window.PQ_COUCHES||{{}};window.PQ_COUCHES.geotech={body};\n", encoding="utf-8")
    return path.stat().st_size


def run(fetch: bool = True) -> dict:
    couches = []
    s = net.session() if fetch else None
    for typename, raw_name, bdg in LAYERS:
        if fetch:
            r = net.get(s, url_layer(typename), timeout=300)
            net.save_raw(raw_name, r.content)
            content = r.content
        else:
            content = (RAW_DIR / raw_name).read_bytes()
        couches.append((bdg, parse(content)))
    payload = build_payload(couches)
    size = write(payload)
    return {"path": OUT_PATH, "rows": len(payload["points"]), "bytes": size,
            "par_couche": {("bdg" if b else "sondages"): len(rows) for b, rows in couches}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-fetch", action="store_true", help="relit data/raw/ au lieu de télécharger")
    args = ap.parse_args(argv)
    res = run(fetch=not args.no_fetch)
    print(f"{res['path']} : {res['rows']} points ({res['par_couche']}), {res['bytes'] / 1e6:.2f} Mo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
