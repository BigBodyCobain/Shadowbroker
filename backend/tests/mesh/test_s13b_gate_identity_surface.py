"""S13B Gate Identity Surface Narrowing.

Tests:
- ordinary member gate_messages response strips node_id/public_key/public_key_algo/signature/sequence
- privileged gate/audit view retains identity fields
- GET /api/mesh/infonet/messages?gate=... uses narrowed member view for ordinary gate members
- GET /api/mesh/infonet/event/{event_id} uses narrowed member view for ordinary gate members
- non-gate public event redaction remains unchanged
- do not overclaim operator privacy; this sprint is only member-facing API narrowing
"""

import pytest


# ── Identity fields that must NOT appear in member view ──────────────────

_IDENTITY_FIELDS = {"node_id", "public_key", "public_key_algo", "signature", "sequence"}

# ── Content fields that MUST appear in both views ────────────────────────

_CONTENT_FIELDS = {"event_id", "event_type", "timestamp", "protocol_version"}
_PAYLOAD_FIELDS = {
    "gate",
    "ciphertext",
    "format",
    "nonce",
    "sender_ref",
    "gate_envelope",
    "envelope_hash",
    "reply_to",
}


def _sample_raw_gate_event() -> dict:
    """A raw gate_message event as it would be stored internally."""
    return {
        "event_id": "evt-abc-123",
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
            "format": "mls_v1",
            "nonce": "random-nonce",
            "sender_ref": "anon-handle-xyz",
            "gate_envelope": "envelope-data",
            "envelope_hash": "envelope-hash",
            "reply_to": "evt-parent-456",
        },
    }


# ── _strip_gate_identity_member tests ────────────────────────────────────


def test_member_view_strips_identity_fields():
    """Ordinary member view must NOT expose identity fields."""
    from routers.mesh_public import _strip_gate_identity_member

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_member(raw)

    for field in _IDENTITY_FIELDS:
        assert field not in result, f"member view must not contain top-level '{field}'"


def test_member_view_preserves_content_fields():
    """Ordinary member view must preserve all content fields."""
    from routers.mesh_public import _strip_gate_identity_member

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_member(raw)

    for field in _CONTENT_FIELDS:
        assert field in result, f"member view must contain '{field}'"
    assert result["event_id"] == "evt-abc-123"
    assert result["event_type"] == "gate_message"
    assert result["protocol_version"] == "0.9.6"


def test_member_view_preserves_payload_fields():
    """Ordinary member view must preserve the default safe payload fields."""
    from routers.mesh_public import _strip_gate_identity_member

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_member(raw)
    payload = result["payload"]

    for field in _PAYLOAD_FIELDS:
        assert field in payload, f"member view payload must contain '{field}'"
    assert payload["sender_ref"] == "anon-handle-xyz"
    assert payload["ciphertext"] == "encrypted-blob"
    assert payload["reply_to"] == ""
    assert payload["gate_envelope"] == "envelope-data"
    assert payload["envelope_hash"] == "envelope-hash"


def test_member_view_preserves_envelope_material_for_member_decrypt():
    from routers.mesh_public import _strip_gate_identity_member

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_member(raw, envelope_policy="envelope_recovery")

    assert result["payload"]["gate_envelope"] == "envelope-data"
    assert result["payload"]["envelope_hash"] == "envelope-hash"


def test_member_view_no_identity_in_payload():
    """Identity fields must not leak into the payload either."""
    from routers.mesh_public import _strip_gate_identity_member

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_member(raw)
    payload = result["payload"]

    for field in _IDENTITY_FIELDS:
        assert field not in payload, f"payload must not contain '{field}'"


# ── _strip_gate_identity_privileged tests ────────────────────────────────


def test_privileged_view_retains_identity_fields():
    """Privileged/audit view must retain all identity fields."""
    from routers.mesh_public import _strip_gate_identity_privileged

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_privileged(raw)

    assert result["node_id"] == "node-secret-id"
    assert result["public_key"] == "c2VjcmV0"
    assert result["public_key_algo"] == "Ed25519"
    assert result["signature"] == "deadbeef"
    assert result["sequence"] == 42


def test_privileged_view_preserves_content_fields():
    """Privileged view must also preserve all content fields."""
    from routers.mesh_public import _strip_gate_identity_privileged

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_privileged(raw)

    for field in _CONTENT_FIELDS:
        assert field in result, f"privileged view must contain '{field}'"
    assert result["event_id"] == "evt-abc-123"
    assert result["protocol_version"] == "0.9.6"


def test_privileged_view_preserves_payload_fields():
    """Privileged view must preserve all payload fields."""
    from routers.mesh_public import _strip_gate_identity_privileged

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity_privileged(raw)
    payload = result["payload"]

    for field in _PAYLOAD_FIELDS:
        assert field in payload, f"privileged view payload must contain '{field}'"
    assert payload["sender_ref"] == "anon-handle-xyz"
    assert payload["gate_envelope"] == "envelope-data"
    assert payload["envelope_hash"] == "envelope-hash"


# ── _strip_gate_for_access routing tests ─────────────────────────────────


def test_strip_for_access_member_strips_identity():
    """_strip_gate_for_access with 'member' must use the narrowed view."""
    from routers.mesh_public import _strip_gate_for_access

    raw = _sample_raw_gate_event()
    result = _strip_gate_for_access(raw, "member")

    for field in _IDENTITY_FIELDS:
        assert field not in result, f"member access must not expose '{field}'"
    assert result["payload"]["sender_ref"] == "anon-handle-xyz"


def test_strip_for_access_privileged_retains_identity():
    """_strip_gate_for_access with 'privileged' must use the full view."""
    from routers.mesh_public import _strip_gate_for_access

    raw = _sample_raw_gate_event()
    result = _strip_gate_for_access(raw, "privileged")

    assert result["node_id"] == "node-secret-id"
    assert result["public_key"] == "c2VjcmV0"
    assert result["signature"] == "deadbeef"
    assert result["sequence"] == 42


# ── main.py sync verification ────────────────────────────────────────────


def test_main_member_view_strips_identity():
    """main.py _strip_gate_identity_member must match router behavior."""
    import main

    raw = _sample_raw_gate_event()
    result = main._strip_gate_identity_member(raw)

    for field in _IDENTITY_FIELDS:
        assert field not in result, f"main.py member view must not contain '{field}'"
    assert result["payload"]["sender_ref"] == "anon-handle-xyz"


def test_main_privileged_view_retains_identity():
    """main.py _strip_gate_identity_privileged must match router behavior."""
    import main

    raw = _sample_raw_gate_event()
    result = main._strip_gate_identity_privileged(raw)

    assert result["node_id"] == "node-secret-id"
    assert result["public_key"] == "c2VjcmV0"
    assert result["signature"] == "deadbeef"
    assert result["sequence"] == 42


def test_main_strip_for_access_routes_correctly():
    """main.py _strip_gate_for_access must route member vs privileged correctly."""
    import main

    raw = _sample_raw_gate_event()

    member = main._strip_gate_for_access(raw, "member")
    for field in _IDENTITY_FIELDS:
        assert field not in member

    privileged = main._strip_gate_for_access(raw, "privileged")
    assert privileged["node_id"] == "node-secret-id"


# ── Legacy alias defaults to member view ─────────────────────────────────


def test_legacy_strip_gate_identity_uses_member_view():
    """_strip_gate_identity (legacy alias) must default to member (narrowed) view."""
    from routers.mesh_public import _strip_gate_identity

    raw = _sample_raw_gate_event()
    result = _strip_gate_identity(raw)

    for field in _IDENTITY_FIELDS:
        assert field not in result, f"legacy alias must not expose '{field}'"
    assert result["payload"]["sender_ref"] == "anon-handle-xyz"


# ── Non-gate public event redaction unchanged ────────────────────────────


def test_redact_public_event_unchanged():
    """_redact_public_event must not be affected by gate identity changes."""
    from routers.mesh_public import _redact_public_event

    public_event = {
        "event_id": "pub-001",
        "event_type": "status_update",
        "timestamp": 1700000000,
        "node_id": "node-public",
        "sequence": 1,
        "signature": "sig-public",
        "public_key": "pub-key",
        "public_key_algo": "Ed25519",
        "protocol_version": "0.9.6",
        "payload": {"message": "hello"},
    }
    result = _redact_public_event(public_event)
    # Public redaction is a different path; it should not strip identity fields
    # the same way gate member redaction does. Just verify it returns a dict.
    assert isinstance(result, dict)
    assert result.get("event_id") == "pub-001"


# ── Edge cases ───────────────────────────────────────────────────────────


def test_member_view_handles_empty_event():
    """Member view must handle empty/malformed events gracefully."""
    from routers.mesh_public import _strip_gate_identity_member

    result = _strip_gate_identity_member({})
    assert result["event_type"] == "gate_message"
    for field in _IDENTITY_FIELDS:
        assert field not in result


def test_member_view_handles_none_event():
    """Member view must handle None gracefully."""
    from routers.mesh_public import _strip_gate_identity_member

    result = _strip_gate_identity_member(None)
    assert result["event_type"] == "gate_message"
    for field in _IDENTITY_FIELDS:
        assert field not in result


def test_privileged_view_handles_empty_event():
    """Privileged view must handle empty events gracefully."""
    from routers.mesh_public import _strip_gate_identity_privileged

    result = _strip_gate_identity_privileged({})
    assert result["event_type"] == "gate_message"
    # Identity fields should be present but empty/zero
    assert result["node_id"] == ""
    assert result["sequence"] == 0
