import base64
import json
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from starlette.requests import Request

from services.config import get_settings
from services.mesh.mesh_crypto import build_signature_payload, derive_node_id
from services.mesh.mesh_protocol import build_signed_context
from services.mesh.mesh_signed_events import (
    PROTOCOL_VERSION,
    SignedWriteKind,
    requires_signed_write,
    verify_signed_event,
)
from services.release_profiles import profile_readiness_snapshot


def setup_function():
    get_settings.cache_clear()


def teardown_function():
    get_settings.cache_clear()


def _make_receive(body: bytes):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _request(body: dict, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": path,
            "query_string": b"",
            "root_path": "",
            "server": ("test", 80),
        },
        _make_receive(json.dumps(body).encode("utf-8")),
    )


def _identity():
    private = ed25519.Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(public_raw).decode("ascii")
    return private, public_key, derive_node_id(public_key)


def _signed_dm_send(path: str = "/api/wormhole/dm/send") -> dict:
    private, public_key, sender_id = _identity()
    sequence = 17
    payload = {
        "recipient_id": "!sb_recipient000000000000000000000",
        "delivery_class": "alias",
        "recipient_token": "recipient-token",
        "ciphertext": "ciphertext",
        "format": "mls1",
        "msg_id": "msg-1",
        "timestamp": int(time.time()),
        "transport_lock": "private_strong",
    }
    payload["signed_context"] = build_signed_context(
        event_type="dm_message",
        kind="dm_send",
        endpoint=path,
        lane_floor="private_strong",
        sequence_domain="dm_send",
        node_id=sender_id,
        sequence=sequence,
        payload=payload,
        recipient_id=payload["recipient_id"],
    )
    signature_payload = build_signature_payload(
        event_type="dm_message",
        node_id=sender_id,
        sequence=sequence,
        payload=payload,
    )
    return {
        "sender_id": sender_id,
        "recipient_id": payload["recipient_id"],
        "delivery_class": payload["delivery_class"],
        "recipient_token": payload["recipient_token"],
        "ciphertext": payload["ciphertext"],
        "format": payload["format"],
        "msg_id": payload["msg_id"],
        "timestamp": payload["timestamp"],
        "transport_lock": payload["transport_lock"],
        "signed_context": payload["signed_context"],
        "sequence": sequence,
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "protocol_version": PROTOCOL_VERSION,
        "signature": private.sign(signature_payload.encode("utf-8")).hex(),
    }


def test_signed_context_is_bound_into_signature_payload():
    body = _signed_dm_send()
    payload = {
        "recipient_id": body["recipient_id"],
        "delivery_class": body["delivery_class"],
        "recipient_token": body["recipient_token"],
        "ciphertext": body["ciphertext"],
        "format": body["format"],
        "msg_id": body["msg_id"],
        "timestamp": body["timestamp"],
        "transport_lock": body["transport_lock"],
        "signed_context": body["signed_context"],
    }

    ok, reason = verify_signed_event(
        event_type="dm_message",
        node_id=body["sender_id"],
        sequence=body["sequence"],
        public_key=body["public_key"],
        public_key_algo=body["public_key_algo"],
        signature=body["signature"],
        payload=payload,
        protocol_version=body["protocol_version"],
    )

    assert ok is True, reason

    mutated = dict(payload)
    mutated["signed_context"] = dict(payload["signed_context"])
    mutated["signed_context"]["endpoint"] = "/api/wormhole/dm/poll"
    ok, reason = verify_signed_event(
        event_type="dm_message",
        node_id=body["sender_id"],
        sequence=body["sequence"],
        public_key=body["public_key"],
        public_key_algo=body["public_key_algo"],
        signature=body["signature"],
        payload=mutated,
        protocol_version=body["protocol_version"],
    )
    assert ok is False
    assert reason == "Invalid signature"


@pytest.mark.asyncio
async def test_decorator_rejects_signed_context_endpoint_mismatch(monkeypatch):
    monkeypatch.setenv("MESH_SIGNED_WRITE_CONTENT_PRIVATE_TRANSPORT_LOCK_REQUIRED", "true")
    body = _signed_dm_send(path="/api/wormhole/dm/send")
    body["signed_context"] = dict(body["signed_context"])
    body["signed_context"]["endpoint"] = "/api/wormhole/dm/poll"

    @requires_signed_write(kind=SignedWriteKind.DM_SEND)
    async def handler(request: Request):
        return {"ok": True}

    result = await handler(_request(body, "/api/wormhole/dm/send"))

    assert result["ok"] is False
    assert result["detail"] == "signed_context_mismatch"
    assert result["retryable"] is True
    assert result["resign_required"] is True
    assert result["canonical"]["signed_context"]["endpoint"] == "/api/wormhole/dm/send"
    assert result["canonical"]["payload"]["signed_context"] == result["canonical"]["signed_context"]
    assert isinstance(result["canonical"]["signature_payload"], str)


@pytest.mark.asyncio
async def test_decorator_requires_signed_context_when_enforced(monkeypatch):
    monkeypatch.setenv("MESH_SIGNED_WRITE_CONTEXT_REQUIRED", "true")
    monkeypatch.setenv("MESH_SIGNED_WRITE_CONTENT_PRIVATE_TRANSPORT_LOCK_REQUIRED", "true")
    body = _signed_dm_send()
    body.pop("signed_context")

    @requires_signed_write(kind=SignedWriteKind.DM_SEND)
    async def handler(request: Request):
        return {"ok": True}

    result = await handler(_request(body, "/api/wormhole/dm/send"))

    assert result["ok"] is False
    assert result["detail"] == "signed_context is required on this signed write"
    assert result["retryable"] is True
    assert result["resign_required"] is True
    assert result["canonical"]["signed_context"]["endpoint"] == "/api/wormhole/dm/send"
    assert result["canonical"]["signed_context"]["kind"] == "dm_send"
    assert result["canonical"]["signed_context"]["lane_floor"] == "private_strong"
    assert result["canonical"]["payload"]["signed_context"] == result["canonical"]["signed_context"]
    assert isinstance(result["canonical"]["signature_payload"], str)


def test_release_candidate_blocks_without_signed_context_requirement(monkeypatch):
    monkeypatch.setenv("MESH_RELEASE_PROFILE", "release-candidate")
    monkeypatch.setenv("MESH_DEBUG_MODE", "false")
    monkeypatch.setenv("PRIVACY_CORE_ALLOWED_SHA256", "a" * 64)
    monkeypatch.setenv("MESH_SIGNED_WRITE_CONTEXT_REQUIRED", "false")
    get_settings.cache_clear()

    readiness = profile_readiness_snapshot()

    assert readiness["profile"] == "release-candidate"
    assert "profile_signed_context_not_required" in readiness["blockers"]


def test_signed_write_v1_vectors_are_stable():
    root = Path(__file__).resolve().parents[3]
    vectors = json.loads((root / "docs" / "protocol" / "signed-write-v1-vectors.json").read_text())

    for case in vectors:
        signature_payload = build_signature_payload(
            event_type=case["event_type"],
            node_id=case["node_id"],
            sequence=case["sequence"],
            payload=case["payload"],
        )
        assert signature_payload == case["signature_payload"]

        ok, reason = verify_signed_event(
            event_type=case["event_type"],
            node_id=case["node_id"],
            sequence=case["sequence"],
            public_key=case["public_key"],
            public_key_algo=case["public_key_algo"],
            signature=case["signature"],
            payload=case["payload"],
            protocol_version=case["protocol_version"],
        )
        assert ok is True, reason
