from __future__ import annotations

import json
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
STATUS_FILE = DATA_DIR / "wormhole_status.json"

_DEFAULTS = {
    "last_restart": 0,
    "last_start": 0,
    "reason": "",
    "transport": "",
    "proxy": "",
    "transport_active": "",
    "proxy_active": "",
    "installed": False,
    "configured": False,
    "running": False,
    "ready": False,
    "pid": 0,
    "started_at": 0,
    "last_error": "",
    "privacy_level_effective": "default",
}


def _safe_int(val, default=0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def read_wormhole_status() -> dict:
    if not STATUS_FILE.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return dict(_DEFAULTS)
    return {
        "last_restart": _safe_int(data.get("last_restart", 0) or 0),
        "last_start": _safe_int(data.get("last_start", 0) or 0),
        "reason": str(data.get("reason", "") or ""),
        "transport": str(data.get("transport", "") or ""),
        "proxy": str(data.get("proxy", "") or ""),
        "transport_active": str(data.get("transport_active", "") or ""),
        "proxy_active": str(data.get("proxy_active", "") or ""),
        "installed": bool(data.get("installed", False)),
        "configured": bool(data.get("configured", False)),
        "running": bool(data.get("running", False)),
        "ready": bool(data.get("ready", False)),
        "pid": _safe_int(data.get("pid", 0) or 0),
        "started_at": _safe_int(data.get("started_at", 0) or 0),
        "last_error": str(data.get("last_error", "") or ""),
        "privacy_level_effective": str(data.get("privacy_level_effective", "default") or "default"),
    }


def write_wormhole_status(
    *,
    reason: str | None = None,
    transport: str | None = None,
    proxy: str | None = None,
    restart: bool = False,
    transport_active: str | None = None,
    proxy_active: str | None = None,
    installed: bool | None = None,
    configured: bool | None = None,
    running: bool | None = None,
    ready: bool | None = None,
    pid: int | None = None,
    started_at: int | None = None,
    last_error: str | None = None,
    privacy_level_effective: str | None = None,
) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = read_wormhole_status()
    now = int(time.time())
    payload = {
        "last_start": now if not restart and reason else existing.get("last_start", now),
        "last_restart": now if restart else existing.get("last_restart", 0),
        "reason": existing.get("reason", "") if reason is None else reason,
        "transport": existing.get("transport", "") if transport is None else transport,
        "proxy": existing.get("proxy", "") if proxy is None else proxy,
        "transport_active": existing.get("transport_active", "") if transport_active is None else transport_active,
        "proxy_active": existing.get("proxy_active", "") if proxy_active is None else proxy_active,
        "installed": existing.get("installed", False) if installed is None else bool(installed),
        "configured": existing.get("configured", False) if configured is None else bool(configured),
        "running": existing.get("running", False) if running is None else bool(running),
        "ready": existing.get("ready", False) if ready is None else bool(ready),
        "pid": existing.get("pid", 0) if pid is None else int(pid or 0),
        "started_at": existing.get("started_at", 0) if started_at is None else int(started_at or 0),
        "last_error": existing.get("last_error", "") if last_error is None else str(last_error),
        "privacy_level_effective": (
            existing.get("privacy_level_effective", "default")
            if privacy_level_effective is None
            else str(privacy_level_effective)
        ),
    }
    STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
