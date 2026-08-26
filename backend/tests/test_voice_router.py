"""Voice REST surface integration suite (voice-agent plan §7.C, items 21+25).

Covers the gating matrix (two-step opt-in), auth (local-operator only),
unconfigured-provider / chat degradation, the persisted daily-budget gate,
the concurrency gate + DELETE kill switch, and the MESH_ONLY lean-mode import
guard. The WS upgrade and wire-contract suites live in
``test_voice_session_api.py``.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys

import pytest
from httpx import ASGITransport, AsyncClient

import services.config as config_mod
import services.api_settings as api_settings_mod

#: The env_check ack-mismatch warning — the 403 detail must quote it exactly.
ACK_MISMATCH_STRING = (
    "VOICE_AGENT_OUTBOUND_ENABLE=allow without VOICE_AGENT_OUTBOUND_ACKNOWLEDGE=true — "
    "the AI voice agent remains disabled until you explicitly acknowledge that enabling it "
    "sends operator speech to the configured realtime provider (OpenAI, an OpenAI-compatible "
    "gateway, or Google Gemini — Google's free tier may use uploaded audio for product "
    "improvement; paid tiers do not) (docs/OUTBOUND_DATA.md)."
)


@pytest.fixture()
def voice_env(tmp_path, monkeypatch):
    """Isolate all VOICE_* configuration: env vars cleared, operator keys file
    redirected to an empty temp path, daily ledger pointed at tmp."""
    from services.voice_broker import _sessions
    from services.voice_session_tokens import reset_voice_session_tokens_for_tests
    from limiter import limiter

    for name in list(os.environ):
        if name.startswith("VOICE_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(api_settings_mod, "OPERATOR_KEYS_ENV_PATH", tmp_path / "operator_keys.env")
    monkeypatch.setenv("SB_DATA_DIR", str(tmp_path / "data"))
    config_mod.get_settings.cache_clear()
    _sessions.clear()
    reset_voice_session_tokens_for_tests()
    yield monkeypatch
    config_mod.get_settings.cache_clear()
    _sessions.clear()
    reset_voice_session_tokens_for_tests()
    try:
        limiter.reset()
    except Exception:
        pass


def _enable(monkeypatch, **extra):
    monkeypatch.setenv("VOICE_AGENT_OUTBOUND_ENABLE", "allow")
    monkeypatch.setenv("VOICE_AGENT_OUTBOUND_ACKNOWLEDGE", "true")
    for key, value in extra.items():
        monkeypatch.setenv(key, value)
    config_mod.get_settings.cache_clear()


@pytest.fixture()
def loopback(voice_env):
    from main import app

    class _Client:
        def __init__(self, peer_ip: str = "127.0.0.1"):
            self._loop = __import__("asyncio").new_event_loop()
            self._transport = ASGITransport(app=app, client=(peer_ip, 12345))
            self._base = f"http://{peer_ip}:8000"

        def _do(self, method: str, url: str, **kw):
            import asyncio

            async def go():
                async with AsyncClient(transport=self._transport, base_url=self._base) as ac:
                    return await ac.request(method, url, **kw)
            return self._loop.run_until_complete(go())

        def get(self, url, **kw):    return self._do("GET", url, **kw)
        def post(self, url, **kw):   return self._do("POST", url, **kw)
        def delete(self, url, **kw): return self._do("DELETE", url, **kw)
        def close(self): self._loop.close()

    c = _Client()
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Item 21 — gating matrix
# ---------------------------------------------------------------------------


class TestGatingMatrix:
    def test_neither_flag_is_403(self, loopback):
        response = loopback.post("/api/voice/session", json={"tier": "standard"})
        assert response.status_code == 403
        body = response.json()
        assert body["error"] == "opt_in_required"
        assert body["reasons"], "refusal must carry human-readable reasons"

    def test_request_without_acknowledge_is_403_with_exact_env_check_string(self, loopback):
        os.environ["VOICE_AGENT_OUTBOUND_ENABLE"] = "allow"
        try:
            config_mod.get_settings.cache_clear()
            response = loopback.post("/api/voice/session", json={"tier": "standard"})
            assert response.status_code == 403
            body = response.json()
            assert ACK_MISMATCH_STRING in body["detail"]
            assert any(ACK_MISMATCH_STRING in r for r in body["reasons"])
        finally:
            os.environ.pop("VOICE_AGENT_OUTBOUND_ENABLE", None)
            config_mod.get_settings.cache_clear()

    def test_both_flags_and_provider_mint_a_session(self, loopback, voice_env):
        _enable(voice_env, VOICE_OPENAI_API_KEY="test-key")
        response = loopback.post("/api/voice/session", json={"tier": "standard"})
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["sessionId"]
        assert body["token"]
        assert body["expiresInSeconds"] == 60
        assert body["wsPath"] == "/api/voice/session/ws"
        assert body["resolvedProvider"] == "openai_realtime"
        assert isinstance(body["limits"], dict)

    def test_remote_caller_without_admin_key_is_403(self, voice_env):
        _enable(voice_env, VOICE_OPENAI_API_KEY="test-key")
        from main import app

        import asyncio

        async def go():
            transport = ASGITransport(app=app, client=("203.0.113.9", 4444))
            async with AsyncClient(transport=transport, base_url="http://203.0.113.9") as ac:
                return await ac.post("/api/voice/session", json={"tier": "standard"})

        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(go())
        finally:
            loop.close()
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Item 25 — unconfigured provider / chat degradation
# ---------------------------------------------------------------------------


class TestUnconfiguredDegradation:
    def test_status_reports_unresolved_provider_with_degraded_reason(self, loopback, voice_env):
        _enable(voice_env)  # opt-in complete, but NO provider keys anywhere
        response = loopback.get("/api/voice/status")
        assert response.status_code == 200
        body = response.json()
        assert body["effectiveEnable"] is True
        assert body["provider"]["resolved"] is None
        assert body["degradedReason"]
        assert body["mode"] == "full"

    def test_session_without_provider_is_503_unconfigured(self, loopback, voice_env):
        _enable(voice_env)
        response = loopback.post("/api/voice/session", json={"tier": "standard"})
        assert response.status_code == 503
        assert response.json()["error"] == "unconfigured"

    def test_chat_without_voice_chat_model_is_503_chat_unconfigured(self, loopback, voice_env):
        _enable(voice_env, VOICE_OPENAI_API_KEY="test-key", VOICE_CHAT_MODEL="")
        response = loopback.post("/api/voice/chat", json={"text": "hello"})
        assert response.status_code == 503
        assert response.json()["error"] == "chat_unconfigured"


# ---------------------------------------------------------------------------
# Daily budget gate (persisted ledger; restart-proof per R18)
# ---------------------------------------------------------------------------


class TestDailyBudgetGate:
    def test_over_budget_session_is_429_with_resets_at(self, loopback, voice_env):
        _enable(voice_env, VOICE_OPENAI_API_KEY="test-key", VOICE_DAILY_BUDGET_USD="0.01")
        from services.voice_daily_budget import record_response

        record_response(usd=0.05)  # persist spend into today's ledger
        response = loopback.post("/api/voice/session", json={"tier": "standard"})
        assert response.status_code == 429
        body = response.json()
        assert body["error"] == "budget"
        assert body["resetsAt"]
        assert int(response.headers["Retry-After"]) > 0


# ---------------------------------------------------------------------------
# Concurrency gate + DELETE kill switch
# ---------------------------------------------------------------------------


class TestConcurrencyAndKillSwitch:
    def test_second_concurrent_session_is_429(self, loopback, voice_env):
        _enable(voice_env, VOICE_OPENAI_API_KEY="test-key")
        first = loopback.post("/api/voice/session", json={"tier": "standard"})
        assert first.status_code == 201
        second = loopback.post("/api/voice/session", json={"tier": "standard"})
        assert second.status_code == 429
        assert second.json()["error"] == "concurrency"

    def test_delete_kills_session_and_frees_slot(self, loopback, voice_env):
        _enable(voice_env, VOICE_OPENAI_API_KEY="test-key")
        first = loopback.post("/api/voice/session", json={})
        session_id = first.json()["sessionId"]

        unknown = loopback.delete(f"/api/voice/session/{session_id}-nope")
        assert unknown.status_code == 404

        killed = loopback.delete(f"/api/voice/session/{session_id}")
        assert killed.status_code == 200
        assert killed.json()["ok"] is True

        again = loopback.post("/api/voice/session", json={})
        assert again.status_code == 201, "DELETE must free the concurrency slot"


# ---------------------------------------------------------------------------
# Status never 500s + §3.3 tool mounts reachable through the router
# ---------------------------------------------------------------------------


class TestStatusRobustness:
    def test_status_ok_on_fresh_install(self, loopback, voice_env):
        response = loopback.get("/api/voice/status")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["opt_in_state"] == "not_requested"
        assert body["dailySpend"]["remainingUsd"] == "off"

    def test_get_voice_tools_mounts_u3_manifest(self, loopback, voice_env):
        _enable(voice_env)
        response = loopback.get("/api/voice/tools")
        assert response.status_code == 200
        tools = response.json()["tools"]
        names = {t["name"] for t in tools}
        assert "get_summary" in names
        assert any(t.get("surface") == "client" for t in tools)


# ---------------------------------------------------------------------------
# §4.1/§4.2 — metering is unconditional across all modes: the typed-text chat
# leg bills its returned usage into the persisted daily ledger.
# ---------------------------------------------------------------------------


class TestChatLegMetering:
    def test_chat_turn_with_usage_grows_daily_ledger(self, loopback, voice_env, monkeypatch):
        import httpx

        _enable(voice_env, VOICE_CHAT_MODEL="test-chat-model")

        class _FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {
                    "choices": [{"message": {"content": "hello operator"}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
                }

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None, headers=None):
                return _FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

        from services.voice_daily_budget import read_daily_spend

        before = read_daily_spend()["usdSpent"]
        response = loopback.post("/api/voice/chat", json={"text": "sitrep?"})
        assert response.status_code == 200, response.text
        assert response.json()["reply"] == "hello operator"

        after = read_daily_spend()["usdSpent"]
        # 1000 prompt × $4 + 500 completion × $24 per 1M (worst-case table for
        # an unrecognized model id) = $0.016 — degraded traffic IS metered and
        # therefore governed by VOICE_DAILY_BUDGET_USD like every other mode.
        assert after > before
        assert abs(after - before - 0.016) < 1e-6


# ---------------------------------------------------------------------------
# §3.3 mount — POST /api/voice/tool executes through validate_and_gate + the
# server command dispatcher verbatim.
# ---------------------------------------------------------------------------


class TestVoiceToolMount:
    def test_unknown_tool_is_400_unknown_tool(self, loopback, voice_env):
        _enable(voice_env)
        response = loopback.post("/api/voice/tool", json={"tool": "definitely_not_a_tool"})
        assert response.status_code == 400
        body = response.json()
        assert body["ok"] is False
        assert body["code"] == "unknown_tool"

    def test_read_tool_dispatches_through_server_dispatcher(self, loopback, voice_env, monkeypatch):
        import services.openclaw_channel as channel_mod

        _enable(voice_env)
        captured: dict = {}

        def fake_dispatch(cmd, args):
            captured["cmd"] = cmd
            captured["args"] = dict(args)
            return {"ok": True, "data": {"echo": cmd}}

        monkeypatch.setattr(channel_mod, "_dispatch_command", fake_dispatch)
        response = loopback.post(
            "/api/voice/tool", json={"tool": "get_summary", "args": {"format": "brief"}}
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"ok": True, "data": {"echo": "get_summary"}}
        assert captured["cmd"] == "get_summary"
        assert "confirm_expensive" not in captured["args"]

    def test_destructive_gate_blocks_then_confirmed_call_dispatches_clean(
        self, loopback, voice_env, monkeypatch
    ):
        import services.openclaw_channel as channel_mod

        _enable(voice_env, OPENCLAW_ACCESS_TIER="full")
        captured: dict = {}

        def fake_dispatch(cmd, args):
            captured["args"] = dict(args)
            return {"ok": True}

        monkeypatch.setattr(channel_mod, "_dispatch_command", fake_dispatch)

        blocked = loopback.post("/api/voice/tool", json={"tool": "delete_pin", "args": {}})
        assert blocked.status_code == 400
        body = blocked.json()
        assert body["ok"] is False and body["code"] == "destructive_confirm_required"
        assert "args" not in captured, "blocked calls must never reach the dispatcher"

        confirmed = loopback.post(
            "/api/voice/tool",
            json={"tool": "delete_pin", "args": {"id": "pin-1"}, "confirm": True},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert captured["args"].get("id") == "pin-1"
        assert "confirm" not in captured["args"], (
            "gate control keys must be consumed, never forwarded as tool args"
        )


# ---------------------------------------------------------------------------
# MESH_ONLY lean-mode guard (defense-in-depth, §1.5)
# ---------------------------------------------------------------------------


class TestMeshOnlyGuard:
    def test_mesh_only_refuses_route_registration(self, caplog):
        saved = sys.modules.pop("routers.voice", None)
        os.environ["MESH_ONLY"] = "1"
        try:
            with caplog.at_level(logging.WARNING):
                mod = importlib.import_module("routers.voice")
            assert len(mod.router.routes) == 0, (
                "MESH_ONLY lean nodes must expose no voice routes"
            )
            assert any("refus" in record.getMessage().lower() for record in caplog.records)
        finally:
            os.environ.pop("MESH_ONLY", None)
            sys.modules.pop("routers.voice", None)
            if saved is not None:
                importlib.import_module("routers.voice")
