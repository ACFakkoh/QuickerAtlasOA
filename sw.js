// QuickerAtlasOA — cache des photos des structures (v0.5.6)
// Le serveur du MTMD n'envoie aucun en-tête de cache (ni Cache-Control, ni ETag, ni Last-Modified) : sans ce
// Service Worker, chaque survol ou ouverture de fiche retélécharge la photo (~45 ko). Ici : cache d'abord, réseau
// ensuite, 600 photos au plus (les plus anciennes sortent en premier). Actif seulement en http(s), pas en file://.
// Fraîcheur (audit v0.5.5 n° 8) : le cache porte la date des données (sw.js?v=AAAA-MM-JJ, passée par la page) ;
// à chaque mise à jour des données, les photos sont relues une fois et les anciens caches supprimés.
var V = new URL(self.location.href).searchParams.get('v') || '0';
var PREFIX = 'qa-photos-', CACHE = PREFIX + V, MAX = 600, PHOTO = /P_PESB_AFFCH_IMAGE/;

self.addEventListener('install', function(){ self.skipWaiting(); });
self.addEventListener('activate', function(e){
  e.waitUntil(caches.keys().then(function(names){
    return Promise.all(names.filter(function(n){ return n.indexOf(PREFIX) === 0 && n !== CACHE; }).map(function(n){ return caches.delete(n); }));
  }).then(function(){ return self.clients.claim(); }));
});

function trim(cache){
  return cache.keys().then(function(keys){
    if (keys.length <= MAX) return;
    return Promise.all(keys.slice(0, keys.length - MAX).map(function(k){ return cache.delete(k); }));
  });
}

self.addEventListener('fetch', function(e){
  var req = e.request;
  if (req.method !== 'GET' || !PHOTO.test(req.url)) return;
  e.respondWith(caches.open(CACHE).then(function(cache){
    return cache.match(req).then(function(hit){
      if (hit) return hit;
      return fetch(req).then(function(res){
        // réponse opaque (image sans CORS) : status 0 ; on la garde quand même, le navigateur l'affichera
        if (res && (res.ok || res.type === 'opaque')) e.waitUntil(cache.put(req, res.clone()).then(function(){ return trim(cache); }));
        return res;
      });
    });
  }));
});
