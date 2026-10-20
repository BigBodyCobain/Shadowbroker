"""Strategic Risk Analytics API — game-theoretic early warning overlays."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import require_local_operator
from limiter import limiter
from analytics.backtest import (
    DEFAULT_BACKTEST_ALERT_THRESHOLD,
    run_historical_backtest,
    tune_alert_threshold,
)
from analytics.feed_adapter import normalize_feed_item
from analytics.integration import get_gt_engine, refresh_from_latest_data
from analytics.gt_alerts import top_gt_alerts
from analytics.micro_rolling import micro_rolling_report
from analytics.rolling_backtest import (
    freeze_weekly_snapshot,
    label_region,
    label_regions,
    rolling_alert_threshold,
    rolling_report,
    score_week,
)
from analytics.weekly_store import load_week
from analytics.settings import gt_analytics_enabled
from services.fetchers._store import _data_lock, get_latest_data_subset_refs, latest_data

logger = logging.getLogger(__name__)

router = APIRouter()


class RiskHeatmapRequest(BaseModel):
    """Optional batch ingest + refresh controls for POST /api/analytics/risk_heatmap."""

    refresh: bool = True
    items: list[dict[str, Any]] = Field(default_factory=list)


class RollingFreezeRequest(BaseModel):
    week_id: str | None = None
    force: bool = False


class RollingLabelEntry(BaseModel):
    region: str
    label: str
    notes: str = ""


class RollingLabelRequest(BaseModel):
    week_id: str
    labels: list[RollingLabelEntry] = Field(default_factory=list)


def _empty_heatmap() -> dict[str, Any]:
    return {
        "enabled": False,
        "type": "FeatureCollection",
        "features": [],
        "clusters": [],
        "processed": 0,
        "timestamp": None,
    }


def _gt_risk_payload() -> dict[str, Any]:
    snap = get_latest_data_subset_refs("gt_risk")
    payload = snap.get("gt_risk")
    if not isinstance(payload, dict):
        return _empty_heatmap()
    heatmap = payload.get("heatmap") or {"type": "FeatureCollection", "features": []}
    return {
        "enabled": bool(payload.get("enabled")),
        "type": heatmap.get("type", "FeatureCollection"),
        "features": list(heatmap.get("features") or []),
        "clusters": list(payload.get("clusters") or []),
        "processed": int(payload.get("processed") or 0),
        "timestamp": payload.get("timestamp"),
    }


@router.get("/api/analytics/risk_heatmap")
@limiter.limit("60/minute")
async def risk_heatmap_get(request: Request) -> dict[str, Any]:
    """Return cached GeoJSON risk overlay (posterior scores per region)."""
    if not gt_analytics_enabled():
        return _empty_heatmap()
    return _gt_risk_payload()


@router.post("/api/analytics/risk_heatmap")
@limiter.limit("12/minute")
async def risk_heatmap_post(
    request: Request,
    body: RiskHeatmapRequest,
    _: None = Depends(require_local_operator),
) -> dict[str, Any]:
    """
    Ingest optional feed items and/or refresh beliefs from latest intel layers.

    Requires local operator auth — intended for OpenClaw agents and admin tooling.
    """
    if not gt_analytics_enabled():
        raise HTTPException(status_code=503, detail="Strategic Risk Analytics is disabled")

    engine = get_gt_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Strategic Risk Analytics engine unavailable")

    ingested = 0
    for raw in body.items:
        if not isinstance(raw, dict):
            continue
        source_type = str(raw.get("source_type") or "manual")
        item = normalize_feed_item(raw, source_type=source_type)
        result = engine.process_feed_item(item)
        if result and not result.get("skipped"):
            ingested += 1

    summary: dict[str, Any] = {"ingested": ingested}
    if body.refresh:
        with _data_lock:
            snapshot = dict(latest_data)
        summary.update(refresh_from_latest_data(snapshot, persist=True))

    payload = _gt_risk_payload()
    payload["ingested"] = ingested
    payload["refresh"] = bool(body.refresh)
    return payload


@router.get("/api/analytics/dossier/{region}")
@limiter.limit("30/minute")
async def analytics_dossier(request: Request, region: str) -> dict[str, Any]:
    """Game-theoretic rationale, recent costly signals, and scenario sketches."""
    region_key = str(region or "").strip().lower()
    if not region_key or len(region_key) > 120:
        raise HTTPException(status_code=400, detail="Invalid region identifier")

    if not gt_analytics_enabled():
        return {
            "enabled": False,
            "region": region_key,
            "current_risk": 0.0,
            "interpretation": "Strategic Risk Analytics is disabled.",
            "recent_signals": [],
            "scenarios": [],
        }

    engine = get_gt_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Strategic Risk Analytics engine unavailable")

    dossier = engine.get_dossier(region_key)
    dossier["enabled"] = True
    return dossier


@router.get("/api/analytics/backtest")
@limiter.limit("6/minute")
async def analytics_backtest(
    request: Request,
    expanded: bool = True,
    tune: bool = False,
    target_confidence: float = 0.95,
) -> dict[str, Any]:
    """
    Run labeled historical backtest and return accuracy + Wilson 95% CI.

    ``confidence_rate`` is the Wilson lower bound (conservative pass metric).
    """
    if not gt_analytics_enabled():
        return {
            "enabled": False,
            "message": "Strategic Risk Analytics is disabled.",
        }

    if tune:
        threshold, report = tune_alert_threshold(target_confidence=target_confidence)
    else:
        threshold = DEFAULT_BACKTEST_ALERT_THRESHOLD
        report = run_historical_backtest(
            use_expanded_suite=expanded,
            alert_threshold=threshold,
            target_confidence=target_confidence,
        )

    payload = report.to_dict()
    payload["enabled"] = True
    payload["expanded_suite"] = expanded
    payload["tuned"] = tune
    payload["recommended_alert_threshold"] = threshold
    return payload


@router.get("/api/analytics/rolling")
@limiter.limit("12/minute")
async def analytics_rolling(
    request: Request,
    weeks: int = 8,
    target_confidence: float = 0.80,
) -> dict[str, Any]:
    """Rolling weekly operational validation — accuracy trend with delayed labels."""
    if not gt_analytics_enabled():
        return {
            "enabled": False,
            "message": "Strategic Risk Analytics is disabled.",
        }

    report = rolling_report(weeks=max(1, min(weeks, 52)), target_confidence=target_confidence)
    report["enabled"] = True
    return report


@router.get("/api/analytics/alerts")
@limiter.limit("30/minute")
async def analytics_top_alerts(
    request: Request,
    limit: int = 8,
) -> dict[str, Any]:
    """Top GT risk regions ranked by score — fly-to targets for the map."""
    if not gt_analytics_enabled():
        return {
            "enabled": False,
            "message": "Strategic Risk Analytics is disabled.",
        }

    report = top_gt_alerts(limit=max(1, min(limit, 25)))
    report["enabled"] = True
    return report


@router.get("/api/analytics/rolling/micro")
@limiter.limit("30/minute")
async def analytics_rolling_micro(
    request: Request,
    window_days: int = 3,
    limit: int = 15,
) -> dict[str, Any]:
    """Rolling 3-day micro average — spot vs baseline, ignition detection."""
    if not gt_analytics_enabled():
        return {
            "enabled": False,
            "message": "Strategic Risk Analytics is disabled.",
        }

    report = micro_rolling_report(
        window_days=max(2, min(window_days, 7)),
        limit=max(1, min(limit, 50)),
    )
    report["enabled"] = True
    return report


@router.get("/api/analytics/rolling/{week_id}")
@limiter.limit("12/minute")
async def analytics_rolling_week(request: Request, week_id: str) -> dict[str, Any]:
    """Return a single frozen week snapshot and its score."""
    if not gt_analytics_enabled():
        return {"enabled": False, "message": "Strategic Risk Analytics is disabled."}

    snapshot = load_week(str(week_id).strip())
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Week {week_id} not found")

    score = score_week(snapshot)
    return {
        "enabled": True,
        "week_id": snapshot.week_id,
        "snapshot": snapshot.to_dict(),
        "score": score.to_dict(),
        "alert_threshold": rolling_alert_threshold(),
    }


@router.post("/api/analytics/rolling/freeze")
@limiter.limit("6/minute")
async def analytics_rolling_freeze(
    request: Request,
    body: RollingFreezeRequest,
    _: None = Depends(require_local_operator),
) -> dict[str, Any]:
    """Freeze current GT scores for the ISO week (idempotent unless force=true)."""
    if not gt_analytics_enabled():
        raise HTTPException(status_code=503, detail="Strategic Risk Analytics is disabled")

    result = freeze_weekly_snapshot(
        week_id=body.week_id,
        force=body.force,
        frozen_by="api",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("detail", "Freeze failed"))
    result["enabled"] = True
    return result


@router.post("/api/analytics/rolling/label")
@limiter.limit("12/minute")
async def analytics_rolling_label(
    request: Request,
    body: RollingLabelRequest,
    _: None = Depends(require_local_operator),
) -> dict[str, Any]:
    """Apply delayed outcome labels to a frozen week."""
    if not gt_analytics_enabled():
        raise HTTPException(status_code=503, detail="Strategic Risk Analytics is disabled")

    week_id = str(body.week_id or "").strip()
    if not week_id:
        raise HTTPException(status_code=400, detail="week_id required")

    if len(body.labels) == 1:
        entry = body.labels[0]
        result = label_region(
            week_id,
            entry.region,
            entry.label,  # type: ignore[arg-type]
            notes=entry.notes,
            labeled_by="api",
        )
    else:
        result = label_regions(
            week_id,
            [row.model_dump() for row in body.labels],
            labeled_by="api",
        )

    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("detail", "Label failed"))
    result["enabled"] = True
    return result