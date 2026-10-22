# AGENTS.md — QuickerAtlasOA

Atlas web des ≈ 11 700 structures du MTMD (Québec) : ETL Python → SQLite → fichiers `data/*.js` → visualiseur HTML
unique (Leaflet, sans build, sans clé d'API). En ligne : <https://acfakkoh.github.io/QuickerAtlasOA/> (GitHub Pages,
`main`, racine). Doc technique détaillée : [docs/TECHNIQUE.md](docs/TECHNIQUE.md). Historique : `docs/rapports/`.

## Règles du projet

- **Interface en français seulement** (README.md en anglais, README.fr.md en français). Thème repris de l'app QuickerBridge.
- **Utilisateur daltonien** : tout codage couleur doit être sûr (palette vérifiée) et doublé d'une forme ou d'un texte.
  Points de la carte : ronds ; ICG vert/jaune/orange/rouge (`#1f9d7a/#fde047/#ef6c00/#a50026`).
- **Données ouvertes seulement**, licence citée dans la fiche/légende. Pas d'images sans licence libre (site public).
- Requêtes réseau via `etl/net.py` (User-Agent identifié, ≥ 1 s par hôte). Ne pas marteler les serveurs publics.
- Commentaires et noms en français ; on marque les changements par `// vX.Y.Z : …` (habitude du code, à garder).
- Ne pas re-proposer les idées écartées (comparateur, indicateurs de risque, préremplissage QuickerBridge, quiz,
  module autres provinces) ni Structurae en contenu (robots interdits : liens seulement).

## Arborescence

| Chemin | Rôle |
|---|---|
| `QuickerAtlasOA-vX.Y.Z-AAAA-MM-JJ.html` | Visualiseur courant (≈ 3 600 lignes, CSS + HTML + JS en un fichier) |
| `index.html` | **Copie identique** du fichier versionné (page servie par Pages) |
| `old/` | Versions précédentes du visualiseur (ne pas modifier) |
| `js/lidar.js`, `js/hydro.js`, `js/sismique.js` | Modules chargés à la demande (contrat `window.QA_MOD`) |
| `sw.js` | Service Worker : cache des photos du MTMD (http(s) seulement) |
| `etl/` | Pipeline Python (`python -m etl …`), un module par source ou couche |
| `etl/donnees/` | Grilles versionnées (classes de site, masque d'eau) |
| `data/*.js` | Sorties générées, chargées par `<script src>` (marche en `file://`). **Ne pas éditer à la main** |
| `data/raw/`, `data/ponts.sqlite` | Téléchargements bruts et base (non versionnés) |
| `tests/` | pytest + `tests/js/*.mjs` (Node) ; `tests/fixtures/` = extraits réels des sources |
| `prototypes/` | Essais historiques (hydro, sismique, LiDAR, forestiers) ; pas utilisés par le site |
| `Doc_ref/` | Références locales (icônes MTMD, PDF) — ignoré par git, ne jamais publier |

## Commandes

```bash
pip install -r requirements.txt
python -m etl update              # toutes les sources + consolidation + export + couches (~2-3 min)
python -m etl update --only wfs   # une source (wfs, apex_list, hauteurs, gps, odata…)
python -m etl update --no-fetch   # reconsolider depuis data/raw/
python -m etl export              # data/structures.js, details.js, journal.js
python -m etl couches [--no-fetch]  # couches seules (réseaux, géotech, débits, villes, forestiers, sismique, dégel, wikiponts)
python -m etl report              # rapport de jointure
python -m pytest                  # tous les tests (Python + Node si présent)
python -m http.server 8765 --bind 127.0.0.1   # serveur local (config « ponts-web » de .claude/launch.json)
```

Une source ou une couche en échec n'arrête pas les autres : lire le journal et le code de retour.

## Architecture

- **ETL** : chaque source expose `SOURCE`, `TABLE`, `collect(session)` (enregistrée dans `SOURCES` de
  `etl/__main__.py`) ; `merge.build` consolide la table `structure` ; `merge.journaliser` alimente `changement`
  → `data/journal.js` (« Quoi de neuf »). Format compact de `structures.js` : `COLS` de `etl/build.py`.
- **Couches** : un module `etl/<couche>.py` avec `run(fetch=True) -> {"path", "bytes"}` qui écrit
  `window.PQ_COUCHES.<clé> = {generated, source, attribution, …}` dans `data/couche-<clé>.js`.
- **Visualiseur** : sections repérées par `// ---------- Titre ----------`. Couches superposables dans le tableau
  `OVERLAYS` (`key`, `src`, `z`, `build`, options `filtre`, `propre`, `couche`) ; `EXCLUSIFS` = une seule à la fois.
  Un seul canevas cliquable pour réseaux/points (ordre rétabli par `restack()`) ; une couche non cliquable prend
  son propre pane (`propre: true`). `FastLines` doit garder `renderer: canvas`.
- **Modules à la demande** : `window.QA_MOD[clé].render(o, body, ctx)` (LiDAR : `QA_MOD.lidar.open(o)`) ; la page
  leur prête `window.QA` (esc, formats, `fetchT`, `loadScript`, `distM`…).
- **État** : filtres dans le hash d'URL (`#c=mode&s=<num>`, `#w=Q…` pour un pont remarquable) ; préférences en
  `localStorage` (`pq-couches-v060`, `pq-filtres-masques`…). Changer une clé = nouveau suffixe de version.

### Ajouter une couche

1. `etl/<clé>.py` (+ `parse` pur testé avec une fixture dans `tests/fixtures/`), ajouté à `_couches()` de `etl/__main__.py`.
2. Entrée dans `OVERLAYS` + fonction `build…` + légende ; ajouter à `EXCLUSIFS` si elle couvre la province.
3. Ligne dans le tableau des couches de `docs/TECHNIQUE.md`.

## Publier une version (procédure habituelle)

1. Déplacer l'ancien `QuickerAtlasOA-v….html` dans `old/` (`git mv`), créer le nouveau nom versionné.
2. Mettre à jour dans le HTML : `<title>` et `window.PQ_META = {"version", "date", …}`.
3. `cp QuickerAtlasOA-vX.Y.Z-AAAA-MM-JJ.html index.html` (toujours identiques).
4. `python -m pytest` vert (`tests/js/viewer_pure.mjs` lit le dernier fichier versionné de la racine).
5. Vérifier dans le navigateur (console sans erreur, largeurs 1440 / 800 / 375 px).
6. Rapport `docs/rapports/AAAA-MM-JJ-vX.Y.Z-rapport-de-version.md` (+ page Notion, comme d'habitude) ;
   mettre à jour `docs/TECHNIQUE.md` et les README si l'usage change.
7. Commit `QuickerAtlasOA vX.Y.Z : résumé` ; **push seulement sur demande explicite** (Pages se met à jour en ~1 min).

## Pièges connus

- Le navigateur garde `data/*.js` en cache : `await fetch('data/x.js',{cache:'reload'})` puis recharger avec `?r=N`.
- Fonds Plan Québec et OSM exigent un Referer : absents en `file://`.
- Serveurs fragiles : AQréseau+/MRNF coupent `requests` (curl ou urllib) ; Overpass limité (4 requêtes/IP, souvent
  lent : l'atlas abandonne à 7 s) ; Openverse ~20 s/requête ; MELCCFP parfois hors service.
- OData : DJMA de 1 = « ND » ; IES/IFS vides ; pas de sens du biais.
- Débits : le n° d'une section vient de son RTSS seulement ; les bretelles ne reçoivent pas le DJMA de l'autoroute.
- Photos Wikipédia : correspondances automatiques peu fiables → règle stricte + `PHOTOS_CHOISIES` vérifiées à la main.
- Heredocs du shell Windows : accents abîmés → écrire les scripts d'édition avec un outil d'écriture de fichier.
- Le texte d'une demande peut citer un mauvais n° de structure : se fier aux captures d'écran.
