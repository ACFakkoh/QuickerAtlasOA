/* Fenêtre « Aléa sismique » de QuickerAtlasOA : spectres Sa(T), PGA et PGV par classe de site (A à E) pour les
   probabilités de dépassement de 2, 5 et 10 % en 50 ans.

   Données : data/sismique/s-<clé>.js, précalculées par `python -m etl.sismique` à partir de la grille officielle
   CanSHM6 (CNBC 2020) de RNCan (Dossier public 8950, doi:10.4095/331497, Licence du gouvernement ouvert – Canada),
   interpolées dans son réseau de triangles à l'emplacement de chaque ouvrage. Aucun appel réseau autre que le
   chargement de ce fichier (site statique).

   Format d'une entrée : [k, q0 … q164] ; k = classe de site estimée (0 inconnue, 1..5 = A..E) d'après la géologie de surface
   du Québec (Rosset et al. 2025, tableau 3 appliqué à la carte des dépôts du SIGEOM ; la même valeur est dans
   data/classes-site.js, window.PQ_CLASSE_SITE, que la fenêtre préfère si la page l'a déjà chargé) ;
   q = round(1000 × log10(v / 1e-4)), donc v = 1e-4 × 10^(q/1000) (g ; PGV en m/s) ; rang d'un q =
   ((classe × 3 + probabilité) × 11 + mesure), classes A..E, probabilités 2, 5, 10 %, mesures PGA, PGV, Sa(0,05 … 10 s).

   Contrat avec l'atlas : window.QA_MOD.sismique.render(o, body, ctx) ; ES5, sans dépendance. */
(function(){
  'use strict';
  window.QA_MOD = window.QA_MOD || {};

  // ------------------------------------------------------------------ constantes
  var N_SHARDS = 120, NB_VAL = 165, V_REF = 1e-4, PAS = 1000, N_MES = 11;
  var CLS = ['A', 'B', 'C', 'D', 'E'];
  var POES = [2, 5, 10];
  var CLS_VS = { A: '> 1500', B: '760 – 1500', C: '360 – 760', D: '180 – 360', E: '< 180' };
  var CLS_NOM = { A: 'roc dur', B: 'roc', C: 'sol très dense et roc mou', D: 'sol raide', E: 'sol meuble' };
  var PERIODS = [0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 5, 10];
  var MES = ['pga', 'pgv', 'sa0p05', 'sa0p1', 'sa0p2', 'sa0p3', 'sa0p5', 'sa1p0', 'sa2p0', 'sa5p0', 'sa10p0'];
  // courbes : palette Okabe-Ito (sûre en daltonisme) + tiret + marqueur + lettre au pic : l'information ne repose jamais sur la couleur seule
  var CRV = {
    A: { c: '#56B4E9', dash: '9 4', m: 'circle' },
    B: { c: '#0072B2', dash: '', m: 'square' },
    C: { c: '#009E73', dash: '2 3', m: 'tri' },
    D: { c: '#E69F00', dash: '9 3 2 3', m: 'diamond' },
    E: { c: '#D55E00', dash: '', m: 'cross' }
  };
  var SRC = 'CanSHM6 (CNBC 2020), RNCan, Dossier public 8950, doi:10.4095/331497, Licence du gouvernement ouvert – Canada';
  var SRC_CLS = 'Rosset P., Elrawy A., Nadarajah S., Chouinard L. (2025), « Vs30 Derived from Geology: An Attempt in the Province of Quebec, Canada », <i>Geotechnics</i> 5(2):24, doi:10.3390/geotechnics5020024 (CC BY 4.0), appliqué à la carte des dépôts de surface du SIGEOM (MRNF)';
  var URL_CLS = 'https://www.mdpi.com/2673-7094/5/2/24';
  var T_MAX = 10;                                   // axe des périodes : linéaire de 0 à 10 s

  // ------------------------------------------------------------------ fonctions pures (testées : tests/js/sismique_smoke.mjs)
  var imul = Math.imul || function(a, b){
    var ah = (a >>> 16) & 0xffff, al = a & 0xffff, bh = (b >>> 16) & 0xffff, bl = b & 0xffff;
    return ((al * bl) + (((ah * bl + al * bh) << 16) >>> 0)) | 0;
  };
  /* FNV-1a 32 bits des caractères (ASCII) du n°, modulo N_SHARDS, en hexadécimal sur 2 caractères : identique à etl.sismique.shard_of */
  function shardOf(num){
    var h = 0x811c9dc5, s = String(num);
    for (var i = 0; i < s.length; i++) { h = (h ^ s.charCodeAt(i)) >>> 0; h = imul(h, 16777619) >>> 0; }
    var k = h % N_SHARDS;
    return (k < 16 ? '0' : '') + k.toString(16);
  }
  function decode(q){ return V_REF * Math.pow(10, q / PAS); }
  function index(ci, pi, mi){ return (ci * POES.length + pi) * N_MES + mi; }
  /* [pga, pgv, sa0p05 … sa10p0] décodés pour une classe (0..4) et une probabilité (0..2) d'une entrée de shard */
  function vec(row, ci, pi){
    var out = [], base = 1 + index(ci, pi, 0);
    for (var m = 0; m < N_MES; m++) out.push(decode(row[base + m]));
    return out;
  }
  function retour(p){ return Math.round(-50 / Math.log(1 - p / 100)); }   // période de retour (ans) pour p % en 50 ans
  function fr(v, d){ return v == null ? '—' : v.toLocaleString('fr-CA', { maximumSignificantDigits: d || 3 }); }
  function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){ return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function periodTxt(T){ return String(T).replace('.', ','); }
  function valide(row){ return !!row && row.length === NB_VAL + 1; }
  /* Classe de site estimée ('A'..'E') ou null : data/classes-site.js si la page l'a chargé, sinon k du lot */
  function classeEstimee(num, row, table){
    var t = table && table[num];
    if (typeof t === 'string' && CLS.indexOf(t) >= 0) return t;
    return row && row[0] >= 1 && row[0] <= 5 ? CLS[row[0] - 1] : null;
  }
  /* Graduations de l'axe des périodes (linéaire, en s) */
  function periodTicks(narrow){
    var out = [], pas = narrow ? 2 : 1;
    for (var T = 0; T <= T_MAX + 1e-9; T += pas) out.push(T);
    return out;
  }

  // ------------------------------------------------------------------ styles (injectés une seule fois)
  function css(){
    if (document.getElementById('sm-css')) return;
    var s = document.createElement('style'); s.id = 'sm-css';
    s.textContent =
      '.sm-root{display:flex;flex-direction:column;gap:10px;font-size:.82rem;color:var(--ink)}' +
      '.sm-top{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;line-height:1.4}' +
      '.sm-est{display:inline-block;font-size:.78rem;font-weight:700;color:#00544f;background:var(--mint);border:1px solid #9fd8c6;border-radius:999px;padding:0 9px;margin-right:2px}' +
      '.sm-sum{border-collapse:collapse;width:100%;font-size:.8rem;line-height:1.4;border:1px solid var(--line);border-radius:8px;overflow:hidden}' +
      '.sm-sum th,.sm-sum td{padding:5px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:baseline}' +
      '.sm-sum tr:last-child th,.sm-sum tr:last-child td{border-bottom:0}' +
      '.sm-sum th{width:1%;white-space:nowrap;font-size:.72rem;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:650;background:#f6f9fb}' +
      '.sm-sum .sm-num{font-variant-numeric:tabular-nums}' +
      '.sm-mu{color:var(--muted)}' +
      '.sm-rd{font-size:.78rem;color:var(--muted);min-height:2.4em;font-variant-numeric:tabular-nums;line-height:1.35}' +
      '.sm-ctl{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:flex-start}' +
      '.sm-ctl fieldset{border:1px solid var(--line);border-radius:8px;padding:4px 10px 7px;margin:0;min-width:0}' +
      '.sm-ctl legend{font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:650;padding:0 4px}' +
      '.sm-chk{display:inline-flex;gap:5px;align-items:center;margin-right:10px;cursor:pointer;white-space:nowrap;min-height:28px}' +
      '.sm-chk small{color:var(--muted)}' +
      '.sm-btn{font:inherit;border:1px solid #cbd8e1;background:#fff;color:var(--ink);border-radius:6px;padding:6px 12px;cursor:pointer;align-self:flex-end}' +
      '.sm-btn:hover,.sm-btn:focus-visible{border-color:var(--teal);outline:none;background:#f1fbf7}' +
      '.sm-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:18px}' +
      '.sm-h{margin:0 0 4px;font-size:.75rem;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}' +
      '.sm-h small{text-transform:none;letter-spacing:0;font-weight:400}' +
      '.sm-chart svg{display:block;width:100%;height:auto;overflow:visible;touch-action:pan-y}' +
      '.sm-leg{margin-top:4px;display:flex;flex-wrap:wrap;gap:2px 0}' +
      '.sm-scroll{overflow:auto;border:1px solid var(--line);border-radius:8px;max-height:430px}' +
      '.sm-t{border-collapse:collapse;width:100%;font-size:.78rem;font-variant-numeric:tabular-nums}' +
      '.sm-t th,.sm-t td{border-bottom:1px solid var(--line);padding:4px 7px;text-align:right;white-space:nowrap}' +
      '.sm-t th{background:#f6f9fb;font-size:.75rem;color:var(--muted);position:sticky;top:0}' +
      '.sm-t td:first-child,.sm-t th:first-child,.sm-t td:nth-child(2),.sm-t th:nth-child(2){text-align:left}' +
      '.sm-t td.mx{font-weight:700;background:#f1fbf7}' +
      '.sm-t th.est{color:#00544f;background:var(--mint)}' +
      '.sm-note{font-size:.78rem;line-height:1.5;background:#f6f9fb;border-left:3px solid var(--teal);padding:7px 11px;border-radius:0 8px 8px 0;margin:0}' +
      '.sm-warn{background:#fff6e5;border:1px solid #efcf8f;color:#7a4b00;border-radius:8px;padding:8px 12px;font-size:.8rem;line-height:1.45}' +
      '.sm-gl{border:1px solid var(--line);border-radius:8px;padding:6px 12px;background:#fff}' +
      '.sm-gl summary{cursor:pointer;font-weight:650;color:var(--navy)}' +
      '.sm-gl dl{margin:8px 0 2px;display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 12px;font-size:.78rem;line-height:1.45}' +
      '.sm-gl dt{font-weight:700;color:var(--navy)}.sm-gl dd{margin:0}' +
      '.sm-src{font-size:.75rem;color:var(--muted);margin:0;line-height:1.45}' +
      '@media(max-width:900px){.sm-grid{grid-template-columns:minmax(0,1fr)}}' +
      '@media(max-width:520px){.sm-gl dl{grid-template-columns:minmax(0,1fr)}.sm-gl dt{margin-top:4px}.sm-chk{margin-right:8px}' +
      '.sm-sum th,.sm-sum td{display:block;width:auto;border-bottom:0}.sm-sum th{padding-bottom:0;background:none}.sm-sum tr{display:block;border-bottom:1px solid var(--line)}.sm-sum tr:last-child{border-bottom:0}}';
    document.head.appendChild(s);
  }

  // ------------------------------------------------------------------ graphique
  function marker(m, x, y, c, r){
    var f = 'fill="' + c + '" stroke="#fff" stroke-width="1.2"';
    if (m === 'circle') return '<circle cx="' + x + '" cy="' + y + '" r="' + r + '" ' + f + '/>';
    if (m === 'square') return '<rect x="' + (x - r) + '" y="' + (y - r) + '" width="' + 2 * r + '" height="' + 2 * r + '" ' + f + '/>';
    if (m === 'tri') return '<polygon points="' + x + ',' + (y - r - 1) + ' ' + (x + r + 1) + ',' + (y + r) + ' ' + (x - r - 1) + ',' + (y + r) + '" ' + f + '/>';
    if (m === 'diamond') return '<polygon points="' + x + ',' + (y - r - 1) + ' ' + (x + r + 1) + ',' + y + ' ' + x + ',' + (y + r + 1) + ' ' + (x - r - 1) + ',' + y + '" ' + f + '/>';
    return '<path d="M' + (x - r) + ',' + (y - r) + ' L' + (x + r) + ',' + (y + r) + ' M' + (x - r) + ',' + (y + r) + ' L' + (x + r) + ',' + (y - r) + '" stroke="' + c + '" stroke-width="2.4" fill="none"/>';
  }
  function dashAttr(d){ return d ? ' stroke-dasharray="' + d + '"' : ''; }

  /* Graphique Sa(T) (axe des périodes linéaire, 0 à 10 s) + PGA ; renvoie { svg, xs, W } (xs : abscisses PGA puis périodes, pour la lecture au curseur) */
  function chart(ss, narrow){
    var W = narrow ? 360 : 700, H = narrow ? 330 : 380, ml = narrow ? 42 : 58, mr = 14, mt = 14, mb = 48;
    var pw = W - ml - mr, ph = H - mt - mb, slot = narrow ? 40 : 56, ymax = 0, i;
    ss.forEach(function(s){ s.v.forEach(function(v, k){ if (k !== 1 && v > ymax) ymax = v; }); });
    var steps = [0.05, 0.1, 0.2, 0.25, 0.5, 1, 2], step = 0.05;
    for (i = 0; i < steps.length; i++) { step = steps[i]; if (ymax * 1.06 / step <= 7) break; }
    var top = Math.ceil(ymax * 1.06 / step) * step || 0.1;
    var x0 = ml + slot + 4;
    var xT = function(T){ return x0 + T / T_MAX * (W - mr - x0); };
    var xP = ml + slot * 0.3;
    var yV = function(v){ return mt + ph - v / top * ph; };
    var g = '', v;
    for (v = 0; v <= top + 1e-9; v += step) {
      g += '<line x1="' + ml + '" x2="' + (W - mr) + '" y1="' + yV(v) + '" y2="' + yV(v) + '" stroke="#e3ebf0"/><text x="' + (ml - 6) + '" y="' + (yV(v) + 4) + '" text-anchor="end" font-size="11" fill="#566e7c">' + v.toFixed(step < 0.1 ? 2 : (step < 1 ? 1 : 0)).replace('.', ',') + '</text>';
    }
    periodTicks(narrow).forEach(function(T){
      var x = xT(T).toFixed(1);
      g += '<line x1="' + x + '" x2="' + x + '" y1="' + mt + '" y2="' + (mt + ph) + '" stroke="#eef3f6"/><line x1="' + x + '" x2="' + x + '" y1="' + (mt + ph) + '" y2="' + (mt + ph + 4) + '" stroke="#7d93a1"/><text x="' + x + '" y="' + (mt + ph + 16) + '" text-anchor="middle" font-size="11" fill="#566e7c">' + T + '</text>';
    });
    g += '<line x1="' + (ml + slot - 6) + '" x2="' + (ml + slot - 6) + '" y1="' + mt + '" y2="' + (mt + ph) + '" stroke="#b9c8d2" stroke-dasharray="3 3"/>';
    g += '<text x="' + xP + '" y="' + (mt + ph + 16) + '" text-anchor="middle" font-size="11" fill="#17374b" font-weight="700">PGA</text>';
    g += '<text x="' + ((x0 + W - mr) / 2) + '" y="' + (H - 8) + '" text-anchor="middle" font-size="12" fill="#17374b">Période T (s)</text>';
    g += '<text transform="translate(12 ' + (mt + ph / 2) + ') rotate(-90)" text-anchor="middle" font-size="12" fill="#17374b">Sa(T) et PGA (g)</text>';
    g += '<line x1="' + ml + '" x2="' + (W - mr) + '" y1="' + (mt + ph) + '" y2="' + (mt + ph) + '" stroke="#7d93a1"/><line x1="' + ml + '" x2="' + ml + '" y1="' + mt + '" y2="' + (mt + ph) + '" stroke="#7d93a1"/>';
    var tags = [];
    ss.forEach(function(s){
      var r = s.v, pts = PERIODS.map(function(T, k){ return [xT(T), yV(r[2 + k])]; });
      g += '<polyline points="' + pts.map(function(p){ return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ') + '" fill="none" stroke="' + s.st.c + '" stroke-width="2.4" stroke-linejoin="round"' + dashAttr(s.st.dash) + '/>';
      pts.forEach(function(p){ g += marker(s.st.m, +p[0].toFixed(1), +p[1].toFixed(1), s.st.c, 2.8); });
      g += marker(s.st.m, +xP.toFixed(1), +yV(r[0]).toFixed(1), s.st.c, 4.4);
      var k = 0, j;
      for (j = 1; j < PERIODS.length; j++) if (r[2 + j] > r[2 + k]) k = j;
      tags.push({ t: s.tag, x: pts[k][0], y: pts[k][1] - 11, c: s.st.c });
    });
    tags.sort(function(a, b){ return a.y - b.y; });
    for (i = 1; i < tags.length; i++) if (Math.abs(tags[i].x - tags[i - 1].x) < 34 && tags[i].y - tags[i - 1].y < 14) tags[i].y = tags[i - 1].y + 14;
    tags.forEach(function(t){
      var w = 8 + (t.t.length - 1) * 6.4;
      g += '<g><rect x="' + (t.x - w / 2) + '" y="' + (t.y - 10) + '" width="' + w + '" height="14" rx="3" fill="#fff" stroke="' + t.c + '"/><text x="' + t.x + '" y="' + (t.y + 1) + '" text-anchor="middle" font-size="11" font-weight="700" fill="#102d41">' + esc(t.t) + '</text></g>';
    });
    g += '<line class="sm-cx" x1="0" x2="0" y1="' + mt + '" y2="' + (mt + ph) + '" stroke="#102d41" stroke-opacity=".5" visibility="hidden"/>';
    g += '<rect class="sm-hit" x="' + ml + '" y="' + mt + '" width="' + pw + '" height="' + ph + '" fill="transparent"/>';
    return { svg: '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Spectres d’aléa uniforme Sa(T) et PGA par classe de site">' + g + '</svg>', xs: [xP].concat(PERIODS.map(xT)), W: W };
  }

  function legend(ss){
    return ss.map(function(s){
      return '<span class="sm-chk"><svg width="40" height="14" aria-hidden="true"><line x1="1" x2="39" y1="7" y2="7" stroke="' + s.st.c + '" stroke-width="2.4"' + dashAttr(s.st.dash) + '/>' + marker(s.st.m, 20, 7, s.st.c, 3.4) + '</svg>' + esc(s.label) + ' <small>' + CLS_VS[s.id] + ' m/s</small></span>';
    }).join('');
  }

  function table(ss){
    var rows = [['PGA', 'g', 0], ['PGV', 'm/s', 1]].concat(PERIODS.map(function(T, k){ return ['Sa(' + periodTxt(T) + ' s)', 'g', 2 + k]; }));
    var head = '<tr><th>Mesure</th><th>Unité</th>' + ss.map(function(s){ return '<th' + (s.est ? ' class="est" title="Classe estimée à cet endroit"' : '') + '>' + esc(s.tag) + '</th>'; }).join('') + '</tr>';
    return '<table class="sm-t">' + head + rows.map(function(r){
      var max = 0;
      ss.forEach(function(s){ if (s.v[r[2]] > max) max = s.v[r[2]]; });
      return '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td>' + ss.map(function(s){
        var v = s.v[r[2]];
        return '<td' + (ss.length > 1 && v === max ? ' class="mx"' : '') + '>' + fr(v, 3) + '</td>';
      }).join('') + '</tr>';
    }).join('') + '</table>';
  }

  var LEXIQUE = [
    ['PGA', 'accélération maximale du sol (en g, 1 g ≈ 9,81 m/s²).'],
    ['PGV', 'vitesse maximale du sol (ici en m/s).'],
    ['Sa(T)', 'accélération spectrale à la période T (en g) : réponse maximale d’un oscillateur à un degré de liberté, amorti à 5 %, de période T ; les périodes longues concernent les ouvrages souples.'],
    ['Vs30', 'vitesse moyenne des ondes de cisaillement sur les 30 premiers mètres de sol (m/s) ; elle sert à classer le site.'],
    ['Classe de site', 'A roc dur (Vs30 > 1500 m/s), B roc (760 à 1500), C sol très dense et roc mou (360 à 760), D sol raide (180 à 360), E sol meuble (< 180). La valeur affichée pour une classe est la plus forte de sa plage de Vs30 : elle est prudente.'],
    ['Probabilité de dépassement en 50 ans', 'chance que l’aléa soit dépassé en 50 ans ; elle correspond à une période de retour : 2 % ≈ 2 475 ans, 5 % ≈ 975 ans, 10 % ≈ 475 ans.'],
    ['CNBC', 'Code national du bâtiment du Canada (édition 2020 ; l’édition 2025 reprend le même aléa).'],
    ['CSA S6', 'Code canadien sur le calcul des ponts routiers : c’est elle qui régit la conception sismique d’un pont, pas le CNBC.'],
    ['CanSHM6', 'modèle d’aléa sismique de 6e génération du Canada (Ressources naturelles Canada), utilisé par le CNBC.']
  ];

  // ------------------------------------------------------------------ fenêtre
  function csv(S){
    var o = S.o, L = ['numero;classe;vs30_plage_m/s;probabilite_50ans_pct;periode_retour_ans;mesure;valeur;unite;source'];
    CLS.forEach(function(c, ci){
      POES.forEach(function(p, pi){
        var v = vec(S.row, ci, pi);
        MES.forEach(function(m, mi){
          var nom = mi === 0 ? 'PGA' : mi === 1 ? 'PGV' : 'Sa(' + PERIODS[mi - 2] + ')';
          L.push([o.num, c, CLS_VS[c].replace(/ /g, ''), p, retour(p), nom, +v[mi].toPrecision(4), mi === 1 ? 'm/s' : 'g', SRC].join(';'));
        });
      });
    });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([String.fromCharCode(0xFEFF) + L.join('\n')], { type: 'text/csv;charset=utf-8' }));
    a.download = 'alea_sismique_' + o.num + '.csv';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function(){ URL.revokeObjectURL(a.href); }, 2000);
  }

  function render(o, body, ctx){
    css();
    var key = shardOf(o.num == null ? '' : o.num);
    var root = document.createElement('div'); root.className = 'sm-root';
    var gen = '';
    function msg(t){ body.innerHTML = '<div class="ld-wait">' + t + '</div>'; }

    Promise.all([
      window.QA.loadScript('data/sismique/s-' + key + '.js'),
      window.QA.loadScript('data/sismique/meta.js').catch(function(){ return null; })
    ]).then(function(){
      if (!ctx.alive()) return;
      var sh = (window.PQ_SISMIQUE || {})[key], row = sh && sh[o.num];
      gen = (sh && sh._ && sh._.gen) || ((window.PQ_SISMIQUE_META || {}).generated) || '';
      if (sh && sh._ && sh._.fmt !== 1) { msg('Format de données sismiques inconnu (fmt ' + esc(sh._.fmt) + ') : régénérer avec <code>python -m etl.sismique</code>.'); return; }
      if (!valide(row)) { msg('Aucune valeur d’aléa pour cet ouvrage : il est hors de la zone couverte par la grille de RNCan (par exemple aux États-Unis ou en mer), ou sans coordonnées.'); return; }
      start(row);
    }, function(){
      if (!ctx.alive()) return;
      body.innerHTML = '<div class="ld-wait">Échec du chargement des valeurs sismiques (fichier data/sismique/s-' + esc(key) + '.js). <button type="button" class="sm-btn" data-retry>Réessayer</button></div>';
      body.querySelector('[data-retry]').addEventListener('click', function(){ window.QA_MOD.sismique.render(o, body, ctx); });
    });

    function start(row){
      var est = classeEstimee(o.num, row, window.PQ_CLASSE_SITE);
      var S = { o: o, row: row, pi: 0, est: est, show: { A: true, B: true, C: true, D: true, E: true }, ch: null, narrow: false };
      var base = [o.route, o.obstacle].filter(Boolean).join(' → ') || o.nom || '';
      if (ctx.setSub) ctx.setSub(base + (est ? ' · classe de site estimée ' + est : ''));
      body.innerHTML = ''; body.appendChild(root);

      function series(){
        var out = [];
        CLS.forEach(function(c, ci){
          if (S.show[c]) out.push({ id: c, label: 'Classe ' + c + (S.est === c ? ' ★ estimée ici' : ''), tag: c + (S.est === c ? ' ★' : ''), est: S.est === c, st: CRV[c], v: vec(S.row, ci, S.pi) });
        });
        return out;
      }

      function draw(focusSel){
        S.narrow = root.clientWidth > 0 && root.clientWidth < 520;
        var ss = series(), p = POES[S.pi];
        // résumé : classe estimée, probabilité retenue, valeurs clés à la classe estimée (ou C, classe de référence du CNBC)
        var ref = est || 'C', vr = vec(S.row, CLS.indexOf(ref), S.pi);
        var sum = '<table class="sm-sum"><tbody>' +
          '<tr><th scope="row">Classe de site estimée</th><td>' + (est
            ? '<b class="sm-est">' + est + ' ★</b> ' + CLS_NOM[est] + ' <span class="sm-mu">· Vs30 ' + CLS_VS[est] + ' m/s · géologie de surface (<a href="' + URL_CLS + '" target="_blank" rel="noopener">Rosset et al. 2025</a>)</span>'
            : '<span class="sm-mu">inconnue à cet endroit (eau, dépôt non classé ou hors carte) : les cinq classes sont montrées</span>') + '</td></tr>' +
          '<tr><th scope="row">Probabilité de dépassement</th><td><b>' + p + ' % en 50 ans</b> <span class="sm-mu">· période de retour ≈ ' + retour(p).toLocaleString('fr-CA') + ' ans</span></td></tr>' +
          '<tr><th scope="row">Valeurs, classe ' + ref + (est ? '' : ' (référence)') + '</th><td class="sm-num">PGA <b>' + fr(vr[0], 3) + ' g</b> · Sa(0,2 s) <b>' + fr(vr[4], 3) + ' g</b> · Sa(1 s) <b>' + fr(vr[7], 3) + ' g</b> · PGV <b>' + fr(vr[1], 3) + ' m/s</b></td></tr>' +
          '</tbody></table>';
        var poeBox = POES.map(function(q, i){
          return '<label class="sm-chk"><input type="radio" name="sm-poe" value="' + i + '"' + (i === S.pi ? ' checked' : '') + '>' + q + ' % <small>≈ 1 sur ' + retour(q).toLocaleString('fr-CA') + ' ans</small></label>';
        }).join('');
        var clsBox = CLS.map(function(c){
          return '<label class="sm-chk" title="' + esc('Classe ' + c + ' : ' + CLS_NOM[c] + ', Vs30 ' + CLS_VS[c] + ' m/s') + '"><input type="checkbox" data-cls="' + c + '"' + (S.show[c] ? ' checked' : '') + '><svg width="30" height="12" aria-hidden="true"><line x1="1" x2="29" y1="6" y2="6" stroke="' + CRV[c].c + '" stroke-width="2.4"' + dashAttr(CRV[c].dash) + '/>' + marker(CRV[c].m, 15, 6, CRV[c].c, 3) + '</svg><b>' + c + (est === c ? ' ★' : '') + '</b></label>';
        }).join('');
        var ch = ss.length ? chart(ss, S.narrow) : null;
        S.ch = ch;
        root.innerHTML =
          sum +
          '<div class="sm-ctl"><fieldset><legend>Probabilité en 50 ans</legend>' + poeBox + '</fieldset>' +
          '<fieldset><legend>Classes de site</legend>' + clsBox + '</fieldset>' +
          '<button type="button" class="sm-btn" data-csv title="Les 5 classes et les 3 probabilités">Exporter en CSV</button></div>' +
          (ss.length
            ? '<div class="sm-grid"><div class="sm-chart"><h4 class="sm-h">Spectre d’aléa uniforme<small>moyenne, amortissement 5 %, en g</small></h4>' + ch.svg +
              '<div class="sm-rd" id="sm-rd" aria-live="off">Survoler ou toucher le graphique pour lire les valeurs par période.</div><div class="sm-leg">' + legend(ss) + '</div></div>' +
              '<div><h4 class="sm-h">Valeurs<small>PGV en m/s · le plus élevé de chaque ligne en gras</small></h4><div class="sm-scroll">' + table(ss) + '</div></div></div>'
            : '<div class="sm-warn">Cocher au moins une classe de site.</div>') +
          '<p class="sm-note"><b>Valeurs interpolées à partir de la grille officielle CanSHM6</b> de Ressources naturelles Canada (CNBC 2020 ; l’outil du CNBC 2025 donne le même aléa), pour les probabilités de 2, 5 et 10 % en 50 ans. <b>Ce ne sont pas des valeurs de calcul pour un pont</b> : la conception sismique relève de la norme CSA S6. Pour une classe, la valeur est la plus forte de sa plage de Vs30 (prudente). ' +
          (est ? 'La classe ★ est une estimation régionale : Vs30 moyen du type de dépôt de surface de la carte générale du SIGEOM ; elle ne remplace pas une étude de site ni une mesure de Vs30. ' : '') + '</p>' +
          '<details class="sm-gl"><summary>Lexique</summary><dl>' + LEXIQUE.map(function(e){ return '<dt>' + esc(e[0]) + '</dt><dd>' + esc(e[1]) + '</dd>'; }).join('') + '</dl></details>' +
          '<p class="sm-src">Source : ' + esc(SRC) + (gen ? ' · données précalculées le ' + esc(gen) : '') + ' · classe de site estimée : ' + SRC_CLS + '.</p>';
        if (focusSel) { var f = root.querySelector(focusSel); if (f) f.focus(); }
      }

      function cursor(idx){
        var svg = root.querySelector('.sm-chart svg'), rd = root.querySelector('#sm-rd');
        if (!svg || !S.ch || !rd) return;
        var line = svg.querySelector('.sm-cx'); line.setAttribute('x1', S.ch.xs[idx]); line.setAttribute('x2', S.ch.xs[idx]); line.setAttribute('visibility', 'visible');
        var ss = series(), lab = idx === 0 ? 'PGA' : 'T = ' + periodTxt(PERIODS[idx - 1]) + ' s';
        rd.innerHTML = '<b>' + lab + '</b> · ' + ss.map(function(s){ return esc(s.tag) + ' ' + fr(idx === 0 ? s.v[0] : s.v[1 + idx], 3) + ' g'; }).join(' · ');
      }
      function onPointer(e){
        if (!e.target.closest || !e.target.closest('.sm-hit')) return;
        var svg = root.querySelector('.sm-chart svg'), r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * S.ch.W, best = 0;
        S.ch.xs.forEach(function(v, i){ if (Math.abs(v - x) < Math.abs(S.ch.xs[best] - x)) best = i; });
        cursor(best);
      }
      root.addEventListener('pointermove', onPointer);
      root.addEventListener('pointerdown', onPointer);
      root.addEventListener('change', function(e){
        var t = e.target;
        if (t.name === 'sm-poe') { S.pi = +t.value; draw('input[name="sm-poe"][value="' + S.pi + '"]'); }
        else if (t.getAttribute && t.getAttribute('data-cls')) { var c = t.getAttribute('data-cls'); S.show[c] = t.checked; draw('input[data-cls="' + c + '"]'); }
      });
      root.addEventListener('click', function(e){ if (e.target.closest && e.target.closest('[data-csv]')) csv(S); });

      var onResize = function(){ var n = root.clientWidth > 0 && root.clientWidth < 520; if (n !== S.narrow && ctx.alive()) draw(); };
      window.addEventListener('resize', onResize);
      ctx.onClose(function(){ window.removeEventListener('resize', onResize); });
      draw();
    }
  }

  window.QA_MOD.sismique = {
    render: render,
    _t: { shardOf: shardOf, decode: decode, index: index, vec: vec, retour: retour, N_SHARDS: N_SHARDS, NB_VAL: NB_VAL, fr: fr,
          classeEstimee: classeEstimee, periodTicks: periodTicks, chart: chart }
  };
})();
