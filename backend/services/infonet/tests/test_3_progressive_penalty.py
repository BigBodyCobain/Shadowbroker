"""Sprint 3 — progressive penalty (whale deterrence).

Maps to IMPLEMENTATION_PLAN.md §7.1 Sprint 3 row:
"Progressive penalty scales with rep."
"""

from __future__ import annotations

import math

from services.infonet.reputation.anti_gaming import (
    apply_progressive_penalty,
    compute_rep_multiplier,
)


def test_multiplier_floor_below_one_rep():
    assert compute_rep_multiplier(0.0) == 1.0
    assert compute_rep_multiplier(1.0) == 1.0
    # Negative inputs clamp to floor as well.
    assert compute_rep_multiplier(-5.0) == 1.0


def test_multiplier_at_two_is_two():
    """1 + log2(2) == 2.0."""
    assert compute_rep_multiplier(2.0) == 2.0


def test_multiplier_at_1024_is_eleven():
    """1 + log2(1024) == 11.0 — the canonical whale check."""
    assert compute_rep_multiplier(1024.0) == 11.0


def test_multiplier_strictly_increasing_with_rep():
    seq = [compute_rep_multiplier(r) for r in [1, 2, 4, 8, 16, 32, 64, 128, 1024]]
    for prev, cur in zip(seq, seq[1:]):
        assert cur > prev


def test_apply_progressive_penalty_scales_with_rep():
    """Same correlation_score, different oracle_rep → larger penalty
    for the higher-rep node."""
    score = 0.5
    small = apply_progressive_penalty(score, 4.0)
    big = apply_progressive_penalty(score, 1024.0)
    assert big > small
    # Concrete values: small = 0.5 * (1+log2(4)) = 0.5 * 3 = 1.5
    #                  big   = 0.5 * 11 = 5.5
    assert abs(small - 1.5) < 1e-9
    assert abs(big - 5.5) < 1e-9


def test_apply_progressive_penalty_zero_score_zero_dock():
    """No correlation → no penalty regardless of rep."""
    assert apply_progressive_penalty(0.0, 1024.0) == 0.0
    assert apply_progressive_penalty(0.0, 1.0) == 0.0


def test_apply_progressive_penalty_handles_log_floor():
    """At rep <= 1, multiplier is 1.0 → penalty == base_penalty."""
    assert apply_progressive_penalty(0.5, 0.5) == 0.5
    assert apply_progressive_penalty(0.5, 1.0) == 0.5


def test_progressive_penalty_canonical_doubling_property():
    """Doubling rep adds exactly 1.0 to the multiplier (log2 derivative).
    Sanity check the math holds across the meaningful range."""
    for r in [2, 4, 8, 16, 32, 128, 1024, 65536]:
        m = compute_rep_multiplier(r)
        expected = 1 + math.log2(r)
        assert abs(m - expected) < 1e-9
