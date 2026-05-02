"""Market resolution — the RULES §3.10 decision procedure.

Pure function over the chain. Returns a structured ``ResolutionResult``
with the decided outcome plus all rep-transfer effects (bond returns /
forfeits / first-submitter bonuses / loser-pool burns / stalemate
burns / DA bond slashing).

Sprint 5 layers in the Round 8 defenses on top of Sprint 4's
state-machine scaffolding:

- DATA_UNAVAILABLE phantom-evidence slashing — when DA stakes meet
  the threshold, ALL evidence bonds are forfeited (burned), DA voters
  get full return, yes/no stakers take the stalemate burn.
- Stalemate burn on supermajority-failed INVALID — when both sides
  staked above the min total but no side reached the supermajority,
  ALL resolution stakes (yes/no/DA) take the burn. Bonds are returned
  in good faith — the market failed, not the submitters.

What Sprint 5 still does NOT handle:

- Bootstrap-mode resolution (Sprint 8 — ``bootstrap_resolution_vote``
  events with Argon2id PoW).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.identity_rotation import rotation_descendants
from services.infonet.markets.data_unavailable import (
    is_data_unavailable_triggered,
    resolve_data_unavailable_effects,
)
from services.infonet.markets.evidence import collect_evidence
from services.infonet.markets.snapshot import find_snapshot
from services.infonet.markets.stalemate_burn import apply_to_stakes


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def excluded_predictor_ids(
    market_id: str,
    chain: Iterable[dict[str, Any]],
) -> set[str]:
    """Predictor exclusion set for ``market_id`` resolution.

    RULES §3.13 / §3.10 Step 1: ``frozen_predictor_ids ∪
    rotation_descendants(frozen_predictor_ids)``. Walks the on-chain
    rotation links — never mutates the snapshot.

    Returns an empty set if no snapshot exists yet. The caller decides
    whether that means "open for everyone" (no exclusion) or "reject
    all" (snapshot required) — Sprint 4 ``collect_resolution_stakes``
    treats absence-of-snapshot as "no exclusion".
    """
    snapshot = find_snapshot(market_id, chain)
    if snapshot is None:
        return set()
    frozen = snapshot.get("frozen_predictor_ids") or []
    if not isinstance(frozen, list):
        return set()
    base: set[str] = {str(x) for x in frozen if isinstance(x, str) and x}
    out = set(base)
    chain_list = [e for e in chain if isinstance(e, dict)]
    for original in base:
        for desc in rotation_descendants(original, chain_list):
            out.add(desc)
    return out


def is_predictor_excluded(
    node_id: str,
    market_id: str,
    chain: Iterable[dict[str, Any]],
) -> bool:
    return node_id in excluded_predictor_ids(market_id, chain)


@dataclass
class _ResolutionStake:
    node_id: str
    side: str
    amount: float
    rep_type: str
    timestamp: float
    sequence: int


def collect_resolution_stakes(
    market_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    exclude_predictors: bool = True,
) -> list[_ResolutionStake]:
    """All ``resolution_stake`` events for ``market_id`` (sorted),
    with predictor exclusion applied by default.

    Excluded stakes are silently dropped — they cannot influence the
    outcome (RULES §3.10 Step 1). The producer-side check should also
    refuse to emit them in the first place, but the resolver MUST
    enforce here too because the chain is ingested from peers.
    """
    excluded = excluded_predictor_ids(market_id, chain) if exclude_predictors else set()
    out: list[_ResolutionStake] = []
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "resolution_stake":
            continue
        p = _payload(ev)
        if p.get("market_id") != market_id:
            continue
        node_id = ev.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            continue
        if node_id in excluded:
            continue
        side = p.get("side")
        if side not in ("yes", "no", "data_unavailable"):
            continue
        amount = p.get("amount")
        try:
            amt = float(amount) if amount is not None else 0.0
        except (TypeError, ValueError):
            continue
        if amt <= 0:
            continue
        rep_type = p.get("rep_type")
        if rep_type not in ("oracle", "common"):
            continue
        out.append(_ResolutionStake(
            node_id=node_id,
            side=side,
            amount=amt,
            rep_type=rep_type,
            timestamp=float(ev.get("timestamp") or 0.0),
            sequence=int(ev.get("sequence") or 0),
        ))
    out.sort(key=lambda s: (s.timestamp, s.sequence))
    return out


@dataclass
class ResolutionResult:
    """Outcome + every rep-transfer effect that resolution should apply.

    The producer of ``resolution_finalize`` writes the outcome onto the
    chain; downstream chain readers (`oracle_rep`, `common_rep`)
    recompute their views from the chain alone — they do not consume
    this struct. The struct exists for tests and for the UI's
    "resolution explainer" view, where users want to see *why* a market
    resolved a particular way.
    """
    market_id: str
    outcome: str           # "yes" | "no" | "invalid"
    is_provisional: bool
    reason: str            # short diagnostic — e.g. "no_evidence", "supermajority_yes"
    bond_returns: dict[str, float] = field(default_factory=dict)
    bond_forfeits: dict[str, float] = field(default_factory=dict)
    first_submitter_bonuses: dict[str, float] = field(default_factory=dict)
    stake_returns: dict[tuple[str, str], float] = field(default_factory=dict)
    """``{(node_id, rep_type): amount}`` — full or partial returns of
    resolution stakes (winners and stalemate-INVALID returns)."""
    stake_winnings: dict[tuple[str, str], float] = field(default_factory=dict)
    """``{(node_id, rep_type): amount}`` — extra winnings from the
    loser pool (winners only)."""
    burned_amount: float = 0.0


def _supermajority_winner(
    yes: float,
    no: float,
    threshold: float,
) -> str | None:
    total = yes + no
    if total <= 0:
        return None
    if yes / total >= threshold:
        return "yes"
    if no / total >= threshold:
        return "no"
    return None


def resolve_market(
    market_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    is_provisional: bool = False,
) -> ResolutionResult:
    """Apply RULES §3.10 to compute the resolution.

    Sprint 4 implements:

    - Step 0: zero-evidence → INVALID (return all stakes, no penalty).
    - Step 1: predictor exclusion via ``collect_resolution_stakes``.
    - Step 1.5 (partial): DA threshold detection → INVALID.
      *Phantom-evidence slashing is Sprint 5.*
    - Step 2: oracle-rep supermajority check.
      *Stalemate burn is Sprint 5.*
    - Step 2.5: winning-side evidence required.
    - Step 3: distribute resolution stakes (oracle + common pools, 2%
      loser burn).
    - Step 4: evidence bond resolution + first-submitter bonus capped
      at losing-bond-pool budget.

    Bootstrap-mode markets (``bootstrap_index <=
    CONFIG['bootstrap_market_count']``) take a different path that
    Sprint 8 will provide. Until then bootstrap markets resolve to
    INVALID with reason ``bootstrap_pending``.
    """
    chain_list = [e for e in chain if isinstance(e, dict)]
    create_event = next(
        (e for e in chain_list if e.get("event_type") == "prediction_create"
         and _payload(e).get("market_id") == market_id),
        None,
    )
    if create_event is None:
        return ResolutionResult(
            market_id=market_id, outcome="invalid",
            is_provisional=is_provisional, reason="no_market",
        )

    create_payload = _payload(create_event)
    bootstrap_index = create_payload.get("bootstrap_index")
    if bootstrap_index is not None:
        try:
            bootstrap_index = int(bootstrap_index)
        except (TypeError, ValueError):
            bootstrap_index = None

    bundles = collect_evidence(market_id, chain_list)
    stakes = collect_resolution_stakes(market_id, chain_list, exclude_predictors=True)

    # Step 0: zero-evidence → INVALID, return everything.
    if not bundles:
        result = ResolutionResult(
            market_id=market_id, outcome="invalid",
            is_provisional=is_provisional, reason="no_evidence",
        )
        for s in stakes:
            result.stake_returns[(s.node_id, s.rep_type)] = (
                result.stake_returns.get((s.node_id, s.rep_type), 0.0) + s.amount
            )
        return result

    # Step 0.5: bootstrap mode (Sprint 8 — eligible-node-one-vote).
    if (bootstrap_index is not None
            and bootstrap_index <= int(CONFIG["bootstrap_market_count"])):
        from services.infonet.bootstrap import (
            deduplicate_votes,
            validate_bootstrap_eligibility,
        )

        canonical_votes = deduplicate_votes(market_id, chain_list)
        # Filter to eligible voters per RULES §3.10 step 0.5
        # is_bootstrap_eligible.
        eligible_votes = []
        for v in canonical_votes:
            node_id = v.get("node_id")
            if not isinstance(node_id, str) or not node_id:
                continue
            if not validate_bootstrap_eligibility(node_id, market_id, chain_list).eligible:
                continue
            side = _payload(v).get("side")
            if side not in ("yes", "no"):
                continue
            eligible_votes.append((node_id, side))

        votes_yes = sum(1 for _, side in eligible_votes if side == "yes")
        votes_no = sum(1 for _, side in eligible_votes if side == "no")
        votes_total = votes_yes + votes_no

        # Min participation gate.
        if votes_total < int(CONFIG["min_market_participants"]):
            result = ResolutionResult(
                market_id=market_id, outcome="invalid",
                is_provisional=is_provisional,
                reason="bootstrap_below_min_participation",
            )
            for b in bundles:
                result.bond_returns[b.node_id] = (
                    result.bond_returns.get(b.node_id, 0.0) + b.bond
                )
            return result

        threshold = float(CONFIG["bootstrap_resolution_supermajority"])
        if votes_yes / votes_total >= threshold:
            winning_side = "yes"
        elif votes_no / votes_total >= threshold:
            winning_side = "no"
        else:
            result = ResolutionResult(
                market_id=market_id, outcome="invalid",
                is_provisional=is_provisional,
                reason="bootstrap_no_supermajority",
            )
            for b in bundles:
                result.bond_returns[b.node_id] = (
                    result.bond_returns.get(b.node_id, 0.0) + b.bond
                )
            return result

        # Step 2.5 (winning-side evidence required) still applies in
        # bootstrap mode.
        winning_evidence = [b for b in bundles if b.claimed_outcome == winning_side]
        if not winning_evidence:
            result = ResolutionResult(
                market_id=market_id, outcome="invalid",
                is_provisional=is_provisional,
                reason="no_winning_side_evidence",
            )
            for b in bundles:
                result.bond_returns[b.node_id] = (
                    result.bond_returns.get(b.node_id, 0.0) + b.bond
                )
            return result

        # Bootstrap markets pass directly to prediction scoring — no
        # resolution-stake settlement (no oracle-rep stakes were
        # collected). Evidence bonds are returned (they were 0 in
        # bootstrap mode by spec, but stated for completeness).
        result = ResolutionResult(
            market_id=market_id, outcome=winning_side,
            is_provisional=is_provisional,
            reason=f"bootstrap_supermajority_{winning_side}",
        )
        for b in bundles:
            if b.claimed_outcome == winning_side:
                result.bond_returns[b.node_id] = (
                    result.bond_returns.get(b.node_id, 0.0) + b.bond
                )
            else:
                result.bond_forfeits[b.node_id] = (
                    result.bond_forfeits.get(b.node_id, 0.0) + b.bond
                )
        return result

    # Step 1.5: DA threshold check (Sprint 5 — phantom-evidence slashing).
    if is_data_unavailable_triggered(stakes):
        result = ResolutionResult(
            market_id=market_id, outcome="invalid",
            is_provisional=is_provisional, reason="data_unavailable",
        )
        effects = resolve_data_unavailable_effects(stakes, bundles)
        for k, v in effects["stake_returns"].items():
            result.stake_returns[k] = result.stake_returns.get(k, 0.0) + v
        for node, amount in effects["bond_forfeits"].items():
            result.bond_forfeits[node] = result.bond_forfeits.get(node, 0.0) + amount
        result.burned_amount += float(effects["burned"])
        return result

    # Step 2: oracle-rep supermajority.
    yes_oracle = sum(s.amount for s in stakes if s.side == "yes" and s.rep_type == "oracle")
    no_oracle = sum(s.amount for s in stakes if s.side == "no" and s.rep_type == "oracle")
    if yes_oracle + no_oracle < float(CONFIG["min_resolution_stake_total"]):
        result = ResolutionResult(
            market_id=market_id, outcome="invalid",
            is_provisional=is_provisional, reason="below_min_resolution_stake",
        )
        for s in stakes:
            result.stake_returns[(s.node_id, s.rep_type)] = (
                result.stake_returns.get((s.node_id, s.rep_type), 0.0) + s.amount
            )
        for b in bundles:
            result.bond_returns[b.node_id] = result.bond_returns.get(b.node_id, 0.0) + b.bond
        return result

    threshold = float(CONFIG["resolution_supermajority"])
    winning_side = _supermajority_winner(yes_oracle, no_oracle, threshold)
    if winning_side is None:
        # No supermajority — Sprint 5 stalemate burn applies.
        # Per RULES §3.10 step 2 alternate: ALL resolution stakes
        # (yes / no / DA) take the burn; bonds are returned in good
        # faith because the market failed (not the submitters).
        result = ResolutionResult(
            market_id=market_id, outcome="invalid",
            is_provisional=is_provisional, reason="no_supermajority",
        )
        burn_returns, burn_total = apply_to_stakes(
            ({"node_id": s.node_id, "rep_type": s.rep_type, "amount": s.amount} for s in stakes),
        )
        for k, v in burn_returns.items():
            result.stake_returns[k] = result.stake_returns.get(k, 0.0) + v
        result.burned_amount += burn_total
        for b in bundles:
            result.bond_returns[b.node_id] = result.bond_returns.get(b.node_id, 0.0) + b.bond
        return result

    # Step 2.5: winning-side evidence required.
    winning_evidence = [b for b in bundles if b.claimed_outcome == winning_side]
    if not winning_evidence:
        result = ResolutionResult(
            market_id=market_id, outcome="invalid",
            is_provisional=is_provisional, reason="no_winning_side_evidence",
        )
        for s in stakes:
            result.stake_returns[(s.node_id, s.rep_type)] = (
                result.stake_returns.get((s.node_id, s.rep_type), 0.0) + s.amount
            )
        for b in bundles:
            result.bond_returns[b.node_id] = result.bond_returns.get(b.node_id, 0.0) + b.bond
        return result

    # Step 3: distribute resolution stakes per rep type.
    result = ResolutionResult(
        market_id=market_id, outcome=winning_side,
        is_provisional=is_provisional,
        reason=f"supermajority_{winning_side}",
    )
    burn_pct = float(CONFIG["resolution_loser_burn_pct"])

    for rep_type in ("oracle", "common"):
        winners = [s for s in stakes if s.side == winning_side and s.rep_type == rep_type]
        # Losers exclude data_unavailable here — they vote on evidence
        # quality, not outcome. Their stakes are returned in full.
        losers = [s for s in stakes
                  if s.side != winning_side
                  and s.side != "data_unavailable"
                  and s.rep_type == rep_type]
        winner_pool = sum(s.amount for s in winners)
        loser_pool = sum(s.amount for s in losers)

        # Always return the principal of winners and DA voters.
        for s in winners:
            result.stake_returns[(s.node_id, rep_type)] = (
                result.stake_returns.get((s.node_id, rep_type), 0.0) + s.amount
            )
        for s in stakes:
            if s.rep_type != rep_type:
                continue
            if s.side != "data_unavailable":
                continue
            result.stake_returns[(s.node_id, rep_type)] = (
                result.stake_returns.get((s.node_id, rep_type), 0.0) + s.amount
            )

        if winner_pool == 0 or loser_pool == 0:
            continue
        burn_amt = loser_pool * burn_pct
        distributable = loser_pool - burn_amt
        result.burned_amount += burn_amt
        for s in winners:
            share = s.amount / winner_pool
            winnings = share * distributable
            result.stake_winnings[(s.node_id, rep_type)] = (
                result.stake_winnings.get((s.node_id, rep_type), 0.0) + winnings
            )
        # Losing stakes are forfeited — don't return them.

    # Step 4: evidence bonds.
    losing_bond_pool = sum(b.bond for b in bundles if b.claimed_outcome != winning_side)
    bonus_budget = losing_bond_pool

    for b in bundles:
        if b.claimed_outcome == winning_side:
            result.bond_returns[b.node_id] = result.bond_returns.get(b.node_id, 0.0) + b.bond
            if b.is_first_for_side and bonus_budget > 0:
                bonus_amt = min(float(CONFIG["evidence_first_bonus"]), bonus_budget)
                if bonus_amt > 0:
                    result.first_submitter_bonuses[b.node_id] = (
                        result.first_submitter_bonuses.get(b.node_id, 0.0) + bonus_amt
                    )
                    bonus_budget -= bonus_amt
        else:
            result.bond_forfeits[b.node_id] = result.bond_forfeits.get(b.node_id, 0.0) + b.bond

    # Remaining unspent bonus budget burns (deflationary).
    result.burned_amount += bonus_budget

    # NOTE: subjective markets are allowed to resolve (they still
    # produce a final outcome), but oracle rep is not minted from them
    # — that gate lives in ``oracle_rep._market_is_mintable``.
    return result


__all__ = [
    "ResolutionResult",
    "collect_resolution_stakes",
    "excluded_predictor_ids",
    "is_predictor_excluded",
    "resolve_market",
]
