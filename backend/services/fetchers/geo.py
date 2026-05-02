"""Ship and geopolitics fetchers — AIS vessels, carriers, frontlines, GDELT, LiveUAmap, fishing."""

import csv
import concurrent.futures
import io
import math
import os
import logging
import time
from urllib.parse import urlencode
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

    with concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="ship_fetch") as executor:
        carrier_future = executor.submit(get_carrier_positions)
        ais_future = executor.submit(get_ais_vessels)

        try:
            carriers = carrier_future.result()
        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
            logger.error(f"Carrier tracker error (non-fatal): {e}")
            carriers = []

        try:
            ais_vessels = ais_future.result()
        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
            logger.error(f"AIS stream error (non-fatal): {e}")
            ais_vessels = []

    ships = list(carriers or [])
    ships.extend(ais_vessels or [])

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
def _fishing_vessel_key(event: dict) -> str:
    vessel_ssvid = str(event.get("vessel_ssvid", "") or "").strip()
    if vessel_ssvid:
        return f"ssvid:{vessel_ssvid}"
    vessel_id = str(event.get("vessel_id", "") or "").strip()
    if vessel_id:
        return f"vid:{vessel_id}"
    vessel_name = str(event.get("vessel_name", "") or "").strip().upper()
    vessel_flag = str(event.get("vessel_flag", "") or "").strip().upper()
    if vessel_name:
        return f"name:{vessel_name}|flag:{vessel_flag}"
    return f"event:{event.get('id', '')}"


def _fishing_event_rank(event: dict) -> tuple[str, str, float, str]:
    return (
        str(event.get("end", "") or ""),
        str(event.get("start", "") or ""),
        float(event.get("duration_hrs", 0) or 0),
        str(event.get("id", "") or ""),
    )


def _dedupe_fishing_events(events: list[dict]) -> list[dict]:
    latest_by_vessel: dict[str, dict] = {}
    counts_by_vessel: dict[str, int] = {}

    for event in events:
        vessel_key = _fishing_vessel_key(event)
        counts_by_vessel[vessel_key] = counts_by_vessel.get(vessel_key, 0) + 1
        current = latest_by_vessel.get(vessel_key)
        if current is None or _fishing_event_rank(event) > _fishing_event_rank(current):
            latest_by_vessel[vessel_key] = event

    deduped: list[dict] = []
    for vessel_key, event in latest_by_vessel.items():
        event_copy = dict(event)
        event_copy["event_count"] = counts_by_vessel.get(vessel_key, 1)
        deduped.append(event_copy)

    deduped.sort(key=_fishing_event_rank, reverse=True)
    return deduped


_FISHING_FETCH_INTERVAL_S = 3600  # once per hour — GFW data has ~5 day lag
_last_fishing_fetch_ts: float = 0.0


@with_retry(max_retries=1, base_delay=5)
def fetch_fishing_activity():
    """Fetch recent fishing events from Global Fishing Watch (~5 day lag)."""
    global _last_fishing_fetch_ts
    from services.fetchers._store import is_any_active, latest_data

    if not is_any_active("fishing_activity"):
        return

    # Skip if we already have data and fetched less than an hour ago
    now = time.time()
    if latest_data.get("fishing_activity") and (now - _last_fishing_fetch_ts) < _FISHING_FETCH_INTERVAL_S:
        return

    token = os.environ.get("GFW_API_TOKEN", "")
    if not token:
        logger.debug("GFW_API_TOKEN not set, skipping fishing activity fetch")
        return
    events = []
    try:
        import datetime as _dt

        _end = _dt.date.today().isoformat()
        _start = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
        page_size = max(1, int(os.environ.get("GFW_EVENTS_PAGE_SIZE", "500") or "500"))
        offset = 0
        seen_offsets: set[int] = set()
        seen_ids: set[str] = set()
        headers = {"Authorization": f"Bearer {token}"}

        while True:
            if offset in seen_offsets:
                logger.warning("Fishing activity pagination repeated offset=%s; stopping fetch", offset)
                break
            seen_offsets.add(offset)

            query = urlencode(
                {
                    "datasets[0]": "public-global-fishing-events:latest",
                    "start-date": _start,
                    "end-date": _end,
                    "limit": page_size,
                    "offset": offset,
                }
            )
            url = f"https://gateway.api.globalfishingwatch.org/v3/events?{query}"
            response = fetch_with_curl(url, timeout=30, headers=headers)
            if response.status_code != 200:
                logger.warning(
                    "Fishing activity fetch failed at offset=%s: HTTP %s",
                    offset,
                    response.status_code,
                )
                break

            payload = response.json() or {}
            entries = payload.get("entries", [])
            if not entries:
                break

            added_this_page = 0
            for e in entries:
                pos = e.get("position", {})
                vessel = e.get("vessel") or {}
                lat = pos.get("lat")
                lng = pos.get("lon")
                if lat is None or lng is None:
                    continue
                event_id = str(e.get("id", "") or "")
                if event_id and event_id in seen_ids:
                    continue
                if event_id:
                    seen_ids.add(event_id)
                dur = e.get("event", {}).get("duration", 0) or 0
                events.append(
                    {
                        "id": event_id,
                        "type": e.get("type", "fishing"),
                        "lat": lat,
                        "lng": lng,
                        "start": e.get("start", ""),
                        "end": e.get("end", ""),
                        "vessel_id": str(vessel.get("id", "") or ""),
                        "vessel_ssvid": str(vessel.get("ssvid", "") or ""),
                        "vessel_name": vessel.get("name", "Unknown"),
                        "vessel_flag": vessel.get("flag", ""),
                        "duration_hrs": round(dur / 3600, 1),
                    }
                )
                added_this_page += 1

            if len(entries) < page_size:
                break

            next_offset = payload.get("nextOffset")
            if next_offset is None:
                next_offset = (payload.get("pagination") or {}).get("nextOffset")
            if next_offset is None:
                next_offset = offset + page_size
            try:
                next_offset = int(next_offset)
            except (TypeError, ValueError):
                next_offset = offset + page_size
            if next_offset <= offset:
                logger.warning(
                    "Fishing activity pagination produced non-increasing next offset=%s; stopping fetch",
                    next_offset,
                )
                break
            if added_this_page == 0:
                logger.warning(
                    "Fishing activity page at offset=%s added no new events; stopping fetch",
                    offset,
                )
                break
            offset = next_offset
        raw_event_count = len(events)
        events = _dedupe_fishing_events(events)
        logger.info("Fishing activity: %s raw events -> %s deduped vessels", raw_event_count, len(events))
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching fishing activity: {e}")
    with _data_lock:
        latest_data["fishing_activity"] = events
    if events:
        _mark_fresh("fishing_activity")
        _last_fishing_fetch_ts = time.time()
