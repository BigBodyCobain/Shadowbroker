"""Historical backtesting for Strategic Risk Analytics.

This is **benchmark validation**, not forward-weeks prediction on live feeds.

The suite scores whether costly-signal patterns + Bayesian updating correctly
classify curated pre-crisis text snippets (positive cases) vs cheap-talk
controls (negative cases) at a tuned alert threshold. A high accuracy on this
labeled corpus does **not** imply the engine will score 100% on messy,
adversarial, or weeks-ahead production telemetry — opponents adapt, labels are
easier here than in the wild, and the window is retrospective.

Reports accuracy and a conservative Wilson 95% confidence lower bound on the
benchmark only. Treat 100% here as "classifier fits the benchmark," not "ship
it for multi-week forecasting." For live week-over-week scoring with delayed
labels, see ``rolling_backtest.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from analytics.gt_early_warning import GT_EarlyWarning
from analytics.historical_events import (
    HistoricalCase,
    default_historical_cases,
    expanded_historical_cases,
)
from analytics.settings import GTAnalyticsSettings

DomainName = Literal["financial", "unrest", "conflict"]

# Validated on expanded suite (82 cases, Wilson lower >= 0.95 at 100% accuracy).
DEFAULT_BACKTEST_ALERT_THRESHOLD = 0.26
MAX_BACKTEST_ALERT_THRESHOLD = 0.39


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    name: str
    kind: str
    region: str
    domain: str
    expected_alert: bool
    alerted: bool
    correct: bool
    peak_domain_risk: float
    peak_composite_risk: float
    costly_signals: list[str]
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BacktestReport:
    total_cases: int
    correct: int
    accuracy: float
    confidence_rate: float
    wilson_lower_95: float
    wilson_upper_95: float
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    sensitivity: float
    specificity: float
    alert_threshold: float
    target_confidence: float
    meets_target: bool
    case_results: tuple[CaseResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
            "confidence_rate": round(self.confidence_rate, 4),
            "wilson_lower_95": round(self.wilson_lower_95, 4),
            "wilson_upper_95": round(self.wilson_upper_95, 4),
            "true_positives": self.true_positives,
            "true_negatives": self.true_negatives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "sensitivity": round(self.sensitivity, 4),
            "specificity": round(self.specificity, 4),
            "alert_threshold": self.alert_threshold,
            "target_confidence": self.target_confidence,
            "meets_target": self.meets_target,
            "cases": [
                {
                    "case_id": row.case_id,
                    "name": row.name,
                    "kind": row.kind,
                    "correct": row.correct,
                    "alerted": row.alerted,
                    "peak_domain_risk": round(row.peak_domain_risk, 4),
                    "peak_composite_risk": round(row.peak_composite_risk, 4),
                    "costly_signals": row.costly_signals,
                }
                for row in self.case_results
            ],
        }


def wilson_interval(
    successes: int,
    total: int,
    z: float = 1.96,
) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (95% default)."""
    if total <= 0:
        return 0.0, 0.0
    phat = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (phat + z2 / (2.0 * total)) / denom
    margin = (
        z
        * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * total)) / total)
        / denom
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _domain_risk(engine: GT_EarlyWarning, region: str, domain: str) -> float:
    if domain in ("financial", "unrest", "conflict"):
        return engine.get_prior(region, domain)
    return engine.composite_risk(region)


def _evaluate_case(
    case: HistoricalCase,
    *,
    settings: GTAnalyticsSettings,
    alert_threshold: float,
) -> CaseResult:
    engine = GT_EarlyWarning(settings)
    peak_domain = float(settings.base_prior)
    peak_composite = float(settings.base_prior)
    detected_signals: set[str] = set()

    for item in case.to_feed_dicts():
        result = engine.process_feed_item(item)
        for sig in (result or {}).get("signals") or {}:
            detected_signals.add(str(sig))
        domain_risk = _domain_risk(engine, case.region, case.domain)
        composite = engine.composite_risk(case.region)
        peak_domain = max(peak_domain, domain_risk)
        peak_composite = max(peak_composite, composite)

    # Domain-specific score for labeled events; composite as secondary for conflict.
    score = peak_domain
    if case.domain == "conflict":
        score = max(peak_domain, peak_composite * 0.95)
    alerted = score >= alert_threshold
    expected_alert = case.kind == "positive"

    return CaseResult(
        case_id=case.case_id,
        name=case.name,
        kind=case.kind,
        region=case.region,
        domain=case.domain,
        expected_alert=expected_alert,
        alerted=alerted,
        correct=alerted == expected_alert,
        peak_domain_risk=peak_domain,
        peak_composite_risk=peak_composite,
        costly_signals=sorted(detected_signals),
        tags=case.tags,
    )


def run_historical_backtest(
    cases: tuple[HistoricalCase, ...] | None = None,
    *,
    settings: GTAnalyticsSettings | None = None,
    alert_threshold: float | None = None,
    target_confidence: float = 0.80,
    use_expanded_suite: bool = True,
) -> BacktestReport:
    """
    Run labeled historical cases and compute accuracy + Wilson 95% CI.

    ``confidence_rate`` is the conservative Wilson lower bound — the metric
    used for pass/fail against ``target_confidence``.
    """
    cfg = settings or GTAnalyticsSettings(enabled=True)
    threshold = float(
        alert_threshold
        if alert_threshold is not None
        else DEFAULT_BACKTEST_ALERT_THRESHOLD
    )
    if cases is not None:
        suite = cases
    elif use_expanded_suite:
        suite = expanded_historical_cases()
    else:
        suite = default_historical_cases()

    results = tuple(
        _evaluate_case(case, settings=cfg, alert_threshold=threshold) for case in suite
    )

    tp = sum(1 for r in results if r.expected_alert and r.alerted)
    tn = sum(1 for r in results if not r.expected_alert and not r.alerted)
    fp = sum(1 for r in results if not r.expected_alert and r.alerted)
    fn = sum(1 for r in results if r.expected_alert and not r.alerted)
    correct = tp + tn
    total = len(results)
    accuracy = correct / total if total else 0.0
    lower, upper = wilson_interval(correct, total)

    pos_total = sum(1 for r in results if r.expected_alert)
    neg_total = total - pos_total
    sensitivity = tp / pos_total if pos_total else 0.0
    specificity = tn / neg_total if neg_total else 0.0

    return BacktestReport(
        total_cases=total,
        correct=correct,
        accuracy=accuracy,
        confidence_rate=lower,
        wilson_lower_95=lower,
        wilson_upper_95=upper,
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
        sensitivity=sensitivity,
        specificity=specificity,
        alert_threshold=threshold,
        target_confidence=target_confidence,
        meets_target=lower >= target_confidence,
        case_results=results,
    )


def tune_alert_threshold(
    cases: tuple[HistoricalCase, ...] | None = None,
    *,
    settings: GTAnalyticsSettings | None = None,
    min_threshold: float = 0.20,
    max_threshold: float = 0.65,
    step: float = 0.01,
    target_confidence: float = 0.95,
) -> tuple[float, BacktestReport]:
    """Grid-search alert threshold to maximize Wilson lower bound."""
    if cases is not None:
        suite = cases
    else:
        suite = expanded_historical_cases()
    best_threshold = min_threshold
    best_report = run_historical_backtest(
        suite,
        settings=settings,
        alert_threshold=min_threshold,
        target_confidence=target_confidence,
    )

    steps = int(round((max_threshold - min_threshold) / step))
    for i in range(steps + 1):
        threshold = min_threshold + i * step
        report = run_historical_backtest(
            suite,
            settings=settings,
            alert_threshold=threshold,
            target_confidence=target_confidence,
        )
        better_confidence = report.confidence_rate > best_report.confidence_rate
        tied_confidence = math.isclose(
            report.confidence_rate, best_report.confidence_rate, rel_tol=0.0, abs_tol=1e-9
        )
        better_accuracy = report.accuracy > best_report.accuracy
        tied_accuracy = math.isclose(
            report.accuracy, best_report.accuracy, rel_tol=0.0, abs_tol=1e-9
        )
        prefer_higher_threshold = (
            tied_confidence and tied_accuracy and threshold > best_threshold
        )
        if better_confidence or (tied_confidence and better_accuracy) or prefer_higher_threshold:
            best_threshold = threshold
            best_report = report

    return best_threshold, best_report