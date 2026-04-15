"""
Local-only Shodan connector.

This module intentionally does NOT merge Shodan results into the dashboard's
canonical live-data store. It exposes manual, operator-triggered lookups that
can be rendered locally in the UI as a temporary investigative overlay.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import requests
from cachetools import TTLCache

logger = logging.getLogger(__name__)

_SHODAN_BASE = "https://api.shodan.io"
_USER_AGENT = "ShadowBroker/0.9.6 local Shodan connector"
_REQUEST_TIMEOUT = 15
_MIN_INTERVAL_SECONDS = 1.05  # Shodan docs say API plans are rate limited to ~1 req/sec.
_DEFAULT_SEARCH_PAGES = 1
_MAX_SEARCH_PAGES = 2

_search_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=24, ttl=90)
_count_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=24, ttl=120)
_host_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=32, ttl=300)

_request_lock = threading.Lock()
_last_request_at = 0.0


class ShodanConnectorError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _get_api_key() -> str:
    api_key = os.environ.get("SHODAN_API_KEY", "").strip()
    if not api_key:
        raise ShodanConnectorError(
            "Shodan API key not configured. Add SHODAN_API_KEY in Settings > API Keys.",
            status_code=428,
        )
    return api_key


def _clean_query(value: str | None) -> str:
    query = (value or "").strip()
    if not query:
        raise ShodanConnectorError("Shodan query cannot be empty.", status_code=400)
    if "\n" in query or "\r" in query:
        raise ShodanConnectorError("Shodan query must be a single line.", status_code=400)
    return query


def _cache_key(prefix: str, payload: dict[str, Any]) -> str:
    normalized = tuple(sorted((str(k), str(v)) for k, v in payload.items()))
    return f"{prefix}:{normalized!r}"


def _normalize_string_list(values: Any, limit: int = 10) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for item in values:
        text = str(item).strip()
        if text:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _location_label(location: dict[str, Any]) -> str | None:
    parts = [
        str(location.get("city") or "").strip(),
        str(location.get("region_code") or "").strip(),
        str(location.get("country_code") or "").strip(),
    ]
    label = ", ".join([p for p in parts if p])
    return label or None


def _normalize_match(match: dict[str, Any]) -> dict[str, Any]:
    location = match.get("location") or {}
    lat = location.get("latitude")
    lng = location.get("longitude")
    port = match.get("port")
    ip_str = str(match.get("ip_str") or match.get("ip") or "").strip()
    host_id = f"shodan-{ip_str or 'unknown'}-{port or 'na'}"
    vulns = match.get("vulns") or []
    if isinstance(vulns, dict):
        vuln_list = _normalize_string_list(list(vulns.keys()), limit=12)
    else:
        vuln_list = _normalize_string_list(vulns, limit=12)
    return {
        "id": host_id,
        "ip": ip_str or "UNKNOWN",
        "port": port,
        "transport": match.get("transport"),
        "timestamp": match.get("timestamp"),
        "lat": lat if isinstance(lat, (int, float)) else None,
        "lng": lng if isinstance(lng, (int, float)) else None,
        "city": location.get("city"),
        "region_code": location.get("region_code"),
        "country_code": location.get("country_code"),
        "country_name": location.get("country_name"),
        "location_label": _location_label(location),
        "asn": match.get("asn"),
        "org": match.get("org"),
        "isp": match.get("isp"),
        "product": match.get("product"),
        "os": match.get("os"),
        "hostnames": _normalize_string_list(match.get("hostnames")),
        "domains": _normalize_string_list(match.get("domains")),
        "tags": _normalize_string_list(match.get("tags")),
        "vulns": vuln_list,
        "data_snippet": str(match.get("data") or "").strip()[:280] or None,
        "attribution": "Data from Shodan",
    }


def _normalize_services(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    services: list[dict[str, Any]] = []
    for item in items[:30]:
        if not isinstance(item, dict):
            continue
        services.append(
            {
                "port": item.get("port"),
                "transport": item.get("transport"),
                "product": item.get("product"),
                "timestamp": item.get("timestamp"),
                "tags": _normalize_string_list(item.get("tags"), limit=8),
                "banner_excerpt": str(item.get("data") or "").strip()[:320] or None,
            }
        )
    return services


def _normalize_facets(raw_facets: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(raw_facets, dict):
        return {}
    normalized: dict[str, list[dict[str, Any]]] = {}
    for key, bucket_list in raw_facets.items():
        if not isinstance(bucket_list, list):
            continue
        normalized[str(key)] = [
            {"value": str(bucket.get("value") or ""), "count": int(bucket.get("count") or 0)}
            for bucket in bucket_list[:12]
            if isinstance(bucket, dict)
        ]
    return normalized


def _request(path: str, *, params: dict[str, Any], cache: TTLCache[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    api_key = _get_api_key()
    payload = {**params, "key": api_key}
    cache_key = _cache_key(path, {k: v for k, v in payload.items() if k != "key"})
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    global _last_request_at
    with _request_lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < _MIN_INTERVAL_SECONDS:
            time.sleep(_MIN_INTERVAL_SECONDS - elapsed)
        try:
            response = requests.get(
                f"{_SHODAN_BASE}{path}",
                params=payload,
                timeout=_REQUEST_TIMEOUT,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            )
        finally:
            _last_request_at = time.monotonic()

    if response.status_code == 401:
        raise ShodanConnectorError("Shodan rejected the API key. Check SHODAN_API_KEY.", 401)
    if response.status_code == 402:
        raise ShodanConnectorError(
            "Shodan returned payment/plan required. This feature needs a paid Shodan API plan.",
            402,
        )
    if response.status_code == 429:
        raise ShodanConnectorError(
            "Shodan rate limit reached. Slow down queries and try again shortly.",
            429,
        )
    if response.status_code >= 400:
        detail = response.text.strip()[:240] or "Unexpected Shodan API error."
        raise ShodanConnectorError(f"Shodan request failed: {detail}", response.status_code)

    try:
        parsed = response.json()
    except ValueError as exc:
        raise ShodanConnectorError(f"Shodan returned invalid JSON: {exc}", 502) from exc

    if cache is not None:
        cache[cache_key] = parsed
    return parsed


def get_shodan_connector_status() -> dict[str, Any]:
    has_key = bool(os.environ.get("SHODAN_API_KEY", "").strip())
    return {
        "ok": True,
        "configured": has_key,
        "source": "Shodan",
        "mode": "operator-supplied local overlay",
        "paid_api": True,
        "manual_only": True,
        "background_polling": False,
        "local_only": True,
        "attribution": "Data from Shodan",
        "warning": (
            "Shodan is a paid API. Searches use your local SHODAN_API_KEY, results stay local to "
            "your ShadowBroker session by default, and any downstream use is your responsibility."
        ),
        "limits": {
            "default_pages_per_search": _DEFAULT_SEARCH_PAGES,
            "max_pages_per_search": _MAX_SEARCH_PAGES,
            "cooldown_seconds": _MIN_INTERVAL_SECONDS,
        },
    }


def search_shodan(query: str, page: int = 1, facets: list[str] | None = None) -> dict[str, Any]:
    cleaned_query = _clean_query(query)
    safe_page = max(1, min(int(page or 1), _MAX_SEARCH_PAGES))
    facet_list = [str(f).strip() for f in (facets or []) if str(f).strip()][:6]
    params: dict[str, Any] = {"query": cleaned_query, "page": safe_page}
    if facet_list:
        params["facets"] = ",".join(facet_list)
    raw = _request("/shodan/host/search", params=params, cache=_search_cache)
    matches = [_normalize_match(match) for match in raw.get("matches") or [] if isinstance(match, dict)]
    return {
        "ok": True,
        "source": "Shodan",
        "attribution": "Data from Shodan",
        "query": cleaned_query,
        "page": safe_page,
        "total": int(raw.get("total") or 0),
        "matches": matches,
        "facets": _normalize_facets(raw.get("facets")),
        "note": "Operator-triggered Shodan results. Not part of ShadowBroker core feeds.",
    }


def count_shodan(query: str, facets: list[str] | None = None) -> dict[str, Any]:
    cleaned_query = _clean_query(query)
    facet_list = [str(f).strip() for f in (facets or []) if str(f).strip()][:8]
    params: dict[str, Any] = {"query": cleaned_query}
    if facet_list:
        params["facets"] = ",".join(facet_list)
    raw = _request("/shodan/host/count", params=params, cache=_count_cache)
    return {
        "ok": True,
        "source": "Shodan",
        "attribution": "Data from Shodan",
        "query": cleaned_query,
        "total": int(raw.get("total") or 0),
        "facets": _normalize_facets(raw.get("facets")),
        "note": "Count/facets query only. No persistent ShadowBroker storage.",
    }


def lookup_shodan_host(ip: str, history: bool = False) -> dict[str, Any]:
    clean_ip = str(ip or "").strip()
    if not clean_ip:
        raise ShodanConnectorError("Host lookup requires an IP address.", 400)
    raw = _request(
        f"/shodan/host/{clean_ip}",
        params={"history": "true" if history else "false"},
        cache=_host_cache,
    )
    location = raw.get("location") or {}
    host = {
        "id": f"shodan-{clean_ip}-host",
        "ip": str(raw.get("ip_str") or clean_ip),
        "lat": location.get("latitude") if isinstance(location.get("latitude"), (int, float)) else None,
        "lng": location.get("longitude") if isinstance(location.get("longitude"), (int, float)) else None,
        "city": location.get("city"),
        "region_code": location.get("region_code"),
        "country_code": location.get("country_code"),
        "country_name": location.get("country_name"),
        "location_label": _location_label(location),
        "asn": raw.get("asn"),
        "org": raw.get("org"),
        "isp": raw.get("isp"),
        "os": raw.get("os"),
        "hostnames": _normalize_string_list(raw.get("hostnames")),
        "domains": _normalize_string_list(raw.get("domains")),
        "tags": _normalize_string_list(raw.get("tags")),
        "ports": [int(p) for p in (raw.get("ports") or []) if isinstance(p, int)],
        "services": _normalize_services(raw.get("data")),
        "vulns": _normalize_string_list(list((raw.get("vulns") or {}).keys()) if isinstance(raw.get("vulns"), dict) else raw.get("vulns"), limit=20),
        "attribution": "Data from Shodan",
    }
    return {
        "ok": True,
        "source": "Shodan",
        "attribution": "Data from Shodan",
        "host": host,
        "history": bool(history),
        "note": "Operator-triggered Shodan host lookup. Not merged into ShadowBroker datasets.",
    }
