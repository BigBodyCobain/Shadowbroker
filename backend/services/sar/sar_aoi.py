"""SAR area-of-interest (AOI) definitions.

AOIs are operator-defined regions that the SAR layer watches.  They live
in ``backend/data/sar_aois.json`` and are loaded once at module init.

The seed file ships with five obvious watch points so a fresh install
has something to do without any configuration.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
AOI_FILE = DATA_DIR / "sar_aois.json"


@dataclass(frozen=True)
class SarAoi:
    """A region the SAR layer watches.

    Either ``polygon`` (list of [lon, lat] pairs) or ``center`` + ``radius_km``
    must be set.  ``polygon`` takes precedence.
    """

    id: str
    name: str
    description: str
    center_lat: float
    center_lon: float
    radius_km: float
    polygon: list[list[float]] | None = None
    category: str = "watchlist"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "center": [self.center_lat, self.center_lon],
            "radius_km": self.radius_km,
            "polygon": self.polygon,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SarAoi":
        polygon = raw.get("polygon")
        if isinstance(polygon, list) and polygon:
            lats = [pt[1] for pt in polygon if isinstance(pt, (list, tuple)) and len(pt) >= 2]
            lons = [pt[0] for pt in polygon if isinstance(pt, (list, tuple)) and len(pt) >= 2]
            center_lat = sum(lats) / len(lats) if lats else 0.0
            center_lon = sum(lons) / len(lons) if lons else 0.0
            radius_km = float(raw.get("radius_km") or 25.0)
        else:
            polygon = None
            center = raw.get("center") or [0.0, 0.0]
            center_lat = float(center[0]) if len(center) > 0 else 0.0
            center_lon = float(center[1]) if len(center) > 1 else 0.0
            radius_km = float(raw.get("radius_km") or 25.0)
        return cls(
            id=str(raw.get("id", "")).strip().lower(),
            name=str(raw.get("name", "")).strip() or str(raw.get("id", "")),
            description=str(raw.get("description", "")).strip(),
            center_lat=center_lat,
            center_lon=center_lon,
            radius_km=radius_km,
            polygon=polygon,
            category=str(raw.get("category", "watchlist")).strip().lower() or "watchlist",
        )


def bbox_for_aoi(aoi: SarAoi) -> tuple[float, float, float, float]:
    """Return (min_lon, min_lat, max_lon, max_lat) for an AOI.

    Uses the polygon if set, otherwise approximates a square around the
    center using the radius (1 deg lat ≈ 111 km).
    """
    if aoi.polygon:
        lons = [pt[0] for pt in aoi.polygon]
        lats = [pt[1] for pt in aoi.polygon]
        return (min(lons), min(lats), max(lons), max(lats))
    deg_lat = aoi.radius_km / 111.0
    cos_lat = max(0.05, math.cos(math.radians(aoi.center_lat)))
    deg_lon = aoi.radius_km / (111.0 * cos_lat)
    return (
        aoi.center_lon - deg_lon,
        aoi.center_lat - deg_lat,
        aoi.center_lon + deg_lon,
        aoi.center_lat + deg_lat,
    )


def wkt_for_aoi(aoi: SarAoi) -> str:
    """Build a POLYGON WKT string for ASF Search ``intersectsWith``."""
    min_lon, min_lat, max_lon, max_lat = bbox_for_aoi(aoi)
    return (
        f"POLYGON(({min_lon} {min_lat},"
        f"{max_lon} {min_lat},"
        f"{max_lon} {max_lat},"
        f"{min_lon} {max_lat},"
        f"{min_lon} {min_lat}))"
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def point_in_aoi(lat: float, lon: float, aoi: SarAoi) -> bool:
    """Cheap point-in-AOI check using haversine to center."""
    return haversine_km(lat, lon, aoi.center_lat, aoi.center_lon) <= aoi.radius_km


_aoi_cache: list[SarAoi] | None = None


def load_aois(force: bool = False) -> list[SarAoi]:
    """Load AOIs from disk.  Cached after first call."""
    global _aoi_cache
    if _aoi_cache is not None and not force:
        return _aoi_cache
    if not AOI_FILE.exists():
        logger.warning("SAR AOI file missing: %s", AOI_FILE)
        _aoi_cache = []
        return _aoi_cache
    try:
        raw = json.loads(AOI_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.error("Failed to load SAR AOIs: %s", exc)
        _aoi_cache = []
        return _aoi_cache
    items = raw.get("aois") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        _aoi_cache = []
        return _aoi_cache
    parsed: list[SarAoi] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        try:
            parsed.append(SarAoi.from_dict(entry))
        except (TypeError, ValueError) as exc:
            logger.debug("Skipping malformed AOI %r: %s", entry, exc)
    _aoi_cache = parsed
    return _aoi_cache


def save_aois(aois: list[SarAoi]) -> None:
    """Persist AOIs to disk and refresh the cache."""
    global _aoi_cache
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"aois": [aoi.to_dict() for aoi in aois]}
    AOI_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _aoi_cache = list(aois)


def add_aoi(aoi: SarAoi) -> None:
    """Add or replace an AOI by id."""
    current = list(load_aois())
    current = [a for a in current if a.id != aoi.id]
    current.append(aoi)
    save_aois(current)


def remove_aoi(aoi_id: str) -> bool:
    """Remove an AOI by id.  Returns True if anything was removed."""
    current = list(load_aois())
    aoi_id = (aoi_id or "").strip().lower()
    new = [a for a in current if a.id != aoi_id]
    if len(new) == len(current):
        return False
    save_aois(new)
    return True
