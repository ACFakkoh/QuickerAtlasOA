/* « Profil LiDAR » : fenêtre de QuickerAtlasOA (MNEHR 1 m de RNCan, calculé à la demande dans le navigateur).
   Module chargé à la demande (sorti du fichier principal en v0.6.0). Contrat : window.QA_MOD.lidar.open(o).
   Outils partagés reçus par window.QA (esc, nf1, nf2, ESRI, LD_WCS, fetchT, det, byNum, wireDialog). ES5.
   v0.6.0 : MNS filtré (arbres, véhicules retirés ; le profil suit le MNT hors de l'ouvrage), imagerie satellite Esri
   (asphalte gris / végétation verte) pour le filtre et la lecture des voies du dessous, recalage du centre et de l'axe
   du tablier sur les pixels de l'ouvrage, tableau récapitulatif ; la pente de l'obstacle n'est plus calculée. */
(function(){
  'use strict';
  window.QA_MOD = window.QA_MOD || {};
  var QA = window.QA, esc = QA.esc, nf = QA.nf, nf1 = QA.nf1, nf2 = QA.nf2, ESRI = QA.ESRI, LD_WCS = QA.LD_WCS, fetchT = QA.fetchT;
  var $ = function(s){ return document.querySelector(s); };
  // ---------- Profil LiDAR (MNEHR 1 m de RNCan, calculé à la demande dans le navigateur) ----------
  // MNT = sol nu, MNS = surface (tablier compris), lus en GeoTIFF par le WCS du Data Cube (CORS autorisé).
  // Axe de la route portée et obstacle : chemins OpenStreetMap (Overpass) ; repli : axe des pixels surélevés.
  // Profil en travers = le long de l'obstacle : perpendiculaire à l'axe, tournée de l'angle de biais de
  // l'inventaire (le sens du biais, absent des données ouvertes, est pris sur l'axe OSM de l'obstacle ou sur le relief).
  // Hauteur sous l'ouvrage = dessus du tablier (MNS) − sol interpolé linéairement entre les deux côtés du tablier.
  var LD_R = 6378137, ldCache = {}, ldMap = null, ldRun = 0, ldCur = null;
  function ldMerc(lat, lon){ return [lon * Math.PI / 180 * LD_R, Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) * LD_R]; }
  function ldUnmerc(x, y){ return [(2 * Math.atan(Math.exp(y / LD_R)) - Math.PI / 2) * 180 / Math.PI, x / LD_R * 180 / Math.PI]; }
  // GeoTIFF du WCS : flottants 32 bits, tuilés, non compressés
  function ldTiff(buf){
    var dv = new DataView(buf), le = dv.getUint16(0) === 0x4949, u16 = function(o){ return dv.getUint16(o, le); }, u32 = function(o){ return dv.getUint32(o, le); };
    var ifd = u32(4), n = u16(ifd), T = {}, size = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8, 16: 8 };
    for (var i = 0; i < n; i++) {
      var e = ifd + 2 + i * 12, tag = u16(e), type = u16(e + 2), cnt = u32(e + 4), sz = size[type] * cnt, off = sz <= 4 ? e + 8 : u32(e + 8), vals = [];
      for (var j = 0; j < cnt && type !== 2; j++) {
        var p = off + j * size[type];
        vals.push(type === 3 ? u16(p) : type === 4 || type === 16 ? u32(p) : type === 12 ? dv.getFloat64(p, le) : type === 11 ? dv.getFloat32(p, le) : dv.getUint8(p));
      }
      T[tag] = vals;
    }
    var w = T[256][0], h = T[257][0], tw = T[322] ? T[322][0] : w, th = T[323] ? T[323][0] : (T[278] ? T[278][0] : h);
    var offs = T[324] || T[273], nx = Math.ceil(w / tw), a = new Float32Array(w * h).fill(NaN), nOk = 0;
    offs.forEach(function(o, k){
      var ty = Math.floor(k / nx), tx = k % nx;
      for (var r = 0; r < th; r++) for (var c = 0; c < tw; c++) {
        var y = ty * th + r, x = tx * tw + c; if (y >= h || x >= w) continue;
        var v = dv.getFloat32(o + (r * tw + c) * 4, le);
        if (v > -1000 && v < 9000) { a[y * w + x] = v; nOk++; }
      }
    });
    return { a: a, w: w, h: h, sx: T[33550][0], sy: T[33550][1], X0: T[33922][3], Y0: T[33922][4], ok: nOk / (w * h) };
  }
  // Interpolation bilinéaire ; null hors de l'emprise téléchargée (audit v0.5.5 n° 2 : les poids n'étaient pas bornés,
  // un point à 100 m du bord renvoyait une altitude extrapolée). Tolérance d'un demi-pixel aux bords.
  function ldSamp(D, x, y){
    var c = (x - D.X0) / D.sx - 0.5, r = (D.Y0 - y) / D.sy - 0.5;
    if (!(c >= -0.5 && r >= -0.5 && c <= D.w - 0.5 && r <= D.h - 0.5)) return null;
    c = Math.max(0, Math.min(D.w - 1, c)); r = Math.max(0, Math.min(D.h - 1, r));
    var c0 = Math.min(D.w - 2, Math.floor(c)), r0 = Math.min(D.h - 2, Math.floor(r)), fc = c - c0, fr = r - r0;
    var g = function(rr, cc){ return D.a[rr * D.w + cc]; };
    var v = g(r0, c0) * (1 - fc) * (1 - fr) + g(r0, c0 + 1) * fc * (1 - fr) + g(r0 + 1, c0) * (1 - fc) * fr + g(r0 + 1, c0 + 1) * fc * fr;
    return isFinite(v) ? Math.round(v * 100) / 100 : null;
  }
  // v0.6.0 : valeur du pixel le plus proche (MNS filtré : l'interpolation bilinéaire mêlerait le tablier et le sol au
  // bord du masque et inventerait des altitudes intermédiaires) ; null hors emprise
  function ldNear(D, x, y){
    var c = Math.floor((x - D.X0) / D.sx), r = Math.floor((D.Y0 - y) / D.sy);
    if (c < 0 || r < 0 || c >= D.w || r >= D.h) return null;
    var v = D.a[r * D.w + c];
    return isFinite(v) ? Math.round(v * 100) / 100 : null;
  }
  function ldWcs(kind, cx, cy, half){
    var q = 'service=WCS&version=1.1.1&request=GetCoverage&identifier=' + kind + '&boundingbox=' + [cx - half, cy - half, cx + half, cy + half].map(function(v){ return v.toFixed(1); }).join(',') + ',urn:ogc:def:crs:EPSG::3857&format=image/geotiff';
    // le serveur répond parfois par une erreur sans en-tête CORS (« Failed to fetch ») : deux nouvelles tentatives espacées
    var get = function(){ return fetchT(LD_WCS + '?' + q, null, 25000, 'arrayBuffer'); };
    var wait = function(ms){ return new Promise(function(res){ setTimeout(res, ms); }); };
    return get().catch(function(){ return wait(1500).then(get); }).catch(function(){ return wait(4000).then(get); }).then(ldTiff);
  }
  function ldOsm(lat, lon){
    var a = 'around:70,' + lat + ',' + lon;
    var q = '[out:json][timeout:8];(way(' + a + ')[highway];way(' + a + ')[waterway];way(' + a + ')[railway];);out geom;';
    return fetchT('https://overpass-api.de/api/interpreter', { method: 'POST', body: 'data=' + encodeURIComponent(q), headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }, 7000, 'json');
  }
  function ldMed(v){ v = v.filter(function(x){ return x != null && isFinite(x); }).sort(function(a, b){ return a - b; }); return v.length ? (v.length % 2 ? v[v.length >> 1] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null; }
  function ldStd(v){ v = v.filter(function(x){ return x != null; }); if (v.length < 5) return Infinity; var m = v.reduce(function(a, b){ return a + b; }, 0) / v.length; return Math.sqrt(v.reduce(function(a, b){ return a + (b - m) * (b - m); }, 0) / v.length); }
  function ldRot(u, deg){ var t = deg * Math.PI / 180, c = Math.cos(t), s = Math.sin(t); return [u[0] * c - u[1] * s, u[0] * s + u[1] * c]; }
  function ldAngle(u, v){ var d = Math.abs(u[0] * v[0] + u[1] * v[1]); return Math.acos(Math.min(1, d)) * 180 / Math.PI; }   // 0–90°

  // Segment le plus proche d'un chemin OSM : {d (m merc), c (projeté), u (direction unitaire)}
  function ldNearest(w, p0){
    var pts = (w.geometry || []).map(function(g){ return ldMerc(g.lat, g.lon); }), best = null;
    for (var i = 0; i + 1 < pts.length; i++) {
      var a = pts[i], b = pts[i + 1], dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
      if (!L2) continue;
      var t = Math.max(0, Math.min(1, ((p0[0] - a[0]) * dx + (p0[1] - a[1]) * dy) / L2)), px = a[0] + t * dx, py = a[1] + t * dy, d = Math.hypot(px - p0[0], py - p0[1]), n = Math.sqrt(L2);
      if (!best || d < best.d) best = { d: d, c: [px, py], u: [dx / n, dy / n], w: w };
    }
    return best;
  }

  // ---- v0.5.5 : pentes et chaussée sous l'ouvrage ----
  // Droite des moindres carrés z = a + b·s sur les points non nuls de [s0, s1] : { a, b (m/m), n, s0, s1 }
  function ldFit(S, Z, s0, s1){
    var n = 0, sx = 0, sz = 0, sxx = 0, sxz = 0, lo = Infinity, hi = -Infinity;
    for (var i = 0; i < S.length; i++) {
      var s = S[i], z = Z[i];
      if (z == null || s < s0 || s > s1) continue;
      n++; sx += s; sz += z; sxx += s * s; sxz += s * z; if (s < lo) lo = s; if (s > hi) hi = s;
    }
    var den = n * sxx - sx * sx;
    if (n < 4 || Math.abs(den) < 1e-9) return null;
    var b = (n * sxz - sx * sz) / den;
    return { a: (sz - b * sx) / n, b: b, n: n, s0: lo, s1: hi };
  }
  // Orientation d'un vecteur (x vers l'est, y vers le nord, en Mercator) : N, NE, E, SE, S, SO, O, NO
  function ldCap(v){ var a = (Math.atan2(v[0], v[1]) * 180 / Math.PI + 360) % 360; return ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'][Math.round(a / 45) % 8]; }
  // Paramètre t (m) où le chemin OSM `w` coupe le segment O + u·t·k, t ∈ [-T, T] ; null si aucun croisement
  function ldCross(w, O, u, T, k){
    var g = (w.geometry || []).map(function(p){ return ldMerc(p.lat, p.lon); }), best = null;
    var ax = O[0] - u[0] * T * k, ay = O[1] - u[1] * T * k, bx = O[0] + u[0] * T * k, by = O[1] + u[1] * T * k;
    for (var i = 0; i + 1 < g.length; i++) {
      var px = g[i][0], py = g[i][1], qx = g[i + 1][0], qy = g[i + 1][1];
      var rx = bx - ax, ry = by - ay, sx = qx - px, sy = qy - py, den = rx * sy - ry * sx;
      if (Math.abs(den) < 1e-9) continue;
      var t1 = ((px - ax) * sy - (py - ay) * sx) / den, t2 = ((px - ax) * ry - (py - ay) * rx) / den;
      if (t1 >= 0 && t1 <= 1 && t2 >= 0 && t2 <= 1) { var t = -T + 2 * T * t1; if (best == null || Math.abs(t) < Math.abs(best)) best = t; }
    }
    return best;
  }

  // ---- v0.6.0 : imagerie satellite (Esri World Imagery) ----
  // Export du MapServer (f=image) sur la même emprise que le WCS, en EPSG:3857. Le serveur répond avec
  // « Access-Control-Allow-Origin: * » : l'image lue par fetch puis createImageBitmap ne « salit » pas le canevas,
  // les pixels sont lisibles. Pas d'image (réseau, navigateur ancien) : les calculs se font sur le LiDAR seul.
  function ldImg(cx, cy, half, k){
    if (!window.createImageBitmap) return Promise.reject(new Error('createImageBitmap absent'));
    var n = Math.max(256, Math.min(2048, Math.round(2 * half / k / 0.7))), bb = [cx - half, cy - half, cx + half, cy + half];
    var url = ESRI + 'World_Imagery/MapServer/export?bbox=' + bb.map(function(v){ return v.toFixed(1); }).join(',') + '&bboxSR=3857&imageSR=3857&size=' + n + ',' + n + '&format=jpg&f=image';
    return fetchT(url, null, 20000, 'arrayBuffer').then(function(buf){ return createImageBitmap(new Blob([buf], { type: 'image/jpeg' })); }).then(function(bm){
      var cv = document.createElement('canvas'); cv.width = bm.width; cv.height = bm.height;
      var g = cv.getContext('2d'); g.drawImage(bm, 0, 0);
      return { px: g.getImageData(0, 0, bm.width, bm.height).data, w: bm.width, h: bm.height, X0: bb[0], Y0: bb[3], sx: (bb[2] - bb[0]) / bm.width, sy: (bb[3] - bb[1]) / bm.height };
    });
  }
  // Couleur moyenne de l'image sur un carré de (2r + 1)² pixels autour de (x, y) (Mercator) ; null hors image
  function ldRgbAt(I, x, y, r){
    var c = Math.floor((x - I.X0) / I.sx), l = Math.floor((I.Y0 - y) / I.sy), R = 0, G = 0, B = 0, n = 0;
    for (var j = l - r; j <= l + r; j++) for (var i = c - r; i <= c + r; i++) {
      if (i < 0 || j < 0 || i >= I.w || j >= I.h) continue;
      var p = (j * I.w + i) * 4; R += I.px[p]; G += I.px[p + 1]; B += I.px[p + 2]; n++;
    }
    return n ? [R / n, G / n, B / n] : null;
  }
  // Classe d'une couleur [r, g, b] (0–255) : 'ombre' (trop sombre pour juger), 'veg' (vert : herbe, arbres),
  // 'gris' (peu saturé : asphalte, béton, gravier), 'eau' (bleuté), 'autre' (sol nu, toits colorés…)
  function ldRgbClass(c){
    if (!c) return null;
    var r = c[0], g = c[1], b = c[2], mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    if (mx < 40) return 'ombre';
    if (2 * g - r - b > 14 && g >= r && g >= b - 4 && g / (r + g + b) >= 0.36) return 'veg';   // béton clair légèrement verdâtre : pas de la végétation
    if (mx - mn <= 26 + mx * 0.06 && b >= r - 14) return 'gris';                     // neutre ou froid ; un beige (sol, herbe sèche) n'est pas de l'asphalte
    if (b > r + 8 && b >= g) return 'eau';
    return 'autre';
  }

  // ---- v0.6.0 : MNS filtré ----
  // Un pixel surélevé (MNS − MNT ≥ 0,5 m) n'est gardé que s'il appartient à une surface lisse (au moins 5 voisins
  // sur 8 à ± 0,3 m), qui n'est pas verte sur l'image (sauf surface parfaitement plane : l'image peut être décalée),
  // d'au moins 25 m² d'un seul tenant dont au moins 5 m² à 2 m ou plus au-dessus du sol (les cultures, lisses mais
  // basses, sont écartées) : tablier, ouvrage jumeau, bâtiment, mur. Ailleurs, le MNS filtré est le MNT : arbres, véhicules, poteaux, panneaux sont retirés. Les trous
  // du masque (véhicule ou lampadaire sur le tablier) sont bouchés par la médiane des voisins ; le pourtour (glissière,
  // parapet) est repris s'il touche le masque et n'est pas vert. Renvoie une grille lisible par ldSamp, plus le masque.
  function ldDsmFilt(dtm, dsm, I, k){
    var w = dtm.w, h = dtm.h, N = w * h, A = dsm.a, T = dtm.a, out = new Float32Array(N), cand = new Uint8Array(N), veg = new Uint8Array(N), M = new Uint8Array(N);
    var nb = [-w - 1, -w, -w + 1, -1, 1, w - 1, w, w + 1], x, y, i, q, nEl = 0, nVeg = 0;
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
      i = y * w + x;
      var s = A[i], t = T[i];
      out[i] = isFinite(t) ? t : s;
      if (!isFinite(s) || !isFinite(t) || s - t < 0.5 || x === 0 || y === 0 || x === w - 1 || y === h - 1) continue;
      nEl++;
      var n = 0; for (q = 0; q < 8; q++) if (Math.abs(A[i + nb[q]] - s) <= 0.3) n++;
      if (I && ldRgbClass(ldRgbAt(I, dtm.X0 + (x + 0.5) * dtm.sx, dtm.Y0 - (y + 0.5) * dtm.sy, 1)) === 'veg') { veg[i] = 1; nVeg++; }
      if (n >= 5 && !(veg[i] && n < 8)) cand[i] = 1;   // parfaitement plan : gardé même si l'image (décalée) le dit vert
    }
    // composantes connexes (4 voisins) des pixels candidats ; on garde celles d'au moins 25 m²
    var lab = new Int32Array(N), stack = new Int32Array(N), id = 0, minPx = 25 / (dtm.sx / k * dtm.sy / k), nKeep = 0, comps = [];
    for (var i0 = 0; i0 < N; i0++) {
      if (!cand[i0] || lab[i0]) continue;
      var top = 0, list = [], core = 0;
      id++; lab[i0] = id; stack[top++] = i0;
      while (top) {
        var p = stack[--top], px = p % w; list.push(p); if (A[p] - T[p] >= 2) core++;
        var vs = [p - w, p + w, px > 0 ? p - 1 : -1, px < w - 1 ? p + 1 : -1];
        for (q = 0; q < 4; q++) { var v = vs[q]; if (v >= 0 && v < N && cand[v] && !lab[v] && Math.abs(A[v] - A[p]) <= 0.5) { lab[v] = id; stack[top++] = v; } }
      }
      if (list.length >= minPx && core >= minPx / 5) comps.push({ id: id, list: list, z: ldMed(list.map(function(p){ return A[p]; })) });
      else for (q = 0; q < list.length; q++) lab[list[q]] = -1;     // composante écartée : visitée, sans étiquette
    }
    // véhicule sur le tablier (camion, autobus : lisse et de plus de 25 m², mais posé sur une autre composante) : petite
    // composante (moins de 100 m²) dont les pixels à 2 pixels de distance sont surtout une autre composante gardée, plus
    // basse de 0,8 à 6 m ; écartée, elle sera bouchée par le pontage à l'altitude du tablier
    var zOf = {}; comps.forEach(function(cp){ zOf[cp.id] = cp.z; });
    var OFF2 = [-2 * w - 2, -2 * w, -2 * w + 2, -2, 2, 2 * w - 2, 2 * w, 2 * w + 2];
    comps.forEach(function(cp){
      if (cp.list.length * (dtm.sx / k) * (dtm.sy / k) >= 100) { cp.keep = true; return; }
      var on = 0, tot = 0;
      cp.list.forEach(function(p){
        for (var r = 0; r < 8; r++) {
          var v = p + OFF2[r]; if (v < 0 || v >= N || lab[v] === cp.id) continue;
          tot++; var l2 = lab[v]; if (l2 > 0 && zOf[l2] != null && cp.z - zOf[l2] >= 0.8 && cp.z - zOf[l2] <= 6) on++;
        }
      });
      cp.keep = !(tot && on / tot >= 0.5);
    });
    comps.forEach(function(cp){
      if (cp.keep) for (q = 0; q < cp.list.length; q++) { M[cp.list[q]] = 1; out[cp.list[q]] = A[cp.list[q]]; nKeep++; }
      else for (q = 0; q < cp.list.length; q++) lab[cp.list[q]] = -1;
    });
    // pontage : un pixel surélevé non vert, encadré par le masque à moins de 6 pixels de part et d'autre (en ligne,
    // en colonne ou en diagonale), est un véhicule, un lampadaire ou un panneau sur le tablier : altitude interpolée
    // entre les deux bords (la plus courte des quatre directions)
    var DIRS = [[1, 0], [0, 1], [1, 1], [1, -1]], RB = 6, fill = [];
    for (y = 1; y < h - 1; y++) for (x = 1; x < w - 1; x++) {
      i = y * w + x;
      if (M[i] || veg[i] || !(A[i] - T[i] >= 0.5)) continue;
      var bestF = null;
      for (q = 0; q < 4; q++) {
        var dx = DIRS[q][0], dy = DIRS[q][1], ja = 0, jb = 0, jj, xa, ya;
        for (jj = 1; jj <= RB; jj++) { xa = x - jj * dx; ya = y - jj * dy; if (xa < 0 || ya < 0 || xa >= w || ya >= h) break; if (M[ya * w + xa]) { ja = jj; break; } }
        if (!ja) continue;
        for (jj = 1; jj <= RB; jj++) { xa = x + jj * dx; ya = y + jj * dy; if (xa < 0 || ya < 0 || xa >= w || ya >= h) break; if (M[ya * w + xa]) { jb = jj; break; } }
        if (!jb || (bestF && ja + jb >= bestF[3])) continue;
        var ia = (y - ja * dy) * w + (x - ja * dx), ib = (y + jb * dy) * w + (x + jb * dx);
        bestF = [i, out[ia] + (out[ib] - out[ia]) * ja / (ja + jb), lab[ia], ja + jb];
      }
      if (bestF) fill.push(bestF);
    }
    for (q = 0; q < fill.length; q++) { M[fill[q][0]] = 1; out[fill[q][0]] = fill[q][1]; lab[fill[q][0]] = fill[q][2]; }
    // trous (au moins 6 voisins sur 8 dans le masque) : médiane des voisins ; pourtour non vert collé au masque
    var add = [];
    for (y = 1; y < h - 1; y++) for (x = 1; x < w - 1; x++) {
      i = y * w + x;
      if (M[i] || !isFinite(A[i])) continue;
      var zs = [], l1 = 0; for (q = 0; q < 8; q++) if (M[i + nb[q]]) { zs.push(A[i + nb[q]]); l1 = lab[i + nb[q]]; }
      if (zs.length >= 6) add.push([i, ldMed(zs), l1]);
      else if (zs.length && !veg[i] && A[i] - T[i] >= 0.5 && A[i] - ldMed(zs) <= 1.0 && A[i] - ldMed(zs) >= -1.5) add.push([i, A[i], l1]);   // glissière, parapet : 1 m au plus ; pas le toit d'un véhicule
    }
    for (q = 0; q < add.length; q++) { M[add[q][0]] = 1; out[add[q][0]] = add[q][1]; lab[add[q][0]] = add[q][2]; }
    for (i = 0; i < N; i++) if (!M[i]) lab[i] = 0;
    var mf = new Float32Array(N); for (i = 0; i < N; i++) mf[i] = M[i];
    var geo = function(a){ return { a: a, w: w, h: h, sx: dtm.sx, sy: dtm.sy, X0: dtm.X0, Y0: dtm.Y0, ok: dsm.ok }; };
    return { F: geo(out), mask: geo(mf), lab: lab, veg: veg, nEl: nEl, nVeg: nVeg, nKeep: nKeep };
  }
  // Tablier de l'ouvrage : composante du masque (MNS filtré) la plus proche du point p0, à moins de rad, d'au moins
  // minPx pixels (Mercator). Ouvrages jumeaux (hint = direction du suffixe N, S, E, O du numéro) : parmi les composantes
  // à 12 m près de la plus proche, celle qui est le plus du côté du suffixe. Renvoie { id, n, cx, cy, d } ou null.
  function ldPickDeck(FL, D, p0, rad, minPx, hint, k){
    var w = D.w, C = {}, cx0 = Math.floor((p0[0] - D.X0) / D.sx), cy0 = Math.floor((D.Y0 - p0[1]) / D.sy), R = Math.ceil(rad / D.sx);
    for (var y = Math.max(0, cy0 - R); y <= Math.min(D.h - 1, cy0 + R); y++) for (var x = Math.max(0, cx0 - R); x <= Math.min(w - 1, cx0 + R); x++) {
      var id = FL.lab[y * w + x]; if (id <= 0) continue;
      var X = D.X0 + (x + 0.5) * D.sx, Y = D.Y0 - (y + 0.5) * D.sy, d = Math.hypot(X - p0[0], Y - p0[1]); if (d > rad) continue;
      var c = C[id] || (C[id] = { id: id, n: 0, d: Infinity, sx: 0, sy: 0 }); c.n++; c.sx += X; c.sy += Y; if (d < c.d) c.d = d;
    }
    var L1 = Object.keys(C).map(function(q){ var c = C[q]; c.cx = c.sx / c.n; c.cy = c.sy / c.n; return c; }).filter(function(c){ return c.n >= minPx; }).sort(function(a, b){ return a.d - b.d; });
    if (!L1.length) return null;
    var best = L1[0];
    if (hint) L1.forEach(function(c){
      var side = function(q){ return (q.cx - p0[0]) * hint[0] + (q.cy - p0[1]) * hint[1]; };
      if (c.d <= L1[0].d + 12 * k && side(c) > side(best)) best = c;
    });
    return best;
  }
  // Médiane glissante (± r échantillons, valeurs nulles ignorées) : pics isolés restants sur un profil
  function ldMed1(Z, r){
    return Z.map(function(z, i){ if (z == null) return null; var v = []; for (var j = Math.max(0, i - r); j <= Math.min(Z.length - 1, i + r); j++) if (Z[j] != null) v.push(Z[j]); return ldMed(v); });
  }
  // Plage continue de valeurs vraies de F (trous de `gap` échantillons tolérés) qui contient s = 0 ou, à défaut,
  // la plus proche de 0 à moins de dmax : { s0, s1 } ; null sinon
  function ldRunAt(S, F, gap, dmax){
    var runs = [], cur = null, miss = 0;
    for (var i = 0; i < S.length; i++) {
      if (F[i]) { if (!cur) cur = { i0: i }; cur.i1 = i; miss = 0; }
      else if (cur && ++miss > gap) { runs.push(cur); cur = null; miss = 0; }
    }
    if (cur) runs.push(cur);
    var best = null;
    runs.forEach(function(r){
      var a = S[r.i0], b = S[r.i1], d = a <= 0 && b >= 0 ? 0 : Math.min(Math.abs(a), Math.abs(b));
      if (d <= dmax && (!best || d < best.d || (d === best.d && b - a > best.s1 - best.s0))) best = { s0: a, s1: b, d: d };
    });
    return best ? { s0: best.s0, s1: best.s1 } : null;
  }

  // Altitude de la chaussée autour de t0 sur une section : fenêtre de 3 m la plus plane (écart-type minimal) dans t0 ± 4 m,
  // pour lire la voie et non l'accotement, le fossé ou le terre-plein. v0.6.0 : avec l'imagerie (img = vrai), une
  // fenêtre surtout verte (terre-plein gazonné, accotement) est écartée et une fenêtre grise (asphalte) est préférée.
  function ldPlat(sec, t0, win, img){
    var best = null;
    for (var c = t0 - (win || 4); c <= t0 + (win || 4) + 1e-9; c += 0.5) {
      var zs = [], kn = 0, gr = 0, vg = 0;
      for (var j = 0; j < sec.t.length; j++) if (Math.abs(sec.t[j] - c) <= 1.5 && sec.z[j] != null) {
        zs.push(sec.z[j]);
        var g = sec.g && sec.g[j];
        if (g && g !== 'ombre') { kn++; if (g === 'gris') gr++; else if (g === 'veg') vg++; }
      }
      if (zs.length < 5) continue;
      var useImg = img && kn >= 3;
      if (useImg && vg / kn >= 0.5) continue;
      var m = zs.reduce(function(a, b){ return a + b; }, 0) / zs.length, sd = Math.sqrt(zs.reduce(function(a, b){ return a + (b - m) * (b - m); }, 0) / zs.length);
      var cost = sd + 0.01 * Math.abs(c - t0) + (useImg ? 0.12 * (1 - gr / kn) : 0);   // à planéité égale : le plus gris, puis le plus près de l'axe OSM
      if (!best || cost < best.cost) best = { cost: cost, sd: sd, t: c, z: ldMed(zs), gris: useImg ? gr / kn : null };
    }
    return best && best.sd < 0.25 ? best : null;
  }
  // Repli sans OSM : plages planes de 3 m ou plus (pente < 5 %, pas de saut > 15 cm) sur une section ; part grise sur l'image.
  // Avec l'image (img vrai), une plage s'arrête aussi au premier échantillon vert, bleuté ou brun : l'accotement gazonné
  // et le terre-plein, plats eux aussi, ne s'ajoutent plus à la chaussée (l'ombre du pont est neutre).
  function ldRuns(sec, img){
    var runs = [], cur = null, paved = function(j){ var g = sec.g && sec.g[j]; return !img || !g || g === 'gris' || g === 'ombre'; };
    for (var j = 1; j < sec.t.length; j++) {
      var a = sec.z[j - 1], b = sec.z[j], ok = a != null && b != null && Math.abs(b - a) <= Math.max(0.15, 0.05 * (sec.t[j] - sec.t[j - 1])) && paved(j - 1) && paved(j);
      if (ok) { if (!cur) cur = { j0: j - 1 }; cur.j1 = j; }
      else if (cur) { runs.push(cur); cur = null; }
    }
    if (cur) runs.push(cur);
    return runs.map(function(r){
      var zs = sec.z.slice(r.j0, r.j1 + 1).filter(function(z){ return z != null; }), kn = 0, gr = 0;
      for (var j = r.j0; j <= r.j1; j++) { var g = sec.g && sec.g[j]; if (g && g !== 'ombre') { kn++; if (g === 'gris') gr++; } }
      return { t: (sec.t[r.j0] + sec.t[r.j1]) / 2, len: sec.t[r.j1] - sec.t[r.j0], z: ldMed(zs), kn: kn, n: r.j1 - r.j0 + 1, gris: kn ? gr / kn : null };
    }).filter(function(r){ return r.len >= 3; });
  }
  // Chaussée(s) sous l'ouvrage. Sections de l'obstacle parallèles à l'axe du pont, à 4, 8, 12 et 16 m au-delà de
  // chaque bord du tablier : on ne lit que les abords, jamais sous le tablier (le MNT y est interpolé). Sur chaque
  // section, la voie est repérée par les chemins OSM qui la croisent (sinon par les plages planes du relief, grises
  // sur l'image), puis son altitude est lue sur la fenêtre la plus plane et la plus grise. Par voie : médiane de chaque
  // côté, puis interpolation linéaire entre les deux côtés au droit du croisement (s = 0) ; la pente de l'obstacle
  // n'est ni calculée ni affichée (v0.6.0). Hauteur = dessus du tablier au droit de la voie (MNS filtré) − chaussée.
  var LD_HW = { motorway: 'autoroute', trunk: 'route principale', primary: 'route principale', secondary: 'route secondaire', tertiary: 'route tertiaire', residential: 'rue',
    unclassified: 'chemin', service: 'voie de service', track: 'chemin de terre', living_street: 'rue', road: 'chemin', footway: 'sentier', path: 'sentier', cycleway: 'piste cyclable' };
  function ldRoadUnder(o, ctx){
    var c = ctx.c, u = ctx.u, dir = ctx.dir, k = ctx.k, ways = ctx.ways, img = ctx.img;
    var Tm = Math.max(Math.abs(ctx.t0), Math.abs(ctx.t1)) + 4, DS = [4, 8, 12, 16], secs = [];
    var isRoad = function(w){
      var t = w.tags || {};
      if (t.tunnel && t.tunnel !== 'no') return false;
      if (t.bridge && t.bridge !== 'no') return false;
      if (t.railway) return /^(rail|light_rail|narrow_gauge|tram|preserved|disused)$/.test(t.railway);
      if (!t.highway) return false;
      if (/^(footway|path|cycleway|steps|pedestrian|bridleway|corridor|proposed|construction)$/.test(t.highway)) return o.obst === 'Piétons, cyclistes, VTT';
      return true;
    };
    var cand = ways.filter(function(w){ return w !== ctx.carriedW && isRoad(w); });
    [-1, 1].forEach(function(side){
      DS.forEach(function(d){
        var s = side < 0 ? ctx.eL - d : ctx.eR + d, O = [c[0] + dir[0] * s * k, c[1] + dir[1] * s * k], sec = { s: s, side: side, t: [], z: [], g: [], O: O, hits: [] };
        for (var t = -Tm; t <= Tm + 1e-9; t += 0.5) {
          var X = O[0] + u[0] * t * k, Y = O[1] + u[1] * t * k;
          sec.t.push(t); sec.z.push(ldSamp(ctx.dtm, X, Y)); sec.g.push(img ? ldRgbClass(ldRgbAt(img, X, Y, 1)) : null);
        }
        cand.forEach(function(w){
          var t = ldCross(w, O, u, Tm, k);
          if (t == null) return;
          var tg = w.tags || {};
          var kind = tg.railway ? 'voie ferrée' : (LD_HW[(tg.highway || '').replace('_link', '')] || 'chemin') + (/_link$/.test(tg.highway || '') ? ' (bretelle)' : '');
          sec.hits.push({ t: t, name: /_link$/.test(tg.highway || '') ? 'Bretelle' + (tg.ref ? ' ' + tg.ref : '') : (tg.name || tg.ref || kind), rail: !!tg.railway });
        });
        secs.push(sec);
      });
    });
    var pts = [], src = 'osm';
    secs.forEach(function(sec){
      sec.hits.forEach(function(hh){
        var p = ldPlat(sec, hh.t, hh.rail ? 2.5 : 4, !!img && !hh.rail);   // ballast : pas de test de couleur
        if (p) pts.push({ s: sec.s, t: p.t, z: p.z, name: hh.name, rail: hh.rail, side: sec.side, gris: p.gris });
      });
    });
    if (!pts.length) {
      // pas de voie OSM sous l'ouvrage : plages planes du relief sous le tablier, grises sur l'image si elle est lisible
      // (un terre-plein gazonné est plat lui aussi), puis les plus basses (à 1 m près) de chaque section
      src = img ? 'relief+image' : 'relief';
      secs.forEach(function(sec){
        var runs = ldRuns(sec, !!img).filter(function(r){ return r.t >= ctx.t0 && r.t <= ctx.t1 && (!img || r.kn < r.n / 2 || r.gris >= 0.5); });
        if (!runs.length) return;
        var zmin = Math.min.apply(null, runs.map(function(r){ return r.z; }));
        runs.filter(function(r){ return r.z <= zmin + 1; }).forEach(function(r){ pts.push({ s: sec.s, t: r.t, z: r.z, name: img ? 'plage plane et grise' : 'plage plane du relief', side: sec.side, gris: r.kn ? r.gris : null }); });
      });
    }
    // regroupement des points en voies (même position t à 4 m près)
    pts.sort(function(a, b){ return a.t - b.t; });
    var lanes = [];
    pts.forEach(function(p){
      var L0 = lanes.filter(function(l){ return Math.abs(l.tm - p.t) <= 4 && (l.name === p.name || src !== 'osm' || Math.abs(l.tm - p.t) <= 2); })[0];
      if (!L0) { L0 = { pts: [], name: p.name, rail: p.rail }; lanes.push(L0); }
      L0.pts.push(p); L0.tm = ldMed(L0.pts.map(function(q){ return q.t; }));
    });
    var out = [];
    lanes.forEach(function(l){
      var sides = {}; l.pts.forEach(function(p){ sides[p.side] = 1; });
      if (l.pts.length < 2 || (src !== 'osm' && !(sides[-1] && sides[1]))) return;   // relief : vue des deux côtés (sinon fossé, terre-plein)
      // par côté : écarte les points à plus de 0,6 m de la médiane du côté, puis médiane et position moyenne
      var P = [], side = {};
      [-1, 1].forEach(function(sd){
        var Q = l.pts.filter(function(p){ return p.side === sd; }), zm = ldMed(Q.map(function(p){ return p.z; }));
        Q = Q.filter(function(p){ return Math.abs(p.z - zm) <= 0.6; });
        if (!Q.length) return;
        P = P.concat(Q);
        side[sd] = { z: ldMed(Q.map(function(p){ return p.z; })), s: Q.reduce(function(a, p){ return a + p.s; }, 0) / Q.length };
      });
      if (P.length < 2) return;
      var both = !!(side[-1] && side[1]);
      var z0 = both ? side[-1].z + (side[1].z - side[-1].z) * (0 - side[-1].s) / (side[1].s - side[-1].s) : (side[-1] || side[1]).z;
      var tops = [];
      ctx.PL.s.forEach(function(s, i){ if (Math.abs(s - ctx.sOff - l.tm) <= 1.5 && ctx.PL.mns[i] != null) tops.push(ctx.PL.mns[i]); });
      var top = ldMed(tops), gs = P.filter(function(p){ return p.gris != null; }).map(function(p){ return p.gris; });
      out.push({ name: l.name, rail: l.rail, t: Math.round(l.tm * 10) / 10, z: Math.round(z0 * 100) / 100,
        top: top, h: top != null ? Math.round((top - z0) * 100) / 100 : null, n: P.length, both: both, pts: P, gris: gs.length ? ldMed(gs) : null,
        guide: both ? [[side[-1].s, side[-1].z], [side[1].s, side[1].z]] : null });
    });
    // une voie trop haute par rapport aux autres (bretelle, butte) ou au-dessus du tablier n'est pas sous l'ouvrage
    out = out.filter(function(l){ return l.h == null || l.h > 0.5; });
    // v0.6.0 : une ligne par voie nommée (une route en diagonale sous le tablier est croisée à plusieurs positions) :
    // on garde la position la plus basse sous le tablier (hauteur minimale) et on compte les autres
    // (positions successives à 8 m au plus l'une de l'autre ; les deux chaussées d'une autoroute restent distinctes)
    if (src === 'osm') {
      out.sort(function(a, b){ return a.t - b.t; });
      var last = {}, kept = [];
      out.forEach(function(l){
        var key = (l.rail ? 'r:' : 'h:') + l.name, g = last[key];
        if (g && l.t - g.tEnd <= 8) {
          g.tEnd = l.t; g.best.nPos++;
          if (l.h != null && (g.best.h == null || l.h < g.best.h)) { l.nPos = g.best.nPos; kept[kept.indexOf(g.best)] = l; g.best = l; }
          return;
        }
        l.nPos = 1; last[key] = { tEnd: l.t, best: l }; kept.push(l);
      });
      out = kept;
    }
    out.sort(function(a, b){ return a.t - b.t; });
    var nz = 0, nn = 0;
    secs.forEach(function(sec){ sec.z.forEach(function(z){ nn++; if (z == null) nz++; }); });
    return { lanes: out, src: src, secs: secs, horsEmprise: nn ? nz / nn : 0 };
  }

  // Calcul complet. dtm, dsm : grilles ldTiff ; osm : réponse Overpass ({ elements }) ; img : imagerie ldImg ou null.
  // Repères : c = centre du tablier (origine du profil en long, s le long de u) ; x = croisement avec l'obstacle,
  // à sx mètres de c sur l'axe (origine du profil en travers et des sections de la voie du dessous).
  function ldCompute(o, dtm, dsm, osm, img){
    var det = QA.det(o.num) || {}, k = 1 / Math.cos(o.lat * Math.PI / 180), p0 = ldMerc(o.lat, o.lon);
    var ponceau = o.fam === 'ponceau';
    var ltb = o.ltb || det.ltm || o.long || (ponceau ? 6 : 20), lht = det.lht || det.lcm || o.larg || 10;
    var skew = det.bad || 0;
    var ways = (osm && osm.elements) || [], isBridge = function(w){ return w.tags && w.tags.bridge && w.tags.bridge !== 'no'; };
    var FL = ldDsmFilt(dtm, dsm, img, k), dsf = FL.F, inMask = function(x, y){ var v = ldSamp(FL.mask, x, y); return v != null && v >= 0.5; };
    // Ouvrage jumeau (n° terminé par N, S, E ou O et jumeau présent à l'inventaire) : direction du suffixe, pour choisir
    // le bon tablier ou le bon chemin OSM quand le point de l'inventaire tombe entre les deux
    var mJ = /^(.*\d)([NSEO])$/.exec(o.num || ''), OPP = { N: 'S', S: 'N', E: 'O', O: 'E' }, HINT = { N: [0, 1], S: [0, -1], E: [1, 0], O: [-1, 0] };
    var hint = mJ && QA.byNum && QA.byNum(mJ[1] + OPP[mJ[2]]) ? HINT[mJ[2]] : null;
    var lhtPx = function(m2){ return m2 / (dtm.sx / k * dtm.sy / k); };
    // 1. Axe de la route portée
    var carried = null, axisSrc, cands = [];
    ways.forEach(function(w){
      if (!w.tags || !w.tags.highway || w.tags.tunnel === 'yes' || (ponceau ? false : !isBridge(w))) return;
      var s = ldNearest(w, p0); if (s && s.d < 40 * k) cands.push(s);
    });
    cands.sort(function(a, b){ return a.d - b.d; });
    carried = cands[0] || null;
    if (hint && carried) cands.forEach(function(s){
      var side = function(q){ return (q.c[0] - p0[0]) * hint[0] + (q.c[1] - p0[1]) * hint[1]; };
      if (s.d <= cands[0].d + 12 * k && ldAngle(s.u, cands[0].u) < 20 && side(s) > side(carried)) carried = s;
    });
    var u, c, deck = null, rad = Math.max(25, Math.max(ltb, lht) / 2 + 10) * k, minDeck = lhtPx(Math.max(60, 0.15 * ltb * lht));
    if (carried) {
      u = carried.u; c = carried.c; axisSrc = 'axe OSM : ' + (carried.w.tags.name || carried.w.tags.ref || 'chemin sans nom') + (hint && cands.length > 1 ? ' (chaussée ' + { N: 'nord', S: 'sud', E: 'est', O: 'ouest' }[mJ[2]] + ', ouvrage jumeau)' : '');
      if (!ponceau) deck = ldPickDeck(FL, dtm, c, rad, minDeck, null, k);
    } else {
      // repli (v0.6.0) : tablier = composante du masque de l'ouvrage (MNS filtré) la plus proche du point de l'inventaire
      // (le point n'est pas toujours sur le tablier ; jumeaux : côté du suffixe). Axe = axe principal de ses pixels,
      // passant par leur centre de gravité (et non plus par le point GPS).
      deck = ponceau ? null : ldPickDeck(FL, dtm, p0, rad, minDeck, hint, k);
      c = p0;
      if (deck) {
        var sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0, nn = 0, w0 = dtm.w;
        for (var i9 = 0; i9 < FL.lab.length; i9++) {
          if (FL.lab[i9] !== deck.id) continue;
          var X = dtm.X0 + (i9 % w0 + 0.5) * dtm.sx - p0[0], Y = dtm.Y0 - (Math.floor(i9 / w0) + 0.5) * dtm.sy - p0[1];
          if (Math.hypot(X, Y) > rad) continue;
          sx += X; sy += Y; sxx += X * X; syy += Y * Y; sxy += X * Y; nn++;
        }
        var mx = sx / nn, my = sy / nn, th = 0.5 * Math.atan2(2 * (sxy / nn - mx * my), (sxx / nn - mx * mx) - (syy / nn - my * my));
        u = [Math.cos(th), Math.sin(th)];
        c = [p0[0] + mx, p0[1] + my];
        // reprise sur tous les pixels du masque dans une bande de ± (demi-largeur + 2 m) autour de ce premier axe : un
        // tablier coupé en morceaux (circulation au levé) donne sinon un axe légèrement de travers ; le jumeau, au-delà, est exclu
        if (lht <= ltb * 1.1) {
          var band9 = (lht / 2 + 2) * k, n2 = 0, s2x = 0, s2y = 0, s2xx = 0, s2yy = 0, s2xy = 0;
          for (var j9 = 0; j9 < FL.lab.length; j9++) {
            if (FL.lab[j9] <= 0) continue;
            var X2 = dtm.X0 + (j9 % w0 + 0.5) * dtm.sx - p0[0], Y2 = dtm.Y0 - (Math.floor(j9 / w0) + 0.5) * dtm.sy - p0[1];
            if (Math.hypot(X2, Y2) > rad || Math.abs((X2 - mx) * -u[1] + (Y2 - my) * u[0]) > band9) continue;
            s2x += X2; s2y += Y2; s2xx += X2 * X2; s2yy += Y2 * Y2; s2xy += X2 * Y2; n2++;
          }
          if (n2 > nn) {
            mx = s2x / n2; my = s2y / n2; nn = n2;
            th = 0.5 * Math.atan2(2 * (s2xy / n2 - mx * my), (s2xx / n2 - mx * mx) - (s2yy / n2 - my * my));
            u = [Math.cos(th), Math.sin(th)]; c = [p0[0] + mx, p0[1] + my];
          }
        }
        // tablier plus large que long (viaduc d'échangeur) : l'axe principal des pixels est sa largeur
        if (lht > ltb * 1.1) u = [-u[1], u[0]];
        axisSrc = 'axe déduit du LiDAR (' + nn + ' pixels du tablier' + (lht > ltb * 1.1 ? ', tablier plus large que long' : '') + (hint ? ', ouvrage jumeau : tablier ' + { N: 'nord', S: 'sud', E: 'est', O: 'ouest' }[mJ[2]] : '') + ')';
      } else { u = [1, 0]; axisSrc = 'axe inconnu (est-ouest par défaut)'; }
    }
    // 1 bis. v0.6.0 : recalage latéral. Le chemin OSM peut être décalé du tablier (tracé approximatif, ligne médiane
    // entre deux ouvrages jumeaux) : on décale l'axe parallèlement à lui-même, de −15 à +15 m, on mesure la plage de
    // pixels de l'ouvrage autour du point pour chaque décalage, et on centre l'axe sur le tablier le plus proche.
    var latShift = 0;
    if (!ponceau) {
      var hl2 = Math.min(ltb / 2 + 20, 150), nrm0 = [-u[1], u[0]];
      var runLen = function(cc){
        var S2 = [], F2 = [];
        for (var s2 = -hl2; s2 <= hl2 + 1e-9; s2 += 1) {
          var X2 = cc[0] + u[0] * s2 * k, Y2 = cc[1] + u[1] * s2 * k, t2 = ldSamp(dtm, X2, Y2), z2 = ldSamp(dsf, X2, Y2);
          S2.push(s2); F2.push(inMask(X2, Y2) && t2 != null && z2 != null && z2 - t2 >= 1);
        }
        var r2 = ldRunAt(S2, F2, 3, 15);
        return r2 ? r2.s1 - r2.s0 : 0;
      };
      var offs = [], lMax = 0;
      for (var of = -15; of <= 15; of += 1) { var ln = runLen([c[0] + nrm0[0] * of * k, c[1] + nrm0[1] * of * k]); offs.push({ of: of, len: ln }); if (ln > lMax) lMax = ln; }
      // bandes contiguës de décalages « bons » (plage d'au moins 70 % de la meilleure) : une bande par tablier ; on prend
      // la plus proche de la position d'origine (jumeaux : à 6 m près, celle du côté du suffixe) et on se place en son milieu
      var bands = [], cur9 = null;
      offs.forEach(function(q){
        if (q.len > 0 && q.len >= 0.7 * lMax) { if (!cur9) { cur9 = { a: q.of, b: q.of }; bands.push(cur9); } cur9.b = q.of; }
        else cur9 = null;
      });
      bands.forEach(function(b){ b.mid = (b.a + b.b) / 2; b.d = b.a <= 0 && b.b >= 0 ? 0 : Math.min(Math.abs(b.a), Math.abs(b.b)); });
      bands.sort(function(a, b){ return a.d - b.d; });
      var pick = bands[0] || null;
      if (pick && hint) bands.forEach(function(b){ var dot = nrm0[0] * hint[0] + nrm0[1] * hint[1]; if (b.d <= bands[0].d + 6 && b.mid * dot > pick.mid * dot) pick = b; });
      if (pick && lMax >= 8 && Math.abs(pick.mid) >= 1.5) { latShift = pick.mid; c = [c[0] + nrm0[0] * pick.mid * k, c[1] + nrm0[1] * pick.mid * k]; }
    }
    // 2. Obstacle OSM (cours d'eau, voie ferrée, route du dessous) : chemin proche qui croise l'axe
    var obs = null, sxObs = 0;
    ways.forEach(function(w){
      if (carried && w === carried.w) return;
      if (w.tags && w.tags.highway && (isBridge(w) || ponceau)) return;
      var s = ldNearest(w, c); if (!s || s.d > 50 * k || ldAngle(s.u, u) < 35) return;
      if (!obs || s.d < obs.d) obs = s;
    });
    if (obs) {   // croisement de l'axe et de l'obstacle (s'il est proche) : position le long de l'axe, en mètres
      var det2 = u[0] * (-obs.u[1]) - u[1] * (-obs.u[0]);
      if (Math.abs(det2) > 1e-6) {
        var bx = obs.c[0] - c[0], by = obs.c[1] - c[1], t = (bx * (-obs.u[1]) - by * (-obs.u[0])) / det2;
        if (Math.abs(t) < 40 * k) sxObs = t / k;
      }
    }
    // 3. v0.6.0 : recalage du centre du tablier sur l'axe. Le point GPS de l'inventaire n'est pas toujours au milieu
    // de l'ouvrage : on lit le masque de l'ouvrage (MNS filtré) le long de l'axe et on prend la plage continue qui
    // contient le point (ou la plus proche, à moins de max(15 m, demi-longueur)). Plage plausible (40 à 160 % de la
    // longueur de l'inventaire, + 10 m) : son milieu devient le centre du tablier, sa longueur la longueur mesurée.
    var hl = Math.min(ltb / 2 + 100, 300), recal = null, dk0 = -ltb / 2, dk1 = ltb / 2;
    if (!ponceau) {
      var S1 = [], F1 = [];
      for (var s1 = -hl; s1 <= hl + 1e-9; s1 += 1) {
        // pixel de l'ouvrage, ou pixel surélevé sur l'axe : non vert (véhicule sur le tablier, absent du masque), ou vert mais
        // à 3 m ou plus au-dessus du sol (image décalée, branches au-dessus du tablier) ; trous de 5 m au plus tolérés
        var X1 = c[0] + u[0] * s1 * k, Y1 = c[1] + u[1] * s1 * k, t1 = ldSamp(dtm, X1, Y1), z1 = ldSamp(dsm, X1, Y1);
        var cI = Math.floor((X1 - dtm.X0) / dtm.sx), rI = Math.floor((dtm.Y0 - Y1) / dtm.sy), vg = cI >= 0 && rI >= 0 && cI < dtm.w && rI < dtm.h && FL.veg[rI * dtm.w + cI];
        S1.push(s1); F1.push(t1 != null && z1 != null && z1 - t1 >= 1 && (inMask(X1, Y1) || !vg || z1 - t1 >= 3));
      }
      var run = ldRunAt(S1, F1, 5, 15);
      if (run) {
        var Lm = run.s1 - run.s0, mid = (run.s0 + run.s1) / 2;
        recal = { Lm: Lm, shift: mid, ok: Lm >= 0.5 * ltb && Lm <= 1.6 * ltb + 10 };
        if (recal.ok) {
          c = [c[0] + u[0] * mid * k, c[1] + u[1] * mid * k]; sxObs = obs ? sxObs - mid : 0;   // sans obstacle OSM : profil en travers au centre
          var half2 = Math.max(Lm, ltb) / 2; dk0 = -half2; dk1 = half2;
          recal.cap = ldCap(mid >= 0 ? u : [-u[0], -u[1]]);
        }
      }
    }
    var x0 = [c[0] + u[0] * sxObs * k, c[1] + u[1] * sxObs * k];
    // 4. Direction du profil en travers : perpendiculaire tournée de ±biais
    var nrm = [-u[1], u[0]], dir = nrm, skewSrc = 'sans biais à l’inventaire', osmSkew = obs ? ldAngle(obs.u, nrm) : null;
    var T = Math.min(Math.max(lht / 2 + 90, 110), 160), step = hl > 200 ? 2 : 1;
    function prof(d, half, st, o0){
      var P = { s: [], mnt: [], mns: [], mnsB: [] }, O = o0 || c;
      for (var s = -half; s <= half + 1e-9; s += st) {
        var x = O[0] + d[0] * s * k, y = O[1] + d[1] * s * k;
        P.s.push(Math.round(s * 10) / 10); P.mnt.push(ldSamp(dtm, x, y)); P.mns.push(ldNear(dsf, x, y)); P.mnsB.push(ldSamp(dsm, x, y));
      }
      P.mns = ldMed1(P.mns, 1);
      return P;
    }
    if (skew > 0.5) {
      var cp = ldRot(nrm, skew), cm = ldRot(nrm, -skew);
      if (obs) { dir = Math.abs(cp[0] * obs.u[0] + cp[1] * obs.u[1]) >= Math.abs(cm[0] * obs.u[0] + cm[1] * obs.u[1]) ? cp : cm; skewSrc = 'biais de ' + nf1.format(skew) + '° (inventaire), sens pris sur l’axe OSM de l’obstacle'; }
      else {
        // sens du biais : celui le long duquel le terrain varie le moins hors du tablier (lit, route du dessous)
        var flat = function(d){ var P = prof(d, 60, 2, x0); return ldStd(P.mnt.filter(function(z, i){ return Math.abs(P.s[i]) > lht / 2 + 4; })); };
        dir = flat(cp) <= flat(cm) ? cp : cm; skewSrc = 'biais de ' + nf1.format(skew) + '° (inventaire), sens déduit du relief';
      }
    }
    var PL = prof(u, hl, step), PT = prof(dir, T, 1, x0), ptOrigin = x0, hd = (dk1 - dk0) / 2;
    // 5. Mesures
    var M = { ponceau: ponceau, ltb: ltb, lht: lht, skew: skew, skewSrc: skewSrc, osmSkew: osmSkew, axisSrc: axisSrc, obsSrc: obs ? (obs.w.tags.name || obs.w.tags.waterway || obs.w.tags.railway || obs.w.tags.highway) : null,
      recal: recal, lat: latShift, latCap: latShift ? ldCap(latShift > 0 ? [-u[1], u[0]] : [u[1], -u[0]]) : null, dk0: dk0, dk1: dk1, sx: sxObs, img: !!img, filt: { el: FL.nEl, veg: FL.nVeg, keep: FL.nKeep } };
    if (ponceau) {
      M.top = ldMed(PL.mnt.filter(function(z, i){ return Math.abs(PL.s[i]) <= 4; }));
      var pied = null, sPied = null;
      PT.s.forEach(function(s, i){ var z = PT.mnt[i]; if (Math.abs(s) <= 40 && z != null && (pied == null || z < pied)) { pied = z; sPied = s; } });
      M.under = pied; M.sUnder = sPied; M.h = M.top != null && pied != null ? M.top - pied : null;
      M.invRemblai = det.rem != null && det.pom != null ? det.rem + det.pom : null;
    } else {
      // dessus du tablier : MNS filtré là où il reste au-dessus du sol (le tablier) ; à défaut (tablier absent du masque :
      // ouvrage sous les arbres, levé ancien), MNS brut comme avant la v0.6.0
      var wTop = Math.max(3, Math.min(hd / 3, 10)), inTop = function(i){ return Math.abs(PL.s[i] - sxObs) <= wTop && PL.s[i] >= dk0 && PL.s[i] <= dk1; };
      var topF = PL.s.map(function(s, i){ return inTop(i) && PL.mns[i] != null && PL.mnt[i] != null && PL.mns[i] - PL.mnt[i] >= 0.5 ? PL.mns[i] : null; }).filter(function(z){ return z != null; });
      if (topF.length >= 3) { M.top = ldMed(topF); M.topSrc = 'filtré'; }
      else { M.top = ldMed(PL.mnsB.filter(function(z, i){ return inTop(i); })); M.topSrc = 'brut'; }
      // bords du tablier sur le profil en travers : on s'éloigne de 0 tant que le MNS filtré reste à moins de 2 m du dessus
      var i0 = PT.s.indexOf(0), edge = function(dirn){
        var last = 0, gap = 0;
        for (var i = i0; i >= 0 && i < PT.s.length && Math.abs(PT.s[i]) <= 60; i += dirn) {
          var z = PT.mns[i];
          if (z != null && M.top != null && z >= M.top - 2) { last = PT.s[i]; gap = 0; } else if (++gap > 2) break;
        }
        return last;
      };
      var eL = edge(-1), eR = edge(1), dflt = lht / 2 / Math.cos(Math.min(skew, 60) * Math.PI / 180);
      if (eR - eL < 3) { eL = -dflt; eR = dflt; M.edgeSrc = 'largeur de l’inventaire'; } else M.edgeSrc = 'bords du tablier lus au MNS filtré';
      var band = function(a, b){ var zs = [], ss = []; PT.s.forEach(function(s, i){ if (s >= a && s <= b && PT.mnt[i] != null) { zs.push(PT.mnt[i]); ss.push(s); } }); return zs.length ? { z: ldMed(zs), s: (a + b) / 2 } : null; };
      var L1 = band(eL - 7, eL - 1), R1 = band(eR + 1, eR + 7);
      M.eL = eL; M.eR = eR; M.bandL = L1; M.bandR = R1;
      if (L1 && R1) M.under = L1.z + (R1.z - L1.z) * (0 - L1.s) / (R1.s - L1.s);
      else M.under = (L1 || R1 || {}).z;
      if (M.under != null) M.under = Math.round(M.under * 100) / 100;
      M.h = M.top != null && M.under != null ? M.top - M.under : null;
      M.hlibre = o.hmin;
      M.epaisseur = M.h != null && o.hmin != null && o.obst === 'Route' ? M.h - o.hmin : null;
      // ancienne lecture (point bas à côté du tablier), pour comparaison
      var lo = null; PT.s.forEach(function(s, i){ if (Math.abs(s) >= lht / 2 + 3 && Math.abs(s) <= lht / 2 + 20 && PT.mnt[i] != null && (lo == null || PT.mnt[i] < lo)) lo = PT.mnt[i]; });
      M.under_min = lo;
      // v0.5.5 : chaussée(s) du dessous lues sur des sections de l'obstacle hors du pont (route, voie ferrée)
      if (o.obst !== "Cours d'eau") {
        var RU = ldRoadUnder(o, { c: x0, u: u, dir: dir, k: k, t0: dk0 - sxObs, t1: dk1 - sxObs, sOff: sxObs, ways: ways, carriedW: carried && carried.w, eL: eL, eR: eR, dtm: dtm, PL: PL, img: o.obst === 'Chemin de fer' ? null : img });   // ballast : la couleur ne distingue pas la voie
        M.secs = RU.secs; M.laneSrc = RU.src; M.horsEmprise = RU.horsEmprise;
        var okL = RU.lanes.filter(function(l){ return l.h != null; });
        if (okL.length) {
          var crit = okL.reduce(function(a, b){ return b.h < a.h ? b : a; });
          M.lanes = RU.lanes; M.crit = crit;
          M.under_band = M.under; M.h_band = M.h;
          M.under = crit.z; M.topCrit = crit.top; M.h = crit.h;
          M.epaisseur = o.hmin != null && o.obst === 'Route' ? M.h - o.hmin : null;
          ptOrigin = [x0[0] + u[0] * crit.t * k, x0[1] + u[1] * crit.t * k];
          PT = prof(dir, T, 1, ptOrigin);       // profil en travers repris sur la voie la plus basse sous le tablier
        }
      }
    }
    // pentes longitudinales de la route portée (approches et tablier), d'après le MNT et le MNS filtré ; fenêtres
    // comptées à partir des extrémités du tablier (mesurées si le recalage a réussi)
    var aw = M.ponceau ? [3, 40] : [5, 60], e0 = M.ponceau ? -hd : dk0, e1 = M.ponceau ? hd : dk1;
    var fL = ldFit(PL.s, PL.mnt, e0 - aw[1], e0 - aw[0]), fR = ldFit(PL.s, PL.mnt, e1 + aw[0], e1 + aw[1]);
    M.capL = ldCap([-u[0], -u[1]]); M.capR = ldCap(u);
    M.appL = fL && fL.s1 - fL.s0 >= 15 ? { pct: fL.b * 100, fit: fL } : null;
    M.appR = fR && fR.s1 - fR.s0 >= 15 ? { pct: fR.b * 100, fit: fR } : null;
    if (!ponceau && hd > 6) { var fD = ldFit(PL.s, PL.mns, dk0 + 2, dk1 - 2); M.deckSlope = fD ? { pct: fD.b * 100, fit: fD } : null; }
    var zl = PL.mnt.filter(function(z){ return z != null; });
    M.denivele = zl.length && M.under != null ? Math.min(Math.max.apply(null, zl.slice(0, zl.length >> 1)), Math.max.apply(null, zl.slice(zl.length >> 1))) - M.under : null;
    return { P: { long: PL, travers: PT }, M: M, c: c, x: x0, u: u, dir: dir, hl: hl, T: T, k: k, ptOrigin: ptOrigin, mask: FL.mask };
  }

  // Relief ombré local (Horn, azimut 315°, hauteur 45°) → image superposée à la mini-carte
  function ldHillshade(D, k){
    var w = D.w, h = D.h, a = D.a, cs = D.sx / k, cv = document.createElement('canvas');
    cv.width = w; cv.height = h;
    var ctx = cv.getContext('2d'), img = ctx.createImageData(w, h), px = img.data;
    var zen = (90 - 45) * Math.PI / 180, azm = (360 - 315 + 90) % 360 * Math.PI / 180, cz = Math.cos(zen), sz = Math.sin(zen);
    for (var y = 1; y < h - 1; y++) for (var x = 1; x < w - 1; x++) {
      var i = y * w + x, A = a[i - w - 1], B = a[i - w], C = a[i - w + 1], Dd = a[i - 1], F = a[i + 1], G = a[i + w - 1], H = a[i + w], I = a[i + w + 1];
      if (!isFinite(A + B + C + Dd + F + G + H + I)) continue;
      var dzdx = ((C + 2 * F + I) - (A + 2 * Dd + G)) / (8 * cs), dzdy = ((G + 2 * H + I) - (A + 2 * B + C)) / (8 * cs);
      var slope = Math.atan(Math.hypot(dzdx, dzdy)), aspect = Math.atan2(dzdy, -dzdx);
      var v = Math.max(0, cz * Math.cos(slope) + sz * Math.sin(slope) * Math.cos(azm - aspect)), g = 40 + v * 215;
      px[i * 4] = g * 0.96; px[i * 4 + 1] = g * 0.98; px[i * 4 + 2] = g; px[i * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    var sw = ldUnmerc(D.X0, D.Y0 - h * D.sy), ne = ldUnmerc(D.X0 + w * D.sx, D.Y0);
    return L.imageOverlay(cv.toDataURL('image/png'), [sw, ne], { opacity: 1 });
  }
  // v0.6.0 : masque de l'ouvrage (pixels gardés au MNS filtré) → calque hachuré de la mini-carte
  function ldMaskLayer(D){
    var w = D.w, h = D.h, cv = document.createElement('canvas'); cv.width = w; cv.height = h;
    var ctx = cv.getContext('2d'), img = ctx.createImageData(w, h), px = img.data;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var i = y * w + x; if (D.a[i] < 0.5) continue;
      var on = (x + y) % 4 < 2;                       // hachures diagonales : lisibles sans la couleur
      px[i * 4] = on ? 16 : 0; px[i * 4 + 1] = on ? 45 : 115; px[i * 4 + 2] = on ? 65 : 109; px[i * 4 + 3] = on ? 200 : 90;
    }
    ctx.putImageData(img, 0, 0);
    var sw = ldUnmerc(D.X0, D.Y0 - h * D.sy), ne = ldUnmerc(D.X0 + w * D.sx, D.Y0);
    return L.imageOverlay(cv.toDataURL('image/png'), [sw, ne], { opacity: 1, className: 'ld-mask' });
  }

  // Profil SVG : P = {s, mnt, mns (filtré), mnsB (brut)} ; opt = {label, deck: [s0, s1] zone de l'ouvrage, under: zone interpolée, marks, arrow, guide}
  function niceStep(v){ var p = Math.pow(10, Math.floor(Math.log10(v || 1))), f = v / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; }
  function ldProfile(el, P, o, onHover){
    var W = 760, H = o.h || 210, ml = 44, mr = 10, mt = 12, mb = 22, zs = [];
    P.mnt.concat(P.mns).forEach(function(z){ if (z != null) zs.push(z); });
    if (!zs.length) { el.innerHTML = '<p class="muted">Pas de données LiDAR sur ce profil.</p>'; return; }
    var zmin = Math.min.apply(null, zs), zmax = Math.max.apply(null, zs);
    (o.marks || []).concat(o.pts || []).forEach(function(m){ zmin = Math.min(zmin, m.z); zmax = Math.max(zmax, m.z); });
    var pad = Math.max(1, (zmax - zmin) * 0.1); zmin -= pad; zmax += pad;
    var s0 = P.s[0], s1 = P.s[P.s.length - 1];
    var X = function(s){ return ml + (s - s0) / (s1 - s0) * (W - ml - mr); }, Y = function(z){ return mt + (zmax - Math.max(zmin, Math.min(zmax, z))) / (zmax - zmin) * (H - mt - mb); };   // MNS brut écrêté au cadre
    var h = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(o.label) + '">';
    var stp = niceStep((zmax - zmin) / 4);
    for (var z = Math.ceil(zmin / stp) * stp; z <= zmax; z += stp) h += '<line x1="' + ml + '" x2="' + (W - mr) + '" y1="' + Y(z) + '" y2="' + Y(z) + '" stroke="#dce5eb"/><text x="' + (ml - 6) + '" y="' + (Y(z) + 4) + '" text-anchor="end" font-size="12" fill="#566e7c">' + nf1.format(z) + '</text>';
    var xs = niceStep((s1 - s0) / 6);
    for (var s = Math.ceil(s0 / xs) * xs; s <= s1; s += xs) h += '<text x="' + X(s) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="12" fill="#566e7c">' + Math.round(s) + ' m</text>';
    if (o.deck) h += '<rect x="' + X(o.deck[0]) + '" y="' + mt + '" width="' + (X(o.deck[1]) - X(o.deck[0])) + '" height="' + (H - mt - mb) + '" fill="#007f78" opacity=".08"/>';
    var area = 'M' + X(s0) + ' ' + Y(zmin);
    P.s.forEach(function(s, i){ if (P.mnt[i] != null) area += 'L' + X(s).toFixed(1) + ' ' + Y(P.mnt[i]).toFixed(1); });
    h += '<path d="' + area + 'L' + X(s1) + ' ' + Y(zmin) + 'Z" fill="#e6d8bb"/>';
    var seg = function(test){ var d = '', on = false; P.s.forEach(function(s, i){ var z = P.mnt[i]; if (z == null || !test(s)) { on = false; return; } d += (on ? 'L' : 'M') + X(s).toFixed(1) + ' ' + Y(z).toFixed(1); on = true; }); return d; };
    var u = o.under;
    h += '<path d="' + seg(function(s){ return !u || s < u[0] || s > u[1]; }) + '" fill="none" stroke="#8a6d3b" stroke-width="1.6"/>';
    if (u) h += '<path d="' + seg(function(s){ return s >= u[0] && s <= u[1]; }) + '" fill="none" stroke="#8a6d3b" stroke-width="1.6" stroke-dasharray="4 3"/>';
    // MNS brut en pointillé fin (seulement là où le filtre l'a modifié de plus de 0,3 m), puis MNS filtré en trait plein
    var raw = '', diff = P.s.map(function(s, i){ var b = P.mnsB ? P.mnsB[i] : null, f = P.mns[i]; return b != null && (f == null || Math.abs(b - f) > 0.3); }), on = false;
    P.s.forEach(function(s, i){
      var b = P.mnsB ? P.mnsB[i] : null;
      if (b == null || !(diff[i] || diff[i - 1] || diff[i + 1])) { on = false; return; }
      raw += (on ? 'L' : 'M') + X(s).toFixed(1) + ' ' + Y(b).toFixed(1); on = true;
    });
    if (raw) h += '<path d="' + raw + '" fill="none" stroke="#7d8f9b" stroke-width="1" stroke-dasharray="1.5 2.5" opacity=".95"/>';
    var line = ''; P.s.forEach(function(s, i){ if (P.mns[i] != null) line += (line ? 'L' : 'M') + X(s).toFixed(1) + ' ' + Y(P.mns[i]).toFixed(1); });
    h += '<path d="' + line + '" fill="none" stroke="#102d41" stroke-width="1.4" opacity=".9"/>';
    if (o.guide) h += '<line x1="' + X(o.guide[0][0]) + '" y1="' + Y(o.guide[0][1]) + '" x2="' + X(o.guide[1][0]) + '" y2="' + Y(o.guide[1][1]) + '" stroke="#c93a2b" stroke-width="1.6" stroke-dasharray="5 3"/>' +
      o.guide.map(function(g){ return '<circle cx="' + X(g[0]) + '" cy="' + Y(g[1]) + '" r="3.2" fill="#c93a2b"/>'; }).join('');
    (o.fits || []).forEach(function(f){
      h += '<line x1="' + X(f.s0) + '" y1="' + Y(f.z0) + '" x2="' + X(f.s1) + '" y2="' + Y(f.z1) + '" stroke="' + f.color + '" stroke-width="2.4" stroke-linecap="round" opacity=".85"/>' +
        '<text x="' + ((X(f.s0) + X(f.s1)) / 2) + '" y="' + (Math.min(Y(f.z0), Y(f.z1)) - 7) + '" text-anchor="middle" font-size="12" font-weight="700" fill="' + f.color + '" paint-order="stroke" stroke="#fff" stroke-width="3">' + esc(f.label) + '</text>';
    });
    (o.pts || []).forEach(function(q){ h += '<circle cx="' + X(q.s) + '" cy="' + Y(q.z) + '" r="3" fill="#fff" stroke="' + (q.color || '#c93a2b') + '" stroke-width="1.8"><title>' + esc(q.title || '') + '</title></circle>'; });
    (o.marks || []).forEach(function(m){
      var a0 = m.s0 != null ? m.s0 : s0, a1 = m.s1 != null ? m.s1 : s1;
      h += '<line x1="' + X(a0) + '" x2="' + X(a1) + '" y1="' + Y(m.z) + '" y2="' + Y(m.z) + '" stroke="' + m.color + '" stroke-width="1.2" stroke-dasharray="5 3"/>' +
        '<text x="' + (X(a1) - 4) + '" y="' + (Y(m.z) - 4) + '" text-anchor="end" font-size="12" font-weight="600" fill="' + m.color + '">' + esc(m.label) + '</text>';
    });
    if (o.arrow) {
      var ax = X(o.arrow.s);
      h += '<line x1="' + ax + '" x2="' + ax + '" y1="' + Y(o.arrow.z1) + '" y2="' + Y(o.arrow.z0) + '" stroke="#b3261e" stroke-width="1.6" marker-start="url(#ld-arr)" marker-end="url(#ld-arr)"/>' +
        '<text x="' + (ax + 7) + '" y="' + ((Y(o.arrow.z1) + Y(o.arrow.z0)) / 2 + 4) + '" font-size="12" font-weight="700" fill="#b3261e">' + esc(o.arrow.label) + '</text>';
    }
    h += '<defs><marker id="ld-arr" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#b3261e"/></marker></defs>';
    h += '<line class="cur" x1="0" x2="0" y1="' + mt + '" y2="' + (H - mb) + '" stroke="#566e7c" stroke-width="1" visibility="hidden"/>';
    h += '<rect x="' + ml + '" y="' + mt + '" width="' + (W - ml - mr) + '" height="' + (H - mt - mb) + '" fill="transparent"/></svg>';
    el.innerHTML = h;
    var svg = el.querySelector('svg'), cur = svg.querySelector('.cur');
    svg.addEventListener('pointermove', function(e){
      var r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W, sv = s0 + (x - ml) / (W - ml - mr) * (s1 - s0), i = 0, best = 1e9;
      P.s.forEach(function(s, j){ if (Math.abs(s - sv) < best) { best = Math.abs(s - sv); i = j; } });
      cur.setAttribute('x1', X(P.s[i])); cur.setAttribute('x2', X(P.s[i])); cur.setAttribute('visibility', 'visible');
      onHover(i);
    });
    svg.addEventListener('pointerleave', function(){ cur.setAttribute('visibility', 'hidden'); onHover(null); });
  }

  // ---- v0.6.0 : tableau récapitulatif (remplace les cartes « ld-chips » et « ld-slopes ») ----
  // Styles injectés une fois par le module (le fichier principal n'est pas modifié).
  function ldCss(){
    if (document.getElementById('qa-lidar-css')) return;
    var st = document.createElement('style'); st.id = 'qa-lidar-css';
    st.textContent =
      '.qa-recap{width:100%;border-collapse:collapse;font-size:.8rem;line-height:1.35}' +
      '.qa-recap th,.qa-recap td{padding:4px 8px;border-bottom:1px solid var(--line);vertical-align:baseline;text-align:left}' +
      '.qa-recap th{font-weight:500;color:var(--ink);white-space:nowrap}' +
      '.qa-recap td.qa-v{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;font-weight:650;color:var(--navy)}' +
      '.qa-recap td.qa-n{color:var(--muted);font-size:.75rem;width:100%}' +
      '.qa-recap tr.qa-g th{padding:9px 8px 3px;font-size:.6875rem;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:650;border-bottom:1px solid #b9c8d2}' +
      '.qa-recap tr.qa-g:first-child th{padding-top:0}' +
      '.qa-recap tr.qa-key th{font-weight:700;color:var(--navy)}.qa-recap tr.qa-key td.qa-v{font-size:.95rem}' +
      '.qa-recap tr.qa-key th,.qa-recap tr.qa-key td{background:#f1fbf7}.qa-recap tr.qa-key th{box-shadow:inset 3px 0 0 var(--teal)}' +
      '.ld-lanes .tbl td.n{color:var(--muted);font-size:.72rem}' +
      '@media(max-width:600px){.qa-recap tr{display:grid;grid-template-columns:minmax(0,1fr) auto}.qa-recap th{white-space:normal}' +
      '.qa-recap td.qa-n{grid-column:1/-1;padding-top:0;border-bottom:1px solid var(--line)}.qa-recap tr:not(.qa-g) th,.qa-recap tr:not(.qa-g) td.qa-v{border-bottom:0}.qa-recap tr.qa-g th{grid-column:1/-1}}';
    document.head.appendChild(st);
  }
  // Ligne du tableau : libellé, valeur (nombre + unité, ou texte déjà échappé si v est une chaîne), note courte (HTML échappé)
  function ldRow(label, v, unit, note, cls, dec){
    if (v == null || (typeof v === 'number' && !isFinite(v))) return '';
    var val = typeof v === 'string' ? v : (dec === 2 ? LD_NF2 : nf1).format(v) + (unit === '°' ? '°' : unit ? '&nbsp;' + unit : '');
    return '<tr' + (cls ? ' class="' + cls + '"' : '') + '><th scope="row">' + esc(label) + '</th><td class="qa-v">' + val + '</td><td class="qa-n">' + (note || '') + '</td></tr>';
  }
  var LD_NF2 = new Intl.NumberFormat('fr-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });   // altitudes et hauteurs : 2 décimales fixes
  function ldGroup(t){ return '<tr class="qa-g"><th colspan="3" scope="rowgroup">' + esc(t) + '</th></tr>'; }

  function ldRender(o, R, secs, srcs){
    ldCss();
    var M = R.M, dlg = $('#lidar-dialog'), body = dlg.querySelector('.ld-body'), eau = o.obst === "Cours d'eau";
    var pctTxt = function(v){ return (v > 0 ? '+' : v < 0 ? '−' : '') + nf1.format(Math.abs(v)) + '&nbsp;%'; };
    var rows = '';
    if (M.ponceau) {
      rows += ldGroup('Hauteurs (LiDAR)') + ldRow('Chaussée', M.top, 'm', 'MNT sur l’axe au droit du ponceau', '', 2) + ldRow('Pied du remblai', M.under, 'm', 'point le plus bas du profil en travers à ± 40 m', '', 2) +
        ldRow('Remblai + ouverture', M.h, 'm', 'chaussée − pied du remblai', 'qa-key', 2) + ldRow('Remblai + ouverture (inventaire)', M.invRemblai, 'm', 'hauteur de remblai + ouverture du MTMD', '', 2);
    } else {
      var topV = M.crit ? M.topCrit : M.top;
      rows += ldGroup('Hauteurs (LiDAR)') +
        ldRow('Dessus du tablier', topV, 'm', (M.topSrc === 'brut' && !M.crit ? 'MNS brut (tablier absent du masque filtré)' : 'MNS filtré') + (M.crit ? ' au droit de la voie la plus basse' : ' au croisement de l’obstacle'), '', 2) +
        ldRow(eau ? 'Eau (interpolée)' : M.crit ? 'Chaussée sous l’ouvrage' : 'Dessous (interpolé)', M.under, 'm',
          eau ? 'MNT de part et d’autre du tablier : surface de l’eau au levé, pas le lit' : M.crit ? 'voie « ' + esc(M.crit.name) + ' », lue hors du tablier et interpolée sous l’axe' : 'MNT de part et d’autre du tablier, interpolé', '', 2) +
        ldRow(eau ? 'Tablier au-dessus de l’eau' : 'Hauteur sous l’ouvrage', M.h, 'm', 'dessus du tablier − ' + (eau ? 'eau' : 'dessous') + ', épaisseur du tablier comprise', 'qa-key', 2) +
        ldRow('Hauteur libre (inventaire)', M.hlibre, 'm', 'MTMD, sous le tablier', '', 2) +
        ldRow('Tablier + chaussée (estimé)', M.epaisseur > 0 ? M.epaisseur : null, 'm', 'hauteur LiDAR − hauteur libre MTMD', '', 2);
      if (M.h_band != null && M.h != null && Math.abs(M.h_band - M.h) > 0.3) rows += ldRow('Lecture simple (comparaison)', M.h_band, 'm', 'sol juste à côté du tablier, sur une seule ligne', '', 2);
    }
    rows += ldRow('Dénivelé du franchissement', M.denivele > 0.5 ? M.denivele : null, 'm', 'plus basse des deux approches − dessous');
    // géométrie : longueur mesurée, recalage du centre, biais
    var geo = '';
    if (M.recal && M.recal.ok) {
      geo += ldRow('Longueur du tablier (LiDAR)', M.recal.Lm, 'm', 'pixels de l’ouvrage le long de l’axe · inventaire ' + nf1.format(M.ltb) + ' m');
      geo += ldRow('Centre du tablier', Math.abs(M.recal.shift) < 1 ? 'au point' : nf1.format(Math.abs(M.recal.shift)) + '&nbsp;m',
        '', Math.abs(M.recal.shift) < 1 ? 'le point de l’inventaire est au milieu du tablier' : 'recalé vers ' + M.recal.cap + ' par rapport au point de l’inventaire');
    } else if (!M.ponceau) geo += ldRow('Centre du tablier', 'non recalé', '', M.recal ? 'pixels de l’ouvrage : ' + nf1.format(M.recal.Lm) + ' m sur l’axe, peu plausible pour ' + nf1.format(M.ltb) + ' m à l’inventaire' : 'pas de tablier surélevé lisible sur l’axe');
    if (M.lat) geo += ldRow('Axe décalé latéralement', nf1.format(Math.abs(M.lat)) + '&nbsp;m', '', 'vers ' + M.latCap + ', pour passer sur le tablier (pixels de l’ouvrage) plutôt que sur ' + (M.axisSrc.indexOf('OSM') >= 0 ? 'le tracé OSM' : 'l’axe initial'));
    if (!M.ponceau && Math.abs(M.sx) >= 1) geo += ldRow('Croisement de l’obstacle', nf1.format(Math.abs(M.sx)) + '&nbsp;m', '', 'du centre du tablier, vers ' + (M.sx > 0 ? M.capR : M.capL) + ' (axe OSM de l’obstacle)');
    geo += ldRow('Biais', M.skew || 0, '°', 'inventaire' + (M.osmSkew != null ? ' · mesuré sur l’axe OSM : ' + nf1.format(M.osmSkew) + '°' : ''));
    rows += ldGroup('Géométrie') + geo;
    // pentes longitudinales de la route portée (signe : + = monte vers l'ouvrage pour les approches ; vers le point cardinal indiqué sinon)
    var sl = '';
    if (M.appL) sl += ldRow('Approche côté ' + M.capL, pctTxt(M.appL.pct), '', M.appL.pct > 0.3 ? 'monte vers l’ouvrage' : M.appL.pct < -0.3 ? 'descend vers l’ouvrage' : 'à plat');
    if (M.deckSlope) sl += ldRow('Tablier', pctTxt(Math.abs(M.deckSlope.pct)), '', M.deckSlope.pct > 0.3 ? 'monte vers ' + M.capR : M.deckSlope.pct < -0.3 ? 'monte vers ' + M.capL : 'à plat');
    if (M.appR) sl += ldRow('Approche côté ' + M.capR, pctTxt(-M.appR.pct), '', -M.appR.pct > 0.3 ? 'monte vers l’ouvrage' : -M.appR.pct < -0.3 ? 'descend vers l’ouvrage' : 'à plat');
    if (sl) rows += ldGroup('Pentes de la route portée') + sl;
    var recap = '<table class="qa-recap"><tbody>' + rows + '</tbody></table>';
    var laneHtml = '';
    if (M.lanes && M.lanes.length) {
      var showG = M.lanes.some(function(l){ return l.gris != null; });
      var srcTxt = M.laneSrc === 'osm' ? 'repérées par OpenStreetMap' : M.laneSrc === 'relief+image' ? 'repérées par le relief et l’image (OSM absent)' : 'repérées par le relief (OSM absent)';
      laneHtml = '<div class="ld-lanes"><h3>Voies sous l’ouvrage <small>' + srcTxt + '</small></h3><table class="tbl"><thead><tr><th>Voie</th><th title="Position le long de l’axe du pont, comptée depuis le centre du tablier">Position</th><th>Chaussée</th><th>Dessus du tablier</th><th>Hauteur</th>' + (showG ? '<th title="Part grise (asphalte, béton) des fenêtres de lecture sur l’image satellite">Gris (image)</th>' : '') + '</tr></thead><tbody>' +
        M.lanes.map(function(l){
          return '<tr' + (l === M.crit ? ' class="crit"' : '') + '><td>' + (l === M.crit ? '<b>▸ </b>' : '') + esc(l.name) + (l.both ? '' : ' <small title="Sections d’un seul côté du tablier : altitude médiane, sans interpolation">(un côté)</small>') + (l.nPos > 1 ? ' <small title="Voie croisée à plusieurs positions sous le tablier : la hauteur la plus faible est retenue">(' + l.nPos + ' positions, hauteur minimale)</small>' : '') + '</td><td>' + nf1.format(l.t + M.sx) + ' m</td><td>' + LD_NF2.format(l.z) + ' m</td><td>' + (l.top != null ? LD_NF2.format(l.top) + ' m' : '—') + '</td><td><b>' + (l.h != null ? LD_NF2.format(l.h) + ' m' : '—') + '</b></td>' +
            (showG ? '<td>' + (l.gris != null ? Math.round(l.gris * 100) + ' %' : '—') + '</td>' : '') + '</tr>';
        }).join('') + '</tbody></table></div>';
    }
    var note = M.ponceau ? 'Chaussée : MNT sur l’axe au droit du ponceau ; pied du remblai : point le plus bas du profil en travers à ± 40 m.' :
      M.crit ? 'Hauteur = dessus du tablier (MNS filtré, au droit de la voie) − chaussée. La chaussée est lue sur 8 sections de l’obstacle parallèles au pont, à 4, 8, 12 et 16 m au-delà de chaque bord du tablier (' + esc(M.edgeSrc) + '), jamais sous le tablier : sur chaque section, la voie est repérée ' + (M.laneSrc === 'osm' ? 'par le tracé OpenStreetMap' : 'par les plages planes du relief' + (M.img ? ' qui sont grises sur l’image' : '')) + ', et son altitude est prise sur la fenêtre de 3 m la plus plane' + (M.img ? ' et la plus grise (asphalte plutôt que terre-plein gazonné)' : '') + '. L’altitude sous l’axe est interpolée entre les deux côtés ; la pente de l’obstacle n’est pas calculée.' :
      'Dessus du tablier : MNS filtré au croisement de l’obstacle. Dessous : sol (MNT) lu juste à l’extérieur des deux bords du tablier (' + esc(M.edgeSrc) + '), puis interpolé en ligne droite sous l’ouvrage (trait rouge pointillé).' +
      (!M.crit && M.under_min != null && M.under != null && Math.abs(M.under - M.under_min) > 0.3 ? ' Le point le plus bas à proximité (' + LD_NF2.format(M.under_min) + ' m, fossé ou berge) aurait donné ' + nf1.format(M.top - M.under_min) + ' m.' : '') +
      (eau ? ' Sur un cours d’eau, le MNT donne la surface de l’eau au moment du levé, pas le lit.' : '');
    note += ' MNS filtré : arbres, véhicules et poteaux retirés (pixels surélevés rugueux' + (M.img ? ' ou verts sur l’image' : '') + ', ou de moins de 25 m²), le profil suit alors le MNT ; le MNS brut reste en pointillé fin là où il diffère.';
    var douteux = M.h == null || M.h < (M.ponceau ? 1 : 0.8) || M.h > 80;
    var alerte = (M.horsEmprise > 0.2 ? '<div class="ld-warn"><b>Couverture partielle.</b> ' + Math.round(M.horsEmprise * 100) + ' % des points de lecture de la voie du dessous sont hors de la zone LiDAR téléchargée (ouvrage très long) : ils sont ignorés, pas extrapolés.</div>' : '') +
      (douteux ? '<div class="ld-warn"><b>Mesure non fiable.</b> ' + (R.osmOk ? 'Le relief autour de l’ouvrage ne permet pas de lire la hauteur (végétation, ouvrage masqué ou levé antérieur).' :
      'OpenStreetMap n’a pas répondu : l’axe a été déduit du LiDAR, ce qui échoue quand des arbres couvrent l’ouvrage.') + '</div>' : '') +
      (!R.osmOk ? '<button type="button" class="ld-retry" data-ld-retry>Réessayer avec OpenStreetMap</button>' : '');
    var recalOk = M.recal && M.recal.ok && Math.abs(M.recal.shift) >= 1;
    body.innerHTML = alerte + '<div class="ld-grid"><div class="ld-mapcol"><div class="ld-map" id="ld-map"></div>' +
      '<div class="ld-legend"><span><i style="background:repeating-linear-gradient(90deg,#007f78 0 6px,transparent 6px 9px)"></i>Profil en long (axe de la route, tireté)</span><span><i style="background:#c93a2b"></i>Profil en travers (le long de l’obstacle, plein)</span>' + (M.secs ? '<span><i style="background:#6a3d9a;height:2px"></i>Sections de l’obstacle hors du pont (fin)</span>' : '') +
      '<span><i style="width:10px;height:10px;border-radius:50%;background:#102d41"></i>Point de l’inventaire</span>' + (recalOk ? '<span><i style="width:10px;height:10px;border-radius:50%;background:#fff;border:2px solid #007f78"></i>Centre du tablier recalé</span>' : '') + '</div>' +
      '<p class="ld-meta">' + esc(M.axisSrc) + (M.obsSrc ? ' · obstacle OSM : ' + esc(M.obsSrc) : '') + ' · ' + esc(M.skewSrc) + '. Calque « Masque de l’ouvrage » (hachures) : pixels gardés au MNS filtré.</p></div>' +
      '<div class="ld-right">' + recap + laneHtml +
      '<div class="ld-pf"><h3>Profil en long <small>axe de la route portée · pas ' + (R.hl > 200 ? 2 : 1) + ' m</small></h3><div class="svg" id="ld-long"></div></div>' +
      '<div class="ld-pf"><h3>Profil en travers <small>le long de l’obstacle' + (M.crit ? ', sur la voie « ' + esc(M.crit.name) + ' »' : '') + (M.skew > 0.5 ? ', biais ' + nf1.format(M.skew) + '°' : '') + '</small></h3><div class="svg" id="ld-tr"></div></div>' +
      '<div class="ld-read" id="ld-read">Survoler un profil pour lire les altitudes.</div>' +
      '<div class="ld-keys"><span><i style="background:#102d41"></i>MNS filtré (surface, tablier)</span><span><i style="background:repeating-linear-gradient(90deg,#7d8f9b 0 2px,transparent 2px 5px)"></i>MNS brut (arbres, véhicules : pointillé)</span><span><i style="background:#e6d8bb;border:1px solid #8a6d3b"></i>MNT (sol nu)</span><span><i style="background:repeating-linear-gradient(90deg,#8a6d3b 0 4px,transparent 4px 7px)"></i>MNT interpolé sous l’ouvrage</span><span><i style="background:#007f78;opacity:.3"></i>Ouvrage</span></div>' +
      '<p class="ld-note">' + note + '</p></div></div>' +
      '<p class="ld-src">' + (secs == null ? 'Résultat déjà calculé dans cette session' : 'Calculé en ' + nf1.format(secs) + ' s dans le navigateur') + ' (' + esc(srcs) + ') · MNEHR 1 m © Ressources naturelles Canada (Licence du gouvernement ouvert – Canada) · Axes © contributeurs OpenStreetMap (ODbL)' +
      (M.img ? ' · Imagerie World Imagery © Esri et ses fournisseurs (couleurs : asphalte gris, végétation verte ; date de prise de vue différente du LiDAR)' : '') + '. ' +
      'Levés de dates variables (2018–2025) : un ouvrage reconstruit depuis peut différer.</p>';
    // Mini-carte : relief ombré local (MNS par défaut), lignes des profils
    if (ldMap) { ldMap.remove(); ldMap = null; }
    ldMap = L.map('ld-map', { zoomControl: true, attributionControl: false, zoomSnap: 0.25 });
    var gris = L.tileLayer(ESRI + 'Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom: 16, maxZoom: 20 });
    var hsS = ldHillshade(R.dsm, R.k), hsT = ldHillshade(R.dtm, R.k);
    var bases = {
      'Relief ombré local — MNS (surface)': L.layerGroup([gris, hsS]),
      'Relief ombré local — MNT (sol)': L.layerGroup([L.tileLayer(ESRI + 'Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom: 16, maxZoom: 20 }), hsT]),
      'Satellite': L.tileLayer(ESRI + 'World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom: 19, maxZoom: 20 })
    };
    bases['Relief ombré local — MNS (surface)'].addTo(ldMap);
    L.control.layers(bases, { 'Masque de l’ouvrage (hachures)': ldMaskLayer(R.mask) }, { collapsed: true }).addTo(ldMap);
    var ends = function(d, half){ return [ldUnmerc(R.c[0] - d[0] * half * R.k, R.c[1] - d[1] * half * R.k), ldUnmerc(R.c[0] + d[0] * half * R.k, R.c[1] + d[1] * half * R.k)]; };
    var lineL = ends(R.u, R.hl), lineT = [ldUnmerc(R.ptOrigin[0] - R.dir[0] * R.T * R.k, R.ptOrigin[1] - R.dir[1] * R.T * R.k), ldUnmerc(R.ptOrigin[0] + R.dir[0] * R.T * R.k, R.ptOrigin[1] + R.dir[1] * R.T * R.k)];
    (M.secs || []).forEach(function(sec){
      var a = ldUnmerc(sec.O[0] - R.u[0] * sec.t[sec.t.length - 1] * R.k, sec.O[1] - R.u[1] * sec.t[sec.t.length - 1] * R.k), b = ldUnmerc(sec.O[0] + R.u[0] * sec.t[sec.t.length - 1] * R.k, sec.O[1] + R.u[1] * sec.t[sec.t.length - 1] * R.k);
      L.polyline([a, b], { color: '#6a3d9a', weight: 1.2, opacity: 0.7, interactive: false }).addTo(ldMap);
    });
    (M.lanes || []).forEach(function(l){
      l.pts.forEach(function(q){
        var O = [R.x[0] + R.dir[0] * q.s * R.k + R.u[0] * q.t * R.k, R.x[1] + R.dir[1] * q.s * R.k + R.u[1] * q.t * R.k];
        L.circleMarker(ldUnmerc(O[0], O[1]), { radius: 3, color: '#6a3d9a', weight: 1.5, fillColor: '#fff', fillOpacity: 1 }).bindTooltip(esc(l.name) + ' · ' + LD_NF2.format(q.z) + ' m').addTo(ldMap);
      });
    });
    L.polyline(lineL, { color: '#007f78', weight: 3, dashArray: '7 5' }).bindTooltip('Profil en long').addTo(ldMap);
    L.polyline(lineT, { color: '#c93a2b', weight: 3.5 }).bindTooltip('Profil en travers (obstacle)').addTo(ldMap);
    L.circleMarker([o.lat, o.lon], { radius: 6, color: '#fff', weight: 2, fillColor: '#102d41', fillOpacity: 1 }).bindTooltip('Structure ' + o.num + ' (point de l’inventaire)').addTo(ldMap);
    if (recalOk) L.circleMarker(ldUnmerc(R.c[0], R.c[1]), { radius: 6, color: '#007f78', weight: 2.5, fillColor: '#fff', fillOpacity: 1 }).bindTooltip('Centre du tablier recalé (' + nf1.format(Math.abs(M.recal.shift)) + ' m vers ' + M.recal.cap + ')').addTo(ldMap);
    ldMap.fitBounds(L.latLngBounds(lineL.concat(lineT)), { padding: [14, 14] });
    var hov = L.circleMarker(lineL[0], { radius: 5, color: '#fff', weight: 2, fillColor: '#e8590c', fillOpacity: 1, interactive: false });
    function onHover(kind, P, ln){
      return function(i){
        if (i == null) { ldMap.removeLayer(hov); return; }
        var b = P.mnsB && P.mnsB[i], f = P.mns[i];
        $('#ld-read').textContent = (kind === 'long' ? 'Profil en long' : 'Profil en travers') + ' · s = ' + nf1.format(P.s[i]) + ' m · MNT ' + (P.mnt[i] != null ? LD_NF2.format(P.mnt[i]) : '—') + ' m · MNS ' + (f != null ? LD_NF2.format(f) : '—') + ' m' +
          (b != null && f != null && Math.abs(b - f) > 0.3 ? ' (brut ' + LD_NF2.format(b) + ' m, filtré)' : '');
        var t = (P.s[i] - P.s[0]) / (P.s[P.s.length - 1] - P.s[0]);
        hov.setLatLng([ln[0][0] + (ln[1][0] - ln[0][0]) * t, ln[0][1] + (ln[1][1] - ln[0][1]) * t]).addTo(ldMap);
      };
    }
    var hd = M.ltb / 2;
    var fitSeg = function(f, label){ return { s0: f.s0, s1: f.s1, z0: f.a + f.b * f.s0, z1: f.a + f.b * f.s1, label: label, color: '#6a3d9a' }; };
    var fitsL = [];
    if (M.appL) fitsL.push(fitSeg(M.appL.fit, nf1.format(Math.abs(M.appL.pct)) + ' %'));
    if (M.appR) fitsL.push(fitSeg(M.appR.fit, nf1.format(Math.abs(M.appR.pct)) + ' %'));
    if (M.deckSlope) fitsL.push(fitSeg(M.deckSlope.fit, nf1.format(Math.abs(M.deckSlope.pct)) + ' %'));
    var topS = M.ponceau ? 0 : M.sx;
    ldProfile($('#ld-long'), R.P.long, { label: 'Profil en long', deck: M.ponceau ? [-3, 3] : [M.dk0, M.dk1], under: M.ponceau ? null : [M.dk0, M.dk1], fits: fitsL,
      pts: (M.lanes || []).map(function(l){ return { s: M.sx + l.t, z: l.z, title: l.name + ' : chaussée ' + LD_NF2.format(l.z) + ' m' }; }),
      marks: M.top != null ? [{ z: M.top, label: (M.ponceau ? 'chaussée ' : 'tablier ') + nf1.format(M.top) + ' m', color: '#102d41', s0: topS - Math.max(hd, 8) * 1.6, s1: topS + Math.max(hd, 8) * 1.6 }] : [] }, onHover('long', R.P.long, lineL));
    var trOpt = { label: 'Profil en travers', h: 200 };
    if (M.ponceau) {
      if (M.h != null) trOpt.arrow = { s: M.sUnder, z0: M.under, z1: M.top, label: nf1.format(M.h) + ' m' };
    } else {
      trOpt.deck = [M.eL, M.eR];
      if (M.crit) {
        trOpt.pts = M.crit.pts.map(function(q){ return { s: q.s, z: q.z, title: 'Section à ' + nf1.format(q.s) + ' m : ' + LD_NF2.format(q.z) + ' m' }; });
        if (M.crit.guide) trOpt.guide = M.crit.guide;
        if (M.h != null) trOpt.arrow = { s: 0, z0: M.under, z1: M.topCrit, label: nf1.format(M.h) + ' m' };
        if (M.topCrit != null) trOpt.marks = [{ z: M.topCrit, label: 'tablier ' + nf1.format(M.topCrit) + ' m', color: '#102d41', s0: M.eL - 25, s1: M.eR + 25 }];
      } else {
        if (M.bandL && M.bandR) trOpt.guide = [[M.bandL.s, M.bandL.z], [M.bandR.s, M.bandR.z]];
        if (M.h != null) trOpt.arrow = { s: 0, z0: M.under, z1: M.top, label: nf1.format(M.h) + ' m' };
        if (M.top != null) trOpt.marks = [{ z: M.top, label: 'tablier ' + nf1.format(M.top) + ' m', color: '#102d41', s0: M.eL - 25, s1: M.eR + 25 }];
      }
    }
    ldProfile($('#ld-tr'), R.P.travers, trOpt, onHover('travers', R.P.travers, lineT));
  }

  // Chargement : rasters (MNT, MNS, imagerie) et chemins OSM mis en cache séparément par structure ; « Réessayer »
  // ne relance qu'OpenStreetMap (et l'imagerie si elle avait échoué), pas le WCS.
  function ldLoad(o){
    var k = 1 / Math.cos(o.lat * Math.PI / 180), p0 = ldMerc(o.lat, o.lon), det = QA.det(o.num) || {};
    var ltb = o.ltb || det.ltm || o.long || 20, lht = det.lht || det.lcm || o.larg || 10;
    var half = (Math.max(Math.min(ltb / 2 + 100, 300), Math.min(Math.max(lht / 2 + 90, 110), 160)) + 70) * k;
    var C = ldCache[o.num] || (ldCache[o.num] = {}), fresh = !(C.ras && C.osm);
    if (!C.ras) {
      var pr = C.ras = Promise.all([ldWcs('dtm', p0[0], p0[1], half), ldWcs('dsm', p0[0], p0[1], half), ldImg(p0[0], p0[1], half, k).catch(function(){ return null; })]);
      pr.catch(function(){ if (C.ras === pr) delete C.ras; });
    }
    if (!C.osm) C.osm = ldOsm(o.lat, o.lon).then(function(j){ return { j: j, src: 'axes OSM', ok: true }; }, function(){ return { j: { elements: [] }, src: 'OSM indisponible', ok: false }; });
    return Promise.all([C.ras, C.osm]).then(function(r){ return { dtm: r[0][0], dsm: r[0][1], img: r[0][2], osm: r[1], fresh: fresh }; });
  }
  function openLidar(o){
    var dlg = $('#lidar-dialog'), run = ++ldRun;
    ldCur = o;
    dlg.querySelector('#ld-title').textContent = 'Profil LiDAR · N° ' + o.num;
    dlg.querySelector('#ld-sub').textContent = [o.route, o.obstacle].filter(Boolean).join(' → ') || (o.nom || '');
    dlg.querySelector('.ld-body').innerHTML = '<div class="ld-wait"><span class="ld-spin"></span>MNT et MNS LiDAR (RNCan), imagerie satellite et axes OpenStreetMap, en parallèle…</div>';
    dlg.style.transform = '';
    if (!dlg.open) dlg.showModal();
    var t0 = performance.now();
    ldLoad(o).then(function(res){
      if (run !== ldRun || !dlg.open) return;
      if (res.dtm.ok < 0.2 || res.dsm.ok < 0.2) { dlg.querySelector('.ld-body').innerHTML = '<div class="ld-wait">Pas de couverture LiDAR (MNEHR) à cet endroit.</div>'; return; }
      var R = ldCompute(o, res.dtm, res.dsm, res.osm.j, res.img);
      R.dtm = res.dtm; R.dsm = res.dsm; R.osmOk = res.osm.ok;
      ldRender(o, R, res.fresh ? (performance.now() - t0) / 1000 : null, 'WCS RNCan, ' + res.osm.src + (res.img ? ', imagerie Esri' : ', imagerie indisponible'));
    }).catch(function(e){
      if (run !== ldRun) return;
      dlg.querySelector('.ld-body').innerHTML = '<div class="ld-wait">Échec du chargement LiDAR (' + esc(e && e.name === 'AbortError' ? 'délai dépassé' : (e && e.message) || 'réseau') + '). Réessayer plus tard.</div>';
    });
  }
  QA.wireDialog($('#lidar-dialog'), function(){ ldRun++; if (ldMap) { ldMap.remove(); ldMap = null; } });
  $('#lidar-dialog').addEventListener('click', function(e){
    if (e.target.closest('[data-ld-retry]') && ldCur) {
      var C = ldCache[ldCur.num];
      if (C) { delete C.osm; if (C.ras) C.ras.then(function(r){ if (!r[2] && ldCache[ldCur.num] === C) delete C.ras; }); }
      setTimeout(function(){ openLidar(ldCur); }, 0);
    }
  });
  window.QA_MOD.lidar = { open: openLidar,
    // fonctions exposées pour les essais (console, tests/js/viewer_pure.mjs extrait les pures par leur nom)
    _t: { ldLoad: ldLoad, ldCompute: ldCompute, ldDsmFilt: ldDsmFilt, ldRgbClass: ldRgbClass, ldRgbAt: ldRgbAt, ldRunAt: ldRunAt, ldMerc: ldMerc, ldSamp: ldSamp } };
})();
