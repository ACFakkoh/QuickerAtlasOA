# Autres bases de données de ponts au Québec (hors MTMD) — recherche du 2026-10-11

**En bref** : très peu de gestionnaires autres que le MTMD publient un inventaire ouvert de leurs ponts. Deux sources valent la peine d'être intégrées et le sont depuis la v0.5.1 : **Ville de Montréal** (avec l'état) et **Ville de Sherbrooke** (localisation seulement). Deux autres servent à contrôler ou compléter : la BDOIn de Statistique Canada et AQréseau+. Hydro-Québec, la SÉPAQ, Parcs Canada et PJCCI ne publient rien.

À savoir d'abord : depuis 2008, le MTMD gère **environ 4 200 ponts du réseau municipal** (municipalités de 100 000 habitants et moins en 2001). Ils sont déjà dans le jeu « Structure ». Les manques sont donc surtout les **grandes villes** et les **gestionnaires non routiers**.

## Données ouvertes utilisables

| Gestionnaire | Jeu de données | Contenu | Remarques |
|---|---|---|---|
| Ville de Montréal | [Inventaire des actifs de voirie – Structures routières](https://donnees.montreal.ca/dataset/structure-routiere) | 577 ouvrages (300 ponts, 254 murs, 18 ponceaux, 5 tunnels) : type (nomenclature du MTMD), année, superficie du tablier, charge de conception, affichage, **ICG de la Ville (0–100 et catégorie)**, date d'inspection, responsabilité, lien vers le rapport PDF | CSV, SHP, GeoJSON ; éditions 2016 à **2021** (aucune plus récente) ; CC-BY 4.0 ; « ne pas utiliser pour des calculs d'ingénierie » |
| Ville de Sherbrooke | [Ouvrages routiers](https://donneesquebec.ca/recherche/dataset/7dc8adc25f25438a86efe6ee4e68731b_0) | 24 ouvrages : identifiant, sous-type, nom | GeoJSON, CSV, REST ArcGIS ; CC-BY 4.0 ; mis à jour en juin 2026 ; aucun attribut d'état |
| Statistique Canada | [Base de données ouvertes sur les infrastructures (BDOIn) v2](https://www150.statcan.gc.ca/n1/pub/34-26-0003/342600032023001-eng.htm) | Couche « ponts et tunnels » compilée à partir des portails ouverts | GPKG, collecte 2023–2024 ; utile pour vérifier qu'aucune ville ne publie d'inventaire qu'on aurait manqué (champ fournisseur) |
| MRNF (Adresses Québec) | [AQréseau+](https://donneesquebec.ca/recherche/dataset/adresses-quebec) | Ponts de tout le réseau, y compris les **chemins multiusages en forêt** | CC-BY 4.0 ; géométrie seulement (ni état ni capacité) ; probablement la seule source ouverte pour les ponts forestiers |

Le [Réseau routier national (RRN) de RNCan](https://data.amerigeoss.org/dataset/f79e8e77-093c-4cbc-ac40-47b0ea0ade59) a aussi un attribut « type de structure » sur ses tronçons. Ce sont des tronçons, pas un inventaire : il ferait doublon avec AQréseau+.

## Pas de données ouvertes trouvées

- **Hydro-Québec** : l'[Atlas Hydro](https://donneesquebec.ca/recherche/showcase/atlas-hydro) ne montre que les installations et l'hydrométrie. Les ponts des chemins d'accès n'apparaissent que dans des études de projet déposées au BAPE (ex. [La Romaine](https://archives.bape.gouv.qc.ca/sections/mandats/La%20Romaine/documents/DA51.pdf)). Certains ponts routiers lui appartiennent, comme le [pont de Beauharnois](https://www.hydroquebec.com/data/projets/rehabilitation-pont-beauharnois/pdf/info-projet-pont-de-beauharnois-juillet-2026.pdf).
- **SÉPAQ** : rien de publié ; seule une [fiche d'organisation](https://donneesquebec.ca/recherche/organization/about/sepaq) existe sur Données Québec.
- **Parcs Canada** : couches ouvertes pour les quais, barrières et bâtiments, **aucune pour les ponts** (canaux de Lachine, de Chambly…).
- **PJCCI** : quelques grands ouvrages (Jacques-Cartier, Champlain d'origine, estacade, pont de L'Île-des-Sœurs, sections fédérales de Bonaventure et d'Honoré-Mercier, tunnel de Melocheville), décrits dans les [rapports annuels](https://JacquesCartierChamplain.ca/site/assets/files/5668/pjcci_ra2020-2021_fr_web_2021-12-15.pdf), sans jeu de données.
- **SPAC** : cinq [ponts interprovinciaux](https://www.canada.ca/fr/services-publics-approvisionnement/services/infrastructure-immeubles/ponts-quais-barrages/ponts-passages-rcn.html) Gatineau–Ottawa. Le [pont de Québec](https://www.canada.ca/fr/logement-infrastructures-collectivites/nouvelles/2024/11/le-gouvernement-du-canada-confirme-lacquisition-du-pont-de-quebec.html) est redevenu fédéral en novembre 2024.
- **Ville de Québec** : gère un actif « ouvrages d'art » ([présentation CERIU](https://ceriu.qc.ca/system/files/2023-01/CERIU-VQ-OA_2022-11-01.pdf)), non publié.
- **Laval, Gatineau, Longueuil, Lévis, Trois-Rivières** : aucun jeu « ponts » ou « ouvrages d'art » trouvé.
- **Ponts couverts patrimoniaux** : chaque pont a sa fiche dans le [Répertoire du patrimoine culturel](https://www.patrimoine-culturel.gouv.qc.ca/rpcq/redirection.do?go=about), sans export ouvert.
- **Données agrégées** : l'[Enquête sur les infrastructures publiques essentielles](https://www150.statcan.gc.ca/daily-quotidien/220524/dq220524a-fra.htm) ne donne que des répartitions de l'état par province.

## Ce qui a été fait (v0.5.1)

- `etl/villes.py` → `data/couche-mtl.js` (577 ouvrages, 0,3 Mo) et `data/couche-sherbrooke.js` (24 ouvrages), régénérés par `python -m etl couches`.
- Les 577 types de Montréal sont tous associés à un code de type du MTMD, y compris une coquille de la source (« voà»té » → « voûté »).
- Lien avec l'inventaire du MTMD : un ouvrage du MTMD à moins de 30 m pour **107 ouvrages montréalais** et **20 sherbrookois**, affiché dans la fiche.

## Pistes suivantes

1. Saisir à la main une courte liste des ouvrages fédéraux (PJCCI, SPAC, pont de Québec), soit environ 15 entrées.
2. Demander les inventaires des villes de Québec, Laval, Gatineau, Longueuil et Lévis, par demande d'accès à l'information au besoin. On peut regrouper cette demande avec celle prévue au MTMD.
3. Le catalogue « pont » de l'IRIU liste aussi un jeu **« Limite de charge » du MTMD**, qui pourrait devenir une couche à part.
