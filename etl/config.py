"""Chemins et URLs des sources."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"          # copies brutes des téléchargements (non versionnées)
DB_PATH = DATA_DIR / "ponts.sqlite"
DOC_REF = ROOT / "Doc_ref"

USER_AGENT = (
    "VisualisationPontsQC/0.1 (projet personnel non commercial; "
    "contact: cheruelanthony@gmail.com)"
)
MIN_INTERVAL_S = 1.0                # délai minimal entre deux requêtes vers un même hôte

# --- Sources -----------------------------------------------------------------
WFS_BASE = "https://ws.mapserver.transports.gouv.qc.ca/swtq"
WFS_TYPENAME = "ms:gsq_v_desc_strct_tri"
WFS_CSV_URL = (
    f"{WFS_BASE}?service=wfs&version=2.0.0&request=getfeature"
    f"&typename={WFS_TYPENAME}&outputformat=csv"
)

APEX_BASE = "https://www.diffusion.transports.gouv.qc.ca/ords/pes/"
APEX_ENTRY = APEX_BASE + "f?p=DIFF:DSI::::::"   # page d'accueil (ouvre la session APEX)
APEX_PAGE_SIZE = 500

HAUTEURS_URL = (
    "https://www.transports.gouv.qc.ca/fr/entreprises-partenaires/ent-camionnage/"
    "hauteurs-libres/Pages/DHLDetails.aspx"
)
