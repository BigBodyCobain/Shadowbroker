"""Evidence canonicalization + first-submitter detection.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §2.2 (evidence
bundle fields), §3.10 (Step 4 — bond resolution + first-submitter
bonus).

Two distinct hashes per evidence bundle:

- ``evidence_content_hash`` — SHA-256 of ``(market_id || claimed_outcome
  || sorted(evidence_hashes) || normalized_utf8(source_description))``.
  **Excludes node_id**. Two submitters who present the same evidence
  produce the same content hash — used for duplicate detection across
  authors.
- ``submission_hash`` — SHA-256 of ``(evidence_content_hash || node_id
  || timestamp)``. **Includes node_id**. Used for authorship + chain
  ordering + first-submitter detection.

"Same evidence = same evidence_content_hash" — submission ordering
determines who is the FIRST submitter for a side. The first submitter
per outcome side gets ``CONFIG['evidence_first_bonus']`` (capped by the
losing-bond pool, never minted) when their side wins.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _normalize_utf8(s: str) -> str:
    """NFC-normalize so visually-identical strings hash identically."""
    return unicodedata.normalize("NFC", s)


def evidence_content_hash(
    market_id: str,
    claimed_outcome: str,
    evidence_hashes: list[str],
    source_description: str,
) -> str:
    """SHA-256 of the canonical evidence content. Excludes node_id."""
    if claimed_outcome not in ("yes", "no"):
        raise ValueError("claimed_outcome must be 'yes' or 'no'")
    sorted_hashes = sorted(str(h) for h in (evidence_hashes or []))
    canonical = "|".join([
        "evidence_content",
        str(market_id),
        claimed_outcome,
        ",".join(sorted_hashes),
        _normalize_utf8(str(source_description or "")),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def submission_hash(
    content_hash: str,
    node_id: str,
    timestamp: float,
) -> str:
    """SHA-256 of ``content_hash || node_id || timestamp``.

    Timestamp is rendered with ``repr(float)`` for cross-implementation
    determinism — Python's repr gives the shortest round-trippable
    decimal, which is stable across CPython versions.
    """
    canonical = "|".join([
        "evidence_submission",
        str(content_hash),
        str(node_id),
        repr(float(timestamp)),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceBundle:
    """Chain-derived view of one ``evidence_submit`` event."""
    node_id: str
    market_id: str
    claimed_outcome: str
    evidence_hashes: tuple[str, ...]
    source_description: str
    bond: float
    timestamp: float
    sequence: int
    content_hash: str
    submission_hash: str
    is_first_for_side: bool


def collect_evidence(
    market_id: str,
    chain: Iterable[dict[str, Any]],
) -> list[EvidenceBundle]:
    """Return all ``evidence_submit`` events for ``market_id`` as
    ``EvidenceBundle``s, sorted by chain order, with
    ``is_first_for_side`` set on the first event per outcome side
    whose ``content_hash`` is unique within that side.
    """
    events: list[dict[str, Any]] = []
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "evidence_submit":
            continue
        if _payload(ev).get("market_id") != market_id:
            continue
        events.append(ev)
    events.sort(key=lambda e: (float(e.get("timestamp") or 0.0), int(e.get("sequence") or 0)))

    seen_content_per_side: dict[str, set[str]] = {"yes": set(), "no": set()}
    bundles: list[EvidenceBundle] = []
    first_set_per_side: dict[str, bool] = {"yes": False, "no": False}

    for ev in events:
        p = _payload(ev)
        node_id = ev.get("node_id")
        outcome = p.get("claimed_outcome")
        if not isinstance(node_id, str) or not node_id:
            continue
        if outcome not in ("yes", "no"):
            continue
        evhashes = p.get("evidence_hashes") or []
        if not isinstance(evhashes, list):
            continue
        source_desc = p.get("source_description") or ""
        bond = p.get("bond")
        try:
            bond_f = float(bond) if bond is not None else 0.0
        except (TypeError, ValueError):
            bond_f = 0.0
        ts = float(ev.get("timestamp") or 0.0)
        seq = int(ev.get("sequence") or 0)

        chash = p.get("evidence_content_hash") or evidence_content_hash(
            market_id, outcome, [str(h) for h in evhashes], str(source_desc),
        )
        shash = p.get("submission_hash") or submission_hash(chash, node_id, ts)

        # First-for-side: this event is the first occurrence (in chain
        # order) of a content hash for this side that we haven't seen
        # before. Duplicate submitters of the same content do NOT
        # qualify for the bonus.
        is_first = False
        if chash not in seen_content_per_side[outcome] and not first_set_per_side[outcome]:
            is_first = True
            first_set_per_side[outcome] = True
        seen_content_per_side[outcome].add(chash)

        bundles.append(EvidenceBundle(
            node_id=node_id,
            market_id=str(market_id),
            claimed_outcome=outcome,
            evidence_hashes=tuple(str(h) for h in evhashes),
            source_description=str(source_desc),
            bond=bond_f,
            timestamp=ts,
            sequence=seq,
            content_hash=str(chash),
            submission_hash=str(shash),
            is_first_for_side=is_first,
        ))
    return bundles


def is_first_for_side(
    market_id: str,
    claimed_outcome: str,
    candidate_content_hash: str,
    chain: Iterable[dict[str, Any]],
) -> bool:
    """Would a NEW evidence submission with ``candidate_content_hash``
    be the first for ``claimed_outcome``?

    True if no prior ``evidence_submit`` for ``market_id`` on
    ``claimed_outcome`` exists (regardless of content hash). The bonus
    is for being temporally first per side, not per content hash.
    """
    if claimed_outcome not in ("yes", "no"):
        return False
    for bundle in collect_evidence(market_id, chain):
        if bundle.claimed_outcome == claimed_outcome:
            return False
    return True


__all__ = [
    "EvidenceBundle",
    "collect_evidence",
    "evidence_content_hash",
    "is_first_for_side",
    "submission_hash",
]
