"""Earth-observation fetchers — earthquakes, FIRMS fires, space weather, weather radar,
severe weather alerts, air quality, volcanoes."""

import csv
import io
import json
import logging
import os
import time
import heapq
from datetime import datetime
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
