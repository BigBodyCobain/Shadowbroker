"""OpenClaw Watchdog — alert triggers that push to the agent automatically.

The agent registers watches (track a callsign, geofence a zone, monitor a
keyword in news). The watchdog runs in a background thread, checks telemetry
on each cycle, and pushes matching alerts as tasks via the command channel.

This is the missing piece between "polling 60MB" and "getting woken up when
something matters."
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_watches: dict[str, dict[str, Any]] = {}  # watch_id -> watch definition
_fired: dict[str, float] = {}  # watch_id -> last fire timestamp (debounce)
_running = False
_stop_event = threading.Event()

# Minimum seconds between re-firing the same watch
DEBOUNCE_S = 60.0
# How often the watchdog checks telemetry
POLL_INTERVAL_S = 15.0

_FLIGHT_LAYERS = (
    "tracked_flights",
    "military_flights",
    "private_jets",
    "private_flights",
    "commercial_flights",
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Watch CRUD
# ---------------------------------------------------------------------------

def add_watch(watch_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """Register a new watch. Returns the watch definition with ID."""
    watch_id = str(uuid.uuid4())[:8]
    watch = {
        "id": watch_id,
        "type": watch_type,
        "params": params,
        "created_at": time.time(),
        "fires": 0,
    }
    with _lock:
        _watches[watch_id] = watch
    _ensure_running()
    return watch


def remove_watch(watch_id: str) -> dict[str, Any]:
    """Remove a watch by ID."""
    with _lock:
        removed = _watches.pop(watch_id, None)
        _fired.pop(watch_id, None)
    if removed:
        return {"ok": True, "removed": removed}
    return {"ok": False, "detail": f"watch '{watch_id}' not found"}


def list_watches() -> list[dict[str, Any]]:
    """List all active watches."""
    with _lock:
        return list(_watches.values())


def clear_watches() -> dict[str, Any]:
    """Remove all watches."""
    with _lock:
        count = len(_watches)
        _watches.clear()
        _fired.clear()
    return {"ok": True, "cleared": count}


# ---------------------------------------------------------------------------
# Watch evaluation
# ---------------------------------------------------------------------------

def _evaluate_watches() -> list[dict[str, Any]]:
    """Check all watches against current telemetry. Returns list of alerts."""
    with _lock:
        watches = list(_watches.values())

    if not watches:
        return []

    # Load telemetry once for all watches
    try:
        from services.telemetry import get_cached_telemetry, get_cached_slow_telemetry
        fast = get_cached_telemetry() or {}
        slow = get_cached_slow_telemetry() or {}
    except Exception:
        return []

    alerts = []
    now = time.time()

    for watch in watches:
        wid = watch["id"]

        # Debounce
        with _lock:
            last = _fired.get(wid, 0)
        if now - last < DEBOUNCE_S:
            continue

        try:
            alert = _check_watch(watch, fast, slow)
            if alert:
                with _lock:
                    _fired[wid] = now
                    if wid in _watches:
                        _watches[wid]["fires"] = _watches[wid].get("fires", 0) + 1
                alerts.append({"watch_id": wid, "watch_type": watch["type"], **alert})
        except Exception as e:
            logger.warning("Watch %s evaluation error: %s", wid, e)

    return alerts


def _check_watch(watch: dict, fast: dict, slow: dict) -> dict[str, Any] | None:
    """Evaluate a single watch against telemetry. Returns alert dict or None."""
    wtype = watch["type"]
    params = watch["params"]

    if wtype == "track_aircraft":
        return _check_track_aircraft(params, fast)
    if wtype == "track_callsign":
        return _check_track_callsign(params, fast)
    if wtype == "track_registration":
        return _check_track_registration(params, fast)
    if wtype == "track_ship":
        return _check_track_ship(params, fast)
    if wtype == "track_entity":
        return _check_track_entity(params)
    if wtype == "geofence":
        return _check_geofence(params, fast)
    if wtype == "keyword":
        return _check_keyword(params, fast, slow)
    if wtype == "prediction_market":
        return _check_prediction_market(params, slow)

    return None


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _iter_flights(fast: dict) -> list[dict[str, Any]]:
    flights: list[dict[str, Any]] = []
    for layer in ("flights", *_FLIGHT_LAYERS):
        items = fast.get(layer, [])
        if isinstance(items, dict):
            items = items.get("items", []) or items.get("results", []) or items.get("flights", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                flight = dict(item)
                flight.setdefault("source_layer", layer)
                flights.append(flight)
    return flights


def _flight_payload(flight: dict[str, Any]) -> dict[str, Any]:
    return {
        "callsign": flight.get("callsign") or flight.get("flight") or flight.get("call"),
        "registration": flight.get("registration") or flight.get("r"),
        "icao24": flight.get("icao24"),
        "owner": flight.get("owner") or flight.get("operator") or flight.get("alert_operator"),
        "lat": flight.get("lat") or flight.get("latitude"),
        "lng": flight.get("lng") or flight.get("lon") or flight.get("longitude"),
        "altitude": flight.get("alt_baro") or flight.get("altitude") or flight.get("alt"),
        "speed": flight.get("gs") or flight.get("speed"),
        "heading": flight.get("track") or flight.get("heading"),
        "type": flight.get("t") or flight.get("type") or flight.get("aircraft_type"),
        "source_layer": flight.get("source_layer"),
    }


def _check_track_aircraft(params: dict, fast: dict) -> dict | None:
    """Track aircraft by callsign, registration, ICAO24, owner/operator, or query."""
    callsign = _norm(params.get("callsign"))
    registration = _norm(params.get("registration"))
    icao24 = _norm(params.get("icao24"))
    owner = _norm(params.get("owner") or params.get("operator"))
    query = _norm(params.get("query") or params.get("name"))
    if not any((callsign, registration, icao24, owner, query)):
        return None

    for flight in _iter_flights(fast):
        values = {
            "callsign": _norm(flight.get("callsign") or flight.get("flight") or flight.get("call")),
            "registration": _norm(flight.get("registration") or flight.get("r")),
            "icao24": _norm(flight.get("icao24")),
            "owner": _norm(flight.get("owner") or flight.get("operator") or flight.get("alert_operator")),
            "type": _norm(flight.get("type") or flight.get("t") or flight.get("aircraft_type")),
        }
        haystack = " ".join(v for v in values.values() if v)
        if callsign and callsign not in values["callsign"]:
            continue
        if registration and registration not in values["registration"]:
            continue
        if icao24 and icao24 != values["icao24"]:
            continue
        if owner and owner not in values["owner"]:
            continue
        if query and not all(token in haystack for token in query.split()):
            continue
        label = values["callsign"] or values["registration"] or values["icao24"] or query
        return {
            "alert": f"Aircraft {label.upper()} spotted",
            "data": _flight_payload(flight),
        }
    return None


def _check_track_callsign(params: dict, fast: dict) -> dict | None:
    """Track a specific aircraft by callsign."""
    target = str(params.get("callsign", "")).upper().strip()
    if not target:
        return None

    for flight in _iter_flights(fast):
        cs = str(flight.get("callsign", "") or flight.get("flight", "") or "").upper().strip()
        if cs == target:
            return {
                "alert": f"Aircraft {target} spotted",
                "data": _flight_payload(flight),
            }
    return None


def _check_track_registration(params: dict, fast: dict) -> dict | None:
    """Track a specific aircraft by registration (tail number)."""
    target = str(params.get("registration", "")).upper().strip()
    if not target:
        return None

    for flight in _iter_flights(fast):
        reg = str(flight.get("r") or flight.get("registration") or "").upper().strip()
        if reg == target:
            return {
                "alert": f"Aircraft {target} spotted",
                "data": _flight_payload(flight),
            }
    return None


def _check_track_ship(params: dict, fast: dict) -> dict | None:
    """Track a ship by MMSI or name."""
    target_mmsi = str(params.get("mmsi", "")).strip()
    target_imo = str(params.get("imo", "")).strip()
    target_name = str(params.get("name", "")).upper().strip()
    target_owner = str(params.get("owner", "") or params.get("operator", "")).upper().strip()
    target_query = str(params.get("query", "")).upper().strip()
    if not any((target_mmsi, target_imo, target_name, target_owner, target_query)):
        return None

    ships = fast.get("ships", [])
    if isinstance(ships, dict):
        ships = ships.get("vessels", [])

    for ship in ships:
        mmsi = str(ship.get("mmsi", "")).strip()
        imo = str(ship.get("imo", "")).strip()
        name = str(ship.get("name", "") or ship.get("shipName", "") or "").upper().strip()
        owner = str(ship.get("yacht_owner", "") or ship.get("owner", "")).upper().strip()
        callsign = str(ship.get("callsign", "")).upper().strip()
        haystack = " ".join(v for v in (name, owner, callsign, mmsi, imo) if v)
        if (
            (target_mmsi and mmsi == target_mmsi)
            or (target_imo and imo == target_imo)
            or (target_name and target_name in name)
            or (target_owner and target_owner in owner)
            or (target_query and all(token in haystack for token in target_query.split()))
        ):
            return {
                "alert": f"Ship {name or mmsi} spotted",
                "data": {
                    "mmsi": mmsi,
                    "imo": imo,
                    "name": name,
                    "owner": owner,
                    "lat": ship.get("lat") or ship.get("latitude"),
                    "lng": ship.get("lng") or ship.get("lon") or ship.get("longitude"),
                    "speed": ship.get("speed"),
                    "heading": ship.get("heading") or ship.get("course"),
                    "type": ship.get("shipType") or ship.get("type"),
                },
            }
    return None


def _check_track_entity(params: dict) -> dict | None:
    """Generic fallback watch using the compact universal search index."""
    query = str(params.get("query", "") or params.get("name", "")).strip()
    if not query:
        return None
    layers = params.get("layers") if isinstance(params.get("layers"), (list, tuple)) else None
    try:
        from services.telemetry import find_entity

        result = find_entity(
            query=query,
            entity_type=str(params.get("entity_type", "") or ""),
            layers=layers,
            limit=3,
        )
    except Exception:
        return None
    best = result.get("best_match")
    if not isinstance(best, dict):
        return None
    return {
        "alert": f"Entity {best.get('label') or query} found",
        "data": best,
    }


def _check_geofence(params: dict, fast: dict) -> dict | None:
    """Alert when any entity enters a geographic zone."""
    center_lat = float(params.get("lat", 0))
    center_lng = float(params.get("lng", 0))
    radius_km = float(params.get("radius_km", 50))
    entity_types = params.get("entity_types", ["flights", "ships"])

    matches = []

    for etype in entity_types:
        etype_norm = str(etype or "").strip().lower()
        if etype_norm in {"flights", "flight", "aircraft", "planes", "plane", "jets"}:
            items = _iter_flights(fast)
        else:
            items = fast.get(etype_norm, [])
        if isinstance(items, dict):
            items = items.get("vessels", items.get("items", []))
        if not isinstance(items, list):
            continue

        for item in items:
            lat = item.get("lat") or item.get("latitude")
            lng = item.get("lng") or item.get("lon") or item.get("longitude")
            if lat is None or lng is None:
                continue
            try:
                dist = _haversine_km(center_lat, center_lng, float(lat), float(lng))
            except (ValueError, TypeError):
                continue
            if dist <= radius_km:
                label = (item.get("callsign") or item.get("flight") or
                         item.get("name") or item.get("shipName") or
                         item.get("mmsi") or item.get("id") or "unknown")
                matches.append({
                    "label": str(label),
                    "type": etype,
                    "lat": float(lat),
                    "lng": float(lng),
                    "distance_km": round(dist, 1),
                })

    if matches:
        return {
            "alert": f"{len(matches)} entities inside geofence ({radius_km}km radius)",
            "data": {"center": {"lat": center_lat, "lng": center_lng},
                     "radius_km": radius_km, "matches": matches[:20]},
        }
    return None


def _check_keyword(params: dict, fast: dict, slow: dict) -> dict | None:
    """Alert when a keyword appears in news/GDELT."""
    keyword = str(params.get("keyword", "")).lower().strip()
    if not keyword:
        return None

    matches = []

    # Check news articles
    for article in slow.get("news", []):
        title = str(article.get("title", "") or "").lower()
        desc = str(article.get("description", "") or article.get("summary", "") or "").lower()
        if keyword in title or keyword in desc:
            matches.append({
                "source": "news",
                "title": article.get("title", ""),
                "url": article.get("url") or article.get("link"),
            })

    # Check GDELT
    for event in slow.get("gdelt", []):
        text = str(event.get("title", "") or event.get("sourceurl", "") or "").lower()
        if keyword in text:
            matches.append({
                "source": "gdelt",
                "title": event.get("title", ""),
                "url": event.get("sourceurl"),
            })

    if matches:
        return {
            "alert": f"Keyword '{keyword}' found in {len(matches)} articles",
            "data": {"keyword": keyword, "matches": matches[:10]},
        }
    return None


def _check_prediction_market(params: dict, slow: dict) -> dict | None:
    """Alert on prediction market movements."""
    query = str(params.get("query", "")).lower().strip()
    threshold = float(params.get("threshold", 0))  # 0 = any change

    markets = slow.get("prediction_markets", [])
    matches = []

    for market in markets:
        title = str(market.get("title", "") or market.get("question", "") or "").lower()
        if query and query not in title:
            continue
        prob = market.get("probability") or market.get("lastTradePrice") or market.get("yes_price")
        if prob is not None:
            try:
                prob = float(prob)
            except (ValueError, TypeError):
                continue
            if threshold and prob >= threshold:
                matches.append({
                    "title": market.get("title") or market.get("question"),
                    "probability": prob,
                })
            elif not threshold:
                matches.append({
                    "title": market.get("title") or market.get("question"),
                    "probability": prob,
                })

    if matches:
        return {
            "alert": f"{len(matches)} prediction markets match",
            "data": {"query": query, "matches": matches[:10]},
        }
    return None


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------

def _push_ws_alert(alert: dict) -> None:
    """Push an alert to connected WebSocket agents (thread-safe bridge)."""
    try:
        import asyncio
        from routers.ai_intel import broadcast_to_agents
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast_to_agents({
                "type": "alert",
                "alert": alert,
            }))
        else:
            loop.run_until_complete(broadcast_to_agents({
                "type": "alert",
                "alert": alert,
            }))
    except Exception:
        pass  # WS broadcast is best-effort, channel.push_task is the fallback


def _watchdog_loop():
    """Background thread that evaluates watches and pushes alerts."""
    global _running
    logger.info("OpenClaw watchdog started")

    while not _stop_event.is_set():
        try:
            alerts = _evaluate_watches()
            if alerts:
                from services.openclaw_channel import channel
                for alert in alerts:
                    channel.push_task("alert", alert)
                    _push_ws_alert(alert)
                    logger.info("Watchdog alert pushed: %s", alert.get("alert", ""))
        except Exception as e:
            logger.warning("Watchdog cycle error: %s", e)

        _stop_event.wait(POLL_INTERVAL_S)

    _running = False
    logger.info("OpenClaw watchdog stopped")


def _ensure_running():
    """Start the watchdog thread if not already running."""
    global _running
    with _lock:
        if _running:
            return
        _running = True
        _stop_event.clear()
    threading.Thread(target=_watchdog_loop, daemon=True, name="openclaw-watchdog").start()


def stop_watchdog():
    """Stop the watchdog thread."""
    _stop_event.set()
