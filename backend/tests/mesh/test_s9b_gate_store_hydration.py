"""S9B Accepted-Only Gate Store Hydration.

Tests:
- A rejected gate_message event does NOT hydrate gate_store
- An accepted gate_message event DOES hydrate gate_store
- A duplicate gate_message already in local infonet CAN hydrate gate_store
- Covers the replay path (main._hydrate_gate_store_from_chain)
- Covers the peer-push path (mesh_peer_sync._hydrate_gate_store_from_chain)
"""

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from services.mesh import mesh_hashchain, mesh_crypto, mesh_protocol


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_keypair():
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(pub).decode("utf-8")
    node_id = mesh_crypto.derive_node_id(pub_b64)
    return priv, pub_b64, node_id


def _make_gate_message_event(priv, pub_b64, node_id, sequence, prev_hash, gate_id="test-gate"):
    """Build a valid signed gate_message event dict."""
    payload = mesh_protocol.normalize_payload(
        "gate_message",
        {
            "gate": gate_id,
            "ciphertext": base64.b64encode(b"encrypted-data").decode(),
            "nonce": base64.b64encode(b"nonce-value-1234").decode(),
            "sender_ref": "sender-abc",
            "format": "mls1",
        },
    )
    sig_payload = mesh_crypto.build_signature_payload(
        event_type="gate_message",
        node_id=node_id,
        sequence=sequence,
        payload=payload,
    )
    signature = priv.sign(sig_payload.encode("utf-8")).hex()

    evt = mesh_hashchain.ChainEvent(
        prev_hash=prev_hash,
        event_type="gate_message",
        node_id=node_id,
        payload=payload,
        sequence=sequence,
        signature=signature,
        public_key=pub_b64,
        public_key_algo="Ed25519",
        protocol_version=mesh_protocol.PROTOCOL_VERSION,
        network_id=mesh_protocol.NETWORK_ID,
    )
    return evt.to_dict()


@pytest.fixture()
def fresh_env(tmp_path, monkeypatch):
    """Set up isolated infonet + gate_store, return (infonet, gate_store)."""
    monkeypatch.setattr(mesh_hashchain, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_hashchain, "CHAIN_FILE", tmp_path / "infonet.json")
    monkeypatch.setattr(mesh_hashchain, "WAL_FILE", tmp_path / "infonet.wal")
    gate_dir = tmp_path / "gate_messages"
    gate_dir.mkdir()
    monkeypatch.setattr(mesh_hashchain, "GATE_STORE_DIR", gate_dir)

    inf = mesh_hashchain.Infonet()
    gs = mesh_hashchain.GateMessageStore(data_dir=str(gate_dir))

    # Replace module-level singletons so _hydrate_gate_store_from_chain sees them.
    monkeypatch.setattr(mesh_hashchain, "infonet", inf)
    monkeypatch.setattr(mesh_hashchain, "gate_store", gs)

    return inf, gs


# ── Rejected gate_message must NOT hydrate gate_store ─────────────────────


def test_rejected_event_does_not_hydrate_gate_store(fresh_env):
    """A gate_message rejected by ingest must not appear in gate_store."""
    inf, gs = fresh_env

    priv, pub_b64, node_id = _make_keypair()
    evt = _make_gate_message_event(priv, pub_b64, node_id, sequence=1,
                                   prev_hash=mesh_hashchain.GENESIS_HASH)

    # Corrupt the signature so ingest rejects it.
    evt["signature"] = "00" * 64

    result = inf.ingest_events([evt])
    assert len(result["rejected"]) == 1, "event should be rejected"

    # Import the function under test from the replay path (main.py).
    from main import _hydrate_gate_store_from_chain
    count = _hydrate_gate_store_from_chain([evt])

    assert count == 0, "rejected event must not hydrate gate_store"
    assert gs.get_messages("test-gate") == [], "gate_store must be empty"


# ── Accepted gate_message DOES hydrate gate_store ─────────────────────────


def test_accepted_event_hydrates_gate_store(fresh_env):
    """A gate_message accepted by ingest must appear in gate_store."""
    inf, gs = fresh_env

    priv, pub_b64, node_id = _make_keypair()
    evt = _make_gate_message_event(priv, pub_b64, node_id, sequence=1,
                                   prev_hash=mesh_hashchain.GENESIS_HASH)

    result = inf.ingest_events([evt])
    assert result["accepted"] == 1, "event should be accepted"

    from main import _hydrate_gate_store_from_chain
    count = _hydrate_gate_store_from_chain([evt])

    assert count == 1, "accepted event must hydrate gate_store"
    messages = gs.get_messages("test-gate")
    assert len(messages) == 1
    assert messages[0].get("event_id") == evt["event_id"]


# ── Duplicate gate_message CAN hydrate gate_store ─────────────────────────


def test_duplicate_event_can_hydrate_gate_store(fresh_env):
    """A gate_message already in local infonet (duplicate) CAN hydrate gate_store.

    This supports gate_store recovery after restart: the event is already
    chain-resident (in event_index) from a prior ingest, but gate_store was
    lost.  Hydration must still copy it into gate_store.
    """
    inf, gs = fresh_env

    priv, pub_b64, node_id = _make_keypair()
    evt = _make_gate_message_event(priv, pub_b64, node_id, sequence=1,
                                   prev_hash=mesh_hashchain.GENESIS_HASH)

    # Ingest: accepted — event is now in event_index.
    result = inf.ingest_events([evt])
    assert result["accepted"] == 1
    assert evt["event_id"] in inf.event_index

    # gate_store is empty (simulates loss after restart).
    assert gs.get_messages("test-gate") == []

    # Hydration should succeed because event_id is in event_index.
    from main import _hydrate_gate_store_from_chain
    count = _hydrate_gate_store_from_chain([evt])

    assert count == 1, "already-present event must hydrate gate_store"
    messages = gs.get_messages("test-gate")
    assert len(messages) == 1


# ── Peer-push path (mesh_peer_sync) ──────────────────────────────────────


def test_peer_push_path_rejects_non_resident_event(fresh_env):
    """The peer-push copy of _hydrate_gate_store_from_chain also filters."""
    inf, gs = fresh_env

    priv, pub_b64, node_id = _make_keypair()
    evt = _make_gate_message_event(priv, pub_b64, node_id, sequence=1,
                                   prev_hash=mesh_hashchain.GENESIS_HASH)
    # Corrupt to force rejection.
    evt["signature"] = "00" * 64

    result = inf.ingest_events([evt])
    assert len(result["rejected"]) == 1

    from routers.mesh_peer_sync import _hydrate_gate_store_from_chain
    count = _hydrate_gate_store_from_chain([evt])

    assert count == 0, "rejected event must not hydrate via peer-push path"
    assert gs.get_messages("test-gate") == []


def test_peer_push_path_accepts_resident_event(fresh_env):
    """The peer-push copy accepts events that are in the local infonet."""
    inf, gs = fresh_env

    priv, pub_b64, node_id = _make_keypair()
    evt = _make_gate_message_event(priv, pub_b64, node_id, sequence=1,
                                   prev_hash=mesh_hashchain.GENESIS_HASH)

    result = inf.ingest_events([evt])
    assert result["accepted"] == 1

    from routers.mesh_peer_sync import _hydrate_gate_store_from_chain
    count = _hydrate_gate_store_from_chain([evt])

    assert count == 1
    messages = gs.get_messages("test-gate")
    assert len(messages) == 1


# ── Mixed batch: accepted + rejected ─────────────────────────────────────


def test_mixed_batch_only_accepted_hydrate(fresh_env):
    """In a batch with both accepted and rejected events, only accepted hydrate."""
    inf, gs = fresh_env

    priv, pub_b64, node_id = _make_keypair()

    # Event 1: valid, will be accepted.
    evt1 = _make_gate_message_event(priv, pub_b64, node_id, sequence=1,
                                    prev_hash=mesh_hashchain.GENESIS_HASH,
                                    gate_id="gate-a")

    # Ingest event 1 first to get the new head_hash.
    result1 = inf.ingest_events([evt1])
    assert result1["accepted"] == 1

    # Event 2: valid signature but wrong prev_hash (will be rejected).
    evt2 = _make_gate_message_event(priv, pub_b64, node_id, sequence=2,
                                    prev_hash="0000deadbeef",
                                    gate_id="gate-b")

    result2 = inf.ingest_events([evt2])
    assert len(result2["rejected"]) == 1

    from main import _hydrate_gate_store_from_chain
    count = _hydrate_gate_store_from_chain([evt1, evt2])

    # Only evt1 (accepted, in event_index) should hydrate.
    assert count == 1
    assert len(gs.get_messages("gate-a")) == 1
    assert gs.get_messages("gate-b") == []


# ── Event without event_id does not hydrate ──────────────────────────────


def test_event_without_event_id_does_not_hydrate(fresh_env):
    """A gate_message event missing event_id must not hydrate gate_store."""
    _inf, gs = fresh_env

    fake_evt = {
        "event_type": "gate_message",
        "payload": {"gate": "orphan-gate"},
    }

    from main import _hydrate_gate_store_from_chain
    count = _hydrate_gate_store_from_chain([fake_evt])

    assert count == 0
    assert gs.get_messages("orphan-gate") == []


# ── mesh_public path ─────────────────────────────────────────────────────


def test_mesh_public_path_rejects_non_resident_event(fresh_env):
    """The mesh_public copy of _hydrate_gate_store_from_chain also filters."""
    inf, gs = fresh_env

    priv, pub_b64, node_id = _make_keypair()
    evt = _make_gate_message_event(priv, pub_b64, node_id, sequence=1,
                                   prev_hash=mesh_hashchain.GENESIS_HASH)
    # Corrupt to force rejection.
    evt["signature"] = "00" * 64

    result = inf.ingest_events([evt])
    assert len(result["rejected"]) == 1

    from routers.mesh_public import _hydrate_gate_store_from_chain
    count = _hydrate_gate_store_from_chain([evt])

    assert count == 0, "rejected event must not hydrate via mesh_public path"
    assert gs.get_messages("test-gate") == []


# ── Canonical-source remediation: forged payload must not reach gate_store ─


def test_forged_payload_hydrates_canonical_not_raw(fresh_env):
    """A forged batch event sharing a resident event_id but carrying
    attacker-chosen payload must hydrate the canonical infonet event,
    not the forged payload.  (Main replay path.)"""
    inf, gs = fresh_env

    priv, pub_b64, node_id = _make_keypair()
    evt = _make_gate_message_event(priv, pub_b64, node_id, sequence=1,
                                   prev_hash=mesh_hashchain.GENESIS_HASH)

    result = inf.ingest_events([evt])
    assert result["accepted"] == 1

    # Build a forged batch event: same event_id, different payload.
    forged = dict(evt)
    forged["payload"] = {
        "gate": "test-gate",
        "ciphertext": base64.b64encode(b"ATTACKER-DATA").decode(),
        "nonce": base64.b64encode(b"attacker-nonce00").decode(),
        "sender_ref": "attacker-ref",
        "format": "mls1",
    }

    from main import _hydrate_gate_store_from_chain
    count = _hydrate_gate_store_from_chain([forged])

    assert count == 1, "event_id is resident, hydration should proceed"
    messages = gs.get_messages("test-gate")
    assert len(messages) == 1
    # The hydrated message must carry the canonical payload, not the forged one.
    hydrated_payload = messages[0].get("payload", {})
    assert hydrated_payload.get("ciphertext") != base64.b64encode(b"ATTACKER-DATA").decode(), \
        "forged ciphertext must not appear in gate_store"
    assert hydrated_payload.get("ciphertext") == evt["payload"]["ciphertext"], \
        "canonical ciphertext must be hydrated"
    assert hydrated_payload.get("sender_ref") == evt["payload"]["sender_ref"]


def test_forged_payload_peer_push_hydrates_canonical(fresh_env):
    """Peer-push path: forged batch event hydrates canonical, not raw."""
    inf, gs = fresh_env

    priv, pub_b64, node_id = _make_keypair()
    evt = _make_gate_message_event(priv, pub_b64, node_id, sequence=1,
                                   prev_hash=mesh_hashchain.GENESIS_HASH)

    result = inf.ingest_events([evt])
    assert result["accepted"] == 1

    forged = dict(evt)
    forged["payload"] = {
        "gate": "test-gate",
        "ciphertext": base64.b64encode(b"ATTACKER-DATA").decode(),
        "nonce": base64.b64encode(b"attacker-nonce00").decode(),
        "sender_ref": "attacker-ref",
        "format": "mls1",
    }

    from routers.mesh_peer_sync import _hydrate_gate_store_from_chain
    count = _hydrate_gate_store_from_chain([forged])

    assert count == 1
    messages = gs.get_messages("test-gate")
    assert len(messages) == 1
    hydrated_payload = messages[0].get("payload", {})
    assert hydrated_payload.get("ciphertext") == evt["payload"]["ciphertext"]
    assert hydrated_payload.get("sender_ref") == evt["payload"]["sender_ref"]


def test_forged_payload_mesh_public_hydrates_canonical(fresh_env):
    """mesh_public path: forged batch event hydrates canonical, not raw."""
    inf, gs = fresh_env

    priv, pub_b64, node_id = _make_keypair()
    evt = _make_gate_message_event(priv, pub_b64, node_id, sequence=1,
                                   prev_hash=mesh_hashchain.GENESIS_HASH)

    result = inf.ingest_events([evt])
    assert result["accepted"] == 1

    forged = dict(evt)
    forged["payload"] = {
        "gate": "test-gate",
        "ciphertext": base64.b64encode(b"ATTACKER-DATA").decode(),
        "nonce": base64.b64encode(b"attacker-nonce00").decode(),
        "sender_ref": "attacker-ref",
        "format": "mls1",
    }

    from routers.mesh_public import _hydrate_gate_store_from_chain
    count = _hydrate_gate_store_from_chain([forged])

    assert count == 1
    messages = gs.get_messages("test-gate")
    assert len(messages) == 1
    hydrated_payload = messages[0].get("payload", {})
    assert hydrated_payload.get("ciphertext") == evt["payload"]["ciphertext"]
    assert hydrated_payload.get("sender_ref") == evt["payload"]["sender_ref"]
