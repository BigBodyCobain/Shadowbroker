"""ShadowBroker intelligence-investigation domain layer.

This package introduces the first-class analytical primitives that the
real-time OSINT aggregator historically lacked: Source, Entity, Observation,
Event, Relationship, Investigation, Evidence, Hypothesis, Note and Alert.

Design goals
------------
* **Fact / inference separation is structural, not cosmetic.** Every analytic
  product carries a :class:`~domain.classification.Classification` that states
  whether it is a raw observation, a derived event, an analysis or a
  hypothesis. Nothing lets a hypothesis masquerade as a fact.
* **Provenance travels with the data.** Observations and evidence carry a
  :class:`~domain.models.Provenance` record (source, url, observed-at,
  ingested-at) so a reader can always answer "where did this come from?".
* **Confidence is explainable and honest.** See :mod:`domain.confidence` — no
  fabricated precision; thin evidence degrades to a qualitative label.

The layer is intentionally storage-light (stdlib ``sqlite3`` via
:mod:`storage`) and additive — it does not modify the existing aggregator.
"""

from domain.classification import Classification, EvidenceKind, EntityType
from domain.confidence import Confidence, Factor, score_confidence
from domain import models

__all__ = [
    "Classification",
    "EvidenceKind",
    "EntityType",
    "Confidence",
    "Factor",
    "score_confidence",
    "models",
]
