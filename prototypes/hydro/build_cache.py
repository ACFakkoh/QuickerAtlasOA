# -*- coding: utf-8 -*-
"""Précalcul du prototype Hydrographie (QuickerAtlasOA).

Pourquoi : le CEHQ (MELCCFP) publie le suivi hydrométrique temps réel en fichiers texte SANS en-tête CORS ;
une page web ne peut donc pas les lire directement. On les télécharge ici (1 requête par seconde, au plus
~20 fichiers) et on les range dans cache/hydro-cache.js, avec la liste des 755 stations du CEHQ
(Données Québec, CC-BY 4.0).

Usage :  python build_cache.py
"""
import csv, io, json, math, re, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parents[1]
CACHE = ICI / "cache"
CACHE.mkdir(exist_ok=True)
# Le serveur du CEHQ (et celui du MRNF) refuse les User-Agent « non navigateur » : on s'identifie quand même.
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QuickerAtlasOA-proto/0.1"}
URL_STATIONS = "https://www.donneesquebec.ca/recherche/dataset/c31e2bee-a899-46ca-ad84-5798f0f49676/resource/6b2d32ef-80e2-445b-9bd1-97ddc39b5d59/download/stations_hydrometriques.csv"
URL_SUIVI = "https://www.cehq.gouv.qc.ca/suivihydro/fichier_donnees.asp?NoStation={no}"
EXEMPLES = ["03994", "03988", "16092", "05041", "00002", "10082"]


def get(url, binaire=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    return b if binaire else b.decode("utf-8", "replace")


def dist_km(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def charger_structures():
    s = (RACINE / "data" / "structures.js").read_text(encoding="utf-8")
    j = json.loads(s[s.index("=") + 1:].rstrip().rstrip(";"))
    return {r[0]: dict(zip(j["cols"], r)) for r in j["rows"]}


def lire_suivi(texte):
    """Fichier CEHQ : 'Date<TAB>Heure<TAB>Niveau<TAB><TAB>Débit' (virgule décimale, heure locale)."""
    lignes = [l for l in texte.splitlines() if l.strip()]
    ent = [c.strip() for c in lignes[0].split("\t") if c.strip()]
    out = []
    for l in lignes[1:]:
        c = l.split("\t")
        try:
            t = datetime.strptime(c[0].strip() + " " + c[1].strip(), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        vals = [x.strip().replace(",", ".") for x in c[2:] if x.strip() != ""]
        out.append((t, [float(v) if re.match(r"^-?\d+(\.\d+)?$", v) else None for v in vals]))
    out.sort(key=lambda x: x[0])
    return ent[2:], out


def main():
    print("Stations du CEHQ (CSV Données Québec)...")
    brut = get(URL_STATIONS)
    stations = list(csv.DictReader(io.StringIO(brut)))
    compact = []
    for r in stations:
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
        except ValueError:
            continue
        compact.append([r["no"], r["nom"], r["cours_eau"], r["description"], float(r["superficie"] or 0),
                        round(lat, 5), round(lon, 5), r["type"], r["regime"], r["etat"], r["debut"], r["fin"]])
    print(" ", len(compact), "stations")

    structs = charger_structures()
    a_telecharger = {}
    for n in EXEMPLES:
        s = structs[n]
        proches = sorted((dist_km(s["lat"], s["lon"], c[5], c[6]), c[0]) for c in compact if c[9] == "Ouverte")
        for d, no in proches[:4]:
            if d <= 12:
                a_telecharger[no] = d
    print("Fichiers de suivi à télécharger :", sorted(a_telecharger))

    snap = {}
    for no in sorted(a_telecharger):
        time.sleep(1.2)
        try:
            ent, pts = lire_suivi(get(URL_SUIVI.format(no=no)))
        except Exception as e:  # noqa: BLE001
            print("  échec", no, e)
            continue
        if not pts:
            continue
        # heure locale du Québec -> décalage non précisé dans le fichier : on garde l'heure locale telle quelle
        t0 = pts[0][0]
        snap[no] = {
            "cols": ent,                       # ex. ['Niveau', 'Débit']
            "t0": t0.strftime("%Y-%m-%dT%H:%M"),
            "dt": [int((t - t0).total_seconds() // 60) for t, _ in pts],
            "v": [[(v[i] if i < len(v) else None) for _, v in pts] for i in range(len(ent))],
        }
        print("  ", no, ent, len(pts), "points", pts[0][0], "->", pts[-1][0])

    cache = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "sources": {"stations": URL_STATIONS, "suivi": URL_SUIVI},
        "cehq_cols": ["no", "nom", "cours_eau", "description", "superficie_km2", "lat", "lon", "type", "regime", "etat", "debut", "fin"],
        "cehq": compact,
        "snap": snap,
    }
    sortie = CACHE / "hydro-cache.js"
    sortie.write_text("window.HYDRO_CACHE=" + json.dumps(cache, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("Écrit", sortie, round(sortie.stat().st_size / 1024), "Ko")


if __name__ == "__main__":
    sys.exit(main())
