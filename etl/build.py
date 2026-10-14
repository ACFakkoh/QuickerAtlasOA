"""Export de la table `structure` vers `data/structures.js` pour le visualiseur.

Chargé par `<script src>` (et non `fetch`) pour fonctionner aussi en `file://`.
Format compact : une ligne = un tableau dans l'ordre de `cols` ; les colonnes
très répétées (région, réseau, limite de charge) sont codées par index dans `enums`.
"""
import json
import re

from .config import DATA_DIR

EXPORT_PATH = DATA_DIR / "structures.js"

# (nom exporté, colonne SQL, enum ?)
COLS = [
    ("num", "num_dossr", False),
    ("nom", "nom", False),
    ("type", "type_code", False),
    ("reseau", "reseau", True),
    ("region", "region", True),
    ("muncp", "municipalite", False),
    ("route", "route", False),
    ("obstacle", "obstacle", False),
    ("annee", "annee_construction", False),
    ("voies", "nb_voies", False),
    ("long", "longueur_m", False),
    ("larg", "largeur_m", False),
    ("lat", "lat", False),
    ("lon", "lon", False),
    ("icg", "icg", False),
    ("ias", "ias", False),
    ("travaux", "annee_travaux", False),
    ("rapport", "rapport_dispo", False),
    ("limH", "lim_hauteur", False),
    ("limP", "lim_poids", False),
    ("charge", "limite_charge", True),
    ("hmin", "hauteur_libre_min_m", False),
    ("ide", "ide_strct", False),
    ("cs", "fiche_url", False),          # seulement le checksum `cs` de l'URL de fiche
    ("public", "in_apex", False),
    ("obst", None, True),                # classe d'obstacle calculée (voir classe_obstacle)
]

# --- Classe d'obstacle (légende « type d'obstacle ») ---------------------------------
OBST_PAR_TYPE_VOIE = {
    "Cours d'eau": "Cours d'eau", "Route standard": "Route", "Chemin privé": "Route", "Stationnement": "Route",
    "Chemin de fer": "Chemin de fer", "Passage pour piétons, cyclistes, motoneiges, VTT": "Piétons, cyclistes, VTT",
    "Passages pour animaux": "Faune", "Autre": "Autre",
}
_SEGMENT = [   # mot de tête d'un segment de texte → classe
    ("Chemin de fer", re.compile(r"^(chemin de fer|voie ferr|ch\.? de fer|CN|CP|CFQ)", re.I)),
    ("Cours d'eau", re.compile(r"^(rivi|riv\.|ruisseau|ruiss|lac|d[ée]charge|d[ée]ch|d[ée]ch\.|fleuve|cours d.eau|bras|chenal|baie|crique|branche)", re.I)),
    ("Route", re.compile(r"^(route|rte|autoroute|aut\.|[AR]-\d|rue|rues|chemin|ch\.|boul|bretelle|racc|rang|rg|avenue|av\.|mont[ée]e|sortie|voie|[ée]changeur|rond-point)", re.I)),
]


def classe_obstacle(type_voie: str | None, texte: str | None) -> str | None:
    """Classe d'obstacle ; « Mixte » si le texte nomme à la fois cours d'eau, route ou chemin de fer
    (« Rivière X et route 132 »). Le type de voie de la fiche prime, le texte sert à repérer le mixte."""
    vus = []
    for seg in re.split(r"\s+et\s+|/|,|;", texte or ""):
        seg = seg.strip(" .()")
        for cls, rx in _SEGMENT:
            if rx.search(seg):
                if cls not in vus:
                    vus.append(cls)
                break
    base = OBST_PAR_TYPE_VOIE.get(type_voie) if type_voie else None
    principales = {"Cours d'eau", "Route", "Chemin de fer"}
    if len(principales.intersection(vus + ([base] if base else []))) > 1:
        return "Mixte"
    return base or (vus[0] if vus else None)


def _rows(conn):
    cols = ", ".join(f"s.{c}" for _, c, _ in COLS if c)
    sql = (f"SELECT {cols}, d.obstacle_type_voie FROM structure s"
           " LEFT JOIN structure_detail d USING (num_dossr) ORDER BY s.num_dossr")
    return [tuple(r[:-1]) + (classe_obstacle(r[-1], r["obstacle"]),) for r in conn.execute(sql)]


def export(conn, path=EXPORT_PATH) -> dict:
    enums: dict[str, list] = {name: [] for name, _, is_enum in COLS if is_enum}
    index: dict[str, dict] = {name: {} for name in enums}
    out_rows = []
    for r in _rows(conn):
        row = []
        for (name, col, is_enum), v in zip(COLS, r):
            if name == "cs":
                m = re.search(r"[?&]cs=([0-9A-Za-z]+)", v or "")
                v = m.group(1) if m else None
            elif name in ("lat", "lon") and v is not None:
                v = round(v, 5)                                   # ~1 m
            if is_enum and v is not None:
                if v not in index[name]:
                    index[name][v] = len(enums[name])
                    enums[name].append(v)
                v = index[name][v]
            row.append(v)
        while row and row[-1] is None:                            # queue de None superflue
            row.pop()
        out_rows.append(row)

    types = {r["code"]: [r["libelle"], r["famille"]]
             for r in conn.execute("SELECT code, libelle, famille FROM type_structure")}
    runs = {r["source"]: r["finished_at"][:10] for r in conn.execute(
        "SELECT source, MAX(finished_at) finished_at FROM source_run WHERE status = 'ok' GROUP BY source")}
    payload = {
        "generated": max(runs.values()) if runs else None,
        "sources": runs,
        "ficheUrl": "https://www.diffusion.transports.gouv.qc.ca/ords/pes/f?p=122:53::::53:P53_IDE_STRCT_0001:{ide}&cs={cs}",
        "rapportUrl": "https://www.transports.gouv.qc.ca/fr/projets-infrastructures/structures/Pages/rapport-inspection-general.aspx?NumDossier={num}",
        "cols": [name for name, _, _ in COLS],
        "enums": enums,
        "types": types,
        "rows": out_rows,
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(f"window.STRUCTURES={body};\n", encoding="utf-8")
    return {"path": path, "rows": len(out_rows), "bytes": path.stat().st_size}


# --- Détails (data/details.js) ------------------------------------------------------
DETAILS_PATH = DATA_DIR / "details.js"
PHOTO_URL = "https://www.diffusion.transports.gouv.qc.ca/ords/pes/APEX_PES.P_PESB_AFFCH_IMAGE?pIDE_STRCT={ide}"

# (clé SQL, clé courte dans le JS, libellé, section, unité) — ordre d'affichage dans la fiche
DETAIL_FIELDS = [
    ("mrc", "m", "MRC", "Identification", ""),
    ("cep", "c", "Circonscription électorale", "Identification", ""),
    ("classe_route", "cr", "Classe de la route", "Localisation", ""),
    ("route_type_voie", "rtv", "Voie portée", "Localisation", ""),
    ("obstacle_type_voie", "otv", "Obstacle franchi", "Localisation", ""),
    ("obstacle_classe_route", "ocr", "Classe de la route franchie", "Localisation", ""),
    ("longueur_totale_m", "ltm", "Longueur totale", "Dimensions", "m"),
    ("longueur_tablier_m", "ltb", "Longueur du tablier", "Dimensions", "m"),
    ("largeur_hors_tout_m", "lht", "Largeur hors tout", "Dimensions", "m"),
    ("largeur_carrossable_m", "lcm", "Largeur carrossable", "Dimensions", "m"),
    ("superficie_tablier_m2", "stm", "Superficie du tablier", "Dimensions", "m²"),
    ("ponceau_ouverture_m", "pom", "Ouverture totale", "Dimensions", "m"),
    ("ponceau_superficie_m2", "psm", "Superficie totale", "Dimensions", "m²"),
    ("remblai_epaisseur_m", "rem", "Épaisseur du remblai", "Dimensions", "m"),
    ("mur_longueur_m", "mlm", "Longueur du mur", "Dimensions", "m"),
    ("mur_hauteur_moy_m", "mhm", "Hauteur moyenne", "Dimensions", "m"),
    ("mur_superficie_m2", "msm", "Superficie du mur", "Dimensions", "m²"),
    ("tunnel_longueur_m", "tlm", "Longueur du tunnel", "Dimensions", "m"),
    ("tunnel_largeur_m", "tla", "Largeur du tunnel", "Dimensions", "m"),
    ("tunnel_superficie_m2", "tsm", "Superficie du tunnel", "Dimensions", "m²"),
    ("biais_angle_deg", "bad", "Angle de biais", "Dimensions", "°"),
    ("djma", "d", "Débit journalier moyen annuel (DJMA)", "Circulation", "véh./j"),
    ("pct_camion", "pc", "Proportion de camions", "Circulation", "%"),
    ("nb_voies", "nv", "Voies de circulation", "Circulation", ""),
    ("travaux_description", "td", "Description des travaux", "État et interventions", ""),
    ("commentaire", "com", "Commentaire", "État et interventions", ""),
    ("panneau", "p", "Panneau de limitation de poids", "Restrictions", ""),
    ("poids_vehicule_t", "pv", "Limite — véhicule routier", "Restrictions", "t"),
    ("poids_ensemble2_t", "pe2", "Limite — ensemble de 2 unités", "Restrictions", "t"),
    ("poids_ensemble3_t", "pe3", "Limite — ensemble de plus de 2 unités", "Restrictions", "t"),
    ("limite_maj", "lm", "Limitation mise à jour le", "Restrictions", ""),
    ("hauteurs_mesurees", "hm", "Hauteurs libres mesurées", "Restrictions", ""),
    ("inspection_generale", "ig", "Dernière inspection générale", "Inspections", ""),
    ("inspection_sommaire", "is", "Dernière inspection sommaire", "Inspections", ""),
    ("frequence_inspection_ans", "fia", "Fréquence des inspections générales", "Inspections", "ans"),
    ("prochaine_inspection", "pi", "Prochaine inspection générale", "Inspections", ""),
]


def _fr(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _hauteurs_mesurees(conn) -> dict[str, str]:
    """« Est : 4,76 m · Ouest : 4,79 m (mesuré 2018-07-25) » par structure (minimum par direction)."""
    par_num: dict[str, dict] = {}
    for r in conn.execute("SELECT num_dossr, direction, MIN(h_min_m) h, MAX(date_mesure) d FROM hauteur_libre_detail"
                          " WHERE h_min_m IS NOT NULL GROUP BY num_dossr, direction ORDER BY num_dossr, direction"):
        e = par_num.setdefault(r["num_dossr"], {"dirs": [], "date": None})
        e["dirs"].append(f"{r['direction'] or '?'} : {_fr(r['h'])} m")
        e["date"] = max(filter(None, [e["date"], r["d"]]), default=None)
    return {n: " · ".join(e["dirs"]) + (f" (mesuré {e['date']})" if e["date"] else "") for n, e in par_num.items()}


def export_details(conn, path=DETAILS_PATH) -> dict:
    hauteurs = _hauteurs_mesurees(conn)
    limites = {r["num_dossr"]: dict(r) for r in conn.execute("SELECT * FROM limite_poids")}
    keys = [(k, short) for k, short, *_ in DETAIL_FIELDS]
    data = {}
    for r in conn.execute("SELECT d.*, s.famille FROM structure_detail d JOIN structure s USING (num_dossr)"):
        d = dict(r)
        lim = limites.get(d["num_dossr"], {})
        d.update({k: lim.get(k) for k in ("panneau", "poids_vehicule_t", "poids_ensemble2_t", "poids_ensemble3_t")})
        d["limite_maj"] = lim.get("date_maj")
        d["hauteurs_mesurees"] = hauteurs.get(d["num_dossr"])
        row = {short: d[k] for k, short in keys if d.get(k) not in (None, "")}
        if d["famille"] == "pont":                 # les fiches de ponts ont une photo ; les autres rarement
            row["photo"] = 1
        data[d["num_dossr"]] = row
    # base neuve ou import OData jamais réussi : date absente plutôt qu'un plantage (audit v0.5.5 n° 4)
    fini = conn.execute("SELECT MAX(finished_at) FROM source_run WHERE source = 'odata_tabbord'"
                        " AND status = 'ok'").fetchone()[0]
    payload = {
        "generated": fini[:10] if fini else None,
        "photoUrl": PHOTO_URL,
        "fields": [{"key": short, "label": l, "section": s, "unit": u} for _, short, l, s, u in DETAIL_FIELDS],
        "data": data,
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(f"window.STRUCTURE_DETAILS={body};\n", encoding="utf-8")
    return {"path": path, "rows": len(data), "bytes": path.stat().st_size}


# --- Journal des changements (data/journal.js, panneau « Quoi de neuf ») -------------------
JOURNAL_PATH = DATA_DIR / "journal.js"
JOURNAL_JOURS = 730                     # profondeur exportée (le reste reste dans la base)


def export_journal(conn, path=JOURNAL_PATH, today: str | None = None) -> dict:
    """`window.PQ_JOURNAL = {generated, debut, runs, items}` :
      debut : date du premier run réussi (début du suivi) ;
      runs  : [[date, nb de changements]…] des consolidations, la plus récente d'abord ;
      items : [[date, n° de structure, genre, champ, ancien, nouveau]…], le plus récent d'abord
              (genre = ajout | retrait | modif ; queue de None retirée)."""
    from datetime import date, timedelta
    today = today or date.today().isoformat()
    debut = conn.execute("SELECT MIN(started_at) FROM source_run WHERE status = 'ok'").fetchone()[0]
    limite = (date.fromisoformat(today) - timedelta(days=JOURNAL_JOURS)).isoformat()
    runs: dict[str, int] = {}
    for r in conn.execute("SELECT finished_at, note FROM source_run WHERE source = 'consolidation' AND status = 'ok'"
                          " ORDER BY finished_at DESC"):
        m = re.match(r"(\d+)", r["note"] or "")
        runs[r["finished_at"][:10]] = runs.get(r["finished_at"][:10], 0) + (int(m.group(1)) if m else 0)
    items = []
    for r in conn.execute("SELECT detected_at, num_dossr, kind, champ, ancien, nouveau FROM changement"
                          " WHERE detected_at >= ? ORDER BY detected_at DESC, num_dossr, id", (limite,)):
        row = [r["detected_at"][:10], r["num_dossr"], r["kind"], r["champ"], r["ancien"], r["nouveau"]]
        while row and row[-1] is None:
            row.pop()
        items.append(row)
    payload = {"generated": today, "debut": debut[:10] if debut else None,
               "runs": [[d, n] for d, n in runs.items()], "items": items}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(f"window.PQ_JOURNAL={body};\n", encoding="utf-8")
    return {"path": path, "rows": len(items), "bytes": path.stat().st_size}
