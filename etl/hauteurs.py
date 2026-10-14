"""Répertoire des hauteurs libres (MTMD) → table `hauteur_libre`.

La page SharePoint `config.HAUTEURS_URL` est une coquille vide : son tableau
DataTables est rempli côté client par un appel AJAX vers le service OData
public ci-dessous (JSON, ~1 500 lignes, ~650 Ko, sans pagination). On interroge
directement ce service plutôt que d'analyser du HTML.

Particularités des données réelles (octobre 2026) :
- une ligne par (structure, route, séquence) : un même `NumeroReference` revient
  jusqu'à 9 fois (ex. un viaduc franchi par plusieurs routes) → 1 535 lignes
  pour 1 246 références distinctes ;
- hauteurs absentes = `null`, ou sentinelle `-1` (hauteur inconnue) → None ;
- les références sont `NNNNN` + suffixe facultatif (`FA`, `N`, `G1`, `JE`...).
"""
import json
import logging
from urllib.parse import quote, urljoin

import requests

from . import net
from .config import HAUTEURS_URL

log = logging.getLogger(__name__)

SOURCE = "hauteurs"
TABLE = "hauteur_libre"

# Service OData appelé par le JavaScript de la page (Mtq.Dhl.js).
ODATA_URL = "https://ws.diffusion.transports.gouv.qc.ca/odata/HauteurLibre"
RAW_NAME = "hauteurs_libres.json"
# Les liens « Détail » de la page sont relatifs au dossier de la page.
DETAIL_FMT = "DHL-Details.aspx?ref={}"

def _txt(v) -> str | None:
    """Chaîne nettoyée ; vide → None."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _hauteur(v) -> float | None:
    """Hauteur en mètres ; vide, « - », 0 ou sentinelle négative (-1) → None."""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip().replace(",", ".")
        if v in ("", "-"):
            return None
    try:
        h = float(v)
    except ValueError:
        return None
    return round(h, 2) if h > 0 else None


def _entier(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _detail_url(num_ref: str) -> str:
    return urljoin(HAUTEURS_URL, DETAIL_FMT.format(quote(num_ref)))


def _min_h(row: dict) -> float:
    hs = [h for h in (row["hauteur_so_m"], row["hauteur_ne_m"]) if h is not None]
    return min(hs) if hs else float("inf")


def parse(payload: bytes | str, *, dedupe: bool = True) -> list[dict]:
    """JSON OData (bytes ou str) → lignes de `hauteur_libre`.

    `num_ref` est la clé primaire du schéma alors que la source compte plusieurs
    lignes (une par route/séquence) pour une même référence. Politique si
    `dedupe` : on garde, par `num_ref`, la ligne à la hauteur minimale (la plus
    contraignante) ; à égalité, la première rencontrée (ordre de la source). Les
    hauteurs sont identiques d'une ligne à l'autre pour une même référence ; seuls
    route/obstacle/séquence diffèrent (les autres routes sont donc perdues).
    """
    data = json.loads(payload)
    items = data["value"] if isinstance(data, dict) else data
    rows: list[dict] = []
    for it in items:
        num_ref = _txt(it.get("NumeroReference"))
        if not num_ref:
            continue
        rows.append({
            "num_ref": num_ref,
            # La référence EST le n° de structure, suffixe compris (14240FA, 13541N…)
            "num_dossr": num_ref,
            "route": _txt(it.get("Route")),
            "seq": _entier(it.get("Sequence")),
            "municipalite": _txt(it.get("Municipalite")),
            "obstacle": _txt(it.get("Obstacle")),
            "dir_so": _txt(it.get("DirectionSO")),
            "hauteur_so_m": _hauteur(it.get("HauteurSO")),
            "dir_ne": _txt(it.get("DirectionNE")),
            "hauteur_ne_m": _hauteur(it.get("HauteurNE")),
            "detail_url": _detail_url(num_ref),
        })
    if not dedupe:
        return rows
    best: dict[str, dict] = {}
    for r in rows:
        cur = best.get(r["num_ref"])
        if cur is None or _min_h(r) < _min_h(cur):   # strict : égalité → on garde la première
            best[r["num_ref"]] = r
    if len(best) < len(rows):
        log.info("hauteurs : %d lignes, %d références distinctes (doublons écartés)",
                 len(rows), len(best))
    return list(best.values())


def collect(s: requests.Session) -> list[dict]:
    r = net.get(s, ODATA_URL, headers={"Accept": "application/json"})
    net.save_raw(RAW_NAME, r.content)
    # Une structure peut enjamber plusieurs routes : on garde toutes les lignes.
    return parse(r.content, dedupe=False)
