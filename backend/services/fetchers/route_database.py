"""Static route + airport database loaded from vrs-standing-data.adsb.lol.

Replaces the per-batch /api/0/routeset POST with a single daily bulk download.
Routes change ~weekly when airlines update schedules, so a 24h refresh cadence
is far more than sufficient and removes ~all live-API pressure on adsb.lol.
"""

from __future__ import annotations

import csv
import gzip
import io
import logging
import threading
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

_ROUTES_URL = "https://vrs-standing-data.adsb.lol/routes.csv.gz"
_AIRPORTS_URL = "https://vrs-standing-data.adsb.lol/airports.csv.gz"
_REFRESH_INTERVAL_S = 5 * 24 * 3600
_HTTP_TIMEOUT_S = 60

_USER_AGENT = (
    "ShadowBroker-OSINT/0.9.7 "
    "(+https://github.com/BigBodyCobain/Shadowbroker; "
    "contact: bigbodycobain@gmail.com)"
)

_lock = threading.RLock()
_routes_by_callsign: dict[str, dict[str, Any]] = {}
_airports_by_icao: dict[str, dict[str, Any]] = {}
_last_refresh = 0.0
_refresh_in_progress = False


def _fetch_csv_gz(url: str) -> list[dict[str, str]]:
    response = requests.get(
        url,
        timeout=_HTTP_TIMEOUT_S,
        headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip"},
    )
    response.raise_for_status()
    text = gzip.decompress(response.content).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def _build_route_index(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        callsign = (row.get("Callsign") or "").strip().upper()
        airport_codes = (row.get("AirportCodes") or "").strip()
        if not callsign or not airport_codes:
            continue
        icaos = [c.strip() for c in airport_codes.split("-") if c.strip()]
        if len(icaos) < 2:
            continue
        index[callsign] = {
            "airline_code": (row.get("AirlineCode") or "").strip(),
            "airport_codes": airport_codes,
            "airport_icaos": icaos,
        }
    return index


def _build_airport_index(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        icao = (row.get("ICAO") or "").strip().upper()
        if not icao:
            continue
        try:
            lat = float(row.get("Latitude") or 0)
            lon = float(row.get("Longitude") or 0)
        except (TypeError, ValueError):
            continue
        index[icao] = {
            "name": (row.get("Name") or "").strip(),
            "iata": (row.get("IATA") or "").strip(),
            "country": (row.get("CountryISO2") or "").strip(),
            "lat": lat,
            "lon": lon,
        }
    return index


def refresh_route_database(force: bool = False) -> bool:
    """Pull routes.csv.gz + airports.csv.gz and rebuild the in-memory indexes.

    Returns True if a refresh was performed (success or attempted), False if
    skipped because the cache is still fresh or another refresh is in flight.
    """
    global _last_refresh, _refresh_in_progress

    now = time.time()
    with _lock:
        if _refresh_in_progress:
            return False
        if not force and (now - _last_refresh) < _REFRESH_INTERVAL_S and _routes_by_callsign:
            return False
        _refresh_in_progress = True

    try:
        started = time.time()
        airport_rows = _fetch_csv_gz(_AIRPORTS_URL)
        route_rows = _fetch_csv_gz(_ROUTES_URL)
        airports = _build_airport_index(airport_rows)
        routes = _build_route_index(route_rows)
        with _lock:
            _airports_by_icao.clear()
            _airports_by_icao.update(airports)
            _routes_by_callsign.clear()
            _routes_by_callsign.update(routes)
            _last_refresh = time.time()
        logger.info(
            "route database refreshed in %.1fs: %d routes, %d airports",
            time.time() - started,
            len(routes),
            len(airports),
        )
        return True
    except (requests.RequestException, OSError, ValueError) as exc:
        logger.warning("route database refresh failed: %s", exc)
        return True
    finally:
        with _lock:
            _refresh_in_progress = False


def lookup_route(callsign: str) -> dict[str, Any] | None:
    """Resolve a callsign to {orig_name, dest_name, orig_loc, dest_loc} or None.

    Matches the shape produced by the legacy fetch_routes_background cache so
    the caller in flights.py can be a drop-in replacement.
    """
    key = (callsign or "").strip().upper()
    if not key:
        return None
    with _lock:
        route = _routes_by_callsign.get(key)
        if not route:
            return None
        icaos = route["airport_icaos"]
        orig = _airports_by_icao.get(icaos[0].upper())
        dest = _airports_by_icao.get(icaos[-1].upper())
    if not orig or not dest:
        return None
    return {
        "orig_name": f"{orig['iata']}: {orig['name']}" if orig["iata"] else orig["name"],
        "dest_name": f"{dest['iata']}: {dest['name']}" if dest["iata"] else dest["name"],
        "orig_loc": [orig["lon"], orig["lat"]],
        "dest_loc": [dest["lon"], dest["lat"]],
    }


def route_database_status() -> dict[str, Any]:
    with _lock:
        return {
            "last_refresh": _last_refresh,
            "routes": len(_routes_by_callsign),
            "airports": len(_airports_by_icao),
            "in_progress": _refresh_in_progress,
        }
