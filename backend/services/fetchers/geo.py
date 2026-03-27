"""Ship and geopolitics fetchers — AIS vessels, carriers, frontlines, GDELT, LiveUAmap, fishing."""

import csv
import io
import math
import os
import logging
from services.network_utils import fetch_with_curl
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.fetchers.retry import with_retry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ships (AIS + Carriers)
# ---------------------------------------------------------------------------
@with_retry(max_retries=1, base_delay=1)
def fetch_ships():
    """Fetch real-time AIS vessel data and combine with OSINT carrier positions."""
    from services.fetchers._store import is_any_active

    if not is_any_active(
        "ships_military", "ships_cargo", "ships_civilian", "ships_passenger", "ships_tracked_yachts"
    ):
        return
    from services.ais_stream import get_ais_vessels
    from services.carrier_tracker import get_carrier_positions

    ships = []
    try:
        carriers = get_carrier_positions()
        ships.extend(carriers)
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Carrier tracker error (non-fatal): {e}")
        carriers = []

    try:
        ais_vessels = get_ais_vessels()
        ships.extend(ais_vessels)
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"AIS stream error (non-fatal): {e}")
        ais_vessels = []

    # Enrich ships with yacht alert data (tracked superyachts)
    from services.fetchers.yacht_alert import enrich_with_yacht_alert

    for ship in ships:
        enrich_with_yacht_alert(ship)

    # Enrich ships with PLAN/CCG vessel data
    from services.fetchers.plan_vessel_alert import enrich_with_plan_vessel
    for ship in ships:
        enrich_with_plan_vessel(ship)

    logger.info(f"Ships: {len(carriers)} carriers + {len(ais_vessels)} AIS vessels")
    with _data_lock:
        latest_data["ships"] = ships
    _mark_fresh("ships")


# ---------------------------------------------------------------------------
# Airports (ourairports.com)
# ---------------------------------------------------------------------------
cached_airports = []


def find_nearest_airport(lat, lng, max_distance_nm=200):
    """Find the nearest large airport to a given lat/lng using haversine distance."""
    if not cached_airports:
        return None

    best = None
    best_dist = float("inf")
    lat_r = math.radians(lat)
    lng_r = math.radians(lng)

    for apt in cached_airports:
        apt_lat_r = math.radians(apt["lat"])
        apt_lng_r = math.radians(apt["lng"])
        dlat = apt_lat_r - lat_r
        dlng = apt_lng_r - lng_r
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat_r) * math.cos(apt_lat_r) * math.sin(dlng / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        dist_nm = 3440.065 * c

        if dist_nm < best_dist:
            best_dist = dist_nm
            best = apt

    if best and best_dist <= max_distance_nm:
        return {
            "iata": best["iata"],
            "name": best["name"],
            "lat": best["lat"],
            "lng": best["lng"],
            "distance_nm": round(best_dist, 1),
        }
    return None


def fetch_airports():
    global cached_airports
    if not cached_airports:
        logger.info("Downloading global airports database from ourairports.com...")
        try:
            url = "https://ourairports.com/data/airports.csv"
            response = fetch_with_curl(url, timeout=15)
            if response.status_code == 200:
                f = io.StringIO(response.text)
                reader = csv.DictReader(f)
                for row in reader:
                    if row["type"] == "large_airport" and row["iata_code"]:
                        cached_airports.append(
                            {
                                "id": row["ident"],
                                "name": row["name"],
                                "iata": row["iata_code"],
                                "lat": float(row["latitude_deg"]),
                                "lng": float(row["longitude_deg"]),
                                "type": "airport",
                            }
                        )
                logger.info(f"Loaded {len(cached_airports)} large airports into cache.")
        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
            logger.error(f"Error fetching airports: {e}")

    with _data_lock:
        latest_data["airports"] = cached_airports


# ---------------------------------------------------------------------------
# Geopolitics & LiveUAMap
# ---------------------------------------------------------------------------
@with_retry(max_retries=1, base_delay=2)
def fetch_frontlines():
    """Fetch Ukraine frontline data (fast — single GitHub API call)."""
    from services.fetchers._store import is_any_active

    if not is_any_active("ukraine_frontline"):
        return
    try:
        from services.geopolitics import fetch_ukraine_frontlines

        frontlines = fetch_ukraine_frontlines()
        if frontlines:
            with _data_lock:
                latest_data["frontlines"] = frontlines
            _mark_fresh("frontlines")
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching frontlines: {e}")


@with_retry(max_retries=1, base_delay=3)
def fetch_gdelt():
    """Fetch GDELT global military incidents (slow — downloads 32 ZIP files)."""
    from services.fetchers._store import is_any_active

    if not is_any_active("global_incidents"):
        return
    try:
        from services.geopolitics import fetch_global_military_incidents

        gdelt = fetch_global_military_incidents()
        if gdelt is not None:
            with _data_lock:
                latest_data["gdelt"] = gdelt
            _mark_fresh("gdelt")
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching GDELT: {e}")


def fetch_geopolitics():
    """Legacy wrapper — runs both sequentially. Used by recurring scheduler."""
    fetch_frontlines()
    fetch_gdelt()


def update_liveuamap():
    from services.fetchers._store import is_any_active

    if not is_any_active("global_incidents"):
        return
    logger.info("Running scheduled Liveuamap scraper...")
    try:
        from services.liveuamap_scraper import fetch_liveuamap

        res = fetch_liveuamap()
        if res:
            with _data_lock:
                latest_data["liveuamap"] = res
            _mark_fresh("liveuamap")
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Liveuamap scraper error: {e}")


# ---------------------------------------------------------------------------
# Fishing Activity (Global Fishing Watch)
# ---------------------------------------------------------------------------
@with_retry(max_retries=1, base_delay=5)
def fetch_fishing_activity():
    """Fetch recent fishing events from Global Fishing Watch (~5 day lag)."""
    from services.fetchers._store import is_any_active

    if not is_any_active("fishing_activity"):
        return
    token = os.environ.get("GFW_API_TOKEN", "")
    if not token:
        logger.debug("GFW_API_TOKEN not set, skipping fishing activity fetch")
        return
    events = []
    try:
        url = (
            "https://gateway.api.globalfishingwatch.org/v3/events"
            "?datasets[0]=public-global-fishing-events:latest"
            "&limit=500&sort=start&sort-direction=DESC"
        )
        headers = {"Authorization": f"Bearer {token}"}
        response = fetch_with_curl(url, timeout=30, headers=headers)
        if response.status_code == 200:
            entries = response.json().get("entries", [])
            for e in entries:
                pos = e.get("position", {})
                lat = pos.get("lat")
                lng = pos.get("lon")
                if lat is None or lng is None:
                    continue
                dur = e.get("event", {}).get("duration", 0) or 0
                events.append(
                    {
                        "id": e.get("id", ""),
                        "type": e.get("type", "fishing"),
                        "lat": lat,
                        "lng": lng,
                        "start": e.get("start", ""),
                        "end": e.get("end", ""),
                        "vessel_name": (e.get("vessel") or {}).get("name", "Unknown"),
                        "vessel_flag": (e.get("vessel") or {}).get("flag", ""),
                        "duration_hrs": round(dur / 3600, 1),
                    }
                )
        logger.info(f"Fishing activity: {len(events)} events")
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching fishing activity: {e}")
    with _data_lock:
        latest_data["fishing_activity"] = events
    if events:
        _mark_fresh("fishing_activity")
