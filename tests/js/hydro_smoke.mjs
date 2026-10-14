// Test minimal de js/hydro.js : charge le module dans un faux « window » et vérifie les fonctions pures.
// Lancer : node tests/js/hydro_smoke.mjs
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
var require = createRequire(import.meta.url);

globalThis.window = {};
require('../../js/hydro.js');
var T = globalThis.window.QA_MOD.hydro._t;
var n = 0;
function ok(name, fn){ fn(); n++; console.log('ok  ' + name); }

ok('tokens : accents, mots vides, saint', function(){
  assert.deepEqual(T.tokens('Rivière des Outaouais'), ['outaouais']);
  assert.deepEqual(T.tokens('Rivière Saint-François'), ['st', 'francois']);
  assert.deepEqual(T.tokens('CHAUDIERE (RIVIERE) AU PONT-ROUTE 218 A SAINT-LAMBERT'), ['chaudiere', '218', 'st', 'lambert']);
  assert.deepEqual(T.tokens(''), []);
  assert.deepEqual(T.tokens(null), []);
});
ok('subset : même cours d’eau ou non', function(){
  assert.equal(T.subset(T.tokens('Rivière Chaudière'), T.tokens('CHAUDIERE (RIVIERE) AU PONT-ROUTE 218')), true);
  assert.equal(T.subset(T.tokens('Rivière Rouge'), T.tokens('OUAREAU (RIVIERE) PRES DE RAWDON')), false);
  assert.equal(T.subset([], ['x']), false);
});
ok('titleCase : noms de stations', function(){
  assert.equal(T.titleCase('CHAUDIERE (RIVIERE) AU PONT-ROUTE 218 A SAINT-LAMBERT'), 'Chaudière (Rivière) au Pont-Route 218 à Saint-Lambert');
});
ok('parseCsv : guillemets, nombres, vides', function(){
  var r = T.parseCsv('x,y,STATION_NUMBER,STATION_NAME,DRAINAGE_AREA_GROSS\r\n-71.2,46.5,02PJ005,"CHAUDIERE, (RIVIERE) ""X""",5829.0\n-70,47,02XX001,AUTRE,\n');
  assert.equal(r.length, 2);
  assert.equal(r[0].x, -71.2);
  assert.equal(r[0].STATION_NAME, 'CHAUDIERE, (RIVIERE) "X"');
  assert.equal(r[0].DRAINAGE_AREA_GROSS, 5829);
  assert.equal(r[1].DRAINAGE_AREA_GROSS, null);
  assert.equal(r[0].STATION_NUMBER, '02PJ005');
  assert.deepEqual(T.parseCsv(''), []);
});
ok('pickStation : plus proche, avantage au même nom, rayon', function(){
  var rows = [
    { x: -71.2150, y: 46.5880, STATION_NUMBER: 'A', STATION_NAME: 'CHAUDIERE (RIVIERE) AU PONT', STATUS_EN: 'Active' },
    { x: -71.2148, y: 46.5865, STATION_NUMBER: 'B', STATION_NAME: 'AFFLUENT (RUISSEAU)', STATUS_EN: 'Active' },
    { x: -75, y: 46.5, STATION_NUMBER: 'C', STATION_NAME: 'LOIN', STATUS_EN: 'Active' }
  ];
  var r = T.pickStation(rows, 46.58629, -71.21481, 'Rivière Chaudière', 40);
  // A (même nom) est à ~190 m, B (autre cours d’eau) à ~25 m : l’avantage de 3 km donne A
  assert.equal(r.n, 2);
  assert.equal(r.best.id, 'A');
  assert.equal(r.best.match, 'oui');
  // si le même nom est à plus de 3 km de plus, l’autre cours d’eau (signalé) l’emporte
  var far = [rows[1], { x: -71.21481 + 0.06, y: 46.58629, STATION_NUMBER: 'D', STATION_NAME: 'CHAUDIERE (RIVIERE) EN AVAL', STATUS_EN: 'Active' }];
  var rf = T.pickStation(far, 46.58629, -71.21481, 'Rivière Chaudière', 40);
  assert.equal(rf.best.id, 'B'); assert.equal(rf.best.match, 'non');
  var r2 = T.pickStation(rows, 46.58629, -71.21481, '', 40);
  assert.equal(r2.best.match, 'inconnu');
  assert.equal(T.pickStation(rows, 40, -60, 'X', 40).best, null);
});
ok('datumKind', function(){
  assert.equal(T.datumKind('ARBITRAIRE'), 'arbitraire');
  assert.equal(T.datumKind('ASSUMED DATUM'), 'arbitraire');
  assert.equal(T.datumKind('SERVICE GEODESIQUE DU CANADA'), 'geodesique');
  assert.equal(T.datumKind(''), 'inconnu');
  assert.equal(T.datumKind(null), 'inconnu');
});
ok('buildSeries / pickSeries / summary', function(){
  var ann = [];
  for (var y = 1990; y < 2000; y++) ann.push({ IDENTIFIER: 'X.' + y + '.level-niveaux', DATA_TYPE_EN: 'Water Level', MAX_VALUE: 24 + (y % 3), MAX_DATE: y + '-05-01', MIN_VALUE: 20 - (y % 2), MIN_DATE: y + '-09-01' });
  ann.push({ IDENTIFIER: 'X.1995.discharge-debit', DATA_TYPE_EN: 'Discharge', MAX_VALUE: 900, MAX_DATE: '1995-04-20', MIN_VALUE: 12, MIN_DATE: '1995-02-01' });
  var mon = []; for (var m = 1; m <= 12; m++) mon.push({ DATE: '1995-' + (m < 10 ? '0' : '') + m, MONTHLY_MEAN_LEVEL: 22, MONTHLY_MEAN_DISCHARGE: null });
  mon.push({ DATE: '1996-01', MONTHLY_MEAN_LEVEL: 22, MONTHLY_MEAN_DISCHARGE: null });   // année incomplète : pas de moyenne
  var lvl = T.buildSeries(ann, mon, 'Water Level'), dis = T.buildSeries(ann, mon, 'Discharge');
  assert.equal(lvl.length, 10);
  assert.equal(dis.length, 1);
  assert.equal(lvl[5].mean, 22);
  assert.equal(lvl[6].mean, null);
  assert.equal(lvl[0].y, 1990);
  var ps = T.pickSeries(lvl, dis);
  assert.equal(ps.kind, 'niveau');
  assert.equal(T.pickSeries(lvl.slice(0, 2), dis).kind, 'debit');
  assert.equal(T.pickSeries([], []), null);
  var s = T.summary(lvl);
  assert.equal(s.n, 10);
  assert.equal(s.maxRec.v, 26);
  assert.equal(s.minRec.v, 19);
  assert.equal(s.y1, 1999);
});
ok('médiane', function(){ assert.equal(T.median([3, 1, 2]), 2); assert.equal(T.median([1, 2, 3, 4]), 2.5); assert.equal(T.median([]), null); });
ok('zoneAt : dedans, dehors, trou', function(){
  // carré de ~100 m de côté autour de (46.5, -71.0), avec un trou central
  var d = 0.0005, sq = [[-71 - d, 46.5 - d], [-71 + d, 46.5 - d], [-71 + d, 46.5 + d], [-71 - d, 46.5 + d], [-71 - d, 46.5 - d]];
  var hole = [[-71 - d / 5, 46.5 - d / 5], [-71 - d / 5, 46.5 + d / 5], [-71 + d / 5, 46.5 + d / 5], [-71 + d / 5, 46.5 - d / 5], [-71 - d / 5, 46.5 - d / 5]];
  var f = [{ attributes: { Description: 'Zone de faible courant', No_rapport: 'R1' }, geometry: { rings: [sq, hole] } }];
  assert.equal(T.zoneAt(f, 46.5 + d / 2, -71).d, 0);                    // dans la zone
  var z = T.zoneAt(f, 46.5, -71);                                          // dans le trou : hors zone
  assert.ok(z.d > 0 && z.d < 30);
  assert.ok(T.zoneAt(f, 46.5 + 3 * d, -71).d > 20);                      // à ~ 55 m du bord
  assert.equal(T.zoneAt([], 46.5, -71), null);
  var both = f.concat([{ attributes: { Description: 'Zone de grand courant' }, geometry: { rings: [sq] } }]);
  assert.match(T.zoneAt(both, 46.5 + d / 2, -71).desc, /grand/);          // à égalité, le grand courant
  assert.equal(T.recurrence('Zone de grand courant'), '0-20 ans');
  assert.equal(T.recurrence('Zone de faible courant'), '20-100 ans');
});
ok('nearestReach / deepBasin / strahlerWord', function(){
  var feats = [
    { attributes: { O_STRAHLER: 1, PERENNITE: 'P' }, geometry: { paths: [[[-71.0010, 46.5], [-71.0010, 46.501]]] } },
    { attributes: { O_STRAHLER: 4, PERENNITE: 'I' }, geometry: { paths: [[[-71.0001, 46.4995], [-71.0001, 46.5005]]] } }
  ];
  var r = T.nearestReach(feats, 46.5, -71);
  assert.equal(r.ord, 4); assert.equal(r.per, 'I'); assert.ok(r.d < 10);
  assert.equal(T.nearestReach([], 46.5, -71), null);
  var b = T.deepBasin([
    { attributes: { Niveau: '2', Nom_bassin: 'Petit, Ruisseau', 'Superficie_(km2)': '27,5' } },
    { attributes: { Niveau: '1', Nom_bassin: 'Grand, Rivière', 'Superficie_(km2)': '6696,001896' } }
  ]);
  assert.equal(b.nom, 'Petit, Ruisseau'); assert.equal(b.km2, 27.5);
  assert.equal(T.deepBasin([]), null);
  assert.match(T.strahlerWord(0), /non classé/);
  assert.equal(T.strahlerWord(6), 'grande rivière');
});
ok('fmt : décimales fixes (fr-CA)', function(){
  assert.equal(T.fmt(5829, 0).replace(/\s/g, ' '), '5 829');
  assert.equal(T.fmt(20.6, 2), '20,60');
});

// Requête « de secours » : échec rapide -> relance ; réponse qui ne vient pas -> deuxième requête après 4 s ; deux échecs -> rejet
var calls = 0;
assert.equal(await T.hedged(function(){ calls++; return calls === 1 ? Promise.reject(new Error('x')) : Promise.resolve('ok2'); }), 'ok2');
n++; console.log('ok  hedged : relance immédiate après un échec');
var t0 = Date.now(), c2 = 0;
assert.equal(await T.hedged(function(){ c2++; return c2 === 1 ? new Promise(function(){}) : Promise.resolve('ok3'); }), 'ok3');
assert.ok(Date.now() - t0 >= 3900 && Date.now() - t0 < 6000);
n++; console.log('ok  hedged : deuxième requête après 4 s sans réponse');
await assert.rejects(T.hedged(function(){ return Promise.reject(new Error('non')); }), /non/);
n++; console.log('ok  hedged : rejet après deux échecs');

console.log('\n' + n + ' groupes de tests réussis');
