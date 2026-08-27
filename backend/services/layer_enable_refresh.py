"""Immediate data refresh when the operator enables a map layer.

Disk/local fetches run inline (milliseconds). Network-heavy fetches run on the
slow executor so POST /api/layers never blocks the single uvicorn worker for
tens of seconds (which freezes bootstrap + live-data and makes the map go black).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Inline — tiny local/static loads (ms).
_INSTANT_LAYER_KEYS: frozenset[str] = frozenset(
    {"power_plants", "datacenters"}
)
# Background — network-bound OR large local scans (full CCTV SELECT can stall
# the single uvicorn worker if run inline on enable).
_SLOW_LAYER_KEYS: frozenset[str] = frozenset(
    {
        "cctv",
        "firms",
        "psk_reporter",
        "fishing_activity",
        "uap_sightings",
        "malware_c2",
        "cyber_threats",
        "scm_suppliers",
        "telegram_osint",
        "gt_risk",
    }
)


def snapshot_active_layers() -> dict[str, bool]:
    from services.fetchers._store import active_layers

    return dict(active_layers)


def _was_off_now_on(before: dict[str, bool], key: str) -> bool:
    from services.fetchers._store import active_layers

    return not bool(before.get(key, False)) and bool(active_layers.get(key, False))


def _instant_fetch(key: str) -> None:
    if key == "power_plants":
        from services.fetchers.infrastructure import fetch_power_plants

        fetch_power_plants()
        logger.info("Power plants loaded (layer enabled)")
        return
    if key == "datacenters":
        from services.fetchers.infrastructure import fetch_datacenters

        fetch_datacenters()
        logger.info("Datacenters loaded (layer enabled)")
        return
    raise KeyError(key)


def _slow_fetch(key: str) -> None:
    if key == "cctv":
        from services.cctv_pipeline import get_camera_count, run_all_ingestors
        from services.fetchers.infrastructure import fetch_cctv

        # A fresh checkout can have an empty SQLite catalog even though the
        # public camera feeds are available. Seed it the first time CCTV is
        # enabled; otherwise the layer stays ON with zero map records until a
        # later scheduler cycle happens to run.
        if get_camera_count() == 0:
            run_all_ingestors()
        fetch_cctv()
        logger.info("CCTV loaded (layer enabled)")
        return
    if key == "firms":
        from services.fetchers.earth_observation import (
            fetch_firms_country_fires,
            fetch_firms_fires,
        )

        fetch_firms_fires()
        fetch_firms_country_fires()
        logger.info("FIRMS fires loaded (layer enabled)")
        return
    if key == "psk_reporter":
        from services.fetchers.infrastructure import fetch_psk_reporter

        fetch_psk_reporter()
        logger.info("PSK Reporter loaded (layer enabled)")
        return
    if key == "fishing_activity":
        from services.fetchers.geo import fetch_fishing_activity

        fetch_fishing_activity()
        logger.info("Fishing activity loaded (layer enabled)")
        return
    if key == "uap_sightings":
        from services.fetchers.earth_observation import fetch_uap_sightings

        fetch_uap_sightings()
        logger.info("UAP sightings loaded (layer enabled)")
        return
    if key == "malware_c2":
        from services.fetchers.malware import fetch_malware_threats

        fetch_malware_threats()
        logger.info("Malware C2 loaded (layer enabled)")
        return
    if key == "cyber_threats":
        from services.fetchers.cyber_status import fetch_cyber_threats

        fetch_cyber_threats()
        logger.info("Cyber threats loaded (layer enabled)")
        return
    if key == "scm_suppliers":
        from services.scm.suppliers import fetch_scm_suppliers

        fetch_scm_suppliers()
        logger.info("SCM suppliers loaded (layer enabled)")
        return
    if key == "telegram_osint":
        from services.fetchers.telegram_osint import fetch_telegram_osint

        fetch_telegram_osint()
        logger.info("Telegram OSINT loaded (layer enabled)")
        return
    if key == "gt_risk":
        from analytics.integration import maybe_refresh_gt_analytics

        maybe_refresh_gt_analytics()
        logger.info("Strategic Risk Analytics refreshed (layer enabled)")
        return
    raise KeyError(key)


def _run_slow_enable_fetches(keys: tuple[str, ...]) -> None:
    from services.fetchers._store import bump_data_version

    for key in keys:
        try:
            _slow_fetch(key)
        except Exception:
            logger.exception("Layer enable fetch failed for %s", key)
    bump_data_version()


def refresh_newly_enabled_layers(before: dict[str, bool]) -> None:
    """Fetch any layers that transitioned off → on."""
    from services.fetchers._store import bump_data_version

    instant_keys: list[str] = []
    slow_keys: list[str] = []

    for key in _INSTANT_LAYER_KEYS | _SLOW_LAYER_KEYS:
        if _was_off_now_on(before, key):
            if key in _INSTANT_LAYER_KEYS:
                instant_keys.append(key)
            else:
                slow_keys.append(key)

    if not instant_keys and not slow_keys:
        return

    for key in instant_keys:
        try:
            _instant_fetch(key)
        except Exception:
            logger.exception("Layer enable fetch failed for %s", key)

    if instant_keys:
        bump_data_version()

    if slow_keys:
        from services.data_fetcher import _SLOW_EXECUTOR

        _SLOW_EXECUTOR.submit(_run_slow_enable_fetches, tuple(slow_keys))
