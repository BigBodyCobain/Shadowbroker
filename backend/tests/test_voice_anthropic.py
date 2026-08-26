"""Anthropic TEXT-ONLY voice provider (Claude) — resolution, chat leg,
provider save, curated models, status disclosure, realtime exclusion.

HONESTY INVARIANT: Anthropic has NO realtime speech API — Claude is
text-in/text-out. ``anthropic_text`` must therefore behave like
``local_text`` on the realtime path: it never opens the WS media pipe and
the mic/PTT gate stays closed. These tests pin that invariant.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from httpx import ASGITransport, AsyncClient

import services.api_settings as api_settings_mod
import services.config as config_mod


@pytest.fixture()
def anthropic_env(tmp_path, monkeypatch):
    """Isolate all VOICE_* configuration (same pattern as test_voice_setup_api)."""
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
def loopback(anthropic_env):
    from main import app

    class _Client:
        def __init__(self, peer_ip: str = "127.0.0.1"):
            self._loop = asyncio.new_event_loop()
            self._transport = ASGITransport(app=app, client=(peer_ip, 12345))
            self._base = f"http://{peer_ip}:8000"

        def _do(self, method: str, url: str, **kw):
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
# resolve_provider — anthropic_text ordering + fields
# ---------------------------------------------------------------------------


class TestResolveProviderAnthropic:
    def test_anthropic_key_resolves_anthropic_text(self, anthropic_env):
        anthropic_env.setenv("VOICE_ANTHROPIC_API_KEY", "sk-ant-test-key")
        config_mod.get_settings.cache_clear()
        from services.voice_broker import resolve_provider

        info = resolve_provider(get_settings_safe())
        assert info["resolved"] == "anthropic_text"
        assert info["anthropicKeySet"] is True
        assert info["anthropicKey"] == "sk-ant-test-key"
        assert info["anthropicBase"] == "https://api.anthropic.com"
        assert info["degradedReason"] is None

    def test_auto_order_prefers_realtime_providers_over_anthropic(self, anthropic_env):
        anthropic_env.setenv("VOICE_ANTHROPIC_API_KEY", "sk-ant")
        config_mod.get_settings.cache_clear()
        from services.voice_broker import resolve_provider

        # OpenAI wins.
        anthropic_env.setenv("VOICE_OPENAI_API_KEY", "sk-oai")
        config_mod.get_settings.cache_clear()
        assert resolve_provider(get_settings_safe())["resolved"] == "openai_realtime"

        # Compat base beats Anthropic.
        os.environ.pop("VOICE_OPENAI_API_KEY", None)
        anthropic_env.setenv("VOICE_COMPAT_BASE_URL", "http://127.0.0.1:11434/v1")
        config_mod.get_settings.cache_clear()
        assert resolve_provider(get_settings_safe())["resolved"] == "compatible_ws"

        # Gemini key beats Anthropic.
        os.environ.pop("VOICE_COMPAT_BASE_URL", None)
        anthropic_env.setenv("VOICE_GEMINI_API_KEY", "g-key")
        config_mod.get_settings.cache_clear()
        assert resolve_provider(get_settings_safe())["resolved"] == "gemini_live"

    def test_anthropic_outranks_local_text_in_auto_mode(self, anthropic_env):
        from services.voice_broker import resolve_provider

        anthropic_env.setenv("VOICE_ANTHROPIC_API_KEY", "sk-ant")
        anthropic_env.setenv("VOICE_CHAT_MODEL", "some-chat-model")
        config_mod.get_settings.cache_clear()
        assert resolve_provider(get_settings_safe())["resolved"] == "anthropic_text"

    def test_requested_mode_pins_anthropic_text(self, anthropic_env):
        from services.voice_broker import resolve_provider

        anthropic_env.setenv("VOICE_ANTHROPIC_API_KEY", "sk-ant")
        anthropic_env.setenv("VOICE_PROVIDER", "anthropic_text")
        config_mod.get_settings.cache_clear()
        info = resolve_provider(get_settings_safe())
        assert info["resolved"] == "anthropic_text"
        assert info["requestedMode"] == "anthropic_text"

    def test_unconfigured_reason_mentions_the_anthropic_key(self, anthropic_env):
        from services.voice_broker import resolve_provider

        info = resolve_provider(get_settings_safe())
        assert info["resolved"] is None
        assert "VOICE_ANTHROPIC_API_KEY" in (info["degradedReason"] or "")


def get_settings_safe():
    config_mod.get_settings.cache_clear()
    return config_mod.get_settings()


# ---------------------------------------------------------------------------
# chat_completion — Anthropic /v1/messages branch
# ---------------------------------------------------------------------------


class _CaptureAsyncClient:
    """Duck-typed httpx.AsyncClient that records the POST contract."""

    captured: dict = {}
    response: object = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        type(self).captured = {"url": url, "json": json, "headers": dict(headers or {})}
        return type(self).response


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = "" if status_code < 400 else "upstream said no"

    def json(self):
        return self._payload


def _patch_httpx(monkeypatch, payload, status_code=200):
    import httpx

    _CaptureAsyncClient.captured = {}
    _CaptureAsyncClient.response = _FakeResponse(payload, status_code)
    monkeypatch.setattr(httpx, "AsyncClient", _CaptureAsyncClient)


class TestChatCompletionAnthropic:
    MESSAGES = [
        {"role": "system", "content": "You are the operator console."},
        {"role": "user", "content": "sitrep?"},
    ]

    ANTHROPIC_BODY = {
        "content": [
            {"type": "text", "text": "Hello"},
            {"type": "tool_use", "id": "x"},  # non-text block must be skipped
            {"type": "text", "text": " operator"},
        ],
        "usage": {"input_tokens": 1000, "output_tokens": 500},
    }

    def _enable(self, monkeypatch, **extra):
        monkeypatch.setenv("VOICE_AGENT_OUTBOUND_ENABLE", "allow")
        monkeypatch.setenv("VOICE_AGENT_OUTBOUND_ACKNOWLEDGE", "true")
        for key, value in extra.items():
            monkeypatch.setenv(key, value)

    def test_posts_messages_contract_with_system_extraction_and_reply_assembly(
        self, anthropic_env, monkeypatch
    ):
        self._enable(monkeypatch, VOICE_ANTHROPIC_API_KEY="sk-ant-k1", VOICE_CHAT_MODEL="claude-opus-4-1")
        _patch_httpx(monkeypatch, self.ANTHROPIC_BODY)

        from services.voice_broker import chat_completion

        result = asyncio.new_event_loop().run_until_complete(
            chat_completion(self.MESSAGES, settings=get_settings_safe())
        )
        captured = _CaptureAsyncClient.captured
        # URL + auth headers per Anthropic's Messages API contract.
        assert captured["url"] == "https://api.anthropic.com/v1/messages"
        assert captured["headers"]["x-api-key"] == "sk-ant-k1"
        assert captured["headers"]["anthropic-version"] == "2023-06-01"
        body = captured["json"]
        # System content collapses into `system`; messages exclude it.
        assert body["system"] == "You are the operator console."
        assert body["messages"] == [{"role": "user", "content": "sitrep?"}]
        assert body["model"] == "claude-opus-4-1"
        assert isinstance(body["max_tokens"], int) and body["max_tokens"] > 0
        # Reply assembly joins ONLY the text blocks.
        assert result["ok"] is True
        assert result["reply"] == "Hello operator"
        assert result["model"] == "claude-opus-4-1"
        # Usage mapped into the same metering shape.
        assert result["usage"] == {"input_tokens": 1000.0, "output_tokens": 500.0}

    def test_default_model_reuses_chat_model_setting_or_curated_fallback(
        self, anthropic_env, monkeypatch
    ):
        self._enable(monkeypatch, VOICE_ANTHROPIC_API_KEY="sk-ant-k2")
        _patch_httpx(monkeypatch, self.ANTHROPIC_BODY)

        from services.voice_broker import chat_completion

        loop = asyncio.new_event_loop()
        # No VOICE_CHAT_MODEL row → curated fallback head.
        result = loop.run_until_complete(chat_completion(self.MESSAGES, settings=get_settings_safe()))
        assert _CaptureAsyncClient.captured["json"]["model"] == "claude-sonnet-4-5"

        # An explicit VOICE_CHAT_MODEL doubles as the Anthropic model id.
        monkeypatch.setenv("VOICE_CHAT_MODEL", "claude-3-5-haiku-latest")
        result = loop.run_until_complete(chat_completion(self.MESSAGES, settings=get_settings_safe()))
        assert result["model"] == "claude-3-5-haiku-latest"
        loop.close()

    def test_usage_metering_grows_daily_ledger(self, anthropic_env, monkeypatch):
        self._enable(monkeypatch, VOICE_ANTHROPIC_API_KEY="sk-ant-k3", VOICE_CHAT_MODEL="claude-sonnet-4-5")
        _patch_httpx(monkeypatch, self.ANTHROPIC_BODY)

        from services.voice_broker import chat_completion
        from services.voice_daily_budget import read_daily_spend

        before = read_daily_spend()["usdSpent"]
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(chat_completion(self.MESSAGES, settings=get_settings_safe()))
        loop.close()
        assert result["ok"] is True
        after = read_daily_spend()["usdSpent"]
        # 1000 input × $4 + 500 output × $24 per 1M (worst-case table for an
        # unrecognized model id) — degraded text traffic IS metered.
        assert abs(after - before - 0.016) < 1e-6

    def test_upstream_error_returns_typed_envelope(self, anthropic_env, monkeypatch):
        self._enable(monkeypatch, VOICE_ANTHROPIC_API_KEY="sk-ant-k4")
        _patch_httpx(monkeypatch, {"error": "nope"}, status_code=401)

        from services.voice_broker import chat_completion

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(chat_completion(self.MESSAGES, settings=get_settings_safe()))
        loop.close()
        assert result["ok"] is False
        assert result["error"] == "upstream_error"
        assert result["status"] == 401


# ---------------------------------------------------------------------------
# POST /api/voice/provider — anthropic save path
# ---------------------------------------------------------------------------


class TestProviderSaveAnthropic:
    def test_save_persists_key_and_model_and_resolves_anthropic_text(self, loopback):
        saved = loopback.post(
            "/api/voice/provider",
            json={"provider": "anthropic", "apiKey": "sk-ant-secret-77", "model": "claude-opus-4-1"},
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["ok"] is True
        assert body["provider"]["resolved"] == "anthropic_text"
        assert body["provider"]["anthropicKeySet"] is True

        rows = api_settings_mod._parse_env_file(api_settings_mod.OPERATOR_KEYS_ENV_PATH)
        assert rows["VOICE_ANTHROPIC_API_KEY"] == "sk-ant-secret-77"
        assert rows["VOICE_CHAT_MODEL"] == "claude-opus-4-1"

        status = loopback.get("/api/voice/status").json()
        assert status["provider"]["resolved"] == "anthropic_text"
        assert status["provider"]["anthropicKeySet"] is True

    def test_missing_key_is_400_missing_field(self, loopback):
        response = loopback.post("/api/voice/provider", json={"provider": "anthropic"})
        assert response.status_code == 400
        body = response.json()
        assert body["error"] == "missing_field"
        assert body["field"] == "apiKey"

    def test_unknown_provider_still_400(self, loopback):
        response = loopback.post("/api/voice/provider", json={"provider": "mistral", "apiKey": "k"})
        assert response.status_code == 400
        assert response.json()["error"] == "unknown_provider"

    def test_key_never_echoed_in_responses(self, loopback):
        bodies = [
            loopback.post("/api/voice/provider", json={"provider": "anthropic", "apiKey": "sk-ant-leak-check"}),
            loopback.get("/api/voice/status"),
        ]
        for resp in bodies:
            assert "sk-ant-leak-check" not in resp.text


# ---------------------------------------------------------------------------
# GET /api/voice/models — curated Anthropic list
# ---------------------------------------------------------------------------


class TestVoiceModelsAnthropic:
    CURATED = ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-5-haiku-latest"]

    def test_curated_list_for_provider_param(self, loopback):
        body = loopback.get("/api/voice/models?provider=anthropic").json()
        assert body["ok"] is True
        assert body["curated"] is True
        assert [m["id"] for m in body["models"]] == self.CURATED

    def test_curated_list_when_resolved_is_anthropic_text(self, loopback):
        saved = loopback.post("/api/voice/provider", json={"provider": "anthropic", "apiKey": "sk-ant-m1"})
        assert saved.status_code == 200
        body = loopback.get("/api/voice/models").json()
        assert body["curated"] is True
        assert [m["id"] for m in body["models"]] == self.CURATED


# ---------------------------------------------------------------------------
# Status payload — anthropicKeySet disclosed in both shapes, never 500s
# ---------------------------------------------------------------------------


class TestStatusPayloadAnthropic:
    def test_success_shape_carries_anthropic_key_set_false_on_fresh_install(self, loopback):
        body = loopback.get("/api/voice/status").json()
        assert body["ok"] is True
        assert body["provider"]["anthropicKeySet"] is False

    def test_catchall_shape_also_discloses_anthropic_key_set(self, loopback, monkeypatch):
        def _boom():
            raise RuntimeError("boom")

        try:
            monkeypatch.setattr(config_mod, "get_settings", _boom)
            body = loopback.get("/api/voice/status").json()
        finally:
            # Undo BEFORE fixture teardown — anthropic_env clears the settings
            # cache on the way out and must see the real get_settings again.
            monkeypatch.undo()
        assert body["ok"] is True  # status NEVER 500s
        assert body["provider"]["anthropicKeySet"] is False


# ---------------------------------------------------------------------------
# Realtime exclusion — anthropic_text is CHAT-ONLY end-to-end
# ---------------------------------------------------------------------------


class _FakeRelayWS:
    def __init__(self):
        self.frames: list = []
        self.closed = False

    async def send_text(self, text):
        import json as _json

        self.frames.append(_json.loads(text))

    async def send_bytes(self, data):
        self.frames.append(data)

    async def receive(self):  # never called by the text-only guard path
        await asyncio.sleep(3600)

    async def close(self, code=None):
        self.closed = True


class TestRealtimeExclusion:
    def test_relay_refuses_anthropic_text_without_any_upstream_dial(self, anthropic_env, monkeypatch):
        anthropic_env.setenv("VOICE_ANTHROPIC_API_KEY", "sk-ant-relay")
        config_mod.get_settings.cache_clear()

        import services.voice_broker as broker
        from services.voice_broker import create_session, run_realtime_relay

        async def _no_dial(url, headers):
            raise AssertionError(f"realtime dial attempted for a text-only provider: {url}")

        monkeypatch.setattr(broker, "_connect_upstream", _no_dial)

        session, error = create_session(tier="standard")
        assert error is None and session is not None
        ws = _FakeRelayWS()
        asyncio.new_event_loop().run_until_complete(run_realtime_relay(ws, session))
        types = [f.get("type") for f in ws.frames if isinstance(f, dict)]
        assert "ready" not in types, "text-only provider must never open the media pipe"
        assert "closed" in types
        closed = next(f for f in ws.frames if isinstance(f, dict) and f.get("type") == "closed")
        assert closed["reason"] == "text_only_provider"
