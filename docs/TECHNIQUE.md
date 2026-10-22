# QuickerAtlasOA — documentation technique (données, ETL, couches)

Copie modernisée et enrichie de l'[inventaire des structures](https://www.transports.gouv.qc.ca/fr/projets-infrastructures/structures/Pages/inventaires-structures.aspx)
du ministère des Transports et de la Mobilité durable du Québec : base SQLite consolidée et visualiseur cartographique.
Plan complet : [PLAN_DE_MATCH.md](../PLAN_DE_MATCH.md).

## Mise à jour des données

```bash
pip install -r requirements.txt
python -m etl update            # toutes les sources (~2 min), consolidation, export web, couches de la carte
python -m etl update --only wfs # une source
python -m etl update --no-fetch # reconsolider sans télécharger
python -m etl report            # rapport de jointure
python -m etl export            # régénère data/structures.js et data/details.js
python -m etl couches [--no-fetch]  # régénère seulement les couches (RTSS, rail, géotechnique, débits, villes)
python -m etl fiches --limit 50  # (optionnel) crawl des fiches HTML, ~1 req/s — inutile en temps normal
python -m pytest -q tests
```

## Sources

| Source | Table | Accès |
|---|---|---|
| [WFS « Structure »](https://donneesquebec.ca/recherche/dataset/structure) (Données Québec, CC-BY 4.0) | `wfs_structure` | 1 requête CSV |
| Liste de l'outil *Inventaire et inspection des structures* (Oracle APEX) | `apex_structure` | POST de recherche + pages de 500 lignes, ×3 (sans filtre, limitation de hauteur, limitation de poids) |
| Répertoire des hauteurs libres (service OData) | `hauteur_libre` | 1 requête JSON |
| Coordonnées GPS (CSV de l'outil APEX) | `gps_point` | 1 requête |
| [Service OData du MTMD](https://ws.diffusion.transports.gouv.qc.ca/odata/$metadata) `Structures_StructuresTabBord` | `structure_detail` | 1 requête JSON (67 champs : dimensions complètes, biais, DJMA, % camion, classes de route, inspections) |
| OData `LimitesDeCharge` | `limite_poids` | 1 requête (panneaux et tonnages par classe de véhicule) |
| OData `HauteurLibreDetail` | `hauteur_libre_detail` | 1 requête (hauteurs mesurées en 5 points par direction) |

Toutes les requêtes passent par `etl/net.py` (User-Agent identifié, ≥ 1 s entre deux requêtes vers un même hôte).
La table consolidée est `structure`.

### Journal des changements (P5)

À chaque `python -m etl update`, `merge.journaliser` compare le nouvel état au précédent et écrit les écarts dans
`changement` : ajouts et retraits de structures, ICG, IAS (fermetures), limitations, travaux prévus, type, réseau,
hauteur libre, ainsi que la date de **dernière inspection générale** (champ suivi de `structure_detail`, comparé avant
remplacement). Chaque consolidation est inscrite dans `source_run` (`source = 'consolidation'`, nombre d'écarts en note).
`build.export_journal` en tire `data/journal.js` (730 derniers jours), lu par le panneau « Quoi de neuf » et le filtre
« Suivi » du visualiseur. Le run complet prend ~1 min (+ ~45 s pour les couches) : aucune mise à jour incrémentale
n'est nécessaire.

### Couches de la carte (chargées à la demande)

| Couche | Module | Fichier | Source (WFS du MTMD, Données Québec, CC-BY 4.0) |
|---|---|---|---|
| Réseau routier RTSS (par classe) | `etl/reseaux.py` | `data/couche-rtss.js` (~0,9 Mo) | `ms:bgr_v_sous_route_res_sup_act` |
| Réseau ferroviaire (par usage / état) | `etl/reseaux.py` | `data/couche-rail.js` (~0,3 Mo) | `ms:reseau_chfer_qc` |
| Sondages géotechniques (+ BDG) | `etl/geotech.py` | `data/couche-geotech.js` (~1,1 Mo) | `ms:site_inv_geotech_p`, `ms:site_inv_geotech_bdg_p` |
| Débits de circulation sur / sous chaque structure, 2016–2025 | `etl/debits.py` | `data/debits.js` (~1,5 Mo) | `ms:circulation_routier` |
| Structures routières de la Ville de Montréal (édition 2021, avec ICG de la Ville) | `etl/villes.py` | `data/couche-mtl.js` (~0,3 Mo) + table `ouvrage_ville` | Données ouvertes de la Ville de Montréal, « Inventaire des actifs de voirie – Structures routières » (CC-BY 4.0) |
| Ouvrages routiers de la Ville de Sherbrooke | `etl/villes.py` | `data/couche-sherbrooke.js` (~3 Ko) + table `ouvrage_ville` | Données ouvertes de la Ville de Sherbrooke, « Ouvrages routiers » (CC-BY 4.0) |
| Ponts ferroviaires (v0.5.6) : 1 314 ponts (CN 628, CPKC 268, autres 418), longueur de la géométrie, nom OSM s'il existe | `etl/reseaux.py` | champ `ponts` de `data/couche-rail.js` (+58 Ko) | `ms:reseau_chfer_qc` (`typstruc`) ; noms : OpenStreetMap (ODbL) |
| Autres ponts hors MTMD (v0.5.6 ; « ponts forestiers » jusqu’à la v0.6.1) : 4 812 points à plus de 30 m d'un ouvrage du MTMD | `etl/forestiers.py` | `data/couche-forestiers.js` (~0,2 Mo) | AQréseau+ (MRNF), couches « Pont ouvert / inconnu / fermé » (CC-BY 4.0) ; requêtes par `curl` (le serveur coupe `requests`) |
| Aléa sismique (v0.6.1) : PGA classe C 2 %/50 ans (image, tout le Québec) + classes de site du Québec (image, couche séparée) + microzonage de Montréal 2023 au-dessus (prioritaire) ; les trois images sont transparentes sur l'eau (masque GRHQ `etl/donnees/eau_qc.png`) ; valeurs par ouvrage, 5 classes × 2/5/10 % × 11 mesures ; classe de site estimée par ouvrage | `etl/sismique.py` | `data/couche-sismique.js`, `data/sismique/*.png`, `data/sismique/s-XX.js` (120 lots, ~80 Ko chacun, 9,8 Mo en tout), `data/classes-site.js` (11 401 ouvrages, dont 1 512 classés par la grille de Montréal, 0,15 Mo) ; grilles versionnées `etl/donnees/classes_site_qc.{png,json}`, `classes_site_mtl.json`, `eau_qc.png` | Grille officielle CanSHM6, CGC Dossier public 8950 (Licence du gouvernement ouvert – Canada), lue par requêtes HTTP partielles (~58 Mo sur 232) ; classes : tableau 3 de Rosset et al. 2025 (Geotechnics 5(2):24, CC BY 4.0) appliqué aux dépôts de surface du SIGEOM (MRNF, CC BY 4.0, WMS, maille ≈ 220 m) ; Montréal : Rosset et al. 2023 (Geosciences 13(9):256, CC BY 4.0) ; eau : GRHQ simple (MRNF, WMS) |
| Cours d'eau (v0.5.6, activée par défaut) | — | tuiles WMS, rien à héberger | GRHQ simple (MRNF) |
| Zones de dégel (v0.6.5) : zones 1, 2 et 3 et dates officielles de la dernière période de dégel ; contours simplifiés (Douglas-Peucker 150 m, îlots < 0,5 km² omis, 1e-4 degré) ; canevas propre sous les réseaux, non cliquable ; une seule couche à la fois parmi PGA, classes de site et dégel | `etl/degel.py` | `data/couche-degel.js` (~0,16 Mo) | WFS du MTMD `ms:zone_degel` (jeu « Zone de dégel » de Données Québec, CC BY 4.0) |

Lignes simplifiées (Douglas-Peucker, 10 m) et encodées en entiers delta. Les débits sont appariés par n° de route
et distance à la structure (`approx` = repli géométrique sans concordance de n°, bit 1 = portée, bit 2 = franchie), avec
deux garde-fous depuis la v0.5.2 : le DJMA de la section doit être cohérent avec celui de la fiche (facteur ≤ 8 si le n°
concorde, ≤ 3 en repli, et pas de repli sans DJMA dans la fiche) ; « Accès route 175 » ou « Chemin de desserte (A-20) »
ne désignent pas la route citée. Les classeurs .xlsx de la source ne sont plus proposés (source citée dans la fiche).
Audit v0.6.4 (`docs/rapports/2026-10-20-audit-debits.md`) : le n° d'une section est celui de son RTSS seulement (le
libellé de début nomme sa limite, une route croisée) ; une section n'est jamais à la fois portée et franchie ; un n°
commun aux deux voies désigne la portée ; bretelles, raccordements, échangeurs et voies de service ne reçoivent pas les
débits de l'autoroute voisine ; parmi les sections portées retenues, la plus cohérente avec le DJMA de la fiche est
affichée, avec une note quand elle diffère de la fiche (souvent : un sens dans la fiche, deux sens dans la section).
Les ouvrages des villes situés à moins de 30 m d'une structure du MTMD de même famille sont marqués `doublon` : le
visualiseur ne les compte qu'une fois, sous leur n° du MTMD. Le RSSCE (réseau stratégique en soutien
au commerce extérieur) n'est publié nulle part en données ouvertes : depuis la v0.5.5, la couche « RSSCE estimé » est
tirée de `couche-rtss.js` (bit 1 du champ `flag`, `reseaux.drapeau_rssce`) = autoroutes et leurs bretelles + routes
nationales 117, 175, 173, 133 et 185, soit ≈ 8 100 km de chaussées (officiel : 8 046 à 8 104 km selon les bilans).

| Ponts remarquables (v0.6.3 ; v0.6.5 : infobox des articles anglais et français — construction début/fin, mise en service, longueur, portée, largeur, hauteur, dégagement, travées, piles, voies, conception, constructeur, débit, péage, coût ; textes français préférés, textes anglais signalés `txtEn` ; introduction entière en français et, si elle est au moins 1,6 fois plus longue, en anglais (`resumeEn`) ; 3 photos Flickr CC choisies à la main (`PHOTOS_EXTERNES`, trouvées par Openverse) ; clic sur la photo → article Wikipédia ; v0.6.4 : infobulle et fiche à droite comme le MTMD, case dans le panneau des filtres, lien Wikipédia seul — français, sinon anglais —, photos de secours : image Wikidata P18, catégorie Commons P373, photo choisie à la main, recherche Commons géolocalisée à 30 km ou fichier à 600 m dont le titre reprend le nom du pont et « bridge » ; sinon vue aérienne Esri) : 179 ponts du Canada hors inventaire du MTMD (étoiles, hors filtres et statistiques) + lien Wikipédia pour 159 ouvrages du MTMD (même nom à ≤ 3 km, ponts jumeaux compris ; un échangeur ou un tunnel ne se lie pas à l'article d'un pont) | `etl/wikiponts.py` | `data/couche-wikiponts.js` (~0,18 Mo) | Wikipédia anglais « List of bridges in Canada » (tableaux + liste par province), API Wikipédia (en, fr : coordonnées, image libre, résumé), Wikidata (CC0 : type, longueur, portée, ouverture, matériau, obstacle, conception, propriétaire, patrimoine, identifiant Structurae P454 ; requête SPARQL des ponts de la boîte du Québec pour l'appariement), Wikimedia Commons (auteur et licence de chaque image). Structurae : liens seulement (site fermé aux robots, droits réservés) |

## Constats de jointure (2026-10-11)

- **WFS 11 701 vs outil public 9 880** : toutes les structures de l'outil sont dans le WFS. Les 1 821 en plus sont
  surtout des ponceaux d'ouverture 3–4,5 m (l'outil ne publie que ≥ 4,5 m) et des structures d'autres responsables
  (EFA sous bail, municipalités, « autre ») ou des stations de pompage. Champ `in_apex` pour les distinguer.
- **ICG / IAS** : totaux identiques à ceux affichés par l'outil.
- **Hauteurs libres** : le « numéro de référence » est le n° de structure complet (suffixe compris, ex. `14240FA`) ;
  1 113 / 1 246 références jointes, les autres sont des ouvrages hors MTMD (pont Victoria, viaducs du CN…).
  Les hauteurs ≥ 10 m (valeurs « sans limite ») sont ignorées pour `hauteur_libre_min_m`.
- **GPS.csv** (sans identifiant) : 9 264 / 9 264 points joints par coordonnées exactes → `limite_charge`.
- **Fiches détaillées** : le service OData qui alimente l'outil fournit les mêmes champs que les ~9 900 fiches HTML
  en une requête (2 s) ; le crawl HTML (`etl/apex_fiche.py`) reste disponible mais n'est plus nécessaire.
  DJMA de 1 = « ND » dans les fiches → traité comme non disponible.
- **Panneaux de poids** : `28t* 44t** 58t***` = véhicule routier / ensemble de 2 unités / de plus de 2 unités
  (notes explicatives du répertoire des limitations de poids).

## Visualiseur

`QuickerAtlasOA-vX.Y.Z-AAAA-MM-JJ.html` à la racine (avant la v0.5.1 : `PontsQC-v…` ; versions précédentes dans `old/` ; thème QuickerBridge, Leaflet + fonds Esri, sans clé d'API).
Charge `data/structures.js` (~2 Mo, format compact décrit dans `etl/build.py`) et `data/details.js` (fiche détaillée, ~2,6 Mo) par `<script src>`,
puis `data/debits.js` et `data/journal.js`, et à la demande les couches ci-dessus (les ouvrages des villes avec la case
« Inclure les ouvrages des villes ») : s'ouvre directement en `file://` (double-clic) ou via `python -m http.server` à la racine.
**En ligne** : <https://acfakkoh.github.io/QuickerAtlasOA/> (GitHub Pages, branche `main`, racine). Depuis la v0.6.0,
`index.html` **est** le visualiseur (copie à l'identique du fichier versionné, refaite à chaque publication :
`cp QuickerAtlasOA-vX.Y.Z-AAAA-MM-JJ.html index.html`) : l'adresse publique reste la racine du site, sans redirection
vers le nom de fichier versionné ; `.nojekyll` désactive Jekyll. Le site n'a besoin que
des HTML, de `sw.js`, de `js/` et de `data/` (sans `raw/` ni `ponts.sqlite`, exclus par `.gitignore`).

**Modules à la demande** (v0.5.6) : `js/hydro.js` (fenêtre « Cours d'eau au pont »), `js/sismique.js` (fenêtre « Aléa
sismique ») et, depuis la v0.6.0, `js/lidar.js` (« Profil LiDAR », contrat `window.QA_MOD.lidar.open(o)`) ne sont chargés
qu'à la première ouverture. Contrat : `window.QA_MOD[clé].render(o, body, ctx)` ; la page leur
prête `window.QA` (échappement, formats, `fetchT` borné dans le temps corps compris, `loadScript`, `distM`, `det`).

**LiDAR** (MNEHR 1 m de Ressources naturelles Canada, Licence du gouvernement ouvert – Canada) : fonds « Relief ombré
MNT / MNS » en tuiles WMS, et bouton « Profil LiDAR » de la fiche, calculé à la demande dans le navigateur (WCS en
GeoTIFF + axes OpenStreetMap par Overpass) : profils en long et en travers (orienté selon le biais), hauteur sous
l'ouvrage, relief ombré local. Aucune donnée précalculée. Depuis la v0.5.5 : pentes longitudinales des approches, du
tablier et de la voie du dessous ; la chaussée du dessous est lue sur 8 sections de l'obstacle hors du pont (4 à 16 m
au-delà de chaque bord), voie repérée par OSM (sinon plages planes du relief), fenêtre de 3 m la plus plane, droite
ajustée → altitude sous l'axe ; hauteur = dessus du tablier (MNS) au droit de la voie − chaussée.
v0.6.1 : pentes de la route portée au meilleur de trois modèles (droite, parabole, double pente). v0.6.2 : sans OSM
ni pixels de tablier (tablier classé « sol » dans le MNT), l'axe de la route portée est lu sur le relief (direction où
la surface reste au niveau du tablier) ; alerte de pente à ± 10 % sur la pente affichée ; équation z = a + b·x + x²/c.

**Performance** (v0.6.3) : routes, rail et ponts ferroviaires sont tracés par une seule couche `FastLines` par réseau
(au lieu de ≈ 25 000 `L.polyline`) : sommets projetés une fois en Mercator au zoom 0, multipliés par 2^zoom ensuite,
lignes hors écran écartées par leur boîte, tracé par lots de même style, survol par boîtes puis segments. Les points
(`L.CircleMarker`) gardent aussi leur position « monde » en cache. Zoom à la molette : événements `pinch`, fonds avec
`updateWhenZooming: false`, ni chargement de tuiles ni test de survol pendant le geste. WMS (cours d'eau, relief LiDAR) en
tuiles de 512 px chargées à l'arrêt de la carte. Mesures (Chrome sans GPU) : zoom avec routes et rail 316–383 ms → ≈ 100 ms ;
zoom molette 6 → 14 : ≈ 530 tuiles demandées → ≈ 28.

**Carte** (v0.6.4) : boutons en haut à gauche (« + », « − », Québec, « Couches »), chacun dans sa case de 36 px ; le
panneau des couches s'ouvre sous son bouton, au-dessus de la légende. Numéros des structures dès le zoom 12 (14 avant),
une étiquette qui en chevaucherait une autre étant omise (grille de 8 px), celle de la structure ouverte en premier.
Lien `#w=Q…` : pont remarquable ouvert (fiche à droite).

**Photos** : servies par le MTMD sans en-tête de cache ; `sw.js` (Service Worker, http(s) seulement) les garde en
cache (600 au plus) pour ne pas les retélécharger à chaque survol.

Données : © MTMD / Données Québec (CC-BY 4.0) · Fonds de carte : © Esri (sans clé d'API) ; depuis la v0.6.0 le fond Esri
« Plan » est retiré et **OpenStreetMap** est le fond par défaut. En http(s) seulement (GitHub Pages, serveur local), deux fonds de plus : **Plan Québec (gouvernement)** (`geoegl.msp.gouv.qc.ca`, toponymie officielle,
zoom ≤ 17) et **OpenStreetMap** ; ils exigent l'en-tête Referer, absent en `file://`. CARTO exige désormais une clé d'API
(tuiles marquées « API KEY REQUIRED ») : écarté.
