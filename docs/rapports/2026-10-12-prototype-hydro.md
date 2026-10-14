# Prototype Hydrographie : cours d'eau, stations et crues au pont (2026-10-12)

**Verdict** : l'idée tient, avec deux volets distincts.
1. Une **couche** « Cours d'eau » (tuiles WMS, rien à héberger) pour situer le cours d'eau d'un ouvrage.
2. Une **fenêtre « Cours d'eau au pont »**, comme le profil LiDAR : nom, ordre de Strahler, bassin, zone inondable officielle, station la plus proche, crues et étiages indicatifs. Elle se calcule à la demande dans le navigateur, en 4 à 9 requêtes, de 25 à 610 Ko et 0,1 à 0,4 s.

Fichiers :
- `prototypes/hydro/prototype-hydro.html` (s'ouvre via le serveur local, `…/prototypes/hydro/prototype-hydro.html`) ;
- `prototypes/hydro/build_cache.py` : précalcul de la liste des stations du CEHQ et d'instantanés de leur suivi temps réel ;
- `prototypes/hydro/cache/hydro-cache.js` (215 Ko, produit par le script).

Sigles : **GRHQ** = Géobase du réseau hydrographique du Québec ; **MRNF** = ministère des Ressources naturelles et des Forêts ; **MELCCFP** = ministère de l'Environnement, de la Lutte contre les changements climatiques, de la Faune et des Parcs ; **CEHQ** = Centre d'expertise hydrique du Québec (au MELCCFP) ; **ECCC** = Environnement et Changement climatique Canada ; **HYDAT** = base nationale de données hydrométriques d'ECCC ; **BDZI** = Base de données des zones inondables ; **WMS/WFS/REST** = services de cartes et de données en ligne ; **CORS** = autorisation, par le serveur, des requêtes depuis une page web ; **RNCan** = Ressources naturelles Canada.

## Sources testées

| # | Source | URL de base | Résultat |
|---|---|---|---|
| A | RNCan CanVec (WMS) : cours d'eau, plans d'eau, courbes de niveau, barrages | `https://maps.geogratis.gc.ca/wms/canvec_en` | **Marche.** CORS ouvert. 0,16 s et 3 à 7 Ko par tuile. Couches : `watercourse_50k`, `waterbody_50k`, `contour_elevation_50k`. Pas de Strahler. |
| A' | RNCan RHN/NHN (WMS) | `https://maps.geogratis.gc.ca/wms/hydro_network_en` | **Marche** (capacités lues). Même réseau, présentation par échelle ; non retenu dans la page (CanVec suffit). |
| A'' | RNCan élévation (MNEHR, relief ombré) | `https://datacube.services.geo.ca/wrapper/ogc/elevation-hrdem-mosaic` | Marche pour les tuiles `dtm-hillshade` (≈ 3 s) ; un 502 passager sur GetCapabilities. |
| B | **GRHQ simple** (MRNF, WMS) | `https://servicescarto.mrnf.gouv.qc.ca/pes/services/Territoire/GRHQ_simple_WMS/MapServer/WMSServer` | **Marche** : couches 1-7 (surfaces), 9-16 (cours d'eau permanents et intermittents), 18-19 (rapides), 20-21 (limites). Toponymes à l'écran. 0,5 à 0,8 s et ≈ 6 Ko par tuile. |
| C | **GRHQ détaillé** (MRNF, WMS) | `…/Territoire/GRHQ_WMS/MapServer/WMSServer` | **Marche** : couches 1-7, 9-14, 17-21, 22 (sens d'écoulement), 23 (jonctions). 0,4 à 1,1 s et 2 à 12 Ko par tuile. |
| D | **GRHQ + bassins + BDZI** (MELCCFP, ArcGIS REST) | `https://www.servicesgeo.enviroweb.gouv.qc.ca/donnees/rest/services/Public/Themes_publics/MapServer` | **Marche, la meilleure source.** CORS ouvert (renvoie l'origine). Couche 101 = ordre de Strahler ; 27 à 34 = bassins nommés avec superficie ; 22 et 42 = zones inondables ; 104 = plans d'eau. `export` de tuile : 0,05 s, 1 à 2 Ko. |
| E | ECCC OGC API, stations | `https://api.weather.gc.ca/collections/hydrometric-stations` | **Marche.** CORS ouvert (`*`). 1 001 stations au Québec (243 en service). Filtre `bbox` pour n'avoir que les stations proches. |
| F | ECCC, séries | `…/hydrometric-annual-statistics`, `-annual-peaks`, `-daily-mean`, `-realtime` | **Marchent**, avec limites (voir plus bas). `f=csv` et `properties=` allègent d'un facteur 4 à 6. |
| G | CEHQ, stations | `donneesquebec.ca` (CSV) | **Marche.** 755 stations, avec cours d'eau, bassin, régime (influencé ou non). CC-BY 4.0. |
| H | CEHQ, suivi temps réel | `https://www.cehq.gouv.qc.ca/suivihydro/fichier_donnees.asp?NoStation=023402` | Données **valides** (pas de 15 min, 7 jours) mais **sans CORS** : inutilisable directement par la page. Précalculé par `build_cache.py`. |
| I | Carte interactive des zones inondables du CEHQ | `cehq.gouv.qc.ca/zones-inond/carte-esri/` | Non testée : la BDZI (D) donne les mêmes polygones. |

### Pièges rencontrés
- **Serveur du MRNF** : refuse les clients dont le User-Agent n'est pas celui d'un navigateur (`curl` : connexion coupée) et coupe parfois des connexions, même depuis le navigateur (quelques tuiles `ERR_CONNECTION_RESET` en début de séance). **Ne jamais appeler GetCapabilities** : 300 Ko et 5 à 15 s. Coder les numéros de couches en dur.
- **BDZI** : `f=geojson` renvoie une erreur 400 sur les polygones. Il faut lire `f=json` (Esri JSON) et convertir. Sans `maxAllowableOffset`, un point près de l'Etchemin ramène 370 Ko ; avec ≈ 10 m de tolérance, 23 Ko.
- **Plans d'eau (couche 104)** en tuiles : des milliers d'étiquettes « Lac » ; à éviter en vue régionale.
- **Erreurs ArcGIS** : renvoyées en HTTP 200 avec un champ `error` ; la page les traite comme des échecs.
- **ECCC temps réel** : seulement 15 stations du Québec avaient des données dans les dernières heures (Outaouais, Richelieu, fleuve). Les stations du CEHQ (les plus nombreuses) n'y sont pas, bien que marquées « temps réel » dans la liste. L'historique journalier HYDAT a un an de retard (jusqu'en sept. 2025 pour la Chaudière, 2023 pour le Saint-François à Sherbrooke).
- **Séries de crues** : les maxima **instantanés** (`annual-peaks`) n'existent que pour certaines stations fédérales (Outaouais : 111 ans, niveaux seulement). Les stations du CEHQ n'ont que les maxima des **moyennes journalières** (`annual-statistics`), qui sous-estiment la pointe.

## Ce que montre le prototype

1. **Fenêtre « Cours d'eau au pont »** pour six ouvrages types, plus une saisie libre du n° de structure. Contenu : ordre de Strahler du tronçon le plus proche, pérennité, bassin nommé (superficie), zone inondable (type, rapport source, distance), station retenue avec bandeau d'avertissement, liste des stations proches cliquable, niveau et débit récents, maxima annuels avec droites de crue, droite de Gumbel, tableau 2/10/25/100 ans, étiage.
2. **Grande carte** avec 7 surcouches : CanVec, GRHQ simple, GRHQ détaillé, Strahler, zones inondables, courbes de niveau, stations (chargées à la volée par `bbox`).
3. **Comparaison synchronisée** CanVec / GRHQ simple / GRHQ détaillé, avec tableau de synthèse.
4. **Section « Ce que ça apporterait à l'atlas »** (couche ou fenêtre, simple ou détaillé, valeur, coûts, limites).

### Les six cas et ce qu'ils montrent

| N° | Ouvrage | Cas | Résultat mesuré |
|---|---|---|---|
| 03994 | Route 218 sur la Chaudière | Grande rivière, station au pont | Strahler 6 ; bassin 6 696 km² (station : 5 829 km², 87 %) ; station 02PJ005 à 0,2 km ; 83 années de maxima ; Gumbel : Q2 1 123, Q10 1 673, Q25 1 950, Q100 2 359 m³/s (maxima journaliers) ; suivi CEHQ du jour (023402). |
| 03988 | Route 173 sur l'Etchemin | Zone inondable officielle | Strahler 5 ; bassin 1 464 km² ; **pont à 4 m d'une zone de grand courant (0-20 ans)** ; station 02PH011 à 0,09 km ; 41 années ; Q100 ≈ 508 m³/s. |
| 16092 | A-20 sur l'Outaouais | Très grand cours d'eau, niveau en temps réel | Station de niveau 02OA013 à 0,14 km, **temps réel ECCC** (4 jours, 5 min) ; 92 années de niveaux maximaux ; zone de crue 0-100 ans à 98 m ; régime « influencé ». |
| 05041 | Chemin du Mont-Snow sur la rivière Rouge, Rawdon | **Station sur un autre cours d'eau** | Strahler 4 ; bassin 334 km² ; la station la plus proche mesure l'Ouareau (6 km, 1 264 km²) : bandeau d'avertissement, tableau « à la station » et ligne « transposé au pont » (facteur 0,34, indicatif). |
| 00002 | Route 395, ruisseau Alexandre, Amos | Petit cours d'eau sans station | Strahler 3 ; bassin 27 km² ; aucune station pertinente (la plus proche, l'Harricana, drainerait un bassin 135 fois plus grand) ; message explicatif. |
| 10082 | Ponceau de l'A-55 | Ruisseau intermittent sous remblai | Strahler 0 (non calculé), écoulement intermittent ; **zone de faible courant à 53 m** ; aucune station pertinente. |

## Méthode de la fenêtre

- **Strahler** : tronçons GRHQ dans 1 200 m, tronçon le plus proche du pont (distance affichée). Strahler = 0 dans les plans d'eau (grands cours d'eau polygonaux) : l'Outaouais en est un exemple.
- **Bassin** : bassin nommé le plus profond (niveaux 1 à 8) contenant le pont, via `identify`. C'est le bassin entier **à l'embouchure** : borne supérieure de la superficie en amont du pont.
- **Choix de la station** : rapprochement par noms normalisés (sans accents ni « rivière », « pont », etc.).
  - Même cours d'eau = les mots du nom de l'ouvrage sont dans le nom de la station.
  - Cours d'eau parent = nom d'un bassin englobant. Retenu seulement si le rapport des bassins reste entre 0,1 et 1,1.
  - Sinon : « aucune station pertinente » (la liste reste affichable, avec drapeau texte ✓, ⚠ ou ✗).
- **Gumbel** : lois des valeurs extrêmes de type I, ajustée par les moments sur les maxima annuels ; points au tracé de Weibull. Avertissements automatiques : moins de 20 années, maxima journaliers, régime influencé, station de niveau seulement.
- **Étiage** : minimum annuel du débit moyen journalier (médiane et record) ; carré vide = sous la glace. Ce n'est pas le Q7,2 ou Q7,10 réglementaire.
- **Daltonisme** : aucun code vert/rouge. Palette Okabe-Ito (bleu, orange, jaune) ; formes (carré = ouvrage, losange = station), traits (épaisseur = Strahler, pointillé = intermittent, hachures = zone inondable), droites de crue distinguées par leur tracé et leur étiquette, bandeaux avec symbole et mot (✓, ≈, ⚠).

## Combien d'ouvrages en profitent ?

Sur 11 701 ouvrages, **8 944** ont un cours d'eau comme obstacle (76 %), dont 8 197 avec un nom. Avec un rapprochement par nom (stations ECCC et CEHQ, ouvertes ou fermées, rayon 40 km) :

| Station du même nom à moins de | 1 km | 5 km | 10 km | 25 km |
|---|---|---|---|---|
| Ouvrages | 573 | 1 406 | 1 950 | 2 453 |

Environ trois ouvrages sur quatre n'ont donc pas de station utilisable. Pour eux : Strahler, bassin et zone inondable seulement. Rapprochement approximatif, à raffiner par un ETL (traitement par lots).

## Coûts et limites

- **Poids mesuré** : 25 Ko (petit cours d'eau sans station), 76 à 221 Ko (cas courants), 610 Ko (Outaouais : 4 jours de niveaux à 5 min). Une tuile : 1 à 12 Ko.
- **Latence** : 0,1 à 0,4 s en régime normal ; une ouverture « à froid » a pris près de 7 s (service lent). Prévoir l'indicateur d'étapes, déjà dans la fenêtre.
- **Rien à héberger** sauf le fichier des 755 stations du CEHQ (≈ 90 Ko, mise à jour annuelle) et, pour le temps réel du CEHQ, un relais.
- **Dépendances** : quatre services externes sans garantie de service. Le MRNF est le moins fiable (coupures, filtre de User-Agent).
- **Valeur de calcul** : aucune. Pas de revanche, pas de cote de crue, pas de datum commun entre les niveaux de station et le LiDAR. À afficher comme repère.
- **Données partielles** : BDZI incomplète ; 76 % des stations québécoises sont fermées ; historique HYDAT en retard d'un an.

## Recommandation d'intégration

| Étape | Contenu | Effort |
|---|---|---|
| 1 (v0.6) | **Couche** « Cours d'eau » dans le menu des fonds : GRHQ simple (MRNF), repli CanVec ; option « Strahler » (MELCCFP, 0,05 s par tuile, très robuste) ; GRHQ détaillé à la demande en zoom ≥ 14 | 0,5 j |
| 2 (v0.6) | **Bouton « Cours d'eau au pont »** dans la fiche pour les ouvrages dont l'obstacle est un cours d'eau : reprise du dialogue (carte + chips + bandeau + graphiques), sans le temps réel du CEHQ | 2 à 3 j |
| 3 | **Relais pour le suivi temps réel du CEHQ** (fonction serverless de 20 lignes, ou ETL quotidien) + liste des stations du CEHQ dans les données de l'atlas | 1 j |
| 4 | **ETL** : rapprochement pont-station-bassin pour les 8 944 ouvrages, résultats stockés dans `structures.js` (nom du bassin, Strahler, station, distance, zone inondable O/N) ; filtres et tris dans l'atlas (p. ex. « ouvrages en zone de grand courant ») | 3 à 4 j |
| 5 (plus tard) | **Revanche indicative** : LiDAR (tablier au-dessus de l'eau) + cote de crue de la BDZI ou d'une station, après validation d'un datum commun avec un hydrologue | à cadrer |

Total des étapes 1 à 3 : environ 4 à 5 jours. L'étape 4 est la plus rentable (priorisation des inspections d'affouillement après une crue) mais demande de valider la méthode de rapprochement avec un hydrologue.

## À corriger ou à valider avant intégration

1. Le rapprochement par noms échoue sur les noms variables (« Décharge du lac… », « Ruisseau » sans nom, homonymes). Prévoir une liste de corrections manuelles.
2. Valider avec le CEHQ la réutilisation des fichiers `fichier_donnees.asp` (aucune licence précisée sur la page de suivi).
3. Les crues sont calculées sur de courtes séries (11 à 83 ans, parfois moins) et sans tenir compte des changements climatiques : à présenter comme « ordre de grandeur », jamais comme valeur de projet.
4. Vérifier les niveaux de la station CEHQ 023402 (≈ 112 m) face aux niveaux ECCC de la même station (≈ 21 à 23 m) : les zéros d'échelle diffèrent, ce qui confirme qu'il ne faut pas comparer des niveaux de station à des cotes de pont sans levé.
