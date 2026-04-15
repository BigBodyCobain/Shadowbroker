import asyncio
import json

from starlette.requests import Request
from httpx import ASGITransport, AsyncClient


def _json_request(path: str, body: dict) -> Request:
    raw = json.dumps(body).encode("utf-8")
    sent = {"value": False}

    async def receive():
        if sent["value"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["value"] = True
        return {"type": "http.request", "body": raw, "more_body": False}

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


def test_fixed_launch_gate_catalog_contains_private_rooms():
    from services.mesh.mesh_reputation import gate_manager

    gate_ids = [gate["gate_id"] for gate in gate_manager.list_gates()]

    assert "infonet" in gate_ids
    assert "finance" in gate_ids
    assert "prediction-markets" in gate_ids
    assert "cryptography" in gate_ids
    assert "opsec-lab" in gate_ids
    assert "public-square" not in gate_ids


def test_fixed_launch_gate_catalog_exposes_descriptions_and_welcome_text():
    from services.mesh.mesh_reputation import gate_manager

    finance = next(g for g in gate_manager.list_gates() if g["gate_id"] == "finance")

    assert finance["fixed"] is True
    assert "Macro" in finance["description"]
    assert "WELCOME TO FINANCE" in finance["welcome"]


def test_gate_create_endpoint_is_disabled_for_fixed_launch_catalog():
    import main

    response = asyncio.run(
        main.gate_create(
            _json_request(
                "/api/mesh/gate/create",
                {
                    "creator_id": "!sb_test",
                    "gate_id": "new-gate",
                    "display_name": "New Gate",
                    "rules": {"min_overall_rep": 0},
                },
            )
        )
    )

    assert response["ok"] is False
    assert "fixed private launch catalog" in response["detail"]


def test_infonet_messages_returns_seed_notice_for_empty_fixed_gate(monkeypatch):
    import main
    from services.mesh import mesh_hashchain

    monkeypatch.setattr(mesh_hashchain.infonet, "get_messages", lambda **kwargs: [])
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))

    response = asyncio.run(
        main.infonet_messages(
            Request(
                {
                    "type": "http",
                    "headers": [(b"x-admin-key", b"test-admin")],
                    "client": ("test", 12345),
                    "method": "GET",
                    "path": "/api/mesh/infonet/messages",
                }
            ),
            gate="finance",
            limit=20,
            offset=0,
        )
    )

    assert response["count"] == 1
    assert response["messages"][0]["system_seed"] is True
    assert response["messages"][0]["gate"] == "finance"
    assert "WELCOME TO FINANCE" in response["messages"][0]["message"]


def test_gate_scoped_vote_rejects_unknown_gate(monkeypatch):
    import main
    from services import wormhole_supervisor

    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True},
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/vote",
                json={
                    "voter_id": "!sb_voter",
                    "target_id": "!sb_target",
                    "vote": 1,
                    "gate": "nonexistent-gate",
                    "voter_pubkey": "pub",
                    "public_key_algo": "Ed25519",
                    "voter_sig": "sig",
                    "sequence": 1,
                    "protocol_version": "1",
                },
            )
            return response.json()

    result = asyncio.run(_run())

    assert result["ok"] is False
    assert "does not exist" in result["detail"]


def test_gate_scoped_vote_requires_voter_gate_access(monkeypatch):
    import main
    from services import wormhole_supervisor
    from services.mesh.mesh_reputation import gate_manager

    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True},
    )
    monkeypatch.setattr(
        gate_manager,
        "can_enter",
        lambda voter_id, gate_id: (False, "Need 10 overall rep (you have 0)"),
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/vote",
                json={
                    "voter_id": "!sb_voter",
                    "target_id": "!sb_target",
                    "vote": -1,
                    "gate": "finance",
                    "voter_pubkey": "pub",
                    "public_key_algo": "Ed25519",
                    "voter_sig": "sig",
                    "sequence": 1,
                    "protocol_version": "1",
                },
            )
            return response.json()

    result = asyncio.run(_run())

    assert result["ok"] is False
    assert "Gate vote denied" in result["detail"]
