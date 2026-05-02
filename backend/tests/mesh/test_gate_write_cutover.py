"""S3A Gate Write Cutover — prove gate writes skip the public chain.

Tests:
- Posting a gate_message no longer appends to the public infonet chain
- gate_store still receives newly posted gate messages
- Sequence counter still advances (replay protection without chain append)
- mesh_public.py router has the same behavior
- gate_sse broadcast is a no-op
"""

import copy
import hashlib

import pytest


# ── Helpers ─────────────────────────────────────────────────────────────


def _build_gate_message_body(gate_id: str, *, sequence: int = 1) -> dict:
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
        "sequence": sequence,
        "protocol_version": "infonet/2",
        "gate_envelope": "",
        "envelope_hash": "",
        "transport_lock": "private_strong",
    }


def _make_request(gate_id: str):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": f"/api/mesh/gate/{gate_id}/message",
        }
    )


def _setup_gate_outbox(monkeypatch):
    import main
    from services.mesh import mesh_private_outbox, mesh_private_transport_manager

    store = {}

    def _read_domain_json(_domain, _filename, default_factory, **_kwargs):
        payload = store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_domain_json(_domain, _filename, payload, **_kwargs):
        store["payload"] = copy.deepcopy(payload)

    monkeypatch.setattr(mesh_private_outbox, "read_sensitive_domain_json", _read_domain_json)
    monkeypatch.setattr(mesh_private_outbox, "write_sensitive_domain_json", _write_domain_json)
    mesh_private_transport_manager.reset_private_transport_manager_for_tests()
    mesh_private_outbox.private_delivery_outbox._load()
    monkeypatch.setattr(
        mesh_private_transport_manager.private_transport_manager,
        "_kickoff_background_bootstrap",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(main, "_kickoff_private_control_transport_upgrade", lambda: None)


def _run_gate_release_once(monkeypatch, *, transport_tier="private_strong"):
    from services.mesh import mesh_private_release_worker

    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: transport_tier)
    mesh_private_release_worker.private_release_worker.run_once()


def _patch_for_successful_post(monkeypatch, module):
    """Apply standard monkeypatches so a gate_message post succeeds."""
    import main

    _setup_gate_outbox(monkeypatch)
    monkeypatch.setattr(main, "_verify_gate_message_signed_write", lambda **kw: (True, "ok", kw.get("reply_to", "")))
    monkeypatch.setattr(main, "_resolve_envelope_policy", lambda _gate_id: "envelope_disabled")

    from services.mesh.mesh_reputation import gate_manager, reputation_ledger

    monkeypatch.setattr(gate_manager, "can_enter", lambda *a, **kw: (True, "ok"))
    monkeypatch.setattr(main, "_check_gate_post_cooldown", lambda *a: (True, "ok"))
    monkeypatch.setattr(main, "_record_gate_post_cooldown", lambda *a: None)
    monkeypatch.setattr(gate_manager, "record_message", lambda *a: None)
    monkeypatch.setattr(reputation_ledger, "register_node", lambda *a: None)


# ── F1: gate_message no longer appends to public infonet chain ─────────


def test_gate_post_does_not_call_infonet_append(monkeypatch):
    """Posting a gate_message must NOT call infonet.append()."""
    import main
    from services.mesh import mesh_hashchain

    _patch_for_successful_post(monkeypatch, main)

    # Track whether infonet.append is called
    infonet_append_called = []
    original_append = mesh_hashchain.infonet.append

    def spy_append(**kwargs):
        infonet_append_called.append(kwargs)
        return original_append(**kwargs)

    monkeypatch.setattr(mesh_hashchain.infonet, "append", spy_append)

    # Mock validate_and_set_sequence to succeed
    monkeypatch.setattr(
        mesh_hashchain.infonet,
        "validate_and_set_sequence",
        lambda node_id, seq: (True, "ok"),
    )
    # Mock gate_store.append
    monkeypatch.setattr(
        mesh_hashchain.gate_store,
        "append",
        lambda gate_id, event: {**event, "event_id": "test-ev-1"},
    )

    gate_id = "infonet"
    body = _build_gate_message_body(gate_id)
    result = main._submit_gate_message_envelope(_make_request(gate_id), gate_id, body)

    assert result["ok"] is True
    assert result["queued"] is True
    assert len(infonet_append_called) == 0, (
        "infonet.append() was called — gate_message should NOT be on the public chain"
    )


def test_gate_post_does_not_call_infonet_append_router(monkeypatch):
    """mesh_public.py router must also skip infonet.append()."""
    from routers import mesh_public
    from services.mesh import mesh_hashchain

    _patch_for_successful_post(monkeypatch, mesh_public)

    infonet_append_called = []

    def spy_append(**kwargs):
        infonet_append_called.append(kwargs)

    monkeypatch.setattr(mesh_hashchain.infonet, "append", spy_append)
    monkeypatch.setattr(
        mesh_hashchain.infonet,
        "validate_and_set_sequence",
        lambda node_id, seq: (True, "ok"),
    )
    monkeypatch.setattr(
        mesh_hashchain.gate_store,
        "append",
        lambda gate_id, event: {**event, "event_id": "test-ev-2"},
    )

    gate_id = "infonet"
    body = _build_gate_message_body(gate_id)
    result = mesh_public._submit_gate_message_envelope(_make_request(gate_id), gate_id, body)

    assert result["ok"] is True
    assert result["queued"] is True
    assert len(infonet_append_called) == 0


# ── F2: gate_store still receives posted gate messages ─────────────────


def test_gate_post_stores_in_gate_store(monkeypatch):
    """A successfully posted gate_message must be stored in gate_store."""
    import main
    from services.mesh import mesh_hashchain

    _patch_for_successful_post(monkeypatch, main)
    monkeypatch.setattr(
        mesh_hashchain.infonet,
        "validate_and_set_sequence",
        lambda node_id, seq: (True, "ok"),
    )

    stored_events = []

    def capture_append(gate_id, event):
        stored_events.append({"gate_id": gate_id, "event": event})
        return {**event, "event_id": "store-ev-1"}

    monkeypatch.setattr(mesh_hashchain.gate_store, "append", capture_append)

    gate_id = "infonet"
    body = _build_gate_message_body(gate_id)
    result = main._submit_gate_message_envelope(_make_request(gate_id), gate_id, body)

    assert result["ok"] is True
    assert result["queued"] is True
    assert len(stored_events) == 1
    _run_gate_release_once(monkeypatch)
    assert len(stored_events) >= 1
    assert stored_events[0]["gate_id"] == gate_id
    assert stored_events[0]["event"]["event_type"] == "gate_message"
    assert stored_events[0]["event"]["node_id"] == "!sb_test1234567890"
    assert "payload" in stored_events[0]["event"]
    assert stored_events[0]["event"]["payload"]["gate"] == gate_id


def test_gate_post_preserves_gate_envelope_in_store(monkeypatch):
    """gate_envelope must survive into gate_store even though it's not on chain."""
    import main
    from services.mesh import mesh_hashchain
    from services.mesh.mesh_gate_mls import _gate_envelope_encrypt

    _patch_for_successful_post(monkeypatch, main)
    monkeypatch.setattr(
        mesh_hashchain.infonet,
        "validate_and_set_sequence",
        lambda node_id, seq: (True, "ok"),
    )

    stored_events = []

    def capture_append(gate_id, event):
        stored_events.append(event)
        return {**event, "event_id": "store-ev-2"}

    monkeypatch.setattr(mesh_hashchain.gate_store, "append", capture_append)

    gate_id = "infonet"
    envelope = _gate_envelope_encrypt(gate_id, "hello from S3A")
    body = _build_gate_message_body(gate_id)
    body["gate_envelope"] = envelope
    body["envelope_hash"] = hashlib.sha256(envelope.encode("ascii")).hexdigest()

    result = main._submit_gate_message_envelope(_make_request(gate_id), gate_id, body)

    assert result["ok"] is True
    _run_gate_release_once(monkeypatch)
    assert stored_events[0]["payload"]["gate_envelope"] == envelope


# ── F3: sequence counter still advances ────────────────────────────────


def test_gate_post_advances_sequence(monkeypatch):
    """validate_and_set_sequence must be called to advance the counter."""
    import main
    from services.mesh import mesh_hashchain

    _patch_for_successful_post(monkeypatch, main)

    seq_calls = []

    def track_seq(node_id, seq, *, domain=""):
        seq_calls.append((node_id, seq, domain))
        return (True, "ok")

    monkeypatch.setattr(mesh_hashchain.infonet, "validate_and_set_sequence", track_seq)
    monkeypatch.setattr(
        mesh_hashchain.gate_store,
        "append",
        lambda gate_id, event: {**event, "event_id": "ev-seq"},
    )

    gate_id = "infonet"
    body = _build_gate_message_body(gate_id, sequence=42)
    result = main._submit_gate_message_envelope(_make_request(gate_id), gate_id, body)

    assert result["ok"] is True
    assert result["queued"] is True
    assert len(seq_calls) == 1
    assert seq_calls[0] == ("!sb_test1234567890", 42, "gate_message")


def test_gate_post_rejects_replay_via_sequence(monkeypatch):
    """A replayed sequence must still be rejected."""
    import main
    from services.mesh import mesh_hashchain

    _patch_for_successful_post(monkeypatch, main)
    monkeypatch.setattr(
        mesh_hashchain.infonet,
        "validate_and_set_sequence",
        lambda node_id, seq: (False, "Replay detected: sequence 1 <= last 1"),
    )

    gate_id = "infonet"
    body = _build_gate_message_body(gate_id, sequence=1)
    result = main._submit_gate_message_envelope(_make_request(gate_id), gate_id, body)

    assert result["ok"] is False
    assert "replay" in result["detail"].lower()


# ── F4: gate SSE broadcast is a no-op ──────────────────────────────────


def test_gate_sse_broadcast_is_noop():
    """_broadcast_gate_events must be a no-op (does not raise or enqueue)."""
    from gate_sse import _broadcast_gate_events

    # Must not raise
    _broadcast_gate_events("infonet", [{"event_type": "gate_message"}])
    _broadcast_gate_events("infonet", [])


def test_no_sse_endpoint_registered():
    """The /api/mesh/gate/stream SSE endpoint must not be registered."""
    import main

    stream_routes = [
        r for r in main.app.routes
        if hasattr(r, "path") and r.path == "/api/mesh/gate/stream"
    ]
    assert len(stream_routes) == 0, (
        "/api/mesh/gate/stream is still registered — SSE endpoint was not removed"
    )
