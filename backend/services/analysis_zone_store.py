"""Analysis Zone store — OpenClaw-placed map overlays with analyst notes.

These render as the dashed-border squares on the correlations layer.
Unlike automated correlations (which are recomputed every cycle), analysis
zones persist until the agent or user deletes them, or their TTL expires.

Shape matches the correlation alert schema so the frontend renders them
identically — the ``source`` field marks them as agent-placed and enables
the delete button in the popup.
"""

import json
import logging
import os
import threading
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_zones: list[dict[str, Any]] = []
_lock = threading.Lock()

_PERSIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_PERSIST_FILE = os.path.join(_PERSIST_DIR, "analysis_zones.json")

ZONE_CATEGORIES = {
    "contradiction",   # narrative vs telemetry mismatch
    "analysis",        # general analyst note / assessment
    "warning",         # potential threat or risk area
    "observation",     # neutral observation worth marking
    "hypothesis",      # unverified theory to investigate
}

# Map categories to correlation type colors on the frontend
CATEGORY_COLORS = {
    "contradiction": "amber",
    "analysis": "cyan",
    "warning": "red",
    "observation": "blue",
    "hypothesis": "purple",
}


def _ensure_dir():
    try:
        os.makedirs(_PERSIST_DIR, exist_ok=True)
    except OSError:
        pass


def _save():
    """Persist to disk. Called under lock."""
    try:
        _ensure_dir()
        with open(_PERSIST_FILE, "w", encoding="utf-8") as f:
            json.dump(_zones, f, indent=2, default=str)
    except Exception as e:
        logger.warning("Failed to save analysis zones: %s", e)


def _load():
    """Load from disk on startup."""
    global _zones
    try:
        if os.path.exists(_PERSIST_FILE):
            with open(_PERSIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                _zones = data
                logger.info("Loaded %d analysis zones from disk", len(_zones))
    except Exception as e:
        logger.warning("Failed to load analysis zones: %s", e)


# Load on import
_load()


def _expire():
    """Remove zones past their TTL. Called under lock."""
    now = time.time()
    before = len(_zones)
    _zones[:] = [
        z for z in _zones
        if z.get("ttl_hours", 0) <= 0
        or (now - z.get("created_at", now)) < z["ttl_hours"] * 3600
    ]
    removed = before - len(_zones)
    if removed:
        logger.info("Expired %d analysis zones", removed)


def create_zone(
    *,
    lat: float,
    lng: float,
    title: str,
    body: str,
    category: str = "analysis",
    severity: str = "medium",
    cell_size_deg: float = 1.0,
    ttl_hours: float = 0,
    source: str = "openclaw",
    drivers: list[str] | None = None,
) -> dict[str, Any]:
    """Create an analysis zone. Returns the created zone dict."""
    category = category if category in ZONE_CATEGORIES else "analysis"
    if severity not in ("high", "medium", "low"):
        severity = "medium"
    cell_size_deg = max(0.1, min(cell_size_deg, 10.0))

    zone: dict[str, Any] = {
        "id": str(uuid.uuid4())[:12],
        "lat": lat,
        "lng": lng,
        "type": "analysis_zone",
        "category": category,
        "severity": severity,
        "score": {"high": 90, "medium": 60, "low": 30}.get(severity, 60),
        "title": title[:200],
        "body": body[:2000],
        "drivers": (drivers or [title])[:5],
        "cell_size": cell_size_deg,
        "source": source,
        "created_at": time.time(),
        "ttl_hours": ttl_hours,
    }

    with _lock:
        _expire()
        _zones.append(zone)
        _save()

    logger.info("Analysis zone created: %s at (%.2f, %.2f)", title[:40], lat, lng)
    return zone


def list_zones() -> list[dict[str, Any]]:
    """Return all live (non-expired) zones."""
    with _lock:
        _expire()
        return list(_zones)


def get_zone(zone_id: str) -> dict[str, Any] | None:
    """Get a single zone by ID."""
    with _lock:
        for z in _zones:
            if z["id"] == zone_id:
                return dict(z)
    return None


def delete_zone(zone_id: str) -> bool:
    """Delete a zone by ID. Returns True if found and removed."""
    with _lock:
        before = len(_zones)
        _zones[:] = [z for z in _zones if z["id"] != zone_id]
        if len(_zones) < before:
            _save()
            return True
    return False


def clear_zones(*, source: str | None = None) -> int:
    """Clear all zones, optionally filtered by source. Returns count removed."""
    with _lock:
        before = len(_zones)
        if source:
            _zones[:] = [z for z in _zones if z.get("source") != source]
        else:
            _zones.clear()
        removed = before - len(_zones)
        if removed:
            _save()
        return removed


def get_live_zones() -> list[dict[str, Any]]:
    """Return zones formatted for the correlation engine merge.

    This is called by compute_correlations() to inject agent-placed zones
    into the correlations list that the frontend renders as map squares.
    """
    with _lock:
        _expire()
        return [dict(z) for z in _zones]
