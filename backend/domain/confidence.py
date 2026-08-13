"""Explainable, honest confidence scoring.

The product rule is strict: **no fabricated precision.** A confidence value is
only ever a compact summary of enumerated supporting and contradicting
factors, produced by a deterministic and inspectable function. When the
evidence base is too thin to justify a number, the scorer degrades to a
*qualitative* label instead of inventing one.

Model
-----
Each :class:`Factor` carries a ``weight`` in ``(0, 1]`` expressing how strongly
it should move belief. Factors are combined in log-odds space starting from a
neutral prior (0.5):

    logit = sum(weight_i * K for supporting) - sum(weight_j * K for contradicting)
    p     = sigmoid(logit)

``K`` is a fixed scale so that a single strong (weight 1.0) factor moves belief
from 0.50 to roughly 0.82 — deliberately far from certainty. The result is
clamped to ``[0.05, 0.95]`` so the system never claims a fact is impossible or
certain from correlated OSINT alone.

Invariants (see ``tests/test_confidence.py``):
* adding a supporting factor never lowers the score; adding a contradicting
  factor never raises it (monotonic);
* the function is symmetric — swapping supporting/contradicting maps ``p`` to
  ``1 - p``;
* the score is bounded in ``(0, 1)`` and deterministic;
* below :data:`MIN_EVIDENCE_MASS` total weight the result is qualitative
  (``score is None``), because a number would be false precision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

# Log-odds scale per unit weight. Chosen so one weight=1.0 factor => ~0.82.
_K = 1.5
# Never assert certainty/impossibility from aggregated OSINT.
_FLOOR = 0.05
_CEIL = 0.95
# Minimum summed factor weight before a numeric score is meaningful. Roughly
# "at least one solid factor, or two weak ones."
MIN_EVIDENCE_MASS = 0.5

_QUALITATIVE_BANDS = (
    (0.20, "very low"),
    (0.40, "low"),
    (0.60, "moderate"),
    (0.80, "high"),
    (1.01, "very high"),
)


@dataclass(frozen=True)
class Factor:
    """A single named consideration bearing on a conclusion.

    ``weight`` is clamped into ``(0, 1]`` on construction. ``note`` is optional
    human-readable context. Factors are the *only* thing that moves a score, so
    they are always retained on the result for explainability.
    """

    label: str
    weight: float = 0.6
    note: str = ""

    def __post_init__(self) -> None:
        w = self.weight
        if not isinstance(w, (int, float)) or math.isnan(w):
            w = 0.6
        w = max(0.01, min(1.0, float(w)))
        object.__setattr__(self, "weight", w)
        object.__setattr__(self, "label", str(self.label))

    def to_dict(self) -> dict:
        return {"label": self.label, "weight": round(self.weight, 3), "note": self.note}

    @classmethod
    def from_dict(cls, d: object) -> "Factor":
        if isinstance(d, Factor):
            return d
        if isinstance(d, str):
            return cls(label=d)
        if isinstance(d, dict):
            return cls(
                label=str(d.get("label", "")),
                weight=float(d.get("weight", 0.6) or 0.6),
                note=str(d.get("note", "") or ""),
            )
        return cls(label=str(d))


def _coerce_factors(items: Optional[Iterable[object]]) -> list[Factor]:
    if not items:
        return []
    return [Factor.from_dict(it) for it in items if it is not None]


def _band(score: float) -> str:
    for threshold, name in _QUALITATIVE_BANDS:
        if score < threshold:
            return name
    return "very high"


@dataclass
class Confidence:
    """The result of a confidence assessment.

    Attributes
    ----------
    score:
        Numeric probability in ``(0, 1)``, or ``None`` when the evidence base
        is too thin to justify a number (in which case ``qualitative`` is True).
    label:
        Human band ("very low".."very high", or "insufficient").
    qualitative:
        True when no defensible numeric score could be produced.
    method:
        Identifier of the scoring method, for auditability.
    supporting / contradicting:
        The factors that produced this assessment (retained for explanation).
    rationale:
        A one-line plain-language explanation of the math.
    """

    score: Optional[float]
    label: str
    qualitative: bool
    method: str = "log_odds_v1"
    supporting: list[Factor] = field(default_factory=list)
    contradicting: list[Factor] = field(default_factory=list)
    rationale: str = ""

    @property
    def percent(self) -> Optional[int]:
        return None if self.score is None else int(round(self.score * 100))

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "percent": self.percent,
            "label": self.label,
            "qualitative": self.qualitative,
            "method": self.method,
            "supporting": [f.to_dict() for f in self.supporting],
            "contradicting": [f.to_dict() for f in self.contradicting],
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, d: object) -> "Confidence":
        if isinstance(d, Confidence):
            return d
        if not isinstance(d, dict):
            return unknown()
        return cls(
            score=(None if d.get("score") is None else float(d["score"])),
            label=str(d.get("label", "insufficient")),
            qualitative=bool(d.get("qualitative", True)),
            method=str(d.get("method", "log_odds_v1")),
            supporting=_coerce_factors(d.get("supporting")),
            contradicting=_coerce_factors(d.get("contradicting")),
            rationale=str(d.get("rationale", "")),
        )


def unknown(reason: str = "no evidence supplied") -> Confidence:
    """A confidence with no basis — explicitly qualitative, never a fake number."""
    return Confidence(
        score=None,
        label="insufficient",
        qualitative=True,
        supporting=[],
        contradicting=[],
        rationale=f"Confidence not calculated: {reason}.",
    )


def qualitative(label: str, rationale: str = "") -> Confidence:
    """Construct an intentionally qualitative confidence (analyst judgement)."""
    lbl = str(label).strip().lower() or "moderate"
    return Confidence(
        score=None,
        label=lbl,
        qualitative=True,
        method="qualitative",
        rationale=rationale or "Qualitative assessment (no numeric model applied).",
    )


def score_confidence(
    supporting: Optional[Sequence[object]] = None,
    contradicting: Optional[Sequence[object]] = None,
    *,
    method: str = "log_odds_v1",
) -> Confidence:
    """Combine supporting and contradicting factors into an honest confidence.

    ``supporting``/``contradicting`` may be :class:`Factor` objects, plain
    strings (default weight applied), or dicts. Returns a :class:`Confidence`;
    when the total factor weight is below :data:`MIN_EVIDENCE_MASS` the result
    is qualitative with ``score is None``.
    """

    sup = _coerce_factors(supporting)
    con = _coerce_factors(contradicting)

    mass = sum(f.weight for f in sup) + sum(f.weight for f in con)
    if mass < MIN_EVIDENCE_MASS:
        result = unknown("insufficient evidence mass to justify a numeric score")
        result.method = method
        result.supporting = sup
        result.contradicting = con
        return result

    logit = _K * (sum(f.weight for f in sup) - sum(f.weight for f in con))
    p = 1.0 / (1.0 + math.exp(-logit))
    p = max(_FLOOR, min(_CEIL, p))
    p = round(p, 2)

    n_sup, n_con = len(sup), len(con)
    rationale = (
        f"{n_sup} supporting factor(s) vs {n_con} contradicting; "
        f"combined in log-odds (K={_K}) from a neutral prior to {int(round(p * 100))}%. "
        f"Bounded to [{int(_FLOOR * 100)}%, {int(_CEIL * 100)}%] — never certainty."
    )

    return Confidence(
        score=p,
        label=_band(p),
        qualitative=False,
        method=method,
        supporting=sup,
        contradicting=con,
        rationale=rationale,
    )
