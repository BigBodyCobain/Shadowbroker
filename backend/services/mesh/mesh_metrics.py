"""Lightweight metrics for mesh protocol health signals."""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_metrics: dict[str, int] = {}
_timers: dict[str, dict[str, float]] = {}
_last_updated: float = 0.0


def increment(name: str, count: int = 1) -> None:
    global _last_updated
    with _lock:
        _metrics[name] = _metrics.get(name, 0) + count
        _last_updated = time.time()


def observe_ms(name: str, duration_ms: float) -> None:
    global _last_updated
    sample = max(0.0, float(duration_ms or 0.0))
    with _lock:
        bucket = dict(_timers.get(name) or {})
        bucket["count"] = float(bucket.get("count", 0.0)) + 1.0
        bucket["total_ms"] = float(bucket.get("total_ms", 0.0)) + sample
        bucket["max_ms"] = max(float(bucket.get("max_ms", 0.0)), sample)
        bucket["last_ms"] = sample
        bucket["avg_ms"] = bucket["total_ms"] / max(bucket["count"], 1.0)
        _timers[name] = bucket
        _last_updated = time.time()


def reset() -> None:
    global _last_updated
    with _lock:
        _metrics.clear()
        _timers.clear()
        _last_updated = 0.0


def snapshot() -> dict:
    with _lock:
        return {
            "updated_at": _last_updated,
            "counters": dict(_metrics),
            "timers": {name: dict(bucket) for name, bucket in _timers.items()},
        }
