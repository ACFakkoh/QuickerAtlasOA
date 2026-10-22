"""Ponts remarquables (Wikipédia, Wikidata) : liens dans les fiches du MTMD et ponts du Canada hors inventaire.

Sources (lecture seule, API publiques, User-Agent identifié) :

- la page « List of bridges in Canada » de Wikipédia en anglais (tableaux « Historical and architectural
  interest bridges », « Major road and railway bridges », « The old bridges over the Niagara » et la liste
  alphabétique par province) : nom, article, distinction, province, renvois Structurae ;
- l'API de Wikipédia (en, fr) : coordonnées, image libre de l'article, résumé, article français ;
- Wikidata (CC0) : type, longueur, portée, ouverture, matériau, obstacle, architecte, propriétaire, statut
  patrimonial, identifiant Structurae ; et, pour l'appariement, les ponts géolocalisés de la boîte du Québec
  ayant un article (fr ou en) ;
- Wikimedia Commons : auteur et licence de chaque image ; pour un pont sans image d'article, image Wikidata (P18),
  catégorie Commons (P373), photo choisie à la main, ou fichier dont le titre reprend le nom du pont (recherche
  géolocalisée à 30 km, ou rayon de 600 m autour du pont).

Structurae n'a pas d'API ; le site refuse tout accès automatisé (403) et réserve ses droits (robots.txt) : on
n'en garde que le lien (identifiant P454 de Wikidata ou renvoi de la liste), jamais le contenu.

Appariement avec l'inventaire du MTMD : nom normalisé (mots significatifs du plus court contenus dans l'autre)
et distance ≤ 3 km ; tous les ouvrages du même nom dans ce rayon sont liés (ponts jumeaux). Un pont de la liste
apparié au MTMD reçoit un lien dans sa fiche ; les autres (hors Québec, ou au Québec mais hors inventaire)
deviennent des « ponts remarquables » : étoiles sur la carte, hors filtres et statistiques.

Sortie : `data/couche-wikiponts.js` :

    (window.PQ_COUCHES = window.PQ_COUCHES || {}).wikiponts = {
      "generated": "2026-10-19", "source": "<URL de la liste>", "attribution": "...",
      "mtmd":  {"04296": {"fr": "Pont Pierre-Laporte", "en": "Pierre Laporte Bridge", "q": "Q761692", "st": "<id>"}, ...},
      "ponts": [{"id": "Q865076", "nom": "...", "nomEn": "...", "prov": "Île-du-Prince-Édouard", "lat": 46.2, "lon": -63.7,
                 "an": 1997, "type": "pont à poutres", "long": 12900, "portee": 250, "mat": "béton précontraint",
                 "franchit": "détroit de Northumberland", "archi": "...", "prop": "...", "patri": "...",
                 "distinction": "<texte anglais de la liste>", "resume": "...", "resumeLang": "fr",
                 "img": {"src": "<miniature>", "page": "<page Commons>", "auteur": "...", "licence": "CC BY-SA 4.0",
                         "origine": "wikidata|categorie|choisie|recherche|proximite (absent : image de l'article)"},
                 "fr": "<titre fr>", "en": "<titre en>", "q": "Q865076", "st": "<id Structurae>"}, ...]}

Cache : réponses brutes dans `data/raw/wikiponts/` (`--no-fetch` les relit).

Usage : python -m etl.wikiponts [--no-fetch]
"""
import argparse
import hashlib
import html
import json
import logging
import math
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup

from . import net
from .config import DATA_DIR, RAW_DIR

log = logging.getLogger("etl.wikiponts")

SOURCE = "wikiponts"
LISTE = "List_of_bridges_in_Canada"
URL_LISTE = "https://en.wikipedia.org/wiki/" + LISTE
API = {"en": "https://en.wikipedia.org/w/api.php", "fr": "https://fr.wikipedia.org/w/api.php",
       "wd": "https://www.wikidata.org/w/api.php", "commons": "https://commons.wikimedia.org/w/api.php"}
SPARQL = "https://query.wikidata.org/sparql"
DOSSIER_RAW = RAW_DIR / "wikiponts"
OUT = DATA_DIR / "couche-wikiponts.js"
ATTRIBUTION = "Ponts remarquables : Wikipédia (CC BY-SA 4.0), Wikidata (CC0), images Wikimedia Commons (licence par image)"
DISTANCE_MAX_M = 3000
M_PAR_DEGRE = 111_320
PROVINCES = {
    "Alberta": "Alberta", "British Columbia": "Colombie-Britannique", "Manitoba": "Manitoba",
    "New Brunswick": "Nouveau-Brunswick", "Newfoundland and Labrador": "Terre-Neuve-et-Labrador",
    "Northwest Territories": "Territoires du Nord-Ouest", "Nova Scotia": "Nouvelle-Écosse", "Nunavut": "Nunavut",
    "Ontario": "Ontario", "Prince Edward Island": "Île-du-Prince-Édouard", "Quebec": "Québec",
    "Saskatchewan": "Saskatchewan", "Yukon": "Yukon",
}
SECTIONS = {"Historical and architectural interest bridges": "patrimoine", "Major road and railway bridges": "majeur",
            "The old bridges over the Niagara": "niagara"}
# Boîte englobante du Québec (un peu large : l'appariement par nom écarte les ponts voisins hors Québec)
BOITE_QC = ((-79.8, 44.9), (-57.1, 62.6))
# Wikidata : propriété → champ (valeurs « élément » traduites en libellé français, à défaut anglais)
P_ITEMS = {"P31": "type", "P186": "mat", "P177": "franchit", "P84": "archi", "P127": "prop", "P1435": "patri"}
P_LONG, P_PORTEE, P_OUVERTURE, P_DEBUT, P_STRUCTURAE, P_COORD = "P2043", "P2787", "P1619", "P571", "P454", "P625"
P_IMAGE, P_COMMONSCAT = "P18", "P373"
RAYON_PHOTO_M = 600                     # photo de Commons « à proximité » : rayon de recherche autour du pont
RE_PHOTO = re.compile(r"\.(jpe?g|png|webp|tiff?)$", re.I)
# Photos choisies à la main (description et catégories de Commons vérifiées le 2026-10-20) pour des ponts sans image
# (pas de photo pour le pont suspendu de la rivière de la Paix : effondré en 1957 ; le pont-pipeline voisin est un autre ouvrage)
PHOTOS_CHOISIES = {"Q14875601": "Route 1 bridge Jemseg.JPG"}                               # Transcanadienne, Jemseg (N.-B.)
# v0.6.5 : photos hors Commons (Flickr, licences Creative Commons, trouvées par Openverse) pour des ponts sans image
# libre sur Commons ; chaque photo vérifiée à l'œil le 2026-10-22 (titre, sujet, lieu). Usage non commercial,
# auteur et licence affichés. Écartées : photos du GouvNB pour le pont de Burton (sans le pont).
FLICKR = "https://live.staticflickr.com/"
PHOTOS_EXTERNES = {
    "Q7589572": {"src": FLICKR + "477/19441909203_d48d21a4fa_z.jpg", "page": "https://www.flickr.com/photos/21953562@N07/19441909203",
                 "auteur": "cmh2315fl", "licence": "CC BY-NC 2.0"},                            # St. Louis Bridge (Sask.)
    "Q5030388": {"src": FLICKR + "276/19448683654_94d54cfdbb_z.jpg", "page": "https://www.flickr.com/photos/21953562@N07/19448683654",
                 "auteur": "cmh2315fl", "licence": "CC BY-NC 2.0"},                            # Canadian Northern, Prince Albert
    "Q7157445": {"src": FLICKR + "65535/54067844169_b30b6171b5_z.jpg", "page": "https://www.flickr.com/photos/46154524@N04/54067844169",
                 "auteur": "Ted LaBar (photo de 1943)", "licence": "CC BY-NC 2.0"},           # pont suspendu de la rivière de la Paix
}
UNITES_M = {"Q11573": 1.0, "Q828224": 1000.0, "Q3710": 0.3048, "Q174728": 0.01}     # m, km, pied, cm
TYPES_GENERIQUES = {"Q12280", "Q1825472"}                                               # « pont », « ouvrage d'art »
MOTS_VIDES = {"pont", "ponts", "bridge", "bridges", "viaduc", "viaduct", "de", "du", "des", "la", "le", "les", "l", "d",
              "the", "of", "and", "et", "a", "au", "aux", "en", "sur", "over", "covered", "couvert", "railway", "rail",
              "ferroviaire", "new", "nouveau", "old", "vieux", "ancien"}
# Nature de l'ouvrage : un « échangeur » ou un « tunnel » du MTMD ne se lie pas à l'article d'un pont du même nom
NATURES = {"echangeur", "tunnel", "passerelle", "ponceau", "interchange", "footbridge"}
# Article ou type Wikidata « pont » (sinon : lien vers une ville, une route… de la liste alphabétique)
RE_PONT = re.compile(r"\b(pont|ponts|bridge|bridges|viaduc|viaduct|tracel|trestle|passerelle|footbridge|causeway|"
                     r"crossing|aqueduc|aqueduct|tunnel)\b|pont-", re.I)


# --- Accès réseau (avec cache brut) -----------------------------------------------------------------
def _cache(nom: str) -> Path:
    return DOSSIER_RAW / nom


def _get_json(s, url: str, params: dict, nom: str, fetch: bool) -> dict:
    """GET JSON avec cache : `fetch=False` relit `data/raw/wikiponts/<nom>` (erreur si absent)."""
    p = _cache(nom)
    if fetch:
        r = net.get(s, url, params={**params, "format": "json", "formatversion": "2"}, timeout=90)
        DOSSIER_RAW.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
    return json.loads(p.read_text(encoding="utf-8"))


def _cle(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:12]


def _lots(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# --- Liste Wikipédia --------------------------------------------------------------------------------
def _titre(href: str | None) -> str | None:
    """`/wiki/Victoria_Bridge_(Montreal)` → « Victoria Bridge (Montreal) » (None : fichier, ancre, lien rouge)."""
    if not href or not href.startswith("/wiki/") or ":" in href[6:]:
        return None
    return unquote(href[6:].split("#")[0]).replace("_", " ")


def _texte(el) -> str:
    for sup in el.select("sup"):
        sup.decompose()
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _structurae_refs(soup) -> dict[str, str]:
    """id de note (cite_note-…) → identifiant Structurae cité dans la note."""
    out = {}
    for li in soup.select("li[id^=cite_note]"):
        a = li.select_one('a[href*="structurae."]')
        if a:
            m = re.search(r"/(?:structures|ouvrages|bauwerke)/([^/?#]+)", a["href"])
            if m and m.group(1) != "data":
                out[li["id"]] = m.group(1)
    return out


def parse_liste(page_html: str) -> list[dict]:
    """HTML rendu de la liste → [{titre, nom, prov, section, distinction, st, lat, lon}…] (un par article)."""
    soup = BeautifulSoup(page_html, "lxml")
    refs = _structurae_refs(soup)
    out, vus = [], set()

    def ajouter(e):
        if e["titre"] and e["titre"] not in vus:
            vus.add(e["titre"])
            out.append(e)

    for table in soup.select("table.wikitable"):
        h = table.find_previous("h2")
        section = SECTIONS.get(h.get_text(strip=True) if h else "", "majeur")
        lignes = table.select("tr")
        entetes = [_texte(th) for th in lignes[0].select("th")]
        col = {t: i for i, t in enumerate(entetes)}
        for tr in lignes[1:]:
            tds = tr.find_all(["td", "th"], recursive=False)
            if len(tds) < len(entetes) - 1:
                continue
            cell = lambda nom: tds[col[nom]] if nom in col and col[nom] < len(tds) else None
            c_nom = cell("Name")
            a = c_nom.select_one("a[href^='/wiki/']") if c_nom else None
            st = next((refs[x["href"][1:]] for x in tr.select("sup.reference a[href^='#cite_note']") if x["href"][1:] in refs), None)
            geo = tr.select_one(".geo")
            lat = lon = None
            if geo:
                try:
                    lat, lon = (float(v) for v in geo.get_text().split(";"))
                except ValueError:
                    pass
            prov_txt = _texte(cell("Province")) if cell("Province") else ("Ontario" if section == "niagara" else "")
            dist = cell("Distinction")
            ajouter({"titre": _titre(a["href"]) if a else None, "nom": _texte(c_nom) if c_nom else None,
                     "prov": next((v for k, v in PROVINCES.items() if k in prov_txt), None), "section": section,
                     "distinction": _texte(dist) if dist else None, "st": st, "lat": lat, "lon": lon})
    # liste alphabétique : <h3>Province</h3> puis des listes à puces
    for h3 in soup.select("h3"):
        prov = PROVINCES.get(h3.get_text(strip=True))
        if not prov:
            continue
        bloc = h3.find_parent("div", class_="mw-heading") or h3
        for sib in bloc.find_next_siblings():
            if sib.name in ("h2", "h3") or (sib.name == "div" and "mw-heading" in (sib.get("class") or [])):
                break
            for li in sib.select("li"):
                liens = [x for x in li.select("a[href^='/wiki/']") if "new" not in (x.get("class") or []) and _titre(x["href"])]
                a = next((x for x in liens if RE_PONT.search(_titre(x["href"]))), liens[0] if liens else None)
                if a:
                    ajouter({"titre": _titre(a["href"]), "nom": _texte(a), "prov": prov, "section": "liste",
                             "distinction": None, "st": None, "lat": None, "lon": None})
    return out


# --- Articles, Wikidata, Commons --------------------------------------------------------------------
def couper(t: str | None, n: int) -> str | None:
    """Texte coupé à la dernière fin de phrase avant `n` caractères (paragraphes gardés)."""
    if not t:
        return None
    t = re.sub(r"\n{2,}", "\n", t.strip())
    if len(t) <= n:
        return t
    m = max(t.rfind(". ", 0, n), t.rfind(".\n", 0, n))
    return t[:m + 1] if m > n // 3 else t[:n].rsplit(" ", 1)[0] + "…"


def infos_articles(s, titres: list[str], lang: str, fetch: bool) -> dict[str, dict]:
    """Titre (tel que demandé) → {titre, q, lat, lon, image, resume, fr} pour les articles existants.
    v0.6.5 : introduction entière de l'article (avant : trois phrases), coupée à INTRO_MAX[lang] caractères."""
    out = {}
    for lot in _lots(sorted(set(titres)), 20):                       # 20 : limite des résumés par requête
        d = _get_json(s, API[lang], {"action": "query", "titles": "|".join(lot), "redirects": 1,
                                     "prop": "coordinates|pageimages|pageprops|extracts|langlinks", "colimit": "max",
                                     "piprop": "name", "ppprop": "wikibase_item", "exintro": 1, "explaintext": 1,
                                     "exlimit": "max", "lllang": "fr", "lllimit": "max"},
                      f"art2_{lang}_{_cle(*lot)}.json", fetch).get("query", {})
        alias = {}
        for k in ("normalized", "redirects"):
            for x in d.get(k, []):
                alias[x["to"]] = alias.get(x["from"], x["from"])
        for pg in d.get("pages", []):
            if pg.get("missing"):
                continue
            demande = pg["title"]
            while demande in alias:
                demande = alias[demande]
            co = (pg.get("coordinates") or [{}])[0]
            out[demande] = {"titre": pg["title"], "q": pg.get("pageprops", {}).get("wikibase_item"),
                            "lat": co.get("lat"), "lon": co.get("lon"), "image": pg.get("pageimage"),
                            "resume": couper(pg.get("extract"), INTRO_MAX[lang]),
                            "fr": (pg.get("langlinks") or [{}])[0].get("title")}
    return out


# --- Infobox (v0.6.5) : année de construction, portée, largeur, travées… -------------------------------
# Libellé de l'infobox → champ. Anglais : modèle « Infobox bridge » ; français : « Infobox Pont ».
IB_EN = {"total length": "long", "longest span": "portee", "width": "larg", "height": "haut", "clearance below": "degag",
         "no. of spans": "travees", "piers in water": "piles", "no. of lanes": "voies", "construction start": "debut",
         "construction end": "fin", "opened": "ouvert", "inaugurated": "inaug", "closed": "ferme", "collapsed": "ferme",
         "construction cost": "cout", "daily traffic": "trafic", "toll": "peage", "design": "conception", "material": "mat",
         "carries": "porte", "designer": "archi", "engineering design by": "archi", "architect": "archi",
         "constructed by": "constr", "fabrication by": "constr", "maintained by": "prop", "owner": "prop"}
IB_FR = {"longueur": "long", "portée principale": "portee", "largeur": "larg", "hauteur": "haut", "hauteur libre": "degag",
         "construction": "construction", "mise en service": "ouvert", "ouverture": "ouvert", "inauguration": "inaug",
         "fin du service": "ferme", "démolition": "ferme", "type": "conception", "matériau(x)": "mat", "matériau": "mat",
         "fonction": "porte", "architecte(s)": "archi", "architecte": "archi", "ingénieur(s)": "archi", "concepteur": "archi",
         "entreprise(s)": "constr", "propriétaire": "prop", "gestion": "prop", "maintenance": "prop", "protection": "patri"}
CHAMPS_M = ("long", "portee", "larg", "haut", "degag")
CHAMPS_N = ("travees", "piles", "voies")
CHAMPS_TXT = ("conception", "mat", "porte", "archi", "constr", "prop", "cout", "trafic", "peage", "patri")
INTRO_MAX = {"fr": 1400, "en": 1800}
TXT_MAX = 140
RE_ANNEE = re.compile(r"(?<!\d)(1[6-9]\d\d|20\d\d)(?!\d)")
RE_AGE = re.compile(r";?\s*\d+\s+(?:years?|months?|days?)\s+ago|;?\s*il y a \d+\s+ans?", re.I)
NOMBRE = {"en": r"(\d[\d,]*(?:\.\d+)?)", "fr": r"(\d[\d   ]*(?:,\d+)?)"}
UNITES_TXT = [(r"km|kilom[eè]t(?:re|er)s?", 1000.0), (r"m|m[eè]t(?:re|er)s?", 1.0),
              (r"ft|feet|foot|pi|pieds?", 0.3048), (r"mi|miles?", 1609.344)]
# Matériaux de l'infobox anglaise → français (liste fermée ; un mot inconnu fait garder le texte anglais)
MATERIAUX = {"steel": "acier", "concrete": "béton", "reinforced concrete": "béton armé", "prestressed concrete": "béton précontraint",
             "wood": "bois", "timber": "bois", "iron": "fer", "wrought iron": "fer forgé", "cast iron": "fonte", "stone": "pierre",
             "masonry": "maçonnerie", "earth": "terre", "aluminum": "aluminium", "aluminium": "aluminium", "granite": "granit",
             "brick": "brique", "asphalt": "asphalte", "rock": "roc", "rockfill": "enrochement"}


def _propre(td) -> str:
    """Texte d'une cellule d'infobox sans renvois, dates cachées (microformats) ni « il y a N ans »."""
    for el in td.select("sup, .reference, .noprint, style, [style*='display:none'], [style*='display: none']"):
        el.decompose()
    for br in td.select("br"):
        br.replace_with(", ")
    for li in td.select("li"):
        li.insert_after(", ")
    t = re.sub(r"\s+", " ", td.get_text(" ", strip=True).replace(" ", " "))
    t = RE_AGE.sub("", t)
    t = re.sub(r"\(\s*\d{4}-\d{2}-\d{2}\s*\)", "", t)                 # ( 1930-05-14 ) des modèles de date
    t = re.sub(r"\s+([,;.)])", r"\1", re.sub(r"\(\s+", "(", t))
    return re.sub(r"(,\s*)+$", "", re.sub(r",\s*,", ",", t)).strip(" ,;")


def infobox(page_html: str) -> dict[str, str]:
    """HTML rendu de la section 0 → {libellé en minuscules: texte} de la première infobox (vide si aucune)."""
    if not page_html:
        return {}
    soup = BeautifulSoup(page_html, "lxml")
    box = soup.select_one("table.infobox, div.infobox_v3, table.infobox_v2, div.infobox")
    out = {}
    if not box:
        return out
    for tr in box.select("tr"):
        th, td = tr.find("th", recursive=False), tr.find("td", recursive=False)
        if th and td:
            k = re.sub(r"\s+", " ", th.get_text(" ", strip=True).replace(" ", " ")).lower()
            v = _propre(td)
            if k and v and k not in out:
                out[k] = v
    return out


def _nombre(txt: str, lang: str) -> float | None:
    t = re.sub(r"[   ]", "", txt) if lang == "fr" else txt.replace(",", "")
    try:
        return float(t.replace(",", ".") if lang == "fr" else t)
    except ValueError:
        return None


def longueur_m(txt: str | None, lang: str = "en") -> float | None:
    """« 1,234 m (4,049 ft) », « 24 feet (7.3 m) », « 2 009 m » → mètres (unité métrique préférée, sinon pieds, milles)."""
    if not txt:
        return None
    for unite, k in UNITES_TXT:
        m = re.search(NOMBRE[lang] + r"\s*(?:" + unite + r")(?![a-zé])", txt, re.I)
        if m:
            v = _nombre(m.group(1).strip(), lang)
            if v:
                return round(v * k, 1)
    return None


def annee(txt: str | None) -> int | None:
    m = RE_ANNEE.search(txt or "")
    return int(m.group(1)) if m else None


def entier(txt: str | None) -> int | None:
    m = re.match(r"\s*(\d{1,3})(?!\d|[.,]\d)", txt or "")
    return int(m.group(1)) if m else None


def court(t: str, n: int = TXT_MAX) -> str:
    """Texte d'infobox limité à `n` caractères, coupé au mot avec « … »."""
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0].rstrip(" ,;:(") + "…"


def _materiaux(txt: str) -> str | None:
    """« Steel, wood, concrete » → « acier, bois, béton » ; None si un mot n'est pas dans MATERIAUX."""
    parts = [p.strip().lower() for p in re.split(r",| and | & |/", txt) if p.strip()]
    fr = [MATERIAUX.get(p) for p in parts]
    return ", ".join(dict.fromkeys(fr)) if parts and all(fr) else None


def faits_infobox(ib_en: dict, ib_fr: dict) -> dict:
    """Infobox anglaise et française → faits (français préféré pour les textes, anglais pour les nombres).
    Les textes repris de l'anglais sont listés dans « en » (affichés comme tels, en italique)."""
    def lire(ib, table):
        r = {}
        for k, v in ib.items():
            c = table.get(k)
            if c and c not in r:
                r[c] = v
        return r
    en, fr = lire(ib_en, IB_EN), lire(ib_fr, IB_FR)
    f, en_txt = {}, []
    for c in CHAMPS_M:
        v = longueur_m(en.get(c), "en") or longueur_m(fr.get(c), "fr")
        if v and 0.5 <= v <= 60_000:
            f[c] = v
    for c in CHAMPS_N:
        v = entier(en.get(c))
        if v:
            f[c] = v
    debut, fin = annee(en.get("debut")), annee(en.get("fin"))
    ans_fr = [int(a) for a in RE_ANNEE.findall(fr.get("construction", ""))]
    debut = debut or (ans_fr[0] if ans_fr else None)
    fin = fin or (ans_fr[-1] if len(ans_fr) > 1 else None)
    f["debut"], f["fin"] = debut, fin
    f["ouvert"] = annee(en.get("ouvert")) or annee(fr.get("ouvert")) or annee(en.get("inaug")) or annee(fr.get("inaug"))
    ferme = en.get("ferme") or fr.get("ferme")
    if ferme:
        f["ferme"] = court(ferme)
    for c in CHAMPS_TXT:
        if fr.get(c):
            f[c] = court(fr[c])
        elif en.get(c):
            tr = _materiaux(en[c]) if c == "mat" else None
            f[c] = court(tr or en[c])
            if not tr and c not in ("trafic", "voies"):
                en_txt.append(c)
    if en_txt:
        f["en"] = en_txt
    return {k: v for k, v in f.items() if v is not None}


def infoboxes(s, titres: list[str], lang: str, fetch: bool) -> dict[str, dict]:
    """Titre → infobox de l'article (section 0 rendue par l'API, une requête par article)."""
    out = {}
    for t in sorted(set(x for x in titres if x)):
        try:
            d = _get_json(s, API[lang], {"action": "parse", "page": t, "prop": "text", "section": 0, "redirects": 1,
                                         "disablelimitreport": 1, "disableeditsection": 1}, f"ib_{lang}_{_cle(t)}.json", fetch)
        except (OSError, ValueError) as e:                 # article renommé, cache absent : pas d'infobox
            log.warning("infobox %s:%s : %s", lang, t, e)
            continue
        out[t] = infobox(d.get("parse", {}).get("text", ""))
    return out


def _val(claims: dict, p: str):
    for c in claims.get(p, []):
        if c.get("rank") == "deprecated":
            continue
        dv = c.get("mainsnak", {}).get("datavalue")
        if dv:
            yield dv["value"]


def _metres(v) -> float | None:
    try:
        f = UNITES_M.get(v["unit"].rsplit("/", 1)[-1])
        return round(float(v["amount"]) * f, 1) if f else None
    except (KeyError, TypeError, ValueError):
        return None


def _annee(v) -> int | None:
    m = re.match(r"[+-]?(\d{4})", (v or {}).get("time", ""))
    return int(m.group(1)) if m else None


def entites(s, qids: list[str], fetch: bool, props: str = "claims|labels|sitelinks") -> dict[str, dict]:
    out = {}
    for lot in _lots(sorted(set(q for q in qids if q)), 50):
        d = _get_json(s, API["wd"], {"action": "wbgetentities", "ids": "|".join(lot), "props": props,
                                     "languages": "fr|en", "sitefilter": "frwiki|enwiki"},
                      f"wd_{_cle(props, *lot)}.json", fetch)
        out.update(d.get("entities", {}))
    return out


def libelle(e: dict | None) -> str | None:
    lb = (e or {}).get("labels", {})
    return (lb.get("fr") or lb.get("en") or {}).get("value")


def faits_wikidata(e: dict) -> dict:
    """Entité Wikidata → faits utiles (valeurs « élément » laissées en QID, traduites ensuite)."""
    cl = e.get("claims", {})
    f = {k: [v["id"] for v in _val(cl, p) if isinstance(v, dict) and "id" in v] for p, k in P_ITEMS.items()}
    f["type"] = [q for q in f["type"] if q not in TYPES_GENERIQUES] or f["type"]
    f["long"] = next((m for m in map(_metres, _val(cl, P_LONG)) if m), None)
    f["portee"] = next((m for m in map(_metres, _val(cl, P_PORTEE)) if m), None)
    f["ouverture"] = next((a for a in map(_annee, _val(cl, P_OUVERTURE)) if a), None)
    f["creation"] = next((a for a in map(_annee, _val(cl, P_DEBUT)) if a), None)
    f["an"] = f["ouverture"] or f["creation"]
    f["st"] = next(iter(_val(cl, P_STRUCTURAE)), None)
    f["image"] = next(iter(_val(cl, P_IMAGE)), None)
    f["commonscat"] = next(iter(_val(cl, P_COMMONSCAT)), None)
    co = next(iter(_val(cl, P_COORD)), None)
    f["lat"], f["lon"] = (co["latitude"], co["longitude"]) if co else (None, None)
    sl = e.get("sitelinks", {})
    f["fr"] = sl.get("frwiki", {}).get("title")
    f["en"] = sl.get("enwiki", {}).get("title")
    f["nom"] = libelle(e)
    return f


def _sans_html(t: str | None) -> str | None:
    if not t:
        return None
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()
    return t[:160] or None


def images(s, fichiers: list[str], fetch: bool) -> dict[str, dict]:
    """Nom de fichier → {src (miniature 480 px), page, auteur, licence} (fichiers de Commons seulement)."""
    out = {}
    for lot in _lots(sorted(set(f for f in fichiers if f)), 50):
        d = _get_json(s, API["commons"], {"action": "query", "titles": "|".join("File:" + f for f in lot),
                                          "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 480,
                                          "iiextmetadatafilter": "Artist|LicenseShortName"},
                      f"img_{_cle(*lot)}.json", fetch).get("query", {})
        norm = {x["to"]: x["from"] for x in d.get("normalized", [])}
        for pg in d.get("pages", []):
            ii = (pg.get("imageinfo") or [None])[0]
            if not ii or pg.get("missing"):
                continue
            meta = ii.get("extmetadata", {})
            nom = norm.get(pg["title"], pg["title"])[5:]
            out[nom.replace(" ", "_")] = out[nom] = {
                "src": (ii.get("thumburl") or ii.get("url") or "").split("?")[0] or None, "page": ii.get("descriptionurl"),
                "auteur": _sans_html(meta.get("Artist", {}).get("value")),
                "licence": _sans_html(meta.get("LicenseShortName", {}).get("value"))}
    return out


def choisir_photo(resultats: list[dict], noms: list[str | None]) -> str | None:
    """Fichiers de Commons (geosearch ou recherche) → le premier (le plus proche, ou le plus pertinent) dont le titre
    contient tous les mots significatifs d'un des noms du pont et un mot « pont » (bridge, crossing…). Sinon : aucun."""
    cles = [m for m in (mots(n) for n in noms) if m]
    for r in sorted(resultats, key=lambda r: r.get("dist", 0)):
        t = r.get("title", "").split(":", 1)[-1]
        if not RE_PHOTO.search(t):
            continue
        base = t.rsplit(".", 1)[0].replace("_", " ")
        if any(c <= mots(base) for c in cles) and RE_PONT.search(base):
            return t
    return None


def resultats_recherche(d: dict, lat: float, lon: float, max_km: float = 30) -> list[dict]:
    """Recherche de Commons (generator=search, prop=coordinates) → [{title, dist}] par pertinence, sans les fichiers
    non géolocalisés ou situés à plus de `max_km` du pont (même nom ailleurs : St. Louis Bridge du Missouri…)."""
    out = []
    for pg in sorted(d.get("query", {}).get("pages", []), key=lambda x: x.get("index", 0)):
        co = (pg.get("coordinates") or [None])[0]
        if not co:
            continue                                    # sans position, impossible d'écarter un homonyme
        else:
            dx = (co["lon"] - lon) * math.cos(math.radians(lat)) * M_PAR_DEGRE
            if math.hypot(dx, (co["lat"] - lat) * M_PAR_DEGRE) > max_km * 1000:
                continue
        out.append({"title": pg["title"], "dist": 0})
    return out


def photos_de_secours(s, ponts: list[dict], ent: dict, fetch: bool) -> dict[str, tuple[str, str]]:
    """Ponts sans image d'article → (fichier Commons, origine) : image Wikidata (P18), catégorie Commons (P373),
    sinon fichier trouvé par la recherche de Commons, sinon photo géolocalisée à moins de RAYON_PHOTO_M ; dans ces
    deux derniers cas, le titre du fichier doit reprendre le nom du pont et un mot « pont » (voir choisir_photo)."""
    out = {}
    for p in ponts:
        if p.get("img"):
            continue
        f = faits_wikidata(ent.get(p["q"], {}))
        if f["image"]:
            out[p["q"]] = (f["image"], "wikidata")
            continue
        if p["q"] in PHOTOS_CHOISIES:
            out[p["q"]] = (PHOTOS_CHOISIES[p["q"]], "choisie")
            continue
        if f["commonscat"]:
            d = _get_json(s, API["commons"], {"action": "query", "list": "categorymembers", "cmtype": "file",
                                              "cmtitle": "Category:" + f["commonscat"], "cmlimit": 50},
                          f"cat_{_cle(f['commonscat'])}.json", fetch)
            fic = next((m["title"][5:] for m in d.get("query", {}).get("categorymembers", []) if RE_PHOTO.search(m["title"])), None)
            if fic:
                out[p["q"]] = (fic, "categorie")
                continue
        noms = [p["nom"], p.get("en"), p.get("fr")]
        d = _get_json(s, API["commons"], {"action": "query", "generator": "search", "gsrnamespace": 6, "gsrlimit": 30,
                                          "gsrsearch": p.get("en") or p["nom"], "prop": "coordinates"},
                      f"rech_{_cle(p.get('en') or p['nom'])}.json", fetch)
        fic = choisir_photo(resultats_recherche(d, p["lat"], p["lon"]), noms)
        if fic:
            out[p["q"]] = (fic, "recherche")
            continue
        d = _get_json(s, API["commons"], {"action": "query", "list": "geosearch", "gsnamespace": 6, "gslimit": 50,
                                          "gscoord": f"{p['lat']}|{p['lon']}", "gsradius": RAYON_PHOTO_M},
                      f"geo_{_cle(p['lat'], p['lon'], RAYON_PHOTO_M)}.json", fetch)
        fic = choisir_photo(d.get("query", {}).get("geosearch", []), noms)
        if fic:
            out[p["q"]] = (fic, "proximite")
    return out


def ponts_qc_wikidata(s, fetch: bool) -> list[dict]:
    """Ponts géolocalisés de la boîte du Québec ayant un article fr ou en : [{q, lat, lon, fr, en, nom}…]."""
    (x0, y0), (x1, y1) = BOITE_QC
    q = ("SELECT DISTINCT ?item ?coord ?frT ?enT ?lbl WHERE { SERVICE wikibase:box { ?item wdt:P625 ?coord. "
         f'bd:serviceParam wikibase:cornerSouthWest "Point({x0} {y0})"^^geo:wktLiteral. '
         f'bd:serviceParam wikibase:cornerNorthEast "Point({x1} {y1})"^^geo:wktLiteral. }} '
         "?item wdt:P31/wdt:P279* wd:Q12280. "
         "OPTIONAL { ?fr schema:about ?item; schema:isPartOf <https://fr.wikipedia.org/>; schema:name ?frT } "
         "OPTIONAL { ?en schema:about ?item; schema:isPartOf <https://en.wikipedia.org/>; schema:name ?enT } "
         'OPTIONAL { ?item rdfs:label ?lbl FILTER(LANG(?lbl) = "fr") } FILTER(BOUND(?frT) || BOUND(?enT)) }')
    p = _cache("sparql_qc.json")
    if fetch:
        r = net.get(s, SPARQL, params={"query": q, "format": "json"}, timeout=120)
        DOSSIER_RAW.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
    vus, out = set(), []
    for b in json.loads(p.read_text(encoding="utf-8"))["results"]["bindings"]:
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", b["coord"]["value"])
        if qid in vus or not m:
            continue
        vus.add(qid)
        g = lambda k: b.get(k, {}).get("value")
        out.append({"q": qid, "lon": float(m.group(1)), "lat": float(m.group(2)), "fr": g("frT"), "en": g("enT"),
                    "nom": g("lbl") or g("frT") or g("enT")})
    return out


# --- Appariement avec le MTMD -----------------------------------------------------------------------
def _ascii(t: str) -> str:
    return unicodedata.normalize("NFD", t).encode("ascii", "ignore").decode().lower()


def natures(nom: str | None) -> frozenset:
    return frozenset(w for w in re.split(r"[^a-z0-9]+", _ascii(nom or "")) if w in NATURES)


def mots(nom: str | None) -> frozenset:
    """Mots significatifs d'un nom de pont (sans accents, sans « pont », articles ni parenthèses)."""
    if not nom:
        return frozenset()
    t = _ascii(re.sub(r"\(.*?\)", " ", nom))
    t = re.sub(r"\b(st|ste)\b\.?", lambda m: "saint" if m.group(1) == "st" else "sainte", t)
    return frozenset(w for w in re.split(r"[^a-z0-9]+", t) if w and w not in MOTS_VIDES)


def meme_nom(a: frozenset, b: frozenset) -> bool:
    """Tous les mots significatifs du nom le plus court figurent dans l'autre."""
    if not a or not b:
        return False
    court, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return court <= long_


def charger_mtmd(structures_js: Path = DATA_DIR / "structures.js") -> list[tuple]:
    """Ouvrages nommés et géolocalisés de l'inventaire : [(n°, nom, lat, lon)…]."""
    S = json.loads(structures_js.read_text(encoding="utf-8").split("=", 1)[1].rstrip().rstrip(";"))
    ix = {c: i for i, c in enumerate(S["cols"])}
    return [(r[ix["num"]], r[ix["nom"]], r[ix["lat"]], r[ix["lon"]]) for r in S["rows"]
            if r[ix["nom"]] and r[ix["lat"]] is not None and r[ix["lon"]] is not None]


def apparier(cands: list[dict], mtmd: list[tuple], max_m: float = DISTANCE_MAX_M) -> dict[str, list[str]]:
    """Candidats {q, lat, lon, noms: [...]} → {q: [n° du MTMD de même nom à ≤ max_m]} (vides omis)."""
    pas = max_m / M_PAR_DEGRE
    grille: dict[tuple, list] = {}
    for num, nom, lat, lon in mtmd:
        grille.setdefault((math.floor(lat / pas), math.floor(lon / pas)), []).append((num, mots(nom), natures(nom), lat, lon))
    out = {}
    for c in cands:
        if c.get("lat") is None:
            continue
        cles = [mots(n) for n in c["noms"] if n]
        nat = frozenset().union(*(natures(n) for n in c["noms"] if n))
        ci, cj = math.floor(c["lat"] / pas), math.floor(c["lon"] / pas)
        kx = math.cos(math.radians(c["lat"])) * M_PAR_DEGRE
        dj = math.ceil(1 / max(math.cos(math.radians(c["lat"])), 0.05))
        trouves = []
        for i in range(ci - 1, ci + 2):
            for j in range(cj - dj, cj + dj + 1):
                for num, mm, nn, la, lo in grille.get((i, j), ()):
                    d = math.hypot((la - c["lat"]) * M_PAR_DEGRE, (lo - c["lon"]) * kx)
                    if d <= max_m and nn <= nat and any(meme_nom(k, mm) for k in cles):
                        trouves.append((d, num))
        if trouves:
            out[c["q"]] = [n for _, n in sorted(trouves)]
    return out


# --- Assemblage -------------------------------------------------------------------------------------
def construire(liste: list[dict], art_en: dict, art_fr: dict, ent: dict, lib: dict, imgs: dict,
               qc: list[dict], mtmd: list[tuple], ib_en: dict | None = None, ib_fr: dict | None = None) -> dict:
    ponts, vus = [], set()
    ib_en, ib_fr = ib_en or {}, ib_fr or {}
    for e in liste:
        a = art_en.get(e["titre"])
        if not a or not a["q"] or a["q"] in vus:        # deux entrées de la liste peuvent mener au même article
            continue
        vus.add(a["q"])
        f = faits_wikidata(ent.get(a["q"], {}))
        types = " ".join(x for q in f["type"] for x in ((lib.get(q) or {}).get("labels", {}).get(l, {}).get("value", "") for l in ("fr", "en")))
        if not (RE_PONT.search(a["titre"]) or RE_PONT.search(types)):
            continue                                    # lien de la liste vers une ville, une route…
        lat = e["lat"] if e["lat"] is not None else a["lat"] if a["lat"] is not None else f["lat"]
        lon = e["lon"] if e["lon"] is not None else a["lon"] if a["lon"] is not None else f["lon"]
        if lat is None or lon is None:
            continue
        fr_titre = f["fr"] or a["fr"]
        afr = art_fr.get(fr_titre) if fr_titre else None
        noms = lambda k: ", ".join(dict.fromkeys(x for x in (libelle(lib.get(q)) for q in f[k]) if x)) or None
        nom = f["nom"] or e["nom"] or a["titre"]
        ib = faits_infobox(ib_en.get(a["titre"], {}), ib_fr.get(fr_titre, {}) if fr_titre else {})
        # v0.6.5 : textes de Wikidata (libellés français) d'abord, puis infobox ; textes anglais signalés dans « txtEn »
        en_txt = set(ib.get("en", []))
        texte = lambda k, wd: wd or ib.get(k)
        p = {"id": a["q"], "nom": nom[:1].upper() + nom[1:], "nomEn": a["titre"], "prov": e["prov"],
             "section": e["section"], "lat": round(lat, 5), "lon": round(lon, 5),
             "an": f["ouverture"] or ib.get("ouvert") or ib.get("fin") or f["creation"],
             "debut": ib.get("debut") or (f["creation"] if f["creation"] and f["ouverture"] and f["creation"] < f["ouverture"] else None),
             "fin": ib.get("fin"), "ferme": ib.get("ferme"),
             "type": noms("type"), "conception": ib.get("conception"), "long": f["long"] or ib.get("long"),
             "portee": f["portee"] or ib.get("portee"), "larg": ib.get("larg"), "haut": ib.get("haut"),
             "degag": ib.get("degag"), "travees": ib.get("travees"), "piles": ib.get("piles"), "voies": ib.get("voies"),
             "mat": texte("mat", noms("mat")), "franchit": noms("franchit"), "porte": ib.get("porte"),
             "archi": texte("archi", noms("archi")), "constr": ib.get("constr"), "prop": texte("prop", noms("prop")),
             "patri": texte("patri", noms("patri")), "cout": ib.get("cout"), "trafic": ib.get("trafic"),
             "peage": ib.get("peage"), "distinction": e["distinction"], "fr": fr_titre, "en": a["titre"], "q": a["q"],
             "st": f["st"] or e["st"]}
        if p["debut"] and p["an"] and p["debut"] > p["an"]:
            p["debut"] = None                           # « début » postérieur à la mise en service : reconstruction
        if p["fin"] and p["fin"] == p["an"]:
            p["fin"] = None
        txt_en = sorted(k for k in en_txt if k in p and p[k] == ib.get(k))
        if txt_en:
            p["txtEn"] = txt_en
        if afr and afr.get("resume"):
            p["resume"], p["resumeLang"] = afr["resume"], "fr"
            # l'introduction anglaise est souvent bien plus fournie : gardée quand elle double au moins le français
            if a["resume"] and len(a["resume"]) > 1.6 * len(afr["resume"]):
                p["resumeEn"] = a["resume"]
        elif a["resume"]:
            p["resume"], p["resumeLang"] = a["resume"], "en"
        img = imgs.get((afr or {}).get("image") or "") or imgs.get(a["image"] or "")
        if img and img.get("src"):
            p["img"] = img
        ponts.append({k: v for k, v in p.items() if v is not None})
    # appariement : ponts de la liste situés au Québec + ponts de Wikidata (boîte du Québec)
    cands = [{"q": p["q"], "lat": p["lat"], "lon": p["lon"], "noms": [p["nom"], p["en"], p.get("fr")]}
             for p in ponts if p.get("prov") == "Québec"]
    cands += [{"q": x["q"], "lat": x["lat"], "lon": x["lon"], "noms": [x["nom"], x["fr"], x["en"]]} for x in qc]
    liens = apparier(cands, mtmd)
    par_q = {p["q"]: p for p in ponts}
    par_q_qc = {x["q"]: x for x in qc}
    mt = {}
    for q, nums in liens.items():
        src = par_q.get(q) or par_q_qc[q]
        st = (par_q.get(q) or {}).get("st") or faits_wikidata(ent.get(q, {})).get("st")
        pontish = lambda t: t if t and RE_PONT.search(t) else None       # pas de lien vers l'article d'une ville
        lien = {k: v for k, v in {"fr": pontish(src.get("fr")), "en": pontish(src.get("en")), "q": q, "st": st}.items() if v}
        if not (lien.get("fr") or lien.get("en")):
            continue
        for n in nums:
            mt.setdefault(n, lien)
    etoiles = [p for p in ponts if p["q"] not in liens]
    etoiles.sort(key=lambda p: (p.get("prov") or "~", p["nom"]))
    return {"generated": date.today().isoformat(), "source": URL_LISTE, "attribution": ATTRIBUTION,
            "mtmd": dict(sorted(mt.items())), "ponts": etoiles}


def run(fetch: bool = True) -> dict:
    s = net.session()
    p = _cache("liste.json")
    if fetch:
        r = net.get(s, API["en"], params={"action": "parse", "page": LISTE, "prop": "text", "format": "json",
                                          "formatversion": "2"}, timeout=90)
        DOSSIER_RAW.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
    liste = parse_liste(json.loads(p.read_text(encoding="utf-8"))["parse"]["text"])
    art_en = infos_articles(s, [e["titre"] for e in liste], "en", fetch)
    qc = ponts_qc_wikidata(s, fetch)
    ent = entites(s, [a["q"] for a in art_en.values()] + [x["q"] for x in qc], fetch)
    titres_fr = [f["fr"] for f in (faits_wikidata(ent[a["q"]]) for a in art_en.values() if a["q"] in ent) if f["fr"]]
    art_fr = infos_articles(s, titres_fr, "fr", fetch)
    vals = {q for a in art_en.values() if a["q"] in ent for k in P_ITEMS.values() for q in faits_wikidata(ent[a["q"]])[k]}
    lib = entites(s, sorted(vals), fetch, props="labels")
    imgs = images(s, [a["image"] for a in art_en.values()] + [a["image"] for a in art_fr.values()], fetch)
    ib_en = infoboxes(s, [a["titre"] for a in art_en.values()], "en", fetch)
    ib_fr = infoboxes(s, [a["titre"] for a in art_fr.values()], "fr", fetch)
    ib_fr.update({t: ib_fr[a["titre"]] for t, a in art_fr.items() if a["titre"] in ib_fr})   # titre demandé → infobox
    payload = construire(liste, art_en, art_fr, ent, lib, imgs, qc, charger_mtmd(), ib_en, ib_fr)
    secours = photos_de_secours(s, payload["ponts"], ent, fetch)
    imgs2 = images(s, [f for f, _ in secours.values()], fetch)
    for p in payload["ponts"]:
        f, origine = secours.get(p["q"], (None, None))
        img = imgs2.get(f or "") or imgs2.get((f or "").replace(" ", "_"))
        if img and img.get("src"):
            p["img"] = {**img, "origine": origine}
        elif not p.get("img") and p["q"] in PHOTOS_EXTERNES:
            p["img"] = {**PHOTOS_EXTERNES[p["q"]], "site": "Flickr", "origine": "flickr"}
    corps = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(f"window.PQ_COUCHES=window.PQ_COUCHES||{{}};window.PQ_COUCHES.wikiponts={corps};\n",
                   encoding="utf-8", newline="\n")
    return {"path": OUT, "bytes": OUT.stat().st_size, "liste": len(liste), "articles": len(art_en),
            "qc_wikidata": len(qc), "mtmd": len(payload["mtmd"]), "rows": len(payload["ponts"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m etl.wikiponts", description=__doc__.splitlines()[0])
    ap.add_argument("--no-fetch", action="store_true", help="relit data/raw/wikiponts/ au lieu de télécharger")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    r = run(fetch=not args.no_fetch)
    print(f"{r['path']} : {r['liste']} entrées de la liste, {r['articles']} articles, {r['qc_wikidata']} ponts "
          f"Wikidata (Québec) ; {r['mtmd']} ouvrages du MTMD liés, {r['rows']} ponts remarquables hors inventaire, "
          f"{r['bytes'] / 1e3:.0f} Ko")
    return 0


if __name__ == "__main__":
    sys.exit(main())
