// Tests des fonctions pures du visualiseur (audit v0.5.5 n° 10) : extraites du HTML courant sans le réécrire.
// Lancé par tests/test_js.py (node tests/js/viewer_pure.mjs).
import { readFileSync, readdirSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const html = readdirSync(root).filter(f => /^QuickerAtlasOA-v[\d.]+-[\d-]+\.html$/.test(f)).sort().pop();
const src = readFileSync(join(root, html), 'utf8');

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
