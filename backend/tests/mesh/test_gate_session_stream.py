import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request


def _make_stream_request(disconnect_after: int = 1) -> Request:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/mesh/infonet/session-stream",
            "raw_path": b"/api/mesh/infonet/session-stream",
            "query_string": b"",
            "headers": [],
            "client": ("test", 12345),
            "server": ("test", 80),
        }
    )
    checks = {"count": 0}

    async def _is_disconnected():
        checks["count"] += 1
        return checks["count"] >= max(1, int(disconnect_after))

    request.is_disconnected = _is_disconnected  # type: ignore[method-assign]
    return request


async def _collect_stream_chunks(iterator, limit: int) -> str:
    chunks: list[str] = []
    async for chunk in iterator:
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
        chunks.append(text)
        if len(chunks) >= limit:
            break
    return "".join(chunks)


def test_gate_session_stream_disabled_by_default():
    from routers import mesh_public

    async def _run():
        response = await mesh_public.infonet_session_stream(_make_stream_request(), gates="")
        return response.status_code, json.loads(response.body)

    status_code, payload = asyncio.run(_run())

    assert status_code == 404
    assert payload == {"ok": False, "detail": "gate_session_stream_disabled"}


def test_gate_session_stream_emits_hello_and_heartbeat(monkeypatch):
    from routers import mesh_public
    from services.mesh import mesh_hashchain

    monkeypatch.setattr(
        mesh_public,
        "get_settings",
        lambda: SimpleNamespace(
            MESH_GATE_SESSION_STREAM_ENABLED=True,
            MESH_GATE_SESSION_STREAM_HEARTBEAT_S=1,
            MESH_GATE_SESSION_STREAM_BATCH_MS=1500,
            MESH_GATE_SESSION_STREAM_MAX_GATES=4,
        ),
    )
    state = {"calls": 0}

    def _wait_for_any_gate_change(_gate_cursors, _timeout_s):
      state["calls"] += 1
      if state["calls"] == 1:
          return {"alpha": 2}
      return {}

    monkeypatch.setattr(mesh_hashchain.gate_store, "gate_cursor", lambda gate_id: 1 if gate_id == "alpha" else 0)
    monkeypatch.setattr(mesh_hashchain.gate_store, "wait_for_any_gate_change", _wait_for_any_gate_change)
    monkeypatch.setattr(
        mesh_public,
        "_sign_gate_access_proof",
        lambda gate_id: {
            "ok": True,
            "gate_id": gate_id,
            "node_id": f"!node_{gate_id}",
            "ts": 1712360000,
            "proof": f"proof-{gate_id}",
        },
    )
    monkeypatch.setattr(
        mesh_public,
        "_build_gate_session_stream_gate_key_status",
        lambda gate_id: {
            "ok": True,
            "gate_id": gate_id,
            "current_epoch": 7 if gate_id == "alpha" else 3,
            "has_local_access": gate_id == "alpha",
            "identity_scope": "anonymous",
            "detail": "gate access ready" if gate_id == "alpha" else "syncing",
        },
    )

    async def _run():
        request = _make_stream_request(disconnect_after=3)
        response = await mesh_public.infonet_session_stream(
            request,
            gates="Alpha,beta,alpha",
        )
        raw_stream = await _collect_stream_chunks(response.body_iterator, limit=2)
        return response.status_code, dict(response.headers), raw_stream

    status_code, headers, raw_stream = asyncio.run(_run())

    assert status_code == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert "event: hello" in raw_stream
    assert "event: gate_update" in raw_stream

    hello_block = raw_stream.split("\n\n", 1)[0]
    hello_payload = json.loads(hello_block.split("data: ", 1)[1])
    assert hello_payload["mode"] == "skeleton"
    assert hello_payload["transport"] == "sse"
    assert hello_payload["subscriptions"] == ["alpha", "beta"]
    assert hello_payload["cursors"] == {"alpha": 1, "beta": 0}
    assert hello_payload["gate_access"] == {
        "alpha": {
            "node_id": "!node_alpha",
            "ts": "1712360000",
            "proof": "proof-alpha",
        },
        "beta": {
            "node_id": "!node_beta",
            "ts": "1712360000",
            "proof": "proof-beta",
        },
    }
    assert hello_payload["gate_key_status"] == {
        "alpha": {
            "ok": True,
            "gate_id": "alpha",
            "current_epoch": 7,
            "has_local_access": True,
            "identity_scope": "anonymous",
            "detail": "gate access ready",
        },
        "beta": {
            "ok": True,
            "gate_id": "beta",
            "current_epoch": 3,
            "has_local_access": False,
            "identity_scope": "anonymous",
            "detail": "syncing",
        },
    }
    assert hello_payload["heartbeat_s"] == 1
    assert hello_payload["batch_ms"] == 1500

    gate_update_block = raw_stream.split("\n\n")[1]
    gate_update_payload = json.loads(gate_update_block.split("data: ", 1)[1])
    assert gate_update_payload["updates"] == [{"gate_id": "alpha", "cursor": 2}]
