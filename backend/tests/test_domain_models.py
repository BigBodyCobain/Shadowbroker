"""Tests for domain models: classification rules, provenance, (de)serialisation."""

from domain.classification import Classification, EntityType, Severity
from domain.confidence import Factor, score_confidence
from domain.models import (
    Alert,
    Entity,
    Event,
    Evidence,
    Hypothesis,
    Investigation,
    Observation,
    Provenance,
    Source,
)


def test_classification_ladder_order_and_predicates():
    assert Classification.RAW_OBSERVATION.order < Classification.DERIVED_EVENT.order
    assert Classification.DERIVED_EVENT.order < Classification.ANALYSIS.order
    assert Classification.ANALYSIS.order < Classification.HYPOTHESIS.order
    assert Classification.RAW_OBSERVATION.is_fact
    assert Classification.DERIVED_EVENT.is_fact
    assert Classification.ANALYSIS.is_inference
    assert Classification.HYPOTHESIS.is_inference


def test_entity_type_coerce_falls_back_to_other():
    assert EntityType.coerce("AIRCRAFT") == EntityType.AIRCRAFT
    assert EntityType.coerce("nonsense") == EntityType.OTHER


def test_entity_deterministic_id_dedupes():
    a = Entity(type=EntityType.AIRCRAFT, canonical_key="abc123", label="Jet A")
    b = Entity(type=EntityType.AIRCRAFT, canonical_key="abc123", label="Jet A (later)")
    assert a.id == b.id  # same natural key -> same entity id


def test_entity_rejects_bad_coordinates():
    e = Entity.from_dict({"type": "aircraft", "canonical_key": "k", "lat": 999, "lng": 1})
    assert e.lat is None and e.lng is None


def test_observation_is_always_raw():
    o = Observation.from_dict({"classification": "hypothesis", "layer": "flights"})
    assert o.classification == Classification.RAW_OBSERVATION


def test_hypothesis_cannot_be_reclassified_as_fact():
    h = Hypothesis(statement="maybe", classification=Classification.RAW_OBSERVATION)
    assert h.classification == Classification.HYPOTHESIS


def test_provenance_separates_observed_and_ingested():
    p = Provenance(source_name="OpenSky", observed_at="2026-08-13T14:32:00Z", method="ADS-B")
    d = p.to_dict()
    assert d["observed_at"] == "2026-08-13T14:32:00Z"
    assert d["ingested_at"]  # auto-stamped, distinct field
    assert d["method"] == "ADS-B"


def test_event_roundtrip_preserves_classification_and_confidence():
    conf = score_confidence([Factor("anomaly", 0.9)], [Factor("no confirmation", 0.4)])
    ev = Event(
        type="heading_change",
        title="Aircraft X heading change",
        classification=Classification.DERIVED_EVENT,
        severity=Severity.MEDIUM,
        explanation="Heading delta 32deg exceeds threshold",
        confidence=conf,
        lat=41.9,
        lng=29.1,
    )
    again = Event.from_dict(ev.to_dict())
    assert again.classification == Classification.DERIVED_EVENT
    assert again.severity == Severity.MEDIUM
    assert again.confidence.score == conf.score
    assert again.explanation == ev.explanation


def test_evidence_roundtrip_and_provenance():
    ev = Evidence(
        kind="observation",
        title="ADS-B contact",
        classification=Classification.RAW_OBSERVATION,
        provenance=Provenance(source_name="OpenSky", source_url="https://opensky-network.org"),
    )
    again = Evidence.from_dict(ev.to_dict())
    assert again.provenance.source_name == "OpenSky"
    assert again.classification == Classification.RAW_OBSERVATION


def test_investigation_roundtrip():
    inv = Investigation(title="Black Sea Activity", question="What changed?", tags=["black-sea"])
    again = Investigation.from_dict(inv.to_dict())
    assert again.title == inv.title
    assert again.tags == ["black-sea"]
    assert again.status.value == "open"


def test_alert_requires_what_when_where_why_shape():
    a = Alert(
        type="unusual_aircraft",
        title="Unusual aircraft activity",
        what="3 military aircraft loitering",
        why="Deviation from baseline traffic",
        lat=44.0,
        lng=33.0,
        severity=Severity.HIGH,
    )
    d = a.to_dict()
    for key in ("what", "why", "occurred_at", "lat", "lng", "confidence"):
        assert key in d
    assert d["severity"] == "high"


def test_source_trusted_flag_defaults_untrusted():
    s = Source(kind="channel", name="t.me/example")
    assert s.trusted is False  # external content untrusted by default
