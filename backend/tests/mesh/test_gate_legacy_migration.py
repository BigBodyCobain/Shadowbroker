import copy

from services.mesh import mesh_gate_legacy_migration


def test_local_archival_rewrap_preserves_original_author_without_resigning_as_them(monkeypatch):
    store = {}
    original = {
        "event_id": "legacy-event-1",
        "event_type": "gate_message",
        "node_id": "original-author",
        "payload": {
            "gate": "legacy-gate",
            "ciphertext": "legacy-ct",
            "nonce": "legacy-nonce",
            "sender_ref": "legacy-sender",
            "format": "mls1",
        },
        "timestamp": 100.0,
        "sequence": 7,
        "signature": "original-signature",
        "public_key": "original-public-key",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
    }

    def _read_domain_json(_domain, _filename, default_factory, **_kwargs):
        payload = store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_domain_json(_domain, _filename, payload, **_kwargs):
        store["payload"] = copy.deepcopy(payload)

    monkeypatch.setattr(mesh_gate_legacy_migration, "read_sensitive_domain_json", _read_domain_json)
    monkeypatch.setattr(mesh_gate_legacy_migration, "write_sensitive_domain_json", _write_domain_json)
    monkeypatch.setattr("services.mesh.mesh_hashchain.gate_store.get_event", lambda event_id: copy.deepcopy(original))
    monkeypatch.setattr(
        "services.mesh.mesh_wormhole_persona.sign_gate_wormhole_event",
        lambda **kwargs: {
            "node_id": "local-wrapper-signer",
            "identity_scope": "gate_persona",
            "sequence": 22,
            "signature": "local-wrapper-signature",
            "public_key": "local-public-key",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
        },
    )

    wrapper = mesh_gate_legacy_migration.create_local_archival_rewrap(
        gate_id="legacy-gate",
        event_id="legacy-event-1",
        archival_envelope="archive-envelope-token",
        reason="test migration",
    )

    assert wrapper["ok"] is True
    assert wrapper["event_type"] == "gate_archival_rewrap"
    assert wrapper["node_id"] == "local-wrapper-signer"
    assert wrapper["signature"] == "local-wrapper-signature"
    assert wrapper["payload"]["original_author_node_id"] == "original-author"
    assert wrapper["payload"]["original_event_id"] == "legacy-event-1"
    assert wrapper["payload"]["authorship_semantics"].startswith("wrapper signer attests")
    assert wrapper["payload"]["original_signature_hash"]
    assert "original-signature" not in str(wrapper["payload"])
    assert original["node_id"] == "original-author"
    assert original["signature"] == "original-signature"

    persisted = mesh_gate_legacy_migration.list_local_archival_rewraps(gate_id="legacy-gate")
    assert len(persisted) == 1
    assert persisted[0]["event_id"] == wrapper["event_id"]


def test_local_archival_rewrap_is_idempotent_per_original_event(monkeypatch):
    store = {}
    original = {
        "event_id": "legacy-event-2",
        "event_type": "gate_message",
        "node_id": "original-author",
        "payload": {
            "gate": "legacy-gate",
            "ciphertext": "legacy-ct",
            "nonce": "legacy-nonce",
            "sender_ref": "legacy-sender",
            "format": "mls1",
        },
        "signature": "original-signature",
    }

    def _read_domain_json(_domain, _filename, default_factory, **_kwargs):
        payload = store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_domain_json(_domain, _filename, payload, **_kwargs):
        store["payload"] = copy.deepcopy(payload)

    monkeypatch.setattr(mesh_gate_legacy_migration, "read_sensitive_domain_json", _read_domain_json)
    monkeypatch.setattr(mesh_gate_legacy_migration, "write_sensitive_domain_json", _write_domain_json)
    monkeypatch.setattr("services.mesh.mesh_hashchain.gate_store.get_event", lambda event_id: copy.deepcopy(original))
    monkeypatch.setattr(
        "services.mesh.mesh_wormhole_persona.sign_gate_wormhole_event",
        lambda **kwargs: {
            "node_id": "local-wrapper-signer",
            "identity_scope": "gate_persona",
            "sequence": 1,
            "signature": "local-wrapper-signature",
            "public_key": "local-public-key",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
        },
    )

    first = mesh_gate_legacy_migration.create_local_archival_rewrap(
        gate_id="legacy-gate",
        event_id="legacy-event-2",
        reason="first",
    )
    second = mesh_gate_legacy_migration.create_local_archival_rewrap(
        gate_id="legacy-gate",
        event_id="legacy-event-2",
        reason="second",
    )

    assert first["ok"] is True
    assert second["ok"] is True
    persisted = mesh_gate_legacy_migration.list_local_archival_rewraps(gate_id="legacy-gate")
    assert len(persisted) == 1
    assert persisted[0]["payload"]["reason"] == "second"


def test_create_missing_local_archival_rewraps_scans_legacy_only(monkeypatch):
    store = {}
    events_by_id = {
        "legacy-event-3": {
            "event_id": "legacy-event-3",
            "event_type": "gate_message",
            "node_id": "legacy-author",
            "payload": {
                "gate": "legacy-gate",
                "ciphertext": "legacy-ct",
                "nonce": "legacy-nonce",
                "sender_ref": "legacy-sender",
                "format": "mls1",
                "gate_envelope": "legacy-envelope-token",
            },
            "signature": "legacy-signature",
            "public_key": "legacy-key",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
        },
        "current-event-1": {
            "event_id": "current-event-1",
            "event_type": "gate_message",
            "node_id": "current-author",
            "payload": {
                "gate": "legacy-gate",
                "ciphertext": "current-ct",
                "nonce": "current-nonce",
                "sender_ref": "current-sender",
                "format": "mls1",
                "gate_envelope": "current-envelope-token",
                "envelope_hash": "current-envelope-hash",
                "transport_lock": "private_strong",
            },
            "signature": "current-signature",
            "public_key": "current-key",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
        },
    }
    original_events = copy.deepcopy(events_by_id)

    def _read_domain_json(_domain, _filename, default_factory, **_kwargs):
        payload = store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_domain_json(_domain, _filename, payload, **_kwargs):
        store["payload"] = copy.deepcopy(payload)

    monkeypatch.setattr(mesh_gate_legacy_migration, "read_sensitive_domain_json", _read_domain_json)
    monkeypatch.setattr(mesh_gate_legacy_migration, "write_sensitive_domain_json", _write_domain_json)
    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.gate_store.get_messages",
        lambda gate_id, limit=500, offset=0: [copy.deepcopy(events_by_id["legacy-event-3"]), copy.deepcopy(events_by_id["current-event-1"])],
    )
    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.gate_store.get_event",
        lambda event_id: copy.deepcopy(events_by_id.get(event_id)),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_wormhole_persona.sign_gate_wormhole_event",
        lambda **kwargs: {
            "node_id": "local-wrapper-signer",
            "identity_scope": "gate_persona",
            "sequence": 5,
            "signature": "local-wrapper-signature",
            "public_key": "local-public-key",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
        },
    )

    result = mesh_gate_legacy_migration.create_missing_local_archival_rewraps(gate_id="legacy-gate")

    assert result["ok"] is True
    assert result["scanned"] == 2
    assert result["created"] == 1
    assert result["skipped"] == 1
    assert result["failed"] == 0
    wrapper = result["wrappers"][0]
    assert wrapper["payload"]["original_event_id"] == "legacy-event-3"
    assert wrapper["payload"]["reason"] == "legacy_unbound_gate_envelope"
    assert wrapper["payload"]["archival_envelope_hash"]
    assert events_by_id == original_events

    second = mesh_gate_legacy_migration.create_missing_local_archival_rewraps(gate_id="legacy-gate")

    assert second["ok"] is True
    assert second["created"] == 0
    assert second["skipped"] == 2
    persisted = mesh_gate_legacy_migration.list_local_archival_rewraps(gate_id="legacy-gate")
    assert len(persisted) == 1


def test_legacy_candidate_classifier_does_not_wrap_current_canonical_gate_event():
    current = {
        "event_id": "current-event-2",
        "event_type": "gate_message",
        "protocol_version": "infonet/2",
        "payload": {
            "gate": "legacy-gate",
            "ciphertext": "ct",
            "nonce": "nonce",
            "sender_ref": "sender",
            "format": "mls1",
            "gate_envelope": "envelope",
            "envelope_hash": "hash",
            "transport_lock": "private_strong",
        },
    }

    assert mesh_gate_legacy_migration.legacy_gate_event_candidate_reason(current) == ""
    legacy = copy.deepcopy(current)
    legacy["payload"].pop("transport_lock")
    assert (
        mesh_gate_legacy_migration.legacy_gate_event_candidate_reason(legacy)
        == "legacy_missing_transport_lock"
    )
