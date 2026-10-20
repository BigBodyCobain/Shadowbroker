"""Disk persistence for road corridor trend runs."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_ROOT, STATE_PATH
from .presets import CORRIDOR_PRESETS, get_preset

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def preset_result_path(preset_id: str) -> Path:
    return DATA_ROOT / f"{preset_id}.json"


def load_preset_result(preset_id: str) -> dict[str, Any] | None:
    path = preset_result_path(preset_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read road corridor result %s: %s", path, exc)
        return None


def save_preset_result(preset_id: str, payload: dict[str, Any]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    path = preset_result_path(preset_id)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_refresh_state() -> dict[str, str]:
    if not STATE_PATH.is_file():
        return {}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in raw.items()}
    except (OSError, json.JSONDecodeError):
        return {}


def save_refresh_state(state: dict[str, str]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def mark_preset_refreshed(preset_id: str) -> None:
    state = load_refresh_state()
    state[preset_id] = _utc_now_iso()
    save_refresh_state(state)


def list_corridor_summaries() -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for preset in CORRIDOR_PRESETS:
        stored = load_preset_result(preset["id"])
        if stored:
            summaries.append(stored)
            continue
        summaries.append(
            {
                "preset_id": preset["id"],
                "label": preset["label"],
                "bbox": preset["bbox"],
                "country": preset["country"],
                "category": preset["category"],
                "status": "never_run",
                "daily_counts": [],
                "total_detections": 0,
            }
        )
    return summaries


def build_trends_payload() -> dict[str, Any]:
    return {
        "updated_at": _utc_now_iso(),
        "corridors": list_corridor_summaries(),
    }


def store_analysis_result(
    preset_id: str,
    *,
    label: str,
    bbox: list[float],
    country: str,
    category: str,
    road_count: int,
    frame_count: int,
    detections: list[dict[str, Any]],
    status: str = "ok",
    error: str | None = None,
) -> dict[str, Any]:
    daily: dict[str, int] = {}
    for det in detections:
        ts = str(det.get("timestamp", ""))[:10]
        if ts:
            daily[ts] = daily.get(ts, 0) + 1
    daily_counts = [{"date": d, "count": daily[d]} for d in sorted(daily.keys())]
    payload = {
        "preset_id": preset_id,
        "label": label,
        "bbox": bbox,
        "country": country,
        "category": category,
        "updated_at": _utc_now_iso(),
        "road_count": road_count,
        "frame_count": frame_count,
        "total_detections": len(detections),
        "daily_counts": daily_counts,
        "status": status,
        "error": error,
    }
    save_preset_result(preset_id, payload)
    mark_preset_refreshed(preset_id)
    return payload


def preset_metadata(preset_id: str) -> dict[str, Any] | None:
    preset = get_preset(preset_id)
    if preset is None:
        return None
    stored = load_preset_result(preset_id)
    if stored:
        return stored
    return {
        "preset_id": preset["id"],
        "label": preset["label"],
        "bbox": preset["bbox"],
        "country": preset["country"],
        "category": preset["category"],
        "status": "never_run",
        "daily_counts": [],
        "total_detections": 0,
    }
