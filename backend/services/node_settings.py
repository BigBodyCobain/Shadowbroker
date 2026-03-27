from __future__ import annotations

import json
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
NODE_FILE = DATA_DIR / "node.json"
_cache: dict | None = None
_cache_ts: float = 0.0
_CACHE_TTL = 5.0
_DEFAULTS = {
    "enabled": False,
}


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read_node_settings() -> dict:
    global _cache, _cache_ts
    now = time.monotonic()
    if _cache is not None and (now - _cache_ts) < _CACHE_TTL:
        return _cache
    if not NODE_FILE.exists():
        result = {**_DEFAULTS, "updated_at": 0}
    else:
        try:
            data = json.loads(NODE_FILE.read_text(encoding="utf-8"))
        except Exception:
            result = {**_DEFAULTS, "updated_at": 0}
        else:
            result = {
                "enabled": bool(data.get("enabled", _DEFAULTS["enabled"])),
                "updated_at": _safe_int(data.get("updated_at", 0) or 0),
            }
    _cache = result
    _cache_ts = now
    return result


def write_node_settings(*, enabled: bool | None = None) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = read_node_settings()
    payload = {
        "enabled": bool(existing.get("enabled", _DEFAULTS["enabled"])) if enabled is None else bool(enabled),
        "updated_at": int(time.time()),
    }
    NODE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    global _cache, _cache_ts
    _cache = payload
    _cache_ts = time.monotonic()
    return payload
