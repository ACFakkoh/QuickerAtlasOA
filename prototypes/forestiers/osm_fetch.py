"""Requêtes Overpass (OpenStreetMap) pour les ponts routiers des régions forestières et les ponts ferroviaires.

Poli : User-Agent identifié, UNE requête à la fois, pause entre les requêtes, reprises espacées.
Les réponses brutes sont conservées dans cache/ (rejouer sans réseau : python osm_fetch.py --no-fetch).
Usage : python osm_fetch.py [--rail] [--regions] [--counts]
"""
import json, subprocess, sys, time
from pathlib import Path

UA = "VisualisationPontsQC/0.1 (projet personnel non commercial; contact: cheruelanthony@gmail.com)"
URL = "https://overpass-api.de/api/interpreter"
CACHE = Path(__file__).parent / "cache"; CACHE.mkdir(exist_ok=True)

# boîtes (sud, ouest, nord, est) des trois régions forestières de la démo
REGIONS = {
    "slsj": (47.6, -74.6, 49.5, -69.8),     # Saguenay–Lac-Saint-Jean
    "cote-nord": (48.0, -69.8, 51.4, -65.8),  # Côte-Nord (boîte large ; build.py exclut la rive sud par un polygone)
    "abitibi": (47.6, -79.8, 49.5, -76.0),   # Abitibi-Témiscamingue (Abitibi)
}


def overpass(ql: str, tries: int = 5) -> dict:
    for k in range(tries):
        r = subprocess.run(["curl", "-s", "-m", "320", "-A", UA, "--data-urlencode", "data@-", URL],
                           input=ql.encode("utf8"), capture_output=True)
        txt = r.stdout.decode("utf8", "replace")
        if txt.lstrip().startswith("{"):
            try:
                return json.loads(txt)
            except ValueError:
                pass
        wait = 30 * (k + 1)
        print(f"  Overpass indisponible ({len(txt)} octets), attente {wait} s", file=sys.stderr)
        time.sleep(wait)
    raise SystemExit("Overpass: abandon")


def cached(name: str, ql: str, force=False) -> dict:
    f = CACHE / name
    if f.exists() and not force:
        return json.loads(f.read_text(encoding="utf8"))
    d = overpass(ql)
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf8")
    time.sleep(15)
    return d


def main():
    args = sys.argv[1:]
    if "--regions" in args or not args:
        for k, (s, w, n, e) in REGIONS.items():
            ql = f'[out:json][timeout:300];\nway["highway"]["bridge"]({s},{w},{n},{e});\nout geom tags qt;'
            d = cached(f"osm_routes_ponts_{k}.json", ql)
            print(k, len(d["elements"]))
    if "--rail" in args or not args:
        ql = ('[out:json][timeout:300];\narea["ISO3166-2"="CA-QC"]->.a;\n'
              'way["railway"="rail"]["bridge"](area.a);\nout geom tags qt;')
        d = cached("osm_rail_bridges_qc.json", ql)
        print("rail", len(d["elements"]))
    if "--counts" in args:
        for nom, filt in [("track+bridge", '["highway"="track"]["bridge"]'),
                          ("track", '["highway"="track"]'),
                          ("unclassified+bridge", '["highway"="unclassified"]["bridge"]'),
                          ("service+bridge", '["highway"="service"]["bridge"]'),
                          ("highway+bridge", '["highway"]["bridge"]')]:
            ql = f'[out:json][timeout:300];\narea["ISO3166-2"="CA-QC"]->.a;\nway{filt}(area.a);\nout count;'
            d = cached("osm_count_" + nom.replace("+", "_") + ".json", ql)
            print(nom, d["elements"][0]["tags"]["ways"])


if __name__ == "__main__":
    main()
