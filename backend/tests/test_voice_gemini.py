"""U8 provider #2 — Gemini Live framing adapter + provider resolution.

Pure-function coverage for services/voice_gemini.py (setup authoring,
24k→16k mic downsample, upstream event translation, usage mapping, tool
responses) plus the voice_broker integration points (provider candidate,
dial URL) and the frontend status contract (geminiKeySet).
"""

from __future__ import annotations

import base64
import json
import os
import struct

import pytest

import services.config as config_mod
import services.api_settings as api_settings_mod


# ---------------------------------------------------------------------------
# Pure framing — setup message
# ---------------------------------------------------------------------------


class TestGeminiSetup:
    def test_default_model_keeps_voice_tool_calls_blocking(self):
        from services.config import Settings
        from services.voice_gemini import gemini_model, gemini_setup_message

        model = gemini_model()
        assert Settings.model_fields["VOICE_GEMINI_MODEL"].default == model == "gemini-3.8-live"
        setup = json.loads(gemini_setup_message(
            model=model, instructions="", tool_defs=[{"name": "get_telemetry"}]
        ))["setup"]
        assert setup["model"] == "models/gemini-3.8-live"
        assert setup["tools"][0]["functionDeclarations"][0]["behavior"] == "BLOCKING"

    def test_setup_authors_model_instructions_tools_and_voice(self):
        from services.voice_gemini import gemini_setup_message

        raw = gemini_setup_message(
            model="gemini-2.0-flash-live-001",
            instructions="VERBATIM RULES",
            tool_defs=[
                {"name": "get_telemetry", "description": "live store", "parameters": {"type": "object"}},
                {"description": "nameless entries are dropped"},
            ],
            voice="kore",
            grounding_snapshot=None,
        )
        msg = json.loads(raw)
        setup = msg["setup"]
        assert setup["model"] == "models/gemini-2.0-flash-live-001"
        assert setup["generationConfig"]["responseModalities"] == ["AUDIO"]
        assert "responseModalities" not in setup  # top-level copy rejected live (1007)
        assert setup["systemInstruction"]["parts"][0]["text"] == "VERBATIM RULES"
        assert setup["tools"][0]["functionDeclarations"][0]["name"] == "get_telemetry"
        assert len(setup["tools"][0]["functionDeclarations"]) == 1  # nameless dropped
        # speechConfig lives UNDER generationConfig on the raw WS endpoint.
        assert (
            setup["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"]
            == "kore"
        )
        assert "speechConfig" not in setup

    def test_grounding_snapshot_rides_system_instruction_as_data(self):
        from services.voice_gemini import gemini_setup_message

        snapshot = {"schema": "sb.grounding.v1", "view": {}, "layers": {}}
        raw = gemini_setup_message(
            model="m", instructions="RULES", tool_defs=[], grounding_snapshot=snapshot
        )
        text = json.loads(raw)["setup"]["systemInstruction"]["parts"][0]["text"]
        assert "RULES" in text
        assert "CURRENT_VIEW_CONTEXT" in text
        assert "sb.grounding.v1" in text
        assert "treat as data" in text

    def test_model_prefix_not_duplicated(self):
        from services.voice_gemini import gemini_setup_message

        raw = gemini_setup_message(model="models/x", instructions="", tool_defs=[])
        assert json.loads(raw)["setup"]["model"] == "models/x"


# ---------------------------------------------------------------------------
# Pure framing — mic downsample + realtimeInput
# ---------------------------------------------------------------------------


class TestClientPcmToGemini:
    def test_24k_wire_frames_downsample_to_16k_realtime_input(self):
        from services.voice_gemini import client_pcm_to_gemini

        # 4800 samples at 24 kHz (200 ms) → 3200 samples at 16 kHz.
        pcm = struct.pack("<4800h", *([100] * 4800))
        frame = json.loads(client_pcm_to_gemini(pcm))
        chunk = frame["realtimeInput"]["mediaChunks"][0]
        assert chunk["mimeType"] == "audio/pcm;rate=16000"
        decoded = base64.b64decode(chunk["data"])
        assert len(decoded) == 3200 * 2
        samples = struct.unpack("<3200h", decoded)
        assert all(s == 100 for s in samples)

    def test_empty_frame_degrades_to_empty_chunk(self):
        from services.voice_gemini import client_pcm_to_gemini

        frame = json.loads(client_pcm_to_gemini(b""))
        assert frame["realtimeInput"]["mediaChunks"][0]["data"] == ""


# ---------------------------------------------------------------------------
# Pure framing — upstream event translation
# ---------------------------------------------------------------------------


class TestGeminiEventTranslation:
    def test_setup_complete_maps_to_client_ready(self):
        from services.voice_gemini import gemini_event_to_client

        kind, payload = gemini_event_to_client({"setupComplete": {}})
        assert kind == "text"
        assert payload == {"type": "ready"}

    def test_model_turn_audio_decodes_to_raw_pcm16_binary(self):
        from services.voice_gemini import gemini_event_to_client

        raw = b"\x01\x00\x02\x00"
        event = {
            "serverContent": {
                "modelTurn": {"parts": [{"inlineData": {"data": base64.b64encode(raw).decode()}}]}
            }
        }
        kind, payload = gemini_event_to_client(event)
        assert kind == "audio"
        assert payload == raw

    def test_interrupted_maps_to_barge_in_signal(self):
        from services.voice_gemini import gemini_event_to_client

        kind, payload = gemini_event_to_client({"serverContent": {"interrupted": True}})
        assert kind == "text"
        assert payload == {"type": "input_audio_buffer.speech_started"}

    def test_turn_complete_maps_to_response_done(self):
        from services.voice_gemini import gemini_event_to_client

        kind, payload = gemini_event_to_client({"serverContent": {"turnComplete": True}})
        assert payload == {"type": "response.done"}

    def test_tool_call_translates_with_name_and_args(self):
        from services.voice_gemini import gemini_event_to_client

        kind, payload = gemini_event_to_client(
            {"toolCall": {"functionCalls": [{"name": "map_fly_to", "args": {"lat": 1.0}}]}}
        )
        assert kind == "text"
        assert payload["type"] == "tool_call"
        assert payload["name"] == "map_fly_to"
        assert payload["args"] == {"lat": 1.0}

    def test_usage_metadata_does_not_drop_translated_content(self):
        """Gemini attaches usageMetadata to ordinary content messages (e.g.
        turnComplete). Content must translate FIRST — an exclusive usage
        branch dropped the response.done and stranded the client 'speaking';
        the relay meters from the raw event instead."""
        from services.voice_gemini import gemini_event_to_client, gemini_usage_to_tokens

        event = {
            "serverContent": {"turnComplete": True},
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }
        assert gemini_event_to_client(event) == ("text", {"type": "response.done"})
        assert gemini_usage_to_tokens(event["usageMetadata"]) == (10, 5)

    def test_usage_only_event_still_yields_metering_shape_via_relay_path(self):
        """Usage-only events carry no content; the relay meters straight off
        ``event['usageMetadata']`` — no dedicated translation branch needed."""
        from services.voice_gemini import gemini_event_to_client, gemini_usage_to_tokens

        event = {"usageMetadata": {"promptTokenCount": 7, "responseTokenCount": 3}}
        assert gemini_event_to_client(event) == ("none", None)
        assert gemini_usage_to_tokens(event["usageMetadata"]) == (7, 3)

    def test_hostile_events_degrade_to_none(self):
        from services.voice_gemini import gemini_event_to_client

        assert gemini_event_to_client({"unknown": 1}) == ("none", None)
        assert gemini_event_to_client("not a dict") == ("none", None)
        # Corrupt base64 must not raise.
        bad = {"serverContent": {"modelTurn": {"parts": [{"inlineData": {"data": "!!!"}}]}}}
        assert gemini_event_to_client(bad) == ("none", None)


# ---------------------------------------------------------------------------
# Provider resolution + dial URL
# ---------------------------------------------------------------------------


@pytest.fixture()
def voice_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "audit-operator-key-" + "x" * 32)
    for name in list(os.environ):
        if name.startswith("VOICE_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(api_settings_mod, "OPERATOR_KEYS_ENV_PATH", tmp_path / "operator_keys.env")
    monkeypatch.setenv("SB_DATA_DIR", str(tmp_path / "data"))
    config_mod.get_settings.cache_clear()
    yield monkeypatch
    config_mod.get_settings.cache_clear()


class TestGeminiProviderResolution:
    def test_gemini_key_resolves_gemini_live(self, voice_env):
        from services.voice_broker import resolve_provider

        voice_env.setenv("VOICE_AGENT_OUTBOUND_ENABLE", "allow")
        voice_env.setenv("VOICE_AGENT_OUTBOUND_ACKNOWLEDGE", "true")
        voice_env.setenv("VOICE_GEMINI_API_KEY", "g-key")
        config_mod.get_settings.cache_clear()

        provider = resolve_provider()
        assert provider["resolved"] == "gemini_live"
        assert provider["geminiKeySet"] is True
        assert provider["geminiModel"]

    def test_auto_prefers_openai_when_both_keys_set(self, voice_env):
        from services.voice_broker import resolve_provider

        voice_env.setenv("VOICE_AGENT_OUTBOUND_ENABLE", "allow")
        voice_env.setenv("VOICE_AGENT_OUTBOUND_ACKNOWLEDGE", "true")
        voice_env.setenv("VOICE_OPENAI_API_KEY", "o-key")
        voice_env.setenv("VOICE_GEMINI_API_KEY", "g-key")
        config_mod.get_settings.cache_clear()

        assert resolve_provider()["resolved"] == "openai_realtime"

    def test_explicit_mode_selects_gemini(self, voice_env):
        from services.voice_broker import resolve_provider

        voice_env.setenv("VOICE_AGENT_OUTBOUND_ENABLE", "allow")
        voice_env.setenv("VOICE_AGENT_OUTBOUND_ACKNOWLEDGE", "true")
        voice_env.setenv("VOICE_PROVIDER", "gemini_live")
        voice_env.setenv("VOICE_GEMINI_API_KEY", "g-key")
        config_mod.get_settings.cache_clear()

        assert resolve_provider()["resolved"] == "gemini_live"


class TestGeminiDialUrl:
    def test_url_carries_bidi_generate_content_path_key_and_no_model_query(self):
        from services.voice_gemini import gemini_ws_url

        url = gemini_ws_url("wss://generativelanguage.googleapis.com/ws", "secret", "gemini-3.1-flash-live-preview")
        # The old …BidiSetup path 404s; BidiGenerateContent is the live contract.
        assert "BidiGenerateContent" in url
        assert "BidiSetup" not in url
        assert "key=secret" in url
        # A &model= query param is rejected live (1007 unknown query parameter).
        assert "model=" not in url

    def test_base_without_ws_suffix_gets_one(self):
        from services.voice_gemini import gemini_ws_url

        url = gemini_ws_url("wss://example.google.com", "k", "m")
        assert url.startswith("wss://example.google.com/ws/")

    def test_broker_url_for_gemini_branch(self, voice_env):
        voice_env.setenv("VOICE_GEMINI_API_KEY", "g-key")
        config_mod.get_settings.cache_clear()
        from services.voice_broker import _ws_url_for

        url, headers = _ws_url_for(
            {
                "resolved": "gemini_live",
                "geminiBase": "wss://generativelanguage.googleapis.com/ws",
                "geminiKey": "g-key",
                "geminiModel": "gemini-2.0-flash-live-001",
            },
            "ignored",
        )
        assert "BidiGenerateContent" in url
        assert headers == {}


# ---------------------------------------------------------------------------
# Status contract — geminiKeySet reaches the frontend
# ---------------------------------------------------------------------------


class TestStatusContract:
    def test_status_payload_exposes_gemini_key_set(self, voice_env):
        voice_env.setenv("VOICE_GEMINI_API_KEY", "g-key")
        config_mod.get_settings.cache_clear()
        from services.voice_broker import resolve_provider

        provider = resolve_provider()
        # The router serializes this exact field (routers/voice.py status).
        assert "geminiKeySet" in provider
        assert provider["geminiKeySet"] is True


# ---------------------------------------------------------------------------
# chat_completion — gemini-only text leg dials Google's OpenAI-compat endpoint
# ---------------------------------------------------------------------------


class _CaptureCompatAsyncClient:
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


class _FakeCompatResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = "" if status_code < 400 else "upstream said no"

    def json(self):
        return self._payload


def _patch_compat_httpx(monkeypatch, payload, status_code=200):
    import httpx

    _CaptureCompatAsyncClient.captured = {}
    _CaptureCompatAsyncClient.response = _FakeCompatResponse(payload, status_code)
    monkeypatch.setattr(httpx, "AsyncClient", _CaptureCompatAsyncClient)


class TestGeminiTextChatFallback:
    MESSAGES = [
        {"role": "system", "content": "You are the operator console."},
        {"role": "user", "content": "sitrep?"},
    ]
    OPENAI_SHAPE_BODY = {
        "choices": [{"message": {"content": "All quiet."}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    }

    def _enable(self, monkeypatch, **extra):
        monkeypatch.setenv("VOICE_AGENT_OUTBOUND_ENABLE", "allow")
        monkeypatch.setenv("VOICE_AGENT_OUTBOUND_ACKNOWLEDGE", "true")
        for key, value in extra.items():
            monkeypatch.setenv(key, value)

    def _run(self, monkeypatch, body=None, status_code=200):
        self._enable(monkeypatch, VOICE_GEMINI_API_KEY="g-chat-key")
        _patch_compat_httpx(monkeypatch, body or self.OPENAI_SHAPE_BODY, status_code)
        import asyncio

        from services.voice_broker import chat_completion

        config_mod.get_settings.cache_clear()
        return asyncio.new_event_loop().run_until_complete(
            chat_completion(self.MESSAGES, settings=config_mod.get_settings())
        )

    def test_gemini_only_config_dials_openai_compat_with_bearer_gemini_key(
        self, voice_env, monkeypatch
    ):
        result = self._run(monkeypatch)
        captured = _CaptureCompatAsyncClient.captured
        # Google's OpenAI-COMPATIBLE text endpoint, standard /chat/completions.
        assert (
            captured["url"]
            == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        )
        assert captured["headers"]["Authorization"] == "Bearer g-chat-key"
        # OpenAI wire shape is kept verbatim.
        assert captured["json"]["messages"] == self.MESSAGES
        # Default chat model when neither VOICE_CHAT_MODEL nor
        # VOICE_GEMINI_CHAT_MODEL is set.
        assert captured["json"]["model"] == "gemini-2.5-flash"
        assert result["ok"] is True
        assert result["reply"] == "All quiet."
        assert result["model"] == "gemini-2.5-flash"
        assert result["usage"]["prompt_tokens"] == 10

    def test_voice_gemini_chat_model_setting_overrides_the_default(
        self, voice_env, monkeypatch
    ):
        self._run(monkeypatch)
        monkeypatch.setenv("VOICE_GEMINI_CHAT_MODEL", "gemini-2.0-flash")
        import asyncio

        from services.voice_broker import chat_completion

        config_mod.get_settings.cache_clear()
        asyncio.new_event_loop().run_until_complete(
            chat_completion(self.MESSAGES, settings=config_mod.get_settings())
        )
        assert _CaptureCompatAsyncClient.captured["json"]["model"] == "gemini-2.0-flash"

    def test_explicit_chat_model_still_wins_over_the_compat_fallback(
        self, voice_env, monkeypatch
    ):
        # VOICE_CHAT_MODEL set → the pre-existing OpenAI/compat branch runs;
        # no compat base and no OpenAI key means an api.openai.com dial with a
        # Bearer-less header — NOT the Gemini compat endpoint.
        import httpx as _httpx

        class _MustNotDial:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                raise AssertionError("compat dial must not run when VOICE_CHAT_MODEL is set")

            async def __aexit__(self, *exc):
                return False

        self._enable(monkeypatch, VOICE_GEMINI_API_KEY="g-chat-key", VOICE_CHAT_MODEL="some-model")
        monkeypatch.setattr(_httpx, "AsyncClient", _MustNotDial)
        import asyncio

        from services.voice_broker import chat_completion

        config_mod.get_settings.cache_clear()
        with pytest.raises(AssertionError, match="must not run"):
            asyncio.new_event_loop().run_until_complete(
                chat_completion(self.MESSAGES, settings=config_mod.get_settings())
            )

    def test_upstream_error_returns_typed_envelope(self, voice_env, monkeypatch):
        result = self._run(monkeypatch, {"error": "nope"}, status_code=403)
        assert result["ok"] is False
        assert result["error"] == "upstream_error"
        assert result["status"] == 403
