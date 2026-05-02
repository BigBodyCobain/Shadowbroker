"""Sprint 6 — shutdown lifecycle.

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 6 row:
"Shutdown requires active suspension. Appeal pauses execution timer.
Anti-stall: one appeal per shutdown, 48h window."
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.gates import (
    compute_shutdown_state,
    compute_suspension_state,
    paused_execution_remaining_sec,
    validate_appeal_filing,
    validate_shutdown_filing,
    validate_suspend_filing,
)
from services.infonet.tests._gate_factory import (
    make_appeal_file,
    make_appeal_resolve,
    make_gate_create,
    make_gate_enter,
    make_shutdown_execute,
    make_shutdown_file,
    make_shutdown_vote,
    make_suspend_execute,
    make_suspend_file,
    make_unsuspend,
)


_SECOND = 1.0
_HOUR = 3600.0
_DAY = 86400.0


def _build(base_ts: float, gate_id: str = "g1") -> list:
    return [
        make_gate_create(gate_id, "creator", ts=base_ts, seq=1),
        make_gate_enter(gate_id, "alice", ts=base_ts + 100, seq=2),
        make_gate_enter(gate_id, "bob", ts=base_ts + 200, seq=3),
    ]


# ── Suspension lifecycle ────────────────────────────────────────────────

def test_unsuspended_gate_status_active():
    base = 1_000_000.0
    chain = _build(base)
    state = compute_suspension_state("g1", chain, now=base + 1000)
    assert state.status == "active"


def test_suspended_gate_status_suspended_until_window_elapses():
    base = 1_000_000.0
    chain = _build(base) + [
        make_suspend_file("g1", "filer", "p1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "p1", ts=base + 2000, seq=11),
    ]
    duration_s = float(CONFIG["gate_suspend_duration_days"]) * _DAY

    # Inside window.
    state = compute_suspension_state("g1", chain, now=base + 2000 + 1000)
    assert state.status == "suspended"
    assert state.suspended_until == base + 2000 + duration_s

    # After window elapses (auto-unsuspend even without explicit event).
    state = compute_suspension_state("g1", chain, now=base + 2000 + duration_s + 1)
    assert state.status == "active"


def test_explicit_unsuspend_returns_to_active():
    base = 1_000_000.0
    chain = _build(base) + [
        make_suspend_file("g1", "filer", "p1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "p1", ts=base + 2000, seq=11),
        make_unsuspend("g1", ts=base + 3000, seq=12),
    ]
    state = compute_suspension_state("g1", chain, now=base + 4000)
    assert state.status == "active"


def test_validate_suspend_rejects_empty_reason():
    base = 1_000_000.0
    chain = _build(base)
    decision = validate_suspend_filing(
        "g1", "filer", reason="", evidence_hashes=["e1"],
        chain=chain, now=base + 1000,
    )
    assert not decision.accepted
    assert decision.reason == "reason_empty"


def test_validate_suspend_rejects_no_evidence():
    base = 1_000_000.0
    chain = _build(base)
    decision = validate_suspend_filing(
        "g1", "filer", reason="abuse", evidence_hashes=[],
        chain=chain, now=base + 1000,
    )
    assert not decision.accepted
    assert decision.reason == "evidence_required"


def test_validate_suspend_rejects_already_suspended():
    base = 1_000_000.0
    chain = _build(base) + [
        make_suspend_file("g1", "f1", "p1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "p1", ts=base + 2000, seq=11),
    ]
    decision = validate_suspend_filing(
        "g1", "f2", reason="abuse", evidence_hashes=["e1"],
        chain=chain, now=base + 3000,
    )
    assert not decision.accepted
    assert decision.reason == "already_suspended"


def test_validate_suspend_rejects_filer_cooldown():
    base = 1_000_000.0
    chain = _build(base)
    decision = validate_suspend_filing(
        "g1", "filer", reason="abuse", evidence_hashes=["e1"],
        chain=chain, now=base + 1000,
        filer_cooldown_until=base + 5000,
    )
    assert not decision.accepted
    assert decision.reason == "filer_cooldown_active"


# ── Shutdown requires active suspension ─────────────────────────────────

def test_shutdown_filing_rejected_when_gate_not_suspended():
    base = 1_000_000.0
    chain = _build(base)
    decision = validate_shutdown_filing(
        "g1", "filer", reason="bad", evidence_hashes=["e1"],
        chain=chain, now=base + 1000,
    )
    assert not decision.accepted
    assert decision.reason == "gate_not_suspended"


def test_shutdown_filing_accepted_when_suspended():
    base = 1_000_000.0
    chain = _build(base) + [
        make_suspend_file("g1", "f1", "sp1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "sp1", ts=base + 2000, seq=11),
    ]
    decision = validate_shutdown_filing(
        "g1", "filer", reason="still bad", evidence_hashes=["e1"],
        chain=chain, now=base + 3000,
    )
    assert decision.accepted


def test_shutdown_filing_rejected_when_already_shutdown():
    base = 1_000_000.0
    chain = _build(base) + [
        make_suspend_file("g1", "f1", "sp1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "sp1", ts=base + 2000, seq=11),
        make_shutdown_file("g1", "f2", "shp1", ts=base + 3000, seq=20),
        make_shutdown_vote("g1", "shp1", "passed", ts=base + 4000, seq=21),
        make_shutdown_execute("g1", "shp1", ts=base + 5000, seq=22),
    ]
    decision = validate_shutdown_filing(
        "g1", "filer", reason="too late", evidence_hashes=["e1"],
        chain=chain, now=base + 6000,
    )
    assert not decision.accepted
    assert decision.reason == "gate_already_shutdown"


def test_shutdown_state_executing_after_vote_passes():
    base = 1_000_000.0
    chain = _build(base) + [
        make_suspend_file("g1", "f1", "sp1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "sp1", ts=base + 2000, seq=11),
        make_shutdown_file("g1", "f2", "shp1", ts=base + 3000, seq=20),
        make_shutdown_vote("g1", "shp1", "passed", ts=base + 4000, seq=21),
    ]
    state = compute_shutdown_state("g1", chain, now=base + 4500)
    assert state.has_pending
    assert state.pending_status == "executing"
    delay_s = float(CONFIG["gate_shutdown_execution_delay_days"]) * _DAY
    assert state.execution_at == base + 4000 + delay_s


# ── Appeal pauses timer + anti-stall ────────────────────────────────────

def test_appeal_filing_pauses_execution_timer():
    base = 1_000_000.0
    chain = _build(base) + [
        make_suspend_file("g1", "f1", "sp1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "sp1", ts=base + 2000, seq=11),
        make_shutdown_file("g1", "f2", "shp1", ts=base + 3000, seq=20),
        make_shutdown_vote("g1", "shp1", "passed", ts=base + 4000, seq=21),
        make_appeal_file("g1", "shp1", "filer", "ap1",
                         ts=base + 4000 + _HOUR, seq=22),
    ]
    state = compute_shutdown_state("g1", chain, now=base + 4000 + 2 * _HOUR)
    assert state.pending_status == "appealed"
    assert state.execution_at is None  # paused


def test_appeal_outside_48h_window_rejected():
    base = 1_000_000.0
    chain = _build(base) + [
        make_suspend_file("g1", "f1", "sp1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "sp1", ts=base + 2000, seq=11),
        make_shutdown_file("g1", "f2", "shp1", ts=base + 3000, seq=20),
        make_shutdown_vote("g1", "shp1", "passed", ts=base + 4000, seq=21),
    ]
    window_s = float(CONFIG["gate_shutdown_appeal_window_hours"]) * _HOUR
    too_late = base + 4000 + window_s + 1
    decision = validate_appeal_filing(
        "g1", "shp1", "filer",
        reason="appeal", evidence_hashes=["e1"],
        chain=chain, now=too_late,
    )
    assert not decision.accepted
    assert decision.reason == "appeal_window_expired"


def test_one_appeal_per_shutdown_anti_stall():
    base = 1_000_000.0
    chain = _build(base) + [
        make_suspend_file("g1", "f1", "sp1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "sp1", ts=base + 2000, seq=11),
        make_shutdown_file("g1", "f2", "shp1", ts=base + 3000, seq=20),
        make_shutdown_vote("g1", "shp1", "passed", ts=base + 4000, seq=21),
        make_appeal_file("g1", "shp1", "filer", "ap1",
                         ts=base + 4000 + _HOUR, seq=22),
    ]
    decision = validate_appeal_filing(
        "g1", "shp1", "filer2",
        reason="another appeal", evidence_hashes=["e2"],
        chain=chain, now=base + 4000 + 2 * _HOUR,
    )
    assert not decision.accepted
    assert decision.reason == "appeal_already_filed"


def test_paused_execution_remaining_sec_correct():
    base = 1_000_000.0
    chain = _build(base) + [
        make_suspend_file("g1", "f1", "sp1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "sp1", ts=base + 2000, seq=11),
        make_shutdown_file("g1", "f2", "shp1", ts=base + 3000, seq=20),
        make_shutdown_vote("g1", "shp1", "passed", ts=base + 4000, seq=21),
    ]
    delay_s = float(CONFIG["gate_shutdown_execution_delay_days"]) * _DAY
    appeal_at = base + 4000 + 24 * _HOUR  # 1 day into the 7-day execution window
    remaining = paused_execution_remaining_sec("shp1", chain, appeal_filed_at=appeal_at)
    expected = (base + 4000 + delay_s) - appeal_at
    assert abs(remaining - expected) < 1e-6


def test_appeal_resolve_voided_status_terminal():
    base = 1_000_000.0
    chain = _build(base) + [
        make_suspend_file("g1", "f1", "sp1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "sp1", ts=base + 2000, seq=11),
        make_shutdown_file("g1", "f2", "shp1", ts=base + 3000, seq=20),
        make_shutdown_vote("g1", "shp1", "passed", ts=base + 4000, seq=21),
        make_appeal_file("g1", "shp1", "filer", "ap1",
                         ts=base + 4000 + _HOUR, seq=22),
        make_appeal_resolve("g1", "ap1", "shp1", "voided_shutdown",
                            ts=base + 4000 + 7 * _DAY, seq=23),
    ]
    state = compute_shutdown_state("g1", chain, now=base + 5_000_000.0)
    # Petition is no longer pending (voided_appeal is terminal).
    assert not state.has_pending


def test_appeal_resolve_resumed_uses_new_execution_at():
    base = 1_000_000.0
    appeal_at = base + 4000 + _HOUR
    resume_at = base + 4000 + 8 * _DAY  # arbitrary later moment
    new_execution_at = resume_at + 6 * _DAY
    chain = _build(base) + [
        make_suspend_file("g1", "f1", "sp1", ts=base + 1000, seq=10),
        make_suspend_execute("g1", "sp1", ts=base + 2000, seq=11),
        make_shutdown_file("g1", "f2", "shp1", ts=base + 3000, seq=20),
        make_shutdown_vote("g1", "shp1", "passed", ts=base + 4000, seq=21),
        make_appeal_file("g1", "shp1", "filer", "ap1",
                         ts=appeal_at, seq=22),
        make_appeal_resolve("g1", "ap1", "shp1", "resumed",
                            ts=resume_at, seq=23,
                            resumed_execution_at=new_execution_at),
    ]
    state = compute_shutdown_state("g1", chain, now=resume_at + 1)
    assert state.pending_status == "executing"
    assert state.execution_at == new_execution_at
