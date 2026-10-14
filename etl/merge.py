"""Consolidation des sources dans `structure` + journal des changements + rapport."""
import re
import sqlite3
from collections import Counter, defaultdict

from . import db

# Champs suivis dans le journal des changements
TRACKED = ("nom", "type_code", "reseau", "icg", "ias", "annee_travaux",
           "lim_hauteur", "lim_poids", "limite_charge", "hauteur_libre_min_m")

RESEAU_PAR_RESPN = {10: "Supérieur", 13: "Municipal"}   # mêmes codes que le filtre APEX
HAUTEUR_SANS_LIMITE = 10.0


def famille(code: int | None) -> str | None:
    if code is None:
        return None
    if code <= 29:
        return "ponceau"
    if code <= 89:
        return "pont"
    return {94: "tunnel", 97: "mur", 98: "station"}.get(code, "autre")


# DG du WFS sans équivalent direct dans les régions APEX
REGION_ALIAS = {
    "Nouvelle Autoroute 30 S.E.N.C.": "Montérégie",
    "Concession A25 S.E.C.": "Métropole",
    "Saguenay - Lac-Saint-Jean": "Saguenay-Lac-Saint-Jean",
}


def region_depuis_dg(dg: str | None) -> str | None:
    """« Direction générale de l'Abitibi-Témiscamingue » → « Abitibi-Témiscamingue »."""
    if not dg:
        return None
    if "réseau métropolitain" in dg:
        return "Métropole"
    m = re.match(r"Direction générale (?:de la |de l'|du |des |d'|de )?(.+)", dg)
    r = m.group(1) if m else dg
    r = r[0].upper() + r[1:]
    return REGION_ALIAS.get(r, r)


def _rows(conn, sql) -> list[sqlite3.Row]:
    return conn.execute(sql).fetchall()


# Coquilles des libellés APEX (le WFS abrège le 36 en « Port. béton armé, ss remblai »)
LIBELLE_CORRIGE = {36: "Portique en béton armé sous remblai"}


def build_types(conn) -> None:
    labels: dict[int, str] = {}
    for r in _rows(conn, "SELECT DISTINCT type_code, type_libelle FROM wfs_structure WHERE type_code IS NOT NULL"):
        labels[r["type_code"]] = r["type_libelle"]
    # Les libellés APEX sont complets (le WFS les abrège : « Pont à pout. béton précont. »)
    for r in _rows(conn, "SELECT type_code, type_libelle, COUNT(*) n FROM apex_structure "
                         "WHERE type_code IS NOT NULL GROUP BY 1, 2 ORDER BY n"):
        labels[r["type_code"]] = r["type_libelle"]
    labels.update({c: l for c, l in LIBELLE_CORRIGE.items() if c in labels})
    db.replace_table(conn, "type_structure",
                     [{"code": c, "libelle": l, "famille": famille(c)} for c, l in sorted(labels.items())])


def build(conn) -> None:
    started = db.now()
    build_types(conn)
    wfs = {r["num_dossr"]: r for r in _rows(conn, "SELECT * FROM wfs_structure")}
    apex = {r["num_dossr"]: r for r in _rows(conn, "SELECT * FROM apex_structure")}

    # Hauteurs ≥ 10 m : valeurs « sans limite » du répertoire, ignorées pour le minimum
    hauteur = {r["num_dossr"]: r["h"] for r in _rows(
        conn, "SELECT num_dossr, MIN(h) h FROM ("
              " SELECT num_dossr, hauteur_so_m h FROM hauteur_libre UNION ALL"
              " SELECT num_dossr, hauteur_ne_m FROM hauteur_libre)"
              f" WHERE h < {HAUTEUR_SANS_LIMITE} AND num_dossr IS NOT NULL GROUP BY num_dossr")}
    # GPS.csv n'a pas d'identifiant : jointure sur les coordonnées exactes du WFS
    par_coord = {(round(w["lat"], 6), round(w["lon"], 6)): n for n, w in wfs.items() if w["lat"] is not None}
    charge = {}
    for g in _rows(conn, "SELECT lat, lon, limite_charge FROM gps_point"):
        n = par_coord.get((round(g["lat"], 6), round(g["lon"], 6)))
        if n:
            charge[n] = g["limite_charge"]

    # Région : libellé APEX ; sinon région APEX dominante de la municipalité ; sinon déduite de la DG
    par_muncp: dict[int, Counter] = defaultdict(Counter)
    for n, a in apex.items():
        if n in wfs and a["direction_territoriale"]:
            par_muncp[wfs[n]["cod_muncp"]][a["direction_territoriale"]] += 1

    def region(w, a):
        if a is not None and a["direction_territoriale"]:
            return a["direction_territoriale"]
        if w is None:
            return None
        if par_muncp.get(w["cod_muncp"]):
            return par_muncp[w["cod_muncp"]].most_common(1)[0][0]
        return region_depuis_dg(w["direction_generale"])

    rows = []
    for num in sorted(wfs.keys() | apex.keys()):
        w, a = wfs.get(num), apex.get(num)
        g = lambda k: (a[k] if a is not None and a[k] is not None else (w[k] if w is not None else None))
        type_code = g("type_code")
        h = hauteur.get(num)
        rows.append({
            "num_dossr": num,
            "ide_strct": g("ide_strct"),
            "nom": g("nom"),
            "type_code": type_code,
            "famille": famille(type_code),
            "reseau": (a["reseau"] if a else None) or (RESEAU_PAR_RESPN.get(w["cod_respn"]) if w else None),
            "region": region(w, a),
            "municipalite": g("municipalite"),
            "route": g("route"),
            "obstacle": g("obstacle"),
            "annee_construction": w["annee_construction"] if w else None,
            "nb_voies": w["nb_voies"] if w else None,
            "longueur_m": w["longueur_m"] if w else None,
            "largeur_m": w["largeur_m"] if w else None,
            "lat": w["lat"] if w else None,
            "lon": w["lon"] if w else None,
            "icg": a["icg"] if a else None,
            "ias": a["ias"] if a else None,
            "annee_travaux": a["annee_travaux"] if a else None,
            "rapport_dispo": a["rapport_dispo"] if a else None,
            "lim_hauteur": a["lim_hauteur"] if a else None,
            "lim_poids": a["lim_poids"] if a else None,
            "limite_charge": charge.get(num),
            "hauteur_libre_min_m": h,
            "fiche_url": a["fiche_url"] if a else None,
            "in_wfs": int(w is not None),
            "in_apex": int(a is not None),
        })
    old = {r["num_dossr"]: dict(r) for r in _rows(conn, "SELECT * FROM structure")}
    with conn:                                       # journal et remplacement : tout ou rien
        n = journaliser(conn, old, {r["num_dossr"]: r for r in rows}, TRACKED, presence=True, commit=False)
        db.replace_table(conn, "structure", rows, commit=False)
    db.record_run(conn, "consolidation", started, status="ok", rows=len(rows), note=f"{n} changements")


def journaliser(conn, old: dict[str, dict], new: dict[str, dict], champs, *, presence: bool, commit: bool = True) -> int:
    """Écrit dans `changement` les écarts entre deux états {n° de structure: ligne} et renvoie leur nombre.
    `presence` : journaliser aussi les ajouts (`nouveau` = nom) et les retraits (`ancien` = nom).
    `commit=False` : l'appelant valide le journal dans la même transaction que le remplacement des données
    (un import refusé ne laisse alors aucun faux événement — audit v0.5.5 n° 3).
    Premier run (ancien état vide) : rien à comparer."""
    if not old:
        return 0
    t = db.now()
    out = []
    if presence:
        out += [(t, n, "ajout", None, None, new[n].get("nom")) for n in sorted(new.keys() - old.keys())]
        out += [(t, n, "retrait", None, old[n].get("nom"), None) for n in sorted(old.keys() - new.keys())]
    for n in sorted(new.keys() & old.keys()):
        for champ in champs:
            a, b = old[n].get(champ), new[n].get(champ)
            if a != b:
                out.append((t, n, "modif", champ, None if a is None else str(a), None if b is None else str(b)))
    sql = "INSERT INTO changement (detected_at, num_dossr, kind, champ, ancien, nouveau) VALUES (?, ?, ?, ?, ?, ?)"
    if commit:
        with conn:
            conn.executemany(sql, out)
    else:
        conn.executemany(sql, out)
    return len(out)


def report(conn) -> str:
    q = lambda sql: conn.execute(sql).fetchall()
    one = lambda sql: conn.execute(sql).fetchone()[0]
    L = ["", "=== Rapport de jointure ==="]
    for r in q("SELECT source, status, rows, finished_at FROM source_run WHERE id IN "
               "(SELECT MAX(id) FROM source_run GROUP BY source) ORDER BY source"):
        L.append(f"  {r['source']:<10} {r['status']:<7} {r['rows'] or 0:>6} lignes  ({r['finished_at']})")
    L.append(f"  structure  : {one('SELECT COUNT(*) FROM structure')} "
             f"(WFS ∩ APEX {one('SELECT COUNT(*) FROM structure WHERE in_wfs AND in_apex')}, "
             f"WFS seul {one('SELECT COUNT(*) FROM structure WHERE in_wfs AND NOT in_apex')}, "
             f"APEX seul {one('SELECT COUNT(*) FROM structure WHERE in_apex AND NOT in_wfs')})")
    L.append("  WFS seul, par famille et responsable (cod_type_r) :")
    for r in q("SELECT s.famille, w.cod_respn, COUNT(*) n FROM structure s JOIN wfs_structure w USING (num_dossr) "
               "WHERE NOT s.in_apex GROUP BY 1, 2 ORDER BY n DESC LIMIT 12"):
        L.append(f"    {r['famille'] or '?':<9} respn={r['cod_respn']}  {r['n']}")
    L.append("  Par famille (inventaire public APEX) :")
    for r in q("SELECT famille, COUNT(*) n FROM structure WHERE in_apex GROUP BY 1 ORDER BY n DESC"):
        L.append(f"    {r['famille'] or '?':<9} {r['n']}")
    hl, hl_ok = one("SELECT COUNT(DISTINCT num_dossr) FROM hauteur_libre"), one(
        "SELECT COUNT(DISTINCT h.num_dossr) FROM hauteur_libre h JOIN structure s USING (num_dossr)")
    L.append(f"  hauteurs libres : {hl_ok}/{hl} n° joints à une structure")
    gp = one("SELECT COUNT(*) FROM gps_point")
    L.append(f"  GPS.csv : {one('SELECT COUNT(*) FROM structure WHERE limite_charge IS NOT NULL')}/{gp} "
             "points joints par coordonnées")
    L.append(f"  changements journalisés (total) : {one('SELECT COUNT(*) FROM changement')}")
    return "\n".join(L)
