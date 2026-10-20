"""Prediction market fetch timing uses jitter to reduce poll fingerprinting."""

from unittest.mock import MagicMock, patch

import pytest

from services.fetchers import prediction_markets as pm


@pytest.fixture(autouse=True)
def clear_market_cache():
    pm._market_cache.clear()
    yield
    pm._market_cache.clear()


def test_pre_fetch_jitter_sleeps_when_configured(monkeypatch):
    monkeypatch.setattr(pm, "_PRE_FETCH_JITTER_S", 10.0)
    sleeps: list[float] = []
    monkeypatch.setattr(pm.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(pm.random, "uniform", lambda _a, _b: 4.5)

    pm._apply_pre_fetch_jitter()

    assert sleeps == [4.5]


def test_fetch_raw_applies_provider_gap(monkeypatch):
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setattr(pm, "_apply_pre_fetch_jitter", lambda: None)
    gap_calls: list[int] = []

    def _track_gap():
        gap_calls.append(1)

    monkeypatch.setattr(pm, "_apply_provider_gap_jitter", _track_gap)
    monkeypatch.setattr(pm, "_fetch_polymarket_events", lambda: [])
    monkeypatch.setattr(pm, "_fetch_kalshi_events", lambda: [])
    monkeypatch.setattr(pm, "_merge_markets", lambda _p, _k: [])

    pm.fetch_prediction_markets_raw()

    assert gap_calls == [1]


def test_pace_provider_adds_per_page_jitter(monkeypatch):
    monkeypatch.setattr(pm, "_POLYMARKET_PAGE_DELAY_JITTER_S", 1.0)
    monkeypatch.setattr(pm, "_provider_last_request_at", {"polymarket": pm.time.monotonic()})
    monkeypatch.setattr(pm.random, "uniform", lambda _a, _b: 0.5)
    sleeps: list[float] = []
    monkeypatch.setattr(pm.time, "sleep", lambda s: sleeps.append(s))

    pm._pace_provider("polymarket", 0.02)

    assert sleeps == [pytest.approx(0.52)]
