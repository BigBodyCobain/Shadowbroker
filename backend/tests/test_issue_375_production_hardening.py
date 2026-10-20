"""Regression tests for GitHub #375 production-readiness fixes."""

import os

import pytest


class TestDevBindHost:
    def test_defaults_to_loopback(self, monkeypatch):
        monkeypatch.delenv("SHADOWBROKER_DEV_BIND_ALL", raising=False)
        from main import _dev_uvicorn_bind_host

        assert _dev_uvicorn_bind_host() == "127.0.0.1"

    @pytest.mark.parametrize("value", ("1", "true", "yes", "on", "TRUE"))
    def test_bind_all_opt_in(self, monkeypatch, value):
        monkeypatch.setenv("SHADOWBROKER_DEV_BIND_ALL", value)
        from main import _dev_uvicorn_bind_host

        assert _dev_uvicorn_bind_host() == "0.0.0.0"


class TestDataStoreSnapshots:
    def test_deepcopy_snapshot_isolated_from_store(self):
        from services.fetchers import _store

        original = [{"title": "baseline"}]
        with _store._data_lock:
            _store.latest_data["news"] = list(original)
        snap = _store.get_latest_data_deepcopy_snapshot()
        snap["news"][0]["title"] = "mutated"
        with _store._data_lock:
            assert _store.latest_data["news"][0]["title"] == "baseline"

    def test_subset_deepcopy_isolated(self):
        from services.fetchers import _store

        with _store._data_lock:
            _store.latest_data["news"] = [{"title": "subset"}]
        snap = _store.get_latest_data_subset("news")
        snap["news"][0]["title"] = "changed"
        with _store._data_lock:
            assert _store.latest_data["news"][0]["title"] == "subset"


class TestHeavyFetchExecutorRouting:
    def test_slow_tier_uses_slow_executor(self):
        from services.data_fetcher import (
            _SLOW_EXECUTOR,
            _SHARED_EXECUTOR,
            _executor_for_task_label,
        )

        assert _executor_for_task_label("slow-tier-refresh") is _SLOW_EXECUTOR
        assert _executor_for_task_label("startup-heavy-warm") is _SLOW_EXECUTOR
        assert _executor_for_task_label("fast-tier-refresh") is _SHARED_EXECUTOR


class TestLiveDataFullEndpoint:
    def test_live_data_supports_etag_304(self, client):
        r1 = client.get("/api/live-data")
        assert r1.status_code == 200
        etag = r1.headers.get("etag")
        assert etag
        r2 = client.get("/api/live-data", headers={"If-None-Match": etag})
        assert r2.status_code == 304
        assert r2.headers.get("etag") == etag

    def test_live_data_fast_serializes_non_json_native_values(self, client):
        from datetime import datetime, timezone

        from services.fetchers import _store

        with _store._data_lock:
            prior = _store.latest_data.get("sigint")
            _store.latest_data["sigint"] = [
                {"source": "aprs", "observed": datetime(2026, 1, 1, tzinfo=timezone.utc)},
            ]
        _store.bump_data_version()
        try:
            r = client.get("/api/live-data/fast")
            assert r.status_code == 200
            assert "2026-01-01" in r.text
        finally:
            with _store._data_lock:
                _store.latest_data["sigint"] = prior
            _store.bump_data_version()

    def test_live_data_serializes_non_json_native_values(self, client):
        from datetime import datetime, timezone

        from services.fetchers import _store

        with _store._data_lock:
            prior = _store.latest_data.get("gdelt")
            _store.latest_data["gdelt"] = [
                {"observed": datetime(2026, 1, 1, tzinfo=timezone.utc)},
            ]
        _store.bump_data_version()
        try:
            r = client.get("/api/live-data")
            assert r.status_code == 200
            assert "2026-01-01" in r.text
        finally:
            with _store._data_lock:
                _store.latest_data["gdelt"] = prior
            _store.bump_data_version()


class TestSlowTaskConcurrency:
    def test_run_tasks_caps_batch_size_to_executor_workers(self, monkeypatch):
        from unittest.mock import MagicMock

        import services.data_fetcher as df

        class _FakeExecutor:
            _max_workers = 2

            def submit(self, func):
                return MagicMock()

        mock_executor = _FakeExecutor()
        monkeypatch.setattr(df, "_executor_for_task_label", lambda _label: mock_executor)
        monkeypatch.setattr(df, "_SLOW_FETCH_CONCURRENCY", 8)

        batch_sizes = []

        def _capture_drain(_label, futures):
            batch_sizes.append(len(futures))

        monkeypatch.setattr(df, "_drain_task_futures", _capture_drain)

        jobs = [lambda: None for _ in range(5)]
        df._run_tasks("slow-tier-test", jobs)

        assert batch_sizes == [2, 2, 1]


class TestFetcherRetryScope:
    def test_http_error_is_not_retried(self, monkeypatch):
        import requests

        from services.fetchers.retry import with_retry

        attempts = {"n": 0}

        @with_retry(max_retries=2, base_delay=0.01)
        def _raises_http():
            attempts["n"] += 1
            raise requests.HTTPError("403 Client Error")

        with pytest.raises(requests.HTTPError):
            _raises_http()
        assert attempts["n"] == 1
