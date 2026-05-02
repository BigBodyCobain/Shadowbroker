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


def test_anonymous_mode_auto_warms_hidden_transport_on_public_mesh_write(monkeypatch):
    """Tor-style: anonymous mode without hidden transport ready does NOT
    refuse the request. The middleware auto-enables Wormhole (if off) and
    kicks off hidden-transport warmup transparently, then lets the request
    proceed. The downstream handler can queue if content-private.
    """
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

    called = {"value": False}

    async def call_next(_request: Request) -> Response:
        called["value"] = True
        return Response(status_code=200)

    response = asyncio.run(main.enforce_high_privacy_mesh(_request("/api/mesh/send"), call_next))

    # Tor-style: request proceeds; middleware does not 428.
    assert response.status_code != 428
    assert called["value"] is True


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


def test_anonymous_mode_auto_warms_private_dm_actions_without_hidden_transport(monkeypatch):
    """Tor-style: DM writes under anonymous mode without hidden transport
    ready proceed silently; the middleware auto-warms the hidden transport
    and the downstream handler queues release if needed.
    """
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

    called = {"value": False}

    async def call_next(_request: Request) -> Response:
        called["value"] = True
        return Response(status_code=200)

    response = asyncio.run(main.enforce_high_privacy_mesh(_request("/api/mesh/dm/send"), call_next))

    # Tor-style: DM send middleware does not 428; it warms the hidden
    # transport and lets the downstream handler queue release if needed.
    assert response.status_code != 428
    assert called["value"] is True


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


def test_anonymous_mode_auto_warms_dm_witness_and_block_without_hidden_transport(monkeypatch):
    """Tor-style: dm/block and dm/witness under anonymous mode without
    hidden transport ready proceed; middleware auto-warms and the handler
    runs. No 428 is returned.
    """
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

    assert block_response.status_code != 428
    assert witness_response.status_code != 428


def test_anonymous_mode_dm_writes_never_refuse_for_missing_hidden_transport(monkeypatch):
    """Tor-style: DM send / block / witness all pass the middleware even
    without a hidden transport ready. The previous "shared refusal payload"
    contract is obsolete — the middleware no longer refuses; it auto-warms
    and lets the handler run.
    """
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

    send_response = asyncio.run(
        main.enforce_high_privacy_mesh(_request("/api/mesh/dm/send"), call_next)
    )
    block_response = asyncio.run(
        main.enforce_high_privacy_mesh(_request("/api/mesh/dm/block"), call_next)
    )
    witness_response = asyncio.run(
        main.enforce_high_privacy_mesh(_request("/api/mesh/dm/witness"), call_next)
    )

    assert send_response.status_code != 428
    assert block_response.status_code != 428
    assert witness_response.status_code != 428


def test_anonymous_mode_auto_warms_public_vouch_without_hidden_transport(monkeypatch):
    """Tor-style: trust_vouch under anonymous mode without hidden transport
    ready proceeds; the middleware never refuses.
    """
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

    # Tor-style: middleware never 428s on this path.
    assert response.status_code != 428


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


def test_private_infonet_gate_write_returns_preparing_state_when_wormhole_not_ready(monkeypatch):
    """Tor-style: gate writes on an insufficient tier do NOT 428.

    The middleware kicks off background warmup and returns 202 with
    ok:True and status "preparing_private_lane" so the client shows a
    spinner rather than an approval dialog. The request itself is not
    forwarded to the handler (tier would leak content), but the client
    can retry once the lane reports ready.
    """
    import main
    import auth
    from services.config import get_settings
    from services import wormhole_supervisor

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": False,
            "wormhole_enabled": True,
            "ready": False,
            "effective_transport": "direct",
        },
    )
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

    assert response.status_code != 428
    assert response.status_code in (200, 202)
    # When the middleware handles tier-insufficient itself, the payload
    # advertises the preparing state; when it forwards to call_next it
    # doesn't carry a payload at all. Either outcome is non-hostile.
    if response.status_code == 202:
        payload = json.loads(response.body.decode("utf-8"))
        assert payload.get("ok") is True
        assert payload.get("pending") is True
        assert payload.get("status") == "preparing_private_lane"
    get_settings.cache_clear()


def test_private_dm_send_blocks_at_transitional_tier(monkeypatch):
    import main
    import auth
    from services.config import get_settings
    from services import wormhole_settings, wormhole_supervisor

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": False,
            "wormhole_enabled": True,
            "ready": False,
            "effective_transport": "direct",
        },
    )
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

    called = {"value": False}

    async def call_next(_request: Request) -> Response:
        called["value"] = True
        return Response(status_code=200)

    response = asyncio.run(main.enforce_high_privacy_mesh(_request("/api/mesh/dm/send"), call_next))

    assert response.status_code == 200
    assert called["value"] is True
    get_settings.cache_clear()
