"""Two-tier state model + epoch finality (Sprint 10).

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.14 Rule 4,
``infonet-economy/IMPLEMENTATION_PLAN.md`` §3.7.

Splits protocol state into two consistency tiers:

- **Tier 1 — Eventually consistent (CRDT-friendly).** Common rep,
  gate activity, content posting, upreps, vote karma. Computed
  locally during partitions; merges without conflict on reconnect.
- **Tier 2 — Epoch finality required.** Oracle rep minting,
  governance execution, market FINAL status, dispute outcomes,
  (eventually) coin minting / dividends. MUST NOT become
  economically final until an epoch checkpoint is confirmed by a
  threshold of Heavy Nodes across Reticulum bridges.

Sprint 10 ships the Tier-1/Tier-2 classification, the chain-staleness
heuristic that producers consult to set ``is_provisional=True`` on
Tier-2 events, and the structural model for an `EpochCheckpoint`. The
full epoch-checkpoint protocol (BFT / threshold sigs / DAG) is open
engineering work — IMPLEMENTATION_PLAN §6.5 — and is intentionally
NOT specified here. The model + thresholds are in place; the
inter-node agreement protocol slots in later.

Why this matters today: ``oracle_rep._market_is_mintable`` (Sprint 2)
already gates on ``is_provisional == False``. Sprint 10 gives
producers the helper to set that flag correctly.
"""

from services.infonet.partition.epoch_checkpoint import (
    EpochCheckpoint,
    EpochCheckpointStatus,
    canonical_epoch_root,
    is_checkpoint_confirmed,
)
from services.infonet.partition.provisional import (
    DEFAULT_MAX_CHAIN_LAG_S,
    chain_lag_seconds,
    is_chain_stale,
    should_mark_provisional,
)
from services.infonet.partition.two_tier_state import (
    TIER1_EVENT_TYPES,
    TIER2_EVENT_TYPES,
    classify_event_type,
)

__all__ = [
    "DEFAULT_MAX_CHAIN_LAG_S",
    "EpochCheckpoint",
    "EpochCheckpointStatus",
    "TIER1_EVENT_TYPES",
    "TIER2_EVENT_TYPES",
    "canonical_epoch_root",
    "chain_lag_seconds",
    "classify_event_type",
    "is_chain_stale",
    "is_checkpoint_confirmed",
    "should_mark_provisional",
]
