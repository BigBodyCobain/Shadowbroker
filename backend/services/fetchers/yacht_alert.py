"""Yacht-Alert DB — load and enrich AIS vessels with tracked yacht metadata."""

import os
import json
import logging

logger = logging.getLogger("services.data_fetcher")

# Category -> color mapping
_CATEGORY_COLOR: dict[str, str] = {
    "Tech Billionaire": "#FF69B4",
    "Celebrity / Mogul": "#FF69B4",
    "Oligarch Watch": "#FF2020",
}


def _category_to_color(cat: str) -> str:
    """Map category to display color. Defaults to hot pink."""
    return _CATEGORY_COLOR.get(cat, "#FF69B4")


_YACHT_ALERT_DB: dict = {}


def _load_yacht_alert_db():
    """Load yacht_alert_db.json into memory at import time."""
    global _YACHT_ALERT_DB
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
        "yacht_alert_db.json",
    )
    if not os.path.exists(json_path):
        logger.warning(f"Yacht-Alert DB not found at {json_path}")
        return
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        for mmsi_str, info in raw.items():
            info["color"] = _category_to_color(info.get("category", ""))
            _YACHT_ALERT_DB[mmsi_str] = info
        logger.info(f"Yacht-Alert DB loaded: {len(_YACHT_ALERT_DB)} vessels")
    except (IOError, OSError, json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error(f"Failed to load Yacht-Alert DB: {e}")


_load_yacht_alert_db()


def enrich_with_yacht_alert(ship: dict) -> dict:
    """If ship's MMSI is in the Yacht-Alert DB, attach owner/alert metadata."""
    mmsi = str(ship.get("mmsi", "")).strip()
    if mmsi and mmsi in _YACHT_ALERT_DB:
        info = _YACHT_ALERT_DB[mmsi]
        ship["yacht_alert"] = True
        ship["yacht_owner"] = info["owner"]
        ship["yacht_name"] = info["name"]
        ship["yacht_category"] = info["category"]
        ship["yacht_color"] = info["color"]
        ship["yacht_builder"] = info.get("builder", "")
        ship["yacht_length"] = info.get("length_m", 0)
        ship["yacht_year"] = info.get("year", 0)
        ship["yacht_link"] = info.get("link", "")
    return ship
