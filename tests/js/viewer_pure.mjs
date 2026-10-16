// Tests des fonctions pures du visualiseur (audit v0.5.5 n° 10) : extraites du HTML courant sans le réécrire.
// Lancé par tests/test_js.py (node tests/js/viewer_pure.mjs).
import { readFileSync, readdirSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const html = readdirSync(root).filter(f => /^QuickerAtlasOA-v[\d.]+-[\d-]+\.html$/.test(f)).sort().pop();
// v0.6.0 : le profil LiDAR est dans js/lidar.js (module à la demande)
const src = readFileSync(join(root, html), 'utf8') + '\n' + readFileSync(join(root, 'js', 'lidar.js'), 'utf8');

// Source d'une fonction nommée (accolades équilibrées ; les fonctions visées n'en ont pas dans leurs chaînes)
function extract(name) {
  const i = src.indexOf('function ' + name + '(');
  assert.ok(i >= 0, 'fonction absente : ' + name);
  let d = 0, j = src.indexOf('{', i);
  for (; j < src.length; j++) { if (src[j] === '{') d++; else if (src[j] === '}' && --d === 0) break; }
  return src.slice(i, j + 1);
}
const fn = (name, deps = '') => new Function(deps + extract(name) + '; return ' + name + ';')();

// ldSamp : bilinéaire dans l'emprise, null au-delà (constat P1 : 99,5 renvoyé loin à droite d'une grille 2 × 2)
const ldSamp = fn('ldSamp');
const G = { a: Float32Array.from([0, 1, 0, 1]), w: 2, h: 2, sx: 1, sy: 1, X0: 0, Y0: 2 };
assert.equal(ldSamp(G, 1.0, 1.0), 0.5);                  // centre
assert.equal(ldSamp(G, 0.5, 1.5), 0);                    // centre du pixel (0,0)
assert.equal(ldSamp(G, 1.5, 0.5), 1);                    // centre du pixel (1,1)
assert.equal(ldSamp(G, 2.0, 1.0), 1);                    // bord droit : tolérance d'un demi-pixel
assert.equal(ldSamp(G, 100, 1.0), null);                 // loin à droite
assert.equal(ldSamp(G, -0.6, 1.0), null);                // gauche
assert.equal(ldSamp(G, 1.0, 2.6), null);                 // haut
assert.equal(ldSamp(G, 1.0, -0.6), null);                // bas

// v0.6.0 : pixel le plus proche (MNS filtré, sans mélange tablier / sol au bord du masque)
const ldNear = fn('ldNear');
assert.equal(ldNear(G, 0.9, 1.9), 0);                    // pixel (0,0)
assert.equal(ldNear(G, 1.1, 1.9), 1);                    // pixel (0,1)
assert.equal(ldNear(G, 2.1, 1.0), null);                 // hors emprise

// v0.6.0 : classes de couleur de l'imagerie (asphalte gris, végétation verte)
const ldRgbClass = fn('ldRgbClass');
assert.equal(ldRgbClass([90, 125, 70]), 'veg');          // herbe
assert.equal(ldRgbClass([40, 62, 45]), 'veg');           // conifères sombres
assert.equal(ldRgbClass([110, 112, 115]), 'gris');       // asphalte
assert.equal(ldRgbClass([192, 199, 191]), 'gris');       // béton clair à peine verdâtre (tablier de 11795)
assert.equal(ldRgbClass([200, 185, 160]), 'autre');      // sol beige, herbe sèche
assert.equal(ldRgbClass([20, 25, 30]), 'ombre');
assert.equal(ldRgbClass(null), null);

// v0.6.0 : plage continue autour de 0 (trous tolérés), médiane glissante
const ldRunAt = fn('ldRunAt');
const S11 = [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5];
assert.deepEqual(ldRunAt(S11, [0, 1, 1, 1, 0, 1, 1, 0, 0, 0, 1], 1, 3), { s0: -4, s1: 1 });   // trou d'un échantillon franchi
assert.deepEqual(ldRunAt(S11, [0, 1, 1, 1, 0, 1, 1, 0, 0, 0, 1], 0, 3), { s0: 0, s1: 1 });
assert.deepEqual(ldRunAt(S11, [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0], 0, 4), { s0: -5, s1: -4 }); // la plus proche, à 4 m
assert.equal(ldRunAt(S11, [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 0, 3), null);                    // trop loin
const ldMed = fn('ldMed');
const ldMed1 = fn('ldMed1', extract('ldMed'));
assert.deepEqual(ldMed1([1, 1, 9, 1, 1, null, 2], 1), [1, 1, 1, 1, 1, null, 2]);              // pic isolé retiré
assert.equal(ldMed([3, null, 1, 2]), 2);

// v0.6.0 : MNS filtré sur une grille synthétique (MNT plat à 10 m, pixels de 1 m)
const ldDsmFilt = fn('ldDsmFilt', extract('ldMed') + extract('ldRgbClass') + extract('ldRgbAt'));
{
  const W = 40, T = new Float32Array(W * W).fill(10), A = new Float32Array(W * W).fill(10);
  const at = (x, y) => y * W + x;
  for (let y = 15; y <= 24; y++) for (let x = 5; x <= 34; x++) A[at(x, y)] = 17;                    // tablier lisse de 30 × 10 m, 7 m au-dessus du sol
  for (let y = 18; y <= 19; y++) for (let x = 18; x <= 21; x++) A[at(x, y)] = 19.5;                 // voiture haute sur le tablier
  for (let y = 21; y <= 23; y++) for (let x = 8; x <= 17; x++) A[at(x, y)] = 21;                   // camion : 30 m² lisses, posé sur le tablier
  for (let y = 2; y <= 8; y++) for (let x = 2; x <= 8; x++) A[at(x, y)] = 13 + (((x * 7 + y * 13) % 5) - 2) * 0.8;   // arbre (rugueux)
  for (let y = 33; y <= 35; y++) for (let x = 33; x <= 35; x++) A[at(x, y)] = 11.5;                 // voiture (lisse, 9 m² < 25 m²)
  const D = a => ({ a, w: W, h: W, sx: 1, sy: 1, X0: 0, Y0: W, ok: 1 });
  const R = ldDsmFilt(D(T), D(A), null, 1);
  assert.equal(R.F.a[at(10, 20)], 17);                   // tablier gardé
  assert.equal(R.mask.a[at(10, 20)], 1);
  assert.ok(Math.abs(R.F.a[at(19, 18)] - 17) < 0.01);    // voiture : altitude du tablier (pontage)
  assert.ok(Math.abs(R.F.a[at(12, 22)] - 17) < 0.01);    // camion écarté (posé sur une autre composante), puis ponté
  assert.equal(R.F.a[at(5, 5)], 10);                     // arbre retiré : MNT
  assert.equal(R.mask.a[at(5, 5)], 0);
  assert.equal(R.F.a[at(34, 34)], 10);                   // voiture isolée retirée
  assert.equal(R.F.a[at(0, 0)], 10);                     // sol inchangé
  assert.ok(R.lab[at(10, 20)] > 0 && R.lab[at(5, 5)] === 0);
}

// v0.6.0 : chaussée lue sur une section : fenêtre grise préférée au terre-plein gazonné
const ldPlat = fn('ldPlat', extract('ldMed'));
const ldRuns = fn('ldRuns', extract('ldMed'));
{
  const sec = { t: [], z: [], g: [] };
  for (let t = -8; t <= 8; t += 0.5) { sec.t.push(t); sec.z.push(5); sec.g.push(Math.abs(t) <= 3 ? 'gris' : 'veg'); }
  const pI = ldPlat(sec, 5, 4, true), p0 = ldPlat(sec, 5, 4, false);
  assert.ok(pI.t <= 2 && pI.gris === 1, 'fenêtre grise attendue, obtenu t = ' + pI.t);
  assert.equal(p0.t, 5);                                 // sans image : la plus plane, la plus proche de l'axe OSM
  const rI = ldRuns(sec, true), r0 = ldRuns(sec, false);
  assert.equal(rI.length, 1); assert.equal(rI[0].t, 0); assert.equal(rI[0].len, 6); assert.equal(rI[0].gris, 1);
  assert.equal(r0.length, 1); assert.equal(r0[0].len, 16);
}

// v0.6.1 : profil en long de la route : droite, parabole ou double pente, robuste aux pics ; alerte au-delà de 5 %
const ldGrade = fn('ldGrade');
{
  const S = [], bruit = i => ((i * 7919) % 11 - 5) * 0.004;               // bruit déterministe de ± 2 cm
  for (let s = -60; s <= 60; s += 1) S.push(s);
  // pente constante de 2 %, avec un camion (pic de 2,5 m sur 4 m) : la droite reste à 2 %
  let g = ldGrade(S, S.map((s, i) => 30 + 0.02 * s + bruit(i) + (s >= 10 && s < 14 ? 2.5 : 0)), -60, 60);
  assert.equal(g.type, 'droite'); assert.ok(Math.abs(g.g(0) - 0.02) < 0.001); assert.equal(g.warn, false);
  // courbe verticale en sommet : z = 31 − (s − 8)² / (2 × 2000) → parabole, rayon et sommet retrouvés
  g = ldGrade(S, S.map((s, i) => 31 - (s - 8) ** 2 / 4000 + bruit(i)), -60, 60);
  assert.equal(g.type, 'parabole'); assert.ok(g.sommet);
  assert.ok(Math.abs(g.R - 2000) / 2000 < 0.08, 'rayon ' + g.R);
  assert.ok(Math.abs(g.apex.s - 8) < 1.5 && Math.abs(g.apex.z - 31) < 0.03);
  assert.ok(Math.abs(g.g(-60) - 0.034) < 0.002 && Math.abs(g.g(60) + 0.026) < 0.002);
  // double pente : +1,5 % puis −2 % avec cassure à s = 10
  g = ldGrade(S, S.map((s, i) => 30 + (s < 10 ? 0.015 * (s - 10) : -0.02 * (s - 10)) + bruit(i)), -60, 60);
  assert.equal(g.type, 'double'); assert.ok(Math.abs(g.sb - 10) <= 3, 'cassure ' + g.sb);
  assert.ok(Math.abs(g.g(-30) - 0.015) < 0.002 && Math.abs(g.g(40) + 0.02) < 0.002);
  // pente de 8 % : signalée
  g = ldGrade(S, S.map((s, i) => 30 + 0.08 * s + bruit(i)), -60, 60);
  assert.equal(g.warn, true);
  // trop peu de points
  assert.equal(ldGrade([0, 1, 2], [1, 1, 1], 0, 2), null);
}

// csvCell : formules neutralisées, nombres et texte ordinaire inchangés
const csvCell = fn('csvCell');
assert.equal(csvCell('=1+1'), "'=1+1");
assert.equal(csvCell('@SUM(A1)'), "'@SUM(A1)");
assert.equal(csvCell(' \t=HYPERLINK("x")'), "\"' \t=HYPERLINK(\"\"x\"\")\"");
assert.equal(csvCell('-12,5'), '-12,5');
assert.equal(csvCell(12.5), '12,5');
assert.equal(csvCell('Pont; rivière'), '"Pont; rivière"');
assert.equal(csvCell(null), '');

// fetchT : le délai couvre la lecture du corps (constat n° 7)
const fetchT = fn('fetchT');
globalThis.window = globalThis;
globalThis.fetch = (url, opt) => Promise.resolve({ ok: true, json: () => new Promise((res, rej) => {
  opt.signal.addEventListener('abort', () => rej(Object.assign(new Error('abandon'), { name: 'AbortError' })));
}) });
await assert.rejects(fetchT('x', null, 20, 'json'), e => e.name === 'AbortError');
globalThis.fetch = () => Promise.resolve({ ok: false, status: 503 });
await assert.rejects(fetchT('x', null, 50, 'json'), /HTTP 503/);
console.log('viewer_pure : ok (' + html + ')');
