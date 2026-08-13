"""End-to-end API tests for the investigation workspace router.

Uses the loopback ``client`` fixture (authenticated as local operator) and the
``remote_client`` fixture (external, unauthenticated) to also assert the
authorization gate. The investigation store is reset to an in-memory database
per test for isolation.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_store():
    from storage import reset_store_for_tests

    reset_store_for_tests()
    yield
    reset_store_for_tests()


def test_full_investigation_flow(client):
    # create
    r = client.post("/api/investigations", json={"title": "Black Sea Activity", "question": "What changed?"})
    assert r.status_code == 201, r.text
    inv = r.json()
    inv_id = inv["id"]
    assert inv["status"] == "open"

    # list
    r = client.get("/api/investigations")
    assert r.status_code == 200
    assert any(i["id"] == inv_id for i in r.json()["investigations"])

    # add entity via record ingestion
    r = client.post(
        f"/api/investigations/{inv_id}/entities",
        json={"record": {"icao24": "abc123", "name": "JET1", "lat": 43.1, "lng": 30.2, "source": "OpenSky"},
              "entity_type": "aircraft", "layer": "commercial_flights"},
    )
    assert r.status_code == 201, r.text
    assert len(r.json()["entity_ids"]) == 1

    # add a derived event
    r = client.post(
        f"/api/investigations/{inv_id}/events",
        json={"type": "heading_change", "title": "Heading change 32deg", "classification": "derived_event",
              "occurred_at": "2026-08-13T09:43:00Z", "lat": 43.1, "lng": 30.2, "severity": "medium",
              "explanation": "delta exceeds baseline"},
    )
    assert r.status_code == 201, r.text
    event = r.json()
    assert event["classification"] == "derived_event"

    # add raw + analysis evidence
    r = client.post(
        f"/api/investigations/{inv_id}/evidence",
        json={"kind": "observation", "title": "ADS-B contact", "classification": "raw_observation",
              "provenance": {"source_name": "OpenSky", "source_url": "https://opensky-network.org", "method": "ADS-B"}},
    )
    assert r.status_code == 201, r.text
    ev_raw = r.json()["id"]
    assert r.json()["classification"] == "raw_observation"

    r = client.post(
        f"/api/investigations/{inv_id}/evidence",
        json={"kind": "correlation", "title": "Vessel co-location", "classification": "analysis"},
    )
    ev_analysis = r.json()["id"]

    # hypothesis with derived confidence
    r = client.post(
        f"/api/investigations/{inv_id}/hypotheses",
        json={"statement": "Coordinated activity", "supporting_evidence_ids": [ev_raw, ev_analysis]},
    )
    assert r.status_code == 201, r.text
    hyp = r.json()
    assert hyp["classification"] == "hypothesis"
    assert hyp["confidence"]["score"] is not None
    assert hyp["confidence"]["score"] > 0.5

    # note
    r = client.post(f"/api/investigations/{inv_id}/notes", json={"body": "Reviewed satellite pass"})
    assert r.status_code == 201

    # bundle
    r = client.get(f"/api/investigations/{inv_id}")
    assert r.status_code == 200
    bundle = r.json()
    assert bundle["counts"]["entities"] == 1
    assert bundle["counts"]["events"] == 1
    assert bundle["counts"]["evidence"] == 2
    assert bundle["counts"]["hypotheses"] == 1
    assert len(bundle["timeline"]) >= 3

    # timeline chronological
    r = client.get(f"/api/investigations/{inv_id}/timeline")
    tl = r.json()["timeline"]
    ts = [x["ts"] for x in tl if x.get("ts")]
    assert ts == sorted(ts)

    # briefing separates facts from inference and never promotes a hypothesis
    r = client.get(f"/api/investigations/{inv_id}/briefing")
    assert r.status_code == 200
    brief = r.json()
    assert brief["summary"]["facts"] >= 1
    assert all(h["classification"] == "hypothesis" for h in brief["hypotheses"])
    assert "caveat" in brief
    assert len(brief["recommended_next_steps"]) >= 1


def test_update_and_delete(client):
    inv_id = client.post("/api/investigations", json={"title": "Case"}).json()["id"]
    r = client.patch(f"/api/investigations/{inv_id}", json={"status": "active", "title": "Case A"})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["title"] == "Case A"
    r = client.delete(f"/api/investigations/{inv_id}")
    assert r.status_code == 200
    assert client.get(f"/api/investigations/{inv_id}").status_code == 404


def test_entity_search_and_get(client):
    inv_id = client.post("/api/investigations", json={"title": "C"}).json()["id"]
    client.post(
        f"/api/investigations/{inv_id}/entities",
        json={"record": {"mmsi": "999", "name": "Vessel Q", "lat": 10, "lng": 20, "source": "AIS"},
              "entity_type": "vessel", "layer": "ships"},
    )
    r = client.get("/api/entities/search", params={"q": "Vessel", "type": "vessel"})
    assert r.status_code == 200 and r.json()["count"] == 1
    eid = r.json()["entities"][0]["id"]
    r = client.get(f"/api/entities/{eid}")
    assert r.status_code == 200
    assert len(r.json()["observations"]) == 1
    assert r.json()["observations"][0]["provenance"]["source_name"] == "AIS"


def test_missing_investigation_returns_404(client):
    assert client.get("/api/investigations/inv_doesnotexist").status_code == 404
    assert client.get("/api/investigations/inv_x/briefing").status_code == 404


def test_create_requires_title(client):
    r = client.post("/api/investigations", json={"question": "no title"})
    assert r.status_code == 422  # pydantic validation


def test_authorization_gate_rejects_remote(remote_client):
    # A non-loopback caller without admin key must be rejected.
    r = remote_client.post("/api/investigations", json={"title": "x"})
    assert r.status_code in (401, 403)
    r = remote_client.get("/api/investigations")
    assert r.status_code in (401, 403)
