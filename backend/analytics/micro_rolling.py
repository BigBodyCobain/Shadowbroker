"""Micro rolling 3-day average — fast ignition signal alongside weekly macro."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from analytics.daily_store import (
    DailyRegionReading,
    DailySnapshot,
    date_id,
    list_daily_ids,
    load_daily,
    save_daily,
    utc_now_iso,
    utc_today,
)
from analytics.gt_early_warning import GT_EarlyWarning
from analytics.rolling_backtest import rolling_alert_threshold

DEFAULT_WINDOW_DAYS = 3
DEFAULT_IGNITION_DELTA = 0.10


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def micro_window_days() -> int:
    return _env_int("GT_MICRO_ROLLING_DAYS", DEFAULT_WINDOW_DAYS)


def ignition_delta() -> float:
    return _env_float("GT_MICRO_IGNITION_DELTA", DEFAULT_IGNITION_DELTA)


def _peak_score(
    *,
    composite: float,
    financial: float,
    unrest: float,
    conflict: float,
) -> float:
    return max(composite, financial, unrest, conflict)


def _region_reading_from_feature(
    feature: dict[str, Any],
    *,
    captured_at: str,
) -> DailyRegionReading | None:
    props = feature.get("properties") or {}
    region = str(props.get("region") or "").strip().lower()
    if not region:
        return None
    composite = float(props.get("risk") or props.get("composite_risk") or 0.0)
    financial = float(props.get("financial") or 0.0)
    unrest = float(props.get("unrest") or 0.0)
    conflict = float(props.get("conflict") or 0.0)
    peak = _peak_score(
        composite=composite,
        financial=financial,
        unrest=unrest,
        conflict=conflict,
    )
    return DailyRegionReading(
        region=region,
        composite_risk=composite,
        financial=financial,
        unrest=unrest,
        conflict=conflict,
        peak_score=peak,
        readings=1,
        last_captured_at=captured_at,
    )


def capture_daily_readings(
    engine: GT_EarlyWarning,
    *,
    when: date | None = None,
) -> dict[str, Any]:
    """
    Upsert today's regional readings from the live heatmap.

    Each GT refresh updates the current day's latest scores (rolling window
    uses one value per calendar day).
    """
    day = when or utc_today()
    day_key = date_id(day)
    captured_at = utc_now_iso()
    heatmap = engine.get_risk_heatmap()
    existing = load_daily(day) or DailySnapshot(date=day_key, regions={})

    updated = 0
    for feature in heatmap.get("features") or []:
        if not isinstance(feature, dict):
            continue
        reading = _region_reading_from_feature(feature, captured_at=captured_at)
        if reading is None:
            continue
        prior = existing.regions.get(reading.region)
        if prior is None:
            existing.regions[reading.region] = reading
            updated += 1
            continue
        prior.composite_risk = reading.composite_risk
        prior.financial = reading.financial
        prior.unrest = reading.unrest
        prior.conflict = reading.conflict
        prior.peak_score = max(prior.peak_score, reading.peak_score)
        prior.readings += 1
        prior.last_captured_at = captured_at
        updated += 1

    existing.last_updated_at = captured_at
    save_daily(existing)
    return {
        "date": day_key,
        "regions": len(existing.regions),
        "updated": updated,
        "captured_at": captured_at,
    }


@dataclass(frozen=True)
class MicroRegionView:
    region: str
    spot_risk: float
    risk_3d_avg: float
    risk_delta: float
    days_in_window: int
    day_scores: tuple[float, ...]
    alerted_spot: bool
    alerted_3d: bool
    ignition: bool
    financial: float
    unrest: float
    conflict: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "spot_risk": round(self.spot_risk, 4),
            "risk_3d_avg": round(self.risk_3d_avg, 4),
            "risk_delta": round(self.risk_delta, 4),
            "days_in_window": self.days_in_window,
            "day_scores": [round(score, 4) for score in self.day_scores],
            "alerted_spot": self.alerted_spot,
            "alerted_3d": self.alerted_3d,
            "ignition": self.ignition,
            "financial": round(self.financial, 4),
            "unrest": round(self.unrest, 4),
            "conflict": round(self.conflict, 4),
        }


def _day_offsets(window_days: int) -> list[int]:
    # Today + prior (window_days - 1) days.
    return list(range(window_days - 1, -1, -1))


def _historical_dates(as_of: date, window_days: int) -> list[date]:
    return [as_of - timedelta(days=offset) for offset in _day_offsets(window_days)]


def compute_micro_view(
    region: str,
    *,
    as_of: date | None = None,
    window_days: int | None = None,
    alert_threshold: float | None = None,
    spot_reading: DailyRegionReading | None = None,
) -> MicroRegionView | None:
    """Compute rolling N-day average and ignition vs spot for one region."""
    region_key = str(region or "").strip().lower()
    if not region_key:
        return None

    today = as_of or utc_today()
    window = window_days or micro_window_days()
    threshold = float(alert_threshold if alert_threshold is not None else rolling_alert_threshold())
    delta_min = ignition_delta()

    day_scores: list[float] = []
    latest: DailyRegionReading | None = spot_reading

    for day in _historical_dates(today, window):
        snap = load_daily(day)
        if snap is None:
            continue
        row = snap.regions.get(region_key)
        if row is None:
            continue
        day_scores.append(row.peak_score)
        if day == today:
            latest = row

    if latest is None and day_scores:
        # Spot may come from yesterday if today not captured yet.
        snap = load_daily(today)
        if snap:
            latest = snap.regions.get(region_key)

    if latest is None and not day_scores:
        return None

    spot = float(latest.peak_score if latest else (day_scores[-1] if day_scores else 0.0))
    avg = sum(day_scores) / len(day_scores) if day_scores else spot
    risk_delta = spot - avg
    ignition = risk_delta >= delta_min and spot >= threshold * 0.75

    return MicroRegionView(
        region=region_key,
        spot_risk=spot,
        risk_3d_avg=avg,
        risk_delta=risk_delta,
        days_in_window=len(day_scores),
        day_scores=tuple(day_scores),
        alerted_spot=spot >= threshold,
        alerted_3d=avg >= threshold,
        ignition=ignition,
        financial=float(latest.financial if latest else 0.0),
        unrest=float(latest.unrest if latest else 0.0),
        conflict=float(latest.conflict if latest else 0.0),
    )


def compute_all_micro_views(
    *,
    as_of: date | None = None,
    window_days: int | None = None,
    alert_threshold: float | None = None,
) -> list[MicroRegionView]:
    """Build micro views for all regions seen in the rolling window."""
    today = as_of or utc_today()
    window = window_days or micro_window_days()
    regions: set[str] = set()

    for day in _historical_dates(today, window):
        snap = load_daily(day)
        if snap is None:
            continue
        regions.update(snap.regions.keys())

    views: list[MicroRegionView] = []
    for region in regions:
        view = compute_micro_view(
            region,
            as_of=today,
            window_days=window,
            alert_threshold=alert_threshold,
        )
        if view is not None:
            views.append(view)

    views.sort(key=lambda row: (row.ignition, row.risk_delta, row.spot_risk), reverse=True)
    return views


def enrich_heatmap_features(
    heatmap: dict[str, Any],
    *,
    as_of: date | None = None,
    window_days: int | None = None,
    alert_threshold: float | None = None,
) -> dict[str, Any]:
    """Attach micro rolling fields to heatmap GeoJSON features."""
    threshold = float(alert_threshold if alert_threshold is not None else rolling_alert_threshold())
    window = window_days or micro_window_days()
    features = heatmap.get("features") or []
    enriched: list[dict[str, Any]] = []

    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = dict(feature.get("properties") or {})
        region = str(props.get("region") or "").strip().lower()
        view = compute_micro_view(
            region,
            as_of=as_of,
            window_days=window,
            alert_threshold=threshold,
        ) if region else None

        if view is not None:
            props["risk_spot"] = view.spot_risk
            props["risk_3d_avg"] = view.risk_3d_avg
            props["risk_delta"] = view.risk_delta
            props["micro_days"] = view.days_in_window
            props["micro_ignition"] = view.ignition
            props["alerted_3d"] = view.alerted_3d
            props["day_scores"] = list(view.day_scores)

        enriched.append({**feature, "properties": props})

    return {
        **heatmap,
        "features": enriched,
        "micro_window_days": window,
        "micro_alert_threshold": threshold,
    }


def micro_rolling_report(
    *,
    as_of: date | None = None,
    window_days: int | None = None,
    limit: int = 15,
) -> dict[str, Any]:
    """API/OpenClaw payload for micro rolling 3-day context."""
    today = as_of or utc_today()
    window = window_days or micro_window_days()
    threshold = rolling_alert_threshold()
    views = compute_all_micro_views(
        as_of=today,
        window_days=window,
        alert_threshold=threshold,
    )
    ignitions = [row for row in views if row.ignition]
    alerted_3d = [row for row in views if row.alerted_3d]
    top = views[: max(1, limit)]

    stored_days = list_daily_ids(newest_first=True, limit=window)
    return {
        "mode": "micro_rolling",
        "window_days": window,
        "alert_threshold": threshold,
        "ignition_delta": ignition_delta(),
        "as_of": date_id(today),
        "days_stored": len(stored_days),
        "stored_dates": stored_days,
        "regions_tracked": len(views),
        "ignition_count": len(ignitions),
        "alerted_3d_count": len(alerted_3d),
        "ignitions": [row.to_dict() for row in ignitions[:limit]],
        "top_regions": [row.to_dict() for row in top],
        "note": (
            f"Micro view: {window}-day rolling average vs spot risk. "
            "Ignition = spot jumped above the rolling baseline (events that flare fast). "
            "Macro week-over-week validation remains on /api/analytics/rolling."
        ),
    }