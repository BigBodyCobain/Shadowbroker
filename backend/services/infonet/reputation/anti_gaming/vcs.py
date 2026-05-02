"""Vote Correlation Score — detects coordinated upreping rings.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.4.

For an uprep from A → B:

    A_targets = {all nodes A has uprepped in decay window}
    B_fans    = {all nodes that uprepped B in decay window, excluding A}

    if len(B_fans) == 0:
        overlap = 0.0
    else:
        overlap = |A_targets ∩ B_fans| / |B_fans|

    correlation_penalty = max(vcs_min_weight, 1.0 - overlap)

The intent: if A always upreps the same group of nodes that always uprep
B (a circle-jerk), the overlap approaches 1 and the penalty floors at
``vcs_min_weight`` (default 0.10 — 10% effective weight, regardless of
how many nodes participate).

Pure function over the chain. Does NOT depend on order beyond the decay
window cutoff.
"""

from __future__ import annotations

from typing import Any, Iterable

from services.infonet.config import CONFIG


_SECONDS_PER_DAY = 86400.0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _decay_window_seconds(decay_window_days: float | None) -> float:
    if decay_window_days is not None:
        return float(decay_window_days) * _SECONDS_PER_DAY
    return float(CONFIG["vote_decay_days"]) * _SECONDS_PER_DAY


def _upreps_within_window(
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
    window_s: float,
) -> list[dict[str, Any]]:
    """All ``uprep`` events whose timestamp is in [now - window, now]."""
    cutoff = now - window_s
    out: list[dict[str, Any]] = []
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "uprep":
            continue
        try:
            ts = float(ev.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            continue
        if cutoff <= ts <= now:
            out.append(ev)
    return out


def compute_vcs(
    upreper_id: str,
    target_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float | None = None,
    decay_window_days: float | None = None,
) -> float:
    """Return the VCS multiplier for an uprep from ``upreper_id`` to ``target_id``.

    Range: ``[vcs_min_weight, 1.0]``. A return of 1.0 means no
    correlation detected (full weight). A return of ``vcs_min_weight``
    (default 0.10) means maximum correlation — the upreper's targets
    completely overlap with the target's fan set.

    ``now`` defaults to the latest timestamp on the chain. Pass an
    explicit value when the caller wants a fixed evaluation point (e.g.
    Sprint 4 will pass the market snapshot's ``frozen_at``).
    """
    if not isinstance(upreper_id, str) or not upreper_id:
        return float(CONFIG["vcs_min_weight"])
    if not isinstance(target_id, str) or not target_id:
        return float(CONFIG["vcs_min_weight"])
    if upreper_id == target_id:
        return 1.0  # self-uprep is filtered by common_rep; VCS is a no-op here

    events = [e for e in chain if isinstance(e, dict)]
    if not events:
        return 1.0

    if now is None:
        now = max(float(ev.get("timestamp") or 0.0) for ev in events)
    window_s = _decay_window_seconds(decay_window_days)
    window_upreps = _upreps_within_window(events, now=now, window_s=window_s)

    a_targets: set[str] = set()
    b_fans: set[str] = set()
    for ev in window_upreps:
        author = ev.get("node_id")
        p = _payload(ev)
        target = p.get("target_node_id")
        if not isinstance(author, str) or not isinstance(target, str):
            continue
        if author == target:
            continue
        if author == upreper_id:
            a_targets.add(target)
        if target == target_id and author != upreper_id:
            b_fans.add(author)

    floor = float(CONFIG["vcs_min_weight"])
    if not b_fans:
        return 1.0
    overlap = len(a_targets & b_fans) / len(b_fans)
    return max(floor, 1.0 - overlap)


__all__ = ["compute_vcs"]
