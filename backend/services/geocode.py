"""Geocoding proxy for Nominatim with caching and proper headers."""

from __future__ import annotations

import json
import os
import re
import time
import threading
from typing import Any, Dict, List
from pathlib import Path
from urllib.parse import urlencode

from services.network_utils import fetch_with_curl
from services.fetchers.geo import cached_airports

_CACHE_TTL_S = 900
_CACHE_MAX = 1000
_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()
_local_search_cache: List[Dict[str, Any]] | None = None
_local_search_lock = threading.Lock()

_USER_AGENT = os.environ.get(
    "NOMINATIM_USER_AGENT", "ShadowBroker/1.0 (https://github.com/BigBodyCobain/Shadowbroker)"
)


def _get_cache(key: str):
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        if now - entry["ts"] > _CACHE_TTL_S:
            _cache.pop(key, None)
            return None
        return entry["value"]


def _set_cache(key: str, value):
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            # Simple eviction: drop ~10% oldest keys
            keys = list(_cache.keys())[: max(1, _CACHE_MAX // 10)]
            for k in keys:
                _cache.pop(k, None)
        _cache[key] = {"ts": time.time(), "value": value}


def _load_local_search_cache() -> List[Dict[str, Any]]:
    global _local_search_cache
    with _local_search_lock:
        if _local_search_cache is not None:
            return _local_search_cache

        results: List[Dict[str, Any]] = []
        cache_path = Path(__file__).resolve().parents[1] / "data" / "geocode_cache.json"
        try:
            if cache_path.exists():
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for label, coords in raw.items():
                        if (
                            isinstance(label, str)
                            and isinstance(coords, list)
                            and len(coords) == 2
                            and all(isinstance(v, (int, float)) for v in coords)
                        ):
                            results.append(
                                {
                                    "label": label,
                                    "lat": float(coords[0]),
                                    "lng": float(coords[1]),
                                }
                            )
        except Exception:
            results = []

        _local_search_cache = results
        return _local_search_cache


def _search_local_fallback(query: str, limit: int) -> List[Dict[str, Any]]:
    """Strict local lookup used only when ``local_only=True`` is set.

    Historical behaviour (substring-token-in-haystack matching) produced
    catastrophically wrong results: any query containing a common word
    would match the first airport with that word anywhere in its name,
    which silently poisoned every cache downstream. Fixed to require
    whole-word matches against airport name/IATA/id and cached-geocode
    labels.
    """
    q = query.strip().lower()
    if not q:
        return []
    q_tokens = set(re.findall(r"[a-z0-9]+", q))
    if not q_tokens:
        return []

    matches: List[Dict[str, Any]] = []
    seen: set[tuple[float, float, str]] = set()

    def _whole_word_tokens(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", (text or "").lower()))

    for item in cached_airports:
        name_tokens = _whole_word_tokens(item.get("name", ""))
        iata = str(item.get("iata", "")).lower().strip()
        icao = str(item.get("id", "")).lower().strip()
        # IATA/ICAO must match exactly; name must share ALL query tokens
        # with the airport name (not "any token in haystack").
        exact_code = bool(iata and iata in q_tokens) or bool(icao and icao in q_tokens)
        name_match = bool(q_tokens) and q_tokens.issubset(name_tokens)
        if not (exact_code or name_match):
            continue
        label = f'{item.get("name", "Airport")} ({item.get("iata", "")})'
        key = (float(item["lat"]), float(item["lng"]), label)
        if key not in seen:
            seen.add(key)
            matches.append(
                {
                    "label": label,
                    "lat": float(item["lat"]),
                    "lng": float(item["lng"]),
                }
            )
            if len(matches) >= limit:
                return matches

    for item in _load_local_search_cache():
        label = str(item.get("label", ""))
        label_tokens = _whole_word_tokens(label)
        if not q_tokens.issubset(label_tokens):
            continue
        key = (float(item["lat"]), float(item["lng"]), label)
        if key not in seen:
            seen.add(key)
            matches.append(item)
            if len(matches) >= limit:
                break

    return matches


def _reverse_geocode_offline(lat: float, lng: float) -> Dict[str, Any]:
    try:
        import reverse_geocoder as rg

        hit = rg.search((lat, lng), mode=1)[0]
        city = hit.get("name") or ""
        state = hit.get("admin1") or ""
        country = hit.get("cc") or ""
        parts = [city, state, country]
        label = ", ".join([p for p in parts if p]) or "Unknown"
        return {"label": label}
    except Exception:
        return {"label": "Unknown"}


def search_geocode(query: str, limit: int = 5, local_only: bool = False) -> List[Dict[str, Any]]:
    q = query.strip()
    if not q:
        return []
    limit = max(1, min(int(limit or 5), 10))
    key = f"search:{q.lower()}:{limit}:{int(local_only)}"
    cached = _get_cache(key)
    if cached is not None:
        return cached
    if local_only:
        results = _search_local_fallback(q, limit)
        _set_cache(key, results)
        return results

    params = urlencode({"q": q, "format": "json", "limit": str(limit)})
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    try:
        res = fetch_with_curl(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept-Language": "en",
            },
            timeout=6,
        )
    except Exception:
        # Intentionally no silent airport-name fallback. Callers that
        # want offline results should pass ``local_only=True``; anything
        # else means we return an empty list so the caller can decide
        # whether to retry or propagate the failure. The old behaviour
        # of falling through to _search_local_fallback silently poisoned
        # every downstream cache with airport coordinates for any query.
        _set_cache(key, [])
        return []

    results: List[Dict[str, Any]] = []
    if res and res.status_code == 200:
        try:
            data = res.json() or []
            for item in data:
                try:
                    results.append(
                        {
                            "label": item.get("display_name"),
                            "lat": float(item.get("lat")),
                            "lng": float(item.get("lon")),
                        }
                    )
                except (TypeError, ValueError):
                    continue
        except Exception:
            results = []

    # No silent airport-name fallback on empty results either — same
    # reason as above. Empty means empty.
    _set_cache(key, results)
    return results


def reverse_geocode(lat: float, lng: float, local_only: bool = False) -> Dict[str, Any]:
    key = f"reverse:{lat:.4f},{lng:.4f}:{int(local_only)}"
    cached = _get_cache(key)
    if cached is not None:
        return cached
    if local_only:
        payload = _reverse_geocode_offline(lat, lng)
        _set_cache(key, payload)
        return payload

    params = urlencode(
        {
            "lat": f"{lat}",
            "lon": f"{lng}",
            "format": "json",
            "zoom": "10",
            "addressdetails": "1",
        }
    )
    url = f"https://nominatim.openstreetmap.org/reverse?{params}"
    try:
        res = fetch_with_curl(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept-Language": "en",
            },
            timeout=6,
        )
    except Exception:
        payload = _reverse_geocode_offline(lat, lng)
        _set_cache(key, payload)
        return payload

    label = "Unknown"
    if res and res.status_code == 200:
        try:
            data = res.json() or {}
            addr = data.get("address") or {}
            city = (
                addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("county")
                or ""
            )
            state = addr.get("state") or addr.get("region") or ""
            country = addr.get("country") or ""
            parts = [city, state, country]
            label = ", ".join([p for p in parts if p]) or (
                data.get("display_name", "") or "Unknown"
            )
        except Exception:
            label = "Unknown"
    if label == "Unknown":
        payload = _reverse_geocode_offline(lat, lng)
        _set_cache(key, payload)
        return payload

    payload = {"label": label}
    _set_cache(key, payload)
    return payload
