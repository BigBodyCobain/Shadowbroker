"""SAR pre-processed product fetcher (Mode B — opt-in, free, account needed).

Pulls already-computed deformation, flood, water, and damage products
from NASA OPERA, Copernicus EGMS, GFM, EMS, and UNOSAT.  No local DSP.

Two-step opt-in: ``MESH_SAR_PRODUCTS_FETCH=allow`` AND
``MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE=true``.  When either flag is
unset, this fetcher logs a single startup hint and returns.
"""

from __future__ import annotations

import logging
from typing import Any

from services.fetchers._store import _data_lock, _mark_fresh, is_any_active, latest_data
from services.fetchers.retry import with_retry
from services.sar.sar_aoi import load_aois
from services.sar.sar_config import products_fetch_enabled, products_fetch_status
from services.sar.sar_normalize import SarAnomaly
from services.sar.sar_products_client import (
    fetch_egms_for_aoi,
    fetch_ems_for_aoi,
    fetch_gfm_for_aoi,
    fetch_opera_for_aoi,
    fetch_unosat_for_aoi,
)
from services.sar.sar_signing import emit_signed_anomaly

logger = logging.getLogger(__name__)
_LOGGED_DISABLED_HINT = False


def _hint_disabled_once() -> None:
    global _LOGGED_DISABLED_HINT
    if _LOGGED_DISABLED_HINT:
        return
    _LOGGED_DISABLED_HINT = True
    status = products_fetch_status()
    missing = ", ".join(status.get("missing", [])) or "nothing"
    logger.info(
        "SAR Mode B (ground-change alerts) is disabled. Missing: %s. "
        "Enable in Settings → SAR or set the env vars listed in .env.example. "
        "Free signup: https://urs.earthdata.nasa.gov/users/new",
        missing,
    )


@with_retry(max_retries=1, base_delay=3)
def fetch_sar_products() -> None:
    """Refresh pre-processed SAR anomalies for all configured AOIs."""
    if not products_fetch_enabled():
        _hint_disabled_once()
        return
    if not is_any_active("sar"):
        return
    aois = load_aois()
    if not aois:
        logger.debug("SAR products: no AOIs configured")
        return

    seen_ids: set[str] = set()
    all_anomalies: list[dict[str, Any]] = []
    publish_summary = {"signed": 0, "skipped": 0, "reasons": {}}

    for aoi in aois:
        for fetcher in (
            fetch_opera_for_aoi,
            fetch_egms_for_aoi,
            fetch_gfm_for_aoi,
            fetch_ems_for_aoi,
            fetch_unosat_for_aoi,
        ):
            try:
                anomalies: list[SarAnomaly] = fetcher(aoi) or []
            except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
                logger.debug("SAR %s for %s failed: %s", fetcher.__name__, aoi.id, exc)
                anomalies = []
            for a in anomalies:
                if a.anomaly_id in seen_ids:
                    continue
                seen_ids.add(a.anomaly_id)
                all_anomalies.append(a.to_dict())
                status = emit_signed_anomaly(a)
                if status.get("signed"):
                    publish_summary["signed"] += 1
                else:
                    publish_summary["skipped"] += 1
                    reason = status.get("reason", "unknown")
                    publish_summary["reasons"][reason] = (
                        publish_summary["reasons"].get(reason, 0) + 1
                    )

    with _data_lock:
        latest_data["sar_anomalies"] = all_anomalies
    if all_anomalies:
        _mark_fresh("sar_anomalies")
    logger.info(
        "SAR products: %d anomalies (%d signed, %d skipped)",
        len(all_anomalies),
        publish_summary["signed"],
        publish_summary["skipped"],
    )
