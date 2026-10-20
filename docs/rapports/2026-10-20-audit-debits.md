# Audit des débits « sur » et « sous » la structure (v0.6.4, 2026-10-20)

Demande (Notion, v0.6.4) : vérifier que les DJMA des structures sont bien associés, sur et sous la structure.

**Méthode.** Les 11 701 structures géolocalisées sont réappariées aux 7 908 sections de trafic du MTMD (WFS `ms:circulation_routier`, copie du 2026-10-11), puis neuf contrôles sont faits automatiquement. Les cas suspects sont ensuite vérifiés un par un. Script : `audit_djma.py` (hors dépôt) ; règles : `etl/debits.py`.

## Ce qui n'allait pas

**1. Le n° de route lu dans la limite d'une section.** Quand le n° du RTSS ne concordait pas, l'appariement lisait le n° dans la description du début de la section. Or ce libellé nomme la **limite** de la section, donc la route croisée, pas la route comptée.

Exemple : 09766W, A-15 Sud au-dessus de la route 117. La section de l'A-15 commence à « R-117, Val-Morin ». Elle était donc prise aussi pour la route 117, et la fiche affichait **26 000 véh./j « sous la structure »** : le trafic de l'A-15, pas celui de la 117.

Même erreur « dessus » : 03871 « Route 125 » affichait le trafic de la route 339 ; 03972 « Route 171 » celui de la 116.

**2. Une même section dessus et dessous.** 126 structures. Exemple : 09703, A-40 au-dessus du raccordement A-15 S / A-40 E. Le n° 40 figure dans les deux libellés, et la même section de l'A-40 était affichée sur et sous l'ouvrage.

**3. Bretelles et raccordements.** Une « Bretelle de l'A-15 Sud vers l'A-40 Ouest » cite deux autoroutes. Elle recevait le trafic de l'une d'elles, ou de l'autoroute voisine en repli. Or le jeu de données ne compte pas les bretelles.

**4. Section affichée.** Quand plusieurs sections étaient retenues (deux chaussées, section voisine), la fiche montrait la plus proche, même si une autre était bien plus cohérente avec le DJMA de la fiche.

## Corrections (etl/debits.py)

- Le n° d'une section vient de son **RTSS seulement**. Le libellé de début n'est plus utilisé.
- Une section n'est **jamais à la fois portée et franchie**. Un n° commun aux deux voies désigne la voie portée.
- **Bretelles, raccordements, échangeurs, voies de service, virages en U** : aucune section numérotée et aucun repli. Le n° cité dans leur nom ne sert pas non plus à chercher la route du dessous.
- **Replis géométriques** (< 40 m) : ils ne prennent jamais une section de la route citée de l'autre côté de l'ouvrage.
- **Section affichée** : parmi les sections portées retenues, celle dont le DJMA est le plus proche de la fiche passe en tête.

## Résultat

| Contrôle | Avant | Après |
|---|---|---|
| Même section sur et sous | 126 | **0** |
| Même DJMA affiché sur et sous | 71 | **0** |
| Même n° de route sur et sous | 133 | **0** |
| Section « sur » portant le n° de la route franchie | 21 | **0** |
| Section « sous » portant le n° de la route portée | 21 | **0** |
| Structures avec un débit « sur » | 6 186 | 5 764 |
| Structures avec un débit « sous » | 1 090 | 988 |

Au total, **288 structures** changent dans la fiche :

- 173 débits « sur » faux sont retirés ;
- 75 débits « sur » sont remplacés par une section plus cohérente ;
- 53 débits « sous » faux sont retirés.

Dans la dizaine de cas vérifiés à la main, les débits retirés étaient tous faux. Pour une bretelle, mieux vaut ne rien afficher que le débit de l'autoroute.

## Écarts restants avec la fiche (pas des erreurs)

Le débit « sur » s'écarte de plus du double de celui de la fiche pour 537 des 3 952 structures qui ont les deux valeurs. **Médiane : 1,08.**

La plupart de ces écarts viennent des ponts d'une seule chaussée (n° en N/S/E/W, « Autoroute 20 Ouest ») : la fiche donne le débit d'un sens, la section de comptage additionne les deux sens. Exemple : 00671N, fiche 21 500, section 46 000.

La fiche le dit maintenant : « Fiche du MTMD : 21 500 véh./j pour ce sens ; la section de comptage additionne les deux sens. » Pour les autres écarts, elle indique « autre année ou autre tronçon de comptage ».

## Limites

- Les **57 structures** au-dessus d'une route numérotée sans débit « sous » sont surtout des bretelles. Il y a aussi des routes en multiplex (route 223 sous l'A-35 à Saint-Jean, route 117 sous l'A-15) qui n'ont pas de section à leur n° près de l'ouvrage.
- Les **replis approximatifs** (sans concordance de n°) restent signalés « (approx.) » : 724 « sur » et 81 « sous ».

Tests : 4 nouveaux tests de non-régression dans `tests/test_debits.py`.
