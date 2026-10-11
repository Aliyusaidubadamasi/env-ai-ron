"""Central configuration and the Nature-Centred AI principles encoded as constants."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ENVAIRON_DATA_DIR", ROOT / "data"))
MODEL_DIR = ROOT / "models"
FRONTEND_DIR = ROOT.parent / "frontend"
STORE_DIR = DATA_DIR / "store"

# --- Region lock -----------------------------------------------------------
# The MVP is deliberately limited to one region so recommendations stay accurate.
REGION = {
    "name": "Lagos Mainland (demo tile)",
    "climate_zone": "Af/Am tropical rainforest-monsoon, coastal lowland",
    "ecoregion": "Nigerian lowland forest / coastal mosaic",
    # Roughly 2 km x 2 km around Yaba / Mushin / Surulere
    "bbox": (3.350, 6.490, 3.3685, 6.508),  # west, south, east, north
}

# --- Grid ------------------------------------------------------------------
IMG_SIZE = 800          # pixels per side of the synthetic demo tile
CELL_PX = 8             # one analysis cell = 8x8 pixels
# At 2.5 m/pixel this is a 20 m x 20 m planning cell.

# --- Nature-Centred principles --------------------------------------------
PRINCIPLES = ("Do no harm", "Be regenerative", "Be egalitarian")

# Objective presets. Weights always sum to 1.
PRESETS: dict[str, dict[str, float]] = {
    "balanced": {"cooling": 0.30, "carbon": 0.20, "pollinator": 0.20, "equity": 0.30},
    "cooling_first": {"cooling": 0.55, "carbon": 0.10, "pollinator": 0.10, "equity": 0.25},
    "carbon_first": {"cooling": 0.15, "carbon": 0.55, "pollinator": 0.10, "equity": 0.20},
    "pollinator_corridor": {"cooling": 0.10, "carbon": 0.10, "pollinator": 0.60, "equity": 0.20},
    "equity_first": {"cooling": 0.20, "carbon": 0.10, "pollinator": 0.10, "equity": 0.60},
}

# --- Simulation assumptions (all editable, all reported in the output) ----
SIM = {
    "horizons_years": (5, 10, 20),
    "establishment_survival": 0.80,      # fraction of planted trees alive and thriving
    "cooling_c_per_10pct_canopy": 0.35,  # air-temperature drop per +10 pp canopy averaged over a ~60 m window (assumption)
    "cooling_uncertainty": 0.40,         # +/- fraction applied for low/high range
    "max_local_cooling_c": 2.5,          # physical cap for neighbourhood air temperature
    "species_share_cap": 0.45,           # no species may exceed this share of any soil/site context
    "cooling_window_cells": 3,           # air temperature responds to canopy over ~60 m, not one 20 m cell
    "baseline_lst_c": 31.0,              # LST proxy for fully vegetated cell
    "imperv_lst_gain_c": 7.0,            # additional surface heat from 100% impervious cover
    "canopy_lst_drop_c": 4.0,            # surface cooling at 100% canopy
}

# --- Security / limits -----------------------------------------------------
MAX_UPLOAD_MB = int(os.environ.get("ENVAIRON_MAX_UPLOAD_MB", "60"))
MAX_IMAGE_PIXELS = 120_000_000
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ENVAIRON_CORS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
]
