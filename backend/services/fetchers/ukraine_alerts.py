"""Ukraine air raid alerts via alerts.in.ua API.

Polls active alerts every 2 minutes, matches to oblast boundary polygons,
and produces GeoJSON-style records for map rendering.

Requires ALERTS_IN_UA_TOKEN env var (free registration at alerts.in.ua).
Gracefully skips if token is not set.
"""

import json
import logging
import os
from pathlib import Path

from services.network_utils import fetch_with_curl
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.fetchers.retry import with_retry

logger = logging.getLogger(__name__)

# ─── Alert type → color mapping ──────────────────────────────────────────────
ALERT_COLORS = {
    "air_raid": "#ef4444",            # red
    "artillery_shelling": "#f97316",  # orange
    "urban_fights": "#eab308",        # yellow
    "chemical": "#a855f7",            # purple
    "nuclear": "#dc2626",             # dark red
}

# ─── Load oblast boundary polygons (once) ────────────────────────────────────
_oblast_geojson = None


def _load_oblasts():
    global _oblast_geojson
    if _oblast_geojson is not None:
        return _oblast_geojson

    data_path = Path(__file__).resolve().parent.parent.parent / "data" / "ukraine_oblasts.geojson"
    if not data_path.exists():
        logger.error(f"Ukraine oblasts GeoJSON not found at {data_path}")
        _oblast_geojson = {}
        return _oblast_geojson

    with open(data_path, "r", encoding="utf-8") as f:
        _oblast_geojson = json.load(f)

    logger.info(f"Loaded {len(_oblast_geojson.get('features', []))} Ukraine oblast boundaries")
    return _oblast_geojson


def _find_oblast_geometry(location_title: str):
    """Find the polygon geometry for an oblast by matching Ukrainian name."""
    oblasts = _load_oblasts()
    features = oblasts.get("features", [])
    for feat in features:
        props = feat.get("properties", {})
        name = props.get("name", "")
        # Exact match on Ukrainian name (e.g. "Луганська область")
        if name == location_title:
            return feat.get("geometry"), props.get("name_en", "")
    # Fuzzy: try partial match (alert may say "Київська область" but GeoJSON says "Київ")
    for feat in features:
        props = feat.get("properties", {})
        name = props.get("name", "")
        if location_title in name or name in location_title:
            return feat.get("geometry"), props.get("name_en", "")
    return None, ""


# ─── Fetcher ─────────────────────────────────────────────────────────────────

@with_retry(max_retries=1, base_delay=2)
def fetch_ukraine_air_raid_alerts():
    """Fetch active Ukraine air raid alerts from alerts.in.ua."""
    from services.fetchers._store import is_any_active

    if not is_any_active("ukraine_alerts"):
        return

    token = os.environ.get("ALERTS_IN_UA_TOKEN", "")
    if not token:
        logger.debug("ALERTS_IN_UA_TOKEN not set, skipping Ukraine air raid alerts")
        return

    alerts_out = []
    try:
        url = f"https://api.alerts.in.ua/v1/alerts/active.json?token={token}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        response = fetch_with_curl(url, timeout=10, headers=headers)

        if response.status_code == 200:
            data = response.json()
            raw_alerts = data.get("alerts", [])

            for alert in raw_alerts:
                loc_type = alert.get("location_type", "")
                # Only render oblast-level alerts (not raion/city/hromada)
                if loc_type != "oblast":
                    continue

                location_title = alert.get("location_title", "")
                alert_type = alert.get("alert_type", "air_raid")
                geometry, name_en = _find_oblast_geometry(location_title)

                if not geometry:
                    logger.debug(f"No geometry for oblast: {location_title}")
                    continue

                alerts_out.append({
                    "id": alert.get("id", 0),
                    "alert_type": alert_type,
                    "location_title": location_title,
                    "location_uid": alert.get("location_uid", ""),
                    "name_en": name_en,
                    "started_at": alert.get("started_at", ""),
                    "color": ALERT_COLORS.get(alert_type, "#ef4444"),
                    "geometry": geometry,
                })

            logger.info(f"Ukraine alerts: {len(alerts_out)} active oblast-level alerts "
                        f"(from {len(raw_alerts)} total)")
        elif response.status_code == 401:
            logger.warning("alerts.in.ua returned 401 — check ALERTS_IN_UA_TOKEN")
        elif response.status_code == 429:
            logger.warning("alerts.in.ua rate-limited (429)")
        else:
            logger.warning(f"alerts.in.ua returned HTTP {response.status_code}")

    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching Ukraine alerts: {e}")

    with _data_lock:
        latest_data["ukraine_alerts"] = alerts_out
    if alerts_out:
        _mark_fresh("ukraine_alerts")
