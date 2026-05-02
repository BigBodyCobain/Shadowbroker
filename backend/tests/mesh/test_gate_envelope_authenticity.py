"""S2 Gate Envelope Authenticity — prove gate_envelope is cryptographically bound.

Tests verify:
- Tampered gate_envelope is rejected when envelope_hash is present
- Stripped gate_envelope is rejected when envelope_hash is present
- Envelopes without envelope_hash are rejected rather than trusted as legacy
- Route-level: ingest rejects mismatched envelope_hash + gate_envelope
- compose_encrypted_gate_message produces envelope_hash
"""

import asyncio
import hashlib

import pytest


# ── Helpers ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _enable_runtime_recovery_envelopes(monkeypatch):
    from services.config import get_settings

    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE", "true")
    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _encrypt_envelope(gate_id: str, plaintext: str) -> str:
    """Encrypt a gate envelope using the real gate secret path."""
    from services.mesh.mesh_gate_mls import _gate_envelope_encrypt

    return _gate_envelope_encrypt(gate_id, plaintext)


def _decrypt_envelope(gate_id: str, token: str) -> str | None:
    """Decrypt a gate envelope using the real waterfall."""
    from services.mesh.mesh_gate_mls import _gate_envelope_decrypt

    return _gate_envelope_decrypt(gate_id, token)


def _compute_hash(envelope: str) -> str:
    return hashlib.sha256(envelope.encode("ascii")).hexdigest()


def _install_test_gate(
    gate_id: str,
    *,
    envelope_policy: str = "envelope_recovery",
    gate_secret: str = "test-gate-secret-authenticity",
):
    from services.mesh.mesh_reputation import gate_manager

    original = gate_manager.gates.get(gate_id)
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Envelope Authenticity Test",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": gate_secret,
        "envelope_policy": envelope_policy,
        "legacy_envelope_fallback": False,
    }
    return original


def _restore_test_gate(gate_id: str, original: dict | None) -> None:
    from services.mesh.mesh_reputation import gate_manager

    if original is None:
        gate_manager.gates.pop(gate_id, None)
    else:
        gate_manager.gates[gate_id] = original


# ── Decrypt-level: tampered envelope with envelope_hash ─────────────────


def test_tampered_gate_envelope_rejected_when_hash_present():
    """A tampered gate_envelope must fail when envelope_hash binds it."""
    from services.mesh.mesh_gate_mls import decrypt_gate_message_for_local_identity

    gate_id = "__test_gate_auth_tampered"
    original = _install_test_gate(gate_id)
    try:
        real_envelope = _encrypt_envelope(gate_id, "real message")
        envelope_hash = _compute_hash(real_envelope)

        # Attacker replaces envelope with one containing different plaintext
        tampered_envelope = _encrypt_envelope(gate_id, "INJECTED BY ATTACKER")

        result = decrypt_gate_message_for_local_identity(
            gate_id=gate_id,
            epoch=1,
            ciphertext="dummyct",  # won't reach MLS path
            nonce="dummynonce",
            gate_envelope=tampered_envelope,
            envelope_hash=envelope_hash,
            recovery_envelope=True,
        )

        assert result["ok"] is False
        assert "integrity" in result["detail"].lower()
    finally:
        _restore_test_gate(gate_id, original)


def test_stripped_gate_envelope_rejected_when_hash_present():
    """A stripped gate_envelope must fail when envelope_hash is present."""
    from services.mesh.mesh_gate_mls import decrypt_gate_message_for_local_identity

    gate_id = "__test_gate_auth_stripped"
    original = _install_test_gate(gate_id)
    try:
        real_envelope = _encrypt_envelope(gate_id, "real message")
        envelope_hash = _compute_hash(real_envelope)

        result = decrypt_gate_message_for_local_identity(
            gate_id=gate_id,
            epoch=1,
            ciphertext="dummyct",
            nonce="dummynonce",
            gate_envelope="",  # stripped
            envelope_hash=envelope_hash,
            recovery_envelope=True,
        )

        assert result["ok"] is False
        assert "missing" in result["detail"].lower()
    finally:
        _restore_test_gate(gate_id, original)


# ── Decrypt-level: unsigned envelope rejection ──────────────────────────


def test_gate_envelope_without_hash_is_rejected():
    """A gate_envelope without envelope_hash is unauthenticated and must not decrypt."""
    from services.mesh.mesh_gate_mls import decrypt_gate_message_for_local_identity

    gate_id = "__test_gate_auth_unsigned"
    original = _install_test_gate(gate_id)
    try:
        envelope = _encrypt_envelope(gate_id, "unsigned envelope content")

        result = decrypt_gate_message_for_local_identity(
            gate_id=gate_id,
            epoch=1,
            ciphertext="dummyct",
            nonce="dummynonce",
            gate_envelope=envelope,
            envelope_hash="",
            recovery_envelope=True,
        )

        assert result["ok"] is False
        assert "envelope_hash" in result["detail"]
    finally:
        _restore_test_gate(gate_id, original)


def test_valid_envelope_with_correct_hash_decrypts():
    """New-format messages with correct hash decrypt on explicit recovery reads."""
    from services.mesh.mesh_gate_mls import decrypt_gate_message_for_local_identity

    gate_id = "__test_gate_auth_valid"
    original = _install_test_gate(gate_id)
    try:
        plaintext = "authenticated message"
        envelope = _encrypt_envelope(gate_id, plaintext)
        envelope_hash = _compute_hash(envelope)

        result = decrypt_gate_message_for_local_identity(
            gate_id=gate_id,
            epoch=1,
            ciphertext="dummyct",
            nonce="dummynonce",
            gate_envelope=envelope,
            envelope_hash=envelope_hash,
            recovery_envelope=True,
        )

        assert result["ok"] is True
        assert result["plaintext"] == plaintext
    finally:
        _restore_test_gate(gate_id, original)


def test_recovery_envelope_not_used_on_ordinary_reads():
    """envelope_recovery gates must not trust gate_envelope on ordinary reads."""
    from services.mesh.mesh_gate_mls import decrypt_gate_message_for_local_identity

    gate_id = "__test_gate_auth_ordinary_read"
    original = _install_test_gate(gate_id, envelope_policy="envelope_recovery")
    try:
        envelope = _encrypt_envelope(gate_id, "recovery-only material")
        envelope_hash = _compute_hash(envelope)

        result = decrypt_gate_message_for_local_identity(
            gate_id=gate_id,
            epoch=1,
            ciphertext="dummyct",
            nonce="dummynonce",
            gate_envelope=envelope,
            envelope_hash=envelope_hash,
            recovery_envelope=False,
        )

        assert result["ok"] is False
        assert result["detail"] == "no active gate identity"
    finally:
        _restore_test_gate(gate_id, original)


# ── Route-level: ingest handler rejects tampered envelope ───────────────


def _build_gate_message_body(
    gate_id: str,
    *,
    gate_envelope: str = "",
    envelope_hash: str = "",
) -> dict:
    """Build a minimal gate_message body for the ingest handler."""
    return {
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
        "transport_lock": "private_strong",
        "gate_envelope": gate_envelope,
        "envelope_hash": envelope_hash,
    }


def test_ingest_rejects_mismatched_envelope_at_route(monkeypatch):
    """The gate_message ingest handler must reject tampered envelopes.

    We monkeypatch signature verification to pass so we can reach the
    envelope binding check.
    """
    import main

    # Skip signature and integrity checks to reach the envelope binding check
    monkeypatch.setattr(main, "_verify_gate_message_signed_write", lambda **kw: (True, "ok", kw.get("reply_to", "")))

    gate_id = "infonet"
    real_envelope = _encrypt_envelope(gate_id, "real content")
    envelope_hash = _compute_hash(real_envelope)
    tampered_envelope = _encrypt_envelope(gate_id, "ATTACKER CONTENT")

    body = _build_gate_message_body(
        gate_id,
        gate_envelope=tampered_envelope,
        envelope_hash=envelope_hash,
    )

    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": f"/api/mesh/gate/{gate_id}/message",
        }
    )

    result = main._submit_gate_message_envelope(request, gate_id, body)

    assert result["ok"] is False
    assert "does not match" in result["detail"]


def test_ingest_rejects_stripped_envelope_at_route(monkeypatch):
    """The ingest handler must reject when envelope_hash is present but envelope is stripped."""
    import main

    monkeypatch.setattr(main, "_verify_gate_message_signed_write", lambda **kw: (True, "ok", kw.get("reply_to", "")))

    gate_id = "infonet"
    real_envelope = _encrypt_envelope(gate_id, "real content")
    envelope_hash = _compute_hash(real_envelope)

    body = _build_gate_message_body(
        gate_id,
        gate_envelope="",  # stripped
        envelope_hash=envelope_hash,
    )

    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": f"/api/mesh/gate/{gate_id}/message",
        }
    )

    result = main._submit_gate_message_envelope(request, gate_id, body)

    assert result["ok"] is False
    assert "required" in result["detail"].lower()


def test_ingest_rejects_unsigned_envelope_at_route(monkeypatch):
    """The ingest handler must reject a durable envelope unless its hash is signed."""
    import main

    monkeypatch.setattr(main, "_verify_gate_message_signed_write", lambda **kw: (True, "ok", kw.get("reply_to", "")))

    gate_id = "infonet"
    envelope = _encrypt_envelope(gate_id, "unsigned content")
    body = _build_gate_message_body(
        gate_id,
        gate_envelope=envelope,
        envelope_hash="",
    )

    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": f"/api/mesh/gate/{gate_id}/message",
        }
    )

    result = main._submit_gate_message_envelope(request, gate_id, body)

    assert result["ok"] is False
    assert "envelope_hash" in result["detail"]


def test_ingest_accepts_legacy_message_without_hash(monkeypatch):
    """MLS-only legacy messages without envelope material remain accepted at ingest."""
    import main

    monkeypatch.setattr(main, "_verify_gate_message_signed_write", lambda **kw: (True, "ok", kw.get("reply_to", "")))
    monkeypatch.setattr(main, "_resolve_envelope_policy", lambda _gate_id: "envelope_disabled")
    # Gate access and cooldown
    from services.mesh.mesh_reputation import gate_manager
    monkeypatch.setattr(gate_manager, "can_enter", lambda *a, **kw: (True, "ok"))
    monkeypatch.setattr(main, "_check_gate_post_cooldown", lambda *a: (True, "ok"))
    monkeypatch.setattr(main, "_record_gate_post_cooldown", lambda *a: None)
    monkeypatch.setattr(gate_manager, "record_message", lambda *a: None)

    # Mock sequence advancement and gate_store
    from services.mesh import mesh_hashchain
    monkeypatch.setattr(
        mesh_hashchain.infonet,
        "validate_and_set_sequence",
        lambda node_id, seq: (True, "ok"),
    )
    monkeypatch.setattr(
        mesh_hashchain.gate_store,
        "append",
        lambda gate_id, event: {**event, "event_id": "test-ev-1"},
    )
    from services.mesh.mesh_reputation import reputation_ledger
    monkeypatch.setattr(reputation_ledger, "register_node", lambda *a: None)

    gate_id = "infonet"
    body = _build_gate_message_body(
        gate_id,
        gate_envelope="",
        envelope_hash="",
    )

    from starlette.requests import Request
    request = Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": f"/api/mesh/gate/{gate_id}/message",
        }
    )

    result = main._submit_gate_message_envelope(request, gate_id, body)
    assert result["ok"] is True


def test_ingest_rejects_envelope_always_message_without_envelope(monkeypatch):
    """envelope_always gates must never store MLS-only messages."""
    import main

    monkeypatch.setattr(main, "_verify_gate_message_signed_write", lambda **kw: (True, "ok", kw.get("reply_to", "")))
    monkeypatch.setattr(main, "_resolve_envelope_policy", lambda _gate_id: "envelope_always")

    gate_id = "infonet"
    body = _build_gate_message_body(gate_id, gate_envelope="", envelope_hash="")

    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": f"/api/mesh/gate/{gate_id}/message",
        }
    )

    result = main._submit_gate_message_envelope(request, gate_id, body)
    assert result == {"ok": False, "detail": "gate_envelope_required"}


# ── mesh_public.py router: same behavior ────────────────────────────────


def test_router_ingest_rejects_mismatched_envelope(monkeypatch):
    """The mesh_public router handler must also reject tampered envelopes."""
    import main
    from routers import mesh_public

    monkeypatch.setattr(main, "_verify_gate_message_signed_write", lambda **kw: (True, "ok", kw.get("reply_to", "")))

    gate_id = "infonet"
    real_envelope = _encrypt_envelope(gate_id, "real content")
    envelope_hash = _compute_hash(real_envelope)
    tampered_envelope = _encrypt_envelope(gate_id, "ATTACKER CONTENT")

    body = _build_gate_message_body(
        gate_id,
        gate_envelope=tampered_envelope,
        envelope_hash=envelope_hash,
    )

    from starlette.requests import Request
    request = Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": f"/api/mesh/gate/{gate_id}/message",
        }
    )

    result = mesh_public._submit_gate_message_envelope(request, gate_id, body)

    assert result["ok"] is False
    assert "does not match" in result["detail"]


# ── Normalization: envelope_hash survives ───────────────────────────────


def test_normalize_preserves_envelope_hash():
    """envelope_hash must survive normalization so it reaches the signature."""
    from services.mesh.mesh_protocol import normalize_payload

    payload = {
        "gate": "infonet",
        "ciphertext": "ct",
        "nonce": "n",
        "sender_ref": "sr",
        "format": "mls1",
        "envelope_hash": "abc123",
    }
    normalized = normalize_payload("gate_message", payload)
    assert normalized["envelope_hash"] == "abc123"


def test_normalize_omits_envelope_hash_when_empty():
    """Empty envelope_hash must not appear in normalized payload."""
    from services.mesh.mesh_protocol import normalize_payload

    payload = {
        "gate": "infonet",
        "ciphertext": "ct",
        "nonce": "n",
        "sender_ref": "sr",
        "format": "mls1",
    }
    normalized = normalize_payload("gate_message", payload)
    assert "envelope_hash" not in normalized


# ── build_signature_payload: envelope_hash is NOT stripped ──────────────


def test_envelope_hash_included_in_signature_payload():
    """envelope_hash must be included in the signature payload (not stripped)."""
    from services.mesh.mesh_crypto import build_signature_payload

    payload_with_hash = {
        "gate": "infonet",
        "ciphertext": "ct",
        "nonce": "n",
        "sender_ref": "sr",
        "format": "mls1",
        "envelope_hash": "abc123",
    }
    payload_without_hash = {
        "gate": "infonet",
        "ciphertext": "ct",
        "nonce": "n",
        "sender_ref": "sr",
        "format": "mls1",
    }

    sig_with = build_signature_payload(
        event_type="gate_message",
        node_id="!sb_test",
        sequence=1,
        payload=payload_with_hash,
    )
    sig_without = build_signature_payload(
        event_type="gate_message",
        node_id="!sb_test",
        sequence=1,
        payload=payload_without_hash,
    )

    # The signature payloads must differ when envelope_hash is present
    assert sig_with != sig_without
    assert "abc123" in sig_with
    assert "abc123" not in sig_without
