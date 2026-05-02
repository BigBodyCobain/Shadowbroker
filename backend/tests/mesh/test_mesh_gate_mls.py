import asyncio
import base64
import json


def _embedded_gate_event_wire_size(gate_mls_mod, persona_id: str, gate_id: str, plaintext: str) -> int:
    from services.mesh.mesh_hashchain import build_gate_wire_ref
    from services.mesh.mesh_rns import RNSMessage

    binding = gate_mls_mod._sync_binding(gate_id)
    member = binding.members[persona_id]
    proof = {
        "proof_version": "embedded-proof-v1",
        "node_id": "!sb_embeddedproof",
        "public_key": "A" * 44,
        "public_key_algo": "Ed25519",
        "sequence": 7,
        "protocol_version": "infonet/2",
        "content_hash": "b" * 64,
        "transport_hash": "c" * 64,
        "signature": "d" * 128,
    }
    plaintext_with_proof = json.dumps(
        {
            "m": plaintext,
            "e": int(binding.epoch),
            "proof": proof,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    ciphertext = gate_mls_mod._privacy_client().encrypt_group_message(
        member.group_handle,
        plaintext_with_proof.encode("utf-8"),
    )
    padded = gate_mls_mod._pad_ciphertext_raw(ciphertext)
    event = {
        "gate_contract_version": "gate-v2-embedded-origin-v1",
        "event_type": "gate_message",
        "timestamp": 1710000000,
        "event_id": "e" * 64,
        "payload": {
            "ciphertext": gate_mls_mod._b64(padded),
            "format": gate_mls_mod.MLS_GATE_FORMAT,
            "nonce": "n" * 16,
            "sender_ref": "s" * 16,
            "epoch": int(binding.epoch),
        },
    }
    event["payload"]["gate_ref"] = build_gate_wire_ref(
        gate_id, event, peer_url="https://test.local"
    )
    return len(
        RNSMessage(
            msg_type="gate_event",
            body={"event": event},
            meta={"message_id": "mid", "dandelion": {"phase": "stem", "hops": 0, "max_hops": 3}},
        ).encode()
    )


class _TestGateManager:
    """Minimal gate manager stub that returns a fixed per-gate secret."""

    _SECRET = "test-gate-secret-for-envelope-encryption"

    def get_gate_secret(self, gate_id: str) -> str:
        return self._SECRET

    def get_envelope_policy(self, gate_id: str) -> str:
        return "envelope_recovery"

    def can_enter(self, sender_id: str, gate_id: str):
        return True, "ok"

    def record_message(self, gate_id: str):
        pass


def _fresh_gate_state(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.config import get_settings
    from services.mesh import mesh_gate_mls, mesh_reputation, mesh_secure_storage, mesh_wormhole_persona

    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE", "true")
    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", "true")
    get_settings.cache_clear()
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
    mesh_gate_mls.reset_gate_mls_state()
    return mesh_gate_mls, mesh_wormhole_persona


def test_gate_message_schema_accepts_mls1_format():
    from services.mesh.mesh_protocol import normalize_payload
    from services.mesh.mesh_schema import validate_event_payload

    payload = normalize_payload(
        "gate_message",
        {
            "gate": "infonet",
            "epoch": 1,
            "ciphertext": "ZmFrZQ==",
            "nonce": "bWxzMS1lbnZlbG9wZQ==",
            "sender_ref": "persona-1",
            "format": "mls1",
        },
    )

    assert validate_event_payload("gate_message", payload) == (True, "ok")


def test_sender_ref_is_stable_for_same_identity_and_nonce():
    from services.mesh import mesh_gate_mls

    identity = {"persona_id": "persona-alpha", "node_id": "!sb_unused"}
    seed = mesh_gate_mls._sender_ref_seed(identity)

    first = mesh_gate_mls._sender_ref(seed, "nonce-stable-1")
    second = mesh_gate_mls._sender_ref(seed, "nonce-stable-1")

    assert first
    assert first == second
    assert len(first) == 16


def test_sender_ref_changes_across_nonce_and_identity_boundaries():
    from services.mesh import mesh_gate_mls

    first_seed = mesh_gate_mls._sender_ref_seed({"persona_id": "persona-alpha"})
    second_seed = mesh_gate_mls._sender_ref_seed({"persona_id": "persona-beta"})

    same_identity_base = mesh_gate_mls._sender_ref(first_seed, "nonce-one")
    same_identity_other_nonce = mesh_gate_mls._sender_ref(first_seed, "nonce-two")
    other_identity_same_nonce = mesh_gate_mls._sender_ref(second_seed, "nonce-one")

    assert same_identity_base != same_identity_other_nonce
    assert same_identity_base != other_identity_same_nonce


def test_compose_and_decrypt_gate_message_round_trip_via_mls(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("finance", label="scribe")

    composed = gate_mls_mod.compose_encrypted_gate_message("finance", "hello mls gate")
    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id="finance",
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
    )

    assert composed["ok"] is True
    assert composed["format"] == "mls1"
    assert composed["ciphertext"] != "hello mls gate"
    assert decrypted == {
        "ok": True,
        "gate_id": "finance",
        "epoch": 1,
        "plaintext": "hello mls gate",
        "identity_scope": "persona",
    }


def test_decrypt_gate_message_recovers_hidden_reply_to_from_ciphertext(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "finance"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    sender = persona_mod.create_gate_persona(gate_id, label="sender")
    receiver = persona_mod.create_gate_persona(gate_id, label="receiver")

    persona_mod.activate_gate_persona(gate_id, sender["identity"]["persona_id"])
    composed = gate_mls_mod.compose_encrypted_gate_message(
        gate_id,
        "hello hidden thread",
        reply_to="evt-parent-hidden",
    )

    persona_mod.activate_gate_persona(gate_id, receiver["identity"]["persona_id"])
    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
    )

    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "hello hidden thread"
    assert decrypted["reply_to"] == "evt-parent-hidden"


def test_export_gate_state_snapshot_returns_opaque_state_only(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("finance", label="scribe")
    composed = gate_mls_mod.compose_encrypted_gate_message("finance", "opaque export")

    snapshot = gate_mls_mod.export_gate_state_snapshot("finance")

    assert composed["ok"] is True
    assert snapshot["ok"] is True
    assert snapshot["gate_id"] == "finance"
    assert int(snapshot["epoch"]) >= 1
    assert isinstance(snapshot["members"], list) and snapshot["members"]
    assert all(int(member["group_handle"]) > 0 for member in snapshot["members"])
    assert "rust_state_blob_b64" in snapshot and snapshot["rust_state_blob_b64"]
    assert base64.b64decode(snapshot["rust_state_blob_b64"])
    serialized = json.dumps(snapshot)
    assert "opaque export" not in serialized
    assert "gate_envelope" not in serialized


def test_export_gate_state_snapshot_includes_active_member_metadata(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    created = persona_mod.create_gate_persona("finance", label="scribe")

    snapshot = gate_mls_mod.export_gate_state_snapshot("finance")

    assert snapshot["ok"] is True
    assert snapshot["active_identity_scope"] == "persona"
    assert snapshot["active_persona_id"] == created["identity"]["persona_id"]
    assert snapshot["active_node_id"] == created["identity"]["node_id"]


def test_sign_encrypted_gate_message_returns_ciphertext_only_signature_surface(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("finance", label="scribe")
    composed = gate_mls_mod.compose_encrypted_gate_message("finance", "native sign target")

    signed = gate_mls_mod.sign_encrypted_gate_message(
        gate_id="finance",
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce="native-sign-nonce",
    )

    assert signed["ok"] is True
    assert signed["gate_id"] == "finance"
    assert signed["ciphertext"] == composed["ciphertext"]
    assert signed["nonce"] == "native-sign-nonce"
    assert signed["reply_to"] == ""
    assert signed["sender_ref"]
    assert "native sign target" not in json.dumps(signed)


def test_sign_encrypted_gate_message_rejects_cleartext_reply_to_without_compat(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("finance", label="scribe")
    composed = gate_mls_mod.compose_encrypted_gate_message("finance", "native sign target")

    signed = gate_mls_mod.sign_encrypted_gate_message(
        gate_id="finance",
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce="native-sign-nonce",
        reply_to="evt-parent-1",
    )

    assert signed == {
        "ok": False,
        "detail": "gate_encrypted_reply_to_hidden_required",
        "gate_id": "finance",
        "compat_reply_to": False,
    }


def test_sign_encrypted_gate_message_allows_cleartext_reply_to_in_explicit_compat_mode(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("finance", label="scribe")
    composed = gate_mls_mod.compose_encrypted_gate_message("finance", "native sign target")

    signed = gate_mls_mod.sign_encrypted_gate_message(
        gate_id="finance",
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce="native-sign-nonce",
        reply_to="evt-parent-1",
        compat_reply_to=True,
    )

    assert signed["ok"] is True
    assert signed["reply_to"] == "evt-parent-1"


def test_sign_encrypted_gate_message_rejects_stale_epoch(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("finance", label="scribe")
    composed = gate_mls_mod.compose_encrypted_gate_message("finance", "stale epoch")

    signed = gate_mls_mod.sign_encrypted_gate_message(
        gate_id="finance",
        epoch=int(composed["epoch"]) + 1,
        ciphertext=str(composed["ciphertext"]),
        nonce="native-sign-stale",
    )

    assert signed == {
        "ok": False,
        "detail": "gate_state_stale",
        "gate_id": "finance",
        "current_epoch": int(composed["epoch"]),
    }


def test_sign_encrypted_gate_message_with_recovery_plaintext_produces_envelope(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("finance", label="scribe")
    composed = gate_mls_mod.compose_encrypted_gate_message("finance", "recoverable payload")

    signed = gate_mls_mod.sign_encrypted_gate_message(
        gate_id="finance",
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce="native-sign-nonce",
        recovery_plaintext="recoverable payload",
    )

    assert signed["ok"] is True
    assert signed["gate_envelope"]
    assert signed["envelope_hash"]
    assert "recoverable payload" not in json.dumps(signed)


def test_compose_refuses_recoverable_gate_without_envelope(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("finance", label="scribe")

    def fail_encrypt(*_args, **_kwargs):
        raise gate_mls_mod.GateSecretUnavailableError("missing test secret")

    monkeypatch.setattr(gate_mls_mod, "_gate_envelope_encrypt", fail_encrypt)

    composed = gate_mls_mod.compose_encrypted_gate_message("finance", "must not become sealed")

    assert composed == {
        "ok": False,
        "detail": "gate_envelope_required",
        "gate_id": "finance",
    }


def test_local_operator_gate_mutation_routes_include_state_snapshot(tmp_path, monkeypatch):
    import auth
    import main
    from httpx import ASGITransport, AsyncClient

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    persona_mod.bootstrap_wormhole_persona_state(force=True)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            created = await ac.post(
                "/api/wormhole/gate/persona/create",
                json={"gate_id": "finance", "label": "scribe"},
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            rotated = await ac.post(
                "/api/wormhole/gate/key/rotate",
                json={"gate_id": "finance", "reason": "unit_test"},
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return created.json(), rotated.json()

    try:
        created, rotated = asyncio.run(_run())
    finally:
        gate_mls_mod.reset_gate_mls_state()

    assert created["ok"] is True
    assert created["gate_state_snapshot"]["ok"] is True
    assert created["gate_state_snapshot"]["gate_id"] == "finance"
    assert int(created["gate_state_snapshot"]["epoch"]) >= 1

    assert rotated["ok"] is True
    assert rotated["gate_state_snapshot"]["ok"] is True
    assert rotated["gate_state_snapshot"]["gate_id"] == "finance"
    assert int(rotated["gate_state_snapshot"]["epoch"]) >= int(
        created["gate_state_snapshot"]["epoch"]
    )


def test_anonymous_gate_session_can_compose_and_decrypt_round_trip(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.enter_gate_anonymously("finance", rotate=True)

    status = gate_mls_mod.get_local_gate_key_status("finance")
    composed = gate_mls_mod.compose_encrypted_gate_message("finance", "hello from anonymous gate")
    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id="finance",
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
    )

    assert status["ok"] is True
    assert status["identity_scope"] == "anonymous"
    assert status["has_local_access"] is True
    assert composed["ok"] is True
    assert composed["identity_scope"] == "anonymous"
    assert decrypted == {
        "ok": True,
        "gate_id": "finance",
        "epoch": 1,
        "plaintext": "hello from anonymous gate",
        "identity_scope": "anonymous",
    }


def test_self_echo_decrypt_uses_local_plaintext_cache_fast_path(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("finance", label="scribe")
    composed = gate_mls_mod.compose_encrypted_gate_message("finance", "cache hit")

    def fail_sync(_gate_id: str):
        raise AssertionError("self-echo cache should bypass MLS sync/decrypt")

    monkeypatch.setattr(gate_mls_mod, "_sync_binding", fail_sync)

    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id="finance",
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
    )

    assert decrypted == {
        "ok": True,
        "gate_id": "finance",
        "epoch": 1,
        "plaintext": "cache hit",
        "identity_scope": "persona",
    }


def test_ordinary_gate_decrypt_does_not_stamp_plaintext_by_default(tmp_path, monkeypatch):
    from services.mesh import mesh_hashchain

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "finance"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    sender = persona_mod.create_gate_persona(gate_id, label="sender")
    receiver = persona_mod.create_gate_persona(gate_id, label="receiver")

    persona_mod.activate_gate_persona(gate_id, sender["identity"]["persona_id"])
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "no durable plaintext")

    stored = mesh_hashchain.gate_store.append(
        gate_id,
        {
            "event_type": "gate_message",
            "timestamp": 1,
            "payload": {
                "gate": gate_id,
                "ciphertext": composed["ciphertext"],
                "nonce": composed["nonce"],
                "sender_ref": composed["sender_ref"],
                "format": composed["format"],
            },
        },
    )

    persona_mod.activate_gate_persona(gate_id, receiver["identity"]["persona_id"])
    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
        event_id=str(stored["event_id"]),
    )

    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "no durable plaintext"
    assert mesh_hashchain.gate_store.lookup_local_plaintext(gate_id, stored["event_id"]) is None
    persisted = mesh_hashchain.gate_store.get_event(stored["event_id"])
    assert persisted is not None
    assert "_local_plaintext" not in (persisted.get("payload") or {})


def test_recovery_envelope_read_decrypts_without_plaintext_persistence(tmp_path, monkeypatch):
    from services.mesh import mesh_hashchain

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "finance"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona(gate_id, label="sender")
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "recovery plaintext")

    stored = mesh_hashchain.gate_store.append(
        gate_id,
        {
            "event_type": "gate_message",
            "timestamp": 1,
            "payload": {
                "gate": gate_id,
                "ciphertext": composed["ciphertext"],
                "nonce": composed["nonce"],
                "sender_ref": composed["sender_ref"],
                "format": composed["format"],
                "gate_envelope": composed.get("gate_envelope", ""),
                "envelope_hash": composed.get("envelope_hash", ""),
            },
        },
    )

    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        gate_envelope=str(composed.get("gate_envelope", "") or ""),
        envelope_hash=str(composed.get("envelope_hash", "") or ""),
        recovery_envelope=True,
        event_id=str(stored["event_id"]),
    )

    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "recovery plaintext"
    assert mesh_hashchain.gate_store.lookup_local_plaintext(gate_id, stored["event_id"]) is None


def test_gate_plaintext_persist_opt_in_is_retired_no_plaintext_stamp(tmp_path, monkeypatch):
    from services.config import get_settings
    from services.mesh import mesh_hashchain

    monkeypatch.setenv("MESH_GATE_PLAINTEXT_PERSIST", "true")
    monkeypatch.setenv("MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE", "true")
    get_settings.cache_clear()

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "finance"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    sender = persona_mod.create_gate_persona(gate_id, label="sender")
    receiver = persona_mod.create_gate_persona(gate_id, label="receiver")

    persona_mod.activate_gate_persona(gate_id, sender["identity"]["persona_id"])
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "persisted plaintext")

    stored = mesh_hashchain.gate_store.append(
        gate_id,
        {
            "event_type": "gate_message",
            "timestamp": 1,
            "payload": {
                "gate": gate_id,
                "ciphertext": composed["ciphertext"],
                "nonce": composed["nonce"],
                "sender_ref": composed["sender_ref"],
                "format": composed["format"],
            },
        },
    )

    persona_mod.activate_gate_persona(gate_id, receiver["identity"]["persona_id"])
    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
        event_id=str(stored["event_id"]),
    )

    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "persisted plaintext"
    assert mesh_hashchain.gate_store.lookup_local_plaintext(gate_id, stored["event_id"]) is None
    get_settings.cache_clear()


def test_verifier_open_does_not_require_active_gate_persona(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "finance"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = persona_mod.create_gate_persona(gate_id, label="first")
    second = persona_mod.create_gate_persona(gate_id, label="second")

    persona_mod.activate_gate_persona(gate_id, first["identity"]["persona_id"])
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "verifier open")
    assert composed["ok"] is True

    persona_mod.enter_gate_anonymously(gate_id, rotate=True)

    opened = gate_mls_mod.open_gate_ciphertext_for_verifier(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        format=str(composed["format"]),
    )

    assert opened["ok"] is True
    assert opened["plaintext"] == "verifier open"
    assert opened["identity_scope"] == "verifier"
    assert opened["opened_by_persona_id"] in {
        first["identity"]["persona_id"],
        second["identity"]["persona_id"],
    }


def test_verifier_open_does_not_use_self_echo_cache(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "finance"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = persona_mod.create_gate_persona(gate_id, label="first")
    second = persona_mod.create_gate_persona(gate_id, label="second")

    persona_mod.activate_gate_persona(gate_id, first["identity"]["persona_id"])
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "no cache authority")
    assert composed["ok"] is True

    monkeypatch.setattr(
        gate_mls_mod,
        "_peek_cached_plaintext",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("verifier must not peek cache")),
    )
    monkeypatch.setattr(
        gate_mls_mod,
        "_consume_cached_plaintext",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("verifier must not consume cache")),
    )
    monkeypatch.setattr(gate_mls_mod, "_active_gate_persona", lambda *_args, **_kwargs: None)

    opened = gate_mls_mod.open_gate_ciphertext_for_verifier(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        format=str(composed["format"]),
    )

    assert opened == {
        "ok": True,
        "gate_id": gate_id,
        "epoch": 1,
        "plaintext": "no cache authority",
        "opened_by_persona_id": second["identity"]["persona_id"],
        "identity_scope": "verifier",
    }


def test_removed_member_cannot_decrypt_new_messages(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "opsec-lab"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = persona_mod.create_gate_persona(gate_id, label="first")
    second = persona_mod.create_gate_persona(gate_id, label="second")

    persona_mod.activate_gate_persona(gate_id, first["identity"]["persona_id"])
    before_removal = gate_mls_mod.compose_encrypted_gate_message(gate_id, "before removal")

    persona_mod.activate_gate_persona(gate_id, second["identity"]["persona_id"])
    readable_before = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(before_removal["epoch"]),
        ciphertext=str(before_removal["ciphertext"]),
        nonce=str(before_removal["nonce"]),
        sender_ref=str(before_removal["sender_ref"]),
    )

    persona_mod.retire_gate_persona(gate_id, second["identity"]["persona_id"])
    persona_mod.activate_gate_persona(gate_id, first["identity"]["persona_id"])
    after_removal = gate_mls_mod.compose_encrypted_gate_message(gate_id, "after removal")

    persona_mod.enter_gate_anonymously(gate_id, rotate=True)
    blocked_after = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(after_removal["epoch"]),
        ciphertext=str(after_removal["ciphertext"]),
        nonce=str(after_removal["nonce"]),
        sender_ref=str(after_removal["sender_ref"]),
    )

    assert readable_before["ok"] is True
    assert readable_before["plaintext"] == "before removal"
    assert blocked_after == {
        "ok": True,
        "gate_id": gate_id,
        "epoch": int(after_removal["epoch"]),
        "plaintext": "after removal",
        "identity_scope": "anonymous",
    }


def test_gate_mls_state_survives_simulated_restart(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "infonet"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = persona_mod.create_gate_persona(gate_id, label="first")
    second = persona_mod.create_gate_persona(gate_id, label="second")

    persona_mod.activate_gate_persona(gate_id, first["identity"]["persona_id"])
    initial = gate_mls_mod.compose_encrypted_gate_message(gate_id, "before restart")

    gate_mls_mod.reset_gate_mls_state()

    persona_mod.activate_gate_persona(gate_id, first["identity"]["persona_id"])
    after_restart = gate_mls_mod.compose_encrypted_gate_message(gate_id, "after restart")

    persona_mod.activate_gate_persona(gate_id, second["identity"]["persona_id"])
    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(after_restart["epoch"]),
        ciphertext=str(after_restart["ciphertext"]),
        nonce=str(after_restart["nonce"]),
        sender_ref=str(after_restart["sender_ref"]),
    )

    assert initial["ok"] is True
    assert after_restart["ok"] is True
    assert after_restart["epoch"] == initial["epoch"]
    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "after restart"


def test_pre_restart_gate_message_fails_to_decrypt_after_reset(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "restart-blackout"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = persona_mod.create_gate_persona(gate_id, label="first")
    second = persona_mod.create_gate_persona(gate_id, label="second")

    persona_mod.activate_gate_persona(gate_id, first["identity"]["persona_id"])
    before_reset = gate_mls_mod.compose_encrypted_gate_message(gate_id, "before reset")
    assert before_reset["ok"] is True

    persona_mod.activate_gate_persona(gate_id, second["identity"]["persona_id"])
    readable_before = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(before_reset["epoch"]),
        ciphertext=str(before_reset["ciphertext"]),
        nonce=str(before_reset["nonce"]),
        sender_ref=str(before_reset["sender_ref"]),
    )
    assert readable_before["ok"] is True
    assert readable_before["plaintext"] == "before reset"

    gate_mls_mod.reset_gate_mls_state()

    persona_mod.activate_gate_persona(gate_id, second["identity"]["persona_id"])
    blocked_after = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(before_reset["epoch"]),
        ciphertext=str(before_reset["ciphertext"]),
        nonce=str(before_reset["nonce"]),
        sender_ref=str(before_reset["sender_ref"]),
    )

    assert blocked_after == {
        "ok": False,
        "detail": "gate_mls_decrypt_failed",
    }


def test_embedded_proof_budget_exceeds_rns_limit_before_6144_bucket_for_large_messages(tmp_path, monkeypatch):
    from services.config import get_settings

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "budget-gate"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = persona_mod.create_gate_persona(gate_id, label="first")
    persona_id = first["identity"]["persona_id"]
    persona_mod.activate_gate_persona(gate_id, persona_id)

    medium_wire = _embedded_gate_event_wire_size(gate_mls_mod, persona_id, gate_id, "x" * 1000)
    large_wire = _embedded_gate_event_wire_size(gate_mls_mod, persona_id, gate_id, "x" * 2000)

    assert medium_wire < get_settings().MESH_RNS_MAX_PAYLOAD
    assert large_wire > get_settings().MESH_RNS_MAX_PAYLOAD


def test_sync_binding_skips_persist_when_membership_is_unchanged(tmp_path, monkeypatch):
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "quiet-room"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = persona_mod.create_gate_persona(gate_id, label="first")
    second = persona_mod.create_gate_persona(gate_id, label="second")

    persona_mod.activate_gate_persona(gate_id, first["identity"]["persona_id"])
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "steady state")

    persist_calls = []
    original_persist = gate_mls_mod._persist_binding

    def track_persist(binding):
        persist_calls.append(binding.gate_id)
        return original_persist(binding)

    monkeypatch.setattr(gate_mls_mod, "_persist_binding", track_persist)
    persona_mod.activate_gate_persona(gate_id, second["identity"]["persona_id"])

    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
    )

    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "steady state"
    assert persist_calls == []


def test_tampered_binding_is_rejected_on_sync(tmp_path, monkeypatch, caplog):
    from services.mesh.mesh_local_custody import read_sensitive_domain_json, write_sensitive_domain_json
    import logging

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "cryptography"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona = persona_mod.create_gate_persona(gate_id, label="scribe")
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "tamper target")
    assert composed["ok"] is True

    stored = read_sensitive_domain_json(
        gate_mls_mod.STATE_DOMAIN,
        gate_mls_mod.STATE_FILENAME,
        gate_mls_mod._default_binding_store,
        custody_scope=gate_mls_mod.STATE_CUSTODY_SCOPE,
    )
    persona_id = persona["identity"]["persona_id"]
    stored["gates"][gate_id]["members"][persona_id]["binding_signature"] = "00" * 64
    write_sensitive_domain_json(
        gate_mls_mod.STATE_DOMAIN,
        gate_mls_mod.STATE_FILENAME,
        stored,
        custody_scope=gate_mls_mod.STATE_CUSTODY_SCOPE,
    )

    gate_mls_mod.reset_gate_mls_state()
    with caplog.at_level(logging.WARNING):
        retry = gate_mls_mod.compose_encrypted_gate_message(gate_id, "should rebuild")

    assert retry["ok"] is True
    assert "corrupted binding for gate#" in caplog.text.lower()
    assert "member persona#" in caplog.text.lower()


def test_mls_compose_allows_public_degraded_for_local_preparation(tmp_path, monkeypatch):
    from services import wormhole_supervisor

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("finance", label="scribe")
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "public_degraded")

    result = gate_mls_mod.compose_encrypted_gate_message("finance", "prepare locally")

    assert result["ok"] is True
    assert result["format"] == "mls1"
    assert result["ciphertext"]
    assert result["sender_id"]


def test_backend_local_gate_compose_post_encrypt_before_storage_but_mls_decrypt_stays_retired(
    tmp_path, monkeypatch
):
    import main
    import auth
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "infonet"
    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona(gate_id, label="scribe")
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)

    admin_headers = {"X-Admin-Key": auth._current_admin_key()}
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "field report")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            compose_response = await ac.post(
                "/api/wormhole/gate/message/compose",
                json={"gate_id": gate_id, "plaintext": "field report", "compat_plaintext": True},
                headers=admin_headers,
            )
            send_response = await ac.post(
                "/api/wormhole/gate/message/post",
                json={"gate_id": gate_id, "plaintext": "field report", "compat_plaintext": True},
                headers=admin_headers,
            )
            decrypt_response = await ac.post(
                "/api/wormhole/gate/message/decrypt",
                json={
                    "gate_id": gate_id,
                    "epoch": composed["epoch"],
                    "ciphertext": composed["ciphertext"],
                    "nonce": composed["nonce"],
                    "sender_ref": composed["sender_ref"],
                    "format": composed["format"],
                    "compat_decrypt": True,
                },
                headers=admin_headers,
            )
            return compose_response.json(), send_response.json(), decrypt_response.json()

    try:
        compose_result, send_result, decrypt_result = asyncio.run(_run())
    finally:
        gate_mls_mod.reset_gate_mls_state()

    assert compose_result["ok"] is True
    assert compose_result["gate_id"] == gate_id
    assert compose_result["ciphertext"]
    assert compose_result["gate_envelope"]
    assert send_result["ok"] is True
    assert send_result["gate_id"] == gate_id
    assert decrypt_result == {
        "ok": False,
        "detail": "gate_backend_decrypt_recovery_only",
        "gate_id": gate_id,
        "compat_requested": True,
        "compat_effective": False,
    }


def test_backend_gate_decrypt_requires_recovery_for_mls_payloads(tmp_path, monkeypatch):
    import main
    import auth
    from routers import wormhole as wormhole_router
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "decrypt-policy-lab"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona(gate_id, label="scribe")
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "compat must be explicit")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/message/decrypt",
                json={
                    "gate_id": gate_id,
                    "epoch": composed["epoch"],
                    "ciphertext": composed["ciphertext"],
                    "nonce": composed["nonce"],
                    "sender_ref": composed["sender_ref"],
                    "format": composed["format"],
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    try:
        result = asyncio.run(_run())
    finally:
        gate_mls_mod.reset_gate_mls_state()

    assert result == {
        "ok": False,
        "detail": "gate_backend_decrypt_recovery_only",
        "gate_id": gate_id,
        "compat_requested": False,
        "compat_effective": False,
    }


def test_backend_gate_plaintext_compose_is_local_only(tmp_path, monkeypatch):
    import main
    import auth
    from routers import wormhole as wormhole_router
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "plaintext-policy-lab"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona(gate_id, label="scribe")
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/message/compose",
                json={
                    "gate_id": gate_id,
                    "plaintext": "compat must be explicit",
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    try:
        result = asyncio.run(_run())
    finally:
        gate_mls_mod.reset_gate_mls_state()

    assert result["ok"] is True
    assert result["gate_id"] == gate_id
    assert result["ciphertext"]
    assert result["gate_envelope"]


def test_backend_encrypted_gate_sign_requires_hidden_reply_to_or_explicit_compat(tmp_path, monkeypatch):
    import auth
    import main
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "encrypted-reply-guard-lab"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona(gate_id, label="scribe")
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "hidden reply_to only")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            blocked = await ac.post(
                "/api/wormhole/gate/message/sign-encrypted",
                json={
                    "gate_id": gate_id,
                    "epoch": composed["epoch"],
                    "ciphertext": composed["ciphertext"],
                    "nonce": "native-sign-nonce",
                    "reply_to": "evt-parent-1",
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            allowed = await ac.post(
                "/api/wormhole/gate/message/sign-encrypted",
                json={
                    "gate_id": gate_id,
                    "epoch": composed["epoch"],
                    "ciphertext": composed["ciphertext"],
                    "nonce": "native-sign-nonce-compat",
                    "reply_to": "evt-parent-1",
                    "compat_reply_to": True,
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return blocked.json(), allowed.json()

    try:
        blocked, allowed = asyncio.run(_run())
    finally:
        gate_mls_mod.reset_gate_mls_state()

    assert blocked == {
        "ok": False,
        "detail": "gate_encrypted_reply_to_hidden_required",
        "gate_id": gate_id,
        "compat_reply_to": False,
    }
    assert allowed["ok"] is True
    assert allowed["reply_to"] == "evt-parent-1"


def test_backend_encrypted_gate_post_requires_hidden_reply_to_or_explicit_compat(tmp_path, monkeypatch):
    import auth
    import main
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "encrypted-post-guard-lab"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona(gate_id, label="scribe")
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "hidden reply_to only")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
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
                    "reply_to": "evt-parent-1",
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    try:
        result = asyncio.run(_run())
    finally:
        gate_mls_mod.reset_gate_mls_state()

    assert result == {
        "ok": False,
        "detail": "gate_encrypted_reply_to_hidden_required",
        "gate_id": gate_id,
        "compat_reply_to": False,
    }


def test_receive_only_mls_decrypt_locks_gate_format(tmp_path, monkeypatch):
    from services.mesh.mesh_secure_storage import read_domain_json, write_domain_json

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "receive-only-lab"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = persona_mod.create_gate_persona(gate_id, label="sender")
    second = persona_mod.create_gate_persona(gate_id, label="receiver")

    persona_mod.activate_gate_persona(gate_id, first["identity"]["persona_id"])
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "receiver should lock gate")

    stored = read_domain_json(
        gate_mls_mod.STATE_DOMAIN,
        gate_mls_mod.STATE_FILENAME,
        gate_mls_mod._default_binding_store,
    )
    stored.setdefault("gate_format_locks", {}).pop(gate_id, None)
    write_domain_json(gate_mls_mod.STATE_DOMAIN, gate_mls_mod.STATE_FILENAME, stored)

    assert gate_mls_mod.is_gate_locked_to_mls(gate_id) is True

    persona_mod.activate_gate_persona(gate_id, second["identity"]["persona_id"])
    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
    )

    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "receiver should lock gate"
    assert gate_mls_mod.is_gate_locked_to_mls(gate_id) is True


def test_mls_locked_gate_rejects_legacy_g1_decrypt(tmp_path, monkeypatch):
    import main
    import auth
    from httpx import ASGITransport, AsyncClient
    from services import wormhole_supervisor

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "lockout-lab"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona(gate_id, label="scribe")
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )

    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "mls only")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/wormhole/gate/message/decrypt",
                json={
                    "gate_id": gate_id,
                    "epoch": composed["epoch"],
                    "ciphertext": composed["ciphertext"],
                    "nonce": composed["nonce"],
                    "sender_ref": composed["sender_ref"],
                    "format": "g1",
                },
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    try:
        result = asyncio.run(_run())
    finally:
        gate_mls_mod.reset_gate_mls_state()

    assert composed["ok"] is True
    assert gate_mls_mod.is_gate_locked_to_mls(gate_id) is True
    assert result == {
        "ok": False,
        "detail": "gate is locked to MLS format",
        "gate_id": gate_id,
        "required_format": "mls1",
        "current_format": "g1",
    }
