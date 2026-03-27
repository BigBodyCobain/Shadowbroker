"""Fetch health registry — tracks per-source success/failure counts and timings."""

import logging
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from services.fetchers._store import _data_lock, source_freshness

logger = logging.getLogger(__name__)

_health: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _update_source_freshness(source: str, *, ok: bool, error_msg: Optional[str] = None):
    """Mirror health summary into shared store for visibility."""
    with _data_lock:
        entry = source_freshness.get(source, {})
        if ok:
            entry["last_ok"] = _now_iso()
        else:
            entry["last_error"] = _now_iso()
            if error_msg:
                entry["last_error_msg"] = error_msg[:200]
        source_freshness[source] = entry


def record_success(source: str, duration_s: Optional[float] = None, count: Optional[int] = None):
    """Record a successful fetch for a source."""
    now = _now_iso()
    with _lock:
        entry = _health.setdefault(
            source,
            {
                "ok_count": 0,
                "error_count": 0,
                "last_ok": None,
                "last_error": None,
                "last_error_msg": None,
                "last_duration_ms": None,
                "avg_duration_ms": None,
                "last_count": None,
            },
        )
        entry["ok_count"] += 1
        entry["last_ok"] = now
        if duration_s is not None:
            dur_ms = round(duration_s * 1000, 1)
            entry["last_duration_ms"] = dur_ms
            prev_avg = entry["avg_duration_ms"] or 0.0
            n = entry["ok_count"]
            entry["avg_duration_ms"] = round(((prev_avg * (n - 1)) + dur_ms) / n, 1)
        if count is not None:
            entry["last_count"] = count

    _update_source_freshness(source, ok=True)


def record_failure(source: str, error: Exception, duration_s: Optional[float] = None):
    """Record a failed fetch for a source."""
    now = _now_iso()
    err_msg = str(error)
    with _lock:
        entry = _health.setdefault(
            source,
            {
                "ok_count": 0,
                "error_count": 0,
                "last_ok": None,
                "last_error": None,
                "last_error_msg": None,
                "last_duration_ms": None,
                "avg_duration_ms": None,
                "last_count": None,
            },
        )
        entry["error_count"] += 1
        entry["last_error"] = now
        entry["last_error_msg"] = err_msg[:200]
        if duration_s is not None:
            entry["last_duration_ms"] = round(duration_s * 1000, 1)

    _update_source_freshness(source, ok=False, error_msg=err_msg)


def get_health_snapshot() -> Dict[str, Dict[str, Any]]:
    """Return a snapshot of current fetch health state."""
    with _lock:
        return {k: dict(v) for k, v in _health.items()}
