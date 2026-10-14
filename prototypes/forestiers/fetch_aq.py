"""Télécharge les trois couches « Pont » d'AQréseau+ (MRNF) en pages de 2000 objets (cache brut dans cache/)."""
import json, sys, time
from pathlib import Path
import subprocess
from urllib.parse import urlencode
UA = "VisualisationPontsQC/0.1 (projet personnel non commercial; contact: cheruelanthony@gmail.com)"
B = "https://servicescarto.mrnf.gouv.qc.ca/pes/rest/services/Territoire/AQreseauPlus_WMS/MapServer"
CACHE = Path(__file__).parent / "cache"; CACHE.mkdir(exist_ok=True)

def get(url, params, tries=6):
    """curl (le client Python de requests est coupé par le serveur du MRNF ; curl passe)."""
    for k in range(tries):
        r = subprocess.run(["curl", "-s", "-m", "120", "-A", UA, url + "?" + urlencode(params)],
                           capture_output=True)
        txt = r.stdout.decode("utf8", "replace")
        if txt.lstrip().startswith("{"):
            return txt
        print("  réponse inattendue", len(txt), file=sys.stderr)
        time.sleep(3 * (k + 1))
    raise SystemExit("échec " + url)

for layer in (1, 2, 3):
    total = 0
    off = 0
    while True:
        f = CACHE / f"aq_pont{layer}_{off}.geojson"
        if f.exists() and f.stat().st_size > 100:
            txt = f.read_text(encoding="utf8")
        else:
            txt = get(f"{B}/{layer}/query", {"where": "1=1", "outFields": "*", "outSR": 4326,
                      "resultOffset": off, "resultRecordCount": 2000, "f": "geojson"})
            f.write_text(txt, encoding="utf8"); time.sleep(1.5)
        n = len(json.loads(txt)["features"])
        total += n
        print(layer, off, n)
        if n < 2000: break
        off += 2000
    print("couche", layer, "total", total)
