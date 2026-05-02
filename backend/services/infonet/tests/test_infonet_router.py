"""Smoke tests for the routers.infonet HTTP surface.

The router is a thin wrapper over the pure-function adapters; these
tests confirm the response shapes match what the frontend client
(`frontend/src/mesh/infonetEconomyClient.ts`) expects, so the two
sides stay aligned.

Tests use FastAPI's TestClient against the router directly, NOT the
full ``main.app`` (which would require the FastAPI app's full startup
pipeline). The router's ``_live_chain`` helper falls back to an empty
chain when ``mesh_hashchain.infonet`` isn't bound — perfect for unit
testing.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.infonet import router


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ── /api/infonet/status ─────────────────────────────────────────────────

def test_status_shape(client: TestClient):
    res = client.get("/api/infonet/status")
    assert res.status_code == 200
    data = res.json()
    # Ramp keys.
    assert "ramp" in data
    for key in ("node_count", "bootstrap_resolution_active",
                "staked_resolution_active", "governance_petitions_active",
                "upgrade_governance_active", "commoncoin_active"):
        assert key in data["ramp"]
    # Privacy primitive statuses.
    assert "privacy_primitive_status" in data
    for prim in ("ringct", "stealth_address", "shielded_balance", "dex"):
        assert prim in data["privacy_primitive_status"]
        # Sprint 11+ scaffolding: all report not_implemented.
        assert data["privacy_primitive_status"][prim] == "not_implemented"
    # Constitutional principles surface.
    assert "immutable_principles" in data
    assert data["immutable_principles"]["oracle_rep_source"] == "predictions_only"
    assert data["immutable_principles"]["coin_governance_firewall"] is True
    # Counts.
    assert data["config_keys_count"] > 90
    assert data["infonet_economy_event_types_count"] >= 49


# ── /api/infonet/petitions ──────────────────────────────────────────────

def test_petitions_list_empty_chain(client: TestClient):
    res = client.get("/api/infonet/petitions")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert isinstance(data["petitions"], list)


def test_petitions_preview_validates_payload(client: TestClient):
    res = client.post("/api/infonet/petitions/preview", json={
        "type": "UPDATE_PARAM",
        "key": "vote_decay_days",
        "value": 30,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["changed_keys"] == ["vote_decay_days"]
    assert data["new_values"]["vote_decay_days"] == 30


def test_petitions_preview_rejects_immutable_key(client: TestClient):
    res = client.post("/api/infonet/petitions/preview", json={
        "type": "UPDATE_PARAM",
        "key": "oracle_rep_source",  # IMMUTABLE_PRINCIPLES key
        "value": "anything",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert "IMMUTABLE_PRINCIPLES" in data["reason"]


def test_petitions_preview_rejects_out_of_bounds(client: TestClient):
    res = client.post("/api/infonet/petitions/preview", json={
        "type": "UPDATE_PARAM",
        "key": "vote_decay_days",
        "value": 9999,  # max is 365
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert "above maximum" in data["reason"]


# ── /api/infonet/events/validate ───────────────────────────────────────

def test_validate_event_uprep_valid(client: TestClient):
    res = client.post("/api/infonet/events/validate", json={
        "event_type": "uprep",
        "payload": {"target_node_id": "alice", "target_event_id": "post1"},
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["tier"] == "tier1"
    # Tier 1 events are never marked provisional.
    assert data["would_be_provisional"] is False


def test_validate_event_resolution_finalize_is_tier2(client: TestClient):
    res = client.post("/api/infonet/events/validate", json={
        "event_type": "resolution_finalize",
        "payload": {
            "market_id": "m1", "outcome": "yes",
            "is_provisional": False, "snapshot_event_hash": "h",
        },
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["tier"] == "tier2"
    # would_be_provisional depends on chain freshness (real disk-persisted
    # chain in dev environments may have recent events, making the chain
    # not stale). The Sprint 10 unit test covers the boolean exactly with
    # explicit `now`. Here we just verify the field is a bool.
    assert isinstance(data["would_be_provisional"], bool)


def test_validate_event_rejects_unknown_type(client: TestClient):
    res = client.post("/api/infonet/events/validate", json={
        "event_type": "totally_made_up",
        "payload": {},
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False


def test_validate_event_rejects_malformed_payload(client: TestClient):
    res = client.post("/api/infonet/events/validate", json={
        "event_type": "uprep",
        "payload": {"target_node_id": "alice"},  # missing target_event_id
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert "target_event_id" in data["reason"]


# ── /api/infonet/upgrades ──────────────────────────────────────────────

def test_upgrades_list_empty_chain(client: TestClient):
    res = client.get("/api/infonet/upgrades")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert isinstance(data["upgrades"], list)


def test_upgrades_get_unknown(client: TestClient):
    res = client.get("/api/infonet/upgrades/nonexistent")
    assert res.status_code == 200
    data = res.json()
    assert data["upgrade"]["status"] == "not_found"


# ── /api/infonet/markets ────────────────────────────────────────────────

def test_market_get_unknown_returns_predicting(client: TestClient):
    res = client.get("/api/infonet/markets/never-seen")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["status"] == "predicting"
    assert data["snapshot"] is None
    assert data["evidence_bundles"] == []
    assert data["disputes"] == []


def test_market_preview_resolution_unknown(client: TestClient):
    res = client.get("/api/infonet/markets/never-seen/preview-resolution")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["preview"]["outcome"] == "invalid"
    # No market means no_market reason.
    assert data["preview"]["reason"] == "no_market"


# ── /api/infonet/gates ──────────────────────────────────────────────────

def test_gate_get_unknown(client: TestClient):
    res = client.get("/api/infonet/gates/never-seen")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["reason"] == "gate_not_found"


# ── /api/infonet/nodes/{node_id}/reputation ─────────────────────────────

def test_node_reputation_unknown_node(client: TestClient):
    res = client.get("/api/infonet/nodes/never-seen/reputation")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["oracle_rep"] == 0.0
    assert data["common_rep"] == 0.0
    assert data["breakdown"]["total"] == 0.0


# ── /api/infonet/bootstrap/markets/{market_id} ──────────────────────────

def test_bootstrap_market_state_unknown(client: TestClient):
    res = client.get("/api/infonet/bootstrap/markets/never-seen")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["votes"] == []
    assert data["tally"]["yes"] == 0
    assert data["tally"]["no"] == 0
    assert data["tally"]["min_market_participants"] >= 2
    assert data["tally"]["supermajority_threshold"] > 0.5


# ── /api/infonet/function-keys/operator/{operator_id}/batch-summary ─────

def test_function_keys_operator_batch_summary(client: TestClient):
    res = client.get("/api/infonet/function-keys/operator/op-1/batch-summary")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["operator_id"] == "op-1"
    assert data["scaffolding_only"] is True


# ── /api/infonet/append (signed write) ──────────────────────────────────

def test_append_rejects_unknown_event_type(client: TestClient):
    res = client.post("/api/infonet/append", json={
        "event_type": "totally_made_up",
        "node_id": "n1",
        "payload": {},
        "signature": "deadbeef",
        "sequence": 1,
        "public_key": "pk",
        "public_key_algo": "ed25519",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert "INFONET_ECONOMY_EVENT_TYPES" in data["reason"]


def test_append_rejects_missing_signature(client: TestClient):
    res = client.post("/api/infonet/append", json={
        "event_type": "uprep",
        "node_id": "n1",
        "payload": {"target_node_id": "n2", "target_event_id": "e1"},
        "sequence": 1,
        "public_key": "pk",
        "public_key_algo": "ed25519",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert "signature" in data["reason"]


def test_append_rejects_invalid_sequence(client: TestClient):
    res = client.post("/api/infonet/append", json={
        "event_type": "uprep",
        "node_id": "n1",
        "payload": {"target_node_id": "n2", "target_event_id": "e1"},
        "signature": "deadbeef",
        "sequence": 0,  # must be > 0
        "public_key": "pk",
        "public_key_algo": "ed25519",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert "sequence" in data["reason"]


def test_append_rejects_missing_node_id(client: TestClient):
    res = client.post("/api/infonet/append", json={
        "event_type": "uprep",
        "payload": {"target_node_id": "n2", "target_event_id": "e1"},
        "signature": "deadbeef",
        "sequence": 1,
        "public_key": "pk",
        "public_key_algo": "ed25519",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert "node_id" in data["reason"]


def test_append_rejects_invalid_signature_at_chain_layer(client: TestClient):
    """The cutover routes the validator + signature check through
    ``Infonet.append``. A garbage signature is rejected with the legacy
    diagnostic — this confirms the secure entry point fires."""
    res = client.post("/api/infonet/append", json={
        "event_type": "uprep",
        "node_id": "n1",
        "payload": {"target_node_id": "n2", "target_event_id": "e1"},
        "signature": "00" * 64,  # well-formed length but invalid
        "sequence": 1,
        "public_key": "AAAAAAAA",
        "public_key_algo": "ed25519",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    # The exact reason depends on which validator catches it first
    # (signature algo, node binding, signature verify). Just confirm
    # something was rejected with a non-empty diagnostic.
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0
