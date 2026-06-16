"""Singleton GT engine and feed-batch integration hooks."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from analytics.feed_adapter import iter_gdelt_features, iter_news_items, iter_telegram_posts
from analytics.gt_early_warning import GT_EarlyWarning
from analytics.settings import gt_analytics_enabled, get_gt_settings, gt_engine_operational, gt_louvain_enabled, gt_scheduled_ingest_enabled
from services.fetchers._store import _data_lock, _mark_fresh, latest_data

logger = logging.getLogger(__name__)

_engine: GT_EarlyWarning | None = None
_engine_lock = threading.Lock()


def get_gt_engine() -> GT_EarlyWarning | None:
    """Return the shared engine when analytics are enabled and runtime allows it."""
    global _engine
    if not gt_engine_operational():
        return None
    with _engine_lock:
        if _engine is None:
            _engine = GT_EarlyWarning(get_gt_settings())
            logger.info("Strategic Risk Analytics engine initialized")
        return _engine


def reset_gt_engine() -> None:
    """Reset singleton — intended for tests."""
    global _engine
    get_gt_settings.cache_clear()
    with _engine_lock:
        _engine = None


def process_feed_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Process a normalized feed item if analytics are enabled."""
    engine = get_gt_engine()
    if engine is None:
        return None
    try:
        return engine.process_feed_item(item)
    except Exception:
        logger.exception("GT process_feed_item failed")
        return None


def _persist_gt_snapshot(
    engine: GT_EarlyWarning,
    *,
    processed: int,
    sample: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    heatmap = engine.get_risk_heatmap()
    micro_summary: dict[str, Any] = {}
    try:
        from analytics.micro_rolling import capture_daily_readings, enrich_heatmap_features

        micro_summary = capture_daily_readings(engine)
        heatmap = enrich_heatmap_features(heatmap)
    except Exception:
        logger.exception("GT micro rolling capture failed")

    clusters = engine.compute_herding_clusters()
    from analytics.gt_alerts import parse_heatmap_alerts

    _, plotted_regions = parse_heatmap_alerts(heatmap)
    with engine._lock:  # noqa: SLF001 — snapshot meta
        engine_regions = len(engine._regions)
    settings = get_gt_settings()
    payload = {
        "enabled": True,
        "timestamp": timestamp,
        "processed": processed,
        "heatmap": heatmap,
        "clusters": clusters,
        "sample": list(sample or [])[:5],
        "regions": len(heatmap.get("features") or []),
        "micro": micro_summary,
        "meta": {
            "tracked_regions": len(heatmap.get("features") or []),
            "engine_regions": engine_regions,
            "plotted_regions": plotted_regions,
            "max_regions": settings.max_heatmap_features,
        },
    }
    with _data_lock:
        latest_data["gt_risk"] = payload
    _mark_fresh("gt_risk")
    return payload


def refresh_from_latest_data(
    data_snapshot: dict[str, Any],
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Batch-ingest recent intel layers from the shared data store.

    Intended to run after telegram/news/gdelt fetch cycles (near-real-time).
    """
    engine = get_gt_engine()
    if engine is None:
        return {"enabled": False, "processed": 0}

    processed = 0
    results: list[dict[str, Any]] = []

    for item in iter_telegram_posts(data_snapshot.get("telegram_osint")):
        result = engine.process_feed_item(item)
        if result and not result.get("skipped"):
            processed += 1
            results.append(result)

    for item in iter_news_items(data_snapshot.get("news")):
        result = engine.process_feed_item(item)
        if result and not result.get("skipped"):
            processed += 1
            if len(results) < 5:
                results.append(result)

    for item in iter_gdelt_features(data_snapshot.get("gdelt")):
        result = engine.process_feed_item(item)
        if result and not result.get("skipped"):
            processed += 1

    logger.info("GT refresh processed %d items", processed)
    summary = {
        "enabled": True,
        "processed": processed,
        "sample": results[:5],
        "heatmap_features": len(engine.get_risk_heatmap().get("features") or []),
    }
    if persist:
        snapshot = _persist_gt_snapshot(engine, processed=processed, sample=results)
        summary["timestamp"] = snapshot.get("timestamp")
        summary["clusters"] = len(snapshot.get("clusters") or [])
    return summary


def recompute_gt_herding_clusters() -> dict[str, Any]:
    """Louvain community pass — run on a schedule independent of feed ingest."""
    if not gt_louvain_enabled():
        return {"enabled": False, "clusters": 0, "reason": "louvain_disabled_on_lean_profile"}

    engine = get_gt_engine()
    if engine is None:
        return {"enabled": False, "clusters": 0}

    clusters = engine.compute_herding_clusters()
    timestamp = datetime.now(timezone.utc).isoformat()
    with _data_lock:
        current = dict(latest_data.get("gt_risk") or {})
        current["clusters"] = clusters
        current["clusters_updated"] = timestamp
        current["enabled"] = True
        latest_data["gt_risk"] = current
    _mark_fresh("gt_risk")
    logger.info("GT Louvain recompute: %d clusters", len(clusters))
    return {"enabled": True, "clusters": len(clusters), "timestamp": timestamp}


def maybe_refresh_gt_analytics() -> None:
    """Hook for data_fetcher — no-op when analytics are disabled or lean-gated."""
    if not gt_scheduled_ingest_enabled():
        return
    try:
        with _data_lock:
            snapshot = dict(latest_data)
        refresh_from_latest_data(snapshot, persist=True)
    except Exception:
        logger.exception("GT analytics refresh failed")


def maybe_freeze_gt_weekly_snapshot() -> None:
    """Hook for weekly scheduler — freeze operational backtest snapshot."""
    if not gt_engine_operational():
        return
    try:
        from analytics.rolling_backtest import freeze_weekly_snapshot

        result = freeze_weekly_snapshot(frozen_by="scheduler")
        if result.get("created"):
            logger.info(
                "GT rolling freeze: week=%s regions=%s alerts=%s",
                result.get("week_id"),
                result.get("region_count"),
                result.get("alert_count"),
            )
    except Exception:
        logger.exception("GT rolling weekly freeze failed")