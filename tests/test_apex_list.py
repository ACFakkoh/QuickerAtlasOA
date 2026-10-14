"""Tests du parseur de la liste APEX et de la reconstruction du POST de recherche."""
import json
from pathlib import Path

from etl import apex_list

FIX = Path(__file__).parent / "fixtures"


def _rows():
    page = (FIX / "apex_liste_extrait.html").read_text(encoding="utf-8")
    return {r["num_dossr"]: r for r in apex_list.parse_rows(page)}


def test_ligne_connue():
    r = _rows()["00009"]
    assert r["ide_strct"] == 211038
    assert (r["type_code"], r["type_libelle"]) == (41, "Pont à poutres en béton armé")
    assert r["reseau"] == "Supérieur"
    assert r["direction_territoriale"] == "Abitibi-Témiscamingue"       # <wbr> retiré
    assert (r["icg"], r["ias"], r["annee_travaux"], r["rapport_dispo"]) == ("1", "vert", 2024, 1)
    assert "P53_IDE_STRCT_0001:211038" in r["fiche_url"] and "&cs=" in r["fiche_url"]


def test_cas_limites():
    rows = _rows()
    assert rows["00002"]["ias"] == "jaune" and rows["00002"]["annee_travaux"] is None
    assert rows["00024A"]["num_dossr"] == "00024A"
    assert rows["01538AK"]["ias"] == "SO"                                # « S. O. » en texte


def test_post_de_recherche():
    page = (FIX / "apex_accueil.html").read_text(encoding="utf-8")
    data = apex_list._form_payload(page, ["C"])
    assert data["p_request"] == "RECHR" and data["p_flow_step_id"] == "56"
    p_json = json.loads(data["p_json"])
    assert p_json["salt"] == data["p_page_submission_id"]
    items = {i["n"]: i for i in p_json["pageItems"]["itemsToSubmit"]}
    assert items["P56_LIMTN_CHARGE_0004"]["v"] == ["C"]
    assert items["P56_VAL_IAS_0009"]["ck"]                               # checksum de l'item protégé
    assert "/" in p_json["pageItems"]["protected"]                       # entité &#x2F; décodée


# --- Validation des réponses (audit v0.5.5 n° 1) -----------------------------------------------
def _page(a, b, total=9880):
    return (f'<table><tr><td>Total</td><td class="t3dataHighlight">{total}</td></tr></table>'
            f'<td class="pagination"><span class="fielddata">{a} - {b}</span></td>')


def test_page_valide_et_total():
    rows = [{}] * 500
    apex_list.verifier_page(_page(501, 1000), rows, 501)
    assert apex_list.total_annonce(_page(1, 500)) == 9880
    apex_list.verifier_total([{}] * 9880, 9880, [])


def test_page_de_connexion_apres_une_page_valide_est_refusee():
    import pytest
    login = "<html><body><form>Connexion — session expirée</form></body></html>"
    with pytest.raises(RuntimeError, match="session expirée"):
        apex_list.verifier_page(login, apex_list.parse_rows(login), 501)


def test_plage_incoherente_ou_total_different_refuse():
    import pytest
    with pytest.raises(RuntimeError, match="incohérente"):
        apex_list.verifier_page(_page(1, 500), [{}] * 120, 1)
    with pytest.raises(RuntimeError, match="incomplet"):
        apex_list.verifier_total([{}] * 500, 9880, [])
    with pytest.raises(RuntimeError, match="introuvable"):
        apex_list.verifier_total([{}] * 500, None, [])
    apex_list.verifier_total([{}] * 12, None, ["H"])                  # recherche filtrée : pas de contrôle du total


def test_pages_reelles_si_disponibles():
    raw = Path(__file__).resolve().parent.parent / "data" / "raw" / "apex_list_19.html"
    if not raw.exists():
        return
    page = raw.read_text(encoding="utf-8")
    apex_list.verifier_page(page, apex_list.parse_rows(page), 9501)
