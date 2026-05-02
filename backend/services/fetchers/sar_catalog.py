"""SAR catalog fetcher (Mode A — default-on, free, no account).

Hits ASF Search every hour for Sentinel-1 scenes that touched any of
the operator-defined AOIs in the last ~36h.  Pure metadata, no
downloads.

Result is written to ``latest_data["sar_scenes"]`` and a per-AOI
coverage summary to ``latest_data["sar_aoi_coverage"]``.
"""

from __future__ import annotations

import logging

from services.fetchers._store import _data_lock, _mark_fresh, is_any_active, latest_data
from services.fetchers.retry import with_retry
from services.sar.sar_aoi import load_aois
from services.sar.sar_catalog_client import estimate_next_pass, search_scenes_for_aoi
from services.sar.sar_config import catalog_enabled

logger = logging.getLogger(__name__)


@with_retry(max_retries=1, base_delay=2)
def fetch_sar_catalog() -> None:
    """Refresh the SAR scene catalog for all configured AOIs."""
    if not catalog_enabled():
        return
    if not is_any_active("sar"):
        return
    aois = load_aois()
    if not aois:
        logger.debug("SAR catalog: no AOIs configured")
        return

    all_scenes: list[dict] = []
    coverage: list[dict] = []
    for aoi in aois:
        try:
            scenes = search_scenes_for_aoi(aoi)
        except (ConnectionError, TimeoutError, OSError, ValueError) as exc:
            logger.debug("SAR catalog %s: %s", aoi.id, exc)
            scenes = []
        scene_dicts = [s.to_dict() for s in scenes]
        all_scenes.extend(scene_dicts)
        next_pass = estimate_next_pass(scenes)
        coverage.append(
            {
                "aoi_id": aoi.id,
                "aoi_name": aoi.name,
                "category": aoi.category,
                "center_lat": aoi.center_lat,
                "center_lon": aoi.center_lon,
                "radius_km": aoi.radius_km,
                "recent_scene_count": len(scene_dicts),
                "latest_scene_time": (
                    max((s["time"] for s in scene_dicts), default="")
                    if scene_dicts
                    else ""
                ),
                **next_pass,
            }
        )

    with _data_lock:
        latest_data["sar_scenes"] = all_scenes
        latest_data["sar_aoi_coverage"] = coverage
    if all_scenes or coverage:
        _mark_fresh("sar_scenes", "sar_aoi_coverage")
    logger.info(
        "SAR catalog: %d scenes across %d AOIs",
        len(all_scenes),
        len(aois),
    )
