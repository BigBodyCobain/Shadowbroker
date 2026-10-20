"""Rolling weekly operational validation for Strategic Risk Analytics.

Freezes live GT scores each ISO week, accepts delayed outcome labels, and
scores prior-week predictions with accuracy + Wilson 95% CI. Unlike the
static historical benchmark, this measures forward operational usefulness.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal

from analytics.backtest import DEFAULT_BACKTEST_ALERT_THRESHOLD, wilson_interval
from analytics.gt_early_warning import GT_EarlyWarning
from analytics.integration import get_gt_engine
from analytics.weekly_store import (
    VALID_LABELS,
    LabelName,
    RegionSnapshot,
    WeeklySnapshot,
    list_week_ids,
    load_week,
    save_week,
    utc_now_iso,
)

MIN_LABELED_FOR_TREND = 5


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def rolling_alert_threshold() -> float:
    """Fixed operational alert cutoff — not retroactively tuned per week."""
    return _env_float("GT_ROLLING_ALERT_THRESHOLD", DEFAULT_BACKTEST_ALERT_THRESHOLD)


def iso_week_id(when: datetime | date | None = None) -> str:
    """Return ISO week id, e.g. ``2026-W24``."""
    if when is None:
        when = datetime.now(timezone.utc)
    if isinstance(when, datetime):
        when = when.date()
    year, week, _ = when.isocalendar()
    return f"{year}-W{week:02d}"


def _region_rows_from_engine(
    engine: GT_EarlyWarning,
    *,
    alert_threshold: float,
) -> list[RegionSnapshot]:
    heatmap = engine.get_risk_heatmap()
    rows: list[RegionSnapshot] = []
    for feature in heatmap.get("features") or []:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        region = str(props.get("region") or "").strip().lower()
        if not region:
            continue
        composite = float(props.get("risk") or 0.0)
        financial = float(props.get("financial") or 0.0)
        unrest = float(props.get("unrest") or 0.0)
        conflict = float(props.get("conflict") or 0.0)
        peak_score = max(composite, financial, unrest, conflict)
        rows.append(
            RegionSnapshot(
                region=region,
                composite_risk=composite,
                financial=financial,
                unrest=unrest,
                conflict=conflict,
                alerted=peak_score >= alert_threshold,
                label="pending",
            )
        )
    rows.sort(key=lambda row: row.composite_risk, reverse=True)
    return rows


@dataclass(frozen=True)
class WeekScore:
    week_id: str
    frozen_at: str
    alert_threshold: float
    total_regions: int
    labeled: int
    pending: int
    alerted: int
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
    scorable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "week_id": self.week_id,
            "frozen_at": self.frozen_at,
            "alert_threshold": round(self.alert_threshold, 4),
            "total_regions": self.total_regions,
            "labeled": self.labeled,
            "pending": self.pending,
            "alerted": self.alerted,
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
            "scorable": self.scorable,
        }


def _predicted_positive(row: RegionSnapshot) -> bool:
    return row.alerted


def _actual_positive(label: LabelName) -> bool:
    return label == "true_escalation"


def _is_correct(row: RegionSnapshot) -> bool:
    if row.label == "pending":
        return False
    predicted = _predicted_positive(row)
    if row.label == "true_escalation":
        return predicted
    if row.label in ("false_alarm", "benign"):
        return not predicted
    return False


def score_week(snapshot: WeeklySnapshot) -> WeekScore:
    """Score a frozen week against delayed labels (pending rows excluded)."""
    labeled_rows = [row for row in snapshot.regions if row.label != "pending"]
    pending = len(snapshot.regions) - len(labeled_rows)

    tp = sum(
        1
        for row in labeled_rows
        if row.alerted and row.label == "true_escalation"
    )
    tn = sum(
        1
        for row in labeled_rows
        if not row.alerted and row.label in ("benign", "false_alarm")
    )
    fp = sum(
        1
        for row in labeled_rows
        if row.alerted and row.label in ("false_alarm", "benign")
    )
    fn = sum(
        1
        for row in labeled_rows
        if not row.alerted and row.label == "true_escalation"
    )

    correct = tp + tn
    total = len(labeled_rows)
    accuracy = correct / total if total else 0.0
    lower, upper = wilson_interval(correct, total)

    pos_total = sum(1 for row in labeled_rows if _actual_positive(row.label))  # type: ignore[arg-type]
    neg_total = total - pos_total
    pred_pos = sum(1 for row in labeled_rows if row.alerted)
    pred_neg = total - pred_pos

    sensitivity = tp / pos_total if pos_total else 0.0
    specificity = tn / pred_neg if pred_neg else (1.0 if tn == total and total else 0.0)

    return WeekScore(
        week_id=snapshot.week_id,
        frozen_at=snapshot.frozen_at,
        alert_threshold=snapshot.alert_threshold,
        total_regions=len(snapshot.regions),
        labeled=total,
        pending=pending,
        alerted=sum(1 for row in snapshot.regions if row.alerted),
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
        scorable=total >= MIN_LABELED_FOR_TREND,
    )


def freeze_weekly_snapshot(
    *,
    week_id: str | None = None,
    alert_threshold: float | None = None,
    force: bool = False,
    frozen_by: str = "system",
    engine: GT_EarlyWarning | None = None,
) -> dict[str, Any]:
    """
    Capture current GT heatmap as an immutable weekly operational snapshot.

    Idempotent per week unless ``force=True``.
    """
    resolved_engine = engine or get_gt_engine()
    if resolved_engine is None:
        return {"ok": False, "detail": "GT analytics engine unavailable"}

    resolved_week = week_id or iso_week_id()
    threshold = float(
        alert_threshold if alert_threshold is not None else rolling_alert_threshold()
    )

    existing = load_week(resolved_week)
    if existing and existing.regions and not force:
        score = score_week(existing)
        return {
            "ok": True,
            "created": False,
            "week_id": resolved_week,
            "snapshot": existing.to_dict(),
            "score": score.to_dict(),
        }

    regions = _region_rows_from_engine(resolved_engine, alert_threshold=threshold)
    snapshot = WeeklySnapshot(
        week_id=resolved_week,
        frozen_at=utc_now_iso(),
        alert_threshold=threshold,
        regions=regions,
        frozen_by=frozen_by,
    )
    save_week(snapshot)
    score = score_week(snapshot)
    return {
        "ok": True,
        "created": True,
        "week_id": resolved_week,
        "snapshot": snapshot.to_dict(),
        "score": score.to_dict(),
        "alert_count": sum(1 for row in regions if row.alerted),
        "region_count": len(regions),
    }


def label_regions(
    week_id: str,
    labels: list[dict[str, Any]],
    *,
    labeled_by: str = "operator",
) -> dict[str, Any]:
    """Apply delayed outcome labels to a frozen week."""
    snapshot = load_week(week_id)
    if snapshot is None:
        return {"ok": False, "detail": f"Week {week_id} not found"}

    by_region = {row.region: row for row in snapshot.regions}
    updated = 0
    skipped: list[str] = []
    now = utc_now_iso()

    for entry in labels:
        if not isinstance(entry, dict):
            continue
        region = str(entry.get("region") or "").strip().lower()
        label = str(entry.get("label") or "").strip().lower()
        if not region or label not in VALID_LABELS or label == "pending":
            if region:
                skipped.append(region)
            continue
        row = by_region.get(region)
        if row is None:
            skipped.append(region)
            continue
        row.label = label  # type: ignore[assignment]
        row.labeled_at = now
        notes = entry.get("notes")
        if notes is not None:
            row.notes = str(notes)
        updated += 1

    save_week(snapshot)
    score = score_week(snapshot)
    return {
        "ok": True,
        "week_id": week_id,
        "updated": updated,
        "skipped": skipped,
        "labeled_by": labeled_by,
        "score": score.to_dict(),
    }


def label_region(
    week_id: str,
    region: str,
    label: LabelName,
    *,
    notes: str = "",
    labeled_by: str = "operator",
) -> dict[str, Any]:
    return label_regions(
        week_id,
        [{"region": region, "label": label, "notes": notes}],
        labeled_by=labeled_by,
    )


def rolling_trend(*, weeks: int = 8) -> list[WeekScore]:
    """Return scored weeks newest-first (only weeks with stored snapshots)."""
    ids = list_week_ids(newest_first=True)[: max(1, weeks)]
    scores: list[WeekScore] = []
    for week_id in ids:
        snapshot = load_week(week_id)
        if snapshot is None:
            continue
        scores.append(score_week(snapshot))
    return scores


def rolling_report(*, weeks: int = 8, target_confidence: float = 0.80) -> dict[str, Any]:
    """Aggregate operational validation trend for API / OpenClaw."""
    threshold = rolling_alert_threshold()
    trend = rolling_trend(weeks=weeks)
    scorable = [row for row in trend if row.scorable]

    latest = scorable[0] if scorable else (trend[0] if trend else None)
    accuracy_series = [
        {"week_id": row.week_id, "accuracy": round(row.accuracy, 4), "labeled": row.labeled}
        for row in reversed(scorable)
    ]

    improving = False
    if len(scorable) >= 2:
        improving = scorable[0].accuracy >= scorable[1].accuracy

    return {
        "mode": "rolling_operational",
        "alert_threshold": threshold,
        "target_confidence": target_confidence,
        "weeks_requested": weeks,
        "weeks_stored": len(trend),
        "weeks_scorable": len(scorable),
        "min_labeled_per_week": MIN_LABELED_FOR_TREND,
        "latest": latest.to_dict() if latest else None,
        "trend": [row.to_dict() for row in trend],
        "accuracy_series": accuracy_series,
        "improving_vs_prior": improving,
        "meets_target": bool(
            latest and latest.scorable and latest.confidence_rate >= target_confidence
        ),
        "note": (
            "Operational metric: scores frozen weekly predictions against delayed "
            "labels. Unlike the static benchmark, this measures live forward utility."
        ),
    }