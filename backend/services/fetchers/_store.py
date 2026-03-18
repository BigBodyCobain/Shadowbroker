"""Shared in-memory data store for all fetcher modules.

Central location for latest_data, source_timestamps, and the data lock.
Every fetcher imports from here instead of maintaining its own copy.
"""
import threading
import logging
from datetime import datetime

logger = logging.getLogger("services.data_fetcher")

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
    "eth_nodes": []
}

# Per-source freshness timestamps
source_timestamps = {}

def _mark_fresh(*keys):
    """Record the current UTC time for one or more data source keys."""
    now = datetime.utcnow().isoformat()
    for k in keys:
        source_timestamps[k] = now

# Thread lock for safe reads/writes to latest_data
_data_lock = threading.Lock()
