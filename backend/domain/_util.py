"""Small shared helpers for the domain layer (IDs, time, coordinate safety)."""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Optional


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string with a trailing ``Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    """A short, prefixed, collision-resistant identifier (e.g. ``inv_ab12cd34ef56``)."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def canonical_id(prefix: str, *parts: object) -> str:
    """A deterministic id derived from ``parts`` — used for entity de-duplication.

    The same (type, key) always maps to the same entity id, so repeated
    observations of one aircraft attach to a single Entity rather than forking.
    """
    basis = "|".join(str(p).strip().lower() for p in parts if p is not None and str(p).strip())
    if not basis:
        return new_id(prefix)
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def coerce_iso(value: object) -> Optional[str]:
    """Best-effort normalisation of a timestamp to ISO-8601, or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = str(value).strip()
    if not s:
        return None
    if _ISO_RE.match(s):
        return s
    # numeric epoch (seconds or milliseconds)
    try:
        num = float(s)
        if num > 1e12:  # milliseconds
            num /= 1000.0
        return datetime.fromtimestamp(num, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return s  # keep as-is; caller may still find it useful


def valid_coord(lat: object, lng: object) -> Optional[tuple[float, float]]:
    """Return ``(lat, lng)`` as floats iff both are finite and in range, else ``None``.

    This is the single chokepoint that stops NaN / out-of-range coordinates
    (a real bug on the agent pin path) from reaching the store or the map.
    """
    try:
        la = float(lat)
        lo = float(lng)
    except (TypeError, ValueError):
        return None
    if math.isnan(la) or math.isnan(lo) or math.isinf(la) or math.isinf(lo):
        return None
    if not (-90.0 <= la <= 90.0) or not (-180.0 <= lo <= 180.0):
        return None
    return (la, lo)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))
