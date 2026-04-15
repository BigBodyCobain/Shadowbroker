from __future__ import annotations

import json
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
WORMHOLE_FILE = DATA_DIR / "wormhole.json"
_cache: dict | None = None
_cache_ts: float = 0.0
_CACHE_TTL = 5.0  # seconds
_DEFAULTS = {
    "enabled": False,
    "transport": "direct",
    "socks_proxy": "",
    "socks_dns": True,
    "privacy_profile": "default",
    "anonymous_mode": False,
}


def _safe_int(val, default=0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def read_wormhole_settings() -> dict:
    global _cache, _cache_ts
    now = time.monotonic()
    if _cache is not None and (now - _cache_ts) < _CACHE_TTL:
        return _cache
    if not WORMHOLE_FILE.exists():
        result = {**_DEFAULTS, "updated_at": 0}
    else:
        try:
            data = json.loads(WORMHOLE_FILE.read_text(encoding="utf-8"))
        except Exception:
            result = {**_DEFAULTS, "updated_at": 0}
        else:
            result = {
                "enabled": bool(data.get("enabled", _DEFAULTS["enabled"])),
                "transport": str(data.get("transport", _DEFAULTS["transport"]) or _DEFAULTS["transport"]),
                "socks_proxy": str(data.get("socks_proxy", _DEFAULTS["socks_proxy"]) or ""),
                "socks_dns": bool(data.get("socks_dns", _DEFAULTS["socks_dns"])),
                "privacy_profile": str(
                    data.get("privacy_profile", _DEFAULTS["privacy_profile"]) or _DEFAULTS["privacy_profile"]
                ),
                "anonymous_mode": bool(data.get("anonymous_mode", _DEFAULTS["anonymous_mode"])),
                "updated_at": _safe_int(data.get("updated_at", 0) or 0),
            }
    _cache = result
    _cache_ts = now
    return result


def write_wormhole_settings(
    *,
    enabled: bool | None = None,
    transport: str | None = None,
    socks_proxy: str | None = None,
    socks_dns: bool | None = None,
    privacy_profile: str | None = None,
    anonymous_mode: bool | None = None,
) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = read_wormhole_settings()
    payload = {
        "enabled": bool(existing.get("enabled")) if enabled is None else bool(enabled),
        "transport": existing.get("transport", _DEFAULTS["transport"])
        if transport is None
        else str(transport),
        "socks_proxy": existing.get("socks_proxy", "")
        if socks_proxy is None
        else str(socks_proxy),
        "socks_dns": bool(existing.get("socks_dns", _DEFAULTS["socks_dns"]))
        if socks_dns is None
        else bool(socks_dns),
        "privacy_profile": existing.get("privacy_profile", _DEFAULTS["privacy_profile"])
        if privacy_profile is None
        else str(privacy_profile),
        "anonymous_mode": bool(existing.get("anonymous_mode", _DEFAULTS["anonymous_mode"]))
        if anonymous_mode is None
        else bool(anonymous_mode),
        "updated_at": int(time.time()),
    }
    WORMHOLE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    global _cache, _cache_ts
    _cache = payload
    _cache_ts = time.monotonic()
    return payload
