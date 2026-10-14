"""Liste de l'outil « Inventaire et inspection des structures » (Oracle APEX 21, app 122 page 56).

Mécanique : la page d'accueil ouvre une session APEX ; la recherche est un POST
`wwv_flow.accept` dont le `p_json` reprend les jetons `salt` / `protected` / `ck`
présents dans le HTML. Le rapport accepte ensuite `pg_max_rows=500` en pagination,
soit ~20 requêtes pour tout l'inventaire. Les drapeaux « limitation de hauteur /
de poids » s'obtiennent en relançant la recherche avec la case correspondante.
"""
import html as htmllib
import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import net
from .config import APEX_BASE, APEX_ENTRY, APEX_PAGE_SIZE

SOURCE = "apex_list"
TABLE = "apex_structure"
log = logging.getLogger(__name__)

IAS_IMG = {"feuvert": "vert", "feujaune": "jaune", "feurouge": "rouge"}
FILTRES = {"lim_hauteur": "H", "lim_poids": "C"}   # valeurs de P56_LIMTN_CHARGE_0004


# --- Soumission du formulaire ----------------------------------------------------
def _attr(page: str, item: str, attr: str = "value") -> str | None:
    tag = re.search(rf'<input[^>]*\bid="{item}"[^>]*>', page)
    m = tag and re.search(rf'\b{attr}="([^"]*)"', tag.group(0))
    return htmllib.unescape(m.group(1)) if m else None


def _form_payload(page: str, limitations: list[str], request: str = "RECHR") -> dict:
    """Reconstruit le POST qu'émet `apex.submit({request:'RECHR'})` dans le navigateur."""
    salt = _attr(page, "pSalt")
    protected = _attr(page, "pPageItemsProtected")
    ck = re.search(r'data-for="P56_VAL_IAS_0009" value="([^"]*)"', page)
    if not (salt and protected and ck):
        raise RuntimeError("Jetons APEX introuvables : la structure de la page a changé ?")
    items = [
        {"n": "P56_DAT_MAJ_SECTN_0001", "v": _attr(page, "P56_DAT_MAJ_SECTN_0001") or ""},
        {"n": "P56_DIR_TERRT_0002", "v": "%"},
        {"n": "P56_NOM_ROUTE_0003", "v": ""},
        {"n": "P56_COD_TYPE_RESPN", "v": "%"},
        {"n": "P56_LIMTN_CHARGE_0004", "v": limitations},
        {"n": "P56_RECHR_0005", "v": ""},
        {"n": "P56_RECHR_ACTIF_0007", "v": "1"},
        {"n": "P56_VAL_ICG_0008", "v": ""},
        {"n": "P56_VAL_IAS_0009", "v": "", "ck": ck.group(1)},
    ]
    p_json = {"salt": salt, "pageItems": {"itemsToSubmit": items, "protected": protected,
                                          "rowVersion": "", "formRegionChecksums": []}}
    return {
        "p_json": json.dumps(p_json, separators=(",", ":")),
        "p_flow_id": _attr(page, "pFlowId") or "122",
        "p_flow_step_id": _attr(page, "pFlowStepId") or "56",
        "p_instance": _attr(page, "pInstance"),
        "p_page_submission_id": _attr(page, "pPageSubmissionId"),
        "p_request": request,
        "p_reload_on_submit": "A",
    }


def _search(s, page: str, limitations: list[str]) -> str:
    """Soumet la recherche ; renvoie le HTML de la 1re page de résultats."""
    net.wait(APEX_BASE)
    r = s.post(urljoin(APEX_BASE, "wwv_flow.accept"), data=_form_payload(page, limitations), timeout=120)
    r.raise_for_status()
    return r.text


def _pages(s, first: str):
    """Itère sur les pages du rapport en mode 500 lignes ; chaque page est vérifiée (`verifier_page`)."""
    m = re.search(r'f\?p=122:56:(\d+):(pg_R_\d+):NO', first)
    if not m:
        raise RuntimeError("Lien de pagination du rapport introuvable.")
    instance, region = m.groups()
    start = 1
    while True:
        url = (f"{APEX_BASE}f?p=122:56:{instance}:{region}:NO"
               f"&pg_min_row={start}&pg_max_rows={APEX_PAGE_SIZE}&pg_rows_fetched={APEX_PAGE_SIZE}")
        page = net.get(s, url).text
        rows = parse_rows(page)
        verifier_page(page, rows, start)
        yield page, rows
        if len(rows) < APEX_PAGE_SIZE:
            return
        start += APEX_PAGE_SIZE


# --- Validation des réponses (audit v0.5.5 n° 1) ---------------------------------
# APEX répond HTTP 200 même quand la session a expiré (page de connexion) ou en cas d'erreur : une liste vide ne
# prouve pas la fin du rapport. Chaque page doit porter sa plage « a - b » cohérente avec les lignes lues, et le
# nombre total collecté doit égaler le « Total » annoncé par le tableau récapitulatif de la recherche.
_PLAGE = re.compile(r'class="fielddata">\s*(\d+)\s*-\s*(\d+)\s*</span>')
_TOTAL = re.compile(r'>Total</td>\s*<td[^>]*>\s*([\d\s ]+?)\s*</td>')


def total_annonce(page: str) -> int | None:
    m = _TOTAL.search(page)
    return int(re.sub(r"\D", "", m.group(1))) if m else None


def verifier_page(page: str, rows: list[dict], start: int) -> None:
    """Refuse une page qui n'est pas la page `start` du rapport (session expirée, erreur, page tronquée)."""
    m = _PLAGE.search(page)
    if not rows:
        # page vide légitime : seulement après la dernière ligne du total annoncé (total multiple de 500)
        if start > 1 and m is None and "pagination" in page:
            return
        raise RuntimeError(f"Réponse APEX inattendue à la ligne {start} : aucune ligne ni pagination "
                           "(session expirée ou erreur du serveur ?) ; inventaire non remplacé.")
    if not m:
        raise RuntimeError(f"Réponse APEX inattendue à la ligne {start} : plage de pagination absente.")
    a, b = int(m.group(1)), int(m.group(2))
    if a != start or b - a + 1 != len(rows):
        raise RuntimeError(f"Page APEX incohérente : plage {a} - {b} annoncée, {len(rows)} lignes lues à partir de {start}.")


# --- Analyse du rapport --------------------------------------------------------
def _text(td) -> str | None:
    t = " ".join(td.get_text(" ", strip=True).split())
    return None if t in ("", "-") else t


def parse_rows(page: str) -> list[dict]:
    soup = BeautifulSoup(page.replace("<wbr>", ""), "lxml")   # « Abitibi-<wbr>Témiscamingue »
    out = []
    for img in soup.select('img[alt^="Fiche de la structure"]'):
        tr = img.find_parent("tr")
        td = tr.find_all("td", recursive=False)
        if len(td) < 13:
            raise RuntimeError(f"Ligne inattendue ({len(td)} colonnes) : {tr.get_text(' ', strip=True)[:120]}")
        link = td[0].find("a")["href"]
        ide = re.search(r"P53_IDE_STRCT_0001:(\d+)", link)
        type_img = td[2].find("img")
        type_code = re.search(r"/(\d+)\.gif", type_img["src"]) if type_img else None
        ias_img = td[9].find("img")
        ias = None
        if ias_img:
            ias = next((v for k, v in IAS_IMG.items() if k in ias_img["src"]), None)
        elif (_text(td[9]) or "").replace(" ", "") == "S.O.":
            ias = "SO"
        icg = _text(td[8])
        annee = _text(td[11])
        out.append({
            "num_dossr": td[0].get_text(strip=True),
            "ide_strct": int(ide.group(1)) if ide else None,
            "nom": _text(td[1]),
            "type_code": int(type_code.group(1)) if type_code else None,
            "type_libelle": type_img.get("alt") if type_img else None,
            "reseau": _text(td[3]),
            "direction_territoriale": _text(td[4]),
            "municipalite": _text(td[5]),
            "route": _text(td[6]),
            "obstacle": _text(td[7]),
            "icg": "SO" if icg and icg.replace(" ", "") == "S.O." else icg,
            "ias": ias,
            "annee_travaux": int(annee) if annee and annee.isdigit() else None,
            "rapport_dispo": int(td[12].find("a") is not None),
            "fiche_url": urljoin(APEX_BASE, link),
            "lim_hauteur": 0,
            "lim_poids": 0,
        })
    return out


# --- Point d'entrée ----------------------------------------------------------------
def _collect_search(s, limitations: list[str]) -> list[dict]:
    entry = net.get(s, APEX_ENTRY).text
    first = _search(s, entry, limitations)
    rows, total = [], None
    for i, (page, chunk) in enumerate(_pages(s, first)):
        if not limitations:
            net.save_raw(f"apex_list_{i:02d}.html", page.encode("utf-8"))
        if i == 0:
            total = total_annonce(page)
        rows += chunk
    verifier_total(rows, total, limitations)
    return rows


def verifier_total(rows: list[dict], total: int | None, limitations: list[str]) -> None:
    """Recherche complète : le nombre de lignes lues doit égaler le « Total » annoncé. Les recherches filtrées
    (limitations) ne servent qu'à poser des drapeaux ; leur récapitulatif n'est pas vérifié."""
    if limitations:
        return
    if total is None:
        raise RuntimeError("Total de l'inventaire introuvable dans la réponse APEX : structure de la page changée ?")
    if len(rows) != total:
        raise RuntimeError(f"Inventaire APEX incomplet : {len(rows)} lignes lues pour {total} annoncées ; non remplacé.")


def collect(s) -> list[dict]:
    rows = _collect_search(s, [])
    by_num = {r["num_dossr"]: r for r in rows}
    if len(by_num) != len(rows):
        log.warning("apex_list : %d doublons de n° de structure", len(rows) - len(by_num))
    for champ, code in FILTRES.items():
        flagged = _collect_search(s, [code])
        for r in flagged:
            if r["num_dossr"] in by_num:
                by_num[r["num_dossr"]][champ] = 1
        log.info("apex_list : %s → %d structures", champ, len(flagged))
    return list(by_num.values())
