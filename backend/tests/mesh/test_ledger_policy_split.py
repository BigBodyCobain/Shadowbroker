"""S4B Active/Legacy Ledger Policy Split — prove gate_message is blocked
from new public-chain appends but remains ingestable as legacy history.

Tests:
- ACTIVE set does not contain gate_message
- LEGACY set contains gate_message
- PUBLIC_LEDGER_EVENT_TYPES is the union of ACTIVE + LEGACY
- gate_message remains in SCHEMA_REGISTRY (EVENT_SCHEMAS)
- append() rejects gate_message at the schema/runtime gate
- ingest_events() accepts a valid legacy gate_message event
"""

import hashlib
import json
import time

import pytest


# ── Schema set derivation ────────────────────────────────────────────────


def test_active_set_does_not_contain_gate_message():
    """gate_message must NOT be in the active append set."""
    from services.mesh.mesh_schema import ACTIVE_PUBLIC_LEDGER_EVENT_TYPES

    assert "gate_message" not in ACTIVE_PUBLIC_LEDGER_EVENT_TYPES


def test_legacy_set_contains_gate_message():
    """gate_message must be in the legacy set."""
    from services.mesh.mesh_schema import LEGACY_PUBLIC_LEDGER_EVENT_TYPES

    assert "gate_message" in LEGACY_PUBLIC_LEDGER_EVENT_TYPES


def test_public_ledger_is_union_of_active_and_legacy():
    """PUBLIC_LEDGER_EVENT_TYPES must equal ACTIVE | LEGACY."""
    from services.mesh.mesh_schema import (
        ACTIVE_PUBLIC_LEDGER_EVENT_TYPES,
        LEGACY_PUBLIC_LEDGER_EVENT_TYPES,
        PUBLIC_LEDGER_EVENT_TYPES,
    )

    assert PUBLIC_LEDGER_EVENT_TYPES == (
        ACTIVE_PUBLIC_LEDGER_EVENT_TYPES | LEGACY_PUBLIC_LEDGER_EVENT_TYPES
    )


def test_gate_message_in_public_ledger_union():
    """gate_message must be in the full PUBLIC_LEDGER_EVENT_TYPES union."""
    from services.mesh.mesh_schema import PUBLIC_LEDGER_EVENT_TYPES

    assert "gate_message" in PUBLIC_LEDGER_EVENT_TYPES


def test_gate_message_remains_in_schema_registry():
    """gate_message must still have a schema in SCHEMA_REGISTRY."""
    from services.mesh.mesh_schema import SCHEMA_REGISTRY

    assert "gate_message" in SCHEMA_REGISTRY
    schema = SCHEMA_REGISTRY["gate_message"]
    assert schema.event_type == "gate_message"


def test_active_types_all_in_schema_registry():
    """Every active type must have a schema entry."""
    from services.mesh.mesh_schema import ACTIVE_PUBLIC_LEDGER_EVENT_TYPES, SCHEMA_REGISTRY

    for event_type in ACTIVE_PUBLIC_LEDGER_EVENT_TYPES:
        assert event_type in SCHEMA_REGISTRY, f"{event_type} missing from SCHEMA_REGISTRY"


def test_legacy_types_all_in_schema_registry():
    """Every legacy type must have a schema entry."""
    from services.mesh.mesh_schema import LEGACY_PUBLIC_LEDGER_EVENT_TYPES, SCHEMA_REGISTRY

    for event_type in LEGACY_PUBLIC_LEDGER_EVENT_TYPES:
        assert event_type in SCHEMA_REGISTRY, f"{event_type} missing from SCHEMA_REGISTRY"


# ── Runtime: append() rejects gate_message ───────────────────────────────


def test_append_rejects_gate_message():
    """Infonet.append() must raise ValueError for gate_message."""
    from services.mesh.mesh_hashchain import infonet

    with pytest.raises(ValueError, match="Unsupported event_type"):
        infonet.append(
            event_type="gate_message",
            node_id="!sb_test1234567890",
            payload={
                "gate": "infonet",
                "ciphertext": "dGVzdA==",
                "nonce": "dGVzdG5vbmNl",
                "sender_ref": "testref1234",
                "format": "mls1",
            },
            signature="deadbeef",
            sequence=999999,
            public_key="",
            public_key_algo="Ed25519",
            protocol_version="1",
        )


def test_append_still_accepts_active_event_type():
    """append() must still accept an active event type (e.g. message).

    We monkeypatch past crypto verification to reach the event-type gate.
    If we get past the event_type check, the test succeeds — we don't need
    the full append to complete.
    """
    from services.mesh.mesh_hashchain import infonet, ACTIVE_APPEND_EVENT_TYPES

    assert "message" in ACTIVE_APPEND_EVENT_TYPES

    # Attempting append with message type should NOT raise "Unsupported event_type".
    # It will fail later (bad signature, etc.) — that's fine, we only care
    # that the event_type gate does not reject it.
    try:
        infonet.append(
            event_type="message",
            node_id="!sb_test1234567890",
            payload={
                "message": "test",
                "destination": "broadcast",
                "channel": "general",
                "priority": "normal",
                "ephemeral": False,
            },
            signature="deadbeef",
            sequence=999999,
            public_key="test",
            public_key_algo="Ed25519",
            protocol_version="1",
        )
    except ValueError as exc:
        # Must NOT be "Unsupported event_type" — any other error is fine
        assert "Unsupported event_type" not in str(exc), (
            f"message was rejected as unsupported: {exc}"
        )


# ── Runtime: ingest_events() accepts legacy gate_message ─────────────────


def _build_chain_event(
    infonet,
    event_type: str,
    node_id: str,
    payload: dict,
    sequence: int,
) -> dict:
    """Build a syntactically valid chain event dict for ingest testing."""
    from services.mesh.mesh_protocol import NETWORK_ID, PROTOCOL_VERSION

    prev_hash = infonet.head_hash
    ts = time.time()

    payload_json = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    raw = f"{prev_hash}{event_type}{payload_json}{ts}{node_id}"
    event_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    return {
        "event_id": event_id,
        "prev_hash": prev_hash,
        "event_type": event_type,
        "node_id": node_id,
        "payload": payload,
        "timestamp": ts,
        "sequence": sequence,
        "signature": "valid_sig",
        "public_key": "valid_pk",
        "public_key_algo": "Ed25519",
        "protocol_version": PROTOCOL_VERSION,
        "network_id": NETWORK_ID,
    }


def test_ingest_accepts_legacy_gate_message(monkeypatch):
    """ingest_events() must accept a valid legacy gate_message event."""
    from services.mesh.mesh_hashchain import infonet, ChainEvent
    from services.mesh import mesh_crypto

    node_id = "!sb_legacyingest001"
    payload = {
        "gate": "infonet",
        "ciphertext": "dGVzdA==",
        "nonce": "dGVzdG5vbmNl",
        "sender_ref": "testref1234",
        "format": "mls1",
    }

    # Build event with a correct event_id via ChainEvent
    prev_hash = infonet.head_hash
    ts = time.time()
    seq = max(infonet.node_sequences.get(node_id, 0) + 1, 1)

    from services.mesh.mesh_protocol import NETWORK_ID, PROTOCOL_VERSION

    # Build via ChainEvent constructor to get a valid event_id
    chain_event = ChainEvent(
        prev_hash=prev_hash,
        event_type="gate_message",
        node_id=node_id,
        payload=payload,
        timestamp=ts,
        sequence=seq,
        signature="deadbeef",
        network_id=NETWORK_ID,
        public_key="validpk",
        public_key_algo="Ed25519",
        protocol_version=PROTOCOL_VERSION,
    )
    raw_event = chain_event.to_dict()

    # Monkeypatch crypto functions used inside ingest_events
    monkeypatch.setattr(mesh_crypto, "verify_signature", lambda **kw: True)
    monkeypatch.setattr(mesh_crypto, "verify_node_binding", lambda node_id, pub_key: True)
    monkeypatch.setattr(mesh_crypto, "parse_public_key_algo", lambda algo: "Ed25519")
    monkeypatch.setattr(infonet, "_bind_public_key", lambda pk, nid: (True, "ok"))
    monkeypatch.setattr(infonet, "_revocation_status", lambda pk: (False, ""))
    monkeypatch.setattr(infonet, "_save", lambda: None)

    result = infonet.ingest_events([raw_event])

    assert result["accepted"] >= 1, (
        f"Legacy gate_message was rejected during ingest: {result}"
    )
