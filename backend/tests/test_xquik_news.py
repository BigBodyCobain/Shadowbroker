"""Xquik search enrichment for the shared news and threat feed."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import requests

from services.fetchers import xquik_news


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> object:
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


def _enable(monkeypatch) -> None:
    monkeypatch.setenv("XQUIK_ENABLED", "true")
    monkeypatch.setenv("XQUIK_API_KEY", "unit-test-key")
    monkeypatch.setenv("XQUIK_SEARCH_QUERY", "missile Kyiv")


def _tweet(tweet_id: str = "1234567890", username: str = "field_reporter") -> dict:
    return {
        "id": tweet_id,
        "text": "Missile strike reported in Kyiv",
        "createdAt": "2026-08-22T08:30:00Z",
        "url": "javascript:alert(1)",
        "author": {"username": username},
    }


def setup_function() -> None:
    xquik_news._reset_cache_for_tests()


def test_disabled_by_default_never_calls_xquik(monkeypatch) -> None:
    monkeypatch.delenv("XQUIK_ENABLED", raising=False)
    monkeypatch.setattr(
        xquik_news.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected request")),
    )

    assert xquik_news.fetch_xquik_entries() == []


def test_enabled_source_requires_key_and_query(monkeypatch) -> None:
    monkeypatch.setenv("XQUIK_ENABLED", "true")
    monkeypatch.delenv("XQUIK_API_KEY", raising=False)
    monkeypatch.setenv("XQUIK_SEARCH_QUERY", "Kyiv")
    monkeypatch.setattr(
        xquik_news.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected request")),
    )

    assert xquik_news.fetch_xquik_entries() == []


def test_request_is_bounded_and_normalizes_untrusted_posts(monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setenv("XQUIK_SEARCH_LIMIT", "999")
    monkeypatch.setenv("XQUIK_SEARCH_TIMEOUT_S", "999")
    monkeypatch.setattr(xquik_news, "outbound_user_agent", lambda purpose: "operator-test")
    seen: dict = {}

    def fake_get(url, *, headers, params, timeout, allow_redirects):
        seen.update(
            url=url,
            headers=headers,
            params=params,
            timeout=timeout,
            allow_redirects=allow_redirects,
        )
        return _Response(
            {
                "tweets": [
                    _tweet(),
                    _tweet(tweet_id="invalid"),
                    _tweet(tweet_id="9876543210", username="invalid-name"),
                    {**_tweet(tweet_id="111"), "createdAt": "not-a-date"},
                    {"id": "42", "text": "", "author": {"username": "empty"}},
                    {**_tweet(tweet_id="222"), "text": {"unexpected": "shape"}},
                    {**_tweet(tweet_id="333"), "createdAt": 1234567890},
                    "not-an-object",
                ]
            }
        )

    monkeypatch.setattr(xquik_news.requests, "get", fake_get)
    entries = xquik_news.fetch_xquik_entries()

    assert len(entries) == 1
    assert entries[0]["link"] == "https://x.com/field_reporter/status/1234567890"
    assert entries[0]["source"] == "Xquik/@field_reporter"
    assert entries[0]["published_parsed"].tm_year == 2026
    assert "javascript:" not in repr(entries)
    assert seen == {
        "url": "https://xquik.com/api/v1/x/tweets/search",
        "headers": {"User-Agent": "operator-test", "x-api-key": "unit-test-key"},
        "params": {
            "q": "missile Kyiv",
            "queryType": "Latest",
            "limit": 100,
            "replies": "exclude",
            "retweets": "exclude",
        },
        "timeout": (5, 30),
        "allow_redirects": False,
    }


def test_successful_results_are_cached_and_copied(monkeypatch) -> None:
    _enable(monkeypatch)
    calls = 0

    def fake_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _Response({"tweets": [_tweet()]})

    monkeypatch.setattr(xquik_news.requests, "get", fake_get)
    first = xquik_news.fetch_xquik_entries()
    first[0]["title"] = "changed"
    second = xquik_news.fetch_xquik_entries()

    assert calls == 1
    assert second[0]["title"] == "Missile strike reported in Kyiv"


def test_http_failure_keeps_cached_results_and_respects_poll_interval(monkeypatch) -> None:
    _enable(monkeypatch)
    responses = [_Response({"tweets": [_tweet()]}), _Response({}, status_code=429)]
    calls = 0

    def fake_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        return responses.pop(0)

    monkeypatch.setattr(xquik_news.requests, "get", fake_get)
    clock = iter((1000.0, 2801.0, 2802.0))
    monkeypatch.setattr(xquik_news.time, "monotonic", lambda: next(clock))

    expected = xquik_news.fetch_xquik_entries()
    assert xquik_news.fetch_xquik_entries() == expected
    assert xquik_news.fetch_xquik_entries() == expected
    assert calls == 2


def test_failure_without_cache_is_throttled(monkeypatch) -> None:
    _enable(monkeypatch)
    calls = 0

    def fake_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _Response({}, status_code=503)

    monkeypatch.setattr(xquik_news.requests, "get", fake_get)
    clock = iter((1000.0, 1001.0))
    monkeypatch.setattr(xquik_news.time, "monotonic", lambda: next(clock))

    assert xquik_news.fetch_xquik_entries() == []
    assert xquik_news.fetch_xquik_entries() == []
    assert calls == 1


def test_api_key_rotation_bypasses_failed_attempt_backoff(monkeypatch) -> None:
    _enable(monkeypatch)
    responses = [_Response({}, status_code=401), _Response({"tweets": [_tweet()]})]
    calls = 0

    def fake_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        return responses.pop(0)

    monkeypatch.setattr(xquik_news.requests, "get", fake_get)

    assert xquik_news.fetch_xquik_entries() == []
    monkeypatch.setenv("XQUIK_API_KEY", "rotated-unit-test-key")
    assert len(xquik_news.fetch_xquik_entries()) == 1
    assert calls == 2


def test_failed_query_change_does_not_reuse_another_query(monkeypatch) -> None:
    _enable(monkeypatch)
    responses = [_Response({"tweets": [_tweet()]}), _Response({}, status_code=503)]
    monkeypatch.setattr(
        xquik_news.requests,
        "get",
        lambda *args, **kwargs: responses.pop(0),
    )
    assert len(xquik_news.fetch_xquik_entries()) == 1

    monkeypatch.setenv("XQUIK_SEARCH_QUERY", "different region")
    assert xquik_news.fetch_xquik_entries() == []


def test_redirect_and_invalid_json_fail_closed(monkeypatch) -> None:
    _enable(monkeypatch)
    responses = [_Response({}, status_code=302), _Response(ValueError("invalid JSON"))]

    monkeypatch.setattr(xquik_news.requests, "get", lambda *args, **kwargs: responses.pop(0))
    assert xquik_news.fetch_xquik_entries() == []
    monkeypatch.setenv("XQUIK_SEARCH_QUERY", "different region")
    assert xquik_news.fetch_xquik_entries() == []


def test_news_fetch_merges_xquik_posts_into_existing_pipeline(monkeypatch) -> None:
    from services import news_feed_config
    from services.fetchers import _store, news

    monkeypatch.setenv("NEWS_ENABLED", "true")
    monkeypatch.setattr(
        news_feed_config,
        "get_feeds",
        lambda: [{"name": "Empty RSS", "url": "https://example.test/rss", "weight": 3}],
    )
    monkeypatch.setattr(news, "fetch_with_curl", lambda *args, **kwargs: SimpleNamespace(text=""))
    monkeypatch.setattr(news.feedparser, "parse", lambda text: SimpleNamespace(entries=[]))
    monkeypatch.setattr(
        news,
        "fetch_xquik_entries",
        lambda: [
            {
                **_tweet(),
                "title": "Missile strike reported in Kyiv",
                "summary": "",
                "link": "https://x.com/field_reporter/status/1234567890",
                "published": "2026-08-22T08:30:00Z",
                "published_parsed": time.gmtime(),
                "source": "Xquik/@field_reporter",
            }
        ],
    )
    monkeypatch.setattr(news, "enrich_news_items", lambda *args: None)
    monkeypatch.setattr(news, "detect_breaking_events", lambda *args: None)
    monkeypatch.setattr(news, "compute_global_threat_level", lambda *args, **kwargs: {"score": 1})

    news.fetch_news()

    item = _store.latest_data["news"][0]
    assert item["source"] == "Xquik/@field_reporter"
    assert item["link"] == "https://x.com/field_reporter/status/1234567890"
    assert item["coords"] == [50.45, 30.523]
    assert item["risk_score"] == 5


def test_news_kill_switch_blocks_xquik_requests(monkeypatch) -> None:
    from services.fetchers import _store, news

    monkeypatch.setenv("NEWS_ENABLED", "false")
    monkeypatch.setitem(_store.latest_data, "news", [{"title": "old"}])
    monkeypatch.setattr(
        news,
        "fetch_xquik_entries",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected Xquik request")),
    )

    news.fetch_news()

    assert _store.latest_data["news"] == []


def test_api_key_is_available_to_the_server_side_settings_registry() -> None:
    from services.api_settings import ALLOWED_ENV_KEYS, API_REGISTRY

    entry = next(item for item in API_REGISTRY if item["id"] == "xquik_api_key")
    assert entry["env_key"] == "XQUIK_API_KEY"
    assert entry["required"] is False
    assert "XQUIK_API_KEY" in ALLOWED_ENV_KEYS


def test_documented_xquik_settings_reach_the_backend_container() -> None:
    root = Path(__file__).resolve().parents[2]
    settings = {
        "XQUIK_ENABLED",
        "XQUIK_API_KEY",
        "XQUIK_SEARCH_QUERY",
        "XQUIK_SEARCH_LIMIT",
        "XQUIK_SEARCH_INTERVAL_MINUTES",
        "XQUIK_SEARCH_TIMEOUT_S",
    }
    for relative_path in (".env.example", "backend/.env.example", "docker-compose.yml"):
        text = (root / relative_path).read_text(encoding="utf-8")
        assert all(setting in text for setting in settings)
