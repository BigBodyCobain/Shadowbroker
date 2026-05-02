"""S14B Public Sync Gate Event Filter.

Tests:
- GET /api/mesh/infonet/sync excludes gate_message when local infonet contains legacy gate_message plus public events
- POST /api/mesh/infonet/sync excludes gate_message under the same condition
- Both main app and router-served paths are covered
- Non-gate public redactions still hold (vote gate label stripped, key_rotate identity stripped)
- Do not overclaim that gate_message is removed from historical infonet storage or ingest
"""

import asyncio
import json

from starlette.requests import Request

import main
from services.mesh import mesh_hashchain


# ── Helpers ──────────────────────────────────────────────────────────────


def _message_event() -> dict:
    return {
        "event_id": "msg-1",
        "event_type": "message",
        "node_id": "!node-1",
        "payload": {"text": "hello world"},
        "timestamp": 100.0,
        "sequence": 1,
        "signature": "sig",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
    }


def _vote_event() -> dict:
    return {
        "event_id": "vote-1",
        "event_type": "vote",
        "node_id": "!node-2",
        "payload": {"gate": "finance", "vote": 1},
        "timestamp": 101.0,
        "sequence": 2,
        "signature": "sig",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
    }


def _key_rotate_event() -> dict:
    return {
        "event_id": "rotate-1",
        "event_type": "key_rotate",
        "node_id": "!node-3",
        "payload": {
            "old_node_id": "!old-node",
            "old_public_key": "old-pub",
            "old_public_key_algo": "Ed25519",
            "old_signature": "old-sig",
            "timestamp": 123,
        },
        "timestamp": 102.0,
        "sequence": 3,
        "signature": "sig",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
    }


def _gate_message_event() -> dict:
    return {
        "event_id": "gate-1",
        "event_type": "gate_message",
        "node_id": "!node-4",
        "payload": {
            "gate": "finance",
            "ciphertext": "opaque-blob",
            "epoch": 2,
            "nonce": "nonce-1",
            "sender_ref": "sender-ref-1",
            "format": "mls1",
        },
        "timestamp": 103.0,
        "sequence": 4,
        "signature": "sig",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
    }


class _FakeInfonet:
    """Minimal fake infonet with a gate_message among public events."""

    def __init__(self):
        self.head_hash = "head-1"
        self.events = [
            _message_event(),
            _vote_event(),
            _key_rotate_event(),
            _gate_message_event(),
        ]

    @staticmethod
    def _limit_value(limit) -> int:
        try:
            return int(limit)
        except Exception:
            return int(getattr(limit, "default", 100) or 100)

    def get_events_after(self, after_hash: str, limit=100):
        resolved = self._limit_value(limit)
        return [dict(e) for e in self.events[:resolved]]

    def get_events_after_locator(self, locator: list[str], limit=100):
        resolved = self._limit_value(limit)
        return self.head_hash, 0, [dict(e) for e in self.events[:resolved]]

    def get_merkle_proofs(self, start_index: int, count: int):
        return {"root": "merkle-root", "total": len(self.events), "start": start_index, "proofs": []}

    def get_merkle_root(self):
        return "merkle-root"


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


def _get_request(path: str) -> Request:
    sent = {"value": False}

    async def receive():
        if sent["value"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["value"] = True
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "headers": [],
            "client": ("test", 12345),
            "method": "GET",
            "path": path,
        },
        receive,
    )


# ── GET sync excludes gate_message (main app) ──────────────────────────


def test_get_sync_excludes_gate_message(client, monkeypatch):
    """GET /api/mesh/infonet/sync must not return gate_message events."""
    monkeypatch.setattr(mesh_hashchain, "infonet", _FakeInfonet(), raising=False)
    resp = client.get("/api/mesh/infonet/sync")
    data = resp.json()
    event_types = [e["event_type"] for e in data["events"]]
    assert "gate_message" not in event_types
    assert "message" in event_types
    assert "vote" in event_types
    assert "key_rotate" in event_types


def test_get_sync_count_excludes_gate_message(client, monkeypatch):
    """GET sync count field must reflect filtered events (gate_message excluded)."""
    monkeypatch.setattr(mesh_hashchain, "infonet", _FakeInfonet(), raising=False)
    resp = client.get("/api/mesh/infonet/sync")
    data = resp.json()
    assert data["count"] == 3  # message, vote, key_rotate — not gate_message


# ── POST sync excludes gate_message (main app) ─────────────────────────


def test_post_sync_excludes_gate_message(monkeypatch):
    """POST /api/mesh/infonet/sync must not return gate_message events."""
    monkeypatch.setattr(mesh_hashchain, "infonet", _FakeInfonet(), raising=False)
    result = asyncio.run(
        main.infonet_sync_post(
            _json_request("/api/mesh/infonet/sync", {"locator": ["head-1"]})
        )
    )
    event_types = [e["event_type"] for e in result["events"]]
    assert "gate_message" not in event_types
    assert "message" in event_types
    assert "vote" in event_types
    assert "key_rotate" in event_types


def test_post_sync_count_excludes_gate_message(monkeypatch):
    """POST sync count field must reflect filtered events."""
    monkeypatch.setattr(mesh_hashchain, "infonet", _FakeInfonet(), raising=False)
    result = asyncio.run(
        main.infonet_sync_post(
            _json_request("/api/mesh/infonet/sync", {"locator": ["head-1"]})
        )
    )
    assert result["count"] == 3


# ── Router-served paths ────────────────────────────────────────────────


def test_router_get_sync_excludes_gate_message(monkeypatch):
    """Router GET /api/mesh/infonet/sync must not return gate_message."""
    from routers.mesh_public import infonet_sync

    monkeypatch.setattr(mesh_hashchain, "infonet", _FakeInfonet(), raising=False)
    result = asyncio.run(infonet_sync(_get_request("/api/mesh/infonet/sync")))
    event_types = [e["event_type"] for e in result["events"]]
    assert "gate_message" not in event_types
    assert "message" in event_types
    assert data_count_matches(result)


def test_router_post_sync_excludes_gate_message(monkeypatch):
    """Router POST /api/mesh/infonet/sync must not return gate_message."""
    from routers.mesh_public import infonet_sync_post

    monkeypatch.setattr(mesh_hashchain, "infonet", _FakeInfonet(), raising=False)
    result = asyncio.run(
        infonet_sync_post(
            _json_request("/api/mesh/infonet/sync", {"locator": ["head-1"]})
        )
    )
    event_types = [e["event_type"] for e in result["events"]]
    assert "gate_message" not in event_types
    assert "message" in event_types
    assert data_count_matches(result)


def data_count_matches(result: dict) -> bool:
    return result["count"] == len(result["events"])


# ── Non-gate redactions still hold ─────────────────────────────────────


def test_get_sync_still_redacts_vote_gate_label(client, monkeypatch):
    """Public sync must still strip gate label from vote payload."""
    monkeypatch.setattr(mesh_hashchain, "infonet", _FakeInfonet(), raising=False)
    resp = client.get("/api/mesh/infonet/sync")
    events = resp.json()["events"]
    vote = next(e for e in events if e["event_type"] == "vote")
    assert "gate" not in vote.get("payload", {})


def test_get_sync_still_redacts_key_rotate_identity(client, monkeypatch):
    """Public sync must still strip old identity fields from key_rotate payload."""
    monkeypatch.setattr(mesh_hashchain, "infonet", _FakeInfonet(), raising=False)
    resp = client.get("/api/mesh/infonet/sync")
    events = resp.json()["events"]
    rotate = next(e for e in events if e["event_type"] == "key_rotate")
    payload = rotate.get("payload", {})
    assert "old_node_id" not in payload
    assert "old_public_key" not in payload
    assert "old_signature" not in payload


def test_post_sync_still_redacts_vote_and_rotate(monkeypatch):
    """POST sync must still apply standard public redactions to non-gate events."""
    monkeypatch.setattr(mesh_hashchain, "infonet", _FakeInfonet(), raising=False)
    result = asyncio.run(
        main.infonet_sync_post(
            _json_request("/api/mesh/infonet/sync", {"locator": ["head-1"]})
        )
    )
    vote = next(e for e in result["events"] if e["event_type"] == "vote")
    rotate = next(e for e in result["events"] if e["event_type"] == "key_rotate")
    assert "gate" not in vote.get("payload", {})
    assert "old_node_id" not in rotate.get("payload", {})


# ── No overclaim ───────────────────────────────────────────────────────


def test_gate_message_still_in_fake_infonet_storage():
    """The filter does NOT remove gate_message from underlying storage.
    This test documents that the infonet still holds gate_message events;
    only the public sync response surface filters them out."""
    fake = _FakeInfonet()
    all_types = [e["event_type"] for e in fake.events]
    assert "gate_message" in all_types


def test_sync_with_only_gate_messages_returns_empty(client, monkeypatch):
    """If infonet contains only gate_message events, sync returns empty list."""
    class _GateOnlyInfonet:
        head_hash = "head-1"
        events = [_gate_message_event()]

        def get_events_after(self, after_hash, limit=100):
            return [dict(e) for e in self.events]

        def get_events_after_locator(self, locator, limit=100):
            return self.head_hash, 0, [dict(e) for e in self.events]

        def get_merkle_proofs(self, start_index, count):
            return {"root": "r", "total": 1, "start": 0, "proofs": []}

        def get_merkle_root(self):
            return "r"

    monkeypatch.setattr(mesh_hashchain, "infonet", _GateOnlyInfonet(), raising=False)
    resp = client.get("/api/mesh/infonet/sync")
    data = resp.json()
    assert data["events"] == []
    assert data["count"] == 0
