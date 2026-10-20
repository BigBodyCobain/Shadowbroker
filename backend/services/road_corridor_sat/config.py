"""Configuration for Sentinel-2 road corridor trend analysis."""
from __future__ import annotations

import os
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("ROAD_CORRIDOR_DATA_DIR", str(_BACKEND_ROOT / "data" / "road_corridors")))
CACHE_DIR = DATA_ROOT / "cache"
DETECTION_CROP_DIR = DATA_ROOT / "detection_crops"
STATE_PATH = DATA_ROOT / "_refresh_state.json"

DEFAULT_MONTHS = int(os.environ.get("ROAD_CORRIDOR_MONTHS", "2"))
DEFAULT_MAX_FRAMES = int(os.environ.get("ROAD_CORRIDOR_MAX_FRAMES", "6"))
SCHEDULED_PRESET_IDS = [
    s.strip()
    for s in os.environ.get("ROAD_CORRIDOR_SCHEDULED_PRESETS", "laredo_i35").split(",")
    if s.strip()
]


def road_corridor_sat_enabled() -> bool:
    return os.environ.get("ROAD_CORRIDOR_SAT_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def optional_deps_available() -> bool:
    try:
        import geopandas  # noqa: F401
        import osmnx  # noqa: F401
        import rasterio  # noqa: F401
        import sentinelhub  # noqa: F401
        import sklearn  # noqa: F401

        return True
    except ImportError:
        return False
