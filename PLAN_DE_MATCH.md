# Plan de match technique — Visualisation ponts et ouvrages d'art QC

*2026-10-11 · Basé sur le brief Notion « Visualisation ponts et ouvrages d'art QC plan de match 2026-10-11 »*

---

## 1. Résumé exécutif

- **Le projet est faisable, et plus simplement que prévu.** Un flux WFS officiel (Données Québec, CC-BY 4.0, mis à jour quotidiennement) fournit **11 701 structures en une seule requête**, avec n°, type, route, obstacle, municipalité, direction territoriale, année, nb de voies, dimensions et coordonnées.
- **La liste de l'outil MTMD (Oracle APEX) se récupère en ~20 requêtes** : le paramètre `pg_max_rows=500` est accepté (au lieu de 15 lignes/page). Elle ajoute réseau, ICG, IAS, année prévue des travaux et rapport disponible.
- **Les fiches détaillées** (classe de route, DJMA, % camion, superficie, inspections…) demandent 1 requête par structure : **une passe unique de ~2–3 h**, puis seulement l'incrémental.
- **Les hauteurs libres** (1 535 entrées) tiennent dans une seule page et se joignent par le n° de structure.
- Environ **80 % des champs demandés** proviennent de 1 + ~20 requêtes.

---

## 2. Sources de données et stratégie d'extraction

| Source | Accès | Volume / coût | Apporte |
|---|---|---|---|
| **WFS « Structure »** — `ws.mapserver.transports.gouv.qc.ca/swtq?service=wfs&version=2.0.0&request=getfeature&typename=ms:gsq_v_desc_strct_tri` (CSV / GeoJSON) | 1 GET | 11 701 entités | `ide_strct`, `num_dossr`, type (code + libellé), nom, route, obstacle, municipalité, centre de services, DT, année, nb voies, longueur tablier et largeur hors-tout (mm), lat/lon |
| **Liste APEX** — `diffusion.transports.gouv.qc.ca/ords/pes/f?p=122:56` | `pg_max_rows=500` → ~20 GET | 9 880 structures | Réseau (Supérieur/Municipal), ICG, IAS, année prévue des travaux, rapport dispo, URL de la fiche (avec checksum `cs`) |
| **Fiche APEX** — `f?p=122:53::::53:P53_IDE_STRCT_0001:<ide_strct>` | 1 GET / structure (~120 ms) | 9 880 GET ≈ 2–3 h à 1 req/s | Classe route, MRC, CEP, longueur totale, largeur carrossable, superficie, DJMA, % camion, dernière / prochaine inspection |
| **Filtres APEX** (limitation hauteur, limitation poids, rapport) | 3 GET filtrés | — | Drapeaux booléens |
| **Répertoire des hauteurs libres** — `…/hauteurs-libres/Pages/DHLDetails.aspx` | 1 GET (DataTables côté client) | 1 535 lignes | Hauteurs S/O et N/E ; « Numéro de référence » = n° de structure (+ suffixe A, N, E, FA…) |
| **GPS.csv / GPS.gpx** (téléchargeables depuis APEX) | 1 GET | 9 264 lignes, **sans identifiant**, latin-1 | « Limite de charge » (texte) → jointure par coordonnées exactes |

**Constats utiles**

- `ide_strct` du WFS = paramètre de la fiche APEX → jointure triviale.
- Les codes de type correspondent aux icônes APEX (`45.gif` = Pont acier-bois).
- Familles par code : **11–21 ponceau · 31–85 pont · 94 tunnel · 97 mur · 98 station de pompage**.
- Écart **WFS 11 701 vs APEX 9 880** à qualifier en Phase 1 (probablement des structures non publiées dans l'outil).

**Réponses aux points « à évaluer » du brief**

- *Extraire les détails des fiches ?* **Oui** — une passe unique de 2–3 h, avec reprise sur interruption, puis rafraîchissement ciblé.
- *Combiner avec les hauteurs libres ?* **Oui** — une requête, jointure directe par n° de structure.

**Politesse du scraping** : User-Agent identifié, 1 req/s, plage nocturne, cache local, reprise là où le run s'est arrêté.

---

## 3. Modèle de données (SQLite)

| Table | Contenu |
|---|---|
| `structure` | Clé `num_dossr`, `ide_strct`, champs WFS + liste APEX, drapeau `dans_inventaire_public` |
| `type_structure` | Code, libellé complet, famille, icône |
| `fiche_detail` | Champs des fiches + `fetched_at` |
| `hauteur_libre` | N° de référence, direction, hauteur, route, obstacle |
| `source_run` | Horodatage, source, nb de lignes, hash du contenu |
| `changement` | Diff entre runs : nouvelles, retirées, ICG/IAS/année prévue modifiés |

Unités normalisées (m, m²), textes en UTF-8.

---

## 4. Pipeline ETL (Python)

```
etl/
  wfs.py          # flux WFS → structure
  apex_list.py    # liste APEX 500/page + 3 filtres → ICG, IAS, réseau, drapeaux
  apex_fiche.py   # fiches détaillées (throttle, reprise)
  hauteurs.py     # répertoire des hauteurs libres
  gps.py          # GPS.csv → limite de charge (jointure par coordonnées)
  db.py           # schéma, upserts, diff
  build.py        # export web
```

Stack : `sqlite3` (stdlib), `requests`, `beautifulsoup4` + `lxml`. Commande unique :

```bash
python -m etl update [--full]
```

---

## 5. Export vers le web

- `data/structures.js` → `window.STRUCTURES = {…}` en format colonnaire compact (~1,5–2,5 Mo).
- Chargé par `<script src>` : fonctionne en **`file://`** (visualiseur local) *et* sur **GitHub Pages**, sans le blocage CORS d'un `fetch`.
- Détails lourds des fiches éventuellement dans un 2ᵉ fichier chargé à la demande.

---

## 6. Mise à jour périodique

- À chaque run (~1 min) : WFS + liste APEX + hauteurs libres + GPS.
- Fiches re-scrapées seulement pour : nouvelles structures, ICG / IAS / année prévue modifiés, ou fiche de plus de 180 jours (rotation).
- **GitHub Action** cron `0 6 1 */2 *` (aux 2 mois) : exécute l'ETL, commit les données et le journal des changements. En local, même commande.
- Interface : bandeau « Données au AAAA-MM-JJ » + panneau « Quoi de neuf » (diff du dernier run). Pas de bouton Refresh dans le HTML.

---

## 7. Interface

- HTML/JS vanilla, style **QuickerBridge** : tokens `--navy #102d41`, `--teal #007f78`, `--bg #f0f4f7`, `--line #dce5eb`, `--ink #17374b`, Segoe UI, topbar navy.
- **Carte** : Leaflet 1.9.4 + tuiles OSM ou CARTO (sans clé API), rendu canvas + clustering.
- **Layout** : topbar · panneau de filtres à gauche · carte dominante · bandeau de stats live · liste / fiche latérale.
- **Filtres** : famille (pont par défaut), région / DT, réseau, ICG, IAS, hauteur libre < X, limitation de poids, année de construction, recherche par mot-clé (index normalisé sans accents).
- Marqueurs colorés selon l'ICG ; **icônes de type redessinées en SVG** par famille (poutres, dalle, portique, béquilles, caisson, arc/voûte, treillis, acier-bois, couvert, suspendu/haubans, ponceau, mur, tunnel).
- Français uniquement.

---

## 8. Statistiques

Compteurs live selon les filtres, répartition ICG / IAS, histogramme des années de construction, types par région, longueur / largeur moyennes, DJMA, structures fermées.

---

## 9. Feuille de route

| Phase | Contenu | Durée | Critère de sortie |
|---|---|---|---|
| **P0** | Squelette du dépôt + thème | ½ j | Arborescence, dépendances, page vide au thème QuickerBridge |
| **P1** | ETL WFS + liste APEX + hauteurs + GPS → SQLite ; qualifier l'écart 11 701 / 9 880 | 1–2 j | `python -m etl update` remplit la BD, rapport de jointure |
| **P2** | Export + carte + filtres de base | 2 j | Visualiseur local filtrable |
| **P3** | Crawl des fiches (passe unique) + champs enrichis | 1 j + run | DJMA, % camion, etc. dans la BD |
| **P4** | Stats, icônes SVG, fiche détaillée, polish | 2 j | Interface complète |
| **P5** | Mise à jour incrémentale + journal des changements | 1 j | Run incrémental < 5 min, diff affiché |
| **P6** | GitHub Pages + Action cron + README / attribution | ½ j | Site public mis à jour automatiquement |

---

## 10. Risques et mitigations

| Risque | Mitigation |
|---|---|
| Changement du HTML APEX | Parseurs tolérants, tests sur fixtures HTML enregistrées |
| Checksum `cs` des URL de fiche | Reprendre l'URL fournie par la liste |
| Charge sur les serveurs du MTMD | Throttle 1 req/s, plage nocturne, incrémental |
| Politique d'usage des tuiles OSM | Attribution ; CARTO en alternative |
| Licence | WFS en CC-BY 4.0 ; contenu APEX : attribution MTMD, conditions à confirmer avant publication |
| Poids du JS | Format colonnaire, fichier de détails séparé |

---

## 11. Décisions ouvertes

1. Afficher les ~1 800 structures du WFS absentes de l'outil public ? *(défaut : masquées, avec drapeau)*
2. Nom du projet / du dépôt GitHub.
3. Fournisseur de tuiles (OSM vs CARTO).

---

## 12. Prochaine action

Lancer **P0 + P1**.

---

*Sources : [Données Québec — Structure](https://donneesquebec.ca/recherche/dataset/structure) · [Inventaire et inspection des structures (MTMD)](https://www.transports.gouv.qc.ca/fr/projets-infrastructures/structures/Pages/inventaires-structures.aspx) · [Répertoire des hauteurs libres](https://www.transports.gouv.qc.ca/fr/entreprises-partenaires/ent-camionnage/hauteurs-libres/Pages/DHLDetails.aspx)*
