"""Voice-agent U7 integration matrix (plan §6 U7 row — spans U2–U6 surfaces).

Cross-milestone rows that no single-subsystem suite covers end-to-end:

1. Opt-in gate uniformity: every billable/sensitive voice endpoint refuses
   with honest reasons while the two-step opt-in is incomplete (status stays
   200 — it is the surface that EXPLAINS the refusal).
2. Full operator journey in deterministic mode (zero model, zero outbound):
   status → tools manifest → stateless tool execute → turn/hud-summary/
   interrogate degrade with 503 ``chat_unconfigured``.
3. Cross-surface budget latch: one persisted daily ledger, crossed once,
   429s session + turn + hud-summary + interrogate alike (§2.7 latched cap).
4. Status never-500 contract under a hostile store (catch-all honesty).
5. Kill-switch lifecycle: mint → DELETE → 404 on repeat.
6. Watchdog producer hook: ``broadcast_to_agents`` fans ``type:"alert"``
   payloads into the voice tap (§3.8) without voice importing the watchdog.
7. MESH_ONLY source guard: the lean-mode stub + import guard remain wired.

The WS upgrade/wire-contract suites live in test_voice_session_api.py; the
per-endpoint gating matrices live in test_voice_router.py. This file asserts
the seams BETWEEN the milestones.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import services.config as config_mod
import services.api_settings as api_settings_mod


@pytest.fixture()
def voice_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "audit-operator-key-" + "x" * 32)
    """Isolate all VOICE_* configuration (same contract as test_voice_router)."""
    from services.voice_broker import _sessions
    from services.voice_session_tokens import reset_voice_session_tokens_for_tests
    from services.voice_daily_budget import _reset_for_tests as reset_budget
    from limiter import limiter

    for name in list(os.environ):
        if name.startswith("VOICE_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(api_settings_mod, "OPERATOR_KEYS_ENV_PATH", tmp_path / "operator_keys.env")
    monkeypatch.setenv("SB_DATA_DIR", str(tmp_path / "data"))
    config_mod.get_settings.cache_clear()
    _sessions.clear()
    reset_voice_session_tokens_for_tests()
    reset_budget()
    yield monkeypatch
    config_mod.get_settings.cache_clear()
    _sessions.clear()
    reset_voice_session_tokens_for_tests()
    reset_budget()
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
                async with AsyncClient(transport=self._transport, base_url=self._base, headers={"X-Admin-Key": "audit-operator-key-" + "x" * 32}) as ac:
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
# Row 1 — opt-in gate uniformity across every sensitive surface
# ---------------------------------------------------------------------------


class TestOptInUniformity:
    def test_every_sensitive_surface_refuses_while_opt_in_incomplete(self, loopback):
        """No voice surface leaks billable functionality pre-opt-in. Session
        and chat answer 403 (§4.3 canonical refusal); the U5/U6 surfaces
        answer 409 ``voice_disabled`` — each with honest reasons."""
        expectations = [
            ("POST", "/api/voice/session", 403, {}),
            ("POST", "/api/voice/chat", 403, {"text": "hello"}),
            ("POST", "/api/voice/hud-summary", 409, {}),
            ("POST", "/api/voice/turn", 409, {"text": "hello"}),
            ("POST", "/api/voice/interrogate", 409, {"question": "why this alert?"}),
        ]
        for method, url, expected, payload in expectations:
            response = loopback.post(url, json=payload) if method == "POST" else loopback.get(url)
            assert response.status_code == expected, f"{url}: {response.status_code} != {expected}"
            body = response.json()
            assert body.get("error") in ("opt_in_required", "voice_disabled"), url
            assert body.get("reasons"), f"{url} must carry human-readable refusal reasons"

    def test_status_stays_200_and_explains_the_refusal(self, loopback):
        response = loopback.get("/api/voice/status")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["effectiveEnable"] is False
        assert body["reasons"], "status is the surface that explains why voice is off"


# ---------------------------------------------------------------------------
# Row 2 — deterministic operator journey (zero model, zero outbound)
# ---------------------------------------------------------------------------


class TestDeterministicJourney:
    def test_full_journey_zero_model(self, loopback, monkeypatch):
        _enable(monkeypatch)
        # Status: enabled but provider unresolved — honest degradedReason.
        status = loopback.get("/api/voice/status").json()
        assert status["effectiveEnable"] is True
        assert status["provider"]["resolved"] is None
        assert status["degradedReason"], "unresolved provider must carry verbatim reason"

        # Tools manifest reachable (U3 mount inside U2's router).
        tools = loopback.get("/api/voice/tools")
        assert tools.status_code == 200
        tool_names = {t.get("name") for t in tools.json().get("tools", [])}
        assert tool_names, "manifest must not be empty"
        assert "what_changed" in tool_names

        # Stateless server-tool execute works with NO model (deterministic).
        executed = loopback.post("/api/voice/tool", json={"tool": "what_changed", "args": {}})
        assert executed.status_code == 200
        assert isinstance(executed.json(), dict)

        # Model-dialing surfaces degrade with 503 chat_unconfigured.
        assert loopback.post("/api/voice/turn", json={"text": "fly to Kyiv"}).status_code == 503
        # Minimal VALID sb.grounding.v1: schema + view + layers (§2.4 validator).
        valid_snapshot = {"schema": "sb.grounding.v1", "view": {}, "layers": {}}
        assert loopback.post("/api/voice/hud-summary", json={"snapshot": valid_snapshot}).status_code == 503

        # Interrogate with a real question but no model: either the target
        # resolver refuses first (400 no_target) or the chat dial degrades
        # (503) — both are honest; a 4xx validation error is NOT acceptable
        # here because the question is well-formed.
        interrogate = loopback.post("/api/voice/interrogate", json={"question": "why this alert?"})
        assert interrogate.status_code in (400, 503)
        if interrogate.status_code == 400:
            assert interrogate.json().get("error") == "no_target"


# ---------------------------------------------------------------------------
# Row 3 — one persisted ledger latches EVERY billable surface
# ---------------------------------------------------------------------------


class TestCrossSurfaceBudgetLatch:
    def test_crossed_daily_budget_429s_all_billable_surfaces(self, loopback, monkeypatch):
        _enable(monkeypatch, VOICE_OPENAI_API_KEY="sk-test", VOICE_DAILY_BUDGET_USD="0.01")

        from services.voice_daily_budget import record_response

        record_response(usd=0.02)  # 2x the daily budget, persisted to the ledger

        # Session (Gate 3) — carries Retry-After.
        session = loopback.post("/api/voice/session", json={"tier": "standard"})
        assert session.status_code == 429
        assert session.json()["error"] == "budget"
        assert "retry-after" in {k.lower() for k in session.headers}

        # The U5/U6 chat-dialing surfaces share the same latched cap.
        valid_snapshot = {"schema": "sb.grounding.v1", "view": {}, "layers": {}}
        for url, payload in (
            ("/api/voice/turn", {"text": "fly to Kyiv"}),
            ("/api/voice/hud-summary", {"snapshot": valid_snapshot}),
            ("/api/voice/interrogate", {"question": "why this alert?"}),
        ):
            response = loopback.post(url, json=payload)
            assert response.status_code == 429, f"{url}: {response.status_code}"
            assert response.json()["error"] == "budget", url

        # Status surfaces the exhausted state honestly.
        spend = loopback.get("/api/voice/status").json()["dailySpend"]
        assert spend["remainingUsd"] == 0


# ---------------------------------------------------------------------------
# Row 4 — status never-500 contract under a hostile store
# ---------------------------------------------------------------------------


class TestStatusNeverFails:
    def test_status_survives_exploding_spend_view(self, loopback, monkeypatch):
        _enable(monkeypatch)

        def _explode(*a, **kw):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr("services.voice_broker.daily_spend_view", _explode)
        response = loopback.get("/api/voice/status")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert "status unavailable" in " ".join(body.get("reasons", [])) or "status unavailable" in str(body.get("degradedReason"))


# ---------------------------------------------------------------------------
# Row 5 — kill-switch lifecycle
# ---------------------------------------------------------------------------


class TestKillSwitchLifecycle:
    def test_mint_then_delete_then_404(self, loopback, monkeypatch):
        _enable(monkeypatch, VOICE_OPENAI_API_KEY="sk-test")
        created = loopback.post("/api/voice/session", json={"tier": "standard"})
        assert created.status_code == 201
        session_id = created.json()["sessionId"]

        killed = loopback.delete(f"/api/voice/session/{session_id}")
        assert killed.status_code == 200
        assert killed.json()["ok"] is True

        repeat = loopback.delete(f"/api/voice/session/{session_id}")
        assert repeat.status_code == 404


# ---------------------------------------------------------------------------
# Row 6 — watchdog producer hook (§3.8 seam)
# ---------------------------------------------------------------------------


class TestWatchdogProducerHook:
    def test_broadcast_to_agents_fans_alerts_into_voice_tap(self, monkeypatch):
        """The U6 producer hook in ai_intel.broadcast_to_agents forwards
        type:alert payloads to publish_watchdog_alert — voice never imports
        the watchdog, the watchdog never learns about voice."""
        import routers.ai_intel as ai_intel

        seen: list = []
        monkeypatch.setattr(
            "services.voice_broker.publish_watchdog_alert",
            lambda alert: seen.append(alert) or 0,
        )

        asyncio.run(ai_intel.broadcast_to_agents({"type": "alert", "alert": {"kind": "geofence", "id": "a1"}}))
        assert seen == [{"kind": "geofence", "id": "a1"}]

        # Non-alert broadcasts must NOT touch the voice tap.
        asyncio.run(ai_intel.broadcast_to_agents({"type": "task", "payload": {}}))
        assert len(seen) == 1

    def test_publish_with_no_active_relays_is_a_safe_noop(self):
        from services.voice_broker import publish_watchdog_alert

        assert publish_watchdog_alert({"kind": "geofence"}) == 0


# ---------------------------------------------------------------------------
# Row 7 — MESH_ONLY lean-mode guard stays wired at both ends
# ---------------------------------------------------------------------------


class TestMeshOnlyGuardPresent:
    def test_router_and_main_keep_the_lean_mode_defenses(self):
        router_src = (Path(__file__).resolve().parent.parent / "routers" / "voice.py").read_text(encoding="utf-8")
        main_src = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        # routers/voice.py: canonical MESH_ONLY import guard (§1.5).
        assert "MESH_ONLY" in router_src, "voice router lost its lean-mode import guard"
        # main.py: stubbed router branch + optional loader + include.
        assert "voice_router" in main_src, "main.py lost the voice router wiring"
