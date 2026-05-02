"""
API Settings management — serves the API key registry and allows updates.
Keys are stored in the backend .env file and loaded via python-dotenv.
"""

import os
from pathlib import Path

# Path to the backend .env file
ENV_PATH = Path(__file__).parent.parent / ".env"
# Path to the example template that ships with the repo
ENV_EXAMPLE_PATH = Path(__file__).parent.parent.parent / ".env.example"

# ---------------------------------------------------------------------------
# API Registry — every external service the dashboard depends on
# ---------------------------------------------------------------------------
API_REGISTRY = [
    {
        "id": "opensky_client_id",
        "env_key": "OPENSKY_CLIENT_ID",
        "name": "OpenSky Network — Client ID",
        "description": "OAuth2 client ID for the OpenSky Network API. Provides global flight state vectors with 400 requests/day.",
        "category": "Aviation",
        "url": "https://opensky-network.org/",
        "required": True,
    },
    {
        "id": "opensky_client_secret",
        "env_key": "OPENSKY_CLIENT_SECRET",
        "name": "OpenSky Network — Client Secret",
        "description": "OAuth2 client secret paired with the Client ID above. Used for authenticated token refresh.",
        "category": "Aviation",
        "url": "https://opensky-network.org/",
        "required": True,
    },
    {
        "id": "ais_api_key",
        "env_key": "AIS_API_KEY",
        "name": "AIS Stream",
        "description": "WebSocket API key for real-time Automatic Identification System (AIS) vessel tracking data worldwide.",
        "category": "Maritime",
        "url": "https://aisstream.io/",
        "required": True,
    },
    {
        "id": "adsb_lol",
        "env_key": None,
        "name": "ADS-B Exchange (adsb.lol)",
        "description": "Community-maintained ADS-B flight tracking API. No key required — public endpoint.",
        "category": "Aviation",
        "url": "https://api.adsb.lol/",
        "required": False,
    },
    {
        "id": "usgs_earthquakes",
        "env_key": None,
        "name": "USGS Earthquake Hazards",
        "description": "Real-time earthquake data feed from the United States Geological Survey. No key required.",
        "category": "Geophysical",
        "url": "https://earthquake.usgs.gov/",
        "required": False,
    },
    {
        "id": "celestrak",
        "env_key": None,
        "name": "CelesTrak (NORAD TLEs)",
        "description": "Satellite orbital element data from CelesTrak. Provides TLE sets for 2,000+ active satellites. No key required.",
        "category": "Space",
        "url": "https://celestrak.org/",
        "required": False,
    },
    {
        "id": "gdelt",
        "env_key": None,
        "name": "GDELT Project",
        "description": "Global Database of Events, Language, and Tone. Monitors news media for geopolitical events worldwide. No key required.",
        "category": "Intelligence",
        "url": "https://www.gdeltproject.org/",
        "required": False,
    },
    {
        "id": "nominatim",
        "env_key": None,
        "name": "Nominatim (OpenStreetMap)",
        "description": "Reverse geocoding service. Converts lat/lng coordinates to human-readable location names. No key required.",
        "category": "Geolocation",
        "url": "https://nominatim.openstreetmap.org/",
        "required": False,
    },
    {
        "id": "rainviewer",
        "env_key": None,
        "name": "RainViewer",
        "description": "Weather radar tile overlay. Provides global precipitation data as map tiles. No key required.",
        "category": "Weather",
        "url": "https://www.rainviewer.com/",
        "required": False,
    },
    {
        "id": "rss_feeds",
        "env_key": None,
        "name": "RSS News Feeds",
        "description": "Aggregates from NPR, BBC, Al Jazeera, NYT, Reuters, and AP for global news coverage. No key required.",
        "category": "Intelligence",
        "url": None,
        "required": False,
    },
    {
        "id": "yfinance",
        "env_key": None,
        "name": "Yahoo Finance (yfinance)",
        "description": "Defense sector stock tickers and commodity prices. Uses the yfinance Python library. No key required.",
        "category": "Markets",
        "url": "https://finance.yahoo.com/",
        "required": False,
    },
    {
        "id": "openmhz",
        "env_key": None,
        "name": "OpenMHz",
        "description": "Public radio scanner feeds for SIGINT interception. Streams police/fire/EMS radio traffic. No key required.",
        "category": "SIGINT",
        "url": "https://openmhz.com/",
        "required": False,
    },
    {
        "id": "shodan_api_key",
        "env_key": "SHODAN_API_KEY",
        "name": "Shodan — Operator API Key",
        "description": "Paid Shodan API key for local operator-driven searches and temporary map overlays. Results are attributed to Shodan and are not merged into ShadowBroker core feeds.",
        "category": "Reconnaissance",
        "url": "https://account.shodan.io/billing",
        "required": False,
    },
    {
        "id": "finnhub_api_key",
        "env_key": "FINNHUB_API_KEY",
        "name": "Finnhub — API Key",
        "description": "Free market data API. Defense stock quotes, congressional trading disclosures, and insider transactions. 60 calls/min free tier.",
        "category": "Financial",
        "url": "https://finnhub.io/register",
        "required": False,
    },
]


def get_env_path_info() -> dict:
    """Return absolute paths for the backend .env and .env.example template.

    Surfaced to the frontend so the API Keys settings panel can tell users
    exactly where to put their keys when in-app editing fails (admin-not-set,
    file permissions, read-only filesystem, etc.).
    """
    env_path = ENV_PATH.resolve()
    example_path = ENV_EXAMPLE_PATH.resolve()
    return {
        "env_path": str(env_path),
        "env_path_exists": env_path.exists(),
        "env_path_writable": os.access(env_path.parent, os.W_OK)
            and (not env_path.exists() or os.access(env_path, os.W_OK)),
        "env_example_path": str(example_path),
        "env_example_path_exists": example_path.exists(),
    }


def get_api_keys():
    """Return the API registry with a binary set/unset flag per key.

    Key values themselves are NEVER returned to the client — not even an
    obfuscated prefix. Users edit the .env file directly; the panel uses
    `is_set` to render a CONFIGURED / NOT CONFIGURED badge and the path
    info from `get_env_path_info()` to tell them where to put each key.
    """
    result = []
    for api in API_REGISTRY:
        entry = {
            "id": api["id"],
            "name": api["name"],
            "description": api["description"],
            "category": api["category"],
            "url": api["url"],
            "required": api["required"],
            "has_key": api["env_key"] is not None,
            "env_key": api["env_key"],
            "is_set": False,
        }
        if api["env_key"]:
            raw = os.environ.get(api["env_key"], "")
            entry["is_set"] = bool(raw)
        result.append(entry)
    return result
