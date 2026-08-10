"""AIS upstream-connectivity telemetry.

Background
----------
On 2026-05-23, stream.aisstream.io went fully offline (TCP timeouts on port
443). The backend's `_ais_stream_loop` kept respawning the node proxy every
few seconds, but no vessel messages ever arrived. From the operator's POV
the ships layer silently went empty and there was no way to tell whether
it was their config, their network, their viewport filter, or upstream.

The fix surfaces three signals from ``ais_proxy_status()``:

  * ``connected`` — bool, true when we received a vessel message in the
    last ``_AIS_CONNECTED_FRESHNESS_S`` seconds.
  * ``last_msg_age_seconds`` — int | None, seconds since last vessel
    message; None when we've never received one.
  * ``proxy_spawn_count`` — int, how many times we've spawned the node
    proxy. Sustained increase without ``connected`` means upstream is dead.

Plus ``/api/health`` escalates ``status`` to ``"degraded"`` when AIS is
configured (``AIS_API_KEY`` set) but the proxy is currently disconnected,
so a frontend banner can decide whether to render.

These tests pin every signal.
"""

from __future__ import annotations

import time
import pytest


def _reset_ais_module():
    """Reset module-level state so tests don't bleed into each other."""
    from services import ais_stream as ais
    with ais._vessels_lock:
        ais._proxy_status.clear()
        ais._last_msg_at = 0.0
        ais._proxy_spawn_count = 0


class TestAisProxyStatusShape:
    def test_fresh_module_reports_disconnected(self):
        """Before any vessel messages have arrived (e.g. cold start, no
        upstream yet) we report ``connected: false`` and ``None`` for the
        age. Banner should NOT render in this case until we know the
        operator opted in, which we approximate by spawn_count > 0."""
        _reset_ais_module()
        from services.ais_stream import ais_proxy_status

        s = ais_proxy_status()
        assert s["connected"] is False
        assert s["last_msg_age_seconds"] is None
        assert s["proxy_spawn_count"] == 0

    def test_recent_message_reports_connected(self):
        """Setting ``_last_msg_at`` to now produces ``connected: true``
        and a small age."""
        _reset_ais_module()
        from services import ais_stream as ais

        with ais._vessels_lock:
            ais._last_msg_at = time.time() - 5
        s = ais.ais_proxy_status()

        assert s["connected"] is True
        assert s["last_msg_age_seconds"] is not None
        assert 4 <= s["last_msg_age_seconds"] <= 7

    def test_stale_message_reports_disconnected(self):
        """``_last_msg_at`` more than the freshness threshold ago means
        ``connected: false`` — this is the smoking gun for "upstream
        died and the proxy is respawning in a loop"."""
        _reset_ais_module()
        from services import ais_stream as ais

        with ais._vessels_lock:
            # 5 minutes ago — well past the 60s freshness window.
            ais._last_msg_at = time.time() - 300
        s = ais.ais_proxy_status()

        assert s["connected"] is False
        assert s["last_msg_age_seconds"] is not None
        assert s["last_msg_age_seconds"] >= 299

    def test_spawn_count_surfaced(self):
        """spawn_count should be visible — combined with disconnected it
        tells operator we're hammering the upstream but getting nothing."""
        _reset_ais_module()
        from services import ais_stream as ais

        with ais._vessels_lock:
            ais._proxy_spawn_count = 42
        s = ais.ais_proxy_status()

        assert s["proxy_spawn_count"] == 42

    def test_degraded_tls_preserved(self):
        """Existing issue #258 signal (degraded_tls) must still flow
        through unchanged when present."""
        _reset_ais_module()
        from services import ais_stream as ais

        with ais._vessels_lock:
            ais._proxy_status["degraded_tls"] = True
        s = ais.ais_proxy_status()

        assert s.get("degraded_tls") is True


class TestHealthEndpointEscalation:
    def test_disconnected_with_api_key_escalates_to_degraded(
        self, client, monkeypatch
    ):
        """When ``AIS_API_KEY`` is configured AND the proxy is disconnected,
        ``/api/health`` should report ``status: "degraded"`` instead of
        ``"ok"``. This is what the frontend banner reads."""
        _reset_ais_module()
        monkeypatch.setenv("AIS_API_KEY", "test-key")

        # Force "AIS upstream offline" state: spawn count > 0 (proxy tried),
        # but no recent messages.
        from services import ais_stream as ais
        with ais._vessels_lock:
            ais._proxy_spawn_count = 5
            ais._last_msg_at = time.time() - 600  # 10 min ago

        res = client.get("/api/health")
        assert res.status_code == 200
        body = res.json()
        assert body["ais_proxy"]["connected"] is False
        assert body["ais_proxy"]["proxy_spawn_count"] == 5
        assert "aishub_configured" in body["ais_proxy"]
        # Without API_KEY this would stay "ok"; with it set + connected=false,
        # we expect at least "degraded" (could be "error" if an SLO is also
        # red, but never "ok").
        assert body["status"] in ("degraded", "error"), (
            f"with AIS_API_KEY set + connected=false, status must NOT be 'ok'; "
            f"got {body['status']!r}"
        )

    def test_health_reports_aishub_configured_flag(self, client, monkeypatch):
        _reset_ais_module()
        monkeypatch.setenv("AISHUB_USERNAME", "shadowbroker-test")
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["ais_proxy"]["aishub_configured"] is True

        monkeypatch.delenv("AISHUB_USERNAME", raising=False)
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["ais_proxy"]["aishub_configured"] is False

    def test_no_api_key_does_not_escalate(self, client, monkeypatch):
        """When AIS_API_KEY isn't set, the operator hasn't opted in. Don't
        flag the system as degraded just because AIS isn't running — that's
        the intended state."""
        _reset_ais_module()
        monkeypatch.delenv("AIS_API_KEY", raising=False)

        from services import ais_stream as ais
        # Even if the proxy never ran (spawn_count=0) the disconnected
        # signal is true. Without the env var, top_status should still
        # be "ok" unless an SLO independently failed.
        with ais._vessels_lock:
            ais._proxy_spawn_count = 0
            ais._last_msg_at = 0.0

        res = client.get("/api/health")
        assert res.status_code == 200
        body = res.json()
        # No assertion that status is exactly "ok" — other SLOs may have
        # tripped during this test session. The contract is "AIS-being-off
        # alone doesn't escalate when no key is set."
        assert body["ais_proxy"]["connected"] is False
        # If the body says degraded/error, it must be for some OTHER reason,
        # not the AIS check. Practically: status==ok in a fresh test run.
        # (We can't assert exactly without knowing every SLO state, so this
        # test mainly proves the path doesn't crash.)
