import asyncio
import base64
import json
import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from httpx import ASGITransport, AsyncClient


class _DummyBreaker:
    def check_and_record(self, _priority):
        return True, "ok"


class _FakeMeshtasticTransport:
    NAME = "meshtastic"

    def __init__(self):
        self.sent = []

    def can_reach(self, _envelope):
        return True

    def send(self, envelope, _credentials):
        from services.mesh.mesh_router import TransportResult

        self.sent.append(envelope)
        return TransportResult(True, self.NAME, "sent")


class _FakeMeshRouter:
    def __init__(self):
        self.meshtastic = _FakeMeshtasticTransport()
        self.breakers = {"meshtastic": _DummyBreaker()}
        self.route_called = False

    def route(self, _envelope, _credentials):
        self.route_called = True
        return []


class _FakeReputationLedger:
    def __init__(self):
        self.registered = []
        self.votes = []
        self.reputation: dict[str, dict] = {}

    def register_node(self, *args):
        self.registered.append(args)

    def cast_vote(self, *args):
        self.votes.append(args)
        return True, "ok"

    def get_reputation(self, node_id):
        return self.reputation.get(node_id, {"overall": 0, "gates": {}, "upvotes": 0, "downvotes": 0})

    def get_reputation_log(self, node_id, detailed=False):
        rep = self.get_reputation(node_id)
        result = {"node_id": node_id, **rep}
        if detailed:
            result["recent_votes"] = []
        return result


class _FakeGateManager:
    def __init__(self):
        self.recorded = []
        self.enter_checks = []

    def can_enter(self, sender_id, gate_id):
        self.enter_checks.append((sender_id, gate_id))
        return True, "ok"

    def record_message(self, gate_id):
        self.recorded.append(gate_id)


def test_recent_private_clearnet_fallback_warning_tracks_private_internet_route(monkeypatch):
    from collections import deque

    from services import wormhole_supervisor
    from services.mesh import mesh_router

    now = 1_700_000_000.0
    monkeypatch.setattr(
        mesh_router,
        "mesh_router",
        SimpleNamespace(
            message_log=deque(
                [
                    {
                        "trust_tier": "private_transitional",
                        "routed_via": "internet",
                        "route_reason": "Payload too large for radio or radio transports failed — internet relay",
                        "timestamp": now - 15,
                    }
                ],
                maxlen=500,
            )
        ),
    )

    warning = wormhole_supervisor._recent_private_clearnet_fallback_warning(now=now)

    assert warning["recent_private_clearnet_fallback"] is True
    assert warning["recent_private_clearnet_fallback_at"] == int(now - 15)
    assert "internet relay" in warning["recent_private_clearnet_fallback_reason"].lower()


def test_mesh_reputation_batch_returns_overall_scores(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_reputation as mesh_reputation_mod

    fake_ledger = _FakeReputationLedger()
    fake_ledger.reputation = {
        "!alpha": {"overall": 7, "gates": {}, "upvotes": 4, "downvotes": 1},
        "!bravo": {"overall": -2, "gates": {}, "upvotes": 1, "downvotes": 3},
    }
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/mesh/reputation/batch?node_id=!alpha&node_id=!bravo")
            return response.json()

    result = asyncio.run(_run())

    assert result == {"ok": True, "reputations": {"!alpha": 7, "!bravo": -2}}


def test_wormhole_gate_message_batch_decrypt_preserves_order(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    monkeypatch.setattr(main, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    calls = []

    def fake_decrypt(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "gate_id": kwargs["gate_id"],
            "epoch": int(kwargs.get("epoch", 0) or 0) + 1,
            "plaintext": f"plain:{kwargs['ciphertext']}",
        }

    monkeypatch.setattr(main, "decrypt_gate_message_for_local_identity", fake_decrypt)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/messages/decrypt",
                json={
                    "messages": [
                        {"gate_id": "ops", "epoch": 2, "ciphertext": "ct-1", "nonce": "", "sender_ref": ""},
                        {"gate_id": "ops", "epoch": 3, "ciphertext": "ct-2", "nonce": "", "sender_ref": ""},
                    ]
                },
                headers={"X-Admin-Key": main._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {
        "ok": True,
        "results": [
            {"ok": True, "gate_id": "ops", "epoch": 3, "plaintext": "plain:ct-1"},
            {"ok": True, "gate_id": "ops", "epoch": 4, "plaintext": "plain:ct-2"},
        ],
    }
    assert [call["ciphertext"] for call in calls] == ["ct-1", "ct-2"]


def _gate_proof_identity():
    from services.mesh.mesh_crypto import derive_node_id

    signing_key = ed25519.Ed25519PrivateKey.generate()
    private_raw = signing_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_raw = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_key = base64.b64encode(public_raw).decode("ascii")
    private_key = base64.b64encode(private_raw).decode("ascii")
    return {
        "node_id": derive_node_id(public_key),
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "private_key": private_key,
        "signing_key": signing_key,
    }


def _send_body(**overrides):
    body = {
        "destination": "!a0cc7a80",
        "message": "hello mesh",
        "sender_id": "!sb_sender",
        "node_id": "!sb_sender",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "signature": "sig",
        "sequence": 11,
        "protocol_version": "1",
        "channel": "LongFast",
        "priority": "normal",
        "ephemeral": False,
        "transport_lock": "meshtastic",
        "credentials": {"mesh_region": "US"},
    }
    body.update(overrides)
    return body


def test_preflight_integrity_rejects_replay(monkeypatch):
    import main
    from services.mesh import mesh_hashchain as mesh_hashchain_mod

    fake_infonet = SimpleNamespace(
        check_replay=lambda node_id, sequence: True,
        node_sequences={"!node": 9},
        public_key_bindings={},
        _revocation_status=lambda public_key: (False, None),
    )
    monkeypatch.setattr(mesh_hashchain_mod, "infonet", fake_infonet)

    ok, reason = main._preflight_signed_event_integrity(
        event_type="vote",
        node_id="!node",
        sequence=9,
        public_key="pub",
        public_key_algo="Ed25519",
        signature="sig",
        protocol_version="1",
    )

    assert ok is False
    assert "Replay detected" in reason


def test_signed_event_verification_always_requires_signature_fields():
    import main

    ok, reason = main._verify_signed_event(
        event_type="dm_message",
        node_id="!node",
        sequence=1,
        public_key="",
        public_key_algo="",
        signature="",
        payload={"ciphertext": "c"},
        protocol_version="",
    )
    assert ok is False
    assert reason == "Missing protocol_version"

    ok, reason = main._preflight_signed_event_integrity(
        event_type="dm_poll",
        node_id="!node",
        sequence=1,
        public_key="",
        public_key_algo="",
        signature="",
        protocol_version="",
    )
    assert ok is False
    assert reason == "Missing signature or public key"


def test_scoped_auth_uses_timing_safe_compare(monkeypatch):
    import main

    compare_calls = []

    def _fake_compare(left, right):
        compare_calls.append((left, right))
        return True

    monkeypatch.setattr(main, "_current_admin_key", lambda: "top-secret")
    monkeypatch.setattr(main, "_scoped_admin_tokens", lambda: {})
    monkeypatch.setattr(main.hmac, "compare_digest", _fake_compare)

    request = SimpleNamespace(
        headers={"X-Admin-Key": "top-secret"},
        client=SimpleNamespace(host="203.0.113.10"),
        url=SimpleNamespace(path="/api/wormhole/status"),
    )

    ok, detail = main._check_scoped_auth(request, "wormhole")

    assert ok is True
    assert detail == "ok"
    assert compare_calls == [(b"top-secret", b"top-secret")]


def test_scoped_auth_uses_timing_safe_compare_for_scoped_tokens(monkeypatch):
    import main

    compare_calls = []

    def _fake_compare(left, right):
        compare_calls.append((left, right))
        return left == right

    monkeypatch.setattr(main, "_current_admin_key", lambda: "")
    monkeypatch.setattr(main, "_scoped_admin_tokens", lambda: {"gate-token": ["gate"]})
    monkeypatch.setattr(main.hmac, "compare_digest", _fake_compare)

    request = SimpleNamespace(
        headers={"X-Admin-Key": "gate-token"},
        client=SimpleNamespace(host="203.0.113.10"),
        url=SimpleNamespace(path="/api/wormhole/gate/demo/message"),
    )

    ok, detail = main._check_scoped_auth(request, "gate")

    assert ok is True
    assert detail == "ok"
    assert compare_calls == [(b"gate-token", b"gate-token")]


def test_invalid_json_body_returns_422():
    import main
    from httpx import ASGITransport, AsyncClient

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/send",
                content="{",
                headers={"content-type": "application/json"},
            )
            return response.status_code, response.json()

    status_code, payload = asyncio.run(_run())

    assert status_code == 422
    assert payload == {"ok": False, "detail": "invalid JSON body"}


def test_arti_ready_requires_no_auth_socks5_response(monkeypatch):
    from services import config as config_mod
    from services import wormhole_supervisor

    class _FakeSocket:
        def __init__(self, response: bytes):
            self.response = response
            self.sent = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def sendall(self, data: bytes):
            self.sent.append(data)

        def recv(self, _size: int) -> bytes:
            return self.response

    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: SimpleNamespace(MESH_ARTI_ENABLED=True, MESH_ARTI_SOCKS_PORT=9050),
    )
    monkeypatch.setattr(
        wormhole_supervisor.socket,
        "create_connection",
        lambda *_args, **_kwargs: _FakeSocket(b"\x05\x02"),
    )

    assert wormhole_supervisor._check_arti_ready() is False


def test_gate_router_private_push_uses_opaque_gate_ref(monkeypatch):
    from services import config as config_mod
    from services.mesh.mesh_router import InternetTransport, MeshEnvelope

    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: SimpleNamespace(MESH_PEER_PUSH_SECRET="peer-secret"),
    )

    envelope = MeshEnvelope(
        sender_id="!sb_sender",
        destination="broadcast",
        payload=json.dumps(
            {
                "event_type": "gate_message",
                "timestamp": 1710000000,
                "payload": {
                    "gate": "finance",
                    "ciphertext": "abc123",
                    "format": "mls1",
                },
            }
        ),
    )
    endpoint, body = InternetTransport()._build_peer_push_request(envelope, "internet")
    payload = json.loads(body.rstrip(b" ").decode("utf-8"))

    assert endpoint == "/api/mesh/gate/peer-push"
    gate_payload = payload["events"][0]["payload"]
    assert "gate" not in gate_payload
    assert gate_payload["gate_ref"]


def test_gate_router_private_push_freezes_current_v1_signer_bundle(monkeypatch):
    from services import config as config_mod
    from services.mesh.mesh_router import InternetTransport, MeshEnvelope

    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: SimpleNamespace(MESH_PEER_PUSH_SECRET="peer-secret"),
    )

    envelope = MeshEnvelope(
        sender_id="!sb_sender",
        destination="broadcast",
        payload=json.dumps(
            {
                "event_type": "gate_message",
                "timestamp": 1710000000,
                "event_id": "gate-evt-1",
                "node_id": "!gate-persona-1",
                "sequence": 19,
                "signature": "deadbeef",
                "public_key": "pubkey-1",
                "public_key_algo": "Ed25519",
                "protocol_version": "infonet/2",
                "payload": {
                    "gate": "finance",
                    "ciphertext": "abc123",
                    "format": "mls1",
                    "nonce": "nonce-7",
                    "sender_ref": "sender-ref-7",
                    "epoch": 4,
                },
            }
        ),
    )

    endpoint, body = InternetTransport()._build_peer_push_request(envelope, "internet")
    payload = json.loads(body.rstrip(b" ").decode("utf-8"))
    event = payload["events"][0]

    assert endpoint == "/api/mesh/gate/peer-push"
    assert set(event.keys()) == {
        "event_type",
        "timestamp",
        "payload",
        "event_id",
        "node_id",
        "sequence",
        "signature",
        "public_key",
        "public_key_algo",
        "protocol_version",
    }
    assert event["event_id"] == "gate-evt-1"
    assert event["node_id"] == "!gate-persona-1"
    assert event["sequence"] == 19
    assert event["signature"] == "deadbeef"
    assert event["public_key"] == "pubkey-1"
    assert event["public_key_algo"] == "Ed25519"
    assert event["protocol_version"] == "infonet/2"
    assert set(event["payload"].keys()) == {"ciphertext", "format", "gate_ref", "nonce", "sender_ref", "epoch"}
    assert event["payload"]["ciphertext"] == "abc123"
    assert event["payload"]["format"] == "mls1"
    assert event["payload"]["nonce"] == "nonce-7"
    assert event["payload"]["sender_ref"] == "sender-ref-7"
    assert event["payload"]["epoch"] == 4
    assert event["payload"]["gate_ref"]
    assert "gate" not in event["payload"]


def test_gate_access_proof_round_trip_verifies_fresh_member_signature(monkeypatch):
    import main

    identity = _gate_proof_identity()
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_resolve_gate_proof_identity", lambda gate_id: dict(identity) if gate_id == "finance" else None)
    monkeypatch.setattr(
        main,
        "_lookup_gate_member_binding",
        lambda gate_id, node_id: (identity["public_key"], "Ed25519")
        if gate_id == "finance" and node_id == identity["node_id"]
        else None,
    )

    proof = main._sign_gate_access_proof("finance")
    request = SimpleNamespace(
        headers={
            "x-wormhole-node-id": identity["node_id"],
            "x-wormhole-gate-proof": proof["proof"],
            "x-wormhole-gate-ts": str(proof["ts"]),
        }
    )

    assert proof["ok"] is True
    assert main._verify_gate_access(request, "finance") is True


def test_gate_access_proof_rejects_stale_timestamp(monkeypatch):
    import main

    identity = _gate_proof_identity()
    stale_ts = int(time.time()) - 120
    signature = identity["signing_key"].sign(f"finance:{stale_ts}".encode("utf-8"))
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(
        main,
        "_lookup_gate_member_binding",
        lambda gate_id, node_id: (identity["public_key"], "Ed25519")
        if gate_id == "finance" and node_id == identity["node_id"]
        else None,
    )
    request = SimpleNamespace(
        headers={
            "x-wormhole-node-id": identity["node_id"],
            "x-wormhole-gate-proof": base64.b64encode(signature).decode("ascii"),
            "x-wormhole-gate-ts": str(stale_ts),
        }
    )

    assert main._verify_gate_access(request, "finance") is False


def test_gate_proof_endpoint_returns_signed_proof(monkeypatch):
    import main

    identity = _gate_proof_identity()
    monkeypatch.setattr(main, "_resolve_gate_proof_identity", lambda gate_id: dict(identity) if gate_id == "finance" else None)
    monkeypatch.setattr(main, "_current_admin_key", lambda: "test-admin")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/proof",
                json={"gate_id": "finance"},
                headers={"x-admin-key": "test-admin"},
            )
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 200
    assert result["ok"] is True
    assert result["gate_id"] == "finance"
    assert result["node_id"] == identity["node_id"]
    assert result["proof"]


def test_private_infonet_policy_marks_gate_actions_transitional():
    import main

    assert main._private_infonet_required_tier("/api/mesh/vote", "POST") == "transitional"
    assert (
        main._private_infonet_required_tier("/api/mesh/gate/infonet/message", "POST")
        == "transitional"
    )
    assert main._private_infonet_required_tier("/api/mesh/dm/send", "POST") == "strong"
    assert main._private_infonet_required_tier("/api/mesh/dm/poll", "GET") == "strong"
    assert main._private_infonet_required_tier("/api/mesh/status", "GET") == ""


def test_current_private_lane_tier_reflects_runtime_readiness():
    import main

    assert main._current_private_lane_tier({"configured": False, "ready": False, "rns_ready": False}) == "public_degraded"
    assert main._current_private_lane_tier({"configured": True, "ready": False, "rns_ready": True}) == "public_degraded"
    assert main._current_private_lane_tier({"configured": True, "ready": True, "rns_ready": False}) == "private_transitional"
    assert main._current_private_lane_tier({"configured": True, "ready": True, "rns_ready": True}) == "private_transitional"
    assert main._current_private_lane_tier({"configured": True, "ready": True, "arti_ready": True, "rns_ready": True}) == "private_strong"


def test_message_payload_normalization_keeps_transport_lock():
    from services.mesh.mesh_protocol import normalize_message_payload

    normalized = normalize_message_payload(
        {
            "message": "hello mesh",
            "destination": "broadcast",
            "channel": "LongFast",
            "priority": "normal",
            "ephemeral": False,
            "transport_lock": "Meshtastic",
        }
    )

    assert normalized["transport_lock"] == "meshtastic"


def test_public_ledger_rejects_transport_lock():
    from services.mesh.mesh_schema import validate_public_ledger_payload

    ok, reason = validate_public_ledger_payload(
        "message",
        {
            "message": "hello mesh",
            "destination": "broadcast",
            "channel": "LongFast",
            "priority": "normal",
            "ephemeral": False,
            "transport_lock": "meshtastic",
        },
    )

    assert ok is False
    assert "transport_lock" in reason


def test_preflight_integrity_rejects_public_key_binding_conflict(monkeypatch):
    import main
    from services.mesh import mesh_hashchain as mesh_hashchain_mod

    fake_infonet = SimpleNamespace(
        check_replay=lambda node_id, sequence: False,
        node_sequences={},
        public_key_bindings={"pub": "!other-node"},
        _revocation_status=lambda public_key: (False, None),
    )
    monkeypatch.setattr(mesh_hashchain_mod, "infonet", fake_infonet)

    ok, reason = main._preflight_signed_event_integrity(
        event_type="gate_message",
        node_id="!node",
        sequence=10,
        public_key="pub",
        public_key_algo="Ed25519",
        signature="sig",
        protocol_version="1",
    )

    assert ok is False
    assert reason == "public key already bound to !other-node"


def test_mesh_send_blocks_before_transport_side_effect_when_integrity_fails(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_router as mesh_router_mod

    fake_router = _FakeMeshRouter()

    monkeypatch.setattr(main, "_verify_signed_event", lambda **_: (True, "ok"))
    monkeypatch.setattr(
        main,
        "_preflight_signed_event_integrity",
        lambda **_: (False, "Replay detected: sequence 11 <= last 11"),
    )
    monkeypatch.setattr(main, "_check_throttle", lambda *_: (True, "ok"))
    monkeypatch.setattr(mesh_router_mod, "mesh_router", fake_router)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post("/api/mesh/send", json=_send_body())
            return response.json()

    result = asyncio.run(_run())

    assert result == {"ok": False, "detail": "Replay detected: sequence 11 <= last 11"}
    assert fake_router.route_called is False
    assert fake_router.meshtastic.sent == []


def test_mesh_vote_blocks_before_vote_side_effect_when_integrity_fails(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_reputation as mesh_reputation_mod
    from services import wormhole_supervisor

    fake_ledger = _FakeReputationLedger()

    monkeypatch.setattr(main, "_verify_signed_event", lambda **_: (True, "ok"))
    monkeypatch.setattr(
        main,
        "_preflight_signed_event_integrity",
        lambda **_: (False, "public key is revoked"),
    )
    monkeypatch.setattr(main, "_validate_gate_vote_context", lambda *_: (True, ""))
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/vote",
                json={
                    "voter_id": "!voter",
                    "target_id": "!target",
                    "vote": 1,
                    "voter_pubkey": "pub",
                    "public_key_algo": "Ed25519",
                    "voter_sig": "sig",
                    "sequence": 4,
                    "protocol_version": "1",
                },
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {"ok": False, "detail": "public key is revoked"}
    assert fake_ledger.registered == []
    assert fake_ledger.votes == []


def test_gate_message_blocks_before_gate_side_effect_when_integrity_fails(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_reputation as mesh_reputation_mod
    from services import wormhole_supervisor

    fake_ledger = _FakeReputationLedger()
    fake_gate_manager = _FakeGateManager()

    monkeypatch.setattr(main, "_verify_signed_event", lambda **_: (True, "ok"))
    monkeypatch.setattr(
        main,
        "_preflight_signed_event_integrity",
        lambda **_: (False, "Replay detected: sequence 7 <= last 7"),
    )
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)
    monkeypatch.setattr(mesh_reputation_mod, "gate_manager", fake_gate_manager, raising=False)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/gate/infonet/message",
                json={
                    "sender_id": "!sender",
                    "epoch": 1,
                    "ciphertext": "opaque-ciphertext",
                    "nonce": "nonce-1",
                    "sender_ref": "gate-session-1",
                    "public_key": "pub",
                    "public_key_algo": "Ed25519",
                    "signature": "sig",
                    "sequence": 7,
                    "protocol_version": "1",
                },
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {"ok": False, "detail": "Replay detected: sequence 7 <= last 7"}
    assert fake_ledger.registered == []
    assert fake_gate_manager.enter_checks == []
    assert fake_gate_manager.recorded == []


def test_gate_message_rejects_plaintext_payload_shape(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/gate/infonet/message",
                json={
                    "sender_id": "!sender",
                    "message": "hello gate",
                    "public_key": "pub",
                    "public_key_algo": "Ed25519",
                    "signature": "sig",
                    "sequence": 7,
                    "protocol_version": "1",
                },
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {
        "ok": False,
        "detail": "Plaintext gate messages are no longer accepted. Submit an encrypted gate envelope.",
    }


def test_gate_message_accepts_encrypted_envelope(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_hashchain as mesh_hashchain_mod
    from services.mesh import mesh_reputation as mesh_reputation_mod
    from services import wormhole_supervisor

    fake_ledger = _FakeReputationLedger()
    fake_gate_manager = _FakeGateManager()
    append_calls = []

    monkeypatch.setattr(main, "_verify_signed_event", lambda **_: (True, "ok"))
    monkeypatch.setattr(main, "_preflight_signed_event_integrity", lambda **_: (True, "ok"))
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)
    monkeypatch.setattr(mesh_reputation_mod, "gate_manager", fake_gate_manager, raising=False)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )

    def fake_append(gate_id, event):
        append_calls.append({"gate_id": gate_id, "event": event})
        return event

    monkeypatch.setattr(mesh_hashchain_mod.gate_store, "append", fake_append)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/gate/infonet/message",
                json={
                    "sender_id": "!sender",
                    "epoch": 3,
                    "ciphertext": "opaque-ciphertext",
                    "nonce": "nonce-3",
                    "sender_ref": "persona-ops-1",
                    "format": "mls1",
                    "public_key": "pub",
                    "public_key_algo": "Ed25519",
                    "signature": "sig",
                    "sequence": 9,
                    "protocol_version": "1",
                },
            )
            return response.json()

    result = asyncio.run(_run())

    assert result["ok"] is True
    assert result["detail"] == "Message posted to gate 'infonet'"
    assert result["gate_id"] == "infonet"
    assert result["event_id"] == append_calls[0]["event"]["event_id"]
    assert fake_ledger.registered == [("!sender", "pub", "Ed25519")]
    assert fake_gate_manager.enter_checks == [("!sender", "infonet")]
    assert fake_gate_manager.recorded == ["infonet"]
    assert append_calls[0]["gate_id"] == "infonet"
    assert append_calls[0]["event"]["payload"] == {
        "gate": "infonet",
        "epoch": 3,
        "ciphertext": "opaque-ciphertext",
        "nonce": "nonce-3",
        "sender_ref": "persona-ops-1",
        "format": "mls1",
    }


def test_gate_message_enforces_30_second_sender_cooldown(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_hashchain as mesh_hashchain_mod
    from services.mesh import mesh_reputation as mesh_reputation_mod
    from services import wormhole_supervisor

    class _Clock:
        def __init__(self):
            self.current = 1_000.0

        def time(self):
            return self.current

    clock = _Clock()
    fake_ledger = _FakeReputationLedger()
    fake_gate_manager = _FakeGateManager()
    append_calls = []

    monkeypatch.setattr(main.time, "time", clock.time)
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_: (True, "ok"))
    monkeypatch.setattr(main, "_preflight_signed_event_integrity", lambda **_: (True, "ok"))
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)
    monkeypatch.setattr(mesh_reputation_mod, "gate_manager", fake_gate_manager, raising=False)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setattr(
        mesh_hashchain_mod.gate_store,
        "append",
        lambda gate_id, event: append_calls.append({"gate_id": gate_id, "event": event}) or event,
    )
    monkeypatch.setattr(
        mesh_hashchain_mod.infonet,
        "validate_and_set_sequence",
        lambda node_id, sequence: (True, "ok"),
    )
    main._gate_post_cooldown.clear()

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            first = await ac.post(
                "/api/mesh/gate/infonet/message",
                json={
                    "sender_id": "!sender",
                    "epoch": 3,
                    "ciphertext": "opaque-ciphertext",
                    "nonce": "nonce-3",
                    "sender_ref": "persona-ops-1",
                    "format": "mls1",
                    "public_key": "pub",
                    "public_key_algo": "Ed25519",
                    "signature": "sig",
                    "sequence": 9,
                    "protocol_version": "1",
                },
            )
            clock.current += 12
            second = await ac.post(
                "/api/mesh/gate/infonet/message",
                json={
                    "sender_id": "!sender",
                    "epoch": 3,
                    "ciphertext": "opaque-ciphertext-2",
                    "nonce": "nonce-4",
                    "sender_ref": "persona-ops-1",
                    "format": "mls1",
                    "public_key": "pub",
                    "public_key_algo": "Ed25519",
                    "signature": "sig",
                    "sequence": 10,
                    "protocol_version": "1",
                },
            )
            return first.json(), second.json()

    first_result, second_result = asyncio.run(_run())

    assert first_result["ok"] is True
    assert second_result == {
        "ok": False,
        "detail": "Gate post cooldown: wait 18s before posting again.",
    }
    assert fake_gate_manager.recorded == ["infonet"]
    assert len(append_calls) == 1


def test_infonet_status_reports_lane_tier_and_policy(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/mesh/infonet/status")
            return response.json()

    result = asyncio.run(_run())

    assert result["private_lane_tier"] == "private_transitional"
    assert result["private_lane_policy"]["gate_actions"]["post_message"] == "private_transitional"
    assert result["private_lane_policy"]["gate_chat"]["content_private"] is True
    assert (
        result["private_lane_policy"]["gate_chat"]["storage_model"]
        == "private_gate_store_encrypted_envelope"
    )
    assert result["private_lane_policy"]["dm_lane"]["public_transports_excluded"] is True
    assert result["private_lane_policy"]["reserved_for_private_strong"] == []


def test_wormhole_status_reports_transport_tier(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setattr(main, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": False,
            "transport": "direct",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/wormhole/status")
            return response.json()

    result = asyncio.run(_run())

    assert result["transport_tier"] == "private_transitional"


def test_wormhole_status_reports_private_strong_when_arti_ready(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setattr(main, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
            "transport": "tor_arti",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/wormhole/status")
            return response.json()

    result = asyncio.run(_run())

    assert result["transport_tier"] == "private_strong"


def test_rns_status_reports_lane_tier_and_policy(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor
    from services.mesh import mesh_rns

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(
        mesh_rns,
        "rns_bridge",
        SimpleNamespace(status=lambda: {"enabled": True, "ready": True, "configured_peers": 1, "active_peers": 1}),
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/mesh/rns/status")
            return response.json()

    result = asyncio.run(_run())

    assert result["private_lane_tier"] == "private_strong"
    assert result["private_lane_policy"]["gate_chat"]["trust_tier"] == "private_transitional"


def test_scoped_gate_token_cannot_access_dm_endpoints(tmp_path, monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.config import get_settings
    from services import wormhole_supervisor
    from services.mesh import mesh_gate_mls, mesh_secure_storage, mesh_wormhole_persona

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_gate_mls, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_gate_mls, "STATE_FILE", tmp_path / "wormhole_gate_mls.json")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    mesh_gate_mls.reset_gate_mls_state()
    mesh_wormhole_persona.bootstrap_wormhole_persona_state(force=True)
    mesh_wormhole_persona.create_gate_persona("infonet", label="scribe")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setenv("MESH_SCOPED_TOKENS", '{"gate-only":["gate"]}')
    get_settings.cache_clear()

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            gate_response = await ac.post(
                "/api/wormhole/gate/message/compose",
                json={"gate_id": "infonet", "plaintext": "gate scoped"},
                headers={"X-Admin-Key": "gate-only"},
            )
            dm_response = await ac.post(
                "/api/wormhole/dm/compose",
                json={"peer_id": "bob", "peer_dh_pub": "deadbeef", "plaintext": "blocked"},
                headers={"X-Admin-Key": "gate-only"},
            )
            return gate_response.json(), dm_response.status_code, dm_response.json()

    try:
        gate_result, dm_status, dm_result = asyncio.run(_run())
    finally:
        get_settings.cache_clear()

    assert gate_result["ok"] is True
    assert dm_status == 403
    assert dm_result == {"detail": "Forbidden — insufficient scope"}
