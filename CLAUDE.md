@AGENTS.md

# Spécifique à Claude Code

Tout le contexte du projet est dans AGENTS.md (importé ci-dessus). Ici : la routine d'une mise à jour, pour ne pas
la redécouvrir à chaque fois.

## Cycle d'une version

1. **Demande** : page Notion « QuickerAtlasOA version X.Y.Z » sous la page parente « Visualisation Ponts et ouvrages
   d'art QC MTMD » (`3f6e798a151f80a78601f618432b05c7`). Lire aussi les captures d'écran (le n° cité peut être faux).
2. **Faire** les demandes, puis la procédure « Publier une version » d'AGENTS.md.
3. **Rapport** « comme d'hab » : page Notion enfant de la page parente + copie `docs/rapports/AAAA-MM-JJ-vX.Y.Z-rapport-de-version.md`.
   Plan type : une section par demande (numérotée comme la page Notion), puis « Vérifications » (nb de tests, cas
   vérifiés au navigateur). Phrases courtes, en français, sans jargon inutile.
4. **Push** seulement si l'utilisateur l'écrit (souvent dans la page Notion), puis vérifier que Pages est à jour.

## Vérifier au navigateur sans tâtonner

- `preview_start` avec le nom `ponts-web` (http.server sur 127.0.0.1:8765) ; un autre chat peut déjà le servir :
  naviguer directement.
- Le volet est étroit (~617 px) et parfois masqué : pour une capture fiable, Chrome sans interface
  (`chrome --headless=new --window-size=1600,900 --virtual-time-budget=20000 --screenshot=…`) ou petit script Node
  CDP (port 9333, WebSocket natif de Node 24).
- Préparer l'état sans cliquer : `localStorage['pq-couches-v060'] = 'eau,rtss,degel'` (couches), `#s=<num>`
  (structure ouverte), `#w=Q…` (pont remarquable), `#c=<mode>` (mode de couleur).
- Toujours finir par : console sans erreur, largeurs 1440 / 800 / 375 px.

## Façon de travailler

- Parties indépendantes (recherche de sources, audit, prototype) : déléguer à des sous-agents Sonnet est accepté.
- Nouvelle source de données : prototype ou rapport d'abord (`prototypes/`, `docs/rapports/`), intégration seulement
  si l'utilisateur la valide.
- Propositions d'idées : les noter dans le rapport, ne rien intégrer sans accord.
