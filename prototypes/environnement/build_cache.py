# -*- coding: utf-8 -*-
"""Précalcul du prototype « Zones sensibles » (QuickerAtlasOA).

Pourquoi : le serveur GeoServer du MRNF qui publie les habitats fauniques (Habitat_legal, Habitat_informationnel)
répond 403 à toute requête portant un en-tête Origin (donc à toute requête de navigateur faite depuis une autre
origine) et n'envoie pas d'en-tête CORS. Une page web ne peut donc pas l'interroger. On le fait ici, une fois,
pour les ouvrages d'exemple, et on range les polygones (simplifiés) dans cache/environnement-cache.js.

On y met aussi les fiches de métadonnées de Données Québec (licence, date de mise à jour) des jeux de données
utilisés : c'est la source de la ligne « source · licence · date » du tableau.

Réseau poli : 1 requête par seconde par hôte, une quinzaine de requêtes au total.

Usage :  python build_cache.py
"""
import json, math, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parents[1]
CACHE = ICI / "cache"
CACHE.mkdir(exist_ok=True)

# Le GeoServer du MRNF refuse (connexion coupée) les clients qui n'ont pas l'air d'un navigateur : on s'identifie
# quand même, comme le fait l'ETL de l'atlas.
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QuickerAtlasOA-proto/0.1 (cheruelanthony@gmail.com)"}
GEOSERVER = "https://servicesvecto3.mern.gouv.qc.ca/geoserver/Habitats_Fauniques_Pub/{couche}/ows"
CKAN = "https://www.donneesquebec.ca/recherche/api/3/action/package_show?id="
# Jeux de données Données Québec (identifiants CKAN) cités dans le tableau
JEUX = {
    "habitats-fauniques": "Habitats fauniques",
    "aires-protegees-au-quebec": "Registre des aires protégées et des AMCE",
    "habitats-floristiques": "Habitats floristiques",
    "occurrences-especes-en-situation-precaire": "Occurrences d'espèces en situation précaire (CDPNQ)",
    "milieux-humides-du-quebec": "Milieux humides, cartographie détaillée",
    "milieux-humides-potentiels": "Milieux humides potentiels",
    "especes-exotiques-envahissantes": "Sentinelle, espèces exotiques envahissantes",
    "base-de-donnees-des-zones-inondables": "Base de données des zones à risque d'inondation (BDZI)",
    "refuge-biologique-designe-et-en-projet": "Refuges biologiques",
    "ecosysteme-forestier-exceptionnel-efe": "Écosystèmes forestiers exceptionnels",
}
# Ouvrages d'exemple (n° de structure) ; les six premiers sont les cas « vedettes » de la page
EXEMPLES = ["14945", "12985", "11726E", "03575", "18136", "14464E", "15382", "14240JH"]
RAYON_DEG = 0.03          # demi-hauteur de la boîte de recherche (≈ 3,3 km) ; la page affiche au plus 2 km
TOLERANCE_M = 6           # simplification de Douglas-Peucker
CHAMPS = ["CODE_HAFA", "CATEGORIE", "ESPECE", "TOPONYME", "STATUT", "REG_FAUNE", "ANNEE_INV", "SUP_HA", "DA_ENT_VIG", "NO_HABITAT", "DOMANIALIT"]

_dernier = {}


def get(url):
    hote = urllib.parse.urlsplit(url).netloc
    d = _dernier.get(hote, 0) + 1.2 - time.monotonic()
    if d > 0:
        time.sleep(d)
    _dernier[hote] = time.monotonic()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def charger_structures():
    s = (RACINE / "data" / "structures.js").read_text(encoding="utf-8")
    j = json.loads(s[s.index("=") + 1:].rstrip().rstrip(";"))
    return {r[0]: dict(zip(j["cols"], r)) for r in j["rows"]}


def dp(pts, tol_deg_x, tol_deg_y):
    """Douglas-Peucker itératif sur des points (lon, lat) ; la tolérance est exprimée en m via l'échelle locale."""
    if len(pts) < 5:
        return pts
    kx, ky = 1.0 / tol_deg_x, 1.0 / tol_deg_y   # degrés -> unités de tolérance
    garde = [False] * len(pts)
    garde[0] = garde[-1] = True
    pile = [(0, len(pts) - 1)]
    while pile:
        a, b = pile.pop()
        ax, ay, bx, by = pts[a][0] * kx, pts[a][1] * ky, pts[b][0] * kx, pts[b][1] * ky
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        pire, ip = 0.0, -1
        for i in range(a + 1, b):
            px, py = pts[i][0] * kx - ax, pts[i][1] * ky - ay
            if L2 == 0:
                d = math.hypot(px, py)
            else:
                t = max(0.0, min(1.0, (px * dx + py * dy) / L2))
                d = math.hypot(px - t * dx, py - t * dy)
            if d > pire:
                pire, ip = d, i
        if pire > 1.0 and ip > 0:
            garde[ip] = True
            pile.append((a, ip))
            pile.append((ip, b))
    return [p for p, g in zip(pts, garde) if g]


def simplifier(geom, lat):
    """MultiPolygon GeoJSON (4326) -> anneaux simplifiés, coordonnées arrondies à 5 décimales (~1 m)."""
    tx = TOLERANCE_M / (111320.0 * math.cos(math.radians(lat)))
    ty = TOLERANCE_M / 111320.0
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    out = []
    for poly in polys:
        anneaux = []
        for i, ring in enumerate(poly):
            r = dp(ring, tx, ty)
            if len(r) >= 4:
                anneaux.append([[round(x, 5), round(y, 5)] for x, y in r])
            elif i == 0:
                break   # contour trop petit : on garde au moins un point plus loin
        if anneaux:
            out.append(anneaux)
    return out


def habitats(couche, lat, lon):
    q = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "Habitats_Fauniques_Pub:" + couche,
         "outputFormat": "application/json", "srsName": "EPSG:4326",
         "bbox": "%f,%f,%f,%f,urn:ogc:def:crs:EPSG::4326" % (lat - RAYON_DEG, lon - RAYON_DEG * 1.45, lat + RAYON_DEG, lon + RAYON_DEG * 1.45)}
    return json.loads(get(GEOSERVER.format(couche=couche) + "?" + urllib.parse.urlencode(q)))["features"]


def main():
    structs = charger_structures()
    sortie = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "rayon_deg": RAYON_DEG, "tolerance_m": TOLERANCE_M,
              "sources": {"Habitat_legal": GEOSERVER.format(couche="Habitat_legal"), "Habitat_informationnel": GEOSERVER.format(couche="Habitat_informationnel")},
              "habitats": {}, "jeux": {}}
    for num in EXEMPLES:
        s = structs[num]
        lst = []
        vus = set()
        for couche in ("Habitat_legal", "Habitat_informationnel"):
            for f in habitats(couche, s["lat"], s["lon"]):
                p = f["properties"]
                cle = (p.get("NO_HABITAT"), p.get("HFA_NO_SEQ"))
                if cle in vus or not f.get("geometry"):
                    continue
                vus.add(cle)
                g = simplifier(f["geometry"], s["lat"])
                if g:
                    lst.append({"p": {k: p.get(k) for k in CHAMPS}, "g": g})
        sortie["habitats"][num] = lst
        print(num, s["route"], "->", len(lst), "habitats", sorted({x["p"]["CATEGORIE"].strip() for x in lst}))
    for slug in JEUX:
        try:
            r = json.loads(get(CKAN + slug))["result"]
            sortie["jeux"][slug] = {"titre": r.get("title"), "licence": r.get("license_title"), "maj": (r.get("metadata_modified") or "")[:10],
                                    "frequence": r.get("frequence_maj") or r.get("update_frequency"), "url": "https://www.donneesquebec.ca/recherche/dataset/" + slug}
            print(" ", slug, sortie["jeux"][slug]["licence"], sortie["jeux"][slug]["maj"])
        except Exception as e:  # noqa: BLE001
            print("  échec", slug, e)
    fichier = CACHE / "environnement-cache.js"
    fichier.write_text("window.ENV_CACHE=" + json.dumps(sortie, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("Écrit", fichier, round(fichier.stat().st_size / 1024), "Ko")


if __name__ == "__main__":
    sys.exit(main())
