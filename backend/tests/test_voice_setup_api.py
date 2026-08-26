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
# POST /api/voice/provider — clear variant + replace-key upsert semantics
# ---------------------------------------------------------------------------


class TestProviderClearAndReplace:
    def _operator_rows(self):
        return api_settings_mod._parse_env_file(api_settings_mod.OPERATOR_KEYS_ENV_PATH)

    def test_clear_removes_gemini_key_and_model_rows(self, loopback, voice_env):
        loopback.post("/api/voice/opt-in", json={"enable": True})
        saved = loopback.post(
            "/api/voice/provider",
            json={"provider": "gemini", "apiKey": "g-secret-clear-1", "model": "gemini-3.1-flash-live-preview"},
        )
        assert saved.json()["provider"]["resolved"] == "gemini_live"
        rows = self._operator_rows()
        assert rows["VOICE_GEMINI_API_KEY"] == "g-secret-clear-1"
        assert rows["VOICE_GEMINI_MODEL"] == "gemini-3.1-flash-live-preview"

        cleared = loopback.post("/api/voice/provider", json={"provider": "gemini", "clear": True})
        assert cleared.status_code == 200, cleared.text
        body = cleared.json()
        assert body["ok"] is True
        assert body["cleared"] is True
        # Fresh status shape: nothing resolves anymore.
        assert body["provider"]["resolved"] is None
        assert body["provider"]["geminiKeySet"] is False

        # File re-read: the key AND its model row are gone.
        rows = self._operator_rows()
        assert "VOICE_GEMINI_API_KEY" not in rows
        assert "VOICE_GEMINI_MODEL" not in rows
        # Live env was synced too — the provider stays de-armed in-process.
        import os as _os

        assert not _os.environ.get("VOICE_GEMINI_API_KEY")
        status = loopback.get("/api/voice/status").json()
        assert status["provider"]["geminiKeySet"] is False

    def test_clear_is_idempotent_for_unknown_provider_rows(self, loopback, voice_env):
        loopback.post("/api/voice/opt-in", json={"enable": True})
        cleared = loopback.post(
            "/api/voice/provider", json={"provider": "openai", "clear": True}
        )
        assert cleared.status_code == 200
        assert cleared.json()["ok"] is True

    def test_clear_unknown_provider_is_400(self, loopback, voice_env):
        response = loopback.post(
            "/api/voice/provider", json={"provider": "elevenlabs", "clear": True}
        )
        assert response.status_code == 400
        assert response.json()["error"] == "unknown_provider"

    def test_saving_a_new_gemini_key_replaces_the_old_row_upsert(self, loopback, voice_env):
        loopback.post("/api/voice/opt-in", json={"enable": True})
        first = loopback.post(
            "/api/voice/provider",
            json={"provider": "gemini", "apiKey": "g-old-key", "model": "gemini-2.0-flash-live-001"},
        )
        assert first.status_code == 200

        second = loopback.post(
            "/api/voice/provider",
            json={"provider": "gemini", "apiKey": "g-new-key", "model": "gemini-3.1-flash-live-preview"},
        )
        assert second.status_code == 200
        assert second.json()["provider"]["geminiKeySet"] is True

        rows = self._operator_rows()
        # Upsert replaced both values; no duplicate KEY= rows lingered.
        assert rows["VOICE_GEMINI_API_KEY"] == "g-new-key"
        assert rows["VOICE_GEMINI_MODEL"] == "gemini-3.1-flash-live-preview"
        raw_text = api_settings_mod.OPERATOR_KEYS_ENV_PATH.read_text(encoding="utf-8")
        assert raw_text.count("VOICE_GEMINI_API_KEY=") == 1
        assert raw_text.count("VOICE_GEMINI_MODEL=") == 1
        assert "g-old-key" not in raw_text

    def test_remove_env_values_helper_drops_only_matching_rows(self, tmp_path):
        target = tmp_path / "keys.env"
        target.write_text(
            "# comment\n"
            "A_KEY=\"keep\"\n"
            "DROP_ME=\"gone\"\n"
            "\n"
            "OTHER=\"also keep\"\n",
            encoding="utf-8",
        )
        api_settings_mod._remove_env_values(target, {"drop_me"})
        text = target.read_text(encoding="utf-8")
        assert "DROP_ME" not in text
        assert 'A_KEY="keep"' in text
        assert 'OTHER="also keep"' in text
        assert "# comment" in text
        # Idempotent: removing an absent key leaves the file untouched-but-valid.
        api_settings_mod._remove_env_values(target, {"ABSENT_KEY"})
        assert len(api_settings_mod._parse_env_file(target)) == 2


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


# ---------------------------------------------------------------------------
# GET /api/voice/models — model discovery for the setup card dropdown
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"data": []}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Duck-typed httpx.AsyncClient — records requested URLs, returns queued
    responses per call."""

    requested: list = []
    responses: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        type(self).requested.append(url)
        idx = min(len(type(self).requested) - 1, len(type(self).responses) - 1)
        return type(self).responses[idx]


def _patch_httpx(monkeypatch, responses):
    import httpx

    _FakeAsyncClient.requested = []
    _FakeAsyncClient.responses = responses
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)


class TestVoiceModels:
    def test_curated_list_for_openai(self, loopback):
        body = loopback.get("/api/voice/models?provider=openai_realtime").json()
        assert body["ok"] is True
        assert body["curated"] is True
        ids = [m["id"] for m in body["models"]]
        assert "gpt-realtime" in ids

    def test_curated_list_for_gemini(self, loopback):
        body = loopback.get("/api/voice/models?provider=gemini_live").json()
        assert body["curated"] is True
        ids = [m["id"] for m in body["models"]]
        # Current Live lineup leads; the retired 2.0 id stays as secondary.
        assert ids[0] == "gemini-3.1-flash-live-preview"
        assert "gemini-2.0-flash-live-001" in ids
        assert "gemini-3.5-live-translate-preview" in ids

    def test_compat_queries_gateway_live_then_v1_fallback(self, loopback, monkeypatch):
        _patch_httpx(
            monkeypatch,
            [
                _FakeResponse(404, {"error": "not found"}),
                _FakeResponse(200, {"data": [{"id": "z-model"}, {"id": "a-model"}, {"nope": 1}]}),
            ],
        )
        body = loopback.get(
            "/api/voice/models?provider=compat&baseUrl=http://gw.test/v1&apiKey=k-1"
        ).json()
        # First probe hits {base}/models, fallback adds /v1 (no double-v1).
        assert "http://gw.test/v1/models" in _FakeAsyncClient.requested[0]
        assert "http://gw.test/v1/v1/models" not in _FakeAsyncClient.requested[1]
        assert body["ok"] is True
        assert [m["id"] for m in body["models"]] == ["a-model", "z-model"]

    def test_compat_failure_is_honest_not_fabricated(self, loopback, monkeypatch):
        _patch_httpx(monkeypatch, [_FakeResponse(503, {}), _FakeResponse(503, {})])
        body = loopback.get("/api/voice/models?provider=compat&baseUrl=http://gw.test").json()
        assert body["ok"] is False
        assert body["error"] == "models_unavailable"
        assert "503" in body["detail"]

    def test_unconfigured_returns_empty_with_note(self, loopback):
        body = loopback.get("/api/voice/models").json()
        assert body["ok"] is True
        assert body["models"] == []
        assert "note" in body

    def test_models_list_capped_at_100(self, loopback, monkeypatch):
        big = {"data": [{"id": f"m{i:03d}"} for i in range(250)]}
        _patch_httpx(monkeypatch, [_FakeResponse(200, big)])
        body = loopback.get("/api/voice/models?provider=compat&baseUrl=http://gw.test").json()
        assert len(body["models"]) == 100
