"""Assemble les données embarquées du prototype « Ponts forestiers et ferroviaires ».

Entrées (cache/, produites par fetch_aq.py, osm_fetch.py, extract_nrwn.py) + ../../data/structures.js (MTMD).
Sorties : data-forestiers.js (window.FORESTIERS), data-ferroviaire.js (window.FERRO), cache/stats.json.
Usage : python build.py
"""
import collections, glob, gzip, json, math, re
from datetime import date
from pathlib import Path

ICI = Path(__file__).parent
CACHE = ICI / "cache"
RACINE = ICI.parent.parent
SEUIL_DOUBLON = 30.0   # m : au plus près d'un ouvrage du MTMD

def rect(s, w, n, e):
    return [[s, w], [s, e], [n, e], [n, w]]


# Zones de démonstration : polygones [lat, lon] (pas les limites administratives exactes).
# La Côte-Nord est limitée par une ligne qui suit approximativement l'axe du Saint-Laurent (exclut la rive sud).
POLYS = {
    "slsj": ("Saguenay–Lac-Saint-Jean", rect(47.6, -74.6, 49.5, -69.8)),
    "cote-nord": ("Côte-Nord", [[51.4, -69.8], [51.4, -65.8], [49.9, -65.8], [49.55, -66.6], [49.0, -67.8], [48.6, -68.9], [48.05, -69.8]]),
    "abitibi": ("Abitibi-Témiscamingue", rect(47.6, -79.5, 49.5, -76.0)),
}


def en_polygone(lat, lon, poly):
    """Point dans polygone (lancer de rayon), coordonnées [lat, lon]."""
    dedans = False
    n = len(poly)
    for i in range(n):
        (y1, x1), (y2, x2) = poly[i], poly[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            dedans = not dedans
    return dedans


def bbox_de(poly):
    la = [p[0] for p in poly]; lo = [p[1] for p in poly]
    return (min(la), min(lo), max(la), max(lo))


REGIONS = {k: (v[0], bbox_de(v[1])) for k, v in POLYS.items()}

# --------------------------------------------------------------------------------------------- géométrie
KLAT = 111320.0


def klon(lat):
    return KLAT * math.cos(math.radians(lat))


class Grille:
    """Index spatial de points (lat, lon, payload...) par cases de ~1 km."""
    def __init__(self, pts):
        self.g = collections.defaultdict(list)
        for p in pts:
            self.g[(int(p[0] * 100), int(p[1] * 70))].append(p)

    def proches(self, lat, lon, r=1):
        cx, cy = int(lat * 100), int(lon * 70)
        for dx in range(-r, r + 1):
            for dy in range(-2 * r, 2 * r + 1):
                yield from self.g.get((cx + dx, cy + dy), ())


def dist_pt(lat, lon, p):
    return math.hypot((p[0] - lat) * KLAT, (p[1] - lon) * klon(lat))


def dist_seg(plat, plon, a, b):
    k = klon(plat)
    px, py = plon * k, plat * KLAT
    ax, ay, bx, by = a[1] * k, a[0] * KLAT, b[1] * k, b[0] * KLAT
    dx, dy = bx - ax, by - ay
    d2 = dx * dx + dy * dy
    t = 0.0 if d2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def longueur(coords):
    return sum(math.hypot((b[0] - a[0]) * KLAT, (b[1] - a[1]) * klon(a[0])) for a, b in zip(coords, coords[1:]))


def plus_proche_pt(grille, lat, lon):
    """(distance, payload) du point de la grille le plus proche."""
    best = (1e9, None)
    for p in grille.proches(lat, lon):
        d = dist_pt(lat, lon, p)
        if d < best[0]:
            best = (d, p)
    return best


def dist_ligne_grille(grille, coords):
    """Distance minimale (m) entre une ligne et les points d'une grille, avec le point le plus proche."""
    best = (1e9, None)
    vus = set()
    for (la, lo) in coords:
        for p in grille.proches(la, lo):
            if id(p) in vus:
                continue
            vus.add(id(p))
            if len(coords) == 1:
                d = dist_pt(p[0], p[1], (la, lo))
            else:
                d = min(dist_seg(p[0], p[1], a, b) for a, b in zip(coords, coords[1:]))
            if d < best[0]:
                best = (d, p)
    return best


def dist_ligne_ligne(coords_a, grille_pts_b):
    """Distance minimale entre les sommets d'une ligne A et les sommets (densifiés) indexés de lignes B."""
    best = 1e9
    for (la, lo) in coords_a:
        for p in grille_pts_b.proches(la, lo):
            best = min(best, dist_pt(la, lo, p))
    return best


def densifier(coords, pas=15.0):
    """Ajoute des points intermédiaires tous les ~pas mètres (pour comparer des lignes par leurs sommets)."""
    out = []
    for a, b in zip(coords, coords[1:]):
        n = max(1, int(math.hypot((b[0] - a[0]) * KLAT, (b[1] - a[1]) * klon(a[0])) / pas))
        for i in range(n):
            out.append((a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n))
    out.append(coords[-1])
    return out


def encoder(coords):
    """[lat0, lon0, dlat, dlon, ...] en 1e-5° (≈ 1 m)."""
    pts = [(round(a * 1e5), round(b * 1e5)) for a, b in coords]
    flat = [pts[0][0], pts[0][1]]
    for p, q in zip(pts, pts[1:]):
        flat += [q[0] - p[0], q[1] - p[1]]
    return flat


def simplifier(coords, tol=1.5):
    """Douglas-Peucker (itératif)."""
    n = len(coords)
    if n < 3:
        return coords
    garde = [False] * n
    garde[0] = garde[-1] = True
    pile = [(0, n - 1)]
    while pile:
        i, j = pile.pop()
        dm, k = 0.0, -1
        for m in range(i + 1, j):
            d = dist_seg(coords[m][0], coords[m][1], coords[i], coords[j])
            if d > dm:
                dm, k = d, m
        if dm > tol and k > 0:
            garde[k] = True
            pile += [(i, k), (k, j)]
    return [c for c, g in zip(coords, garde) if g]


def dans_boite(lat, lon, b):
    return b[0] <= lat <= b[2] and b[1] <= lon <= b[3]


def dans_region(lat, lon, k):
    return en_polygone(lat, lon, POLYS[k][1])


def dans_boite_any(lat, lon):
    return any(dans_region(lat, lon, k) for k in POLYS)


# --------------------------------------------------------------------------------------------- MTMD
def charger_mtmd():
    txt = (RACINE / "data" / "structures.js").read_text(encoding="utf8")
    S = json.loads(txt.split("=", 1)[1].rstrip().rstrip(";"))
    ix = {c: i for i, c in enumerate(S["cols"])}
    pts = []
    for r in S["rows"]:
        if r[ix["lat"]] and r[ix["lon"]]:
            obst = r[ix["obst"]] if len(r) > ix["obst"] else None
            pts.append((r[ix["lat"]], r[ix["lon"]], r[ix["num"]], S["enums"]["obst"][obst] if obst is not None else "",
                        r[ix["nom"]], r[ix["route"]], r[ix["obstacle"]]))
    return S, pts


# --------------------------------------------------------------------------------------------- AQréseau+
SRC_AQ = ["AQ", "AQ_FO", "ROUTARD", "DGIG", "Sépaq", "BDTQ"]
ST_AQ = ["O", "INC", "F"]


def charger_aq():
    out = []
    for couche in (1, 2, 3):
        for f in sorted(glob.glob(str(CACHE / f"aq_pont{couche}_*.geojson"))):
            for ft in json.load(open(f, encoding="utf8"))["features"]:
                p = ft["properties"]
                lon, lat = ft["geometry"]["coordinates"]
                src = p["Source"].replace("S�paq", "Sépaq")
                out.append({"lat": lat, "lon": lon, "src": src, "st": p["Stat_Pont"], "id": p["Dossi_Pont"] or "",
                            "cap": p["Cap_Port"] or "", "couche": couche, "version": p["Version"]})
    return out


# --------------------------------------------------------------------------------------------- OSM routes
CLASSES_OSM = ["Chemins et pistes", "Routes locales", "Routes principales", "Sentiers piétons et vélo"]


def classe_osm(hw):
    if hw in ("track", "service"):
        return 0
    if hw in ("unclassified", "residential", "tertiary", "living_street", "tertiary_link", "construction"):
        return 1
    if hw in ("motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link", "secondary_link"):
        return 2
    return 3


BRIDGE_OSM = ["yes", "viaduct", "movable", "trestle", "cantilever", "autre"]


def br_idx(v):
    return BRIDGE_OSM.index(v) if v in BRIDGE_OSM else BRIDGE_OSM.index("autre")


def charger_osm_routes():
    vus = {}
    for k in REGIONS:
        for e in json.load(open(CACHE / f"osm_routes_ponts_{k}.json", encoding="utf8"))["elements"]:
            g = e["geometry"][0]
            if dans_region(g["lat"], g["lon"], k):   # les fichiers bruts couvrent une boîte plus large
                vus[e["id"]] = e
    return list(vus.values())


# --------------------------------------------------------------------------------------------- exploitants ferroviaires
GROUPES_FER = ["CN", "CPKC", "Courtes lignes et industriels", "Autre ou inconnu"]


def groupe_exploitant_osm(*txts):
    t = " ".join(x for x in txts if x).lower()
    if re.search(r"canadien national|canadian national|\bcn\b", t):
        return 0
    if re.search(r"canadien pacifique|canadian pacific|\bcp\b|cpkc|cpr|kansas city", t):
        return 1
    if re.search(r"gatineau|genesee|saint-laurent|st-laurent|st\. lawrence|atlantique|maine|quebec central|baie des chaleurs|"
                 r"charlevoix|roberval|saguenay|cartier|north shore|labrador|romaine|chemin de fer|railway|ciment|csx|"
                 r"tshiuetin|arnaud|port de|port of", t):
        return 2
    return 3


def groupe_exploitant_nrwn(abr):
    """Groupe d'exploitant à partir du sigle (RFN : CN, CPR ; couche du MTMD : CN, CPKC)."""
    if abr == "CN":
        return 0
    if abr in ("CPR", "CPKC"):
        return 1
    if abr in (None, "", "Unknown", "Inconnu", "AMT", "VIA", "EXO", "exo"):
        return 3
    return 2


def est_pont(t):
    return t in ("Pont", "Pont mobile")


def charger_rfn_mtmd():
    """Segments de voie ferrée portant une structure (champ `typstruc`) dans la couche ferroviaire du MTMD (ms:reseau_chfer_qc)."""
    cache = CACHE / "rfn_mtmd_structures.json"
    if not cache.exists():
        d = json.load(open(RACINE / "data" / "raw" / "rail.geojson", encoding="utf8"))
        out = []
        for x in d["features"]:
            p = x["properties"]
            if p.get("typstruc"):
                out.append({"t": p["typstruc"], "pts": [[round(c[0], 5), round(c[1], 5)] for c in x["geometry"]["coordinates"]],
                            "ex": p["nmfrexploi"], "exa": p["siglexploi"], "pr": p["nmfrpropr"], "us": p["typeutilis"], "st": p["etat"],
                            "au": p["nmfruti1vo"], "sub": p["nomsubdiv1"], "cl": p["classvoie"], "ver": p["version"]})
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf8")
    return json.load(open(cache, encoding="utf8"))


def ecrire(nom, var, obj):
    txt = f"window.{var}=" + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (ICI / nom).write_text(txt, encoding="utf8")
    print(nom, round(len(txt.encode("utf8")) / 1e6, 2), "Mo ; gzip", round(len(gzip.compress(txt.encode("utf8"))) / 1e6, 2), "Mo")


def main():
    S, mtmd = charger_mtmd()
    GM = Grille(mtmd)
    print("MTMD", len(mtmd))

    # ---- AQréseau+
    aq = charger_aq()
    print("AQ", len(aq))
    for a in aq:
        d, p = plus_proche_pt(GM, a["lat"], a["lon"])
        a["d"], a["mtmd"] = round(min(d, 999)), (p[2] if p and d < 100 else "")
    GA = Grille([(a["lat"], a["lon"], a) for a in aq])

    # ---- OSM routes
    routes = charger_osm_routes()
    print("OSM routes", len(routes))
    orow = []
    for e in routes:
        co = [(g["lat"], g["lon"]) for g in e["geometry"]]
        t = e["tags"]
        dM, _ = dist_ligne_grille(GM, co)
        dA, _ = dist_ligne_grille(GA, co)
        co2 = simplifier(co)
        orow.append({"id": e["id"], "cls": classe_osm(t["highway"]), "hw": t["highway"], "br": br_idx(t.get("bridge")),
                     "name": t.get("name", ""), "len": round(longueur(co)), "mw": t.get("maxweight", ""),
                     "surf": t.get("surface", ""), "acc": t.get("access", ""), "dM": round(min(dM, 999)),
                     "dA": round(min(dA, 999)), "geom": encoder(co2), "c": co})
    # ---- AQ ↔ OSM (position confirmée par un pont OSM à moins de 50 m)
    pts_osm = []
    for o in orow:
        for (la, lo) in densifier(o["c"], 10):
            pts_osm.append((la, lo, o))
    GO = Grille(pts_osm)
    for a in aq:
        if dans_boite_any(a["lat"], a["lon"]):
            d, _ = plus_proche_pt(GO, a["lat"], a["lon"])
            a["dosm"] = round(min(d, 999))
        else:
            a["dosm"] = None

    # ---- écriture data-forestiers.js
    rows = []
    for a in aq:
        rows.append([round(a["lat"], 5), round(a["lon"], 5), SRC_AQ.index(a["src"]), ST_AQ.index(a["st"]) if a["st"] in ST_AQ else 1,
                     round(min(a["d"], 999)), a["id"], a["cap"], a["mtmd"],
                     a["dosm"] if a["dosm"] is not None else -1])
    F = {"generated": date.today().isoformat(), "version": aq[0]["version"] if aq else "",
         "regions": {k: {"nom": v[0], "poly": v[1], "bbox": list(bbox_de(v[1]))} for k, v in POLYS.items()},
         "aq": {"srcs": SRC_AQ, "sts": ST_AQ, "cols": ["lat", "lon", "src", "st", "d", "id", "cap", "mtmd", "dosm"], "rows": rows},
         "osm": {"cls": CLASSES_OSM, "br": BRIDGE_OSM,
                 "cols": ["id", "cls", "hw", "br", "name", "len", "mw", "surf", "acc", "dM", "dA", "geom"],
                 "rows": [[o["id"], o["cls"], o["hw"], o["br"], o["name"], o["len"], o["mw"], o["surf"], o["acc"], o["dM"], o["dA"], o["geom"]]
                          for o in orow]}}
    ecrire("data-forestiers.js", "FORESTIERS", F)

    # ---- ferroviaire
    nr = charger_rfn_mtmd()
    osm_rail = json.load(open(CACHE / "osm_rail_bridges_qc.json", encoding="utf8"))["elements"]
    nrows = []
    for x in nr:
        co = [(p[1], p[0]) for p in x["pts"]]
        d, p = dist_ligne_grille(GM, co)
        nrows.append({"t": x["t"], "geo": "ligne", "co": co, "ex": x.get("ex") or "", "exa": x.get("exa") or "",
                      "pr": x.get("pr") or "", "us": x.get("us") or "", "st": x.get("st") or "", "au": x.get("au") or "",
                      "sub": x.get("sub") or "", "cl": x.get("cl") or "", "len": round(longueur(co)), "dM": round(min(d, 999)),
                      "mn": p[2] if p and round(d) < SEUIL_DOUBLON else "", "mo": (p[3] if p and round(d) < SEUIL_DOUBLON else "") or ""})
    orail = []
    for e in osm_rail:
        co = [(g["lat"], g["lon"]) for g in e["geometry"]]
        t = e["tags"]
        d, p = dist_ligne_grille(GM, co)
        orail.append({"id": e["id"], "br": t.get("bridge", ""), "name": t.get("name", ""), "op": t.get("operator", ""),
                      "ow": t.get("owner", ""), "us": t.get("usage", ""), "sv": t.get("service", ""), "len": round(longueur(co)),
                      "ly": t.get("layer", ""), "co": co, "dM": round(min(d, 999)),
                      "mn": p[2] if p and d < SEUIL_DOUBLON else "", "mo": (p[3] if p and d < SEUIL_DOUBLON else "") or "",
                      "g": groupe_exploitant_osm(t.get("operator"), t.get("owner"))})
    # lien NRWN ↔ OSM (< 30 m, comparaison par sommets densifiés)
    GOr = Grille([(la, lo, i) for i, o in enumerate(orail) for (la, lo) in densifier(o["co"], 10)])
    GNr = Grille([(la, lo, i) for i, n in enumerate(nrows) if est_pont(n["t"])
                  for (la, lo) in densifier(n["co"], 10)])
    for n in nrows:
        n["dO"] = round(min(dist_ligne_ligne(densifier(n["co"], 15), GOr), 999)) if est_pont(n["t"]) else -1
    for o in orail:
        o["dN"] = round(min(dist_ligne_ligne(densifier(o["co"], 15), GNr), 999))
    FE = {"generated": date.today().isoformat(), "groupes": GROUPES_FER,
          "nrwn": {"cols": ["type", "geo", "grp", "exploitant", "proprietaire", "usage", "statut", "autre", "subdiv", "classe", "len", "dM", "mtmd", "mtmdObst", "dO", "geom"],
                   "rows": [[n["t"], n["geo"], groupe_exploitant_nrwn(n["exa"]), n["ex"], n["pr"], n["us"], n["st"], n["au"], n["sub"], n["cl"],
                             n["len"], n["dM"], n["mn"], n["mo"], n["dO"], encoder(n["co"])] for n in nrows]},
          "osm": {"cols": ["id", "bridge", "name", "operator", "owner", "usage", "service", "len", "layer", "grp", "dM", "mtmd", "mtmdObst", "dN", "geom"],
                  "rows": [[o["id"], o["br"], o["name"], o["op"], o["ow"], o["us"], o["sv"], o["len"], o["ly"], o["g"], o["dM"], o["mn"], o["mo"], o["dN"],
                            encoder(simplifier(o["co"]))] for o in orail]}}
    ecrire("data-ferroviaire.js", "FERRO", FE)

    stats(S, mtmd, aq, orow, nrows, orail)


# --------------------------------------------------------------------------------------------- statistiques pour le rapport
def stats(S, mtmd, aq, orow, nrows, orail):
    C = collections.Counter
    st = {}
    st["mtmd_total"] = len(mtmd)
    st["mtmd_obst"] = dict(C(p[3] for p in mtmd))
    st["aq_total"] = len(aq)
    st["aq_par_couche"] = dict(C(a["couche"] for a in aq))
    st["aq_par_source"] = dict(C(a["src"] for a in aq))
    st["aq_doublons_30"] = sum(1 for a in aq if a["d"] < SEUIL_DOUBLON)
    st["aq_doublons_100"] = sum(1 for a in aq if a["d"] < 100)
    st["aq_par_source_doublons"] = {s: sum(1 for a in aq if a["src"] == s and a["d"] < SEUIL_DOUBLON) for s in SRC_AQ}
    st["aq_hors_mtmd_par_source"] = {s: sum(1 for a in aq if a["src"] == s and a["d"] >= SEUIL_DOUBLON) for s in SRC_AQ}
    hors = [a for a in aq if a["d"] >= SEUIL_DOUBLON]
    st["aq_hors_mtmd_total"] = len(hors)
    st["aq_hors_mtmd_statut"] = dict(C(a["st"] for a in hors))
    st["aq_hors_mtmd_cap_connue"] = sum(1 for a in hors if a["cap"] not in ("", "INC", "--") and not set(a["cap"].replace("-", "")) <= {"0"})
    st["aq_hors_mtmd_cap_nulle"] = sum(1 for a in hors if a["cap"] and set(a["cap"].replace("-", "")) <= {"0"})
    st["aq_hors_mtmd_id_pattern"] = dict(C(re.sub(r"\d", "9", a["id"] or "None") for a in hors).most_common(8))
    st["regions"] = {}
    for k in POLYS:
        r = {}
        ok = lambda la, lo, k=k: dans_region(la, lo, k)
        aqr = [a for a in aq if ok(a["lat"], a["lon"])]
        r["mtmd"] = sum(1 for p in mtmd if ok(p[0], p[1]))
        r["aq_total"] = len(aqr)
        r["aq_hors_mtmd"] = sum(1 for a in aqr if a["d"] >= SEUIL_DOUBLON)
        r["aq_hors_par_source"] = dict(C(a["src"] for a in aqr if a["d"] >= SEUIL_DOUBLON))
        r["aq_dup_par_source"] = dict(C(a["src"] for a in aqr if a["d"] < SEUIL_DOUBLON))
        fo = [a for a in aqr if a["d"] >= SEUIL_DOUBLON and a["src"] in ("ROUTARD", "AQ_FO", "DGIG")]
        r["aq_fo_total"] = len(fo)
        r["aq_fo_osm_50"] = sum(1 for a in fo if a.get("dosm") is not None and a["dosm"] <= 50)
        orr = [o for o in orow if ok(o["c"][0][0], o["c"][0][1])]
        r["osm_total"] = len(orr)
        r["osm_par_classe"] = dict(C(CLASSES_OSM[o["cls"]] for o in orr))
        r["osm_hors_mtmd_ni_aq"] = dict(C(CLASSES_OSM[o["cls"]] for o in orr if o["dM"] >= SEUIL_DOUBLON and o["dA"] >= SEUIL_DOUBLON))
        r["osm_tags"] = {"name": sum(1 for o in orr if o["name"]), "maxweight": sum(1 for o in orr if o["mw"]), "surface": sum(1 for o in orr if o["surf"])}
        r["osm_longueur_moy_m"] = round(sum(o["len"] for o in orr) / max(1, len(orr)), 1)
        r["rail_rfn"] = sum(1 for n in nrows if est_pont(n["t"]) and ok(n["co"][0][0], n["co"][0][1]))
        r["rail_osm"] = sum(1 for o in orail if ok(o["co"][0][0], o["co"][0][1]))
        st["regions"][k] = r
    st["osm_total_3_regions"] = len(orow)
    ponts = [n for n in nrows if est_pont(n["t"])]
    st["rfn_types"] = dict(C(n["t"] for n in nrows))
    st["rfn_ponts"] = len(ponts)
    st["rfn_groupes"] = dict(C(GROUPES_FER[groupe_exploitant_nrwn(n["exa"])] for n in ponts))
    st["rfn_exploitants"] = dict(C(n["exa"] for n in ponts).most_common(15))
    st["rfn_proprietaires"] = dict(C(n["pr"] for n in ponts).most_common(8))
    st["rfn_statut"] = dict(C(n["st"] for n in ponts))
    st["rfn_long_totale_m"] = sum(n["len"] for n in ponts)
    st["rfn_long_moy_m"] = round(st["rfn_long_totale_m"] / len(ponts), 1)
    mtq = [n for n in ponts if "Transports" in n["pr"]]
    st["rfn_mtq_ponts"] = len(mtq)
    st["rfn_mtq_avec_ouvrage_mtmd_30"] = sum(1 for n in mtq if n["mn"])
    st["rfn_mtmd_30"] = sum(1 for n in ponts if n["mn"])
    st["rfn_mtmd_30_obst"] = dict(C(n["mo"] for n in ponts if n["mn"]))
    st["rfn_osm_30"] = sum(1 for n in ponts if n["dO"] < 30)
    try:
        nr = json.load(open(CACHE / "nrwn_structures.json", encoding="utf8"))
        st["nrwn_types"] = dict(C(x["type"] for x in nr))
    except OSError:
        pass
    st["osm_rail_total"] = len(orail)
    st["osm_rail_groupes"] = dict(C(GROUPES_FER[o["g"]] for o in orail))
    st["osm_rail_bridge_type"] = dict(C(o["br"] for o in orail))
    st["osm_rail_long_totale_m"] = sum(o["len"] for o in orail)
    st["osm_rail_mtmd_30"] = sum(1 for o in orail if o["mn"])
    st["osm_rail_mtmd_30_obst"] = dict(C(o["mo"] for o in orail if o["mn"]))
    st["osm_rail_rfn_30"] = sum(1 for o in orail if o["dN"] < 30)
    st["osm_rail_tags"] = {k: sum(1 for o in orail if o[k]) for k in ("name", "op", "ow", "us", "ly")}
    (CACHE / "stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf8")
    print(json.dumps(st, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
