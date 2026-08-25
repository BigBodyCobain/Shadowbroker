"""Voice-agent U6 — §3.8 watchdog alert context events.

Voice CONSUMES already-broadcast alert payloads as read-only
``{"type":"watchdog_alert","alert":{…}}`` SB→client frames; it never owns an
evaluation loop and never imports ``services.openclaw_watchdog`` from
``routers.voice`` / ``services.voice_tool_registry`` / ``services.voice_broker``
(CI guard #20). These tests pin the broker-side tap, the relay pump, and the
broadcast_to_agents producer hook.
"""

from __future__ import annotations

import asyncio
import json

import pytest


class _FakeClientWs:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append("<binary>")

    async def receive(self):  # pragma: no cover - pump drives termination below
        await asyncio.sleep(3600)


def _make_state():
    from services.voice_broker import VoiceSession, _RelayState

    session = VoiceSession(
        session_id="watch-test",
        tier="standard",
        requested_tier="standard",
        model_id="gpt-realtime",
        provider="openai_realtime",
        limits={},
        tokens_per_sec=50,
        max_concurrent=1,
    )
    return _RelayState(session), session


class TestWatchdogAlertTap:
    def test_publish_fans_out_to_registered_relays_only(self):
        from services.voice_broker import _WatchdogAlertTap, _relay_taps, _relay_taps_lock

        tap_a, tap_b = _WatchdogAlertTap(), _WatchdogAlertTap()
        with _relay_taps_lock:
            _relay_taps.add(tap_a)
            _relay_taps.add(tap_b)
        try:
            alert = {"alert": "geofence crossed", "watch_id": "w1"}
            assert tap_a.publish(alert) and tap_b.publish(alert)
            drained = tap_a.drain()
            assert drained == [alert]
            assert tap_a.drain() == [], "drain is destructive — each alert appears exactly once"
        finally:
            with _relay_taps_lock:
                _relay_taps.discard(tap_a)
                _relay_taps.discard(tap_b)

    def test_bounded_tap_drops_oldest(self):
        from services.voice_broker import _WATCHDOG_ALERT_TAP_MAX, _WatchdogAlertTap

        tap = _WatchdogAlertTap()
        for i in range(_WATCHDOG_ALERT_TAP_MAX + 4):
            tap.publish({"seq": i})
        drained = tap.drain()
        assert len(drained) == _WATCHDOG_ALERT_TAP_MAX
        assert drained[0]["seq"] == 4 and drained[-1]["seq"] == _WATCHDOG_ALERT_TAP_MAX + 3

    def test_publish_watchdog_alert_normalizes_non_dict_payload(self):
        from services.voice_broker import _WatchdogAlertTap, _relay_taps, _relay_taps_lock

        tap = _WatchdogAlertTap()
        with _relay_taps_lock:
            _relay_taps.add(tap)
        try:
            from services.voice_broker import publish_watchdog_alert

            assert publish_watchdog_alert("raw alert text") == 1
            assert tap.drain()[0] == {"alert": "raw alert text"}
        finally:
            with _relay_taps_lock:
                _relay_taps.discard(tap)


class TestRelayPump:
    def test_alert_frames_reach_the_client_exactly_once(self):
        from services.voice_broker import (
            _WatchdogAlertTap,
            _pump_watchdog_alerts,
            _TERMINATION_POLL_SECONDS,
        )

        state, session = _make_state()
        client = _FakeClientWs()
        tap = _WatchdogAlertTap()

        async def scenario():
            tap.publish({"alert": "geofence crossed", "watch_id": "w1"})
            task = asyncio.ensure_future(_pump_watchdog_alerts(client, state, tap))
            # Give the pump one poll cycle, then end the session.
            await asyncio.sleep(_TERMINATION_POLL_SECONDS + 0.05)
            session.closed = True
            await asyncio.wait_for(task, timeout=5)

        asyncio.new_event_loop().run_until_complete(scenario())
        frames = [json.loads(text) for text in client.sent]
        alerts = [frame for frame in frames if frame.get("type") == "watchdog_alert"]
        assert alerts == [{"type": "watchdog_alert", "alert": {"alert": "geofence crossed", "watch_id": "w1"}}]

    def test_no_alerts_means_no_frames(self):
        from services.voice_broker import _WatchdogAlertTap, _pump_watchdog_alerts

        state, session = _make_state()
        client = _FakeClientWs()
        tap = _WatchdogAlertTap()

        async def scenario():
            task = asyncio.ensure_future(_pump_watchdog_alerts(client, state, tap))
            await asyncio.sleep(0.05)
            session.closed = True
            await asyncio.wait_for(task, timeout=5)

        asyncio.new_event_loop().run_until_complete(scenario())
        assert client.sent == []


class TestBroadcastProducerHook:
    def test_broadcast_to_agents_feeds_voice_subscribers(self):
        """The §3.8 consumption point: ai_intel.broadcast_to_agents forwards
        alert-type payloads into the voice broker's read-only tap."""
        from routers.ai_intel import broadcast_to_agents
        from services.voice_broker import _WatchdogAlertTap, _relay_taps, _relay_taps_lock

        tap = _WatchdogAlertTap()
        with _relay_taps_lock:
            _relay_taps.add(tap)
        try:
            alert = {"type": "alert", "alert": {"alert": "market threshold", "data": {}}}
            asyncio.new_event_loop().run_until_complete(broadcast_to_agents(dict(alert)))
            drained = tap.drain()
            assert drained == [alert["alert"]]
        finally:
            with _relay_taps_lock:
                _relay_taps.discard(tap)

    def test_non_alert_messages_do_not_touch_voice(self):
        from routers.ai_intel import broadcast_to_agents
        from services.voice_broker import _WatchdogAlertTap, _relay_taps, _relay_taps_lock

        tap = _WatchdogAlertTap()
        with _relay_taps_lock:
            _relay_taps.add(tap)
        try:
            asyncio.new_event_loop().run_until_complete(
                broadcast_to_agents({"type": "ping", "detail": "hello"})
            )
            assert tap.drain() == []
        finally:
            with _relay_taps_lock:
                _relay_taps.discard(tap)


class TestDecouplingGuard:
    def test_voice_modules_never_import_the_watchdog(self):
        """CI guard #20 restated at the unit level (the topology suite walks
        source too; this keeps the runtime import graph honest)."""
        import sys

        offenders = [
            name
            for name in ("routers.voice", "services.voice_tool_registry", "services.voice_broker")
            if name in sys.modules
            and "openclaw_watchdog" in getattr(sys.modules[name], "__dict__", {})
        ]
        assert not offenders
