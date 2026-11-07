"""LIVE Gemini BidiGenerateContent handshake integration test.

SKIPPED unless ``VOICE_GEMINI_API_KEY`` is set (real key, real network,
real cost) — run explicitly with::

    VOICE_GEMINI_API_KEY=... python -m pytest tests/test_voice_gemini_live.py -q

Contract verified live 2026-02 against wss://generativelanguage.googleapis.com:
dial …BidiGenerateContent?key=<KEY> (no model query param), send one
``{"setup": {...}}`` frame authored by :func:`services.voice_gemini.gemini_setup_message`,
await ``setupComplete``, then push one 16 kHz PCM chunk and require either
modelTurn audio or a typed upstream error (never silence).
"""

from __future__ import annotations

import asyncio
import json
import os
import struct

import pytest

# Skip before any heavy imports when the live key is absent.
if not os.environ.get("VOICE_GEMINI_API_KEY"):
    pytest.skip("VOICE_GEMINI_API_KEY not set — live Gemini handshake test skipped", allow_module_level=True)

from services.voice_gemini import (  # noqa: E402
    GEMINI_DEFAULT_MODEL,
    client_pcm_to_gemini,
    gemini_model,
    gemini_setup_message,
    gemini_ws_url,
)

HANDSHAKE_TIMEOUT_S = 30.0
AUDIO_REPLY_WINDOW_S = 20.0


def _billing_hint(close_or_error: object) -> str:
    text = str(close_or_error)
    if "prepayment credits" in text or "billing" in text.lower():
        return (
            "Google rejected the session for ACCOUNT reasons (prepayment credits "
            "depleted) — top up at https://ai.studio/projects; this is not an "
            "adapter-contract failure."
        )
    return ""


async def _handshake() -> dict:
    """Dial + setup exactly as voice_broker.run_realtime_relay does."""
    from websockets.asyncio.client import connect

    key = os.environ["VOICE_GEMINI_API_KEY"]
    url = gemini_ws_url("wss://generativelanguage.googleapis.com/ws", key, gemini_model())
    setup = gemini_setup_message(
        model=gemini_model() or GEMINI_DEFAULT_MODEL,
        instructions="You are a helpful voice assistant. Reply briefly.",
        tool_defs=[],
        voice="aoede",
        grounding_snapshot=None,
    )
    trace: dict = {"url_path": url.split("?")[0], "frames": []}
    async with connect(url, max_size=None) as ws:
        await ws.send(setup)
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=HANDSHAKE_TIMEOUT_S)
            event = json.loads(raw)
            trace["frames"].append(event)
            if "setupComplete" in event:
                return trace
            error = event.get("error")
            if error:
                pytest.fail(f"Gemini rejected the setup: {error}. {_billing_hint(error)}")


def test_gemini_live_handshake_reaches_setup_complete():
    trace = asyncio.new_event_loop().run_until_complete(_handshake())
    assert trace["frames"], "no frames received"


def test_gemini_live_audio_chunk_gets_audio_or_typed_error():
    """One 16 kHz PCM chunk must produce modelTurn audio or an intelligible
    error — never silent abandonment (the original 'LINK… forever' symptom)."""

    async def run() -> dict:
        from websockets.asyncio.client import connect

        key = os.environ["VOICE_GEMINI_API_KEY"]
        url = gemini_ws_url("wss://generativelanguage.googleapis.com/ws", key, gemini_model())
        setup = gemini_setup_message(
            model=gemini_model() or GEMINI_DEFAULT_MODEL,
            instructions="You are a helpful voice assistant. Reply briefly.",
            tool_defs=[],
            voice="aoede",
            grounding_snapshot=None,
        )
        # 1 s of 440 Hz tone at 16 kHz, mono PCM16.
        pcm = struct.pack("<16000h", *([int(8000 * __import__("math").sin(i * 0.172)) for i in range(16000)]))
        trace: dict = {"audio_bytes": 0, "errors": [], "turn_complete": False}
        async with connect(url, max_size=None) as ws:
            await ws.send(setup)
            saw_setup_complete = False
            while not saw_setup_complete:
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=HANDSHAKE_TIMEOUT_S))
                if "setupComplete" in event:
                    saw_setup_complete = True
                elif event.get("error"):
                    pytest.fail(f"Gemini rejected the setup: {event['error']}. {_billing_hint(event['error'])}")
            await ws.send(client_pcm_to_gemini(pcm))
            try:
                while True:
                    event = json.loads(await asyncio.wait_for(ws.recv(), timeout=AUDIO_REPLY_WINDOW_S))
                    server = event.get("serverContent") or {}
                    turn = server.get("modelTurn") or {}
                    for part in turn.get("parts") or []:
                        data = ((part or {}).get("inlineData") or {}).get("data") or ""
                        trace["audio_bytes"] += len(data)
                    if server.get("turnComplete"):
                        trace["turn_complete"] = True
                        break
                    if event.get("error"):
                        trace["errors"].append(event["error"])
                        break
            except asyncio.TimeoutError:
                pass
        return trace

    trace = asyncio.new_event_loop().run_until_complete(run())
    assert trace["audio_bytes"] > 0 or trace["errors"] or trace["turn_complete"], (
        f"silent abandonment after audio chunk: {trace}"
    )
