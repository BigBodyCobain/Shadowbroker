"""Rolling weekly operational validation for Strategic Risk Analytics."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from analytics.backtest import DEFAULT_BACKTEST_ALERT_THRESHOLD
from analytics.gt_early_warning import GT_EarlyWarning
from analytics.integration import reset_gt_engine
from analytics.rolling_backtest import (
    freeze_weekly_snapshot,
    iso_week_id,
    label_regions,
    rolling_report,
    score_week,
)
from analytics.settings import GTAnalyticsSettings
from analytics.weekly_store import RegionSnapshot, WeeklySnapshot, load_week


@pytest.fixture()
def rolling_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store = tmp_path / "gt_rolling"
    monkeypatch.setenv("GT_ROLLING_STORE_DIR", str(store))
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
    engine.process_feed_item(
        {
            "text": "Routine diplomatic statement about trade",
            "region": "canada",
            "source": "test",
            "source_type": "manual",
        }
    )
    return engine


def test_iso_week_id_format() -> None:
    assert iso_week_id(date(2026, 6, 16)) == "2026-W25"


def test_freeze_and_score_week(rolling_store: Path) -> None:
    engine = _seed_engine()
    result = freeze_weekly_snapshot(
        week_id="2026-W10",
        engine=engine,
        frozen_by="test",
    )
    assert result["ok"] is True
    assert result["created"] is True
    assert result["region_count"] >= 2

    snapshot = load_week("2026-W10")
    assert snapshot is not None
    ukraine = next(row for row in snapshot.regions if row.region == "ukraine")
    assert ukraine.alerted is True

    pending_score = score_week(snapshot)
    assert pending_score.labeled == 0
    assert pending_score.scorable is False

    label_regions(
        "2026-W10",
        [
            {"region": "ukraine", "label": "true_escalation"},
            {"region": "canada", "label": "benign"},
        ],
    )
    labeled = load_week("2026-W10")
    assert labeled is not None
    scored = score_week(labeled)
    assert scored.labeled == 2
    assert scored.true_positives == 1
    assert scored.true_negatives == 1
    assert scored.accuracy == 1.0
    assert scored.confidence_rate >= 0.0


def test_freeze_is_idempotent(rolling_store: Path) -> None:
    engine = _seed_engine()
    first = freeze_weekly_snapshot(week_id="2026-W11", engine=engine)
    second = freeze_weekly_snapshot(week_id="2026-W11", engine=engine)
    assert first["created"] is True
    assert second["created"] is False


def test_rolling_report_trend(rolling_store: Path) -> None:
    engine = _seed_engine()
    freeze_weekly_snapshot(week_id="2026-W20", engine=engine)
    freeze_weekly_snapshot(week_id="2026-W21", engine=engine)

    label_regions("2026-W20", [{"region": "ukraine", "label": "true_escalation"}])
    label_regions(
        "2026-W21",
        [
            {"region": "ukraine", "label": "true_escalation"},
            {"region": "canada", "label": "benign"},
        ],
    )

    report = rolling_report(weeks=4)
    assert report["mode"] == "rolling_operational"
    assert report["alert_threshold"] == DEFAULT_BACKTEST_ALERT_THRESHOLD
    assert len(report["trend"]) == 2
    assert report["latest"] is not None


def test_openclaw_rolling_commands(
    rolling_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from analytics.integration import get_gt_engine
    from services.openclaw_channel import _dispatch_command

    monkeypatch.setenv("GT_ANALYTICS_ENABLED", "true")
    reset_gt_engine()
    engine = get_gt_engine()
    assert engine is not None
    engine.process_feed_item(
        {
            "text": "Troop movement and military mobilization near border",
            "region": "ukraine",
            "source": "test",
            "source_type": "manual",
        }
    )

    freeze = _dispatch_command("gt_rolling_freeze", {"week_id": "2026-W30", "compact": True})
    assert freeze["ok"] is True
    assert freeze["data"]["enabled"] is True

    label = _dispatch_command(
        "gt_rolling_label",
        {
            "week_id": "2026-W30",
            "region": "ukraine",
            "label": "false_alarm",
        },
    )
    assert label["ok"] is True
    assert label["data"]["updated"] == 1

    trend = _dispatch_command("gt_rolling_backtest", {"weeks": 4, "compact": True})
    assert trend["ok"] is True
    assert trend["data"]["mode"] == "rolling_operational"


def test_route_query_rolling_intent() -> None:
    from services.openclaw_routing import route_query

    plan = route_query("Show GT rolling operational backtest week over week")
    assert plan["recommended"]["cmd"] == "gt_rolling_backtest"

    freeze_plan = route_query("Freeze weekly GT snapshot for operational validation")
    assert freeze_plan["recommended"]["cmd"] == "gt_rolling_freeze"