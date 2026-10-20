"""Map-viewport helpers for on-demand corridor analysis."""
from __future__ import annotations

import hashlib


def bbox_around_point(lat: float, lon: float, *, half_span_deg: float = 0.04) -> list[float]:
    """Square AOI around a map center (~4–5 km half-span, under the 0.5° engine cap)."""
    span = min(max(half_span_deg, 0.02), 0.24)
    return [lat - span, lon - span, lat + span, lon + span]


def adhoc_preset_id(lat: float, lon: float) -> str:
    digest = hashlib.sha256(f"{lat:.4f},{lon:.4f}".encode()).hexdigest()[:12]
    return f"adhoc_{digest}"


def default_label_for_point(lat: float, lon: float) -> str:
    return f"Map center ({lat:.4f}, {lon:.4f})"
