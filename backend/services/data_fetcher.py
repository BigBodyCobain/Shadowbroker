import yfinance as yf
import feedparser
import requests
import logging
from services.network_utils import fetch_with_curl
import csv
import os
import re
import random
import math
import json
import time
import threading
import io
from apscheduler.schedulers.background import BackgroundScheduler
import concurrent.futures
from sgp4.api import Satrec, WGS72
from sgp4.api import jday
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
from services.cctv_pipeline import init_db, TFLJamCamIngestor, LTASingaporeIngestor, AustinTXIngestor, NYCDOTIngestor, get_all_cameras

logger = logging.getLogger(__name__)

def _gmst(jd_ut1):
    """Greenwich Mean Sidereal Time in radians from Julian Date."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    gmst_sec = 67310.54841 + (876600.0 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t * t * t
    gmst_rad = (gmst_sec % 86400) / 86400.0 * 2 * math.pi
    return gmst_rad

# Pre-compiled regex patterns for airline code extraction (used in hot loop)
_RE_AIRLINE_CODE_1 = re.compile(r'^([A-Z]{3})\d')
_RE_AIRLINE_CODE_2 = re.compile(r'^([A-Z]{3})[A-Z\d]')


# ---------------------------------------------------------------------------
# OpenSky Network API Client (OAuth2)
# ---------------------------------------------------------------------------
class OpenSkyClient:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self.expires_at = 0

    def get_token(self):
        import time
        if self.token and time.time() < self.expires_at - 60:
            return self.token
        
        url = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        try:
            r = requests.post(url, data=data, timeout=10)
            if r.status_code == 200:
                res = r.json()
                self.token = res.get("access_token")
                self.expires_at = time.time() + res.get("expires_in", 1800)
                logger.info("OpenSky OAuth2 token refreshed.")
                return self.token
            else:
                logger.error(f"OpenSky Auth Failed: {r.status_code} {r.text}")
        except Exception as e:
            logger.error(f"OpenSky Auth Exception: {e}")
        return None

# User provided credentials
opensky_client = OpenSkyClient(
    client_id=os.environ.get("OPENSKY_CLIENT_ID", ""),
    client_secret=os.environ.get("OPENSKY_CLIENT_SECRET", "")
)

# Throttling and caching for OpenSky to observe the 400 req/day limit
last_opensky_fetch = 0
cached_opensky_flights = []



# In-memory store
latest_data = {
    "last_updated": None,
    "news": [],
    "stocks": {},
    "oil": {},
    "flights": [],
    "ships": [],
    "military_flights": [],
    "tracked_flights": [],
    "cctv": [],
    "weather": None,
    # bikeshare removed per user request
    "traffic": [],
    "earthquakes": [],
    "uavs": [],
    "frontlines": None,
    "gdelt": [],
    "liveuamap": []
}

# Thread lock for safe reads/writes to latest_data
_data_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Plane-Alert DB — load tracked aircraft from CSV on startup
# ---------------------------------------------------------------------------

# Category → color mapping
_PINK_CATEGORIES = {
    "Dictator Alert", "Head of State", "Da Comrade", "Oligarch",
    "Governments", "Royal Aircraft", "Quango",
}
_RED_CATEGORIES = {
    "Don't you know who I am?", "As Seen on TV", "Joe Cool",
    "Vanity Plate", "Football", "Bizjets",
}
_DARKBLUE_CATEGORIES = {
    "USAF", "United States Navy", "United States Marine Corps",
    "Special Forces", "Hired Gun", "Oxcart", "Gunship", "Nuclear",
    "CAP", "Zoomies",
}

def _category_to_color(cat: str) -> str:
    if cat in _PINK_CATEGORIES:
        return "pink"
    if cat in _RED_CATEGORIES:
        return "red"
    if cat in _DARKBLUE_CATEGORIES:
        return "darkblue"
    return "white"

# Load once on module import
_PLANE_ALERT_DB: dict = {}  # uppercase ICAO hex → dict of aircraft info

def _load_plane_alert_db():
    """Parse plane_alert_db.json into a dict keyed by uppercase ICAO hex."""
    global _PLANE_ALERT_DB
    import json
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "plane_alert_db.json"
    )
    if not os.path.exists(json_path):
        logger.warning(f"Plane-Alert JSON DB not found at {json_path}")
        return
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            for icao_hex, info in data.items():
                info["color"] = _category_to_color(info.get("category", ""))
                _PLANE_ALERT_DB[icao_hex] = info
        logger.info(f"Plane-Alert JSON DB loaded: {len(_PLANE_ALERT_DB)} aircraft")
    except Exception as e:
        logger.error(f"Failed to load Plane-Alert JSON DB: {e}")

_load_plane_alert_db()

def enrich_with_plane_alert(flight: dict) -> dict:
    """If flight's icao24 is in the Plane-Alert DB, add alert metadata."""
    icao = flight.get("icao24", "").strip().upper()
    if icao and icao in _PLANE_ALERT_DB:
        info = _PLANE_ALERT_DB[icao]
        flight["alert_category"] = info["category"]
        flight["alert_color"] = info["color"]
        flight["alert_operator"] = info["operator"]
        flight["alert_type"] = info["ac_type"]
        flight["alert_tag1"] = info["tag1"]
        flight["alert_tag2"] = info["tag2"]
        flight["alert_tag3"] = info["tag3"]
        flight["alert_link"] = info["link"]
        # Override registration if DB has a better one
        if info["registration"]:
            flight["registration"] = info["registration"]

    return flight

# (json imported at module top)
_TRACKED_NAMES_DB: dict = {} # Map from uppercase registration to {name, category}

def _load_tracked_names():
    global _TRACKED_NAMES_DB
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "tracked_names.json"
    )
    if not os.path.exists(json_path):
        return
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # data has:
            # "names": [ {"name": "...", "category": "..."} ]
            # "details": { "Name": { "category": "...", "registrations": ["..."] } }
            for name, info in data.get("details", {}).items():
                cat = info.get("category", "Other")
                for reg in info.get("registrations", []):
                    reg_clean = reg.strip().upper()
                    if reg_clean:
                        _TRACKED_NAMES_DB[reg_clean] = {"name": name, "category": cat}
        logger.info(f"Tracked Names DB loaded: {len(_TRACKED_NAMES_DB)} registrations")
    except Exception as e:
        logger.error(f"Failed to load Tracked Names DB: {e}")

_load_tracked_names()

def enrich_with_tracked_names(flight: dict) -> dict:
    """If flight's registration matches our Excel extraction, tag it as tracked."""
    reg = flight.get("registration", "").strip().upper()
    callsign = flight.get("callsign", "").strip().upper()
    
    match = None
    if reg and reg in _TRACKED_NAMES_DB:
        match = _TRACKED_NAMES_DB[reg]
    elif callsign and callsign in _TRACKED_NAMES_DB:
        match = _TRACKED_NAMES_DB[callsign]
        
    if match:
        # Don't overwrite Plane-Alert DB operator if it exists unless we want Excel to take precedence.
        # Let's let Excel take precedence as it has cleaner individual names (e.g. Elon Musk instead of FALCON LANDING LLC).
        flight["alert_operator"] = match["name"]
        flight["alert_category"] = match["category"]
        if "alert_color" not in flight:
            flight["alert_color"] = "pink"

    return flight


def generate_machine_assessment(title, description, risk_score):
    if risk_score < 8:
        return None
        
    import random
    keywords = [word.lower() for word in title.split() + description.split()]
    
    assessment = "ANALYSIS: "
    if any(k in keywords for k in ["strike", "missile", "attack", "bomb", "drone"]):
        assessment += f"{random.randint(75, 95)}% probability of kinetic escalation within 24 hours. Recommend immediate asset relocation from projected blast radius."
    elif any(k in keywords for k in ["sanction", "trade", "economy", "tariff", "boycott"]):
        assessment += f"Significant economic severing detected. {random.randint(60, 85)}% chance of reciprocal sanctions. Global supply chains may experience cascading latency."
    elif any(k in keywords for k in ["cyber", "hack", "breach", "ddos", "ransomware"]):
        assessment += f"Asymmetric digital warfare signature matched. {random.randint(80, 99)}% probability of infrastructure probing. Initiate air-gapping protocol for critical nodes."
    elif any(k in keywords for k in ["troop", "deploy", "border", "navy", "carrier"]):
        assessment += f"Force projection detected. {random.randint(70, 90)}% probability of theater escalation. Monitor adjacent maritime and airspace for mobilization."
    else:
        assessment += f"Anomalous geopolitical shift detected. Confidence interval {random.randint(60, 90)}%. Awaiting further signals intelligence for definitive vector."
        
    return assessment

# ---------------------------------------------------------------------------
# Keyword → coordinate mapping for geocoding news articles
# ---------------------------------------------------------------------------
_KEYWORD_COORDS = {
    "venezuela": (7.119, -66.589),
    "brazil": (-14.235, -51.925),
    "argentina": (-38.416, -63.616),
    "colombia": (4.570, -74.297),
    "mexico": (23.634, -102.552),
    "united states": (38.907, -77.036),
    " usa ": (38.907, -77.036),
    " us ": (38.907, -77.036),
    "washington": (38.907, -77.036),
    "canada": (56.130, -106.346),
    "ukraine": (49.487, 31.272),
    "kyiv": (50.450, 30.523),
    "russia": (61.524, 105.318),
    "moscow": (55.755, 37.617),
    "israel": (31.046, 34.851),
    "gaza": (31.416, 34.333),
    "iran": (32.427, 53.688),
    "lebanon": (33.854, 35.862),
    "syria": (34.802, 38.996),
    "yemen": (15.552, 48.516),
    "china": (35.861, 104.195),
    "beijing": (39.904, 116.407),
    "taiwan": (23.697, 120.960),
    "north korea": (40.339, 127.510),
    "south korea": (35.907, 127.766),
    "pyongyang": (39.039, 125.762),
    "seoul": (37.566, 126.978),
    "japan": (36.204, 138.252),
    "tokyo": (35.676, 139.650),
    "afghanistan": (33.939, 67.709),
    "pakistan": (30.375, 69.345),
    "india": (20.593, 78.962),
    " uk ": (55.378, -3.435),
    "london": (51.507, -0.127),
    "france": (46.227, 2.213),
    "paris": (48.856, 2.352),
    "germany": (51.165, 10.451),
    "berlin": (52.520, 13.405),
    "sudan": (12.862, 30.217),
    "congo": (-4.038, 21.758),
    "south africa": (-30.559, 22.937),
    "nigeria": (9.082, 8.675),
    "egypt": (26.820, 30.802),
    "zimbabwe": (-19.015, 29.154),
    "kenya": (-1.292, 36.821),
    "libya": (26.335, 17.228),
    "mali": (17.570, -3.996),
    "niger": (17.607, 8.081),
    "somalia": (5.152, 46.199),
    "ethiopia": (9.145, 40.489),
    "australia": (-25.274, 133.775),
    "middle east": (31.500, 34.800),
    "europe": (48.800, 2.300),
    "africa": (0.000, 25.000),
    "america": (38.900, -77.000),
    "south america": (-14.200, -51.900),
    "asia": (34.000, 100.000),
    "california": (36.778, -119.417),
    "texas": (31.968, -99.901),
    "florida": (27.994, -81.760),
    "new york": (40.712, -74.006),
    "virginia": (37.431, -78.656),
    "british columbia": (53.726, -127.647),
    "ontario": (51.253, -85.323),
    "quebec": (52.939, -73.549),
    "delhi": (28.704, 77.102),
    "new delhi": (28.613, 77.209),
    "mumbai": (19.076, 72.877),
    "shanghai": (31.230, 121.473),
    "hong kong": (22.319, 114.169),
    "istanbul": (41.008, 28.978),
    "dubai": (25.204, 55.270),
    "singapore": (1.352, 103.819),
    "bangkok": (13.756, 100.501),
    "jakarta": (-6.208, 106.845),
}

def fetch_news():
    feeds = {
        "NPR": "https://feeds.npr.org/1004/rss.xml",
        "BBC": "http://feeds.bbci.co.uk/news/world/rss.xml",
        "AlJazeera": "https://www.aljazeera.com/xml/rss/all.xml",
        "NYT": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "GDACS": "https://www.gdacs.org/xml/rss.xml",
        "NHK": "https://www3.nhk.or.jp/nhkworld/rss/world.xml",
        "CNA": "https://www.channelnewsasia.com/rssfeed/8395986",
        "Mercopress": "https://en.mercopress.com/rss/"
    }
    source_weights = {
        "NPR": 4, "BBC": 3, "AlJazeera": 2, "NYT": 1, 
        "GDACS": 5, "NHK": 3, "CNA": 3, "Mercopress": 3
    }
    
    clusters = {}
    
    # Fetch all feeds in parallel for speed (each has a 10s timeout)
    def _fetch_feed(item):
        source_name, url = item
        try:
            xml_data = fetch_with_curl(url, timeout=10).text
            return source_name, feedparser.parse(xml_data)
        except Exception as e:
            logger.warning(f"Feed {source_name} failed: {e}")
            return source_name, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(feeds)) as pool:
        feed_results = list(pool.map(_fetch_feed, feeds.items()))

    for source_name, feed in feed_results:
        if not feed:
            continue
        for entry in feed.entries[:5]:
            title = entry.get('title', '')
            summary = entry.get('summary', '')
            
            # Filter out Earthquakes/seismic events (redundant with dedicated EQ layer)
            _seismic_kw = ["earthquake", "seismic", "quake", "tremor", "magnitude", "richter"]
            _text_lower = (title + " " + summary).lower()
            if any(kw in _text_lower for kw in _seismic_kw):
                continue
            
            # GDACS-specific risk score mapping
            if source_name == "GDACS":
                alert_level = entry.get("gdacs_alertlevel", "Green")
                if alert_level == "Red": risk_score = 10
                elif alert_level == "Orange": risk_score = 7
                else: risk_score = 4
            else:
                risk_keywords = ['war', 'missile', 'strike', 'attack', 'crisis', 'tension', 'military', 'conflict', 'defense', 'clash', 'nuclear']
                text = (title + " " + summary).lower()
                
                risk_score = 1
                for kw in risk_keywords:
                    if kw in text:
                        risk_score += 2
                
                risk_score = min(10, risk_score)
            
            
            keyword_coords = _KEYWORD_COORDS
            
            lat, lng = None, None
            
            # Try GeoRSS Extraction first (common in GDACS)
            if 'georss_point' in entry:
                geo_parts = entry['georss_point'].split()
                if len(geo_parts) == 2:
                    lat, lng = float(geo_parts[0]), float(geo_parts[1])
            elif 'where' in entry and hasattr(entry['where'], 'coordinates'):
                # Some feeds use the 'where' attribute
                coords = entry['where'].coordinates
                lat, lng = coords[1], coords[0] # Usually lon, lat in GeoJSON style points
            
            # Fallback to Keyword Mapping
            if lat is None:
                padded_text = f" {text} "
                for kw, coords in keyword_coords.items():
                    if kw.startswith(" ") or kw.endswith(" "):
                        if kw in padded_text:
                            lat, lng = coords
                            break
                    else:
                        if re.search(r'\b' + re.escape(kw) + r'\b', text):
                            lat, lng = coords
                            break
                        
            # If mapped, check if there is an existing cluster within ~400km (4 degrees) to merge them
            if lat is not None:
                key = None
                for existing_key in clusters.keys():
                    if "," in existing_key:
                        parts = existing_key.split(",")
                        try:
                            elat, elng = float(parts[0]), float(parts[1])
                            if ((lat - elat)**2 + (lng - elng)**2)**0.5 < 4.0:
                                key = existing_key
                                break
                        except ValueError:
                            pass
                if key is None:
                    key = f"{lat},{lng}"
            else:
                key = title
                
            if key not in clusters:
                clusters[key] = []
                
            clusters[key].append({
                "title": title,
                "link": entry.get('link', ''),
                "published": entry.get('published', ''),
                "source": source_name,
                "risk_score": risk_score,
                "coords": [lat, lng] if lat is not None else None
            })
            
            
    news_items = []
    for key, articles in clusters.items():
        # Sort internal articles primarily by risk score (highest first), then by source hierarchy
        articles.sort(key=lambda x: (x['risk_score'], source_weights.get(x["source"], 0)), reverse=True)
        max_risk = articles[0]['risk_score']
        
        top_article = articles[0]
        news_items.append({
            "title": top_article["title"],
            "link": top_article["link"],
            "published": top_article["published"],
            "source": top_article["source"],
            "risk_score": max_risk,
            "coords": top_article["coords"],
            "cluster_count": len(articles),
            "articles": articles,
            "machine_assessment": generate_machine_assessment(top_article["title"], "", max_risk)
        })

    news_items.sort(key=lambda x: x['risk_score'], reverse=True)
    latest_data['news'] = news_items

def fetch_defense_stocks():
    tickers = ["RTX", "LMT", "NOC", "GD", "BA", "PLTR"]
    stocks_data = {}
    try:
        for t in tickers:
            try:
                ticker = yf.Ticker(t)
                hist = ticker.history(period="2d")
                if len(hist) >= 1:
                    current_price = hist['Close'].iloc[-1]
                    prev_close = hist['Close'].iloc[0] if len(hist) > 1 else current_price
                    change_percent = ((current_price - prev_close) / prev_close) * 100 if prev_close else 0
                    
                    stocks_data[t] = {
                        "price": round(float(current_price), 2),
                        "change_percent": round(float(change_percent), 2),
                        "up": bool(change_percent >= 0)
                    }
            except Exception as e:
                logger.warning(f"Could not fetch data for {t}: {e}")
                
        latest_data['stocks'] = stocks_data
    except Exception as e:
        logger.error(f"Error fetching stocks: {e}")

def fetch_oil_prices():
    # CL=F is Crude Oil, BZ=F is Brent Crude
    tickers = {"WTI Crude": "CL=F", "Brent Crude": "BZ=F"}
    oil_data = {}
    try:
        for name, symbol in tickers.items():
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d")
                if len(hist) >= 2:
                    current_price = hist['Close'].iloc[-1]
                    prev_close = hist['Close'].iloc[-2]
                    change_percent = ((current_price - prev_close) / prev_close) * 100 if prev_close else 0
                    
                    oil_data[name] = {
                        "price": round(float(current_price), 2),
                        "change_percent": round(float(change_percent), 2),
                        "up": bool(change_percent >= 0)
                    }
            except Exception as e:
                logger.warning(f"Could not fetch data for {symbol}: {e}")
                
        latest_data['oil'] = oil_data
    except Exception as e:
        logger.error(f"Error fetching oil: {e}")

dynamic_routes_cache = {}  # callsign -> {data..., _ts: timestamp}
routes_fetch_in_progress = False
ROUTES_CACHE_TTL = 7200  # 2 hours
ROUTES_CACHE_MAX = 5000

def fetch_routes_background(sampled):
    global dynamic_routes_cache, routes_fetch_in_progress
    if routes_fetch_in_progress:
        return
    routes_fetch_in_progress = True
    
    try:
        # Prune stale entries (older than 2 hours) and cap at max size
        now_ts = time.time()
        stale_keys = [k for k, v in dynamic_routes_cache.items() if now_ts - v.get('_ts', 0) > ROUTES_CACHE_TTL]
        for k in stale_keys:
            del dynamic_routes_cache[k]
        if len(dynamic_routes_cache) > ROUTES_CACHE_MAX:
            # Remove oldest entries
            sorted_keys = sorted(dynamic_routes_cache, key=lambda k: dynamic_routes_cache[k].get('_ts', 0))
            for k in sorted_keys[:len(dynamic_routes_cache) - ROUTES_CACHE_MAX]:
                del dynamic_routes_cache[k]

        callsigns_to_query = []
        for f in sampled:
            c_sign = str(f.get("flight", "")).strip()
            if c_sign and c_sign != "UNKNOWN":
                callsigns_to_query.append({
                    "callsign": c_sign,
                    "lat": f.get("lat", 0),
                    "lng": f.get("lon", 0)
                })
        
        batch_size = 100
        batches = [callsigns_to_query[i:i+batch_size] for i in range(0, len(callsigns_to_query), batch_size)]
        
        for batch in batches:
            try:
                r = fetch_with_curl("https://api.adsb.lol/api/0/routeset", method="POST", json_data={"planes": batch}, timeout=15)
                if r.status_code == 200:
                    route_data = r.json()
                    route_list = []
                    if isinstance(route_data, dict):
                        route_list = route_data.get("value", [])
                    elif isinstance(route_data, list):
                        route_list = route_data
                        
                    for route in route_list:
                        callsign = route.get("callsign", "")
                        airports = route.get("_airports", [])
                        if airports and len(airports) >= 2:
                            orig_apt = airports[0]
                            dest_apt = airports[-1]
                            dynamic_routes_cache[callsign] = {
                                "orig_name": f"{orig_apt.get('iata', '')}: {orig_apt.get('name', 'Unknown')}",
                                "dest_name": f"{dest_apt.get('iata', '')}: {dest_apt.get('name', 'Unknown')}",
                                "orig_loc": [orig_apt.get("lon", 0), orig_apt.get("lat", 0)],
                                "dest_loc": [dest_apt.get("lon", 0), dest_apt.get("lat", 0)],
                                "_ts": time.time(),
                            }
                time.sleep(0.25) # Throttle strictly beneath 10 requests / second limit
            except Exception:
                pass
    finally:
        routes_fetch_in_progress = False

# Helicopter type codes (backend classification)
_HELI_TYPES_BACKEND = {
    "R22", "R44", "R66", "B06", "B06T", "B204", "B205", "B206", "B212", "B222", "B230",
    "B407", "B412", "B427", "B429", "B430", "B505", "B525",
    "AS32", "AS35", "AS50", "AS55", "AS65",
    "EC20", "EC25", "EC30", "EC35", "EC45", "EC55", "EC75",
    "H125", "H130", "H135", "H145", "H155", "H160", "H175", "H215", "H225",
    "S55", "S58", "S61", "S64", "S70", "S76", "S92",
    "A109", "A119", "A139", "A169", "A189", "AW09",
    "MD52", "MD60", "MDHI", "MD90", "NOTR",
    "B47G", "HUEY", "GAMA", "CABR", "EXE",
}

def fetch_flights():
    # OpenSky Network public API for flights. We want to demonstrate global coverage.
    flights = []
    try:
        # Sample flights from North America, Europe, Asia
        regions = [
            {"lat": 39.8, "lon": -98.5, "dist": 2000},  # USA
            {"lat": 50.0, "lon": 15.0, "dist": 2000},   # Europe
            {"lat": 35.0, "lon": 105.0, "dist": 2000},  # Asia / China
            {"lat": -25.0, "lon": 133.0, "dist": 2000}, # Australia
            {"lat": 0.0, "lon": 20.0, "dist": 2500},    # Africa
            {"lat": -15.0, "lon": -60.0, "dist": 2000}  # South America
        ]
        
        all_adsb_flights = []

        # Fetch all regions in parallel for ~5x speedup
        def _fetch_region(r):
            url = f"https://api.adsb.lol/v2/lat/{r['lat']}/lon/{r['lon']}/dist/{r['dist']}"
            try:
                res = fetch_with_curl(url, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    return data.get("ac", [])
            except Exception as e:
                logger.warning(f"Region fetch failed for lat={r['lat']}: {e}")
            return []

        # Fetch all regions in parallel for maximum speed
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = pool.map(_fetch_region, regions)
        for region_flights in results:
            all_adsb_flights.extend(region_flights)

        # ---------------------------------------------------------------------------
        # OpenSky Regional Fallback (Africa, Asia, South America)
        # ---------------------------------------------------------------------------
        now = time.time()
        global last_opensky_fetch, cached_opensky_flights
        
        # OpenSky has a 400 req/day limit (~16 pings/hour)
        # 5 minutes = 288 pings/day (Safe margin)
        if now - last_opensky_fetch > 300:
            token = opensky_client.get_token()
            if token:
                opensky_regions = [
                    {"name": "Africa", "bbox": {"lamin": -35.0, "lomin": -20.0, "lamax": 38.0, "lomax": 55.0}},
                    {"name": "Asia", "bbox": {"lamin": 0.0, "lomin": 30.0, "lamax": 75.0, "lomax": 150.0}},
                    {"name": "South America", "bbox": {"lamin": -60.0, "lomin": -95.0, "lamax": 15.0, "lomax": -30.0}}
                ]
                
                new_opensky_flights = []
                for os_reg in opensky_regions:
                    try:
                        bb = os_reg["bbox"]
                        os_url = f"https://opensky-network.org/api/states/all?lamin={bb['lamin']}&lomin={bb['lomin']}&lamax={bb['lamax']}&lomax={bb['lomax']}"
                        headers = {"Authorization": f"Bearer {token}"}
                        os_res = requests.get(os_url, headers=headers, timeout=15)
                        
                        if os_res.status_code == 200:
                            os_data = os_res.json()
                            states = os_data.get("states") or []
                            logger.info(f"OpenSky: Fetched {len(states)} states for {os_reg['name']}")
                            
                            for s in states:
                                # OpenSky state vector mapping:
                                # 0icao, 1callsign, 2country, 3time, 4last, 5lon, 6lat, 7baro, 8ground, 9vel, 10track, 11vert, 12sens, 13geo, 14sqk
                                new_opensky_flights.append({
                                    "hex": s[0],
                                    "flight": s[1].strip() if s[1] else "UNKNOWN",
                                    "r": s[2],
                                    "lon": s[5],
                                    "lat": s[6],
                                    "alt_baro": (s[7] * 3.28084) if s[7] else 0, # Meters to Feet for internal consistency
                                    "track": s[10] or 0,
                                    "gs": (s[9] * 1.94384) if s[9] else 0, # m/s to knots
                                    "t": "Unknown", # Model unknown in states API
                                    "is_opensky": True
                                })
                        else:
                            logger.warning(f"OpenSky API {os_reg['name']} failed: {os_res.status_code}")
                    except Exception as ex:
                        logger.error(f"OpenSky fetching error for {os_reg['name']}: {ex}")
                
                cached_opensky_flights = new_opensky_flights
                last_opensky_fetch = now
        
        # Merge cached OpenSky flights, but deduplicate by icao24 hex code
        # ADS-B Exchange is primary; OpenSky only fills gaps
        seen_hex = set()
        for f in all_adsb_flights:
            h = f.get("hex")
            if h:
                seen_hex.add(h.lower().strip())
        for osf in cached_opensky_flights:
            h = osf.get("hex")
            if h and h.lower().strip() not in seen_hex:
                all_adsb_flights.append(osf)
                seen_hex.add(h.lower().strip())

                    
        if all_adsb_flights:
            
            # The user requested maximum flight density. Rendering all available aircraft.
            sampled = all_adsb_flights
            
            # Spin up the background batch route resolver if it's not already trickling
            if not routes_fetch_in_progress:
                threading.Thread(target=fetch_routes_background, args=(sampled,), daemon=True).start()
            
            for f in sampled:
                try:
                    lat = f.get("lat")
                    lng = f.get("lon")
                    heading = f.get("track") or 0
                    
                    if lat is None or lng is None:
                        continue
                        
                    flight_str = str(f.get("flight", "UNKNOWN")).strip()
                    if not flight_str or flight_str == "UNKNOWN":
                        flight_str = str(f.get("hex", "Unknown"))
                        
                    # Origin and destination are fetched via the background thread and cached
                    origin_loc = None
                    dest_loc = None
                    origin_name = "UNKNOWN"
                    dest_name = "UNKNOWN"
                    
                    if flight_str in dynamic_routes_cache:
                        cached = dynamic_routes_cache[flight_str]
                        origin_name = cached["orig_name"]
                        dest_name = cached["dest_name"]
                        origin_loc = cached["orig_loc"]
                        dest_loc = cached["dest_loc"]
                    
                    # Extract 3-letter ICAO Airline Code from CallSign (e.g. UAL123 -> UAL)
                    airline_code = ""
                    match = _RE_AIRLINE_CODE_1.match(flight_str)
                    if not match:
                        match = _RE_AIRLINE_CODE_2.match(flight_str)
                    if match:
                        airline_code = match.group(1)

                    alt_raw = f.get("alt_baro")
                    alt_value = 0
                    if isinstance(alt_raw, (int, float)):
                        alt_value = alt_raw * 0.3048
                    
                    # Ground speed from ADS-B (in knots)
                    gs_knots = f.get("gs")
                    speed_knots = round(gs_knots, 1) if isinstance(gs_knots, (int, float)) else None

                    model_upper = f.get("t", "").upper()
                    ac_category = "heli" if model_upper in _HELI_TYPES_BACKEND else "plane"

                    flights.append({
                        "callsign": flight_str,
                        "country": f.get("r", "N/A"),
                        "lng": float(lng),
                        "lat": float(lat),
                        "alt": alt_value,
                        "heading": heading,
                        "type": "flight",
                        "origin_loc": origin_loc,
                        "dest_loc": dest_loc,
                        "origin_name": origin_name,
                        "dest_name": dest_name,
                        "registration": f.get("r", "N/A"),
                        "model": f.get("t", "Unknown"),
                        "icao24": f.get("hex", ""),
                        "speed_knots": speed_knots,
                        "squawk": f.get("squawk", ""),
                        "airline_code": airline_code,
                        "aircraft_category": ac_category,
                        "nac_p": f.get("nac_p")  # Navigation accuracy — used for GPS jamming detection
                    })
                except Exception as loop_e:
                    logger.error(f"Flight interpolation error: {loop_e}")
                    continue
                
    except Exception as e:
        logger.error(f"Error fetching adsb.lol flights: {e}")
        
    # Private jet ICAO type designator codes (business jets wealthy individuals fly)
    PRIVATE_JET_TYPES = {
        # Gulfstream
        "G150", "G200", "G280", "GLEX", "G500", "G550", "G600", "G650", "G700",
        "GLF2", "GLF3", "GLF4", "GLF5", "GLF6", "GL5T", "GL7T", "GV", "GIV",
        # Bombardier
        "CL30", "CL35", "CL60", "BD70", "BD10", "GL5T", "GL7T",
        "CRJ1", "CRJ2",  # Challenger variants used privately
        # Cessna Citation
        "C25A", "C25B", "C25C", "C500", "C501", "C510", "C525", "C526",
        "C550", "C560", "C56X", "C680", "C68A", "C700", "C750",
        # Dassault Falcon
        "FA10", "FA20", "FA50", "FA7X", "FA8X", "F900", "F2TH", "ASTR",
        # Embraer Business Jets
        "E35L", "E545", "E550", "E55P", "LEGA",  # Praetor / Legacy
        "PH10",  # Phenom 100
        "PH30",  # Phenom 300
        # Learjet
        "LJ23", "LJ24", "LJ25", "LJ28", "LJ31", "LJ35", "LJ36",
        "LJ40", "LJ45", "LJ55", "LJ60", "LJ70", "LJ75",
        # Hawker / Beechcraft
        "H25A", "H25B", "H25C", "HA4T", "BE40", "PRM1",
        # Other business jets
        "HDJT",  # HondaJet
        "PC24",  # Pilatus PC-24
        "EA50",  # Eclipse 500
        "SF50",  # Cirrus Vision Jet
        "GALX",  # IAI Galaxy
    }
    
    commercial = []
    private_jets = []
    private_ga = []
    tracked = []
    
    
    for f in flights:
        # Enrich every flight with plane-alert data
        enrich_with_plane_alert(f)
        enrich_with_tracked_names(f)
        
        callsign = f.get('callsign', '').strip().upper()
        # Heuristic: standard airline callsigns are 3 letters + 1 to 4 digits (e.g., AFR7403, BAW12)
        is_commercial_format = bool(re.match(r'^[A-Z]{3}\d{1,4}[A-Z]{0,2}$', callsign))
        
        if f.get('alert_category'):
            # This is a tracked aircraft — pull it out into tracked list
            f['type'] = 'tracked_flight'
            tracked.append(f)
        elif f.get('airline_code') or is_commercial_format:
            f['type'] = 'commercial_flight'
            commercial.append(f)
        elif f.get('model', '').upper() in PRIVATE_JET_TYPES:
            f['type'] = 'private_jet'
            private_jets.append(f)
        else:
            f['type'] = 'private_ga'
            private_ga.append(f)
    
    # --- Smart merge: protect against partial API failures ---
    # If the new dataset has dramatically fewer flights than what we already have,
    # a region fetch probably failed — keep the old data to prevent planes vanishing.
    prev_commercial_count = len(latest_data.get('commercial_flights', []))
    prev_total = prev_commercial_count + len(latest_data.get('private_jets', [])) + len(latest_data.get('private_flights', []))
    new_total = len(commercial) + len(private_jets) + len(private_ga)

    if new_total == 0:
        logger.warning("No civilian flights found! Skipping overwrite to prevent clearing the map.")
    elif prev_total > 100 and new_total < prev_total * 0.5:
        # Dramatic drop (>50% loss) — a region probably failed, keep existing data
        logger.warning(f"Flight count dropped from {prev_total} to {new_total} (>50% loss). Keeping previous data to prevent flicker.")
    else:
        # Merge: deduplicate by icao24, prefer new data
        import time as _time
        _now = _time.time()

        def _merge_category(new_list, old_list, max_stale_s=120):
            """Merge new flights with old, keeping stale entries for up to max_stale_s."""
            by_icao = {}
            # Old entries first (will be overwritten by new)
            for f in old_list:
                icao = f.get('icao24', '')
                if icao:
                    f.setdefault('_seen_at', _now)
                    # Evict if stale for too long
                    if (_now - f.get('_seen_at', _now)) < max_stale_s:
                        by_icao[icao] = f
            # New entries overwrite old
            for f in new_list:
                icao = f.get('icao24', '')
                if icao:
                    f['_seen_at'] = _now
                    by_icao[icao] = f
                else:
                    by_icao[id(f)] = f  # no icao — keep as unique
            return list(by_icao.values())

        with _data_lock:
            latest_data['commercial_flights'] = _merge_category(commercial, latest_data.get('commercial_flights', []))
            latest_data['private_jets'] = _merge_category(private_jets, latest_data.get('private_jets', []))
            latest_data['private_flights'] = _merge_category(private_ga, latest_data.get('private_flights', []))

    # Always write raw flights for GPS jamming analysis (nac_p field)
    if flights:
        latest_data['flights'] = flights
    
    # Merge tracked civilian flights with any tracked military flights
    # CRITICAL: Update positions for already-tracked aircraft on every cycle,
    # not just add new ones — otherwise tracked positions go stale.
    existing_tracked = latest_data.get('tracked_flights', [])
    
    # Build a map of fresh tracked data keyed by icao24
    fresh_tracked_map = {}
    for t in tracked:
        icao = t.get('icao24', '').upper()
        if icao:
            fresh_tracked_map[icao] = t
    
    # Update existing tracked entries with fresh positions, preserve metadata
    merged_tracked = []
    seen_icaos = set()
    for old_t in existing_tracked:
        icao = old_t.get('icao24', '').upper()
        if icao in fresh_tracked_map:
            # Fresh data available — use it, but preserve any extra metadata from old entry
            fresh = fresh_tracked_map[icao]
            for key in ('alert_category', 'alert_operator', 'alert_special', 'alert_flag'):
                if key in old_t and key not in fresh:
                    fresh[key] = old_t[key]
            merged_tracked.append(fresh)
            seen_icaos.add(icao)
        else:
            # No fresh data (military-only tracked, or plane landed/out of range)
            merged_tracked.append(old_t)
            seen_icaos.add(icao)
    
    # Add any newly-discovered tracked aircraft
    for icao, t in fresh_tracked_map.items():
        if icao not in seen_icaos:
            merged_tracked.append(t)
    
    latest_data['tracked_flights'] = merged_tracked
    logger.info(f"Tracked flights: {len(merged_tracked)} total ({len(fresh_tracked_map)} fresh from civilian)")
    
    # -----------------------------------------------------------------------
    # Flight Trail Accumulation — build position history for unrouted flights
    # -----------------------------------------------------------------------
    def _accumulate_trail(f, now_ts, check_route=True):
        """Accumulate trail points for a single flight. Returns 1 if trail updated, 0 otherwise."""
        hex_id = f.get('icao24', '').lower()
        if not hex_id:
            return 0, None
        if check_route and f.get('origin_name', 'UNKNOWN') != 'UNKNOWN':
            f['trail'] = []
            return 0, hex_id
        lat, lng, alt = f.get('lat'), f.get('lng'), f.get('alt', 0)
        if lat is None or lng is None:
            f['trail'] = flight_trails.get(hex_id, {}).get('points', [])
            return 0, hex_id
        point = [round(lat, 5), round(lng, 5), round(alt, 1), round(now_ts)]
        if hex_id not in flight_trails:
            flight_trails[hex_id] = {'points': [], 'last_seen': now_ts}
        trail_data = flight_trails[hex_id]
        if trail_data['points'] and trail_data['points'][-1][0] == point[0] and trail_data['points'][-1][1] == point[1]:
            trail_data['last_seen'] = now_ts
        else:
            trail_data['points'].append(point)
            trail_data['last_seen'] = now_ts
        if len(trail_data['points']) > 200:
            trail_data['points'] = trail_data['points'][-200:]
        f['trail'] = trail_data['points']
        return 1, hex_id

    now_ts = datetime.utcnow().timestamp()
    all_lists = [commercial, private_jets, private_ga, existing_tracked]
    seen_hexes = set()
    trail_count = 0
    with _trails_lock:
        for flist in all_lists:
            for f in flist:
                count, hex_id = _accumulate_trail(f, now_ts, check_route=True)
                trail_count += count
                if hex_id:
                    seen_hexes.add(hex_id)

        # Also process military flights (separate list)
        for mf in latest_data.get('military_flights', []):
            count, hex_id = _accumulate_trail(mf, now_ts, check_route=False)
            trail_count += count
            if hex_id:
                seen_hexes.add(hex_id)

        # Prune stale trails (10 min for non-tracked, 30 min for tracked)
        tracked_hexes = {t.get('icao24', '').lower() for t in latest_data.get('tracked_flights', [])}
        stale_keys = []
        for k, v in flight_trails.items():
            cutoff = now_ts - 1800 if k in tracked_hexes else now_ts - 600
            if v['last_seen'] < cutoff:
                stale_keys.append(k)
        for k in stale_keys:
            del flight_trails[k]

        # Enforce global cap — evict oldest trails first
        if len(flight_trails) > _MAX_TRACKED_TRAILS:
            sorted_keys = sorted(flight_trails.keys(), key=lambda k: flight_trails[k]['last_seen'])
            evict_count = len(flight_trails) - _MAX_TRACKED_TRAILS
            for k in sorted_keys[:evict_count]:
                del flight_trails[k]

    logger.info(f"Trail accumulation: {trail_count} active trails, {len(stale_keys)} pruned, {len(flight_trails)} total")

    # -----------------------------------------------------------------------
    # GPS / GNSS Jamming Detection — aggregate NACp from ADS-B transponders
    # NACp (Navigation Accuracy Category for Position):
    #   11 = full accuracy (<3m), 8 = good (<93m), <8 = degraded = potential jamming
    # We use a 1°×1° grid (~111km at equator) to aggregate interference zones.
    # -----------------------------------------------------------------------
    try:
        jamming_grid = {}  # "lat,lng" -> {"degraded": int, "total": int}
        raw_flights = latest_data.get('flights', [])
        for rf in raw_flights:
            rlat = rf.get('lat')
            rlng = rf.get('lng') or rf.get('lon')
            if rlat is None or rlng is None:
                continue
            nacp = rf.get('nac_p')
            if nacp is None:
                continue
            # Grid key: snap to 1-degree cells
            grid_key = f"{int(rlat)},{int(rlng)}"
            if grid_key not in jamming_grid:
                jamming_grid[grid_key] = {"degraded": 0, "total": 0}
            jamming_grid[grid_key]["total"] += 1
            if nacp < 8:
                jamming_grid[grid_key]["degraded"] += 1

        jamming_zones = []
        for gk, counts in jamming_grid.items():
            if counts["total"] < 3:
                continue  # Need at least 3 aircraft to be meaningful
            ratio = counts["degraded"] / counts["total"]
            if ratio > 0.25:  # >25% degraded = jamming
                lat_i, lng_i = gk.split(",")
                severity = "low" if ratio < 0.5 else "medium" if ratio < 0.75 else "high"
                jamming_zones.append({
                    "lat": int(lat_i) + 0.5,  # Center of cell
                    "lng": int(lng_i) + 0.5,
                    "severity": severity,
                    "ratio": round(ratio, 2),
                    "degraded": counts["degraded"],
                    "total": counts["total"]
                })
        latest_data['gps_jamming'] = jamming_zones
        if jamming_zones:
            logger.info(f"GPS Jamming: {len(jamming_zones)} interference zones detected")
    except Exception as e:
        logger.error(f"GPS Jamming detection error: {e}")
        latest_data['gps_jamming'] = []

    # -----------------------------------------------------------------------
    # Holding Pattern Detection — flag aircraft circling in place
    # If cumulative heading change over last 8 trail points > 300°, it's circling
    # -----------------------------------------------------------------------
    try:
        holding_count = 0
        all_flight_lists = [commercial, private_jets, private_ga,
                            latest_data.get('tracked_flights', []),
                            latest_data.get('military_flights', [])]
        for flist in all_flight_lists:
            for f in flist:
                hex_id = f.get('icao24', '').lower()
                trail = flight_trails.get(hex_id, {}).get('points', [])
                if len(trail) < 6:
                    f['holding'] = False
                    continue
                # Calculate cumulative bearing change over last 8 points
                pts = trail[-8:]
                total_turn = 0.0
                prev_bearing = 0.0
                for i in range(1, len(pts)):
                    lat1, lng1 = math.radians(pts[i-1][0]), math.radians(pts[i-1][1])
                    lat2, lng2 = math.radians(pts[i][0]), math.radians(pts[i][1])
                    dlng = lng2 - lng1
                    x = math.sin(dlng) * math.cos(lat2)
                    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
                    bearing = math.degrees(math.atan2(x, y)) % 360
                    if i > 1:
                        delta = abs(bearing - prev_bearing)
                        if delta > 180:
                            delta = 360 - delta
                        total_turn += delta
                    prev_bearing = bearing
                f['holding'] = total_turn > 300  # > 300° = nearly a full circle
                if f['holding']:
                    holding_count += 1
        if holding_count:
            logger.info(f"Holding patterns: {holding_count} aircraft circling")
    except Exception as e:
        logger.error(f"Holding pattern detection error: {e}")

    # Update timestamp so the ETag in /api/live-data/fast changes on every fetch cycle
    latest_data['last_updated'] = datetime.utcnow().isoformat()

def fetch_ships():
    """Fetch real-time AIS vessel data and combine with OSINT carrier positions."""
    from services.ais_stream import get_ais_vessels
    from services.carrier_tracker import get_carrier_positions
    
    ships = []
    
    # Dynamic OSINT carrier positions (updated from GDELT + cache)
    carriers = get_carrier_positions()
    ships.extend(carriers)
    
    # Real AIS vessel data from aisstream.io
    ais_vessels = get_ais_vessels()
    ships.extend(ais_vessels)
    
    logger.info(f"Ships: {len(carriers)} carriers + {len(ais_vessels)} AIS vessels")
    latest_data['ships'] = ships

def fetch_military_flights():
    # True ADS-B Exchange military data requires paid API access.
    # We will use adsb.lol (an open source ADSB aggregator) /v2/mil fallback.
    military_flights = []
    try:
        url = "https://api.adsb.lol/v2/mil"
        response = fetch_with_curl(url, timeout=10)
        if response.status_code == 200:
            ac = response.json().get('ac', [])
            for f in ac: 
                try:
                    lat = f.get("lat")
                    lng = f.get("lon")
                    heading = f.get("track") or 0
                    
                    if lat is None or lng is None:
                        continue
                        
                    model = str(f.get("t", "UNKNOWN")).upper()
                    mil_cat = "default"
                    if "H" in model and any(c.isdigit() for c in model):
                        mil_cat = "heli"
                    elif any(k in model for k in ["K35", "K46", "A33"]):
                        mil_cat = "tanker"
                    elif any(k in model for k in ["F16", "F35", "F22", "F15", "F18", "T38", "T6", "A10"]):
                        mil_cat = "fighter"
                    elif any(k in model for k in ["C17", "C5", "C130", "C30", "A400", "V22"]):
                        mil_cat = "cargo"
                    elif any(k in model for k in ["P8", "E3", "E8", "U2", "RQ", "MQ"]):
                        mil_cat = "recon"

                    # Military flights don't file public routes
                    origin_loc = None
                    dest_loc = None
                    origin_name = "UNKNOWN"
                    dest_name = "UNKNOWN"


                    alt_raw = f.get("alt_baro")
                    alt_value = 0
                    if isinstance(alt_raw, (int, float)):
                        alt_value = alt_raw * 0.3048
                    
                    # Ground speed from ADS-B (in knots)
                    gs_knots = f.get("gs")
                    speed_knots = round(gs_knots, 1) if isinstance(gs_knots, (int, float)) else None

                    military_flights.append({
                        "callsign": str(f.get("flight", "MIL-UNKN")).strip(),
                        "country": f.get("r", "Military Asset"),
                        "lng": float(lng),
                        "lat": float(lat),
                        "alt": alt_value,
                        "heading": heading,
                        "type": "military_flight",
                        "military_type": mil_cat,
                        "origin_loc": origin_loc,
                        "dest_loc": dest_loc,
                        "origin_name": origin_name,
                        "dest_name": dest_name,
                        "registration": f.get("r", "N/A"),
                        "model": f.get("t", "Unknown"),
                        "icao24": f.get("hex", ""),
                        "speed_knots": speed_knots,
                        "squawk": f.get("squawk", "")
                    })
                except Exception as loop_e:
                    logger.error(f"Mil flight interpolation error: {loop_e}")
                    continue
    except Exception as e:
        logger.error(f"Error fetching military flights: {e}")
        
    if not military_flights:
        # API failed or rate limited — log but do NOT inject fake data
        logger.warning("No military flights retrieved — keeping previous data if available")
        # Preserve existing data rather than overwriting with empty
        if latest_data.get('military_flights'):
            return
            
    latest_data['military_flights'] = military_flights
    
    # Cross-reference military flights with Plane-Alert DB
    tracked_mil = []
    remaining_mil = []
    for mf in military_flights:
        enrich_with_plane_alert(mf)
        if mf.get('alert_category'):
            mf['type'] = 'tracked_flight'
            tracked_mil.append(mf)
        else:
            remaining_mil.append(mf)
    latest_data['military_flights'] = remaining_mil
    
    # Store tracked military flights — update positions for existing entries
    existing_tracked = latest_data.get('tracked_flights', [])
    fresh_mil_map = {}
    for t in tracked_mil:
        icao = t.get('icao24', '').upper()
        if icao:
            fresh_mil_map[icao] = t
    
    # Update existing military tracked entries with fresh positions
    updated_tracked = []
    seen_icaos = set()
    for old_t in existing_tracked:
        icao = old_t.get('icao24', '').upper()
        if icao in fresh_mil_map:
            fresh = fresh_mil_map[icao]
            for key in ('alert_category', 'alert_operator', 'alert_special', 'alert_flag'):
                if key in old_t and key not in fresh:
                    fresh[key] = old_t[key]
            updated_tracked.append(fresh)
            seen_icaos.add(icao)
        else:
            updated_tracked.append(old_t)
            seen_icaos.add(icao)
    for icao, t in fresh_mil_map.items():
        if icao not in seen_icaos:
            updated_tracked.append(t)
    latest_data['tracked_flights'] = updated_tracked
    logger.info(f"Tracked flights: {len(updated_tracked)} total ({len(tracked_mil)} from military)")

def fetch_weather():
    try:
        url = "https://api.rainviewer.com/public/weather-maps.json"
        response = fetch_with_curl(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "radar" in data and "past" in data["radar"]:
                latest_time = data["radar"]["past"][-1]["time"]
                latest_data["weather"] = {"time": latest_time, "host": data.get("host", "https://tilecache.rainviewer.com")}
    except Exception as e:
        logger.error(f"Error fetching weather: {e}")

def fetch_cctv():
    try:
        latest_data["cctv"] = get_all_cameras()
    except Exception as e:
        logger.error(f"Error fetching cctv from DB: {e}")
        latest_data["cctv"] = []

def fetch_bikeshare():
    bikes = []
    try:
        # CitiBike NYC Free GBFS Feed
        info_url = "https://gbfs.citibikenyc.com/gbfs/en/station_information.json"
        status_url = "https://gbfs.citibikenyc.com/gbfs/en/station_status.json"
        
        info_res = fetch_with_curl(info_url, timeout=10)
        status_res = fetch_with_curl(status_url, timeout=10)
        
        if info_res.status_code == 200 and status_res.status_code == 200:
            stations = info_res.json()["data"]["stations"]
            statuses = status_res.json()["data"]["stations"]
            
            # Map statuses
            status_map = {s["station_id"]: s for s in statuses}
            
            # Top 100 stations for performance
            for st in stations[:100]:
                sid = st["station_id"]
                stat = status_map.get(sid, {})
                bikes.append({
                    "id": sid,
                    "name": st.get("name", "Station"),
                    "lat": st.get("lat", 0),
                    "lng": st.get("lon", 0),
                    "capacity": st.get("capacity", 0),
                    "available": stat.get("num_bikes_available", 0)
                })
    except Exception as e:
        logger.error(f"Error fetching bikeshare: {e}")
    latest_data["bikeshare"] = bikes

def fetch_traffic():
    # Deprecated: TomTom warning signs removed from UI to declutter CCTV mesh
    latest_data["traffic"] = []

def fetch_earthquakes():
    quakes = []
    try:
        url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
        response = fetch_with_curl(url, timeout=10)
        if response.status_code == 200:
            features = response.json().get("features", [])
            for f in features[:50]:
                mag = f["properties"]["mag"]
                lng, lat, depth = f["geometry"]["coordinates"]
                quakes.append({
                    "id": f["id"],
                    "mag": mag,
                    "lat": lat,
                    "lng": lng,
                    "place": f["properties"]["place"]
                })
    except Exception as e:
        logger.error(f"Error fetching earthquakes: {e}")
    latest_data["earthquakes"] = quakes

# Satellite GP data cache — re-download from CelesTrak only every 30 minutes
_sat_gp_cache = {"data": None, "last_fetch": 0}

# Satellite intelligence classification database — module-level constant.
# Key: substring to match in OBJECT_NAME → {country, mission, sat_type, wiki}
_SAT_INTEL_DB = [
    # Military reconnaissance / imaging
        ("USA 224", {"country": "USA", "mission": "military_recon", "sat_type": "KH-11 Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/KH-11_KENNEN"}),
        ("USA 245", {"country": "USA", "mission": "military_recon", "sat_type": "KH-11 Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/KH-11_KENNEN"}),
        ("USA 290", {"country": "USA", "mission": "military_recon", "sat_type": "KH-11 Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/KH-11_KENNEN"}),
        ("USA 314", {"country": "USA", "mission": "military_recon", "sat_type": "KH-11 Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/KH-11_KENNEN"}),
        ("USA 338", {"country": "USA", "mission": "military_recon", "sat_type": "Keyhole Successor", "wiki": "https://en.wikipedia.org/wiki/KH-11_KENNEN"}),
        ("TOPAZ", {"country": "Russia", "mission": "military_recon", "sat_type": "Optical Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Persona_(satellite)"}),
        ("PERSONA", {"country": "Russia", "mission": "military_recon", "sat_type": "Optical Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Persona_(satellite)"}),
        ("KONDOR", {"country": "Russia", "mission": "military_sar", "sat_type": "SAR Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Kondor_(satellite)"}),
        ("BARS-M", {"country": "Russia", "mission": "military_recon", "sat_type": "Mapping Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Bars-M"}),
        ("YAOGAN", {"country": "China", "mission": "military_recon", "sat_type": "Remote Sensing / ELINT", "wiki": "https://en.wikipedia.org/wiki/Yaogan"}),
        ("GAOFEN", {"country": "China", "mission": "military_recon", "sat_type": "High-Res Imaging", "wiki": "https://en.wikipedia.org/wiki/Gaofen"}),
        ("JILIN", {"country": "China", "mission": "commercial_imaging", "sat_type": "Video / Imaging", "wiki": "https://en.wikipedia.org/wiki/Jilin-1"}),
        ("OFEK", {"country": "Israel", "mission": "military_recon", "sat_type": "Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Ofeq"}),
        ("CSO", {"country": "France", "mission": "military_recon", "sat_type": "Optical Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/CSO_(satellite)"}),
        ("IGS", {"country": "Japan", "mission": "military_recon", "sat_type": "Intelligence Gathering", "wiki": "https://en.wikipedia.org/wiki/Information_Gathering_Satellite"}),
        # SAR (Synthetic Aperture Radar) — can see through clouds
        ("CAPELLA", {"country": "USA", "mission": "sar", "sat_type": "SAR Imaging", "wiki": "https://en.wikipedia.org/wiki/Capella_Space"}),
        ("ICEYE", {"country": "Finland", "mission": "sar", "sat_type": "SAR Microsatellite", "wiki": "https://en.wikipedia.org/wiki/ICEYE"}),
        ("COSMO-SKYMED", {"country": "Italy", "mission": "sar", "sat_type": "SAR Constellation", "wiki": "https://en.wikipedia.org/wiki/COSMO-SkyMed"}),
        ("TANDEM", {"country": "Germany", "mission": "sar", "sat_type": "SAR Interferometry", "wiki": "https://en.wikipedia.org/wiki/TanDEM-X"}),
        ("PAZ", {"country": "Spain", "mission": "sar", "sat_type": "SAR Imaging", "wiki": "https://en.wikipedia.org/wiki/PAZ_(satellite)"}),
        # Commercial imaging
        ("WORLDVIEW", {"country": "USA", "mission": "commercial_imaging", "sat_type": "Maxar High-Res", "wiki": "https://en.wikipedia.org/wiki/WorldView-3"}),
        ("GEOEYE", {"country": "USA", "mission": "commercial_imaging", "sat_type": "Maxar Imaging", "wiki": "https://en.wikipedia.org/wiki/GeoEye-1"}),
        ("PLEIADES", {"country": "France", "mission": "commercial_imaging", "sat_type": "Airbus Imaging", "wiki": "https://en.wikipedia.org/wiki/Pl%C3%A9iades_(satellite)"}),
        ("SPOT", {"country": "France", "mission": "commercial_imaging", "sat_type": "Airbus Medium-Res", "wiki": "https://en.wikipedia.org/wiki/SPOT_(satellite)"}),
        ("PLANET", {"country": "USA", "mission": "commercial_imaging", "sat_type": "PlanetScope", "wiki": "https://en.wikipedia.org/wiki/Planet_Labs"}),
        ("SKYSAT", {"country": "USA", "mission": "commercial_imaging", "sat_type": "Planet Video", "wiki": "https://en.wikipedia.org/wiki/SkySat"}),
        ("BLACKSKY", {"country": "USA", "mission": "commercial_imaging", "sat_type": "BlackSky Imaging", "wiki": "https://en.wikipedia.org/wiki/BlackSky"}),
        # Signals intelligence / ELINT
        ("NROL", {"country": "USA", "mission": "sigint", "sat_type": "Classified NRO", "wiki": "https://en.wikipedia.org/wiki/National_Reconnaissance_Office"}),
        ("MENTOR", {"country": "USA", "mission": "sigint", "sat_type": "SIGINT / ELINT", "wiki": "https://en.wikipedia.org/wiki/Mentor_(satellite)"}),
        ("LUCH", {"country": "Russia", "mission": "sigint", "sat_type": "Relay / SIGINT", "wiki": "https://en.wikipedia.org/wiki/Luch_(satellite)"}),
        ("SHIJIAN", {"country": "China", "mission": "sigint", "sat_type": "ELINT / Tech Demo", "wiki": "https://en.wikipedia.org/wiki/Shijian"}),
        # Navigation
        ("NAVSTAR", {"country": "USA", "mission": "navigation", "sat_type": "GPS", "wiki": "https://en.wikipedia.org/wiki/GPS_satellite_blocks"}),
        ("GLONASS", {"country": "Russia", "mission": "navigation", "sat_type": "GLONASS", "wiki": "https://en.wikipedia.org/wiki/GLONASS"}),
        ("BEIDOU", {"country": "China", "mission": "navigation", "sat_type": "BeiDou", "wiki": "https://en.wikipedia.org/wiki/BeiDou"}),
        ("GALILEO", {"country": "EU", "mission": "navigation", "sat_type": "Galileo", "wiki": "https://en.wikipedia.org/wiki/Galileo_(satellite_navigation)"}),
        # Early warning
        ("SBIRS", {"country": "USA", "mission": "early_warning", "sat_type": "Missile Warning", "wiki": "https://en.wikipedia.org/wiki/Space-Based_Infrared_System"}),
        ("TUNDRA", {"country": "Russia", "mission": "early_warning", "sat_type": "Missile Warning", "wiki": "https://en.wikipedia.org/wiki/Tundra_(satellite)"}),
        # Space stations
        ("ISS", {"country": "Intl", "mission": "space_station", "sat_type": "Space Station", "wiki": "https://en.wikipedia.org/wiki/International_Space_Station"}),
    ("TIANGONG", {"country": "China", "mission": "space_station", "sat_type": "Space Station", "wiki": "https://en.wikipedia.org/wiki/Tiangong_space_station"}),
]

def _parse_tle_to_gp(name, norad_id, line1, line2):
    """Convert TLE two-line element to CelesTrak GP-style dict for unified processing."""
    try:
        # Parse TLE line 2 fields (standard TLE format)
        incl = float(line2[8:16].strip())
        raan = float(line2[17:25].strip())
        ecc = float("0." + line2[26:33].strip())
        argp = float(line2[34:42].strip())
        ma = float(line2[43:51].strip())
        mm = float(line2[52:63].strip())
        # Parse BSTAR from line 1 (columns 54-61)
        bstar_str = line1[53:61].strip()
        if bstar_str:
            mantissa = float(bstar_str[:-2]) / 1e5
            exponent = int(bstar_str[-2:])
            bstar = mantissa * (10 ** exponent)
        else:
            bstar = 0.0
        # Parse epoch from line 1 (columns 18-32)
        epoch_yr = int(line1[18:20])
        epoch_day = float(line1[20:32].strip())
        year = 2000 + epoch_yr if epoch_yr < 57 else 1900 + epoch_yr
        from datetime import datetime, timedelta
        epoch_dt = datetime(year, 1, 1) + timedelta(days=epoch_day - 1)
        return {
            "OBJECT_NAME": name,
            "NORAD_CAT_ID": norad_id,
            "MEAN_MOTION": mm,
            "ECCENTRICITY": ecc,
            "INCLINATION": incl,
            "RA_OF_ASC_NODE": raan,
            "ARG_OF_PERICENTER": argp,
            "MEAN_ANOMALY": ma,
            "BSTAR": bstar,
            "EPOCH": epoch_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    except Exception:
        return None


def _fetch_satellites_from_tle_api():
    """Fallback: fetch satellite TLEs from tle.ivanstanojevic.me when CelesTrak is blocked."""
    # Build search terms from our intel DB — deduplicate short prefixes
    search_terms = set()
    for key, _ in _SAT_INTEL_DB:
        # Use first word for broader matching (e.g., "USA" catches USA 224, USA 245, etc.)
        term = key.split()[0] if len(key.split()) > 1 and key.split()[0] in ("USA", "NROL") else key
        search_terms.add(term)

    all_results = []
    seen_ids = set()
    for term in search_terms:
        try:
            url = f"https://tle.ivanstanojevic.me/api/tle/?search={term}&page_size=100&format=json"
            response = fetch_with_curl(url, timeout=10)
            if response.status_code != 200:
                continue
            data = response.json()
            for member in data.get("member", []):
                sat_id = member.get("satelliteId")
                if sat_id in seen_ids:
                    continue
                seen_ids.add(sat_id)
                gp = _parse_tle_to_gp(
                    member.get("name", "UNKNOWN"),
                    sat_id,
                    member.get("line1", ""),
                    member.get("line2", ""),
                )
                if gp:
                    all_results.append(gp)
        except Exception as e:
            logger.debug(f"TLE fallback search '{term}' failed: {e}")
            continue

    return all_results


def fetch_satellites():
    sats = []
    try:
        # Cache GP data from CelesTrak — only re-download every 30 minutes
        # Positions are re-propagated from cached orbital elements each cycle
        now_ts = time.time()
        if _sat_gp_cache["data"] is None or (now_ts - _sat_gp_cache["last_fetch"]) > 1800:
            # Try multiple CelesTrak mirrors — .org is often blocked/banned by some networks
            gp_urls = [
                "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=json",
                "https://celestrak.com/NORAD/elements/gp.php?GROUP=active&FORMAT=json",
            ]
            for url in gp_urls:
                try:
                    response = fetch_with_curl(url, timeout=8)
                    if response.status_code == 200:
                        gp_data = response.json()
                        if isinstance(gp_data, list) and len(gp_data) > 100:
                            _sat_gp_cache["data"] = gp_data
                            _sat_gp_cache["last_fetch"] = now_ts
                            logger.info(f"Satellites: Downloaded {len(gp_data)} GP records from {url}")
                            break
                except Exception as e:
                    logger.warning(f"Satellites: Failed to fetch from {url}: {e}")
                    continue

            # Fallback: if CelesTrak is blocked, use tle.ivanstanojevic.me TLE API
            if _sat_gp_cache["data"] is None:
                logger.info("Satellites: CelesTrak unreachable, trying TLE fallback API...")
                try:
                    fallback_data = _fetch_satellites_from_tle_api()
                    if fallback_data and len(fallback_data) > 10:
                        _sat_gp_cache["data"] = fallback_data
                        _sat_gp_cache["last_fetch"] = now_ts
                        logger.info(f"Satellites: Got {len(fallback_data)} records from TLE fallback API")
                except Exception as e:
                    logger.error(f"Satellites: TLE fallback also failed: {e}")

        data = _sat_gp_cache["data"]
        if not data:
            logger.warning("No satellite GP data available from any source")
            latest_data["satellites"] = sats
            return

        # Only keep satellites matching the intel classification DB
        classified = []
        for sat in data:
            name = sat.get("OBJECT_NAME", "UNKNOWN").upper()
            intel = None
            for key, meta in _SAT_INTEL_DB:
                if key.upper() in name:
                    intel = dict(meta)
                    break
            if not intel:
                continue  # Skip junk, debris, CubeSats, bulk constellations
            entry = {
                "id": sat.get("NORAD_CAT_ID"),
                "name": sat.get("OBJECT_NAME", "UNKNOWN"),
                "MEAN_MOTION": sat.get("MEAN_MOTION"),
                "ECCENTRICITY": sat.get("ECCENTRICITY"),
                "INCLINATION": sat.get("INCLINATION"),
                "RA_OF_ASC_NODE": sat.get("RA_OF_ASC_NODE"),
                "ARG_OF_PERICENTER": sat.get("ARG_OF_PERICENTER"),
                "MEAN_ANOMALY": sat.get("MEAN_ANOMALY"),
                "BSTAR": sat.get("BSTAR"),
                "EPOCH": sat.get("EPOCH"),
            }
            entry.update(intel)
            classified.append(entry)

        all_sats = classified
        logger.info(f"Satellites: {len(classified)} intel-classified out of {len(data)} total in catalog")

        # Propagate orbital elements to get current lat/lng/alt using SGP4
        now = datetime.utcnow()
        jd, fr = jday(now.year, now.month, now.day, now.hour, now.minute, now.second + now.microsecond / 1e6)
        
        for s in all_sats:
            try:
                mean_motion = s.get('MEAN_MOTION')
                ecc = s.get('ECCENTRICITY')
                incl = s.get('INCLINATION')
                raan = s.get('RA_OF_ASC_NODE')
                argp = s.get('ARG_OF_PERICENTER')
                ma = s.get('MEAN_ANOMALY')
                bstar = s.get('BSTAR', 0)
                epoch_str = s.get('EPOCH')
                norad_id = s.get('id', 0)
                
                if mean_motion is None or ecc is None or incl is None:
                    continue
                
                epoch_dt = datetime.strptime(epoch_str[:19], '%Y-%m-%dT%H:%M:%S')
                epoch_jd, epoch_fr = jday(epoch_dt.year, epoch_dt.month, epoch_dt.day,
                                          epoch_dt.hour, epoch_dt.minute, epoch_dt.second)
                
                sat_obj = Satrec()
                sat_obj.sgp4init(
                    WGS72, 'i', norad_id,
                    (epoch_jd + epoch_fr) - 2433281.5,
                    bstar, 0.0, 0.0, ecc,
                    math.radians(argp), math.radians(incl),
                    math.radians(ma),
                    mean_motion * 2 * math.pi / 1440.0,
                    math.radians(raan)
                )
                
                e, r, v = sat_obj.sgp4(jd, fr)
                if e != 0:
                    continue
                
                x, y, z = r
                gmst = _gmst(jd + fr)
                lng_rad = math.atan2(y, x) - gmst
                lat_rad = math.atan2(z, math.sqrt(x*x + y*y))
                alt_km = math.sqrt(x*x + y*y + z*z) - 6371.0
                
                s['lat'] = round(math.degrees(lat_rad), 4)
                lng_deg = math.degrees(lng_rad) % 360
                s['lng'] = round(lng_deg - 360 if lng_deg > 180 else lng_deg, 4)
                s['alt_km'] = round(alt_km, 1)
                
                # Compute ground speed and heading from ECI velocity vector
                # v is in km/s in ECI frame; subtract Earth rotation to get ground-relative
                vx, vy, vz = v
                omega_e = 7.2921159e-5  # Earth rotation rate rad/s
                # Ground-relative velocity (subtract Earth rotation)
                vx_g = vx + omega_e * y  # note: y from position, not vy
                vy_g = vy - omega_e * x
                vz_g = vz
                # Convert ECI velocity to East/North/Up at satellite's geodetic position
                cos_lat = math.cos(lat_rad)
                sin_lat = math.sin(lat_rad)
                cos_lng = math.cos(lng_rad + gmst)  # need ECEF longitude
                sin_lng = math.sin(lng_rad + gmst)
                # East = -sin(lng)*vx + cos(lng)*vy
                v_east = -sin_lng * vx_g + cos_lng * vy_g
                # North = -sin(lat)*cos(lng)*vx - sin(lat)*sin(lng)*vy + cos(lat)*vz
                v_north = -sin_lat * cos_lng * vx_g - sin_lat * sin_lng * vy_g + cos_lat * vz_g
                # Ground speed in km/s → knots (1 km/s = 1943.84 knots)
                ground_speed_kms = math.sqrt(v_east**2 + v_north**2)
                s['speed_knots'] = round(ground_speed_kms * 1943.84, 1)
                # Heading: angle from north, clockwise
                heading_rad = math.atan2(v_east, v_north)
                s['heading'] = round(math.degrees(heading_rad) % 360, 1)
                # Wikipedia URL: USA-XXX satellites get their own article,
                # all others keep the curated class/type URL from _SAT_INTEL_DB
                sat_name = s.get('name', '')
                usa_match = re.search(r'USA[\s\-]*(\d+)', sat_name)
                if usa_match:
                    s['wiki'] = f"https://en.wikipedia.org/wiki/USA-{usa_match.group(1)}"
                # Strip GP element fields to save bandwidth
                for k in ('MEAN_MOTION', 'ECCENTRICITY', 'INCLINATION',
                          'RA_OF_ASC_NODE', 'ARG_OF_PERICENTER', 'MEAN_ANOMALY',
                          'BSTAR', 'EPOCH', 'tle1', 'tle2'):
                    s.pop(k, None)
                sats.append(s)
            except Exception:
                continue

        logger.info(f"Satellites: {len(classified)} classified, {len(sats)} positioned")
    except Exception as e:
        logger.error(f"Error fetching satellites: {e}")
    # Only overwrite if we got data — don't wipe the map on API timeout
    if sats:
        latest_data["satellites"] = sats
    elif not latest_data.get("satellites"):
        latest_data["satellites"] = []

def fetch_uavs():
    # Simulated high-altitude long-endurance (HALE) and MALE UAVs over high-risk regions
    
    uav_targets = [
        {
            "name": "RQ-4 Global Hawk", "center": [31.5, 34.8], "radius": 0.5, "alt": 15000,
            "country": "USA", "uav_type": "HALE Surveillance", "range_km": 2200,
            "wiki": "https://en.wikipedia.org/wiki/Northrop_Grumman_RQ-4_Global_Hawk",
            "speed_knots": 340
        },
        {
            "name": "MQ-9 Reaper", "center": [49.0, 31.4], "radius": 1.2, "alt": 12000,
            "country": "USA", "uav_type": "MALE Strike/ISR", "range_km": 1850,
            "wiki": "https://en.wikipedia.org/wiki/General_Atomics_MQ-9_Reaper",
            "speed_knots": 250
        },
        {
            "name": "Bayraktar TB2", "center": [23.6, 120.9], "radius": 0.8, "alt": 8000,
            "country": "Turkey", "uav_type": "MALE Strike", "range_km": 150,
            "wiki": "https://en.wikipedia.org/wiki/Bayraktar_TB2",
            "speed_knots": 120
        },
        {
            "name": "MQ-1C Gray Eagle", "center": [38.0, 127.0], "radius": 0.4, "alt": 10000,
            "country": "USA", "uav_type": "MALE ISR/Strike", "range_km": 400,
            "wiki": "https://en.wikipedia.org/wiki/General_Atomics_MQ-1C_Gray_Eagle",
            "speed_knots": 150
        },
        {
            "name": "RQ-170 Sentinel", "center": [25.0, 55.0], "radius": 1.5, "alt": 18000,
            "country": "USA", "uav_type": "Stealth ISR", "range_km": 1100,
            "wiki": "https://en.wikipedia.org/wiki/Lockheed_Martin_RQ-170_Sentinel",
            "speed_knots": 300
        }
    ]
    
    # Use the current hour and minute to create a continuous slow orbit
    now = datetime.utcnow()
    # 1 full orbit every 10 minutes
    time_factor = ((now.minute % 10) * 60 + now.second) / 600.0  
    angle = time_factor * 2 * math.pi
    
    uavs = []
    for idx, t in enumerate(uav_targets):
        # Offset the angle slightly so they aren't all synchronized
        offset_angle = angle + (idx * math.pi / 2.5)
        
        lat = t["center"][0] + math.sin(offset_angle) * t["radius"]
        lng = t["center"][1] + math.cos(offset_angle) * t["radius"]
        
        heading = (math.degrees(offset_angle) + 90) % 360
        
        uavs.append({
            "id": f"uav-{idx}",
            "callsign": t["name"],
            "aircraft_model": t["name"],
            "lat": lat,
            "lng": lng,
            "alt": t["alt"],
            "heading": heading,
            "speed_knots": t["speed_knots"],
            "center": t["center"],
            "orbit_radius": t["radius"],
            "range_km": t["range_km"],
            "country": t["country"],
            "uav_type": t["uav_type"],
            "wiki": t["wiki"],
        })
        
    latest_data['uavs'] = uavs

cached_airports = []
flight_trails = {}  # {icao_hex: {points: [[lat, lng, alt, ts], ...], last_seen: ts}}
_trails_lock = threading.Lock()
_MAX_TRACKED_TRAILS = 2000  # Global cap on number of aircraft trails in memory

# (math imported at module top)

def find_nearest_airport(lat, lng, max_distance_nm=200):
    """Find the nearest large airport to a given lat/lng using haversine distance.
    Returns dict with iata, name, lat, lng, distance_nm or None if no airport within range."""
    if not cached_airports:
        return None
    
    best = None
    best_dist = float('inf')
    
    lat_r = math.radians(lat)
    lng_r = math.radians(lng)
    
    for apt in cached_airports:
        apt_lat_r = math.radians(apt['lat'])
        apt_lng_r = math.radians(apt['lng'])
        
        dlat = apt_lat_r - lat_r
        dlng = apt_lng_r - lng_r
        a = math.sin(dlat / 2) ** 2 + math.cos(lat_r) * math.cos(apt_lat_r) * math.sin(dlng / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        dist_nm = 3440.065 * c  # Earth radius in nautical miles
        
        if dist_nm < best_dist:
            best_dist = dist_nm
            best = apt
    
    if best and best_dist <= max_distance_nm:
        return {
            "iata": best['iata'],
            "name": best['name'],
            "lat": best['lat'],
            "lng": best['lng'],
            "distance_nm": round(best_dist, 1)
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
                import csv
                import io
                f = io.StringIO(response.text)
                reader = csv.DictReader(f)
                for row in reader:
                    # Filter to only large international hubs that have an IATA code assigned
                    if row['type'] == 'large_airport' and row['iata_code']:
                        cached_airports.append({
                            "id": row['ident'],
                            "name": row['name'],
                            "iata": row['iata_code'],
                            "lat": float(row['latitude_deg']),
                            "lng": float(row['longitude_deg']),
                            "type": "airport"
                        })
                logger.info(f"Loaded {len(cached_airports)} large airports into cache.")
        except Exception as e:
            logger.error(f"Error fetching airports: {e}")
            
    latest_data['airports'] = cached_airports

from services.geopolitics import fetch_ukraine_frontlines, fetch_global_military_incidents

def fetch_geopolitics():
    logger.info("Fetching Geopolitics data...")
    try:
        frontlines = fetch_ukraine_frontlines()
        if frontlines:
            latest_data['frontlines'] = frontlines

        gdelt = fetch_global_military_incidents()
        if gdelt is not None:
            latest_data['gdelt'] = gdelt
    except Exception as e:
        logger.error(f"Error fetching geopolitics: {e}")

def update_liveuamap():
    logger.info("Running scheduled Liveuamap scraper...")
    try:
        from services.liveuamap_scraper import fetch_liveuamap
        res = fetch_liveuamap()
        if res:
            latest_data['liveuamap'] = res
    except Exception as e:
        logger.error(f"Liveuamap scraper error: {e}")

def update_fast_data():
    """Fast-tier: moving entities that need frequent updates (every 60s)."""
    logger.info("Fast-tier data update starting...")
    fast_funcs = [
        fetch_flights,
        fetch_military_flights,
        fetch_ships,
        fetch_uavs,
        fetch_satellites,
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(fast_funcs)) as executor:
        futures = [executor.submit(func) for func in fast_funcs]
        concurrent.futures.wait(futures)
    with _data_lock:
        latest_data['last_updated'] = datetime.utcnow().isoformat()
    logger.info("Fast-tier update complete.")

def update_slow_data():
    """Slow-tier: feeds that change infrequently (every 30min)."""
    logger.info("Slow-tier data update starting...")
    slow_funcs = [
        fetch_news,
        fetch_defense_stocks,
        fetch_oil_prices,
        fetch_weather,
        fetch_cctv,
        fetch_earthquakes,
        fetch_geopolitics,
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(slow_funcs)) as executor:
        futures = [executor.submit(func) for func in slow_funcs]
        concurrent.futures.wait(futures)
    logger.info("Slow-tier update complete.")

def update_all_data():
    """Full update — runs on startup. Fast and slow tiers run IN PARALLEL for fastest startup."""
    logger.info("Full data update starting (parallel)...")
    fetch_airports()  # Cached after first download
    # Run fast + slow in parallel so the user sees data ASAP
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(update_fast_data)
        f2 = pool.submit(update_slow_data)
        concurrent.futures.wait([f1, f2])
    logger.info("Full data update complete.")

scheduler = BackgroundScheduler()

def start_scheduler():
    init_db()
    
    # Run full update once on startup
    scheduler.add_job(update_all_data, 'date', run_date=datetime.now())
    
    # Fast tier: every 60 seconds (flights, ships, military, satellites, UAVs)
    scheduler.add_job(update_fast_data, 'interval', seconds=60)
    
    # Slow tier: every 30 minutes (news, stocks, weather, geopolitics)
    scheduler.add_job(update_slow_data, 'interval', minutes=30)
    
    # CCTV pipeline has its own cadence
    def update_cctvs():
        logger.info("Running CCTV Pipeline Ingestion...")
        ingestors = [
            TFLJamCamIngestor, 
            LTASingaporeIngestor, 
            AustinTXIngestor, 
            NYCDOTIngestor
        ]
        for ingestor in ingestors:
            try:
                ingestor().ingest()
            except Exception as e:
                logger.error(f"Failed {ingestor.__name__} cctv ingest: {e}")
        fetch_cctv()
            
    scheduler.add_job(update_cctvs, 'date', run_date=datetime.now())
    scheduler.add_job(update_cctvs, 'interval', minutes=1)
    
    # Liveuamap: startup + every 12 hours
    scheduler.add_job(update_liveuamap, 'date', run_date=datetime.now())
    scheduler.add_job(update_liveuamap, 'interval', hours=12)
    
    # Geopolitics (frontlines) more frequently than other slow data
    scheduler.add_job(fetch_geopolitics, 'interval', minutes=5)
    
    scheduler.start()

def stop_scheduler():
    scheduler.shutdown()

def get_latest_data():
    with _data_lock:
        return dict(latest_data)

