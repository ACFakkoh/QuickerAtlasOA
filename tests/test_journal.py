"""Tests du journal des changements (P5) : écarts entre deux runs et export `data/journal.js`."""
import json
import sqlite3

from etl import build, db, merge


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    return conn


def _items(conn):
    return [tuple(r) for r in conn.execute("SELECT num_dossr, kind, champ, ancien, nouveau FROM changement ORDER BY id")]


def test_journaliser_premier_run_ne_journalise_rien():
    conn = _conn()
    assert merge.journaliser(conn, {}, {"00001": {"nom": "A", "icg": "3"}}, ("icg",), presence=True) == 0
    assert _items(conn) == []


def test_journaliser_ajouts_retraits_et_modifications():
    conn = _conn()
    old = {"00001": {"nom": "Pont A", "icg": "3", "ias": "vert"}, "00002": {"nom": "Pont B", "icg": "4", "ias": "vert"}}
    new = {"00001": {"nom": "Pont A", "icg": "2", "ias": "rouge"}, "00003": {"nom": "Pont C", "icg": None, "ias": None}}
    assert merge.journaliser(conn, old, new, ("icg", "ias"), presence=True) == 4
    assert _items(conn) == [
        ("00003", "ajout", None, None, "Pont C"),
        ("00002", "retrait", None, "Pont B", None),
        ("00001", "modif", "icg", "3", "2"),
        ("00001", "modif", "ias", "vert", "rouge"),
    ]


def test_journaliser_sans_presence_ignore_ajouts_et_retraits():
    conn = _conn()
    old = {"00001": {"inspection_generale": "2023-06-01"}, "00002": {"inspection_generale": None}}
    new = {"00001": {"inspection_generale": "2025-07-14"}, "00009": {"inspection_generale": "2025-01-01"}}
    assert merge.journaliser(conn, old, new, ("inspection_generale",), presence=False) == 1
    assert _items(conn) == [("00001", "modif", "inspection_generale", "2023-06-01", "2025-07-14")]


def test_export_journal(tmp_path):
    conn = _conn()
    db.record_run(conn, "wfs", "2026-08-01T06:00:00+00:00", status="ok", rows=10)
    conn.execute("UPDATE source_run SET finished_at = '2026-08-01T06:01:00+00:00'")
    for fin, note in (("2026-08-01T06:02:00+00:00", "0 changements"), ("2026-10-01T06:02:00+00:00", "3 changements")):
        conn.execute("INSERT INTO source_run (source, started_at, finished_at, status, note) VALUES "
                     "('consolidation', ?, ?, 'ok', ?)", (fin, fin, note))
    conn.executemany("INSERT INTO changement (detected_at, num_dossr, kind, champ, ancien, nouveau) VALUES (?,?,?,?,?,?)", [
        ("2026-10-01T06:02:00+00:00", "00001", "modif", "icg", "3", "2"),
        ("2026-10-01T06:02:00+00:00", "00003", "ajout", None, None, "Pont C"),
        ("2026-10-01T06:02:00+00:00", "00002", "retrait", None, "Pont B", None),
        ("2023-01-01T06:02:00+00:00", "00004", "modif", "icg", "4", "3"),       # au-delà de 730 jours : non exporté
    ])
    out = tmp_path / "journal.js"
    info = build.export_journal(conn, out, today="2026-10-11")
    txt = out.read_text(encoding="utf-8")
    assert txt.startswith("window.PQ_JOURNAL=") and txt.endswith(";\n")
    d = json.loads(txt[len("window.PQ_JOURNAL="):-2])
    assert d["debut"] == "2026-08-01" and d["generated"] == "2026-10-11"
    assert d["runs"] == [["2026-10-01", 3], ["2026-08-01", 0]]
    assert d["items"] == [
        ["2026-10-01", "00001", "modif", "icg", "3", "2"],
        ["2026-10-01", "00002", "retrait", None, "Pont B"],                       # queue de None retirée
        ["2026-10-01", "00003", "ajout", None, None, "Pont C"],
    ]
    assert info["rows"] == 3


def test_export_journal_vide(tmp_path):
    out = tmp_path / "journal.js"
    build.export_journal(_conn(), out, today="2026-10-11")
    d = json.loads(out.read_text(encoding="utf-8")[len("window.PQ_JOURNAL="):-2])
    assert d == {"generated": "2026-10-11", "debut": None, "runs": [], "items": []}


def test_import_refuse_ne_laisse_aucun_faux_evenement():
    """Audit v0.5.5 n° 3 : doublon de clé → le remplacement échoue, le journal reste vide et l'ancien état demeure."""
    import pytest
    conn = _conn()
    db.replace_table(conn, "structure_detail", [{"num_dossr": "00001", "inspection_generale": "2023-06-01"}])
    old = {r["num_dossr"]: dict(r) for r in conn.execute("SELECT * FROM structure_detail")}
    rows = [{"num_dossr": "00001", "inspection_generale": "2025-01-01"}, {"num_dossr": "00001", "inspection_generale": "2026-01-01"}]
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            merge.journaliser(conn, old, {r["num_dossr"]: r for r in rows}, ("inspection_generale",), presence=False, commit=False)
            db.replace_table(conn, "structure_detail", rows, commit=False)
    assert _items(conn) == []
    assert conn.execute("SELECT inspection_generale FROM structure_detail").fetchall()[0][0] == "2023-06-01"
