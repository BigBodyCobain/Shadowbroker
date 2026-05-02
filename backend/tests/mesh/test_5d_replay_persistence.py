"""Phase 5D — Replay Persistence Narrowing tests.

Validates that:
1. append persist failure leaves no in-memory mutation and does not return success
2. append success survives reload/rebuild
3. ingest_peer_events persist failure does not over-report accepted and leaves no ghost state
4. Replay dedupe remains aligned with durably persisted gate events
5. No regression to existing persisted gate data readability
"""
import hashlib
import json
import time
import os

import pytest

from services.mesh import mesh_hashchain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gate_store(tmp_path, monkeypatch):
    """Create a GateMessageStore with a temporary data directory."""
    store_dir = tmp_path / "gate_messages"
    store_dir.mkdir(parents=True, exist_ok=True)
    # Patch GATE_STORE_DIR so _load doesn't pick up real data
    monkeypatch.setattr(mesh_hashchain, "GATE_STORE_DIR", store_dir)
    return mesh_hashchain.GateMessageStore(data_dir=str(store_dir))


def _make_event(gate_id: str, ciphertext: str = "ct-hello", ts: float = None) -> dict:
    """Build a minimal gate event suitable for GateMessageStore.append()."""
    return {
        "event_type": "gate_message",
        "node_id": "test-node-001",
        "timestamp": ts or time.time(),
        "sequence": 1,
        "signature": "deadbeef",
        "public_key": "dGVzdA==",
        "public_key_algo": "Ed25519",
        "protocol_version": "1.0",
        "payload": {
            "gate": gate_id,
            "ciphertext": ciphertext,
            "format": "mls1",
        },
    }


def _make_ingestable_event(gate_id: str, ciphertext: str = "ct-peer", ts: float = None,
                           sequence: int = 1, node_id: str = "peer-node-001") -> dict:
    """Build an event for ingest_peer_events (passes validation via monkeypatch)."""
    event_id = hashlib.sha256(
        f"{gate_id}|{ciphertext}|{ts or time.time()}|{node_id}".encode()
    ).hexdigest()
    return {
        "event_id": event_id,
        "event_type": "gate_message",
        "node_id": node_id,
        "timestamp": ts or time.time(),
        "sequence": sequence,
        "signature": "deadbeef",
        "public_key": "dGVzdA==",
        "public_key_algo": "Ed25519",
        "protocol_version": "1.0",
        "payload": {
            "gate": gate_id,
            "ciphertext": ciphertext,
            "format": "mls1",
        },
    }


def _bypass_verify(monkeypatch):
    """Monkeypatch _verify_private_gate_transport_event to skip crypto checks."""
    def _fake_verify(gate_id, event):
        from services.mesh.mesh_hashchain import _sanitize_private_gate_event
        sanitized = _sanitize_private_gate_event(gate_id, event)
        event_id = str(event.get("event_id", "") or "").strip()
        if event_id:
            sanitized["event_id"] = event_id
        return True, "ok", sanitized
    monkeypatch.setattr(
        mesh_hashchain, "_verify_private_gate_transport_event", _fake_verify
    )


def _make_persist_fail(monkeypatch, store):
    """Make _persist_gate raise an IOError."""
    original = store._persist_gate

    def _exploding_persist(gate_id, events=None):
        raise IOError("disk full")

    monkeypatch.setattr(store, "_persist_gate", _exploding_persist)
    return original


# ---------------------------------------------------------------------------
# 1. append persist failure leaves no in-memory mutation
# ---------------------------------------------------------------------------

class TestAppendPersistFailure:
    def test_raises_on_persist_failure(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        _make_persist_fail(monkeypatch, store)
        event = _make_event("test-gate", "secret-payload")
        with pytest.raises(IOError, match="disk full"):
            store.append("test-gate", event)

    def test_no_gate_list_mutation_on_persist_failure(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        _make_persist_fail(monkeypatch, store)
        event = _make_event("test-gate", "secret-payload")
        try:
            store.append("test-gate", event)
        except IOError:
            pass
        assert store.get_messages("test-gate") == []

    def test_no_event_index_mutation_on_persist_failure(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        _make_persist_fail(monkeypatch, store)
        event = _make_event("test-gate", "secret-payload")
        try:
            store.append("test-gate", event)
        except IOError:
            pass
        # No event should be findable by event_id
        for eid in store._event_index:
            assert False, f"unexpected event_id in index: {eid}"

    def test_no_replay_index_mutation_on_persist_failure(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        _make_persist_fail(monkeypatch, store)
        event = _make_event("test-gate", "secret-payload")
        try:
            store.append("test-gate", event)
        except IOError:
            pass
        # Replay index should be empty — the event was never committed
        assert len(store._replay_index) == 0

    def test_retry_after_persist_recovery_succeeds(self, tmp_path, monkeypatch):
        """After a persist failure, a retry with working persistence must succeed."""
        store = _make_gate_store(tmp_path, monkeypatch)
        original = _make_persist_fail(monkeypatch, store)
        event = _make_event("test-gate", "retry-payload")
        try:
            store.append("test-gate", event)
        except IOError:
            pass
        # Restore persistence
        monkeypatch.setattr(store, "_persist_gate", original)
        result = store.append("test-gate", event)
        assert result is not None
        assert store.get_messages("test-gate") != []


# ---------------------------------------------------------------------------
# 2. append success survives reload/rebuild
# ---------------------------------------------------------------------------

class TestAppendSurvivesReload:
    def test_appended_event_readable_after_reload(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        event = _make_event("durable-gate", "durable-payload")
        result = store.append("durable-gate", event)
        event_id = result.get("event_id")
        assert event_id

        # Create a new store from the same directory — simulates restart
        store2 = mesh_hashchain.GateMessageStore(data_dir=str(store._data_dir))
        messages = store2.get_messages("durable-gate")
        assert len(messages) == 1
        assert messages[0]["payload"]["ciphertext"] == "durable-payload"

    def test_replay_index_rebuilt_correctly_after_reload(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        event = _make_event("rebuild-gate", "rebuild-payload")
        result = store.append("rebuild-gate", event)
        event_id = result.get("event_id")

        # Reload
        store2 = mesh_hashchain.GateMessageStore(data_dir=str(store._data_dir))
        # Appending the same event again should return the existing one (dedupe)
        result2 = store2.append("rebuild-gate", event)
        assert result2.get("event_id") == event_id
        # Still only one message
        assert len(store2.get_messages("rebuild-gate")) == 1

    def test_multiple_events_survive_reload_in_order(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        now = time.time()
        for i in range(5):
            event = _make_event("ordered-gate", f"msg-{i}", ts=now + i)
            store.append("ordered-gate", event)

        store2 = mesh_hashchain.GateMessageStore(data_dir=str(store._data_dir))
        messages = store2.get_messages("ordered-gate", limit=10)
        # get_messages returns newest first
        ciphertexts = [m["payload"]["ciphertext"] for m in reversed(messages)]
        assert ciphertexts == [f"msg-{i}" for i in range(5)]


# ---------------------------------------------------------------------------
# 3. ingest_peer_events persist failure — no ghost state
# ---------------------------------------------------------------------------

class TestIngestPersistFailure:
    def test_raises_on_persist_failure(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        _bypass_verify(monkeypatch)
        _make_persist_fail(monkeypatch, store)
        events = [_make_ingestable_event("test-gate", "peer-payload-1")]
        with pytest.raises(IOError, match="disk full"):
            store.ingest_peer_events("test-gate", events)

    def test_no_gate_list_mutation_on_persist_failure(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        _bypass_verify(monkeypatch)
        _make_persist_fail(monkeypatch, store)
        events = [_make_ingestable_event("test-gate", "peer-payload-2")]
        try:
            store.ingest_peer_events("test-gate", events)
        except IOError:
            pass
        assert store.get_messages("test-gate") == []

    def test_no_event_index_mutation_on_persist_failure(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        _bypass_verify(monkeypatch)
        _make_persist_fail(monkeypatch, store)
        events = [_make_ingestable_event("test-gate", "peer-payload-3")]
        try:
            store.ingest_peer_events("test-gate", events)
        except IOError:
            pass
        for eid in store._event_index:
            assert False, f"unexpected event_id in index: {eid}"

    def test_no_replay_index_mutation_on_persist_failure(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        _bypass_verify(monkeypatch)
        _make_persist_fail(monkeypatch, store)
        events = [_make_ingestable_event("test-gate", "peer-payload-4")]
        try:
            store.ingest_peer_events("test-gate", events)
        except IOError:
            pass
        assert len(store._replay_index) == 0

    def test_does_not_over_report_accepted(self, tmp_path, monkeypatch):
        """When persist fails, accepted count must not leak out."""
        store = _make_gate_store(tmp_path, monkeypatch)
        _bypass_verify(monkeypatch)
        _make_persist_fail(monkeypatch, store)
        events = [
            _make_ingestable_event("test-gate", f"peer-{i}", ts=time.time() + i)
            for i in range(3)
        ]
        # The exception prevents returning any accepted count
        with pytest.raises(IOError):
            store.ingest_peer_events("test-gate", events)

    def test_partial_batch_no_ghost_on_persist_failure(self, tmp_path, monkeypatch):
        """A batch with mixed valid/invalid events: on persist failure,
        none of the valid ones should remain in memory."""
        store = _make_gate_store(tmp_path, monkeypatch)
        _bypass_verify(monkeypatch)
        _make_persist_fail(monkeypatch, store)
        events = [
            _make_ingestable_event("test-gate", "valid-1"),
            {"bad": "event"},  # rejected
            _make_ingestable_event("test-gate", "valid-2", ts=time.time() + 1),
        ]
        try:
            store.ingest_peer_events("test-gate", events)
        except IOError:
            pass
        assert store.get_messages("test-gate") == []
        assert len(store._event_index) == 0
        assert len(store._replay_index) == 0


# ---------------------------------------------------------------------------
# 4. Replay dedupe aligned with durably persisted gate events
# ---------------------------------------------------------------------------

class TestReplayDedupeAlignment:
    def test_replay_blocks_duplicate_after_successful_append(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        event = _make_event("dedup-gate", "unique-payload")
        result1 = store.append("dedup-gate", event)
        result2 = store.append("dedup-gate", event)
        # Same event returned (deduplicated)
        assert result1.get("event_id") == result2.get("event_id")
        assert len(store.get_messages("dedup-gate")) == 1

    def test_replay_does_not_block_after_persist_failure(self, tmp_path, monkeypatch):
        """If append failed (persist failure), the replay index must NOT block
        a subsequent retry of the same event."""
        store = _make_gate_store(tmp_path, monkeypatch)
        original = _make_persist_fail(monkeypatch, store)
        event = _make_event("dedup-gate", "retry-dedup")
        try:
            store.append("dedup-gate", event)
        except IOError:
            pass
        # Restore persistence
        monkeypatch.setattr(store, "_persist_gate", original)
        # Retry must succeed — the event was never durably persisted
        result = store.append("dedup-gate", event)
        assert result is not None
        assert len(store.get_messages("dedup-gate")) == 1

    def test_replay_dedupe_survives_reload(self, tmp_path, monkeypatch):
        """After reload, the rebuilt replay index must still block duplicates."""
        store = _make_gate_store(tmp_path, monkeypatch)
        event = _make_event("reload-dedup-gate", "dedup-after-reload")
        result1 = store.append("reload-dedup-gate", event)
        eid = result1.get("event_id")

        store2 = mesh_hashchain.GateMessageStore(data_dir=str(store._data_dir))
        result2 = store2.append("reload-dedup-gate", event)
        assert result2.get("event_id") == eid
        assert len(store2.get_messages("reload-dedup-gate")) == 1

    def test_ingest_replay_does_not_block_after_persist_failure(self, tmp_path, monkeypatch):
        store = _make_gate_store(tmp_path, monkeypatch)
        _bypass_verify(monkeypatch)
        original = _make_persist_fail(monkeypatch, store)
        events = [_make_ingestable_event("dedup-gate", "ingest-retry")]
        try:
            store.ingest_peer_events("dedup-gate", events)
        except IOError:
            pass
        # Restore persistence
        monkeypatch.setattr(store, "_persist_gate", original)
        result = store.ingest_peer_events("dedup-gate", events)
        assert result["accepted"] == 1
        assert len(store.get_messages("dedup-gate")) == 1


# ---------------------------------------------------------------------------
# 5. No regression to existing persisted gate data readability
# ---------------------------------------------------------------------------

class TestExistingDataReadability:
    def test_legacy_jsonl_still_loads(self, tmp_path, monkeypatch):
        """Simulate a legacy .jsonl file (pre-encrypted) and verify it loads."""
        store_dir = tmp_path / "gate_messages"
        store_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(mesh_hashchain, "GATE_STORE_DIR", store_dir)

        gate_id = "legacy-gate"
        digest = hashlib.sha256(gate_id.encode("utf-8")).hexdigest()
        legacy_file = store_dir / f"gate_{digest}.jsonl"
        now = time.time()
        event = {
            "event_id": hashlib.sha256(b"legacy-event-1").hexdigest(),
            "event_type": "gate_message",
            "node_id": "legacy-node",
            "timestamp": now,
            "sequence": 1,
            "signature": "abcd",
            "public_key": "dGVzdA==",
            "public_key_algo": "Ed25519",
            "protocol_version": "1.0",
            "payload": {
                "gate": gate_id,
                "ciphertext": "legacy-ct",
                "format": "mls1",
            },
        }
        legacy_file.write_text(json.dumps(event) + "\n", encoding="utf-8")

        store = mesh_hashchain.GateMessageStore(data_dir=str(store_dir))
        messages = store.get_messages(gate_id)
        assert len(messages) == 1
        assert messages[0]["payload"]["ciphertext"] == "legacy-ct"

    def test_encrypted_domain_data_still_loads(self, tmp_path, monkeypatch):
        """Data written by _persist_gate (encrypted) must be readable by a fresh store."""
        store = _make_gate_store(tmp_path, monkeypatch)
        event = _make_event("encrypted-gate", "encrypted-ct")
        store.append("encrypted-gate", event)

        # Fresh store from same dir
        store2 = mesh_hashchain.GateMessageStore(data_dir=str(store._data_dir))
        messages = store2.get_messages("encrypted-gate")
        assert len(messages) == 1
        assert messages[0]["payload"]["ciphertext"] == "encrypted-ct"

    def test_event_index_consistent_after_load(self, tmp_path, monkeypatch):
        """After reload, get_event must find all persisted events."""
        store = _make_gate_store(tmp_path, monkeypatch)
        event = _make_event("index-gate", "index-ct")
        result = store.append("index-gate", event)
        eid = result["event_id"]

        store2 = mesh_hashchain.GateMessageStore(data_dir=str(store._data_dir))
        found = store2.get_event(eid)
        assert found is not None
        assert found["payload"]["ciphertext"] == "index-ct"
