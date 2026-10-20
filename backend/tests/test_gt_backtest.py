"""Historical backtest validation for Strategic Risk Analytics."""

from __future__ import annotations

from analytics.backtest import (
    DEFAULT_BACKTEST_ALERT_THRESHOLD,
    MAX_BACKTEST_ALERT_THRESHOLD,
    run_historical_backtest,
    tune_alert_threshold,
    wilson_interval,
)
from analytics.historical_events import default_historical_cases, expanded_historical_cases


def test_wilson_interval_perfect_run() -> None:
    lower, upper = wilson_interval(18, 18)
    assert lower >= 0.80
    assert upper == 1.0


def test_base_suite_meets_eighty_percent_confidence() -> None:
    report = run_historical_backtest(
        default_historical_cases(),
        use_expanded_suite=False,
        target_confidence=0.80,
    )
    assert report.accuracy >= 0.95
    assert report.confidence_rate >= 0.80
    assert report.meets_target
    assert report.false_positives == 0
    assert report.false_negatives == 0


def test_expanded_suite_meets_ninety_five_percent_confidence() -> None:
    threshold, report = tune_alert_threshold(target_confidence=0.95)
    assert len(expanded_historical_cases()) >= 80
    assert report.accuracy == 1.0
    assert report.confidence_rate >= 0.95
    assert report.meets_target
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert DEFAULT_BACKTEST_ALERT_THRESHOLD <= threshold <= MAX_BACKTEST_ALERT_THRESHOLD


def test_default_backtest_threshold_on_expanded_suite() -> None:
    report = run_historical_backtest(
        use_expanded_suite=True,
        target_confidence=0.95,
    )
    assert report.alert_threshold == DEFAULT_BACKTEST_ALERT_THRESHOLD
    assert report.accuracy == 1.0
    assert report.confidence_rate >= 0.95