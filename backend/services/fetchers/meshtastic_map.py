"""Meshtastic Map fetcher — pulls global node positions from meshtastic.liamcottle.net.

Bootstrap + top-up strategy:
  - On startup: fetch all nodes with positions to seed the map
  - Every 4 hours: refresh from the API
  - Persists to JSON cache so data survives restarts
  - MQTT bridge provides real-time updates between API fetches

API source: https://meshtastic.liamcottle.net/api/v1/nodes (community project by Liam Cottle)
Polling interval deliberately kept low (4h) to be respectful to the service.
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from services.fetchers._store import latest_data, _data_lock, _mark_fresh

logger = logging.getLogger("services.data_fetcher")

_API_URL = "https://meshtastic.liamcottle.net/api/v1/nodes"
_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "meshtastic_nodes_cache.json"
_FETCH_TIMEOUT = 90  # seconds — response is ~37MB, needs time on slow connections
_MAX_AGE_HOURS = 4  # discard nodes not seen within this window (matches refresh interval)

# Track when we last fetched so the frontend can show staleness
_last_fetch_ts: float = 0.0


def _parse_node(node: dict) -> dict | None:
    """Convert an API node into a slim signal-like dict."""
    lat_i = node.get("latitude")
    lng_i = node.get("longitude")
    if lat_i is None or lng_i is None:
        return None

    lat = lat_i / 1e7
    lng = lng_i / 1e7

    # Basic validity
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    if abs(lat) < 0.1 and abs(lng) < 0.1:
        return None

    callsign = node.get("node_id_hex", "")
    if not callsign:
        nid = node.get("node_id")
        callsign = f"!{int(nid):08x}" if nid else ""
    if not callsign:
        return None

    # Position age from API — reject nodes older than _MAX_AGE_HOURS
    pos_updated = node.get("position_updated_at") or node.get("updated_at", "")
    if pos_updated:
        try:
            ts = datetime.fromisoformat(pos_updated.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - ts > timedelta(hours=_MAX_AGE_HOURS):
                return None
        except (ValueError, TypeError):
            pass
    else:
        return None  # no timestamp at all — skip

    return {
        "callsign": callsign[:20],
        "lat": round(lat, 5),
        "lng": round(lng, 5),
        "source": "meshtastic",
        "confidence": 0.5,
        "timestamp": pos_updated,
        "position_updated_at": pos_updated,
        "from_api": True,
        "long_name": (node.get("long_name") or "")[:40],
        "short_name": (node.get("short_name") or "")[:4],
        "hardware": node.get("hardware_model_name", ""),
        "role": node.get("role_name", ""),
        "battery_level": node.get("battery_level"),
        "voltage": node.get("voltage"),
        "altitude": node.get("altitude"),
    }


def _is_fresh(node: dict) -> bool:
    """Check if a cached node is still within the _MAX_AGE_HOURS window."""
    ts_str = node.get("position_updated_at") or node.get("timestamp", "")
    if not ts_str:
        return False
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - ts <= timedelta(hours=_MAX_AGE_HOURS)
    except (ValueError, TypeError):
        return False


def _load_cache() -> list[dict]:
    """Load cached nodes from disk, filtering out stale entries."""
    if _CACHE_FILE.exists():
        try:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            nodes = data.get("nodes", [])
            fresh = [n for n in nodes if _is_fresh(n)]
            logger.info(f"Meshtastic map cache loaded: {len(fresh)} fresh / {len(nodes)} total")
            return fresh
        except Exception as e:
            logger.warning(f"Failed to load meshtastic cache: {e}")
    return []


def _save_cache(nodes: list[dict], fetch_ts: float):
    """Persist processed nodes to disk."""
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps(
                {
                    "fetched_at": fetch_ts,
                    "count": len(nodes),
                    "nodes": nodes,
                }
            ),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Failed to save meshtastic cache: {e}")


def fetch_meshtastic_nodes():
    """Fetch global Meshtastic node positions from Liam Cottle's map API.

    Stores processed nodes in latest_data["meshtastic_map_nodes"].
    Persists to JSON cache for restart resilience.
    """
    from services.fetchers._store import is_any_active

    if not is_any_active("sigint_meshtastic"):
        return
    global _last_fetch_ts

    try:
        logger.info("Fetching Meshtastic map nodes from API...")
        resp = requests.get(
            _API_URL,
            timeout=_FETCH_TIMEOUT,
            headers={
                "User-Agent": "ShadowBroker/1.0 (OSINT dashboard, 4h polling)",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()

        raw = resp.json()
        raw_nodes = raw.get("nodes", []) if isinstance(raw, dict) else raw

        # Parse and filter to only nodes with valid positions
        parsed = []
        for node in raw_nodes:
            sig = _parse_node(node)
            if sig:
                parsed.append(sig)

        _last_fetch_ts = time.time()
        _save_cache(parsed, _last_fetch_ts)

        with _data_lock:
            latest_data["meshtastic_map_nodes"] = parsed
            latest_data["meshtastic_map_fetched_at"] = _last_fetch_ts
        try:
            from services.fetchers.sigint import refresh_sigint_snapshot

            refresh_sigint_snapshot()
        except Exception as exc:
            logger.debug(f"Meshtastic map: SIGINT snapshot refresh skipped: {exc}")

        logger.info(
            f"Meshtastic map: {len(parsed)} nodes with positions " f"(from {len(raw_nodes)} total)"
        )

    except Exception as e:
        logger.error(f"Meshtastic map fetch failed: {e}")
        # Fall back to cache if available and we have nothing in memory
        with _data_lock:
            if not latest_data.get("meshtastic_map_nodes"):
                cached = _load_cache()
                if cached:
                    latest_data["meshtastic_map_nodes"] = cached
                    latest_data["meshtastic_map_fetched_at"] = (
                        _CACHE_FILE.stat().st_mtime if _CACHE_FILE.exists() else 0
                    )
                    logger.info(
                        f"Meshtastic map: using {len(cached)} cached nodes (API unavailable)"
                    )
                    try:
                        from services.fetchers.sigint import refresh_sigint_snapshot

                        refresh_sigint_snapshot()
                    except Exception as exc:
                        logger.debug(f"Meshtastic map cache: SIGINT snapshot refresh skipped: {exc}")

    _mark_fresh("meshtastic_map")


def load_meshtastic_cache_if_available():
    """On startup, load cached nodes immediately (before first API fetch)."""
    global _last_fetch_ts
    cached = _load_cache()
    if cached:
        with _data_lock:
            latest_data["meshtastic_map_nodes"] = cached
            _last_fetch_ts = _CACHE_FILE.stat().st_mtime if _CACHE_FILE.exists() else 0
            latest_data["meshtastic_map_fetched_at"] = _last_fetch_ts
        try:
            from services.fetchers.sigint import refresh_sigint_snapshot

            refresh_sigint_snapshot()
        except Exception as exc:
            logger.debug(f"Meshtastic preload: SIGINT snapshot refresh skipped: {exc}")
        logger.info(f"Meshtastic map: preloaded {len(cached)} nodes from cache")
