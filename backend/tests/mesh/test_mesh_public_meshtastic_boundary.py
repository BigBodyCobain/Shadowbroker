import asyncio
import time
from collections import deque
from types import SimpleNamespace


class _DummyBreaker:
    def check_and_record(self, _priority):
        return True, "ok"


class _FakeMeshtasticTransport:
    NAME = "meshtastic"

    def __init__(self, can_reach: bool = True, send_ok: bool = True):
        self._can_reach = can_reach
        self._send_ok = send_ok
        self.sent = []

    def can_reach(self, _envelope):
        return self._can_reach

    def send(self, envelope, _credentials):
        from services.mesh.mesh_router import TransportResult

        self.sent.append(envelope)
        return TransportResult(self._send_ok, self.NAME, "sent")


class _FakeMeshRouter:
    def __init__(self, meshtastic):
        self.meshtastic = meshtastic
        self.breakers = {"meshtastic": _DummyBreaker()}
        self.route_called = False

    def route(self, _envelope, _credentials):
        self.route_called = True
        return []


def _valid_body(**overrides):
    body = {
        "destination": "!a0cc7a80",
        "message": "hello mesh",
        "sender_id": "!sb_sender",
        "node_id": "!sb_sender",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "signature": "sig",
        "sequence": 1,
        "protocol_version": "1",
        "channel": "LongFast",
        "priority": "normal",
        "ephemeral": False,
        "transport_lock": "meshtastic",
        "credentials": {"mesh_region": "US"},
    }
    body.update(overrides)
    return body


def test_meshtastic_transport_lock_stays_on_public_direct_path(monkeypatch):
    import main
    from services.mesh import mesh_router as mesh_router_mod
    from services.sigint_bridge import sigint_grid
    from httpx import ASGITransport, AsyncClient

    fake_meshtastic = _FakeMeshtasticTransport(can_reach=True, send_ok=True)
    fake_router = _FakeMeshRouter(fake_meshtastic)
    fake_bridge = SimpleNamespace(messages=deque(maxlen=10))

    monkeypatch.setattr(main, "_verify_signed_event", lambda **_: (True, "ok"))
    monkeypatch.setattr(main, "_preflight_signed_event_integrity", lambda **_: (True, "ok"))
    monkeypatch.setattr(main, "_check_throttle", lambda *_: (True, "ok"))
    monkeypatch.setattr(mesh_router_mod, "mesh_router", fake_router)
    monkeypatch.setattr(sigint_grid, "mesh", fake_bridge)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post("/api/mesh/send", json=_valid_body())
            return response.json()

    result = asyncio.run(_run())

    assert result["ok"] is True
    assert result["routed_via"] == "meshtastic"
    assert "public node-targeted path" in result["route_reason"]
    assert fake_router.route_called is False
    assert len(fake_meshtastic.sent) == 1
    assert fake_meshtastic.sent[0].destination == "!a0cc7a80"
    assert fake_bridge.messages[0]["from"] == "!0779e8b8"


def test_meshtastic_transport_lock_does_not_fallback_when_unreachable(monkeypatch):
    import main
    from services.mesh import mesh_router as mesh_router_mod
    from httpx import ASGITransport, AsyncClient

    fake_meshtastic = _FakeMeshtasticTransport(can_reach=False, send_ok=False)
    fake_router = _FakeMeshRouter(fake_meshtastic)

    monkeypatch.setattr(main, "_verify_signed_event", lambda **_: (True, "ok"))
    monkeypatch.setattr(main, "_preflight_signed_event_integrity", lambda **_: (True, "ok"))
    monkeypatch.setattr(main, "_check_throttle", lambda *_: (True, "ok"))
    monkeypatch.setattr(mesh_router_mod, "mesh_router", fake_router)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post("/api/mesh/send", json=_valid_body(message="x" * 10))
            return response.json()

    result = asyncio.run(_run())

    assert result["ok"] is False
    assert result["routed_via"] == ""
    assert fake_router.route_called is False
    assert fake_meshtastic.sent == []
    assert result["results"] == [
        {
            "ok": False,
            "transport": "meshtastic",
            "detail": "Message exceeds Meshtastic payload limit",
        }
    ]


def test_meshtastic_transport_lock_allows_two_messages_per_minute(monkeypatch):
    import main

    node_id = "!sb_meshrate"
    now = time.time()
    main._node_throttle[node_id] = {
        "last_send": now - 31,
        "daily_count": 0,
        "daily_reset": now,
        "first_seen": now,
    }

    ok_first, _reason_first = main._check_throttle(node_id, "normal", "meshtastic")
    ok_second, reason_second = main._check_throttle(node_id, "normal", "meshtastic")

    assert ok_first is True
    assert ok_second is False
    assert "1 message per 30s" in reason_second


def test_private_trust_tier_skips_public_transports():
    from services.mesh.mesh_router import MeshEnvelope, MeshRouter, Priority, TransportResult

    class _FakeTransport:
        def __init__(self, name):
            self.NAME = name
            self.sent = []

        def can_reach(self, _envelope):
            return True

        def send(self, envelope, _credentials):
            self.sent.append(envelope)
            return TransportResult(True, self.NAME, "sent")

    router = MeshRouter()
    router.aprs = _FakeTransport("aprs")
    router.meshtastic = _FakeTransport("meshtastic")
    router.internet = _FakeTransport("internet")
    router.transports = [router.aprs, router.meshtastic, router.internet]

    envelope = MeshEnvelope(
        sender_id="!sb_sender",
        destination="broadcast",
        priority=Priority.NORMAL,
        payload="private payload",
        trust_tier="private_strong",
    )

    results = router.route(envelope, {})

    assert [r.transport for r in results] == ["policy"]
    assert router.aprs.sent == []
    assert router.meshtastic.sent == []
    assert len(router.internet.sent) == 0


def test_private_route_recognizes_tor_arti_and_falls_back_to_internet():
    from services.mesh.mesh_router import MeshEnvelope, MeshRouter, Priority, TransportResult

    class _FakeTransport:
        def __init__(self, name, ok=True):
            self.NAME = name
            self.ok = ok
            self.sent = []

        def can_reach(self, _envelope):
            return True

        def send(self, envelope, _credentials):
            self.sent.append(envelope)
            return TransportResult(self.ok, self.NAME, "sent" if self.ok else "stub")

    router = MeshRouter()
    router.aprs = _FakeTransport("aprs")
    router.meshtastic = _FakeTransport("meshtastic")
    router.tor_arti = _FakeTransport("tor_arti", ok=False)
    router.internet = _FakeTransport("internet", ok=True)
    router.transports = [router.aprs, router.meshtastic, router.tor_arti, router.internet]

    envelope = MeshEnvelope(
        sender_id="!sb_sender",
        destination="broadcast",
        priority=Priority.NORMAL,
        payload="private payload",
        trust_tier="private_strong",
    )

    results = router.route(envelope, {})

    assert [r.transport for r in results] == ["tor_arti", "policy"]
    assert router.aprs.sent == []
    assert router.meshtastic.sent == []
    assert len(router.tor_arti.sent) == 1
    assert len(router.internet.sent) == 0


def test_private_tier_blocks_meshtastic_transport_lock(monkeypatch):
    """C-2 fix: transport_lock=meshtastic must be rejected when trust_tier is private."""
    import main
    from services.mesh import mesh_router as mesh_router_mod
    from services import wormhole_supervisor
    from httpx import ASGITransport, AsyncClient

    fake_meshtastic = _FakeMeshtasticTransport(can_reach=True, send_ok=True)
    fake_router = _FakeMeshRouter(fake_meshtastic)

    monkeypatch.setattr(main, "_verify_signed_event", lambda **_: (True, "ok"))
    monkeypatch.setattr(main, "_preflight_signed_event_integrity", lambda **_: (True, "ok"))
    monkeypatch.setattr(main, "_check_throttle", lambda *_: (True, "ok"))
    monkeypatch.setattr(mesh_router_mod, "mesh_router", fake_router)
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post("/api/mesh/send", json=_valid_body())
            return response.json()

    result = asyncio.run(_run())

    assert result["ok"] is False
    assert "Private-tier content cannot be sent over Meshtastic" in result["results"][0]["detail"]
    assert fake_meshtastic.sent == []
    assert fake_router.route_called is False


def test_envelope_trust_tier_set_from_wormhole_state(monkeypatch):
    """C-1 fix: MeshEnvelope.trust_tier must reflect actual Wormhole transport tier."""
    import main
    from services.mesh import mesh_router as mesh_router_mod
    from services import wormhole_supervisor
    from services.sigint_bridge import sigint_grid
    from httpx import ASGITransport, AsyncClient

    captured_envelopes = []

    class _CapturingRouter:
        def __init__(self):
            self.meshtastic = _FakeMeshtasticTransport(can_reach=True, send_ok=True)
            self.breakers = {"meshtastic": _DummyBreaker()}

        def route(self, envelope, _credentials):
            from services.mesh.mesh_router import TransportResult

            captured_envelopes.append(envelope)
            return [TransportResult(True, "internet", "sent")]

    fake_router = _CapturingRouter()
    fake_bridge = SimpleNamespace(messages=deque(maxlen=10))

    monkeypatch.setattr(main, "_verify_signed_event", lambda **_: (True, "ok"))
    monkeypatch.setattr(main, "_preflight_signed_event_integrity", lambda **_: (True, "ok"))
    monkeypatch.setattr(main, "_check_throttle", lambda *_: (True, "ok"))
    monkeypatch.setattr(mesh_router_mod, "mesh_router", fake_router)
    monkeypatch.setattr(sigint_grid, "mesh", fake_bridge)
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")

    body = _valid_body()
    del body["transport_lock"]  # no lock — use normal routing

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post("/api/mesh/send", json=body)
            return response.json()

    result = asyncio.run(_run())

    assert result["ok"] is True
    assert len(captured_envelopes) == 1
    assert captured_envelopes[0].trust_tier == "private_transitional"
