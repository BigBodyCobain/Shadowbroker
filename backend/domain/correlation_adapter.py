"""Bridge the existing correlation engine into first-class domain Events.

The correlation engine already produces empirically-tuned, *explained* alerts:
each carries a ``drivers`` list stating why observations were grouped. This
adapter maps those dicts into :class:`~domain.models.Event` objects classified
as :attr:`Classification.ANALYSIS` (a correlation is interpretation, not raw
fact), with an explainable, evidence-derived confidence — so nothing arrives as
a black-box conclusion and the fact/inference line is preserved.
"""

from __future__ import annotations

from typing import Any

from domain._util import now_iso, valid_coord
from domain.classification import Classification, Severity
from domain.confidence import Factor, score_confidence, unknown
from domain.models import Event

_TYPE_TITLES = {
    "rf_anomaly": "RF anomaly (GPS jamming + outage)",
    "military_buildup": "Possible military buildup",
    "infra_cascade": "Infrastructure disruption cascade",
    "contradiction": "Reporting contradiction",
    "analysis_zone": "Analyst / agent assessment",
}


def _confidence_from_drivers(drivers: list[str], severity: str):
    """Explainable confidence: each independent driver is a supporting factor.

    Weight rises slightly with severity but the scorer stays bounded, so a
    correlation never claims certainty.
    """
    if not drivers:
        return unknown("correlation has no stated drivers")
    base = {"critical": 0.7, "high": 0.65, "medium": 0.55, "low": 0.45}.get(str(severity).lower(), 0.5)
    factors = [Factor(d, weight=base) for d in drivers]
    return score_confidence(factors, [])


def correlation_to_event(corr: dict) -> Event:
    ctype = str(corr.get("type", "correlation"))
    drivers = [str(d) for d in (corr.get("drivers") or [])]
    severity = str(corr.get("severity", "info"))
    coord = valid_coord(corr.get("lat"), corr.get("lng"))
    title = _TYPE_TITLES.get(ctype, ctype.replace("_", " ").title())
    explanation = (
        "Correlated because: " + "; ".join(drivers) if drivers
        else "Correlation produced by the ShadowBroker correlation engine."
    )
    return Event(
        type=ctype,
        title=title,
        summary=corr.get("summary") or corr.get("title") or title,
        classification=Classification.ANALYSIS,
        occurred_at=corr.get("occurred_at") or now_iso(),
        lat=coord[0] if coord else None,
        lng=coord[1] if coord else None,
        severity=Severity.coerce(severity),
        explanation=explanation,
        confidence=_confidence_from_drivers(drivers, severity),
        attributes={
            "correlation_score": corr.get("score"),
            "indicator_count": corr.get("indicator_count") or len(drivers),
            "cell_size": corr.get("cell_size"),
            "source": "correlation_engine",
        },
    )


def correlations_to_events(correlations: list[dict[str, Any]]) -> list[Event]:
    out: list[Event] = []
    for corr in correlations or []:
        if not isinstance(corr, dict):
            continue
        try:
            out.append(correlation_to_event(corr))
        except Exception:
            # A single malformed correlation must never break the batch.
            continue
    return out
