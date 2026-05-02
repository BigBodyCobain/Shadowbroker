import base64
import json
import os
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from starlette.requests import Request


def _make_receive(body: bytes = b"{}"):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _request(gate_id: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": f"/api/mesh/gate/{gate_id}/message",
            "path_params": {"gate_id": gate_id},
            "query_string": b"",
            "root_path": "",
            "server": ("test", 80),
        },
        _make_receive(),
    )


def _identity():
    from services.mesh.mesh_crypto import derive_node_id

    private = ed25519.Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(public_raw).decode("ascii")
    return private, public_key, derive_node_id(public_key)


def _signed_gate_body(gate_id: str, *, epoch: int, sign_epoch: bool = True, sequence: int = 1) -> dict:
    from services.mesh.mesh_crypto import build_signature_payload
    from services.mesh.mesh_gate_mls import _gate_envelope_hash
    from services.mesh.mesh_protocol import PROTOCOL_VERSION

    private, public_key, node_id = _identity()
    gate_envelope = base64.b64encode(os.urandom(48)).decode("ascii")
    envelope_hash = _gate_envelope_hash(gate_envelope)
    payload = {
        "gate": gate_id,
        "ciphertext": base64.b64encode(os.urandom(96)).decode("ascii"),
        "nonce": "nonce-1",
        "sender_ref": "sender-ref",
        "format": "mls1",
        "envelope_hash": envelope_hash,
        "transport_lock": "private_strong",
    }
    if sign_epoch:
        payload["epoch"] = epoch
    signature_payload = build_signature_payload(
        event_type="gate_message",
        node_id=node_id,
        sequence=sequence,
        payload=payload,
    )
    body = {
        "sender_id": node_id,
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "signature": private.sign(signature_payload.encode("utf-8")).hex(),
        "sequence": sequence,
        "protocol_version": PROTOCOL_VERSION,
        "epoch": epoch,
        "ciphertext": payload["ciphertext"],
        "nonce": payload["nonce"],
        "sender_ref": payload["sender_ref"],
        "format": payload["format"],
        "gate_envelope": gate_envelope,
        "envelope_hash": envelope_hash,
        "transport_lock": "private_strong",
    }
    return body


def _patch_successful_gate_submit(monkeypatch, *, current_epoch: int):
    import main
    from services.mesh import mesh_hashchain, mesh_reputation
    from services.mesh import mesh_gate_mls

    captured: dict = {}
    monkeypatch.setattr(mesh_reputation.gate_manager, "can_enter", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(mesh_reputation.gate_manager, "record_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_check_gate_post_cooldown", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(main, "_record_gate_post_cooldown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_validate_private_signed_sequence", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        mesh_gate_mls,
        "inspect_local_gate_state",
        lambda _gate_id, *, expected_epoch=0: {
            "ok": expected_epoch == current_epoch,
            "repair_state": "gate_state_ok" if expected_epoch == current_epoch else "gate_state_stale",
            "current_epoch": current_epoch,
        },
    )

    def _append(gate_id, event):
        captured["gate_id"] = gate_id
        captured["event"] = event
        return {**event, "event_id": event.get("event_id", "evt")}

    monkeypatch.setattr(mesh_hashchain.gate_store, "append", _append)
    monkeypatch.setattr(main, "_queue_gate_release", lambda **kwargs: {"ok": True, **kwargs})
    return captured


def test_gate_post_rejects_stale_signed_epoch_before_storage(monkeypatch):
    import main
    from services.mesh import mesh_gate_mls, mesh_hashchain

    gate_id = "epoch-proof"
    body = _signed_gate_body(gate_id, epoch=4, sign_epoch=True)
    append_called = {"value": False}
    monkeypatch.setattr(
        mesh_gate_mls,
        "inspect_local_gate_state",
        lambda _gate_id, *, expected_epoch=0: {
            "ok": False,
            "repair_state": "gate_state_stale",
            "current_epoch": 5,
        },
    )
    monkeypatch.setattr(mesh_hashchain.gate_store, "append", lambda *_args, **_kwargs: append_called.__setitem__("value", True))

    result = main._submit_gate_message_envelope(_request(gate_id), gate_id, body)

    assert result["ok"] is False
    assert result["detail"] == "gate_state_stale"
    assert result["current_epoch"] == 5
    assert result["expected_epoch"] == 4
    assert append_called["value"] is False


def test_gate_post_stores_epoch_only_when_epoch_was_signed(monkeypatch):
    import main

    gate_id = "epoch-proof"
    captured = _patch_successful_gate_submit(monkeypatch, current_epoch=7)
    body = _signed_gate_body(gate_id, epoch=7, sign_epoch=True)

    result = main._submit_gate_message_envelope(_request(gate_id), gate_id, body)

    assert result["ok"] is True
    assert captured["event"]["payload"]["epoch"] == 7


def test_legacy_gate_signature_with_unsigned_epoch_does_not_store_epoch(monkeypatch):
    import main

    gate_id = "epoch-proof"
    captured = _patch_successful_gate_submit(monkeypatch, current_epoch=7)
    body = _signed_gate_body(gate_id, epoch=7, sign_epoch=False)

    result = main._submit_gate_message_envelope(_request(gate_id), gate_id, body)

    assert result["ok"] is True
    assert "epoch" not in captured["event"]["payload"]


def test_previous_secret_archive_ttl_scrubs_bytes(monkeypatch):
    from services.mesh import mesh_reputation

    gate_id = "ttl-proof"
    monkeypatch.setattr(mesh_reputation.gate_manager, "_save", lambda: None)
    monkeypatch.setenv("MESH_GATE_PREVIOUS_SECRET_TTL_S", "10")
    mesh_reputation.gate_manager.gates[gate_id] = {
        "gate_secret": "current",
        "gate_secret_archive": {
            "previous_secret": "old-secret",
            "previous_valid_through_event_id": "evt-old",
            "previous_valid_through_epoch": 3,
            "rotated_at": 100.0,
            "reason": "ban",
        },
    }
    monkeypatch.setattr(mesh_reputation.time, "time", lambda: 111.0)

    archive = mesh_reputation.gate_manager.get_gate_secret_archive(gate_id)

    assert archive["previous_secret"] == ""
    assert archive["previous_valid_through_event_id"] == ""
    assert archive["previous_valid_through_epoch"] == 0
    assert "scrubbed_ttl" in archive["reason"]


def test_banned_previous_secret_cannot_open_post_rotation_envelope(monkeypatch):
    from services.mesh import mesh_gate_mls

    gate_id = "post-rotation-proof"
    message_nonce = "nonce-after-ban"
    plaintext = "post rotation"
    nonce = os.urandom(12)
    aad = f"gate_envelope|{gate_id}|{message_nonce}".encode("utf-8")
    ct = AESGCM(
        mesh_gate_mls._gate_envelope_key_scoped(
            gate_id,
            "current-secret",
            message_nonce=message_nonce,
        )
    ).encrypt(nonce, plaintext.encode("utf-8"), aad)
    token = base64.b64encode(nonce + ct).decode("ascii")

    opened_with_previous = mesh_gate_mls._try_gate_envelope_decrypt(
        gate_id,
        "previous-secret",
        nonce,
        ct,
        message_nonce=message_nonce,
    )

    assert opened_with_previous is None
    assert base64.b64decode(token) == nonce + ct


def test_gate_claim_downgrades_when_rotation_or_archive_ttl_disabled(monkeypatch):
    from services.privacy_claims import privacy_claims_snapshot

    monkeypatch.setenv("MESH_GATE_BAN_KICK_ROTATION_ENABLE", "false")
    monkeypatch.setenv("MESH_GATE_PREVIOUS_SECRET_TTL_S", "0")

    snapshot = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody={"protected_at_rest": True},
        privacy_core={"attestation_state": "attested_current"},
        compatibility_readiness={},
        gate_privilege_access={
            "privileged_gate_event_scope_class": "explicit_gate_audit",
            "repair_detail_scope_class": "local_operator_diagnostic",
        },
    )

    gate = snapshot["claims"]["gate_transitional"]
    assert gate["allowed"] is False
    assert "gate_ban_kick_rotation_disabled" in gate["blockers"]
    assert "gate_previous_secret_ttl_disabled" in gate["blockers"]
