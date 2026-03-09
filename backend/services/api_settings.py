"""
API Settings management — serves the API key registry and allows updates.
Keys are stored in the backend .env file and loaded via python-dotenv.
"""
import os
import re
from pathlib import Path

# Path to the backend .env file
ENV_PATH = Path(__file__).parent.parent / ".env"

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
]


def _obfuscate(value: str) -> str:
    """Show first 4 chars, mask the rest with bullets."""
    if not value or len(value) <= 4:
        return "••••••••"
    return value[:4] + "•" * (len(value) - 4)


def get_api_keys():
    """Return the full API registry with obfuscated key values."""
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
            "value_obfuscated": None,
            "is_set": False,
        }
        if api["env_key"]:
            raw = os.environ.get(api["env_key"], "")
            entry["value_obfuscated"] = _obfuscate(raw)
            entry["is_set"] = bool(raw)
        result.append(entry)
    return result


def update_api_key(env_key: str, new_value: str) -> bool:
    """Update a single key in the .env file and in the current process env."""
    if not ENV_PATH.exists():
        return False

    # Update os.environ immediately
    os.environ[env_key] = new_value

    # Update the .env file on disk
    content = ENV_PATH.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(env_key)}=.*$", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(f"{env_key}={new_value}", content)
    else:
        content = content.rstrip("\n") + f"\n{env_key}={new_value}\n"

    ENV_PATH.write_text(content, encoding="utf-8")
    return True
