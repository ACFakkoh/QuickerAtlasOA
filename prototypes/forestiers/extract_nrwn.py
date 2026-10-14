"""Extrait les structures ferroviaires du Réseau ferroviaire national (RFN / NRWN, RNCan) pour le Québec.

Entrée : le dossier décompressé de nrwn_rfn_qc_shp_en.zip
  (https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_nrwn_rfn/qc/nrwn_rfn_qc_shp_en.zip, 5,4 Mo, édition 2014)
Sortie : cache/nrwn_structures.json  (lignes de ponts/tunnels + exploitant/propriétaire joints depuis TRACK)
Nécessite pyogrio (pip install pyogrio numpy) ; le reste de la chaîne n'en a pas besoin.
Usage : python extract_nrwn.py <dossier_shp>
"""
import json, struct, sys
from pathlib import Path
import pyogrio

ENC = "ISO-8859-1"


def lire(chemin, geom=True):
    meta, _fid, geoms, champs = pyogrio.raw.read(str(chemin), encoding=ENC, read_geometry=geom)
    noms = list(meta["fields"])
    return noms, {n: champs[i] for i, n in enumerate(noms)}, geoms


def wkb_points(b):
    """Coordonnées (lon, lat) d'un WKB Point ou LineString (petit-boutiste)."""
    t = struct.unpack_from("<I", b, 1)[0] & 0xFF
    if t == 1:
        return [struct.unpack_from("<2d", b, 5)]
    n = struct.unpack_from("<I", b, 5)[0]
    return [struct.unpack_from("<2d", b, 9 + 16 * i) for i in range(n)]


def main(dossier):
    d = Path(dossier)
    _, T, _ = lire(next(d.glob("*_TRACK.shp")), geom=False)
    piste = {nid: i for i, nid in enumerate(T["NID"].tolist())}
    sortie = []
    for suf, geom_type in (("STRUCTURE_1", "ligne"), ("STRUCTURE_0", "point")):
        _, F, G = lire(next(d.glob(f"*_{suf}.shp")))
        for i in range(len(G)):
            if G[i] is None:
                continue
            j = piste.get(F["TRACKNID"][i])
            pts = wkb_points(G[i])
            rec = {
                "geo": geom_type,
                "type": F["STRUCTYPE"][i],
                "classe": F["TRACKCLASS"][i],
                "subdiv": F["SUBDI1NAME"][i] if F["SUBDI1NAME"][i] != "None" else None,
                "pts": [[round(x, 5), round(y, 5)] for x, y in pts],
                "maj": F["ATTREVDATE"][i],
            }
            if j is not None:
                rec.update({"exploitant": T["OPERATOENA"][j], "exploitant_abr": T["OPERATORMK"][j],
                            "proprietaire": T["OWNERENA"][j], "usage": T["USETYPE"][j], "statut": T["STATUS"][j],
                            "autre": T["TRKUSR1ENA"][j]})
            sortie.append(rec)
    out = Path(__file__).parent / "cache" / "nrwn_structures.json"
    out.write_text(json.dumps(sortie, ensure_ascii=False), encoding="utf8")
    print(len(sortie), "structures ->", out)


if __name__ == "__main__":
    main(sys.argv[1])
