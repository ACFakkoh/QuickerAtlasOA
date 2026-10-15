/* « Cours d'eau au pont » : fenêtre de QuickerAtlasOA pour les ouvrages au-dessus d'un cours d'eau.
   Module chargé à la demande (openAux). Contrat : window.QA_MOD.hydro.render(o, body, ctx).
   Sources (toutes interrogeables depuis le navigateur, CORS ouvert) :
   - MELCCFP, ArcGIS REST : couche 101 (ordre de Strahler), 27 à 34 (bassins nommés), 22 (zones inondables BDZI) ;
   - ECCC, API OGC : stations, statistiques annuelles et moyennes mensuelles (HYDAT) ;
   - MRNF : GRHQ simple (tuiles WMS, image seulement).
   v0.6.0 : les repères (Strahler, bassin, zone inondable, station, maximum et étiage) sont réunis dans un tableau
   récapitulatif (classe qa-recap, styles injectés par le module) au lieu de cartes côte à côte. */
(function(){
  'use strict';
  window.QA_MOD = window.QA_MOD || {};

  var MELCC = 'https://www.servicesgeo.enviroweb.gouv.qc.ca/donnees/rest/services/Public/Themes_publics/MapServer';
  var ECCC = 'https://api.weather.gc.ca/collections/';
  var GRHQ = 'https://servicescarto.mrnf.gouv.qc.ca/pes/services/Territoire/GRHQ_simple_WMS/MapServer/WMSServer';
  var GRHQ_LAYERS = '1,2,3,4,5,6,7,9,10,11,12,13,14,15,16,18,19,20,21';
  var KM_MAX = 40;       // rayon de recherche de la station (km)
  var KM_FAR = 25;       // au-delà : avertissement « station éloignée »
  var CACHE = {};        // par n° de structure : promesses des blocs (reprise instantanée à la réouverture)
  var cur = { map: null, onResize: null };

  /* ================= Outils (purs, testables) ================= */
  function esc(s){
    var q = window.QA;
    if (q && q.esc) return q.esc(s);
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){ return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
  }
  var NF = [0, 1, 2].map(function(d){ return new Intl.NumberFormat('fr-CA', { minimumFractionDigits: d, maximumFractionDigits: d }); });
  function fmt(v, dec){ return NF[dec].format(v); }
  // Débits : 0 décimale au-delà de 100, 1 au-delà de 10 ; niveaux : 2 décimales
  function fmtQ(v){ var a = Math.abs(v); return fmt(v, a >= 100 ? 0 : a >= 10 ? 1 : 2); }
  function qs(o){ return Object.keys(o).map(function(k){ return encodeURIComponent(k) + '=' + encodeURIComponent(o[k]); }).join('&'); }
  var distM = function(la1, lo1, la2, lo2){
    var p = Math.PI / 180, x = Math.pow(Math.sin((la2 - la1) * p / 2), 2) + Math.cos(la1 * p) * Math.cos(la2 * p) * Math.pow(Math.sin((lo2 - lo1) * p / 2), 2);
    return 12742000 * Math.asin(Math.sqrt(x));
  };
  function median(v){ var s = v.slice().sort(function(a, b){ return a - b; }), n = s.length; if (!n) return null; return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; }
  function niceStep(v){ var p = Math.pow(10, Math.floor(Math.log10(v || 1))), f = v / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; }
  function fmtDate(iso){
    var d = new Date(String(iso).slice(0, 10) + 'T12:00:00');
    return isNaN(d) ? String(iso || '') : d.toLocaleDateString('fr-CA', { day: 'numeric', month: 'long', year: 'numeric' });
  }

  // Noms : sans accents ni mots vides ; « saint » et « sainte » ramenés à st / ste (les stations écrivent ST-, STE-)
  var STOP = {};
  'riviere ruisseau cours eau deau de du des la le les l d au aux a en aval amont pont route decharge dech branche bras fleuve'.split(' ').forEach(function(w){ STOP[w] = 1; });
  function tokens(s){
    var x = String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    return x.split(/[^a-z0-9]+/).map(function(w){ return w === 'saint' ? 'st' : w === 'sainte' ? 'ste' : w; }).filter(function(w){ return w && !STOP[w]; });
  }
  function subset(a, b){ // tous les mots de a sont dans b
    if (!a.length) return false;
    var set = {}; b.forEach(function(w){ set[w] = 1; });
    return a.every(function(w){ return set[w]; });
  }
  // Noms de stations ECCC en majuscules sans accents : mise en forme lisible
  var ACC = { a: 'à', pres: 'près', centrale: 'centrale', riviere: 'rivière', chaudiere: 'chaudière', francois: 'françois', quebec: 'québec', etienne: 'étienne', eglise: 'église', ile: 'île',
    epiphanie: 'épiphanie', ecluse: 'écluse', decharge: 'décharge', valerien: 'valérien', jerome: 'jérôme', chene: 'chêne', rene: 'rené', andre: 'andré',
    therese: 'thérèse', cesaire: 'césaire', levis: 'lévis', gedeon: 'gédéon', desert: 'désert', belanger: 'bélanger', mere: 'mère', pere: 'père', eau: 'eau', grace: 'grâce', hebert: 'hébert', theophile: 'théophile' };
  function titleCase(s){
    var r = String(s || '').toLowerCase().replace(/[a-z]+/g, function(w){ return ACC[w] || w; });
    r = r.replace(/(^|[\s(\-'])([a-zà-ÿ])/g, function(m, a, b){ return a + b.toUpperCase(); });
    r = r.replace(/(^|[\s(\-])(Du|De|Des|La|Le|Au|Aux|En|Et|Sur|À)(?=[\s)\-])/g, function(m, a, w){ return a + w.toLowerCase(); });
    return r.replace(/^./, function(c){ return c.toUpperCase(); });
  }

  // CSV de l'API OGC d'ECCC : 4 à 6 fois plus léger que le GeoJSON (x,y = longitude, latitude de la station)
  var NUMK = { x: 1, y: 1, MAX_VALUE: 1, MIN_VALUE: 1, DRAINAGE_AREA_GROSS: 1, MONTHLY_MEAN_LEVEL: 1, MONTHLY_MEAN_DISCHARGE: 1 };
  function parseCsv(txt){
    var rows = [], row = [], f = '', inq = false, i, c, n = txt.length;
    for (i = 0; i < n; i++) {
      c = txt.charAt(i);
      if (inq) { if (c === '"') { if (txt.charAt(i + 1) === '"') { f += '"'; i++; } else inq = false; } else f += c; }
      else if (c === '"') inq = true;
      else if (c === ',') { row.push(f); f = ''; }
      else if (c === '\n') { row.push(f); rows.push(row); row = []; f = ''; }
      else if (c !== '\r') f += c;
    }
    if (f.length || row.length) { row.push(f); rows.push(row); }
    var h = rows.shift() || [];
    return rows.filter(function(r){ return r.length === h.length; }).map(function(r){
      var o = {}; h.forEach(function(k, j){ var v = r[j]; o[k] = v === '' ? null : (NUMK[k] && isFinite(+v) ? +v : v); }); return o;
    });
  }

  /* ---------- Station la plus proche ---------- */
  // rows = lignes CSV des stations ; renvoie { best, n } ; best.match = 'oui' | 'non' | 'inconnu' (même cours d'eau que l'ouvrage ?)
  // « Plus proche » avec un léger avantage (3 km) à une station du même nom : évite un affluent à 100 m au lieu de la rivière à 1 km.
  function pickStation(rows, lat, lon, obst, maxKm){
    var ot = tokens(obst), out = [];
    rows.forEach(function(r){
      if (r.x == null || r.y == null) return;
      var d = distM(lat, lon, r.y, r.x) / 1000;
      if (d > maxKm) return;
      var m = ot.length ? (subset(ot, tokens(r.STATION_NAME)) ? 'oui' : 'non') : 'inconnu';
      out.push({ id: r.STATION_NUMBER, nom: r.STATION_NAME, act: r.STATUS_EN === 'Active', area: r.DRAINAGE_AREA_GROSS, datum: r.VERTICAL_DATUM, lat: r.y, lon: r.x, d: d, match: m, score: d + (m === 'non' ? 3 : 0) });
    });
    out.sort(function(a, b){ return a.score - b.score; });
    return { best: out[0] || null, n: out.length };
  }
  // Référentiel vertical de la station : 'arbitraire' (zéro d'échelle), 'geodesique' (altitudes) ou 'inconnu'
  function datumKind(s){
    var t = String(s || '').toUpperCase();
    if (!t) return 'inconnu';
    if (/ARBITRAIRE|ASSUMED/.test(t)) return 'arbitraire';
    if (/GEODE|GRANDS LACS|GEODETIC/.test(t)) return 'geodesique';
    return 'inconnu';
  }

  /* ---------- Séries annuelles ---------- */
  function yearOf(r){
    var m = /\.(\d{4})\./.exec(r.IDENTIFIER || '');
    if (m) return +m[1];
    var d = r.MAX_DATE || r.MIN_DATE;
    return d ? +String(d).slice(0, 4) : null;
  }
  // Moyenne annuelle approchée = moyenne des 12 moyennes mensuelles (années complètes seulement)
  function monthlyMeans(mon, key){
    var by = {}, out = {};
    (mon || []).forEach(function(r){
      if (r[key] == null || !r.DATE) return;
      var y = +String(r.DATE).slice(0, 4); by[y] = by[y] || { n: 0, s: 0 }; by[y].n++; by[y].s += r[key];
    });
    Object.keys(by).forEach(function(y){ if (by[y].n === 12) out[y] = by[y].s / 12; });
    return out;
  }
  // type = 'Water Level' | 'Discharge' ; renvoie [{y, max, maxD, min, minD, mean}] trié par année
  function buildSeries(ann, mon, type){
    var means = monthlyMeans(mon, type === 'Water Level' ? 'MONTHLY_MEAN_LEVEL' : 'MONTHLY_MEAN_DISCHARGE'), rows = [];
    (ann || []).forEach(function(r){
      if (r.DATA_TYPE_EN !== type) return;
      var y = yearOf(r); if (y == null || (r.MAX_VALUE == null && r.MIN_VALUE == null)) return;
      var mean = means[y] != null ? means[y] : null;
      if (mean != null && ((r.MAX_VALUE != null && mean > r.MAX_VALUE) || (r.MIN_VALUE != null && mean < r.MIN_VALUE))) mean = null;
      rows.push({ y: y, max: r.MAX_VALUE, maxD: r.MAX_DATE, min: r.MIN_VALUE, minD: r.MIN_DATE, mean: mean });
    });
    rows.sort(function(a, b){ return a.y - b.y; });
    return rows;
  }
  // Niveau de préférence (au moins 5 années), sinon débit
  function pickSeries(lvl, dis){
    if (lvl.length >= 5) return { kind: 'niveau', unit: 'm', rows: lvl };
    if (dis.length) return { kind: 'debit', unit: 'm³/s', rows: dis };
    if (lvl.length) return { kind: 'niveau', unit: 'm', rows: lvl };
    return null;
  }
  // Repères : maximum enregistré, étiage (médiane des minimums annuels, plus bas enregistré)
  function summary(rows){
    var mx = null, mn = null, mins = [];
    rows.forEach(function(r){
      if (r.max != null && (!mx || r.max > mx.v)) mx = { v: r.max, d: r.maxD };
      if (r.min != null) { mins.push(r.min); if (!mn || r.min < mn.v) mn = { v: r.min, d: r.minD }; }
    });
    return { n: rows.length, y0: rows[0].y, y1: rows[rows.length - 1].y, maxRec: mx, minRec: mn, medMin: median(mins), nMin: mins.length };
  }

  /* ---------- Géométrie (mètres locaux autour de l'ouvrage) ---------- */
  function kxy(lat0){ return [111320 * Math.cos(lat0 * Math.PI / 180), 110540]; }
  function segDist(ax, ay, bx, by){ // distance de l'origine au segment AB
    var dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy, t = l2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / l2)) : 0, px = ax + t * dx, py = ay + t * dy;
    return Math.sqrt(px * px + py * py);
  }
  // Distance minimale (m) de l'ouvrage à des lignes [[lon,lat],…]
  function linesDist(lat0, lon0, lines){
    var k = kxy(lat0), best = 1e9;
    lines.forEach(function(ln){
      for (var i = 1; i < ln.length; i++) best = Math.min(best, segDist((ln[i - 1][0] - lon0) * k[0], (ln[i - 1][1] - lat0) * k[1], (ln[i][0] - lon0) * k[0], (ln[i][1] - lat0) * k[1]));
    });
    return best;
  }
  // Point dans des anneaux (règle pair/impair : les trous comptent d'eux-mêmes)
  function inRings(lat0, lon0, rings){
    var k = kxy(lat0), ins = false;
    rings.forEach(function(ring){
      for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        var xi = (ring[i][0] - lon0) * k[0], yi = (ring[i][1] - lat0) * k[1], xj = (ring[j][0] - lon0) * k[0], yj = (ring[j][1] - lat0) * k[1];
        if ((yi > 0) !== (yj > 0) && (0 < (xj - xi) * (0 - yi) / (yj - yi) + xi)) ins = !ins;
      }
    });
    return ins;
  }
  // Tronçon de Strahler le plus proche : features Esri JSON { attributes:{O_STRAHLER,PERENNITE}, geometry:{paths} }
  function nearestReach(feats, lat0, lon0){
    var best = null;
    (feats || []).forEach(function(f){
      var paths = f.geometry && f.geometry.paths; if (!paths) return;
      var d = linesDist(lat0, lon0, paths);
      if (!best || d < best.d) best = { d: d, ord: f.attributes.O_STRAHLER, per: f.attributes.PERENNITE, paths: paths };
    });
    return best;
  }
  // Zone inondable : celle qui contient l'ouvrage ou, à défaut, la plus proche ; à égalité, le grand courant
  function zoneAt(feats, lat0, lon0){
    var best = null;
    (feats || []).forEach(function(f){
      var rings = f.geometry && f.geometry.rings; if (!rings) return;
      var d = inRings(lat0, lon0, rings) ? 0 : linesDist(lat0, lon0, rings), a = f.attributes || {};
      if (!best || d < best.d || (d === best.d && /grand/i.test(a.Description || ''))) best = { d: d, desc: a.Description || 'Zone inondable', rapport: a.No_rapport, titre: a.Nm_rapport };
    });
    return best;
  }
  function recurrence(desc){ return /grand/i.test(desc) ? '0-20 ans' : /faible/i.test(desc) ? '20-100 ans' : ''; }
  // Bassins nommés (identify, niveau 1 = le plus grand) : le plus fin contenant l'ouvrage
  function deepBasin(results){
    var bas = (results || []).map(function(x){
      var a = x.attributes || {};
      return { lvl: +a['Niveau'], nom: a['Nom_bassin'], km2: parseFloat(String(a['Superficie_(km2)']).replace(',', '.')) };
    }).filter(function(b){ return b.nom && isFinite(b.km2); }).sort(function(a, b){ return a.lvl - b.lvl; });
    return bas.length ? bas[bas.length - 1] : null;
  }
  function strahlerWord(o){
    if (o == null) return '';
    if (o === 0) return 'non classé (plan d’eau ou tronçon isolé)';
    return o <= 1 ? 'ruisselet' : o <= 3 ? 'petit cours d’eau' : o <= 5 ? 'rivière' : 'grande rivière';
  }
  var PER = { P: 'écoulement permanent', I: 'écoulement intermittent', NA: 'surface d’eau' };

  /* ================= Requêtes ================= */
  // Le serveur du MELCCFP laisse parfois une requête sans réponse (jusqu'au délai de 15 s) alors que la même, relancée, répond en 0,2 s.
  // Requête « de secours » : relancée tout de suite en cas d'échec, ou après 4 s sans réponse ; la première réponse valide l'emporte.
  function hedged(make){
    return new Promise(function(resolve, reject){
      var done = false, n = 0, fails = 0, timer = null;
      function launch(){
        n++;
        make().then(function(v){ if (!done) { done = true; clearTimeout(timer); resolve(v); } }, function(e){
          fails++;
          if (done) return;
          if (n < 2) { clearTimeout(timer); launch(); }
          else if (fails >= n) { done = true; reject(e); }
        });
      }
      launch();
      timer = setTimeout(function(){ if (!done && n < 2) launch(); }, 4000);
    });
  }
  function esri(url){
    var Q = window.QA;
    return hedged(function(){ return Q.fetchT(url, {}, 15000, 'json').then(function(j){ if (j && j.error) throw new Error(j.error.message || 'erreur du service'); return j; }); });
  }
  function ogc(coll, params){
    var Q = window.QA, url = ECCC + coll + '/items?' + qs(params);
    return hedged(function(){ return Q.fetchT(url, {}, 15000, 'text'); }).then(parseCsv);
  }
  function cached(E, k, make){
    if (!E[k]) { var p = make(); E[k] = p; p.catch(function(){ if (E[k] === p) delete E[k]; }); }
    return E[k];
  }
  function qStrahler(o){
    return esri(MELCC + '/101/query?' + qs({ f: 'json', geometry: o.lon + ',' + o.lat, geometryType: 'esriGeometryPoint', inSR: 4326, outSR: 4326, distance: 800, units: 'esriSRUnit_Meter',
      spatialRel: 'esriSpatialRelIntersects', outFields: 'O_STRAHLER,PERENNITE', returnGeometry: 'true', maxAllowableOffset: 0.00003 }));
  }
  function qBassin(o){
    return esri(MELCC + '/identify?' + qs({ f: 'json', geometry: o.lon + ',' + o.lat, geometryType: 'esriGeometryPoint', sr: 4326, layers: 'all:27,28,29,30,31,32,33,34', tolerance: 3,
      mapExtent: (o.lon - 0.01) + ',' + (o.lat - 0.01) + ',' + (o.lon + 0.01) + ',' + (o.lat + 0.01), imageDisplay: '400,400,96', returnGeometry: 'false' }));
  }
  function qZone(o){ // maxAllowableOffset ≈ 10 m : 370 Ko deviennent 23 Ko
    return esri(MELCC + '/22/query?' + qs({ f: 'json', geometry: o.lon + ',' + o.lat, geometryType: 'esriGeometryPoint', inSR: 4326, outSR: 4326, distance: 1200, units: 'esriSRUnit_Meter',
      spatialRel: 'esriSpatialRelIntersects', outFields: 'Description,No_rapport,Nm_rapport', returnGeometry: 'true', maxAllowableOffset: 0.0001 }));
  }
  function qStations(o){
    var dlat = KM_MAX / 110.5, dlon = KM_MAX / (111.3 * Math.cos(o.lat * Math.PI / 180));
    return ogc('hydrometric-stations', { f: 'csv', limit: 300, bbox: [o.lon - dlon, o.lat - dlat, o.lon + dlon, o.lat + dlat].map(function(v){ return v.toFixed(4); }).join(','),
      properties: 'STATION_NUMBER,STATION_NAME,STATUS_EN,DRAINAGE_AREA_GROSS,VERTICAL_DATUM' }).then(function(rows){ return pickStation(rows, o.lat, o.lon, o.obstacle, KM_MAX); });
  }
  function qSeries(id){
    var pa = ogc('hydrometric-annual-statistics', { f: 'csv', limit: 1000, STATION_NUMBER: id, properties: 'IDENTIFIER,DATA_TYPE_EN,MAX_VALUE,MAX_DATE,MIN_VALUE,MIN_DATE' });
    var pm = ogc('hydrometric-monthly-mean', { f: 'csv', limit: 3000, STATION_NUMBER: id, properties: 'DATE,MONTHLY_MEAN_LEVEL,MONTHLY_MEAN_DISCHARGE' }).catch(function(){ return []; });  // moyenne : facultative
    return Promise.all([pa, pm]).then(function(r){ return { lvl: buildSeries(r[0], r[1], 'Water Level'), dis: buildSeries(r[0], r[1], 'Discharge') }; });
  }

  /* ================= Interface ================= */
  function injectCss(){
    if (document.getElementById('qa-hydro-css')) return;
    var st = document.createElement('style'); st.id = 'qa-hydro-css';
    st.textContent =
      // v0.6.0 : tableau récapitulatif (mêmes règles que la fenêtre LiDAR, injectées ici aussi : l'un peut s'ouvrir sans l'autre)
      '.qa-recap{width:100%;border-collapse:collapse;font-size:.8rem;line-height:1.35}' +
      '.qa-recap th,.qa-recap td{padding:4px 8px;border-bottom:1px solid var(--line);vertical-align:baseline;text-align:left}' +
      '.qa-recap th{font-weight:500;color:var(--ink);white-space:nowrap}' +
      '.qa-recap td.qa-v{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;font-weight:650;color:var(--navy)}' +
      '.qa-recap td.qa-n{color:var(--muted);font-size:.75rem;width:100%}.qa-recap td.qa-n b{color:var(--ink);font-weight:600}' +
      '.qa-recap tr.qa-g th{padding:9px 8px 3px;font-size:.6875rem;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:650;border-bottom:1px solid #b9c8d2}' +
      '.qa-recap tbody:first-child tr.qa-g:first-child th{padding-top:0}' +
      '.qa-recap tr.hy-hit th{font-weight:700;color:var(--navy);box-shadow:inset 3px 0 0 var(--navy)}.qa-recap tr.hy-hit td{background:#f6f9fb}' +
      '.qa-recap td.qa-v .hy-ko{font-weight:400}' +
      '@media(max-width:600px){.qa-recap tr{display:grid;grid-template-columns:minmax(0,1fr) auto}.qa-recap th{white-space:normal}' +
      '.qa-recap td.qa-n{grid-column:1/-1;padding-top:0}.qa-recap tr:not(.qa-g) th,.qa-recap tr:not(.qa-g) td.qa-v{border-bottom:0}.qa-recap tr.qa-g th{grid-column:1/-1}}' +
      '.hy-ph{color:var(--muted);font-size:.78rem}.hy-ko{color:var(--muted);font-size:.8rem;font-style:italic}' +
      '.hy-mk-b{width:16px;height:16px;background:var(--navy);border:2px solid #fff;box-shadow:0 0 0 1px var(--navy)}' +
      '.hy-mk-s{width:14px;height:14px;transform:rotate(45deg);background:#e69f00;border:2px solid var(--navy)}' +
      '.ld-legend.hy-leg{align-items:center}.ld-legend.hy-leg i{display:inline-block;margin-right:5px;vertical-align:middle;border-radius:0}' +
      '.ld-keys.hy-keys{margin:2px 0 0;align-items:center}.ld-pf .hy-keys svg{display:inline-block;width:30px;height:12px;overflow:visible;vertical-align:middle;margin-right:5px}' +
      '.hy-pf .hy-pfh{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin:0}' +
      '.hy-lex{margin-top:12px;border:1px solid var(--line);border-radius:8px;background:#fff}' +
      '.hy-lex summary{cursor:pointer;padding:8px 12px;font-weight:700;font-size:.85rem;color:var(--navy)}' +
      '.hy-lex dl{margin:0;padding:0 12px 10px;display:grid;grid-template-columns:max-content minmax(0,1fr);gap:5px 14px;font-size:.78rem;line-height:1.45}' +
      '.hy-lex dt{font-weight:700;color:var(--navy)}.hy-lex dd{margin:0}' +
      '@media(max-width:600px){.hy-lex dl{grid-template-columns:minmax(0,1fr);gap:0}.hy-lex dd{margin:0 0 7px}}';
    document.head.appendChild(st);
  }

  var LEX = [
    ['Bassin versant', 'Territoire dont toutes les eaux s’écoulent vers un même point. La superficie affichée est celle du bassin nommé le plus fin qui contient l’ouvrage, mesurée à l’embouchure du cours d’eau : c’est une borne supérieure de la superficie réellement drainée en amont du pont.'],
    ['BDZI', 'Base de données des zones inondables (MELCCFP) : zones inondables cartographiées officiellement. Elle ne couvre pas tout le territoire : l’absence de zone ne signifie pas l’absence de risque.'],
    ['CEHQ', 'Centre d’expertise hydrique du Québec (MELCCFP). Il exploite la plupart des stations hydrométriques du Québec, dont plusieurs figurent aussi dans la base d’ECCC ; son suivi en temps réel n’est pas consulté ici.'],
    ['CC-BY 4.0', 'Licence ouverte qui autorise la réutilisation à condition de citer la source.'],
    ['Débit', 'Volume d’eau qui passe en une seconde, en mètres cubes par seconde (m³/s).'],
    ['ECCC', 'Environnement et Changement climatique Canada. Il publie les stations et les séries hydrométriques du pays.'],
    ['Étiage', 'Basses eaux : plus bas niveau ou plus faible débit d’une année. Ici, le minimum annuel des valeurs journalières (parfois en hiver, sous la glace). Ce n’est pas le débit réglementaire Q7,10 utilisé en conception.'],
    ['Grand courant, faible courant', 'Classes officielles de zones inondables : le grand courant est inondé en moyenne au moins une fois tous les 20 ans (récurrence 0-20 ans), le faible courant au moins une fois tous les 100 ans (récurrence 20-100 ans).'],
    ['GRHQ', 'Géobase du réseau hydrographique du Québec : le tracé officiel des cours d’eau et plans d’eau, avec ordre de Strahler et pérennité (MELCCFP, MRNF).'],
    ['HYDAT', 'Base nationale de données hydrométriques d’ECCC : séries de niveaux et de débits des stations. Les dernières années publiées ont souvent un an de retard.'],
    ['LiDAR', 'Relevé laser aérien du relief. Il sert au profil LiDAR de l’atlas ; ses altitudes ne sont pas rapportées au même zéro que les niveaux d’une station.'],
    ['MELCCFP', 'Ministère de l’Environnement, de la Lutte contre les changements climatiques, de la Faune et des Parcs du Québec.'],
    ['MRNF', 'Ministère des Ressources naturelles et des Forêts du Québec (fond cartographique du réseau hydrographique).'],
    ['MTMD', 'Ministère des Transports et de la Mobilité durable du Québec : source de l’inventaire des structures, dont le nom du cours d’eau.'],
    ['Niveau d’eau, élévation', 'Le niveau d’eau est la hauteur de l’eau mesurée à l’échelle de la station, comptée à partir de son zéro d’échelle. Une élévation (altitude) est comptée à partir d’un référentiel commun, le niveau moyen de la mer. Les deux ne sont comparables que si le zéro d’échelle est lié à ce référentiel.'],
    ['Ordre de Strahler', 'Classement de la taille d’un cours d’eau dans son réseau. 1 = petit ruisseau de tête ; quand deux cours d’eau de même ordre n se rejoignent, le tronçon qui suit est d’ordre n + 1. Plus l’ordre est élevé, plus le cours d’eau est important : il indique au concepteur si le franchissement est un petit ruisseau (1 à 3) ou une grande rivière (6 et plus). 0 : plan d’eau ou tronçon non classé.'],
    ['Pérennité', 'Permanent : le cours d’eau coule toute l’année. Intermittent : il s’assèche une partie de l’année.'],
    ['Récurrence', 'Fréquence moyenne d’une crue : « 20 ans » signifie une crue atteinte ou dépassée en moyenne une fois tous les 20 ans (une chance sur 20 chaque année).'],
    ['Régime influencé', 'Débits et niveaux modifiés par des barrages, des réservoirs ou des prises d’eau en amont. Ce n’est pas vérifié ici : une série influencée n’est pas représentative d’un cours d’eau naturel.'],
    ['Station hydrométrique', 'Poste de mesure du niveau d’eau et, souvent, du débit d’un cours d’eau. « En service » : encore active ; « fermée » : seul l’historique existe.'],
    ['Zéro d’échelle, datum', 'Point de départ de l’échelle de niveau de la station. Souvent arbitraire (propre à la station) ; parfois lié à un référentiel géodésique, auquel cas les niveaux sont des altitudes.']
  ];

  // Ligne du tableau récapitulatif (v0.6.0) : libellé, valeur courte (HTML), note (HTML échappé par l'appelant)
  function rowHtml(label, val, note){
    return '<th scope="row">' + esc(label) + '</th><td class="qa-v">' + val + '</td><td class="qa-n">' + (note || '') + '</td>';
  }
  function groupHtml(t){ return '<tr class="qa-g"><th colspan="3" scope="rowgroup">' + esc(t) + '</th></tr>'; }

  function render(o, body, ctx){
    var Q = window.QA;
    if (Q && Q.distM) distM = Q.distM;
    injectCss();
    if (cur.map) { try { cur.map.remove(); } catch (e) { /* déjà retirée */ } cur.map = null; }
    if (cur.onResize) { window.removeEventListener('resize', cur.onResize); cur.onResize = null; }
    var E = CACHE[o.num] || (CACHE[o.num] = {}), fails = 0, pending = 5, moved = false, lastSeries = null, rtmr = null;
    var eau = o.obstacle || 'cours d’eau sans nom';

    function q(s){ return body.querySelector('[data-hy="' + s + '"]'); }
    function rowSkel(k, label){ return '<tr data-hy="' + k + '">' + rowHtml(label, '…', '<span class="hy-ph">chargement…</span>') + '</tr>'; }
    function setChip(k, label, val, small, cls){
      var el = q(k); if (!el) return;
      el.className = cls || '';
      el.innerHTML = rowHtml(label, val, small);
    }
    function ko(k, label){ var el = q(k); if (el) { el.className = ''; el.innerHTML = rowHtml(label, '<span class="hy-ko">indisponible</span>', '<span class="hy-ko">service sans réponse</span>'); } }
    function settled(failed){
      if (failed) fails++;
      if (--pending > 0 || !ctx.alive()) return;
      if (fails) {
        var r = q('retry');
        if (r) { r.innerHTML = '<button type="button" class="ld-retry">Réessayer les blocs indisponibles</button>'; r.firstChild.addEventListener('click', function(){ if (ctx.alive()) render(o, body, ctx); }); }
      }
    }

    body.innerHTML =
      '<div class="ld-grid"><div class="ld-mapcol"><div class="ld-map" data-hy="map"></div>' +
      '<div class="ld-legend hy-leg">' +
        '<span><i style="width:14px;height:14px;background:#102d41;border:2px solid #fff;box-shadow:0 0 0 1px #102d41"></i>Ouvrage (carré)</span>' +
        '<span><i style="width:11px;height:11px;transform:rotate(45deg);background:#e69f00;border:2px solid #102d41"></i>Station (losange)</span>' +
        '<span><i style="width:22px;height:0;border-top:4px solid #0072b2;opacity:.65"></i>Tronçon retenu (Strahler)</span>' +
        '<span><i style="width:22px;height:0;border-top:1.5px solid #8a3c73"></i>Contour de zone inondable</span></div>' +
      '<p class="ld-meta">Fond Esri ; cours d’eau : GRHQ simple (MRNF), cochable dans le menu de la carte. Station la plus proche seulement.</p></div>' +
      '<div class="ld-right">' +
        '<table class="qa-recap"><tbody>' + groupHtml('Cours d’eau au pont') + rowSkel('c-str', 'Ordre de Strahler') + rowSkel('c-bas', 'Bassin versant') + rowSkel('c-zi', 'Zone inondable (BDZI)') + '</tbody>' +
          '<tbody>' + groupHtml('Station hydrométrique') + rowSkel('c-stn', 'Station la plus proche') + '</tbody>' +
          '<tbody data-hy="t-ser"><tr>' + rowHtml('Historique', '…', '<span class="hy-ph">chargement…</span>') + '</tr></tbody></table>' +
        '<div data-hy="warn"></div><div data-hy="retry"></div>' +
        '<p class="ld-note" data-hy="zi"><span class="hy-ph">Zone inondable : chargement…</span></p>' +
        '<div class="ld-pf hy-pf" data-hy="chart"><h3 class="hy-pfh"><span data-hy="chtitle">Historique à la station</span> <small data-hy="chsub"></small></h3><div data-hy="keys"></div><div data-hy="svg"><span class="hy-ph">Chargement de l’historique…</span></div><div class="ld-read" data-hy="read">Survoler le graphique pour lire les valeurs.</div></div>' +
        '<p class="ld-note" data-hy="ref" hidden></p>' +
      '</div></div>' +
      '<details class="hy-lex"><summary>Lexique</summary><dl>' + LEX.map(function(r){ return '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>'; }).join('') + '</dl></details>' +
      '<p class="ld-src">Réseau hydrographique, ordre de Strahler, bassins versants et zones inondables (BDZI) © Gouvernement du Québec, MELCCFP (CC-BY 4.0) ; couche GRHQ simple © MRNF ; stations et séries (HYDAT) © Environnement et Changement climatique Canada (Licence du gouvernement ouvert – Canada) ; fond © Esri. ' +
      'Repères d’aide à la lecture, sans valeur de calcul : ils ne remplacent pas une étude hydrologique.</p>';

    /* ----- Mini-carte ----- */
    var map = cur.map = L.map(q('map'), { zoomControl: true, attributionControl: false, zoomSnap: 0.5 });
    var gris = L.tileLayer(Q.ESRI + 'Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom: 16, maxZoom: 20 }).addTo(map);
    var wms = L.tileLayer.wms(GRHQ, { layers: GRHQ_LAYERS, version: '1.3.0', format: 'image/png', transparent: true, maxZoom: 20 }).addTo(map);
    var gZi = L.layerGroup().addTo(map), gOv = L.layerGroup().addTo(map);
    L.control.layers(null, { 'Cours d’eau (GRHQ, MRNF)': wms, 'Contour de zone inondable': gZi }, { collapsed: true }).addTo(map);
    map.setView([o.lat, o.lon], 15);
    L.marker([o.lat, o.lon], { icon: L.divIcon({ className: '', html: '<div class="hy-mk-b"></div>', iconSize: [16, 16], iconAnchor: [8, 8] }), zIndexOffset: 1000, keyboard: false })
      .bindTooltip('Ouvrage N° ' + esc(o.num) + (o.route ? ' · ' + esc(o.route) : '')).addTo(map);
    ['mousedown', 'touchstart', 'wheel'].forEach(function(ev){ map.getContainer().addEventListener(ev, function(){ moved = true; }, { passive: true }); });
    setTimeout(function(){ if (ctx.alive() && cur.map === map) map.invalidateSize(); }, 80);
    ctx.onClose(function(){
      if (cur.map === map) { map.remove(); cur.map = null; }
      if (cur.onResize) { window.removeEventListener('resize', cur.onResize); cur.onResize = null; }
    });

    /* ----- Ordre de Strahler ----- */
    cached(E, 'str', function(){ return qStrahler(o); }).then(function(j){
      if (!ctx.alive()) return;
      var r = nearestReach(j.features, o.lat, o.lon), L1 = 'Ordre de Strahler';
      if (!r) setChip('c-str', L1, '—', 'aucun tronçon du réseau à moins de 800 m');
      else {
        setChip('c-str', L1, r.ord == null ? '—' : String(r.ord), '<b>' + esc(strahlerWord(r.ord) || 'ordre non précisé') + '</b> · ' + esc(PER[r.per] || 'écoulement non précisé') + ' · tronçon à ' + fmt(r.d, 0) + ' m de l’ouvrage');
        L.polyline(r.paths.map(function(p){ return p.map(function(c){ return [c[1], c[0]]; }); }), { color: '#0072b2', weight: 6, opacity: .55, dashArray: r.per === 'I' ? '8 6' : null, interactive: false }).addTo(gOv);
      }
      settled(false);
    }, function(){ if (!ctx.alive()) return; ko('c-str', 'Ordre de Strahler'); settled(true); });

    /* ----- Bassin versant ----- */
    cached(E, 'bas', function(){ return qBassin(o); }).then(function(j){
      if (!ctx.alive()) return;
      var b = deepBasin(j.results), L1 = 'Bassin versant (à l’embouchure)';
      if (!b) setChip('c-bas', L1, '—', 'aucun bassin nommé à cet endroit');
      else {
        var same = subset(tokens(eau), tokens(b.nom));
        setChip('c-bas', L1, fmt(b.km2, 0) + '&nbsp;km²', '<b>' + esc(b.nom) + '</b> · borne supérieure de la superficie en amont du pont' + (same || !tokens(eau).length ? '' : ' (bassin du cours d’eau parent)'));
      }
      settled(false);
    }, function(){ if (!ctx.alive()) return; ko('c-bas', 'Bassin versant'); settled(true); });

    /* ----- Zone inondable ----- */
    cached(E, 'zi', function(){ return qZone(o); }).then(function(j){
      if (!ctx.alive()) return;
      var z = zoneAt(j.features, o.lat, o.lon), L1 = 'Zone inondable (BDZI)', note = q('zi');
      if (!z) {
        setChip('c-zi', L1, 'non', 'aucune zone cartographiée à moins de 1,2 km · la BDZI ne couvre pas tout le territoire : cela n’exclut pas un risque d’inondation');
        note.hidden = true;
      } else {
        var rec = recurrence(z.desc), within = z.d === 0;
        setChip('c-zi', L1, within ? 'oui' : 'à ' + fmt(z.d, 0) + '&nbsp;m', '<b>' + esc(z.desc) + '</b>' + (rec ? ' · récurrence ' + rec : '') + (within ? ' · l’ouvrage est dans la zone' : ''), within || z.d < 200 ? 'hy-hit' : '');
        note.innerHTML = '<b>Zone inondable officielle :</b> ' + (within ? 'l’ouvrage est dans une' : 'l’ouvrage est à ' + fmt(z.d, 0) + ' m d’une') + ' « ' + esc(z.desc.toLowerCase()) + ' »' + (rec ? ' (récurrence ' + rec + ')' : '') +
          (z.rapport ? '. Rapport source : ' + esc(z.rapport) + (z.titre ? ', ' + esc(z.titre) : '') : '') + '.';
        (j.features || []).forEach(function(f){
          ((f.geometry && f.geometry.rings) || []).forEach(function(ring){
            L.polyline(ring.map(function(c){ return [c[1], c[0]]; }), { color: '#8a3c73', weight: 1.4, opacity: .9, interactive: false }).addTo(gZi);
          });
        });
      }
      settled(false);
    }, function(){ if (!ctx.alive()) return; ko('c-zi', 'Zone inondable (BDZI)'); q('zi').innerHTML = '<span class="hy-ko">Zones inondables : service indisponible.</span>'; settled(true); });

    /* ----- Station la plus proche, puis séries ----- */
    var pStn = cached(E, 'stn', function(){ return qStations(o); });
    pStn.then(function(res){
      if (!ctx.alive()) return;
      var s = res.best, L1 = 'Station la plus proche';
      if (!s) {
        setChip('c-stn', L1, 'aucune', 'pas de station à moins de ' + KM_MAX + ' km');
        q('warn').innerHTML = '';
        settled(false);
        return;
      }
      var same = s.match === 'oui' ? ' · même cours d’eau' : s.match === 'non' ? ' · autre cours d’eau' : '';
      setChip('c-stn', L1, fmt(s.d, 1) + '&nbsp;km', '<b>' + esc(titleCase(s.nom)) + '</b> (' + esc(s.id) + ') · ' + (s.act ? 'en service' : 'fermée, historique seulement') + same);
      // Avertissement en une ligne ; complété par le rapport des bassins dès que le bassin du pont est connu
      function warn(bas){
        var msg = [], ratio = bas && s.area ? s.area / bas.km2 : null;
        if (s.match === 'non') msg.push('la station mesure « ' + esc(titleCase(s.nom)) + ' », un autre cours d’eau que « ' + esc(eau) + ' » : ses niveaux ne sont pas ceux du pont' +
          (ratio && ratio >= 2 ? ' (son bassin est ' + fmt(ratio, ratio >= 10 ? 0 : 1) + ' fois plus grand)' : ''));
        else if (s.match === 'inconnu') msg.push('le cours d’eau n’est pas nommé à l’inventaire : vérifier que la station est sur le même cours d’eau');
        if (s.d > KM_FAR) msg.push('station éloignée (' + fmt(s.d, 0) + ' km)');
        if (ctx.alive()) q('warn').innerHTML = msg.length ? '<div class="ld-warn"><b>⚠ Attention :</b> ' + msg.join(' ; ') + '.</div>' : '';
      }
      warn(null);
      if (s.match === 'non' && s.area && E.bas) E.bas.then(function(j){ warn(deepBasin(j.results)); }, function(){});
      var st = L.marker([s.lat, s.lon], { icon: L.divIcon({ className: '', html: '<div class="hy-mk-s"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }), keyboard: false })
        .bindTooltip(esc(titleCase(s.nom)) + '<br>' + esc(s.id) + ' · ' + fmt(s.d, 1) + ' km').addTo(map);
      if (s.d < 6 && !moved) map.fitBounds(L.latLngBounds([[o.lat, o.lon], [s.lat, s.lon]]).pad(0.4), { maxZoom: 16, animate: false });
      st.setZIndexOffset(500);
      settled(false);
    }, function(){ if (!ctx.alive()) return; ko('c-stn', 'Station la plus proche'); settled(true); });

    cached(E, 'ser', function(){ return pStn.then(function(res){ return res.best ? qSeries(res.best.id).then(function(s){ s.stn = res.best; return s; }) : { none: true }; }); }).then(function(S){
      if (!ctx.alive()) return;
      if (S.none) {
        q('t-ser').innerHTML = '';
        q('svg').innerHTML = '<span class="hy-ko">Aucune station à moins de ' + KM_MAX + ' km : pas d’historique de niveaux ni de débits pour cet ouvrage.</span>';
        q('chart').querySelector('h3').style.display = 'none'; q('read').hidden = true;
        settled(false); return;
      }
      var ps = pickSeries(S.lvl, S.dis);
      if (!ps) {
        q('t-ser').innerHTML = '<tr>' + rowHtml('Historique', '—', 'aucune série annuelle publiée pour la station ' + esc(S.stn.id)) + '</tr>';
        q('svg').innerHTML = '<span class="hy-ko">Aucune série annuelle publiée pour la station ' + esc(S.stn.id) + '.</span>';
        q('read').hidden = true; settled(false); return;
      }
      lastSeries = { ps: ps, S: S };
      drawSeries();
      cur.onResize = function(){ clearTimeout(rtmr); rtmr = setTimeout(function(){ if (ctx.alive()) drawSeries(); }, 150); };
      window.addEventListener('resize', cur.onResize);
      settled(false);
    }, function(){
      if (!ctx.alive()) return;
      q('t-ser').innerHTML = '<tr>' + rowHtml('Historique', '<span class="hy-ko">indisponible</span>', '<span class="hy-ko">service sans réponse</span>') + '</tr>';
      q('svg').innerHTML = '<span class="hy-ko">Historique de la station : indisponible.</span>'; q('read').hidden = true; settled(true);
    });

    /* ----- Graphique annuel (SVG fait main) et repères ----- */
    function drawSeries(){
      var ps = lastSeries.ps, S = lastSeries.S, rows = ps.rows, lvl = ps.kind === 'niveau', sm = summary(rows);
      var host = q('svg'), readEl = q('read'), W = Math.max(300, Math.min(900, host.clientWidth || 640)), H = W < 500 ? 230 : 260;
      var ml = 46, mr = 12, mt = 12, mb = 24, C = { max: '#0072b2', mean: '#102d41', min: '#d55e00' };
      var vs = []; rows.forEach(function(r){ [r.max, r.mean, r.min].forEach(function(v){ if (v != null) vs.push(v); }); });
      var lo = Math.min.apply(null, vs), hi = Math.max.apply(null, vs), pad = (hi - lo) * 0.08 || 0.5;
      if (lvl) lo -= pad; else lo = 0; hi += pad;
      var ya = rows[0].y - 1, yb = rows[rows.length - 1].y + 1;
      var X = function(y){ return ml + (y - ya) / (yb - ya) * (W - ml - mr); }, Y = function(v){ return mt + (hi - v) / (hi - lo) * (H - mt - mb); };
      var h = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc((lvl ? 'Niveaux d’eau' : 'Débits') + ' annuels maximum, moyen et minimum, de ' + sm.y0 + ' à ' + sm.y1) + '">';
      var stp = niceStep((hi - lo) / 5), dec = stp >= 1 ? 0 : stp >= 0.1 ? 1 : 2, z, y;
      for (z = Math.ceil(lo / stp) * stp; z <= hi; z += stp) h += '<line x1="' + ml + '" x2="' + (W - mr) + '" y1="' + Y(z).toFixed(1) + '" y2="' + Y(z).toFixed(1) + '" stroke="#dce5eb"/><text x="' + (ml - 6) + '" y="' + (Y(z) + 4).toFixed(1) + '" text-anchor="end" font-size="12" fill="#566e7c">' + fmt(z, dec) + '</text>';
      var ys = niceStep((yb - ya) / (W < 500 ? 4 : 7));
      for (y = Math.ceil(ya / ys) * ys; y <= yb; y += ys) h += '<text x="' + X(y).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="12" fill="#566e7c">' + y + '</text>';
      // Étiage : médiane des minimums annuels (trait mixte, étiquette)
      if (sm.medMin != null && sm.nMin >= 5) {
        h += '<line x1="' + ml + '" x2="' + (W - mr) + '" y1="' + Y(sm.medMin).toFixed(1) + '" y2="' + Y(sm.medMin).toFixed(1) + '" stroke="' + C.min + '" stroke-width="1.2" stroke-dasharray="9 3 2 3"/>';
      }
      function line(key, dash){
        var d = '', prev = null;
        rows.forEach(function(r){ if (r[key] == null) { prev = null; return; } d += (prev != null && r.y - prev === 1 ? 'L' : 'M') + X(r.y).toFixed(1) + ' ' + Y(r[key]).toFixed(1); prev = r.y; });
        return '<path d="' + d + '" fill="none" stroke="' + C[key] + '" stroke-width="1.1" ' + (dash ? 'stroke-dasharray="' + dash + '" ' : '') + 'stroke-linejoin="round"/>';
      }
      h += line('min', '2 3') + line('mean', '6 3') + line('max', '');
      rows.forEach(function(r){
        var x = X(r.y).toFixed(1);
        if (r.min != null) h += '<rect x="' + (x - 2.4) + '" y="' + (Y(r.min) - 2.4).toFixed(1) + '" width="4.8" height="4.8" fill="#fff" stroke="' + C.min + '" stroke-width="1.3"/>';
        if (r.mean != null) h += '<polygon points="' + x + ',' + (Y(r.mean) - 3.4).toFixed(1) + ' ' + (+x + 3.4) + ',' + Y(r.mean).toFixed(1) + ' ' + x + ',' + (Y(r.mean) + 3.4).toFixed(1) + ' ' + (x - 3.4) + ',' + Y(r.mean).toFixed(1) + '" fill="' + C.mean + '"/>';
        if (r.max != null) h += '<circle cx="' + x + '" cy="' + Y(r.max).toFixed(1) + '" r="2.6" fill="' + C.max + '"/>';
      });
      h += '<line data-hy="cur" x1="0" x2="0" y1="' + mt + '" y2="' + (H - mb) + '" stroke="#566e7c" visibility="hidden"/><rect x="' + ml + '" y="' + mt + '" width="' + (W - ml - mr) + '" height="' + (H - mt - mb) + '" fill="transparent"/></svg>';
      host.innerHTML = h;
      function key(c, dash, shape, label){
        var mk = shape === 'c' ? '<circle cx="15" cy="6" r="2.8" fill="' + c + '"/>' : shape === 'd' ? '<polygon points="15,2.5 18.5,6 15,9.5 11.5,6" fill="' + c + '"/>' : '<rect x="12.6" y="3.6" width="4.8" height="4.8" fill="#fff" stroke="' + c + '" stroke-width="1.3"/>';
        return '<span><svg width="30" height="12" aria-hidden="true"><line x1="0" x2="30" y1="6" y2="6" stroke="' + c + '" stroke-width="1.2"' + (dash ? ' stroke-dasharray="' + dash + '"' : '') + '/>' + mk + '</svg>' + label + '</span>';
      }
      q('keys').innerHTML = '<div class="ld-keys hy-keys">' + key(C.max, '', 'c', 'maximum annuel') + (rows.some(function(r){ return r.mean != null; }) ? key(C.mean, '6 3', 'd', 'moyenne annuelle') : '') + key(C.min, '2 3', 's', 'minimum annuel') +
        (sm.medMin != null && sm.nMin >= 5 ? '<span><svg width="30" height="12" aria-hidden="true"><line x1="0" x2="30" y1="6" y2="6" stroke="' + C.min + '" stroke-width="1.2" stroke-dasharray="9 3 2 3"/></svg>étiage médian (' + (lvl ? fmt(sm.medMin, 2) : fmtQ(sm.medMin)) + ' ' + ps.unit + ')</span>' : '') + '</div>';
      q('chtitle').textContent = lvl ? 'Niveaux d’eau à la station' : 'Débits à la station';
      q('chsub').textContent = (lvl ? 'niveau d’eau, m' : 'débit, m³/s (pas de niveau publié)') + ' · ' + sm.n + ' années, ' + sm.y0 + '–' + sm.y1;
      readEl.hidden = false;
      var svg = host.querySelector('svg'), cl = svg.querySelector('[data-hy="cur"]');
      function f(v){ return v == null ? '—' : (lvl ? fmt(v, 2) : fmtQ(v)) + ' ' + ps.unit; }
      svg.addEventListener('pointermove', function(e){
        var r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W, yv = ya + (x - ml) / (W - ml - mr) * (yb - ya), best = null, bd = 1e9;
        rows.forEach(function(p){ var dd = Math.abs(p.y - yv); if (dd < bd) { bd = dd; best = p; } });
        if (!best) return;
        cl.setAttribute('x1', X(best.y)); cl.setAttribute('x2', X(best.y)); cl.setAttribute('visibility', 'visible');
        readEl.textContent = best.y + ' · maximum ' + f(best.max) + (best.maxD ? ' (' + new Date(best.maxD + 'T12:00:00').toLocaleDateString('fr-CA', { day: 'numeric', month: 'short' }) + ')' : '') + ' · moyenne ' + f(best.mean) + ' · minimum ' + f(best.min);
      });
      svg.addEventListener('pointerleave', function(){ cl.setAttribute('visibility', 'hidden'); readEl.textContent = 'Survoler le graphique pour lire les valeurs.'; });
      drawRefs(ps, S, sm);
    }
    function drawRefs(ps, S, sm){
      var lvl = ps.kind === 'niveau', s = S.stn, el = q('ref'), dk = datumKind(s.datum), rows = '';
      rows += serieRows(S.lvl.length >= 5 || ps.kind === 'niveau' ? S.lvl : [], true) + serieRows(S.dis.length >= 5 ? S.dis : [], false);
      if (!rows) rows = serieRows(ps.rows, lvl);
      rows += '<tr>' + rowHtml('Années publiées', String(sm.n), sm.y0 + '–' + sm.y1 + ' · ' + (lvl ? 'niveaux d’eau' : 'débits') + ' (HYDAT)') + '</tr>';
      if (s.area) rows += '<tr>' + rowHtml('Bassin drainé à la station', fmt(s.area, 0) + '&nbsp;km²', 'superficie brute publiée par ECCC') + '</tr>';
      q('t-ser').innerHTML = rows;
      var datum = '';
      if (lvl) {
        datum = dk === 'arbitraire' ? 'Niveaux comptés à partir du zéro d’échelle de la station (référentiel arbitraire) : ils ne se comparent pas aux élévations du pont ou du LiDAR sans levé topographique.' :
          dk === 'geodesique' ? 'Niveaux rapportés à un référentiel géodésique (« ' + esc(s.datum) + ' ») : ce sont des altitudes, comparables à celles du pont à condition de confirmer le référentiel et son ajustement par un levé.' :
          'Référentiel vertical de la station non précisé : ne pas comparer ces niveaux aux élévations du pont ou du LiDAR sans levé topographique.';
      }
      el.innerHTML = (datum ? datum + '<br>' : '') + '<span class="hy-ph">Régime d’écoulement non vérifié : un barrage en amont peut influencer les niveaux (voir « régime influencé » au lexique). Historique publié jusqu’en ' + sm.y1 + '.</span>';
      el.hidden = false;
    }
    // Lignes « maximum enregistré » et « étiage » d'une série annuelle (niveaux en m, débits en m³/s)
    function serieRows(rows, isLvl){
      if (!rows.length) return '';
      var m = summary(rows), u = isLvl ? 'm' : 'm³/s', t = isLvl ? 'niveau' : 'débit', f = function(v){ return (isLvl ? fmt(v, 2) : fmtQ(v)) + '&nbsp;' + u; }, h = '';
      if (m.maxRec) h += '<tr>' + rowHtml('Maximum enregistré (' + t + ')', f(m.maxRec.v), esc(fmtDate(m.maxRec.d))) + '</tr>';
      if (m.nMin >= 5) h += '<tr>' + rowHtml('Étiage (' + t + ')', f(m.medMin), 'médiane des ' + m.nMin + ' minimums annuels · plus bas ' + f(m.minRec.v) + ' (' + esc(fmtDate(m.minRec.d)) + ')') + '</tr>';
      return h;
    }
  }

  window.QA_MOD.hydro = {
    render: render,
    // Fonctions pures exposées pour les tests (tests/js/hydro_smoke.mjs)
    _t: { hedged: hedged, fmt: fmt, rowHtml: rowHtml, tokens: tokens, subset: subset, titleCase: titleCase, parseCsv: parseCsv, pickStation: pickStation, datumKind: datumKind, buildSeries: buildSeries, pickSeries: pickSeries,
      summary: summary, median: median, nearestReach: nearestReach, zoneAt: zoneAt, inRings: inRings, deepBasin: deepBasin, strahlerWord: strahlerWord, recurrence: recurrence, niceStep: niceStep }
  };
})();
