"""Sprint 8 — stateless one-vote-per-node dedup.

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 8 row:
"One-vote-per-node: lowest lexicographical event_hash wins regardless
of observation order."
"""

from __future__ import annotations

from services.infonet.bootstrap import canonical_event_hash, deduplicate_votes
from services.infonet.tests._chain_factory import make_event


def _vote(node_id: str, market_id: str, side: str, *,
          ts: float, seq: int, pow_nonce: int = 0) -> dict:
    return make_event(
        "bootstrap_resolution_vote", node_id,
        {"market_id": market_id, "side": side, "pow_nonce": pow_nonce},
        timestamp=ts, sequence=seq,
    )


def test_canonical_event_hash_is_deterministic():
    e = _vote("alice", "m1", "yes", ts=100.0, seq=1)
    assert canonical_event_hash(e) == canonical_event_hash(dict(e))
    assert len(canonical_event_hash(e)) == 64


def test_canonical_event_hash_different_for_different_payloads():
    a = _vote("alice", "m1", "yes", ts=100.0, seq=1)
    b = _vote("alice", "m1", "no", ts=100.0, seq=1)
    assert canonical_event_hash(a) != canonical_event_hash(b)


def test_dedup_keeps_one_vote_per_node():
    chain = [
        _vote("alice", "m1", "yes", ts=100.0, seq=1, pow_nonce=1),
        _vote("alice", "m1", "yes", ts=200.0, seq=2, pow_nonce=2),
        _vote("bob", "m1", "no", ts=300.0, seq=3, pow_nonce=3),
    ]
    canonical = deduplicate_votes("m1", chain)
    nodes = [v["node_id"] for v in canonical]
    assert sorted(nodes) == ["alice", "bob"]


def test_dedup_chooses_lowest_lexicographical_event_hash():
    """Among multiple votes from the same node, the one whose
    canonical_event_hash is lexicographically smallest wins.
    """
    chain = [
        _vote("alice", "m1", "yes", ts=100.0, seq=1, pow_nonce=10),
        _vote("alice", "m1", "yes", ts=200.0, seq=2, pow_nonce=20),
        _vote("alice", "m1", "yes", ts=300.0, seq=3, pow_nonce=30),
    ]
    hashes = [(canonical_event_hash(e), e) for e in chain]
    hashes.sort(key=lambda h: h[0])
    expected_winner = hashes[0][1]

    canonical = deduplicate_votes("m1", chain)
    assert len(canonical) == 1
    # The chosen vote's hash matches the lowest among inputs.
    assert canonical_event_hash(canonical[0]) == hashes[0][0]
    # And specifically the same payload as the lowest-hash input.
    assert canonical[0]["payload"] == expected_winner["payload"]


def test_dedup_is_order_independent():
    """Same chain in any order produces the same canonical set."""
    forward = [
        _vote("alice", "m1", "yes", ts=100.0, seq=1, pow_nonce=10),
        _vote("alice", "m1", "yes", ts=200.0, seq=2, pow_nonce=20),
        _vote("bob", "m1", "no", ts=300.0, seq=3, pow_nonce=30),
        _vote("alice", "m1", "yes", ts=400.0, seq=4, pow_nonce=40),
    ]
    reverse = list(reversed(forward))
    a_set = {(v["node_id"], canonical_event_hash(v)) for v in deduplicate_votes("m1", forward)}
    b_set = {(v["node_id"], canonical_event_hash(v)) for v in deduplicate_votes("m1", reverse)}
    assert a_set == b_set


def test_dedup_filters_other_markets():
    chain = [
        _vote("alice", "m1", "yes", ts=100.0, seq=1),
        _vote("alice", "m2", "no", ts=200.0, seq=2),
    ]
    out = deduplicate_votes("m1", chain)
    assert len(out) == 1
    assert out[0]["node_id"] == "alice"
    assert out[0]["payload"]["side"] == "yes"


def test_dedup_only_processes_bootstrap_votes():
    """Other event types in the chain are ignored even if they
    reference the market_id."""
    chain = [
        _vote("alice", "m1", "yes", ts=100.0, seq=1),
        make_event("prediction_place", "bob",
                   {"market_id": "m1", "side": "no", "probability_at_bet": 50.0},
                   timestamp=200.0, sequence=2),
    ]
    out = deduplicate_votes("m1", chain)
    assert len(out) == 1
    assert out[0]["event_type"] == "bootstrap_resolution_vote"


def test_dedup_returns_sorted_output():
    """Output is sorted by (node_id, event_hash) — deterministic
    across any input ordering."""
    chain = [
        _vote("zebra", "m1", "yes", ts=100.0, seq=1),
        _vote("alice", "m1", "yes", ts=200.0, seq=2),
        _vote("mike", "m1", "no", ts=300.0, seq=3),
    ]
    out = deduplicate_votes("m1", chain)
    assert [v["node_id"] for v in out] == ["alice", "mike", "zebra"]
