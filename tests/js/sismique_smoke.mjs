// Test de fumée de js/sismique.js (sans navigateur) : `node tests/js/sismique_smoke.mjs`
//  - parité de shardOf avec etl.sismique.shard_of (valeurs figées + 3 000 n° comparés à Python si disponible) ;
//  - décodage des entiers (échelle logarithmique), rang des valeurs, période de retour ;
//  - classe de site estimée (data/classes-site.js prioritaire, sinon k du lot) et axe des périodes LINÉAIRE du graphique.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const ici = path.dirname(fileURLToPath(import.meta.url));
const racine = path.resolve(ici, '..', '..');
globalThis.window = { QA_MOD: {} };
await import(pathToFileURL(path.join(racine, 'js', 'sismique.js')).href);
const T = window.QA_MOD.sismique._t;
assert.ok(T && typeof window.QA_MOD.sismique.render === 'function', 'module non enregistré');

let n = 0;
const ok = (nom, f) => { f(); n++; console.log('ok  ' + nom); };

// mêmes valeurs que SHARDS_REF dans tests/test_sismique.py
const REF = { '00002': '65', '00003': '2a', '03226': '62', '13247A': '77', '14346C': '58', '14949N': '2e', '99999': '68', '1': '04', 'ABC': '03', 'X-1': '6d' };
ok('shardOf : valeurs de référence', () => { for (const k of Object.keys(REF)) assert.equal(T.shardOf(k), REF[k], k); });

ok('shardOf : parité avec Python sur 3 000 n°', () => {
  const nums = [];
  for (let i = 1; i <= 3000; i++) nums.push(String(i * 3).padStart(5, '0') + (i % 7 === 0 ? 'ABCDNS'[i % 6] : ''));
  let py;
  try {
    py = JSON.parse(execFileSync('python', ['-I', '-c',
      'import json,sys; sys.path.insert(0, sys.argv[1]); from etl.sismique import shard_of; print(json.dumps([shard_of(n) for n in json.loads(sys.argv[2])]))',
      racine, JSON.stringify(nums)], { encoding: 'utf8' }));
  } catch (e) { console.log('    (Python indisponible : parité large ignorée)'); return; }
  assert.deepEqual(nums.map(T.shardOf), py);
});

ok('shardOf : clés valides', () => {
  for (let i = 0; i < 2000; i++) { const k = T.shardOf(String(i)); assert.match(k, /^[0-9a-f]{2}$/); assert.ok(parseInt(k, 16) < T.N_SHARDS); }
});

ok('decode : échelle logarithmique 1e-4 × 10^(q/1000)', () => {
  const rel = (a, b) => Math.abs(a - b) / b;
  assert.ok(rel(T.decode(0), 1e-4) < 1e-12);
  assert.ok(rel(T.decode(1000), 1e-3) < 1e-12);
  assert.ok(rel(T.decode(4000), 1) < 1e-12);
  assert.ok(rel(T.decode(2777), 0.05984115950603199) < 1e-12);   // valeurs calculées par etl.sismique.decoder
  assert.ok(rel(T.decode(4609), 4.064433291652128) < 1e-12);
  assert.ok(rel(T.decode(74), 0.00011857687481671603) < 1e-12);
});

ok('index et vec : classe → probabilité → mesure', () => {
  assert.equal(T.index(0, 0, 0), 0); assert.equal(T.index(0, 1, 0), 11); assert.equal(T.index(1, 0, 0), 33); assert.equal(T.index(4, 2, 10), 164);
  const row = [3]; for (let i = 0; i < T.NB_VAL; i++) row.push(1000 + i);
  const v = T.vec(row, 2, 1);                                      // classe C, 5 %
  assert.equal(v.length, 11);
  assert.ok(Math.abs(v[0] - T.decode(1000 + T.index(2, 1, 0))) < 1e-15);
  assert.ok(Math.abs(v[10] - T.decode(1000 + T.index(2, 1, 10))) < 1e-15);
});

ok('retour : période de retour (2 % ≈ 2 475 ans, 5 % ≈ 975, 10 % ≈ 475)', () => { assert.equal(T.retour(2), 2475); assert.equal(T.retour(5), 975); assert.equal(T.retour(10), 475); });

ok('classeEstimee : classes-site.js prioritaire, sinon k du lot, sinon null', () => {
  const row = [2]; for (let i = 0; i < T.NB_VAL; i++) row.push(1000);
  assert.equal(T.classeEstimee('00002', row, null), 'B');
  assert.equal(T.classeEstimee('00002', row, { '00002': 'D' }), 'D');
  assert.equal(T.classeEstimee('00002', row, { '00002': 'Z' }), 'B');          // valeur invalide ignorée
  assert.equal(T.classeEstimee('00002', [0].concat(row.slice(1)), {}), null);
  assert.equal(T.classeEstimee('x', null, undefined), null);
});

ok('axe des périodes linéaire coupé à 5 s (v0.6.1) : abscisses proportionnelles à T, Sa(10 s) hors de l’axe', () => {
  assert.equal(T.T_MAX, 5);
  assert.deepEqual(T.periodTicks(false), [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]);
  assert.deepEqual(T.periodTicks(true), [0, 1, 2, 3, 4, 5]);
  const v = [0.5, 0.4]; for (let i = 0; i < 9; i++) v.push(0.3);
  for (const narrow of [false, true]) {
    const ch = T.chart([{ id: 'C', label: 'Classe C', tag: 'C', est: false, st: { c: '#009E73', dash: '', m: 'tri' }, v }], narrow, false);
    const xs = ch.xs.slice(1), P = [0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 5];
    assert.equal(xs[8], null, 'Sa(10 s) hors de l’axe linéaire');
    const pente = (xs[7] - xs[6]) / (5 - 2);
    for (let k = 1; k < P.length; k++) assert.ok(Math.abs((xs[k] - xs[0]) - pente * (P[k] - P[0])) < 1e-6, 'abscisse non linéaire');
    assert.ok(ch.xs[0] < xs[0], 'PGA à gauche des périodes');
    assert.ok(!/échelle log/.test(ch.svg) && /Période T \(s\)/.test(ch.svg));
  }
});

ok('échelle log (v0.6.1) : abscisses proportionnelles à log T, 0,05 à 10 s', () => {
  assert.deepEqual(T.periodTicks(false, true), [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10]);
  const v = [0.5, 0.4]; for (let i = 0; i < 9; i++) v.push(0.3);
  const ch = T.chart([{ id: 'C', label: 'Classe C', tag: 'C', est: false, st: { c: '#009E73', dash: '', m: 'tri' }, v }], false, true);
  const xs = ch.xs.slice(1), P = [0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 5, 10];
  const pente = (xs[8] - xs[0]) / Math.log(10 / 0.05);
  for (let k = 1; k < P.length; k++) assert.ok(Math.abs((xs[k] - xs[0]) - pente * Math.log(P[k] / P[0])) < 1e-6, 'abscisse non logarithmique');
  assert.ok(/échelle log/.test(ch.svg));
});

ok('étiquettes des courbes : écart minimal respecté et bornes tenues', () => {
  const y = T.spread([100, 101, 102, 300, 299], 15, 20, 305);
  const s = y.slice().sort((a, b) => a - b);
  for (let k = 1; k < s.length; k++) assert.ok(s[k] - s[k - 1] >= 15 - 1e-9);
  assert.ok(s[0] >= 20 - 1e-9 && s[s.length - 1] <= 305 + 1e-9);
  assert.equal(y[3] > y[0], true);                     // l'ordre vertical est conservé
});

console.log(n + ' tests réussis');
