"""OpenClaw routing and commands for Strategic Risk Analytics."""

from __future__ import annotations

import pytest

from analytics.integration import reset_gt_engine
from services.openclaw_routing import route_query


def test_route_query_gt_analyze_intent() -> None:
    plan = route_query("Run GT analysis on UK and Europe feeds")
    assert plan["intent"] == "gt_analyze"
    assert plan["recommended"]["cmd"] == "gt_analyze"


def test_route_query_gt_dossier_intent() -> None:
    plan = route_query("GT rationale dossier for ukraine strategic risk")
    assert plan["recommended"]["cmd"] in {"gt_dossier", "gt_analyze"}


def test_gt_analyze_command_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.openclaw_channel import _dispatch_command

    monkeypatch.delenv("GT_ANALYTICS_ENABLED", raising=False)
    reset_gt_engine()
    result = _dispatch_command("gt_analyze", {})
    assert result["ok"] is False


def test_route_query_gt_backtest_intent() -> None:
    plan = route_query("Run GT historical backtest with Wilson confidence")
    assert plan["intent"] == "gt_backtest"
    assert plan["recommended"]["cmd"] == "gt_backtest"
    assert plan["recommended"]["args"]["expanded"] is True


def test_gt_backtest_command_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.openclaw_channel import _dispatch_command

    monkeypatch.setenv("GT_ANALYTICS_ENABLED", "true")
    reset_gt_engine()
    result = _dispatch_command("gt_backtest", {"expanded": True, "compact": True})
    assert result["ok"] is True
    data = result["data"]
    assert data["enabled"] is True
    assert data["accuracy"] == 1.0
    assert data["confidence_rate"] >= 0.95
    assert data["meets_target"] is True
    assert "cases" not in data


def test_gt_backtest_command_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.openclaw_channel import _dispatch_command

    monkeypatch.delenv("GT_ANALYTICS_ENABLED", raising=False)
    reset_gt_engine()
    result = _dispatch_command("gt_backtest", {})
    assert result["ok"] is True
    assert result["data"]["enabled"] is False