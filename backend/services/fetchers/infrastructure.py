"""Infrastructure fetchers — internet outages (IODA), data centers, CCTV, KiwiSDR, Ethereum nodes."""
import json
import os
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
    except Exception:
        pass
    _region_geocode_cache[cache_key] = None
    return None


@with_retry(max_retries=1, base_delay=1)
def fetch_internet_outages():
    """Fetch regional internet outage alerts from IODA (Georgia Tech)."""
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
    except Exception as e:
        logger.error(f"Error fetching internet outages: {e}")
    with _data_lock:
        latest_data["internet_outages"] = outages
    if outages:
        _mark_fresh("internet_outages")


# ---------------------------------------------------------------------------
# Data Centers (local geocoded JSON)
# ---------------------------------------------------------------------------
_DC_GEOCODED_PATH = Path(__file__).parent.parent.parent / "data" / "datacenters_geocoded.json"


def fetch_datacenters():
    """Load geocoded data centers (5K+ street-level precise locations)."""
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
            dcs.append({
                "name": entry.get("name", "Unknown"),
                "company": entry.get("company", ""),
                "street": entry.get("street", ""),
                "city": entry.get("city", ""),
                "country": entry.get("country", ""),
                "zip": entry.get("zip", ""),
                "lat": lat, "lng": lng,
            })
        logger.info(f"Data centers: {len(dcs)} geocoded locations loaded")
    except Exception as e:
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
# CCTV Cameras
# ---------------------------------------------------------------------------
def fetch_cctv():
    try:
        from services.cctv_pipeline import get_all_cameras
        cameras = get_all_cameras()
        with _data_lock:
            latest_data["cctv"] = cameras
        _mark_fresh("cctv")
    except Exception as e:
        logger.error(f"Error fetching cctv from DB: {e}")
        with _data_lock:
            latest_data["cctv"] = []


# ---------------------------------------------------------------------------
# KiwiSDR Receivers
# ---------------------------------------------------------------------------
@with_retry(max_retries=2, base_delay=2)
def fetch_kiwisdr():
    try:
        from services.kiwisdr_fetcher import fetch_kiwisdr_nodes
        nodes = fetch_kiwisdr_nodes()
        with _data_lock:
            latest_data["kiwisdr"] = nodes
        _mark_fresh("kiwisdr")
    except Exception as e:
        logger.error(f"Error fetching KiwiSDR nodes: {e}")
        with _data_lock:
            latest_data["kiwisdr"] = []


# ---------------------------------------------------------------------------
# Ethereum Nodes (Shodan — port:30303)
# ---------------------------------------------------------------------------
@with_retry(max_retries=1, base_delay=2)
def fetch_eth_nodes():
    """Fetch Ethereum nodes from Shodan (port:30303)."""
    api_key = os.environ.get("SHODAN_API_KEY", "")
    if not api_key:
        logger.debug("SHODAN_API_KEY not set — skipping Ethereum nodes")
        return

    nodes = []
    max_pages = 5  # 500 nodes max, 5 credits per fetch cycle
    for page in range(1, max_pages + 1):
        url = f"https://api.shodan.io/shodan/host/search?key={api_key}&query=port:30303&page={page}"
        response = fetch_with_curl(url, timeout=15)
        if response.status_code != 200:
            break
        data = response.json()
        for match in data.get("matches", []):
            loc = match.get("location", {})
            lat = loc.get("latitude")
            lng = loc.get("longitude")
            if lat is None or lng is None:
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            nodes.append({
                "ip": match.get("ip_str", ""),
                "port": match.get("port", 30303),
                "country": loc.get("country_code", ""),
                "city": loc.get("city", ""),
                "lat": lat,
                "lng": lng,
                "org": match.get("org", ""),
                "isp": match.get("isp", ""),
                "asn": match.get("asn", ""),
                "os": match.get("os", ""),
            })
        if len(data.get("matches", [])) < 100:
            break  # Last page

    with _data_lock:
        latest_data["eth_nodes"] = nodes
    if nodes:
        _mark_fresh("eth_nodes")
    logger.info(f"Ethereum nodes: {len(nodes)} found via Shodan")
