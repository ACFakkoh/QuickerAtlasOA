"""Rend le paquet `etl` importable quand pytest est lancé depuis n'importe où."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
