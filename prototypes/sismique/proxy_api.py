"""Mini-proxy local pour l'API GraphQL CanSHM6 de RNCan (prototype uniquement).

Pourquoi : l'API repond avec DEUX en-tetes « Access-Control-Allow-Origin: * » ; les navigateurs rejettent
cette reponse (« multiple values ») et fetch() depuis une autre origine echoue. Ce proxy renvoie un seul en-tete.
Il limite aussi le debit (>= 0,5 s entre appels amont), met les reponses en cache (cache/proxy/) et
n'accepte que des requetes NBC2025 / canSHM6 de moins de 6 000 caracteres.

Usage : python proxy_api.py   (ecoute sur http://127.0.0.1:8766/graphql)
En production : remplacer par une fonction serverless (Cloudflare Worker, etc.) ou precalculer.
"""
import hashlib, json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests

AMONT = 'https://www.earthquakescanada.nrcan.gc.ca/api/canshm/graphql'
ICI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ICI, 'cache', 'proxy')
os.makedirs(CACHE, exist_ok=True)
verrou = threading.Lock()
dernier = [0.0]

class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length', '0'))
            q = json.loads(self.rfile.read(n))['query']
            if len(q) > 6000 or ('NBC2025' not in q and 'canSHM6' not in q): raise ValueError('requete refusee')
            f = os.path.join(CACHE, hashlib.sha1(q.encode()).hexdigest()[:20] + '.json')
            if os.path.exists(f):
                out = open(f, 'rb').read()
            else:
                with verrou:
                    d = 0.5 - (time.time() - dernier[0])
                    if d > 0: time.sleep(d)
                    r = requests.post(AMONT, json={'query': q}, timeout=60); dernier[0] = time.time()
                out = r.content
                if r.status_code == 200: open(f, 'wb').write(out)
            self.send_response(200)
        except Exception as e:
            out = json.dumps({'errors': [{'message': str(e)}]}).encode(); self.send_response(400)
        self.send_header('Content-Type', 'application/json'); self._cors(); self.send_header('Content-Length', str(len(out))); self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a): pass

if __name__ == '__main__':
    print('Proxy CanSHM6 sur http://127.0.0.1:8766/graphql (Ctrl+C pour arreter)')
    ThreadingHTTPServer(('127.0.0.1', 8766), H).serve_forever()
