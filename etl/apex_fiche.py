"""Fiches détaillées de l'outil APEX (page 53) : crawl incrémental et reprenable.

Chaque fiche est une suite de tableaux `t3standard` : un titre de section puis des
paires libellé → valeur. Toutes les paires sont conservées dans `champs_json` ; les
champs connus (dimensions, circulation, inspections…) sont en plus typés en colonnes.

Coût : 1 requête par structure (~9 900) à ≥ 1 s d'intervalle, soit ~3 h la
première fois. Ensuite seules les fiches nouvelles, modifiées (ICG, IAS, travaux,
rapport) ou trop anciennes sont retéléchargées.
"""
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from . import db, net
from .config import APEX_ENTRY

log = logging.getLogger(__name__)

MOIS = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
        "août": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}

# (section, libellé) → (colonne, convertisseur). Section None = n'importe laquelle.
def _num(v):
    """« 3 357,0 m² » → 3357.0 ; « ND », « - » → None."""
    m = re.search(r"-?[\d\s  ]+(?:,\d+)?", v or "")
    if not m or not re.search(r"\d", m.group(0)):
        return None
    return float(re.sub(r"[\s  ]", "", m.group(0)).replace(",", "."))


def _metres(v):
    """Valeur en m, ou en mm convertie en m."""
    f = _num(v)
    if f is None:
        return None
    return round(f / 1000, 3) if re.search(r"\bmm\b", v) else f


def _int(v):
    f = _num(v)
    return int(f) if f is not None else None


def _txt(v):
    v = " ".join((v or "").split())
    return None if v in ("", "-", "ND") else v


MAPPING = {
    ("Route", "Classe route"): ("classe_route", _txt),
    ("Municipalité", "MRC"): ("mrc", _txt),
    ("Municipalité", "CEP"): ("cep", _txt),
    ("Obstacle", "Type de voie"): ("obstacle_type_voie", _txt),
    ("Obstacle", "Classe route"): ("obstacle_classe_route", _txt),
    ("Dimension", "Longueur totale"): ("longueur_totale_m", _metres),
    ("Dimension", "Longueur tablier"): ("longueur_tablier_m", _metres),
    ("Dimension", "Largeur hors tout"): ("largeur_hors_tout_m", _metres),
    ("Dimension", "Largeur carrossable"): ("largeur_carrossable_m", _metres),
    ("Dimension", "Superficie tablier"): ("superficie_tablier_m2", _num),
    ("Dimension", "Longueur"): ("longueur_m", _metres),
    ("Dimension", "Ouverture totale"): ("ouverture_totale_m", _metres),
    ("Dimension", "Épaisseur du remblai"): ("epaisseur_remblai_m", _metres),
    ("Dimension", "Hauteur moyenne"): ("hauteur_moyenne_m", _metres),
    ("Dimension", "Largeur totale"): ("largeur_totale_m", _metres),
    ("Dimension", "Superficie totale"): ("superficie_m2", _num),
    ("Dimension", "Superficie"): ("superficie_m2", _num),
    ("Circulation", "DJMA"): ("djma", _int),
    ("Circulation", "% camion"): ("pct_camion", _int),
    ("Chaussée", "Nombre de voies"): ("nb_voies", _int),
    ("Inspections générales", "Dernière inspection générale"): ("derniere_inspection", _txt),
    ("Inspections générales", "Prochaine inspection générale"): ("prochaine_inspection", _int),
}
COLONNES = sorted({c for c, _ in MAPPING.values()}) + ["derniere_inspection_ym", "limitations", "photo", "champs_json"]


def _pairs(soup) -> tuple[dict, list[str]]:
    """Toutes les paires (section, libellé) → texte, et les phrases de « Limitation »."""
    pairs: dict[str, str] = {}
    limitations: list[str] = []
    for tb in soup.select("table.t3standard"):
        section = None
        for tr in tb.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            if len(cells) == 1 and cells[0].name == "th":          # titre de section
                section = cells[0].get_text(" ", strip=True)
                continue
            if section == "Limitation" and len(cells) == 1:
                t = " ".join(cells[0].get_text(" ", strip=True).split())
                if t and t != "Limitation":
                    limitations.append(t)
                continue
            i = 0
            while i < len(cells):
                if cells[i].name == "th" and i + 1 < len(cells) and cells[i + 1].name == "td":
                    label = cells[i].get_text(" ", strip=True)
                    value = " ".join(cells[i + 1].get_text(" ", strip=True).split())
                    if label and label != "Carte":
                        pairs.setdefault(f"{section} / {label}", value)
                    i += 2
                else:
                    i += 1
    return pairs, limitations


def parse(page: str) -> dict:
    soup = BeautifulSoup(page.replace("<wbr>", ""), "lxml")
    pairs, limitations = _pairs(soup)
    if not any(k.startswith("Identification / Numéro") for k in pairs):
        raise ValueError("page de fiche invalide (session expirée ou structure absente ?)")
    out = {c: None for c in COLONNES}
    for key, value in pairs.items():
        section, _, label = key.partition(" / ")
        hit = MAPPING.get((section, label))
        if hit and out[hit[0]] is None:
            out[hit[0]] = hit[1](value)
    if out["derniere_inspection"]:
        m = re.match(r"(\w+)\s+(\d{4})", out["derniere_inspection"])
        if m and m.group(1).lower() in MOIS:
            out["derniere_inspection_ym"] = f"{m.group(2)}-{MOIS[m.group(1).lower()]:02d}"
    out["limitations"] = " · ".join(limitations) or None
    out["photo"] = int(soup.find("img", src=re.compile(r"P_PESB_AFFCH_IMAGE")) is not None)
    out["champs_json"] = json.dumps(pairs, ensure_ascii=False)
    return out


# --- Crawl -----------------------------------------------------------------------
def _sig(r) -> str:
    return f"{r['icg']}|{r['ias']}|{r['annee_travaux']}|{r['rapport_dispo']}"


def a_rafraichir(conn, refresh_days: int | None) -> list:
    """Structures de l'inventaire public dont la fiche manque, a changé ou est trop vieille."""
    rows = conn.execute(
        "SELECT a.num_dossr, a.ide_strct, a.fiche_url, a.icg, a.ias, a.annee_travaux, a.rapport_dispo,"
        "       f.fetched_at, f.status, f.apex_sig"
        " FROM apex_structure a LEFT JOIN fiche_detail f USING (num_dossr)"
        " WHERE a.fiche_url IS NOT NULL ORDER BY a.num_dossr").fetchall()
    limite = None
    if refresh_days is not None:
        limite = (datetime.now(timezone.utc) - timedelta(days=refresh_days)).isoformat(timespec="seconds")
    todo = []
    for r in rows:
        if (r["fetched_at"] is None or r["status"] != "ok" or r["apex_sig"] != _sig(r)
                or (limite and r["fetched_at"] < limite)):
            todo.append(r)
    return todo


def _save(conn, r, data: dict | None, erreur: str | None) -> None:
    row = {"num_dossr": r["num_dossr"], "ide_strct": r["ide_strct"], "fetched_at": db.now(),
           "status": "ok" if data else "erreur", "apex_sig": _sig(r), "erreur": erreur,
           **(data or {c: None for c in COLONNES})}
    cols = list(row)
    conn.execute(f"INSERT OR REPLACE INTO fiche_detail ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                 [row[c] for c in cols])


def crawl(conn, *, limit: int | None = None, refresh_days: int | None = None) -> dict:
    todo = a_rafraichir(conn, refresh_days)
    if limit:
        todo = todo[:limit]
    log.info("fiches : %d à télécharger (~%.0f min)", len(todo), len(todo) * 1.15 / 60)
    started, t0 = db.now(), time.monotonic()
    s = net.session()
    net.get(s, APEX_ENTRY)                               # ouvre la session APEX
    ok = err = 0
    for i, r in enumerate(todo, 1):
        data, erreur = None, None
        for essai in range(2):
            try:
                data = parse(net.get(s, r["fiche_url"], timeout=60).text)
                break
            except Exception as e:                       # session perdue, erreur réseau…
                erreur = str(e)[:300]
                if essai == 0:
                    s = net.session()
                    net.get(s, APEX_ENTRY)
        _save(conn, r, data, None if data else erreur)
        ok, err = ok + bool(data), err + (not data)
        if i % 25 == 0 or i == len(todo):
            conn.commit()
        if i % 250 == 0:
            rate = (time.monotonic() - t0) / i
            log.info("fiches : %d/%d (%d erreurs) — reste ~%.0f min", i, len(todo), err, (len(todo) - i) * rate / 60)
    conn.commit()
    db.record_run(conn, "apex_fiche", started, status="ok" if ok or not todo else "erreur",
                  rows=ok, note=f"{err} erreurs sur {len(todo)}")
    return {"ok": ok, "erreurs": err, "total": len(todo)}
