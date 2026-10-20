"""Micro rolling 3-day average for Strategic Risk Analytics."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from analytics.daily_store import DailyRegionReading, DailySnapshot, date_id, save_daily
from analytics.gt_early_warning import GT_EarlyWarning
from analytics.micro_rolling import (
    capture_daily_readings,
    compute_micro_view,
    enrich_heatmap_features,
    micro_rolling_report,
)
from analytics.settings import GTAnalyticsSettings


@pytest.fixture()
def daily_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store = tmp_path / "daily"
    monkeypatch.setenv("GT_DAILY_STORE_DIR", str(store))
    return store


def _seed_engine() -> GT_EarlyWarning:
    engine = GT_EarlyWarning(GTAnalyticsSettings(enabled=True, base_prior=0.15))
    engine.process_feed_item(
        {
            "text": "Troop movement and military mobilization near border",
            "region": "ukraine",
            "source": "test",
            "source_type": "manual",
        }
    )
    return engine


def _save_day(day: date, region: str, peak: float) -> None:
    day_key = date_id(day)
    snap = DailySnapshot(date=day_key, regions={})
    snap.regions[region] = DailyRegionReading(
        region=region,
        composite_risk=peak * 0.9,
        financial=0.15,
        unrest=0.15,
        conflict=peak,
        peak_score=peak,
        readings=1,
        last_captured_at=f"{day_key}T12:00:00+00:00",
    )
    save_daily(snap)


def test_capture_daily_readings(daily_store: Path) -> None:
    engine = _seed_engine()
    result = capture_daily_readings(engine, when=date(2026, 6, 16))
    assert result["regions"] >= 1
    again = capture_daily_readings(engine, when=date(2026, 6, 16))
    assert again["regions"] >= 1


def test_3day_rolling_average_and_ignition(daily_store: Path) -> None:
    region = "ukraine"
    today = date(2026, 6, 16)
    _save_day(today - timedelta(days=2), region, 0.20)
    _save_day(today - timedelta(days=1), region, 0.22)
    _save_day(today, region, 0.45)

    view = compute_micro_view(region, as_of=today, window_days=3)
    assert view is not None
    assert view.days_in_window == 3
    assert view.risk_3d_avg == pytest.approx(0.29, abs=0.01)
    assert view.spot_risk == 0.45
    assert view.risk_delta == pytest.approx(0.16, abs=0.01)
    assert view.ignition is True


def test_enrich_heatmap_features(daily_store: Path) -> None:
    engine = _seed_engine()
    today = date(2026, 6, 16)
    capture_daily_readings(engine, when=today)
    heatmap = engine.get_risk_heatmap()
    enriched = enrich_heatmap_features(heatmap, as_of=today, window_days=3)
    feature = enriched["features"][0]
    props = feature["properties"]
    assert "risk_3d_avg" in props
    assert "risk_spot" in props
    assert "micro_ignition" in props


def test_micro_rolling_report(daily_store: Path) -> None:
    region = "ukraine"
    today = date(2026, 6, 16)
    _save_day(today - timedelta(days=1), region, 0.21)
    _save_day(today, region, 0.40)

    report = micro_rolling_report(as_of=today, window_days=3, limit=5)
    assert report["mode"] == "micro_rolling"
    assert report["window_days"] == 3
    assert report["regions_tracked"] >= 1


def test_openclaw_micro_command(daily_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from analytics.integration import reset_gt_engine
    from services.openclaw_channel import _dispatch_command

    monkeypatch.setenv("GT_ANALYTICS_ENABLED", "true")
    reset_gt_engine()
    result = _dispatch_command("gt_micro_rolling", {"window_days": 3, "compact": True})
    assert result["ok"] is True
    assert result["data"]["mode"] == "micro_rolling"


def test_route_query_micro_intent() -> None:
    from services.openclaw_routing import route_query

    plan = route_query("Show GT rolling 3 day average and ignition regions")
    assert plan["recommended"]["cmd"] == "gt_micro_rolling"