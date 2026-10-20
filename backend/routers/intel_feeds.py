"""Malware, cyber threats, and country risk feeds."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from limiter import limiter
from services.fetchers._store import get_latest_data_subset_refs
from services.fetchers.telegram_osint import telegram_media_host_allowed
from services.intel_feeds.country_risk import build_country_risk_payload
from services.network_utils import outbound_user_agent
from services.telegram_translate import apply_posts_translations, normalize_translate_target

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/malware")
@limiter.limit("60/minute")
async def malware_feed(request: Request) -> dict:
    snap = get_latest_data_subset_refs("malware_threats")
    payload = snap.get("malware_threats")
    if isinstance(payload, dict) and payload.get("threats") is not None:
        return payload
    return {"threats": [], "total": 0, "timestamp": None, "source": "abuse.ch"}


@router.get("/api/cyber-threats")
@limiter.limit("60/minute")
async def cyber_threats(request: Request) -> dict:
    snap = get_latest_data_subset_refs("cyber_threats")
    return snap.get("cyber_threats") or {"threats": [], "stats": {}}


@router.get("/api/country-risk")
@limiter.limit("30/minute")
async def country_risk(request: Request) -> dict:
    return build_country_risk_payload()


@router.get("/api/telegram-feed")
@limiter.limit("30/minute")
async def telegram_feed(request: Request, lang: str | None = Query(default=None)) -> dict:
    snap = get_latest_data_subset_refs("telegram_osint")
    payload = snap.get("telegram_osint")
    if not isinstance(payload, dict) or payload.get("posts") is None:
        return {"posts": [], "total": 0, "geolocated": 0, "timestamp": None}

    if lang:
        target = normalize_translate_target(lang)
        localized = dict(payload)
        localized["posts"] = apply_posts_translations(list(payload.get("posts") or []), target)
        localized["translate_locale"] = target
        return localized
    return payload


def _infer_telegram_media_type(target_url: str, content_type: str) -> str:
    clean_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if clean_type and clean_type not in {"application/octet-stream", "binary/octet-stream"}:
        return content_type
    path = str(urlparse(target_url).path or "").lower()
    if path.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if path.endswith(".png"):
        return "image/png"
    if path.endswith(".webp"):
        return "image/webp"
    if path.endswith(".gif"):
        return "image/gif"
    if path.endswith(".mp4"):
        return "video/mp4"
    if path.endswith(".webm"):
        return "video/webm"
    return content_type or "application/octet-stream"


@router.get("/api/telegram/media")
@limiter.limit("60/minute")
async def telegram_media_proxy(request: Request, url: str = Query(...)) -> StreamingResponse:
    """Stream Telegram CDN media for in-app playback (host allowlist only)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid scheme")
    if not telegram_media_host_allowed(parsed.hostname):
        raise HTTPException(status_code=403, detail="Host not allowed")

    headers = {
        "User-Agent": (
            f"Mozilla/5.0 (compatible; {outbound_user_agent('telegram-media')}) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
    }
    if range_header := request.headers.get("range"):
        headers["Range"] = range_header

    try:
        resp = requests.get(url, stream=True, timeout=(3, 45), headers=headers)
    except requests.RequestException as exc:
        logger.warning("Telegram media upstream failure %s: %s", url, exc)
        raise HTTPException(status_code=502, detail="Upstream fetch failed") from exc

    if resp.status_code >= 400:
        resp.close()
        raise HTTPException(status_code=int(resp.status_code), detail=f"Upstream returned {resp.status_code}")

    media_type = _infer_telegram_media_type(url, resp.headers.get("Content-Type", "application/octet-stream"))
    response_headers = {
        "Cache-Control": "private, max-age=300",
        "Accept-Ranges": resp.headers.get("Accept-Ranges", "bytes"),
    }
    if content_length := resp.headers.get("Content-Length"):
        response_headers["Content-Length"] = content_length
    if content_range := resp.headers.get("Content-Range"):
        response_headers["Content-Range"] = content_range

    return StreamingResponse(
        resp.iter_content(chunk_size=65536),
        status_code=resp.status_code,
        media_type=media_type,
        headers=response_headers,
        background=BackgroundTask(resp.close),
    )
