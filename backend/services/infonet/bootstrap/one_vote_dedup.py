"""Stateless one-vote-per-node dedup.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.10 step 0.5
("Phase valid + one-vote-per-node (stateless duplicate resolution)").

The protocol allows a node to submit only one
``bootstrap_resolution_vote`` per market_id. If duplicates appear
(retries, network split + heal, malicious flooding), the canonical
choice is **the vote with the lowest lexicographical event_hash**.

Key property: this is **stateless and order-independent**. Every node
computes the same canonical vote regardless of which duplicate they
saw first. No "last-write-wins" or "first-write-wins" — just the
hash comparison.

``event_hash = SHA-256(canonical_serialize(event))`` — must include
signature, payload, and metadata so two events with different
payloads produce different hashes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


def canonical_event_hash(event: dict[str, Any]) -> str:
    """SHA-256 of the canonically-serialized event.

    Canonicalization: sorted keys, compact separators, UTF-8.
    Includes every field on the event dict — payload, signature (if
    present), node_id, timestamp, sequence, event_type. Different
    inputs always produce different hashes.
    """
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def deduplicate_votes(
    market_id: str,
    chain: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the canonical set of ``bootstrap_resolution_vote`` events
    for ``market_id`` — at most one per ``node_id``, with the lowest
    lexicographical ``canonical_event_hash`` chosen on collision.

    The returned list is sorted by ``(node_id, event_hash)`` so the
    output is deterministic for any chain ordering.
    """
    candidates_per_node: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "bootstrap_resolution_vote":
            continue
        if _payload(ev).get("market_id") != market_id:
            continue
        node = ev.get("node_id")
        if not isinstance(node, str) or not node:
            continue
        h = canonical_event_hash(ev)
        candidates_per_node.setdefault(node, []).append((h, ev))

    canonical: list[dict[str, Any]] = []
    for node, candidates in candidates_per_node.items():
        # Lowest lexicographical event_hash wins. Stable secondary
        # sort by sequence to make the choice deterministic for
        # any duplicate hash (which would itself be a SHA-256
        # collision — so academically impossible).
        candidates.sort(key=lambda c: (c[0], int(c[1].get("sequence") or 0)))
        canonical.append(candidates[0][1])
    canonical.sort(key=lambda e: (e.get("node_id") or "", canonical_event_hash(e)))
    return canonical


__all__ = [
    "canonical_event_hash",
    "deduplicate_votes",
]
