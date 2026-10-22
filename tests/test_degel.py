"""Tests des zones de dégel (v0.6.5) : lecture du GeoJSON du MTMD, simplification des contours."""
from etl import degel


def _carre(lon0, lat0, d, n=40):
    """Carré de côté `d` degrés, avec `n` points par côté (alignés : la simplification doit les retirer)."""
    pts = []
    for (x0, y0), (x1, y1) in [((0, 0), (1, 0)), ((1, 0), (1, 1)), ((1, 1), (0, 1)), ((0, 1), (0, 0))]:
        pts += [[lon0 + d * (x0 + (x1 - x0) * i / n), lat0 + d * (y0 + (y1 - y0) * i / n)] for i in range(n)]
    return pts + [pts[0]]


def test_simplifier_anneau_garde_les_coins_et_quantifie():
    a = degel.simplifier_anneau(_carre(-72.0, 46.0, 1.0))
    assert len(a) == 4                                                       # points alignés retirés
    assert sorted(a) == sorted([[460000, -720000], [460000, -710000], [470000, -710000], [470000, -720000]])


def test_simplifier_anneau_ecarte_les_ilots():
    assert degel.simplifier_anneau(_carre(-72.0, 46.0, 0.001)) == []        # ≈ 0,01 km² < AIRE_MIN_KM2


def test_parse_zones_dates_et_ordre():
    gj = {"features": [
        {"properties": {"zone": "Zone 2", "num_zone": 2.0, "nom_partie_zone": "Partie médiane du Québec",
                        "dat_debut_zone": "2026-04-13  00h01", "dat_fin_zone": "2026-05-22  23h59", "dat_maj": "2022-03-04"},
         "geometry": {"type": "Polygon", "coordinates": [_carre(-75.0, 47.0, 2.0)]}},
        {"properties": {"zone": "Zone 1", "num_zone": 1.0, "dat_debut_zone": "2026-03-16  00h01", "dat_fin_zone": "2026-05-15  23h59"},
         "geometry": {"type": "MultiPolygon", "coordinates": [[_carre(-72.0, 45.0, 1.0)], [_carre(-61.9, 47.3, 0.3)]]}},
        {"properties": {"zone": "?", "num_zone": None}, "geometry": None}]}
    z = degel.parse(gj)
    assert [x["num"] for x in z] == [1, 2]
    assert (z[0]["debut"], z[0]["fin"]) == ("2026-03-16", "2026-05-15")
    assert len(z[0]["anneaux"]) == 2                                          # Îles-de-la-Madeleine gardées
    assert z[1]["partie"] == "Partie médiane du Québec" and z[1]["maj"] == "2022-03-04"


def test_aire_km2_ordre_de_grandeur():
    # 1° × 1° à 46° N ≈ 111,3 km × 77,3 km ≈ 8 600 km²
    a = degel.aire_km2([(46.0, -72.0), (46.0, -71.0), (47.0, -71.0), (47.0, -72.0)])
    assert 8000 < a < 9200
