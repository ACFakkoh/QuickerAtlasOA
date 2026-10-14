"""Precalcul / cache des appels a l'API GraphQL CanSHM6 (RNCan) pour le prototype sismique.
- Respecte l'API : >= 0,6 s entre requetes, cache JSON local (cache/), compteur de points (budget total 300).
- Usage : python precalcul_sismique.py [exemples|montreal|grille|tout]
Sorties : cache/exemples.json, cache/montreal_ouvrages.json, cache/grille_pga_qc.json, donnees_sismique.js
"""
import json, os, sys, time, hashlib, math, random
import requests

ICI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ICI, 'cache')
RACINE = os.path.abspath(os.path.join(ICI, '..', '..'))
URL = 'https://www.earthquakescanada.nrcan.gc.ca/api/canshm/graphql'
CHAMPS = 'vs30 poe50 foe pga pgv sa0p05 sa0p1 sa0p2 sa0p3 sa0p5 sa1p0 sa2p0 sa5p0 sa10p0'
PAUSE = 0.6
BUDGET = 300
LOG = os.path.join(CACHE, 'compteur_points.json')

def compteur():
    return json.load(open(LOG)) if os.path.exists(LOG) else {'points': 38, 'requetes': 7}  # 38 pts / 7 req deja utilises en exploration

def gql(query, npts):
    """POST avec cache disque (cle = hash de la requete)."""
    h = hashlib.sha1(query.encode()).hexdigest()[:16]
    f = os.path.join(CACHE, 'req_%s.json' % h)
    if os.path.exists(f):
        return json.load(open(f, encoding='utf-8'))
    c = compteur()
    if c['points'] + npts > BUDGET:
        raise SystemExit('budget de points depasse (%d + %d > %d)' % (c['points'], npts, BUDGET))
    time.sleep(PAUSE)
    r = requests.post(URL, json={'query': query}, timeout=120)
    r.raise_for_status()
    d = r.json()
    if 'errors' in d: raise RuntimeError(d['errors'])
    json.dump(d, open(f, 'w', encoding='utf-8'))
    c['points'] += npts; c['requetes'] += 1
    json.dump(c, open(LOG, 'w'))
    return d

def charger_structures():
    s = open(os.path.join(RACINE, 'data', 'structures.js'), encoding='utf-8').read()
    j = json.loads(s[s.find('=') + 1:].rstrip().rstrip(';'))
    ix = {k: i for i, k in enumerate(j['cols'])}
    out = []
    for r in j['rows']:
        if r[ix['lat']] is None or r[ix['lon']] is None: continue
        out.append({k: r[ix[k]] for k in ('num', 'nom', 'route', 'obstacle', 'muncp', 'lat', 'lon', 'long', 'annee', 'type')})
    return out

EXEMPLES = ['03226', '13247A', '04296', '13628', '14324', '14346C', '14949N', '17666', '11148', '11117', '07117']

def exemples():
    S = {s['num']: s for s in charger_structures()}
    out = {}
    for num in EXEMPLES:
        s = S[num]
        q = '{ NBC2025(latitude:%s, longitude:%s){ metadata{zones} %s } }' % (
            s['lat'], s['lon'], ' '.join('%s:siteDesignationsXs(siteClass:%s){ %s }' % (c, c, CHAMPS) for c in 'ABCDE'))
        d = gql(q, 1)['data']['NBC2025']
        out[num] = {'ouvrage': s, 'zones': d['metadata']['zones'], 'classes': {c: d[c] for c in 'ABCDE'}}
        print(num, s['nom'] or s['route'], 'PGA 2% C =', d['C'][0]['pga'])
    json.dump(out, open(os.path.join(CACHE, 'exemples.json'), 'w', encoding='utf-8'), ensure_ascii=False)

def classe_mtl(grille, lat, lon):
    j = int((grille['north'] - lat) // grille['step']); i = int((lon - grille['west']) // grille['step'])
    if 0 <= j < grille['ny'] and 0 <= i < grille['nx']:
        return '0ABCDE'.index(grille['rows'][j][i])
    return 0

def montreal(n_par_classe=8):
    g = json.load(open(os.path.join(CACHE, 'grille_classes_site_mtl.json')))
    random.seed(7)
    par = {k: [] for k in range(1, 6)}
    for s in charger_structures():
        k = classe_mtl(g, s['lat'], s['lon'])
        if k and (s['long'] or 0) >= 30: par[k].append(s)
    print({k: len(v) for k, v in par.items()})
    choix = []
    for k, v in par.items():
        random.shuffle(v); choix += [(k, s) for s in v[:n_par_classe]]
    out = []
    for lot in range(0, len(choix), 10):
        sub = choix[lot:lot + 10]
        q = '{ ' + ' '.join('p%d:NBC2025(latitude:%s,longitude:%s){ siteDesignationsXs(siteClass:%s,poe50:[2]){ pga pgv sa0p2 sa1p0 } }' % (i, s['lat'], s['lon'], 'ABCDE'[k - 1]) for i, (k, s) in enumerate(sub)) + ' }'
        d = gql(q, len(sub))['data']
        for i, (k, s) in enumerate(sub):
            p = d['p%d' % i]
            v = p['siteDesignationsXs'][0] if p and p['siteDesignationsXs'] else None
            out.append({**s, 'classe': 'ABCDE'[k - 1], 'aleas': v})
    json.dump(out, open(os.path.join(CACHE, 'montreal_ouvrages.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(len(out), 'ouvrages Montreal')

def montreal_complet():
    """Toutes classes x toutes probabilites pour les 35 ouvrages de Montreal (5 ouvrages par requete)."""
    mt = json.load(open(os.path.join(CACHE, 'montreal_ouvrages.json'), encoding='utf-8'))
    for lot in range(0, len(mt), 5):
        sub = mt[lot:lot + 5]
        q = '{ ' + ' '.join('p%d:NBC2025(latitude:%s,longitude:%s){ %s }' % (i, s['lat'], s['lon'], ' '.join('%s:siteDesignationsXs(siteClass:%s){ %s }' % (c, c, CHAMPS) for c in 'ABCDE')) for i, s in enumerate(sub)) + ' }'
        d = gql(q, len(sub))['data']
        for i, s in enumerate(sub):
            p = d['p%d' % i]
            s['classes'] = {c: p[c] for c in 'ABCDE'} if p else None
    json.dump(mt, open(os.path.join(CACHE, 'montreal_complet.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(len(mt), 'ouvrages Montreal (5 classes x 10 probabilites)')

def points_grille():
    S = charger_structures()
    pts = []
    for la in [45.0 + 1.0 * i for i in range(0, 8)]:
        for lo in [-79.0 + 1.0 * k for k in range(0, 23)]:
            if any(abs(s['lat'] - la) < 0.55 and abs(s['lon'] - lo) < 0.7 for s in S): pts.append((la, lo))
    # patch plus fin Charlevoix - Saguenay (0,5 deg) : zone de hausse d'alea
    fin = [(la, lo) for la in (46.5, 47.0, 47.5, 48.0, 48.5) for lo in (-72.0, -71.5, -71.0, -70.5, -70.0, -69.5, -69.0)]
    pts = [p for p in pts if not (46.25 <= p[0] <= 48.75 and -72.25 <= p[1] <= -68.75)] + fin
    return pts

def grille():
    pts = points_grille()
    print(len(pts), 'points de grille')
    out = []
    for lot in range(0, len(pts), 10):
        sub = pts[lot:lot + 10]
        q = '{ ' + ' '.join('p%d:NBC2025(latitude:%s,longitude:%s){ siteDesignationsXv(vs30:450,poe50:[2]){ pga sa0p2 sa1p0 } }' % (i, la, lo) for i, (la, lo) in enumerate(sub)) + ' }'
        d = gql(q, len(sub))['data']
        for i, (la, lo) in enumerate(sub):
            p = d['p%d' % i]
            v = p['siteDesignationsXv'][0] if p and p['siteDesignationsXv'] else None
            out.append({'lat': la, 'lon': lo, 'v': v})
    json.dump(out, open(os.path.join(CACHE, 'grille_pga_qc.json'), 'w'))
    print(sum(1 for o in out if o['v']), 'valides')

def _compact(rows):
    ks = ['pga', 'pgv', 'sa0p05', 'sa0p1', 'sa0p2', 'sa0p3', 'sa0p5', 'sa1p0', 'sa2p0', 'sa5p0', 'sa10p0']
    return [[r['poe50']] + [r[k] for k in ks] for r in rows]

def exporter_js():
    ex = json.load(open(os.path.join(CACHE, 'exemples.json'), encoding='utf-8'))
    mt = json.load(open(os.path.join(CACHE, 'montreal_complet.json'), encoding='utf-8'))
    gr = json.load(open(os.path.join(CACHE, 'grille_pga_qc.json')))
    cl = json.load(open(os.path.join(CACHE, 'grille_classes_site_mtl.json')))
    for e in ex.values(): e['classes'] = {c: _compact(v) for c, v in e['classes'].items()}
    for m in mt:
        m['classes'] = {c: _compact(v) for c, v in m['classes'].items()} if m.get('classes') else None
        if m.get('aleas'): m['aleas'] = {k: m['aleas'][k] for k in ('pga', 'pgv', 'sa0p2', 'sa1p0')}
    gr = [{'lat': g['lat'], 'lon': g['lon'], 'v': ({k: g['v'][k] for k in ('pga', 'sa0p2', 'sa1p0')} if g['v'] else None)} for g in gr]
    data = {'genere': time.strftime('%Y-%m-%d'), 'colonnes': ['poe50', 'pga', 'pgv', 'sa0p05', 'sa0p1', 'sa0p2', 'sa0p3', 'sa0p5', 'sa1p0', 'sa2p0', 'sa5p0', 'sa10p0'],
            'exemples': ex, 'montreal': mt, 'grille': gr, 'classesMtl': cl}
    open(os.path.join(ICI, 'donnees_sismique.js'), 'w', encoding='utf-8').write(
        '/* Genere par precalcul_sismique.py - donnees RNCan (CanSHM6 / CNBC 2025) + classes de site Rosset et al. 2023 (CC BY 4.0) */\nwindow.SISMIQUE='
        + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n')
    print('donnees_sismique.js', os.path.getsize(os.path.join(ICI, 'donnees_sismique.js')) // 1024, 'Ko')

if __name__ == '__main__':
    os.makedirs(CACHE, exist_ok=True)
    a = sys.argv[1] if len(sys.argv) > 1 else 'tout'
    if a == 'compte': print(points_grille().__len__(), compteur()); sys.exit()
    if a in ('exemples', 'tout'): exemples()
    if a in ('montreal', 'tout'): montreal()
    if a in ('grille', 'tout'): grille()
    if a in ('mtl2', 'tout'): montreal_complet()
    if a in ('js', 'tout'): exporter_js()
    print(compteur())

