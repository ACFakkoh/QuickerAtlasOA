"""Ponts forestiers (MRNF) : ponts d'AQréseau+ qui ne sont pas dans l'inventaire du MTMD.

Source : Adresses Québec / AQréseau+ (MRNF, CC-BY 4.0), service REST
`https://servicescarto.mrnf.gouv.qc.ca/pes/rest/services/Territoire/AQreseauPlus_WMS/MapServer`,
couches 1, 2 et 3 = « Pont ouvert », « Pont inconnu », « Pont fermé » (~11 300 points, 2 000 par requête).
Le serveur coupe (reset TLS) les connexions du client Python `requests` mais accepte `curl` : le
téléchargement passe donc par un sous-processus `curl` (User-Agent identifié, pause entre les pages).

On ne garde que les points à plus de 30 m de tout ouvrage de l'inventaire du MTMD (les autres sont le même
pont, déjà dans l'atlas) : ~4 800 points. Positions et capacités sont indicatives (« aucune valeur légale »),
les ponts ne sont pas inspectés par le MTMD, et la source ne donne ni type, ni matériau, ni état : aucun
type de pont n'est inventé.

Sortie : `data/couche-forestiers.js` (chargé par `<script src>` → compatible `file://`) :

    (window.PQ_COUCHES = window.PQ_COUCHES || {}).forestiers = {
      "generated": "2026-10-14",              # date de génération
      "version":   "AQ20260701",              # version d'AQréseau+ (champ `Version` de la source)
      "titre":     "Ponts forestiers (MRNF)",
      "attribution": "Adresses Québec / AQréseau+ — MRNF, CC-BY 4.0",
      "source":    "<URL du service>",
      "avertissement": "Aucune valeur légale : positions et capacités indicatives, non inspectées par le MTMD.",
      "srcs":      ["ROUTARD", "AQ", ...],     # codes de source (champ `Source`), seulement ceux présents
      "srcLabels": {"ROUTARD": "...", ...},    # sens en français clair ; « signification non documentée » si inconnu
      "sts":       ["Ouvert", "Inconnu", "Fermé"],
      "points": [[lat, lon, srcIdx, stIdx, dossier, cap], ...]}

Chaque point : `lat`, `lon` = degrés × 1e5 (entiers, ≈ 1 m) ; `srcIdx` = indice dans `srcs` ; `stIdx` = indice
dans `sts` (0 ouvert, 1 inconnu, 2 fermé) ; `dossier` = n° de dossier du pont (`Dossi_Pont`, ex. « H024-025 »)
ou null ; `cap` = capacité portante `Cap_Port` telle que publiée (ex. « 30-48-60 » : trois valeurs en tonnes
selon la configuration du véhicule, la fiche de couche ne précise pas lesquelles ; « 0-0-0 » = pont fermé,
« 0-0-0-0 » conservé tel quel), ou null quand elle est inconnue (« INC », « -- » ou vide). Les points sont
triés par (lat, lon) : sortie reproductible.

Cache : les pages brutes sont conservées dans `data/raw/forestiers/aq_pont<couche>_<décalage>.geojson`
(`--no-fetch` les relit). Si le serveur est injoignable, le cache et le fichier de sortie précédents sont
conservés (avertissement, pas d'échec).

Usage : python -m etl.forestiers [--no-fetch]
"""
import argparse
import glob
import json
import logging
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from . import villes
from .config import DATA_DIR, DB_PATH, RAW_DIR, USER_AGENT

SOURCE = "forestiers"
log = logging.getLogger(__name__)

URL_SERVICE = "https://servicescarto.mrnf.gouv.qc.ca/pes/rest/services/Territoire/AQreseauPlus_WMS/MapServer"
COUCHES_AQ = (1, 2, 3)                    # ouvert / inconnu / fermé
TAILLE_PAGE = 2000                        # objets par requête (limite du service)
MAX_PAGES = 50                            # garde-fou contre une pagination qui ne finit pas
PAUSE_S = 1.5                             # pause entre deux requêtes
DELAI_CURL_S = 120
ESSAIS = 6
DOSSIER_RAW = RAW_DIR / "forestiers"
OUT = DATA_DIR / "couche-forestiers.js"

SEUIL_DOUBLON_M = 30                      # à moins de 30 m d'un ouvrage du MTMD : même pont, déjà dans l'atlas
ECHELLE = 100_000                         # degrés → entiers (1e-5° ≈ 1,11 m)

TITRE = "Ponts forestiers (MRNF)"
ATTRIBUTION = "Adresses Québec / AQréseau+ — MRNF, CC-BY 4.0"
AVERTISSEMENT = "Aucune valeur légale : positions et capacités indicatives, non inspectées par le MTMD."

STATUTS = ["Ouvert", "Inconnu", "Fermé"]
CODE_STATUT = {"O": 0, "INC": 1, "F": 2}              # champ `Stat_Pont`
STATUT_DE_COUCHE = {1: 0, 2: 1, 3: 2}                 # repli si `Stat_Pont` est absent ou inattendu

# Ordre d'affichage des sources ; une source inconnue est ajoutée à la fin (par ordre alphabétique).
ORDRE_SOURCES = ["ROUTARD", "AQ", "AQ_FO", "DGIG", "Sépaq", "BDTQ"]
LIBELLES_SOURCES = {
    "ROUTARD": "Routard — base interne du MRNF sur les chemins multiusages (non documentée publiquement)",
    "AQ": "Adresses Québec (AQréseau+) — surtout des ponts déjà inventoriés par le MTMD",
    "AQ_FO": "AQréseau+, volet forêt — signification non documentée",
    "DGIG": "DGIG — signification non documentée",
    "Sépaq": "Société des établissements de plein air du Québec (Sépaq)",
    "BDTQ": "Base de données topographiques du Québec (BDTQ)",
}
LIBELLE_INCONNU = "signification non documentée"
CAP_INCONNUE = {"", "INC", "--"}                      # → null


class ErreurReseau(RuntimeError):
    """Le service du MRNF est injoignable ou répond autre chose qu'un JSON valide."""


# --- Téléchargement (curl) -----------------------------------------------------------------------
def _decoder(octets: bytes) -> str:
    """UTF-8 (le service annonce charset=UTF-8) ; à défaut cp1252, jamais de caractères perdus."""
    try:
        return octets.decode("utf-8")
    except UnicodeDecodeError:
        return octets.decode("cp1252", errors="replace")


def _curl(url: str, params: dict) -> str:
    """GET via `curl` (le client `requests` est coupé par le serveur du MRNF) ; reprises espacées."""
    derniere = ""
    for k in range(ESSAIS):
        try:
            r = subprocess.run(["curl", "-s", "-m", str(DELAI_CURL_S), "-A", USER_AGENT,
                                url + "?" + urlencode(params)], capture_output=True)
            txt = _decoder(r.stdout)
        except OSError as e:                                  # curl absent
            raise ErreurReseau(f"curl indisponible : {e}") from e
        if txt.lstrip().startswith("{"):
            try:
                if "error" not in json.loads(txt):
                    return txt
            except ValueError:
                pass
        derniere = f"{len(txt)} octets, code curl {r.returncode}"
        log.warning("forestiers : réponse inattendue (%s), nouvel essai", derniere)
        time.sleep(3 * (k + 1))
    raise ErreurReseau(f"{url} : {derniere}")


def telecharger_couche(couche: int) -> dict[int, str]:
    """Pages brutes d'une couche : {décalage: texte GeoJSON}."""
    pages: dict[int, str] = {}
    decalage = 0
    for _ in range(MAX_PAGES):
        txt = _curl(f"{URL_SERVICE}/{couche}/query",
                    {"where": "1=1", "outFields": "*", "outSR": 4326, "resultOffset": decalage,
                     "resultRecordCount": TAILLE_PAGE, "f": "geojson"})
        d = json.loads(txt)
        if "features" not in d:
            raise ErreurReseau(f"couche {couche} : réponse sans objets")
        pages[decalage] = txt
        n = len(d["features"])
        log.info("forestiers : couche %d, décalage %d : %d objets", couche, decalage, n)
        if n == 0 or (n < TAILLE_PAGE and not d.get("exceededTransferLimit")):
            return pages
        decalage += n
        time.sleep(PAUSE_S)
    raise ErreurReseau(f"couche {couche} : plus de {MAX_PAGES} pages")


def telecharger() -> dict[int, dict[int, str]]:
    """Les trois couches : {couche: {décalage: texte}}. Ne touche pas au cache (écrit après succès complet)."""
    out = {}
    for couche in COUCHES_AQ:
        out[couche] = telecharger_couche(couche)
        time.sleep(PAUSE_S)
    return out


def ecrire_cache(pages: dict[int, dict[int, str]], dossier: Path = None) -> None:
    """Remplace les pages en cache par les nouvelles (appelé seulement quand tout le téléchargement a réussi)."""
    dossier = dossier or DOSSIER_RAW
    dossier.mkdir(parents=True, exist_ok=True)
    for ancien in dossier.glob("aq_pont*_*.geojson"):
        ancien.unlink()
    for couche, par_decalage in pages.items():
        for decalage, txt in par_decalage.items():
            (dossier / f"aq_pont{couche}_{decalage}.geojson").write_text(txt, encoding="utf-8")


# --- Analyse -------------------------------------------------------------------------------------
def normaliser_cap(v) -> str | None:
    """Capacité portante telle que publiée ; « INC », « -- » et vide → None."""
    v = (v or "").strip() if isinstance(v, str) else ""
    return None if v.upper() in CAP_INCONNUE else v


def normaliser_dossier(v) -> str | None:
    v = (v or "").strip() if isinstance(v, str) else ""
    return v or None


def normaliser_source(v) -> str:
    """Code de source ; corrige une éventuelle perte d'accent (caractère de remplacement dans « Sépaq »)."""
    v = (v or "").strip() if isinstance(v, str) else ""
    return v.replace("�", "é") if v.startswith("S") and v.endswith("paq") else v


def parse_geojson(geojson: dict, couche: int) -> list[dict]:
    """GeoJSON d'une page → [{lat, lon, src, st, dossier, cap, version, oid}], points valides seulement."""
    out = []
    for f in geojson.get("features", []):
        g = f.get("geometry") or {}
        c = g.get("coordinates")
        if g.get("type") != "Point" or not c or len(c) < 2:
            continue
        p = f.get("properties") or {}
        st = CODE_STATUT.get((p.get("Stat_Pont") or "").strip(), STATUT_DE_COUCHE.get(couche, 1))
        out.append({"lat": float(c[1]), "lon": float(c[0]), "src": normaliser_source(p.get("Source")), "st": st,
                    "dossier": normaliser_dossier(p.get("Dossi_Pont")), "cap": normaliser_cap(p.get("Cap_Port")),
                    "version": (p.get("Version") or "").strip(), "oid": (couche, p.get("OBJECTID"))})
    return out


def charger_cache(dossier: Path = None) -> list[dict]:
    """Tous les points des pages en cache (une entrée par objet ; doublons d'`OBJECTID` d'une couche ignorés)."""
    dossier = dossier or DOSSIER_RAW
    fichiers = sorted(glob.glob(str(dossier / "aq_pont*_*.geojson")))
    if not fichiers:
        raise FileNotFoundError(f"{dossier} sans page aq_pont*.geojson : relancer sans --no-fetch")
    vus, out = set(), []
    couches = set()
    for chemin in fichiers:
        m = re.search(r"aq_pont(\d+)_(\d+)\.geojson$", chemin)
        if not m:
            continue
        couche = int(m.group(1))
        couches.add(couche)
        geojson = json.loads(Path(chemin).read_text(encoding="utf-8"))
        for p in parse_geojson(geojson, couche):
            if p["oid"][1] is not None and p["oid"] in vus:
                continue
            vus.add(p["oid"])
            out.append(p)
    manquantes = set(COUCHES_AQ) - couches
    if manquantes:
        log.warning("forestiers : couche(s) %s absente(s) du cache", sorted(manquantes))
    return out


# --- MTMD et doublons ----------------------------------------------------------------------------
def charger_mtmd(db_path: Path = DB_PATH, structures_js: Path = DATA_DIR / "structures.js") -> list[tuple]:
    """Ouvrages géolocalisés du MTMD [(n°, lat, lon, famille)…] : base SQLite, à défaut `data/structures.js`."""
    try:
        rows = villes.charger_structures_mtmd(db_path)
        if rows:
            return rows
    except sqlite3.Error:
        pass
    log.warning("forestiers : base %s illisible, lecture de %s", db_path.name, structures_js.name)
    S = json.loads(structures_js.read_text(encoding="utf-8").split("=", 1)[1].rstrip().rstrip(";"))
    ix = {c: i for i, c in enumerate(S["cols"])}
    return [(r[ix["num"]], r[ix["lat"]], r[ix["lon"]], None) for r in S["rows"] if r[ix["lat"]] and r[ix["lon"]]]


def hors_mtmd(ponts: list[dict], mtmd_rows, max_m: float = SEUIL_DOUBLON_M) -> list[dict]:
    """Ponts à plus de `max_m` mètres de tout ouvrage du MTMD (les autres sont des doublons)."""
    proches = villes.nearest_mtmd([(p["lat"], p["lon"]) for p in ponts], mtmd_rows, max_m)
    return [p for p, num in zip(ponts, proches) if num is None]


# --- Sortie --------------------------------------------------------------------------------------
def codes_sources(ponts: list[dict]) -> list[str]:
    """Codes de source présents, dans l'ordre d'affichage (les inconnus à la fin, ordre alphabétique)."""
    presents = {p["src"] for p in ponts}
    return [s for s in ORDRE_SOURCES if s in presents] + sorted(presents - set(ORDRE_SOURCES))


def version_aq(ponts: list[dict]) -> str:
    """Version d'AQréseau+ (la plus récente si plusieurs, ex. « AQ20260701 »)."""
    return max((p["version"] for p in ponts if p["version"]), default="")


def construire_payload(ponts: list[dict], generated: str | None = None) -> dict:
    """Ponts (déjà filtrés) → charge utile de la couche (voir le format dans le docstring du module)."""
    srcs = codes_sources(ponts)
    idx = {s: i for i, s in enumerate(srcs)}
    points = [[round(p["lat"] * ECHELLE), round(p["lon"] * ECHELLE), idx[p["src"]], p["st"], p["dossier"], p["cap"]]
              for p in ponts]
    points.sort(key=lambda r: (r[0], r[1], r[2], r[3], r[4] or "", r[5] or ""))
    return {
        "generated": generated or date.today().isoformat(),
        "version": version_aq(ponts),
        "titre": TITRE,
        "attribution": ATTRIBUTION,
        "source": URL_SERVICE,
        "avertissement": AVERTISSEMENT,
        "srcs": srcs,
        "srcLabels": {s: LIBELLES_SOURCES.get(s, f"{s} — {LIBELLE_INCONNU}") for s in srcs},
        "sts": STATUTS,
        "points": points,
    }


def ecrire(payload: dict, path: Path = None) -> int:
    path = path or OUT
    corps = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(f"window.PQ_COUCHES=window.PQ_COUCHES||{{}};window.PQ_COUCHES.forestiers={corps};\n",
                    encoding="utf-8", newline="\n")
    return path.stat().st_size


def stats(ponts: list[dict]) -> dict:
    """Décomptes par source et par statut (pour le bilan)."""
    return {"par_source": dict(Counter(p["src"] for p in ponts)),
            "par_statut": {STATUTS[k]: n for k, n in sorted(Counter(p["st"] for p in ponts).items())}}


def run(fetch: bool = True) -> dict:
    """Produit `data/couche-forestiers.js`. Serveur injoignable → fichier précédent conservé (si présent).
    Renvoie {path, rows, bytes, total_aq, doublons, par_source, par_statut[, conserve]}."""
    if fetch:
        try:
            ecrire_cache(telecharger())
        except ErreurReseau as e:
            if not OUT.exists():
                raise
            log.warning("forestiers : serveur du MRNF injoignable (%s) ; %s conservé tel quel", e, OUT.name)
            return {"path": OUT, "rows": None, "bytes": OUT.stat().st_size, "conserve": True}
    aq = charger_cache()
    ponts = hors_mtmd(aq, charger_mtmd())
    payload = construire_payload(ponts)
    return {"path": OUT, "rows": len(ponts), "bytes": ecrire(payload), "total_aq": len(aq),
            "doublons": len(aq) - len(ponts), **stats(ponts)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m etl.forestiers", description=__doc__.splitlines()[0])
    ap.add_argument("--no-fetch", action="store_true", help="relit data/raw/forestiers/ au lieu de télécharger")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):                 # console Windows redirigée (cp1252) : « é » de Sépaq
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    r = run(fetch=not args.no_fetch)
    if r.get("conserve"):
        print(f"{r['path']} conservé (serveur injoignable), {r['bytes'] / 1e3:.0f} Ko")
        return 0
    print(f"{r['path']} : {r['rows']} ponts hors MTMD sur {r['total_aq']} ({r['doublons']} doublons), "
          f"{r['bytes'] / 1e3:.0f} Ko")
    print("  par source :", ", ".join(f"{k} {v}" for k, v in r["par_source"].items()))
    print("  par statut :", ", ".join(f"{k} {v}" for k, v in r["par_statut"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
