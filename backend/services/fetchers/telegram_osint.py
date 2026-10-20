"""Telegram OSINT — public channel web previews (t.me/s) with keyword geoparsing."""
from __future__ import annotations

import hashlib
import html
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from services.fetchers._store import _data_lock, _mark_fresh, is_any_active, latest_data
from services.fetchers.news import resolve_coords_match
from services.network_utils import fetch_with_curl, outbound_user_agent
from services.telegram_translate import apply_post_translation, apply_posts_translations

logger = logging.getLogger(__name__)

_DEFAULT_CHANNELS = (
    "osintdefender",
    "insiderpaper",
    "aljazeeraenglish",
    "nexta_live",
    "war_monitor",
    "OSINTtechnical",
    "Liveuamap",
)

_MESSAGE_BLOCK_RE = re.compile(
    r'<div class="tgme_widget_message_wrap js-widget_message_wrap"[\s\S]*?</div>\s*</div>\s*</div>',
    re.IGNORECASE,
)
_TEXT_RE = re.compile(
    r'<div class="tgme_widget_message_text[^>]*>([\s\S]*?)</div>',
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r'<a class="tgme_widget_message_date" href="(https://t\.me/[^"]+)".*?<time datetime="([^"]+)"',
    re.IGNORECASE,
)
_HAS_VIDEO_RE = re.compile(
    r'tgme_widget_message_video|js-message_video|<video\s',
    re.IGNORECASE,
)
_HAS_PHOTO_RE = re.compile(r'tgme_widget_message_photo_wrap', re.IGNORECASE)
_VIDEO_SRC_RE = re.compile(r'<video[^>]+src="([^"]+)"', re.IGNORECASE)
_BG_IMAGE_RE = re.compile(r"background-image:url\('([^']+)'\)", re.IGNORECASE)

_TELEGRAM_MEDIA_HOST_SUFFIXES = (".telesco.pe", ".telegram-cdn.org")

# Cyrillic / Arabic aliases for war-reporting channels (merged after English resolver).
_EXTRA_PLACE_KEYWORDS: dict[str, tuple[float, float]] = {
    "киев": (50.450, 30.523),
    "київ": (50.450, 30.523),
    "харьков": (49.993, 36.231),
    "харків": (49.993, 36.231),
    "одесса": (46.482, 30.724),
    "одеса": (46.482, 30.724),
    "донецк": (48.015, 37.803),
    "донецьк": (48.015, 37.803),
    "луганск": (48.574, 39.307),
    "луганськ": (48.574, 39.307),
    "москва": (55.755, 37.617),
    "крым": (45.000, 34.000),
    "крим": (45.000, 34.000),
    "бахмут": (48.595, 38.000),
    "запорожье": (47.838, 35.139),
    "запоріжжя": (47.838, 35.139),
    "غزة": (31.416, 34.333),
    "دمشق": (33.513, 36.276),
    "بيروت": (33.893, 35.501),
    "tel aviv": (32.085, 34.781),
    "תל אביב": (32.085, 34.781),
}

# Country-level news geocodes sit on national centroids that stack with threat alerts.
# Telegram uses major metro anchors so pins land on a different map cell than news.
_TELEGRAM_ANCHOR_OVERRIDES: dict[str, tuple[float, float]] = {
    "israel": (32.085, 34.781),  # Tel Aviv (news uses central Israel ~Jerusalem corridor)
    "middle east": (32.085, 34.781),
    "china": (39.904, 116.407),  # Beijing (news uses country centroid)
    "united states": (40.712, -74.006),  # New York (news uses Washington DC)
    "usa": (40.712, -74.006),
    "us": (40.712, -74.006),
    "america": (40.712, -74.006),
    "uk": (51.507, -0.127),  # London
    "iran": (35.689, 51.389),  # Tehran
    "russia": (55.755, 37.617),  # Moscow
    "ukraine": (50.450, 30.523),  # Kyiv
    "france": (48.856, 2.352),  # Paris
    "germany": (52.520, 13.405),  # Berlin
    "lebanon": (34.433, 35.844),  # Tripoli (news uses Beirut corridor)
}

_RISK_KEYWORDS = (
    "war",
    "missile",
    "strike",
    "attack",
    "crisis",
    "tension",
    "military",
    "conflict",
    "defense",
    "clash",
    "nuclear",
    "invasion",
    "bomb",
    "drone",
    "weapon",
    "sanctions",
    "ceasefire",
    "escalation",
    "killed",
    "destroyed",
    "operation",
    "casualty",
    "frontline",
    "threat",
    "explosion",
    "shelling",
)


def telegram_osint_enabled() -> bool:
    return str(os.environ.get("TELEGRAM_OSINT_ENABLED", "true")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "",
    }


def _configured_channels() -> list[str]:
    raw = str(os.environ.get("TELEGRAM_OSINT_CHANNELS", "")).strip()
    if raw:
        return [part.strip().lstrip("@") for part in raw.split(",") if part.strip()]
    return list(_DEFAULT_CHANNELS)


def telegram_media_host_allowed(hostname: str | None) -> bool:
    host = str(hostname or "").strip().lower()
    if not host:
        return False
    return any(host.endswith(suffix) for suffix in _TELEGRAM_MEDIA_HOST_SUFFIXES)


def _extract_media(block: str, link: str) -> dict[str, Any]:
    has_video = bool(_HAS_VIDEO_RE.search(block))
    has_photo = bool(_HAS_PHOTO_RE.search(block))
    media_type: str | None = None
    media_url: str | None = None
    if has_video:
        media_type = "video"
        video_match = _VIDEO_SRC_RE.search(block)
        if video_match:
            media_url = video_match.group(1).strip()
    elif has_photo:
        media_type = "photo"
        photo_match = _BG_IMAGE_RE.search(block)
        if photo_match:
            media_url = photo_match.group(1).strip()

    embed_url: str | None = None
    if media_type and link:
        embed_url = f"{link}?embed=1"

    return {
        "media_type": media_type,
        "media_url": media_url,
        "embed_url": embed_url,
    }


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return html.unescape(cleaned).strip()


def _score_risk(text: str) -> int:
    lower = text.lower()
    score = 1
    for kw in _RISK_KEYWORDS:
        if kw in lower:
            score += 2
    return min(10, score)


def _refresh_post_coords(post: dict[str, Any]) -> dict[str, Any]:
    """Re-apply geoparsing so stored posts pick up anchor updates."""
    text = "\n".join(
        str(part).strip()
        for part in (post.get("title"), post.get("description"))
        if part and str(part).strip()
    )
    if not text:
        return post
    coords = _resolve_telegram_coords(text)
    if not coords:
        return post
    updated = dict(post)
    updated["coords"] = [coords[0], coords[1]]
    return updated


def _resolve_telegram_coords(text: str) -> tuple[float, float] | None:
    lower = text.lower()
    match = resolve_coords_match(lower)
    if match:
        _coords, keyword = match
        anchor = _TELEGRAM_ANCHOR_OVERRIDES.get(keyword.strip().lower())
        if anchor:
            return anchor
        return _coords
    for keyword, coords in sorted(_EXTRA_PLACE_KEYWORDS.items(), key=lambda x: len(x[0]), reverse=True):
        if keyword in lower:
            return coords
    return None


def _post_link(post: dict[str, Any]) -> str:
    return str(post.get("link") or "").strip()


def _extract_new_channel_posts(
    html: str,
    channel: str,
    known_links: set[str],
    *,
    bootstrap_limit: int = 12,
) -> list[dict[str, Any]]:
    """Return unseen posts from a channel page; stop once we hit a stored link."""
    parsed = parse_telegram_channel_html(html, channel)
    if not parsed:
        return []
    if not known_links:
        return parsed[-bootstrap_limit:]

    fresh: list[dict[str, Any]] = []
    for post in reversed(parsed):
        link = _post_link(post)
        if not link:
            continue
        if link in known_links:
            break
        fresh.append(post)
    fresh.reverse()
    return fresh


def _merge_telegram_posts(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    max_posts: int = 120,
) -> tuple[list[dict[str, Any]], int]:
    known_links = {_post_link(post) for post in existing if _post_link(post)}
    added = 0
    for post in incoming:
        link = _post_link(post)
        if not link or link in known_links:
            continue
        known_links.add(link)
        existing.append(post)
        added += 1
    existing.sort(key=lambda p: str(p.get("published") or ""), reverse=True)
    return existing[:max_posts], added


def parse_telegram_channel_html(html: str, channel: str) -> list[dict[str, Any]]:
    """Parse public t.me/s channel preview HTML into post dicts."""
    posts: list[dict[str, Any]] = []
    for block in _MESSAGE_BLOCK_RE.findall(html or ""):
        text_match = _TEXT_RE.search(block)
        if not text_match:
            continue
        text = _strip_html(text_match.group(1))
        if len(text) < 10:
            continue

        date_match = _DATE_RE.search(block)
        link = date_match.group(1) if date_match else f"https://t.me/{channel}"
        published = date_match.group(2) if date_match else datetime.now(timezone.utc).isoformat()
        title = text.split("\n", 1)[0][:160]
        risk_score = _score_risk(text)
        coords = _resolve_telegram_coords(text)
        post_id = hashlib.sha1(f"{link}|{published}".encode("utf-8")).hexdigest()[:16]

        media = _extract_media(block, link)
        post = {
            "id": post_id,
            "title": title,
            "description": text[:1200],
            "link": link,
            "published": published,
            "source": f"t.me/{channel}",
            "channel": channel,
            "risk_score": risk_score,
            "coords": [coords[0], coords[1]] if coords else None,
            **media,
        }
        posts.append(apply_post_translation(post))
    return posts


def fetch_telegram_osint() -> dict[str, Any]:
    if not is_any_active("telegram_osint"):
        return latest_data.get("telegram_osint") or {"posts": [], "total": 0, "timestamp": None}

    if not telegram_osint_enabled():
        with _data_lock:
            latest_data["telegram_osint"] = {"posts": [], "total": 0, "timestamp": None, "disabled": True}
        _mark_fresh("telegram_osint")
        return latest_data["telegram_osint"]

    headers = {
        "User-Agent": (
            f"Mozilla/5.0 (compatible; {outbound_user_agent('telegram-osint')}) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }

    with _data_lock:
        prior = latest_data.get("telegram_osint") or {}
        existing_posts = list(prior.get("posts") or [])

    known_links = {_post_link(post) for post in existing_posts if _post_link(post)}
    incoming: list[dict[str, Any]] = []

    for channel in _configured_channels():
        url = f"https://t.me/s/{channel}"
        try:
            resp = fetch_with_curl(url, timeout=15, headers=headers)
            if not resp or resp.status_code != 200:
                logger.warning(
                    "Telegram channel %s fetch failed: HTTP %s",
                    channel,
                    resp.status_code if resp else "no response",
                )
                continue
            channel_new = _extract_new_channel_posts(resp.text, channel, known_links)
            for post in channel_new:
                link = _post_link(post)
                if not link or link in known_links:
                    continue
                known_links.add(link)
                incoming.append(post)
        except Exception as exc:
            logger.warning("Telegram channel %s parse failed: %s", channel, exc)

    merged_posts, added = _merge_telegram_posts(existing_posts, incoming)
    merged_posts = [_refresh_post_coords(post) for post in merged_posts]
    merged_posts = apply_posts_translations(merged_posts)
    geolocated = sum(1 for p in merged_posts if p.get("coords"))

    payload = {
        "posts": merged_posts,
        "total": len(merged_posts),
        "geolocated": geolocated,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "channels": _configured_channels(),
        "last_fetch_new": added,
    }

    with _data_lock:
        latest_data["telegram_osint"] = payload
    _mark_fresh("telegram_osint")
    logger.info(
        "Telegram OSINT: +%s new, %s retained (%s geolocated)",
        added,
        len(merged_posts),
        geolocated,
    )
    return payload
