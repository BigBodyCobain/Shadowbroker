"""Epoch checkpoint model.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.14 Rule 4
("Epoch checkpoint: a global Merkle root for that epoch agreed upon
by a threshold of Heavy Nodes across Reticulum bridges. Epoch
duration, threshold, and checkpoint protocol: OPEN ENGINEERING
PROBLEM").

Sprint 10 ships the **structural model** only. The inter-node
agreement protocol (BFT vs threshold sigs vs DAG-style) is open per
IMPLEMENTATION_PLAN §6.5 and is intentionally NOT specified here.

What IS specified:

- A canonical ``EpochCheckpoint`` dataclass: epoch_id + root_hash +
  participating_heavy_node_ids + threshold.
- A ``canonical_epoch_root`` helper that computes a deterministic
  SHA-256 over a chain segment for a given epoch window. Every
  Heavy Node computes the same value from the same chain prefix —
  that's the whole point of the structural commitment.
- An ``is_checkpoint_confirmed`` predicate that says "yes, this
  epoch's root has Heavy Node agreement at or above the threshold".

When the inter-node protocol lands, it produces ``EpochCheckpoint``
records that ``is_checkpoint_confirmed`` consults. Until then,
producers can hand-construct test scenarios.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class EpochCheckpointStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"  # threshold not met by epoch deadline


@dataclass(frozen=True)
class EpochCheckpoint:
    """One epoch's chain-state commitment.

    ``root_hash`` is computed over the epoch's chain events using
    ``canonical_epoch_root``. ``participating_heavy_node_ids``
    records which Heavy Nodes have signed off on this root —
    confirmation requires ``len(participating) / total_heavy >=
    threshold``.

    Sprint 10 simplification: ``signatures`` is a dict from
    ``heavy_node_id`` to a placeholder bytes blob. Production wires
    in the chosen threshold-signature scheme (BLS, FROST, etc.) —
    those signatures aggregate into a single root signature, but
    Sprint 10's structural model just tracks who signed.
    """
    epoch_id: int
    root_hash: str
    epoch_start_ts: float
    epoch_end_ts: float
    participating_heavy_node_ids: frozenset[str] = frozenset()
    signatures: dict[str, bytes] = field(default_factory=dict)
    threshold: float = 0.67  # 67% of Heavy Nodes — same as upgrade activation

    def participation_fraction(self, *, total_heavy_nodes: int) -> float:
        if total_heavy_nodes <= 0:
            return 0.0
        return len(self.participating_heavy_node_ids) / total_heavy_nodes

    def status(self, *, total_heavy_nodes: int, now: float) -> EpochCheckpointStatus:
        if self.participation_fraction(total_heavy_nodes=total_heavy_nodes) >= self.threshold:
            return EpochCheckpointStatus.CONFIRMED
        if now > self.epoch_end_ts:
            return EpochCheckpointStatus.FAILED
        return EpochCheckpointStatus.PENDING


def canonical_epoch_root(
    chain: Iterable[dict[str, Any]],
    *,
    epoch_start_ts: float,
    epoch_end_ts: float,
) -> str:
    """SHA-256 over canonically-serialized events in the epoch window.

    Events are filtered by ``epoch_start_ts <= timestamp < epoch_end_ts``
    and sorted by ``(timestamp, sequence, event_id-or-hash)`` for
    deterministic ordering. Empty epoch returns the SHA-256 of the
    empty string (so even an "empty" epoch has a stable root).

    Every Heavy Node computing this from the same chain prefix gets
    the same hex string. Disagreement on this value is the signal
    that a partition has produced divergent histories.
    """
    in_window: list[dict[str, Any]] = []
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        try:
            ts = float(ev.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            continue
        if epoch_start_ts <= ts < epoch_end_ts:
            in_window.append(ev)

    in_window.sort(key=lambda e: (
        float(e.get("timestamp") or 0.0),
        int(e.get("sequence") or 0),
        str(e.get("event_id") or ""),
    ))

    h = hashlib.sha256()
    for ev in in_window:
        encoded = json.dumps(
            ev, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        h.update(encoded.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def is_checkpoint_confirmed(
    checkpoint: EpochCheckpoint,
    *,
    total_heavy_nodes: int,
    now: float,
) -> bool:
    """Convenience: ``True`` iff the checkpoint has reached the
    Heavy Node threshold."""
    return (
        checkpoint.status(total_heavy_nodes=total_heavy_nodes, now=now)
        == EpochCheckpointStatus.CONFIRMED
    )


__all__ = [
    "EpochCheckpoint",
    "EpochCheckpointStatus",
    "canonical_epoch_root",
    "is_checkpoint_confirmed",
]
