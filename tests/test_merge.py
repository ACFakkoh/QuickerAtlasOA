"""Tests des règles de consolidation."""
from etl import merge


def test_famille_par_code():
    assert [merge.famille(c) for c in (13, 21, 31, 45, 85, 94, 97, 98, None)] == [
        "ponceau", "ponceau", "pont", "pont", "pont", "tunnel", "mur", "station", None]


def test_region_depuis_dg():
    f = merge.region_depuis_dg
    assert f("Direction générale de l'Abitibi-Témiscamingue") == "Abitibi-Témiscamingue"
    assert f("Direction générale des Laurentides - Lanaudière") == "Laurentides - Lanaudière"
    assert f("Direction générale du Saguenay - Lac-Saint-Jean") == "Saguenay-Lac-Saint-Jean"
    assert f("Direction générale d'Eeyou Istchee Baie-James") == "Eeyou Istchee Baie-James"
    assert f("Direction générale de l'exploitation du réseau métropolitain") == "Métropole"
    assert f("Nouvelle Autoroute 30 S.E.N.C.") == "Montérégie"
    assert f(None) is None
