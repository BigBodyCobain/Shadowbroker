"""Earth-observation fetchers — earthquakes, FIRMS fires, space weather, weather radar,
severe weather alerts, air quality, volcanoes."""

import concurrent.futures
import csv
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import time
import heapq
from datetime import datetime, timedelta
from pathlib import Path
from services.network_utils import fetch_with_curl
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.fetchers.retry import with_retry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Earthquakes (USGS)
# ---------------------------------------------------------------------------
@with_retry(max_retries=1, base_delay=1)
def fetch_earthquakes():
    from services.fetchers._store import is_any_active

    if not is_any_active("earthquakes"):
        return
    quakes = []
    try:
        url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
        response = fetch_with_curl(url, timeout=10)
        if response.status_code == 200:
            features = response.json().get("features", [])
            for f in features[:50]:
                mag = f["properties"]["mag"]
                lng, lat, depth = f["geometry"]["coordinates"]
                quakes.append(
                    {
                        "id": f["id"],
                        "mag": mag,
                        "lat": lat,
                        "lng": lng,
                        "place": f["properties"]["place"],
                    }
                )
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching earthquakes: {e}")
    with _data_lock:
        latest_data["earthquakes"] = quakes
    if quakes:
        _mark_fresh("earthquakes")


# ---------------------------------------------------------------------------
# NASA FIRMS Fires
# ---------------------------------------------------------------------------
@with_retry(max_retries=1, base_delay=2)
def fetch_firms_fires():
    """Fetch global fire/thermal anomalies from NASA FIRMS (NOAA-20 VIIRS, 24h, no key needed)."""
    from services.fetchers._store import is_any_active

    if not is_any_active("firms"):
        return
    fires = []
    try:
        url = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_24h.csv"
        response = fetch_with_curl(url, timeout=30)
        if response.status_code == 200:
            reader = csv.DictReader(io.StringIO(response.text))
            all_rows = []
            for row in reader:
                try:
                    lat = float(row.get("latitude", 0))
                    lng = float(row.get("longitude", 0))
                    frp = float(row.get("frp", 0))
                    conf = row.get("confidence", "nominal")
                    daynight = row.get("daynight", "")
                    bright = float(row.get("bright_ti4", 0))
                    all_rows.append(
                        {
                            "lat": lat,
                            "lng": lng,
                            "frp": frp,
                            "brightness": bright,
                            "confidence": conf,
                            "daynight": daynight,
                            "acq_date": row.get("acq_date", ""),
                            "acq_time": row.get("acq_time", ""),
                        }
                    )
                except (ValueError, TypeError):
                    continue
            fires = heapq.nlargest(5000, all_rows, key=lambda x: x["frp"])
        logger.info(f"FIRMS fires: {len(fires)} hotspots (from {response.status_code})")
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching FIRMS fires: {e}")
    with _data_lock:
        latest_data["firms_fires"] = fires
    if fires:
        _mark_fresh("firms_fires")


# ---------------------------------------------------------------------------
# NASA FIRMS Country-Scoped Fires (enriches global CSV with conflict zones)
# ---------------------------------------------------------------------------
# Conflict-zone countries of interest for higher-detail fire/thermal data
_FIRMS_COUNTRIES = ["ISR", "IRN", "IRQ", "LBN", "SYR", "YEM", "SAU", "UKR", "RUS", "TUR"]


@with_retry(max_retries=1, base_delay=2)
def fetch_firms_country_fires():
    """Fetch country-scoped fire hotspots from NASA FIRMS MAP_KEY API.

    Supplements the global CSV feed with more granular data for conflict zones.
    Merges results into the existing firms_fires data store (no new frontend key).
    Requires FIRMS_MAP_KEY env var (free from NASA Earthdata). Skips if not set.
    """
    from services.fetchers._store import is_any_active

    if not is_any_active("firms"):
        return

    map_key = os.environ.get("FIRMS_MAP_KEY", "")
    if not map_key:
        logger.debug("FIRMS_MAP_KEY not set, skipping country-scoped FIRMS fetch")
        return

    # Build a set of existing (lat, lng) rounded to 0.01° for dedup
    with _data_lock:
        existing = set()
        for f in latest_data.get("firms_fires", []):
            existing.add((round(f["lat"], 2), round(f["lng"], 2)))

    new_fires = []
    for country in _FIRMS_COUNTRIES:
        try:
            url = (
                f"https://firms.modaps.eosdis.nasa.gov/api/country/csv/"
                f"{map_key}/VIIRS_NOAA20_NRT/{country}/1"
            )
            response = fetch_with_curl(url, timeout=15)
            if response.status_code != 200:
                logger.debug(f"FIRMS country {country}: HTTP {response.status_code}")
                continue

            reader = csv.DictReader(io.StringIO(response.text))
            for row in reader:
                try:
                    lat = float(row.get("latitude", 0))
                    lng = float(row.get("longitude", 0))
                    key = (round(lat, 2), round(lng, 2))
                    if key in existing:
                        continue  # Already in global data
                    existing.add(key)

                    frp = float(row.get("frp", 0))
                    new_fires.append({
                        "lat": lat,
                        "lng": lng,
                        "frp": frp,
                        "brightness": float(row.get("bright_ti4", 0)),
                        "confidence": row.get("confidence", "nominal"),
                        "daynight": row.get("daynight", ""),
                        "acq_date": row.get("acq_date", ""),
                        "acq_time": row.get("acq_time", ""),
                    })
                except (ValueError, TypeError):
                    continue

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
            logger.debug(f"FIRMS country {country} failed: {e}")

    if new_fires:
        with _data_lock:
            current = latest_data.get("firms_fires", [])
            merged = current + new_fires
            # Keep top 6000 by FRP (slightly more than global-only cap of 5000)
            if len(merged) > 6000:
                merged = heapq.nlargest(6000, merged, key=lambda x: x["frp"])
            latest_data["firms_fires"] = merged
        logger.info(f"FIRMS country enrichment: +{len(new_fires)} fires from {len(_FIRMS_COUNTRIES)} countries")
        _mark_fresh("firms_fires")
    else:
        logger.debug("FIRMS country enrichment: no new fires found")


# ---------------------------------------------------------------------------
# Space Weather (NOAA SWPC)
# ---------------------------------------------------------------------------
@with_retry(max_retries=1, base_delay=1)
def fetch_space_weather():
    """Fetch NOAA SWPC Kp index and recent solar events."""
    try:
        kp_resp = fetch_with_curl(
            "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json", timeout=10
        )
        kp_value = None
        kp_text = "QUIET"
        if kp_resp.status_code == 200:
            kp_data = kp_resp.json()
            if kp_data:
                latest_kp = kp_data[-1]
                kp_value = float(latest_kp.get("kp_index", 0))
                if kp_value >= 7:
                    kp_text = f"STORM G{min(int(kp_value) - 4, 5)}"
                elif kp_value >= 5:
                    kp_text = f"STORM G{min(int(kp_value) - 4, 5)}"
                elif kp_value >= 4:
                    kp_text = "ACTIVE"
                elif kp_value >= 3:
                    kp_text = "UNSETTLED"

        events = []
        ev_resp = fetch_with_curl(
            "https://services.swpc.noaa.gov/json/edited_events.json", timeout=10
        )
        if ev_resp.status_code == 200:
            all_events = ev_resp.json()
            for ev in all_events[-10:]:
                events.append(
                    {
                        "type": ev.get("type", ""),
                        "begin": ev.get("begin", ""),
                        "end": ev.get("end", ""),
                        "classtype": ev.get("classtype", ""),
                    }
                )

        with _data_lock:
            latest_data["space_weather"] = {
                "kp_index": kp_value,
                "kp_text": kp_text,
                "events": events,
            }
        _mark_fresh("space_weather")
        logger.info(f"Space weather: Kp={kp_value} ({kp_text}), {len(events)} events")
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching space weather: {e}")


# ---------------------------------------------------------------------------
# Weather Radar (RainViewer)
# ---------------------------------------------------------------------------
@with_retry(max_retries=1, base_delay=1)
def fetch_weather():
    try:
        url = "https://api.rainviewer.com/public/weather-maps.json"
        response = fetch_with_curl(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "radar" in data and "past" in data["radar"]:
                latest_time = data["radar"]["past"][-1]["time"]
                with _data_lock:
                    latest_data["weather"] = {
                        "time": latest_time,
                        "host": data.get("host", "https://tilecache.rainviewer.com"),
                    }
                _mark_fresh("weather")
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching weather: {e}")


# ---------------------------------------------------------------------------
# NOAA/NWS Severe Weather Alerts
# ---------------------------------------------------------------------------
@with_retry(max_retries=1, base_delay=2)
def fetch_weather_alerts():
    """Fetch active severe weather alerts from NOAA/NWS (US coverage, GeoJSON polygons)."""
    from services.fetchers._store import is_any_active

    if not is_any_active("weather_alerts"):
        return
    alerts = []
    try:
        url = "https://api.weather.gov/alerts/active?status=actual"
        headers = {
            "User-Agent": "(ShadowBroker OSINT Dashboard, github.com/BigBodyCobain/Shadowbroker)",
            "Accept": "application/geo+json",
        }
        response = fetch_with_curl(url, timeout=15, headers=headers)
        if response.status_code == 200:
            features = response.json().get("features", [])
            for f in features:
                props = f.get("properties", {})
                geom = f.get("geometry")
                if not geom:
                    continue  # skip zone-only alerts with no polygon
                alerts.append(
                    {
                        "id": props.get("id", ""),
                        "event": props.get("event", ""),
                        "severity": props.get("severity", "Unknown"),
                        "certainty": props.get("certainty", ""),
                        "urgency": props.get("urgency", ""),
                        "headline": props.get("headline", ""),
                        "description": (props.get("description", "") or "")[:300],
                        "expires": props.get("expires", ""),
                        "geometry": geom,
                    }
                )
        logger.info(f"Weather alerts: {len(alerts)} active (with polygons)")
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching weather alerts: {e}")
    with _data_lock:
        latest_data["weather_alerts"] = alerts
    if alerts:
        _mark_fresh("weather_alerts")


# ---------------------------------------------------------------------------
# Air Quality (OpenAQ v3)
# ---------------------------------------------------------------------------
def _pm25_to_aqi(pm25: float) -> int:
    """Convert PM2.5 concentration (µg/m³) to US EPA AQI."""
    breakpoints = [
        (0, 12.0, 0, 50),
        (12.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 500.4, 301, 500),
    ]
    for c_lo, c_hi, i_lo, i_hi in breakpoints:
        if pm25 <= c_hi:
            return round(((i_hi - i_lo) / (c_hi - c_lo)) * (pm25 - c_lo) + i_lo)
    return 500


@with_retry(max_retries=1, base_delay=2)
def fetch_air_quality():
    """Fetch global air quality stations with PM2.5 data from OpenAQ."""
    from services.fetchers._store import is_any_active

    if not is_any_active("air_quality"):
        return
    stations = []
    api_key = os.environ.get("OPENAQ_API_KEY", "")
    if not api_key:
        logger.debug("OPENAQ_API_KEY not set, skipping air quality fetch")
        return
    try:
        url = "https://api.openaq.org/v3/locations?limit=5000&parameter_id=2&order_by=datetime&sort_order=desc"
        headers = {"X-API-Key": api_key}
        response = fetch_with_curl(url, timeout=30, headers=headers)
        if response.status_code == 200:
            results = response.json().get("results", [])
            for loc in results:
                coords = loc.get("coordinates", {})
                lat = coords.get("latitude")
                lng = coords.get("longitude")
                if lat is None or lng is None:
                    continue
                pm25 = None
                for p in loc.get("parameters", []):
                    if p.get("id") == 2:
                        pm25 = p.get("lastValue")
                        break
                if pm25 is None:
                    continue
                pm25_val = float(pm25)
                if pm25_val < 0:
                    continue
                stations.append(
                    {
                        "id": loc.get("id"),
                        "name": loc.get("name", "Unknown"),
                        "lat": lat,
                        "lng": lng,
                        "pm25": round(pm25_val, 1),
                        "aqi": _pm25_to_aqi(pm25_val),
                        "country": loc.get("country", {}).get("code", ""),
                    }
                )
        logger.info(f"Air quality: {len(stations)} stations")
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching air quality: {e}")
    with _data_lock:
        latest_data["air_quality"] = stations
    if stations:
        _mark_fresh("air_quality")


# ---------------------------------------------------------------------------
# Volcanoes (Smithsonian Global Volcanism Program)
# ---------------------------------------------------------------------------
@with_retry(max_retries=2, base_delay=5)
def fetch_volcanoes():
    """Fetch Holocene volcanoes from Smithsonian GVP WFS (static reference data)."""
    from services.fetchers._store import is_any_active

    if not is_any_active("volcanoes"):
        return
    volcanoes = []
    try:
        url = (
            "https://webservices.volcano.si.edu/geoserver/GVP-VOTW/wfs"
            "?service=WFS&version=2.0.0&request=GetFeature"
            "&typeName=GVP-VOTW:E3WebApp_HoloceneVolcanoes"
            "&outputFormat=application/json"
        )
        response = fetch_with_curl(url, timeout=30)
        if response.status_code == 200:
            features = response.json().get("features", [])
            for f in features:
                props = f.get("properties", {})
                geom = f.get("geometry", {})
                coords = geom.get("coordinates", [None, None])
                if coords[0] is None:
                    continue
                last_eruption = props.get("LastEruption")
                last_eruption_year = None
                if last_eruption is not None:
                    try:
                        last_eruption_year = int(last_eruption)
                    except (ValueError, TypeError):
                        pass
                volcanoes.append(
                    {
                        "name": props.get("VolcanoName", "Unknown"),
                        "type": props.get("VolcanoType", ""),
                        "country": props.get("Country", ""),
                        "region": props.get("TectonicSetting", ""),
                        "elevation": props.get("Elevation", 0),
                        "last_eruption_year": last_eruption_year,
                        "lat": coords[1],
                        "lng": coords[0],
                    }
                )
        logger.info(f"Volcanoes: {len(volcanoes)} Holocene volcanoes loaded")
    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
        logger.error(f"Error fetching volcanoes: {e}")
    with _data_lock:
        latest_data["volcanoes"] = volcanoes
    if volcanoes:
        _mark_fresh("volcanoes")


# ---------------------------------------------------------------------------
# VIIRS Night Lights Change Detection (Google Earth Engine — optional)
# ---------------------------------------------------------------------------
_VIIRS_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "viirs_change_nodes.json"
_VIIRS_CACHE_MAX_AGE_S = 86400  # 24 hours

# Conflict-zone AOIs: (name, south, west, north, east)
_VIIRS_AOIS = [
    ("Gaza Strip", 31.2, 34.2, 31.6, 34.6),
    ("Kharkiv Oblast", 48.5, 35.0, 50.5, 38.5),
    ("Donetsk Oblast", 47.0, 36.5, 49.0, 39.5),
    ("Zaporizhzhia Oblast", 46.5, 34.5, 48.5, 37.0),
    ("Aleppo", 35.8, 36.5, 36.5, 37.5),
    ("Khartoum", 15.2, 32.2, 15.9, 32.9),
    ("Sana'a", 14.9, 43.8, 15.6, 44.5),
    ("Mosul", 36.0, 42.8, 36.7, 43.5),
    ("Mariupol", 46.9, 37.2, 47.3, 37.8),
    ("Southern Lebanon", 33.0, 35.0, 33.5, 36.0),
]

_VIIRS_SEVERITY_THRESHOLDS = [
    (-100, -70, "severe"),
    (-70, -50, "high"),
    (-50, -30, "moderate"),
    (30, 100, "growth"),
    (100, 500, "rapid_growth"),
]


def _classify_viirs_severity(pct_change: float):
    for lo, hi, label in _VIIRS_SEVERITY_THRESHOLDS:
        if lo <= pct_change <= hi:
            return label
    return None


def _load_viirs_stale_cache():
    """Load stale cache if available (when GEE is not configured)."""
    if _VIIRS_CACHE_PATH.exists():
        try:
            cached = json.loads(_VIIRS_CACHE_PATH.read_text(encoding="utf-8"))
            with _data_lock:
                latest_data["viirs_change_nodes"] = cached
            _mark_fresh("viirs_change_nodes")
            logger.info(f"VIIRS change nodes: loaded {len(cached)} from stale cache")
        except Exception:
            pass


@with_retry(max_retries=1, base_delay=5)
def fetch_viirs_change_nodes():
    """Compute VIIRS nighttime radiance change nodes via GEE (optional)."""
    from services.fetchers._store import is_any_active

    if not is_any_active("viirs_nightlights"):
        return

    # Check cache freshness first
    if _VIIRS_CACHE_PATH.exists():
        age = time.time() - _VIIRS_CACHE_PATH.stat().st_mtime
        if age < _VIIRS_CACHE_MAX_AGE_S:
            try:
                cached = json.loads(_VIIRS_CACHE_PATH.read_text(encoding="utf-8"))
                with _data_lock:
                    latest_data["viirs_change_nodes"] = cached
                _mark_fresh("viirs_change_nodes")
                logger.info(f"VIIRS change nodes: loaded {len(cached)} from cache (age {age:.0f}s)")
                return
            except Exception as e:
                logger.warning(f"VIIRS cache read failed: {e}")

    # Try importing earthengine-api (optional dependency)
    try:
        import ee
    except ImportError:
        logger.debug("earthengine-api not installed, skipping VIIRS change detection")
        _load_viirs_stale_cache()
        return

    # Authenticate with service account
    sa_key_path = os.environ.get("GEE_SERVICE_ACCOUNT_KEY", "")
    if not sa_key_path:
        logger.debug("GEE_SERVICE_ACCOUNT_KEY not set, skipping VIIRS change detection")
        _load_viirs_stale_cache()
        return

    try:
        credentials = ee.ServiceAccountCredentials(None, key_file=sa_key_path)
        ee.Initialize(credentials)
    except Exception as e:
        logger.error(f"GEE authentication failed: {e}")
        _load_viirs_stale_cache()
        return

    # Compute change nodes for each AOI
    nodes = []
    viirs = ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMCFG").select("avg_rad")

    for aoi_name, s_lat, w_lng, n_lat, e_lng in _VIIRS_AOIS:
        try:
            aoi = ee.Geometry.Rectangle([w_lng, s_lat, e_lng, n_lat])

            # Most recent available date
            now = ee.Date(datetime.utcnow().isoformat()[:10])

            # Current: 12-month rolling mean ending now
            current = viirs.filterDate(now.advance(-12, "month"), now).mean().clip(aoi)

            # Baseline: 12-month mean ending 12 months ago
            baseline = viirs.filterDate(
                now.advance(-24, "month"), now.advance(-12, "month")
            ).mean().clip(aoi)

            # Floor baseline at 0.5 nW/cm²/sr to avoid div-by-zero in dark areas
            baseline_safe = baseline.max(0.5)

            # Percentage change
            change = current.subtract(baseline).divide(baseline_safe).multiply(100)

            # Only keep pixels with >30% absolute change
            sig_mask = change.abs().gt(30)
            change_masked = change.updateMask(sig_mask)

            # Sample up to 200 points per AOI
            samples = change_masked.sample(
                region=aoi, scale=500, numPixels=200, geometries=True
            )
            sample_list = samples.getInfo()

            for feat in sample_list.get("features", []):
                coords = feat["geometry"]["coordinates"]
                pct = feat["properties"].get("avg_rad", 0)
                severity = _classify_viirs_severity(pct)
                if severity is None:
                    continue
                nodes.append({
                    "lat": round(coords[1], 4),
                    "lng": round(coords[0], 4),
                    "mean_change_pct": round(pct, 1),
                    "severity": severity,
                    "aoi_name": aoi_name,
                })
        except Exception as e:
            logger.warning(f"VIIRS change detection failed for {aoi_name}: {e}")
            continue

    # Save to cache
    try:
        _VIIRS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _VIIRS_CACHE_PATH.write_text(
            json.dumps(nodes, separators=(",", ":")), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"Failed to write VIIRS cache: {e}")

    with _data_lock:
        latest_data["viirs_change_nodes"] = nodes
    if nodes:
        _mark_fresh("viirs_change_nodes")
    logger.info(f"VIIRS change nodes: {len(nodes)} nodes from {len(_VIIRS_AOIS)} AOIs")


# ---------------------------------------------------------------------------
# UAP Sightings (NUFORC — National UAP Reporting Center)
# ---------------------------------------------------------------------------

# Shape → canonical category mapping for consistent frontend filtering
_UAP_SHAPE_MAP = {
    "light": "light", "fireball": "fireball", "orb": "orb",
    "sphere": "orb", "circle": "orb", "oval": "orb", "egg": "orb",
    "triangle": "triangle", "delta": "triangle", "chevron": "triangle",
    "boomerang": "triangle",
    "cigar": "cigar", "cylinder": "cigar", "tube": "cigar",
    "disk": "disk", "disc": "disk", "saucer": "disk",
    "diamond": "diamond", "cone": "diamond", "cross": "diamond",
    "rectangle": "rectangle", "square": "rectangle",
    "formation": "formation", "cluster": "formation",
    "changing": "changing", "flash": "flash", "star": "light",
    "tic-tac": "tic-tac", "tic tac": "tic-tac",
}

# US state → approximate centroid for coarse geocoding when city lookup fails
_US_STATE_COORDS: dict[str, tuple[float, float]] = {
    "AL": (32.8, -86.8), "AK": (64.2, -152.5), "AZ": (34.0, -111.1),
    "AR": (35.2, -91.8), "CA": (36.8, -119.4), "CO": (39.6, -105.3),
    "CT": (41.6, -72.7), "DE": (39.3, -75.5), "FL": (27.8, -81.8),
    "GA": (32.7, -83.5), "HI": (19.9, -155.6), "ID": (44.1, -114.7),
    "IL": (40.3, -89.0), "IN": (40.3, -86.1), "IA": (42.0, -93.2),
    "KS": (39.0, -98.5), "KY": (37.8, -84.3), "LA": (31.2, -92.5),
    "ME": (45.3, -69.4), "MD": (39.0, -76.6), "MA": (42.4, -71.4),
    "MI": (44.3, -85.6), "MN": (46.7, -94.7), "MS": (32.7, -89.5),
    "MO": (38.6, -91.8), "MT": (46.8, -110.4), "NE": (41.5, -99.9),
    "NV": (38.8, -116.4), "NH": (43.2, -71.6), "NJ": (40.1, -74.4),
    "NM": (34.5, -106.0), "NY": (43.0, -75.0), "NC": (35.6, -79.8),
    "ND": (47.5, -100.5), "OH": (40.4, -82.9), "OK": (35.0, -97.1),
    "OR": (43.8, -120.6), "PA": (41.2, -77.2), "RI": (41.6, -71.5),
    "SC": (33.8, -81.2), "SD": (43.9, -99.4), "TN": (35.5, -86.6),
    "TX": (31.0, -97.6), "UT": (39.3, -111.1), "VT": (44.6, -72.6),
    "VA": (37.4, -78.7), "WA": (47.4, -120.7), "WV": (38.6, -80.6),
    "WI": (43.8, -88.8), "WY": (43.1, -107.6), "DC": (38.9, -77.0),
}


def _normalize_uap_shape(raw: str) -> str:
    """Normalize a raw NUFORC shape string to a canonical category."""
    key = raw.strip().lower()
    return _UAP_SHAPE_MAP.get(key, "unknown")


def _reverse_geocode_state(lat: float, lng: float) -> tuple[str, str]:
    """Best-effort reverse-geocode a lat/lng to (state_abbr, country).

    Uses the _US_STATE_COORDS centroid table for fast approximate matching.
    Returns ('', 'Unknown') if no close match is found.
    """
    best_state = ""
    best_dist = 999.0
    for st, (slat, slng) in _US_STATE_COORDS.items():
        d = ((lat - slat) ** 2 + (lng - slng) ** 2) ** 0.5
        if d < best_dist:
            best_dist = d
            best_state = st
    if best_dist < 5.0:  # ~5 degrees tolerance
        return best_state, "US"
    return "", "Unknown"


# ── NUFORC Mapbox Tilequery API ─────────────────────────────────────────
# NUFORC's website switched to a JS-rendered Mapbox GL map.  The old HTML
# table scraper is defunct.  We now query the Mapbox Tilequery API against
# NUFORC's public tileset to get precise sighting coordinates.
#
# Tileset: nuforc.cmm18aqea06bu1mmselhpnano-0ce5v
# Layer:   Sightings   Fields: Count, From, To, LinkLat, LinkLon
#
# We sample a grid of points across the US/world with a 100 km radius and
# filter to sightings within the last 60 days.

_NUFORC_TILESET = "nuforc.cmm18aqea06bu1mmselhpnano-0ce5v"
_NUFORC_TOKEN = os.environ.get("NUFORC_MAPBOX_TOKEN", "").strip()
_NUFORC_RADIUS_M = 200_000  # 200 km query radius
_NUFORC_LIMIT = 50  # max features per tilequery call
_NUFORC_RECENT_DAYS = int(os.environ.get("NUFORC_RECENT_DAYS", "60"))
_NUFORC_GEOCODE_WORKERS = max(1, int(os.environ.get("NUFORC_GEOCODE_WORKERS", "1")))
# Photon (Komoot) is more lenient than Nominatim — ~200ms per query in
# practice, so a 0.3s spacing keeps us well under any soft throttle while
# still rebuilding a full 12-month window in ~10 minutes.
_NUFORC_GEOCODE_SPACING_S = float(os.environ.get("NUFORC_GEOCODE_SPACING_S", "0.3"))
_NUFORC_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_NUFORC_SIGHTINGS_CACHE_FILE = _NUFORC_DATA_DIR / "nuforc_recent_sightings.json"
_NUFORC_LOCATION_CACHE_FILE = _NUFORC_DATA_DIR / "nuforc_location_cache.json"

# Live NUFORC databank scraping (wpDataTables server-side AJAX).
# The HuggingFace mirror froze at 2023-12-20, so we pull directly from
# nuforc.org's monthly sub-index. Each month page embeds a wdtNonce we
# must extract, then POST to admin-ajax.php to get the DataTables JSON.
_NUFORC_LIVE_INDEX_URL = "https://nuforc.org/subndx/?id=e{yyyymm}"
_NUFORC_LIVE_AJAX_URL = (
    "https://nuforc.org/wp-admin/admin-ajax.php"
    "?action=get_wdtable&table_id=1&wdt_var1=YearMonth&wdt_var2={yyyymm}"
)
_NUFORC_LIVE_NONCE_RE = re.compile(
    r'id=["\']wdtNonceFrontendServerSide_1["\'][^>]*value=["\']([a-f0-9]+)["\']'
)
_NUFORC_LIVE_SIGHTING_ID_RE = re.compile(r"id=(\d+)")
_NUFORC_LIVE_USER_AGENT = "Mozilla/5.0 (ShadowBroker-OSINT NUFORC-fetcher)"
_NUFORC_LIVE_SESSION_COOKIES = _NUFORC_DATA_DIR / "nuforc_session.cookies"

# Sample grid covering continental US, Alaska, Hawaii, Canada, UK, Australia
_TILEQUERY_GRID: list[tuple[float, float]] = [
    # Continental US — ~4° spacing (lon, lat)
    (-122.4, 37.8), (-118.2, 34.1), (-112.1, 33.4), (-104.9, 39.7),
    (-95.4, 29.8),  (-96.8, 32.8),  (-87.6, 41.9),  (-84.4, 33.7),
    (-81.7, 41.5),  (-80.2, 25.8),  (-77.0, 38.9),  (-74.0, 40.7),
    (-71.1, 42.4),  (-90.2, 38.6),  (-93.3, 44.9),  (-111.9, 40.8),
    (-122.7, 45.5), (-86.2, 39.8),  (-106.6, 35.1), (-73.9, 43.2),
    (-76.6, 39.3),  (-97.5, 35.5),  (-83.0, 42.3),  (-117.2, 32.7),
    (-82.5, 28.0),  (-78.6, 35.8),  (-90.1, 30.0),  (-71.4, 41.8),
    # Alaska, Hawaii
    (-149.9, 61.2), (-155.5, 19.9),
    # Canada
    (-79.4, 43.7), (-123.1, 49.3), (-73.6, 45.5),
    # UK & Europe
    (-0.1, 51.5), (-3.2, 55.9),
    # Australia
    (151.2, -33.9), (144.9, -37.8),
]


def _fetch_nuforc_tilequery(lng: float, lat: float) -> list[dict]:
    """Query NUFORC Mapbox tileset around a single point, return raw features."""
    if not _NUFORC_TOKEN:
        return []
    url = (
        f"https://api.mapbox.com/v4/{_NUFORC_TILESET}/tilequery/"
        f"{lng},{lat}.json"
        f"?radius={_NUFORC_RADIUS_M}&limit={_NUFORC_LIMIT}"
        f"&access_token={_NUFORC_TOKEN}"
    )
    try:
        resp = fetch_with_curl(url, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("features", [])
    except Exception:
        pass
    return []


def _parse_nuforc_tile_date(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace("T", " ")
    raw = re.sub(r"\s+local$", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s+utc$", "", raw, flags=re.IGNORECASE)
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except (TypeError, ValueError):
            continue
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d")
        except ValueError:
            return None
    return None


def _load_nuforc_sightings_cache(*, force_refresh: bool = False) -> list[dict] | None:
    if force_refresh or not _NUFORC_SIGHTINGS_CACHE_FILE.exists():
        return None
    try:
        raw = json.loads(_NUFORC_SIGHTINGS_CACHE_FILE.read_text(encoding="utf-8"))
        built = raw.get("built", "")
        built_dt = datetime.fromisoformat(built) if built else None
        if built_dt is None:
            return None
        if (datetime.utcnow() - built_dt).total_seconds() > 86400:
            return None
        sightings = raw.get("sightings")
        if isinstance(sightings, list):
            if len(sightings) <= 0:
                logger.info("UAP sightings: cache is fresh but empty; rebuilding")
                return None
            logger.info(
                "UAP sightings: loaded %d cached reports from %s",
                len(sightings),
                built,
            )
            return sightings
    except Exception as e:
        logger.warning("UAP sightings: cache load error: %s", e)
    return None


def _save_nuforc_sightings_cache(sightings: list[dict]) -> None:
    if not sightings:
        logger.warning("UAP sightings: refusing to save empty daily cache")
        return
    try:
        _NUFORC_DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "built": datetime.utcnow().isoformat(),
            "count": len(sightings),
            "sightings": sightings,
        }
        _NUFORC_SIGHTINGS_CACHE_FILE.write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("UAP sightings: cache save error: %s", e)


def _load_nuforc_location_cache() -> dict[str, list[float] | None]:
    if not _NUFORC_LOCATION_CACHE_FILE.exists():
        return {}
    try:
        raw = json.loads(_NUFORC_LOCATION_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        cache: dict[str, list[float] | None] = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            if (
                isinstance(value, list)
                and len(value) == 2
                and all(isinstance(v, (int, float)) for v in value)
            ):
                cache[key] = [float(value[0]), float(value[1])]
            elif value is None:
                cache[key] = None
        return cache
    except Exception as e:
        logger.warning("UAP sightings: location cache load error: %s", e)
        return {}


def _save_nuforc_location_cache(cache: dict[str, list[float] | None]) -> None:
    try:
        _NUFORC_DATA_DIR.mkdir(parents=True, exist_ok=True)
        _NUFORC_LOCATION_CACHE_FILE.write_text(
            json.dumps(cache, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("UAP sightings: location cache save error: %s", e)


def _normalize_uap_location(raw: str) -> str:
    return re.sub(r"\s+", " ", str(raw or "").strip())


def _uap_country_from_location(location: str, state: str) -> str:
    if state:
        return "US"
    upper = location.upper()
    if "USA" in upper or "UNITED STATES" in upper:
        return "US"
    parts = [part.strip() for part in location.split(",") if part.strip()]
    if not parts:
        return "Unknown"
    country = parts[-1]
    return country.upper() if len(country) == 2 else country


_US_COUNTRY_ALIASES = {
    "", "USA", "US", "U.S.", "U.S.A.",
    "UNITED STATES", "UNITED STATES OF AMERICA",
}


def _uap_geocode_candidates(
    location: str, city: str, state: str, country: str = ""
) -> list[str]:
    """Build geocode query candidates in priority order.

    NUFORC's live databank is international, so we must query with the
    actual country first. Only when the country is empty or explicitly US
    do we fall back to the legacy USA-assumption behavior.
    """
    candidates: list[str] = []
    c = (country or "").strip()
    c_upper = c.upper()
    is_us = c_upper in _US_COUNTRY_ALIASES

    if not is_us:
        # Non-US: try country-qualified queries first to prevent the
        # geocoder from fuzzy-matching to a same-named US city.
        if city and state:
            candidates.append(f"{city}, {state}, {c}")
        if city:
            candidates.append(f"{city}, {c}")
        if city and state:
            candidates.append(f"{city}, {state}")
        if city:
            candidates.append(city)
    else:
        if city and state:
            candidates.append(f"{city}, {state}, USA")
            candidates.append(f"{city}, {state}")
        if city:
            candidates.append(city)

    normalized = _normalize_uap_location(location)
    if normalized:
        candidates.append(normalized)
        parts = [part.strip() for part in normalized.split(",") if part.strip()]
        if len(parts) >= 2:
            candidates.append(", ".join(parts[:2]))
        if parts:
            candidates.append(parts[0])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _photon_lookup(query: str) -> list[float] | None:
    """Query Komoot's public Photon instance (OSM-based, no API key).

    Returns [lat, lng] on success, None on any failure. We bypass the
    shared search_geocode() helper on purpose: it falls back to an
    airport-name token matcher on failure that confidently returns
    completely wrong coordinates, which poisoned the cache for years.
    """
    from urllib.parse import urlencode

    params = urlencode({"q": query, "limit": 1})
    url = f"https://photon.komoot.io/api?{params}"
    try:
        res = fetch_with_curl(
            url,
            headers={
                "User-Agent": "ShadowBroker-OSINT/1.0 (NUFORC-UAP-layer)",
                "Accept-Language": "en",
            },
            timeout=10,
        )
    except Exception:
        return None
    if not res or res.status_code != 200:
        return None
    try:
        payload = res.json()
    except Exception:
        return None
    features = (payload or {}).get("features") or []
    if not features:
        return None
    try:
        # GeoJSON order is [lng, lat] — flip to our [lat, lng] convention.
        coords = features[0]["geometry"]["coordinates"]
        return [float(coords[1]), float(coords[0])]
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _geocode_uap_location(
    location: str, city: str, state: str, country: str = ""
) -> list[float] | None:
    """Resolve a NUFORC sighting location to [lat, lng] via Photon.

    Returns None on failure. The caller caches None alongside real hits
    so we don't retry unresolvable queries every run.
    """
    for query in _uap_geocode_candidates(location, city, state, country):
        coords = _photon_lookup(query)
        if coords:
            return coords
    return None


def _build_uap_sighting_id(row: dict, occurred: str, location: str) -> str:
    raw_id = str(row.get("Sighting", "") or row.get("sighting", "")).strip()
    if raw_id:
        return raw_id
    digest = hashlib.sha1(
        f"{occurred}|{location}|{row.get('Summary', '')}|{row.get('Text', '')}".encode("utf-8", "ignore")
    ).hexdigest()[:12]
    return f"NUFORC-{digest}"


def _nuforc_months_for_window(days: int) -> list[str]:
    """Enumerate YYYYMM strings covering the rolling `days`-day window.

    Returned newest first. Always includes the current month even if the
    window technically starts later, because new reports land there.
    """
    today = datetime.utcnow().date()
    start = today - timedelta(days=days)
    months: list[str] = []
    cur = today.replace(day=1)
    start_floor = start.replace(day=1)
    while cur >= start_floor:
        months.append(cur.strftime("%Y%m"))
        if cur.month == 1:
            cur = cur.replace(year=cur.year - 1, month=12)
        else:
            cur = cur.replace(month=cur.month - 1)
    return months


def _nuforc_fetch_month_live(yyyymm: str, cookie_jar: Path) -> list[dict]:
    """Pull one month of NUFORC sightings via the live wpDataTables AJAX.

    Returns a list of raw row dicts with the fields we care about:
    id, occurred (YYYY-MM-DD), posted (YYYY-MM-DD), city, state, country,
    shape_raw, summary, explanation. Empty list on any failure — caller
    decides whether a failure is fatal.
    """
    from services.fetchers.nuforc_enrichment import _parse_date

    curl_bin = shutil.which("curl") or "curl"
    index_url = _NUFORC_LIVE_INDEX_URL.format(yyyymm=yyyymm)
    ajax_url = _NUFORC_LIVE_AJAX_URL.format(yyyymm=yyyymm)

    # Step 1: GET the month index to capture session cookies + fresh nonce.
    try:
        index_res = subprocess.run(
            [
                curl_bin, "-sL",
                "-A", _NUFORC_LIVE_USER_AGENT,
                "-c", str(cookie_jar),
                "-b", str(cookie_jar),
                index_url,
            ],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("NUFORC live: index fetch failed for %s: %s", yyyymm, e)
        return []
    if index_res.returncode != 0 or not index_res.stdout:
        logger.warning(
            "NUFORC live: index fetch exit=%s for %s", index_res.returncode, yyyymm,
        )
        return []
    nonce_match = _NUFORC_LIVE_NONCE_RE.search(index_res.stdout)
    if not nonce_match:
        logger.warning("NUFORC live: wdtNonce not found on index page for %s", yyyymm)
        return []
    nonce = nonce_match.group(1)

    # Step 2: POST to admin-ajax.php with length=-1 to pull the whole month.
    post_data = (
        "draw=1"
        "&columns%5B0%5D%5Bdata%5D=0&columns%5B0%5D%5Bsearchable%5D=true&columns%5B0%5D%5Borderable%5D=false"
        "&columns%5B1%5D%5Bdata%5D=1&columns%5B1%5D%5Bsearchable%5D=true&columns%5B1%5D%5Borderable%5D=true"
        "&order%5B0%5D%5Bcolumn%5D=1&order%5B0%5D%5Bdir%5D=desc"
        "&start=0&length=-1"
        "&search%5Bvalue%5D=&search%5Bregex%5D=false"
        f"&wdtNonce={nonce}"
    )
    try:
        ajax_res = subprocess.run(
            [
                curl_bin, "-sL",
                "-A", _NUFORC_LIVE_USER_AGENT,
                "-c", str(cookie_jar),
                "-b", str(cookie_jar),
                "-X", "POST",
                "-H", f"Referer: {index_url}",
                "-H", "X-Requested-With: XMLHttpRequest",
                "-H", "Content-Type: application/x-www-form-urlencoded",
                "--data", post_data,
                ajax_url,
            ],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("NUFORC live: ajax fetch failed for %s: %s", yyyymm, e)
        return []
    if ajax_res.returncode != 0 or not ajax_res.stdout:
        logger.warning(
            "NUFORC live: ajax fetch exit=%s for %s", ajax_res.returncode, yyyymm,
        )
        return []
    try:
        payload = json.loads(ajax_res.stdout)
    except json.JSONDecodeError as e:
        logger.warning("NUFORC live: ajax JSON decode failed for %s: %s", yyyymm, e)
        return []

    raw_rows = payload.get("data") or []
    out: list[dict] = []
    for raw in raw_rows:
        if not isinstance(raw, list) or len(raw) < 8:
            continue
        link_html = str(raw[0] or "")
        occurred_raw = str(raw[1] or "")
        city = str(raw[2] or "").strip()
        state = str(raw[3] or "").strip()
        country = str(raw[4] or "").strip()
        shape_raw = (str(raw[5] or "").strip() or "Unknown")
        summary = str(raw[6] or "").strip()
        reported_raw = str(raw[7] or "")
        explanation = str(raw[9] or "").strip() if len(raw) > 9 and raw[9] else ""

        occurred_ymd = _parse_date(occurred_raw)
        if not occurred_ymd:
            continue
        if not city and not state and not country:
            continue

        id_match = _NUFORC_LIVE_SIGHTING_ID_RE.search(link_html)
        if id_match:
            sighting_id = f"NUFORC-{id_match.group(1)}"
        else:
            digest = hashlib.sha1(
                f"{occurred_ymd}|{city}|{state}|{summary}".encode("utf-8", "ignore")
            ).hexdigest()[:12]
            sighting_id = f"NUFORC-{digest}"

        if summary and len(summary) > 280:
            summary = summary[:277] + "..."
        if not summary:
            summary = "Sighting reported"

        out.append({
            "id": sighting_id,
            "occurred": occurred_ymd,
            "posted": _parse_date(reported_raw) or occurred_ymd,
            "city": city,
            "state": state,
            "country": country,
            "shape_raw": shape_raw,
            "summary": summary,
            "explanation": explanation,
        })
    return out


def _build_recent_uap_sightings() -> list[dict]:
    """Build the rolling 1-year UAP sightings layer from live NUFORC data.

    Hits nuforc.org's public sub-index once per month in the window, drops
    anything outside the exact day-precision cutoff, dedupes by sighting id,
    geocodes city+state via the existing location cache, and returns rows
    keyed to the same schema the frontend already renders.
    """
    cutoff_dt = datetime.utcnow() - timedelta(days=_NUFORC_RECENT_DAYS)
    cutoff_str = cutoff_dt.strftime("%Y-%m-%d")
    months = _nuforc_months_for_window(_NUFORC_RECENT_DAYS)

    try:
        _NUFORC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    rows: list[dict] = []
    locations: dict[str, tuple[str, str]] = {}
    seen_ids: set[str] = set()
    total_pulled = 0
    months_with_data = 0

    for yyyymm in months:
        month_rows = _nuforc_fetch_month_live(yyyymm, _NUFORC_LIVE_SESSION_COOKIES)
        if month_rows:
            months_with_data += 1
        total_pulled += len(month_rows)
        for row in month_rows:
            if row["occurred"] < cutoff_str:
                continue
            if row["id"] in seen_ids:
                continue
            seen_ids.add(row["id"])

            # Build the geocode key as "City, State, Country" to match the
            # existing 3,000+ entry location cache (format: "Toronto, ON, Canada").
            parts = [row["city"], row["state"], row["country"]]
            location = _normalize_uap_location(
                ", ".join(p for p in parts if p) if any(parts) else ""
            )
            if not location:
                continue

            row["location"] = location
            locations.setdefault(location, (row["city"], row["state"], row["country"]))
            row["shape"] = (
                _normalize_uap_shape(row["shape_raw"])
                if row["shape_raw"] != "Unknown"
                else "unknown"
            )
            if not row["country"]:
                row["country"] = _uap_country_from_location(location, row["state"])
            rows.append(row)

    # Clean up the cookie jar — we don't reuse it across runs.
    try:
        if _NUFORC_LIVE_SESSION_COOKIES.exists():
            _NUFORC_LIVE_SESSION_COOKIES.unlink()
    except Exception:
        pass

    # Source-integrity canary: if the upstream plugin changed its
    # DataTables schema or the wdtNonce regex is stale, total_pulled
    # collapses to ~0 without any HTTP error. assert_canary logs a loud
    # ERROR so the failure is visible in the health registry and the
    # daily refresh log, instead of silently serving a stale cache.
    from services.slo import assert_canary
    assert_canary("uap_sightings", total_pulled)

    if not rows:
        raise RuntimeError(
            f"NUFORC live: zero rows pulled across {len(months)} months "
            f"(months_with_data={months_with_data})"
        )

    from services.geocode_validate import coord_in_country

    location_cache = _load_nuforc_location_cache()
    missing_locations = [location for location in locations if location not in location_cache]
    if missing_locations:
        logger.info(
            "UAP sightings: geocoding %d new locations (throttled at %.1fs spacing)",
            len(missing_locations),
            _NUFORC_GEOCODE_SPACING_S,
        )
        # Sequential with spacing — Photon is fast and lenient but we
        # stay sub-second to be polite. Incremental cache saves every 50
        # hits keep long runs resumable.
        resolved = 0
        bbox_rejected = 0
        save_every = 50
        for idx, location in enumerate(missing_locations):
            city, state, country = locations[location]
            coords = None
            try:
                coords = _geocode_uap_location(location, city, state, country)
            except Exception:
                coords = None

            # Country-bbox post-filter: reject namesake collisions like
            # "Milan, WI" landing in Milan, Italy. Unknown countries
            # (bbox not registered) are passed through unchanged.
            if coords and country:
                inside = coord_in_country(coords[0], coords[1], country)
                if inside is False:
                    logger.warning(
                        "UAP sightings: bbox reject %r -> (%.3f, %.3f) not in %s",
                        location, coords[0], coords[1], country,
                    )
                    coords = None
                    bbox_rejected += 1

            location_cache[location] = coords
            if coords:
                resolved += 1

            if (idx + 1) % save_every == 0:
                _save_nuforc_location_cache(location_cache)
                logger.info(
                    "UAP sightings: geocoded %d/%d (%d resolved, %d bbox-rejected)",
                    idx + 1, len(missing_locations), resolved, bbox_rejected,
                )
            if idx + 1 < len(missing_locations):
                time.sleep(_NUFORC_GEOCODE_SPACING_S)
        _save_nuforc_location_cache(location_cache)
        logger.info(
            "UAP sightings: geocoding complete — %d/%d resolved, %d bbox-rejected",
            resolved, len(missing_locations), bbox_rejected,
        )

    sightings: list[dict] = []
    skipped_unmapped = 0
    skipped_bbox = 0
    for row in rows:
        coords = location_cache.get(row["location"])
        if not coords:
            skipped_unmapped += 1
            continue
        # Apply bbox filter to pre-existing cache entries too — this
        # cleans up the ~1-2% of cached coords that pre-dated the bbox
        # check without requiring a full cache rebuild.
        if row.get("country"):
            inside = coord_in_country(coords[0], coords[1], row["country"])
            if inside is False:
                skipped_bbox += 1
                continue
        sightings.append(
            {
                "id": row["id"],
                "date_time": row["occurred"],
                "city": row["city"],
                "state": row["state"],
                "country": row["country"],
                "shape": row["shape"],
                "shape_raw": row["shape_raw"],
                "duration": row.get("duration", ""),
                "summary": row["summary"],
                "posted": row["posted"],
                "lat": float(coords[0]),
                "lng": float(coords[1]),
                "count": 1,
                "source": "NUFORC",
            }
        )
        if row.get("explanation"):
            sightings[-1]["explanation"] = row["explanation"]

    sightings.sort(
        key=lambda sighting: (
            sighting.get("date_time", ""),
            sighting.get("posted", ""),
            str(sighting.get("id", "")),
        ),
        reverse=True,
    )
    logger.info(
        "UAP sightings: %d mapped reports from %d rows across %d months "
        "(cutoff %s, %d unmapped, %d bbox-rejected)",
        len(sightings),
        total_pulled,
        len(months),
        cutoff_str,
        skipped_unmapped,
        skipped_bbox,
    )
    return sightings


@with_retry(max_retries=1, base_delay=5)
def fetch_uap_sightings(*, force_refresh: bool = False):
    """Fetch last-year UAP sightings from NUFORC.

    Startup reads the cached daily snapshot when it is still fresh. The daily
    scheduler forces a rebuild so this layer updates once per day instead of
    churning continuously.
    """
    from services.fetchers._store import is_any_active

    if not is_any_active("uap_sightings"):
        return

    sightings = _load_nuforc_sightings_cache(force_refresh=force_refresh)
    if sightings is None:
        sightings = _build_recent_uap_sightings()
        _save_nuforc_sightings_cache(sightings)

    with _data_lock:
        latest_data["uap_sightings"] = sightings
    _mark_fresh("uap_sightings")
    return

    cutoff = datetime.utcnow() - timedelta(days=_NUFORC_RECENT_DAYS)

    # Query the grid concurrently (up to 8 threads)
    all_features: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_fetch_nuforc_tilequery, lng, lat): (lng, lat)
            for lng, lat in _TILEQUERY_GRID
        }
        for fut in concurrent.futures.as_completed(futures, timeout=60):
            try:
                all_features.extend(fut.result())
            except Exception:
                pass

    # Deduplicate by (LinkLat, LinkLon) and filter to recent sightings
    seen: set[tuple[str, str]] = set()
    sightings: list[dict] = []
    enriched_count = 0
    for feat in all_features:
        props = feat.get("properties", {})
        link_lat = props.get("LinkLat", "")
        link_lon = props.get("LinkLon", "")
        if not link_lat or not link_lon:
            continue

        key = (link_lat, link_lon)
        if key in seen:
            continue
        seen.add(key)

        # Filter by date — keep if the latest sighting date >= cutoff
        to_date = props.get("To", "")
        from_date = props.get("From", "")
        latest_date = to_date or from_date
        latest_dt = _parse_nuforc_tile_date(latest_date)
        if latest_dt is not None and latest_dt < cutoff:
            continue

        try:
            lat = float(link_lat)
            lng = float(link_lon)
        except (ValueError, TypeError):
            continue

        count = int(props.get("Count", "1") or "1")
        state_abbr, country = _reverse_geocode_state(lat, lng)

        # Enrich with HF NUFORC dataset (shape, duration, city, summary)
        enrichment = enrich_sighting(state_abbr, from_date, to_date)
        city = enrichment.get("city", "")
        shape_raw = enrichment.get("shape_raw", "Unknown")
        shape = _normalize_uap_shape(shape_raw) if shape_raw != "Unknown" else "unknown"
        duration = enrichment.get("duration", "")
        summary = enrichment.get("summary", "")
        if enrichment:
            enriched_count += 1

        # Build display summary: prefer enriched text, fall back to count-based
        if not summary:
            summary = f"{count} sighting(s) reported" if count > 1 else "Sighting reported"

        sightings.append({
            "id": f"NUFORC-{hash(key) & 0xFFFFFFFF:08x}",
            "date_time": from_date if from_date == to_date else f"{from_date} to {to_date}",
            "city": city,
            "state": state_abbr,
            "country": country,
            "shape": shape,
            "shape_raw": shape_raw,
            "duration": duration,
            "summary": summary,
            "posted": to_date,
            "lat": lat,
            "lng": lng,
            "count": count,
            "source": "NUFORC",
        })

    logger.info(
        f"UAP sightings: {len(sightings)} recent from NUFORC tilequery "
        f"({len(all_features)} raw, {enriched_count} enriched)"
    )

    with _data_lock:
        latest_data["uap_sightings"] = sightings
    if sightings:
        _mark_fresh("uap_sightings")
