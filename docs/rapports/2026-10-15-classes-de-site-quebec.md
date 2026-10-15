# Classes de site sismique pour tout le Québec (v0.6.0)

Date : 2026-10-15 · Module : `etl/sismique.py`, `js/sismique.js` · Tests : `tests/test_sismique.py`, `tests/js/sismique_smoke.mjs`

## En bref

- Nouvelle couche **« Classes de site sismique »** pour tout le Québec, tirée de Rosset P., Elrawy A., Nadarajah S.,
  Chouinard L. (2025), « Vs30 Derived from Geology: An Attempt in the Province of Quebec, Canada », *Geotechnics*
  5(2):24, doi:10.3390/geotechnics5020024 (CC BY 4.0), <https://www.mdpi.com/2673-7094/5/2/24>.
- **Méthode refaite à partir des données sources** (et non à partir de la figure) : tableau 3 de l'article appliqué à la
  carte des dépôts de surface du SIGEOM, que l'article utilise comme intrant. La figure 10 sert seulement à la **vérification** :
  **99,5 % d'accord** pixel à pixel sur 3,47 millions de pixels.
- **Classe estimée par ouvrage** : 11 390 des 11 701 structures (97,3 %) : A 1 029, B 5 120, C 5 229, D 12, E 0.
- **PGA** (classe C, 2 % en 50 ans) étendu à **tout le territoire québécois** (avant : 50 km autour des structures).
- Fenêtre « Aléa sismique » : axe des périodes **linéaire** (0 à 10 s), étoile ★ sur la nouvelle classe, tableau de synthèse compact en tête.
- La couche de Montréal (Rosset et al. 2023) est **retirée** : la carte du Québec couvre Montréal (voir les limites ci-dessous).

## 1. Recherche des données sources

| Piste | Résultat |
|---|---|
| Énoncé de disponibilité des données | « The original contributions presented in this study are included in the article » : aucun jeu de données déposé |
| Matériel supplémentaire, Zenodo, figshare, GitHub | Aucun |
| Intrant de la méthode | Réf. [45] : SIGEOM, *Géologie du Quaternaire* (MRNF), données ouvertes, CC BY 4.0 → **utilisable** |
| ZIP officiel du SIGEOM (`SIGEOM_QC_Geologie_du_Quaternaire_SHP.zip`, 1,5 Go) | Lu par requêtes `Range` (répertoire central, DBF) ; débit mesuré **≈ 17 Ko/s** : 242 Mo compressés de géométrie = ≈ 4 h. Abandonné |
| WMS du MRNF (`servicesvectoriels.atlas.gouv.qc.ca/IDS_SGM_WMS`) | **Retenu** : couche `SGM:Zones_morpho_sedimentologiques_qc`, rendue sans lissage (`FORMAT_OPTIONS=antialias:none`) au style officiel. Les styles SLD personnalisés sont refusés (404) |
| WFS du MRNF (même hôte) | Sert à relever la couleur officielle (`COUL_REMPL_HEXA`) et la description de chaque code |

**Quelle couche ?** L'article cite le fichier complet, qui contient deux couches de polygones : la couche détaillée
(codes Tm, Tc, Ri, At…) et la couche **générale** (`Zone morphosedimentologique generale`). Seule la couche générale
utilise exactement les codes du tableau 3 (T, R, A, Ap, MGa…). C'est donc elle que l'article a utilisée, et l'accord de
99,5 % avec la figure 10 le confirme.

## 2. Méthode (celle de l'article)

1. **Tableau 3** : chaque code de dépôt reçoit la classe du CNBC de son Vs30 moyen pondéré (moyenne de Gatineau,
   Saguenay et Grand Montréal, plus la vallée du Saint-Laurent pondérée à 50 %). Les 21 codes et leurs Vs30 sont dans
   `TABLEAU3` (testés : chaque classe correspond au Vs30 publié). D : glissements (Cg) seulement ; A : roc (R) seulement.
2. **Q de l'article = Qa du SIGEOM** : le code Q n'existe plus dans la couche ; Qa a exactement la même description
   (« Formation quaternaire ancienne altérée ») → B (1 416 m/s).
3. **Codes absents du tableau** : Qf (felsenmeer), Ce (éboulis), Gxi (juxtaglaciaire interlobaire), H (anthropique),
   Ac (cône alluvial) → **inconnus** (gris « Unknown » de la figure 10 ; transparents ici). Ils couvrent 0,9 % du territoire.
4. **Eau** : dans la carte générale, les lacs eux-mêmes portent le code **L** (« sédiment lacustre actuel »). La figure 10
   les recouvre d'une couche hydrographique bleu clair : sur 3,47 millions de pixels A à D de la figure, **42** seulement
   tombent sur un L, alors que L est le premier code sous le bleu (106 118 pixels). On suit donc la figure : **L = eau**,
   sans classe et transparent (constante `CODES_EAU`). Les rivières sont des trous de la couche (aucun polygone). Le fleuve
   en amont de Québec est codé Ap (alluvion actuelle, B), comme dans les données sources.
5. **Grille** : lat/lon, 44,9 à 62,7 °N et 79,8 à 57,0 °O, maille **0,002° × 0,003°** (≈ 222 × 214 m à 50 °N),
   7 600 × 8 900 cellules. Le serveur WMS rend 20 tuiles de 2 048 px dont les pixels coïncident avec les cellules.
   26 couleurs officielles, **toutes distinctes** ; **0 pixel de couleur inconnue** après décodage.
6. **Versionnée** : `etl/donnees/classes_site_qc.png` (PNG à palette, indice = code de dépôt, couleurs officielles du
   SIGEOM, 4,2 Mo) + `classes_site_qc.json` (géométrie, liste des codes, tableau 3, alias, comptes). Sans réseau,
   `python -m etl.sismique --no-fetch` relit cette grille si les tuiles brutes (`data/raw/sismique/sigeom/wms/`) manquent.
7. **Raster de la carte** `data/sismique/classes-qc.png` : 3 200 × 4 314 px, lignes Web Mercator (comme les autres
   images, pour `L.imageOverlay`), classe **majoritaire** des cellules sous chaque pixel (≈ 2 × 1 à 2 cellules), 0,96 Mo.
   Couleurs de la figure 10, relevées sur les pastilles de sa légende (médiane, écart type < 2,2) : A `#36bf29`, B `#2306ff`,
   C `#e4ff04`, D `#cf15d8`. L'article n'a pas de classe E.

Part du territoire cartographié : A 23,6 % · B 58,5 % · C 9,7 % · D < 0,01 % (2 085 cellules) · eau (L) 7,3 % · non classé 0,9 %.

## 3. Vérification contre la figure 10 (géoréférencement)

La figure 10 (Montréal–Québec–Saguenay, ≈ 45 à 49,6 °N, 76,6 à 69,9 °O) est extraite du PDF (3 507 × 2 480 px) puis
géoréférencée à partir des **graduations du cadre** : chaque degré correspond à un passage noir/blanc des barres.
On compte 7 graduations en longitude (barres nord et sud) et 5 en latitude (est et ouest), soit 24 points. Le modèle
est `pixel = a + b·degré ± e`, où ± e absorbe l'épaisseur du trait des segments noirs.

| Axe | Pente | Terme de trait | Résidus RMS | Résidu max |
|---|---|---|---|---|
| x (longitude) | 479,295 px/° | ± 1,81 px | **0,080 px** | 0,137 px |
| y (latitude)  | 479,317 px/° | ± 1,84 px | **0,093 px** | 0,114 px |

- Les deux pentes sont égales à 0,005 % près : la figure est en **plate carrée** (EPSG:4326/4269), sans cisaillement mesurable.
- 0,1 px ≈ 0,0002° ≈ 20 m : l'erreur de géoréférencement est négligeable devant la résolution de la figure elle-même
  (1 px = 0,0021° ≈ 160 × 230 m).
- **Accord par classe**, sur les pixels A à D de la figure, hors légende, échelle et flèche du nord : **99,5 %**.
  - A : 99,6 % ; B : 99,6 % ; C : 99,2 % ; D : 96,8 % (727 sur 751 pixels).
  - Le reste se trouve au contact de l'eau et des contours.
- **Décalage horizontal** de la grille par rapport à la figure → accord : −3 px 92,0 %, −2 px 96,0 %, −1 px 98,7 %,
  **0 px 99,5 %**, +1 px 98,8 %, +2 px 96,4 %, +3 px 92,5 %. Le maximum à 0 confirme le géoréférencement.
- Repères : les deux petites taches D de la figure (Saguenay, à l'est du Lac Saint-Jean, et Outaouais) tombent à 97 %
  sur des glissements Cg de la grille. Le C des argiles de la mer de Champlain suit le Saint-Laurent ; le Lac Saint-Jean
  est de l'eau (L) dans les deux cartes.

Commande de vérification : `python -m etl.sismique --figure data/raw/sismique/article/geotechnics-05-00024.pdf`.
Le PDF provient de mdpi-res.com (13,9 Mo) ; la page HTML de MDPI répond 403 aux robots.

## 4. Classe par structure

`data/classes-site.js` : `window.PQ_CLASSE_SITE = {"_": {"source", "url", "generated"}, "<n°>": "B", …}`. Il contient
11 390 entrées (0,14 Mo) ; le n° est celui de `num_dossr` dans `data/ponts.sqlite`, comme dans `data/structures.js`.
La même classe est recopiée en tête (`k`) de chaque entrée des 120 lots `data/sismique/s-XX.js`. Les 11 701 entrées ont
été vérifiées : aucun écart entre `k` et `classes-site.js`, et les 165 valeurs d'aléa sont inchangées.

| Classe | Structures |
|---|---|
| A (roc dur) | 1 029 |
| B (roc) | 5 120 |
| C (sol très dense, roc mou) | 5 229 |
| D (sol raide) | 12 |
| E | 0 |
| **Sans classe** | **311** |

Structures sans classe :
- 248 tombent dans un trou de la couche (rivière), toutes à une cellule (≈ 220 m) d'un polygone ;
- 60 tombent dans un lac (L) ;
- 3 tombent sur un code non classé (Qf, H, Gxi).

Codes de dépôt les plus fréquents sous les structures : T 2 654, A 2 067, MGa 2 034, MGb 1 205, R 1 029.

**Comparaison avec l'ancienne grille de Montréal** (Rosset et al. 2023, microzonage à partir de mesures de Vs30) :
sur les 1 512 ouvrages qui y avaient une classe, **509 (34 %)** gardent la même. La carte géologique régionale donne
surtout B et C là où le microzonage donnait D ou E. Par exemple, sur 278 anciens D, 264 deviennent C, 13 deviennent B
et 1 n'a plus de classe ; sur 137 anciens E, 132 deviennent C.

## 5. Couche PGA pour toute la province

Avant, le raster était masqué à 50 km des structures. Il couvre maintenant le territoire québécois : cellules couvertes
par la carte du SIGEOM, lacs intérieurs bouchés, plus 2 px de marge. Cela donne 1 400 × 1 887 px pour 44,9 à 62,7 °N
et 79,8 à 57,0 °O ; le Labrador et la mer sont exclus. La palette, les seuils et le format sont inchangés.
`avertissement` mis à jour. Les deux couches sont séparées et superposables (`pga` et `classes` dans `data/couche-sismique.js`).

## 6. Fenêtre « Aléa sismique » (`js/sismique.js`)

- **Axe des périodes linéaire**, 0 à 10 s, graduations chaque seconde (chaque 2 s sur mobile). Le PGA garde sa colonne à gauche.
  Les périodes courtes (0,05 à 0,5 s) sont serrées sur ≈ 5 % de la largeur : c'est le prix de l'échelle linéaire ;
  le tableau de valeurs reste complet.
- **Étoile ★** : classe de `window.PQ_CLASSE_SITE` si la page l'a chargé, sinon `k` du lot. Les deux viennent de la même source.
- **Tableau de synthèse** compact en tête : classe estimée (avec lien vers l'article), probabilité et période de
  retour, et PGA, Sa(0,2 s), Sa(1 s), PGV à la classe estimée (ou à la classe C de référence si la classe est inconnue).
  Il remplace la pastille et la ligne de texte d'avant ; sur mobile, chaque ligne s'empile.
- Note et source mises à jour (Rosset et al. 2025 + SIGEOM). Vérifié dans la page réelle (ouvrage 13247A : « C ★ »).

## 7. Limites

- **Échelle régionale** : une classe par type de dépôt de la carte **générale**, à la maille de 220 m. Ce n'est pas une
  étude de site. L'écart type du Vs30 par dépôt va de 127 à 974 m/s (tableau 3), soit souvent ± 1 classe ; l'article
  l'indique lui-même (« uncertainty… relatively large (one site class) »).
- La méthode **sous-estime les sols mous** :
  - D n'existe que pour les glissements (Cg) ; E n'existe pas ;
  - à Montréal, le microzonage de 2023 était plus fin (34 % d'accord seulement, voir § 4). Si l'on préfère ce microzonage
    pour Montréal, la grille et son code sont dans l'historique git (commit f5c6743, `etl/donnees/classes_site_mtl.json`).
- **Eau** : décision « L = eau » tirée de la figure (§ 2.4). Un pont sur un lac ou une rivière n'a donc pas de classe,
  alors que ses appuis sont dans les dépôts du fond ou des rives.
- La couleur → code dépend du style officiel du WMS (relevé le 2026-10-15). Si le MRNF change une couleur, le
  décodage signale des pixels « inconnus » dans le journal de l'ETL.
- Les couleurs de l'article (vert, bleu, jaune, magenta) ne sont **pas** adaptées au daltonisme ; elles sont gardées à la
  demande de l'utilisateur. Le libellé de chaque classe reste lisible dans la légende et la fenêtre.
- Table 3 : les Vs30 de la région de Québec (en classes) ne sont pas dans la moyenne pondérée, comme dans l'article.

## 8. Fichiers

- Modifiés : `etl/sismique.py`, `js/sismique.js`, `data/couche-sismique.js` (clés `pga` et `classes` ; `mtl` retirée),
  `data/sismique/s-XX.js` (k), `data/sismique/meta.js`, `data/sismique/pga-c-2pc.png`, `tests/test_sismique.py`,
  `tests/js/sismique_smoke.mjs`, `docs/TECHNIQUE.md` (ligne sismique).
- Nouveaux : `data/classes-site.js`, `data/sismique/classes-qc.png`, `etl/donnees/classes_site_qc.png`,
  `etl/donnees/classes_site_qc.json`, ce rapport.
- Retirés : `data/sismique/classes-mtl.png`, `etl/donnees/classes_site_mtl.json`.
- Brut (non versionné) : `data/raw/sismique/sigeom/` (20 tuiles WMS, DBF et métadonnées du SIGEOM, couleurs WFS),
  `data/raw/sismique/article/` (PDF de l'article).

Tests : `python -m pytest -q tests/test_sismique.py` → 37 réussis (dont les tests sur données réelles) ;
`node tests/js/sismique_smoke.mjs` → 8 réussis.
