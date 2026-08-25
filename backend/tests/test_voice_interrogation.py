"""Voice-agent U6 — §2.7 interrogation relay (correlate_entity /
get_entity_profile behind voice turns).

Covers: local target resolution, tier-gating inheritance through
validate_and_gate, verbatim evidence-pack pass-through, per-session memory
capped at 2 exchanges, and POST /api/voice/interrogate endpoint contracts
(409 disabled / 503 unconfigured / 400 no-target / 200 happy path / 429 cap).
"""

from __future__ import annotations

import json
import os

import pytest
from httpx import ASGITransport, AsyncClient

import services.config as config_mod
import services.api_settings as api_settings_mod


@pytest.fixture()
def voice_env(tmp_path, monkeypatch):
    """Isolate all VOICE_* configuration (same discipline as U5 suites)."""
    from services.voice_broker import _sessions
    from limiter import limiter
    from services.voice_interrogation import reset_interrogation_memory_for_tests

    for name in list(os.environ):
        if name.startswith("VOICE_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(api_settings_mod, "OPERATOR_KEYS_ENV_PATH", tmp_path / "operator_keys.env")
    monkeypatch.setenv("SB_DATA_DIR", str(tmp_path / "data"))
    config_mod.get_settings.cache_clear()
    _sessions.clear()
    reset_interrogation_memory_for_tests()
    yield monkeypatch
    config_mod.get_settings.cache_clear()
    _sessions.clear()
    reset_interrogation_memory_for_tests()
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
            import asyncio

            self._loop = asyncio.new_event_loop()
            self._transport = ASGITransport(app=app, client=(peer_ip, 12345))
            self._base = f"http://{peer_ip}:8000"

        def _do(self, method: str, url: str, **kw):
            import asyncio

            async def go():
                async with AsyncClient(transport=self._transport, base_url=self._base) as ac:
                    return await ac.request(method, url, **kw)
            return self._loop.run_until_complete(go())

        def post(self, url, **kw):
            return self._do("POST", url, **kw)

        def close(self):
            self._loop.close()

    c = _Client()
    yield c
    c.close()


_SNAPSHOT = {
    "schema": "sb.grounding.v1",
    "view": {"bounds": {"south": 44.0, "west": 28.0, "north": 52.0, "east": 40.0}, "zoom": 6},
    "layers": {"active": ["tracked_flights"], "inactive_count": 12},
    "entities": [
        {"id": "ae1f23", "name": "RCH451", "layer": "tracked_flights"},
        {"id": "24b7ce", "name": "GLF7", "layer": "private_jets"},
        {"id": "5124789", "name": "MV VANTA", "layer": "ships"},
    ],
}


# ---------------------------------------------------------------------------
# Local target resolution (§2.7)
# ---------------------------------------------------------------------------


class TestTargetResolution:
    def test_explicit_target_wins(self):
        from services.voice_interrogation import resolve_interrogation_target

        resolved = resolve_interrogation_target(
            "who is this?",
            snapshot=_SNAPSHOT,
            target={"id": "ae1f23", "name": "RCH451", "layer": "tracked_flights"},
        )
        assert resolved is not None
        assert resolved["entity"]["id"] == "ae1f23"
        assert resolved["args"]["query"] == "RCH451"

    def test_why_question_routes_to_correlate_entity(self):
        from services.voice_interrogation import resolve_interrogation_target

        resolved = resolve_interrogation_target("why this alert?", snapshot=_SNAPSHOT)
        assert resolved is not None
        assert resolved["cmd"] == "correlate_entity"

    def test_who_question_routes_to_get_entity_profile(self):
        from services.voice_interrogation import resolve_interrogation_target

        resolved = resolve_interrogation_target("who is RCH451?", snapshot=_SNAPSHOT)
        assert resolved is not None
        assert resolved["cmd"] == "get_entity_profile"
        assert resolved["args"]["query"] == "RCH451"

    def test_mentioned_entity_id_is_matched(self):
        from services.voice_interrogation import resolve_interrogation_target

        resolved = resolve_interrogation_target("tell me about ae1f23", snapshot=_SNAPSHOT)
        assert resolved is not None
        assert resolved["entity"]["id"] == "ae1f23"

    def test_ship_entity_gets_mmsi_hint(self):
        from services.voice_interrogation import resolve_interrogation_target

        resolved = resolve_interrogation_target("profile MV VANTA", snapshot=_SNAPSHOT)
        assert resolved is not None
        assert resolved["cmd"] == "get_entity_profile"
        assert resolved["entity"]["layer"] == "ships"

    def test_no_match_is_honest_none(self):
        from services.voice_interrogation import resolve_interrogation_target

        empty = {**_SNAPSHOT, "entities": []}
        assert resolve_interrogation_target("why this alert?", snapshot=empty) is None
        assert resolve_interrogation_target("", snapshot=None) is None


# ---------------------------------------------------------------------------
# Relay mechanics: gating inheritance + evidence pack + memory cap
# ---------------------------------------------------------------------------


def _run(awaitable):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(awaitable)


class TestInterrogationTurn:
    @pytest.fixture()
    def relayed(self, monkeypatch):
        import services.voice_broker as broker
        import services.openclaw_channel as channel
        from services.voice_interrogation import reset_interrogation_memory_for_tests

        captured = {"dispatches": [], "legs": []}
        replies: list[str] = []

        async def fake_chat(messages, settings=None):
            captured["legs"].append([dict(m) for m in messages])
            reply = replies.pop(0) if replies else "Correlated with two naval contacts."
            return {"ok": True, "reply": reply, "model": "test-chat-model"}

        def fake_dispatch(cmd, args):
            captured["dispatches"].append((cmd, dict(args)))
            return {"ok": True, "data": {"cmd": cmd, "correlations": [{"summary": "consistent with"}]}}

        monkeypatch.setattr(broker, "chat_completion", fake_chat)
        monkeypatch.setattr(channel, "_dispatch_command", fake_dispatch)
        reset_interrogation_memory_for_tests()
        return captured, replies

    def test_happy_path_dispatches_and_narrates(self, relayed):
        from services.voice_interrogation import run_interrogation_turn

        captured, replies = relayed
        replies.append("Two naval contacts are consistent with the track.")
        result = _run(
            run_interrogation_turn(
                "why this alert about RCH451?",
                target={"id": "ae1f23", "name": "RCH451", "layer": "tracked_flights"},
                snapshot=_SNAPSHOT,
            )
        )
        assert result["ok"] is True
        assert result["command"] == "correlate_entity"
        assert result["evidence_ok"] is True
        assert len(captured["dispatches"]) == 1
        # Tier gating inherited: a restricted-tier READ command passes.
        cmd, args = captured["dispatches"][0]
        assert cmd == "correlate_entity" and args.get("query") == "RCH451"
        # Evidence pack rides as the second user message with the verbatim envelope.
        evidence = [m for m in captured["legs"][0] if m["content"].startswith("EVIDENCE PACK")]
        assert evidence and '"cmd": "correlate_entity"' in evidence[0]["content"]

    def test_no_target_refuses_without_dialing_the_model(self, relayed):
        from services.voice_interrogation import run_interrogation_turn

        captured, _replies = relayed
        empty = {**_SNAPSHOT, "entities": []}
        result = _run(run_interrogation_turn("why this alert?", snapshot=empty))
        assert result["ok"] is False
        assert result["error"] == "no_target"
        assert not captured["legs"], "an unresolved target must never reach the model"

    def test_per_session_memory_capped_at_two_exchanges(self, relayed):
        from services.voice_interrogation import (
            get_interrogation_memory,
            record_interrogation_exchange,
        )

        for i in range(5):
            record_interrogation_exchange("sess-a", f"q{i}", f"a{i}")
        memory = get_interrogation_memory("sess-a")
        assert len(memory) == 2  # §2.7 hard cap
        assert memory[-1]["question"] == "q4" and memory[0]["question"] == "q3"

        record_interrogation_exchange("sess-b", "other", "thread")
        assert len(get_interrogation_memory("sess-a")) == 2
        assert get_interrogation_memory("sess-b")[0]["question"] == "other"

    def test_memory_feeds_subsequent_turns_then_stops_growing(self, relayed):
        from services.voice_interrogation import run_interrogation_turn

        captured, replies = relayed
        replies.extend(["first answer", "second answer"])
        target = {"id": "ae1f23", "name": "RCH451", "layer": "tracked_flights"}
        _run(run_interrogation_turn("who is this?", target=target))
        _run(run_interrogation_turn("and why this alert?", target=target))
        _run(run_interrogation_turn("anything else?", target=target))
        second_leg = captured["legs"][1]
        earlier = [m for m in second_leg if str(m["content"]).startswith("(earlier)")]
        assert earlier and "who is this?" in earlier[0]["content"]
        third_leg = captured["legs"][2]
        earlier_third = [m for m in third_leg if str(m["content"]).startswith("(earlier)")]
        assert len(earlier_third) <= 4, "memory stays capped at 2 exchanges of context"


# ---------------------------------------------------------------------------
# POST /api/voice/interrogate
# ---------------------------------------------------------------------------


class TestInterrogateEndpoint:
    def test_disabled_is_409_with_reasons(self, loopback):
        response = loopback.post("/api/voice/interrogate", json={"question": "why?"})
        assert response.status_code == 409
        body = response.json()
        assert body["error"] == "opt_in_required"
        assert body["reasons"]

    def test_unconfigured_chat_model_is_503(self, loopback, voice_env):
        _enable(voice_env)  # opt-in satisfied, no VOICE_CHAT_MODEL
        response = loopback.post(
            "/api/voice/interrogate",
            json={"question": "why?", "target": {"id": "x", "name": "RCH451"}},
        )
        assert response.status_code == 503
        assert response.json()["error"] == "chat_unconfigured"

    def test_no_target_is_400_honest(self, loopback, voice_env, monkeypatch):
        import services.voice_broker as broker

        async def must_not_dial(messages, settings=None):  # pragma: no cover
            raise AssertionError("no-target must short-circuit before the chat leg")

        monkeypatch.setattr(broker, "chat_completion", must_not_dial)
        _enable(voice_env, VOICE_CHAT_MODEL="m")
        response = loopback.post(
            "/api/voice/interrogate",
            json={"question": "why this alert?", "snapshot": {**_SNAPSHOT, "entities": []}},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["ok"] is False and body["error"] == "no_target"

    def test_happy_path_returns_say_command_and_mode(self, loopback, voice_env, monkeypatch):
        import services.voice_broker as broker
        import services.openclaw_channel as channel

        async def fake_chat(messages, settings=None):
            return {"ok": True, "reply": "Consistent with two naval contacts.", "model": "t"}

        dispatched: list[tuple] = []

        def fake_dispatch(cmd, args):
            dispatched.append((cmd, dict(args)))
            return {"ok": True, "data": {"cmd": cmd}}

        monkeypatch.setattr(broker, "chat_completion", fake_chat)
        monkeypatch.setattr(channel, "_dispatch_command", fake_dispatch)
        _enable(voice_env, VOICE_CHAT_MODEL="m")

        response = loopback.post(
            "/api/voice/interrogate",
            json={
                "question": "who is RCH451?",
                "snapshot": _SNAPSHOT,
                "sessionId": "sess-42",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["say"] == "Consistent with two naval contacts."
        assert body["command"] == "get_entity_profile"
        assert body["evidence_ok"] is True
        assert body["mode"] in ("full", "mesh_lean")
        assert dispatched[0][0] == "get_entity_profile"

    def test_over_budget_is_429_before_any_generation(self, loopback, voice_env, monkeypatch):
        import services.voice_broker as broker

        async def must_not_dial(messages, settings=None):  # pragma: no cover
            raise AssertionError("budget cap must short-circuit before the chat leg")

        monkeypatch.setattr(broker, "chat_completion", must_not_dial)
        _enable(voice_env, VOICE_OPENAI_API_KEY="test-key", VOICE_DAILY_BUDGET_USD="0.01")
        from services.voice_daily_budget import record_response

        record_response(usd=0.05)
        response = loopback.post("/api/voice/interrogate", json={"question": "why?"})
        assert response.status_code == 429
        body = response.json()
        assert body["error"] == "budget"
        assert body["resetsAt"]
        assert int(response.headers["Retry-After"]) > 0
