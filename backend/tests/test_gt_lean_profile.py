"""Lean-profile gating for Strategic Risk Analytics."""

from __future__ import annotations

import pytest

from analytics.integration import get_gt_engine, maybe_refresh_gt_analytics, reset_gt_engine
from analytics.settings import gt_engine_operational, gt_scheduled_ingest_enabled


def test_gt_engine_blocked_on_lean_without_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GT_ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("GT_ANALYTICS_PROFILE", "lean")
    monkeypatch.delenv("GT_ANALYTICS_ACK_LOW_CPU", raising=False)
    reset_gt_engine()
    assert gt_engine_operational() is False
    assert get_gt_engine() is None


def test_gt_engine_allowed_on_lean_with_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GT_ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("GT_ANALYTICS_PROFILE", "lean")
    monkeypatch.setenv("GT_ANALYTICS_ACK_LOW_CPU", "true")
    reset_gt_engine()
    assert gt_engine_operational() is True
    assert get_gt_engine() is not None


def test_scheduled_ingest_skipped_on_lean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GT_ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("GT_ANALYTICS_PROFILE", "lean")
    monkeypatch.delenv("GT_ANALYTICS_ACK_LOW_CPU", raising=False)
    reset_gt_engine()
    assert gt_scheduled_ingest_enabled() is False
    maybe_refresh_gt_analytics()
