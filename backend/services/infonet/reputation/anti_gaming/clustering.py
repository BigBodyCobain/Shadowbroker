"""Clustering coefficient — detects sophisticated farming where the
voters who uprep a target also uprep each other.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.5.

For a target B:

    voters = {all nodes that uprepped B in decay window}
    n = len(voters)

    if n < 2:
        return 0.0

    possible_edges = n * (n - 1) / 2
    actual_edges = count of pairs (V1, V2) where V1 has uprepped V2
                   OR V2 has uprepped V1
    clustering = actual_edges / possible_edges

The penalty per RULES §3.3:

    target_penalty = max(clustering_min_weight, 1.0 - clustering)

Why this catches what VCS misses: VCS measures *one* upreper's
similarity to the target's fan set. Clustering measures whether the
*entire* fan set is socially networked — a 10-node cabal that
upreps each other is a cluster coefficient near 1.0 even if no
individual upreper has unusual VCS.
"""

from __future__ import annotations

from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.reputation.anti_gaming.vcs import _upreps_within_window  # noqa: I201


_SECONDS_PER_DAY = 86400.0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _decay_window_seconds(decay_window_days: float | None) -> float:
    if decay_window_days is not None:
        return float(decay_window_days) * _SECONDS_PER_DAY
    return float(CONFIG["vote_decay_days"]) * _SECONDS_PER_DAY


def compute_clustering_coefficient(
    target_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float | None = None,
    decay_window_days: float | None = None,
) -> float:
    """Coefficient in ``[0.0, 1.0]`` for ``target_id``'s voter graph.

    0.0 means voters are strangers; 1.0 means every voter has uprepped
    every other voter.
    """
    if not isinstance(target_id, str) or not target_id:
        return 0.0
    events = [e for e in chain if isinstance(e, dict)]
    if not events:
        return 0.0

    if now is None:
        now = max(float(ev.get("timestamp") or 0.0) for ev in events)
    window_s = _decay_window_seconds(decay_window_days)
    window_upreps = _upreps_within_window(events, now=now, window_s=window_s)

    voters: set[str] = set()
    edges: set[tuple[str, str]] = set()
    # Build an adjacency map from author -> {targets}.
    by_author: dict[str, set[str]] = {}
    for ev in window_upreps:
        author = ev.get("node_id")
        p = _payload(ev)
        tgt = p.get("target_node_id")
        if not isinstance(author, str) or not isinstance(tgt, str):
            continue
        if author == tgt:
            continue
        by_author.setdefault(author, set()).add(tgt)
        if tgt == target_id:
            voters.add(author)

    n = len(voters)
    if n < 2:
        return 0.0

    voter_list = sorted(voters)
    for i, v1 in enumerate(voter_list):
        for v2 in voter_list[i + 1:]:
            v1_upreps_v2 = v2 in by_author.get(v1, ())
            v2_upreps_v1 = v1 in by_author.get(v2, ())
            if v1_upreps_v2 or v2_upreps_v1:
                edges.add((v1, v2))

    possible = n * (n - 1) / 2
    return len(edges) / possible


def clustering_penalty(coefficient: float) -> float:
    """Per-uprep multiplier from a clustering coefficient.

    Spec formula: ``max(clustering_min_weight, 1.0 - coefficient)``.
    """
    floor = float(CONFIG["clustering_min_weight"])
    return max(floor, 1.0 - float(coefficient))


__all__ = [
    "clustering_penalty",
    "compute_clustering_coefficient",
]
