"""Scheduled Sentinel-2 road corridor freight trend fetcher (opt-in, slow tier)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from services.fetchers._store import _data_lock, _mark_fresh, is_any_active, latest_data

logger = logging.getLogger(__name__)

_REFRESH_HOURS = float(os.environ.get("ROAD_CORRIDOR_REFRESH_HOURS", "24"))


def _hours_since(iso_ts: str) -> float | None:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except ValueError:
        return None


def _feature_ready() -> bool:
    from services.road_corridor_sat.config import optional_deps_available, road_corridor_sat_enabled
    from services.road_corridor_sat.credentials import sentinel_credentials_configured

    if not road_corridor_sat_enabled():
        return False
    if not optional_deps_available():
        logger.debug("road_corridor_trends skipped — optional deps not installed")
        return False
    if not sentinel_credentials_configured():
        logger.debug("road_corridor_trends skipped — Sentinel credentials missing")
        return False
    return True


def refresh_road_corridor_store() -> None:
    from services.road_corridor_sat.storage import build_trends_payload

    payload = build_trends_payload()
    with _data_lock:
        latest_data["road_corridor_trends"] = payload
    _mark_fresh("road_corridor_trends")


def fetch_road_corridor_trends(force: bool = False) -> None:
    """Refresh scheduled corridor presets (default: laredo_i35 every 24h)."""
    if not is_any_active("road_corridor_trends"):
        return
    if not _feature_ready():
        return

    from services.road_corridor_sat.config import SCHEDULED_PRESET_IDS
    from services.road_corridor_sat.pipeline import analyze_preset
    from services.road_corridor_sat.presets import get_preset
    from services.road_corridor_sat.storage import load_refresh_state

    state = load_refresh_state()
    for preset_id in SCHEDULED_PRESET_IDS:
        preset = get_preset(preset_id)
        if preset is None:
            logger.warning("Unknown scheduled road corridor preset: %s", preset_id)
            continue
        last = state.get(preset_id)
        if last and not force:
            age_h = _hours_since(last)
            if age_h is not None and age_h < _REFRESH_HOURS:
                logger.info(
                    "road_corridor %s fresh (%.1fh < %.1fh) — skipping",
                    preset_id,
                    age_h,
                    _REFRESH_HOURS,
                )
                continue
        try:
            logger.info("road_corridor analysis starting for %s", preset_id)
            analyze_preset(preset_id)
        except Exception as exc:
            logger.exception("road_corridor analysis failed for %s: %s", preset_id, exc)

    refresh_road_corridor_store()
