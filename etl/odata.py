"""Service OData public du MTMD (ws.diffusion.transports.gouv.qc.ca/odata).

C'est la source des pages « Inventaire des structures », « Hauteurs libres » et
« Limitations de poids » : une requête par jeu, sans pagination.
- Structures_StructuresTabBord : 67 champs par structure de l'inventaire public
  (dimensions complètes, biais, DJMA, % camion, classes de route, inspections…).
- LimitesDeCharge : panneaux de limitation de poids (tonnages par classe de véhicule).
- HauteurLibreDetail : hauteurs libres mesurées en 5 points par direction.
Ces données remplacent le crawl des ~9 900 fiches HTML (voir apex_fiche.py, conservé en option).
"""
import json
import re

from . import net

BASE = "https://ws.diffusion.transports.gouv.qc.ca/odata/"
JSON = {"Accept": "application/json"}


def _get(s, entity: str) -> tuple[list[dict], bytes]:
    r = net.get(s, BASE + entity, timeout=300, headers=JSON)
    data = r.json()
    if data.get("@odata.nextLink"):
        raise RuntimeError(f"{entity} : pagination OData inattendue")
    return data["value"], r.content


def _num(v) -> float | None:
    """« '   7 170,0' » → 7170.0 ; « '' », « 0,0 » → None (0 = non renseigné dans ce service)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) or None
    v = re.sub(r"[\s  ]", "", v).replace(",", ".")
    return (float(v) or None) if v else None


def _txt(v) -> str | None:
    v = " ".join((v or "").split())
    return v or None


def famille(code: int | None) -> str | None:
    if code is None:
        return None
    return "ponceau" if code <= 29 else "pont" if code <= 89 else {94: "tunnel", 97: "mur", 98: "station"}.get(code)


# --- Structures_StructuresTabBord ----------------------------------------------------
class TabBord:
    SOURCE = "odata_tabbord"
    TABLE = "structure_detail"
    TRACKED = ("inspection_generale",)      # journalisés à chaque run (P5 : « nouvelle inspection générale »)

    @staticmethod
    def parse(rows: list[dict], types_voie: dict[int, str]) -> list[dict]:
        out = []
        for x in rows:
            f = famille(x["COD_TYPE_STRCT"])
            # Les champs propres aux ponceaux / murs / tunnels traînent parfois des valeurs
            # pour d'autres familles : on ne les lit que pour la bonne famille.
            pick = lambda key, fam: _num(x[key]) if f == fam else None
            out.append({
                "num_dossr": x["NUM_DOSSR"].strip(),
                "ide_strct": x["Id"],
                "region_admin": _txt(x["NOM_REGN_ADMNS"]),
                "mrc": _txt(x["NOM_MRC_CU_TE"]),
                "cep": _txt(x["NOM_CEP"]),
                "classe_route": _txt(x["DES_CLASSE_RTE"]),
                "route_type_voie": types_voie.get(x["RTE_COD_TYPE_VOIE"]),
                "nb_voies": x["RTE_NBR_VOIE_EFFCF"] or None,
                # DJMA ≤ 1 = valeur bidon (la fiche HTML affiche « ND » et le % camion aussi)
                "djma": x["VAL_DJMA_ESTM"] if (x["VAL_DJMA_ESTM"] or 0) > 1 else None,
                "pct_camion": x["VAL_POURC_CAMN_DJMA"] if (x["VAL_DJMA_ESTM"] or 0) > 1 else None,
                "obstacle_type_voie": types_voie.get(x["OBS_COD_TYPE_DE_VOIE"]),
                "obstacle_classe_route": _txt(x["DES_CLASSE_RTE_OBS"]),
                "longueur_totale_m": _num(x["VAL_LONGR_TOTAL"]) if f in ("pont", "ponceau") else None,
                "longueur_tablier_m": pick("VAL_LONGR_TABLR", "pont"),
                "largeur_carrossable_m": _num(x["VAL_LARGR_CHAS_EFFCF"]) if f in ("pont", "ponceau", "tunnel") else None,
                "largeur_hors_tout_m": pick("VAL_LARGR_HORS_TOUT", "pont"),
                "superficie_tablier_m2": pick("VAL_SUPRF_TABLR", "pont"),
                "biais_type": x["COD_TYPE_BIAIS"],
                "biais_angle_deg": x["VAL_ANGLE_BIAIS"] or None,
                "ponceau_ouverture_m": pick("VAL_OUVRT_TOTAL_PONC", "ponceau"),
                "ponceau_superficie_m2": pick("VAL_SUPRF_TOTAL_PONC", "ponceau"),
                "remblai_epaisseur_m": round(v / 1000, 3) if (v := pick("VAL_EPASR_REMBL", "ponceau")) else None,  # mm
                "mur_longueur_m": pick("VAL_LONGR_TOTAL_MUR", "mur"),
                "mur_hauteur_moy_m": pick("VAL_HAUTR_MOYEN_MUR", "mur"),
                "mur_superficie_m2": pick("VAL_SUPRF_MUR", "mur"),
                "tunnel_longueur_m": pick("VAL_LONGR_TOTAL_TUNNL", "tunnel"),
                "tunnel_largeur_m": pick("VAL_LARGR_TOTAL_TUNNL", "tunnel"),
                "tunnel_superficie_m2": pick("VAL_SUPRF_TOTAL_TUNNL", "tunnel"),
                "affichage_code": x["COD_TYPE_AFFCH_PLACE"],
                "inspection_generale": x["DAT_DERNR_INSPC_GENRL"],
                "inspection_sommaire": x["DAT_DERNR_INSPC_SOMMR"],
                "frequence_inspection_ans": x["VAL_FREQN_INSPC_EFFCF"],
                "prochaine_inspection": x["VAL_ANNEE_PROCH_INSPC"],
                "commentaire": _txt(x["VAL_COMMT_STRCT"]),
                "travaux_description": _txt(x["VAL_DESCR_TRAVX_TEMP"]),
                "raw_json": json.dumps(x, ensure_ascii=False),
            })
        return out

    @classmethod
    def collect(cls, s) -> list[dict]:
        voies = {v["Id"]: v["DES_COMPL"] for v in _get(s, "Structures_TypeVoie")[0]}
        rows, raw = _get(s, "Structures_StructuresTabBord")
        net.save_raw("odata_tabbord.json", raw)
        return cls.parse(rows, voies)


# --- LimitesDeCharge -------------------------------------------------------------------
def panneau(text: str | None) -> dict:
    """« 28t* 48t**58t*** » → tonnages par classe (notes explicatives du répertoire) :
    xt* = tous véhicules (P-200-3) ; xxt* xxt** = véhicule / ensemble (P-200-1) ;
    xxt* xxt** xxt*** = véhicule / ensemble de 2 unités / de plus de 2 unités (P-200-2)."""
    t = {len(stars): float(n.replace(",", ".")) for n, stars in re.findall(r"(\d+(?:[.,]\d+)?)\s*t\s*(\*+)", text or "")}
    if len(t) == 1:
        v = t[1] if 1 in t else next(iter(t.values()))
        return {"poids_vehicule_t": v, "poids_ensemble2_t": v, "poids_ensemble3_t": v}
    return {"poids_vehicule_t": t.get(1), "poids_ensemble2_t": t.get(2), "poids_ensemble3_t": t.get(3) or t.get(2)}


class Limites:
    SOURCE = "odata_limites"
    TABLE = "limite_poids"

    @staticmethod
    def parse(rows: list[dict]) -> list[dict]:
        out = {}
        for x in rows:
            num = x["NoDossier"].strip()
            out[num] = {"num_dossr": num, "panneau": _txt(x["Panneau"]), **panneau(x["Panneau"]),
                        "diffusion_511": int(x["Diffusion511"] == "O"), "date_maj": _txt(x["DateMAJ"])}
        return list(out.values())

    @classmethod
    def collect(cls, s) -> list[dict]:
        rows, raw = _get(s, "LimitesDeCharge")
        net.save_raw("odata_limites.json", raw)
        return cls.parse(rows)


# --- HauteurLibreDetail ----------------------------------------------------------------
class HauteursDetail:
    SOURCE = "odata_hl_detail"
    TABLE = "hauteur_libre_detail"
    POINTS = ("Gauche", "CentreGauche", "Centre", "CentreDroit", "Droite")

    @classmethod
    def parse(cls, rows: list[dict]) -> list[dict]:
        out = []
        for x in rows:
            mesures = {p: x[p] for p in cls.POINTS if x[p] is not None and x[p] > 0}
            out.append({"id": x["Id"], "num_dossr": x["Dossier"].strip(), "point": _txt(x["Point"]),
                        "direction": _txt(x["Direction"]),
                        "h_min_m": float(min(mesures.values())) if mesures else None,
                        "mesures_json": json.dumps({k: float(v) for k, v in mesures.items()}),
                        "remarques": _txt(x["Remarques"]), "date_mesure": _txt(x["Date"])})
        return out

    @classmethod
    def collect(cls, s) -> list[dict]:
        rows, raw = _get(s, "HauteurLibreDetail")
        net.save_raw("odata_hl_detail.json", raw)
        return cls.parse(rows)
