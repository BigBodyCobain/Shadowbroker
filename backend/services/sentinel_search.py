"""
Sentinel-2 satellite imagery search via Microsoft Planetary Computer STAC API.
Free, keyless search for metadata + thumbnails. Used in the right-click dossier.

We use the raw STAC HTTP API with explicit timeouts so the right-click dossier
cannot hang behind a slow client library call.
"""

import logging
import requests
from datetime import datetime, timedelta
from cachetools import TTLCache

from services.network_utils import outbound_user_agent

logger = logging.getLogger(__name__)

# Cache by rounded lat/lon (0.02° grid ~= 2km), TTL 1 hour
_sentinel_cache = TTLCache(maxsize=200, ttl=3600)


def _planetary_user_agent() -> str:
    # Round 7a: per-install handle so Microsoft Planetary Computer can
    # attribute requests to the specific operator rather than treating
    # the whole Shadowbroker user base as one entity.
    return outbound_user_agent("sentinel2-planetary-computer")


def _sign_planetary_href(href: str) -> str:
    """Sign a Planetary Computer blob URL with a short-lived SAS token."""
    if not href or "blob.core.windows.net" not in href:
        return href
    try:
        account = href.split(".blob.core.windows.net")[0].split("//")[-1]
        token_resp = requests.get(
            f"https://planetarycomputer.microsoft.com/api/sas/v1/token/{account}",
            timeout=5,
            headers={"User-Agent": _planetary_user_agent()},
        )
        token_resp.raise_for_status()
        token = token_resp.json().get("token", "")
        if not token:
            return href
        sep = "&" if "?" in href else "?"
        return f"{href}{sep}{token}"
    except (requests.RequestException, ValueError, KeyError):
        return href


def _scene_from_stac_feature(item: dict) -> dict:
    assets = item.get("assets", {}) or {}
    rendered = assets.get("rendered_preview") or {}
    thumbnail = assets.get("thumbnail") or {}
    props = item.get("properties", {}) or {}
    thumb_href = _sign_planetary_href(thumbnail.get("href") or rendered.get("href") or "")
    full_href = _sign_planetary_href(rendered.get("href") or thumbnail.get("href") or "")
    return {
        "found": True,
        "scene_id": item.get("id"),
        "datetime": props.get("datetime"),
        "cloud_cover": props.get("eo:cloud_cover"),
        "thumbnail_url": thumb_href or None,
        "fullres_url": full_href or None,
        "bbox": list(item.get("bbox", [])) if item.get("bbox") else None,
        "platform": props.get("platform", "Sentinel-2"),
    }


def _esri_imagery_fallback(lat: float, lng: float) -> dict:
    lat_span = 0.18
    lng_span = 0.24
    bbox = f"{lng - lng_span},{lat - lat_span},{lng + lng_span},{lat + lat_span}"
    fullres = (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/"
        f"export?bbox={bbox}&bboxSR=4326&imageSR=4326&size=1600,900&format=png32&f=image"
    )
    thumbnail = (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/"
        f"export?bbox={bbox}&bboxSR=4326&imageSR=4326&size=640,360&format=png32&f=image"
    )
    return {
        "found": True,
        "scene_id": None,
        "datetime": None,
        "cloud_cover": None,
        "thumbnail_url": thumbnail,
        "fullres_url": fullres,
        "bbox": [lng - lng_span, lat - lat_span, lng + lng_span, lat + lat_span],
        "platform": "Esri World Imagery",
        "fallback": True,
        "message": "Planetary Computer unavailable; using Esri World Imagery fallback",
    }


def search_sentinel2_scene(lat: float, lng: float) -> dict:
    """Search for up to 3 recent Sentinel-2 L2A scenes covering a point."""
    cache_key = f"{round(lat, 2)}_{round(lng, 2)}"
    if cache_key in _sentinel_cache:
        return _sentinel_cache[cache_key]

    try:
        end = datetime.utcnow()
        start = end - timedelta(days=60)
        search_payload = {
            "collections": ["sentinel-2-l2a"],
            "intersects": {"type": "Point", "coordinates": [lng, lat]},
            "datetime": f"{start.isoformat()}Z/{end.isoformat()}Z",
            "sortby": [{"field": "datetime", "direction": "desc"}],
            "limit": 3,
            "query": {"eo:cloud_cover": {"lt": 30}},
        }
        search_res = requests.post(
            "https://planetarycomputer.microsoft.com/api/stac/v1/search",
            json=search_payload,
            timeout=8,
            headers={"User-Agent": _planetary_user_agent()},
        )
        search_res.raise_for_status()
        data = search_res.json()
        features = data.get("features", [])
        if not features:
            result = _esri_imagery_fallback(lat, lng)
            _sentinel_cache[cache_key] = result
            return result

        scenes = [_scene_from_stac_feature(item) for item in features[:3]]
        result = {**scenes[0], "scenes": scenes}
        _sentinel_cache[cache_key] = result
        return result

    except (requests.RequestException, ConnectionError, TimeoutError, ValueError) as e:
        logger.error(f"Sentinel-2 search failed for ({lat}, {lng}): {e}")
        result = _esri_imagery_fallback(lat, lng)
        result["error"] = str(e)
        _sentinel_cache[cache_key] = result
        return result
