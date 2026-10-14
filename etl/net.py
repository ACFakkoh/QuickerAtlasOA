"""Client HTTP poli : User-Agent identifié, délai minimal par hôte, reprises."""
import time
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import MIN_INTERVAL_S, RAW_DIR, USER_AGENT

_last_hit: dict[str, float] = {}


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def wait(url: str) -> None:
    """Respecte le délai minimal avant une requête vers l'hôte de `url`."""
    host = urlsplit(url).netloc
    delay = _last_hit.get(host, 0) + MIN_INTERVAL_S - time.monotonic()
    if delay > 0:
        time.sleep(delay)
    _last_hit[host] = time.monotonic()


def get(s: requests.Session, url: str, *, timeout: float = 120, **kw) -> requests.Response:
    wait(url)
    r = s.get(url, timeout=timeout, **kw)
    r.raise_for_status()
    return r


def save_raw(name: str, content: bytes) -> None:
    """Conserve la dernière copie brute d'une source (débogage, rejouer un parse)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / name).write_bytes(content)
