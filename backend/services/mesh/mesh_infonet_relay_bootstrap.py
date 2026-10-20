"""Auto-enable Tor wormhole transport on Infonet relay/seed nodes."""

from __future__ import annotations

import logging
from typing import Any

from services.config import get_settings
from services.wormhole_settings import read_wormhole_settings, write_wormhole_settings

logger = logging.getLogger(__name__)


def infonet_relay_auto_wormhole_requested() -> bool:
    settings = get_settings()
    if bool(settings.MESH_INFONET_RELAY_AUTO_WORMHOLE_DISABLED):
        return False
    if bool(settings.MESH_INFONET_RELAY_AUTO_WORMHOLE):
        return True
    if str(settings.MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY or "").strip():
        return True
    return False


def _relay_tor_wormhole_target_settings() -> dict[str, Any]:
    settings = get_settings()
    socks_port = int(settings.MESH_ARTI_SOCKS_PORT or 9050)
    return {
        "enabled": True,
        "transport": "tor_arti",
        "socks_proxy": f"socks5h://127.0.0.1:{socks_port}",
        "socks_dns": True,
        "anonymous_mode": True,
    }


def _wormhole_settings_match(existing: dict[str, Any], target: dict[str, Any]) -> bool:
    return (
        bool(existing.get("enabled")) is bool(target["enabled"])
        and str(existing.get("transport", "")) == str(target["transport"])
        and str(existing.get("socks_proxy", "")) == str(target["socks_proxy"])
        and bool(existing.get("socks_dns", True)) is bool(target["socks_dns"])
        and bool(existing.get("anonymous_mode", False)) is bool(target["anonymous_mode"])
    )


def ensure_infonet_relay_wormhole_ready(*, reason: str = "relay_auto") -> dict[str, Any]:
    """Persist Tor wormhole settings and connect on relay/seed startup."""
    if not infonet_relay_auto_wormhole_requested():
        return {"ok": True, "skipped": True, "reason": "not_requested"}

    from routers.ai_intel import _write_env_value
    from services.tor_hidden_service import tor_service
    from services.wormhole_supervisor import connect_wormhole, restart_wormhole

    existing = read_wormhole_settings()
    target = _relay_tor_wormhole_target_settings()
    settings_updated = not _wormhole_settings_match(existing, target)
    updated = write_wormhole_settings(**target) if settings_updated else existing

    tor_result: dict[str, Any] = {"ok": False, "detail": "not started"}
    try:
        tor_result = tor_service.start(target_port=8000)
        if tor_result.get("ok"):
            _write_env_value("MESH_ARTI_ENABLED", "true")
            get_settings.cache_clear()
    except Exception as exc:
        tor_result = {"ok": False, "detail": str(exc or type(exc).__name__)}

    runtime = (
        restart_wormhole(reason=reason)
        if settings_updated
        else connect_wormhole(reason=reason)
    )

    if settings_updated:
        logger.info("Infonet relay auto-wormhole enabled (%s)", reason)

    return {
        "ok": True,
        "skipped": False,
        "settings_updated": settings_updated,
        "tor": tor_result,
        "runtime": runtime,
        "settings": updated,
    }
