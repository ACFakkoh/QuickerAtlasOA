"""Tests des ponts remarquables (Wikipédia, Wikidata) : lecture de la liste, noms, appariement au MTMD, faits.

Les extraits HTML et Wikidata sont fabriqués à l'image des réponses réelles (structure de la page
« List of bridges in Canada » d'octobre 2026, entité Q761692 du pont Pierre-Laporte).
"""
from etl import wikiponts as wp

LISTE_HTML = """
<div class="mw-heading mw-heading2"><h2>Historical and architectural interest bridges</h2></div>
<table class="wikitable sortable"><tbody>
<tr><th></th><th></th><th>Name</th><th>Distinction</th><th>Length</th><th>Type</th><th>Carries Crosses</th>
<th>Opened</th><th>Location</th><th>Province</th><th>Ref.</th></tr>
<tr><td><a href="/wiki/File:Victoria.jpg">img</a></td><td>1</td><td><a href="/wiki/Victoria_Bridge_(Montreal)">Victoria Bridge</a></td>
<td>Longest bridge in the world when inaugurated<sup class="reference"><a href="#cite_note-x">[1]</a></sup></td><td>2,009 m</td>
<td>Tubular</td><td>GTR</td><td>1859</td><td>Montreal <span class="geo">45.4918; -73.5289</span></td>
<td><a href="/wiki/Quebec">Quebec</a></td><td><sup class="reference"><a href="#cite_note-S-1">[S 1]</a></sup></td></tr>
</tbody></table>
<div class="mw-heading mw-heading2"><h2>Alphabetical list</h2></div>
<div class="mw-heading mw-heading3"><h3>Ontario</h3></div>
<ul><li><a href="/wiki/Ottawa">Ottawa</a> – <a href="/wiki/Alexandra_Bridge">Alexandra Bridge</a></li>
<li><a href="/wiki/Missing_bridge" class="new">Missing bridge</a></li></ul>
<div class="mw-heading mw-heading3"><h3>Quebec</h3></div>
<ul><li><a href="/wiki/Pierre_Laporte_Bridge">Pierre Laporte Bridge</a></li>
<li><a href="/wiki/Victoria_Bridge_(Montreal)">Victoria Bridge</a> (doublon)</li></ul>
<ol class="references"><li id="cite_note-S-1"><a href="https://structurae.net/en/structures/victoria-bridge">Victoria</a></li></ol>
"""


def test_parse_liste_tableau_liste_alphabetique_et_structurae():
    e = {x["titre"]: x for x in wp.parse_liste(LISTE_HTML)}
    assert list(e) == ["Victoria Bridge (Montreal)", "Alexandra Bridge", "Pierre Laporte Bridge"]  # doublon et lien rouge écartés
    v = e["Victoria Bridge (Montreal)"]
    assert (v["prov"], v["section"], v["st"]) == ("Québec", "patrimoine", "victoria-bridge")
    assert (v["lat"], v["lon"]) == (45.4918, -73.5289)
    assert v["distinction"] == "Longest bridge in the world when inaugurated"            # renvoi [1] retiré
    assert e["Alexandra Bridge"]["prov"] == "Ontario"                                     # le lien du pont, pas celui de la ville


def test_mots_et_meme_nom():
    assert wp.mots("Pont d'aluminium d'Arvida") == {"aluminium", "arvida"}
    assert wp.mots("Pierre Laporte Bridge") == wp.mots("Pont Pierre-Laporte") == {"pierre", "laporte"}
    assert wp.mots("Pont Mercier (Matapédia)") == {"mercier"}
    assert wp.meme_nom(wp.mots("Pont d'Arvida"), wp.mots("Pont d'aluminium d'Arvida"))
    assert wp.meme_nom(wp.mots("Pont Champlain"), wp.mots("Pont Samuel-De Champlain"))   # inclusion : la distance départage
    assert not wp.meme_nom(wp.mots("Pont couvert"), wp.mots("Pont Champlain"))                        # aucun mot utile
    assert not wp.meme_nom(wp.mots("Pont Viau"), wp.mots("Pont Lachapelle"))


def test_apparier_nom_distance_jumeaux_et_nature():
    mtmd = [("03226", "Pont Honoré-Mercier", 45.41752, -73.65429), ("03228", "Pont Honoré-Mercier", 45.41771, -73.65471),
            ("99999", "Pont Honoré-Mercier", 46.5, -72.0),                       # même nom, 150 km plus loin
            ("09671", "Échangeur Arthur-Sauvé", 45.60, -73.85), ("02071", "Pont Arthur-Sauvé", 45.601, -73.851)]
    cands = [{"q": "Q1", "lat": 45.4175, "lon": -73.6545, "noms": ["pont Honoré-Mercier", "Honoré Mercier Bridge"]},
             {"q": "Q2", "lat": 45.6005, "lon": -73.8505, "noms": ["Pont Arthur-Sauvé"]},
             {"q": "Q3", "lat": 45.0, "lon": -73.0, "noms": ["Pont Inconnu"]}]
    r = wp.apparier(cands, mtmd)
    assert sorted(r["Q1"]) == ["03226", "03228"]                                  # ponts jumeaux, pas le lointain
    assert r["Q2"] == ["02071"]                                                    # l'échangeur n'est pas le pont
    assert "Q3" not in r


def test_faits_wikidata_unites_dates_et_structurae():
    m = "http://www.wikidata.org/entity/"
    e = {"labels": {"fr": {"value": "pont Pierre-Laporte"}},
         "sitelinks": {"frwiki": {"title": "Pont Pierre-Laporte"}, "enwiki": {"title": "Pierre Laporte Bridge"}},
         "claims": {
             "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q12280"}}}}, {"mainsnak": {"datavalue": {"value": {"id": "Q12570"}}}}],
             "P2043": [{"mainsnak": {"datavalue": {"value": {"amount": "+1.041", "unit": m + "Q828224"}}}}],
             "P2787": [{"rank": "deprecated", "mainsnak": {"datavalue": {"value": {"amount": "+1", "unit": m + "Q11573"}}}},
                       {"mainsnak": {"datavalue": {"value": {"amount": "+667.5", "unit": m + "Q11573"}}}}],
             "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+1966-00-00T00:00:00Z"}}}}],
             "P1619": [{"mainsnak": {"datavalue": {"value": {"time": "+1970-11-04T00:00:00Z"}}}}],
             "P454": [{"mainsnak": {"datavalue": {"value": "20003362"}}}],
             "P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 46.745, "longitude": -71.29}}}}]}}
    f = wp.faits_wikidata(e)
    assert f["type"] == ["Q12570"]                                                 # « pont » générique retiré
    assert (f["long"], f["portee"], f["an"], f["st"]) == (1041.0, 667.5, 1970, "20003362")
    assert (f["fr"], f["en"], f["nom"]) == ("Pont Pierre-Laporte", "Pierre Laporte Bridge", "pont Pierre-Laporte")
    assert (f["lat"], f["lon"]) == (46.745, -71.29)


def test_construire_lie_le_mtmd_et_garde_les_autres_en_etoiles():
    liste = [{"titre": "Pierre Laporte Bridge", "nom": "Pierre Laporte Bridge", "prov": "Québec", "section": "majeur",
              "distinction": None, "st": None, "lat": None, "lon": None},
             {"titre": "Alexandra Bridge", "nom": "Alexandra Bridge", "prov": "Ontario", "section": "liste",
              "distinction": None, "st": None, "lat": None, "lon": None},
             {"titre": "Ottawa", "nom": "Ottawa", "prov": "Ontario", "section": "liste",
              "distinction": None, "st": None, "lat": None, "lon": None}]
    art = {"Pierre Laporte Bridge": {"titre": "Pierre Laporte Bridge", "q": "Q761692", "lat": 46.745, "lon": -71.2908,
                                     "image": None, "resume": "Suspension bridge.", "fr": "Pont Pierre-Laporte"},
           "Alexandra Bridge": {"titre": "Alexandra Bridge", "q": "Q1", "lat": 45.43, "lon": -75.70, "image": "A.jpg",
                                "resume": "Truss bridge.", "fr": "Pont Alexandra"},
           "Ottawa": {"titre": "Ottawa", "q": "Q1930", "lat": 45.42, "lon": -75.69, "image": None, "resume": None, "fr": None}}
    ent = {"Q761692": {"labels": {"fr": {"value": "pont Pierre-Laporte"}}, "claims": {"P454": [{"mainsnak": {"datavalue": {"value": "20003362"}}}]},
                       "sitelinks": {"frwiki": {"title": "Pont Pierre-Laporte"}}},
           "Q1": {"labels": {"fr": {"value": "pont Alexandra"}}, "claims": {}, "sitelinks": {"frwiki": {"title": "Pont Alexandra"}}},
           "Q1930": {"labels": {"fr": {"value": "Ottawa"}}, "claims": {}, "sitelinks": {}}}
    art_fr = {"Pont Alexandra": {"titre": "Pont Alexandra", "image": None, "resume": "Pont en treillis."}}
    imgs = {"A.jpg": {"src": "https://upload.wikimedia.org/a.jpg", "page": "p", "auteur": "X", "licence": "CC BY-SA 4.0"}}
    mtmd = [("04296", "Pont Pierre-Laporte", 46.74554, -71.29068)]
    out = wp.construire(liste, art, art_fr, ent, {}, imgs, [], mtmd)
    assert out["mtmd"] == {"04296": {"fr": "Pont Pierre-Laporte", "en": "Pierre Laporte Bridge", "q": "Q761692", "st": "20003362"}}
    assert [p["nom"] for p in out["ponts"]] == ["Pont Alexandra"]                  # la ville est écartée, Pierre-Laporte lié
    a = out["ponts"][0]
    assert (a["resume"], a["resumeLang"], a["img"]["licence"]) == ("Pont en treillis.", "fr", "CC BY-SA 4.0")
