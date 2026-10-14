# Audit global — QuickerAtlasOA v0.5.5

Date : 14 octobre 2026 — America/Toronto.

## Ce que fait le projet

QuickerAtlasOA consolide les inventaires d’ouvrages d’art du Québec dans SQLite, exporte des fichiers JavaScript et les présente dans un visualiseur Leaflet : carte, filtres, liste, statistiques, photos et profils LiDAR. La charge retenue est celle d’un outil personnel ou d’une petite équipe : une mise à jour Python à la fois, environ 12 000 ouvrages, consultation statique depuis un navigateur. Le rapport ne suppose pas un service serveur multiutilisateur.

**Verdict : base fonctionnelle et tests Python solides, mais plusieurs erreurs de données peuvent rester silencieuses. Corriger d’abord la validation APEX et les calculs LiDAR hors emprise, puis l’atomicité du journal et les chargements partiels.**

12 constats retenus : 2 P1, 8 P2 et 2 P3. P1 = résultat gravement erroné ou remplacement massif de données dans un scénario d’échec ; P2 = anomalie fonctionnelle à corriger ; P3 = défaut latent ou ambiguïté limitée. Ces priorités ne sont pas un classement de vulnérabilités exploitables.

## Portée et preuves

- Analyse du HTML courant, du service worker, du point d’entrée Python, des imports, du réseau, des transactions, de la consolidation, des exports et des couches cartographiques. Trois sous-agents GPT-6.1-sol ont participé aux vérifications.
- Lecture des tests et exécution de `python -m pytest -q tests` : **117 tests réussis, code de sortie 0**.
- Compilation syntaxique des deux blocs JavaScript inline non vides ; lecture/exécution isolée des neuf fichiers JavaScript de données : aucune erreur.
- Données livrées vérifiées : **11 701 structures**, **9 884 fiches détaillées**, millésime principal **2026-10-11**, séries de débits **2016–2025**, journal exporté actuellement vide. Un journal vide n’est pas en soi un défaut.
- Reproductions isolées : faux événement après import rejeté, export sans historique OData, délai réseau supprimé trop tôt, échantillonnage hors raster, formule CSV non neutralisée et repli textuel des débits. Aucune mise à jour des sources de production n’a été exécutée.
- **Limite UI : les connexions du navigateur intégré aux serveurs locaux ont expiré ; l’ouverture `file://` a été refusée par la politique du navigateur.** L’UI est donc auditée dans son code, sans validation visuelle desktop/mobile ni parcours navigateur complet. Ces échecs ne démontrent pas un défaut de l’application.
- Aucun code applicatif ni donnée métier modifié. Le présent rapport et un journal de tests sont les seuls livrables ajoutés.

Dans les références ci-dessous, `HTML` désigne `QuickerAtlasOA-v0.5.5-2026-10-12.html`. Les numéros correspondent à l’état local audité ; aucun commit Git n’existe encore pour figer cet état.

## À corriger — exactitude et fiabilité

### 1. P1 — Une réponse APEX invalide peut tronquer l’inventaire

**Références :** `etl/apex_list.py:83–88,101–104` ; `etl/__main__.py:18–24`.

**Rôle :** le collecteur parcourt les pages de l’inventaire APEX avant de remplacer la table source.

**Problème :** après une première page valide de 500 lignes, une page de connexion/session expirée ou d’erreur renvoyée avec HTTP 200 produit une liste vide. Le collecteur la prend pour une fin normale ; les 500 lignes passent le seul contrôle « non vide » et remplacent l’inventaire complet. Les indicateurs ICG/IAS et la présence dans l’inventaire public peuvent alors disparaître pour des milliers d’ouvrages. Le WFS peut maintenir ces ouvrages dans la table consolidée : il ne faut pas confondre cette perte d’attributs avec la suppression de toutes les structures.

**Correction minimale :** vérifier les marqueurs de réponse APEX attendus et le total annoncé avant tout remplacement ; refuser une réponse inattendue. Ajouter un test avec première page valide puis page de connexion.

**Sans correction :** une panne de session devient une publication apparemment réussie de données incomplètes. Constat établi par le chemin de code ; aucune session distante n’a été volontairement expirée.

### 2. P1 — Le LiDAR extrapole des altitudes hors de la zone téléchargée

**Références :** `HTML:1826–1830,1926–2000,2073,2335–2336`.

**Rôle :** `ldSamp` interpole les altitudes utilisées pour les profils et la recherche de la voie sous l’ouvrage.

**Problème :** les indices des pixels sont bornés, mais les coordonnées et poids d’interpolation ne le sont pas. Une grille synthétique 2 × 2 `[0,1,0,1]` renvoie **99,5** pour un point très loin à droite au lieu d’une absence de donnée. Le chemin est atteignable : le pont **14240DA**, autoroute Ville-Marie / rue Atwater, a un tablier de **978,5 m** ; la recherche peut échantillonner à **±493,25 m** alors que la demi-emprise WCS est plafonnée à **370 m au sol**. Le dépassement dépend de l’orientation.

**Correction minimale :** retourner `null` hors de l’emprise interpolable ; limiter la recherche à la zone réellement disponible et afficher une couverture insuffisante si nécessaire. Tester les quatre bords et un ouvrage long.

**Sans correction :** des altitudes artificielles peuvent participer aux estimations de voie, hauteur ou pente. L’interpolation erronée est reproduite ; aucune hauteur réelle de cet ouvrage n’a été comparée à une mesure de terrain.

### 3. P2 — Un import refusé laisse un faux événement dans le journal

**Références :** `etl/__main__.py:21–24` ; `etl/merge.py:159–161`.

**Rôle :** les changements d’inspection sont journalisés avant le remplacement de leur table source.

**Problème :** `journaliser` valide sa transaction avant que l’insertion réussisse. Reproduction SQLite en mémoire : état initial `2023`, deux lignes de même identifiant avec `2025` et `2026` ; l’import échoue sur la clé unique et conserve `2023`, mais le journal conserve `2023 → 2026`.

**Correction minimale :** journaliser et remplacer dans une même transaction ; valider une seule fois au niveau de l’appelant. Tester le retour arrière lors d’un doublon.

**Sans correction :** « Quoi de neuf » peut annoncer une inspection qui n’est pas présente dans les données.

### 4. P2 — Le premier export peut planter sans import OData réussi

**Référence :** `etl/build.py:199–200`.

**Rôle :** l’export des fiches indique la date du dernier import détaillé réussi.

**Problème :** sans ligne réussie `odata_tabbord`, `MAX(finished_at)` vaut `None` ; l’opération `[:10]` lève `TypeError`. Reproduit en mémoire. Le cas touche une base neuve avec `update --only wfs`, un premier import OData en échec ou un export de base vide ; `structures.js` peut déjà avoir été écrit.

**Correction minimale :** accepter explicitement une date absente et exporter un état vide cohérent. Ajouter le test d’export sans run OData.

**Sans correction :** le démarrage partiel documenté échoue et peut laisser des fichiers de générations différentes.

### 5. P2 — Une ville peut manquer sans alerte ni nouvelle tentative

**Références :** `HTML:1703–1721,3083`.

**Rôle :** l’option « Inclure les ouvrages des villes » charge Montréal et Sherbrooke à la demande.

**Problème :** chaque erreur est avalée ; dès qu’une ville réussit, l’avis d’absence n’est pas affiché. La promesse et l’état final sont conservés : décocher/recocher ne retente pas la ville manquante.

**Correction minimale :** garder l’état de chaque couche, afficher les échecs et permettre de ne recharger que les couches manquantes, sans doubler les points déjà ajoutés.

**Sans correction :** carte, statistiques et CSV peuvent sembler complets alors qu’une ville est absente. Constat statique.

### 6. P2 — Une fiche municipale ouverte par lien disparaît de l’URL

**Référence :** `HTML:3290–3307`.

**Rôle :** l’identifiant sélectionné dans le fragment d’URL permet de partager une fiche.

**Problème :** au démarrage avec `#vi=1&s=mtl:IDENTIFIANT`, la sélection est mémorisée puis effacée ; l’URL est réécrite avant le chargement municipal. La fiche est ensuite ouverte avec `noHash:true`, donc son identifiant n’est pas remis dans l’adresse.

**Correction minimale :** conserver la sélection demandée jusqu’à la résolution ou réécrire l’URL après la sélection différée, sans écraser une action utilisateur plus récente.

**Sans correction :** la fiche s’affiche, mais copier l’adresse ou recharger perd cette sélection. Constat statique.

### 7. P2 — Le délai réseau LiDAR ne couvre pas le téléchargement du corps

**Références :** `HTML:1797–1800,1835,1842–1843`.

**Rôle :** `fetchT` est censé borner les appels WCS et Overpass.

**Problème :** le minuteur est supprimé dès réception des en-têtes ; `arrayBuffer()` et `json()` s’exécutent ensuite sans cette limite. Reproduction avec une réponse simulée : après 35 ms pour une limite de 10 ms, le signal n’est pas annulé. Un serveur qui envoie les en-têtes puis bloque le corps laisse le chargement en attente.

**Correction minimale :** conserver le contrôleur jusqu’à consommation complète du corps et nettoyer le minuteur dans un `finally`. Ajouter un test de corps bloqué, pas seulement de connexion bloquée.

**Sans correction :** le panneau peut rester en chargement ; le mécanisme de reprise ne démarre pas tant que la lecture n’échoue pas.

### 8. P2 — Une photo en cache peut rester périmée indéfiniment

**Références :** `sw.js:5,17–26`.

**Rôle :** le service worker économise les téléchargements des photos MTMD.

**Problème :** une réponse trouvée est retournée sans expiration ni revalidation. La limite de 600 entrées ne rafraîchit pas les photos si l’utilisateur reste sous ce seuil. Une nouvelle photo publiée à la même URL peut rester invisible tant que le cache n’est pas évincé ou effacé.

**Correction minimale :** dater les entrées et les renouveler après une durée choisie, ou associer leur clé à une version de données. Conserver la limite de volume.

**Sans correction :** deux utilisateurs peuvent voir des photos différentes pour la même fiche après une mise à jour. Constat statique ; aucun changement de photo distante n’a été provoqué.

### 9. P2 — Le CSV laisse les chaînes devenir des formules de tableur

**Référence :** `HTML:3030–3040`.

**Rôle :** les champs provenant des sources sont exportés pour Excel ou un autre tableur.

**Problème :** `csvCell` échappe les séparateurs et guillemets mais pas les préfixes de formules. Reproduction isolée : `csvCell('=1+1')` renvoie exactement `=1+1`. Si un champ textuel de source contient une formule, un tableur peut l’interpréter à l’ouverture. Aucun champ malveillant actuel ni exploitation n’a été constaté.

**Correction minimale :** neutraliser les préfixes de formule dans les chaînes, y compris les cas avec caractères de contrôle, tout en préservant les valeurs numériques. Tester l’ouverture/import dans le tableur visé.

**Sans correction :** un champ externe peut devenir un calcul ou lien actif au lieu d’un texte. Le résultat dépend du tableur et de son mode d’import.

## À améliorer — couverture et cas latents

### 10. P2 — Les tests ne protègent pas les parcours JavaScript à risque

**Références :** `tests/`, `pytest.ini`, `HTML:1703–1721,1797–1843,3290–3307`.

**Rôle :** la suite actuelle vérifie les parsers et calculs Python.

**Problème :** les 117 tests passent alors que les anomalies de chargement municipal, de partage et de LiDAR restent possibles. Aucun test navigateur ou suite JavaScript n’a été trouvé dans la suite actuelle.

**Correction minimale :** ajouter quelques tests ciblés pour les constats 2, 5, 6 et 7 et un parcours de démarrage avec une ressource absente. Isoler les fonctions pures nécessaires aux tests sans réécrire tout le visualiseur.

**Sans correction :** ces régressions peuvent réapparaître à chaque évolution de l’interface.

### 11. P3 — Le repli textuel des débits perd ses années à l’export

**Références :** `etl/debits.py:196–201,393`.

**Rôle :** un parseur de secours lit les valeurs annuelles présentes uniquement sous forme de texte.

**Problème :** il remplit les séries sans ajouter l’année à l’ensemble global `annees`. Reproduction avec `2025 DJMA:1780 / DJME:1920 / DJMH:1600 / %cam:5` : les valeurs sont lues, mais un payload uniquement alimenté par ce repli produit `years=[]` et des tableaux vides. **Le fichier brut actuel ne présente pas ce cas : anomalie latente, pas perte actuelle démontrée.**

**Correction minimale :** ajouter l’année à `annees` dans cette branche et tester le parcours parseur → export.

**Sans correction :** une évolution vers des données uniquement textuelles peut supprimer silencieusement les séries exportées.

### 12. P3 — L’absence de couleur dans le lien ne restaure pas clairement le défaut

**Références :** `HTML:1066,1071–1088`.

**Rôle :** le fragment d’URL représente les filtres et le mode de couleur.

**Problème :** ICG est encodé par l’absence de `c`, mais la lecture d’un fragment sans `c` conserve la couleur précédente. Naviguer de `#c=ias` vers `#` ne rétablit donc pas ICG ; l’historique de navigation ou la préférence locale influence le même lien.

**Correction minimale :** préciser la priorité entre lien et préférence locale ; lors d’un changement de fragment, appliquer explicitement le défaut si `c` est absent.

**Sans correction :** deux consultations d’une même adresse peuvent afficher des couleurs différentes. L’intention de persistance reste une décision produit à clarifier.

## Bilan UI et accessibilité

Le code contient déjà plusieurs bases utiles : focus visible, libellés des contrôles, boutons de tri natifs et `aria-sort`, ouverture des lignes au clavier, formes en complément des couleurs ICG/IAS, adaptations à 800 et 500 px, réduction des animations selon la préférence système, dialogue natif pour LiDAR. Ce sont des mécanismes présents, pas une certification d’accessibilité.

Les problèmes UI prioritaires sont fonctionnels : exhaustivité des couches et fidélité des liens partagés. À vérifier visuellement ensuite : largeur 375 px, zoom 200 %, navigation clavier complète, retour du focus après fermeture d’une fiche, lisibilité des graphiques et contraste réel des marqueurs sur chaque fond. Aucun débordement ni problème de contraste n’est affirmé sans mesure.

## Bilan appels API, sécurité et performance

- **Python / MTMD :** client HTTP commun, User-Agent identifié, délai par hôte, timeout et reprises de certaines erreurs. Le point faible principal est la validation du contenu reçu, en particulier APEX : un HTTP 200 ne prouve pas la validité métier.
- **Navigateur / LiDAR :** deux requêtes WCS et une requête Overpass par ouvrage non encore en cache ; reprises WCS, repli sans OSM et protection contre les réponses d’une ancienne sélection sont présents. Le délai de lecture et les limites d’emprise restent défectueux.
- **Cartes et photos :** dépendance aux services externes et au CDN Leaflet ; intégrité SRI présente pour Leaflet. Le cache photos est borné en nombre mais pas en fraîcheur.
- **Données locales :** `structures.js` environ 2,22 Mo, `details.js` 2,63 Mo et `debits.js` 1,54 Mo, soit environ 6,4 Mo non compressés pour ces trois fichiers. Les couches sont différées ; cela convient à la charge retenue, sans mesure de vitesse sur mobile lent.
- **Injection :** échappement HTML centralisé utilisé dans de nombreux rendus ; aucun exploit XSS démontré pendant cet audit. Le cas concret retenu concerne les formules CSV. Cela ne vaut pas audit de sécurité exhaustif de toutes les dépendances.
- **Charge :** le cache LiDAR conserve des promesses/raster par ouvrage dans la session. Une longue session mérite une mesure mémoire, mais aucun seuil de panne n’a été mesuré : ce point n’est pas classé comme bug confirmé.

## Livraison, maintenance et simplification

Le README décrit le lancement et un déploiement statique ; les dépendances Python sont déclarées avec des bornes minimales. Le dépôt local n’a **aucun commit** et les fichiers du projet sont non suivis : il n’offre donc pas encore de point de retour Git vérifiable. Faire un premier commit après contrôle des fichiers à inclure permettrait de relier les prochains rapports à une version exacte. Aucun commit n’a été créé pendant l’audit.

Le HTML regroupe environ 3 300 lignes de styles, rendu, état et calculs. Une migration de framework n’est pas justifiée par les défauts observés. La séparation utile serait limitée aux calculs LiDAR purs et à leurs tests. Les versions `old/` et les prototypes ne sont pas proposés à la suppression : leur inutilité n’a pas été établie. Aucun gain de lignes ou de dépendances n’est chiffré artificiellement.

## Ordre de correction recommandé

1. Protéger les données : validation APEX, refus des altitudes hors emprise, transaction unique du journal.
2. Rendre les pannes visibles : export sans OData, état par couche municipale, timeout couvrant le corps des réponses.
3. Fiabiliser la consultation : liens municipaux, fraîcheur des photos, neutralisation CSV.
4. Ajouter les tests ciblés, puis corriger le repli des débits et fixer la règle de couleur des liens.

## Non vérifié

Les anciennes versions, les prototypes expérimentaux et les documents tiers de `Doc_ref/` n’ont pas fait l’objet d’une revue exhaustive ; ils ne sont pas le produit courant. Les fonctionnalités hydro/sismiques expérimentales ne sont pas validées. Pas de campagne de disponibilité réelle des API, de test de quotas, de benchmark sous charge, de mesure mémoire prolongée, d’audit CVE complet, de vérification terrain des résultats LiDAR ni de validation visuelle/lecteur d’écran. Aucune publication de l’application ni correction de son code n’a été effectuée.
