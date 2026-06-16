"""Top strategic-risk alerts — ranked regions with map coordinates."""

from __future__ import annotations

from typing import Any

from analytics.integration import get_gt_engine
from analytics.settings import get_gt_settings


def _peak_score(props: dict[str, Any]) -> float:
    composite = float(props.get("risk") or 0.0)
    financial = float(props.get("financial") or 0.0)
    unrest = float(props.get("unrest") or 0.0)
    conflict = float(props.get("conflict") or 0.0)
    return max(composite, financial, unrest, conflict)


def _valid_coords(coords: Any) -> tuple[float, float] | None:
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    try:
        lng = float(coords[0])
        lat = float(coords[1])
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return None
    if abs(lat) < 0.001 and abs(lng) < 0.001:
        return None
    return lat, lng


def _region_label(region: str) -> str:
    text = str(region or "").strip()
    if not text:
        return "unknown"
    if "," in text:
        parts = [piece.strip() for piece in text.split(",") if piece.strip()]
        if len(parts) >= 2:
            try:
                lat = float(parts[0])
                lng = float(parts[-1])
                return f"{lat:.2f}°, {lng:.2f}°"
            except ValueError:
                pass
    return text.replace("_", " ")


def parse_heatmap_alerts(
    heatmap: dict[str, Any] | None,
    *,
    limit: int = 8,
) -> tuple[list[dict[str, Any]], int]:
    """Return ranked alerts and count of regions plottable on the map."""
    features = (heatmap or {}).get("features") or []
    rows: list[dict[str, Any]] = []

    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") or {}
        coords = _valid_coords(geometry.get("coordinates"))
        if coords is None:
            continue
        lat, lng = coords
        props = feature.get("properties") or {}
        region = str(props.get("region") or "").strip().lower()
        if not region:
            continue
        score = _peak_score(props)
        rows.append(
            {
                "region": region,
                "region_label": _region_label(region),
                "risk": round(float(props.get("risk") or 0.0), 4),
                "financial": round(float(props.get("financial") or 0.0), 4),
                "unrest": round(float(props.get("unrest") or 0.0), 4),
                "conflict": round(float(props.get("conflict") or 0.0), 4),
                "contagion": round(float(props.get("contagion") or 0.0), 4),
                "score": round(score, 4),
                "lat": lat,
                "lng": lng,
                "ignition": bool(props.get("micro_ignition")),
                "risk_3d_avg": props.get("risk_3d_avg"),
                "risk_delta": props.get("risk_delta"),
                "updates": int(props.get("updates") or 0),
            }
        )

    rows.sort(
        key=lambda row: (
            bool(row.get("ignition")),
            float(row.get("risk_delta") or 0.0),
            float(row.get("score") or 0.0),
        ),
        reverse=True,
    )
    return rows[: max(1, limit)], len(rows)


def top_gt_alerts(*, limit: int = 8) -> dict[str, Any]:
    """Ranked top regions for API / OpenClaw."""
    settings = get_gt_settings()
    engine = get_gt_engine()
    heatmap: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    engine_regions = 0

    if engine is not None:
        heatmap = engine.get_risk_heatmap()
        with engine._lock:  # noqa: SLF001 — intentional meta read
            engine_regions = len(engine._regions)

    alerts, plotted = parse_heatmap_alerts(heatmap, limit=limit)
    tracked = len(heatmap.get("features") or [])

    return {
        "alerts": alerts,
        "tracked_regions": tracked,
        "engine_regions": engine_regions,
        "plotted_regions": plotted,
        "max_regions": settings.max_heatmap_features,
        "note": (
            "Layer count is tracked GT regions (cap "
            f"{settings.max_heatmap_features}), not raw feed events. "
            "Only regions with valid coordinates appear on the map."
        ),
    }