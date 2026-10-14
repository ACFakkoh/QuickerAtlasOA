"""Tests de l'export `data/structures.js` (base SQLite en mémoire)."""
import json
import sqlite3

from etl import build, db


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    db.replace_table(conn, "type_structure", [{"code": 41, "libelle": "Pont à poutres en béton armé", "famille": "pont"}])
    base = {c: None for _, c, _ in build.COLS if c}
    db.replace_table(conn, "structure", [
        {**base, "num_dossr": "00009", "type_code": 41, "reseau": "Supérieur", "region": "Abitibi-Témiscamingue",
         "lat": 48.8611171, "lon": -77.1388844, "icg": "1", "ias": "vert", "ide_strct": 211038, "in_apex": 1,
         "fiche_url": "https://x/f?p=122:53::::53:P53_IDE_STRCT_0001:211038&cs=1D36ABC"},
        {**base, "num_dossr": "00010", "type_code": 41, "reseau": "Supérieur"},
    ])
    db.record_run(conn, "wfs", db.now(), status="ok", rows=2)
    return conn


def test_export(tmp_path):
    out = tmp_path / "structures.js"
    info = build.export(_conn(), out)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("window.STRUCTURES=") and text.endswith(";\n")
    d = json.loads(text[len("window.STRUCTURES="):-2])
    assert info["rows"] == 2 and d["cols"][0] == "num"
    row = dict(zip(d["cols"], d["rows"][0]))
    assert d["enums"]["reseau"][row["reseau"]] == "Supérieur"
    assert d["enums"]["region"][row["region"]] == "Abitibi-Témiscamingue"
    assert (row["lat"], row["lon"]) == (48.86112, -77.13888)            # arrondi à 5 décimales
    assert row["cs"] == "1D36ABC" and row["ide"] == 211038
    assert d["types"]["41"] == ["Pont à poutres en béton armé", "pont"]
    assert len(d["rows"][1]) < len(d["cols"])                           # queue de None retirée


def test_classe_obstacle():
    co = build.classe_obstacle
    assert co("Cours d'eau", "Rivière Ditton, branche ouest") == "Cours d'eau"
    assert co("Route standard", "Autoroute 40") == "Route"
    assert co("Chemin de fer", "Chemin de fer (CN)") == "Chemin de fer"
    assert co("Cours d'eau", "Rivière Noire et route 132") == "Mixte"
    assert co(None, "Ruisseau Vacher / Chemin de fer (CN)") == "Mixte"
    assert co("Route standard", "Chemin du Lac-Noir") == "Route"           # « Lac » dans un nom de chemin
    assert co("Passages pour animaux", "Passage pour piéton et animaux") == "Faune"
    assert co(None, None) is None


def test_export_obstacle(tmp_path):
    out = tmp_path / "structures.js"
    conn = _conn()
    db.replace_table(conn, "structure_detail", [{"num_dossr": "00009", "obstacle_type_voie": "Chemin de fer"}])
    build.export(conn, out)
    d = json.loads(out.read_text(encoding="utf-8")[len("window.STRUCTURES="):-2])
    row = dict(zip(d["cols"], d["rows"][0]))
    assert d["enums"]["obst"][row["obst"]] == "Chemin de fer"


def test_export_details_sans_import_odata(tmp_path):
    """Audit v0.5.5 n° 4 : base sans run OData réussi → export cohérent, date absente, pas de TypeError."""
    out = tmp_path / "details.js"
    info = build.export_details(_conn(), out)
    d = json.loads(out.read_text(encoding="utf-8")[len("window.STRUCTURE_DETAILS="):-2])
    assert info["rows"] == 0 and d["generated"] is None and d["data"] == {}
