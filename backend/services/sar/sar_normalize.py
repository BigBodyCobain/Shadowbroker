"""Unified SAR scene + anomaly schema.

Every provider response (ASF, OPERA, EGMS, GFM, EMS, UNOSAT) lands in
one of these two shapes before it touches anything else in the system.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

# All anomaly kinds the SAR layer can emit.  Frontend and OpenClaw skill
# must use exactly these strings.
ANOMALY_KINDS = (
    "ground_deformation",       # mm or mm/yr — InSAR / EGMS / OPERA-DISP
    "surface_water_change",     # OPERA DSWx — water mask delta
    "vegetation_disturbance",   # OPERA DIST-ALERT — canopy loss
    "flood_extent",             # GFM Sentinel-1 flood polygons
    "damage_assessment",        # Copernicus EMS / UNOSAT damage maps
    "coherence_change",         # CCD — something physically changed
    "scene_pass",               # Mode A only — informational, not an anomaly
)


@dataclass
class SarScene:
    """A single SAR acquisition (Mode A — catalog only).

    No pixels — this is just metadata that says "Sentinel-1 flew over
    this AOI at this time, here is the download URL if you ever want it".
    """

    scene_id: str
    platform: str
    mode: str           # IW / EW / SM / WV
    level: str          # SLC / GRD / RAW
    time: str           # ISO-8601 UTC
    aoi_id: str
    relative_orbit: int
    flight_direction: str  # ASCENDING / DESCENDING
    bbox: list[float]      # [min_lon, min_lat, max_lon, max_lat]
    download_url: str
    provider: str          # ASF / Copernicus / Earthdata
    raw_provider_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SarAnomaly:
    """A pre-processed SAR finding (Mode B).

    Confidence is 0..1.  ``magnitude`` + ``magnitude_unit`` interpretation
    depends on ``kind`` — see ANOMALY_KINDS for the canonical list.
    """

    anomaly_id: str
    kind: str
    lat: float
    lon: float
    magnitude: float
    magnitude_unit: str
    confidence: float
    first_seen: int        # epoch seconds
    last_seen: int         # epoch seconds
    aoi_id: str
    scene_count: int
    solver: str            # OPERA-DISP, EGMS, GFM, EMS, UNOSAT, ...
    source_constellation: str  # Sentinel-1, ALOS, ...
    provenance_url: str
    category: str          # infrastructure / conflict / geohazard / watchlist
    title: str
    summary: str
    evidence_hash: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_pin_dict(self) -> dict[str, Any]:
        """Convert to the AI Intel pin shape used by ai_pin_store."""
        return {
            "lat": self.lat,
            "lng": self.lon,
            "label": self.title or f"SAR {self.kind}",
            "category": _kind_to_pin_category(self.kind, self.category),
            "description": (
                f"{self.summary}\n\n"
                f"Solver: {self.solver}\n"
                f"Constellation: {self.source_constellation}\n"
                f"Magnitude: {self.magnitude} {self.magnitude_unit}\n"
                f"Confidence: {self.confidence:.2f}\n"
                f"Scenes: {self.scene_count}\n"
                f"Evidence: {self.evidence_hash[:16] or 'n/a'}"
            ),
            "source": f"SAR · {self.solver}",
            "source_url": self.provenance_url,
            "confidence": self.confidence,
        }


def _kind_to_pin_category(kind: str, default: str) -> str:
    """Map SAR anomaly kind to ShadowBroker pin category color."""
    return {
        "ground_deformation": "infrastructure",
        "surface_water_change": "weather",
        "vegetation_disturbance": "research",
        "flood_extent": "weather",
        "damage_assessment": "threat",
        "coherence_change": "anomaly",
    }.get(kind, "satellite")


def canonical_anomaly_json(payload: dict[str, Any]) -> str:
    """Stable JSON encoding for evidence_hash + signature payloads."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def evidence_hash_for_payload(payload: dict[str, Any]) -> str:
    """SHA-256 hex digest used to bind anomaly events to their source data.

    Mirrors the gate_envelope ``envelope_hash`` pattern from the audit:
    the raw provider response is hashed and the digest is bound into the
    signed event so downstream consumers can re-verify the lineage.
    """
    return hashlib.sha256(canonical_anomaly_json(payload).encode("utf-8")).hexdigest()


def make_anomaly_id(solver: str, raw_id: str, lat: float, lon: float) -> str:
    """Stable, dedup-friendly anomaly id."""
    base = f"{solver}|{raw_id}|{round(lat, 4)}|{round(lon, 4)}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
    return f"sar_{solver.lower().replace('-', '_')}_{digest}"


def now_epoch() -> int:
    return int(time.time())
