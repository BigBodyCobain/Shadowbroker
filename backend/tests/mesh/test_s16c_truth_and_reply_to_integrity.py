"""S16C truth-surface and gate reply_to integrity regressions.

Tests:
- DM MLS missing-session failures do not trip over binding.restored
- anonymous hidden-transport enforcement keys off ready, not just enabled
- private-lane policy snapshot stays aligned with route-tier truth
- wormhole gate compose/post forwards reply_to into compose signing
- gate ingest preserves signed reply_to and strips legacy unsigned reply_to
"""

import asyncio
import base64
import copy
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from starlette.requests import Request
from services.mesh.mesh_protocol import build_signed_context
from services.mesh.mesh_crypto import build_signature_payload


def _make_gate_request(gate_id: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": f"/api/mesh/gate/{gate_id}/message",
        }
    )


def _json_request(path: str, body: dict) -> Request:
    payload = json.dumps(body).encode("utf-8")
    sent = {"value": False}

    async def receive():
        if sent["value"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["value"] = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": path,
        },
        receive,
    )


def _build_gate_message_body(gate_id: str, *, reply_to: str = "") -> dict:
    gate_envelope = "dGVzdC1lbnZlbG9wZQ=="
    body = {
        "sender_id": "!sb_test1234567890",
        "ciphertext": "dGVzdA==",
        "nonce": "dGVzdG5vbmNl",
        "sender_ref": "testref1234",
        "format": "mls1",
        "public_key": "",
        "public_key_algo": "Ed25519",
        "signature": "deadbeef",
        "sequence": 1,
        "protocol_version": "infonet/2",
        "gate_envelope": gate_envelope,
        "envelope_hash": hashlib.sha256(gate_envelope.encode("ascii")).hexdigest(),
        "transport_lock": "private_strong",
    }
    if reply_to:
        body["reply_to"] = reply_to
    return body


def _patch_gate_submit_success(monkeypatch, module, captured: dict) -> None:
    import main
    from services.mesh.mesh_reputation import gate_manager, reputation_ledger

    monkeypatch.setattr(main, "_verify_gate_message_signed_write", lambda **kw: (True, "ok", kw.get("reply_to", "")))
    monkeypatch.setattr(gate_manager, "can_enter", lambda *a, **kw: (True, "ok"))
    monkeypatch.setattr(main, "_check_gate_post_cooldown", lambda *a: (True, "ok"))
    monkeypatch.setattr(main, "_record_gate_post_cooldown", lambda *a: None)
    monkeypatch.setattr(gate_manager, "record_message", lambda *a: None)
    monkeypatch.setattr(reputation_ledger, "register_node", lambda *a: None)
    monkeypatch.setattr("services.mesh.mesh_hashchain.infonet.validate_and_set_sequence", lambda *a, **kw: (True, "ok"))

    def fake_queue_gate_release(*, current_tier, gate_id, payload):
        captured["current_tier"] = current_tier
        captured["gate_id"] = gate_id
        captured["payload"] = copy.deepcopy(payload)
        return {
            "ok": True,
            "queued": True,
            "gate_id": gate_id,
            "event_id": str(payload.get("event_id", "") or ""),
            "outbox_id": "outbox-gate-test",
            "detail": "Queued for private delivery",
            "delivery": {
                "state": "queued",
                "status": {"label": "Queued for private delivery"},
                "required_tier": "private_transitional",
                "current_tier": current_tier,
            },
        }

    monkeypatch.setattr(main, "_queue_gate_release", fake_queue_gate_release)


def test_encrypt_dm_missing_session_binding_fails_cleanly(monkeypatch):
    from services.mesh import mesh_dm_mls
    from services.privacy_core_client import PrivacyCoreError

    monkeypatch.setattr(mesh_dm_mls, "_require_private_transport", lambda: (True, "ok"))

    def _raise_missing(*_args, **_kwargs):
        raise PrivacyCoreError("dm session not found for alice::bob")

    monkeypatch.setattr(mesh_dm_mls, "_session_binding", _raise_missing)

    result = mesh_dm_mls.encrypt_dm("alice", "bob", "hello")

    assert result["ok"] is False
    assert result["detail"] == "dm_mls_encrypt_failed"


def test_decrypt_dm_missing_session_binding_fails_cleanly(monkeypatch):
    from services.mesh import mesh_dm_mls
    from services.privacy_core_client import PrivacyCoreError

    monkeypatch.setattr(mesh_dm_mls, "_require_private_transport", lambda: (True, "ok"))

    def _raise_missing(*_args, **_kwargs):
        raise PrivacyCoreError("dm session not found for alice::bob")

    monkeypatch.setattr(mesh_dm_mls, "_session_binding", _raise_missing)

    result = mesh_dm_mls.decrypt_dm("alice", "bob", "Y3Q=", "bm9uY2U=")

    assert result["ok"] is False
    assert result["detail"] == "dm_mls_decrypt_failed"


def test_anonymous_hidden_transport_requires_ready(monkeypatch):
    import main

    monkeypatch.setattr(main, "_anonymous_mode_state", lambda: {"enabled": True, "ready": False})
    assert main._anonymous_dm_hidden_transport_enforced() is False

    monkeypatch.setattr(main, "_anonymous_mode_state", lambda: {"enabled": True, "ready": True})
    assert main._anonymous_dm_hidden_transport_enforced() is True


def test_main_dm_send_anonymous_enabled_but_not_ready_is_not_hidden_transport(monkeypatch):
    import main
    import time
    from services import wormhole_supervisor
    from services.mesh import (
        mesh_dm_relay,
        mesh_hashchain,
        mesh_private_outbox,
        mesh_private_release_worker,
        mesh_wormhole_contacts,
    )

    store = {}

    def _read_domain_json(_domain, _filename, default_factory, **_kwargs):
        payload = store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_domain_json(_domain, _filename, payload, **_kwargs):
        store["payload"] = copy.deepcopy(payload)

    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(mesh_private_outbox, "read_sensitive_domain_json", _read_domain_json)
    monkeypatch.setattr(mesh_private_outbox, "write_sensitive_domain_json", _write_domain_json)
    mesh_private_outbox.private_delivery_outbox._load()
    monkeypatch.setattr(main, "_verify_signed_write", lambda **kw: (True, "ok"))
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(main, "_anonymous_mode_state", lambda: {"enabled": True, "ready": False})
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "verified_first_contact_requirement",
        lambda *_a, **_kw: {"ok": True, "trust_level": "invite_pinned"},
    )
    monkeypatch.setattr(
        main,
        "consume_wormhole_dm_sender_token",
        lambda **_kw: {
            "ok": True,
            "recipient_id": "!sb_test_recipient",
            "sender_id": "!sb_test1234567890",
            "sender_token_hash": "sender-token-hash",
            "public_key": "",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
        },
    )
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "consume_nonce", lambda *a, **kw: (True, "ok"))
    monkeypatch.setattr(
        mesh_private_release_worker,
        "_secure_dm_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        mesh_private_release_worker,
        "_rns_private_dm_ready",
        lambda: False,
    )
    monkeypatch.setattr(
        mesh_private_release_worker,
        "_anonymous_dm_hidden_transport_enforced",
        lambda: False,
    )
    monkeypatch.setattr(
        mesh_private_release_worker,
        "_anonymous_dm_hidden_transport_requested",
        lambda: True,
    )
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(
        mesh_dm_relay.dm_relay,
        "deposit",
        lambda **kw: {
            "ok": True,
            "msg_id": kw.get("msg_id", "dm-1"),
            "transport": "relay",
            "carrier": "relay",
            "hidden_transport_effective": False,
        },
    )
    monkeypatch.setattr(
        mesh_hashchain,
        "infonet",
        type("FakeInfonet", (), {"validate_and_set_sequence": staticmethod(lambda *a, **kw: (True, "ok"))})(),
        raising=False,
    )

    result = asyncio.run(
        main.dm_send(
            _json_request(
                "/api/mesh/dm/send",
                (lambda body: body | {
                    "signed_context": build_signed_context(
                        event_type="dm_message",
                        kind="dm_send",
                        endpoint="/api/mesh/dm/send",
                        lane_floor="private_strong",
                        sequence_domain="dm_send",
                        node_id=body["sender_id"],
                        sequence=body["sequence"],
                        payload={
                            "recipient_id": body["recipient_id"],
                            "delivery_class": body["delivery_class"],
                            "recipient_token": body.get("recipient_token", ""),
                            "ciphertext": body["ciphertext"],
                            "format": body.get("format", "mls1"),
                            "msg_id": body["msg_id"],
                            "timestamp": body["timestamp"],
                            "transport_lock": body["transport_lock"],
                        },
                        recipient_id=body["recipient_id"],
                    )
                })(
                    {
                        "sender_id": "!sb_test1234567890",
                        "sender_token": "sender-token",
                        "recipient_id": "!sb_test_recipient",
                        "delivery_class": "request",
                        "ciphertext": "Y3Q=",
                        "msg_id": "dm-1",
                        "timestamp": int(time.time()),
                        "public_key": "",
                        "public_key_algo": "Ed25519",
                        "signature": "deadbeef",
                        "sequence": 1,
                        "protocol_version": "infonet/2",
                        "transport_lock": "private_strong",
                    }
                ),
                )
            )
    )

    assert result["ok"] is True
    assert result["queued"] is True
    mesh_private_release_worker.private_release_worker.run_once()
    delivered = next(
        item
        for item in mesh_private_outbox.private_delivery_outbox.list_items(
            limit=10,
            exposure="diagnostic",
        )
        if item["id"] == result["outbox_id"]
    )
    assert delivered["release_state"] == "queued"
    assert delivered["result"] == {}


def test_private_lane_policy_snapshot_dm_truth_is_honest():
    from auth import _private_infonet_policy_snapshot

    dm_lane = _private_infonet_policy_snapshot()["dm_lane"]

    assert dm_lane["minimum_transport_tier"] == "private_strong"
    assert dm_lane["local_operation_tier"] == "private_control_only"
    assert dm_lane["queued_acceptance_tier"] == "public_degraded"
    assert dm_lane["network_release_tier"] == "private_strong"
    assert dm_lane["poll_tier"] == "private_strong"


def test_private_lane_policy_snapshot_gate_truth_is_honest():
    """Gate posture must be weaker than DM and honestly say so."""
    from auth import _private_infonet_policy_snapshot

    snapshot = _private_infonet_policy_snapshot()
    gate = snapshot["gate_chat"]
    dm = snapshot["dm_lane"]

    # Hardening Rec #4: gate release floor lifted to private_strong to match DM.
    # Local operations remain control-only; admission (gate_actions) remains
    # private_transitional so composition stays possible on weaker tiers.
    assert gate["trust_tier"] == "private_strong"
    assert gate["local_operation_tier"] == "private_control_only"
    assert gate["queued_acceptance_tier"] == "public_degraded"
    assert gate["network_release_tier"] == "private_strong"
    assert gate["content_private"] is True
    # Gate requires Wormhole
    assert gate["wormhole_required"] is True

    # DM and gate releases are now at the same floor (both private_strong).
    assert dm["minimum_transport_tier"] == "private_strong"
    assert gate["trust_tier"] == dm["minimum_transport_tier"]

    # Gate notes still describe DM/Dead Drop as the recommended confidentiality
    # posture; the transport floor parity doesn't change the guidance.
    gate_notes_joined = " ".join(gate["notes"])
    assert "DM" in gate_notes_joined or "Dead Drop" in gate_notes_joined

    # Top-level notes must mention gate and DM are separate
    top_notes_joined = " ".join(snapshot["notes"])
    assert "gate" in top_notes_joined.lower()


def test_private_lane_policy_snapshot_exposes_compatibility_sunset_targets():
    from auth import _private_infonet_policy_snapshot

    compatibility = _private_infonet_policy_snapshot()["compatibility_sunset"]

    assert compatibility["legacy_node_id_binding"]["target_version"] == "0.10.0"
    assert compatibility["legacy_node_id_binding"]["target_date"] == "2026-06-01"
    assert compatibility["legacy_agent_id_lookup"]["target_version"] == "0.10.0"
    assert compatibility["legacy_agent_id_lookup"]["target_date"] == "2026-06-01"


def test_private_lane_policy_snapshot_separates_transport_tier_from_strong_claims(monkeypatch):
    import auth
    from services.config import get_settings

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": True,
            "wormhole_enabled": True,
            "ready": False,
            "effective_transport": "tor_arti",
        },
    )

    strong_claims = auth._private_infonet_policy_snapshot(
        current_tier="private_transitional"
    )["strong_claims"]

    assert strong_claims["current_transport_tier"] == "private_transitional"
    assert strong_claims["allowed"] is False
    assert "transport_tier_not_private_strong" in strong_claims["reasons"]
    assert "hidden_transport_not_ready" in strong_claims["reasons"]
    get_settings.cache_clear()


def test_private_lane_policy_gate_actions_remain_honest():
    """Room posting publishes its real release floor; public gate actions stay transitional."""
    from auth import _private_infonet_policy_snapshot

    gate_actions = _private_infonet_policy_snapshot()["gate_actions"]
    assert gate_actions["post_message"] == "private_strong"
    assert gate_actions["vote"] == "private_transitional"
    assert gate_actions["create_gate"] == "private_transitional"


def test_private_lane_policy_wormhole_gate_lifecycle_is_control_only():
    from auth import _private_infonet_policy_snapshot

    lifecycle = _private_infonet_policy_snapshot()["wormhole_gate_lifecycle"]

    assert lifecycle["trust_tier"] == "private_control_only"
    notes_joined = " ".join(lifecycle["notes"]).lower()
    assert "local control-plane actions" in notes_joined
    assert "gate compose/decrypt work once wormhole itself is ready" in notes_joined


def test_main_wormhole_gate_compose_uses_local_encrypting_control_path(monkeypatch):
    import main

    called = {"value": False}

    def fake_compose(gate_id, plaintext, reply_to=""):
        called["value"] = True
        return {"ok": True}

    monkeypatch.setattr(main, "compose_gate_message_with_repair", fake_compose)

    request = Request(
        {
            "type": "http",
            "headers": [],
            "client": ("test", 12345),
            "method": "POST",
            "path": "/api/wormhole/gate/message/compose",
        }
    )
    body = main.WormholeGateComposeRequest(
        gate_id="infonet",
        plaintext="hello",
        reply_to="evt-parent-1",
        compat_plaintext=True,
    )

    result = asyncio.run(main.api_wormhole_gate_message_compose(request, body))

    assert result["ok"] is True
    assert called["value"] is True


def test_router_wormhole_gate_post_uses_local_encrypting_control_path(monkeypatch):
    import main
    from routers import wormhole

    called = {"compose": False, "submit": False}

    def fake_compose(gate_id, plaintext, reply_to=""):
        called["compose"] = True
        return {"ok": True}

    def fake_submit(request, gate_id, body):
        called["submit"] = True
        return {"ok": True, "gate_id": gate_id, "reply_to": body.get("reply_to", "")}

    monkeypatch.setattr(main, "compose_gate_message_with_repair", fake_compose)
    monkeypatch.setattr(main, "_submit_gate_message_envelope", fake_submit)

    request = Request(
        {
            "type": "http",
            "headers": [],
            "client": ("test", 12345),
            "method": "POST",
            "path": "/api/wormhole/gate/message/post",
        }
    )
    body = wormhole.WormholeGateComposeRequest(
        gate_id="infonet",
        plaintext="hello",
        reply_to="evt-parent-2",
        compat_plaintext=True,
    )

    result = asyncio.run(wormhole.api_wormhole_gate_message_post(request, body))

    assert result == {"ok": True, "gate_id": "infonet", "reply_to": "evt-parent-2"}
    assert called == {"compose": True, "submit": True}


def test_main_gate_submit_preserves_signed_reply_to(monkeypatch):
    import main

    captured = {}
    _patch_gate_submit_success(monkeypatch, main, captured)
    monkeypatch.setattr(
        main,
        "_verify_gate_message_signed_write",
        lambda **kw: (
            kw.get("reply_to") == "evt-parent-3",
            "reply_to missing from signed payload",
            kw.get("reply_to", ""),
        ),
    )

    gate_id = "infonet"
    body = _build_gate_message_body(gate_id, reply_to="evt-parent-3")
    result = main._submit_gate_message_envelope(_make_gate_request(gate_id), gate_id, body)

    assert result["ok"] is True
    assert captured["payload"]["event"]["payload"]["reply_to"] == "evt-parent-3"


def test_router_gate_submit_strips_legacy_unsigned_reply_to(monkeypatch):
    from routers import mesh_public

    captured = {}
    _patch_gate_submit_success(monkeypatch, mesh_public, captured)

    def fake_verify(**kw):
        return True, "legacy signature only", ""

    import main

    monkeypatch.setattr(main, "_verify_gate_message_signed_write", fake_verify)

    gate_id = "infonet"
    body = _build_gate_message_body(gate_id, reply_to="evt-parent-4")
    result = mesh_public._submit_gate_message_envelope(_make_gate_request(gate_id), gate_id, body)

    assert result["ok"] is True
    assert "reply_to" not in captured["payload"]["event"]["payload"]


def test_gate_signature_verification_binds_reply_to():
    import main
    from services.mesh.mesh_crypto import derive_node_id

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(public_key_raw).decode("ascii")
    node_id = derive_node_id(public_key)
    payload = {
        "gate": "infonet",
        "ciphertext": "dGVzdA==",
        "nonce": "dGVzdG5vbmNl",
        "sender_ref": "testref1234",
        "format": "mls1",
        "reply_to": "evt-parent-5",
    }
    sig_payload = build_signature_payload(
        event_type="gate_message",
        node_id=node_id,
        sequence=1,
        payload=payload,
    )
    signature = private_key.sign(sig_payload.encode("utf-8")).hex()

    ok, reason = main._verify_signed_event(
        event_type="gate_message",
        node_id=node_id,
        sequence=1,
        public_key=public_key,
        public_key_algo="Ed25519",
        signature=signature,
        payload=payload,
        protocol_version="infonet/2",
    )
    assert ok is True, reason

    tampered_ok, _tampered_reason = main._verify_signed_event(
        event_type="gate_message",
        node_id=node_id,
        sequence=1,
        public_key=public_key,
        public_key_algo="Ed25519",
        signature=signature,
        payload={**payload, "reply_to": "evt-parent-5-tampered"},
        protocol_version="infonet/2",
    )
    assert tampered_ok is False


def test_private_gate_transport_signature_binds_reply_to(monkeypatch):
    from services.mesh import mesh_hashchain
    from services.mesh.mesh_crypto import derive_node_id, build_signature_payload

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(public_key_raw).decode("ascii")
    node_id = derive_node_id(public_key)
    gate_envelope = "ZW52ZWxvcGU="
    envelope_hash = hashlib.sha256(gate_envelope.encode("ascii")).hexdigest()
    payload = {
        "gate": "finance",
        "ciphertext": "dGVzdC1jdA==",
        "nonce": "dGVzdC1ub25jZQ==",
        "sender_ref": "transport-ref",
        "format": "mls1",
        "reply_to": "evt-transport-parent",
        "envelope_hash": envelope_hash,
    }
    signature = private_key.sign(
        build_signature_payload(
            event_type="gate_message",
            node_id=node_id,
            sequence=1,
            payload=payload,
        ).encode("utf-8")
    ).hex()
    event = {
        "event_type": "gate_message",
        "timestamp": 1.0,
        "node_id": node_id,
        "sequence": 1,
        "signature": signature,
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
        "payload": {**payload, "gate_envelope": gate_envelope},
    }

    monkeypatch.setattr(mesh_hashchain, "_authorize_private_gate_transport_author", lambda *a, **kw: (True, "ok"))

    ok, reason, sanitized = mesh_hashchain._verify_private_gate_transport_event("finance", event)

    assert ok is True, reason
    assert sanitized is not None
    assert sanitized["payload"]["reply_to"] == "evt-transport-parent"
    assert sanitized["payload"]["envelope_hash"] == envelope_hash


def test_private_gate_transport_legacy_unsigned_reply_to_is_stripped(monkeypatch):
    from services.mesh import mesh_hashchain
    from services.mesh.mesh_crypto import derive_node_id, build_signature_payload

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(public_key_raw).decode("ascii")
    node_id = derive_node_id(public_key)
    gate_envelope = "bGVnYWN5LWVudg=="
    envelope_hash = hashlib.sha256(gate_envelope.encode("ascii")).hexdigest()
    signed_payload = {
        "gate": "finance",
        "ciphertext": "bGVnYWN5LWN0",
        "nonce": "bGVnYWN5LW5vbmNl",
        "sender_ref": "legacy-ref",
        "format": "mls1",
        "envelope_hash": envelope_hash,
    }
    signature = private_key.sign(
        build_signature_payload(
            event_type="gate_message",
            node_id=node_id,
            sequence=7,
            payload=signed_payload,
        ).encode("utf-8")
    ).hex()
    event = {
        "event_type": "gate_message",
        "timestamp": 7.0,
        "node_id": node_id,
        "sequence": 7,
        "signature": signature,
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
        "payload": {
            **signed_payload,
            "gate_envelope": gate_envelope,
            "reply_to": "evt-legacy-parent",
        },
    }

    monkeypatch.setattr(mesh_hashchain, "_authorize_private_gate_transport_author", lambda *a, **kw: (True, "ok"))

    ok, reason, sanitized = mesh_hashchain._verify_private_gate_transport_event("finance", event)

    assert ok is True, reason
    assert sanitized is not None
    assert "reply_to" not in sanitized["payload"]
    assert sanitized["payload"]["envelope_hash"] == envelope_hash


def test_main_gate_read_strips_legacy_unsigned_reply_to():
    import main
    from services.mesh.mesh_crypto import derive_node_id, build_signature_payload

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(public_key_raw).decode("ascii")
    node_id = derive_node_id(public_key)
    signed_payload = {
        "gate": "finance",
        "ciphertext": "bGVnYWN5LXJlYWQtY3Q=",
        "nonce": "bGVnYWN5LXJlYWQtbm9uY2U=",
        "sender_ref": "legacy-read-ref",
        "format": "mls1",
    }
    signature = private_key.sign(
        build_signature_payload(
            event_type="gate_message",
            node_id=node_id,
            sequence=9,
            payload=signed_payload,
        ).encode("utf-8")
    ).hex()
    event = {
        "event_id": "legacy-read-1",
        "event_type": "gate_message",
        "timestamp": 9.0,
        "node_id": node_id,
        "sequence": 9,
        "signature": signature,
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
        "payload": {
            **signed_payload,
            "reply_to": "evt-legacy-read-parent",
        },
    }

    stripped = main._strip_gate_identity_member(event)

    assert stripped["payload"]["reply_to"] == ""


def test_main_gate_peer_push_preserves_envelope_hash_and_reply_to(monkeypatch):
    import main
    from services.mesh import mesh_hashchain

    captured = {}

    monkeypatch.setattr(main, "_verify_peer_push_hmac", lambda *_a, **_kw: True)

    class _FakeGateStore:
        def ingest_peer_events(self, gate_id, items):
            captured["gate_id"] = gate_id
            captured["items"] = items
            return {"accepted": len(items), "duplicates": 0, "rejected": 0}

    monkeypatch.setattr(mesh_hashchain, "gate_store", _FakeGateStore(), raising=False)

    gate_envelope = "cGVlci1wdXNoLWVudg=="
    envelope_hash = hashlib.sha256(gate_envelope.encode("ascii")).hexdigest()
    request = _json_request(
        "/api/mesh/gate/peer-push",
        {
            "events": [
                {
                    "event_type": "gate_message",
                    "timestamp": 1.0,
                    "node_id": "!sb_peerpush123456",
                    "sequence": 1,
                    "signature": "deadbeef",
                    "public_key": "dGVzdA==",
                    "public_key_algo": "Ed25519",
                    "protocol_version": "infonet/2",
                    "payload": {
                        "gate": "finance",
                        "ciphertext": "cGVlci1wdXNoLWN0",
                        "format": "mls1",
                        "nonce": "cGVlci1wdXNoLW5vbmNl",
                        "sender_ref": "peerpush-ref",
                        "gate_envelope": gate_envelope,
                        "envelope_hash": envelope_hash,
                        "reply_to": "evt-peer-push-parent",
                    },
                }
            ]
        },
    )

    result = asyncio.run(main.gate_peer_push(request))

    assert result["ok"] is True
    assert captured["gate_id"] == "finance"
    assert captured["items"][0]["payload"]["envelope_hash"] == envelope_hash
    assert captured["items"][0]["payload"]["reply_to"] == "evt-peer-push-parent"
