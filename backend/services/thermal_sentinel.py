"""Thermal Sentinel — SWIR spectral anomaly detection via Sentinel-2 L2A.

Queries Microsoft Planetary Computer for Sentinel-2 scenes near a given
coordinate and checks SWIR bands (B11 @ 1610nm, B12 @ 2190nm) for thermal
anomalies that could indicate kinetic events (explosions, fires, strikes).

Thermal index: (B12 - B11) / (B12 + B11) — values > 0.1 suggest heat anomaly.

Falls back to metadata-only analysis (cloud cover, scene age) when rasterio
is not available, and cross-references with FIRMS fire data for corroboration.
"""

import logging
import requests
from datetime import datetime, timedelta
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Cache by rounded lat/lon (0.05° grid ~= 5km), TTL 30 min
_thermal_cache = TTLCache(maxsize=100, ttl=1800)


def search_thermal_anomaly(
    lat: float, lng: float, radius_km: float = 10, days_back: int = 5
) -> dict:
    """Search for thermal anomalies near a coordinate using Sentinel-2 SWIR bands.

    Args:
        lat, lng: Target coordinates
        radius_km: Search radius in km (default 10)
        days_back: How many days back to search (default 5)

    Returns:
        dict with: verified (bool), confidence (float 0-1), scenes_checked (int),
        thermal_index (float or None), latest_scene (str), firms_corroboration (bool)
    """
    cache_key = f"{round(lat, 2)}_{round(lng, 2)}_{radius_km}_{days_back}"
    if cache_key in _thermal_cache:
        return _thermal_cache[cache_key]

    result = {
        "verified": False,
        "confidence": 0.0,
        "scenes_checked": 0,
        "thermal_index": None,
        "latest_scene": None,
        "latest_scene_date": None,
        "cloud_cover": None,
        "firms_corroboration": False,
        "method": "metadata",  # or "swir_analysis" if rasterio available
    }

    try:
        # Step 1: STAC search for Sentinel-2 scenes
        scenes = _search_scenes(lat, lng, radius_km, days_back)
        result["scenes_checked"] = len(scenes)

        if not scenes:
            result["confidence"] = 0.0
            _thermal_cache[cache_key] = result
            return result

        best_scene = scenes[0]
        result["latest_scene"] = best_scene.get("id")
        result["latest_scene_date"] = best_scene.get("datetime")
        result["cloud_cover"] = best_scene.get("cloud_cover")

        # Step 2: Try SWIR band analysis if rasterio is available
        swir_result = _analyze_swir_bands(best_scene, lat, lng)
        if swir_result is not None:
            result["thermal_index"] = swir_result["thermal_index"]
            result["method"] = "swir_analysis"
            if swir_result["thermal_index"] > 0.1:
                result["verified"] = True
                result["confidence"] = min(0.9, swir_result["thermal_index"] * 3)
            elif swir_result["thermal_index"] > 0.05:
                result["confidence"] = 0.3
        else:
            # Fallback: metadata-only analysis
            # Recent scene + low cloud cover = higher confidence that we CAN verify
            scene_age_days = _scene_age_days(best_scene.get("datetime"))
            if scene_age_days is not None and scene_age_days <= 2:
                result["confidence"] = 0.2  # recent scene, but no SWIR analysis
            else:
                result["confidence"] = 0.1

        # Step 3: Cross-reference with FIRMS fire data
        firms_hit = _check_firms_corroboration(lat, lng, radius_km)
        if firms_hit:
            result["firms_corroboration"] = True
            result["confidence"] = min(1.0, result["confidence"] + 0.4)
            if not result["verified"]:
                result["verified"] = True  # FIRMS confirms thermal activity

        _thermal_cache[cache_key] = result
        return result

    except ImportError:
        logger.warning("pystac-client not installed — Thermal Sentinel unavailable")
        result["confidence"] = 0.0
        return result
    except Exception as e:
        logger.error(f"Thermal Sentinel error for ({lat}, {lng}): {e}")
        result["confidence"] = 0.0
        return result


def _search_scenes(lat: float, lng: float, radius_km: float, days_back: int) -> list[dict]:
    """Search Planetary Computer STAC for Sentinel-2 scenes."""
    from pystac_client import Client

    catalog = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
    end = datetime.utcnow()
    start = end - timedelta(days=days_back)

    # Convert radius_km to rough bbox
    dlat = radius_km / 111.0
    dlng = radius_km / (
        111.0
        * max(0.1, abs(lat) < 89 and __import__("math").cos(__import__("math").radians(lat)) or 0.1)
    )

    bbox = [lng - dlng, lat - dlat, lng + dlng, lat + dlat]

    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=f"{start.isoformat()}Z/{end.isoformat()}Z",
        sortby=[{"field": "datetime", "direction": "desc"}],
        max_items=5,
        query={"eo:cloud_cover": {"lt": 50}},
    )

    scenes = []
    for item in search.items():
        scenes.append(
            {
                "id": item.id,
                "datetime": item.datetime.isoformat() if item.datetime else None,
                "cloud_cover": item.properties.get("eo:cloud_cover"),
                "b11_href": item.assets.get("B11", {}).href if "B11" in item.assets else None,
                "b12_href": item.assets.get("B12", {}).href if "B12" in item.assets else None,
                "item": item,
            }
        )

    return scenes


def _analyze_swir_bands(scene: dict, lat: float, lng: float) -> dict | None:
    """Analyze SWIR bands B11 and B12 for thermal anomalies.

    Returns dict with thermal_index or None if rasterio unavailable.
    """
    try:
        import rasterio
        from rasterio.windows import from_bounds
    except ImportError:
        logger.debug("rasterio not installed — falling back to metadata analysis")
        return None

    b11_href = scene.get("b11_href")
    b12_href = scene.get("b12_href")
    if not b11_href or not b12_href:
        return None

    # Sign URLs for Azure blob access
    item = scene.get("item")
    if item:
        try:
            import planetary_computer

            item = planetary_computer.sign_item(item)
            b11_href = item.assets["B11"].href
            b12_href = item.assets["B12"].href
        except (ImportError, KeyError, Exception) as e:
            logger.debug(f"SWIR signing failed: {e}")
            return None

    try:
        # Read a small window around the target coordinate
        # Sentinel-2 SWIR bands are 20m resolution
        buffer_deg = 0.005  # ~500m window

        with rasterio.open(b11_href) as b11_ds:
            window = from_bounds(
                lng - buffer_deg,
                lat - buffer_deg,
                lng + buffer_deg,
                lat + buffer_deg,
                b11_ds.transform,
            )
            b11_data = b11_ds.read(1, window=window).astype(float)

        with rasterio.open(b12_href) as b12_ds:
            window = from_bounds(
                lng - buffer_deg,
                lat - buffer_deg,
                lng + buffer_deg,
                lat + buffer_deg,
                b12_ds.transform,
            )
            b12_data = b12_ds.read(1, window=window).astype(float)

        if b11_data.size == 0 or b12_data.size == 0:
            return None

        # Compute thermal index: (B12 - B11) / (B12 + B11)
        denom = b12_data + b11_data
        # Avoid division by zero
        valid = denom > 0
        if not valid.any():
            return None

        thermal_index = (b12_data[valid] - b11_data[valid]) / denom[valid]
        max_ti = float(thermal_index.max())

        return {"thermal_index": round(max_ti, 4)}

    except Exception as e:
        logger.warning(f"SWIR band read failed: {e}")
        return None


def _scene_age_days(dt_str: str | None) -> float | None:
    """Calculate age of a scene in days."""
    if not dt_str:
        return None
    try:
        scene_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        now = datetime.now(scene_dt.tzinfo) if scene_dt.tzinfo else datetime.utcnow()
        return (now - scene_dt).total_seconds() / 86400
    except (ValueError, TypeError):
        return None


def _check_firms_corroboration(lat: float, lng: float, radius_km: float) -> bool:
    """Check if FIRMS fire data corroborates thermal activity near the coordinate."""
    from services.fetchers._store import latest_data, _data_lock

    with _data_lock:
        fires = list(latest_data.get("firms_fires", []))
    if not fires:
        return False

    # Simple distance check (approximate, using equirectangular projection)
    import math

    threshold_deg = radius_km / 111.0

    for fire in fires:
        try:
            flat = fire.get("lat") or fire.get("latitude")
            flng = fire.get("lng") or fire.get("longitude")
            if flat is None or flng is None:
                continue
            dlat = abs(float(flat) - lat)
            dlng = abs(float(flng) - lng) * math.cos(math.radians(lat))
            if math.sqrt(dlat**2 + dlng**2) <= threshold_deg:
                return True
        except (ValueError, TypeError):
            continue

    return False
