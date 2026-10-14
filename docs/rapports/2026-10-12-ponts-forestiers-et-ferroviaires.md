# Ponts forestiers et ouvrages ferroviaires — recherche et prototype du 2026-10-12

**En bref**

- **Ponts forestiers : oui, des données existent et elles sont ouvertes.** Mais elles sont maigres : une position, un numéro de dossier, un statut et (parfois) une capacité portante. Pas de type, de matériau, de portée, d'année ni d'état.
- **Ouvrages ferroviaires CN / CPKC : non, aucune base ouverte.** Ni les compagnies ni Transports Canada ne publient d'inventaire de ponts. Par contre, la **couche ferroviaire du MTMD, déjà dans l'atlas**, marque 1 372 segments de voie sur pont, pont mobile ou tunnel (champ `typstruc`). L'atlas ne l'exploite pas encore.
- Prototype : `prototypes/forestiers/prototype-forestiers.html` (carte, comptes par source, doublons, évaluation).

**Sigles** : MTMD = ministère des Transports et de la Mobilité durable ; MRNF = ministère des Ressources naturelles et des Forêts ; MFFP = ancien nom du MRNF pour les forêts ; RNCan = Ressources naturelles Canada ; AQréseau+ = produit routier d'Adresses Québec (devenu RQTT, Référentiel québécois du transport terrestre) ; RFN / NRWN = Réseau ferroviaire national ; RRN / NRN = Réseau routier national ; OSM = OpenStreetMap ; PRANA = programmation annuelle autorisée ; RATF = rapport d'activité technique et financier ; CN = Canadien National ; CPKC = Canadien Pacifique Kansas City ; CFIL = chemin de fer d'intérêt local ; WFS / WMS = services web de données / d'images cartographiques.

---

## 1. Ponts sur chemins forestiers (chemins multiusages)

### 1.1 Ce qui existe

Les ponts des chemins multiusages relèvent du MRNF et des détenteurs de droits forestiers, **pas du MTMD**. Ils n'entrent donc pas dans l'inventaire « Structure ».

| Source | Adresse testée | Volume | Attributs utiles | Licence · mise à jour | Verdict |
|---|---|---|---|---|---|
| **AQréseau+ / RQTT**, couches « Pont ouvert », « Pont inconnu », « Pont fermé » | [REST MapServer](https://servicescarto.mrnf.gouv.qc.ca/pes/rest/services/Territoire/AQreseauPlus_WMS/MapServer) couches 1, 2, 3 (GeoJSON, 2 000 objets par requête) | **11 321 points** : 5 126 ouverts, 5 130 inconnus, 1 065 fermés | Position, n° de dossier du pont (`Dossi_Pont`), capacité portante (`Cap_Port`, 3 valeurs en tonnes), statut (`Stat_Pont`), source, version. **Ni type, ni matériau, ni portée, ni année, ni propriétaire, ni état.** | CC-BY 4.0 · trimestrielle (mars, juin, sept., déc.) ; version testée AQ20260701 · « aucune valeur légale » | **Retenue.** Seule source ouverte qui couvre tout le Québec. |
| AQréseau+ — chemins multiusages | [couche 37](https://servicescarto.mrnf.gouv.qc.ca/pes/rest/services/Territoire/AQreseauPlus_WMS/MapServer/37) ; WMS : couche 81 | **944 719 tronçons** | Classe de chemin forestier (`Cls_CheFor`), gestionnaire (`Gestion` : Forêt, Transports Québec, Privé, Municipal…), et, pour 3 037 tronçons, n° de pont, capacité portante, statut | CC-BY 4.0 · trimestrielle | Contexte seulement (trop lourd à embarquer). Affiché en WMS dans le prototype. |
| **Ponts et ponceaux autorisés** (PRANA) | [WFS](https://geoegl.msp.gouv.qc.ca/ws/mffpecofor.fcgi?service=WFS&version=2.0.0&request=GetCapabilities) `ms:prana_ponts_ponceaux` ; [GPKG 29 Mo](https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/INTERVENTIONS_FORESTIERES//PRANA/PRANA_2026.gpkg.zip) | 152 points (147 ponceaux, 4 ponts, 1 ouvrage amovible) | Type, chantier, intervention prévue. Aucune dimension | CC-BY 4.0 · annuelle | Écartée : **travaux planifiés**, pas un inventaire. |
| **RATF** | [Données Québec](https://www.donneesquebec.ca/recherche/dataset/rapport-d-activite-technique-et-financier-ratf) ; un FGDB par année, 2013-14 à 2024-25 | **2024-25** (FGDB de 86 Mo, extrait) : **20 ponts**, 2 690 ponceaux, 24 096 chemins | Couches `pont` et `ponc` : type de structure (codes `ACBO` 16, `BOIS`, `ACIER`, `ACBE` pour les ponts ; plastique et tôle ondulée pour les ponceaux), intervention (implantation, réfection, amélioration), dates de début et de fin, méthode de levé (GPS ou numérisation). **Seule source qui donne un type de pont**, mais ni portée ni état | CC-BY 4.0 · annuelle | Écartée : **seulement les ponts touchés par des travaux de l'année** (20 en 2024-25). Un fichier par année. |
| **Opérations régionales** MRNF | [serveur ArcGIS](https://operationsregionales.mrnf.gouv.qc.ca/server/rest/services) : `Pont_fermés_Routard` (52), `Ponts_fermés_Reg_14` (9), `Pont_planifie_oct_2026` (128), `038_Activités_2025_2026 - Ponts et Ponceaux` (132) | 2 à 132 points par couche | Ponts fermés ou planifiés d'une région | Variable | Écartée : partiel. L'ancien domaine `operationsregionales.mffp.gouv.qc.ca` n'existe plus (nom DNS introuvable). |
| **RRN** de RNCan | [GPKG Québec, 403 Mo](https://geo.statcan.gc.ca/nrn_rrn/qc/nrn_rrn_qc_GPKG.zip) ; service REST `geo.statcan.gc.ca/geo_wa/rest/services/NRN-RRN/nrn_rrn/MapServer` | Non compté (fichier trop gros) ; le service REST répond « Application Error » | Sur chaque tronçon : `STRUCTTYPE` (pont, pont couvert, pont mobile, tunnel…), `STRUCTID`, nom de la structure | Licence du gouvernement ouvert – Canada · 2026-06 | Écartée : des tronçons, pas des ouvrages ; recoupe AQréseau+. |
| **OpenStreetMap** (Overpass) | `way[highway][bridge]` | **19 007** tronçons de route avec `bridge` au Québec ; 1 833 sur `track`, 2 774 sur `unclassified`, 792 sur `service` (80 084 `track` au total) | Géométrie (donc longueur), type de pont, nom, surface. `maxweight` sur moins de 1 %. Pas de matériau, d'année ni de propriétaire | ODbL · continue | **Complément utile** : donne la longueur et trouve des ponts absents d'AQréseau+. |
| Autres | « Infrastructures en milieu forestier » (polygones), cartes écoforestières, RQTT ([GPKG 409 Mo](https://diffusion.mern.gouv.qc.ca/diffusion/RGQ/Vectoriel/Theme/Local/RQTT/OGC(GPKG)/RQTT_GPKG.zip)) | — | Aucun inventaire de ponts supplémentaire | CC-BY 4.0 | Le RQTT remplace AQréseau+ : son service web n'est pas encore ouvert, l'ancien reste actif « jusqu'à la mise en service ». |

À savoir :

- Le MRNF a évalué la capacité portante d'environ **2 000 ponts forestiers** et les affiche sur place, d'après sa [procédure d'affichage](https://cdn-contenu.quebec.ca/cdn-contenu/forets/documents/ponts/PR_affichage_capacite_portante_ponts.pdf). Ces avis ne sont pas publiés ; c'est probablement ce que contient `Cap_Port`.
- Les trois valeurs de `Cap_Port` sont des tonnes selon la configuration du véhicule (ex. `30-48-60`). La fiche de couche ne dit pas lesquelles. `0-0-0` signale un pont fermé, `INC` une capacité inconnue.
- La base interne « Routard » du MFFP n'est pas documentée publiquement. Son nom apparaît dans la source `ROUTARD` et dans la couche `Pont_fermés_Routard`.
- Appel de bonne foi : la fiche de couche AQréseau+ précise que « les informations diffusées sont celles disponibles à ce jour au MFFP ».
- **Piège technique** : le serveur du MRNF coupe les connexions du client Python `requests` (reset TLS) mais accepte `curl`. Le script `fetch_aq.py` passe donc par `curl`.

### 1.2 Ce que contient AQréseau+ (11 321 ponts)

Le champ `Source` dit d'où vient chaque point. Les chiffres comparent à l'inventaire du MTMD (11 701 ouvrages avec coordonnées), par proximité : **à moins de 30 m = doublon probable**.

| Source | Total | À moins de 30 m d'un ouvrage MTMD | **Hors MTMD** | Ouverts / inconnus / fermés (hors MTMD) | Capacité portante > 0 (hors MTMD) |
|---|---:|---:|---:|---|---:|
| `AQ` | 7 440 | 6 395 | 1 052 | 523 / 528 / 1 | 34 |
| `ROUTARD` | 2 530 | 11 | **2 519** | 1 468 / 65 / 986 | 1 467 |
| `DGIG` | 754 | 7 | 747 | 51 / 676 / 20 | 51 |
| `AQ_FO` | 482 | 93 | 389 | 265 / 93 / 31 | 273 |
| `Sépaq` | 60 | 0 | 60 | 49 / 8 / 3 | 49 |
| `BDTQ` (Base de données topographiques du Québec) | 55 | 1 | 54 | 31 / 1 / 22 | 31 |
| **Total** | **11 321** | **6 500** | **4 821** | 2 387 / 1 371 / 1 063 | 1 905 |

Lecture :

- `AQ` (6 chiffres) = surtout des ponts du MTMD déjà dans l'atlas (88 % à moins de 30 m).
- `ROUTARD` (n° `H000-000` et `R0000-00`) = les **vrais ponts de chemins multiusages** : 2 519 hors MTMD, dont 1 468 ouverts avec capacité portante et 986 fermés (`0-0-0`).
- `DGIG` : sa signification n'est pas documentée (vraisemblablement la Direction générale de l'information géographique du MRNF). 676 de ses 747 ponts ont un statut inconnu et aucune capacité : donnée la plus faible.
- `AQ_FO` : probablement issu de Forêt ouverte (non documenté).
- La médiane de la distance au plus proche ouvrage du MTMD est de **5 m** pour les points à moins de 100 m : le seuil de 30 m est large mais raisonnable.
- Doublons à 100 m : 6 981. Seulement 481 de plus qu'à 30 m, donc peu de ponts du MTMD sont décalés de 30 à 100 m.

### 1.3 Trois régions de démonstration

Zones de démonstration : deux rectangles (Saguenay–Lac-Saint-Jean, Abitibi) et un polygone pour la Côte-Nord (limité à la rive nord du Saint-Laurent). Ce ne sont pas les limites administratives exactes.

| Mesure | Saguenay–Lac-Saint-Jean | Côte-Nord | Abitibi |
|---|---:|---:|---:|
| Ouvrages du MTMD | 608 | 193 | 422 |
| Ponts AQréseau+ | 1 245 | 374 | 563 |
| dont hors MTMD | **846** | **267** | **261** |
| — dont `ROUTARD` | 588 | 198 | 195 |
| Ponts forestiers hors MTMD (`ROUTARD`, `AQ_FO`, `DGIG`) confirmés par un pont OSM à moins de 50 m | 215 sur 783 (27 %) | 100 sur 255 (39 %) | 91 sur 239 (38 %) |
| Ponts OSM (route avec `bridge`) | 1 244 | 422 | 740 |
| — chemins et pistes (`track`, `service`) | 252 | 71 | 180 |
| — dont ni MTMD ni AQréseau+ à moins de 30 m | 187 | 53 | 159 |
| — routes locales | 555 | 188 | 386 |
| — dont ni MTMD ni AQréseau+ | 212 | 80 | 111 |

Ce que ça dit :

- **OSM connaît beaucoup moins de ponts forestiers qu'AQréseau+** (27 à 39 % de confirmation), mais il en connaît que le MRNF n'a pas : 187 pistes sur 252 dans le Saguenay–Lac-Saint-Jean n'ont ni ouvrage MTMD ni point AQréseau+ à moins de 30 m.
- OSM donne la **longueur** (moyenne de 36 à 73 m selon la zone) et parfois un nom (32 à 51 % des ponts). `maxweight` est quasi absent (3 ponts sur 2 406).
- Les deux sources se complètent, sans se valider l'une l'autre.

### 1.4 Est-ce que ça aurait de l'allure de les ajouter à l'atlas ?

**Oui, comme couche séparée, légère et clairement étiquetée. Non, comme fiches d'ouvrage.**

- **Valeur : moyenne.**
  - 4 821 ponts hors MTMD, dont 2 519 « Routard », l'essentiel des ponts de chemins multiusages.
  - Capacité portante pour 1 905 : utile à un transporteur ou à un gestionnaire, peu à un ingénieur en structures.
  - Répond à « où sont les ponts qui ne sont pas au MTMD ? ».
- **Qualité : faible à moyenne.**
  - Aucun type, matériau, portée, année ni état.
  - Statut inconnu pour 1 371 ponts, fermé pour 1 063 (des ponts démantelés peuvent rester listés).
  - Positions non validées de façon indépendante.
  - Plusieurs identifiants (`H000-000`, `R0000-00`) n'ont aucune fiche publique.
- **Poids : léger.** ≈ 207 Ko (60 Ko compressés) pour les 4 821 points (lat, lon, source, statut, n° de dossier, capacité). Les ponts OSM hors MTMD des chemins et routes locales des 3 régions ajoutent ≈ 103 Ko (28 Ko compressés). Les chemins multiusages restent en WMS.
- **Mise à jour : facile.** Trimestrielle chez le diffuseur. L'extraction tient en 6 requêtes REST d'environ une minute. Un module `etl/forestiers.py` calqué sur `etl/villes.py` suffit. Attention au changement de nom (AQréseau+ vers RQTT).
- **Risques.**
  - Confusion avec un inventaire d'inspection : ces ponts ne sont pas sous la responsabilité du MTMD.
  - « Aucune valeur légale » selon le diffuseur ; ne pas servir de ces positions ni de ces capacités pour un calcul.
  - Doublons avec le MTMD (6 500 points), à filtrer comme dans le prototype.
  - Une capacité portante affichée comme un état laisserait croire qu'un pont est « bon ».

**Façon de faire proposée.**

1. Couche « Ponts forestiers (MRNF) », **désactivée par défaut**, avec les 4 821 points hors MTMD. Forme selon la source, remplissage selon le statut, jamais de couleur d'état.
2. Fiche courte : n° de dossier, capacité portante (avec la note « 3 configurations de véhicule »), statut, source, version d'AQréseau+, avertissement permanent.
3. Option : pont OSM à moins de 50 m, pour donner une longueur approximative.
4. Pas de score d'état, pas de lien avec l'ICG (indice de condition général) du MTMD.

**Effort estimé : 2 à 3 jours** (ETL, couche, fiche, tests). Le premier jet est dans le prototype (`fetch_aq.py`, `build.py`).

---

## 2. Ouvrages ferroviaires (CN, CPKC et autres)

### 2.1 Réponse

**Non, aucune base de données ouverte du CN ni du CPKC.**

- Ni le CN, ni le CPKC, ni VIA Rail, ni les chemins de fer d'intérêt local du Québec ne publient un inventaire de leurs ponts. Je n'ai trouvé aucun jeu de données sur Données Québec ni sur le portail du gouvernement ouvert.
- **Transports Canada** : la [ligne directrice sur la gestion de la sécurité des ponts (2018)](https://tc.canada.ca/en/rail-transportation/guidelines/guideline-bridge-safety-management/part-general) confie l'inventaire et les inspections aux compagnies. Le ministère surveille par des inspections fondées sur le risque et par les données que les compagnies lui transmettent (selon ses pages, en vertu du *Règlement sur les renseignements relatifs au transport*). **Rien n'est publié.** Je n'ai pas vérifié le texte du règlement ni testé une demande d'accès à l'information.
- Seul inventaire ferroviaire ouvert de Transports Canada trouvé : l'[inventaire des passages à niveau](https://tc.canada.ca/en/rail-transportation/grade-crossings/grade-crossings-inventory), mis à jour chaque année. Il ne contient pas de ponts.
- Les pages du CPKC sur les [travaux publics](https://www.cpkcr.com/en/community/public-works-and-utilities) ne parlent que des franchissements de la voie par de nouveaux ponts routiers (je n'ai pas fouillé le site du CN).

### 2.2 Ce qui existe quand même

| Source | Adresse testée | Volume | Attributs utiles | Licence · mise à jour | Verdict |
|---|---|---|---|---|---|
| **Couche ferroviaire du MTMD** | [WFS](https://ws.mapserver.transports.gouv.qc.ca/swtq?service=wfs&version=2.0.0&request=getfeature&typename=ms:reseau_chfer_qc&srsname=EPSG:4326&outputformat=geojson) `ms:reseau_chfer_qc` (déjà utilisée par `etl/reseaux.py`) | 12 653 segments, dont **1 372 sur structure** : 1 348 ponts, 9 ponts mobiles, 15 tunnels | Exploitant, propriétaire, usage, état de la voie, subdivision, **type de structure** (`typstruc`) ; longueur du segment par la géométrie | CC-BY 4.0 · version 2026-06-08 | **Retenue.** Aucune nouvelle donnée à télécharger. Le champ `typstruc` n'est pas utilisé par l'atlas. |
| **RFN / NRWN** de RNCan | [SHP Québec, 5,4 Mo](https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_nrwn_rfn/qc/nrwn_rfn_qc_shp_en.zip) ; [WMS](https://maps.geogratis.gc.ca/wms/railway_en?service=WMS&version=1.3.0&request=GetCapabilities) (couches `railway.structure.line` et `.point`) | 1 350 ponts, 9 ponts mobiles, 87 tunnels, 100 ponceaux (lignes ou points) | Type de structure, voie, subdivision ; nom de la structure toujours « None » ; exploitant et propriétaire en joignant la couche des voies | Licence du gouvernement ouvert – Canada · données de 2014 (fichiers de 2019) | Même origine que la couche du MTMD, mais plus ancienne. Sert de vérification. |
| **OpenStreetMap** | Overpass `way[railway=rail][bridge]` (1 requête, ~30 s) | **1 170 tronçons**, 79,9 km | Nom (92 %), exploitant (98 %), propriétaire (58 %), usage, type de pont (96 % `yes`), `layer`. Pas de matériau, d'année ni de portée | ODbL · continue | Complément : noms de ponts et exploitants à jour. Peu de valeur ajoutée. |
| Transports Canada | Ligne directrice ; inventaire des passages à niveau | — | — | — | Pas de ponts. |

### 2.3 Chiffres (Québec)

Segments ou tronçons ; un même pont peut en compter plus d'un.

| Exploitant | Ponts, couche du MTMD | Tronçons OSM |
|---|---:|---:|
| CN | 654 | 652 |
| CPKC | 278 | 187 |
| Courtes lignes et industriels (CFQG, CFC, SLQ, QNSL, etc.) | 418 | 286 |
| Autre ou inconnu | 7 | 45 |
| **Total** | **1 357** | **1 170** |
| Longueur cumulée | 86,3 km | 79,9 km |
| Tunnels | 15 | — |

- **Recoupement** : 74 % des ponts de la couche du MTMD ont un pont OSM à moins de 30 m ; 86 % des tronçons OSM ont un pont de la couche du MTMD à moins de 30 m. Les deux sources racontent la même histoire.
- Statut de la voie sous les ponts de la couche du MTMD : 1 242 opérationnels, 110 inexploités, 3 abandonnés, 2 inconnus.

### 2.4 Ponts routiers au-dessus des voies vs ponts ferroviaires

- **Ponts routiers au-dessus des voies** : **177** ouvrages du MTMD ont pour obstacle un chemin de fer (+ 3 « mixtes »). Ils sont dans l'atlas. Ils appartiennent aux gestionnaires routiers.
- **Ponts ferroviaires** (la voie passe sur un pont, au-dessus d'une rivière ou d'une route) : propriété des compagnies, **absents** de l'inventaire du MTMD. Aucune inspection de ces ponts ne se retrouve dans l'atlas.
- **150 ponts ferroviaires** de la couche du MTMD ont un ouvrage du MTMD à moins de 30 m (82 sur un cours d'eau, 46 sur une route, 4 sur un chemin de fer, 18 sans obstacle classé). Ce sont presque sûrement des **ponts routiers voisins**, pas les ponts ferroviaires eux-mêmes.
- **Exception notable** : le **MTQ est propriétaire de lignes** de la Gaspésie et du Québec Central (sigles `SCFG(MTQ)` et `CFQC(MTQ)`, subdivisions Cascapédia, Chandler West, Vallée, Chaudière, Lévis). **156 segments de pont** leur appartiennent. Seulement **44** ont un ouvrage du MTMD à moins de 30 m. Le ministère devrait donc avoir ces dossiers en interne, mais ils ne sont pas dans le jeu « Structure ».

### 2.5 Est-ce que ça aurait de l'allure ?

- **Valeur** : moyenne, pour l'ingénieur qui se demande « quel pont ferroviaire passe ici ? » (franchissement de cours d'eau, proximité d'un pont routier).
- **Qualité** : géométrie seulement. La longueur vient du tracé, pas d'un plan. Aucun matériau, année, portée ni état.
- **Poids** : nul si on réutilise la couche déjà embarquée (`data/couche-rail.js`) ; ≈ 60 Ko à ajouter pour le champ de structure.
- **Mise à jour** : celle de la couche ferroviaire actuelle.
- **Risques** : laisser croire que l'atlas a l'état des ponts du CN ou du CPKC (il ne l'a pas) ; confondre les ponts routiers au-dessus des voies avec les ponts ferroviaires.

**Façon de faire proposée.**

1. **Surligner les voies sur pont** dans la couche ferroviaire déjà affichée, à partir du champ `typstruc` (trait plus épais ou pointillé, forme redondante avec la couleur). Étiquette : « Pont ferroviaire — propriétaire : CN », sans fiche d'ouvrage. **Effort : environ 0,5 jour.**
2. Ajouter exploitant, propriétaire et longueur du segment à l'infobulle, avec la mention « longueur de la géométrie ».
3. **Ne pas** intégrer OpenStreetMap : trop peu de valeur ajoutée.
4. Demander en interne les dossiers des 156 segments de pont appartenant au MTQ.
5. Pour le reste, une demande d'accès à l'information à Transports Canada est la seule voie vers un inventaire des ponts ferroviaires (non vérifiée ; peu de chances de succès, vu les enjeux de sécurité).

---

## 3. Le prototype

- Fichier : `prototypes/forestiers/prototype-forestiers.html` (Leaflet 1.9.4, autonome ; lit `../../data/structures.js`).
- Données embarquées : `data-forestiers.js` (0,81 Mo) et `data-ferroviaire.js` (0,45 Mo).
- Carte : ouvrages du MTMD, ponts forestiers d'AQréseau+ hors MTMD (forme = source, remplissage = statut), ponts OSM, chemins multiusages (WMS), ponts ferroviaires par exploitant, ouvrages routiers au-dessus des voies. Trois régions (Saguenay–Lac-Saint-Jean, Côte-Nord, Abitibi) et tout le Québec.
- Accessibilité : forme, remplissage, motif de trait et texte doublent toujours la couleur (palette Okabe-Ito).
- Page : comptes par source calculés dans la page, tableau des sources essayées, évaluation, section ferroviaire.
- Régénérer :
  1. `python fetch_aq.py` (AQréseau+, via `curl`).
  2. `python osm_fetch.py` (Overpass, une requête à la fois avec pauses de 15 s ; reprises espacées).
  3. `python extract_nrwn.py <dossier_shp>` (facultatif, validation ; nécessite `pyogrio`).
  4. `python build.py` : calcule les distances au MTMD, écrit les deux fichiers de données et `cache/stats.json`.
- Les réponses brutes sont dans `prototypes/forestiers/cache/`.

## 4. Limites

- Les positions d'AQréseau+ et le seuil de 30 m n'ont pas été validés sur le terrain.
- OSM n'a été interrogé que pour 3 zones, pas pour tout le Québec (sauf les comptes globaux et les ponts ferroviaires).
- La signification exacte de `Cap_Port`, `DGIG` et `AQ_FO` vient de déductions ; seule la documentation officielle (guide AQréseau+, fiche RQTT) ou le MRNF peut la confirmer.
- Les ponts ferroviaires dont le MTQ est propriétaire sont comptés par segments de voie. Le nombre de ponts distincts est plus petit.
- Du RATF, seule l'année 2024-25 a été téléchargée (86 Mo, lue puis supprimée) ; le contenu des autres années n'est pas vérifié. Les codes de type de pont (`ACBO`, `ACBE`…) ne sont pas décodés par une documentation lue.
- Je n'ai pas testé de demande d'accès à l'information ni consulté les sites du CN et de VIA Rail en détail.
