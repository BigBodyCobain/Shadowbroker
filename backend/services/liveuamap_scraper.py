"""Resilient LiveUAMap enrichment providers.

Global Incidents itself is backed independently by GDELT. This module adds
LiveUAMap pins when either an operator-configured supported API is available or
the existing Playwright provider is allowed. Provider failures are isolated and
return an empty enrichment set instead of breaking the fetch scheduler.

The browser provider intentionally does not add any new anti-bot behavior. It
retains the repository's pre-existing Playwright/stealth profile for backward
compatibility while making parsing, packaging failures, and upstream drift
fail-soft.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from services.liveuamap_parser import (
    extract_ovens_expression,
    iter_valid_coordinates,
    normalize_liveuamap_payload,
    payload_shape,
)

logger = logging.getLogger(__name__)

_REGIONS = (
    {"name": "Ukraine", "url": "https://liveuamap.com"},
    {"name": "Middle East", "url": "https://mideast.liveuamap.com"},
    {"name": "Israel-Palestine", "url": "https://israelpalestine.liveuamap.com"},
    {"name": "Syria", "url": "https://syria.liveuamap.com"},
)

_BROWSER_FAILURE_THRESHOLD = 3
_BROWSER_BACKOFF_BASE_S = 15 * 60
_BROWSER_BACKOFF_MAX_S = 6 * 60 * 60
_browser_failures = 0
_browser_blocked_until = 0.0
_browser_health_lock = threading.Lock()

_CHALLENGE_MARKERS = (
    "cf-turnstile",
    "challenge-platform",
    "just a moment",
    "checking your browser",
    "verify you are human",
)


def _bounded_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _safe_header_name(raw: str, default: str) -> str:
    value = (raw or "").strip()
    if not value or any(ch in value for ch in "\r\n:"):
        return default
    if not all(ch.isalnum() or ch in "-_" for ch in value):
        return default
    return value


def _api_url() -> str:
    raw = str(os.getenv("LIVEUAMAP_API_URL", "") or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    return raw


def _public_api_base_url(raw: str) -> str:
    """Return a URL safe to use for relative links without exposing query auth."""
    parsed = urlparse(raw)
    return parsed._replace(query="", fragment="").geturl()


def _api_headers() -> dict[str, str]:
    from services.network_utils import outbound_user_agent

    headers = {
        "Accept": "application/geo+json, application/json;q=0.9",
        "User-Agent": outbound_user_agent("liveuamap-api"),
    }
    api_key = str(os.getenv("LIVEUAMAP_API_KEY", "") or "").strip()
    if api_key:
        header = _safe_header_name(
            str(os.getenv("LIVEUAMAP_API_AUTH_HEADER", "Authorization") or ""),
            "Authorization",
        )
        scheme = str(os.getenv("LIVEUAMAP_API_AUTH_SCHEME", "Bearer") or "").strip()
        if any(ch in scheme for ch in "\r\n"):
            scheme = "Bearer"
        headers[header] = f"{scheme} {api_key}".strip() if scheme else api_key
    return headers


def _fetch_liveuamap_api() -> list[dict[str, Any]]:
    """Fetch an operator-configured supported LiveUAMap JSON/GeoJSON endpoint."""
    url = _api_url()
    if not url:
        return []

    timeout_s = _bounded_int_env("LIVEUAMAP_API_TIMEOUT_S", 30, minimum=5, maximum=120)
    hostname = urlparse(url).hostname or "configured endpoint"
    logger.info("Fetching LiveUAMap supported API from %s", hostname)
    # Refuse redirects while sending operator credentials. A custom auth header
    # is not guaranteed to be stripped by requests on a redirect, so the safest
    # contract is that LIVEUAMAP_API_URL names the final HTTPS endpoint.
    response = requests.get(
        url,
        headers=_api_headers(),
        timeout=(5, timeout_s),
        allow_redirects=False,
    )
    if 300 <= response.status_code < 400:
        raise requests.HTTPError("LiveUAMap API redirected; configure the final HTTPS endpoint")
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("LiveUAMap API did not return JSON/GeoJSON") from exc

    candidates = normalize_liveuamap_payload(payload)
    markers = _format_markers(
        candidates,
        region="LiveUAMap",
        base_url=_public_api_base_url(url),
        fallback_link="https://liveuamap.com",
        provider="api",
    )
    if not markers:
        raise ValueError(
            f"LiveUAMap API returned no recognizable point markers ({payload_shape(payload)})"
        )
    logger.info("LiveUAMap API returned %s normalized markers", len(markers))
    return markers


def _browser_circuit_open() -> tuple[bool, int]:
    now = time.monotonic()
    with _browser_health_lock:
        remaining = max(0, int(_browser_blocked_until - now))
        return remaining > 0, remaining


def _record_browser_success() -> None:
    global _browser_failures, _browser_blocked_until
    with _browser_health_lock:
        _browser_failures = 0
        _browser_blocked_until = 0.0


def _record_browser_failure(reason: str) -> None:
    global _browser_failures, _browser_blocked_until
    now = time.monotonic()
    with _browser_health_lock:
        _browser_failures += 1
        failures = _browser_failures
        if failures < _BROWSER_FAILURE_THRESHOLD:
            logger.warning(
                "LiveUAMap browser provider failure %s/%s: %s",
                failures,
                _BROWSER_FAILURE_THRESHOLD,
                reason,
            )
            return
        exponent = failures - _BROWSER_FAILURE_THRESHOLD
        delay_s = min(_BROWSER_BACKOFF_BASE_S * (2**exponent), _BROWSER_BACKOFF_MAX_S)
        _browser_blocked_until = max(_browser_blocked_until, now + delay_s)
    logger.warning(
        "LiveUAMap browser provider paused for %ss after repeated failures: %s",
        delay_s,
        reason,
    )


def _looks_like_challenge(html: str) -> bool:
    lowered = (html or "").lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def _read_page_payload(page: Any, html: str) -> Any:
    """Prefer evaluated page state, then fall back to the legacy source variable."""
    try:
        serialized = page.evaluate(
            "() => typeof ovens !== 'undefined' ? JSON.stringify(ovens) : null"
        )
        if serialized:
            return serialized
    except Exception as exc:  # Playwright exception types differ across releases.
        logger.debug("LiveUAMap ovens JS evaluation unavailable: %s", exc)

    expression = extract_ovens_expression(html)
    return expression if expression is not None else None


def _fetch_liveuamap_browser() -> list[dict[str, Any]]:
    open_now, remaining_s = _browser_circuit_open()
    if open_now:
        logger.info(
            "LiveUAMap browser provider circuit open; skipping Chromium for another %ss",
            remaining_s,
        )
        return []

    # Import browser-only dependencies lazily so API-only deployments do not
    # require Chromium just to import this module.
    from playwright.sync_api import sync_playwright
    from playwright_stealth import stealth_sync
    from services.network_utils import outbound_user_agent

    all_markers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    successful_regions = 0
    failed_regions = 0

    try:
        with sync_playwright() as playwright:
            # Existing repository behavior retained for compatibility. This PR
            # deliberately adds no further anti-detection/evasion measures.
            browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                context = browser.new_context(
                    user_agent=f"Mozilla/5.0 (compatible; {outbound_user_agent('liveuamap')})",
                    viewport={"width": 1920, "height": 1080},
                    color_scheme="dark",
                )
                context.set_default_navigation_timeout(60_000)
                context.set_default_timeout(30_000)
                page = context.new_page()
                stealth_sync(page)

                for region in _REGIONS:
                    try:
                        logger.info("Fetching LiveUAMap browser region: %s", region["name"])
                        response = page.goto(
                            region["url"],
                            timeout=60_000,
                            wait_until="domcontentloaded",
                        )
                        if response is not None and response.status >= 400:
                            logger.warning(
                                "LiveUAMap %s returned HTTP %s",
                                region["name"],
                                response.status,
                            )
                        page.wait_for_timeout(5_000)
                        html = page.content()

                        # Try useful marker state before classifying the page as
                        # a challenge. Normal pages may load Turnstile assets;
                        # valid marker data should win over that heuristic.
                        payload = _read_page_payload(page, html)
                        if payload is None:
                            if _looks_like_challenge(html):
                                logger.warning(
                                    "LiveUAMap %s appears to be serving an access challenge; "
                                    "leaving this region empty",
                                    region["name"],
                                )
                            else:
                                logger.warning(
                                    "LiveUAMap %s did not expose an ovens payload",
                                    region["name"],
                                )
                            failed_regions += 1
                            continue

                        candidates = normalize_liveuamap_payload(payload)
                        region_markers = _format_markers(
                            candidates,
                            region=region["name"],
                            base_url=region["url"],
                            provider="browser",
                            seen_ids=seen_ids,
                        )
                        if not region_markers:
                            if _looks_like_challenge(html):
                                logger.warning(
                                    "LiveUAMap %s returned no markers and appears challenge-gated",
                                    region["name"],
                                )
                            else:
                                logger.warning(
                                    "LiveUAMap %s payload contained no recognizable point markers (%s)",
                                    region["name"],
                                    payload_shape(payload),
                                )
                            failed_regions += 1
                            continue

                        all_markers.extend(region_markers)
                        successful_regions += 1
                    except Exception as exc:  # Keep one region from killing the other three.
                        failed_regions += 1
                        logger.warning("LiveUAMap %s fetch failed: %s", region["name"], exc)
            finally:
                browser.close()
    except Exception as exc:
        _record_browser_failure(f"Chromium/provider launch failed: {exc}")
        return []

    if successful_regions:
        _record_browser_success()
        logger.info(
            "LiveUAMap browser provider normalized %s markers from %s/%s regions",
            len(all_markers),
            successful_regions,
            len(_REGIONS),
        )
        return all_markers

    _record_browser_failure(f"all {failed_regions or len(_REGIONS)} regions failed or drifted")
    return []


def _normalize_marker_link(raw: Any, base_url: str) -> str:
    """Resolve only HTTP(S) marker links; reject active/non-web URL schemes."""
    text = _as_text(raw).strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme:
        return text if parsed.scheme.lower() in {"http", "https"} else ""

    try:
        resolved = urljoin(base_url.rstrip("/") + "/", text)
        resolved_scheme = urlparse(resolved).scheme.lower()
    except ValueError:
        return ""
    return resolved if resolved_scheme in {"http", "https"} else ""


def _format_markers(
    candidates: list[dict[str, Any]],
    *,
    region: str,
    base_url: str,
    provider: str,
    seen_ids: set[str] | None = None,
    fallback_link: str | None = None,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    dedupe = seen_ids if seen_ids is not None else set()

    for marker, lat, lng in iter_valid_coordinates(candidates):
        title = _as_text(
            marker.get("s")
            or marker.get("title")
            or marker.get("name")
            or marker.get("event")
            or "Unknown Event"
        ).strip()
        description = _as_text(
            marker.get("d")
            or marker.get("desc")
            or marker.get("description")
            or marker.get("summary")
            or ""
        ).strip()
        category = _as_text(
            marker.get("c") or marker.get("cat") or marker.get("category") or ""
        ).strip()
        image = _as_text(marker.get("img") or marker.get("image") or marker.get("photo") or "").strip()
        source = _as_text(marker.get("source") or marker.get("src") or "").strip()
        event_time = marker.get("time", marker.get("t", marker.get("timestamp", "")))
        link = _normalize_marker_link(marker.get("link") or marker.get("url") or "", base_url)

        raw_id = marker.get("id", marker.get("event_id"))
        marker_id = _as_text(raw_id).strip() if raw_id is not None else ""
        if not marker_id:
            marker_id = _stable_marker_id(lat, lng, title, event_time, link)
        if marker_id in dedupe:
            continue
        dedupe.add(marker_id)

        date_str = _format_event_time(event_time)
        output.append(
            {
                "id": marker_id,
                "type": "liveuamap",
                "title": title or "Unknown Event",
                "description": description[:500],
                "lat": lat,
                "lng": lng,
                "timestamp": event_time if event_time is not None else "",
                "date": date_str,
                "link": link or fallback_link or base_url,
                "region": _as_text(marker.get("region") or region).strip() or region,
                "category": category,
                "image": image,
                "source": source,
                "provider": provider,
            }
        )
    return output


def _stable_marker_id(lat: float, lng: float, title: str, event_time: Any, link: str) -> str:
    fingerprint = f"{lat:.6f}|{lng:.6f}|{title}|{event_time}|{link}".encode(
        "utf-8", errors="replace"
    )
    return f"liveuamap-{hashlib.sha256(fingerprint).hexdigest()[:20]}"


def _format_event_time(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("non-finite timestamp")
        if abs(numeric) > 100_000_000_000:  # milliseconds since epoch
            numeric /= 1000.0
        dt = datetime.fromtimestamp(numeric, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError, OverflowError):
        return _as_text(value)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def fetch_liveuamap() -> list[dict[str, Any]]:
    """Return LiveUAMap enrichment without making Global Incidents depend on it."""
    from services.liveuamap_settings import (
        liveuamap_api_configured,
        liveuamap_browser_scraper_enabled,
    )

    if liveuamap_api_configured():
        try:
            return _fetch_liveuamap_api()
        except (requests.RequestException, ValueError, OSError) as exc:
            logger.warning(
                "LiveUAMap supported API failed (%s); considering browser fallback",
                type(exc).__name__,
            )
            # POSIX installs preserve their historical browser fallback; on
            # Windows it remains available only after the operator opted in.

    if liveuamap_browser_scraper_enabled():
        return _fetch_liveuamap_browser()

    logger.info("LiveUAMap enrichment disabled/unavailable; Global Incidents continues with GDELT")
    return []


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(fetch_liveuamap()[:3], indent=2))
