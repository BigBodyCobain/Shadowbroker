"""Bootstrap mode — Argon2id PoW + eligibility + one-vote-per-node dedup.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.10 step 0.5.

Bootstrap mode replaces oracle-rep-weighted resolution with
**eligible-node-one-vote** for the first ``bootstrap_market_count``
(default 100) markets. Each eligible Heavy Node submits a
``bootstrap_resolution_vote`` event with an Argon2id PoW solution.

Key Sprint 8 invariants:

- **Argon2id is Heavy-Node-only.** Light Nodes lack the ≥64 MB RAM
  required per computation. The PoW verifier does NOT run on Light
  Nodes.
- **Salt = raw ``snapshot_event_hash`` bytes.** Hex-encoding or any
  reformatting causes a consensus fork. The salt MUST be the exact
  byte sequence of the snapshot event hash.
- **Leading-zero check is on RAW output bytes, MSB first.** Different
  bit ordering causes a consensus fork.
- **Identity age is measured against ``market.snapshot.frozen_at``,
  NOT against ``now``.** This is deterministic — every node computes
  the same eligibility from the same chain state. Prevents clock
  manipulation.
- **One-vote-per-node tie-break is stateless.** Among multiple votes
  from the same node_id for the same market_id, the canonical vote is
  the one with the LOWEST LEXICOGRAPHICAL ``event_hash``. Every node
  selects the same canonical vote regardless of observation order.
- **Anti-DoS funnel runs cheapest-first.** Schema → signature →
  identity age → predictor exclusion → phase + dedup → Argon2id.
  Argon2id is last because it's the most expensive.

Sprint 8 ships the eligibility + dedup + ramp pipeline in pure
Python. ``verify_pow`` is a structural verifier that takes the
already-computed hash output as input — it does NOT call Argon2id
itself. Production callers wire this through ``privacy-core`` Rust.
A future sprint will add the Rust binding; until then, tests
synthesize valid hash outputs.
"""

from services.infonet.bootstrap.argon2id import (
    canonical_pow_preimage,
    has_leading_zero_bits,
    verify_pow_structure,
)
from services.infonet.bootstrap.eligibility import (
    EligibilityDecision,
    is_identity_age_eligible,
    validate_bootstrap_eligibility,
)
from services.infonet.bootstrap.filter_funnel import (
    FunnelStage,
    run_filter_funnel,
)
from services.infonet.bootstrap.one_vote_dedup import (
    canonical_event_hash,
    deduplicate_votes,
)
from services.infonet.bootstrap.ramp import (
    ActiveFeatures,
    compute_active_features,
    network_node_count,
)

__all__ = [
    "ActiveFeatures",
    "EligibilityDecision",
    "FunnelStage",
    "canonical_event_hash",
    "canonical_pow_preimage",
    "compute_active_features",
    "deduplicate_votes",
    "has_leading_zero_bits",
    "is_identity_age_eligible",
    "network_node_count",
    "run_filter_funnel",
    "validate_bootstrap_eligibility",
    "verify_pow_structure",
]
