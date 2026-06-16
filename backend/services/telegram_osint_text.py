"""Shared Telegram OSINT post text helpers for search and watchdog matching."""
from __future__ import annotations

from typing import Any

from services.telegram_translate import source_lang_label


def iter_telegram_posts(layer_payload: Any) -> list[dict[str, Any]]:
    """Normalize telegram_osint layer payloads into a list of post dicts."""
    if isinstance(layer_payload, list):
        return [post for post in layer_payload if isinstance(post, dict)]
    if isinstance(layer_payload, dict):
        posts = layer_payload.get("posts")
        if isinstance(posts, list):
            return [post for post in posts if isinstance(post, dict)]
    return []


def telegram_post_search_text(post: dict[str, Any]) -> str:
    """Build a lowercase haystack for keyword matching (translated + original)."""
    parts = (
        post.get("title_translated"),
        post.get("description_translated"),
        post.get("title"),
        post.get("description"),
        post.get("source"),
        post.get("channel"),
    )
    return " ".join(str(part).strip() for part in parts if str(part or "").strip()).lower()


def telegram_post_display_title(post: dict[str, Any]) -> str:
    """Prefer translated headline for alerts and agent-facing summaries."""
    translated = str(post.get("title_translated") or post.get("description_translated") or "").strip()
    if translated:
        return translated.split("\n", 1)[0][:200]
    return str(post.get("title") or post.get("description") or "").strip()[:200]


def telegram_post_match_entry(post: dict[str, Any]) -> dict[str, Any]:
    """Compact match record for watchdog alerts and search results."""
    lat, lng = None, None
    coords = post.get("coords")
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        lat, lng = coords[0], coords[1]
    return {
        "source": "telegram_osint",
        "title": telegram_post_display_title(post),
        "original_title": str(post.get("title") or "").strip(),
        "url": post.get("link") or "",
        "channel": post.get("channel") or post.get("source") or "",
        "risk_score": post.get("risk_score"),
        "source_lang": post.get("source_lang"),
        "source_lang_label": post.get("source_lang_label") or source_lang_label(post.get("source_lang")),
        "lat": lat,
        "lng": lng,
        "id": post.get("id") or post.get("link") or "",
    }


def keyword_matches_telegram_post(post: dict[str, Any], keyword: str) -> bool:
    needle = str(keyword or "").strip().lower()
    if not needle:
        return False
    return needle in telegram_post_search_text(post)