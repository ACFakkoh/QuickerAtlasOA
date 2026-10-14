"""Tests des parseurs OData (fixtures : extraits réels du service ws.diffusion.transports.gouv.qc.ca)."""
import json
from pathlib import Path

from etl import odata

FIX = Path(__file__).parent / "fixtures"
VOIES = {1: "Route standard", 2: "Cours d'eau", 3: "Chemin de fer"}


def _load(name):
    return json.loads((FIX / f"{name}_extrait.json").read_text(encoding="utf-8"))["value"]


def test_tabbord_pont():
    rows = {r["num_dossr"]: r for r in odata.TabBord.parse(_load("odata_tabbord"), VOIES)}
    r = rows["00009"]
    assert r["ide_strct"] == 211038
    assert (r["longueur_totale_m"], r["longueur_tablier_m"]) == (61.4, 54.9)
    assert (r["largeur_hors_tout_m"], r["largeur_carrossable_m"], r["superficie_tablier_m2"]) == (11.1, 9.1, 609.0)
    assert (r["djma"], r["pct_camion"], r["classe_route"]) == (530, 26, "Nationale")
    assert r["obstacle_type_voie"] == "Cours d'eau"
    assert r["tunnel_longueur_m"] is None and r["mur_longueur_m"] is None     # champs d'une autre famille ignorés


def test_tabbord_ponceau_mur_tunnel():
    rows = {r["num_dossr"]: r for r in odata.TabBord.parse(_load("odata_tabbord"), VOIES)}
    p = rows["20336"]
    assert (p["ponceau_ouverture_m"], p["ponceau_superficie_m2"], p["remblai_epaisseur_m"]) == (4.5, 1769.0, 6.0)  # remblai mm → m
    assert p["djma"] is None and p["pct_camion"] is None                      # DJMA « 1 » = ND
    m = rows["15728A"]
    assert (m["mur_longueur_m"], m["mur_hauteur_moy_m"], m["mur_superficie_m2"]) == (7200.0, 4.1, 29783.0)
    assert m["longueur_totale_m"] is None
    t = rows["14240FA"]
    assert (t["tunnel_longueur_m"], t["tunnel_largeur_m"]) == (1968.9, 17.7)


def test_panneau():
    assert odata.panneau("28t* 44t**58t***") == {"poids_vehicule_t": 28, "poids_ensemble2_t": 44, "poids_ensemble3_t": 58}
    assert odata.panneau("5t* ") == {"poids_vehicule_t": 5, "poids_ensemble2_t": 5, "poids_ensemble3_t": 5}
    assert odata.panneau("18t* 24t**") == {"poids_vehicule_t": 18, "poids_ensemble2_t": 24, "poids_ensemble3_t": 24}
    assert odata.panneau("Charges légales") == {"poids_vehicule_t": None, "poids_ensemble2_t": None, "poids_ensemble3_t": None}
    rows = odata.Limites.parse(_load("odata_limites"))
    assert len(rows) == 4 and all(r["panneau"] for r in rows)


def test_hauteurs_detail():
    rows = odata.HauteursDetail.parse(_load("odata_hl_detail"))
    est = next(r for r in rows if r["num_dossr"] == "00734" and r["direction"] == "Est")
    assert est["h_min_m"] == 4.76 and json.loads(est["mesures_json"]) == {"Droite": 4.76}
    multi = rows[-1]
    assert multi["h_min_m"] == min(json.loads(multi["mesures_json"]).values())
