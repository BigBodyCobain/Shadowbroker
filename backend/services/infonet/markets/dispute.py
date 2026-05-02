"""Bounded-reversal disputes — RULES §3.12.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.12 + §5.2
step 6.

A dispute is a post-finality challenge. Any node can stake oracle rep
to open one, and other nodes can stake oracle OR common rep on
``confirm`` (uphold the original outcome) or ``reverse`` (flip it).
Oracle-rep simple majority decides — resolution already established
the supermajority, so a simple majority is enough to overturn.

If the dispute reverses, **only this market's oracle rep is
recalculated**. Downstream rep earned in OTHER markets from rep
originally minted here is NOT clawed back. No cascading rewrites.
That's the "bounded" in bounded reversal.

Two effects:

1. ``effective_outcome(market_id, chain)`` returns the flipped
   outcome if a reversed dispute exists; the unmodified outcome
   otherwise. Used by ``oracle_rep._market_is_mintable`` so
   reputation views automatically reflect the reversal.
2. ``compute_dispute_outcome`` returns ``"upheld" | "reversed" |
   "tie"`` from accumulated stakes — used when an authoritative
   ``dispute_resolve`` event has not yet landed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from services.infonet.config import CONFIG


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


@dataclass
class DisputeView:
    """Chain-derived view of a single dispute."""
    dispute_id: str
    market_id: str
    challenger_id: str
    challenger_stake: float
    opened_at: float
    confirm_stakes: list[dict] = field(default_factory=list)
    reverse_stakes: list[dict] = field(default_factory=list)
    resolved_outcome: str | None = None  # "upheld" | "reversed" | "tie"
    resolved_at: float | None = None

    @property
    def is_resolved(self) -> bool:
        return self.resolved_outcome is not None


def _dispute_id(event: dict[str, Any]) -> str:
    """Pick the dispute_id from a dispute event payload, falling back
    to the event_id for ``dispute_open`` (which is the canonical
    identifier the rest of the chain references)."""
    p = _payload(event)
    did = p.get("dispute_id")
    if isinstance(did, str) and did:
        return did
    # dispute_open events: synthesize from event_id if present, else
    # market_id + opener + timestamp. Producers SHOULD attach a
    # dispute_id explicitly — Sprint 7+ enforces this in the schema.
    eid = event.get("event_id")
    if isinstance(eid, str) and eid:
        return eid
    market_id = p.get("market_id") or ""
    return f"dispute:{market_id}:{event.get('node_id','')}:{event.get('timestamp','')}"


def collect_disputes(
    market_id: str,
    chain: Iterable[dict[str, Any]],
) -> list[DisputeView]:
    """All disputes filed against ``market_id``, sorted by open time."""
    chain_list = [e for e in chain if isinstance(e, dict)]

    open_events = [e for e in chain_list
                   if e.get("event_type") == "dispute_open"
                   and _payload(e).get("market_id") == market_id]
    if not open_events:
        return []

    # Build by dispute_id keyed off the open event.
    disputes: dict[str, DisputeView] = {}
    open_id_by_market_event: dict[str, str] = {}
    for ev in open_events:
        p = _payload(ev)
        did = _dispute_id(ev)
        challenger = ev.get("node_id") or ""
        try:
            cstake = float(p.get("challenger_stake") or 0.0)
        except (TypeError, ValueError):
            cstake = 0.0
        opened_at = float(ev.get("timestamp") or 0.0)
        disputes[did] = DisputeView(
            dispute_id=did, market_id=str(market_id),
            challenger_id=str(challenger), challenger_stake=cstake,
            opened_at=opened_at,
        )
        open_id_by_market_event[ev.get("event_id") or ""] = did

    # Stakes reference dispute_id explicitly (Sprint 1 schema).
    for ev in chain_list:
        if ev.get("event_type") != "dispute_stake":
            continue
        p = _payload(ev)
        did = p.get("dispute_id")
        if not isinstance(did, str) or did not in disputes:
            continue
        side = p.get("side")
        if side not in ("confirm", "reverse"):
            continue
        rep_type = p.get("rep_type")
        if rep_type not in ("oracle", "common"):
            continue
        try:
            amount = float(p.get("amount") or 0.0)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        record = {
            "node_id": ev.get("node_id") or "",
            "amount": amount,
            "rep_type": rep_type,
        }
        target = disputes[did].confirm_stakes if side == "confirm" else disputes[did].reverse_stakes
        target.append(record)

    # Resolution events.
    for ev in chain_list:
        if ev.get("event_type") != "dispute_resolve":
            continue
        p = _payload(ev)
        did = p.get("dispute_id")
        if not isinstance(did, str) or did not in disputes:
            continue
        outcome = p.get("outcome")
        if outcome not in ("upheld", "reversed", "tie"):
            continue
        disputes[did].resolved_outcome = outcome
        disputes[did].resolved_at = float(ev.get("timestamp") or 0.0)

    return sorted(disputes.values(), key=lambda d: (d.opened_at, d.dispute_id))


def compute_dispute_outcome(dispute: DisputeView) -> str:
    """Apply RULES §3.12 to compute the dispute outcome from its
    accumulated stakes (oracle-rep majority).

    Returns ``"upheld"`` (default — original outcome stands),
    ``"reversed"``, or ``"tie"``. ``"tie"`` is treated as upheld for
    bookkeeping but is reported separately so callers can log it.
    """
    confirm_oracle = sum(
        s.get("amount", 0.0) for s in dispute.confirm_stakes
        if s.get("rep_type") == "oracle"
    )
    reverse_oracle = sum(
        s.get("amount", 0.0) for s in dispute.reverse_stakes
        if s.get("rep_type") == "oracle"
    )
    if confirm_oracle > reverse_oracle:
        return "upheld"
    if reverse_oracle > confirm_oracle:
        return "reversed"
    return "tie"


def market_was_reversed(market_id: str, chain: Iterable[dict[str, Any]]) -> bool:
    """``True`` if any dispute on ``market_id`` resolved as reversed.

    Multiple disputes on the same market are unusual but possible —
    if any one reverses, the market's effective outcome flips. A
    subsequent dispute that re-reverses would flip it back, but
    Sprint 5 leaves multi-dispute behavior intentionally simple
    (last reversed wins — see ``effective_outcome``).
    """
    for d in collect_disputes(market_id, chain):
        if d.resolved_outcome == "reversed":
            return True
    return False


def _flip(outcome: str) -> str:
    if outcome == "yes":
        return "no"
    if outcome == "no":
        return "yes"
    return outcome


def effective_outcome(
    original_outcome: str,
    market_id: str,
    chain: Iterable[dict[str, Any]],
) -> str:
    """Apply bounded reversal to a market's outcome.

    Walks resolved disputes in chain order. Each ``reversed`` outcome
    flips the running outcome; ``upheld`` and ``tie`` leave it. The
    final value is the **effective** outcome that ``oracle_rep`` and
    ``last_successful_prediction_ts`` should use.

    BOUNDED: this function operates on a single market_id only. It does
    NOT cascade into other markets even if oracle rep used to stake in
    those other markets came from this one.
    """
    if original_outcome not in ("yes", "no"):
        return original_outcome
    current = original_outcome
    for d in collect_disputes(market_id, chain):
        if d.resolved_outcome == "reversed":
            current = _flip(current)
    return current


def dispute_settlement_effects(dispute: DisputeView) -> dict[str, Any]:
    """Compute rep transfers from a *resolved* dispute.

    Per RULES §3.12: winning side splits the loser pool, 2% loser tax
    burned, oracle and common pools settle independently.

    Returns the same shape as ``resolve_data_unavailable_effects`` — a
    dict the caller folds into a higher-level result.
    """
    out: dict[str, Any] = {
        "stake_returns": {},
        "stake_winnings": {},
        "burned": 0.0,
    }
    if not dispute.is_resolved:
        return out
    outcome = dispute.resolved_outcome
    if outcome == "tie":
        # Return all stakes intact.
        for s in dispute.confirm_stakes + dispute.reverse_stakes:
            key = (s["node_id"], s["rep_type"])
            out["stake_returns"][key] = out["stake_returns"].get(key, 0.0) + s["amount"]
        return out

    winners = dispute.confirm_stakes if outcome == "upheld" else dispute.reverse_stakes
    losers = dispute.reverse_stakes if outcome == "upheld" else dispute.confirm_stakes
    burn_pct = float(CONFIG["resolution_loser_burn_pct"])

    for rep_type in ("oracle", "common"):
        rep_winners = [s for s in winners if s["rep_type"] == rep_type]
        rep_losers = [s for s in losers if s["rep_type"] == rep_type]
        winner_pool = sum(s["amount"] for s in rep_winners)
        loser_pool = sum(s["amount"] for s in rep_losers)

        for s in rep_winners:
            key = (s["node_id"], rep_type)
            out["stake_returns"][key] = out["stake_returns"].get(key, 0.0) + s["amount"]

        if winner_pool == 0 or loser_pool == 0:
            continue
        burn = loser_pool * burn_pct
        distributable = loser_pool - burn
        out["burned"] += burn
        for s in rep_winners:
            share = s["amount"] / winner_pool
            winnings = share * distributable
            key = (s["node_id"], rep_type)
            out["stake_winnings"][key] = out["stake_winnings"].get(key, 0.0) + winnings

    return out


__all__ = [
    "DisputeView",
    "collect_disputes",
    "compute_dispute_outcome",
    "dispute_settlement_effects",
    "effective_outcome",
    "market_was_reversed",
]
