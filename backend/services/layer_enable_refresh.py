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
    {"cctv", "firms", "psk_reporter", "fishing_activity"}
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
        from services.fetchers.infrastructure import fetch_cctv

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
