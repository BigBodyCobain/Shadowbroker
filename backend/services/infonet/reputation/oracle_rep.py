"""Oracle rep computation — pure functions over the chain.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.1, §3.2, §3.11.

Constitutional anchor (``IMMUTABLE_PRINCIPLES["oracle_rep_source"] ==
"predictions_only"``): oracle rep may ONLY be minted by verified
predictions against reality. Sprint 2 enforces this by structurally
constraining the mint formula — there is no other code path that
returns a positive contribution to ``compute_oracle_rep``.

A market's prediction mints oracle rep only when ALL of the following
hold:

- The market produced a ``resolution_finalize`` event with
  ``outcome != "invalid"`` and ``is_provisional == False``.
- The corresponding ``market_snapshot`` shows
  ``frozen_participant_count >= CONFIG["min_market_participants"]`` AND
  ``frozen_total_stake >= CONFIG["min_market_total_stake"]``.
- The market is NOT a bootstrap-mode market (Sprint 8 will add the
  bootstrap path; until then bootstrap markets contribute zero).
- The market is objective. Subjective markets mint Common Rep only
  (RULES §3.1).
- The prediction's ``side`` matches the FINAL outcome.

Lost stakes from incorrect *staked* predictions reduce the running
``oracle_rep`` balance (RULES §3.2 — the staked amount is forfeited to
the winner pool). ``oracle_rep_lifetime`` is monotonically increasing
and ignores losses.

Sprint 2 does NOT yet handle:

- Dispute reversal (Sprint 5 — `dispute_resolve` with `outcome="reversed"`).
- Resolution-stake redistribution (Sprint 4/5 — `resolution_stake`
  events and the loser-pool burn).
- Anti-gaming farming multipliers (Sprint 3).

These layers will be added by their owning sprints; the function
signature and return shape are stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.markets.dispute import effective_outcome as _effective_outcome
from services.infonet.reputation.anti_gaming.farming import (
    compute_farming_pct,
    farming_multiplier,
)


def _as_event_list(chain: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept any iterable, return a stable list ordered by (timestamp, sequence)."""
    events = [e for e in chain if isinstance(e, dict)]
    events.sort(key=lambda e: (float(e.get("timestamp") or 0.0), int(e.get("sequence") or 0)))
    return events


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


@dataclass
class _MarketView:
    """Internal: chain-derived view of a single market.

    Populated in one pass over the chain. Holds only what oracle_rep
    needs to mint correctly per RULES §3.1/§3.2.
    """
    market_id: str
    market_type: str = "objective"
    bootstrap_index: int | None = None
    snapshot: dict[str, Any] | None = None
    finalize: dict[str, Any] | None = None
    finalize_ts: float = 0.0
    predictions: list[dict[str, Any]] = field(default_factory=list)
    farming_pct_lookup: dict[str, float] = field(default_factory=dict)


def _index_markets(events: list[dict[str, Any]]) -> dict[str, _MarketView]:
    markets: dict[str, _MarketView] = {}
    for ev in events:
        et = ev.get("event_type")
        p = _payload(ev)
        mid = p.get("market_id")
        if not isinstance(mid, str) or not mid:
            continue
        m = markets.setdefault(mid, _MarketView(market_id=mid))
        if et == "prediction_create":
            m.market_type = str(p.get("market_type") or "objective")
            if "bootstrap_index" in p and p["bootstrap_index"] is not None:
                try:
                    m.bootstrap_index = int(p["bootstrap_index"])
                except (TypeError, ValueError):
                    m.bootstrap_index = None
        elif et == "market_snapshot":
            m.snapshot = p
        elif et == "resolution_finalize":
            m.finalize = p
            m.finalize_ts = float(ev.get("timestamp") or 0.0)
        elif et == "prediction_place":
            m.predictions.append({
                "node_id": ev.get("node_id"),
                "side": p.get("side"),
                "stake_amount": p.get("stake_amount"),
                "probability_at_bet": p.get("probability_at_bet"),
                "timestamp": ev.get("timestamp"),
            })
    return markets


def _market_passes_liquidity(market: _MarketView) -> bool:
    snap = market.snapshot or {}
    try:
        participants = int(snap.get("frozen_participant_count") or 0)
        total_stake = float(snap.get("frozen_total_stake") or 0.0)
    except (TypeError, ValueError):
        return False
    return (
        participants >= int(CONFIG["min_market_participants"])
        and total_stake >= float(CONFIG["min_market_total_stake"])
    )


def _market_is_mintable(market: _MarketView) -> bool:
    """Return True if the market is final, non-provisional, non-bootstrap,
    objective, and passed liquidity. Mintable markets contribute oracle rep
    to correct predictors.
    """
    finalize = market.finalize
    if not finalize:
        return False
    if finalize.get("is_provisional") is not False:
        return False
    outcome = finalize.get("outcome")
    if outcome not in ("yes", "no"):
        return False
    if market.market_type != "objective":
        return False
    # Sprint 8: bootstrap markets that resolved via eligible-node-one-vote
    # mint oracle rep from correct predictions, same as normal markets.
    # The bootstrap mechanic only changes HOW resolution decides yes/no —
    # not whether predictors get rep for being correct. RULES §3.10 step
    # 0.5: "Oracle rep minted normally from correct predictions
    # (constitutional)".
    if not _market_passes_liquidity(market):
        return False
    return True


def _free_pred_mint(probability_at_bet: float) -> float:
    """RULES §3.1 — mint = max(oracle_min_earned, 1.0 - p/100)."""
    if probability_at_bet is None:
        return 0.0
    try:
        prob = float(probability_at_bet)
    except (TypeError, ValueError):
        return 0.0
    if not (0.0 <= prob <= 100.0):
        return 0.0
    return max(float(CONFIG["oracle_min_earned"]), 1.0 - (prob / 100.0))


def _staked_pred_settlement(
    stake_amount: float,
    side: str,
    outcome: str,
    predictions: list[dict[str, Any]],
) -> float:
    """RULES §3.2 — pool settlement for staked predictions.

    Returns the *net* change to oracle rep for a single staked
    prediction. Positive = winnings (returned stake + share of loser
    pool). Negative = forfeited stake.
    """
    winning_side = outcome
    losing_side = "no" if outcome == "yes" else "yes"
    winner_pool = 0.0
    loser_pool = 0.0
    for pred in predictions:
        amt = pred.get("stake_amount")
        if amt is None:
            continue
        try:
            a = float(amt)
        except (TypeError, ValueError):
            continue
        if a <= 0:
            continue
        if pred.get("side") == winning_side:
            winner_pool += a
        elif pred.get("side") == losing_side:
            loser_pool += a

    if side == winning_side:
        if winner_pool == 0.0:
            return float(stake_amount)  # degenerate — return stake
        if loser_pool == 0.0:
            return float(stake_amount)  # everyone won — no profit
        share = float(stake_amount) / winner_pool
        winnings = share * loser_pool
        return float(stake_amount) + winnings
    elif side == losing_side:
        return -float(stake_amount)
    return 0.0


@dataclass(frozen=True)
class OracleRepBreakdown:
    """Auditable breakdown of how a node arrived at its oracle_rep balance.

    Useful for the UI's reputation-history view and for invariant tests.
    Sprint 4+ extensions will add resolution-stake redistribution and
    dispute-reversal adjustments to this struct.
    """
    free_prediction_mints: float
    staked_prediction_returns: float
    staked_prediction_losses: float
    total: float


def compute_oracle_rep_breakdown(
    node_id: str,
    chain: Iterable[dict[str, Any]],
) -> OracleRepBreakdown:
    """Per-component breakdown — exposed for tests and audit trails.

    Sprint 3 wiring: applies the farming multiplier (RULES §3.1) to
    free-pick mints. Staked predictions are NOT farming-penalized — the
    farmer is risking actual rep, which is the protocol's deterrent for
    that case. Per-spec semantics.
    """
    events = _as_event_list(chain)
    markets = _index_markets(events)

    farming_pct = compute_farming_pct(node_id, events)
    farming_mult = farming_multiplier(farming_pct)

    free_mint = 0.0
    staked_return = 0.0
    staked_loss = 0.0

    for market in markets.values():
        if not _market_is_mintable(market):
            continue
        original = market.finalize["outcome"]  # type: ignore[index]
        # Sprint 5 bounded reversal: a resolved dispute can flip the
        # effective outcome of THIS market only — no cascade.
        outcome = _effective_outcome(original, market.market_id, events)
        for pred in market.predictions:
            if pred.get("node_id") != node_id:
                continue
            stake = pred.get("stake_amount")
            if stake is None:
                if pred.get("side") == outcome:
                    free_mint += _free_pred_mint(pred.get("probability_at_bet")) * farming_mult
                # Wrong free pick: oracle_rep_earned = 0 (RULES §3.1)
            else:
                delta = _staked_pred_settlement(
                    stake_amount=stake,
                    side=pred.get("side", ""),
                    outcome=outcome,
                    predictions=market.predictions,
                )
                if delta >= 0:
                    staked_return += delta
                else:
                    staked_loss += -delta

    total = free_mint + staked_return - staked_loss
    if total < 0:
        # Oracle rep is non-negative by spec (lost-stake forfeits transfer to
        # winners; they never push a balance below zero in isolation, but a
        # naive node-only view can underflow if the node never won
        # anything). Clamp to zero — the chain analysis on the full network
        # always sums to a non-negative total.
        total = 0.0
    return OracleRepBreakdown(
        free_prediction_mints=free_mint,
        staked_prediction_returns=staked_return,
        staked_prediction_losses=staked_loss,
        total=total,
    )


def compute_oracle_rep(node_id: str, chain: Iterable[dict[str, Any]]) -> float:
    """Current oracle rep balance for ``node_id``.

    Wins (free mint + staked winnings) minus losses (staked forfeits).
    Clamped at zero. See ``compute_oracle_rep_breakdown`` for the full
    component view.
    """
    return compute_oracle_rep_breakdown(node_id, chain).total


def compute_oracle_rep_lifetime(node_id: str, chain: Iterable[dict[str, Any]]) -> float:
    """Cumulative oracle rep ever earned by ``node_id``.

    Monotonically increasing (analytics / profiles only — never drives
    protocol logic per RULES §2.1). Counts wins; ignores losses.
    """
    bd = compute_oracle_rep_breakdown(node_id, chain)
    return bd.free_prediction_mints + bd.staked_prediction_returns


def last_successful_prediction_ts(
    node_id: str,
    chain: Iterable[dict[str, Any]],
) -> float | None:
    """Timestamp of the node's most recent correct prediction in a
    market that:

    1. Reached FINAL (non-INVALID) status.
    2. Was not provisional at finalize time.
    3. Passed the frozen liquidity thresholds.
    4. Was not later reversed by dispute (Sprint 5 — until then, no
       reversal logic; this function only sees the raw outcome).

    Returns ``None`` if the node has no qualifying prediction.

    Used by ``governance_decay.compute_oracle_rep_active`` to determine
    decay age. Per RULES §3.11 INVALID markets do NOT reset the clock —
    enforced here by the ``_market_is_mintable`` filter.
    """
    events = _as_event_list(chain)
    markets = _index_markets(events)

    best_ts: float | None = None
    for market in markets.values():
        if not _market_is_mintable(market):
            continue
        original = market.finalize["outcome"]  # type: ignore[index]
        # Sprint 5 bounded reversal: dispute reversal flips the
        # effective outcome — predictors who picked the new winning
        # side are the ones whose timestamps qualify.
        outcome = _effective_outcome(original, market.market_id, events)
        finalize_ts = market.finalize_ts
        for pred in market.predictions:
            if pred.get("node_id") != node_id:
                continue
            if pred.get("side") != outcome:
                continue
            ts = float(pred.get("timestamp") or 0.0)
            # Use the LATER of prediction timestamp and finalize timestamp —
            # the "successful prediction" only crystallizes when finalize lands.
            ts = max(ts, finalize_ts)
            if best_ts is None or ts > best_ts:
                best_ts = ts
    return best_ts


__all__ = [
    "OracleRepBreakdown",
    "compute_oracle_rep",
    "compute_oracle_rep_breakdown",
    "compute_oracle_rep_lifetime",
    "last_successful_prediction_ts",
]
