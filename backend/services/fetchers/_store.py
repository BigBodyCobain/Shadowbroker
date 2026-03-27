"""Shared in-memory data store for all fetcher modules.

Central location for latest_data, source_timestamps, and the data lock.
Every fetcher imports from here instead of maintaining its own copy.
"""

import threading
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

logger = logging.getLogger("services.data_fetcher")


class DashboardData(TypedDict, total=False):
    """Schema for the in-memory data store. Catches key typos at dev time."""

    last_updated: Optional[str]
    news: List[Dict[str, Any]]
    stocks: Dict[str, Any]
    oil: Dict[str, Any]
    commercial_flights: List[Dict[str, Any]]
    private_flights: List[Dict[str, Any]]
    private_jets: List[Dict[str, Any]]
    flights: List[Dict[str, Any]]
    ships: List[Dict[str, Any]]
    military_flights: List[Dict[str, Any]]
    tracked_flights: List[Dict[str, Any]]
    cctv: List[Dict[str, Any]]
    weather: Optional[Dict[str, Any]]
    earthquakes: List[Dict[str, Any]]
    uavs: List[Dict[str, Any]]
    frontlines: Optional[Any]
    gdelt: List[Dict[str, Any]]
    liveuamap: List[Dict[str, Any]]
    kiwisdr: List[Dict[str, Any]]
    space_weather: Optional[Dict[str, Any]]
    internet_outages: List[Dict[str, Any]]
    firms_fires: List[Dict[str, Any]]
    datacenters: List[Dict[str, Any]]
    airports: List[Dict[str, Any]]
    gps_jamming: List[Dict[str, Any]]
    satellites: List[Dict[str, Any]]
    satellite_source: str
    prediction_markets: List[Dict[str, Any]]
    sigint: List[Dict[str, Any]]
    sigint_totals: Dict[str, Any]
    mesh_channel_stats: Dict[str, Any]
    meshtastic_map_nodes: List[Dict[str, Any]]
    meshtastic_map_fetched_at: Optional[float]
    weather_alerts: List[Dict[str, Any]]
    air_quality: List[Dict[str, Any]]
    volcanoes: List[Dict[str, Any]]
    fishing_activity: List[Dict[str, Any]]
    satnogs_stations: List[Dict[str, Any]]
    satnogs_observations: List[Dict[str, Any]]
    tinygs_satellites: List[Dict[str, Any]]
    ukraine_alerts: List[Dict[str, Any]]
    power_plants: List[Dict[str, Any]]
    viirs_change_nodes: List[Dict[str, Any]]
    fimi: Dict[str, Any]
    psk_reporter: List[Dict[str, Any]]
    correlations: List[Dict[str, Any]]


# In-memory store
latest_data: DashboardData = {
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
    "earthquakes": [],
    "uavs": [],
    "frontlines": None,
    "gdelt": [],
    "liveuamap": [],
    "kiwisdr": [],
    "space_weather": None,
    "internet_outages": [],
    "firms_fires": [],
    "datacenters": [],
    "military_bases": [],
    "prediction_markets": [],
    "sigint": [],
    "sigint_totals": {},
    "mesh_channel_stats": {},
    "meshtastic_map_nodes": [],
    "meshtastic_map_fetched_at": None,
    "weather_alerts": [],
    "air_quality": [],
    "volcanoes": [],
    "fishing_activity": [],
    "satnogs_stations": [],
    "satnogs_observations": [],
    "tinygs_satellites": [],
    "ukraine_alerts": [],
    "power_plants": [],
    "viirs_change_nodes": [],
    "fimi": {},
    "psk_reporter": [],
    "correlations": [],
}

# Per-source freshness timestamps
source_timestamps = {}

# Per-source health/freshness metadata (last ok/error)
source_freshness: dict[str, dict] = {}


def _mark_fresh(*keys):
    """Record the current UTC time for one or more data source keys."""
    now = datetime.utcnow().isoformat()
    with _data_lock:
        for k in keys:
            source_timestamps[k] = now


# Thread lock for safe reads/writes to latest_data
_data_lock = threading.Lock()

# Monotonic version counter — incremented on each data update cycle.
# Used for cheap ETag generation instead of MD5-hashing the full response.
_data_version: int = 0


def bump_data_version() -> None:
    """Increment the data version counter after a fetch cycle completes."""
    global _data_version
    _data_version += 1


def get_data_version() -> int:
    """Return the current data version (for ETag generation)."""
    return _data_version


_active_layers_version: int = 0


def bump_active_layers_version() -> None:
    """Increment the active-layer version when frontend toggles change response shape."""
    global _active_layers_version
    _active_layers_version += 1


def get_active_layers_version() -> int:
    """Return the current active-layer version (for ETag generation)."""
    return _active_layers_version


def get_latest_data_subset(*keys: str) -> DashboardData:
    """Return a shallow snapshot of only the requested top-level keys.

    This avoids cloning the entire dashboard store for endpoints that only need
    a small tier-specific subset.
    """
    with _data_lock:
        snap: DashboardData = {}
        for key in keys:
            value = latest_data.get(key)
            if isinstance(value, list):
                snap[key] = list(value)
            elif isinstance(value, dict):
                snap[key] = dict(value)
            else:
                snap[key] = value
        return snap


def get_latest_data_subset_refs(*keys: str) -> DashboardData:
    """Return direct top-level references for read-only hot paths.

    Writers replace top-level values under the lock instead of mutating them
    in place, so readers can safely use these references after releasing the
    lock as long as they do not modify them.
    """
    with _data_lock:
        snap: DashboardData = {}
        for key in keys:
            snap[key] = latest_data.get(key)
        return snap


def get_source_timestamps_snapshot() -> dict[str, str]:
    """Return a stable copy of per-source freshness timestamps."""
    with _data_lock:
        return dict(source_timestamps)


# ---------------------------------------------------------------------------
# Active layers — frontend POSTs toggles, fetchers check before running.
# Keep these aligned with the dashboard's default layer state so startup does
# not fetch heavyweight feeds the UI starts with disabled.
# ---------------------------------------------------------------------------
active_layers: dict[str, bool] = {
    "flights": True,
    "private": True,
    "jets": True,
    "military": True,
    "tracked": True,
    "satellites": True,
    "ships_military": True,
    "ships_cargo": True,
    "ships_civilian": True,
    "ships_passenger": True,
    "ships_tracked_yachts": True,
    "earthquakes": True,
    "cctv": True,
    "ukraine_frontline": True,
    "global_incidents": True,
    "gps_jamming": True,
    "kiwisdr": True,
    "scanners": True,
    "firms": True,
    "internet_outages": True,
    "datacenters": True,
    "military_bases": True,
    "sigint_meshtastic": True,
    "sigint_aprs": True,
    "weather_alerts": True,
    "air_quality": True,
    "volcanoes": True,
    "fishing_activity": True,
    "satnogs": True,
    "tinygs": True,
    "ukraine_alerts": True,
    "power_plants": False,
    "viirs_nightlights": False,
    "psk_reporter": True,
    "correlations": True,
}


def is_any_active(*layer_names: str) -> bool:
    """Return True if any of the given layer names is currently active."""
    return any(active_layers.get(name, True) for name in layer_names)
