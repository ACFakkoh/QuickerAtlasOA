"""Flux WFS « Structure » de Données Québec (MTMD, CC-BY 4.0, mis à jour quotidiennement).

Dictionnaire : https://www.donneesquebec.ca/recherche/dataset/structure
"""
import csv
import io
import json

from . import net
from .config import WFS_CSV_URL

SOURCE = "wfs"
TABLE = "wfs_structure"


def _txt(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def _int(v: str | None) -> int | None:
    v = _txt(v)
    return int(float(v)) if v else None


def _float(v: str | None) -> float | None:
    v = _txt(v)
    return float(v) if v else None


def _mm_to_m(v: str | None) -> float | None:
    f = _float(v)
    return round(f / 1000, 2) if f else None


def _yes(v: str | None) -> int | None:
    v = _txt(v)
    return {"O": 1, "N": 0}.get(v) if v else None


def _type(code_des_t: str | None) -> tuple[int | None, str | None]:
    """« 45 - Pont acier-bois » → (45, « Pont acier-bois »)."""
    v = _txt(code_des_t)
    if not v:
        return None, None
    code, _, label = v.partition(" - ")
    return int(code), label.strip() or None


def parse(content: bytes) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(content.decode("utf-8-sig"))):
        code, label = _type(r["code_des_t"])
        rows.append({
            "num_dossr": r["num_dossr"].strip(),
            "ide_strct": _int(r["ide_strct"]),
            "nom": _txt(r["nom_strct"]),
            "type_code": code,
            "type_libelle": label,
            "route": _txt(r["nom_route"]),
            "num_rts": _txt(r["num_rts"]),
            "obstacle": _txt(r["nom_obstc"]),
            "municipalite": _txt(r["nom_muncp"]),
            "cod_muncp": _int(r["cod_muncp"]),
            "centre_services": _txt(r["des_cs"]),
            "direction_generale": _txt(r["dirct_te00"]),
            "annee_construction": _int(r["val_annee_"]),
            "nb_voies": _int(r["nbr_voie"]),
            "longueur_m": _mm_to_m(r["val_longr"]),
            "largeur_m": _mm_to_m(r["val_largr_"]),
            "lat": _float(r["geo_lattd"]),
            "lon": _float(r["geo_longt"]),
            "cod_respn": _int(r["cod_type_r"]),
            "route_principale": _yes(r["rte_ind_pr"]),
            "deficient_etat": _yes(r["ind_strct_"]),
            "deficient_fonct": _yes(r["ind_strc00"]),
            "raw_json": json.dumps(r, ensure_ascii=False),
        })
    return rows


def collect(s) -> list[dict]:
    r = net.get(s, WFS_CSV_URL, timeout=300)
    net.save_raw("wfs_structure.csv", r.content)
    return parse(r.content)
