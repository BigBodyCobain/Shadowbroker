import asyncio
import json

from starlette.requests import Request
from starlette.responses import Response


def _request(path: str, method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "headers": [],
            "client": ("test", 12345),
            "method": method,
            "path": path,
        }
    )


def test_anonymous_mode_blocks_public_mesh_write_without_hidden_transport(monkeypatch):
    import main
    from services import wormhole_settings, wormhole_status

    monkeypatch.setattr(
        wormhole_settings,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "privacy_profile": "default",
            "transport": "direct",
            "anonymous_mode": True,
        },
    )
    monkeypatch.setattr(
        wormhole_status,
        "read_wormhole_status",
        lambda: {
            "running": True,
            "ready": True,
            "transport_active": "direct",
        },
    )

    async def call_next(_request: Request) -> Response:
        return Response(status_code=200)

    response = asyncio.run(main.enforce_high_privacy_mesh(_request("/api/mesh/send"), call_next))
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 428
    assert "hidden Wormhole transport" in payload["detail"]


def test_anonymous_mode_allows_public_mesh_write_when_hidden_transport_ready(monkeypatch):
    import main
    from services import wormhole_settings, wormhole_status

    monkeypatch.setattr(
        wormhole_settings,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "privacy_profile": "default",
            "transport": "tor",
            "anonymous_mode": True,
        },
    )
    monkeypatch.setattr(
        wormhole_status,
        "read_wormhole_status",
        lambda: {
            "running": True,
            "ready": True,
            "transport_active": "tor",
        },
    )
    called = {"value": False}

    async def call_next(_request: Request) -> Response:
        called["value"] = True
        return Response(status_code=200)

    response = asyncio.run(main.enforce_high_privacy_mesh(_request("/api/mesh/send"), call_next))

    assert response.status_code == 200
    assert called["value"] is True


def test_anonymous_mode_treats_tor_arti_as_hidden_transport(monkeypatch):
    import main
    from services import wormhole_settings, wormhole_status

    monkeypatch.setattr(
        wormhole_settings,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "privacy_profile": "default",
            "transport": "tor_arti",
            "anonymous_mode": True,
        },
    )
    monkeypatch.setattr(
        wormhole_status,
        "read_wormhole_status",
        lambda: {
            "running": True,
            "ready": True,
            "transport_active": "tor_arti",
        },
    )
    called = {"value": False}

    async def call_next(_request: Request) -> Response:
        called["value"] = True
        return Response(status_code=200)

    response = asyncio.run(main.enforce_high_privacy_mesh(_request("/api/mesh/send"), call_next))

    assert response.status_code == 200
    assert called["value"] is True


def test_anonymous_mode_does_not_block_read_only_mesh_requests(monkeypatch):
    import main
    from services import wormhole_settings, wormhole_status

    monkeypatch.setattr(
        wormhole_settings,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "privacy_profile": "default",
            "transport": "direct",
            "anonymous_mode": True,
        },
    )
    monkeypatch.setattr(
        wormhole_status,
        "read_wormhole_status",
        lambda: {
            "running": False,
            "ready": False,
            "transport_active": "direct",
        },
    )
    called = {"value": False}

    async def call_next(_request: Request) -> Response:
        called["value"] = True
        return Response(status_code=200)

    response = asyncio.run(
        main.enforce_high_privacy_mesh(_request("/api/mesh/status", method="GET"), call_next)
    )

    assert response.status_code == 200
    assert called["value"] is True


def test_anonymous_mode_blocks_private_dm_actions_without_hidden_transport(monkeypatch):
    import main
    from services import wormhole_settings, wormhole_status, wormhole_supervisor

    monkeypatch.setattr(
        wormhole_settings,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "privacy_profile": "default",
            "transport": "direct",
            "anonymous_mode": True,
        },
    )
    monkeypatch.setattr(
        wormhole_status,
        "read_wormhole_status",
        lambda: {
            "running": True,
            "ready": True,
            "transport_active": "direct",
        },
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )

    async def call_next(_request: Request) -> Response:
        return Response(status_code=200)

    response = asyncio.run(main.enforce_high_privacy_mesh(_request("/api/mesh/dm/send"), call_next))
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 428
    assert "private DM activity" in payload["detail"]


def test_anonymous_mode_allows_private_dm_actions_when_hidden_transport_ready(monkeypatch):
    import main
    from services import wormhole_settings, wormhole_status, wormhole_supervisor

    monkeypatch.setattr(
        wormhole_settings,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "privacy_profile": "default",
            "transport": "tor",
            "anonymous_mode": True,
        },
    )
    monkeypatch.setattr(
        wormhole_status,
        "read_wormhole_status",
        lambda: {
            "running": True,
            "ready": True,
            "transport_active": "tor",
        },
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    called = {"value": False}

    async def call_next(_request: Request) -> Response:
        called["value"] = True
        return Response(status_code=200)

    response = asyncio.run(main.enforce_high_privacy_mesh(_request("/api/mesh/dm/poll"), call_next))

    assert response.status_code == 200
    assert called["value"] is True


def test_anonymous_mode_blocks_dm_witness_and_block_without_hidden_transport(monkeypatch):
    import main
    from services import wormhole_settings, wormhole_status, wormhole_supervisor

    monkeypatch.setattr(
        wormhole_settings,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "privacy_profile": "default",
            "transport": "direct",
            "anonymous_mode": True,
        },
    )
    monkeypatch.setattr(
        wormhole_status,
        "read_wormhole_status",
        lambda: {
            "running": True,
            "ready": True,
            "transport_active": "direct",
        },
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )

    async def call_next(_request: Request) -> Response:
        return Response(status_code=200)

    block_response = asyncio.run(
        main.enforce_high_privacy_mesh(_request("/api/mesh/dm/block"), call_next)
    )
    witness_response = asyncio.run(
        main.enforce_high_privacy_mesh(_request("/api/mesh/dm/witness"), call_next)
    )

    assert block_response.status_code == 428
    assert witness_response.status_code == 428


def test_anonymous_mode_blocks_public_vouch_without_hidden_transport(monkeypatch):
    import main
    from services import wormhole_settings, wormhole_status, wormhole_supervisor

    monkeypatch.setattr(
        wormhole_settings,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "privacy_profile": "default",
            "transport": "direct",
            "anonymous_mode": True,
        },
    )
    monkeypatch.setattr(
        wormhole_status,
        "read_wormhole_status",
        lambda: {
            "running": True,
            "ready": True,
            "transport_active": "direct",
        },
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": False,
        },
    )

    async def call_next(_request: Request) -> Response:
        return Response(status_code=200)

    response = asyncio.run(
        main.enforce_high_privacy_mesh(_request("/api/mesh/trust/vouch"), call_next)
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 428
    assert "hidden Wormhole transport" in payload["detail"]


def test_private_infonet_gate_write_requires_wormhole_ready_but_not_rns(monkeypatch):
    import main
    from services import wormhole_supervisor

    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": False,
        },
    )

    async def call_next(_request: Request) -> Response:
        return Response(status_code=200)

    response = asyncio.run(
        main.enforce_high_privacy_mesh(_request("/api/mesh/gate/test-gate/message"), call_next)
    )

    assert response.status_code == 200


def test_private_infonet_gate_write_blocks_when_wormhole_not_ready(monkeypatch):
    import main
    from services import wormhole_supervisor

    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": False,
            "rns_ready": True,
        },
    )

    async def call_next(_request: Request) -> Response:
        return Response(status_code=200)

    response = asyncio.run(
        main.enforce_high_privacy_mesh(_request("/api/mesh/gate/test-gate/message"), call_next)
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 428
    assert payload == {
        "ok": False,
        "detail": "transport tier insufficient",
        "required": "private_transitional",
        "current": "public_degraded",
    }


def test_private_dm_send_blocks_at_transitional_tier(monkeypatch):
    import main
    from services import wormhole_settings, wormhole_supervisor

    monkeypatch.setattr(
        wormhole_settings,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "privacy_profile": "default",
            "transport": "direct",
            "anonymous_mode": False,
        },
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": False,
        },
    )

    async def call_next(_request: Request) -> Response:
        return Response(status_code=200)

    response = asyncio.run(main.enforce_high_privacy_mesh(_request("/api/mesh/dm/send"), call_next))
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 428
    assert payload == {
        "ok": False,
        "detail": "transport tier insufficient",
        "required": "private_strong",
        "current": "private_transitional",
    }
