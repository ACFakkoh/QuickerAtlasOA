"""Tests du parseur de fiche HTML APEX (crawl optionnel)."""
import json
from pathlib import Path

import pytest

from etl import apex_fiche

FIXTURE = Path(__file__).parent / "fixtures" / "fiche_00760.html"


def test_fiche_complete():
    d = apex_fiche.parse(FIXTURE.read_text(encoding="utf-8"))
    assert (d["longueur_totale_m"], d["longueur_tablier_m"], d["largeur_carrossable_m"]) == (63.8, 57.7, 4.6)
    assert (d["superficie_tablier_m2"], d["djma"], d["pct_camion"], d["nb_voies"]) == (341.0, 1770, 14, 1)
    assert (d["classe_route"], d["mrc"], d["cep"]) == ("Collectrice", "Robert-Cliche", "Beauce-Nord")
    assert (d["derniere_inspection_ym"], d["prochaine_inspection"]) == ("2025-12", 2027)
    assert "limitation de poids" in d["limitations"] and "hauteurs libres" in d["limitations"]
    assert d["photo"] == 1
    assert "Dimension / Longueur totale" in json.loads(d["champs_json"])


def test_page_invalide():
    with pytest.raises(ValueError):
        apex_fiche.parse("<html><body>Session expirée</body></html>")
