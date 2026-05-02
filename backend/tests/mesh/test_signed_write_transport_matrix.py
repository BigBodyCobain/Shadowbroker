import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from starlette.requests import Request
from starlette.responses import Response

from auth import _transport_tier_is_sufficient


TIERS = [
    "public_degraded",
    "private_control_only",
    "private_transitional",
    "private_strong",
]


def _make_receive(body: bytes):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _request(path: str, body: dict[str, Any] | None = None, method: str = "POST") -> Request:
    raw_body = json.dumps(body or {}).encode("utf-8")
    return Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": method,
            "path": path,
            "query_string": b"",
            "root_path": "",
            "server": ("test", 80),
        },
        _make_receive(raw_body),
    )


def _now() -> int:
    return int(time.time())


@dataclass(frozen=True)
class SignedWriteCase:
    name: str
    path: str
    required_tier: str
    event_type: str
    body_factory: Callable[[], dict[str, Any]]
    invoke: Callable[[Any, Request], Any]
    pre_setup: Callable[[pytest.MonkeyPatch], None] | None = None
    verifier_attr: str = "_verify_signed_write"
    capture_result: tuple[Any, ...] = (False, "captured")


def _set_transport_tier(monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    import main
    from services import wormhole_settings, wormhole_supervisor

    async def _no_upgrade():
        return None

    monkeypatch.setattr(main, "_current_private_lane_tier", lambda _wormhole: tier)
    monkeypatch.setattr(main, "_try_transparent_transport_upgrade", _no_upgrade)
    monkeypatch.setattr(main, "_kickoff_dm_send_transport_upgrade", lambda: None)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {
            "configured": tier != "public_degraded",
            "ready": tier != "public_degraded",
            "arti_ready": tier == "private_strong",
            "rns_ready": tier in {"private_transitional", "private_strong"},
        },
    )
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: tier)
    monkeypatch.setattr(
        wormhole_settings,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "privacy_profile": "default",
            "transport": "direct",
            "anonymous_mode": False,
        },
    )


def _enable_dynamic_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.mesh import mesh_reputation

    monkeypatch.setattr(mesh_reputation, "ALLOW_DYNAMIC_GATES", True)


def _dm_send_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    import main
    from services.mesh import mesh_wormhole_contacts
    from services.mesh import mesh_crypto

    monkeypatch.setattr(
        main,
        "consume_wormhole_dm_sender_token",
        lambda **_: {
            "ok": True,
            "recipient_id": "!sb_recipient",
            "sender_id": "!sb_sender",
            "sender_token_hash": "tokhash",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "protocol_version": "1",
        },
    )
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "verified_first_contact_requirement",
        lambda _recipient_id: {"ok": True},
    )
    monkeypatch.setattr(mesh_crypto, "verify_node_binding", lambda *_: True)


SIGNED_WRITE_CASES = [
    SignedWriteCase(
        name="vote",
        path="/api/mesh/vote",
        required_tier="private_transitional",
        event_type="vote",
        body_factory=lambda: {
            "voter_id": "!sb_voter",
            "target_id": "!sb_target",
            "vote": 1,
            "gate": "",
            "voter_pubkey": "pub",
            "public_key_algo": "Ed25519",
            "voter_sig": "sig",
            "sequence": 1,
            "protocol_version": "1",
        },
        invoke=lambda main, req: main.mesh_vote(req),
    ),
    SignedWriteCase(
        name="report",
        path="/api/mesh/report",
        required_tier="private_transitional",
        event_type="abuse_report",
        body_factory=lambda: {
            "reporter_id": "!sb_reporter",
            "target_id": "!sb_target",
            "reason": "spam",
            "gate": "",
            "evidence": "evidence",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "1",
        },
        invoke=lambda main, req: main.mesh_report(req),
    ),
    SignedWriteCase(
        name="gate_create",
        path="/api/mesh/gate/create",
        required_tier="private_transitional",
        event_type="gate_create",
        body_factory=lambda: {
            "creator_id": "!sb_creator",
            "gate_id": "test-gate",
            "display_name": "Test Gate",
            "rules": {},
            "creator_pubkey": "pub",
            "public_key_algo": "Ed25519",
            "creator_sig": "sig",
            "sequence": 1,
            "protocol_version": "1",
        },
        invoke=lambda main, req: main.gate_create(req),
        pre_setup=_enable_dynamic_gates,
    ),
    SignedWriteCase(
        name="gate_message",
        path="/api/mesh/gate/test-gate/message",
        required_tier="private_strong",
        event_type="gate_message",
        body_factory=lambda: {
            "sender_id": "!sb_sender",
            "ciphertext": "Y2lwaGVydGV4dA==",
            "nonce": "bm9uY2U=",
            "sender_ref": "sender-ref",
            "format": "mls1",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "1",
            "transport_lock": "private_strong",
        },
        invoke=lambda main, req: main.gate_message(req, "test-gate"),
        verifier_attr="_verify_gate_message_signed_write",
        capture_result=(False, "captured", ""),
    ),
    SignedWriteCase(
        name="identity_rotate",
        path="/api/mesh/identity/rotate",
        required_tier="private_strong",
        event_type="key_rotate",
        body_factory=lambda: {
            "old_node_id": "!sb_old",
            "old_public_key": "oldpub",
            "old_public_key_algo": "Ed25519",
            "old_signature": "oldsig",
            "new_node_id": "!sb_new",
            "new_public_key": "newpub",
            "new_public_key_algo": "Ed25519",
            "new_signature": "newsig",
            "timestamp": _now(),
            "sequence": 1,
            "protocol_version": "1",
            "transport_lock": "private_strong",
        },
        invoke=lambda main, req: main.mesh_identity_rotate(req),
    ),
    SignedWriteCase(
        name="identity_revoke",
        path="/api/mesh/identity/revoke",
        required_tier="private_strong",
        event_type="key_revoke",
        body_factory=lambda: {
            "node_id": "!sb_node",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "revoked_at": _now(),
            "grace_until": _now() + 60,
            "reason": "rotated",
            "sequence": 1,
            "protocol_version": "1",
            "transport_lock": "private_strong",
        },
        invoke=lambda main, req: main.mesh_identity_revoke(req),
    ),
    SignedWriteCase(
        name="oracle_predict",
        path="/api/mesh/oracle/predict",
        required_tier="private_transitional",
        event_type="prediction",
        body_factory=lambda: {
            "node_id": "!sb_oracle",
            "market_title": "Alpha",
            "side": "yes",
            "stake_amount": 0,
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "1",
        },
        invoke=lambda main, req: main.oracle_predict(req),
    ),
    SignedWriteCase(
        name="oracle_stake",
        path="/api/mesh/oracle/stake",
        required_tier="private_transitional",
        event_type="stake",
        body_factory=lambda: {
            "staker_id": "!sb_oracle",
            "message_id": "msg-1",
            "poster_id": "!sb_target",
            "side": "truth",
            "amount": 1,
            "duration_days": 1,
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "1",
        },
        invoke=lambda main, req: main.oracle_stake(req),
    ),
    SignedWriteCase(
        name="dm_register",
        path="/api/mesh/dm/register",
        required_tier="private_strong",
        event_type="dm_key",
        body_factory=lambda: {
            "agent_id": "!sb_agent",
            "dh_pub_key": "deadbeef",
            "dh_algo": "X25519",
            "timestamp": _now(),
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "1",
            "transport_lock": "private_strong",
        },
        invoke=lambda main, req: main.dm_register_key(req),
    ),
    SignedWriteCase(
        name="dm_send",
        path="/api/mesh/dm/send",
        required_tier="private_strong",
        event_type="dm_message",
        body_factory=lambda: {
            "sender_id": "!sb_sender",
            "sender_token": "token",
            "recipient_id": "!sb_recipient",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "format": "mls1",
            "msg_id": "msg-1",
            "timestamp": _now(),
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "1",
            "transport_lock": "private_strong",
        },
        invoke=lambda main, req: main.dm_send(req),
        pre_setup=_dm_send_setup,
    ),
    SignedWriteCase(
        name="dm_block",
        path="/api/mesh/dm/block",
        required_tier="private_strong",
        event_type="dm_block",
        body_factory=lambda: {
            "agent_id": "!sb_agent",
            "blocked_id": "!sb_blocked",
            "action": "block",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "1",
            "transport_lock": "private_strong",
        },
        invoke=lambda main, req: main.dm_block(req),
    ),
    SignedWriteCase(
        name="dm_witness",
        path="/api/mesh/dm/witness",
        required_tier="private_strong",
        event_type="dm_key_witness",
        body_factory=lambda: {
            "witness_id": "!sb_witness",
            "target_id": "!sb_target",
            "dh_pub_key": "deadbeef",
            "timestamp": _now(),
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "1",
            "transport_lock": "private_strong",
        },
        invoke=lambda main, req: main.dm_key_witness(req),
    ),
    SignedWriteCase(
        name="trust_vouch",
        path="/api/mesh/trust/vouch",
        required_tier="private_strong",
        event_type="trust_vouch",
        body_factory=lambda: {
            "voucher_id": "!sb_voucher",
            "target_id": "!sb_target",
            "note": "trusted",
            "timestamp": _now(),
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "1",
            "transport_lock": "private_strong",
        },
        invoke=lambda main, req: main.trust_vouch(req),
    ),
]


@pytest.mark.parametrize("case", SIGNED_WRITE_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("tier", TIERS)
def test_signed_write_transport_matrix_enforces_tier_before_handler(monkeypatch, case: SignedWriteCase, tier: str):
    import main

    _set_transport_tier(monkeypatch, tier)
    if case.pre_setup is not None:
        case.pre_setup(monkeypatch)

    reached = {"value": False}

    async def call_next(_request: Request) -> Response:
        reached["value"] = True
        return Response(status_code=200)

    response = asyncio.run(main.enforce_high_privacy_mesh(_request(case.path), call_next))
    allowed = _transport_tier_is_sufficient(tier, case.required_tier) or case.name in {
        "dm_send",
        "gate_message",
    }

    if allowed:
        assert response.status_code == 200
        assert reached["value"] is True
    else:
        # Tor-style (hardening): no 428 — middleware returns 202 with
        # ok:True + pending to signal the client to wait for warmup.
        payload = json.loads(response.body.decode("utf-8"))
        assert response.status_code == 202
        assert reached["value"] is False
        assert payload.get("ok") is True
        assert payload.get("pending") is True
        assert payload.get("status") == "preparing_private_lane"
        assert payload["required"] == case.required_tier
        assert payload["current"] == tier


@pytest.mark.parametrize("case", SIGNED_WRITE_CASES, ids=lambda case: case.name)
def test_signed_write_handler_uses_expected_event_type(monkeypatch, case: SignedWriteCase):
    import main

    monkeypatch.setenv("MESH_SIGNED_WRITE_CONTEXT_REQUIRED", "false")
    _set_transport_tier(monkeypatch, case.required_tier)
    if case.pre_setup is not None:
        case.pre_setup(monkeypatch)

    captured: list[str] = []

    def _capture_signed_event(**kwargs):
        captured.append(
            str(
                kwargs.get(
                    "event_type",
                    "gate_message" if case.verifier_attr == "_verify_gate_message_signed_write" else "",
                )
            )
        )
        return case.capture_result

    monkeypatch.setattr(main, case.verifier_attr, _capture_signed_event)

    request = _request(case.path, case.body_factory())
    result = asyncio.run(case.invoke(main, request))

    assert captured == [case.event_type]
    assert result["ok"] is False
    assert result["detail"] == "captured"


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

    def route(self, _envelope, _credentials):
        from services.mesh.mesh_router import TransportResult

        return [TransportResult(True, "internet", "sent")]


@pytest.mark.parametrize(
    ("tier", "transport_lock", "expect_ok", "expected_detail"),
    [
        ("public_degraded", "meshtastic", True, ""),
        ("private_transitional", "meshtastic", False, "Private-tier content cannot be sent over Meshtastic"),
        ("public_degraded", "aprs", True, ""),
        ("private_strong", "aprs", False, "Private-tier content cannot be sent over APRS"),
        ("private_transitional", "", True, ""),
    ],
)
def test_mesh_send_transport_lock_matrix(monkeypatch, tier, transport_lock, expect_ok, expected_detail):
    import main
    from services import wormhole_supervisor
    from services.mesh import mesh_router as mesh_router_mod
    from services.sigint_bridge import sigint_grid

    captured: list[dict[str, Any]] = []
    fake_meshtastic = _FakeMeshtasticTransport(can_reach=True, send_ok=True)
    fake_router = _FakeMeshRouter(fake_meshtastic)
    fake_bridge = SimpleNamespace(messages=deque(maxlen=10))

    monkeypatch.setattr(
        main,
        "_verify_signed_write",
        lambda **kwargs: (captured.append(kwargs) or True, "ok"),
    )
    monkeypatch.setattr(main, "_check_throttle", lambda *_: (True, "ok"))
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: tier)
    monkeypatch.setattr(mesh_router_mod, "mesh_router", fake_router)
    monkeypatch.setattr(sigint_grid, "mesh", fake_bridge)

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
        "credentials": {"mesh_region": "US"},
    }
    if transport_lock:
        body["transport_lock"] = transport_lock

    result = asyncio.run(main.mesh_send(_request("/api/mesh/send", body)))

    assert captured and captured[0]["event_type"] == "message"
    if transport_lock:
        assert captured[0]["payload"]["transport_lock"] == transport_lock
    else:
        assert "transport_lock" not in captured[0]["payload"]

    assert result["ok"] is expect_ok
    if expected_detail:
        assert expected_detail in result["results"][0]["detail"]
