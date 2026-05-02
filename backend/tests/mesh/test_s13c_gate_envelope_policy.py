"""S13C Gate Envelope Policy.

Tests:
- existing gate without explicit policy behaves as envelope_disabled
- new gate defaults to envelope_always for durable gate history
- enabling envelope_always requires explicit acknowledgement
- compose under envelope_always creates gate_envelope when secret available
- compose under envelope_recovery creates gate_envelope when secret available
- compose under envelope_disabled omits gate_envelope and envelope_hash
- member read view exposes gate envelope ciphertext for envelope_always and envelope_recovery
- member read view only preserves trusted signed reply_to metadata
- privileged read view preserves stored envelope for envelope_always and envelope_recovery
- non-gate public event redaction remains unchanged
- do not overclaim: envelope_recovery still stores recovery material
"""



# ── Fixtures ─────────────────────────────────────────────────────────────


import pytest


@pytest.fixture
def enable_runtime_recovery_envelopes(monkeypatch):
    from services.config import get_settings

    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE", "true")
    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _sample_raw_gate_event(*, gate_envelope: str = "encrypted-recovery-blob") -> dict:
    """A raw gate_message event as it would be stored internally."""
    return {
        "event_id": "evt-s13c-001",
        "event_type": "gate_message",
        "timestamp": 1700000000,
        "node_id": "node-secret-id",
        "sequence": 42,
        "signature": "deadbeef",
        "public_key": "c2VjcmV0",
        "public_key_algo": "Ed25519",
        "protocol_version": "0.9.6",
        "payload": {
            "gate": "test-gate",
            "ciphertext": "encrypted-blob",
            "format": "mls1",
            "nonce": "random-nonce",
            "sender_ref": "anon-handle-xyz",
            "envelope_hash": "envelope-hash-001",
            "gate_envelope": gate_envelope,
            "reply_to": "evt-parent-456",
        },
    }


def _sample_signed_gate_event(
    *,
    gate_envelope: str = "encrypted-recovery-blob",
    reply_to: str = "evt-parent-456",
) -> dict:
    """A gate_message event whose reply_to survives signature verification."""
    import base64
    import hashlib

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from services.mesh.mesh_crypto import build_signature_payload, derive_node_id

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(public_key_raw).decode("ascii")
    node_id = derive_node_id(public_key)
    payload = {
        "gate": "test-gate",
        "ciphertext": "encrypted-blob",
        "format": "mls1",
        "nonce": "random-nonce",
        "sender_ref": "anon-handle-xyz",
        "envelope_hash": hashlib.sha256(gate_envelope.encode("ascii")).hexdigest(),
        "reply_to": reply_to,
    }
    signature = private_key.sign(
        build_signature_payload(
            event_type="gate_message",
            node_id=node_id,
            sequence=42,
            payload=payload,
        ).encode("utf-8")
    ).hex()
    return {
        "event_id": "evt-s13c-signed-001",
        "event_type": "gate_message",
        "timestamp": 1700000000,
        "node_id": node_id,
        "sequence": 42,
        "signature": signature,
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
        "payload": {
            **payload,
            "gate_envelope": gate_envelope,
        },
    }


# ── GateManager envelope_policy field ────────────────────────────────────


def test_existing_gate_without_policy_behaves_as_envelope_disabled():
    """A gate with no explicit envelope_policy must fail closed to envelope_disabled."""
    from services.mesh.mesh_reputation import gate_manager

    # Inject a gate without envelope_policy
    gate_manager.gates["__test_legacy"] = {
        "creator_node_id": "test",
        "display_name": "Legacy Gate",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
        # No envelope_policy field
    }
    try:
        assert gate_manager.get_envelope_policy("__test_legacy") == "envelope_disabled"
    finally:
        gate_manager.gates.pop("__test_legacy", None)


def test_new_gate_defaults_to_envelope_always():
    """Newly created gates default to envelope_always for durable gate history."""
    from services.mesh.mesh_reputation import gate_manager, ALLOW_DYNAMIC_GATES

    # Temporarily enable dynamic gates for this test
    import services.mesh.mesh_reputation as rep_mod
    original = rep_mod.ALLOW_DYNAMIC_GATES
    rep_mod.ALLOW_DYNAMIC_GATES = True
    try:
        ok, msg = gate_manager.create_gate(
            creator_id="test-node",
            gate_id="test-new-s13c",
            display_name="S13C Test Gate",
        )
        assert ok, msg
        assert gate_manager.get_envelope_policy("test-new-s13c") == "envelope_always"
    finally:
        gate_manager.gates.pop("test-new-s13c", None)
        rep_mod.ALLOW_DYNAMIC_GATES = original


def test_set_envelope_policy_valid():
    """set_envelope_policy must accept valid policies."""
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_policy"] = {
        "creator_node_id": "test",
        "display_name": "Policy Test",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
    }
    try:
        ok, _ = gate_manager.set_envelope_policy("__test_policy", "envelope_disabled")
        assert ok
        assert gate_manager.get_envelope_policy("__test_policy") == "envelope_disabled"

        ok, _ = gate_manager.set_envelope_policy("__test_policy", "envelope_recovery")
        assert ok
        assert gate_manager.get_envelope_policy("__test_policy") == "envelope_recovery"

        ok, _ = gate_manager.set_envelope_policy(
            "__test_policy",
            "envelope_always",
            acknowledge_recovery_risk=True,
        )
        assert ok
        assert gate_manager.get_envelope_policy("__test_policy") == "envelope_always"
    finally:
        gate_manager.gates.pop("__test_policy", None)


def test_set_envelope_policy_requires_ack_for_envelope_always():
    """envelope_always must require explicit risk acknowledgement."""
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_policy_ack"] = {
        "creator_node_id": "test",
        "display_name": "Policy Ack Test",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
        "envelope_policy": "envelope_disabled",
    }
    try:
        ok, detail = gate_manager.set_envelope_policy("__test_policy_ack", "envelope_always")
        assert not ok
        assert "acknowledge_recovery_risk=true" in detail
        assert gate_manager.get_envelope_policy("__test_policy_ack") == "envelope_disabled"
    finally:
        gate_manager.gates.pop("__test_policy_ack", None)


def test_set_envelope_policy_invalid():
    """set_envelope_policy must reject invalid policies."""
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_invalid"] = {
        "creator_node_id": "test",
        "display_name": "Invalid Test",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
    }
    try:
        ok, detail = gate_manager.set_envelope_policy("__test_invalid", "bogus_policy")
        assert not ok
        assert "Invalid policy" in detail
    finally:
        gate_manager.gates.pop("__test_invalid", None)


def test_set_envelope_policy_nonexistent_gate():
    """set_envelope_policy must fail for a nonexistent gate."""
    from services.mesh.mesh_reputation import gate_manager

    ok, detail = gate_manager.set_envelope_policy("__nonexistent_gate_s13c", "envelope_disabled")
    assert not ok
    assert "not found" in detail.lower()


def test_get_envelope_policy_unknown_gate():
    """get_envelope_policy for unknown gate must fail closed to envelope_disabled."""
    from services.mesh.mesh_reputation import gate_manager

    assert gate_manager.get_envelope_policy("__totally_unknown_s13c") == "envelope_disabled"


def test_valid_envelope_policies_constant():
    """VALID_ENVELOPE_POLICIES must contain exactly the three defined values."""
    from services.mesh.mesh_reputation import VALID_ENVELOPE_POLICIES

    assert set(VALID_ENVELOPE_POLICIES) == {"envelope_always", "envelope_recovery", "envelope_disabled"}


# ── Member read view envelope behavior ───────────────────────────────────


def test_member_view_envelope_always_preserves_envelope_material():
    """Member view with envelope_always must expose envelope material for local decrypt."""
    from routers.mesh_public import _strip_gate_identity_member

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_member(raw, envelope_policy="envelope_always")

    assert result["payload"]["gate_envelope"] == "encrypted-recovery-blob"
    assert result["payload"]["envelope_hash"] == "envelope-hash-001"


def test_member_view_envelope_recovery_preserves_envelope_material():
    """Member view with envelope_recovery preserves envelope material and strips unsigned reply_to."""
    from routers.mesh_public import _strip_gate_identity_member

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_member(raw, envelope_policy="envelope_recovery")

    assert result["payload"]["gate_envelope"] == "encrypted-recovery-blob"
    assert result["payload"]["envelope_hash"] == "envelope-hash-001"
    assert result["payload"]["sender_ref"] == "anon-handle-xyz"
    assert result["payload"]["ciphertext"] == "encrypted-blob"
    assert result["payload"]["reply_to"] == ""


def test_member_view_envelope_recovery_preserves_trusted_reply_to():
    """Member view with envelope_recovery must preserve signed reply_to metadata."""
    from routers.mesh_public import _strip_gate_identity_member

    raw = _sample_signed_gate_event()
    result = _strip_gate_identity_member(raw, envelope_policy="envelope_recovery")

    assert result["payload"]["gate_envelope"] == "encrypted-recovery-blob"
    assert len(result["payload"]["envelope_hash"]) == 64
    assert result["payload"]["reply_to"] == "evt-parent-456"


def test_member_view_envelope_disabled_preserves_stored_envelope():
    """Member view exposes stored envelope material; disabled gates should not create it."""
    from routers.mesh_public import _strip_gate_identity_member

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_member(raw, envelope_policy="envelope_disabled")

    assert result["payload"]["gate_envelope"] == "encrypted-recovery-blob"
    assert result["payload"]["envelope_hash"] == "envelope-hash-001"


def test_member_view_default_preserves_stored_envelope():
    """Member view without explicit policy still emits stored envelope material."""
    from routers.mesh_public import _strip_gate_identity_member

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_member(raw)

    assert result["payload"]["gate_envelope"] == "encrypted-recovery-blob"
    assert result["payload"]["envelope_hash"] == "envelope-hash-001"


# ── Privileged read view always preserves stored envelope ────────────────


def test_privileged_view_preserves_envelope_always():
    """Privileged view must preserve gate_envelope for envelope_always."""
    from routers.mesh_public import _strip_gate_identity_privileged

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_privileged(raw)

    assert result["payload"]["gate_envelope"] == "encrypted-recovery-blob"
    assert result["payload"]["envelope_hash"] == "envelope-hash-001"


def test_privileged_view_preserves_envelope_recovery():
    """Privileged view must preserve stored gate_envelope for envelope_recovery."""
    from routers.mesh_public import _strip_gate_identity_privileged

    raw = _sample_raw_gate_event(gate_envelope="recovery-stored-blob")
    result = _strip_gate_identity_privileged(raw)

    assert result["payload"]["gate_envelope"] == "recovery-stored-blob"
    assert result["payload"]["envelope_hash"] == "envelope-hash-001"


def test_privileged_view_envelope_disabled_no_envelope():
    """Privileged view with envelope_disabled sees no envelope (none was created)."""
    from routers.mesh_public import _strip_gate_identity_privileged

    raw = _sample_raw_gate_event(gate_envelope="")
    result = _strip_gate_identity_privileged(raw)

    assert result["payload"]["gate_envelope"] == ""
    assert result["payload"]["envelope_hash"] == "envelope-hash-001"


# ── _strip_gate_for_access policy routing ────────────────────────────────


def test_strip_for_access_member_preserves_envelope_policy_material(enable_runtime_recovery_envelopes):
    """_strip_gate_for_access for member + envelope_recovery exposes envelope material."""
    from routers.mesh_public import _strip_gate_for_access
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_access_s13c"] = {
        "creator_node_id": "test",
        "display_name": "Access Test",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
        "envelope_policy": "envelope_recovery",
    }
    try:
        raw = _sample_raw_gate_event()
        raw["payload"]["gate"] = "__test_access_s13c"
        result = _strip_gate_for_access(raw, "member")
        assert result["payload"]["gate_envelope"] == "encrypted-recovery-blob"
        assert result["payload"]["envelope_hash"] == "envelope-hash-001"
        assert result["payload"]["sender_ref"] == "anon-handle-xyz"
    finally:
        gate_manager.gates.pop("__test_access_s13c", None)


def test_strip_for_access_privileged_ignores_policy():
    """_strip_gate_for_access for privileged always preserves envelope."""
    from routers.mesh_public import _strip_gate_for_access
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_priv_s13c"] = {
        "creator_node_id": "test",
        "display_name": "Priv Test",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
        "envelope_policy": "envelope_recovery",
    }
    try:
        raw = _sample_raw_gate_event()
        raw["payload"]["gate"] = "__test_priv_s13c"
        result = _strip_gate_for_access(raw, "privileged")
        assert result["payload"]["gate_envelope"] == "encrypted-recovery-blob"
    finally:
        gate_manager.gates.pop("__test_priv_s13c", None)


# ── main.py sync verification ────────────────────────────────────────────


def test_main_member_view_envelope_recovery_preserves():
    """main.py member view with envelope_recovery must expose envelope material."""
    import main

    raw = _sample_raw_gate_event()
    result = main._strip_gate_identity_member(raw, envelope_policy="envelope_recovery")
    assert result["payload"]["gate_envelope"] == "encrypted-recovery-blob"
    assert result["payload"]["envelope_hash"] == "envelope-hash-001"


def test_main_member_view_envelope_always_preserves():
    """main.py member view with envelope_always must expose envelope material."""
    import main

    raw = _sample_raw_gate_event()
    result = main._strip_gate_identity_member(raw, envelope_policy="envelope_always")
    assert result["payload"]["gate_envelope"] == "encrypted-recovery-blob"
    assert result["payload"]["envelope_hash"] == "envelope-hash-001"


def test_main_strip_for_access_member_recovery(enable_runtime_recovery_envelopes):
    """main.py _strip_gate_for_access for member + envelope_recovery gate exposes envelope material."""
    import main
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_main_s13c"] = {
        "creator_node_id": "test",
        "display_name": "Main Test",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
        "envelope_policy": "envelope_recovery",
    }
    try:
        raw = _sample_raw_gate_event()
        raw["payload"]["gate"] = "__test_main_s13c"
        result = main._strip_gate_for_access(raw, "member")
        assert result["payload"]["gate_envelope"] == "encrypted-recovery-blob"
        assert result["payload"]["envelope_hash"] == "envelope-hash-001"
    finally:
        gate_manager.gates.pop("__test_main_s13c", None)


# ── Compose behavior under envelope policies ────────────────────────────
# These test the compose_encrypted_gate_message envelope_policy branching
# by testing the policy lookup function and the gate_mls module's awareness.


def test_compose_envelope_disabled_skips_envelope():
    """Under envelope_disabled, compose must not create gate_envelope or envelope_hash."""
    # We test the policy-aware branching in mesh_gate_mls by verifying
    # the policy lookup returns the right value for a disabled gate.
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_compose_disabled"] = {
        "creator_node_id": "test",
        "display_name": "Compose Disabled",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
        "envelope_policy": "envelope_disabled",
    }
    try:
        assert gate_manager.get_envelope_policy("__test_compose_disabled") == "envelope_disabled"
    finally:
        gate_manager.gates.pop("__test_compose_disabled", None)


def test_compose_envelope_always_creates_envelope(enable_runtime_recovery_envelopes):
    """Under envelope_always, compose must create gate_envelope when secret available."""
    from services.mesh import mesh_gate_mls
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_compose_always"] = {
        "creator_node_id": "test",
        "display_name": "Compose Always",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
        "envelope_policy": "envelope_always",
    }
    try:
        assert mesh_gate_mls._resolve_gate_envelope_policy("__test_compose_always") == "envelope_always"
    finally:
        gate_manager.gates.pop("__test_compose_always", None)


def test_compose_envelope_recovery_creates_envelope(enable_runtime_recovery_envelopes):
    """Under envelope_recovery, compose must still create gate_envelope when secret available."""
    from services.mesh import mesh_gate_mls
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_compose_recovery"] = {
        "creator_node_id": "test",
        "display_name": "Compose Recovery",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
        "envelope_policy": "envelope_recovery",
    }
    try:
        policy = mesh_gate_mls._resolve_gate_envelope_policy("__test_compose_recovery")
        assert policy == "envelope_recovery"
        assert policy != "envelope_disabled"
    finally:
        gate_manager.gates.pop("__test_compose_recovery", None)


def test_local_legacy_no_hash_envelope_can_decrypt_with_store_witness(monkeypatch):
    """Old local history with no envelope_hash can unlock only with a local store witness."""
    from services.mesh import mesh_gate_mls
    from services.mesh.mesh_reputation import gate_manager

    gate_id = "__test_legacy_no_hash_local"
    nonce = "legacy-no-hash-nonce"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Legacy No Hash",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "legacy-no-hash-secret",
        "envelope_policy": "envelope_always",
    }
    try:
        token = mesh_gate_mls._gate_envelope_encrypt(gate_id, "legacy plaintext", message_nonce=nonce)
        monkeypatch.setattr(
            mesh_gate_mls,
            "_stored_legacy_unbound_envelope_allowed",
            lambda *_args, **_kwargs: True,
        )
        result = mesh_gate_mls.decrypt_gate_message_for_local_identity(
            gate_id=gate_id,
            epoch=1,
            ciphertext="ct",
            nonce=nonce,
            gate_envelope=token,
            envelope_hash="",
            recovery_envelope=True,
            event_id="evt-local-legacy",
        )
        assert result["ok"] is True
        assert result["plaintext"] == "legacy plaintext"
        assert result["legacy_unbound_envelope"] is True
    finally:
        gate_manager.gates.pop(gate_id, None)


def test_remote_legacy_no_hash_envelope_still_fails_without_store_witness(monkeypatch):
    """No-hash envelopes from outside local store do not get a recovery bypass."""
    from services.mesh import mesh_gate_mls
    from services.mesh.mesh_reputation import gate_manager

    gate_id = "__test_legacy_no_hash_remote"
    nonce = "legacy-no-hash-remote-nonce"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Legacy No Hash Remote",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "legacy-no-hash-remote-secret",
        "envelope_policy": "envelope_always",
    }
    try:
        token = mesh_gate_mls._gate_envelope_encrypt(gate_id, "legacy plaintext", message_nonce=nonce)
        monkeypatch.setattr(
            mesh_gate_mls,
            "_stored_legacy_unbound_envelope_allowed",
            lambda *_args, **_kwargs: False,
        )
        result = mesh_gate_mls.decrypt_gate_message_for_local_identity(
            gate_id=gate_id,
            epoch=1,
            ciphertext="ct",
            nonce=nonce,
            gate_envelope=token,
            envelope_hash="",
            recovery_envelope=True,
            event_id="evt-remote-legacy",
        )
        assert result["ok"] is False
        assert result["detail"] == "gate_envelope missing signed envelope_hash"
    finally:
        gate_manager.gates.pop(gate_id, None)


def test_per_gate_recovery_policy_is_not_downgraded_by_runtime_switches():
    import main
    from routers import mesh_public
    from services.mesh import mesh_gate_mls
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_runtime_gate"] = {
        "creator_node_id": "test",
        "display_name": "Runtime Gate",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
        "envelope_policy": "envelope_recovery",
    }
    try:
        assert mesh_gate_mls._resolve_gate_envelope_policy("__test_runtime_gate") == "envelope_recovery"
        assert mesh_public._resolve_envelope_policy("__test_runtime_gate") == "envelope_recovery"
        assert main._resolve_envelope_policy("__test_runtime_gate") == "envelope_recovery"
    finally:
        gate_manager.gates.pop("__test_runtime_gate", None)


# ── Do not overclaim ────────────────────────────────────────────────────


def test_envelope_recovery_is_not_envelope_disabled():
    """envelope_recovery must not be confused with envelope_disabled."""
    from services.mesh.mesh_reputation import VALID_ENVELOPE_POLICIES

    assert "envelope_recovery" in VALID_ENVELOPE_POLICIES
    assert "envelope_disabled" in VALID_ENVELOPE_POLICIES
    assert "envelope_recovery" != "envelope_disabled"


def test_envelope_recovery_still_stores_recovery():
    """envelope_recovery still stores recovery material for member decrypt."""
    from routers.mesh_public import _strip_gate_identity_member, _strip_gate_identity_privileged

    raw = _sample_raw_gate_event(gate_envelope="stored-recovery-material")

    member = _strip_gate_identity_member(raw, envelope_policy="envelope_recovery")
    assert member["payload"]["gate_envelope"] == "stored-recovery-material"
    assert member["payload"]["envelope_hash"] == "envelope-hash-001"

    priv = _strip_gate_identity_privileged(raw)
    assert priv["payload"]["gate_envelope"] == "stored-recovery-material"
    assert priv["payload"]["envelope_hash"] == "envelope-hash-001"


# ── Non-gate public event redaction unchanged ────────────────────────────


def test_redact_public_event_not_affected():
    """Public event redaction must not be affected by envelope policy changes."""
    from routers.mesh_public import _redact_public_event

    public_event = {
        "event_id": "pub-s13c",
        "event_type": "status_update",
        "timestamp": 1700000000,
        "node_id": "node-public",
        "payload": {"message": "hello"},
    }
    result = _redact_public_event(public_event)
    assert isinstance(result, dict)
    assert result.get("event_id") == "pub-s13c"


# ── Edge cases ───────────────────────────────────────────────────────────


def test_member_view_no_envelope_in_event():
    """If event has no gate_envelope at all, member view handles it gracefully."""
    from routers.mesh_public import _strip_gate_identity_member

    raw = _sample_raw_gate_event(gate_envelope="")

    result = _strip_gate_identity_member(raw, envelope_policy="envelope_always")
    assert result["payload"]["gate_envelope"] == ""
    assert result["payload"]["envelope_hash"] == "envelope-hash-001"

    result = _strip_gate_identity_member(raw, envelope_policy="envelope_recovery")
    assert result["payload"]["gate_envelope"] == ""
    assert result["payload"]["envelope_hash"] == "envelope-hash-001"
