"""Lightweight metrics for mesh protocol health signals."""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_metrics: dict[str, int] = {}
_last_updated: float = 0.0


def increment(name: str, count: int = 1) -> None:
    global _last_updated
    with _lock:
        _metrics[name] = _metrics.get(name, 0) + count
        _last_updated = time.time()


def snapshot() -> dict:
    with _lock:
        return {
            "updated_at": _last_updated,
            "counters": dict(_metrics),
        }
