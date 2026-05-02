"""S16A DM Count Coarsening.

Tests:
- _coarsen_dm_count helper boundary values
- POST /api/mesh/dm/count returns coarsened values
- GET /api/mesh/dm/count returns coarsened values
- /api/mesh/dm/poll still returns exact count == len(messages)
- No overclaim: internal relay exact counting unchanged
"""

import asyncio
import json

from starlette.requests import Request

import main
from services.config import get_settings
from services.mesh import mesh_dm_relay, mesh_hashchain


def _bypass_transport_tier(monkeypatch):
    """Allow DM endpoints through the transport-tier middleware."""
    monkeypatch.setattr(main, "_transport_tier_is_sufficient", lambda cur, req: True)


# ── Helper boundary tests ─────────────────────────────────────────────


def test_coarsen_zero():
    assert main._coarsen_dm_count(0) == 0


def test_coarsen_one():
    assert main._coarsen_dm_count(1) == 1


def test_coarsen_two():
    assert main._coarsen_dm_count(2) == 5


def test_coarsen_five():
    assert main._coarsen_dm_count(5) == 5


def test_coarsen_six():
    assert main._coarsen_dm_count(6) == 20


def test_coarsen_twenty():
    assert main._coarsen_dm_count(20) == 20


def test_coarsen_twenty_one():
    assert main._coarsen_dm_count(21) == 50


def test_coarsen_large():
    assert main._coarsen_dm_count(999) == 50


# ── POST /api/mesh/dm/count returns coarsened ─────────────────────────


def _json_request(path: str, body: dict) -> Request:
    payload = json.dumps(body).encode("utf-8")
    sent = {"value": False}

    async def receive():
        if sent["value"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["value"] = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": path,
        },
        receive,
    )


def test_post_dm_count_coarsened(monkeypatch):
    """POST dm/count with 3 messages should return coarsened 5, not exact 3."""
    monkeypatch.setattr(main, "_verify_dm_mailbox_request", lambda **kw: (True, "", kw))
    monkeypatch.setattr(main, "_anonymous_dm_hidden_transport_enforced", lambda: True)
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "consume_nonce", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "claim_mailbox_keys", lambda *a, **kw: [])
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "claim_message_ids", lambda *a, **kw: {"a", "b", "c"})
    monkeypatch.setattr(mesh_hashchain, "infonet", type("FakeInfonet", (), {
        "validate_and_set_sequence": staticmethod(lambda *a, **kw: (True, ""))
    })(), raising=False)

    result = asyncio.run(main.dm_count_secure(
        _json_request("/api/mesh/dm/count", {
            "agent_id": "test-agent",
            "mailbox_claims": [],
            "timestamp": 1000,
            "nonce": "nonce-1",
            "public_key": "pk",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "infonet/2",
        })
    ))
    assert result["ok"] is True
    assert result["count"] == 5  # coarsened from 3


def test_post_dm_count_zero_stays_zero(monkeypatch):
    """POST dm/count with 0 messages should return 0."""
    monkeypatch.setattr(main, "_verify_dm_mailbox_request", lambda **kw: (True, "", kw))
    monkeypatch.setattr(main, "_anonymous_dm_hidden_transport_enforced", lambda: True)
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "consume_nonce", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "claim_mailbox_keys", lambda *a, **kw: [])
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "claim_message_ids", lambda *a, **kw: set())
    monkeypatch.setattr(mesh_hashchain, "infonet", type("FakeInfonet", (), {
        "validate_and_set_sequence": staticmethod(lambda *a, **kw: (True, ""))
    })(), raising=False)

    result = asyncio.run(main.dm_count_secure(
        _json_request("/api/mesh/dm/count", {
            "agent_id": "test-agent",
            "mailbox_claims": [],
            "timestamp": 1000,
            "nonce": "nonce-2",
            "public_key": "pk",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 2,
            "protocol_version": "infonet/2",
        })
    ))
    assert result["count"] == 0


def test_post_dm_count_21_coarsened_to_50(monkeypatch):
    """POST dm/count with 21 messages should return coarsened 50."""
    ids = {f"id-{i}" for i in range(21)}
    monkeypatch.setattr(main, "_verify_dm_mailbox_request", lambda **kw: (True, "", kw))
    monkeypatch.setattr(main, "_anonymous_dm_hidden_transport_enforced", lambda: True)
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "consume_nonce", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "claim_mailbox_keys", lambda *a, **kw: [])
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "claim_message_ids", lambda *a, **kw: ids)
    monkeypatch.setattr(mesh_hashchain, "infonet", type("FakeInfonet", (), {
        "validate_and_set_sequence": staticmethod(lambda *a, **kw: (True, ""))
    })(), raising=False)

    result = asyncio.run(main.dm_count_secure(
        _json_request("/api/mesh/dm/count", {
            "agent_id": "test-agent",
            "mailbox_claims": [],
            "timestamp": 1000,
            "nonce": "nonce-3",
            "public_key": "pk",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 3,
            "protocol_version": "infonet/2",
        })
    ))
    assert result["count"] == 50


# ── GET /api/mesh/dm/count returns coarsened ──────────────────────────


def _allow_legacy_get(monkeypatch):
    _bypass_transport_tier(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_legacy_dm_get_allowed", lambda: True)


def test_get_dm_count_coarsened(client, monkeypatch):
    """GET dm/count with 7 messages should return coarsened 20."""
    _allow_legacy_get(monkeypatch)
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "count_legacy", lambda **kw: 7)
    resp = client.get("/api/mesh/dm/count?agent_token=tok1")
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 20


def test_get_dm_count_one_stays_one(client, monkeypatch):
    """GET dm/count with exactly 1 message should return 1."""
    _allow_legacy_get(monkeypatch)
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "count_legacy", lambda **kw: 1)
    resp = client.get("/api/mesh/dm/count?agent_token=tok1")
    assert resp.json()["count"] == 1


def test_get_dm_count_large_coarsened(client, monkeypatch):
    """GET dm/count with 100 messages should return coarsened 50."""
    _allow_legacy_get(monkeypatch)
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "count_legacy", lambda **kw: 100)
    resp = client.get("/api/mesh/dm/count?agent_token=tok1")
    assert resp.json()["count"] == 50


def test_get_dm_count_old_bool_no_longer_enables_legacy_route(client, monkeypatch):
    _bypass_transport_tier(monkeypatch)
    monkeypatch.setenv("MESH_DM_ALLOW_LEGACY_GET", "true")
    monkeypatch.delenv("MESH_ALLOW_LEGACY_DM_GET_UNTIL", raising=False)
    get_settings.cache_clear()
    try:
        resp = client.get("/api/mesh/dm/count?agent_token=tok1")
    finally:
        get_settings.cache_clear()
    assert resp.json()["ok"] is False
    assert resp.json()["detail"] == "Legacy GET count is disabled in secure mode"


def test_get_dm_count_dated_override_enables_legacy_route(client, monkeypatch):
    _bypass_transport_tier(monkeypatch)
    monkeypatch.setenv("MESH_ALLOW_LEGACY_DM_GET_UNTIL", "2099-01-01")
    get_settings.cache_clear()
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "count_legacy", lambda **kw: 7)
    try:
        resp = client.get("/api/mesh/dm/count?agent_token=tok1")
    finally:
        get_settings.cache_clear()
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 20


# ── DM poll returns bounded batch with has_more ──────────────────────


def test_poll_returns_bounded_batch(client, monkeypatch):
    """GET dm/poll with 3 messages returns all 3 (under batch limit), has_more=False."""
    fake_msgs = [{"msg_id": f"m{i}", "ciphertext": "ct", "timestamp": float(i)} for i in range(3)]
    _allow_legacy_get(monkeypatch)
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "collect_legacy", lambda **kw: (list(fake_msgs), False))
    resp = client.get("/api/mesh/dm/poll?agent_token=tok1")
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 3
    assert len(data["messages"]) == 3
    assert data["has_more"] is False


def test_poll_caps_at_batch_limit(client, monkeypatch):
    """GET dm/poll with 25 messages returns at most DM_POLL_BATCH_LIMIT, has_more=True."""
    fake_msgs = [{"msg_id": f"m{i}", "ciphertext": "ct", "timestamp": float(i)} for i in range(25)]
    _allow_legacy_get(monkeypatch)
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "collect_legacy", lambda **kw: (list(fake_msgs), True))
    resp = client.get("/api/mesh/dm/poll?agent_token=tok1")
    data = resp.json()
    assert data["count"] <= main.DM_POLL_BATCH_LIMIT
    assert len(data["messages"]) <= main.DM_POLL_BATCH_LIMIT
    assert data["has_more"] is True


# ── No overclaim ──────────────────────────────────────────────────────


def test_coarsening_is_response_surface_only():
    """Coarsening is a pure function on integers — it does not modify relay internals."""
    for n in range(100):
        result = main._coarsen_dm_count(n)
        assert isinstance(result, int)
        assert result >= 0
        assert result in {0, 1, 5, 20, 50}


def test_coarsening_is_monotonic():
    """Coarsened output never decreases as input increases."""
    prev = 0
    for n in range(200):
        cur = main._coarsen_dm_count(n)
        assert cur >= prev
        prev = cur
