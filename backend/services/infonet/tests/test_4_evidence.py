"""Sprint 4 — evidence canonicalization + first-submitter detection."""

from __future__ import annotations

from services.infonet.markets import (
    collect_evidence,
    evidence_content_hash,
    is_first_for_side,
    submission_hash,
)
from services.infonet.tests._chain_factory import make_event


def _evidence(market_id: str, node_id: str, outcome: str, *,
              hashes: list[str], desc: str, ts: float, seq: int,
              bond: float = 2.0) -> dict:
    chash = evidence_content_hash(market_id, outcome, hashes, desc)
    shash = submission_hash(chash, node_id, ts)
    return make_event(
        "evidence_submit", node_id,
        {"market_id": market_id, "claimed_outcome": outcome,
         "evidence_hashes": list(hashes), "source_description": desc,
         "evidence_content_hash": chash, "submission_hash": shash,
         "bond": bond},
        timestamp=ts, sequence=seq,
    )


def test_content_hash_is_deterministic():
    h1 = evidence_content_hash("m1", "yes", ["a", "b"], "src")
    h2 = evidence_content_hash("m1", "yes", ["b", "a"], "src")
    assert h1 == h2  # sorted internally


def test_content_hash_excludes_node_id():
    """Two submitters with identical evidence produce the same content
    hash — that's the whole point of the duplicate-detection scheme."""
    a = evidence_content_hash("m1", "yes", ["e1"], "src")
    b = evidence_content_hash("m1", "yes", ["e1"], "src")
    assert a == b


def test_content_hash_distinguishes_outcomes():
    yes_h = evidence_content_hash("m1", "yes", ["e1"], "src")
    no_h = evidence_content_hash("m1", "no", ["e1"], "src")
    assert yes_h != no_h


def test_submission_hash_includes_node_id():
    chash = evidence_content_hash("m1", "yes", ["e1"], "src")
    a = submission_hash(chash, "alice", 100.0)
    b = submission_hash(chash, "bob", 100.0)
    assert a != b


def test_collect_evidence_marks_first_per_side():
    chain = [
        _evidence("m1", "alice", "yes", hashes=["e1"], desc="src1", ts=10, seq=1),
        _evidence("m1", "bob",   "yes", hashes=["e2"], desc="src2", ts=20, seq=2),
        _evidence("m1", "carol", "no",  hashes=["e3"], desc="src3", ts=30, seq=3),
    ]
    bundles = collect_evidence("m1", chain)
    by_node = {b.node_id: b for b in bundles}
    assert by_node["alice"].is_first_for_side
    assert not by_node["bob"].is_first_for_side
    assert by_node["carol"].is_first_for_side


def test_duplicate_content_does_not_get_first_bonus():
    """If two submitters submit the same content hash for the same
    side, only the temporally-first one is flagged. The second is a
    duplicate, NOT eligible for the bonus."""
    chash = evidence_content_hash("m1", "yes", ["e1"], "src")
    chain = [
        make_event("evidence_submit", "alice",
                   {"market_id": "m1", "claimed_outcome": "yes",
                    "evidence_hashes": ["e1"], "source_description": "src",
                    "evidence_content_hash": chash,
                    "submission_hash": submission_hash(chash, "alice", 10.0),
                    "bond": 2.0},
                   timestamp=10.0, sequence=1),
        make_event("evidence_submit", "bob",
                   {"market_id": "m1", "claimed_outcome": "yes",
                    "evidence_hashes": ["e1"], "source_description": "src",
                    "evidence_content_hash": chash,
                    "submission_hash": submission_hash(chash, "bob", 20.0),
                    "bond": 2.0},
                   timestamp=20.0, sequence=2),
    ]
    bundles = collect_evidence("m1", chain)
    by_node = {b.node_id: b for b in bundles}
    assert by_node["alice"].is_first_for_side
    assert not by_node["bob"].is_first_for_side


def test_is_first_for_side_when_no_evidence():
    chash = evidence_content_hash("m1", "yes", ["e1"], "src")
    assert is_first_for_side("m1", "yes", chash, [])


def test_is_first_for_side_after_existing_submission():
    chain = [
        _evidence("m1", "alice", "yes", hashes=["e1"], desc="src", ts=10, seq=1),
    ]
    chash = evidence_content_hash("m1", "yes", ["e2"], "src2")
    # Even with a different content hash, alice already grabbed the
    # first-for-side slot for "yes".
    assert not is_first_for_side("m1", "yes", chash, chain)
    # The "no" side is still first-eligible.
    chash_no = evidence_content_hash("m1", "no", ["e2"], "src2")
    assert is_first_for_side("m1", "no", chash_no, chain)


def test_collect_evidence_filters_other_markets():
    chain = [
        _evidence("m1", "alice", "yes", hashes=["e1"], desc="src", ts=10, seq=1),
        _evidence("m2", "bob",   "yes", hashes=["e2"], desc="src", ts=20, seq=2),
    ]
    bundles = collect_evidence("m1", chain)
    assert len(bundles) == 1
    assert bundles[0].node_id == "alice"


def test_collect_evidence_sorts_by_chain_order():
    """Out-of-order timestamp insertions should still be sorted."""
    chain = [
        _evidence("m1", "bob",   "yes", hashes=["e2"], desc="src", ts=20, seq=2),
        _evidence("m1", "alice", "yes", hashes=["e1"], desc="src", ts=10, seq=1),
    ]
    bundles = collect_evidence("m1", chain)
    assert bundles[0].node_id == "alice"
    assert bundles[1].node_id == "bob"
