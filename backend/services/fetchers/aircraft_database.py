"""OpenSky aircraft metadata: ICAO24 hex -> ICAO type code + friendly model.

OpenSky's /states/all does not include aircraft type, so OpenSky-sourced
flights arrive with ``t`` field empty. This module bulk-loads the public
OpenSky aircraft database (one snapshot CSV per month, ~108 MB uncompressed,
~600k aircraft) once every 5 days and exposes a fast in-memory hex lookup.

The data is also useful when adsb.lol's live API is degraded: even the
adsb.lol /v2 feed sometimes returns aircraft with empty ``t`` for newly seen
transponders, and the lookup gracefully fills those in too.
"""

from __future__ import annotations

import csv
import logging
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BUCKET_LIST_URL = (
    "https://s3.opensky-network.org/data-samples?prefix=metadata/&list-type=2"
)
_BUCKET_BASE = "https://s3.opensky-network.org/data-samples/"
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_REFRESH_INTERVAL_S = 5 * 24 * 3600
_LIST_TIMEOUT_S = 30
_DOWNLOAD_TIMEOUT_S = 600
_USER_AGENT = (
    "ShadowBroker-OSINT/0.9.7 "
    "(+https://github.com/BigBodyCobain/Shadowbroker; "
    "contact: bigbodycobain@gmail.com)"
)

_lock = threading.RLock()
_aircraft_by_hex: dict[str, dict[str, str]] = {}
_last_refresh = 0.0
_in_progress = False


def _latest_snapshot_key() -> str:
    """Discover the most recent aircraft-database-complete snapshot key."""
    response = requests.get(
        _BUCKET_LIST_URL,
        timeout=_LIST_TIMEOUT_S,
        headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    keys: list[str] = []
    for content in root.iter(f"{_S3_NS}Contents"):
        key_el = content.find(f"{_S3_NS}Key")
        if key_el is None or not key_el.text:
            continue
        if "aircraft-database-complete-" in key_el.text and key_el.text.endswith(".csv"):
            keys.append(key_el.text)
    if not keys:
        raise RuntimeError("no aircraft-database-complete snapshot found in bucket listing")
    return sorted(keys)[-1]


def _stream_csv_index(url: str) -> dict[str, dict[str, str]]:
    """Stream-parse the OpenSky aircraft CSV into a hex-keyed index.

    The CSV uses single-quote quoting, so csv.DictReader is configured with
    ``quotechar="'"``. Rows are processed line-by-line via iter_lines() to
    keep memory bounded even though the file is ~108 MB.
    """
    with requests.get(
        url,
        timeout=_DOWNLOAD_TIMEOUT_S,
        stream=True,
        headers={"User-Agent": _USER_AGENT},
    ) as response:
        response.raise_for_status()
        line_iter = (
            line.decode("utf-8", errors="replace")
            for line in response.iter_lines(decode_unicode=False)
            if line
        )
        reader = csv.DictReader(line_iter, quotechar="'")
        index: dict[str, dict[str, str]] = {}
        for row in reader:
            hex_code = (row.get("icao24") or "").strip().lower()
            if not hex_code or hex_code == "000000":
                continue
            typecode = (row.get("typecode") or "").strip().upper()
            model = (row.get("model") or "").strip()
            mfr = (row.get("manufacturerName") or "").strip()
            registration = (row.get("registration") or "").strip().upper()
            operator = (row.get("operator") or "").strip()
            if not (typecode or model):
                continue
            entry: dict[str, str] = {}
            if typecode:
                entry["typecode"] = typecode
            if model:
                entry["model"] = model
            if mfr:
                entry["manufacturer"] = mfr
            if registration:
                entry["registration"] = registration
            if operator:
                entry["operator"] = operator
            index[hex_code] = entry
    return index


def refresh_aircraft_database(force: bool = False) -> bool:
    """Download the latest OpenSky aircraft snapshot and rebuild the index.

    Returns True if a refresh was performed (success or attempted), False if
    skipped because the cache is still fresh or another refresh is in flight.
    """
    global _last_refresh, _in_progress

    now = time.time()
    with _lock:
        if _in_progress:
            return False
        if not force and (now - _last_refresh) < _REFRESH_INTERVAL_S and _aircraft_by_hex:
            return False
        _in_progress = True

    try:
        started = time.time()
        key = _latest_snapshot_key()
        index = _stream_csv_index(_BUCKET_BASE + key)
        with _lock:
            _aircraft_by_hex.clear()
            _aircraft_by_hex.update(index)
            _last_refresh = time.time()
        logger.info(
            "aircraft database refreshed in %.1fs from %s: %d aircraft",
            time.time() - started,
            key,
            len(index),
        )
        return True
    except (requests.RequestException, OSError, ValueError, ET.ParseError) as exc:
        logger.warning("aircraft database refresh failed: %s", exc)
        return True
    finally:
        with _lock:
            _in_progress = False


def lookup_aircraft(icao24: str) -> dict[str, str] | None:
    """Return the metadata record for an ICAO24 hex code, or None."""
    key = (icao24 or "").strip().lower()
    if not key:
        return None
    with _lock:
        entry = _aircraft_by_hex.get(key)
    return dict(entry) if entry else None


def lookup_aircraft_type(icao24: str) -> str:
    """Return the ICAO type code (e.g. 'B738', 'GLF4') or '' if unknown."""
    entry = lookup_aircraft(icao24)
    if not entry:
        return ""
    return entry.get("typecode", "")


def aircraft_database_status() -> dict[str, Any]:
    with _lock:
        return {
            "last_refresh": _last_refresh,
            "aircraft": len(_aircraft_by_hex),
            "in_progress": _in_progress,
        }
