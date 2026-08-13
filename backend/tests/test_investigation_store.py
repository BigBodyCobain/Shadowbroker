"""Tests for the SQLite investigation store."""

import pytest

from domain.classification import Classification, EntityType, Severity
from domain.models import (
    Alert,
    Entity,
    Event,
    Evidence,
    Hypothesis,
    Investigation,
    Note,
    Observation,
    Relationship,
    Source,
)
from storage import Store


@pytest.fixture()
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_investigation_crud(store):
    inv = store.upsert_investigation(Investigation(title="Case 1", question="What happened?"))
    got = store.get_investigation(inv.id)
    assert got is not None and got.title == "Case 1"
    got.title = "Case 1 renamed"
    store.upsert_investigation(got)
    assert store.get_investigation(inv.id).title == "Case 1 renamed"
    listed = store.list_investigations()
    assert any(i.id == inv.id for i in listed)
    assert store.delete_investigation(inv.id) is True
    assert store.get_investigation(inv.id) is None


def test_entity_upsert_and_key_lookup(store):
    e = store.upsert_entity(Entity(type=EntityType.VESSEL, canonical_key="mmsi:123", label="Vessel Y"))
    assert store.get_entity(e.id).label == "Vessel Y"
    found = store.find_entity_by_key("vessel", "mmsi:123")
    assert found is not None and found.id == e.id
    results = store.search_entities(query="Vessel", etype="vessel")
    assert len(results) == 1


def test_observations_attach_to_entity(store):
    e = store.upsert_entity(Entity(type=EntityType.AIRCRAFT, canonical_key="icao:abc", label="X"))
    for i in range(3):
        store.add_observation(Observation(entity_id=e.id, layer="flights", lat=40 + i, lng=30, observed_at=f"2026-08-13T0{i}:00:00Z"))
    obs = store.observations_for_entity(e.id)
    assert len(obs) == 3
    # ordered by observed_at desc
    assert obs[0].observed_at >= obs[-1].observed_at


def test_events_time_and_type_filter(store):
    store.upsert_event(Event(type="heading_change", occurred_at="2026-08-13T01:00:00Z"))
    store.upsert_event(Event(type="route_change", occurred_at="2026-08-13T05:00:00Z"))
    all_events = store.search_events()
    assert len(all_events) == 2
    typed = store.search_events(etype="route_change")
    assert len(typed) == 1 and typed[0].type == "route_change"
    windowed = store.search_events(time_from="2026-08-13T03:00:00Z")
    assert len(windowed) == 1 and windowed[0].type == "route_change"


def test_events_near_spatial(store):
    store.upsert_event(Event(type="a", lat=41.0, lng=29.0, occurred_at="2026-08-13T01:00:00Z"))
    store.upsert_event(Event(type="b", lat=41.05, lng=29.05, occurred_at="2026-08-13T01:00:00Z"))
    store.upsert_event(Event(type="far", lat=10.0, lng=10.0, occurred_at="2026-08-13T01:00:00Z"))
    near = store.events_near(41.0, 29.0, radius_km=50)
    types = {ev.type for ev, _ in near}
    assert "a" in types and "b" in types and "far" not in types
    # nearest first
    assert near[0][1] <= near[-1][1]


def test_evidence_and_hypothesis_lifecycle(store):
    inv = store.upsert_investigation(Investigation(title="C"))
    ev = store.add_evidence(Evidence(investigation_id=inv.id, kind="observation", title="ADS-B", classification=Classification.RAW_OBSERVATION))
    assert len(store.evidence_for_investigation(inv.id)) == 1
    hyp = store.upsert_hypothesis(Hypothesis(investigation_id=inv.id, statement="coordinated activity", supporting_evidence_ids=[ev.id]))
    got = store.get_hypothesis(hyp.id)
    assert got.classification == Classification.HYPOTHESIS
    assert got.supporting_evidence_ids == [ev.id]
    assert store.delete_evidence(ev.id) is True


def test_delete_investigation_cascades(store):
    inv = store.upsert_investigation(Investigation(title="C"))
    store.add_evidence(Evidence(investigation_id=inv.id, title="e"))
    store.upsert_hypothesis(Hypothesis(investigation_id=inv.id, statement="h"))
    store.add_note(Note(investigation_id=inv.id, body="n"))
    store.delete_investigation(inv.id)
    assert store.evidence_for_investigation(inv.id) == []
    assert store.hypotheses_for_investigation(inv.id) == []
    assert store.notes_for_investigation(inv.id) == []


def test_relationships(store):
    a = store.upsert_entity(Entity(type=EntityType.AIRCRAFT, canonical_key="k1"))
    b = store.upsert_entity(Entity(type=EntityType.ORGANIZATION, canonical_key="k2"))
    store.upsert_relationship(Relationship(src_entity_id=a.id, dst_entity_id=b.id, type="operated_by"))
    rels = store.relationships_for_entity(a.id)
    assert len(rels) == 1 and rels[0].type == "operated_by"
    assert store.relationships_for_entity(b.id)[0].src_entity_id == a.id


def test_alerts(store):
    store.upsert_alert(Alert(type="unusual_aircraft", title="t", severity=Severity.HIGH))
    assert len(store.list_alerts()) == 1
    assert len(store.list_alerts(status="new")) == 1
    assert store.list_alerts(status="resolved") == []


def test_sources(store):
    store.upsert_source(Source(kind="feed", name="OpenSky", trusted=True))
    assert len(store.list_sources()) == 1


def test_audit_log(store):
    store.audit("agent:x", "create_investigation", tool="create_investigation", scope="write")
    log = store.recent_audit()
    assert len(log) == 1 and log[0]["action"] == "create_investigation"


def test_stats(store):
    store.upsert_investigation(Investigation(title="C"))
    stats = store.stats()
    assert stats["investigations"] == 1
    assert "entities" in stats


def test_persistence_across_reopen(tmp_path):
    path = str(tmp_path / "inv.db")
    s1 = Store(path)
    inv = s1.upsert_investigation(Investigation(title="Persisted"))
    s1.close()
    s2 = Store(path)
    assert s2.get_investigation(inv.id).title == "Persisted"
    s2.close()
