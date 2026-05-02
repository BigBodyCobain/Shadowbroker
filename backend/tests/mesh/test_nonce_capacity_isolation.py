"""S5B Nonce Capacity Isolation — prove targeted nonce quota isolation.

Tests:
- Replay for same agent+nonce is still rejected
- One agent filling its quota does not block a different agent
- Cache remains bounded without turning the global budget into a hard denial
- Expiry frees capacity
"""

import time
from collections import OrderedDict
from unittest.mock import patch

import pytest


def _make_relay(tmp_path, monkeypatch, *, per_agent_max=4, global_max=16, ttl=60):
    from services.mesh import mesh_dm_relay

    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")

    relay = mesh_dm_relay.DMRelay()

    class _FakeSettings:
        MESH_DM_NONCE_TTL_S = ttl
        MESH_DM_NONCE_CACHE_MAX = global_max
        MESH_DM_NONCE_PER_AGENT_MAX = per_agent_max
        MESH_DM_PERSIST_SPOOL = False
        MESH_DM_REQUEST_MAILBOX_LIMIT = 100
        MESH_DM_SHARED_MAILBOX_LIMIT = 100
        MESH_DM_SELF_MAILBOX_LIMIT = 100
        MESH_DM_MAX_MSG_BYTES = 65536
        MESH_DM_METADATA_PERSIST = False
        MESH_DM_TOKEN_PEPPER = ""
        ADMIN_KEY = ""

    monkeypatch.setattr(relay, "_settings", lambda: _FakeSettings())
    monkeypatch.setenv("MESH_DM_TOKEN_PEPPER", "test-pepper")
    return relay


def test_same_agent_nonce_replay_rejected(tmp_path, monkeypatch):
    """Replay detection for the same agent+nonce must still work."""
    relay = _make_relay(tmp_path, monkeypatch)
    now = int(time.time())

    ok1, _ = relay.consume_nonce("agent-a", "nonce-1", now)
    assert ok1 is True

    ok2, reason = relay.consume_nonce("agent-a", "nonce-1", now)
    assert ok2 is False
    assert "replay" in reason.lower()


def test_different_agents_same_nonce_both_accepted(tmp_path, monkeypatch):
    """Different agents using the same nonce string must both succeed."""
    relay = _make_relay(tmp_path, monkeypatch)
    now = int(time.time())

    ok1, _ = relay.consume_nonce("agent-a", "shared-nonce", now)
    assert ok1 is True

    ok2, _ = relay.consume_nonce("agent-b", "shared-nonce", now)
    assert ok2 is True


def test_one_agent_full_does_not_block_another(tmp_path, monkeypatch):
    """One agent filling its per-agent quota must NOT block a different agent."""
    relay = _make_relay(tmp_path, monkeypatch, per_agent_max=4, global_max=100)
    now = int(time.time())

    # Fill agent-a's quota
    for i in range(4):
        ok, _ = relay.consume_nonce("agent-a", f"nonce-{i}", now)
        assert ok is True, f"agent-a nonce-{i} should succeed"

    # agent-a is now at capacity
    ok_full, reason = relay.consume_nonce("agent-a", "nonce-overflow", now)
    assert ok_full is False
    assert "capacity" in reason.lower()

    # agent-b must still work
    ok_b, _ = relay.consume_nonce("agent-b", "fresh-nonce", now)
    assert ok_b is True


def test_global_budget_trims_oldest_entry_without_cross_agent_denial(tmp_path, monkeypatch):
    """Global nonce budget stays bounded by trimming the oldest entry."""
    relay = _make_relay(tmp_path, monkeypatch, per_agent_max=8, global_max=6)
    now = int(time.time())

    # 3 nonces for agent-a
    for i in range(3):
        ok, _ = relay.consume_nonce("agent-a", f"n{i}", now)
        assert ok is True

    # 3 nonces for agent-b → hits global max of 6
    for i in range(3):
        ok, _ = relay.consume_nonce("agent-b", f"n{i}", now)
        assert ok is True

    # agent-c should still work; the oldest entry is trimmed first.
    ok_c, reason = relay.consume_nonce("agent-c", "overflow", now)
    assert ok_c is True, reason

    # Total entries must equal global max
    assert relay._total_nonce_count() == 6
    assert "n0" not in relay._nonce_caches.get("agent-a", {})
    assert "overflow" in relay._nonce_caches.get("agent-c", {})


def test_cache_bounded_per_agent(tmp_path, monkeypatch):
    """Per-agent cache must be bounded."""
    relay = _make_relay(tmp_path, monkeypatch, per_agent_max=3, global_max=100)
    now = int(time.time())

    for i in range(3):
        ok, _ = relay.consume_nonce("agent-x", f"n{i}", now)
        assert ok is True

    ok, reason = relay.consume_nonce("agent-x", "overflow", now)
    assert ok is False
    assert "capacity" in reason.lower()
    assert len(relay._nonce_caches.get("agent-x", {})) == 3


def test_expiry_frees_capacity(tmp_path, monkeypatch):
    """Expired nonces must free capacity for the same agent."""
    relay = _make_relay(tmp_path, monkeypatch, per_agent_max=2, global_max=100, ttl=1)
    now = int(time.time())

    ok1, _ = relay.consume_nonce("agent-a", "n1", now)
    ok2, _ = relay.consume_nonce("agent-a", "n2", now)
    assert ok1 is True
    assert ok2 is True

    # At capacity
    ok3, reason = relay.consume_nonce("agent-a", "n3", now)
    assert ok3 is False

    # Manually expire all entries
    for nonce_key in list(relay._nonce_caches.get("agent-a", {})):
        relay._nonce_caches["agent-a"][nonce_key] = time.time() - 1

    # Now capacity is freed
    ok4, _ = relay.consume_nonce("agent-a", "n4", now)
    assert ok4 is True


def test_global_budget_accepts_new_agent_by_trimming_oldest(tmp_path, monkeypatch):
    """A fresh agent should not be hard-blocked by unrelated nonce history."""
    relay = _make_relay(tmp_path, monkeypatch, per_agent_max=4, global_max=4, ttl=1)
    now = int(time.time())

    for i in range(4):
        ok, _ = relay.consume_nonce(f"agent-{i}", "n1", now)
        assert ok is True

    # Global budget is full, but the oldest entry is trimmed to make room.
    ok_after, _ = relay.consume_nonce("agent-new", "n1", now)
    assert ok_after is True
    assert relay._total_nonce_count() == 4
    assert "n1" not in relay._nonce_caches.get("agent-0", {})
    assert "n1" in relay._nonce_caches.get("agent-new", {})


def test_persistence_round_trip(tmp_path, monkeypatch):
    """Nonce caches must survive save/load cycle in per-agent format."""
    from services.mesh import mesh_dm_relay

    relay = _make_relay(tmp_path, monkeypatch, per_agent_max=10, global_max=100, ttl=3600)
    now = int(time.time())

    relay.consume_nonce("agent-a", "n1", now)
    relay.consume_nonce("agent-b", "n2", now)
    relay._flush()

    # Create a fresh relay instance and load
    relay2 = mesh_dm_relay.DMRelay.__new__(mesh_dm_relay.DMRelay)
    import threading
    from collections import defaultdict
    relay2._lock = threading.RLock()
    relay2._mailboxes = defaultdict(list)
    relay2._dh_keys = {}
    relay2._prekey_bundles = {}
    relay2._mailbox_bindings = defaultdict(dict)
    relay2._witnesses = defaultdict(list)
    relay2._blocks = defaultdict(set)
    relay2._nonce_caches = {}
    relay2._stats = {"messages_in_memory": 0}
    relay2._dirty = False
    relay2._save_timer = None
    relay2._SAVE_INTERVAL = 5.0
    monkeypatch.setattr(relay2, "_settings", relay._settings)
    relay2._load()

    # Replayed nonces must be rejected
    ok_a, reason = relay2.consume_nonce("agent-a", "n1", now)
    assert ok_a is False
    assert "replay" in reason.lower()

    ok_b, reason = relay2.consume_nonce("agent-b", "n2", now)
    assert ok_b is False
    assert "replay" in reason.lower()

    # Fresh nonces must succeed
    ok_new, _ = relay2.consume_nonce("agent-a", "new-nonce", now)
    assert ok_new is True
