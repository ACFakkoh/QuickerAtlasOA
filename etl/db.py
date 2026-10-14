"""Schéma SQLite et utilitaires d'écriture.

Chaque source écrit dans SA table (snapshot remplacé à chaque run) ; `merge.py`
construit ensuite la table consolidée `structure` et le journal `changement`.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,            -- ok | erreur
    rows        INTEGER,
    sha256      TEXT,                     -- empreinte du contenu normalisé
    note        TEXT
);

-- Flux WFS Données Québec (ms:gsq_v_desc_strct_tri) -------------------------
CREATE TABLE IF NOT EXISTS wfs_structure (
    num_dossr           TEXT PRIMARY KEY,
    ide_strct           INTEGER UNIQUE,
    nom                 TEXT,
    type_code           INTEGER,
    type_libelle        TEXT,
    route               TEXT,
    num_rts             TEXT,
    obstacle            TEXT,
    municipalite        TEXT,
    cod_muncp           INTEGER,
    centre_services     TEXT,
    direction_generale  TEXT,
    annee_construction  INTEGER,
    nb_voies            INTEGER,
    longueur_m          REAL,             -- val_longr (mm → m), longueur du tablier
    largeur_m           REAL,             -- val_largr_ (mm → m), largeur hors-tout
    lat                 REAL,
    lon                 REAL,
    cod_respn           INTEGER,          -- cod_type_r : 10 = MTQ, 13 = MTQ-Mun. (décret)…
    route_principale    INTEGER,          -- rte_ind_pr O/N
    deficient_etat      INTEGER,          -- ind_strct_ O/N (élément principal déficient)
    deficient_fonct     INTEGER,          -- ind_strc00 O/N (fonctionnalité déficiente)
    raw_json            TEXT              -- ligne d'origine complète
);

-- Liste de l'outil « Inventaire et inspection des structures » (APEX) --------
CREATE TABLE IF NOT EXISTS apex_structure (
    num_dossr               TEXT PRIMARY KEY,
    ide_strct               INTEGER,
    nom                     TEXT,
    type_code               INTEGER,
    type_libelle            TEXT,
    reseau                  TEXT,         -- Supérieur | Municipal
    direction_territoriale  TEXT,
    municipalite            TEXT,
    route                   TEXT,
    obstacle                TEXT,
    icg                     TEXT,         -- 1..4 | AC | SO
    ias                     TEXT,         -- vert | jaune | rouge | SO
    annee_travaux           INTEGER,
    rapport_dispo           INTEGER,
    fiche_url               TEXT,
    lim_hauteur             INTEGER,      -- drapeaux issus des filtres APEX
    lim_poids               INTEGER
);

-- Répertoire des hauteurs libres ---------------------------------------------
CREATE TABLE IF NOT EXISTS hauteur_libre (
    id              INTEGER PRIMARY KEY,
    num_ref         TEXT NOT NULL,        -- ex. 14240FA, 01542 (une ligne par route franchie)
    num_dossr       TEXT,                 -- = num_ref (n° de structure complet) → jointure
    route           TEXT,
    seq             INTEGER,
    municipalite    TEXT,
    obstacle        TEXT,
    dir_so          TEXT,
    hauteur_so_m    REAL,
    dir_ne          TEXT,
    hauteur_ne_m    REAL,
    detail_url      TEXT,
    UNIQUE (num_ref, route, seq)
);

-- GPS.csv (APEX) : seule source de la « limite de charge » -----------------------
CREATE TABLE IF NOT EXISTS gps_point (
    id              INTEGER PRIMARY KEY,
    lat             REAL,
    lon             REAL,
    nom             TEXT,
    route           TEXT,
    obstacle        TEXT,
    limite_charge   TEXT,
    annee           INTEGER,
    num_dossr       TEXT                  -- rempli par jointure de coordonnées
);

-- OData Structures_StructuresTabBord : détails complets de l'inventaire public ------
CREATE TABLE IF NOT EXISTS structure_detail (
    num_dossr               TEXT PRIMARY KEY,
    ide_strct               INTEGER,
    region_admin            TEXT,
    mrc                     TEXT,
    cep                     TEXT,
    classe_route            TEXT,
    route_type_voie         TEXT,
    nb_voies                INTEGER,
    djma                    INTEGER,
    pct_camion              INTEGER,
    obstacle_type_voie      TEXT,
    obstacle_classe_route   TEXT,
    longueur_totale_m       REAL,
    longueur_tablier_m      REAL,
    largeur_carrossable_m   REAL,
    largeur_hors_tout_m     REAL,
    superficie_tablier_m2   REAL,
    biais_type              INTEGER,
    biais_angle_deg         REAL,
    ponceau_ouverture_m     REAL,
    ponceau_superficie_m2   REAL,
    remblai_epaisseur_m     REAL,
    mur_longueur_m          REAL,
    mur_hauteur_moy_m       REAL,
    mur_superficie_m2       REAL,
    tunnel_longueur_m       REAL,
    tunnel_largeur_m        REAL,
    tunnel_superficie_m2    REAL,
    affichage_code          INTEGER,
    inspection_generale     TEXT,
    inspection_sommaire     TEXT,
    frequence_inspection_ans REAL,
    prochaine_inspection    INTEGER,
    commentaire             TEXT,
    travaux_description     TEXT,
    raw_json                TEXT
);

-- OData LimitesDeCharge : panneaux de limitation de poids -------------------------
CREATE TABLE IF NOT EXISTS limite_poids (
    num_dossr           TEXT PRIMARY KEY,
    panneau             TEXT,             -- « 28t* 48t**58t*** », « Charges légales », « Fermé »…
    poids_vehicule_t    REAL,             -- * véhicule routier
    poids_ensemble2_t   REAL,             -- ** ensemble de 2 unités (ou ensemble, panneau P-200-1)
    poids_ensemble3_t   REAL,             -- *** ensemble de plus de 2 unités
    diffusion_511       INTEGER,
    date_maj            TEXT
);

-- OData HauteurLibreDetail : mesures en 5 points par direction -------------------
CREATE TABLE IF NOT EXISTS hauteur_libre_detail (
    id              TEXT PRIMARY KEY,
    num_dossr       TEXT,
    point           TEXT,
    direction       TEXT,
    h_min_m         REAL,
    mesures_json    TEXT,                 -- {"Gauche": 4.8, "Centre": 4.9, …}
    remarques       TEXT,
    date_mesure     TEXT
);

-- Fiches détaillées APEX (crawl incrémental, une ligne par structure) -------------
CREATE TABLE IF NOT EXISTS fiche_detail (
    num_dossr               TEXT PRIMARY KEY,
    ide_strct               INTEGER,
    fetched_at              TEXT NOT NULL,
    status                  TEXT NOT NULL,     -- ok | erreur
    apex_sig                TEXT,              -- ICG|IAS|travaux|rapport au moment du crawl
    classe_route            TEXT,
    mrc                     TEXT,
    cep                     TEXT,
    obstacle_type_voie      TEXT,
    obstacle_classe_route   TEXT,
    longueur_totale_m       REAL,              -- ponts
    longueur_tablier_m      REAL,
    largeur_hors_tout_m     REAL,
    largeur_carrossable_m   REAL,
    superficie_tablier_m2   REAL,
    longueur_m              REAL,              -- ponceaux, murs
    ouverture_totale_m      REAL,
    epaisseur_remblai_m     REAL,
    hauteur_moyenne_m       REAL,
    largeur_totale_m        REAL,              -- tunnels
    superficie_m2           REAL,
    djma                    INTEGER,
    pct_camion              INTEGER,
    nb_voies                INTEGER,
    derniere_inspection     TEXT,              -- « Août 2024 »
    derniere_inspection_ym  TEXT,              -- « 2024-08 »
    prochaine_inspection    INTEGER,
    limitations             TEXT,              -- phrases de la section « Limitation »
    photo                   INTEGER,
    champs_json             TEXT,              -- toutes les paires (section, libellé) → valeur
    erreur                  TEXT
);

-- Ouvrages des villes (données ouvertes municipales, hors inventaire du MTMD) -------
CREATE TABLE IF NOT EXISTS ouvrage_ville (
    source              TEXT NOT NULL,    -- mtl | sherbrooke
    id                  TEXT NOT NULL,    -- n° de structure de la Ville (Montréal) ou identifiant (Sherbrooke)
    num                 TEXT,
    nom                 TEXT,
    type_code           INTEGER,          -- code de type du MTMD, quand le libellé concorde
    type_libelle        TEXT,
    famille             TEXT,
    route               TEXT,
    obstacle            TEXT,
    obstacle_classe     TEXT,
    annee_construction  INTEGER,
    icg_ville           REAL,             -- indice de la Ville (/100)
    cat_icg             TEXT,             -- catégorie 1..4
    inspection_generale TEXT,
    gestion             TEXT,
    lat                 REAL,
    lon                 REAL,
    num_dossr_mtmd      TEXT,             -- structure du MTMD à moins de 30 m
    doublon             INTEGER,          -- 1 = même ouvrage que num_dossr_mtmd
    raw_json            TEXT,
    PRIMARY KEY (source, id)
);

CREATE TABLE IF NOT EXISTS type_structure (
    code     INTEGER PRIMARY KEY,
    libelle  TEXT,
    famille  TEXT                          -- pont | ponceau | mur | tunnel | station
);

-- Table consolidée --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS structure (
    num_dossr               TEXT PRIMARY KEY,
    ide_strct               INTEGER,
    nom                     TEXT,
    type_code               INTEGER,
    famille                 TEXT,
    reseau                  TEXT,
    region                  TEXT,
    municipalite            TEXT,
    route                   TEXT,
    obstacle                TEXT,
    annee_construction      INTEGER,
    nb_voies                INTEGER,
    longueur_m              REAL,
    largeur_m               REAL,
    lat                     REAL,
    lon                     REAL,
    icg                     TEXT,
    ias                     TEXT,
    annee_travaux           INTEGER,
    rapport_dispo           INTEGER,
    lim_hauteur             INTEGER,
    lim_poids               INTEGER,
    limite_charge           TEXT,
    hauteur_libre_min_m     REAL,
    fiche_url               TEXT,
    in_wfs                  INTEGER,
    in_apex                 INTEGER
);

CREATE TABLE IF NOT EXISTS changement (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT NOT NULL,
    num_dossr   TEXT NOT NULL,
    kind        TEXT NOT NULL,            -- ajout | retrait | modif
    champ       TEXT,
    ancien      TEXT,
    nouveau     TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def fingerprint(rows: list[dict]) -> str:
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def replace_table(conn: sqlite3.Connection, table: str, rows: list[dict], *, commit: bool = True) -> None:
    """Remplace tout le contenu de `table` par `rows`, dans une transaction.
    `commit=False` : laisse la transaction ouverte (l'appelant valide le journal et le remplacement ensemble)."""
    if commit:
        with conn:
            _replace(conn, table, rows)
    else:
        _replace(conn, table, rows)


def _replace(conn, table: str, rows: list[dict]) -> None:
    conn.execute(f"DELETE FROM {table}")
    if not rows:
        return
    cols = list(rows[0])
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    conn.executemany(sql, ([r[c] for c in cols] for r in rows))


def record_run(conn, source: str, started_at: str, *, status: str,
               rows: int | None = None, sha256: str | None = None, note: str | None = None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO source_run (source, started_at, finished_at, status, rows, sha256, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source, started_at, now(), status, rows, sha256, note),
        )
