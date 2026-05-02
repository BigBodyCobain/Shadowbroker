import asyncio
import copy
import time

from services.config import get_settings

REQUEST_CLAIMS = [{"type": "requests", "token": "request-claim-token"}]


def _fresh_dm_mls_state(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import (
        mesh_dm_mls,
        mesh_dm_relay,
        mesh_private_outbox,
        mesh_private_release_worker,
        mesh_private_transport_manager,
        mesh_relay_policy,
        mesh_secure_storage,
        mesh_wormhole_persona,
    )

    outbox_store = {}
    relay_policy_store = {}

    def _read_outbox_json(_domain, _filename, default_factory, **_kwargs):
        payload = outbox_store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_outbox_json(_domain, _filename, payload, **_kwargs):
        outbox_store["payload"] = copy.deepcopy(payload)

    def _read_relay_policy_json(_domain, _filename, default_factory, **_kwargs):
        payload = relay_policy_store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_relay_policy_json(_domain, _filename, payload, **_kwargs):
        relay_policy_store["payload"] = copy.deepcopy(payload)

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
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_strong")
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)
    monkeypatch.setattr(mesh_private_outbox, "read_sensitive_domain_json", _read_outbox_json)
    monkeypatch.setattr(mesh_private_outbox, "write_sensitive_domain_json", _write_outbox_json)
    monkeypatch.setattr(mesh_relay_policy, "read_sensitive_domain_json", _read_relay_policy_json)
    monkeypatch.setattr(mesh_relay_policy, "write_sensitive_domain_json", _write_relay_policy_json)
    mesh_private_release_worker.reset_private_release_worker_for_tests()
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_transport_manager.reset_private_transport_manager_for_tests()
    mesh_relay_policy.reset_relay_policy_for_tests()
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


def test_legacy_dm1_decrypt_requires_migration_override(tmp_path, monkeypatch):
    import main
    from services import wormhole_supervisor

    _fresh_dm_mls_state(tmp_path, monkeypatch)
    monkeypatch.delenv("MESH_ALLOW_LEGACY_DM1_UNTIL", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "public_degraded")

    try:
        result = main.decrypt_wormhole_dm_envelope(
            peer_id="alice-agent",
            local_alias="bob",
            remote_alias="alice",
            ciphertext="legacy-ciphertext",
            payload_format="dm1",
            nonce="legacy-nonce",
        )
    finally:
        get_settings.cache_clear()

    assert result == {
        "ok": False,
        "detail": "legacy dm1 decrypt disabled; migrate peer to MLS",
    }


def test_dm_mls_decrypt_bootstrap_uses_local_identity_alias(tmp_path, monkeypatch):
    import main

    _fresh_dm_mls_state(tmp_path, monkeypatch)

    captured: dict[str, str] = {}

    monkeypatch.setattr(main, "has_mls_dm_session", lambda *_args, **_kwargs: {"ok": True, "exists": False})

    def _ensure(local_alias, remote_alias, welcome_b64, local_dh_secret="", identity_alias=""):
        captured["local_alias"] = local_alias
        captured["remote_alias"] = remote_alias
        captured["welcome_b64"] = welcome_b64
        captured["local_dh_secret"] = local_dh_secret
        captured["identity_alias"] = identity_alias
        return {"ok": True, "session_id": "bootstrap"}

    monkeypatch.setattr(main, "ensure_mls_dm_session", _ensure)
    monkeypatch.setattr(
        main,
        "read_wormhole_identity",
        lambda: {"node_id": "local-node-id", "dh_private_key": "local-dh-secret"},
    )
    monkeypatch.setattr(
        main,
        "decrypt_mls_dm",
        lambda *_args, **_kwargs: {"ok": True, "plaintext": "hello over bootstrap"},
    )

    result = main.decrypt_wormhole_dm_envelope(
        peer_id="alice-agent",
        local_alias="peer-smoke-alias",
        remote_alias="main-smoke-alias",
        ciphertext="ciphertext",
        payload_format="mls1",
        nonce="",
        session_welcome="welcome-b64",
    )

    assert result == {
        "ok": True,
        "peer_id": "alice-agent",
        "local_alias": "peer-smoke-alias",
        "remote_alias": "main-smoke-alias",
        "plaintext": "hello over bootstrap",
        "format": "mls1",
    }
    assert captured == {
        "local_alias": "peer-smoke-alias",
        "remote_alias": "main-smoke-alias",
        "welcome_b64": "welcome-b64",
        "local_dh_secret": "local-dh-secret",
        "identity_alias": "local-node-id",
    }


def test_dm_mls_proceeds_on_public_degraded_tier_and_queues_release(tmp_path, monkeypatch):
    """Local MLS operations must not prompt for consent on a weak tier.

    Under the Tor-style non-hostile policy (hardening follow-up), MLS session
    setup, encryption, and decryption happen locally at any tier. The only
    tier-gated operation is *network release* of the ciphertext, which the
    outbound release path queues until the floor is satisfied.
    """
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

    # Local setup must not refuse; a malformed key_package here fails for a
    # different reason, but it must NOT surface a consent-required detail.
    assert result.get("detail") != "needs_private_transport_consent"


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


def test_dm_mls_session_survives_privacy_core_reset_with_durable_state(tmp_path, monkeypatch):
    """S6A: Rust state is persisted and restored — session survives privacy-core reset."""
    dm_mls, _relay = _fresh_dm_mls_state(tmp_path, monkeypatch)

    bob_bundle = dm_mls.export_dm_key_package_for_alias("bob")
    initiated = dm_mls.initiate_dm_session("alice", "bob", bob_bundle)
    accepted = dm_mls.accept_dm_session("bob", "alice", initiated["welcome"])
    assert accepted["ok"] is True

    # Encrypt before restart.
    encrypted = dm_mls.encrypt_dm("alice", "bob", "durable hello")
    assert encrypted["ok"] is True

    # Reset privacy-core but keep persistence (simulates restart).
    dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=False)

    # Session must survive via Rust-state restore.
    decrypted = dm_mls.decrypt_dm("bob", "alice", encrypted["ciphertext"], encrypted["nonce"])
    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "durable hello"
    assert dm_mls.has_dm_session("alice", "bob") == {
        "ok": True,
        "exists": True,
        "session_id": "alice::bob",
    }


def test_dm_mls_recreates_alias_identity_when_binding_proof_is_tampered(tmp_path, monkeypatch, caplog):
    import logging

    from services.mesh.mesh_local_custody import (
        read_sensitive_domain_json,
        write_sensitive_domain_json,
    )

    dm_mls, _relay = _fresh_dm_mls_state(tmp_path, monkeypatch)

    first_bundle = dm_mls.export_dm_key_package_for_alias("alice")
    assert first_bundle["ok"] is True

    stored = read_sensitive_domain_json(
        dm_mls.STATE_DOMAIN,
        dm_mls.STATE_FILENAME,
        dm_mls._default_state,
        custody_scope=dm_mls.STATE_CUSTODY_SCOPE,
    )
    original_handle = int(stored["aliases"]["alice"]["handle"])
    stored["aliases"]["alice"]["binding_proof"] = "00" * 64
    write_sensitive_domain_json(
        dm_mls.STATE_DOMAIN,
        dm_mls.STATE_FILENAME,
        stored,
        custody_scope=dm_mls.STATE_CUSTODY_SCOPE,
    )

    dm_mls.reset_dm_mls_state(clear_privacy_core=False, clear_persistence=False)

    with caplog.at_level(logging.WARNING):
        second_bundle = dm_mls.export_dm_key_package_for_alias("alice")

    reloaded = read_sensitive_domain_json(
        dm_mls.STATE_DOMAIN,
        dm_mls.STATE_FILENAME,
        dm_mls._default_state,
        custody_scope=dm_mls.STATE_CUSTODY_SCOPE,
    )
    assert second_bundle["ok"] is True
    assert "dm mls alias binding invalid" in caplog.text.lower()
    assert int(reloaded["aliases"]["alice"]["handle"]) != original_handle


def test_dm_mls_http_compose_store_poll_decrypt_round_trip(tmp_path, monkeypatch):
    import auth
    import main
    from httpx import ASGITransport, AsyncClient
    from services.mesh import mesh_hashchain
    from services.mesh import mesh_private_release_worker
    from services.mesh import mesh_wormhole_contacts
    from services.mesh import mesh_wormhole_sender_token
    from services import wormhole_supervisor

    dm_mls, relay = _fresh_dm_mls_state(tmp_path, monkeypatch)
    bob_bundle = dm_mls.export_dm_key_package_for_alias("bob")
    assert bob_bundle["ok"] is True

    monkeypatch.setattr(auth, "_current_admin_key", lambda: "test-admin")
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(main, "observe_remote_prekey_bundle", lambda *_args, **_kwargs: {"trust_level": "invite_pinned"})
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "verified_first_contact_requirement",
        lambda *_args, **_kwargs: {"ok": True, "trust_level": "invite_pinned"},
    )
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
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
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
    monkeypatch.setattr(
        mesh_wormhole_sender_token,
        "consume_wormhole_dm_sender_token",
        lambda **_kwargs: {
            "ok": True,
            "recipient_id": "bob-agent",
            "sender_id": "alice-agent",
            "sender_token_hash": "reqtok-dm-mls-http",
            "public_key": "cHVi",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
        },
    )
    monkeypatch.setattr(
        main,
        "consume_wormhole_dm_sender_token",
        lambda **_kwargs: {
            "ok": True,
            "recipient_id": "bob-agent",
            "sender_id": "alice-agent",
            "sender_token_hash": "reqtok-dm-mls-http",
            "public_key": "cHVi",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
        },
    )

    admin_headers = {"X-Admin-Key": auth._current_admin_key()}

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
            assert compose_response.status_code == 200
            assert composed["ok"] is True
            accepted = dm_mls.accept_dm_session("bob", "alice", composed["session_welcome"])
            assert accepted["ok"] is True
            send_response = await ac.post(
                "/api/mesh/dm/send",
                json={
                    "sender_id": "alice-agent",
                    "sender_token": "opaque-sender-token",
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
                    "transport_lock": "private_strong",
                },
            )
            sent = send_response.json()
            assert sent["ok"] is True
            assert sent["queued"] is True
            assert relay.count_claims("bob-agent", REQUEST_CLAIMS) == 0
            mesh_private_release_worker.private_release_worker.run_once()
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
                    "transport_lock": "private_strong",
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
            return composed, sent, polled, decrypt_response.json()

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
