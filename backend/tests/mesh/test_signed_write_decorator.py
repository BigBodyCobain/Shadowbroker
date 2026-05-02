import json
import time

import pytest
from starlette.requests import Request

from services.mesh import mesh_signed_events


def _make_receive(body: bytes):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _request(body: bytes, path: str = "/api/mesh/send") -> Request:
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
        _make_receive(body),
    )


def _mesh_send_body() -> dict[str, object]:
    return {
        "destination": "broadcast",
        "message": "hello",
        "node_id": "node-1",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "signature": "sig",
        "sequence": 7,
        "protocol_version": mesh_signed_events.PROTOCOL_VERSION,
    }


@pytest.mark.asyncio
async def test_requires_signed_write_allows_valid_payload(monkeypatch):
    monkeypatch.setattr(mesh_signed_events, "verify_signed_write", lambda **_kwargs: (True, "ok"))

    @mesh_signed_events.requires_signed_write(kind=mesh_signed_events.SignedWriteKind.MESH_SEND)
    async def handler(request: Request):
        prepared = mesh_signed_events.get_prepared_signed_write(request)
        return {"ok": True, "event_type": prepared.event_type, "body": prepared.body}

    result = await handler(_request(json.dumps(_mesh_send_body()).encode("utf-8")))

    assert result["ok"] is True
    assert result["event_type"] == "message"
    assert result["body"]["message"] == "hello"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "kind", "payload"),
    [
        ("bad signature", mesh_signed_events.SignedWriteKind.MESH_SEND, _mesh_send_body),
        ("Replay detected: sequence 7 <= last 7", mesh_signed_events.SignedWriteKind.MESH_SEND, _mesh_send_body),
        ("public key is revoked", mesh_signed_events.SignedWriteKind.MESH_SEND, _mesh_send_body),
        ("wrong kind", mesh_signed_events.SignedWriteKind.DM_BLOCK, _mesh_send_body),
    ],
)
async def test_requires_signed_write_propagates_verifier_failures(monkeypatch, reason, kind, payload):
    monkeypatch.setenv("MESH_SIGNED_WRITE_CONTENT_PRIVATE_TRANSPORT_LOCK_REQUIRED", "false")
    monkeypatch.setattr(mesh_signed_events, "verify_signed_write", lambda **_kwargs: (False, reason))

    @mesh_signed_events.requires_signed_write(kind=kind)
    async def handler(request: Request):
        return {"ok": True}

    result = await handler(_request(json.dumps(payload()).encode("utf-8")))

    assert result == {"ok": False, "detail": reason}


@pytest.mark.asyncio
async def test_requires_signed_write_rejects_missing_body_object(monkeypatch):
    monkeypatch.setattr(mesh_signed_events, "verify_signed_write", lambda **_kwargs: (True, "ok"))

    @mesh_signed_events.requires_signed_write(kind=mesh_signed_events.SignedWriteKind.MESH_SEND)
    async def handler(request: Request):
        return {"ok": True}

    result = await handler(_request(b"[]"))

    assert result.status_code == 422
    assert result.body == b'{"ok":false,"detail":"Request body must be a JSON object"}'


@pytest.mark.asyncio
async def test_requires_signed_write_returns_retryable_503_for_revocation_refresh_unavailable(monkeypatch):
    mesh_signed_events._reset_revocation_ttl_cache()
    try:
        monkeypatch.setattr(
            mesh_signed_events,
            "verify_signed_write",
            lambda **_kwargs: (False, "Signed event integrity preflight unavailable"),
        )
        with mesh_signed_events._REVOCATION_TTL_LOCK:
            mesh_signed_events._REVOCATION_REFRESH_STATE["last_failure_at"] = time.time()

        @mesh_signed_events.requires_signed_write(kind=mesh_signed_events.SignedWriteKind.MESH_SEND)
        async def handler(request: Request):
            return {"ok": True}

        result = await handler(_request(json.dumps(_mesh_send_body()).encode("utf-8")))

        assert result.status_code == 503
        assert result.headers["Retry-After"] == "5"
        assert json.loads(result.body) == {
            "ok": False,
            "detail": "Signed event integrity preflight unavailable",
            "retryable": True,
            "error_code": "revocation_refresh_unavailable",
            "retry_after_s": 5,
        }
    finally:
        mesh_signed_events._reset_revocation_ttl_cache()
