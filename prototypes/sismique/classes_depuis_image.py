"""Extrait la grille de classes de site (A-E) de la figure 10 de Rosset, Takahashi & Chouinard (2023)
(Geosciences 13(9):256, CC BY 4.0) a partir d'une image PNG de cette figure.
Georeference : graduations du cadre (voir constantes). Produit grille_classes.json + PNG transparent.
Usage : python classes_depuis_image.py [cache/figure10_rosset2023.png]
"""
import sys, json, os
import numpy as np
from PIL import Image

ICI = os.path.dirname(os.path.abspath(__file__))
REF = {1: (48, 241, 47), 2: (43, 2, 255), 3: (255, 254, 0), 4: (253, 154, 153), 5: (255, 0, 11)}  # A..E
# georeferencement par les graduations du cadre (mesurees sur l'image 1039x723)
X0, LON0, PXLON = 260.5, -74.0, 796.0     # px (centre de la graduation -74.0), lon, px/degre
Y0, LAT0, PXLAT = 90.5, 46.0, 778.67      # px de la graduation 46.0, px/degre
def lon2x(l): return X0 + (l - LON0) * PXLON
def lat2y(l): return Y0 + (LAT0 - l) * PXLAT

def classify(a, tol=34):
    """Classe chaque pixel par la couleur de reference la plus proche, en tolerant un assombrissement
    (traits fins noirs/gris translucides superposes : bleu fonce = classe B sous un trait)."""
    h, w, _ = a.shape
    lab = np.zeros((h, w), np.uint8)
    best = np.full((h, w), 1e9)
    for k, c in REF.items():
        r = np.array(c, float)
        s = np.clip((a @ r) / (r @ r), 0.45, 1.0)
        d = np.sqrt(((a - s[..., None] * r) ** 2).sum(2))
        m = (d < tol) & (d < best)
        lab[m] = k; best[m] = d[m]
    # masques : hors cadre, legende, fleche nord, echelle
    lab[:40, :] = 0; lab[692:, :] = 0; lab[:, :44] = 0; lab[:, 1016:] = 0
    lab[:292, :202] = 0
    lab[35:105, 940:1010] = 0
    lab[640:690, 760:990] = 0
    return lab

def masks(a):
    """pixels « eau/fond » (bleu clair, blanc) et « surcharge » (noir, gris fonce, orange = points de donnees)."""
    water = (np.abs(a - np.array([164, 206, 226])).sum(2) < 40) | (a.min(2) > 235)
    over = (a.sum(2) < 330) | ((a[..., 0] > 200) & (a[..., 1] > 90) & (a[..., 1] < 170) & (a[..., 2] < 80) & (np.abs(a[..., 1] - 154) > 20))
    return water, over

# ---------------------------------------------------------------------------
# Etape 2 : re-echantillonnage sur la grille native (cellule 0,004 deg, mesuree par analyse
# periodique des bords de blocs : 3,18 px en x, 3,11 px en y ; le texte de l'article dit « 0,01 deg »
# mais indique aussi 300 m x 400 m, ce qui correspond a 0,004 deg).
STEP = 0.004
def build_grid(lab, water, over):
    # bords de cellules : lon = -74.0 + 0.0023456 + k*STEP ; lat = 46.0 - 0.00054596 - k*STEP (phase mesuree)
    lon_e = -74.0 + 0.002345636
    lat_e = 46.0 - 0.000545961
    k0 = int(np.floor((-74.2745 - lon_e) / STEP)); k1 = int(np.ceil((-73.048 - lon_e) / STEP))
    lons = [lon_e + k * STEP for k in range(k0, k1 + 1)]       # bords ouest des cellules
    lat_top0 = lat_e + np.ceil((46.0726 - lat_e) / STEP) * STEP  # bord nord de la 1re rangee
    lats = []
    t = lat_top0
    while t > 45.225: lats.append(t); t -= STEP
    nx, ny = len(lons) - 1, len(lats) - 1
    grid = np.zeros((ny, nx), np.uint8)
    conf = np.zeros((ny, nx), np.float32)
    occl = np.zeros((ny, nx), bool)
    for j in range(ny):
        y_a, y_b = lat2y(lats[j]), lat2y(lats[j + 1])
        ya, yb = int(np.ceil(y_a - .5)), int(np.floor(y_b - .5))  # pixels dont le centre est dans la cellule
        if yb < ya: yb = ya
        for i in range(nx):
            x_a, x_b = lon2x(lons[i]), lon2x(lons[i + 1])
            xa, xb = int(np.ceil(x_a - .5)), int(np.floor(x_b - .5))
            if xb < xa: xb = xa
            if ya < 0 or yb >= lab.shape[0] or xa < 0 or xb >= lab.shape[1]: continue
            blk = lab[ya:yb + 1, xa:xb + 1].ravel()
            blk = blk[blk > 0]
            tot = (yb - ya + 1) * (xb - xa + 1)
            if len(blk) < max(2, 0.3 * tot):
                wsh = water[ya:yb + 1, xa:xb + 1].mean()
                osh = over[ya:yb + 1, xa:xb + 1].mean()
                if wsh < 0.4 and osh >= 0.35: occl[j, i] = True   # masque par un point/trait : a combler
                continue
            cnt = np.bincount(blk, minlength=6)
            grid[j, i] = cnt.argmax(); conf[j, i] = cnt.max() / len(blk)
    # comblement des cellules masquees par les symboles (vote des 8 voisines classees, >= 3 voisines)
    filled = 0
    for _ in range(3):
        upd = []
        for j, i in zip(*np.nonzero(occl & (grid == 0))):
            nb = grid[max(j - 1, 0):j + 2, max(i - 1, 0):i + 2].ravel(); nb = nb[nb > 0]
            if len(nb) >= 3: upd.append((j, i, np.bincount(nb, minlength=6).argmax()))
        for j, i, v in upd: grid[j, i] = v; conf[j, i] = 0.5; filled += 1
        if not upd: break
    return grid, lons, lats, conf, filled

if __name__ == '__main__':
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ICI, 'cache', 'figure10_rosset2023.png')
    a = np.array(Image.open(p).convert('RGB')).astype(int)
    lab = classify(a)
    print('pixels classes :', {k: int((lab == k).sum()) for k in REF})
    grid, lons, lats, conf, filled = build_grid(lab, *masks(a))
    print('cellules comblees (masquees par un symbole) :', filled)
    ny, nx = grid.shape
    print('grille', nx, 'x', ny, 'cellules ; cellules classees :', int((grid > 0).sum()),
          {k: int((grid == k).sum()) for k in range(1, 6)}, 'conf moy', float(conf[grid > 0].mean()))
    chars = '0ABCDE'
    out = {'source': 'Rosset, Takahashi & Chouinard (2023), Geosciences 13(9):256, fig. 10, CC BY 4.0',
           'doi': '10.3390/geosciences13090256', 'step': STEP, 'west': lons[0], 'north': lats[0],
           'nx': nx, 'ny': ny, 'rows': [''.join(chars[v] for v in r) for r in grid]}
    json.dump(out, open(os.path.join(ICI, 'cache', 'grille_classes_site_mtl.json'), 'w'))
    # PNG transparent, palette sequentielle (clarte decroissante A -> E) pour daltoniens, 4 px / cellule
    pal = {1: (255, 255, 178), 2: (161, 218, 180), 3: (65, 182, 196), 4: (44, 127, 184), 5: (37, 52, 148)}
    S = 4
    rgba = np.zeros((ny * S, nx * S, 4), np.uint8)
    for k, c in pal.items():
        m = np.kron(grid == k, np.ones((S, S), bool))
        rgba[m] = (*c, 200)
    Image.fromarray(rgba, 'RGBA').save(os.path.join(ICI, 'couche_classes_site_mtl.png'))
    print('bornes : O', lons[0], 'E', lons[-1], 'N', lats[0], 'S', lats[-1])
