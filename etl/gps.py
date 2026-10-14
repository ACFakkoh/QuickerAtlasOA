"""Export « Coordonnées GPS (format .csv) » de l'outil APEX → table `gps_point`.

C'est la seule source de la « limite de charge ». Le fichier n'a aucun
identifiant de structure : la jointure avec les autres sources se fait ailleurs,
par coordonnées (d'où `num_dossr = None` ici).

Deux variantes du même fichier existent (cp1252, séparateur `;`) :
- export en ligne (APEX) : `lon;lat;"Name";"Route : X / Obstacle : Y / Limite de charge : Z / Année de construction : N"`
  (en-tête `Longitude;Latitude;Name;Description`), vrai CSV avec champs entre guillemets ;
- copie locale `Doc_ref/GPS.csv` (passée par un tableur) : `lon;lat;Name;Route : X ; Obstacle : Y ; ...;;`
  avec en-tête `Longitude;Latitude;Name;Description;;;;;`, des `;` dans la Description
  et parfois des guillemets parasites.
On ne peut donc pas se fier aux colonnes : on découpe la ligne brute après les deux
coordonnées et le nom, puis on lit la Description par ses étiquettes (`Route :`, etc.),
quel que soit le séparateur (`/` ou `;`).
"""
import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from . import net
from .config import APEX_BASE, APEX_ENTRY, DOC_REF

log = logging.getLogger(__name__)

SOURCE = "gps"
TABLE = "gps_point"
RAW_NAME = "GPS.csv"
LOCAL_COPY = DOC_REF / "GPS.csv"

# Lien statique de la page d'accueil APEX (région « Téléchargements »), repéré par
# son nom de procédure. Valeur de repli si la page ne permet pas de le retrouver ;
# paramètres vides = aucun filtre (toutes les structures).
_LIEN_CSV = "P_PESB_GENRT_CSV"
CSV_URL_DEFAUT = APEX_BASE + "APEX_PES." + _LIEN_CSV + "?p_vc_DT=&p_vc_ROUTE=&p_vc_OPT_CHARGE="

_LABELS = {
    "route": "Route",
    "obstacle": "Obstacle",
    "limite_charge": "Limite de charge",
    "annee": "Année de construction",
}
_KEY = {v.lower(): k for k, v in _LABELS.items()}
# lon ; lat ; nom (éventuellement entre guillemets, avec `""` échappés) ; reste = Description
_RE_LIGNE = re.compile(r'^([^;]*);([^;]*);("(?:[^"]|"")*"|[^;]*)(?:;(.*))?$', re.S)
_RE_LABEL = re.compile(
    r"(?:^|(?<=[\s;\"]))(" + "|".join(map(re.escape, _LABELS.values())) + r")\s*:", re.I
)


def _decode(content: bytes) -> str:
    """UTF-8 si valide, sinon cp1252 (encodage observé de l'export)."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _nettoie(v: str) -> str | None:
    """Retire les guillemets/`;` parasites de l'échappement CSV et normalise les blancs."""
    v = v.replace('"', "")
    v = re.sub(r"\s+", " ", v).strip(" ;/")
    v = re.sub(r"\s+,", ",", v)
    return v or None


def _parse_description(desc: str) -> dict:
    """`Route : A ; Obstacle : B ; ...` → {'route': 'A', 'obstacle': 'B', ...} (par étiquettes)."""
    out: dict = {}
    marks = list(_RE_LABEL.finditer(desc))
    for i, m in enumerate(marks):
        fin = marks[i + 1].start() if i + 1 < len(marks) else len(desc)
        out.setdefault(_KEY[m.group(1).lower()], _nettoie(desc[m.end():fin]))
    return out


def _coord(v: str) -> float | None:
    try:
        return float(v.strip().replace(",", "."))
    except ValueError:
        return None


def parse(payload: bytes | str) -> list[dict]:
    """Contenu du CSV → lignes de `gps_point` (`id` = rang 1-based de la ligne de données)."""
    text = _decode(payload) if isinstance(payload, bytes) else payload
    rows: list[dict] = []
    n = 0
    for i, line in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
        if not line.strip("; \t"):
            continue
        m = _RE_LIGNE.match(line)
        if i == 0 and line.lstrip("﻿").lower().startswith("longitude"):
            continue                                    # en-tête
        n += 1
        if not m:
            log.warning("gps : ligne %d ignorée (trop courte)", n)
            continue
        parts = [m.group(1), m.group(2), m.group(3), m.group(4) or ""]
        lon, lat = _coord(parts[0]), _coord(parts[1])
        if lon is None or lat is None:
            log.warning("gps : ligne %d ignorée (coordonnées illisibles)", n)
            continue
        d = _parse_description(parts[3])
        annee = re.search(r"\d{4}", d.get("annee") or "")
        rows.append({
            "id": n,
            "lat": lat,
            "lon": lon,
            "nom": _nettoie(parts[2]),
            "route": d.get("route"),
            "obstacle": d.get("obstacle"),
            "limite_charge": d.get("limite_charge"),
            "annee": int(annee.group(0)) if annee else None,
            "num_dossr": None,
        })
    return rows


def _trouve_url_csv(html: bytes | str, base: str) -> str | None:
    """Cherche dans la page d'accueil APEX le lien « (format .csv) »."""
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        if _LIEN_CSV in a["href"]:
            return urljoin(base, a["href"])
    return None


def collect(s: requests.Session) -> list[dict]:
    try:
        page = net.get(s, APEX_ENTRY)                   # ouvre la session APEX (cookies)
        url = _trouve_url_csv(page.content, page.url) or CSV_URL_DEFAUT
        r = net.get(s, url)
        rows = parse(r.content)
        if not rows:
            raise ValueError("fichier CSV vide ou illisible")
        net.save_raw(RAW_NAME, r.content)
        return rows
    except Exception as e:                              # réseau, HTTP, contenu inattendu
        log.warning("gps : téléchargement en ligne impossible (%s) ; repli sur %s", e, LOCAL_COPY)
        return parse(LOCAL_COPY.read_bytes())
