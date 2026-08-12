"""Regression tests for the throttled fast startup cache writer.

The fast tier runs every 60s but the snapshot it persists is only read at cold
boot, where staleness up to ``FAST_STARTUP_CACHE_MAX_AGE_S`` (6h) is accepted.
``_save_fast_startup_cache`` therefore throttles itself; these tests pin that
behaviour (and the shutdown-flush bypass) so it cannot silently regress.
"""
from __future__ import annotations

import json

import pytest

# Captured at import time: the autouse conftest fixture patches
# ``services.data_fetcher.stop_scheduler`` with a MagicMock for every test, so grab a
# reference to the real function before that happens.
from services.data_fetcher import stop_scheduler as _real_stop_scheduler


@pytest.fixture()
def cache_env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point the cache at a tmp dir, reset the throttle, and fake the clock."""
    from services import data_fetcher

    cache_path = tmp_path / "fast_startup_cache.json"
    monkeypatch.setattr(data_fetcher, "_FAST_STARTUP_CACHE_PATH", cache_path)
    monkeypatch.setattr(data_fetcher, "_FAST_STARTUP_CACHE_SAVE_INTERVAL_S", 600.0)
    monkeypatch.setattr(data_fetcher, "_last_fast_startup_cache_save", 0.0)

    clock = {"now": 1000.0}
    monkeypatch.setattr(data_fetcher.time, "monotonic", lambda: clock["now"])

    # A tiny payload so the test never writes a real multi-MB snapshot.
    monkeypatch.setattr(data_fetcher, "_FAST_STARTUP_CACHE_KEYS", ("ships",))
    monkeypatch.setitem(data_fetcher.latest_data, "ships", [{"id": "vessel-1"}])

    return data_fetcher, cache_path, clock


def test_second_save_within_interval_is_skipped(cache_env):
    data_fetcher, cache_path, clock = cache_env

    data_fetcher._save_fast_startup_cache()
    assert cache_path.exists()
    first_mtime = cache_path.stat().st_mtime_ns
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["layers"]["ships"] == [{"id": "vessel-1"}]

    # Next fast-tier tick, 60s later: still inside the 600s window.
    clock["now"] += 60.0
    data_fetcher.latest_data["ships"] = [{"id": "vessel-2"}]
    data_fetcher._save_fast_startup_cache()

    assert cache_path.stat().st_mtime_ns == first_mtime
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["layers"]["ships"] == [{"id": "vessel-1"}]


def test_save_resumes_once_interval_elapses(cache_env):
    data_fetcher, cache_path, clock = cache_env

    data_fetcher._save_fast_startup_cache()
    clock["now"] += 601.0
    data_fetcher.latest_data["ships"] = [{"id": "vessel-2"}]
    data_fetcher._save_fast_startup_cache()

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["layers"]["ships"] == [{"id": "vessel-2"}]


def test_force_bypasses_throttle(cache_env):
    data_fetcher, cache_path, clock = cache_env

    data_fetcher._save_fast_startup_cache()
    clock["now"] += 1.0
    data_fetcher.latest_data["ships"] = [{"id": "vessel-2"}]
    data_fetcher._save_fast_startup_cache(force=True)

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["layers"]["ships"] == [{"id": "vessel-2"}]


def test_failed_write_does_not_advance_throttle(cache_env, monkeypatch):
    data_fetcher, cache_path, clock = cache_env

    real_dumps = data_fetcher.json.dumps
    fail = {"on": True}

    def maybe_boom(*args, **kwargs):
        if fail["on"]:
            raise OSError("disk full")
        return real_dumps(*args, **kwargs)

    monkeypatch.setattr(data_fetcher.json, "dumps", maybe_boom)
    data_fetcher._save_fast_startup_cache()
    assert not cache_path.exists()
    assert data_fetcher._last_fast_startup_cache_save == 0.0

    # The very next tick must retry rather than being suppressed for 10 minutes.
    fail["on"] = False
    clock["now"] += 60.0
    data_fetcher._save_fast_startup_cache()
    assert cache_path.exists()


def test_stop_scheduler_flushes_cache(monkeypatch):
    from services import data_fetcher

    calls: list[bool] = []
    monkeypatch.setattr(
        data_fetcher,
        "_save_fast_startup_cache",
        lambda force=False: calls.append(force),
    )
    monkeypatch.setattr(data_fetcher, "_scheduler", None)
    monkeypatch.setattr(data_fetcher._SLOW_EXECUTOR, "shutdown", lambda **kw: None)

    _real_stop_scheduler()
    assert calls == [True]


def test_stop_scheduler_survives_flush_failure(monkeypatch):
    from services import data_fetcher

    def boom(force=False):
        raise RuntimeError("nope")

    monkeypatch.setattr(data_fetcher, "_save_fast_startup_cache", boom)
    monkeypatch.setattr(data_fetcher, "_scheduler", None)
    shutdown_calls: list[dict] = []
    monkeypatch.setattr(
        data_fetcher._SLOW_EXECUTOR, "shutdown", lambda **kw: shutdown_calls.append(kw)
    )

    _real_stop_scheduler()
    assert shutdown_calls, "executor shutdown must still run after a flush failure"
