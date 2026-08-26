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
        assert setup["systemInstruction"]["parts"][0]["text"] == "VERBATIM RULES"
        assert setup["tools"][0]["functionDeclarations"][0]["name"] == "get_telemetry"
        assert len(setup["tools"][0]["functionDeclarations"]) == 1  # nameless dropped
        assert setup["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "kore"

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
    def test_url_carries_bidi_setup_path_and_key(self):
        from services.voice_gemini import gemini_ws_url

        url = gemini_ws_url("wss://generativelanguage.googleapis.com/ws", "secret", "gemini-2.0-flash-live-001")
        assert "BidiSetup" in url
        assert "key=secret" in url
        assert "model=gemini-2.0-flash-live-001" in url

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
        assert "BidiSetup" in url
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
