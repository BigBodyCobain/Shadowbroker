"""Daily GT risk readings for micro rolling averages."""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DAILY_DIR = Path(__file__).parent.parent / "data" / "gt_rolling" / "daily"
_store_lock = threading.Lock()


def daily_store_dir() -> Path:
    override = str(os.environ.get("GT_DAILY_STORE_DIR", "")).strip()
    if override:
        return Path(override)
    return _DAILY_DIR


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def date_id(when: date | datetime | None = None) -> str:
    if when is None:
        when = utc_today()
    if isinstance(when, datetime):
        when = when.date()
    return when.isoformat()


@dataclass
class DailyRegionReading:
    region: str
    composite_risk: float
    financial: float
    unrest: float
    conflict: float
    peak_score: float
    readings: int = 1
    last_captured_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DailyRegionReading:
        return cls(
            region=str(raw.get("region") or "").strip().lower(),
            composite_risk=float(raw.get("composite_risk") or 0.0),
            financial=float(raw.get("financial") or 0.0),
            unrest=float(raw.get("unrest") or 0.0),
            conflict=float(raw.get("conflict") or 0.0),
            peak_score=float(raw.get("peak_score") or 0.0),
            readings=int(raw.get("readings") or 1),
            last_captured_at=str(raw.get("last_captured_at") or ""),
        )


@dataclass
class DailySnapshot:
    date: str
    regions: dict[str, DailyRegionReading] = field(default_factory=dict)
    last_updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "last_updated_at": self.last_updated_at,
            "regions": {key: row.to_dict() for key, row in self.regions.items()},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DailySnapshot:
        regions: dict[str, DailyRegionReading] = {}
        for key, row in (raw.get("regions") or {}).items():
            if isinstance(row, dict):
                reading = DailyRegionReading.from_dict(row)
                regions[str(key).strip().lower()] = reading
        return cls(
            date=str(raw.get("date") or ""),
            regions=regions,
            last_updated_at=str(raw.get("last_updated_at") or ""),
        )


def _daily_path(day_id: str) -> Path:
    safe = day_id.replace("/", "-").replace("..", "")
    return daily_store_dir() / f"{safe}.json"


def _ensure_dir() -> None:
    daily_store_dir().mkdir(parents=True, exist_ok=True)


def list_daily_ids(*, newest_first: bool = True, limit: int | None = None) -> list[str]:
    _ensure_dir()
    ids = sorted(
        (path.stem for path in daily_store_dir().glob("*.json")),
        reverse=newest_first,
    )
    if limit is not None:
        return ids[:limit]
    return ids


def load_daily(day: date | str | None = None) -> DailySnapshot | None:
    day_id = date_id(day) if day is not None else date_id()
    path = _daily_path(day_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        return DailySnapshot.from_dict(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        logger.exception("Failed to load GT daily reading %s", day_id)
        return None


def save_daily(snapshot: DailySnapshot) -> None:
    _ensure_dir()
    path = _daily_path(snapshot.date)
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(snapshot.to_dict(), indent=2, sort_keys=True)
    with _store_lock:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()