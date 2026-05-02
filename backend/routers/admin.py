import json as json_mod
import logging
import os
import threading
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Request, Depends, Response
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin, require_local_operator
from node_state import (
    _current_node_mode,
    _participant_node_enabled,
    _refresh_node_peer_store,
    _set_participant_node_enabled,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class NodeSettingsUpdate(BaseModel):
    enabled: bool


class TimeMachineToggle(BaseModel):
    enabled: bool


@router.get("/api/settings/api-keys", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_get_keys(request: Request):
    from services.api_settings import get_api_keys
    return get_api_keys()


@router.get("/api/settings/api-keys/meta")
@limiter.limit("30/minute")
async def api_get_keys_meta(request: Request):
    """Return absolute paths for the backend .env and .env.example template.

    Not gated behind admin auth: the paths are not sensitive, and the frontend
    needs them to render the API Keys panel banner before the user has had a
    chance to enter an admin key. Helps users find the file when in-app editing
    is blocked or when the backend is read-only.
    """
    from services.api_settings import get_env_path_info
    return get_env_path_info()


@router.get("/api/settings/news-feeds")
@limiter.limit("30/minute")
async def api_get_news_feeds(request: Request):
    from services.news_feed_config import get_feeds
    return get_feeds()


@router.put("/api/settings/news-feeds", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_save_news_feeds(request: Request):
    from services.news_feed_config import save_feeds
    body = await request.json()
    ok = save_feeds(body)
    if ok:
        return {"status": "updated", "count": len(body)}
    return Response(
        content=json_mod.dumps({"status": "error",
            "message": "Validation failed (max 20 feeds, each needs name/url/weight 1-5)"}),
        status_code=400,
        media_type="application/json",
    )


@router.post("/api/settings/news-feeds/reset", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_reset_news_feeds(request: Request):
    from services.news_feed_config import get_feeds, reset_feeds
    ok = reset_feeds()
    if ok:
        return {"status": "reset", "feeds": get_feeds()}
    return {"status": "error", "message": "Failed to reset feeds"}


@router.get("/api/settings/node")
@limiter.limit("30/minute")
async def api_get_node_settings(request: Request):
    import asyncio
    from services.node_settings import read_node_settings
    data = await asyncio.to_thread(read_node_settings)
    return {
        **data,
        "node_mode": _current_node_mode(),
        "node_enabled": _participant_node_enabled(),
    }


@router.put("/api/settings/node", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_set_node_settings(request: Request, body: NodeSettingsUpdate):
    _refresh_node_peer_store()
    return _set_participant_node_enabled(bool(body.enabled))


@router.get("/api/settings/timemachine")
@limiter.limit("30/minute")
async def api_get_timemachine_settings(request: Request):
    import asyncio
    from services.node_settings import read_node_settings
    data = await asyncio.to_thread(read_node_settings)
    return {
        "enabled": data.get("timemachine_enabled", False),
        "storage_warning": "Time Machine auto-snapshots use ~68 MB/day compressed (~2 GB/month). "
                           "Snapshots capture entity positions (flights, ships, satellites) for historical playback.",
    }


@router.put("/api/settings/timemachine", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_set_timemachine_settings(request: Request, body: TimeMachineToggle):
    import asyncio
    from services.node_settings import write_node_settings
    result = await asyncio.to_thread(write_node_settings, timemachine_enabled=body.enabled)
    return {
        "ok": True,
        "enabled": result.get("timemachine_enabled", False),
    }


@router.post("/api/system/update", dependencies=[Depends(require_admin)])
@limiter.limit("1/minute")
async def system_update(request: Request):
    """Download latest release, backup current files, extract update, and restart."""
    from services.updater import perform_update, schedule_restart
    candidate = Path(__file__).resolve().parent.parent.parent
    if (candidate / "frontend").is_dir() or (candidate / "backend").is_dir():
        project_root = str(candidate)
    else:
        project_root = os.getcwd()
    result = perform_update(project_root)
    if result.get("status") == "error":
        return Response(content=json_mod.dumps(result), status_code=500, media_type="application/json")
    if result.get("status") == "docker":
        return result
    threading.Timer(2.0, schedule_restart, args=[project_root]).start()
    return result


# ── Tor Hidden Service ──────────────────────────────────────────────


@router.get("/api/settings/tor", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_tor_status(request: Request):
    """Return Tor hidden service status and .onion address if available."""
    import asyncio
    from services.tor_hidden_service import tor_service

    return await asyncio.to_thread(tor_service.status)


@router.post("/api/settings/tor/start", dependencies=[Depends(require_local_operator)])
@limiter.limit("5/minute")
async def api_tor_start(request: Request):
    """Start Tor and provision a hidden service for this ShadowBroker instance.

    Also enables MESH_ARTI so the mesh/wormhole system can route traffic
    through the Tor SOCKS proxy (port 9050) automatically.
    """
    import asyncio
    from services.tor_hidden_service import tor_service

    result = await asyncio.to_thread(tor_service.start)

    # If Tor started successfully, enable Arti (Tor SOCKS proxy for mesh)
    if result.get("ok"):
        try:
            from routers.ai_intel import _write_env_value
            from services.config import get_settings
            _write_env_value("MESH_ARTI_ENABLED", "true")
            get_settings.cache_clear()
        except Exception:
            pass  # Non-fatal — hidden service still works without mesh Arti

    return result


@router.post("/api/settings/tor/reset-identity", dependencies=[Depends(require_local_operator)])
@limiter.limit("2/minute")
async def api_tor_reset_identity(request: Request):
    """Destroy current .onion identity and generate a fresh one on next start.

    This is irreversible — the old .onion address is permanently lost.
    """
    import asyncio, shutil
    from services.tor_hidden_service import tor_service, TOR_DIR

    # Stop Tor if running
    await asyncio.to_thread(tor_service.stop)

    # Delete the hidden service directory (contains the private key)
    hs_dir = TOR_DIR / "hidden_service"
    if hs_dir.exists():
        shutil.rmtree(str(hs_dir), ignore_errors=True)

    # Clear cached address
    tor_service._onion_address = ""

    return {"ok": True, "detail": "Tor identity destroyed. A new .onion will be generated on next start."}


@router.post("/api/settings/agent/reset-all", dependencies=[Depends(require_local_operator)])
@limiter.limit("2/minute")
async def api_reset_all_agent_credentials(request: Request):
    """Nuclear reset: regenerate HMAC key, destroy .onion, revoke agent identity.

    After this, the agent is fully disconnected and needs new credentials.
    """
    import asyncio, secrets, shutil
    from services.tor_hidden_service import tor_service, TOR_DIR
    from services.config import get_settings

    results = {}

    # 1. Regenerate HMAC key
    new_secret = secrets.token_hex(24)
    from routers.ai_intel import _write_env_value
    _write_env_value("OPENCLAW_HMAC_SECRET", new_secret)
    results["hmac"] = "regenerated"

    # 2. Revoke agent identity (Ed25519 keypair)
    try:
        from services.openclaw_bridge import revoke_agent_identity
        revoke_agent_identity()
        results["identity"] = "revoked"
    except Exception as e:
        results["identity"] = f"error: {e}"

    # 3. Destroy .onion and restart Tor with new identity
    await asyncio.to_thread(tor_service.stop)
    hs_dir = TOR_DIR / "hidden_service"
    if hs_dir.exists():
        shutil.rmtree(str(hs_dir), ignore_errors=True)
    tor_service._onion_address = ""
    results["tor"] = "identity destroyed"

    # 4. Bootstrap fresh identity + start Tor with new .onion
    try:
        from services.openclaw_bridge import generate_agent_keypair
        keypair = generate_agent_keypair(force=True)
        results["new_node_id"] = keypair.get("node_id", "")
    except Exception as e:
        results["new_node_id"] = f"error: {e}"

    tor_result = await asyncio.to_thread(tor_service.start)
    results["new_onion"] = tor_result.get("onion_address", "")
    results["tor_ok"] = tor_result.get("ok", False)

    # Clear settings cache
    get_settings.cache_clear()

    return {
        "ok": True,
        "new_hmac_secret": new_secret,
        "detail": "All agent credentials have been reset. Reconfigure your agent with the new credentials.",
        **results,
    }


@router.post("/api/settings/tor/stop", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_tor_stop(request: Request):
    """Stop the Tor hidden service."""
    import asyncio
    from services.tor_hidden_service import tor_service

    return await asyncio.to_thread(tor_service.stop)
