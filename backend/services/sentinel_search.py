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

logger = logging.getLogger(__name__)

# Cache by rounded lat/lon (0.02° grid ~= 2km), TTL 1 hour
_sentinel_cache = TTLCache(maxsize=200, ttl=3600)


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
    """Search for the latest Sentinel-2 L2A scene covering a point."""
    cache_key = f"{round(lat, 2)}_{round(lng, 2)}"
    if cache_key in _sentinel_cache:
        return _sentinel_cache[cache_key]

    try:
        end = datetime.utcnow()
        start = end - timedelta(days=30)
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
            headers={"User-Agent": "ShadowBroker-OSINT/1.0 (live-risk-dashboard)"},
        )
        search_res.raise_for_status()
        data = search_res.json()
        features = data.get("features", [])
        if not features:
            result = _esri_imagery_fallback(lat, lng)
            _sentinel_cache[cache_key] = result
            return result

        item = features[0]
        assets = item.get("assets", {}) or {}
        rendered = assets.get("rendered_preview") or {}
        thumbnail = assets.get("thumbnail") or {}

        # Full-res image URL — what opens when user clicks
        fullres_url = rendered.get("href") or thumbnail.get("href")
        # Thumbnail URL — what shows in the popup card
        thumb_url = thumbnail.get("href") or rendered.get("href")

        result = {
            "found": True,
            "scene_id": item.get("id"),
            "datetime": item.get("properties", {}).get("datetime"),
            "cloud_cover": item.get("properties", {}).get("eo:cloud_cover"),
            "thumbnail_url": thumb_url,
            "fullres_url": fullres_url,
            "bbox": list(item.get("bbox", [])) if item.get("bbox") else None,
            "platform": item.get("properties", {}).get("platform", "Sentinel-2"),
        }
        _sentinel_cache[cache_key] = result
        return result

    except (requests.RequestException, ConnectionError, TimeoutError, ValueError) as e:
        logger.error(f"Sentinel-2 search failed for ({lat}, {lng}): {e}")
        result = _esri_imagery_fallback(lat, lng)
        result["error"] = str(e)
        _sentinel_cache[cache_key] = result
        return result
