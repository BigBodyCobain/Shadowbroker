"""Infrastructure fetchers — internet outages (IODA), data centers, CCTV, KiwiSDR."""

import json
import time
import heapq
import logging
from pathlib import Path
from cachetools import TTLCache
from services.network_utils import fetch_with_curl
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.fetchers.retry import with_retry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internet Outages (IODA — Georgia Tech)
# ---------------------------------------------------------------------------
_region_geocode_cache: TTLCache = TTLCache(maxsize=2000, ttl=86400)


def _geocode_region(region_name: str, country_name: str) -> tuple:
    """Geocode a region using OpenStreetMap Nominatim (cached, respects rate limit)."""
    cache_key = f"{region_name}|{country_name}"
    if cache_key in _region_geocode_cache:
        return _region_geocode_cache[cache_key]
    try:
        import urllib.parse

        query = urllib.parse.quote(f"{region_name}, {country_name}")
        url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1"
        response = fetch_with_curl(url, timeout=8, headers={"User-Agent": "ShadowBroker-OSINT/1.0"})
        if response.status_code == 200:
            results = response.json()
            if results:
                lat = float(results[0]["lat"])
                lon = float(results[0]["lon"])
                _region_geocode_cache[cache_key] = (lat, lon)
                return (lat, lon)
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError):
        pass
    _region_geocode_cache[cache_key] = None
    return None


@with_retry(max_retries=1, base_delay=1)
def fetch_internet_outages():
    """Fetch regional internet outage alerts from IODA (Georgia Tech)."""
    from services.fetchers._store import is_any_active

    if not is_any_active("internet_outages"):
        return
    RELIABLE_DATASOURCES = {"bgp", "ping-slash24"}
    outages = []
    try:
        now = int(time.time())
        start = now - 86400
        url = f"https://api.ioda.inetintel.cc.gatech.edu/v2/outages/alerts?from={start}&until={now}&limit=500"
        response = fetch_with_curl(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            alerts = data.get("data", [])
            region_outages = {}
            for alert in alerts:
                entity = alert.get("entity", {})
                etype = entity.get("type", "")
                level = alert.get("level", "")
                if level == "normal" or etype != "region":
                    continue
                datasource = alert.get("datasource", "")
                if datasource not in RELIABLE_DATASOURCES:
                    continue
                code = entity.get("code", "")
                name = entity.get("name", "")
                attrs = entity.get("attrs", {})
                country_code = attrs.get("country_code", "")
                country_name = attrs.get("country_name", "")
                value = alert.get("value", 0)
                history_value = alert.get("historyValue", 0)
                severity = 0
                if history_value and history_value > 0:
                    severity = round((1 - value / history_value) * 100)
                severity = max(0, min(severity, 100))
                if severity < 10:
                    continue
                if code not in region_outages or severity > region_outages[code]["severity"]:
                    region_outages[code] = {
                        "region_code": code,
                        "region_name": name,
                        "country_code": country_code,
                        "country_name": country_name,
                        "level": level,
                        "datasource": datasource,
                        "severity": severity,
                    }
            geocoded = []
            for rcode, r in region_outages.items():
                coords = _geocode_region(r["region_name"], r["country_name"])
                if coords:
                    r["lat"] = coords[0]
                    r["lng"] = coords[1]
                    geocoded.append(r)
            outages = heapq.nlargest(100, geocoded, key=lambda x: x["severity"])
        logger.info(f"Internet outages: {len(outages)} regions affected")
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as e:
        logger.error(f"Error fetching internet outages: {e}")
    with _data_lock:
        latest_data["internet_outages"] = outages
    if outages:
        _mark_fresh("internet_outages")


# ---------------------------------------------------------------------------
# RIPE Atlas — complement IODA with probe-level disconnection data
# ---------------------------------------------------------------------------

@with_retry(max_retries=1, base_delay=3)
def fetch_ripe_atlas_probes():
    """Fetch disconnected RIPE Atlas probes and merge into internet_outages (complementing IODA)."""
    from services.fetchers._store import is_any_active

    if not is_any_active("internet_outages"):
        return
    try:
        # 1. Fetch disconnected probes (status=2) — ~2,000 probes, no auth needed
        url_disc = "https://atlas.ripe.net/api/v2/probes/?status=2&page_size=500&format=json"
        resp_disc = fetch_with_curl(url_disc, timeout=20)
        if resp_disc.status_code != 200:
            logger.warning(f"RIPE Atlas probes API returned {resp_disc.status_code}")
            return
        disc_data = resp_disc.json()
        disconnected = disc_data.get("results", [])

        # 2. Fetch connected probe count (page_size=1 — we only need the count)
        url_conn = "https://atlas.ripe.net/api/v2/probes/?status=1&page_size=1&format=json"
        resp_conn = fetch_with_curl(url_conn, timeout=10)
        total_connected = 0
        if resp_conn.status_code == 200:
            total_connected = resp_conn.json().get("count", 0)

        # 3. Group disconnected probes by country
        country_disc: dict = {}
        for p in disconnected:
            cc = p.get("country_code", "")
            if not cc:
                continue
            if cc not in country_disc:
                country_disc[cc] = []
            country_disc[cc].append(p)

        # 4. Get IODA-covered countries to avoid double-reporting
        with _data_lock:
            ioda_outages = list(latest_data.get("internet_outages", []))
        ioda_countries = {
            o.get("country_code", "").upper()
            for o in ioda_outages
            if o.get("datasource") != "ripe-atlas"
        }

        # 5. Build RIPE-only alerts for countries NOT already in IODA
        ripe_alerts = []
        for cc, probes in country_disc.items():
            if cc.upper() in ioda_countries:
                continue  # IODA already covers this country
            if len(probes) < 3:
                continue  # Too few probes to be meaningful

            # Use centroid of disconnected probes as marker location
            lats = [
                p["geometry"]["coordinates"][1]
                for p in probes
                if p.get("geometry") and p["geometry"].get("coordinates")
            ]
            lngs = [
                p["geometry"]["coordinates"][0]
                for p in probes
                if p.get("geometry") and p["geometry"].get("coordinates")
            ]
            if not lats:
                continue

            disc_count = len(probes)
            # Severity: scale 10-80 based on disconnected probe count
            severity = min(80, 10 + disc_count * 2)

            ripe_alerts.append({
                "region_code": f"RIPE-{cc}",
                "region_name": f"{cc} (Atlas probes)",
                "country_code": cc,
                "country_name": cc,
                "level": "critical" if disc_count >= 10 else "warning",
                "datasource": "ripe-atlas",
                "severity": severity,
                "lat": sum(lats) / len(lats),
                "lng": sum(lngs) / len(lngs),
                "probe_count": disc_count,
            })

        # 6. Merge into internet_outages — keep IODA entries, replace old RIPE entries
        with _data_lock:
            current = latest_data.get("internet_outages", [])
            ioda_only = [o for o in current if o.get("datasource") != "ripe-atlas"]
            latest_data["internet_outages"] = ioda_only + ripe_alerts

        if ripe_alerts:
            _mark_fresh("internet_outages")
        logger.info(
            f"RIPE Atlas: {len(ripe_alerts)} countries with probe disconnections "
            f"(from {len(disconnected)} disconnected / ~{total_connected} connected probes)"
        )
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as e:
        logger.error(f"Error fetching RIPE Atlas probes: {e}")


# ---------------------------------------------------------------------------
# Data Centers (local geocoded JSON)
# ---------------------------------------------------------------------------
_DC_GEOCODED_PATH = Path(__file__).parent.parent.parent / "data" / "datacenters_geocoded.json"


def fetch_datacenters():
    """Load geocoded data centers (5K+ street-level precise locations)."""
    from services.fetchers._store import is_any_active

    if not is_any_active("datacenters"):
        return
    dcs = []
    try:
        if not _DC_GEOCODED_PATH.exists():
            logger.warning(f"Geocoded DC file not found: {_DC_GEOCODED_PATH}")
            return
        raw = json.loads(_DC_GEOCODED_PATH.read_text(encoding="utf-8"))
        for entry in raw:
            lat = entry.get("lat")
            lng = entry.get("lng")
            if lat is None or lng is None:
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            dcs.append(
                {
                    "name": entry.get("name", "Unknown"),
                    "company": entry.get("company", ""),
                    "street": entry.get("street", ""),
                    "city": entry.get("city", ""),
                    "country": entry.get("country", ""),
                    "zip": entry.get("zip", ""),
                    "lat": lat,
                    "lng": lng,
                }
            )
        logger.info(f"Data centers: {len(dcs)} geocoded locations loaded")
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as e:
        logger.error(f"Error loading data centers: {e}")
    with _data_lock:
        latest_data["datacenters"] = dcs
    if dcs:
        _mark_fresh("datacenters")


# ---------------------------------------------------------------------------
# Military Bases (static JSON — Western Pacific)
# ---------------------------------------------------------------------------
_MILITARY_BASES_PATH = Path(__file__).parent.parent.parent / "data" / "military_bases.json"


def fetch_military_bases():
    """Load static military base locations (Western Pacific focus)."""
    bases = []
    try:
        if not _MILITARY_BASES_PATH.exists():
            logger.warning(f"Military bases file not found: {_MILITARY_BASES_PATH}")
            return
        raw = json.loads(_MILITARY_BASES_PATH.read_text(encoding="utf-8"))
        for entry in raw:
            lat = entry.get("lat")
            lng = entry.get("lng")
            if lat is None or lng is None:
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            bases.append({
                "name": entry.get("name", "Unknown"),
                "country": entry.get("country", ""),
                "operator": entry.get("operator", ""),
                "branch": entry.get("branch", ""),
                "lat": lat, "lng": lng,
            })
        logger.info(f"Military bases: {len(bases)} locations loaded")
    except Exception as e:
        logger.error(f"Error loading military bases: {e}")
    with _data_lock:
        latest_data["military_bases"] = bases
    if bases:
        _mark_fresh("military_bases")


# ---------------------------------------------------------------------------
# Power Plants (WRI Global Power Plant Database)
# ---------------------------------------------------------------------------
_POWER_PLANTS_PATH = Path(__file__).parent.parent.parent / "data" / "power_plants.json"


def fetch_power_plants():
    """Load WRI Global Power Plant Database (~35K facilities)."""
    plants = []
    try:
        if not _POWER_PLANTS_PATH.exists():
            logger.warning(f"Power plants file not found: {_POWER_PLANTS_PATH}")
            return
        raw = json.loads(_POWER_PLANTS_PATH.read_text(encoding="utf-8"))
        for entry in raw:
            lat = entry.get("lat")
            lng = entry.get("lng")
            if lat is None or lng is None:
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            plants.append({
                "name": entry.get("name", "Unknown"),
                "country": entry.get("country", ""),
                "fuel_type": entry.get("fuel_type", "Unknown"),
                "capacity_mw": entry.get("capacity_mw"),
                "owner": entry.get("owner", ""),
                "lat": lat, "lng": lng,
            })
        logger.info(f"Power plants: {len(plants)} facilities loaded")
    except Exception as e:
        logger.error(f"Error loading power plants: {e}")
    with _data_lock:
        latest_data["power_plants"] = plants
    if plants:
        _mark_fresh("power_plants")


# ---------------------------------------------------------------------------
# CCTV Cameras
# ---------------------------------------------------------------------------
def fetch_cctv():
    from services.fetchers._store import is_any_active

    if not is_any_active("cctv"):
        return
    try:
        from services.cctv_pipeline import get_all_cameras

        cameras = get_all_cameras()
        if len(cameras) < 500:
            # Serve the current DB snapshot immediately and let the scheduled
            # ingest cycle populate/refresh cameras asynchronously.
            logger.info(
                "CCTV DB currently has %d cameras — serving cached snapshot and waiting for scheduled ingest",
                len(cameras),
            )
        with _data_lock:
            latest_data["cctv"] = cameras
        _mark_fresh("cctv")
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as e:
        logger.error(f"Error fetching cctv from DB: {e}")


# ---------------------------------------------------------------------------
# KiwiSDR Receivers
# ---------------------------------------------------------------------------
@with_retry(max_retries=2, base_delay=2)
def fetch_kiwisdr():
    from services.fetchers._store import is_any_active

    if not is_any_active("kiwisdr"):
        return
    try:
        from services.kiwisdr_fetcher import fetch_kiwisdr_nodes

        nodes = fetch_kiwisdr_nodes()
        with _data_lock:
            latest_data["kiwisdr"] = nodes
        _mark_fresh("kiwisdr")
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as e:
        logger.error(f"Error fetching KiwiSDR nodes: {e}")
        with _data_lock:
            latest_data["kiwisdr"] = []


# ---------------------------------------------------------------------------
# SatNOGS Ground Stations + Observations
# ---------------------------------------------------------------------------
@with_retry(max_retries=2, base_delay=2)
def fetch_satnogs():
    from services.fetchers._store import is_any_active

    if not is_any_active("satnogs"):
        return
    try:
        from services.satnogs_fetcher import fetch_satnogs_stations, fetch_satnogs_observations

        stations = fetch_satnogs_stations()
        obs = fetch_satnogs_observations()
        with _data_lock:
            latest_data["satnogs_stations"] = stations
            latest_data["satnogs_observations"] = obs
        _mark_fresh("satnogs_stations", "satnogs_observations")
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as e:
        logger.error(f"Error fetching SatNOGS: {e}")


# ---------------------------------------------------------------------------
# PSK Reporter — HF Digital Mode Spots
# ---------------------------------------------------------------------------
@with_retry(max_retries=2, base_delay=2)
def fetch_psk_reporter():
    from services.fetchers._store import is_any_active

    if not is_any_active("psk_reporter"):
        return
    try:
        from services.psk_reporter_fetcher import fetch_psk_reporter_spots

        spots = fetch_psk_reporter_spots()
        with _data_lock:
            latest_data["psk_reporter"] = spots
        _mark_fresh("psk_reporter")
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as e:
        logger.error(f"Error fetching PSK Reporter: {e}")
        with _data_lock:
            latest_data["psk_reporter"] = []


# ---------------------------------------------------------------------------
# TinyGS LoRa Satellites
# ---------------------------------------------------------------------------
@with_retry(max_retries=2, base_delay=2)
def fetch_tinygs():
    from services.fetchers._store import is_any_active

    if not is_any_active("tinygs"):
        return
    try:
        from services.tinygs_fetcher import fetch_tinygs_satellites

        sats = fetch_tinygs_satellites()
        with _data_lock:
            latest_data["tinygs_satellites"] = sats
        _mark_fresh("tinygs_satellites")
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as e:
        logger.error(f"Error fetching TinyGS: {e}")


# ---------------------------------------------------------------------------
# Police Scanners (OpenMHZ) — geocode city+state via local GeoNames DB
# ---------------------------------------------------------------------------
_scanner_geo_cache: dict = {}  # city|state -> (lat, lng) — populated once from GeoNames


def _build_scanner_geo_lookup():
    """Build a US city/county→coords lookup from reverse_geocoder's bundled GeoNames CSV."""
    if _scanner_geo_cache:
        return
    try:
        import csv, os, reverse_geocoder as rg

        geo_file = os.path.join(os.path.dirname(rg.__file__), "rg_cities1000.csv")
        # US state abbreviation → admin1 name mapping
        _abbr = {
            "AL": "Alabama",
            "AK": "Alaska",
            "AZ": "Arizona",
            "AR": "Arkansas",
            "CA": "California",
            "CO": "Colorado",
            "CT": "Connecticut",
            "DE": "Delaware",
            "FL": "Florida",
            "GA": "Georgia",
            "HI": "Hawaii",
            "ID": "Idaho",
            "IL": "Illinois",
            "IN": "Indiana",
            "IA": "Iowa",
            "KS": "Kansas",
            "KY": "Kentucky",
            "LA": "Louisiana",
            "ME": "Maine",
            "MD": "Maryland",
            "MA": "Massachusetts",
            "MI": "Michigan",
            "MN": "Minnesota",
            "MS": "Mississippi",
            "MO": "Missouri",
            "MT": "Montana",
            "NE": "Nebraska",
            "NV": "Nevada",
            "NH": "New Hampshire",
            "NJ": "New Jersey",
            "NM": "New Mexico",
            "NY": "New York",
            "NC": "North Carolina",
            "ND": "North Dakota",
            "OH": "Ohio",
            "OK": "Oklahoma",
            "OR": "Oregon",
            "PA": "Pennsylvania",
            "RI": "Rhode Island",
            "SC": "South Carolina",
            "SD": "South Dakota",
            "TN": "Tennessee",
            "TX": "Texas",
            "UT": "Utah",
            "VT": "Vermont",
            "VA": "Virginia",
            "WA": "Washington",
            "WV": "West Virginia",
            "WI": "Wisconsin",
            "WY": "Wyoming",
            "DC": "Washington, D.C.",
        }
        state_full = {v.lower(): k for k, v in _abbr.items()}
        state_full["washington, d.c."] = "DC"

        county_coords = {}  # admin2(county)|state -> (lat, lon) — first city per county
        with open(geo_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for row in reader:
                if len(row) < 6 or row[5] != "US":
                    continue
                lat_s, lon_s, name, admin1, admin2 = row[0], row[1], row[2], row[3], row[4]
                st = state_full.get(admin1.lower(), "")
                if not st:
                    continue
                coords = (float(lat_s), float(lon_s))
                # City name → coords
                _scanner_geo_cache[f"{name.lower()}|{st}"] = coords
                # County name → coords (keep first match per county, usually the largest city)
                if admin2:
                    county_key = f"{admin2.lower()}|{st}"
                    if county_key not in county_coords:
                        county_coords[county_key] = coords
                    # Also strip " County" suffix for matching
                    stripped = admin2.lower().replace(" county", "").strip()
                    stripped_key = f"{stripped}|{st}"
                    if stripped_key not in county_coords:
                        county_coords[stripped_key] = coords

        # Merge county lookups (don't override city entries)
        for k, v in county_coords.items():
            if k not in _scanner_geo_cache:
                _scanner_geo_cache[k] = v
        # Special case: DC
        _scanner_geo_cache["washington|DC"] = (38.89511, -77.03637)
        logger.info(f"Scanner geo lookup: {len(_scanner_geo_cache)} US entries loaded")
    except Exception as e:
        logger.warning(f"Failed to build scanner geo lookup: {e}")


def _geocode_scanner(city: str, state: str):
    """Look up city+state coordinates from local GeoNames cache."""
    _build_scanner_geo_lookup()
    if not city or not state:
        return None
    st = state.upper()
    # Strip trailing state from city (e.g. "Lehigh, PA")
    c = city.strip()
    if ", " in c:
        parts = c.rsplit(", ", 1)
        if len(parts[1]) <= 2:
            c = parts[0]
    name = c.lower()
    # Try exact city match
    result = _scanner_geo_cache.get(f"{name}|{st}")
    if result:
        return result
    # Strip "County" / "Co" suffix
    stripped = name.replace(" county", "").replace(" co", "").strip()
    result = _scanner_geo_cache.get(f"{stripped}|{st}")
    if result:
        return result
    # Normalize "St." / "St" → "Saint"
    import re

    normed = re.sub(r"\bst\.?\s", "saint ", name)
    if normed != name:
        result = _scanner_geo_cache.get(f"{normed}|{st}")
        if result:
            return result
        # Also try with "s" suffix: "St. Marys" → "Saint Marys" and "Saint Mary's"
        for variant in [normed.rstrip("s"), normed.replace("ys", "y's")]:
            result = _scanner_geo_cache.get(f"{variant}|{st}")
            if result:
                return result
    # "Prince Georges" → "Prince George's" (apostrophe variants)
    if "georges" in name:
        key = name.replace("georges", "george's") + "|" + st
        result = _scanner_geo_cache.get(key)
        if result:
            return result
    # Multi-location: "Scott and Carver" → try first part
    if " and " in name:
        first = name.split(" and ")[0].strip()
        result = _scanner_geo_cache.get(f"{first}|{st}")
        if result:
            return result
    # Comma-separated list: "Adams, Jackson, Juneau" → try first
    if ", " in name:
        first = name.split(", ")[0].strip()
        result = _scanner_geo_cache.get(f"{first}|{st}")
        if result:
            return result
    # Drop directional prefix: "North Fulton" → "Fulton"
    for prefix in ("north ", "south ", "east ", "west "):
        if name.startswith(prefix):
            result = _scanner_geo_cache.get(f"{name[len(prefix):]}|{st}")
            if result:
                return result
    return None


@with_retry(max_retries=2, base_delay=2)
def fetch_scanners():
    from services.fetchers._store import is_any_active

    if not is_any_active("scanners"):
        return
    try:
        from services.radio_intercept import get_openmhz_systems

        systems = get_openmhz_systems()
        scanners = []
        for s in systems:
            city = s.get("city", "") or s.get("county", "") or ""
            state = s.get("state", "")
            coords = _geocode_scanner(city, state)
            if not coords:
                continue
            lat, lng = coords
            scanners.append(
                {
                    "shortName": s.get("shortName", ""),
                    "name": s.get("name", "Unknown Scanner"),
                    "lat": round(lat, 5),
                    "lng": round(lng, 5),
                    "city": city,
                    "state": state,
                    "clientCount": s.get("clientCount", 0),
                    "description": s.get("description", ""),
                }
            )
        with _data_lock:
            latest_data["scanners"] = scanners
        if scanners:
            _mark_fresh("scanners")
        logger.info(f"Scanners: {len(scanners)}/{len(systems)} geocoded")
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as e:
        logger.error(f"Error fetching scanners: {e}")
        with _data_lock:
            latest_data["scanners"] = []
