"""
KiwiSDR public receiver list fetcher.

Pulls from Pierre Ynard's dyatlov map mirror at rx.linkfanel.net, which
auto-generates a JSON-like JS array from kiwisdr.com/public/. We use the
mirror instead of kiwisdr.com directly to avoid adding load to jks-prv's
bandwidth — see issue #131 for context.

Receivers are stationary hardware (someone's house, antenna on the roof) —
their lat/lon and antenna config don't move. We refresh the list once per
day, persisted to disk so restarts don't re-fetch. The slow-tier scheduler
still calls this every 5 minutes, but those calls hit the in-memory or
on-disk cache and never touch the network until 24 hours have passed.

The mirror returns a JS file shaped like:
    // KiwiSDR.com receiver list for dyatlov map maker
    var kiwisdr_com = [ {...}, {...}, ... ];
"""

import re
import json
import time
import logging
from pathlib import Path

import requests
from cachetools import TTLCache, cached

logger = logging.getLogger(__name__)

# 24-hour in-memory TTL — receivers don't move, so daily is plenty.
_REFRESH_SECONDS = 24 * 3600
kiwisdr_cache: TTLCache = TTLCache(maxsize=1, ttl=_REFRESH_SECONDS)

_SOURCE_URL = "http://rx.linkfanel.net/kiwisdr_com.js"
_CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "kiwisdr_cache.json"
_LINE_COMMENT_RE = re.compile(r"^\s*//.*$", re.MULTILINE)
_VAR_PREFIX_RE = re.compile(r"^\s*var\s+kiwisdr_com\s*=\s*", re.MULTILINE)
_TRAILING_COMMA_RE = re.compile(r",(\s*[\]}])")
_GPS_RE = re.compile(r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)")


def _parse_gps(gps_str: str):
    if not gps_str:
        return None, None
    m = _GPS_RE.search(gps_str)
    if not m:
        return None, None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None, None


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_disk_cache() -> list[dict] | None:
    """Return cached receivers if disk cache exists and is <24h old."""
    if not _CACHE_FILE.exists():
        return None
    try:
        age = time.time() - _CACHE_FILE.stat().st_mtime
        if age > _REFRESH_SECONDS:
            return None
        nodes = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(nodes, list):
            return nodes
    except Exception as e:
        logger.warning(f"KiwiSDR disk cache read failed: {e}")
    return None


def _save_disk_cache(nodes: list[dict]) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(nodes), encoding="utf-8")
    except Exception as e:
        logger.warning(f"KiwiSDR disk cache write failed: {e}")


def _parse_mirror_payload(body: str) -> list[dict]:
    """Strip the JS wrapper and return parsed receiver dicts."""
    json_body = _LINE_COMMENT_RE.sub("", body)
    json_body = _VAR_PREFIX_RE.sub("", json_body, count=1).strip()
    if json_body.endswith(";"):
        json_body = json_body[:-1].rstrip()
    json_body = _TRAILING_COMMA_RE.sub(r"\1", json_body)

    try:
        entries = json.loads(json_body)
    except json.JSONDecodeError as e:
        logger.error(f"KiwiSDR mirror returned unparseable JS: {e}")
        return []

    if not isinstance(entries, list):
        logger.error("KiwiSDR mirror payload was not a list")
        return []

    nodes: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("offline", "")).lower() == "yes":
            continue

        lat, lon = _parse_gps(str(entry.get("gps", "")))
        if lat is None or lon is None:
            continue
        if abs(lat) > 90 or abs(lon) > 180:
            continue

        name = (entry.get("name") or "Unknown SDR").strip()
        url = (entry.get("url") or "").strip()
        antenna = (entry.get("antenna") or "").strip()
        location = (entry.get("loc") or "").strip()

        nodes.append(
            {
                "name": name[:120],
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "url": url,
                "users": _to_int(entry.get("users")),
                "users_max": _to_int(entry.get("users_max")),
                "bands": (entry.get("bands") or ""),
                "antenna": antenna[:200],
                "location": location[:100],
            }
        )
    return nodes


@cached(kiwisdr_cache)
def fetch_kiwisdr_nodes() -> list[dict]:
    """Return the KiwiSDR receiver list, refreshed at most once per day.

    Order of preference: in-memory cache (handled by @cached) → on-disk cache
    if <24h old → network fetch from rx.linkfanel.net.
    """
    from services.network_utils import fetch_with_curl

    # 1. Trust on-disk cache if fresh.
    cached_nodes = _load_disk_cache()
    if cached_nodes is not None:
        logger.info(
            f"KiwiSDR: loaded {len(cached_nodes)} receivers from disk cache (<24h old)"
        )
        return cached_nodes

    # 2. Cache cold or stale — fetch from network.
    try:
        res = fetch_with_curl(_SOURCE_URL, timeout=20)
        if not res or res.status_code != 200:
            logger.error(
                f"KiwiSDR fetch failed: HTTP {res.status_code if res else 'no response'}"
            )
            return []

        nodes = _parse_mirror_payload(res.text)
        if nodes:
            _save_disk_cache(nodes)
            logger.info(
                f"KiwiSDR: refreshed {len(nodes)} receivers from rx.linkfanel.net "
                "(next refresh in 24h)"
            )
        return nodes

    except (requests.RequestException, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        logger.error(f"KiwiSDR fetch exception: {e}")
        # Fall back to a stale disk cache if one exists, even if >24h old.
        if _CACHE_FILE.exists():
            try:
                stale = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(stale, list):
                    logger.info(
                        f"KiwiSDR: serving {len(stale)} stale receivers from disk after fetch failure"
                    )
                    return stale
            except Exception:
                pass
        return []
