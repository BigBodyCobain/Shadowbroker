"""Small route-level smoke lane for private/runtime-critical flows.

This file is intentionally compact. It exercises the actual ASGI app for:
- wormhole join
- gate open/send on the encrypted path
- DM send
- public Meshtastic send

The goal is to catch route wiring and integration regressions that deep
targeted crypto tests can miss.
"""

import asyncio
import json
import time
from collections import deque
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient
from services.mesh.mesh_protocol import build_signed_context


class _TestGateManager:
    _SECRET = "test-gate-secret-for-envelope-encryption"

    def get_gate_secret(self, gate_id: str) -> str:
        return self._SECRET

    def can_enter(self, sender_id: str, gate_id: str):
        return True, "ok"

    def record_message(self, gate_id: str):
        pass

    def get_gate(self, gate_id: str):
        return {"gate_id": gate_id, "welcome": "", "fixed": False}


def _fresh_gate_state(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import mesh_gate_mls, mesh_hashchain, mesh_reputation, mesh_secure_storage, mesh_wormhole_persona

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_gate_mls, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_gate_mls, "STATE_FILE", tmp_path / "wormhole_gate_mls.json")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setattr(mesh_reputation, "gate_manager", _TestGateManager(), raising=False)
    monkeypatch.setattr(
        mesh_hashchain,
        "gate_store",
        mesh_hashchain.GateMessageStore(data_dir=str(tmp_path / "gate_messages")),
    )
    mesh_gate_mls.reset_gate_mls_state()
    return mesh_gate_mls, mesh_wormhole_persona


REQUEST_CLAIM = [{"type": "requests", "token": "request-claim-token"}]
_KNOWN_TOKEN_HASH = "a1b2c3d4e5f6789012345678abcdef0123456789abcdef0123456789abcdef01"


def _fake_consume_token(*, sender_token, recipient_id, delivery_class, recipient_token=""):
    return {
        "ok": True,
        "sender_token_hash": _KNOWN_TOKEN_HASH,
        "sender_id": "alice",
        "public_key": "cHVi",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
        "recipient_id": recipient_id or "bob",
        "delivery_class": delivery_class,
        "issued_at": int(time.time()) - 10,
        "expires_at": int(time.time()) + 290,
    }


def _fresh_dm_route_env(tmp_path, monkeypatch):
    import main
    from services import wormhole_supervisor
    from services.config import get_settings
    from services.mesh import (
        mesh_crypto,
        mesh_dm_relay,
        mesh_hashchain,
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_sender_token,
    )

    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    get_settings.cache_clear()
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)

    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    mesh_wormhole_contacts.observe_remote_prekey_identity("bob", fingerprint="aa" * 32)
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "_derive_expected_contact_sas_phrase",
        lambda *_args, **_kwargs: {"ok": True, "phrase": "able acid", "peer_ref": "bob", "words": 2},
    )
    mesh_wormhole_contacts.confirm_sas_verification("bob", "able acid")

    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(main, "_current_private_lane_tier", lambda *_args, **_kwargs: "private_strong")
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(mesh_hashchain.infonet, "validate_and_set_sequence", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(mesh_crypto, "verify_node_binding", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(main, "consume_wormhole_dm_sender_token", _fake_consume_token)
    monkeypatch.setattr(mesh_wormhole_sender_token, "consume_wormhole_dm_sender_token", _fake_consume_token)
    return relay


class _DummyBreaker:
    def check_and_record(self, _priority):
        return True, "ok"


class _FakeMeshtasticTransport:
    NAME = "meshtastic"

    def __init__(self, can_reach: bool = True, send_ok: bool = True):
        self._can_reach = can_reach
        self._send_ok = send_ok
        self.sent = []

    def can_reach(self, _envelope):
        return self._can_reach

    def send(self, envelope, _credentials):
        from services.mesh.mesh_router import TransportResult

        self.sent.append(envelope)
        return TransportResult(self._send_ok, self.NAME, "sent")


class _FakeMeshRouter:
    def __init__(self, meshtastic):
        self.meshtastic = meshtastic
        self.breakers = {"meshtastic": _DummyBreaker()}
        self.route_called = False

    def route(self, _envelope, _credentials):
        self.route_called = True
        return []


def _meshtastic_send_body(**overrides):
    body = {
        "destination": "!a0cc7a80",
        "message": "hello mesh",
        "sender_id": "!sb_sender",
        "node_id": "!sb_sender",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "signature": "sig",
        "sequence": 1,
        "protocol_version": "1",
        "channel": "LongFast",
        "priority": "normal",
        "ephemeral": False,
        "transport_lock": "meshtastic",
        "credentials": {"mesh_region": "US"},
    }
    body.update(overrides)
    return body


def test_runtime_smoke_wormhole_join_route(monkeypatch):
    import main
    from routers import wormhole as wormhole_router
    from services import node_settings

    bootstrap_calls = []
    node_setting_calls = []
    refresh_calls = []

    monkeypatch.setattr(
        wormhole_router,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "transport": "direct",
            "socks_proxy": "",
            "socks_dns": True,
            "anonymous_mode": False,
        },
    )
    monkeypatch.setattr(wormhole_router, "write_wormhole_settings", lambda **kwargs: dict(kwargs))
    monkeypatch.setattr(wormhole_router, "bootstrap_wormhole_identity", lambda: bootstrap_calls.append("identity"))
    monkeypatch.setattr(
        wormhole_router,
        "bootstrap_wormhole_persona_state",
        lambda: bootstrap_calls.append("persona"),
    )
    monkeypatch.setattr(
        wormhole_router,
        "connect_wormhole",
        lambda **kwargs: {"ok": True, "ready": True, "reason": kwargs.get("reason", "")},
    )
    monkeypatch.setattr(wormhole_router, "get_transport_identity", lambda: {"node_id": "!sb_test_join"})
    monkeypatch.setattr(node_settings, "write_node_settings", lambda **kwargs: node_setting_calls.append(kwargs))
    monkeypatch.setattr(main, "_refresh_node_peer_store", lambda **kwargs: refresh_calls.append(kwargs) or {"ok": True})

    async def _run():
        async with AsyncClient(
            transport=ASGITransport(app=main.app, client=("127.0.0.1", 54321)),
            base_url="http://test",
        ) as ac:
            response = await ac.post("/api/wormhole/join")
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 200
    assert result["ok"] is True
    assert result["identity"] == {"node_id": "!sb_test_join"}
    assert bootstrap_calls == ["identity", "persona"]
    assert node_setting_calls == [{"enabled": True}]
    assert refresh_calls == [{}]


def test_runtime_smoke_gate_open_and_send_encrypted(tmp_path, monkeypatch):
    import auth
    import main
    from routers import mesh_public

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "smoke-gate"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona(gate_id, label="scribe")
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "smoke gate payload")

    monkeypatch.setattr(main, "_verify_gate_access", lambda *_args, **_kwargs: "member")
    monkeypatch.setattr(mesh_public, "_verify_gate_access", lambda *_args, **_kwargs: "member")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            proof_response = await ac.post(
                "/api/wormhole/gate/proof",
                json={"gate_id": gate_id},
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            post_response = await ac.post(
                "/api/wormhole/gate/message/post-encrypted",
                json={
                    "gate_id": gate_id,
                    "sender_id": composed["sender_id"],
                    "public_key": composed["public_key"],
                    "public_key_algo": composed["public_key_algo"],
                    "signature": composed["signature"],
                    "sequence": composed["sequence"],
                    "protocol_version": composed["protocol_version"],
                    "epoch": composed["epoch"],
                    "ciphertext": composed["ciphertext"],
                    "nonce": composed["nonce"],
                    "sender_ref": composed["sender_ref"],
                    "format": composed["format"],
                    "gate_envelope": composed.get("gate_envelope", ""),
                    "envelope_hash": composed.get("envelope_hash", ""),
                    "compat_reply_to": False,
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            wait_response = await ac.get(
                f"/api/mesh/infonet/messages/wait?gate={gate_id}&after=0&limit=10&timeout_ms=1000",
            )
            return proof_response.json(), post_response.json(), wait_response.status_code, wait_response.json()

    try:
        proof_result, post_result, wait_status, wait_result = asyncio.run(_run())
    finally:
        gate_mls_mod.reset_gate_mls_state()

    assert proof_result["ok"] is True
    assert proof_result["gate_id"] == gate_id
    assert post_result["ok"] is True
    assert wait_status == 200
    assert wait_result["gate"] == gate_id
    assert wait_result["changed"] is True
    assert wait_result["count"] == 1
    assert wait_result["messages"][0]["event_id"] == post_result["event_id"]


def test_runtime_smoke_dm_send_route(tmp_path, monkeypatch):
    import main

    relay = _fresh_dm_route_env(tmp_path, monkeypatch)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/dm/send",
                json=(lambda body: body | {
                    "signed_context": build_signed_context(
                        event_type="dm_message",
                        kind="dm_send",
                        endpoint="/api/mesh/dm/send",
                        lane_floor="private_strong",
                        sequence_domain="dm_send",
                        node_id="alice",
                        sequence=body["sequence"],
                        payload={
                            "recipient_id": body["recipient_id"],
                            "delivery_class": body["delivery_class"],
                            "recipient_token": body["recipient_token"],
                            "ciphertext": body["ciphertext"],
                            "format": "mls1",
                            "msg_id": body["msg_id"],
                            "timestamp": body["timestamp"],
                            "sender_seal": body["sender_seal"],
                            "transport_lock": body["transport_lock"],
                        },
                        recipient_id=body["recipient_id"],
                    )
                })(
                    {
                        "sender_id": "",
                        "sender_token": "opaque-sender-token",
                        "recipient_id": "bob",
                        "delivery_class": "request",
                        "recipient_token": "",
                        "ciphertext": "x3dh1:sealed-payload",
                        "msg_id": "runtime-smoke-dm-1",
                        "timestamp": int(time.time()),
                        "public_key": "cHVi",
                        "public_key_algo": "Ed25519",
                        "signature": "sig",
                        "sequence": 1,
                        "protocol_version": "infonet/2",
                        "transport_lock": "private_strong",
                        "sender_seal": "v3:test-seal-data",
                    }
                ),
            )
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 200
    assert result["ok"] is True
    assert result["msg_id"] == "runtime-smoke-dm-1"
    assert result["queued"] is True
    assert result["delivery"]["local_state"] == "sealed_local"


def test_runtime_smoke_public_meshtastic_send_route(monkeypatch):
    import main
    from services.mesh import mesh_router as mesh_router_mod
    from services.sigint_bridge import sigint_grid

    fake_meshtastic = _FakeMeshtasticTransport(can_reach=True, send_ok=True)
    fake_router = _FakeMeshRouter(fake_meshtastic)
    fake_bridge = SimpleNamespace(messages=deque(maxlen=10))

    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(main, "_check_throttle", lambda *_args: (True, "ok"))
    monkeypatch.setattr(mesh_router_mod, "mesh_router", fake_router)
    monkeypatch.setattr(sigint_grid, "mesh", fake_bridge)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post("/api/mesh/send", json=_meshtastic_send_body())
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 200
    assert result["ok"] is True
    assert result["routed_via"] == "meshtastic"
    assert fake_router.route_called is False
    assert len(fake_meshtastic.sent) == 1
