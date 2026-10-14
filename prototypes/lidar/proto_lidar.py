"""Prototype : relief ombré LiDAR et profils en long / en travers autour de quelques structures.

Sources (aucune clé requise) :
  - MNEHR / HRDEM 1 m de Ressources naturelles Canada (LiDAR aérien ; MNT = sol nu, MNS = surface,
    tablier compris), WCS 1.1.1 du Data Cube : https://datacube.services.geo.ca/wrapper/ogc/elevation-hrdem-mosaic
    (Licence du gouvernement ouvert – Canada) ;
  - axe des ouvrages : chemins OpenStreetMap (API Overpass, ODbL), faute d'axe dans les données du MTMD.

Sortie : `prototypes/lidar/profils.json`, lu par `prototypes/lidar/prototype-lidar.html`.
Usage : python prototypes/lidar/proto_lidar.py [--no-fetch]
"""
import argparse
import json
import math
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CACHE = HERE / "cache"
UA = "VisualisationPontsQC/0.1 (prototype LiDAR; contact: cheruelanthony@gmail.com)"
WCS = "https://datacube.services.geo.ca/wrapper/ogc/elevation-hrdem-mosaic"
OVERPASS = "https://overpass-api.de/api/interpreter"
R = 6378137.0

SITES = [
    {"num": "13716", "cas": "Viaduc urbain", "but": "Hauteur sous l'ouvrage et épaisseur du tablier, à comparer à la hauteur libre mesurée",
     "osm": "bridge", "approche": 120, "travers": 120},
    {"num": "03994", "cas": "Grand pont en vallée", "but": "Profondeur de la vallée, hauteur du tablier au-dessus de l'eau, pentes des approches",
     "osm": "bridge", "approche": 250, "travers": 300},
    {"num": "05041", "cas": "Petit pont rural en mauvais état (ICG 1)", "but": "Contexte hydraulique : lit, berges, plaine inondable, méandres",
     "osm": "bridge", "approche": 100, "travers": 250},
    {"num": "10082", "cas": "Ponceau sous un haut remblai d'autoroute", "but": "Hauteur du remblai mesurée au LiDAR, à comparer à l'épaisseur inscrite à l'inventaire",
     "osm": "road", "approche": 150, "travers": 150},
]


# --- Projections ---------------------------------------------------------------------------------
def merc(lat, lon):
    return math.radians(lon) * R, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R


def unmerc(x, y):
    return math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2), math.degrees(x / R)


# --- Réseau --------------------------------------------------------------------------------------
_last = {}


def fetch(url, data=None, name=None, fetch=True):
    path = CACHE / name if name else None
    if path and (path.exists() and (not fetch or path.stat().st_size > 0)):
        return path.read_bytes()
    urls = [url]
    body, err = None, None
    for attempt in range(6):
        u = urls[attempt % len(urls)]
        host = urllib.parse.urlsplit(u).netloc
        wait = _last.get(host, 0) + 1.5 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(u, data=data, headers={"User-Agent": UA})
            body = urllib.request.urlopen(req, timeout=120).read()
            break
        except Exception as e:                       # service saturé (504, 429) : on réessaie plus tard
            err = e
            time.sleep(5 * (attempt + 1))
        finally:
            _last[host] = time.monotonic()
    if body is None:
        raise err
    if path:
        CACHE.mkdir(exist_ok=True)
        path.write_bytes(body)
    return body


def read_tiff(b):
    """GeoTIFF flottant (tuilé, gros-boutiste, non compressé) du WCS → (tableau, x0, y0, pas)."""
    import io
    im = Image.open(io.BytesIO(b))
    t = im.tag_v2
    w, h = im.size
    tw, th = t[322], t[323]
    bo = ">" if b[:2] == b"MM" else "<"
    a = np.full((h, w), np.nan)
    nx = -(-w // tw)
    for i, (o, c) in enumerate(zip(t[324], t[325])):
        ty, tx = divmod(i, nx)
        tile = np.frombuffer(b[o:o + c], dtype=bo + "f4").reshape(th, tw).astype(float)
        y0, x0 = ty * th, tx * tw
        hh, ww = min(th, h - y0), min(tw, w - x0)
        a[y0:y0 + hh, x0:x0 + ww] = tile[:hh, :ww]
    a[a <= -32000] = np.nan
    sx, sy = t[33550][0], t[33550][1]
    X0, Y0 = t[33922][3], t[33922][4]
    return a, X0, Y0, sx, sy


def get_dem(kind, cx, cy, half, tag, fetch_ok):
    q = urllib.parse.urlencode({
        "service": "WCS", "version": "1.1.1", "request": "GetCoverage", "identifier": kind,
        "boundingbox": f"{cx - half},{cy - half},{cx + half},{cy + half},urn:ogc:def:crs:EPSG::3857",
        "format": "image/geotiff"})
    return read_tiff(fetch(f"{WCS}?{q}", name=f"{tag}_{kind}.tif", fetch=fetch_ok))


def sample(dem, xs, ys):
    """Interpolation bilinéaire (centres de pixels)."""
    a, X0, Y0, sx, sy = dem
    c = (np.asarray(xs) - X0) / sx - 0.5
    r = (Y0 - np.asarray(ys)) / sy - 0.5
    c0 = np.clip(np.floor(c).astype(int), 0, a.shape[1] - 2)
    r0 = np.clip(np.floor(r).astype(int), 0, a.shape[0] - 2)
    fc, fr = c - c0, r - r0
    v = (a[r0, c0] * (1 - fc) * (1 - fr) + a[r0, c0 + 1] * fc * (1 - fr) +
         a[r0 + 1, c0] * (1 - fc) * fr + a[r0 + 1, c0 + 1] * fc * fr)
    return v


def osm_axis(site, lat, lon, fetch_ok):
    """Chemin OSM le plus proche (pont si possible) → liste de (lat, lon)."""
    if site["osm"] == "bridge":
        q = f'[out:json][timeout:25];way(around:70,{lat},{lon})[highway][bridge];out geom;'
    else:
        q = f'[out:json][timeout:25];way(around:40,{lat},{lon})[highway~"motorway|trunk|primary|secondary|tertiary"];out geom;'
    js = json.loads(fetch(OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(), name=f"{site['num']}_osm.json", fetch=fetch_ok))
    best, bd = None, 1e18
    x0, y0 = merc(lat, lon)
    for w in js.get("elements", []):
        pts = [merc(g["lat"], g["lon"]) for g in w.get("geometry", [])]
        if len(pts) < 2:
            continue
        d = min(math.hypot(x - x0, y - y0) for x, y in densify(pts, 2))
        if d < bd:
            best, bd = (w, pts), d
    return best


def densify(pts, step):
    out = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / step))
        out += [(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(n)]
    out.append(pts[-1])
    return out


def hillshade(a, px, az=315, alt=45, z=2.0):
    gy, gx = np.gradient(np.nan_to_num(a, nan=np.nanmean(a)) * z, px)
    slope = np.pi / 2 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    azr, altr = math.radians(360 - az + 90), math.radians(alt)
    hs = np.sin(altr) * np.sin(slope) + np.cos(altr) * np.cos(slope) * np.cos(azr - aspect)
    return np.clip(hs, 0, 1)


def run(fetch_ok=True):
    con = sqlite3.connect(f"file:{ROOT / 'data' / 'ponts.sqlite'}?mode=ro", uri=True)
    out = []
    for site in SITES:
        row = con.execute("""select s.num_dossr, s.nom, s.route, s.obstacle, s.lat, s.lon, s.annee_construction, s.icg,
                                    s.hauteur_libre_min_m, d.longueur_tablier_m, d.longueur_totale_m, d.remblai_epaisseur_m,
                                    d.ponceau_ouverture_m, s.type_code, t.libelle, s.region, s.municipalite, d.largeur_hors_tout_m
                             from structure s left join structure_detail d using(num_dossr) left join type_structure t on t.code = s.type_code
                             where s.num_dossr = ?""", (site["num"],)).fetchone()
        keys = ["num", "nom", "route", "obstacle", "lat", "lon", "annee", "icg", "hlibre", "ltb", "ltm", "remblai", "ouverture", "tc", "type", "region", "muncp", "lht"]
        st = dict(zip(keys, row))
        lat, lon = st["lat"], st["lon"]
        k = 1 / math.cos(math.radians(lat))                         # m Mercator par m au sol
        ax = osm_axis(site, lat, lon, fetch_ok)
        x0, y0 = merc(lat, lon)
        if ax:
            way, pts = ax
            dens = densify(pts, 1)
            # centre = point de l'axe le plus proche de la structure ; direction locale = corde de ±15 m
            i = min(range(len(dens)), key=lambda j: math.hypot(dens[j][0] - x0, dens[j][1] - y0))
            a_, b_ = dens[max(0, i - int(15 * k))], dens[min(len(dens) - 1, i + int(15 * k))]
            cx, cy = dens[i]
            ux, uy = b_[0] - a_[0], b_[1] - a_[1]
            n = math.hypot(ux, uy)
            ux, uy = ux / n, uy / n
            osm = {"id": way["id"], "nom": way.get("tags", {}).get("name"), "ref": way.get("tags", {}).get("ref"),
                   "pont": way.get("tags", {}).get("bridge"), "couches": way.get("tags", {}).get("layer")}
        else:
            cx, cy, ux, uy, osm = x0, y0, 1.0, 0.0, None
        L = ((st["ltb"] or st["ltm"] or 20) / 2 + site["approche"])
        T = site["travers"]
        half = max(L, T) * k + 60 * k
        dtm = get_dem("dtm", cx, cy, half, site["num"], fetch_ok)
        dsm = get_dem("dsm", cx, cy, half, site["num"], fetch_ok)
        px = dtm[3] / k                                             # pas au sol (m)

        def profile(dx, dy, half_len, step=1.0):
            s = np.arange(-half_len, half_len + step / 2, step)
            xs, ys = cx + dx * s * k, cy + dy * s * k
            return s, sample(dtm, xs, ys), sample(dsm, xs, ys)

        s1, t1, m1 = profile(ux, uy, L)
        s2, t2, m2 = profile(-uy, ux, T)
        # Mesures. Tablier = MNS sur le tiers central de l'ouvrage. Sous un tablier, le MNT est INTERPOLÉ (le LiDAR ne
        # voit pas le sol sous le pont) : le dessous se lit donc dans le profil en travers, juste à côté du tablier
        # (bande de 3 à 20 m au-delà de la demi-largeur hors tout), là où l'obstacle (route, eau) est mesuré.
        half_deck = (st["ltb"] or 20) / 2
        half_w = (st["lht"] or 12) / 2
        on = np.abs(s1) <= max(3, half_deck / 3)
        deck = float(np.nanmedian(m1[on]))
        band = (np.abs(s2) >= half_w + 3) & (np.abs(s2) <= half_w + 20)
        sol = float(np.nanmin(t2[band]))
        sol_interp = float(np.nanmin(t1[np.abs(s1) <= max(3, half_deck * 0.8)]))
        mes = {"tablier_m": round(deck, 2), "dessous_m": round(sol, 2), "hauteur_sous_tablier_m": round(deck - sol, 2),
               "dessous_mnt_interpole_m": round(sol_interp, 2)}
        # pentes des approches (sur le MNS, de 0,6 à 1 × demi-longueur d'approche au-delà des culées)
        for side, sign in (("pente_approche_amont_pct", -1), ("pente_approche_aval_pct", 1)):
            sel = (sign * s1 > half_deck + 10) & (sign * s1 < half_deck + site["approche"] - 10)
            if sel.sum() > 10:
                p = np.polyfit(s1[sel], m1[sel], 1)[0] * sign
                mes[side] = round(float(p) * 100, 1)
        # dénivelé du franchissement : sur le profil en long, bord le plus bas des deux rives − fond
        crest = min(np.nanmax(t1[s1 < 0]), np.nanmax(t1[s1 > 0]))
        mes["denivele_franchissement_m"] = round(float(crest - min(sol, np.nanmin(t1))), 1)
        if st["hlibre"]:
            mes["epaisseur_tablier_estimee_m"] = round(deck - sol - st["hlibre"], 2)
        if site["num"] == "10082":
            # ponceau : chaussée (MNT au centre, le remblai fait partie du sol) − fond du cours d'eau (profil en travers)
            road = float(np.nanmedian(t1[np.abs(s1) <= 3]))
            lit = float(np.nanmin(t2[np.abs(s2) <= 60]))            # pied du remblai, côté entrée ou sortie
            mes.update({"chaussee_m": round(road, 2), "lit_m": round(lit, 2), "hauteur_remblai_lidar_m": round(road - lit, 2)})
        # relief ombré (image PNG) du MNT et du MNS, cadré sur ±half
        imgs = {}
        for kind, dem in (("mnt", dtm), ("mns", dsm)):
            hs = hillshade(dem[0], px)
            Image.fromarray((hs * 255).astype(np.uint8)).save(HERE / f"{site['num']}_{kind}.png", optimize=True)
            imgs[kind] = f"{site['num']}_{kind}.png"
        a, X0, Y0, sx, sy = dtm
        la1, lo0 = unmerc(X0, Y0)
        la0, lo1 = unmerc(X0 + sx * a.shape[1], Y0 - sy * a.shape[0])
        r2 = lambda v: [None if not np.isfinite(x) else round(float(x), 2) for x in v]
        out.append({
            "site": site, "structure": st, "osm": osm, "mesures": mes, "pas_m": round(px, 2),
            "centre": list(unmerc(cx, cy)), "axe": [ux, uy],
            "bornes": [[la0, lo0], [la1, lo1]], "images": imgs,
            "long": {"s": s1[::2].round(1).tolist(), "mnt": r2(t1[::2]), "mns": r2(m1[::2])},
            "travers": {"s": s2[::2].round(1).tolist(), "mnt": r2(t2[::2]), "mns": r2(m2[::2])},
            "lignes": {"long": [list(unmerc(cx - ux * L * k, cy - uy * L * k)), list(unmerc(cx + ux * L * k, cy + uy * L * k))],
                       "travers": [list(unmerc(cx + uy * T * k, cy - ux * T * k)), list(unmerc(cx - uy * T * k, cy + ux * T * k))]},
        })
        print(site["num"], st["route"], "→", st["obstacle"], mes, file=sys.stderr)
    payload = {"generated": time.strftime("%Y-%m-%d"), "sites": out,
               "sources": {"mne": "MNEHR 1 m (LiDAR) — Ressources naturelles Canada, Licence du gouvernement ouvert – Canada",
                           "axes": "© contributeurs OpenStreetMap (ODbL)", "inventaire": "MTMD / Données Québec (CC-BY 4.0)"}}
    (HERE / "profils.js").write_text("window.PROTO_LIDAR=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    run(fetch_ok=not ap.parse_args().no_fetch)
