"""Protected export of Shadow-owned analytical signals for QazPipe."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from services.fetchers._store import get_latest_data_subset_refs

router = APIRouter()

UTC = timezone.utc

_EXPORTED_FIELDS = frozenset(
    {
        "layer_family",
        "layer_key",
        "category",
        "status",
        "severity",
        "risk_score",
        "magnitude",
        "altitude_m",
        "speed_mps",
        "heading_deg",
        "callsign",
        "country_code",
        "title",
        "latitude",
        "longitude",
        "geometry",
    }
)
_TIME_FIELDS = ("occurred_at", "observed_at", "updated_at", "timestamp", "detected_at")
_IDENTITY_FIELDS = ("entity_id", "target_id", "cluster_id", "id", "callsign", "name")
_GEOMETRY_TYPES = frozenset(
    {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _clean_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return None


def _clean_geometry(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("type") not in _GEOMETRY_TYPES:
        return None
    coordinates = value.get("coordinates")
    if not isinstance(coordinates, list):
        return None
    return {"type": value["type"], "coordinates": coordinates}


def _signal(
    kind: str, item: dict[str, Any], fallback_time: str, ordinal: int
) -> dict[str, Any]:
    exported = {
        key: _clean_scalar(value) if key != "geometry" else value
        for key, value in item.items()
        if key in _EXPORTED_FIELDS and value is not None
    }
    exported["geometry"] = _clean_geometry(exported.get("geometry"))
    if exported["geometry"] is None:
        exported.pop("geometry", None)
    entity_id = next(
        (str(item[key]) for key in _IDENTITY_FIELDS if item.get(key) not in (None, "")),
        f"{kind}:{ordinal}",
    )
    occurred_at = next(
        (str(item[key]) for key in _TIME_FIELDS if item.get(key) not in (None, "")),
        fallback_time,
    )
    identity_material = json.dumps(
        {"kind": kind, "entity_id": entity_id, "properties": exported},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    signal_id = str(item.get("signal_id") or item.get("id") or "").strip()
    if not signal_id:
        signal_id = f"{kind}-{hashlib.sha256(identity_material).hexdigest()[:24]}"
    return {
        "signal_id": signal_id,
        "signal_type": kind,
        "occurred_at": occurred_at,
        "entity_id": entity_id,
        **exported,
    }


def build_derived_signals() -> list[dict[str, Any]]:
    snapshot = get_latest_data_subset_refs(
        "last_updated", "correlations", "gt_risk", "threat_level"
    )
    fallback_time = str(snapshot.get("last_updated") or _utc_now())
    signals: list[dict[str, Any]] = []

    for index, item in enumerate(snapshot.get("correlations") or []):
        if isinstance(item, dict):
            signals.append(_signal("correlation", item, fallback_time, index))

    gt_risk = snapshot.get("gt_risk")
    if isinstance(gt_risk, dict) and gt_risk.get("enabled"):
        for index, item in enumerate(gt_risk.get("clusters") or []):
            if isinstance(item, dict):
                signals.append(_signal("gt-risk", item, fallback_time, index))

    threat_level = snapshot.get("threat_level")
    if isinstance(threat_level, dict) and threat_level:
        signals.append(_signal("risk-aggregate", threat_level, fallback_time, 0))
    return signals


def _require_derived_token(request: Request) -> None:
    expected = str(os.environ.get("SHADOW_DERIVED_SIGNALS_TOKEN", "") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503, detail="derived signals feed is not configured"
        )
    provided = str(request.headers.get("x-shadow-derived-token", "") or "").strip()
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/api/internal/v1/qazpipe/derived-signals")
async def derived_signals(request: Request) -> dict[str, Any]:
    _require_derived_token(request)
    return {
        "schema_version": "shadow.derived-signals/v1",
        "generated_at": _utc_now(),
        "signals": build_derived_signals(),
    }
