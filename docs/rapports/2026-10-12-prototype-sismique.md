# Prototype « aléa sismique CNBC 2025 » — rapport du 2026-10-12

**En bref** : les trois pistes sont faisables. Mais **le navigateur ne peut pas appeler l'API de RNCan directement** (en-tête CORS en double), il faut donc un petit proxy ou du précalcul. La carte de PGA du Québec ne doit pas se faire par l'API : RNCan publie la **grille officielle** (Dossier public 8950, licence gouvernement ouvert). Les classes de site de Montréal sont reconstituées avec précision à partir d'une étude publiée (CC BY 4.0). Pour le reste du Québec, la voie réaliste est une **carte déduite des dépôts de surface** (méthode déjà publiée par la même équipe de McGill, 2025).

Fichiers : `prototypes/sismique/` — `prototype-sismique.html` (le prototype), `precalcul_sismique.py`, `classes_depuis_image.py`, `proxy_api.py`, `donnees_sismique.js`, `couche_classes_site_mtl.png`. Ouvrir via http://127.0.0.1:8765/prototypes/sismique/prototype-sismique.html. Pour les appels en direct (point libre, Vs30 saisi), lancer d'abord `python prototypes/sismique/proxy_api.py`.

**Sigles** : **CNBC** = Code national du bâtiment du Canada (NBC en anglais). **CSA S6** = Code canadien sur le calcul des ponts routiers. **PGA** = accélération maximale du sol (en g). **PGV** = vitesse maximale du sol (ici en m/s). **Sa(T)** = accélération spectrale à la période T (en g). **Vs30** = vitesse moyenne des ondes de cisaillement sur les 30 premiers mètres (m/s). **RNCan** = Ressources naturelles Canada. **CanSHM6** = modèle d'aléa sismique de 6e génération du Canada. **TIN** = réseau de triangles irréguliers. **CVD** = daltonisme.

## 1. L'API GraphQL de RNCan

URL : `https://www.earthquakescanada.nrcan.gc.ca/api/canshm/graphql` (POST JSON, sans clé ; l'introspection est ouverte). Même point d'accès sur `www.seismescanada.rncan.gc.ca`.

### Schéma utile

| Requête | Arguments | Rôle |
|---|---|---|
| `NBC2025(latitude, longitude)` | deux `Float!` | valeurs de l'outil CNBC 2025 (même type que `canSHM6P1`) |
| `NBC2020(latitude, longitude)` | idem | valeurs CNBC 2020 (alias : `canSHM6`) |
| `zone(latitude, longitude)` | idem | zone de modèle (`id`, `geometry`) |

Sous `NBC2025` : `metadata { projX projY zones }`, puis deux champs de valeurs.

| Champ | Arguments | Sens |
|---|---|---|
| `siteDesignationsXs` | `siteClass` (A, B, C, D ou E), `poe50` (liste, facultatif) | désignation par **classe de site** |
| `siteDesignationsXv` | `vs30` (140 à 3000 m/s), `poe50` (facultatif) | désignation par **Vs30** |

Chaque ligne renvoyée : `vs30` (plage de la classe, ou valeur), `poe50` (probabilité de dépassement en 50 ans, en %), `foe` (fréquence annuelle), `pga`, `pgv`, `sa0p05`, `sa0p1`, `sa0p2`, `sa0p3`, `sa0p5`, `sa1p0`, `sa2p0`, `sa5p0`, `sa10p0`.

Probabilités disponibles (10) : **2 ; 2,5 ; 3,5 ; 5 ; 7 ; 10 ; 14 ; 20 ; 30 ; 40 %** en 50 ans. Le code n'en utilise que trois (2, 5 et 10 %). 2 % en 50 ans = période de retour de ≈ 2 475 ans. Unités : PGA et Sa en g, PGV en m/s. Retourne `null` hors de la zone couverte (États-Unis, mer).

### Requête exacte qui fonctionne

```graphql
{
  NBC2025(latitude: 45.532, longitude: -73.583) {
    metadata { zones }
    A: siteDesignationsXs(siteClass: A) { vs30 poe50 foe pga pgv sa0p05 sa0p1 sa0p2 sa0p3 sa0p5 sa1p0 sa2p0 sa5p0 sa10p0 }
    B: siteDesignationsXs(siteClass: B) { vs30 poe50 foe pga pgv sa0p05 sa0p1 sa0p2 sa0p3 sa0p5 sa1p0 sa2p0 sa5p0 sa10p0 }
    C: siteDesignationsXs(siteClass: C, poe50: [2, 5, 10]) { poe50 pga pgv sa0p2 sa1p0 }
    v450: siteDesignationsXv(vs30: 450, poe50: [2]) { vs30 pga pgv sa0p2 sa1p0 }
  }
}
```

```bash
curl -s -X POST https://www.earthquakescanada.nrcan.gc.ca/api/canshm/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"{ NBC2025(latitude:45.532, longitude:-73.583){ siteDesignationsXs(siteClass:B, poe50:[2]){ vs30 poe50 pga pgv sa0p2 sa1p0 } } }"}'
```

Résultat (site de l'exemple fédéral, classe B, 2 % en 50 ans) : PGA 0,422 g ; PGV 0,22 m/s ; Sa(0,2) 0,739 g ; Sa(1,0) 0,152 g. On peut mettre **plusieurs points dans une requête** avec des alias (`p0:NBC2025(...) p1:NBC2025(...)`) : 25 points en une requête ont passé.

### Constats

- **CORS bloquant** : la réponse contient deux fois `Access-Control-Allow-Origin` (« multiple values »). Chrome rejette `fetch()` depuis toute autre origine, même si `curl` marche. Constaté dans le navigateur intégré. L'outil officiel marche parce qu'il est de la même origine.
  - Solution du prototype : `proxy_api.py` (une cinquantaine de lignes, port 8766, un seul en-tête, cache, ≥ 0,5 s entre appels, requêtes `NBC2025` seulement).
  - En production : fonction serverless (type Cloudflare Worker) ou précalcul. On peut aussi demander à RNCan de corriger l'en-tête (earthquakeinfo-infoseisme@nrcan-rncan.gc.ca, adresse trouvée sur les fiches de données ouvertes).
- **`NBC2025` = `NBC2020` = `canSHM6`** : valeurs identiques à Montréal à 3 chiffres (zone `NBC_CNB2020_Canada` ; un seul point comparé). Le CNBC 2025 semble donc reprendre l'aléa du CNBC 2020 ; l'outil précise que les valeurs 2025 restent sujettes à changement jusqu'à la publication.
- **Classes de site** : la valeur d'une classe est le **maximum** de l'aléa dans sa plage de Vs30 (règle du CNBC 2020, d'après la littérature de RNCan). La classe C donne donc plus que `vs30 = 450`. À Montréal : C → PGA 0,459 g, V450 → 0,435 g.
- **Il n'y a pas de classe « X »** : « XS » dans l'URL de l'outil veut dire *désignation par classe de site* (A à E), « XV » *par Vs30*.

## 2. Piste 1 — fenêtre « Aléa sismique CNBC 2025 » (fonctionne)

Dans `prototype-sismique.html`, un clic sur un ouvrage (11 exemples, un point bleu de la carte, une vignette de Montréal, un N° saisi) ou un point libre ouvre une fenêtre de même facture que « Profil LiDAR » (déplaçable, Échap pour fermer).

- **Graphique** : spectres Sa(T) (9 périodes, 0,05 à 10 s, échelle log) et PGA à gauche. SVG maison, sans bibliothèque. Lecture au curseur par période.
- **Classes A à E** cochables, **jusqu'à 3 Vs30 libres** (appel direct), **probabilité** au choix (2, 5, 10 % + 7 autres).
- **Tableau** PGA, PGV, Sa ; la plus forte valeur de chaque ligne en gras. **Export CSV**.
- **Classe estimée** (★) si l'ouvrage est dans la couche de Montréal.
- **Daltonisme** : palette Okabe-Ito, mais chaque classe a aussi son tiret, son marqueur (cercle, carré, triangle, losange, croix) et sa lettre au pic de la courbe. Les Vs30 libres ont leurs propres marqueurs. Le tableau et la lecture au curseur donnent les chiffres.
- **Hors ligne** : les 11 exemples et les 35 ouvrages de Montréal sont **précalculés** (aucun proxy requis). Un point libre ou un Vs30 saisi exige le proxy.

Exemples (classe C, 2 % en 50 ans) :

| Ouvrage | PGA (g) | Sa(0,2) (g) | Sa(1,0) (g) |
|---|---|---|---|
| La Malbaie, route 362 (Charlevoix) | 1,18 | 2,30 | 0,716 |
| Saguenay, route 175 | 0,590 | 1,11 | 0,345 |
| Montréal, pont Honoré-Mercier | 0,463 | 0,845 | 0,259 |
| Longueuil, route 134 Est | 0,456 | 0,833 | 0,255 |
| Québec, pont Pierre-Laporte | 0,395 | 0,752 | 0,242 |
| Gatineau, autoroute 50 | 0,349 | 0,653 | 0,208 |
| Rimouski, route 132 | 0,347 | 0,672 | 0,218 |
| Trois-Rivières, pont Laviolette | 0,307 | 0,596 | 0,204 |
| Sherbrooke, pont Hubert-C.-Cabana | 0,177 | 0,397 | 0,158 |
| Gaspé, rue de la Reine | 0,116 | 0,256 | 0,106 |
| Amos, pont Desmarais | 0,0918 | 0,211 | 0,0915 |

Effet de la classe (35 ouvrages de Montréal, classe lue dans la couche) : le PGA moyen varie peu (0,42 à 0,46 g), mais **Sa(1,0) passe de 0,152 g (B) à 0,403 g (E), soit × 2,6**. La classe de site compte surtout pour les périodes longues, donc pour les grands ponts souples.

## 3. Piste 2 — carte de PGA du Québec

### Par l'API : faisable, mais ce n'est pas la bonne voie

| Scénario | Points | Durée serveur |
|---|---|---|
| Cette démo (131 points de grille, 11 exemples, 35 ouvrages, Vs30 libres, essais) | ≈ 260 points, ≈ 50 requêtes | ≈ 1,5 min |
| Les 11 701 ouvrages, 1 classe (estimé) | 11 701 | ≈ 45 min |
| Grille de 5 km sur le Québec habité (estimé) | ≈ 25 000 | ≈ 1,6 h |

Mesure : ≈ 0,23 s par point, en lots de 10 à 25 points (10 points : 2,3 s ; 25 points : 5,7 s). Ce n'est pas « trop demandant » pour un traitement unique espacé, mais c'est inutile : l'aléa est un champ lisse et RNCan donne déjà les nœuds.

**Démo livrée** : 131 points (pas de 1°, plus fin à 0,5° dans Charlevoix–Saguenay), un seul Vs30 de 450 m/s, 2 % en 50 ans, 121 points valides (10 sont aux États-Unis). PGA de **0,042 g** (52 °N, 76 °O, Baie-James) à **1,10 g** (47,5 °N, 70 °O, Charlevoix). Vignettes à valeur imprimée + palette de clarté monotone.

### Grille officielle téléchargeable (existe)

- **Dossier public 8950 de la CGC** : *Sixth-generation seismic hazard model of Canada: grid values of mean hazard to be used with the 2020 National Building Code of Canada* (Kolaj, Halchuk et Adams, 2023). DOI : [10.4095/331497](https://doi.org/10.4095/331497). Licence : [gouvernement ouvert – Canada](https://open.canada.ca/en/open-government-licence-canada).
- Fichier : `gid_331497.zip`, **232 Mo**, via le dépôt de RNCan (OSTR) : `https://ostr-backend-prod.azure.cloud.nrcan-rncan.gc.ca/server/api/core/bitstreams/c36e469b-89ab-4ef9-a874-903def23bab4/content`.
- Contenu (lu par requêtes HTTP partielles, **sans téléchargement complet** : index du ZIP + ≈ 0,8 Mo) :
  - `AppendixB/NBCC2020_CanadaSHM6_X*.csv` : 20 fichiers (classes XA à XE, et Vs30 de 140, 160, 180, 250, 300, 360, 450, 580, 760, 910, 1100, 1500, 1600, 2000 et 3000 m/s), ≈ 53 Mo chacun (≈ 11,4 Mo compressés).
  - Colonnes : Index, Longitude, Latitude, x et y projetés (LCC), désignation, probabilité (10 valeurs par nœud), Sa(0,05 à 10), PGA, PGV.
  - `AppendixC/…Grid.csv` : **triangles** (index de 3 sommets) = maillage TIN. Les valeurs sont interpolées dans les triangles, comme le fait l'outil.
  - `AppendixD` : polygones de zones (JSON). `AppendixE` : exemples et schéma JSON. Rapport PDF et lisez-moi.
  - Nombre de nœuds : ≈ 30 000 pour tout le Canada (estimé d'après la taille des fichiers ; non vérifié).
- Les **cartes officielles** ([page](https://www.earthquakescanada.nrcan.gc.ca/hazard-alea/zoning-zonage/NBCC2020maps-en.php)) sont des **images PNG** seulement : désignation X450, 2 % en 50 ans, PGA, PGV et 9 Sa. Pas de grille sur cette page, pas de carte 2025 séparée.
- **À faire (accord requis, ≈ 11 Mo par désignation)** : télécharger par exemple XB, XC, XD, XE et X450, filtrer le Québec et interpoler les 11 701 ouvrages hors ligne en quelques secondes. Aucun appel API, aucun proxy pour la couche.

### Réponse à la question

- Une **carte de PGA du Québec par ouvrage** (11 701 points) coûte ≈ 45 min d'API ; **par grille officielle** : un téléchargement et un script.
- Le PGA dépend de la classe de site, mais peu (± 10 % à Montréal, jusqu'à ± 30 % là où l'aléa est faible) ; Sa à 1 s et plus en dépend beaucoup (× 2 à 3). Pour une carte, mieux vaut **une carte par classe de référence** (X450 comme RNCan, ou C) et, par ouvrage, la classe estimée.
- Le champ est très hétérogène : hausse locale à Charlevoix (≈ 1,1 g à X450) et Saguenay (≈ 0,55 g), Montréal ≈ 0,43 g, Outaouais et Québec ≈ 0,3 à 0,4 g ; Abitibi, Baie-James et Gaspésie faibles (< 0,12 g).

## 4. Piste 3 — classes de site de Montréal (reconstituée)

### Source trouvée

L'image est la **figure 10** de : Rosset P., Takahashi A., Chouinard L. (2023). *Vs30 Mapping of the Greater Montreal Region Using Multiple Data Sources*. **Geosciences 13(9):256**, [doi:10.3390/geosciences13090256](https://doi.org/10.3390/geosciences13090256). Université McGill. Accès libre.

- Méthode des auteurs : 229 387 sites de Vs30 (forages, bruit ambiant HVSR, sismique réfraction), interpolés par pondération inverse de la distance (p = 4) sur une grille, puis regroupés en classes A à E. Les zones de roc affleurant sont mises en classe A.
- Étendue : 45,229 à 45,984 °N, 74,268 à 73,062 °O (Communauté métropolitaine de Montréal).
- **Droit d'auteur** : l'article est sous licence **CC BY 4.0** (texte du PDF). La figure peut être reprise **avec attribution**, ce qui est plus permissif que « usage interne ». La grille reconstituée est une dérivée : citer l'article et dire qu'elle est reconstituée.
- **Données d'origine** : « disponibles sur demande » (déclaration de l'article). Contact : Philippe Rosset, philippe.rosset@affiliate.mcgill.ca. **À demander** : la vraie grille (301 × 189 cellules) vaudra mieux que ma reconstitution.
- Je n'ai pas trouvé la source exacte de l'article du *Montreal Gazette* (le site refuse les requêtes automatisées) ; l'étude scientifique ci-dessus correspond à la figure, mot pour mot (légende, étendue, points Vs et HVSR).

### Méthode (`classes_depuis_image.py`)

1. **Géoréférence par les graduations du cadre** (l'image fait 1039 × 723 px, pas 1050). Les alternances noir/blanc du cadre tombent aux graduations, espacées de 0,25° : lon −74,25 / −74,00 / −73,75 / −73,50 / −73,25 (les étiquettes arrondies « −74,3 », « −73,8 »… cachent les quarts de degré), lat 46,00 / 45,75 / 45,50 / 45,25. Échelle : **796 px/° en longitude et 779 px/° en latitude**.
2. **Classement par pixel** : couleur de la légende la plus proche (A vert, B bleu, C jaune, D rose, E rouge), en tolérant l'assombrissement par les traits fins. Eau, fond, traits, points de données, légende, flèche et échelle sont ignorés.
3. **Maille native** : l'analyse périodique des bords de blocs donne **0,004°** (3,18 px en x, 3,11 px en y), soit **≈ 310 × 445 m**. L'article parle de « 0,01° » dans le résumé, mais de 300 m × 400 m dans le texte ; la mesure confirme les 300 × 400 m. Chaque cellule reçoit la classe majoritaire de ses pixels.
4. **Comblement** : les cellules masquées par un point ou un trait épais (2 132, soit 6,5 % des 32 756 cellules classées) prennent le vote de leurs 8 voisines. Les cellules d'eau restent vides.
5. **Sorties** : `cache/grille_classes_site_mtl.json` (308 × 212 cellules, chaînes de caractères « 0ABCDE »), `couche_classes_site_mtl.png` (transparent, 4 px par cellule) et `couche_classes_site_mtl.limites.json` (bornes : O −74,2777, E −73,0457, S 45,2275, N 46,0755).

Palette : **clarté décroissante de A à E** (jaune pâle, vert menthe, turquoise, bleu, indigo ; ColorBrewer YlGnBu) = lisible en daltonisme, car les classes sont ordonnées. Doublée de **motifs** (points épars, lignes horizontales, diagonales, hachures croisées, points denses) et de **lettres** dans la légende. Curseur d'opacité et case « motifs ».

### Précision (honnête)

- **Maille de 310 × 445 m** : c'est la vraie résolution de l'étude ; un pixel de l'image fait ≈ 98 m (est-ouest) × 143 m (nord-sud). Aucun détail sous la maille.
- **Géoréférence** : ± 0,5 px sur les graduations, soit ≈ ± 50 à 70 m, plus la phase de grille mesurée : **± 100 m** au total, à peu près un tiers de cellule.
- **Reprojection** : la grille recalée sur l'image redonne la même classe dans **97,5 %** des pixels classés des deux côtés. Environ 4 % des pixels classés de l'image tombent hors d'une cellule retenue (bordure et symboles).
- **Valeur du produit** : c'est une **estimation par interpolation** (les auteurs rappellent que les zones sans mesure sont à vérifier). Les classes ne remplacent pas une mesure de Vs30 au site, que le CNBC permet d'utiliser directement.
- **Dans la couche** : 1 512 des 11 701 ouvrages du MTMD (4 en A, 531 en B, 562 en C, 278 en D, 137 en E).
- Le prototype affiche la classe d'un point et l'aléa à cette classe pour **35 ouvrages** (3 en A, 8 par classe de B à E).

## 5. Les classes de site pour le reste du Québec

### Ce qui existe (URL vérifiées)

| Région ou source | Contenu | Accès |
|---|---|---|
| **Grand Montréal** | grille de Vs30 et classes (Rosset et al. 2023, ci-dessus) | CC BY ; données sur demande |
| **Province de Québec, par géologie** | Rosset P., Elrawy A., Nadarajah S., Chouinard L. (2025), *Vs30 Derived from Geology: An Attempt in the Province of Quebec, Canada*, **Geotechnics 5(2):24**, [doi:10.3390/geotechnics5020024](https://doi.org/10.3390/geotechnics5020024). Table dépôt de surface → Vs30 → classe, et **carte provinciale de classes** (fig. 10) | CC BY 4.0 ; la table 3 est dans l'article ; la carte n'est qu'une figure |
| **Dépôts de surface du Québec (sud)** | polygones de dépôts (code, épaisseur), MFFP, inventaire écoforestier | [Données Québec « Dépôt de surface »](https://www.donneesquebec.ca/recherche/dataset/depots-de-surface), CC-BY ; index des feuillets 1/250 000 : [URL_Depot.csv](https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/DONNEES_FOR_ECO_SUD/Depots_surface/03-Telechargement/URL_Depot.csv) ; dictionnaire des codes : [DICTIONNAIRE_DEPOT_SURFACE.xls](https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/DONNEES_FOR_ECO_SUD/Depots_surface/01-Documentation/DICTIONNAIRE_DEPOT_SURFACE.xls) |
| **Dépôts de surface du Nord** | idem, nord du Québec | [Données Québec](https://www.donneesquebec.ca/recherche/dataset/carte-des-depots-de-surface-du-nord-quebecois), CC-BY |
| **Île de Montréal** | géologie et épaisseur des dépôts meubles | [Données Québec / Ville de Montréal](https://www.donneesquebec.ca/recherche/dataset/vmtl-geologie-des-depots-meubles), licence gouvernement ouvert |
| **Vs30 mondial par pente** | grille de 30 secondes d'arc (≈ 0,9 km), partout, hors glaciation mal | [USGS Vs30](https://earthquake.usgs.gov/data/vs30/) (Heath et al. 2020 ; Wald et Allen 2007) ; ZIP de 631 Mo |
| **Régions avec microzonage** | Québec (en classes), Saguenay (Salsabili et al. 2021), Ottawa-Gatineau (Motazedian et al. ; Hunter et al. 2009, Dossier public de la CGC), vallée du Saint-Laurent (Nastev et al. 2016, grille de Vs30) | cités dans Rosset 2025 ; **données obtenues « sur demande »** par les auteurs, aucune URL de téléchargement trouvée |

À noter : SIGÉOM (géologie du Québec, MRNF) n'a pas répondu à mes essais (erreur 500) ; je ne le cite donc pas comme URL vérifiée.

### Ce que montre Rosset et al. (2025)

- La **pente topographique** (USGS) concorde avec les microzonages à seulement **18 à 36 %** des classes dans cinq régions du Québec. Elle **sous-estime** généralement le Vs30 dans les régions glaciaires. À réserver au nord, sans autre donnée.
- La **géologie de surface** fait mieux : les auteurs calibrent le Vs30 moyen par type de dépôt avec les microzonages de Montréal, Saguenay et Gatineau (Table 3). Résumé de la table 3 : roc (R) → **A** ; till (T), fluvio-glaciaire (Go, Gs, Gx), lacs (L), alluvions actuelles (Ap), glaciomarin côtier (MGb) et glaciolacustre profond (LGa) → **B** ; éoliens (Ed), organiques (O), dépôts de pente (C), alluvions indifférenciées (A), **glaciomarin d'eau profonde (MGa)** et deltaïque (MGd), glaciolacustre côtier ou deltaïque (LGb, LGd) → **C** ; glissements de terrain (Cg) → **D**. **Aucun dépôt n'est classé E** : la classe E ne peut venir que d'une règle d'épaisseur ou d'un microzonage.
- Anomalie à signaler : leur table 3 donne pour le till (T) un Vs30 moyen pondéré de ≈ 1 185 m/s (classe B), alors que leur résumé de la figure 9 le range en classe A. Il faut trancher avant de réutiliser la table.
- Ils proposent eux-mêmes d'**affiner avec des cartes à 1/25 000** et avec **l'épaisseur jusqu'au roc** (loi Vs30 = a × Z^b, R² de 0,32 à 0,56 selon le dépôt).

### Méthode réaliste proposée

1. **Dépôts de surface** (MFFP, polygones) → **classe de site** par la table de Rosset et al. 2025 (table 3), en gardant l'**épaisseur** quand elle existe (classe D ou E pour les argiles épaisses).
2. **Superposer les microzonages quand on les a** (Montréal : grille de 2023 ; Québec, Saguenay, Gatineau : obtenir les données auprès des auteurs ou des villes). Ils l'emportent sur la déduction.
3. **Hors couverture** (nord, sans carte de dépôts) : USGS Vs30 par pente, **marqué « faible confiance »**.
4. **Pour chaque ouvrage** : classe probable, **plage plausible** (± 1 classe) et niveau de confiance ; l'aléa est calculé pour la classe **la plus défavorable** de la plage. Un sondage ou une mesure de Vs30 au site remplace tout cela.
5. **Validation** : comparer la carte déduite aux microzonages connus (Montréal surtout) et publier le taux de concordance.

Effort : 4 à 6 jours (jointure spatiale des feuillets, correspondance des codes, épaisseur, validation, couche de l'atlas). Beaucoup moins si les auteurs fournissent la carte provinciale.

## 6. CSA S6 et CNBC 2025

- Les ponts relèvent de la **CSA S6**, pas du CNBC. La [CSA S6:25](https://www.csagroup.org/store/product/CSA_S6:25/) est la **13e édition** (2025). Les sources trouvées indiquent que la section 4 (séismes) a été **réorganisée**, avec quatre approches sous un cadre de **calcul basé sur la performance**.
- **Je n'ai pas trouvé de source fiable sur les valeurs d'aléa exactes que la S6:25 retient** (CanSHM6, CNBC 2020 ou autre) ni sur sa définition des classes de site. **C'est à vérifier dans le texte de la norme** (section 4 de la norme).
- À valider avec les ingénieurs du MTMD : si la S6:25 reprend l'aléa du CNBC 2020 avec les mêmes classes A à E, la fenêtre actuelle suffit ; sinon, il faut ajuster les probabilités affichées et la désignation de site.
- Le prototype affiche donc **des valeurs de l'outil du CNBC**, pas des valeurs de calcul d'un pont. Ce n'est pas à utiliser en conception.

## 7. Recommandation d'intégration

Le CNBC 2025 semble reprendre l'aléa du CNBC 2020 (valeurs identiques à Montréal, vérifié sur un seul point). L'atlas gagne à ajouter ces données **à deux conditions** : vérifier le lien avec la S6:25 et afficher l'incertitude sur la classe de site.

| Étape | Contenu | Effort |
|---|---|---|
| 1. Fenêtre « Aléa sismique CNBC 2025 » | reprendre la fenêtre du prototype dans l'atlas ; données **précalculées** à partir de la grille officielle (5 classes × 3 probabilités par ouvrage, JSON par lots) | 2 à 3 jours |
| 2. Appels en direct (Vs30 libre) | petit proxy serverless (30 lignes) ou omission du champ en v1 | 0,5 à 1 jour |
| 3. Couche de PGA du Québec | grille officielle X450 ou classe C, interpolée en tuiles ou en grille légère | 1 à 2 jours |
| 4. Couche des classes de Montréal | PNG et grille déjà prêts ; remplacer par la grille d'origine si Rosset la fournit | 0,5 jour |
| 5. Classes de site du Québec | méthode du § 5, avec niveau de confiance | 4 à 6 jours |
| 6. Alignement S6 | confirmer l'aléa et les classes de la S6:25 avec le MTMD | 1 à 2 jours (surtout de la lecture) |

Ordre conseillé : **6 → 1 → 4 → 3 → 2 → 5**. Si l'on n'a qu'une journée : la fenêtre (étape 1) avec les valeurs précalculées donne déjà un spectre par ouvrage pour les cinq classes.

## 8. Limites et points à vérifier

- Valeurs de l'outil CNBC 2025 **préliminaires** jusqu'à la publication du code.
- Le téléchargement de la grille officielle n'a **pas** été fait (accord à donner) ; le nombre de nœuds (≈ 30 000) est estimé.
- Grille de Montréal : reconstituée d'une image, **maille 0,004°**, ± 100 m ; 6,5 % de cellules comblées. Demander les données d'origine.
- Lien S6:25 ↔ CNBC 2025 : **non vérifié**.
- La table dépôt → classe de Rosset 2025 est calibrée sur trois régions ; l'incertitude de classe reste d'au moins une classe.
- Les 131 points de la grille de démo sont trop espacés pour une carte publiée (l'étape 3 les remplace).
- Appels à l'API : ≈ 260 points en ≈ 50 requêtes, espacés d'au moins 0,5 s (cache local dans `cache/`).

## 9. Fichiers

| Fichier | Rôle |
|---|---|
| `prototypes/sismique/prototype-sismique.html` | prototype (Leaflet 1.9.4 depuis cdnjs ; lit `../../data/structures.js`) |
| `prototypes/sismique/donnees_sismique.js` | résultats précalculés + grille de classes (260 Ko) |
| `prototypes/sismique/precalcul_sismique.py` | appels à l'API avec cache, budget de 300 points, export JS |
| `prototypes/sismique/proxy_api.py` | proxy local (port 8766) pour les appels en direct |
| `prototypes/sismique/classes_depuis_image.py` | extraction de la grille A–E de la figure 10 |
| `prototypes/sismique/couche_classes_site_mtl.png`, `…limites.json` | couche raster transparente et ses bornes |
| `prototypes/sismique/cache/` | réponses de l'API, figure source, grille JSON |
