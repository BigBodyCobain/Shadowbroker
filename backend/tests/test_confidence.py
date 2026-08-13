"""Tests for the explainable confidence scorer.

These lock in the honesty invariants: monotonicity, symmetry, boundedness,
determinism, and qualitative degradation on thin evidence.
"""

from domain.confidence import (
    MIN_EVIDENCE_MASS,
    Confidence,
    Factor,
    qualitative,
    score_confidence,
    unknown,
)


def test_no_evidence_is_qualitative_not_a_number():
    c = score_confidence([], [])
    assert c.score is None
    assert c.qualitative is True
    assert c.label == "insufficient"


def test_thin_evidence_degrades_to_qualitative():
    # A single very weak factor is below the evidence-mass floor.
    c = score_confidence([Factor("weak hint", weight=0.1)], [])
    assert c.score is None
    assert c.qualitative is True


def test_supporting_factor_raises_above_prior():
    c = score_confidence([Factor("aircraft anomaly", weight=1.0)], [])
    assert c.score is not None
    assert c.score > 0.5
    assert c.qualitative is False
    assert "supporting" in c.rationale


def test_contradicting_factor_lowers_below_prior():
    c = score_confidence([], [Factor("official denial", weight=1.0)])
    assert c.score is not None
    assert c.score < 0.5


def test_monotonic_more_support_never_lowers():
    base = score_confidence([Factor("a", 0.8)], [])
    more = score_confidence([Factor("a", 0.8), Factor("b", 0.8)], [])
    assert more.score >= base.score


def test_monotonic_more_contradiction_never_raises():
    base = score_confidence([Factor("a", 0.8), Factor("b", 0.8)], [Factor("x", 0.5)])
    more = score_confidence([Factor("a", 0.8), Factor("b", 0.8)], [Factor("x", 0.5), Factor("y", 0.5)])
    assert more.score <= base.score


def test_symmetry_swap_maps_p_to_one_minus_p():
    sup = [Factor("a", 0.9), Factor("b", 0.4)]
    con = [Factor("c", 0.6)]
    forward = score_confidence(sup, con)
    swapped = score_confidence(con, sup)
    assert forward.score is not None and swapped.score is not None
    assert abs(forward.score + swapped.score - 1.0) < 1e-9


def test_bounded_never_certain():
    # A pile of strong supporting factors must still not claim certainty.
    strong = [Factor(f"f{i}", 1.0) for i in range(20)]
    c = score_confidence(strong, [])
    assert c.score is not None
    assert c.score <= 0.95
    impossible = score_confidence([], strong)
    assert impossible.score >= 0.05


def test_deterministic():
    a = score_confidence([Factor("a", 0.7)], [Factor("b", 0.3)])
    b = score_confidence([Factor("a", 0.7)], [Factor("b", 0.3)])
    assert a.score == b.score
    assert a.rationale == b.rationale


def test_factor_weight_is_clamped():
    hi = Factor("x", weight=5.0)
    lo = Factor("y", weight=-1.0)
    assert hi.weight == 1.0
    assert 0 < lo.weight <= 1.0


def test_factors_accept_strings_and_dicts():
    c = score_confidence(["plain string factor", {"label": "d", "weight": 0.9}], [])
    assert len(c.supporting) == 2
    assert c.supporting[0].label == "plain string factor"


def test_percent_helper():
    c = score_confidence([Factor("a", 1.0), Factor("b", 1.0)], [])
    assert c.percent == int(round(c.score * 100))


def test_roundtrip_to_from_dict():
    c = score_confidence([Factor("a", 0.8, note="n")], [Factor("b", 0.4)])
    again = Confidence.from_dict(c.to_dict())
    assert again.score == c.score
    assert again.label == c.label
    assert again.supporting[0].note == "n"


def test_qualitative_constructor_has_no_number():
    c = qualitative("high", "analyst judgement")
    assert c.score is None
    assert c.qualitative is True
    assert c.label == "high"


def test_unknown_constructor():
    c = unknown("no sources")
    assert c.score is None and c.qualitative
    assert "no sources" in c.rationale


def test_min_evidence_mass_boundary():
    # Exactly at the threshold produces a number; just below is qualitative.
    at = score_confidence([Factor("a", MIN_EVIDENCE_MASS)], [])
    below = score_confidence([Factor("a", MIN_EVIDENCE_MASS - 0.05)], [])
    assert at.score is not None
    assert below.score is None
