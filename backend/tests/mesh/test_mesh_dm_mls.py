import asyncio
import time

REQUEST_CLAIMS = [{"type": "requests", "token": "request-claim-token"}]


def _fresh_dm_mls_state(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import mesh_dm_mls, mesh_dm_relay, mesh_secure_storage, mesh_wormhole_persona

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(mesh_dm_mls, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_mls, "STATE_FILE", tmp_path / "wormhole_dm_mls.json")
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(
        mesh_dm_mls,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)
    mesh_dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=True)
    return mesh_dm_mls, relay


def test_dm_mls_initiate_accept_encrypt_decrypt_round_trip(tmp_path, monkeypatch):
    dm_mls, _relay = _fresh_dm_mls_state(tmp_path, monkeypatch)

    bob_bundle = dm_mls.export_dm_key_package_for_alias("bob")
    assert bob_bundle["ok"] is True
    assert bob_bundle["welcome_dh_pub"]

    initiated = dm_mls.initiate_dm_session("alice", "bob", bob_bundle)
    assert initiated["ok"] is True
    assert initiated["welcome"]

    accepted = dm_mls.accept_dm_session("bob", "alice", initiated["welcome"])
    assert accepted["ok"] is True

    encrypted = dm_mls.encrypt_dm("alice", "bob", "hello bob")
    assert encrypted["ok"] is True
    decrypted = dm_mls.decrypt_dm("bob", "alice", encrypted["ciphertext"], encrypted["nonce"])
    assert decrypted == {
        "ok": True,
        "plaintext": "hello bob",
        "session_id": accepted["session_id"],
        "nonce": encrypted["nonce"],
    }

    encrypted_back = dm_mls.encrypt_dm("bob", "alice", "hello alice")
    assert encrypted_back["ok"] is True
    decrypted_back = dm_mls.decrypt_dm(
        "alice",
        "bob",
        encrypted_back["ciphertext"],
        encrypted_back["nonce"],
    )
    assert decrypted_back["ok"] is True
    assert decrypted_back["plaintext"] == "hello alice"


def test_dm_mls_lock_rejects_legacy_dm1_decrypt(tmp_path, monkeypatch):
    import main

    dm_mls, _relay = _fresh_dm_mls_state(tmp_path, monkeypatch)

    bob_bundle = dm_mls.export_dm_key_package_for_alias("bob")
    initiated = dm_mls.initiate_dm_session("alice", "bob", bob_bundle)
    accepted = dm_mls.accept_dm_session("bob", "alice", initiated["welcome"])
    assert accepted["ok"] is True

    encrypted = dm_mls.encrypt_dm("alice", "bob", "lock me in")
    assert encrypted["ok"] is True

    first_decrypt = main.decrypt_wormhole_dm_envelope(
        peer_id="alice-agent",
        local_alias="bob",
        remote_alias="alice",
        ciphertext=encrypted["ciphertext"],
        payload_format="mls1",
        nonce=encrypted["nonce"],
    )
    assert first_decrypt["ok"] is True
    assert dm_mls.is_dm_locked_to_mls("bob", "alice") is True

    locked = main.decrypt_wormhole_dm_envelope(
        peer_id="alice-agent",
        local_alias="bob",
        remote_alias="alice",
        ciphertext="legacy-ciphertext",
        payload_format="dm1",
        nonce="legacy-nonce",
    )
    assert locked == {
        "ok": False,
        "detail": "DM session is locked to MLS format",
        "required_format": "mls1",
        "current_format": "dm1",
    }


def test_dm_mls_refuses_public_degraded_transport(tmp_path, monkeypatch):
    dm_mls, _relay = _fresh_dm_mls_state(tmp_path, monkeypatch)

    monkeypatch.setattr(
        dm_mls,
        "get_wormhole_state",
        lambda: {"configured": False, "ready": False, "rns_ready": False},
    )

    result = dm_mls.initiate_dm_session(
        "alice",
        "bob",
        {"mls_key_package": "ZmFrZQ=="},
    )

    assert result == {"ok": False, "detail": "DM MLS requires PRIVATE transport tier"}


def test_dm_mls_session_persistence_survives_same_process_restart(tmp_path, monkeypatch):
    dm_mls, _relay = _fresh_dm_mls_state(tmp_path, monkeypatch)

    bob_bundle = dm_mls.export_dm_key_package_for_alias("bob")
    initiated = dm_mls.initiate_dm_session("alice", "bob", bob_bundle)
    accepted = dm_mls.accept_dm_session("bob", "alice", initiated["welcome"])

    dm_mls.reset_dm_mls_state(clear_privacy_core=False, clear_persistence=False)

    encrypted = dm_mls.encrypt_dm("alice", "bob", "persisted hello")
    assert encrypted["ok"] is True
    decrypted = dm_mls.decrypt_dm("bob", "alice", encrypted["ciphertext"], encrypted["nonce"])
    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "persisted hello"
    assert decrypted["session_id"] == accepted["session_id"]


def test_dm_mls_encrypt_detects_stale_session_after_privacy_core_reset(tmp_path, monkeypatch):
    dm_mls, _relay = _fresh_dm_mls_state(tmp_path, monkeypatch)

    bob_bundle = dm_mls.export_dm_key_package_for_alias("bob")
    initiated = dm_mls.initiate_dm_session("alice", "bob", bob_bundle)
    accepted = dm_mls.accept_dm_session("bob", "alice", initiated["welcome"])
    assert accepted["ok"] is True

    dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=False)

    expired = dm_mls.encrypt_dm("alice", "bob", "stale handle")
    assert expired == {
        "ok": False,
        "detail": "session_expired",
        "session_id": "alice::bob",
    }
    assert dm_mls.has_dm_session("alice", "bob") == {
        "ok": True,
        "exists": False,
        "session_id": "alice::bob",
    }


def test_dm_mls_recreates_alias_identity_when_binding_proof_is_tampered(tmp_path, monkeypatch, caplog):
    import logging

    from services.mesh.mesh_secure_storage import read_domain_json, write_domain_json

    dm_mls, _relay = _fresh_dm_mls_state(tmp_path, monkeypatch)

    first_bundle = dm_mls.export_dm_key_package_for_alias("alice")
    assert first_bundle["ok"] is True

    stored = read_domain_json(dm_mls.STATE_DOMAIN, dm_mls.STATE_FILENAME, dm_mls._default_state)
    original_handle = int(stored["aliases"]["alice"]["handle"])
    stored["aliases"]["alice"]["binding_proof"] = "00" * 64
    write_domain_json(dm_mls.STATE_DOMAIN, dm_mls.STATE_FILENAME, stored)

    dm_mls.reset_dm_mls_state(clear_privacy_core=False, clear_persistence=False)

    with caplog.at_level(logging.WARNING):
        second_bundle = dm_mls.export_dm_key_package_for_alias("alice")

    reloaded = read_domain_json(dm_mls.STATE_DOMAIN, dm_mls.STATE_FILENAME, dm_mls._default_state)
    assert second_bundle["ok"] is True
    assert "dm mls alias binding invalid for alice" in caplog.text.lower()
    assert int(reloaded["aliases"]["alice"]["handle"]) != original_handle


def test_dm_mls_http_compose_store_poll_decrypt_round_trip(tmp_path, monkeypatch):
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_hashchain
    from services import wormhole_supervisor

    dm_mls, relay = _fresh_dm_mls_state(tmp_path, monkeypatch)
    bob_bundle = dm_mls.export_dm_key_package_for_alias("bob")
    assert bob_bundle["ok"] is True

    monkeypatch.setattr(main, "_current_admin_key", lambda: "test-admin")
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "_verify_dm_mailbox_request",
        lambda **_kwargs: (
            True,
            "ok",
            {"mailbox_claims": REQUEST_CLAIMS},
        ),
    )
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(
        dm_mls,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(mesh_hashchain.infonet, "validate_and_set_sequence", lambda *_args, **_kwargs: (True, "ok"))

    admin_headers = {"X-Admin-Key": main._current_admin_key()}

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            now = int(time.time())
            compose_response = await ac.post(
                "/api/wormhole/dm/compose",
                json={
                    "peer_id": "bob-agent",
                    "plaintext": "hello through http",
                    "local_alias": "alice",
                    "remote_alias": "bob",
                    "remote_prekey_bundle": bob_bundle,
                },
                headers=admin_headers,
            )
            composed = compose_response.json()
            send_response = await ac.post(
                "/api/mesh/dm/send",
                json={
                    "sender_id": "alice-agent",
                    "recipient_id": "bob-agent",
                    "delivery_class": "request",
                    "ciphertext": composed["ciphertext"],
                        "format": composed["format"],
                        "session_welcome": composed["session_welcome"],
                        "msg_id": "dm-mls-http-1",
                        "timestamp": now,
                        "nonce": "http-mls-nonce-1",
                        "public_key": "cHVi",
                        "public_key_algo": "Ed25519",
                    "signature": "sig",
                    "sequence": 11,
                    "protocol_version": "infonet/2",
                },
            )
            poll_response = await ac.post(
                "/api/mesh/dm/poll",
                    json={
                        "agent_id": "bob-agent",
                        "mailbox_claims": REQUEST_CLAIMS,
                        "timestamp": now + 1,
                        "nonce": "http-mls-nonce-2",
                        "public_key": "cHVi",
                        "public_key_algo": "Ed25519",
                    "signature": "sig",
                    "sequence": 12,
                    "protocol_version": "infonet/2",
                },
            )
            polled = poll_response.json()
            decrypt_response = await ac.post(
                "/api/wormhole/dm/decrypt",
                json={
                    "peer_id": "alice-agent",
                    "local_alias": "bob",
                    "remote_alias": "alice",
                    "ciphertext": polled["messages"][0]["ciphertext"],
                    "format": polled["messages"][0]["format"],
                    "nonce": "",
                    "session_welcome": polled["messages"][0]["session_welcome"],
                },
                headers=admin_headers,
            )
            return composed, send_response.json(), polled, decrypt_response.json()

    composed, sent, polled, decrypted = asyncio.run(_run())

    assert composed["ok"] is True
    assert composed["format"] == "mls1"
    assert sent["ok"] is True
    assert sent["msg_id"] == "dm-mls-http-1"
    assert polled["ok"] is True
    assert polled["count"] == 1
    assert polled["messages"][0]["format"] == "mls1"
    assert polled["messages"][0]["session_welcome"] == composed["session_welcome"]
    assert decrypted == {
        "ok": True,
        "peer_id": "alice-agent",
        "local_alias": "bob",
        "remote_alias": "alice",
        "plaintext": "hello through http",
        "format": "mls1",
    }
    assert relay.count_claims("bob-agent", REQUEST_CLAIMS) == 0
