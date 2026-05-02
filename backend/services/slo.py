"""Service-Level Objectives for data fetchers.

Declarative per-source freshness / volume expectations that the health
endpoint uses to compute red/yellow/green status and that fetchers use
as canary thresholds — the early-warning signal that an upstream source
structure has silently broken.

A human operator cannot reliably monitor 30+ layers for "is this still
flowing?". This registry is the automated check that does it for them.

Usage
-----

    from services.slo import SLO_REGISTRY, compute_all_statuses, assert_canary

    # In a fetcher, after pulling raw rows:
    assert_canary("uap_sightings", len(rows))

    # In the health endpoint:
    statuses = compute_all_statuses(latest_data, source_timestamps)
    # -> {"uap_sightings": {"status": "green", "age_s": 3200, ...}, ...}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR


@dataclass(frozen=True)
class SLO:
    """Declarative freshness + volume expectation for a data source."""

    # Maximum allowed age of the last successful fetch (seconds).
    max_age_s: int
    # Minimum row count expected in latest_data[source]. None = not checked.
    # Also used as the canary threshold for assert_canary().
    min_rows: Optional[int] = None
    # Human description shown in the health dashboard.
    description: str = ""


# Per-source registry. Add new sources here as they stabilise; a missing
# entry just means the source is not monitored (status="unconfigured").
#
# Thresholds are deliberately generous — goal is to catch "silent zero",
# not flap on normal variance. Tune downward once baseline is observed.
SLO_REGISTRY: Dict[str, SLO] = {
    # --- rolling daily snapshot feeds ---
    "uap_sightings": SLO(
        max_age_s=26 * _HOUR,
        min_rows=50,
        description="NUFORC rolling 60-day window (daily refresh)",
    ),
    "wastewater": SLO(
        max_age_s=30 * _HOUR,
        min_rows=1,
        description="WastewaterSCAN pathogen surveillance",
    ),
    "fimi": SLO(
        max_age_s=13 * _HOUR,
        description="Foreign information manipulation feed",
    ),
    # --- near-real-time feeds ---
    "commercial_flights": SLO(
        max_age_s=5 * _MINUTE,
        min_rows=50,
        description="ADS-B commercial traffic",
    ),
    "military_flights": SLO(
        max_age_s=10 * _MINUTE,
        min_rows=1,
        description="ADS-B military / mil-callsign traffic",
    ),
    "private_jets": SLO(
        max_age_s=5 * _MINUTE,
        description="ADS-B private aircraft",
    ),
    "ships": SLO(
        max_age_s=15 * _MINUTE,
        min_rows=50,
        description="AIS maritime traffic",
    ),
    # --- periodic geospatial feeds ---
    "earthquakes": SLO(
        max_age_s=1 * _HOUR,
        description="USGS M2.5+ earthquakes",
    ),
    "firms_fires": SLO(
        max_age_s=6 * _HOUR,
        description="NASA FIRMS active fire detections",
    ),
    "satellites": SLO(
        max_age_s=24 * _HOUR,
        min_rows=50,
        description="TLE / SGP4 satellite positions",
    ),
    "space_weather": SLO(
        max_age_s=2 * _HOUR,
        description="NOAA SWPC space weather",
    ),
    "weather_alerts": SLO(
        max_age_s=1 * _HOUR,
        description="NWS weather alerts",
    ),
    "volcanoes": SLO(
        max_age_s=12 * _HOUR,
        description="Smithsonian GVP volcanic activity",
    ),
    # --- news / OSINT feeds ---
    "news": SLO(
        max_age_s=2 * _HOUR,
        min_rows=1,
        description="Aggregated OSINT news items",
    ),
    "gdelt": SLO(
        max_age_s=2 * _HOUR,
        description="GDELT global events",
    ),
    "liveuamap": SLO(
        max_age_s=1 * _HOUR,
        description="LiveUAMap conflict markers",
    ),
    "prediction_markets": SLO(
        max_age_s=2 * _HOUR,
        description="Polymarket / Kalshi odds",
    ),
}


def _parse_iso(iso: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp as naive UTC. Returns None on failure."""
    if not iso:
        return None
    try:
        cleaned = iso.replace("Z", "").split("+", 1)[0]
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def compute_status(
    source: str,
    row_count: int,
    last_fresh_iso: Optional[str],
) -> Dict[str, Any]:
    """Compute the red/yellow/green status for one source.

    Returns a dict with keys: source, status, age_s, row_count, slo,
    stale, empty, description.

    Status codes:
        green         — within SLO on both age and volume
        yellow        — one SLO violated (stale OR empty, not both)
        red           — both SLOs violated OR never fetched
        unconfigured  — no SLO registered for this source
    """
    slo = SLO_REGISTRY.get(source)
    if slo is None:
        return {
            "source": source,
            "status": "unconfigured",
            "row_count": row_count,
        }

    last_fresh = _parse_iso(last_fresh_iso)
    now = datetime.utcnow()

    if last_fresh is None:
        return {
            "source": source,
            "status": "red",
            "age_s": None,
            "row_count": row_count,
            "slo": {"max_age_s": slo.max_age_s, "min_rows": slo.min_rows},
            "stale": True,
            "empty": (slo.min_rows is not None and row_count < slo.min_rows),
            "never_fetched": True,
            "description": slo.description,
        }

    age_s = max(0.0, (now - last_fresh).total_seconds())
    stale = age_s > slo.max_age_s
    empty = slo.min_rows is not None and row_count < slo.min_rows

    if stale and empty:
        status = "red"
    elif stale or empty:
        status = "yellow"
    else:
        status = "green"

    return {
        "source": source,
        "status": status,
        "age_s": round(age_s),
        "row_count": row_count,
        "slo": {"max_age_s": slo.max_age_s, "min_rows": slo.min_rows},
        "stale": stale,
        "empty": empty,
        "description": slo.description,
    }


def compute_all_statuses(
    latest_data: Dict[str, Any],
    source_timestamps: Dict[str, str],
) -> Dict[str, Dict[str, Any]]:
    """Compute status for every source in the SLO registry.

    `latest_data` is the shared dashboard store (or any dict-like with
    the same keys). `source_timestamps` is the per-source fresh-mark
    dict from services.fetchers._store.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for source in SLO_REGISTRY:
        value = latest_data.get(source)
        if hasattr(value, "__len__"):
            count = len(value)
        else:
            count = 0
        out[source] = compute_status(source, count, source_timestamps.get(source))
    return out


def summarise_statuses(statuses: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """Return a small tally of status counts for dashboards."""
    tally = {"green": 0, "yellow": 0, "red": 0, "unconfigured": 0}
    for entry in statuses.values():
        s = entry.get("status", "unconfigured")
        tally[s] = tally.get(s, 0) + 1
    return tally


def assert_canary(source: str, actual: int) -> bool:
    """Fetcher-side early-warning check.

    Call this inside a fetcher immediately after pulling raw rows from
    upstream. If `actual` is below the SLO's `min_rows`, logs a loud
    ERROR — that's the signal that an upstream source has structurally
    broken (plugin changed, nonce rotated, endpoint moved) and needs a
    human investigation *before* the empty result propagates and the
    stale cache keeps serving.

    Returns True if the canary is healthy, False if it tripped. Callers
    can use the return value to decide whether to continue.
    """
    slo = SLO_REGISTRY.get(source)
    if slo is None or slo.min_rows is None:
        return True
    if actual >= slo.min_rows:
        return True
    logger.error(
        "SLO CANARY TRIPPED: %s pulled %d rows, expected >= %d — "
        "upstream likely broken, check %s",
        source,
        actual,
        slo.min_rows,
        slo.description or "source definition",
    )
    return False
