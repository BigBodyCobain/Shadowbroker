"""Opt-in X post search for the shared news and threat feed."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests

from services.network_utils import outbound_user_agent


logger = logging.getLogger("services.data_fetcher")

_SEARCH_URL = "https://xquik.com/api/v1/x/tweets/search"
_TWEET_ID_RE = re.compile(r"^[0-9]{1,32}$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_MAX_RESULTS = 100
_MAX_TEXT_LENGTH = 500

_cache_lock = threading.Lock()
_cache_signature: tuple[str, int] | None = None
_cache_entries: list[dict[str, Any]] = []
_attempt_signature: tuple[str, int, str] | None = None
_last_attempt_at: float | None = None


def xquik_fetch_enabled() -> bool:
    """Return whether the operator enabled Xquik search enrichment."""
    return str(os.environ.get("XQUIK_ENABLED", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _published_parts(value: object) -> time.struct_time | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).timetuple()


def _normalize_tweet(tweet: object) -> dict[str, Any] | None:
    if not isinstance(tweet, dict):
        return None
    tweet_id = str(tweet.get("id") or "").strip()
    raw_text = tweet.get("text")
    author = tweet.get("author")
    username = str(author.get("username") or "").strip() if isinstance(author, dict) else ""
    created_at = tweet.get("createdAt")
    if (
        not _TWEET_ID_RE.fullmatch(tweet_id)
        or not _USERNAME_RE.fullmatch(username)
        or not isinstance(raw_text, str)
        or not isinstance(created_at, str)
    ):
        return None

    text = " ".join(raw_text.split())
    created_at = created_at.strip()
    if not text:
        return None
    published_parts = _published_parts(created_at)
    if published_parts is None:
        return None
    entry: dict[str, Any] = {
        "title": text[:_MAX_TEXT_LENGTH],
        "summary": "",
        "link": f"https://x.com/{username}/status/{tweet_id}",
        "published": created_at,
        "published_parsed": published_parts,
        "source": f"Xquik/@{username}",
    }
    return entry


def _request_entries(api_key: str, query: str, limit: int) -> list[dict[str, Any]] | None:
    timeout = _bounded_int("XQUIK_SEARCH_TIMEOUT_S", 10, 1, 30)
    try:
        response = requests.get(
            _SEARCH_URL,
            headers={
                "User-Agent": outbound_user_agent("xquik-search"),
                "x-api-key": api_key,
            },
            params={
                "q": query,
                "queryType": "Latest",
                "limit": limit,
                "replies": "exclude",
                "retweets": "exclude",
            },
            timeout=(5, timeout),
            allow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            raise requests.HTTPError("Xquik search redirected")
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Xquik search failed: %s", type(exc).__name__)
        return None

    tweets = payload.get("tweets") if isinstance(payload, dict) else None
    if not isinstance(tweets, list):
        logger.warning("Xquik search returned an invalid response")
        return None

    entries = [entry for tweet in tweets[:limit] if (entry := _normalize_tweet(tweet))]
    logger.info("Xquik search returned %d usable posts", len(entries))
    return entries


def _credential_fingerprint(api_key: str) -> str:
    """Return a non-secret cache key so credential rotation retries immediately."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def fetch_xquik_entries() -> list[dict[str, Any]]:
    """Return cached, normalized X posts for the configured search query."""
    if not xquik_fetch_enabled():
        return []

    api_key = str(os.environ.get("XQUIK_API_KEY", "")).strip()
    query = str(os.environ.get("XQUIK_SEARCH_QUERY", "")).strip()
    if not api_key or not query:
        logger.warning("Xquik search requires XQUIK_API_KEY and XQUIK_SEARCH_QUERY")
        return []

    limit = _bounded_int("XQUIK_SEARCH_LIMIT", 20, 1, _MAX_RESULTS)
    interval_seconds = _bounded_int("XQUIK_SEARCH_INTERVAL_MINUTES", 30, 5, 1440) * 60
    cache_signature = (query, limit)
    attempt_signature = (query, limit, _credential_fingerprint(api_key))

    global _cache_entries, _cache_signature
    global _attempt_signature, _last_attempt_at
    with _cache_lock:
        now = time.monotonic()
        if (
            _attempt_signature == attempt_signature
            and _last_attempt_at is not None
            and now - _last_attempt_at < interval_seconds
        ):
            if _cache_signature == cache_signature:
                return [dict(entry) for entry in _cache_entries]
            return []

        # Record every outbound attempt, not only successes. This keeps an
        # unhealthy provider from being retried by the 5-minute news scheduler
        # more frequently than the operator-configured Xquik interval.
        _attempt_signature = attempt_signature
        _last_attempt_at = now

        entries = _request_entries(api_key, query, limit)
        if entries is not None:
            _cache_signature = cache_signature
            _cache_entries = entries
        if _cache_signature == cache_signature:
            return [dict(entry) for entry in _cache_entries]
        return []


def _reset_cache_for_tests() -> None:
    global _cache_entries, _cache_signature
    global _attempt_signature, _last_attempt_at
    with _cache_lock:
        _cache_signature = None
        _cache_entries = []
        _attempt_signature = None
        _last_attempt_at = None
