import asyncio
import base64
import copy
import json
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from httpx import ASGITransport, AsyncClient
from services.mesh.mesh_protocol import build_signed_context
from .review_surface_contracts import (
    EXPLICIT_REVIEW_EXPORT_CONTRACT,
    REVIEW_CONSISTENCY_CONTRACT,
    REVIEW_MANIFEST_CONTRACT,
    assert_surface_contract,
)


def _gate_signed_context_body(
    *,
    path: str,
    sender_id: str,
    sequence: int,
    ciphertext: str,
    nonce: str,
    sender_ref: str,
    transport_lock: str = "private_strong",
    epoch: int = 1,
    fmt: str = "mls1",
) -> dict:
    payload = {
        "gate": "infonet",
        "ciphertext": ciphertext,
        "nonce": nonce,
        "sender_ref": sender_ref,
        "format": fmt,
        "epoch": epoch,
        "transport_lock": transport_lock,
    }
    return {
        "sender_id": sender_id,
        "epoch": epoch,
        "ciphertext": ciphertext,
        "nonce": nonce,
        "sender_ref": sender_ref,
        "format": fmt,
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "signature": "sig",
        "sequence": sequence,
        "protocol_version": "1",
        "transport_lock": transport_lock,
        "signed_context": build_signed_context(
            event_type="gate_message",
            kind="gate_message",
            endpoint=path,
            lane_floor="private_strong",
            sequence_domain="gate_message",
            node_id=sender_id,
            sequence=sequence,
            payload=payload,
            gate_id="infonet",
        ),
    }


class _DummyBreaker:
    def check_and_record(self, _priority):
        return True, "ok"


class _FakeMeshtasticTransport:
    NAME = "meshtastic"

    def __init__(self):
        self.sent = []

    def can_reach(self, _envelope):
        return True

    def send(self, envelope, _credentials):
        from services.mesh.mesh_router import TransportResult

        self.sent.append(envelope)
        return TransportResult(True, self.NAME, "sent")


class _FakeMeshRouter:
    def __init__(self):
        self.meshtastic = _FakeMeshtasticTransport()
        self.breakers = {"meshtastic": _DummyBreaker()}
        self.route_called = False

    def route(self, _envelope, _credentials):
        self.route_called = True
        return []


class _FakeReputationLedger:
    def __init__(self):
        self.registered = []
        self.votes = []
        self.reputation: dict[str, dict] = {}

    def register_node(self, *args):
        self.registered.append(args)

    def cast_vote(self, *args):
        self.votes.append(args)
        return True, "ok"

    def get_reputation(self, node_id):
        return self.reputation.get(node_id, {"overall": 0, "gates": {}, "upvotes": 0, "downvotes": 0})

    def get_reputation_log(self, node_id, detailed=False):
        rep = self.get_reputation(node_id)
        result = {"node_id": node_id, **rep}
        if detailed:
            result["recent_votes"] = []
        return result


class _FakeGateManager:
    def __init__(self):
        self.recorded = []
        self.enter_checks = []

    def can_enter(self, sender_id, gate_id):
        self.enter_checks.append((sender_id, gate_id))
        return True, "ok"

    def record_message(self, gate_id):
        self.recorded.append(gate_id)


def _patch_in_memory_private_delivery(monkeypatch):
    import main
    from services.mesh import (
        mesh_private_outbox,
        mesh_private_release_worker,
        mesh_private_transport_manager,
    )

    store = {}

    def _read_domain_json(_domain, _filename, default_factory, **_kwargs):
        payload = store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_domain_json(_domain, _filename, payload, **_kwargs):
        store["payload"] = copy.deepcopy(payload)

    monkeypatch.setattr(mesh_private_outbox, "read_sensitive_domain_json", _read_domain_json)
    monkeypatch.setattr(mesh_private_outbox, "write_sensitive_domain_json", _write_domain_json)
    mesh_private_release_worker.reset_private_release_worker_for_tests()
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_transport_manager.reset_private_transport_manager_for_tests()
    mesh_private_outbox.private_delivery_outbox._load()
    monkeypatch.setattr(
        mesh_private_transport_manager.private_transport_manager,
        "_kickoff_background_bootstrap",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(main, "_kickoff_dm_send_transport_upgrade", lambda: None)
    monkeypatch.setattr(main, "_kickoff_private_control_transport_upgrade", lambda: None)
    return store, mesh_private_outbox, mesh_private_release_worker


def test_recent_private_clearnet_fallback_warning_tracks_private_internet_route(monkeypatch):
    from collections import deque

    from services import wormhole_supervisor
    from services.mesh import mesh_router

    now = 1_700_000_000.0
    monkeypatch.setattr(
        mesh_router,
        "mesh_router",
        SimpleNamespace(
            message_log=deque(
                [
                    {
                        "trust_tier": "private_transitional",
                        "routed_via": "internet",
                        "route_reason": "Payload too large for radio or radio transports failed — internet relay",
                        "timestamp": now - 15,
                    }
                ],
                maxlen=500,
            )
        ),
    )

    warning = wormhole_supervisor._recent_private_clearnet_fallback_warning(now=now)

    assert warning["recent_private_clearnet_fallback"] is True
    assert warning["recent_private_clearnet_fallback_at"] == int(now - 15)
    assert "internet relay" in warning["recent_private_clearnet_fallback_reason"].lower()


def test_mesh_reputation_batch_returns_overall_scores(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_reputation as mesh_reputation_mod

    fake_ledger = _FakeReputationLedger()
    fake_ledger.reputation = {
        "!alpha": {"overall": 7, "gates": {}, "upvotes": 4, "downvotes": 1},
        "!bravo": {"overall": -2, "gates": {}, "upvotes": 1, "downvotes": 3},
    }
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/mesh/reputation/batch?node_id=!alpha&node_id=!bravo")
            return response.json()

    result = asyncio.run(_run())

    assert result == {"ok": True, "reputations": {"!alpha": 7, "!bravo": -2}}


def test_wormhole_gate_message_batch_decrypt_preserves_order(monkeypatch):
    import main
    import auth
    from routers import wormhole as wormhole_router
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    calls = []

    def fake_decrypt(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "gate_id": kwargs["gate_id"],
            "epoch": int(kwargs.get("epoch", 0) or 0) + 1,
            "plaintext": f"plain:{kwargs['ciphertext']}",
        }

    monkeypatch.setattr(main, "decrypt_gate_message_with_repair", fake_decrypt)
    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/messages/decrypt",
                json={
                    "messages": [
                        {
                            "gate_id": "ops",
                            "epoch": 2,
                            "ciphertext": "ct-1",
                            "nonce": "",
                            "sender_ref": "",
                            "recovery_envelope": True,
                        },
                        {
                            "gate_id": "ops",
                            "epoch": 3,
                            "ciphertext": "ct-2",
                            "nonce": "",
                            "sender_ref": "",
                            "recovery_envelope": True,
                        },
                    ]
                },
                headers={"X-Admin-Key": main._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {
        "ok": True,
        "results": [
            {"ok": True, "gate_id": "ops", "epoch": 3, "plaintext": "plain:ct-1"},
            {"ok": True, "gate_id": "ops", "epoch": 4, "plaintext": "plain:ct-2"},
        ],
    }
    assert [call["ciphertext"] for call in calls] == ["ct-1", "ct-2"]


def test_wormhole_gate_sign_encrypted_returns_recovery_envelope_for_post_storage(tmp_path, monkeypatch):
    import main
    import auth
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(main, "_is_debug_test_request", lambda _request: False)
    monkeypatch.setattr(
        main,
        "sign_gate_message_with_repair",
        lambda **_kwargs: {
            "ok": True,
            "gate_id": "ops",
            "identity_scope": "persona",
            "sender_id": "!sb_test",
            "public_key": "pk",
            "public_key_algo": "Ed25519",
            "protocol_version": "1",
            "sequence": 7,
            "ciphertext": "ct",
            "nonce": "native-sign-nonce",
            "sender_ref": "sr",
            "format": "mls1",
            "timestamp": 1.0,
            "signature": "sig",
            "gate_envelope": "recovery-envelope",
            "envelope_hash": "recovery-hash",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/message/sign-encrypted",
                json={
                    "gate_id": "ops",
                    "epoch": 1,
                    "ciphertext": "ct",
                    "nonce": "native-sign-nonce",
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result["ok"] is True, result
    assert result["gate_id"] == "ops"
    assert result["gate_envelope"] == "recovery-envelope"
    assert result["envelope_hash"] == "recovery-hash"


def test_wormhole_gate_message_decrypt_recovery_mode_accepts_explicit_recovery_material(monkeypatch):
    import main
    import auth
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_reputation

    class _EnvelopeGateManager:
        def get_gate_secret(self, gate_id: str) -> str:
            return "test-gate-secret-wormhole-binding"

        def ensure_gate_secret(self, gate_id: str) -> str:
            return "test-gate-secret-wormhole-binding"

        def get_envelope_policy(self, gate_id: str) -> str:
            return "envelope_recovery"

    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(mesh_reputation, "gate_manager", _EnvelopeGateManager(), raising=False)
    from services.mesh import mesh_gate_mls
    monkeypatch.setattr(mesh_gate_mls, "_resolve_gate_envelope_policy", lambda _gate_id: "envelope_recovery")

    from services.mesh.mesh_gate_mls import _gate_envelope_encrypt
    import hashlib

    gate_id = "__test_recovery_envelope_endpoint"
    gate_envelope = _gate_envelope_encrypt(gate_id, "recovery plaintext", message_nonce="nonce-1")
    envelope_hash = hashlib.sha256(gate_envelope.encode("ascii")).hexdigest()
    monkeypatch.setattr(
        main,
        "decrypt_gate_message_with_repair",
        lambda **_kwargs: {
            "ok": True,
            "gate_id": gate_id,
            "epoch": 1,
            "plaintext": "recovery plaintext",
            "identity_scope": "gate_envelope",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/message/decrypt",
                json={
                    "gate_id": gate_id,
                    "epoch": 1,
                    "ciphertext": "dummy-ct",
                    "nonce": "nonce-1",
                    "sender_ref": "sr",
                    "format": "mls1",
                    "gate_envelope": gate_envelope,
                    "envelope_hash": envelope_hash,
                    "recovery_envelope": True,
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {
        "ok": True,
        "gate_id": gate_id,
        "epoch": 1,
        "plaintext": "recovery plaintext",
        "identity_scope": "gate_envelope",
    }


class _GateRepairTestManager:
    _SECRET = "test-gate-secret-for-envelope-encryption"

    def get_gate_secret(self, gate_id: str) -> str:
        return self._SECRET

    def can_enter(self, sender_id: str, gate_id: str):
        return True, "ok"

    def record_message(self, gate_id: str):
        pass


def _fresh_gate_repair_test_state(tmp_path, monkeypatch):
    import auth
    from services import wormhole_supervisor
    from services.mesh import (
        mesh_gate_mls,
        mesh_gate_repair,
        mesh_reputation,
        mesh_secure_storage,
        mesh_wormhole_persona,
    )

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
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setattr(mesh_reputation, "gate_manager", _GateRepairTestManager(), raising=False)
    mesh_gate_repair.reset_gate_repair_manager_for_tests()
    mesh_gate_mls.reset_gate_mls_state()
    auth._admin_key = None
    return mesh_gate_mls, mesh_wormhole_persona


def _bootstrap_gate_repair_messages(tmp_path, monkeypatch, gate_id="ops"):
    gate_mls_mod, persona_mod = _fresh_gate_repair_test_state(tmp_path, monkeypatch)
    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona(gate_id, label="scribe")
    first = gate_mls_mod.compose_encrypted_gate_message(gate_id, "first recovery plaintext")
    second = gate_mls_mod.compose_encrypted_gate_message(gate_id, "second recovery plaintext")
    assert first["ok"] is True
    assert second["ok"] is True
    return gate_mls_mod, first, second


def test_wormhole_gate_message_decrypt_blocks_ordinary_non_recovery_requests(monkeypatch):
    import main
    import auth
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    called = []

    def fake_decrypt(**kwargs):
        called.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(main, "decrypt_gate_message_with_repair", fake_decrypt)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/message/decrypt",
                json={
                    "gate_id": "ops",
                    "epoch": 2,
                    "ciphertext": "ct-1",
                    "nonce": "",
                    "sender_ref": "",
                    "format": "mls1",
                    "recovery_envelope": False,
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {
        "ok": False,
        "detail": "gate_backend_decrypt_recovery_only",
        "gate_id": "ops",
        "compat_requested": False,
        "compat_effective": False,
    }
    assert called == []


def test_wormhole_gate_message_decrypt_recovery_mode_hits_repair_seam_on_stale_state(tmp_path, monkeypatch):
    import main
    import auth
    from httpx import ASGITransport, AsyncClient

    gate_mls_mod, composed, _second = _bootstrap_gate_repair_messages(tmp_path, monkeypatch)
    gate_key = gate_mls_mod._stable_gate_ref("ops")
    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)
    gate_mls_mod._write_gate_rust_state_snapshot(gate_key, None)
    calls = []

    def fake_decrypt(**kwargs):
        calls.append(kwargs)
        assert gate_mls_mod._read_gate_rust_state_snapshot(gate_key) is None
        return {
            "ok": True,
            "gate_id": kwargs["gate_id"],
            "epoch": int(kwargs.get("epoch", 0) or 0),
            "plaintext": "recovered through repair seam",
            "identity_scope": "persona",
        }

    monkeypatch.setattr(main, "decrypt_gate_message_with_repair", fake_decrypt)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/message/decrypt",
                json={
                    "gate_id": "ops",
                    "epoch": int(composed["epoch"]),
                    "ciphertext": str(composed["ciphertext"]),
                    "nonce": str(composed["nonce"]),
                    "sender_ref": str(composed["sender_ref"]),
                    "format": "mls1",
                    "recovery_envelope": True,
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {
        "ok": True,
        "gate_id": "ops",
        "epoch": int(composed["epoch"]),
        "plaintext": "recovered through repair seam",
        "identity_scope": "persona",
    }
    assert [call["ciphertext"] for call in calls] == [str(composed["ciphertext"])]


def test_wormhole_gate_message_batch_decrypt_blocks_ordinary_non_recovery_requests(monkeypatch):
    import main
    import auth
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    calls = []

    def fake_decrypt(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(main, "decrypt_gate_message_with_repair", fake_decrypt)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/messages/decrypt",
                json={
                    "messages": [
                        {
                            "gate_id": "ops",
                            "epoch": 2,
                            "ciphertext": "ct-1",
                            "nonce": "",
                            "sender_ref": "",
                            "format": "mls1",
                            "recovery_envelope": False,
                        },
                        {
                            "gate_id": "ops",
                            "epoch": 3,
                            "ciphertext": "ct-2",
                            "nonce": "",
                            "sender_ref": "",
                            "format": "mls1",
                            "recovery_envelope": False,
                        },
                    ]
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {
        "ok": True,
        "results": [
            {
                "ok": False,
                "detail": "gate_backend_decrypt_recovery_only",
                "gate_id": "ops",
                "compat_requested": False,
                "compat_effective": False,
            },
            {
                "ok": False,
                "detail": "gate_backend_decrypt_recovery_only",
                "gate_id": "ops",
                "compat_requested": False,
                "compat_effective": False,
            },
        ],
    }
    assert calls == []


def test_wormhole_gate_message_batch_decrypt_recovery_mode_hits_repair_seam_on_stale_state(tmp_path, monkeypatch):
    import main
    import auth
    from httpx import ASGITransport, AsyncClient

    gate_mls_mod, first, second = _bootstrap_gate_repair_messages(tmp_path, monkeypatch)
    gate_key = gate_mls_mod._stable_gate_ref("ops")
    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)
    gate_mls_mod._write_gate_rust_state_snapshot(gate_key, None)
    calls = []

    def fake_decrypt(**kwargs):
        calls.append(kwargs)
        assert gate_mls_mod._read_gate_rust_state_snapshot(gate_key) is None
        label = "first" if kwargs["ciphertext"] == str(first["ciphertext"]) else "second"
        return {
            "ok": True,
            "gate_id": kwargs["gate_id"],
            "epoch": int(kwargs.get("epoch", 0) or 0),
            "plaintext": f"{label} recovered through repair seam",
            "identity_scope": "persona",
        }

    monkeypatch.setattr(main, "decrypt_gate_message_with_repair", fake_decrypt)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/messages/decrypt",
                json={
                    "messages": [
                        {
                            "gate_id": "ops",
                            "epoch": int(first["epoch"]),
                            "ciphertext": str(first["ciphertext"]),
                            "nonce": str(first["nonce"]),
                            "sender_ref": str(first["sender_ref"]),
                            "format": "mls1",
                            "recovery_envelope": True,
                        },
                        {
                            "gate_id": "ops",
                            "epoch": int(second["epoch"]),
                            "ciphertext": str(second["ciphertext"]),
                            "nonce": str(second["nonce"]),
                            "sender_ref": str(second["sender_ref"]),
                            "format": "mls1",
                            "recovery_envelope": True,
                        },
                    ]
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {
        "ok": True,
        "results": [
            {
                "ok": True,
                "gate_id": "ops",
                "epoch": int(first["epoch"]),
                "plaintext": "first recovered through repair seam",
                "identity_scope": "persona",
            },
            {
                "ok": True,
                "gate_id": "ops",
                "epoch": int(second["epoch"]),
                "plaintext": "second recovered through repair seam",
                "identity_scope": "persona",
            },
        ],
    }
    assert [call["ciphertext"] for call in calls] == [
        str(first["ciphertext"]),
        str(second["ciphertext"]),
    ]


def _gate_proof_identity():
    from services.mesh.mesh_crypto import derive_node_id

    signing_key = ed25519.Ed25519PrivateKey.generate()
    private_raw = signing_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_raw = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_key = base64.b64encode(public_raw).decode("ascii")
    private_key = base64.b64encode(private_raw).decode("ascii")
    return {
        "node_id": derive_node_id(public_key),
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "private_key": private_key,
        "signing_key": signing_key,
    }


def _send_body(**overrides):
    body = {
        "destination": "!a0cc7a80",
        "message": "hello mesh",
        "sender_id": "!sb_sender",
        "node_id": "!sb_sender",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "signature": "sig",
        "sequence": 11,
        "protocol_version": "1",
        "channel": "LongFast",
        "priority": "normal",
        "ephemeral": False,
        "transport_lock": "meshtastic",
        "credentials": {"mesh_region": "US"},
    }
    body.update(overrides)
    return body


def test_preflight_integrity_rejects_replay(monkeypatch):
    import main
    from services.mesh import mesh_hashchain as mesh_hashchain_mod

    fake_infonet = SimpleNamespace(
        check_replay=lambda node_id, sequence: True,
        node_sequences={"!node": 9},
        public_key_bindings={},
        _revocation_status=lambda public_key: (False, None),
    )
    monkeypatch.setattr(mesh_hashchain_mod, "infonet", fake_infonet)

    ok, reason = main._preflight_signed_event_integrity(
        event_type="vote",
        node_id="!node",
        sequence=9,
        public_key="pub",
        public_key_algo="Ed25519",
        signature="sig",
        protocol_version="1",
    )

    assert ok is False
    assert "Replay detected" in reason


def test_signed_event_verification_always_requires_signature_fields():
    import main

    ok, reason = main._verify_signed_event(
        event_type="dm_message",
        node_id="!node",
        sequence=1,
        public_key="",
        public_key_algo="",
        signature="",
        payload={"ciphertext": "c"},
        protocol_version="",
    )
    assert ok is False
    assert reason == "Missing protocol_version"

    ok, reason = main._preflight_signed_event_integrity(
        event_type="dm_poll",
        node_id="!node",
        sequence=1,
        public_key="",
        public_key_algo="",
        signature="",
        protocol_version="",
    )
    assert ok is False
    assert reason == "Missing signature or public key"


def test_scoped_auth_uses_timing_safe_compare(monkeypatch):
    import main
    import auth

    compare_calls = []

    def _fake_compare(left, right):
        compare_calls.append((left, right))
        return True

    monkeypatch.setattr(auth, "_current_admin_key", lambda: "top-secret")
    monkeypatch.setattr(auth, "_scoped_admin_tokens", lambda: {})
    monkeypatch.setattr(main.hmac, "compare_digest", _fake_compare)

    request = SimpleNamespace(
        headers={"X-Admin-Key": "top-secret"},
        client=SimpleNamespace(host="203.0.113.10"),
        url=SimpleNamespace(path="/api/wormhole/status"),
    )

    ok, detail = main._check_scoped_auth(request, "wormhole")

    assert ok is True
    assert detail == "ok"
    assert compare_calls == [(b"top-secret", b"top-secret")]


def test_scoped_auth_uses_timing_safe_compare_for_scoped_tokens(monkeypatch):
    import main
    import auth

    compare_calls = []

    def _fake_compare(left, right):
        compare_calls.append((left, right))
        return left == right

    monkeypatch.setattr(auth, "_current_admin_key", lambda: "")
    monkeypatch.setattr(auth, "_scoped_admin_tokens", lambda: {"gate-token": ["gate"]})
    monkeypatch.setattr(main.hmac, "compare_digest", _fake_compare)

    request = SimpleNamespace(
        headers={"X-Admin-Key": "gate-token"},
        client=SimpleNamespace(host="203.0.113.10"),
        url=SimpleNamespace(path="/api/wormhole/gate/demo/message"),
    )

    ok, detail = main._check_scoped_auth(request, "gate")

    assert ok is True
    assert detail == "ok"
    assert compare_calls == [(b"gate-token", b"gate-token")]


def test_scoped_auth_loopback_without_admin_key_stays_forbidden(monkeypatch):
    import main
    import auth

    monkeypatch.setattr(auth, "_current_admin_key", lambda: "")
    monkeypatch.setattr(auth, "_scoped_admin_tokens", lambda: {})
    monkeypatch.setattr(auth, "_allow_insecure_admin", lambda: False)
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: False)

    request = SimpleNamespace(
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
        url=SimpleNamespace(path="/api/wormhole/dm/root-health"),
    )

    ok, detail = main._check_scoped_auth(request, "dm")

    assert ok is False
    assert detail == "Forbidden — admin key not configured"


def test_scoped_auth_remote_without_admin_key_stays_forbidden(monkeypatch):
    import main
    import auth

    monkeypatch.setattr(auth, "_current_admin_key", lambda: "")
    monkeypatch.setattr(auth, "_scoped_admin_tokens", lambda: {})
    monkeypatch.setattr(auth, "_allow_insecure_admin", lambda: False)
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: False)

    request = SimpleNamespace(
        headers={},
        client=SimpleNamespace(host="203.0.113.10"),
        url=SimpleNamespace(path="/api/wormhole/dm/root-health"),
    )

    ok, detail = main._check_scoped_auth(request, "dm")

    assert ok is False
    assert detail == "Forbidden — admin key not configured"


def test_invalid_json_body_returns_422():
    import main
    from httpx import ASGITransport, AsyncClient

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/send",
                content="{",
                headers={"content-type": "application/json"},
            )
            return response.status_code, response.json()

    status_code, payload = asyncio.run(_run())

    assert status_code == 422
    assert payload == {"ok": False, "detail": "invalid JSON body"}


def test_arti_ready_requires_no_auth_socks5_response(monkeypatch):
    from services import config as config_mod
    from services import wormhole_supervisor

    class _FakeSocket:
        def __init__(self, response: bytes):
            self.response = response
            self.sent = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def sendall(self, data: bytes):
            self.sent.append(data)

        def recv(self, _size: int) -> bytes:
            return self.response

    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: SimpleNamespace(MESH_ARTI_ENABLED=True, MESH_ARTI_SOCKS_PORT=9050),
    )
    monkeypatch.setattr(
        wormhole_supervisor.socket,
        "create_connection",
        lambda *_args, **_kwargs: _FakeSocket(b"\x05\x02"),
    )

    assert wormhole_supervisor._check_arti_ready() is False


def test_gate_router_private_push_uses_opaque_gate_ref(monkeypatch):
    from services import config as config_mod
    from services.mesh.mesh_router import InternetTransport, MeshEnvelope

    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: SimpleNamespace(MESH_PEER_PUSH_SECRET="peer-secret"),
    )

    envelope = MeshEnvelope(
        sender_id="!sb_sender",
        destination="broadcast",
        payload=json.dumps(
            {
                "event_type": "gate_message",
                "timestamp": 1710000000,
                "payload": {
                    "gate": "finance",
                    "ciphertext": "abc123",
                    "format": "mls1",
                },
            }
        ),
    )
    endpoint, build_for_peer = InternetTransport()._build_peer_push_request(envelope, "internet")
    body = build_for_peer("https://peer.example")
    payload = json.loads(body.rstrip(b" ").decode("utf-8"))

    assert endpoint == "/api/mesh/gate/peer-push"
    gate_payload = payload["events"][0]["payload"]
    assert "gate" not in gate_payload
    assert gate_payload["gate_ref"]


def test_gate_router_private_push_freezes_current_v1_signer_bundle(monkeypatch):
    from services import config as config_mod
    from services.mesh.mesh_router import InternetTransport, MeshEnvelope

    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: SimpleNamespace(MESH_PEER_PUSH_SECRET="peer-secret"),
    )

    envelope = MeshEnvelope(
        sender_id="!sb_sender",
        destination="broadcast",
        payload=json.dumps(
            {
                "event_type": "gate_message",
                "timestamp": 1710000000,
                "event_id": "gate-evt-1",
                "node_id": "!gate-persona-1",
                "sequence": 19,
                "signature": "deadbeef",
                "public_key": "pubkey-1",
                "public_key_algo": "Ed25519",
                "protocol_version": "infonet/2",
                "payload": {
                    "gate": "finance",
                    "ciphertext": "abc123",
                    "format": "mls1",
                    "nonce": "nonce-7",
                    "sender_ref": "sender-ref-7",
                    "epoch": 4,
                },
            }
        ),
    )

    endpoint, build_for_peer = InternetTransport()._build_peer_push_request(envelope, "internet")
    body = build_for_peer("https://peer.example")
    payload = json.loads(body.rstrip(b" ").decode("utf-8"))
    event = payload["events"][0]

    assert endpoint == "/api/mesh/gate/peer-push"
    assert set(event.keys()) == {
        "event_type",
        "timestamp",
        "payload",
        "event_id",
        "node_id",
        "sequence",
        "signature",
        "public_key",
        "public_key_algo",
        "protocol_version",
    }
    assert event["event_id"] == "gate-evt-1"
    assert event["node_id"] == "!gate-persona-1"
    assert event["sequence"] == 19
    assert event["signature"] == "deadbeef"
    assert event["public_key"] == "pubkey-1"
    assert event["public_key_algo"] == "Ed25519"
    assert event["protocol_version"] == "infonet/2"
    assert set(event["payload"].keys()) == {"ciphertext", "format", "gate_ref", "nonce", "sender_ref", "epoch"}
    assert event["payload"]["ciphertext"] == "abc123"
    assert event["payload"]["format"] == "mls1"
    assert event["payload"]["nonce"] == "nonce-7"
    assert event["payload"]["sender_ref"] == "sender-ref-7"
    assert event["payload"]["epoch"] == 4
    assert event["payload"]["gate_ref"]
    assert "gate" not in event["payload"]


def test_gate_access_proof_round_trip_verifies_fresh_member_signature(monkeypatch):
    import main

    identity = _gate_proof_identity()
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_resolve_gate_proof_identity", lambda gate_id: dict(identity) if gate_id == "finance" else None)
    monkeypatch.setattr(
        main,
        "_lookup_gate_member_binding",
        lambda gate_id, node_id: (identity["public_key"], "Ed25519")
        if gate_id == "finance" and node_id == identity["node_id"]
        else None,
    )

    proof = main._sign_gate_access_proof("finance")
    request = SimpleNamespace(
        headers={
            "x-wormhole-node-id": identity["node_id"],
            "x-wormhole-gate-proof": proof["proof"],
            "x-wormhole-gate-ts": str(proof["ts"]),
        }
    )

    assert proof["ok"] is True
    assert main._verify_gate_access(request, "finance") == "member"


def test_gate_access_exact_audit_scope_is_required_for_privileged_view(monkeypatch):
    import main
    from services.config import get_settings

    monkeypatch.setenv(
        "MESH_SCOPED_TOKENS",
        json.dumps(
            {
                "gate-only": ["gate"],
                "gate-audit": ["gate.audit"],
                "mesh-audit": ["mesh.audit"],
            }
        ),
    )
    get_settings.cache_clear()
    try:
        gate_request = SimpleNamespace(headers={"X-Admin-Key": "gate-only"})
        gate_audit_request = SimpleNamespace(headers={"X-Admin-Key": "gate-audit"})
        mesh_audit_request = SimpleNamespace(headers={"X-Admin-Key": "mesh-audit"})

        assert main._verify_gate_access(gate_request, "finance") == "member"
        assert main._verify_gate_access(gate_audit_request, "finance") == "privileged"
        assert main._verify_gate_access(mesh_audit_request, "finance") == "privileged"
    finally:
        get_settings.cache_clear()


def test_gate_access_proof_rejects_stale_timestamp(monkeypatch):
    import main

    identity = _gate_proof_identity()
    stale_ts = int(time.time()) - 120
    signature = identity["signing_key"].sign(f"finance:{stale_ts}".encode("utf-8"))
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(
        main,
        "_lookup_gate_member_binding",
        lambda gate_id, node_id: (identity["public_key"], "Ed25519")
        if gate_id == "finance" and node_id == identity["node_id"]
        else None,
    )
    request = SimpleNamespace(
        headers={
            "x-wormhole-node-id": identity["node_id"],
            "x-wormhole-gate-proof": base64.b64encode(signature).decode("ascii"),
            "x-wormhole-gate-ts": str(stale_ts),
        }
    )

    assert main._verify_gate_access(request, "finance") == ""


def test_gate_proof_endpoint_returns_signed_proof(monkeypatch):
    import main
    import auth

    identity = _gate_proof_identity()
    monkeypatch.setattr(main, "_resolve_gate_proof_identity", lambda gate_id: dict(identity) if gate_id == "finance" else None)
    monkeypatch.setattr(auth, "_current_admin_key", lambda: "test-admin")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/proof",
                json={"gate_id": "finance"},
                headers={"x-admin-key": "test-admin"},
            )
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 200
    assert result["ok"] is True, result
    assert result["gate_id"] == "finance"
    assert result["node_id"] == identity["node_id"]
    assert result["proof"]


def test_private_infonet_policy_marks_gate_actions_transitional():
    import auth

    assert auth._private_infonet_required_tier("/api/mesh/vote", "POST") == "transitional"
    assert (
        auth._private_infonet_required_tier("/api/mesh/gate/infonet/message", "POST")
        == "strong"
    )
    assert auth._private_infonet_required_tier("/api/mesh/dm/send", "POST") == "strong"
    assert auth._private_infonet_required_tier("/api/mesh/dm/poll", "GET") == "strong"
    assert auth._private_infonet_required_tier("/api/mesh/status", "GET") == ""


def test_current_private_lane_tier_reflects_runtime_readiness():
    import main

    assert main._current_private_lane_tier({"configured": False, "ready": False, "rns_ready": False}) == "public_degraded"
    assert main._current_private_lane_tier({"configured": True, "ready": False, "rns_ready": True}) == "public_degraded"
    assert main._current_private_lane_tier({"configured": True, "ready": True, "rns_ready": False}) == "private_control_only"
    assert main._current_private_lane_tier({"configured": True, "ready": True, "rns_ready": True}) == "private_transitional"
    assert main._current_private_lane_tier({"configured": True, "ready": True, "arti_ready": True, "rns_ready": True}) == "private_strong"


def test_message_payload_normalization_keeps_transport_lock():
    from services.mesh.mesh_protocol import normalize_message_payload

    normalized = normalize_message_payload(
        {
            "message": "hello mesh",
            "destination": "broadcast",
            "channel": "LongFast",
            "priority": "normal",
            "ephemeral": False,
            "transport_lock": "Meshtastic",
        }
    )

    assert normalized["transport_lock"] == "meshtastic"


def test_public_ledger_rejects_transport_lock():
    from services.mesh.mesh_schema import validate_public_ledger_payload

    ok, reason = validate_public_ledger_payload(
        "message",
        {
            "message": "hello mesh",
            "destination": "broadcast",
            "channel": "LongFast",
            "priority": "normal",
            "ephemeral": False,
            "transport_lock": "meshtastic",
        },
    )

    assert ok is False
    assert "transport_lock" in reason


def test_preflight_integrity_rejects_public_key_binding_conflict(monkeypatch):
    import main
    from services.mesh import mesh_hashchain as mesh_hashchain_mod

    fake_infonet = SimpleNamespace(
        check_replay=lambda node_id, sequence: False,
        node_sequences={},
        public_key_bindings={"pub": "!other-node"},
        _revocation_status=lambda public_key: (False, None),
    )
    monkeypatch.setattr(mesh_hashchain_mod, "infonet", fake_infonet)

    ok, reason = main._preflight_signed_event_integrity(
        event_type="gate_message",
        node_id="!node",
        sequence=10,
        public_key="pub",
        public_key_algo="Ed25519",
        signature="sig",
        protocol_version="1",
    )

    assert ok is False
    assert reason == "public key already bound to !other-node"


def test_mesh_send_blocks_before_transport_side_effect_when_integrity_fails(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_router as mesh_router_mod

    fake_router = _FakeMeshRouter()

    monkeypatch.setattr(
        main,
        "_verify_signed_write",
        lambda **_: (False, "Replay detected: sequence 11 <= last 11"),
    )
    monkeypatch.setattr(main, "_check_throttle", lambda *_: (True, "ok"))
    monkeypatch.setattr(mesh_router_mod, "mesh_router", fake_router)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post("/api/mesh/send", json=_send_body())
            return response.json()

    result = asyncio.run(_run())

    assert result == {"ok": False, "detail": "Replay detected: sequence 11 <= last 11"}
    assert fake_router.route_called is False
    assert fake_router.meshtastic.sent == []


def test_mesh_vote_blocks_before_vote_side_effect_when_integrity_fails(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_reputation as mesh_reputation_mod
    from services import wormhole_supervisor

    fake_ledger = _FakeReputationLedger()

    monkeypatch.setattr(
        main,
        "_verify_signed_write",
        lambda **_: (False, "public key is revoked"),
    )
    monkeypatch.setattr(main, "_validate_gate_vote_context", lambda *_: (True, ""))
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/vote",
                json={
                    "voter_id": "!voter",
                    "target_id": "!target",
                    "vote": 1,
                    "voter_pubkey": "pub",
                    "public_key_algo": "Ed25519",
                    "voter_sig": "sig",
                    "sequence": 4,
                    "protocol_version": "1",
                },
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {"ok": False, "detail": "public key is revoked"}
    assert fake_ledger.registered == []
    assert fake_ledger.votes == []


def test_gate_message_blocks_before_gate_side_effect_when_integrity_fails(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_reputation as mesh_reputation_mod
    from services import wormhole_supervisor

    fake_ledger = _FakeReputationLedger()
    fake_gate_manager = _FakeGateManager()

    monkeypatch.setattr(
        main,
        "_verify_gate_message_signed_write",
        lambda **_: (False, "Replay detected: sequence 7 <= last 7", ""),
    )
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)
    monkeypatch.setattr(mesh_reputation_mod, "gate_manager", fake_gate_manager, raising=False)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/gate/infonet/message",
                json=_gate_signed_context_body(
                    path="/api/mesh/gate/infonet/message",
                    sender_id="!sender",
                    sequence=7,
                    ciphertext="opaque-ciphertext",
                    nonce="nonce-1",
                    sender_ref="gate-session-1",
                ),
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {"ok": False, "detail": "Replay detected: sequence 7 <= last 7"}
    assert fake_ledger.registered == []
    assert fake_gate_manager.enter_checks == []
    assert fake_gate_manager.recorded == []


def test_gate_message_rejects_plaintext_payload_shape(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/gate/infonet/message",
                json={
                    "sender_id": "!sender",
                    "message": "hello gate",
                    "public_key": "pub",
                    "public_key_algo": "Ed25519",
                    "signature": "sig",
                    "sequence": 7,
                    "protocol_version": "1",
                },
            )
            return response.json()

    result = asyncio.run(_run())

    assert result == {
        "ok": False,
        "detail": "Plaintext gate messages are no longer accepted. Submit an encrypted gate envelope.",
    }


def test_gate_message_accepts_encrypted_envelope(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_hashchain as mesh_hashchain_mod
    from services.mesh import mesh_reputation as mesh_reputation_mod
    from services import wormhole_supervisor

    fake_ledger = _FakeReputationLedger()
    fake_gate_manager = _FakeGateManager()
    append_calls = []
    _, mesh_private_outbox, mesh_private_release_worker = _patch_in_memory_private_delivery(monkeypatch)

    monkeypatch.setattr(
        main,
        "_verify_gate_message_signed_write",
        lambda **_: (True, "ok", ""),
    )
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)
    monkeypatch.setattr(mesh_reputation_mod, "gate_manager", fake_gate_manager, raising=False)
    monkeypatch.setattr(
        mesh_hashchain_mod.infonet,
        "validate_and_set_sequence",
        lambda *_args, **_kwargs: (True, "ok"),
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_transport_tier",
        lambda: "private_transitional",
    )

    def fake_append(gate_id, event):
        stored = dict(event)
        stored["event_id"] = str(stored.get("event_id", "") or "gate_evt_test")
        append_calls.append({"gate_id": gate_id, "event": stored})
        return stored

    monkeypatch.setattr(mesh_hashchain_mod.gate_store, "append", fake_append)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/mesh/gate/infonet/message",
                json=_gate_signed_context_body(
                    path="/api/mesh/gate/infonet/message",
                    sender_id="!sender",
                    sequence=9,
                    ciphertext="opaque-ciphertext",
                    nonce="nonce-3",
                    sender_ref="persona-ops-1",
                ),
            )
            return response.json()

    result = asyncio.run(_run())
    queued = mesh_private_outbox.private_delivery_outbox.list_items(
        limit=10,
        exposure="diagnostic",
    )

    assert result["ok"] is True, result
    assert result["detail"] == "Queued for private delivery"
    assert result["queued"] is True
    assert result["gate_id"] == "infonet"
    assert len(append_calls) == 1
    assert fake_ledger.registered == [("!sender", "pub", "Ed25519")]
    assert fake_gate_manager.enter_checks == [("!sender", "infonet")]
    assert fake_gate_manager.recorded == ["infonet"]
    assert len(queued) == 1
    assert queued[0]["lane"] == "gate"
    assert queued[0]["release_state"] == "queued"
    assert queued[0]["meta"]["gate_id"] == "infonet"
    assert queued[0]["meta"]["event_id"] == result["event_id"]

    mesh_private_release_worker.private_release_worker.run_once()
    delivered = mesh_private_outbox.private_delivery_outbox.list_items(
        limit=10,
        exposure="diagnostic",
    )

    assert len(append_calls) == 1
    assert append_calls[0]["gate_id"] == "infonet"
    assert result["event_id"] == append_calls[0]["event"]["event_id"]
    assert append_calls[0]["event"]["payload"] == {
        "gate": "infonet",
        "ciphertext": "opaque-ciphertext",
        "nonce": "nonce-3",
        "sender_ref": "persona-ops-1",
        "format": "mls1",
        "epoch": 1,
        "transport_lock": "private_strong",
    }
    assert delivered[0]["release_state"] == "queued"


def test_gate_message_enforces_30_second_sender_cooldown(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_hashchain as mesh_hashchain_mod
    from services.mesh import mesh_reputation as mesh_reputation_mod
    from services import wormhole_supervisor

    class _Clock:
        def __init__(self):
            self.current = 1_000.0

        def time(self):
            return self.current

    clock = _Clock()
    fake_ledger = _FakeReputationLedger()
    fake_gate_manager = _FakeGateManager()
    append_calls = []
    _, mesh_private_outbox, mesh_private_release_worker = _patch_in_memory_private_delivery(monkeypatch)

    monkeypatch.setattr(main.time, "time", clock.time)
    monkeypatch.setattr(
        main,
        "_verify_gate_message_signed_write",
        lambda **_: (True, "ok", ""),
    )
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)
    monkeypatch.setattr(mesh_reputation_mod, "gate_manager", fake_gate_manager, raising=False)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_transport_tier",
        lambda: "private_transitional",
    )
    monkeypatch.setattr(
        mesh_hashchain_mod.gate_store,
        "append",
        lambda gate_id, event: append_calls.append({"gate_id": gate_id, "event": event}) or event,
    )
    monkeypatch.setattr(
        mesh_hashchain_mod.infonet,
        "validate_and_set_sequence",
        lambda node_id, sequence: (True, "ok"),
    )
    main._gate_post_cooldown.clear()

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            first = await ac.post(
                "/api/mesh/gate/infonet/message",
                json=_gate_signed_context_body(
                    path="/api/mesh/gate/infonet/message",
                    sender_id="!sender",
                    sequence=9,
                    ciphertext="opaque-ciphertext",
                    nonce="nonce-3",
                    sender_ref="persona-ops-1",
                ),
            )
            clock.current += 12
            second = await ac.post(
                "/api/mesh/gate/infonet/message",
                json=_gate_signed_context_body(
                    path="/api/mesh/gate/infonet/message",
                    sender_id="!sender",
                    sequence=10,
                    ciphertext="opaque-ciphertext-2",
                    nonce="nonce-4",
                    sender_ref="persona-ops-1",
                ),
            )
            return first.json(), second.json()

    first_result, second_result = asyncio.run(_run())

    assert first_result["ok"] is True
    assert first_result["queued"] is True
    assert second_result == {
        "ok": False,
        "detail": "Gate post cooldown: wait 18s before posting again.",
    }
    assert fake_gate_manager.recorded == ["infonet"]
    queued = mesh_private_outbox.private_delivery_outbox.list_items(
        limit=10,
        exposure="diagnostic",
    )
    assert len(queued) == 1
    assert len(append_calls) == 1

    mesh_private_release_worker.private_release_worker.run_once()
    delivered = mesh_private_outbox.private_delivery_outbox.list_items(
        limit=10,
        exposure="diagnostic",
    )

    assert len(append_calls) >= 1
    assert delivered[0]["release_state"] == "queued"


def test_infonet_status_reports_lane_tier_and_policy(monkeypatch):
    import main
    import auth
    from httpx import ASGITransport, AsyncClient
    from services.config import get_settings
    from services import wormhole_supervisor

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": True,
            "wormhole_enabled": True,
            "ready": True,
            "effective_transport": "tor_arti",
        },
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/mesh/infonet/status")
            return response.json()

    result = asyncio.run(_run())

    assert result["private_lane_tier"] == "private_transitional"
    assert result["private_lane_policy"]["gate_actions"]["post_message"] == "private_strong"
    assert result["private_lane_policy"]["gate_chat"]["content_private"] is True
    assert (
        result["private_lane_policy"]["gate_chat"]["storage_model"]
        == "private_gate_store_mls_state_optional_recovery_envelope"
    )
    assert result["private_lane_policy"]["dm_lane"]["public_transports_excluded"] is True
    assert result["private_lane_policy"]["dm_lane"]["relay_fallback"] is True
    assert result["private_lane_policy"]["dm_lane"]["relay_fallback_operator_opt_in"] is True
    assert result["private_lane_policy"]["strong_claims"]["allowed"] is False
    assert "transport_tier_not_private_strong" in result["private_lane_policy"]["strong_claims"]["reasons"]
    assert result["private_lane_policy"]["reserved_for_private_strong"] == []
    get_settings.cache_clear()


def test_wormhole_status_reports_transport_tier(tmp_path, monkeypatch):
    import main
    import auth
    from starlette.requests import Request
    from services.config import get_settings
    from services.mesh import mesh_compatibility

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", "false")
    monkeypatch.setattr(mesh_compatibility, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_compatibility,
        "COMPATIBILITY_FILE",
        tmp_path / "mesh_compatibility_usage.json",
    )
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: True)
    main.private_transport_manager.reset_for_tests()
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": True,
            "wormhole_enabled": True,
            "ready": True,
            "effective_transport": "tor_arti",
        },
    )
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": False,
            "transport": "direct",
        },
    )

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/wormhole/status",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )
    result = asyncio.run(main.api_wormhole_status(request))

    assert result["transport_tier"] == "private_transitional"
    assert result["private_lane_readiness"]["status"]["label"] in {
        "Preparing private lane",
        "Private lane ready",
    }
    assert result["strong_claims"]["allowed"] is False
    assert result["strong_claims"]["compat_overrides_clear"] is True
    assert result["clearnet_fallback_policy"] == "block"
    assert result["compatibility_debt"]["legacy_lookup_reliance"]["active"] is False
    assert result["compatibility_debt"]["legacy_mailbox_get_reliance"]["active"] is False
    assert "legacy_compatibility" not in result
    get_settings.cache_clear()


def test_wormhole_status_reports_private_strong_when_arti_ready(monkeypatch):
    import main
    import auth
    from services.config import get_settings
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": True,
            "wormhole_enabled": True,
            "ready": True,
            "effective_transport": "tor_arti",
        },
    )
    monkeypatch.setattr(
        auth,
        "_external_assurance_status_snapshot",
        lambda: {
            "current": True,
            "configured": True,
            "state": "current_external",
            "detail": "configured external assurance is current",
            "witness_state": "current",
            "transparency_state": "current",
        },
    )
    monkeypatch.setattr(
        "services.privacy_core_attestation.privacy_core_attestation",
        lambda *_args, **_kwargs: {
            "attestation_state": "attested_current",
            "override_active": False,
            "detail": "privacy-core version and trusted artifact hash are current",
        },
    )
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
            "transport": "tor_arti",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/wormhole/status")
            return response.json()

    result = asyncio.run(_run())

    assert result["transport_tier"] == "private_strong"
    assert result["strong_claims"]["allowed"] is True
    assert result["strong_claims"]["reasons"] == []
    get_settings.cache_clear()


def test_wormhole_status_requires_external_assurance_for_strong_claims(monkeypatch):
    import main
    import auth
    from services.config import get_settings
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": True,
            "wormhole_enabled": True,
            "ready": True,
            "effective_transport": "tor_arti",
        },
    )
    monkeypatch.setattr(
        auth,
        "_external_assurance_status_snapshot",
        lambda: {
            "current": False,
            "configured": False,
            "state": "local_cached_only",
            "detail": "external witness and transparency assurance are not fully configured",
            "witness_state": "not_configured",
            "transparency_state": "not_configured",
        },
    )
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
            "transport": "tor_arti",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/wormhole/status?exposure=diagnostic",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result["transport_tier"] == "private_strong"
    assert result["strong_claims"]["allowed"] is False
    assert result["strong_claims"]["external_assurance_current"] is False
    assert result["strong_claims"]["external_assurance_state"] == "local_cached_only"
    assert "external_assurance_not_current" in result["strong_claims"]["reasons"]
    assert result["release_gate"]["criteria"]["external_assurance_current"]["ok"] is False
    get_settings.cache_clear()


def test_wormhole_status_marks_legacy_dm_signature_compat_as_policy_override(monkeypatch):
    import main
    import auth
    from services.config import get_settings
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", "false")
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    monkeypatch.setenv("MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL", "2099-01-01")
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": True,
            "wormhole_enabled": True,
            "ready": True,
            "effective_transport": "tor_arti",
        },
    )
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
            "transport": "tor_arti",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/wormhole/status?exposure=diagnostic",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result["transport_tier"] == "private_strong"
    assert result["strong_claims"]["allowed"] is False
    assert result["strong_claims"]["compat_overrides_clear"] is False
    assert result["strong_claims"]["compatibility"]["legacy_dm_signature_compat_enabled"] is True
    assert "compat_overrides_enabled" in result["strong_claims"]["reasons"]
    get_settings.cache_clear()


def test_wormhole_status_marks_legacy_dm_get_as_policy_override(monkeypatch):
    import main
    import auth
    from services.config import get_settings
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", "false")
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    monkeypatch.setenv("MESH_ALLOW_LEGACY_DM_GET_UNTIL", "2099-01-01")
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": True,
            "wormhole_enabled": True,
            "ready": True,
            "effective_transport": "tor_arti",
        },
    )
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
            "transport": "tor_arti",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/wormhole/status?exposure=diagnostic",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result["transport_tier"] == "private_strong"
    assert result["strong_claims"]["allowed"] is False
    assert result["strong_claims"]["compat_overrides_clear"] is False
    assert result["strong_claims"]["compatibility"]["legacy_dm_get_enabled"] is True
    assert result["legacy_compatibility"]["sunset"]["legacy_dm_get"]["status"] == "dev_migration_override"
    assert "compat_overrides_enabled" in result["strong_claims"]["reasons"]
    get_settings.cache_clear()


def test_wormhole_status_marks_compat_dm_invite_import_as_policy_override(monkeypatch):
    import main
    import auth
    from services.config import get_settings
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    monkeypatch.setenv("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT_UNTIL", "2099-01-01")
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": True,
            "wormhole_enabled": True,
            "ready": True,
            "effective_transport": "tor_arti",
        },
    )
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
            "transport": "tor_arti",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/wormhole/status?exposure=diagnostic",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result["transport_tier"] == "private_strong"
    assert result["strong_claims"]["allowed"] is False
    assert result["strong_claims"]["compat_overrides_clear"] is False
    assert result["strong_claims"]["compatibility"]["compat_dm_invite_import_enabled"] is True
    assert result["legacy_compatibility"]["sunset"]["compat_dm_invite_import"]["status"] == "dev_migration_override"
    assert "compat_overrides_enabled" in result["strong_claims"]["reasons"]
    get_settings.cache_clear()


def test_wormhole_status_marks_legacy_dm1_as_policy_override(monkeypatch):
    import main
    import auth
    from services.config import get_settings
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    monkeypatch.setenv("MESH_ALLOW_LEGACY_DM1_UNTIL", "2099-01-01")
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": True,
            "wormhole_enabled": True,
            "ready": True,
            "effective_transport": "tor_arti",
        },
    )
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
            "transport": "tor_arti",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/wormhole/status?exposure=diagnostic",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result["transport_tier"] == "private_strong"
    assert result["strong_claims"]["allowed"] is False
    assert result["strong_claims"]["compat_overrides_clear"] is False
    assert result["strong_claims"]["compatibility"]["legacy_dm1_enabled"] is True
    assert result["legacy_compatibility"]["sunset"]["legacy_dm1"]["status"] == "dev_migration_override"
    assert "compat_overrides_enabled" in result["strong_claims"]["reasons"]
    get_settings.cache_clear()


def test_wormhole_status_marks_gate_plaintext_persist_as_policy_override(monkeypatch):
    import auth
    import main
    from httpx import ASGITransport, AsyncClient
    from services.config import get_settings

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_GATE_PLAINTEXT_PERSIST", "true")
    monkeypatch.setenv("MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": True,
            "wormhole_enabled": True,
            "ready": True,
            "effective_transport": "tor_arti",
        },
    )
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
            "transport": "tor_arti",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/wormhole/status",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    result = asyncio.run(_run())

    assert result["transport_tier"] == "private_strong"
    assert result["strong_claims"]["allowed"] is False
    assert result["strong_claims"]["compat_overrides_clear"] is False
    assert result["strong_claims"]["compatibility"]["gate_plaintext_persist"] is True
    assert "compat_overrides_enabled" in result["strong_claims"]["reasons"]
    get_settings.cache_clear()


def test_wormhole_status_marks_gate_recovery_envelope_as_policy_override(monkeypatch):
    import auth
    import main
    from httpx import ASGITransport, AsyncClient
    from services.config import get_settings
    from services.mesh.mesh_reputation import gate_manager

    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "true")
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE", "true")
    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {
            "enabled": True,
            "wormhole_enabled": True,
            "ready": True,
            "effective_transport": "tor_arti",
        },
    )
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
            "transport": "tor_arti",
        },
    )
    gate_manager.gates["__test_recovery_status"] = {
        "creator_node_id": "test",
        "display_name": "Recovery Status",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "fake-secret",
        "envelope_policy": "envelope_recovery",
    }

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/wormhole/status")
            return response.json()

    try:
        result = asyncio.run(_run())
    finally:
        gate_manager.gates.pop("__test_recovery_status", None)

    assert result["transport_tier"] == "private_strong"
    assert result["strong_claims"]["allowed"] is False
    assert result["strong_claims"]["compat_overrides_clear"] is True
    assert "compat_overrides_enabled" not in result["strong_claims"]["reasons"]
    get_settings.cache_clear()


def test_wormhole_join_route_refreshes_node_peer_store(monkeypatch):
    import main
    from routers import wormhole as wormhole_router
    from httpx import ASGITransport, AsyncClient
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
    monkeypatch.setattr(
        wormhole_router,
        "bootstrap_wormhole_identity",
        lambda: bootstrap_calls.append("identity"),
    )
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
    monkeypatch.setattr(
        wormhole_router,
        "get_transport_identity",
        lambda: {"node_id": "!sb_test_join"},
    )
    monkeypatch.setattr(
        node_settings,
        "write_node_settings",
        lambda **kwargs: node_setting_calls.append(kwargs),
    )
    monkeypatch.setattr(
        main,
        "_refresh_node_peer_store",
        lambda **kwargs: refresh_calls.append(kwargs) or {"ok": True},
    )

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


def test_infonet_gate_wait_returns_changed_payload_with_cursor(monkeypatch):
    import main
    from routers import mesh_public
    from services.mesh import mesh_hashchain

    sample_message = {
        "event_id": "evt-2",
        "event_type": "gate_message",
        "timestamp": 1_712_360_010,
        "gate": "infonet",
        "payload": {
            "gate": "infonet",
            "ciphertext": "cipher-2",
            "format": "mls1",
            "nonce": "nonce-2",
            "sender_ref": "sender-2",
        },
    }

    monkeypatch.setattr(main, "_verify_gate_access", lambda *_args, **_kwargs: "member")
    monkeypatch.setattr(mesh_public, "_verify_gate_access", lambda *_args, **_kwargs: "member")
    monkeypatch.setattr(main, "_strip_gate_for_access", lambda message, _access: message)
    monkeypatch.setattr(mesh_public, "_strip_gate_for_access", lambda message, _access: message)
    monkeypatch.setattr(
        mesh_hashchain.gate_store,
        "wait_for_gate_change",
        lambda gate_id, after_cursor, timeout_s: (True, 2),
    )
    monkeypatch.setattr(
        mesh_hashchain.gate_store,
        "get_messages_with_cursor",
        lambda gate_id, limit=20, offset=0: ([sample_message], 2),
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/mesh/infonet/messages/wait?gate=infonet&after=1&limit=10&timeout_ms=1500")
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 200
    assert result["gate"] == "infonet"
    assert result["cursor"] == 2
    assert result["changed"] is True
    assert result["messages"][0]["event_id"] == "evt-2"


def test_infonet_gate_wait_requires_gate_membership(monkeypatch):
    import main
    from routers import mesh_public

    monkeypatch.setattr(main, "_verify_gate_access", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mesh_public, "_verify_gate_access", lambda *_args, **_kwargs: "")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/mesh/infonet/messages/wait?gate=infonet&after=0")
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 403
    assert result == {"ok": False, "detail": "access denied"}


def test_infonet_gate_event_member_proof_cannot_retrieve_privileged_detail(monkeypatch):
    import main
    from services.mesh import mesh_hashchain

    identity = _gate_proof_identity()
    raw_event = {
        "event_id": "evt-gate-proof-1",
        "event_type": "gate_message",
        "timestamp": 1_700_000_000,
        "node_id": "node-secret-id",
        "sequence": 7,
        "signature": "deadbeef",
        "public_key": "c2VjcmV0",
        "public_key_algo": "Ed25519",
        "protocol_version": "0.9.6",
        "payload": {
            "gate": "finance",
            "ciphertext": "ciphertext",
            "format": "mls1",
            "nonce": "nonce-1",
            "sender_ref": "sender-ref-1",
            "gate_envelope": "recovery-envelope",
            "envelope_hash": "envelope-hash",
            "reply_to": "evt-parent-1",
        },
    }

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_resolve_gate_proof_identity", lambda gate_id: dict(identity) if gate_id == "finance" else None)
    monkeypatch.setattr(
        main,
        "_lookup_gate_member_binding",
        lambda gate_id, node_id: (identity["public_key"], "Ed25519")
        if gate_id == "finance" and node_id == identity["node_id"]
        else None,
    )
    monkeypatch.setattr(mesh_hashchain.infonet, "get_event", lambda _event_id: None)
    monkeypatch.setattr(mesh_hashchain.gate_store, "get_event", lambda _event_id: copy.deepcopy(raw_event))

    proof = main._sign_gate_access_proof("finance")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/mesh/infonet/event/evt-gate-proof-1",
                headers={
                    "x-wormhole-node-id": identity["node_id"],
                    "x-wormhole-gate-proof": proof["proof"],
                    "x-wormhole-gate-ts": str(proof["ts"]),
                },
            )
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 200
    assert result["event_id"] == "evt-gate-proof-1"
    assert "node_id" not in result
    assert "public_key" not in result
    assert "signature" not in result
    assert result["payload"]["gate_envelope"] == "recovery-envelope"
    assert result["payload"]["envelope_hash"] == "envelope-hash"


def test_infonet_gate_event_audit_scope_can_retrieve_privileged_detail(monkeypatch):
    import main
    from services.config import get_settings
    from services.mesh import mesh_hashchain

    raw_event = {
        "event_id": "evt-gate-audit-1",
        "event_type": "gate_message",
        "timestamp": 1_700_000_001,
        "node_id": "node-secret-id",
        "sequence": 8,
        "signature": "deadbeef",
        "public_key": "c2VjcmV0",
        "public_key_algo": "Ed25519",
        "protocol_version": "0.9.6",
        "payload": {
            "gate": "finance",
            "ciphertext": "ciphertext",
            "format": "mls1",
            "nonce": "nonce-2",
            "sender_ref": "sender-ref-2",
            "gate_envelope": "recovery-envelope",
            "envelope_hash": "envelope-hash",
            "reply_to": "evt-parent-2",
        },
    }

    monkeypatch.setenv(
        "MESH_SCOPED_TOKENS",
        json.dumps({"gate-only": ["gate"], "gate-audit": ["gate.audit"]}),
    )
    get_settings.cache_clear()
    monkeypatch.setattr(mesh_hashchain.infonet, "get_event", lambda _event_id: None)
    monkeypatch.setattr(mesh_hashchain.gate_store, "get_event", lambda _event_id: copy.deepcopy(raw_event))

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            member_response = await ac.get(
                "/api/mesh/infonet/event/evt-gate-audit-1",
                headers={"X-Admin-Key": "gate-only"},
            )
            audit_response = await ac.get(
                "/api/mesh/infonet/event/evt-gate-audit-1",
                headers={"X-Admin-Key": "gate-audit"},
            )
            return (
                member_response.status_code,
                member_response.json(),
                audit_response.status_code,
                audit_response.json(),
            )

    try:
        member_status, member_result, audit_status, audit_result = asyncio.run(_run())
    finally:
        get_settings.cache_clear()

    assert member_status == 200
    assert "node_id" not in member_result
    assert member_result["payload"]["gate_envelope"] == "recovery-envelope"

    assert audit_status == 200
    assert set(audit_result.keys()) == {
        "event_id",
        "event_type",
        "timestamp",
        "node_id",
        "sequence",
        "signature",
        "public_key",
        "public_key_algo",
        "protocol_version",
        "payload",
    }
    assert set(audit_result["payload"].keys()) == {
        "gate",
        "ciphertext",
        "format",
        "nonce",
        "sender_ref",
        "gate_envelope",
        "envelope_hash",
        "reply_to",
        "transport_lock",
    }
    assert audit_result["node_id"] == "node-secret-id"
    assert audit_result["payload"]["gate_envelope"] == "recovery-envelope"


def test_rns_status_reports_lane_tier_and_policy(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor
    from services.mesh import mesh_rns

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(
        mesh_rns,
        "rns_bridge",
        SimpleNamespace(status=lambda: {"enabled": True, "ready": True, "configured_peers": 1, "active_peers": 1}),
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/mesh/rns/status")
            return response.json()

    result = asyncio.run(_run())

    assert result["private_lane_tier"] == "private_strong"
    # Hardening Rec #4: gate release floor lifted to private_strong (matches DM).
    assert result["private_lane_policy"]["gate_chat"]["trust_tier"] == "private_strong"


def test_scoped_gate_token_cannot_access_dm_endpoints(tmp_path, monkeypatch):
    import main
    from routers import wormhole as wormhole_router
    from httpx import ASGITransport, AsyncClient
    from services.config import get_settings
    from services import wormhole_supervisor
    from services.mesh import mesh_gate_mls, mesh_secure_storage, mesh_wormhole_persona

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
    mesh_gate_mls.reset_gate_mls_state()
    mesh_wormhole_persona.bootstrap_wormhole_persona_state(force=True)
    mesh_wormhole_persona.create_gate_persona("infonet", label="scribe")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setenv("MESH_SCOPED_TOKENS", '{"gate-only":["gate"]}')
    get_settings.cache_clear()

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            gate_response = await ac.post(
                "/api/wormhole/gate/proof",
                json={"gate_id": "infonet"},
                headers={"X-Admin-Key": "gate-only"},
            )
            dm_response = await ac.post(
                "/api/wormhole/dm/compose",
                json={"peer_id": "bob", "peer_dh_pub": "deadbeef", "plaintext": "blocked"},
                headers={"X-Admin-Key": "gate-only"},
            )
            return gate_response.json(), dm_response.status_code, dm_response.json()

    try:
        gate_result, dm_status, dm_result = asyncio.run(_run())
    finally:
        get_settings.cache_clear()

    assert gate_result["ok"] is True
    assert gate_result["gate_id"] == "infonet"
    assert dm_status == 403
    assert dm_result == {"ok": False, "detail": "access denied"}


def test_wormhole_status_reports_coarse_gate_privilege_access(monkeypatch):
    import auth
    import main
    from services.config import get_settings

    monkeypatch.setenv(
        "MESH_SCOPED_TOKENS",
        json.dumps({"gate-only": ["gate"], "gate-audit": ["gate.audit"]}),
    )
    get_settings.cache_clear()
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": False,
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/wormhole/status",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.status_code, response.json()

    try:
        status_code, result = asyncio.run(_run())
    finally:
        get_settings.cache_clear()

    assert status_code == 200
    assert result["gate_privilege_access"] == {
        "ordinary_gate_view_scope_class": "gate_member_or_gate_scope",
        "privileged_gate_event_scope_class": "explicit_gate_audit",
        "repair_detail_scope_class": "local_operator_diagnostic",
        "privileged_gate_event_view_enabled": True,
        "repair_detail_view_enabled": True,
    }


def test_wormhole_review_export_returns_expected_consolidated_package(monkeypatch):
    import auth
    import main

    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_privacy_core_status",
        lambda: {
            "state": "attested_current",
            "attestation_state": "attested_current",
            "allowed": True,
            "override_active": False,
        },
    )
    monkeypatch.setattr(
        main,
        "local_custody_status_snapshot",
        lambda: {
            "code": "protected_at_rest",
            "provider": "passphrase",
            "protected_at_rest": True,
        },
    )
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(
        main,
        "gate_privileged_access_status_snapshot",
        lambda: {
            "ordinary_gate_view_scope_class": "gate_member_or_gate_scope",
            "privileged_gate_event_scope_class": "explicit_gate_audit",
            "repair_detail_scope_class": "local_operator_diagnostic",
            "privileged_gate_event_view_enabled": True,
            "repair_detail_view_enabled": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )
    monkeypatch.setattr(
        main,
        "_strong_claims_policy_snapshot",
        lambda **_kwargs: {
            "allowed": True,
            "state": "dm_strong_ready",
            "plain_label": "Strong private ready",
            "detail": "ready",
            "compatibility_shim": True,
            "source_model": "privacy_claims",
            "source_surface": "privacy_claims",
        },
    )
    monkeypatch.setattr(
        main,
        "_release_gate_status",
        lambda **_kwargs: {
            "ready": True,
            "state": "gate_transitional_ready",
            "plain_label": "Transitional private ready",
            "detail": "ready",
            "compatibility_shim": True,
            "source_model": "privacy_claims",
            "authoritative_dm_claim_state": "dm_strong_ready",
            "authoritative_gate_claim_state": "gate_transitional_ready",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/wormhole/review-export",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 200
    assert_surface_contract(result, EXPLICIT_REVIEW_EXPORT_CONTRACT)
    assert result["schema_version"] == "privacy_explicit_review_export.v1"
    assert result["export_kind"] == "explicit_review_export"
    assert result["surface_class"] == "authoritative_export_bundle"
    assert result["export_metadata"]["deterministic"] is True
    assert result["export_metadata"]["identifier_free"] is True
    assert result["export_metadata"]["source_surfaces"] == [
        "final_review_bundle",
        "staged_rollout_telemetry",
        "release_claims_matrix",
        "release_checklist",
    ]
    assert result["final_review_bundle"]["schema_version"] == "privacy_final_review_bundle.v1"
    assert result["staged_rollout_telemetry"]["schema_version"] == "privacy_staged_rollout_telemetry.v1"
    assert result["release_claims_matrix"]["schema_version"] == "privacy_release_claims_matrix.v1"
    assert result["release_checklist"]["schema_version"] == "privacy_release_checklist.v1"
    export_text = repr(result)
    assert "recent_targets" not in export_text
    assert "agent_id" not in export_text


def test_wormhole_review_export_is_local_operator_or_admin_only():
    import main

    async def _run():
        async with AsyncClient(
            transport=ASGITransport(app=main.app, client=("203.0.113.10", 54321)),
            base_url="http://test",
        ) as ac:
            response = await ac.get("/api/wormhole/review-export")
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 403
    assert result == {"detail": "Forbidden — local operator access only"}


def test_wormhole_review_export_matches_status_derived_diagnostic_package(monkeypatch):
    import auth
    import main

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_privacy_core_status",
        lambda: {
            "state": "attested_current",
            "attestation_state": "attested_current",
            "allowed": True,
            "override_active": False,
        },
    )
    monkeypatch.setattr(
        main,
        "local_custody_status_snapshot",
        lambda: {
            "code": "protected_at_rest",
            "provider": "passphrase",
            "protected_at_rest": True,
        },
    )
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(
        main,
        "gate_privileged_access_status_snapshot",
        lambda: {
            "ordinary_gate_view_scope_class": "gate_member_or_gate_scope",
            "privileged_gate_event_scope_class": "explicit_gate_audit",
            "repair_detail_scope_class": "local_operator_diagnostic",
            "privileged_gate_event_view_enabled": True,
            "repair_detail_view_enabled": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )
    monkeypatch.setattr(
        main,
        "_strong_claims_policy_snapshot",
        lambda **_kwargs: {
            "allowed": True,
            "state": "dm_strong_ready",
            "plain_label": "Strong private ready",
            "detail": "ready",
            "compatibility_shim": True,
            "source_model": "privacy_claims",
            "source_surface": "privacy_claims",
        },
    )
    monkeypatch.setattr(
        main,
        "_release_gate_status",
        lambda **_kwargs: {
            "ready": True,
            "state": "gate_transitional_ready",
            "plain_label": "Transitional private ready",
            "detail": "ready",
            "compatibility_shim": True,
            "source_model": "privacy_claims",
            "authoritative_dm_claim_state": "dm_strong_ready",
            "authoritative_gate_claim_state": "gate_transitional_ready",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            status_response = await ac.get(
                "/api/wormhole/status?exposure=diagnostic",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            export_response = await ac.get(
                "/api/wormhole/review-export",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return status_response.status_code, status_response.json(), export_response.status_code, export_response.json()

    status_code, status_result, export_status_code, export_result = asyncio.run(_run())

    assert status_code == 200
    assert export_status_code == 200
    assert export_result == {
        "schema_version": "privacy_explicit_review_export.v1",
        "export_kind": "explicit_review_export",
        "surface_class": "authoritative_export_bundle",
        "source_surface": "final_review_bundle",
        "authoritative_model": status_result["final_review_bundle"]["authoritative_model"],
        "export_metadata": {
            "deterministic": True,
            "identifier_free": True,
            "source_surfaces": [
                "final_review_bundle",
                "staged_rollout_telemetry",
                "release_claims_matrix",
                "release_checklist",
            ],
        },
        "final_review_bundle": status_result["final_review_bundle"],
        "staged_rollout_telemetry": status_result["staged_rollout_telemetry"],
        "release_claims_matrix": status_result["release_claims_matrix"],
        "release_checklist": status_result["release_checklist"],
    }


def test_wormhole_review_manifest_returns_expected_summary_and_matches_export(monkeypatch):
    import auth
    import main
    from services.privacy_claims import review_manifest_snapshot

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_privacy_core_status",
        lambda: {
            "state": "attested_current",
            "attestation_state": "attested_current",
            "allowed": True,
            "override_active": False,
        },
    )
    monkeypatch.setattr(
        main,
        "local_custody_status_snapshot",
        lambda: {
            "code": "protected_at_rest",
            "provider": "passphrase",
            "protected_at_rest": True,
        },
    )
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(
        main,
        "gate_privileged_access_status_snapshot",
        lambda: {
            "ordinary_gate_view_scope_class": "gate_member_or_gate_scope",
            "privileged_gate_event_scope_class": "explicit_gate_audit",
            "repair_detail_scope_class": "local_operator_diagnostic",
            "privileged_gate_event_view_enabled": True,
            "repair_detail_view_enabled": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )
    monkeypatch.setattr(
        main,
        "_strong_claims_policy_snapshot",
        lambda **_kwargs: {
            "allowed": True,
            "state": "dm_strong_ready",
            "plain_label": "Strong private ready",
            "detail": "ready",
            "compatibility_shim": True,
            "source_model": "privacy_claims",
            "source_surface": "privacy_claims",
        },
    )
    monkeypatch.setattr(
        main,
        "_release_gate_status",
        lambda **_kwargs: {
            "ready": True,
            "state": "gate_transitional_ready",
            "plain_label": "Transitional private ready",
            "detail": "ready",
            "compatibility_shim": True,
            "source_model": "privacy_claims",
            "authoritative_dm_claim_state": "dm_strong_ready",
            "authoritative_gate_claim_state": "gate_transitional_ready",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            export_response = await ac.get(
                "/api/wormhole/review-export",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            manifest_response = await ac.get(
                "/api/wormhole/review-manifest",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return export_response.status_code, export_response.json(), manifest_response.status_code, manifest_response.json()

    export_status_code, export_result, manifest_status_code, manifest_result = asyncio.run(_run())

    assert export_status_code == 200
    assert manifest_status_code == 200
    assert_surface_contract(manifest_result, REVIEW_MANIFEST_CONTRACT)
    assert manifest_result == review_manifest_snapshot(explicit_review_export=export_result)
    assert manifest_result["schema_version"] == "privacy_review_manifest.v1"
    assert manifest_result["claim_summary_rows"]["dm_strong_claim_now"]["allowed"] is True
    assert manifest_result["checklist_summary"]["checklist_status"] == "completed"
    manifest_text = repr(manifest_result)
    assert "recent_targets" not in manifest_text
    assert "agent_id" not in manifest_text


def test_wormhole_review_manifest_is_local_operator_or_admin_only():
    import main

    async def _run():
        async with AsyncClient(
            transport=ASGITransport(app=main.app, client=("203.0.113.10", 54321)),
            base_url="http://test",
        ) as ac:
            response = await ac.get("/api/wormhole/review-manifest")
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 403
    assert result == {"detail": "Forbidden — local operator access only"}


def test_wormhole_review_consistency_returns_aligned_package(monkeypatch):
    import auth
    import main
    from services.privacy_claims import review_consistency_snapshot, review_manifest_snapshot

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_privacy_core_status",
        lambda: {
            "state": "attested_current",
            "attestation_state": "attested_current",
            "allowed": True,
            "override_active": False,
        },
    )
    monkeypatch.setattr(
        main,
        "local_custody_status_snapshot",
        lambda: {
            "code": "protected_at_rest",
            "provider": "passphrase",
            "protected_at_rest": True,
        },
    )
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(
        main,
        "gate_privileged_access_status_snapshot",
        lambda: {
            "ordinary_gate_view_scope_class": "gate_member_or_gate_scope",
            "privileged_gate_event_scope_class": "explicit_gate_audit",
            "repair_detail_scope_class": "local_operator_diagnostic",
            "privileged_gate_event_view_enabled": True,
            "repair_detail_view_enabled": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )
    monkeypatch.setattr(
        main,
        "_strong_claims_policy_snapshot",
        lambda **_kwargs: {
            "allowed": True,
            "state": "dm_strong_ready",
            "plain_label": "Strong private ready",
            "detail": "ready",
            "compatibility_shim": True,
            "source_model": "privacy_claims",
            "source_surface": "privacy_claims",
        },
    )
    monkeypatch.setattr(
        main,
        "_release_gate_status",
        lambda **_kwargs: {
            "ready": True,
            "state": "gate_transitional_ready",
            "plain_label": "Transitional private ready",
            "detail": "ready",
            "compatibility_shim": True,
            "source_model": "privacy_claims",
            "authoritative_dm_claim_state": "dm_strong_ready",
            "authoritative_gate_claim_state": "gate_transitional_ready",
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            export_response = await ac.get(
                "/api/wormhole/review-export",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            consistency_response = await ac.get(
                "/api/wormhole/review-consistency",
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return export_response.status_code, export_response.json(), consistency_response.status_code, consistency_response.json()

    export_status_code, export_result, consistency_status_code, consistency_result = asyncio.run(_run())

    assert export_status_code == 200
    assert consistency_status_code == 200
    assert_surface_contract(consistency_result, REVIEW_CONSISTENCY_CONTRACT)
    manifest = review_manifest_snapshot(explicit_review_export=export_result)
    assert consistency_result == review_consistency_snapshot(
        explicit_review_export=export_result,
        review_manifest=manifest,
    )
    assert consistency_result["alignment_verdict"]["aligned"] is True
    assert consistency_result["blocker_category_mismatches"] == {
        "export_only": [],
        "manifest_only": [],
    }
    assert consistency_result["handoff_summary"]["claim_rows_fully_backed_by_evidence_now"]["allowed"] is True
    consistency_text = repr(consistency_result)
    assert "recent_targets" not in consistency_text
    assert "agent_id" not in consistency_text


def test_wormhole_review_consistency_is_local_operator_or_admin_only():
    import main

    async def _run():
        async with AsyncClient(
            transport=ASGITransport(app=main.app, client=("203.0.113.10", 54321)),
            base_url="http://test",
        ) as ac:
            response = await ac.get("/api/wormhole/review-consistency")
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 403
    assert result == {"detail": "Forbidden — local operator access only"}


def test_scoped_gate_token_private_strong_dm_scope_failure_is_generic(tmp_path, monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.config import get_settings
    from services import wormhole_supervisor
    from services.mesh import mesh_gate_mls, mesh_secure_storage, mesh_wormhole_persona

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
    mesh_gate_mls.reset_gate_mls_state()
    mesh_wormhole_persona.bootstrap_wormhole_persona_state(force=True)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setenv("MESH_SCOPED_TOKENS", '{"gate-only":["gate"]}')
    get_settings.cache_clear()

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/dm/compose",
                json={"peer_id": "bob", "peer_dh_pub": "deadbeef", "plaintext": "blocked"},
                headers={"X-Admin-Key": "gate-only"},
            )
            return response.status_code, response.json()

    try:
        status_code, result = asyncio.run(_run())
    finally:
        get_settings.cache_clear()

    assert status_code == 403
    assert result == {"ok": False, "detail": "access denied"}


def test_wormhole_dm_compose_allows_public_degraded_and_starts_background_transport(monkeypatch):
    import auth
    import main
    from routers import wormhole as wormhole_router
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    kickoff = {"count": 0}

    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {
            "configured": False,
            "ready": False,
            "arti_ready": False,
            "rns_ready": False,
        },
    )
    monkeypatch.setattr(
        main.private_transport_manager,
        "request_warmup",
        lambda **_kwargs: kickoff.__setitem__("count", kickoff["count"] + 1) or {"status": {"label": "Preparing private lane"}},
    )
    monkeypatch.setattr(
        wormhole_router,
        "compose_wormhole_dm",
        lambda **_kwargs: {"ok": True, "ciphertext": "sealed", "format": "mls1"},
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/dm/compose",
                json={"peer_id": "bob", "peer_dh_pub": "deadbeef", "plaintext": "hello"},
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 200
    assert result == {"ok": True, "ciphertext": "sealed", "format": "mls1"}
    assert kickoff["count"] == 1


def test_scoped_gate_token_public_degraded_dm_scope_failure_is_generic(monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.config import get_settings
    from services import wormhole_supervisor

    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {
            "configured": False,
            "ready": False,
            "arti_ready": False,
            "rns_ready": False,
        },
    )
    monkeypatch.setattr(main, "_kickoff_private_control_transport_upgrade", lambda: None)
    monkeypatch.setenv("MESH_SCOPED_TOKENS", '{"gate-only":["gate"]}')
    get_settings.cache_clear()

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/dm/compose",
                json={"peer_id": "bob", "peer_dh_pub": "deadbeef", "plaintext": "blocked"},
                headers={"X-Admin-Key": "gate-only"},
            )
            return response.status_code, response.json()

    try:
        status_code, result = asyncio.run(_run())
    finally:
        get_settings.cache_clear()

    assert status_code == 403
    assert result == {"ok": False, "detail": "access denied"}


def test_wormhole_gate_proof_failure_is_generic(tmp_path, monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_gate_mls, mesh_secure_storage, mesh_wormhole_persona

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
    monkeypatch.setattr(
        main,
        "_sign_gate_access_proof",
        lambda *_args, **_kwargs: {"ok": False, "detail": "gate_access_proof_failed"},
    )

    async def _run():
        async with AsyncClient(
            transport=ASGITransport(app=main.app, client=("127.0.0.1", 54321)),
            base_url="http://test",
        ) as ac:
            response = await ac.post("/api/wormhole/gate/proof", json={"gate_id": "infonet"})
            return response.status_code, response.json()

    status_code, result = asyncio.run(_run())

    assert status_code == 403
    assert result == {"ok": False, "detail": "access denied"}
