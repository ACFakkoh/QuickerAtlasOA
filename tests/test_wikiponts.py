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



def test_choisir_photo_nom_complet_et_mot_pont():
    noms = ["Cochin Bridge", "Cochin Bridge (Saskatchewan)"]
    res = [{"title": "File:BURN! - Birthday Day Trip to Cochin SK.jpg", "dist": 10},
           {"title": "File:Cochin Bridge from the east.jpg", "dist": 300},
           {"title": "File:Cochin Bridge.pdf", "dist": 1}]
    assert wp.choisir_photo(res, noms) == "Cochin Bridge from the east.jpg"          # nom + « bridge », image
    assert wp.choisir_photo([{"title": "File:Albert Edward Bridge.jpg"}], ["Edward's Way Bridge"]) is None


def test_resultats_recherche_ecarte_les_homonymes_lointains():
    d = {"query": {"pages": [
        {"index": 2, "title": "File:St. Louis Bridge, Saskatchewan.jpg", "coordinates": [{"lat": 52.93, "lon": -105.81}]},
        {"index": 1, "title": "File:Eads Bridge, St. Louis.jpg", "coordinates": [{"lat": 38.63, "lon": -90.18}]},
        {"index": 3, "title": "File:St. Louis Bridge sans position.jpg"}]}}
    assert [r["title"] for r in wp.resultats_recherche(d, 52.925, -105.808)] == ["File:St. Louis Bridge, Saskatchewan.jpg"]


# --- v0.6.5 : infobox et introduction ------------------------------------------------------------------
INFOBOX_EN = """<table class="infobox"><tbody>
<tr><th colspan="2">Pierre Laporte Bridge</th></tr>
<tr><th class="infobox-label">Carries</th><td>6 lanes of <a href="/wiki/A-73">A-73</a><sup class="reference">[1]</sup></td></tr>
<tr><th>Total&nbsp;length</th><td>1,041&nbsp;m (3,415&nbsp;ft)</td></tr>
<tr><th>Longest span</th><td>667.5 m (2,190 ft)</td></tr>
<tr><th>Width</th><td>29 feet (8.8 m)</td></tr>
<tr><th>Clearance below</th><td>55 m (180 ft) at mid-span</td></tr>
<tr><th>No. of spans</th><td>3</td></tr>
<tr><th>Construction start</th><td>1966</td></tr>
<tr><th>Construction end</th><td>1970</td></tr>
<tr><th>Opened</th><td>November 6, 1970<span style="display:none"> (<span class="bday">1970-11-06</span>)</span>; 55 years ago</td></tr>
<tr><th>Material</th><td>Steel, concrete</td></tr>
<tr><th>Design</th><td>Suspension bridge</td></tr>
<tr><th>Daily traffic</th><td>120,000</td></tr>
</tbody></table>"""
INFOBOX_FR = """<div class="infobox_v3"><table><tbody>
<tr><th>Fonction</th><td>Pont routier</td></tr>
<tr><th>Longueur</th><td>1&nbsp;041&nbsp;m</td></tr>
<tr><th>Construction</th><td>1966-1970</td></tr>
<tr><th>Architecte(s)</th><td>Montreal Engineering</td></tr>
</tbody></table></div>"""


def test_infobox_libelles_et_textes_nettoyes():
    ib = wp.infobox(INFOBOX_EN)
    assert ib["total length"] == "1,041 m (3,415 ft)"                      # espace insécable normalisée
    assert ib["carries"] == "6 lanes of A-73"                              # renvoi [1] retiré
    assert ib["opened"] == "November 6, 1970"                              # date cachée et « 55 years ago » retirées
    assert wp.infobox("<p>sans infobox</p>") == {}


def test_longueur_annee_entier():
    assert wp.longueur_m("1,041 m (3,415 ft)") == 1041.0
    assert wp.longueur_m("29 feet (8.8 m)") == 8.8                         # unité métrique préférée
    assert wp.longueur_m("100 ft") == 30.5
    assert wp.longueur_m("2.3 km") == 2300.0
    assert wp.longueur_m("1 234,5 m", "fr") == 1234.5
    assert wp.longueur_m("12 miles") == 19312.1
    assert wp.longueur_m("aucune") is None
    assert wp.annee("(original) October 10, 1907; (replica) 2018") == 1907
    assert wp.entier("2, one each on either side") == 2 and wp.entier("1.5") is None


def test_faits_infobox_francais_prefere_nombres_anglais():
    f = wp.faits_infobox(wp.infobox(INFOBOX_EN), wp.infobox(INFOBOX_FR))
    assert (f["long"], f["portee"], f["larg"], f["degag"], f["travees"]) == (1041.0, 667.5, 8.8, 55.0, 3)
    assert (f["debut"], f["fin"], f["ouvert"]) == (1966, 1970, 1970)
    assert f["porte"] == "Pont routier" and f["archi"] == "Montreal Engineering"   # français d'abord
    assert f["mat"] == "acier, béton"                                               # matériaux traduits
    assert f["conception"] == "Suspension bridge" and "conception" in f["en"]       # texte anglais signalé
    assert f["trafic"] == "120,000" and "trafic" not in f["en"]


def test_couper_a_la_phrase():
    t = "Première phrase. Deuxième phrase un peu plus longue. Troisième."
    assert wp.couper(t, 40) == "Première phrase."
    assert wp.couper("Court.", 40) == "Court."
    assert wp.couper(None, 40) is None


def test_court_au_mot():
    assert wp.court("abc def ghi", 7) == "abc…"
    assert wp.court("abc", 7) == "abc"
