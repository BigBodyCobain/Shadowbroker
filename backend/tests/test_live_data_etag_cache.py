"""Unit tests for ETag-keyed live-data orjson byte cache (P4)."""
from __future__ import annotations

from routers import data as data_router


def test_cached_live_data_bytes_invokes_factory_once_per_etag():
    calls = {"n": 0}

    def _build():
        calls["n"] += 1
        return {"ok": True, "n": calls["n"]}

    etag = "test|etag|cache-hit"
    # Isolate from other tests / endpoint warm-up.
    with data_router._LIVE_DATA_BYTES_CACHE_LOCK:
        data_router._LIVE_DATA_BYTES_CACHE.pop(etag, None)

    first = data_router._cached_live_data_bytes(etag, _build)
    second = data_router._cached_live_data_bytes(etag, _build)

    assert first == second
    assert calls["n"] == 1
    assert b'"ok"' in first


def test_cached_live_data_bytes_misses_on_etag_change():
    calls = {"n": 0}

    def _build():
        calls["n"] += 1
        return {"n": calls["n"]}

    etag_a = "test|etag|a"
    etag_b = "test|etag|b"
    with data_router._LIVE_DATA_BYTES_CACHE_LOCK:
        data_router._LIVE_DATA_BYTES_CACHE.pop(etag_a, None)
        data_router._LIVE_DATA_BYTES_CACHE.pop(etag_b, None)

    a = data_router._cached_live_data_bytes(etag_a, _build)
    b = data_router._cached_live_data_bytes(etag_b, _build)

    assert a != b
    assert calls["n"] == 2
