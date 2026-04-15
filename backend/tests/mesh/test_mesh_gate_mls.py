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
    event["payload"]["gate_ref"] = build_gate_wire_ref(gate_id, event)
    return len(
        RNSMessage(
            msg_type="gate_event",
            body={"event": event},
            meta={"message_id": "mid", "dandelion": {"phase": "stem", "hops": 0, "max_hops": 3}},
        ).encode()
    )


def _fresh_gate_state(tmp_path, monkeypatch):
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
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
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
    from services.mesh.mesh_secure_storage import read_domain_json, write_domain_json
    import logging

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "cryptography"

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona = persona_mod.create_gate_persona(gate_id, label="scribe")
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "tamper target")
    assert composed["ok"] is True

    stored = read_domain_json(
        gate_mls_mod.STATE_DOMAIN,
        gate_mls_mod.STATE_FILENAME,
        gate_mls_mod._default_binding_store,
    )
    persona_id = persona["identity"]["persona_id"]
    stored["gates"][gate_id]["members"][persona_id]["binding_signature"] = "00" * 64
    write_domain_json(gate_mls_mod.STATE_DOMAIN, gate_mls_mod.STATE_FILENAME, stored)

    gate_mls_mod.reset_gate_mls_state()
    with caplog.at_level(logging.WARNING):
        retry = gate_mls_mod.compose_encrypted_gate_message(gate_id, "should rebuild")

    assert retry["ok"] is True
    assert "corrupted binding for gate#" in caplog.text.lower()
    assert "member persona#" in caplog.text.lower()


def test_mls_compose_refuses_public_degraded_transport(tmp_path, monkeypatch):
    from services import wormhole_supervisor

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("finance", label="scribe")
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "public_degraded")

    result = gate_mls_mod.compose_encrypted_gate_message("finance", "should fail closed")

    assert result == {
        "ok": False,
        "detail": "MLS gate compose requires PRIVATE transport tier",
    }


def test_compose_endpoint_can_use_mls_without_changing_gate_post_envelope(tmp_path, monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_hashchain, mesh_reputation
    from services import wormhole_supervisor

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona("infonet", label="scribe")
    monkeypatch.setattr(main, "_debug_mode_enabled", lambda: True)

    class _Ledger:
        def __init__(self):
            self.registered = []

        def register_node(self, *args):
            self.registered.append(args)

    class _GateManager:
        def __init__(self):
            self.recorded = []
            self.enter_checks = []

        def can_enter(self, sender_id, gate_id):
            self.enter_checks.append((sender_id, gate_id))
            return True, "ok"

        def record_message(self, gate_id):
            self.recorded.append(gate_id)

    fake_ledger = _Ledger()
    fake_gate_manager = _GateManager()
    append_calls = []

    def fake_append(gate_id, event):
        append_calls.append({"gate_id": gate_id, "event": event})
        return event

    admin_headers = {"X-Admin-Key": main._current_admin_key()}
    monkeypatch.setattr(main, "_preflight_signed_event_integrity", lambda **_: (True, "ok"))
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setattr(mesh_reputation, "reputation_ledger", fake_ledger, raising=False)
    monkeypatch.setattr(mesh_reputation, "gate_manager", fake_gate_manager, raising=False)
    monkeypatch.setattr(mesh_hashchain.gate_store, "append", fake_append)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            compose_response = await ac.post(
                "/api/wormhole/gate/message/compose",
                json={"gate_id": "infonet", "plaintext": "field report"},
                headers=admin_headers,
            )
            composed = compose_response.json()
            send_response = await ac.post(
                "/api/wormhole/gate/message/post",
                json={"gate_id": "infonet", "plaintext": "field report"},
                headers=admin_headers,
            )
            decrypt_response = await ac.post(
                "/api/wormhole/gate/message/decrypt",
                json={
                    "gate_id": "infonet",
                    "epoch": composed["epoch"],
                    "ciphertext": composed["ciphertext"],
                    "nonce": composed["nonce"],
                    "sender_ref": composed["sender_ref"],
                    "format": composed["format"],
                },
                headers=admin_headers,
            )
            return composed, send_response.json(), decrypt_response.json()

    try:
        composed, sent, decrypted = asyncio.run(_run())
    finally:
        gate_mls_mod.reset_gate_mls_state()

    assert composed["ok"] is True
    assert composed["format"] == "mls1"
    assert len(base64.b64decode(composed["nonce"])) == 12
    assert sent["ok"] is True
    assert sent["detail"] == "Message posted to gate 'infonet'"
    assert sent["gate_id"] == "infonet"
    assert sent["event_id"] == append_calls[0]["event"]["event_id"]
    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "field report"
    assert fake_gate_manager.enter_checks == [(append_calls[0]["event"]["node_id"], "infonet")]
    assert fake_gate_manager.recorded == ["infonet"]
    assert fake_ledger.registered == [
        (
            append_calls[0]["event"]["node_id"],
            append_calls[0]["event"]["public_key"],
            append_calls[0]["event"]["public_key_algo"],
        )
    ]
    assert append_calls[0]["gate_id"] == "infonet"
    assert append_calls[0]["event"]["payload"]["gate"] == "infonet"
    assert append_calls[0]["event"]["payload"]["format"] == "mls1"
    assert append_calls[0]["event"]["payload"]["ciphertext"]
    assert append_calls[0]["event"]["payload"]["nonce"]
    assert append_calls[0]["event"]["payload"]["sender_ref"]


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
                headers={"X-Admin-Key": main._current_admin_key()},
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
