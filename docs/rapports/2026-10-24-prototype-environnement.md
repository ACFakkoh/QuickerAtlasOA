# Prototype Zones sensibles : milieux humides, aires protégées, faune et flore autour d'un ouvrage (2026-10-24)

**Verdict** : l'idée tient. Une fenêtre « Zones sensibles », sur le modèle de « Profil LiDAR » et « Cours d'eau », répond à la question « qu'est-ce qui est répertorié autour de ce pont ? » avec une carte et un tableau (présent ou absent, distance, nom, superficie, statut légal, source, licence, date). Sept thèmes sur huit marchent en direct depuis le navigateur. Un seul (habitats fauniques du MRNF) doit être précalculé.

Fichiers :
- `prototypes/environnement/prototype-environnement.html` : la page (serveur local : `…/prototypes/environnement/prototype-environnement.html`). Un cas s'ouvre directement par l'adresse : `#n=14945` (et `&r=2000` pour le rayon).
- `prototypes/environnement/build_cache.py` : précalcul des habitats fauniques pour les huit ouvrages d'exemple, et des fiches de licence et de date de Données Québec.
- `prototypes/environnement/cache/environnement-cache.js` (74 Ko, produit par le script).
- `prototypes/environnement/apercu.png` : capture de la fenêtre (ouvrage 14945).

Sigles : **MELCCFP** = ministère de l'Environnement, de la Lutte contre les changements climatiques, de la Faune et des Parcs ; **MRNF** = ministère des Ressources naturelles et des Forêts ; **CDPNQ** = Centre de données sur le patrimoine naturel du Québec ; **CIC** = Canards Illimités Canada ; **HAFA** = habitats fauniques (couches du MRNF) ; **HEMV** = habitat d'une espèce faunique menacée ou vulnérable ; **BDZI** = base de données des zones à risque d'inondation ; **AMCE** = autres mesures de conservation efficaces ; **CORS** = autorisation, par le serveur, des requêtes depuis une page web.

## Sources testées (2026-10-24)

Test CORS : requête avec l'en-tête `Origin: http://127.0.0.1:8765`, comme le ferait un navigateur. Licence et date : fiches de Données Québec (API CKAN). Toutes les licences retenues sont **CC-BY 4.0**.

| Thème | Service et couche | CORS | Mise à jour | Résultat |
|---|---|---|---|---|
| P · Aires protégées | MELCCFP `geo.environnement.gouv.qc.ca/donnees/rest/services/Biodiversite/Aires_protegees/MapServer/23` (5 611 polygones) | oui (renvoie l'origine) | 2026-09-23 | **Marche.** Le champ `DESIG_GR` classe l'aire : parc, réserve écologique ou marine, refuge biologique, écosystème forestier exceptionnel, milieu naturel de conservation volontaire, habitat faunique, habitat floristique… |
| F · Habitats floristiques | `…/Habitats_floristiques/MapServer/0` (58 habitats) | oui | 2026-10-14 | **Marche.** Les 29 habitats non inscrits au registre ne sont que dans cette couche. |
| S · Espèces en situation précaire | `…/EMVS_publique/MapServer/1` (4 621 floristiques) et `/3` (6 726 fauniques), couches « non sensibles » | oui | 2026-09-30 | **Marche.** Nom, statut (menacée, vulnérable, susceptible, candidate), dernière observation, précision (S < 150 m, M < 1,5 km). |
| X · Occurrences masquées | `…/EMVS_publique/MapServer/2` et `/4` | oui | 2026-09-30 | **Marche.** Forme généralisée, sans nom : le prototype n'affiche que la forme, jamais un nom. |
| M · Milieux humides (détaillés) | `…/MH_detailles/MapServer/0` (CIC et MELCCFP) | oui | 2025-05-07 | **Marche, au sud seulement** (basses-terres, Saguenay–Lac-Saint-Jean, secteurs habités). Classe codée (EP, ME, MS, PH, TB, BG, FN), superficie, pression. |
| M · Milieux humides (potentiels) | `…/MH_potentiels/MapServer/0` (2 446 410 polygones) | oui | 2026-05-29 | **Marche, partout.** C'est un modèle (confiance faible, moyenne ou élevée) : à valider sur le terrain. |
| Z · Zones inondables | MELCCFP `servicesgeo.enviroweb.gouv.qc.ca/…/Themes_publics/MapServer/22` (621 polygones) | oui | 2026-02-03 | **Marche** (déjà utilisé par « Cours d'eau »). Couverture partielle. |
| E · Espèces exotiques envahissantes | `…/Biodiversite/EEE/MapServer/0` (Sentinelle, 11 015 points) | oui | 2026-05-01 | **Marche.** Piège : la couche 77 de `Themes_publics` (mêmes données) répond 0 à toute requête spatiale, même sur un point qui s'y trouve. |
| H · Habitats fauniques | MRNF `servicesvecto3.mern.gouv.qc.ca/geoserver/Habitats_Fauniques_Pub/Habitat_legal/ows` (2 261 légaux) et `Habitat_informationnel` (410) | **non** : réponse 403 dès qu'un en-tête Origin est présent | 2026-06-22 | **Précalculé.** Le WFS en GeoJSON marche depuis Python (sans Origin), les tuiles WMS marchent en balise image, mais le chemin `/wfs` coupe la connexion : il faut `/ows`. |
| (refuges, EFE, MH d'intérêt) | MRNF `servicescarto.mrnf.gouv.qc.ca/pes/rest/services/Forets/STF_WMS/MapServer/3, 2, 5, 7` | oui | 2026-06-12 | **En partie.** Les attributs répondent, mais la géométrie n'est jamais renvoyée par `query`. Refuges désignés et EFE : on les prend dans le registre (couche P). Projets de refuge et milieux humides d'intérêt : tuiles seulement. |
| Forêt ouverte | `foretouverte.gouv.qc.ca/config/config.json` | sans objet | — | **Lue.** Le portail ne fait que renvoyer vers les services ci-dessus (MRNF GeoServer, MRNF STF, MELCCFP Biodiversité, Canards Illimités). Il n'y a aucun service propre à appeler. |

Écartées :
- **Territoires fauniques structurés** (zecs, pourvoiries) : licence CC-BY-NC-ND, sans œuvre dérivée ni usage commercial.
- **Frayères et rivières à saumon** : aucun jeu ouvert trouvé sur Données Québec. La seule piste est l'habitat du poisson de la couche HAFA, mais seules 21 baies sont publiées (avec les espèces, dont le saumon atlantique) ; 595 autres habitats sont « sans publication » (polygone sans espèce ni superficie).
- **Habitats essentiels fédéraux** (espèces en péril) et **atlas des territoires d'intérêt des basses-terres du Saint-Laurent** (couches 134 à 140 de `Themes_publics`) : non testés en profondeur.
- Service de Canards Illimités (`maps.ducks.ca`) : répond avec CORS, mais les mêmes données sont déjà dans `MH_detailles`.

Pièges notés :
- Le GeoServer du MRNF coupe la connexion (`Recv failure: Connection was reset`) sur le chemin `/wfs` et pour les clients qui n'ont pas l'air d'un navigateur, comme les autres serveurs du MRNF.
- `f=geojson` n'est pas utilisé : on lit l'Esri JSON (`f=json`) et on garde les anneaux tels quels (règle pair-impair, comme Leaflet).
- Le Saint-Laurent donne des polygones très longs : zone inondable de 876 Ko et occurrences fauniques de 1,6 Mo à 5 m de tolérance. À 20 m, 577 Ko et 650 Ko.

## Ce que le prototype montre

Pour chaque ouvrage : mini-carte Leaflet (rayon de 500 m, 1 km ou 2 km au choix, sans nouvelle requête), légende cochable, pastilles de comptage, tableau de huit lignes (sept thèmes et les occurrences masquées), puis bandeaux d'avertissement. Un thème dont le service n'a pas répondu porte « ? non vérifié », jamais « absent » (essayé en coupant volontairement deux services).

Les six cas, mesurés à 1 km (sauf Orford à 2 km) :

| N° | Ouvrage | Ce qu'on y voit |
|---|---|---|
| 14945 | Route 148, Pontiac (baie Breckenridge, Outaouais) | **Cas riche.** 8 aires protégées (milieux naturels de conservation volontaire du ruisseau Breckenridge, dès 30 m), 5 habitats fauniques (rainette faux-grillon de l'Ouest à 13 m, aire de concentration d'oiseaux aquatiques à 255 m, habitat du rat musqué à 343 m), 12 occurrences d'espèces précaires, 38 milieux humides, 2 zones inondables. |
| 12985 | Accès Mont-Orford, Orford | **Dans un parc national** (5 944 ha, le polygone contient le ponceau). 16 occurrences d'espèces précaires (salamandre pourpre, grenouille des marais…), 135 milieux humides à 2 km. Le ravage de cerfs est à 2,2 km : absent du cercle, ce que la fenêtre montre honnêtement. |
| 11726E | Route 175, Lac-Ministuk (Laurentides) | **Héronnière** du lac des Élets à 380 m (grand héron, bihoreau gris, grande aigrette), réserve écologique Victor-A.-Huard à 970 m, une occurrence historique de hibou des marais (1985), 12 milieux humides potentiels. |
| 03575 | Pont couvert de La Macaza | **Aire de confinement du cerf de Virginie** : 15 649 ha selon le HAFA, qui contient le pont (le registre n'en retient que 4 076 ha). 37 milieux humides, dont 26 marécages cartographiés en détail à 325 m. Aucune espèce précaire. |
| 18136 | Ponceau de la route 198, Saint-Maxime-du-Mont-Louis (Gaspésie) | **Forêt publique.** Refuge biologique 11256R166 à 140 m (322 ha). Presque rien d'autre : une occurrence de caribou des bois (polygone très étendu) et une plante. Aucun habitat faunique. |
| 14464E | Route 132, embouchure de la rivière Bonaventure | **Estuaire.** Habitat du poisson (baie de Bonaventure : anguille d'Amérique, éperlan, omble anadrome, poulamon, saumon atlantique) contenant le pont, réserve marine à 20 m, habitat floristique légal du Barachois-de-Bonaventure à 75 m, 5 occurrences précaires, 2 zones inondables. |

À essayer aussi (boutons sous les cartes) :
- **15382**, route 153, Yamachiche : 43 observations d'espèces exotiques envahissantes à 1 km (surtout la renouée du Japon), zone inondable du Saint-Laurent, aucune espèce précaire.
- **14240JH**, rue Bleury, centre-ville de Montréal : aucune aire protégée ni milieu humide, mais 7 occurrences fauniques dans le fleuve à 310 m et plus (faucon pèlerin, tortue géographique, martinet ramoneur) et 2 espèces exotiques. Même « sans grand-chose », le centre-ville n'est pas vide.

Mesure en direct : 10 requêtes, de **24 Ko** (forêt) à **1,1 Mo** (rives du Saint-Laurent), en 0,3 à 1 s.

Daltonisme : palette Okabe-Ito ; chaque thème a une **lettre** (P, H, F, S, M, Z, E, X), une couleur **et** un motif (P hachures /, H quadrillage, F traits verticaux, S points, M traits horizontaux, Z hachures \, E triangle noir). Bordure pointillée pour les statuts plus faibles (habitat informationnel, milieu humide potentiel, zone de faible courant, précision de 1,5 km). Rien ne repose sur le vert contre le rouge.

## Précautions sur les espèces sensibles

- Le CDPNQ masque lui-même les espèces sensibles à la diffusion. On n'affiche les noms que pour les couches « non sensibles ».
- Pour les couches masquées, on ne dessine que la forme généralisée publiée, sans nom. La ligne X du tableau le dit.
- Les occurrences à précision « M » (moins de 1,5 km) sont dessinées en pointillé sans motif : c'est une zone d'incertitude, pas une position.
- Bandeau rappelant que l'absence d'occurrence ne prouve pas l'absence d'espèce.
- Les observations d'espèces exotiques sont des déclarations de citoyens (Sentinelle), non vérifiées : le tableau le dit.

## Limites

- **Habitats fauniques précalculés pour huit ouvrages seulement.** Ailleurs, la fenêtre se rabat sur les habitats fauniques inscrits au registre des aires protégées (sans espèces) et l'écrit dans un bandeau.
- **Géométries simplifiées** (5 à 20 m) : les distances sont à ± 20 m. Ne pas s'en servir pour délimiter un chantier.
- **Statuts légaux résumés en une phrase** à partir des descriptions des services (Loi sur les espèces menacées ou vulnérables, régime des milieux humides, politique des plaines inondables). Un juriste du ministère devrait relire ces phrases avant publication.
- **Le milieu humide « potentiel » est un modèle**, pas un statut ; la cartographie détaillée n'existe qu'au sud.
- **Ce n'est pas un avis** : la fenêtre ne remplace ni une demande de renseignements au CDPNQ ni une autorisation du MELCCFP.
- **Pas vérifié** : textes juridiques non relus ; les habitats essentiels fédéraux ; une longue durée d'utilisation (les services répondaient en 0,3 à 1 s ce jour-là) ; les tuiles WMS des habitats fauniques avec en-tête Origin (non utilisées).
- Capture à 375 px : vérifiée dans le volet du navigateur (pas de défilement horizontal de la page ; le tableau défile dans son cadre). La capture `apercu.png` est à 1600 px.

## Pour l'intégrer (sans l'intégrer ici)

| Étape | Contenu | Effort |
|---|---|---|
| 1 | `js/environnement.js` avec `window.QA_MOD.environnement.render(o, body, ctx)` : reprendre `analyse` et `render` de la page, la carte et le tableau ; styles injectés par le module, motifs SVG dans le module (pas dans la page) | 2 à 3 j |
| 2 | Bouton « Zones sensibles » dans la fiche, pour tous les ouvrages (les ponceaux en premier) | 0,5 j |
| 3 | **Habitats fauniques** : au choix, (a) étape de l'ETL (`python -m etl couches`) qui précalcule, pour chaque ouvrage, la liste des habitats dans 2 km et la range dans `data/couche-habitats.js` (le serveur n'accepte pas Origin, mais l'ETL n'en envoie pas) ; ou (b) rester sur la version du registre, en direct et sans espèces | 1 j |
| 4 | Vérifier la présence de chaque couche avant l'ouverture (index des couches) et prévoir un bouton « Réessayer » par thème | 0,5 j |
| 5 | Relecture juridique des phrases de statut, et décision sur l'affichage des occurrences masquées (forme seulement, ou rien) | à cadrer |

Idées, sans rien intégrer :
- Un pictogramme dans la liste des résultats (« zone sensible à moins de 100 m ») calculé par l'ETL pour les thèmes lourds à interroger : aires protégées, habitats floristiques, habitats fauniques. Demande un jeu de polygones simplifiés ; à peser avant.
- Un lien « Demande au CDPNQ » dans la fenêtre.
- Ajouter les tuiles des projets de refuge biologique et des milieux humides d'intérêt (MRNF), seule voie pour les voir.
