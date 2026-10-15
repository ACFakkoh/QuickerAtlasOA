"""Couches de lignes du visualiseur : réseau routier (RTSS) et réseau ferroviaire.

Sources (WFS du MTMD, Données Québec, CC-BY 4.0) :
  - `ms:bgr_v_sous_route_res_sup_act` : « Réseau routier - RTSS » (~12 600 segments)
  - `ms:reseau_chfer_qc`              : « Réseau ferroviaire »    (~12 700 segments)

Sortie : `data/couche-rtss.js` et `data/couche-rail.js`, chargés par `<script src>` (donc compatibles
`file://`). Chaque fichier ajoute une entrée à `window.PQ_COUCHES` :

    {"generated", "titre", "attribution",
     "classes": [{"label", "color", "weight"}, ...],          # ordre = ordre de légende
     "labels":  ["Autoroute 10", ...],                         # libellés d'infobulle dédupliqués
     "lines":   [[classIdx, labelIdx, flag, lat0, lon0, dlat1, dlon1, ...], ...]}

Coordonnées : entiers = degrés × 1e5 (≈ 1 m), ordre **lat, lon** ; première paire absolue, suivantes en
deltas. `flag` : bit 1 = RSSCE estimé (voir `drapeau_rssce`). Les lignes sont écrites de la
classe la moins importante à la plus importante, pour qu'un rendu « dans l'ordre » dessine l'important dessus.

Ponts ferroviaires (couche `rail` seulement, clés ajoutées SANS toucher à `lines` : les ponts restent dans les
voies dessinées). Ils viennent du champ `typstruc` (« Pont », « Pont mobile » ; les tunnels sont exclus) :

    "ponts":         [[groupe, exploitantIdx, proprietaireIdx, longueur_m, nomIdx|null, mobile,
                       lat0, lon0, dlat1, dlon1, ...], ...],
    "ponts_labels":  ["Canadien National", "Ministère des Transports du Québec", "Pont de Québec", ...],
    "ponts_groupes": ["CN", "CPKC", "Autre (courtes lignes, industriels, inconnu)"],
    "ponts_attribution": "Noms de ponts : © contributeurs OpenStreetMap (ODbL)"

  - `groupe` : 0 = CN, 1 = CPKC, 2 = autre (courtes lignes, industriels, inconnu), d'après l'exploitant
    (`nmfrexploi`, puis son sigle `siglexploi`) ou, quand l'exploitant est absent (« Aucun », « Inconnu »,
    vide), le propriétaire (`nmfrpropr`) ; table explicite `GROUPE_DE_EXPLOITANT`. Exemple : « Ottawa Valley
    Railway » (sigle CP/OVR) est un exploitant distinct → groupe 2, même si la voie appartient au CPKC.
  - `exploitantIdx`, `proprietaireIdx` : indices dans `ponts_labels` (« Exploitant inconnu » /
    « Propriétaire inconnu » quand la source n'en donne pas) ; `nomIdx` : indice du nom du pont dans
    `ponts_labels`, ou null (voir ci-dessous) ; `mobile` : 1 si au moins un segment est un « Pont mobile ».
  - `longueur_m` : longueur de la géométrie d'ORIGINE (non simplifiée), en mètres entiers (approximation
    ellipsoïdale WGS84 locale), somme des segments fusionnés. Ce n'est pas une longueur d'ouvrage mesurée.
  - Fusion : les segments de pont du même exploitant dont les extrémités sont à 2 m ou moins sont un seul
    pont (même ouvrage à plusieurs travées, coupé en segments). Une chaîne ramifiée (aiguillage sur le pont)
    est écrite en autant d'entrées que de chaînes continues.
  - Coordonnées : mêmes entiers lat, lon (degrés × 1e5) et même encodage delta que `lines` ; géométrie
    simplifiée légèrement (tolérance `TOLERANCE_PONT_M` = 2 m), au moins 2 points.
  - `nom` (OpenStreetMap, ODbL) : `bridge:name` d'un pont OSM (`railway=rail` + `bridge=*`, cache
    `data/raw/osm_rail_bridges_qc.json`) à 30 m ou moins du milieu du pont ; à défaut, `name` seulement s'il
    désigne un pont (« Pont … », « … Bridge ») et non une subdivision. En pratique le `name` OSM des voies
    ferrées est presque toujours la subdivision (« Subdivision Parc »), pas un nom de pont : peu de ponts
    sont nommés. Cache par défaut ; `--osm-refresh` relance la requête Overpass.

Usage : python -m etl.reseaux [--only rtss,rail] [--no-fetch] [--tolerance 25] [--osm-refresh]
"""
import argparse
import json
import logging
import math
import re
import sys
import unicodedata
from datetime import date

from . import net
from .config import DATA_DIR, RAW_DIR, WFS_BASE

log = logging.getLogger(__name__)

ECHELLE = 100_000                  # degrés → entiers (1e-5° ≈ 1,11 m en latitude)
M_PAR_UNITE = 1.1132               # mètres par unité entière en latitude
TOLERANCE_M = 10.0                 # tolérance Douglas-Peucker (calibrée : 10 m = 0,9 + 0,3 Mo, sous la cible de 4 Mo)
FLAG_RSSCE = 1                     # bit 1 du champ `flag`

_WFS_GEOJSON = (f"{WFS_BASE}?service=wfs&version=2.0.0&request=getfeature"
                "&typename={typename}&srsname=EPSG:4326&outputformat=geojson")


# --- Définition des couches -----------------------------------------------------------------------
# Palette routière sobre (v0.6.0, à la demande : les teintes vives se mêlaient aux couleurs des ouvrages) : une seule
# famille gris-bleu, de l'ardoise foncée (autoroutes) au gris clair (réseau local) ; la couleur reste aux ouvrages.
CLASSES_RTSS = [
    # La hiérarchie se lit d'abord par l'épaisseur, la clarté et les tirets (lisible par les personnes daltoniennes),
    # la teinte n'est qu'un complément. Traits affinés en v0.5.5 (l'autoroute à 4,5 px masquait la carte).
    {"label": "Autoroute", "color": "#34495a", "weight": 2.8},
    {"label": "Nationale", "color": "#52687a", "weight": 2.2},
    {"label": "Régionale", "color": "#71848f", "weight": 1.7},
    {"label": "Collectrice", "color": "#86969f", "weight": 1.3, "dash": "7 3"},
    {"label": "Accès aux ressources", "color": "#97a4ab", "weight": 1.2, "dash": "2 3"},
    {"label": "Local (1 à 3)", "color": "#a5b1b8", "weight": 1},
    {"label": "Sans classe", "color": "#a5b1b8", "weight": 1, "dash": "1 2"},        # bretelles, virages en U, etc.
]
# des_clasf_ du WFS → libellé de classe ci-dessus (regroupements pour une légende lisible)
CLASSE_RTSS_DE = {
    "Autoroute": "Autoroute",
    "Nationale": "Nationale",
    "Régionale": "Régionale",
    "Collectrice": "Collectrice",
    "Accès aux ressources": "Accès aux ressources",
    "Accès aux ressources et aux localités isolées": "Accès aux ressources",
    "Local 1": "Local (1 à 3)",
    "Local 2": "Local (1 à 3)",
    "Local 3": "Local (1 à 3)",
    "Sans classe": "Sans classe",
}

# Rail : le visualiseur ajoute des traverses (tirets perpendiculaires) à toutes les classes, pour ne pas le
# confondre avec une route ; la classe se lit ensuite par la couleur et les tirets de la ligne.
CLASSES_RAIL = [
    {"label": "Voyageurs (seul ou mixte)", "color": "#0072b2", "weight": 2.8},
    {"label": "Marchandises", "color": "#37474f", "weight": 2.2},
    {"label": "Touristique", "color": "#8e24aa", "weight": 2, "dash": "8 3"},
    {"label": "Opérationnel, usage inconnu", "color": "#78909c", "weight": 1.5},
    {"label": "Inexploité", "color": "#f59e0b", "weight": 1.5, "dash": "4 3"},
    {"label": "Abandonné", "color": "#d81b60", "weight": 1.5, "dash": "1 3"},
    {"label": "État inconnu", "color": "#9e9e9e", "weight": 1, "dash": "2 2"},
]
USAGE_RAIL = {                       # typeutilis → classe (pour les voies opérationnelles)
    "Voyageurs": "Voyageurs (seul ou mixte)",
    "Marchandises et voyageurs": "Voyageurs (seul ou mixte)",
    "Marchandises": "Marchandises",
    "Touristique": "Touristique",
    "Marchandises et touristique": "Touristique",
}

COUCHES = {
    "rtss": {
        "typename": "ms:bgr_v_sous_route_res_sup_act", "raw": "rtss.geojson", "fichier": "couche-rtss.js",
        "titre": "Réseau routier (RTSS)", "classes": CLASSES_RTSS,
        "attribution": "Réseau routier : MTMD / Données Québec (CC-BY 4.0)",
    },
    "rail": {
        "typename": "ms:reseau_chfer_qc", "raw": "rail.geojson", "fichier": "couche-rail.js",
        "titre": "Réseau ferroviaire", "classes": CLASSES_RAIL,
        "attribution": "Réseau ferroviaire : MTMD / Données Québec (CC-BY 4.0)",
    },
}


# --- Géométrie : Douglas-Peucker en Python pur ----------------------------------------------------
def _dist_segment(p, a, b) -> float:
    """Distance du point `p` au segment [a, b] (plan cartésien)."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    d2 = dx * dx + dy * dy
    if d2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def douglas_peucker(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Simplifie une polyligne (plan cartésien) ; conserve toujours les deux extrémités.

    Version itérative (pas de récursion : certaines lignes fusionnées ont des dizaines de milliers de points).
    Tout point supprimé reste à une distance ≤ `tol` de la ligne simplifiée.
    """
    n = len(pts)
    if n < 3:
        return list(pts)
    garde = [False] * n
    garde[0] = garde[-1] = True
    pile = [(0, n - 1)]
    while pile:
        i, j = pile.pop()
        a, b = pts[i], pts[j]
        dmax, imax = -1.0, -1
        for k in range(i + 1, j):
            d = _dist_segment(pts[k], a, b)
            if d > dmax:
                dmax, imax = d, k
        if dmax > tol:
            garde[imax] = True
            pile.append((i, imax))
            pile.append((imax, j))
    return [p for p, g in zip(pts, garde) if g]


def simplifier(pts: list[tuple[int, int]], tol_m: float) -> list[tuple[int, int]]:
    """Douglas-Peucker sur des points entiers (lat, lon) ; la longitude est corrigée par cos(latitude)."""
    if len(pts) < 3:
        return list(pts)
    lat_moy = sum(p[0] for p in pts) / len(pts) / ECHELLE
    k = math.cos(math.radians(lat_moy))
    plan = [(lat, lon * k) for lat, lon in pts]
    garde = douglas_peucker(plan, tol_m / M_PAR_UNITE)
    # on retrouve les points d'origine (les tuples du plan sont dans le même ordre que `pts`)
    out, j = [], 0
    for q in garde:
        while plan[j] is not q:
            j += 1
        out.append(pts[j])
    return out


def quantifier(coords) -> list[tuple[int, int]]:
    """[[lon, lat], ...] → [(lat_e5, lon_e5), ...] sans points consécutifs identiques."""
    out: list[tuple[int, int]] = []
    for lon, lat in coords:
        p = (round(lat * ECHELLE), round(lon * ECHELLE))
        if not out or out[-1] != p:
            out.append(p)
    return out


def fusionner(lignes: dict[int, tuple[tuple, list]]) -> list[tuple[tuple, list]]:
    """Joint bout à bout les lignes de même clé (classe, libellé, drapeau) dont les extrémités coïncident.

    `lignes` : id → (clé, points). Renvoie [(clé, points)], les lignes jointes pouvant être inversées.
    """
    bouts: dict[tuple, list[int]] = {}
    for i, (cle, pts) in lignes.items():
        for p in {pts[0], pts[-1]}:
            bouts.setdefault((cle, p), []).append(i)
    utilise: set[int] = set()

    def voisin(cle, p):
        for j in bouts.get((cle, p), ()):
            if j not in utilise:
                return j
        return None

    def prolonger(cle, chaine):
        while True:
            j = voisin(cle, chaine[-1])
            if j is None:
                return chaine
            utilise.add(j)
            pts = lignes[j][1]
            if pts[0] != chaine[-1]:
                pts = pts[::-1]
            chaine.extend(pts[1:])

    out = []
    for i, (cle, pts) in lignes.items():
        if i in utilise:
            continue
        utilise.add(i)
        chaine = prolonger(cle, list(pts))
        chaine.reverse()
        chaine = prolonger(cle, chaine)
        out.append((cle, chaine))
    return out


# --- Encodage delta -------------------------------------------------------------------------------
def encoder_ligne(classe: int, libelle: int, flag: int, pts: list[tuple[int, int]]) -> list[int]:
    """[classe, libellé, flag, lat0, lon0, dlat1, dlon1, ...] (première paire absolue, ensuite deltas)."""
    out = [classe, libelle, flag, pts[0][0], pts[0][1]]
    for (a, b), (c, d) in zip(pts, pts[1:]):
        out += [c - a, d - b]
    return out


def decoder_ligne(ligne: list[int]) -> tuple[int, int, int, list[tuple[int, int]]]:
    """Inverse de `encoder_ligne` → (classe, libellé, flag, [(lat_e5, lon_e5), ...])."""
    classe, libelle, flag, lat, lon = ligne[:5]
    pts = [(lat, lon)]
    for k in range(5, len(ligne), 2):
        lat += ligne[k]
        lon += ligne[k + 1]
        pts.append((lat, lon))
    return classe, libelle, flag, pts


# --- Parsing des entités --------------------------------------------------------------------------
def _txt(v) -> str:
    return (v or "").strip() if isinstance(v, str) else ""


# Routes nationales retenues pour le RSSCE estimé : grands corridors d'échanges avec l'Ontario (117), le Saguenay (175),
# le Maine (173), le Vermont (133) et le Nouveau-Brunswick (185). Avec toutes les autoroutes et leurs bretelles, on
# obtient ≈ 8 100 km de chaussées, comme le RSSCE officiel (8 046 à 8 104 km selon les bilans du MTMD).
NATIONALES_RSSCE = {117, 175, 173, 133, 185}


def drapeau_rssce(props: dict, numeros_autoroutes: set[int] = frozenset()) -> int:
    """Bit RSSCE **estimé** d'un segment RTSS (1 = probablement dans le RSSCE).

    Le MTMD ne publie pas la géométrie du RSSCE (ni attribut dans le WFS RTSS, ni couche dédiée, ni jeu sur Données
    Québec) : il n'est défini que dans les bilans de l'état des chaussées (« constitué essentiellement des autoroutes
    et d'une partie des routes nationales », ≈ 8 100 km). Estimation : toutes les autoroutes, leurs bretelles (sans
    classe, même n°) et les routes nationales de `NATIONALES_RSSCE`.
    """
    num = _txt(props.get("num_route"))
    n = int(num) if num.isdigit() else 0
    classe = _txt(props.get("des_clasf_"))
    if classe == "Autoroute" or (classe == "Sans classe" and n in numeros_autoroutes):
        return FLAG_RSSCE
    return FLAG_RSSCE if classe == "Nationale" and n in NATIONALES_RSSCE else 0


def _libelle_rtss(props: dict, numeros_autoroutes: set[int]) -> str:
    """« Autoroute 20 », « Route 117 » ; à défaut de numéro de route (≥ 1000), le nom indicatif de la sous-route."""
    num = _txt(props.get("num_route"))
    n = int(num) if num.isdigit() else 0
    if 0 < n < 1000:
        autoroute = props.get("des_clasf_") == "Autoroute" or (
            props.get("des_clasf_") == "Sans classe" and n in numeros_autoroutes)
        return f"Autoroute {n}" if autoroute else f"Route {n}"
    return _txt(props.get("nom_sous_r")) or (f"Route {n}" if n else "Sans nom")


def _classe_rail(props: dict) -> str:
    etat = _txt(props.get("etat"))
    if etat == "Opérationnel":
        return USAGE_RAIL.get(_txt(props.get("typeutilis")), "Opérationnel, usage inconnu")
    return etat if etat in ("Inexploité", "Abandonné") else "État inconnu"


def _libelle_rail(props: dict) -> str:
    exploitant = _txt(props.get("nmfrexploi"))
    subdiv = _txt(props.get("nomsubdiv1"))
    if subdiv.lower() == "aucun":
        subdiv = ""
    return " · ".join(x for x in (exploitant, subdiv and f"subdivision {subdiv}") if x) or "Exploitant inconnu"


def _parties(geom: dict | None):
    """LineString → 1 partie ; MultiLineString → 1 partie par ligne ; le reste est ignoré."""
    if not geom:
        return
    if geom["type"] == "LineString":
        yield geom["coordinates"]
    elif geom["type"] == "MultiLineString":
        yield from geom["coordinates"]


def parse_rtss(geojson: dict) -> list[tuple[str, str, int, list]]:
    """GeoJSON RTSS → [(classe, libellé, drapeau, coordonnées [lon, lat]), ...], une entrée par partie."""
    feats = geojson["features"]
    autoroutes = {int(p["num_route"]) for f in feats if (p := f["properties"]).get("des_clasf_") == "Autoroute"
                  and _txt(p.get("num_route")).isdigit()}
    out = []
    for f in feats:
        p = f["properties"]
        classe = CLASSE_RTSS_DE.get(_txt(p.get("des_clasf_")), "Sans classe")
        for coords in _parties(f.get("geometry")):
            out.append((classe, _libelle_rtss(p, autoroutes), drapeau_rssce(p, autoroutes), coords))
    return out


def parse_rail(geojson: dict) -> list[tuple[str, str, int, list]]:
    """GeoJSON ferroviaire → même forme que `parse_rtss` (drapeau toujours 0)."""
    out = []
    for f in geojson["features"]:
        p = f["properties"]
        for coords in _parties(f.get("geometry")):
            out.append((_classe_rail(p), _libelle_rail(p), 0, coords))
    return out


PARSEURS = {"rtss": parse_rtss, "rail": parse_rail}


# --- Ponts ferroviaires ---------------------------------------------------------------------------
TYPES_PONT = ("Pont", "Pont mobile")          # `typstruc` ; les tunnels ne sont pas des ponts
FUSION_PONT_M = 2.0                           # extrémités à 2 m ou moins : même pont
TOLERANCE_PONT_M = 2.0                        # les ponts sont courts : simplification légère
RAYON_NOM_M = 30.0                            # pont OSM à 30 m ou moins du milieu du pont
GROUPES_PONT = ["CN", "CPKC", "Autre (courtes lignes, industriels, inconnu)"]
EXPLOITANT_INCONNU = "Exploitant inconnu"
PROPRIETAIRE_INCONNU = "Propriétaire inconnu"
ATTRIBUTION_PONTS = "Noms de ponts : © contributeurs OpenStreetMap (ODbL)"
RAW_OSM_RAIL = "osm_rail_bridges_qc.json"
URL_OVERPASS = "https://overpass-api.de/api/interpreter"
REQUETE_OSM_RAIL = ('[out:json][timeout:300];\narea["ISO3166-2"="CA-QC"]->.a;\n'
                    'way["railway"="rail"]["bridge"](area.a);\nout geom tags qt;')

# Groupe d'un pont d'après l'exploitant (nom complet ou sigle), puis le propriétaire si l'exploitant est absent.
# Clés normalisées (`_cle`) ; ce qui n'est pas listé (courtes lignes, industriels, ports, EXO, VIA, MTQ…) va dans le
# groupe 2. Chaînes observées dans `nmfrexploi` / `siglexploi` / `nmfrpropr` du WFS (version 2026-06-08) :
#   CN   : « Canadien National » (CN)
#   CPKC : « Chemin de fer Canadien Pacifique Kansas City » (CPKC)
GROUPE_DE_EXPLOITANT = {
    "canadien national": 0, "canadian national": 0, "cn": 0,
    "chemin de fer canadien pacifique kansas city": 1, "chemin de fer canadien pacifique": 1,
    "canadien pacifique kansas city": 1, "canadien pacifique": 1, "canadian pacific kansas city": 1,
    "canadian pacific": 1, "cpkc": 1, "cpr": 1,
}
VALEURS_ABSENTES = {"", "aucun", "inconnu", "unknown", "none"}

_NOM_DE_PONT = re.compile(r"\b(pont|bridge|viaduc|passerelle|trestle)\b", re.I)
_NOM_DE_VOIE = re.compile(r"subdivision|embranchement|\bsub\b|siding|connection|voie |lead\b|spur|track", re.I)

# WGS84
_A = 6378137.0
_E2 = 0.00669437999014


def _cle(texte) -> str:
    """Clé de comparaison : sans accents, minuscules, blancs réduits."""
    t = unicodedata.normalize("NFKD", texte or "")
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip().casefold()


def groupe_pont(exploitant: str, sigle: str = "", proprietaire: str = "") -> int:
    """0 = CN, 1 = CPKC, 2 = autre. L'exploitant décide (nom, puis sigle) ; sans exploitant, le propriétaire."""
    nom = _cle(exploitant)
    if nom not in VALEURS_ABSENTES:
        g = GROUPE_DE_EXPLOITANT.get(nom)
        return g if g is not None else GROUPE_DE_EXPLOITANT.get(_cle(sigle), 2)
    return GROUPE_DE_EXPLOITANT.get(_cle(proprietaire), 2)


def longueur_geodesique_m(coords) -> float:
    """Longueur (m) d'une polyligne [[lon, lat], ...] : plan tangent local sur l'ellipsoïde WGS84 (rayons de
    courbure du méridien et du premier vertical à la latitude moyenne de chaque segment ; écart < 0,01 %)."""
    total = 0.0
    for (lo1, la1), (lo2, la2) in zip(coords, coords[1:]):
        phi = math.radians((la1 + la2) / 2)
        w = 1 - _E2 * math.sin(phi) ** 2
        dn = math.radians(la2 - la1) * _A * (1 - _E2) / w ** 1.5
        de = math.radians(lo2 - lo1) * _A / math.sqrt(w) * math.cos(phi)
        total += math.hypot(dn, de)
    return total


def _plan_m(lat: float, lon: float) -> tuple[float, float]:
    """(x, y) en mètres, équirectangulaire (suffisant pour des distances de quelques dizaines de mètres)."""
    return lon * 111_320.0 * math.cos(math.radians(lat)), lat * 111_320.0


def parse_ponts(geojson: dict) -> list[dict]:
    """GeoJSON ferroviaire → un dict par partie de ligne portant un pont :
    {exploitant, sigle, proprietaire, mobile, coords [[lon, lat], ...]} (champ `typstruc`)."""
    out = []
    for f in geojson["features"]:
        p = f["properties"]
        if _txt(p.get("typstruc")) not in TYPES_PONT:
            continue
        for coords in _parties(f.get("geometry")):
            if len(coords) >= 2:
                out.append({"exploitant": _txt(p.get("nmfrexploi")), "sigle": _txt(p.get("siglexploi")),
                            "proprietaire": _txt(p.get("nmfrpropr")), "mobile": _txt(p.get("typstruc")) == "Pont mobile",
                            "coords": coords})
    return out


def _classes_de_points(pts: list[tuple[float, float]], seuil_m: float) -> list[int]:
    """Union-find : indice de classe pour chaque point (lat, lon), deux points à `seuil_m` ou moins
    étant dans la même classe."""
    parent = list(range(len(pts)))

    def racine(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    xy = [_plan_m(*p) for p in pts]
    grille: dict[tuple[int, int], list[int]] = {}
    for i, (x, y) in enumerate(xy):
        grille.setdefault((math.floor(x / seuil_m), math.floor(y / seuil_m)), []).append(i)
    for i, (x, y) in enumerate(xy):
        cx, cy = math.floor(x / seuil_m), math.floor(y / seuil_m)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grille.get((cx + dx, cy + dy), ()):
                    if j > i and math.hypot(xy[j][0] - x, xy[j][1] - y) <= seuil_m:
                        parent[racine(j)] = racine(i)
    return [racine(i) for i in range(len(pts))]


def _chaines(segments: list[dict]) -> list[list[tuple[int, bool]]]:
    """Chaînes continues de segments (même exploitant) : [[(indice de segment, inversé?), ...], ...].
    Les extrémités à `FUSION_PONT_M` ou moins sont un même nœud ; une chaîne s'arrête aux extrémités libres
    et aux nœuds où plus de deux segments se rejoignent (aiguillage)."""
    bouts = []                                     # (lat, lon) de chaque extrémité : 2 par segment
    for sg in segments:
        (lo0, la0), (lo1, la1) = sg["coords"][0], sg["coords"][-1]
        bouts += [(la0, lo0), (la1, lo1)]
    noeud = _classes_de_points(bouts, FUSION_PONT_M)
    incidents: dict[int, list[int]] = {}           # nœud → segments
    for i in range(len(segments)):
        for n in (noeud[2 * i], noeud[2 * i + 1]):
            incidents.setdefault(n, []).append(i)
    vu: set[int] = set()
    chaines = []

    def suivre(i: int, depart: int) -> list[tuple[int, bool]]:
        """Chaîne à partir du segment `i`, parti du nœud `depart`."""
        chaine = []
        while True:
            vu.add(i)
            inverse = noeud[2 * i + 1] == depart and noeud[2 * i] != depart
            chaine.append((i, inverse))
            fin = noeud[2 * i] if inverse else noeud[2 * i + 1]
            suite = [j for j in incidents[fin] if j != i]
            if len(incidents[fin]) != 2 or len(suite) != 1 or suite[0] in vu:
                return chaine
            i, depart = suite[0], fin

    for n, segs in incidents.items():              # d'abord les chaînes qui partent d'un nœud de degré ≠ 2
        if len(segs) != 2:
            for i in segs:
                if i not in vu:
                    chaines.append(suivre(i, n))
    for i in range(len(segments)):                 # puis les boucles fermées éventuelles
        if i not in vu:
            chaines.append(suivre(i, noeud[2 * i]))
    return chaines


def fusionner_ponts(segments: list[dict]) -> list[dict]:
    """Segments de pont → ponts : les segments du même exploitant qui se touchent (≤ 2 m) sont fusionnés.
    Chaque pont : {exploitant, sigle, proprietaire (le plus long), mobile, longueur (m, géométrie d'origine,
    somme des segments), coords [[lon, lat], ...] (jointes bout à bout)}."""
    par_exploitant: dict[str, list[dict]] = {}
    for sg in segments:
        par_exploitant.setdefault(sg["exploitant"], []).append(sg)
    ponts = []
    for exploitant, segs in par_exploitant.items():
        for chaine in _chaines(segs):
            coords, par_proprio = [], {}
            for i, inverse in chaine:
                c = segs[i]["coords"][::-1] if inverse else segs[i]["coords"]
                coords += c if not coords else c[1:]
                par_proprio[segs[i]["proprietaire"]] = (par_proprio.get(segs[i]["proprietaire"], 0.0)
                                                        + longueur_geodesique_m(segs[i]["coords"]))
            ponts.append({
                "exploitant": exploitant, "sigle": segs[chaine[0][0]]["sigle"],
                "proprietaire": max(par_proprio, key=par_proprio.get),
                "mobile": any(segs[i]["mobile"] for i, _ in chaine),
                "longueur": sum(par_proprio.values()),
                "coords": coords})
    return ponts


def point_a_mi_longueur(coords) -> tuple[float, float]:
    """(lat, lon) du point situé à la moitié de la longueur d'une polyligne [[lon, lat], ...]."""
    long_seg = [longueur_geodesique_m([a, b]) for a, b in zip(coords, coords[1:])]
    reste = sum(long_seg) / 2
    for (lo1, la1), (lo2, la2), d in zip(coords, coords[1:], long_seg):
        if reste <= d or d == 0:
            t = 0.0 if d == 0 else reste / d
            return la1 + (la2 - la1) * t, lo1 + (lo2 - lo1) * t
        reste -= d
    return coords[-1][1], coords[-1][0]


def nom_pont_osm(tags: dict) -> str | None:
    """Nom d'un pont ferroviaire OSM : `bridge:name`, sinon `name` s'il désigne un pont (« Pont Mitchell »,
    « … Bridge ») et pas une voie (« Subdivision Parc », « Voie d'évitement … »)."""
    nom = _txt(tags.get("bridge:name"))
    if nom:
        return nom
    nom = _txt(tags.get("name"))
    return nom if nom and _NOM_DE_PONT.search(nom) and not _NOM_DE_VOIE.search(nom) else None


def ponts_osm_nommes(elements: list[dict]) -> list[tuple[str, list[tuple[float, float]]]]:
    """Éléments Overpass (`out geom`) → [(nom, [(lat, lon), ...])] pour les ponts OSM qui ont un nom."""
    out = []
    for e in elements:
        nom = nom_pont_osm(e.get("tags") or {})
        geom = [(g["lat"], g["lon"]) for g in e.get("geometry") or ()]
        if nom and geom:
            out.append((nom, geom))
    return out


def _dist_point_polyligne_m(lat: float, lon: float, geom) -> float:
    px, py = _plan_m(lat, lon)
    pts = [_plan_m(la, lo) for la, lo in geom]
    if len(pts) == 1:
        return math.hypot(px - pts[0][0], py - pts[0][1])
    return min(_dist_segment((px, py), a, b) for a, b in zip(pts, pts[1:]))


def nom_le_plus_proche(lat: float, lon: float, nommes, rayon_m: float = RAYON_NOM_M) -> str | None:
    """Nom du pont OSM le plus proche du point, à `rayon_m` mètres ou moins."""
    marge = rayon_m / 111_320.0 * 1.5
    meilleur, d_min = None, rayon_m
    for nom, geom in nommes:
        if not (min(g[0] for g in geom) - marge <= lat <= max(g[0] for g in geom) + marge
                and min(g[1] for g in geom) - 2 * marge <= lon <= max(g[1] for g in geom) + 2 * marge):
            continue
        d = _dist_point_polyligne_m(lat, lon, geom)
        if d <= d_min:
            meilleur, d_min = nom, d
    return meilleur


def construire_ponts(geojson: dict, osm_elements: list[dict] | None = None, tol_m: float = TOLERANCE_PONT_M) -> dict:
    """Ponts ferroviaires du GeoJSON du MTMD → clés `ponts`, `ponts_labels`, `ponts_groupes`, `ponts_attribution`
    (format dans le docstring du module). `osm_elements` : ponts OSM (Overpass `out geom`) pour les noms."""
    nommes = ponts_osm_nommes(osm_elements or [])
    labels: list[str] = []
    idx: dict[str, int] = {}

    def lab(texte: str) -> int:
        if texte not in idx:
            idx[texte] = len(labels)
            labels.append(texte)
        return idx[texte]

    def valeur(texte: str, inconnu: str) -> str:
        return inconnu if _cle(texte) in VALEURS_ABSENTES else texte

    produits = []
    for pont in fusionner_ponts(parse_ponts(geojson)):
        pts = simplifier(quantifier(pont["coords"]), tol_m)
        if len(pts) < 2:
            continue
        nom = nom_le_plus_proche(*point_a_mi_longueur(pont["coords"]), nommes) if nommes else None
        produits.append((groupe_pont(pont["exploitant"], pont["sigle"], pont["proprietaire"]), pont, nom, pts))
    produits.sort(key=lambda x: (x[0], x[3][0]))
    ponts = []
    for groupe, pont, nom, pts in produits:
        entete = [groupe, lab(valeur(pont["exploitant"], EXPLOITANT_INCONNU)),
                  lab(valeur(pont["proprietaire"], PROPRIETAIRE_INCONNU)), round(pont["longueur"]),
                  None if nom is None else lab(nom), int(pont["mobile"])]
        ponts.append(entete + encoder_ligne(0, 0, 0, pts)[3:])
    return {"ponts": ponts, "ponts_labels": labels, "ponts_groupes": GROUPES_PONT,
            "ponts_attribution": ATTRIBUTION_PONTS}


def decoder_pont(entree: list) -> dict:
    """Inverse de l'encodage d'un pont (tests et contrôles) :
    {groupe, exploitant, proprietaire, longueur, nom, mobile, pts [(lat_e5, lon_e5), ...]} (indices non résolus)."""
    groupe, expl, prop, longueur, nom, mobile, lat, lon = entree[:8]
    pts = [(lat, lon)]
    for k in range(8, len(entree), 2):
        lat += entree[k]
        lon += entree[k + 1]
        pts.append((lat, lon))
    return {"groupe": groupe, "exploitant": expl, "proprietaire": prop, "longueur": longueur, "nom": nom,
            "mobile": mobile, "pts": pts}


def charger_osm_rail(refresh: bool = False) -> list[dict]:
    """Ponts ferroviaires OSM : cache `data/raw/osm_rail_bridges_qc.json` (défaut) ou, avec `refresh`, une requête
    Overpass (une seule). Cache absent et pas de rafraîchissement : [] (ponts sans nom)."""
    chemin = RAW_DIR / RAW_OSM_RAIL
    if refresh:
        try:
            r = net.get(net.session(), URL_OVERPASS, timeout=330, params={"data": REQUETE_OSM_RAIL})
            json.loads(r.content)                       # valide avant d'écraser le cache
            net.save_raw(RAW_OSM_RAIL, r.content)
        except Exception as e:                          # Overpass est souvent saturé : on garde le cache
            log.warning("rail : Overpass indisponible (%s), cache OSM conservé", e)
    if not chemin.exists():
        log.warning("rail : %s absent, ponts sans nom (relancer avec --osm-refresh)", chemin.name)
        return []
    return json.loads(chemin.read_text(encoding="utf-8")).get("elements", [])


# --- Assemblage du payload ------------------------------------------------------------------------
def construire_payload(entrees, classes_def, titre, attribution, tol_m=TOLERANCE_M, generated=None) -> dict:
    """Quantifie, fusionne, simplifie et encode. Les classes sans ligne sont retirées de la légende."""
    ordre = {c["label"]: i for i, c in enumerate(classes_def)}
    labels: list[str] = []
    idx_label: dict[str, int] = {}
    lignes: dict[int, tuple[tuple, list]] = {}
    effectifs = {c["label"]: 0 for c in classes_def}
    for classe, libelle, flag, coords in entrees:
        effectifs[classe] += 1
        pts = quantifier(coords)
        if len(pts) < 2:
            continue
        if libelle not in idx_label:
            idx_label[libelle] = len(labels)
            labels.append(libelle)
        lignes[len(lignes)] = ((ordre[classe], idx_label[libelle], flag), pts)

    # classes réellement utilisées, dans l'ordre de légende
    utilisees = sorted({cle[0] for cle, _ in lignes.values()})
    remap = {old: new for new, old in enumerate(utilisees)}
    classes = [classes_def[i] for i in utilisees]

    produites = []
    for (c, lb, flag), pts in fusionner(lignes):
        pts = simplifier(pts, tol_m)
        if len(pts) >= 2:
            produites.append((remap[c], lb, flag, pts))
    produites.sort(key=lambda x: -x[0])              # classes secondaires d'abord, importantes dessinées dessus

    return {
        "generated": generated or date.today().isoformat(),
        "titre": titre,
        "attribution": attribution,
        "classes": classes,
        "labels": labels,
        "lines": [encoder_ligne(*x) for x in produites],
        "_effectifs": {k: v for k, v in effectifs.items() if v},     # retiré avant l'écriture
    }


def ecrire(cle: str, payload: dict) -> dict:
    """Écrit `data/couche-<cle>.js` et renvoie le bilan de la couche."""
    payload = {k: v for k, v in payload.items() if not k.startswith("_")}
    corps = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path = DATA_DIR / COUCHES[cle]["fichier"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(f"window.PQ_COUCHES=window.PQ_COUCHES||{{}};window.PQ_COUCHES.{cle}={corps};\n",
                    encoding="utf-8")
    return {"cle": cle, "path": path, "lignes": len(payload["lines"]),
            "points": sum((len(x) - 3) // 2 for x in payload["lines"]), "bytes": path.stat().st_size}


# --- Orchestration --------------------------------------------------------------------------------
def charger(cle: str, s=None, fetch: bool = True) -> dict:
    """GeoJSON de la couche : téléchargé (et conservé dans data/raw/) ou relu depuis data/raw/."""
    cfg = COUCHES[cle]
    if fetch:
        r = net.get(s or net.session(), _WFS_GEOJSON.format(typename=cfg["typename"]), timeout=600)
        net.save_raw(cfg["raw"], r.content)
        return json.loads(r.content.decode("utf-8"))
    path = RAW_DIR / cfg["raw"]
    if not path.exists():
        raise FileNotFoundError(f"{path} absent : relancer sans --no-fetch")
    return json.loads(path.read_text(encoding="utf-8"))


def run(only=None, fetch=True, tol_m: float = TOLERANCE_M, osm_refresh: bool = False) -> list[dict]:
    """Produit les couches demandées (toutes par défaut). Une entrée de bilan par couche :
    {cle, path, lignes, points, bytes, effectifs} (+ `ponts`, `ponts_nommes` pour le rail)."""
    cles = list(COUCHES) if not only else [c for c in COUCHES if c in set(only)]
    inconnues = set(only or ()) - set(COUCHES)
    if inconnues:
        raise ValueError(f"couche(s) inconnue(s) : {', '.join(sorted(inconnues))} (valides : {', '.join(COUCHES)})")
    s = net.session() if fetch else None
    bilans = []
    for cle in cles:
        cfg = COUCHES[cle]
        geojson = charger(cle, s, fetch)
        entrees = PARSEURS[cle](geojson)
        payload = construire_payload(entrees, cfg["classes"], cfg["titre"], cfg["attribution"], tol_m)
        if cle == "rail":
            payload.update(construire_ponts(geojson, charger_osm_rail(osm_refresh)))
        bilan = ecrire(cle, payload)
        bilan["effectifs"] = payload["_effectifs"]
        if cle == "rail":
            bilan["ponts"] = len(payload["ponts"])
            bilan["ponts_nommes"] = sum(1 for x in payload["ponts"] if x[4] is not None)
        bilans.append(bilan)
    return bilans


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m etl.reseaux", description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="couches à produire, séparées par des virgules (rtss,rail)")
    ap.add_argument("--no-fetch", action="store_true", help="relit data/raw/ au lieu de télécharger")
    ap.add_argument("--tolerance", type=float, default=TOLERANCE_M, help="tolérance de simplification, en mètres")
    ap.add_argument("--osm-refresh", action="store_true",
                    help="rail : relance la requête Overpass des ponts OSM (noms) au lieu du cache data/raw/")
    a = ap.parse_args(argv)
    only = [x.strip() for x in a.only.split(",") if x.strip()] if a.only else None
    for b in run(only, fetch=not a.no_fetch, tol_m=a.tolerance, osm_refresh=a.osm_refresh):
        print(f"{b['cle']}: {b['lignes']} lignes, {b['points']} points, {b['bytes'] / 1e6:.2f} Mo -> {b['path']}")
        for classe, n in b["effectifs"].items():
            print(f"    {classe}: {n} segments")
        if "ponts" in b:
            print(f"    ponts ferroviaires : {b['ponts']} ({b['ponts_nommes']} avec nom OSM)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
