"""ASF Search catalog client (Mode A).

Pure metadata.  No downloads, no auth, no DSP.  Returns a list of
``SarScene`` objects so the fetcher can write them straight into
``latest_data["sar_scenes"]``.

ASF Search reference:
  https://docs.asf.alaska.edu/api/keywords/

The endpoint accepts ``intersectsWith`` (WKT), ``platform``, ``processingLevel``,
``beamMode``, and ``start``/``end`` ISO timestamps among many others.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from services.network_utils import fetch_with_curl
from services.sar.sar_aoi import SarAoi, wkt_for_aoi
from services.sar.sar_normalize import SarScene

logger = logging.getLogger(__name__)

ASF_SEARCH_URL = "https://api.daac.asf.alaska.edu/services/search/param"
DEFAULT_LOOKBACK_HOURS = 36
DEFAULT_MAX_RESULTS = 30


def _iso_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def search_scenes_for_aoi(
    aoi: SarAoi,
    *,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    max_results: int = DEFAULT_MAX_RESULTS,
    platform: str = "Sentinel-1",
    processing_level: str = "SLC",
    beam_mode: str = "IW",
) -> list[SarScene]:
    """Query ASF for scenes that intersected the AOI in the last N hours.

    Returns an empty list on any error — fetcher logs the failure.
    """
    end = datetime.utcnow()
    start = end - timedelta(hours=lookback_hours)
    params = {
        "platform": platform,
        "processingLevel": processing_level,
        "beamMode": beam_mode,
        "start": _iso_utc(start),
        "end": _iso_utc(end),
        "intersectsWith": wkt_for_aoi(aoi),
        "output": "JSON",
        "maxResults": str(max_results),
    }
    qs = "&".join(f"{k}={_url_encode(v)}" for k, v in params.items())
    url = f"{ASF_SEARCH_URL}?{qs}"
    try:
        resp = fetch_with_curl(url, timeout=20)
    except (ConnectionError, TimeoutError, OSError) as exc:
        logger.warning("ASF search failed for %s: %s", aoi.id, exc)
        return []
    if resp.status_code != 200:
        logger.debug("ASF search %s → HTTP %s", aoi.id, resp.status_code)
        return []
    try:
        body = resp.json()
    except (ValueError, KeyError) as exc:
        logger.debug("ASF search %s parse failed: %s", aoi.id, exc)
        return []
    # ASF returns a list of lists when output=JSON.  Flatten.
    flat: list[dict[str, Any]] = []
    if isinstance(body, list):
        for item in body:
            if isinstance(item, list):
                flat.extend(x for x in item if isinstance(x, dict))
            elif isinstance(item, dict):
                flat.append(item)
    elif isinstance(body, dict):
        results = body.get("results") or body.get("features") or []
        if isinstance(results, list):
            flat = [x for x in results if isinstance(x, dict)]
    return [_to_scene(item, aoi) for item in flat if _is_usable(item)]


def _is_usable(item: dict[str, Any]) -> bool:
    return bool(item.get("granuleName") or item.get("sceneName") or item.get("productID"))


def _to_scene(item: dict[str, Any], aoi: SarAoi) -> SarScene:
    scene_id = (
        item.get("granuleName")
        or item.get("sceneName")
        or item.get("productID")
        or ""
    )
    bbox = _extract_bbox(item)
    return SarScene(
        scene_id=str(scene_id),
        platform=str(item.get("platform", "Sentinel-1")),
        mode=str(item.get("beamModeType") or item.get("beamMode", "IW")),
        level=str(item.get("processingLevel", "SLC")),
        time=str(item.get("startTime") or item.get("sceneDate") or ""),
        aoi_id=aoi.id,
        relative_orbit=_safe_int(item.get("relativeOrbit") or item.get("pathNumber") or 0),
        flight_direction=str(item.get("flightDirection", "")).upper(),
        bbox=bbox,
        download_url=str(item.get("downloadUrl") or item.get("url") or ""),
        provider="ASF",
        raw_provider_id=str(item.get("productID") or scene_id),
    )


def _extract_bbox(item: dict[str, Any]) -> list[float]:
    """Best-effort bbox extraction from the ASF item."""
    for key in ("centerLat", "centerLon"):
        if key not in item:
            break
    try:
        center_lat = float(item.get("centerLat", 0))
        center_lon = float(item.get("centerLon", 0))
        if center_lat or center_lon:
            return [center_lon - 1, center_lat - 1, center_lon + 1, center_lat + 1]
    except (TypeError, ValueError):
        pass
    return [0.0, 0.0, 0.0, 0.0]


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _url_encode(value: str) -> str:
    """Tiny URL encoder — avoids importing urllib.parse for one call."""
    safe = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~()")
    out: list[str] = []
    for ch in str(value):
        if ch in safe:
            out.append(ch)
        elif ch == " ":
            out.append("%20")
        else:
            out.append("".join(f"%{b:02X}" for b in ch.encode("utf-8")))
    return "".join(out)


def estimate_next_pass(scenes: list[SarScene]) -> dict[str, Any]:
    """Cheap heuristic — given recent scenes, guess when the next pass might be.

    Sentinel-1 has a ~12-day repeat cycle, so the next pass over the same
    relative orbit is roughly 12 days after the last one.  This is a
    rough hint, not an authoritative orbit prediction.
    """
    if not scenes:
        return {"next_pass_estimate": None, "confidence": "none"}
    latest = max(scenes, key=lambda s: s.time)
    try:
        dt = datetime.strptime(latest.time[:19], "%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return {"next_pass_estimate": None, "confidence": "low"}
    next_pass = dt + timedelta(days=12)
    return {
        "next_pass_estimate": _iso_utc(next_pass),
        "confidence": "estimate",
        "based_on_scene": latest.scene_id,
        "repeat_cycle_days": 12,
    }
