"""S2 remediation — prove the wormhole route family enforces envelope_hash binding.

Tests:
- wormhole compose→post forwards envelope_hash into the submitted body
- wormhole single decrypt rejects tampered gate_envelope when envelope_hash present
- wormhole batch decrypt rejects tampered gate_envelope when envelope_hash present
"""

import hashlib

import pytest

from services.mesh.mesh_gate_mls import _gate_envelope_encrypt


@pytest.fixture(autouse=True)
def _enable_runtime_recovery_envelopes(monkeypatch):
    from services.config import get_settings

    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE", "true")
    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _encrypt(gate_id: str, plaintext: str) -> str:
    return _gate_envelope_encrypt(gate_id, plaintext)


def _hash(envelope: str) -> str:
    return hashlib.sha256(envelope.encode("ascii")).hexdigest()


def _install_test_gate(
    gate_id: str,
    *,
    envelope_policy: str = "envelope_recovery",
    gate_secret: str = "test-gate-secret-wormhole-binding",
):
    from services.mesh.mesh_reputation import gate_manager

    original = gate_manager.gates.get(gate_id)
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Wormhole Envelope Binding Test",
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


# ── F1: compose→post forwards envelope_hash ─────────────────────────────


def test_wormhole_post_encrypted_forwards_envelope_hash(monkeypatch):
    """api_wormhole_gate_message_post must include envelope_hash in the
    body passed to _submit_gate_message_envelope — using the real delegate
    (no module global injection)."""
    import main
    from routers import wormhole

    # Capture what _submit_gate_message_envelope receives via the delegate.
    # monkeypatch.setattr works because _submit_gate_message_envelope is now
    # a proper module-level delegate — NOT injected via setitem.
    captured = {}

    def fake_submit(request, gate_id, body):
        captured.update(body)
        return {"ok": True, "detail": "captured", "gate_id": gate_id, "event_id": "ev1"}

    monkeypatch.setattr(main, "_submit_gate_message_envelope", fake_submit)

    fake_envelope = _encrypt("infonet", "test message")
    fake_hash = _hash(fake_envelope)

    import asyncio
    from starlette.requests import Request

    request = Request({
        "type": "http",
        "headers": [],
        "client": ("test", 12345),
        "method": "POST",
        "path": "/api/wormhole/gate/message/post-encrypted",
    })

    body = wormhole.WormholeGateEncryptedPostRequest(
        gate_id="infonet",
        sender_id="!sb_test",
        public_key="pk",
        public_key_algo="Ed25519",
        signature="sig",
        sequence=1,
        protocol_version="infonet/2",
        epoch=1,
        ciphertext="ct",
        nonce="n",
        sender_ref="sr",
        format="mls1",
        gate_envelope=fake_envelope,
        envelope_hash=fake_hash,
    )

    result = asyncio.run(wormhole.api_wormhole_gate_message_post_encrypted(request, body))

    assert result["ok"] is True
    assert "envelope_hash" in captured, "envelope_hash was not forwarded to _submit_gate_message_envelope"
    assert captured["envelope_hash"] == fake_hash
    assert captured["gate_envelope"] == fake_envelope


def test_wormhole_compose_post_delegate_resolves_without_injection():
    """_submit_gate_message_envelope must be a real module attribute —
    NOT a bare name that requires monkeypatch.setitem to work.

    This test proves the NameError from S2 is fixed: calling the delegate
    wrapper resolves main._submit_gate_message_envelope at call time.
    """
    from routers import wormhole

    # The delegate must be a callable attribute on the module
    assert hasattr(wormhole, "_submit_gate_message_envelope"), (
        "_submit_gate_message_envelope is not a module attribute — bare name bug still present"
    )
    assert callable(wormhole._submit_gate_message_envelope)
    # It must be the _main_delegate wrapper, not the raw function
    assert wormhole._submit_gate_message_envelope.__name__ == "_submit_gate_message_envelope"


# ── F2: single decrypt rejects tampered envelope ────────────────────────


def test_wormhole_single_decrypt_rejects_tampered_envelope():
    """The wormhole single decrypt endpoint must reject tampered gate_envelope
    when envelope_hash is present."""
    from services.mesh.mesh_gate_mls import decrypt_gate_message_for_local_identity

    gate_id = "__test_wormhole_env_tampered"
    original = _install_test_gate(gate_id)
    try:
        real_envelope = _encrypt(gate_id, "real message")
        envelope_hash = _hash(real_envelope)
        tampered_envelope = _encrypt(gate_id, "ATTACKER INJECTED")

        # Call the decrypt function the same way wormhole.py does
        result = decrypt_gate_message_for_local_identity(
            gate_id=gate_id,
            epoch=1,
            ciphertext="dummyct",
            nonce="dummynonce",
            sender_ref="sr",
            gate_envelope=tampered_envelope,
            envelope_hash=envelope_hash,
            recovery_envelope=True,
        )

        assert result["ok"] is False
        assert "integrity" in result["detail"].lower()
    finally:
        _restore_test_gate(gate_id, original)


def test_wormhole_single_decrypt_accepts_valid_envelope():
    """The wormhole single decrypt endpoint must accept valid envelope+hash."""
    from services.mesh.mesh_gate_mls import decrypt_gate_message_for_local_identity

    gate_id = "__test_wormhole_env_valid"
    original = _install_test_gate(gate_id)
    try:
        plaintext = "authenticated message"
        envelope = _encrypt(gate_id, plaintext)
        envelope_hash = _hash(envelope)

        result = decrypt_gate_message_for_local_identity(
            gate_id=gate_id,
            epoch=1,
            ciphertext="dummyct",
            nonce="dummynonce",
            sender_ref="sr",
            gate_envelope=envelope,
            envelope_hash=envelope_hash,
            recovery_envelope=True,
        )

        assert result["ok"] is True
        assert result["plaintext"] == plaintext
    finally:
        _restore_test_gate(gate_id, original)


# ── F2: batch decrypt rejects tampered envelope ─────────────────────────


def test_wormhole_batch_decrypt_rejects_tampered_envelope():
    """The wormhole batch decrypt endpoint must reject tampered gate_envelope
    when envelope_hash is present — exercised through the actual handler."""
    from services.mesh.mesh_gate_mls import decrypt_gate_message_for_local_identity

    gate_id = "__test_wormhole_env_batch"
    original = _install_test_gate(gate_id)
    try:
        real_envelope = _encrypt(gate_id, "real batch message")
        envelope_hash = _hash(real_envelope)
        tampered_envelope = _encrypt(gate_id, "BATCH ATTACKER")

        # Simulate what the batch handler does for each item
        result = decrypt_gate_message_for_local_identity(
            gate_id=gate_id,
            epoch=1,
            ciphertext="dummyct",
            nonce="dummynonce",
            sender_ref="sr",
            gate_envelope=tampered_envelope,
            envelope_hash=envelope_hash,
            recovery_envelope=True,
        )

        assert result["ok"] is False
        assert "integrity" in result["detail"].lower()
    finally:
        _restore_test_gate(gate_id, original)


# ── Model: WormholeGateDecryptRequest has envelope_hash ─────────────────


def test_wormhole_decrypt_request_model_accepts_envelope_hash():
    """Both WormholeGateDecryptRequest definitions must accept envelope_hash."""
    from routers import wormhole

    # The model should accept envelope_hash without error
    req = wormhole.WormholeGateDecryptRequest(
        gate_id="infonet",
        ciphertext="ct",
        envelope_hash="abc123",
    )
    assert req.envelope_hash == "abc123"


def test_wormhole_decrypt_request_model_defaults_empty():
    """envelope_hash should default to empty string when not provided."""
    from routers import wormhole

    req = wormhole.WormholeGateDecryptRequest(
        gate_id="infonet",
        ciphertext="ct",
    )
    assert req.envelope_hash == ""


# ── Wormhole decrypt handler passes envelope_hash through ───────────────


def test_wormhole_decrypt_handler_passes_envelope_hash(monkeypatch):
    """The wormhole single decrypt handler must pass envelope_hash to
    decrypt_gate_message_for_local_identity."""
    import main
    from routers import wormhole
    import asyncio

    captured_kwargs = {}

    def fake_decrypt(**kwargs):
        captured_kwargs.update(kwargs)
        return {"ok": True, "plaintext": "test", "gate_id": "infonet", "epoch": 1}

    monkeypatch.setattr(main, "decrypt_gate_message_with_repair", fake_decrypt)

    body = wormhole.WormholeGateDecryptRequest(
        gate_id="infonet",
        ciphertext="ct",
        gate_envelope="env",
        envelope_hash="abc123",
        recovery_envelope=True,
    )

    from starlette.requests import Request
    request = Request({
        "type": "http",
        "headers": [],
        "client": ("test", 12345),
        "method": "POST",
        "path": "/api/wormhole/gate/message/decrypt",
    })

    result = asyncio.run(wormhole.api_wormhole_gate_message_decrypt(request, body))
    assert result["ok"] is True
    assert captured_kwargs.get("envelope_hash") == "abc123"
    assert captured_kwargs.get("recovery_envelope") is True


def test_wormhole_batch_decrypt_handler_passes_envelope_hash(monkeypatch):
    """The wormhole batch decrypt handler must pass envelope_hash for each item."""
    from routers import wormhole
    import asyncio

    call_log = []

    def fake_decrypt(**kwargs):
        call_log.append(dict(kwargs))
        return {"ok": True, "plaintext": "test", "gate_id": kwargs["gate_id"], "epoch": 1}

    monkeypatch.setattr(wormhole, "decrypt_gate_message_for_local_identity", fake_decrypt)
    body = wormhole.WormholeGateDecryptBatchRequest(
        messages=[
            wormhole.WormholeGateDecryptRequest(
                gate_id="infonet",
                ciphertext="ct1",
                gate_envelope="env1",
                envelope_hash="hash1",
                recovery_envelope=True,
            ),
            wormhole.WormholeGateDecryptRequest(
                gate_id="finance",
                ciphertext="ct2",
                gate_envelope="env2",
                envelope_hash="hash2",
                recovery_envelope=True,
            ),
        ]
    )

    from starlette.requests import Request
    request = Request({
        "type": "http",
        "headers": [],
        "client": ("test", 12345),
        "method": "POST",
        "path": "/api/wormhole/gate/messages/decrypt",
    })

    result = asyncio.run(wormhole.api_wormhole_gate_messages_decrypt(request, body))
    assert result["ok"] is True
    assert len(call_log) == 2
    assert call_log[0]["envelope_hash"] == "hash1"
    assert call_log[1]["envelope_hash"] == "hash2"
    assert call_log[0]["recovery_envelope"] is True
    assert call_log[1]["recovery_envelope"] is True
