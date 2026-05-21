"""Issue #208 (tg12): Merkle proofs were rebuilt from scratch on every
public ``/api/mesh/infonet/sync?include_proofs=true`` request. The
endpoint is part of the federation protocol so we can't add auth — the
fix is to cache the levels at append time so retrieval is O(1) per
proof, eliminating the DoS surface without breaking peer sync.

These tests verify:

* A fresh Infonet has no cache (lazy state).
* After ``append()``, the cache is invalidated.
* Two consecutive ``get_merkle_proofs()`` calls without an append return
  identical results and don't rebuild — we assert this by reaching into
  the cache attributes directly.
"""
import os
import tempfile

import pytest

from services.mesh.mesh_hashchain import Infonet


@pytest.fixture
def fresh_infonet(monkeypatch, tmp_path):
    """Build a clean Infonet rooted at a temp directory."""
    # Redirect persistence to the temp dir so we don't pollute real state.
    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.CHAIN_FILE",
        tmp_path / "infonet_chain.json",
    )
    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.WAL_PATH",
        tmp_path / "infonet_chain.wal",
        raising=False,
    )
    inst = Infonet()
    inst.events = []  # ensure empty
    inst._invalidate_merkle_cache()
    return inst


def test_cache_starts_empty(fresh_infonet):
    """The cache fields exist and start in their lazy state."""
    assert hasattr(fresh_infonet, "_merkle_levels_cache")
    assert fresh_infonet._merkle_levels_cache is None
    assert fresh_infonet._merkle_levels_for_event_count == -1


def test_get_merkle_root_populates_cache(fresh_infonet):
    """First call computes and caches the levels."""
    # Add a synthetic event so there's something to hash
    fresh_infonet.events = [{"event_id": "a" * 64}, {"event_id": "b" * 64}]
    _ = fresh_infonet.get_merkle_root()
    assert fresh_infonet._merkle_levels_cache is not None
    assert fresh_infonet._merkle_levels_for_event_count == 2


def test_repeated_root_calls_reuse_cache(fresh_infonet):
    """The cache survives multiple reads when no events were appended."""
    fresh_infonet.events = [{"event_id": "a" * 64}, {"event_id": "b" * 64}]
    _ = fresh_infonet.get_merkle_root()
    cached_levels = fresh_infonet._merkle_levels_cache
    cached_count = fresh_infonet._merkle_levels_for_event_count

    _ = fresh_infonet.get_merkle_root()
    # Same object — no rebuild.
    assert fresh_infonet._merkle_levels_cache is cached_levels
    assert fresh_infonet._merkle_levels_for_event_count == cached_count


def test_append_invalidates_cache(fresh_infonet):
    """After events change, the cache_for_count diverges from len(events).

    The next read recomputes; that's the architectural point.
    """
    fresh_infonet.events = [{"event_id": "a" * 64}]
    _ = fresh_infonet.get_merkle_root()
    assert fresh_infonet._merkle_levels_for_event_count == 1

    # Simulate an append's side effect (the real append() also calls
    # _invalidate_merkle_cache() — we test that integration in the
    # in-tree append-flow test, not here).
    fresh_infonet.events.append({"event_id": "b" * 64})
    fresh_infonet._invalidate_merkle_cache()

    _ = fresh_infonet.get_merkle_root()
    assert fresh_infonet._merkle_levels_for_event_count == 2


def test_proofs_use_cache(fresh_infonet):
    """get_merkle_proofs() reads from the same cache get_merkle_root() does."""
    fresh_infonet.events = [
        {"event_id": (str(i) * 64)[:64]} for i in range(8)
    ]
    _ = fresh_infonet.get_merkle_root()
    cached_levels = fresh_infonet._merkle_levels_cache

    proofs = fresh_infonet.get_merkle_proofs(0, 8)
    assert proofs["total"] == 8
    assert len(proofs["proofs"]) == 8
    # Cache wasn't rebuilt — same object as before the proof call.
    assert fresh_infonet._merkle_levels_cache is cached_levels


def test_empty_chain_returns_genesis(fresh_infonet):
    """An empty chain should serve GENESIS_HASH without computing levels."""
    from services.mesh.mesh_hashchain import GENESIS_HASH

    root = fresh_infonet.get_merkle_root()
    assert root == GENESIS_HASH

    proofs = fresh_infonet.get_merkle_proofs(0, 0)
    assert proofs["total"] == 0
    assert proofs["root"] == GENESIS_HASH
