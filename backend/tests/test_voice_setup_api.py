"""Voice setup API tests — first-class enablement (POST /api/voice/opt-in and
POST /api/voice/provider).

Covers: opt-in round-trip flipping status.effectiveEnable, provider save
resolving through resolve_provider, unknown-provider 400, the env-var-wins
honesty note, the MESH_ONLY lean-mode guard, and no key leakage in any
response body. Uses the same isolation pattern as test_voice_router.voice_env.
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


@pytest.fixture()
def voice_env(tmp_path, monkeypatch):
    """Isolate all VOICE_* configuration: env vars cleared, operator keys file
    redirected to an empty temp path.

    The setup endpoints intentionally mutate os.environ (env-var-wins sync);
    those writes happen AFTER fixture setup, so monkeypatch cannot restore
    them — teardown pops every remaining VOICE_* var explicitly.
    """
    from services.voice_broker import _sessions
    from services.voice_session_tokens import reset_voice_session_tokens_for_tests
    from limiter import limiter

    for name in [n for n in list(os.environ) if n.startswith("VOICE_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(api_settings_mod, "OPERATOR_KEYS_ENV_PATH", tmp_path / "operator_keys.env")
    monkeypatch.setenv("SB_DATA_DIR", str(tmp_path / "data"))
    config_mod.get_settings.cache_clear()
    _sessions.clear()
    reset_voice_session_tokens_for_tests()
    yield monkeypatch
    for name in [n for n in list(os.environ) if n.startswith("VOICE_")]:
        os.environ.pop(name, None)
    config_mod.get_settings.cache_clear()
    _sessions.clear()
    reset_voice_session_tokens_for_tests()
    try:
        limiter.reset()
    except Exception:
        pass


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
# POST /api/voice/opt-in — round trip flips status.effectiveEnable
# ---------------------------------------------------------------------------


class TestOptInEndpoint:
    def test_enable_then_disable_round_trip(self, loopback, voice_env):
        fresh = loopback.get("/api/voice/status")
        assert fresh.status_code == 200
        assert fresh.json()["effectiveEnable"] is False

        enabled = loopback.post("/api/voice/opt-in", json={"enable": True})
        assert enabled.status_code == 200
        body = enabled.json()
        assert body["ok"] is True
        assert body["effectiveEnable"] is True
        assert body["managedByEnvironment"] is False

        status = loopback.get("/api/voice/status")
        assert status.json()["effectiveEnable"] is True
        assert status.json()["opt_in_state"] == "enabled"

        disabled = loopback.post("/api/voice/opt-in", json={"enable": False})
        assert disabled.status_code == 200
        assert disabled.json()["ok"] is True
        assert disabled.json()["effectiveEnable"] is False
        assert loopback.get("/api/voice/status").json()["effectiveEnable"] is False

    def test_persisted_rows_land_in_operator_file(self, loopback, voice_env):
        response = loopback.post("/api/voice/opt-in", json={"enable": True})
        assert response.status_code == 200
        rows = api_settings_mod._parse_env_file(api_settings_mod.OPERATOR_KEYS_ENV_PATH)
        assert rows["VOICE_AGENT_OUTBOUND_ENABLE"] == "allow"
        assert rows["VOICE_AGENT_OUTBOUND_ACKNOWLEDGE"] == "true"

    def test_opt_in_alone_does_not_resolve_a_provider(self, loopback, voice_env):
        response = loopback.post("/api/voice/opt-in", json={"enable": True})
        assert response.json()["effectiveEnable"] is True
        status = loopback.get("/api/voice/status").json()
        assert status["provider"]["resolved"] is None
        assert status["degradedReason"], "unresolved provider must keep its honest reason"


# ---------------------------------------------------------------------------
# POST /api/voice/provider — save resolves through resolve_provider
# ---------------------------------------------------------------------------


class TestProviderSaveEndpoint:
    def test_gemini_key_resolves_gemini_live(self, loopback, voice_env):
        loopback.post("/api/voice/opt-in", json={"enable": True})

        saved = loopback.post(
            "/api/voice/provider",
            json={"provider": "gemini", "apiKey": "g-secret-key-123"},
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["ok"] is True
        assert body["provider"]["resolved"] == "gemini_live"
        assert body["provider"]["geminiKeySet"] is True
        assert body["provider"]["openaiKeySet"] is False

        status = loopback.get("/api/voice/status").json()
        assert status["provider"]["resolved"] == "gemini_live"
        assert status["degradedReason"] is None

    def test_openai_key_resolves_openai_realtime(self, loopback, voice_env):
        saved = loopback.post(
            "/api/voice/provider",
            json={"provider": "openai", "apiKey": "sk-openai-secret-xyz"},
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["provider"]["resolved"] == "openai_realtime"
        assert body["provider"]["openaiKeySet"] is True

    def test_compat_base_url_resolves_compatible_ws_and_optional_key(self, loopback, voice_env):
        base_only = loopback.post(
            "/api/voice/provider",
            json={"provider": "compat", "baseUrl": "http://127.0.0.1:11434/v1"},
        )
        assert base_only.status_code == 200, base_only.text
        assert base_only.json()["provider"]["resolved"] == "compatible_ws"
        assert base_only.json()["provider"]["compatBaseUrlSet"] is True
        assert base_only.json()["provider"]["compatKeySet"] is False

        with_key = loopback.post(
            "/api/voice/provider",
            json={
                "provider": "compat",
                "baseUrl": "http://127.0.0.1:11434/v1",
                "apiKey": "compat-key-42",
            },
        )
        assert with_key.status_code == 200
        assert with_key.json()["provider"]["compatKeySet"] is True

    def test_unknown_provider_is_400(self, loopback, voice_env):
        response = loopback.post(
            "/api/voice/provider", json={"provider": "elevenlabs", "apiKey": "k"}
        )
        assert response.status_code == 400
        body = response.json()
        assert body["ok"] is False
        assert body["error"] == "unknown_provider"

    @pytest.mark.parametrize("payload,field", [
        ({"provider": "openai"}, "apiKey"),
        ({"provider": "gemini"}, "apiKey"),
        ({"provider": "compat"}, "baseUrl"),
    ])
    def test_missing_required_field_is_400(self, loopback, voice_env, payload, field):
        response = loopback.post("/api/voice/provider", json=payload)
        assert response.status_code == 400
        body = response.json()
        assert body["ok"] is False
        assert body["error"] == "missing_field"
        assert body["field"] == field


# ---------------------------------------------------------------------------
# Env-var-wins honesty contract
# ---------------------------------------------------------------------------


class TestEnvVarWinsHonesty:
    def test_real_env_var_reports_managed_and_cannot_be_overridden(
        self, loopback, voice_env
    ):
        voice_env.setenv("VOICE_AGENT_OUTBOUND_ENABLE", "block")
        config_mod.get_settings.cache_clear()

        response = loopback.post("/api/voice/opt-in", json={"enable": True})
        assert response.status_code == 200
        body = response.json()
        assert body["managedByEnvironment"] is True
        # The real env var wins: the file write cannot enable the agent here.
        assert body["effectiveEnable"] is False
        assert "VOICE_AGENT_OUTBOUND_ENABLE" in body["note"]
        assert "environment variables always win" in body["note"]

        # The file row was still written (it governs future processes without
        # the env var) but this process stays disabled.
        rows = api_settings_mod._parse_env_file(api_settings_mod.OPERATOR_KEYS_ENV_PATH)
        assert rows["VOICE_AGENT_OUTBOUND_ENABLE"] == "allow"
        assert os.environ.get("VOICE_AGENT_OUTBOUND_ENABLE") == "block"

    def test_unmanaged_toggle_reports_no_environment_management(self, loopback, voice_env):
        response = loopback.post("/api/voice/opt-in", json={"enable": True})
        assert response.json()["managedByEnvironment"] is False
        assert "note" not in response.json()


# ---------------------------------------------------------------------------
# No key leakage anywhere in setup responses
# ---------------------------------------------------------------------------


class TestNoKeyLeakage:
    SECRETS = ["sk-openai-secret-xyz", "g-secret-key-123", "compat-key-42"]

    def test_raw_keys_never_appear_in_any_response_body(self, loopback, voice_env):
        responses = [
            loopback.post("/api/voice/opt-in", json={"enable": True}),
            loopback.post(
                "/api/voice/provider",
                json={"provider": "openai", "apiKey": "sk-openai-secret-xyz"},
            ),
            loopback.post(
                "/api/voice/provider",
                json={"provider": "gemini", "apiKey": "g-secret-key-123"},
            ),
            loopback.post(
                "/api/voice/provider",
                json={
                    "provider": "compat",
                    "baseUrl": "http://127.0.0.1:11434/v1",
                    "apiKey": "compat-key-42",
                },
            ),
            loopback.get("/api/voice/status"),
            loopback.get("/api/voice/tools"),
        ]
        bodies = [f"{r.status_code} {r.text}" for r in responses]
        for secret in self.SECRETS:
            for body in bodies:
                assert secret not in body, f"raw key {secret!r} leaked in response body"


# ---------------------------------------------------------------------------
# MESH_ONLY lean-mode guard covers the new endpoints too
# ---------------------------------------------------------------------------


class TestMeshOnlyGuard:
    def test_mesh_only_refuses_all_voice_routes_including_setup_api(self, caplog):
        saved = sys.modules.pop("routers.voice", None)
        os.environ["MESH_ONLY"] = "1"
        try:
            with caplog.at_level(logging.WARNING):
                mod = importlib.import_module("routers.voice")
            assert len(mod.router.routes) == 0, (
                "MESH_ONLY lean nodes must expose no voice routes (incl. opt-in/provider)"
            )
            assert any("refus" in record.getMessage().lower() for record in caplog.records)
        finally:
            os.environ.pop("MESH_ONLY", None)
            sys.modules.pop("routers.voice", None)
            if saved is not None:
                importlib.import_module("routers.voice")
