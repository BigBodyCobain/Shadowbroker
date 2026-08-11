"""
API Settings management — serves the API key registry and allows updates.
Keys are stored in the backend .env file and loaded via python-dotenv.
"""

import os
import re
import tempfile
import threading
from pathlib import Path

# Path to the backend .env file
ENV_PATH = Path(__file__).parent.parent / ".env"
# Path to the example template that ships with the repo
ENV_EXAMPLE_PATH = Path(__file__).parent.parent.parent / ".env.example"
DATA_DIR = Path(os.environ.get("SB_DATA_DIR", str(Path(__file__).parent.parent / "data")))
if not DATA_DIR.is_absolute():
    DATA_DIR = Path(__file__).parent.parent / DATA_DIR
OPERATOR_KEYS_ENV_PATH = Path(
    os.environ.get("SHADOWBROKER_OPERATOR_KEYS_ENV", str(DATA_DIR / "operator_api_keys.env"))
)
OPENCLAW_ENV_PATH = Path(
    os.environ.get("SHADOWBROKER_OPENCLAW_ENV", str(DATA_DIR / "openclaw.env"))
)
OPENCLAW_PERSISTED_KEYS = frozenset({"OPENCLAW_HMAC_SECRET", "OPENCLAW_ACCESS_TIER"})
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

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
        "id": "aishub_username",
        "env_key": "AISHUB_USERNAME",
        "name": "AISHub Username (backup)",
        "description": "Free AISHub account username used as a slow REST backup when AISStream is silent or offline. Does not replace live AIS — polls about every 20 minutes into the same ships layer. Register at aishub.net/api.",
        "category": "Maritime",
        "url": "https://www.aishub.net/api",
        "required": False,
    },
    {
        "id": "gfw_api_token",
        "env_key": "GFW_API_TOKEN",
        "name": "Global Fishing Watch",
        "description": "Bearer token for Global Fishing Watch fishing-vessel activity events (Fishing Activity map layer). Free registration at globalfishingwatch.org.",
        "category": "Maritime",
        "url": "https://globalfishingwatch.org/our-apis/",
        "required": False,
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
        "id": "firms_map_key",
        "env_key": "FIRMS_MAP_KEY",
        "name": "NASA FIRMS — MAP Key (optional)",
        "description": "Optional NASA Earthdata MAP key for country-scoped VIIRS fire enrichment. Global VIIRS hotspots work without a key; set this only if you want per-country FIRMS detail. Free from NASA Earthdata.",
        "category": "Geophysical",
        "url": "https://firms.modaps.eosdis.nasa.gov/api/area/",
        "required": False,
    },
    {
        "id": "airframes_api_key",
        "env_key": "AIRFRAMES_API_KEY",
        "name": "Airframes.io — API Key",
        "description": "ACARS/VDL datalink for plane dossiers. ShadowBroker bulk-ingests the global Airframes firehose (up to 100 messages per API call, one call every 2s, refill every 15 minutes) and indexes by tail/ICAO. Opening a dossier with no cache queues a single-plane lookup. Get a key at app.airframes.io → Dashboard → API Key.",
        "category": "Aviation",
        "url": "https://app.airframes.io/user/dashboard",
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
    # Issue #298 (tg12): Sentinel Hub / Copernicus Data Space Ecosystem
    # credentials were previously held in browser localStorage / sessionStorage
    # by the Settings panel. Moved server-side to the same .env-backed
    # store every other third-party API key lives in. The Sentinel proxy
    # routes (POST /api/sentinel/token, /tile) now fall back to these
    # env values when the request body omits credentials — see
    # backend/routers/tools.py for the resolution order.
    {
        "id": "sentinel_client_id",
        "env_key": "SENTINEL_CLIENT_ID",
        "name": "Sentinel Hub / Copernicus — Client ID",
        "description": "OAuth2 client ID for Copernicus Data Space Ecosystem (CDSE). Required for the Sentinel-2 imagery overlay and the right-click Sentinel-2 Intel Card. Sign in at dataspace.copernicus.eu and create OAuth credentials.",
        "category": "Imagery",
        "url": "https://dataspace.copernicus.eu/",
        "required": False,
    },
    {
        "id": "sentinel_client_secret",
        "env_key": "SENTINEL_CLIENT_SECRET",
        "name": "Sentinel Hub / Copernicus — Client Secret",
        "description": "OAuth2 client secret paired with the Client ID above. Used by the backend to mint short-lived access tokens against the CDSE identity provider. Stored in the backend .env; never sent to the browser.",
        "category": "Imagery",
        "url": "https://dataspace.copernicus.eu/",
        "required": False,
    },
]

ALLOWED_ENV_KEYS = {
    str(api["env_key"])
    for api in API_REGISTRY
    if api.get("env_key")
}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _ENV_KEY_RE.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _quote_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _write_env_values(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if "=" not in stripped or stripped.startswith("#"):
            next_lines.append(raw_line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            next_lines.append(f"{key}={_quote_env_value(updates[key])}")
            seen.add(key)
        else:
            next_lines.append(raw_line)
    for key, value in updates.items():
        if key not in seen:
            next_lines.append(f"{key}={_quote_env_value(value)}")

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.tmp.", text=True)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(next_lines).rstrip() + "\n")
        if os.name != "nt":
            os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def load_persisted_api_keys_into_environ() -> None:
    """Load persisted operator API keys if no process env value exists."""
    for key, value in _parse_env_file(OPERATOR_KEYS_ENV_PATH).items():
        if key in ALLOWED_ENV_KEYS and value and not os.environ.get(key):
            os.environ[key] = value


def load_persisted_openclaw_into_environ() -> None:
    """Load OpenClaw secrets from the data volume when env is unset/empty.

    Docker Compose often injects ``OPENCLAW_HMAC_SECRET=`` as an empty string,
    which blocks pydantic from reading backend/.env. Persisting bootstrap output
    under ``data/openclaw.env`` (on the backend_data volume) keeps remote HMAC
    working across container restarts (#424).
    """
    persisted = _parse_env_file(OPENCLAW_ENV_PATH)
    if not persisted.get("OPENCLAW_HMAC_SECRET"):
        # One-time migration from legacy backend/.env writes inside the image.
        persisted = {**_parse_env_file(ENV_PATH), **persisted}

    for key, value in persisted.items():
        if key not in OPENCLAW_PERSISTED_KEYS:
            continue
        cleaned = str(value or "").strip()
        if cleaned and not str(os.environ.get(key, "")).strip():
            os.environ[key] = cleaned


def persist_openclaw_env_value(key: str, value: str) -> None:
    """Persist OpenClaw runtime settings to the data volume."""
    if key not in OPENCLAW_PERSISTED_KEYS:
        return
    _write_env_values(OPENCLAW_ENV_PATH, {key: value})


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
        "operator_keys_env_path": str(OPERATOR_KEYS_ENV_PATH.resolve()),
        "operator_keys_env_path_exists": OPERATOR_KEYS_ENV_PATH.exists(),
        "operator_keys_env_path_writable": os.access(OPERATOR_KEYS_ENV_PATH.parent, os.W_OK)
            and (not OPERATOR_KEYS_ENV_PATH.exists() or os.access(OPERATOR_KEYS_ENV_PATH, os.W_OK)),
        "openclaw_env_path": str(OPENCLAW_ENV_PATH.resolve()),
        "openclaw_env_path_exists": OPENCLAW_ENV_PATH.exists(),
        "openclaw_env_path_writable": os.access(OPENCLAW_ENV_PATH.parent, os.W_OK)
            and (not OPENCLAW_ENV_PATH.exists() or os.access(OPENCLAW_ENV_PATH, os.W_OK)),
    }


def get_api_keys():
    """Return the API registry with a binary set/unset flag per key.

    Key values themselves are NEVER returned to the client — not even an
    obfuscated prefix. Users edit the .env file directly; the panel uses
    `is_set` to render a CONFIGURED / NOT CONFIGURED badge and the path
    info from `get_env_path_info()` to tell them where to put each key.
    """
    load_persisted_api_keys_into_environ()
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


def save_api_keys(updates: dict[str, str]) -> dict:
    """Persist allowed API keys from a local operator request.

    Values are accepted write-only: the response includes only configured flags.
    """
    clean: dict[str, str] = {}
    for key, value in updates.items():
        env_key = str(key or "").strip().upper()
        if env_key not in ALLOWED_ENV_KEYS:
            continue
        clean_value = str(value or "").strip()
        if clean_value:
            clean[env_key] = clean_value
    if not clean:
        return {"ok": False, "detail": "No supported API keys were provided."}

    _write_env_values(OPERATOR_KEYS_ENV_PATH, clean)
    try:
        _write_env_values(ENV_PATH, clean)
    except OSError:
        # The persistent operator key file is the source of truth for Docker.
        pass
    for key, value in clean.items():
        os.environ[key] = value
    if "AIS_API_KEY" in clean:
        try:
            from services import ais_stream
            ais_stream.API_KEY = clean["AIS_API_KEY"]
        except Exception:
            pass
    if "OPENSKY_CLIENT_ID" in clean or "OPENSKY_CLIENT_SECRET" in clean:
        try:
            from services.fetchers import flights
            flights.opensky_client.client_id = os.environ.get("OPENSKY_CLIENT_ID", "")
            flights.opensky_client.client_secret = os.environ.get("OPENSKY_CLIENT_SECRET", "")
            flights.opensky_client.token = None
            flights.opensky_client.expires_at = 0
        except Exception:
            pass
    if "AIRFRAMES_API_KEY" in clean:
        try:
            from services.fetchers.airframes import sync_airframes_messages

            threading.Thread(
                target=lambda: sync_airframes_messages(force=True),
                daemon=True,
                name="airframes-initial-sync",
            ).start()
        except Exception:
            pass

    try:
        from services.config import get_settings
        get_settings.cache_clear()
    except Exception:
        pass

    return {
        "ok": True,
        "updated": sorted(clean.keys()),
        "keys": get_api_keys(),
        "env": get_env_path_info(),
    }
