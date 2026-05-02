"""Soft feature activation ramp — node-count milestones.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §1.2
(``CONFIG['bootstrap_threshold']`` comment) + the spec's general
"phase activation by network size" theme.

The protocol activates features in stages as the network grows. The
canonical milestones are 1k / 2k / 5k / 10k node count, but the
specific thresholds and which features they unlock are a Sprint 8+
design choice that's expected to evolve via governance.

Sprint 8 ships:

- ``network_node_count(chain)`` — distinct ``node_register`` events
  on the chain.
- ``compute_active_features(chain)`` — returns an ``ActiveFeatures``
  flag set indicating which protocol features are currently active.

Today's bindings:

- ``bootstrap_resolution_active`` — True while node count is below
  ``bootstrap_threshold`` (default 1000). Bootstrap-mode markets use
  eligible-node-one-vote resolution.
- ``staked_resolution_active`` — True once node count crosses 1k.
  Oracle-rep-weighted resolution staking is the primary mechanism.
- ``governance_petitions_active`` — True at 2k+. Petitions can be
  filed.
- ``upgrade_governance_active`` — True at 5k+. Upgrade-hash
  governance is unlocked.
- ``commoncoin_active`` — True at 10k+. CommonCoin minting starts.

These bindings are intentionally simple — production wiring will
read them via governance petitions that adjust ``bootstrap_threshold``
and the milestones themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from services.infonet.config import CONFIG


def network_node_count(chain: Iterable[dict[str, Any]]) -> int:
    """Distinct nodes that have appeared on the chain.

    Counted as: distinct ``node_id`` from ``node_register`` events.
    If no ``node_register`` events exist on the chain (e.g. test
    chains that only synthesize markets/predictions), falls back to
    distinct authoring nodes across all events. Production chains
    will have the registers.
    """
    registered: set[str] = set()
    fallback: set[str] = set()
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        node = ev.get("node_id")
        if not isinstance(node, str) or not node:
            continue
        fallback.add(node)
        if ev.get("event_type") == "node_register":
            registered.add(node)
    return len(registered) if registered else len(fallback)


@dataclass(frozen=True)
class ActiveFeatures:
    bootstrap_resolution_active: bool
    staked_resolution_active: bool
    governance_petitions_active: bool
    upgrade_governance_active: bool
    commoncoin_active: bool
    node_count: int


# Milestone thresholds promoted to CONFIG 2026-04-28 (Sprint 8 polish).
# Governance can now tune them via petition; the cross-field invariant
# in config.py enforces strict ascending order across the four tiers.


def compute_active_features(chain: Iterable[dict[str, Any]]) -> ActiveFeatures:
    chain_list = [e for e in chain if isinstance(e, dict)]
    n = network_node_count(chain_list)
    bootstrap_threshold = int(CONFIG["bootstrap_threshold"])
    return ActiveFeatures(
        # Bootstrap resolution is active until the network crosses the
        # bootstrap_threshold. Once crossed, it's still allowed for
        # bootstrap-indexed markets, but new markets default to
        # staked resolution.
        bootstrap_resolution_active=n < bootstrap_threshold,
        staked_resolution_active=n >= int(CONFIG["ramp_staked_resolution_threshold"]),
        governance_petitions_active=n >= int(CONFIG["ramp_petitions_threshold"]),
        upgrade_governance_active=n >= int(CONFIG["ramp_upgrade_threshold"]),
        commoncoin_active=n >= int(CONFIG["ramp_commoncoin_threshold"]),
        node_count=n,
    )


__all__ = [
    "ActiveFeatures",
    "compute_active_features",
    "network_node_count",
]
