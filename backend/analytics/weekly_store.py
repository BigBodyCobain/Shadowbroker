"""Persistent JSON store for rolling GT operational backtest weeks."""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

LabelName = Literal["pending", "true_escalation", "false_alarm", "benign"]
VALID_LABELS: frozenset[str] = frozenset(
    {"pending", "true_escalation", "false_alarm", "benign"}
)

_STORE_DIR = Path(__file__).parent.parent / "data" / "gt_rolling"
_store_lock = threading.Lock()


def rolling_store_dir() -> Path:
    """Return the rolling-backtest data directory (override via env in tests)."""
    override = str(os.environ.get("GT_ROLLING_STORE_DIR", "")).strip()
    if override:
        return Path(override)
    return _STORE_DIR


@dataclass
class RegionSnapshot:
    region: str
    composite_risk: float
    financial: float
    unrest: float
    conflict: float
    alerted: bool
    label: LabelName = "pending"
    labeled_at: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RegionSnapshot:
        label = str(raw.get("label") or "pending")
        if label not in VALID_LABELS:
            label = "pending"
        return cls(
            region=str(raw.get("region") or "").strip().lower(),
            composite_risk=float(raw.get("composite_risk") or 0.0),
            financial=float(raw.get("financial") or 0.0),
            unrest=float(raw.get("unrest") or 0.0),
            conflict=float(raw.get("conflict") or 0.0),
            alerted=bool(raw.get("alerted")),
            label=label,  # type: ignore[arg-type]
            labeled_at=raw.get("labeled_at"),
            notes=str(raw.get("notes") or ""),
        )


@dataclass
class WeeklySnapshot:
    week_id: str
    frozen_at: str
    alert_threshold: float
    regions: list[RegionSnapshot] = field(default_factory=list)
    frozen_by: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "week_id": self.week_id,
            "frozen_at": self.frozen_at,
            "alert_threshold": self.alert_threshold,
            "frozen_by": self.frozen_by,
            "regions": [row.to_dict() for row in self.regions],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WeeklySnapshot:
        regions = [
            RegionSnapshot.from_dict(row)
            for row in (raw.get("regions") or [])
            if isinstance(row, dict)
        ]
        return cls(
            week_id=str(raw.get("week_id") or ""),
            frozen_at=str(raw.get("frozen_at") or ""),
            alert_threshold=float(raw.get("alert_threshold") or 0.0),
            regions=regions,
            frozen_by=str(raw.get("frozen_by") or "system"),
        )


def _week_path(week_id: str) -> Path:
    safe = week_id.replace("/", "-").replace("..", "")
    return rolling_store_dir() / f"{safe}.json"


def _ensure_dir() -> None:
    rolling_store_dir().mkdir(parents=True, exist_ok=True)


def list_week_ids(*, newest_first: bool = True) -> list[str]:
    """Return stored ISO week ids."""
    _ensure_dir()
    ids = [
        path.stem
        for path in rolling_store_dir().glob("*.json")
        if path.stem and path.stem != "index"
    ]
    ids.sort(reverse=newest_first)
    return ids


def load_week(week_id: str) -> WeeklySnapshot | None:
    path = _week_path(week_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        return WeeklySnapshot.from_dict(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        logger.exception("Failed to load GT rolling week %s", week_id)
        return None


def save_week(snapshot: WeeklySnapshot) -> None:
    _ensure_dir()
    path = _week_path(snapshot.week_id)
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(snapshot.to_dict(), indent=2, sort_keys=True)
    with _store_lock:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)


def delete_week(week_id: str) -> bool:
    path = _week_path(week_id)
    if not path.is_file():
        return False
    with _store_lock:
        path.unlink()
    return True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()