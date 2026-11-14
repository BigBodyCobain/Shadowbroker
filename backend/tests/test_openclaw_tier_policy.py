from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request

import auth
from services import openclaw_channel, openclaw_routing


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tier,method,path,permitted",
    [
        ("restricted", "GET", "/api/ai/status", True),
        ("restricted", "POST", "/api/ai/channel/poll", True),
        ("restricted", "POST", "/api/ai/channel/batch", True),
        ("restricted", "POST", "/api/ai/pins", False),
        ("unknown", "DELETE", "/api/ai/pins", False),
        ("full", "POST", "/api/ai/pins", True),
    ],
)
async def test_verified_agent_route_tier(monkeypatch, tier, method, path, permitted):
    monkeypatch.setattr(auth, "operator_origin_allowed", lambda request: True)
    monkeypatch.setattr(auth, "_is_debug_test_request", lambda request: False)
    monkeypatch.setattr(auth, "_current_admin_key", lambda: "")
    monkeypatch.setattr(auth, "_verify_openclaw_hmac", AsyncMock(return_value=True))
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(OPENCLAW_ACCESS_TIER=tier))
    request = Request({"type": "http", "method": method, "path": path, "headers": []})
    if permitted:
        await auth.require_openclaw_or_local(request)
    else:
        with pytest.raises(HTTPException) as exc:
            await auth.require_openclaw_or_local(request)
        assert exc.value.status_code == 403


def test_restricted_playbook_checks_inner_permissions(monkeypatch):
    monkeypatch.setattr(openclaw_routing, "plan_playbook", lambda *_: {
        "ok": True, "batch": [{"cmd": "gt_analyze"}],
    })
    channel = openclaw_channel.CommandChannel()
    for result in (
        channel.submit_command("run_playbook", {}, "restricted"),
        channel.submit_batch([{"cmd": "run_playbook"}], "restricted")["results"][0],
    ):
        assert result["result"]["data"]["results"][0]["ok"] is False
    assert {"gt_analyze", "gt_rolling_freeze", "gt_rolling_label"}.isdisjoint(
        openclaw_channel.allowed_commands("restricted")
    )
