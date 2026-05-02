"""Route-level verification of P2A hardened request sender blinding.

Proves that the `/api/mesh/dm/send` route path — not just `DMRelay.deposit()` —
correctly blinds relay-visible sender identity when a sender token is consumed.

Uses a real DMRelay instance to inspect actual mailbox contents after the route
deposits the message.
"""

import asyncio
import json
import time

from starlette.requests import Request

from services.config import get_settings
from services.mesh import (
    mesh_dm_relay,
    mesh_private_outbox,
    mesh_private_release_worker,
    mesh_private_transport_manager,
    mesh_relay_policy,
    mesh_secure_storage,
)


REQUEST_CLAIM = [{"type": "requests", "token": "request-claim-token"}]

# Known sender_token_hash for deterministic assertions.
_KNOWN_TOKEN_HASH = "a1b2c3d4e5f6789012345678abcdef0123456789abcdef0123456789abcdef01"


def _json_request(path: str, body: dict) -> Request:
    request_body = dict(body)
    if path == "/api/mesh/dm/send":
        request_body.setdefault("transport_lock", "private_strong")
    payload = json.dumps(request_body).encode("utf-8")
    sent = {"value": False}

    async def receive():
        if sent["value"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["value"] = True
        return {"type": "http.request", "body": payload, "more_body": False}

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


def _fake_consume_token(*, sender_token, recipient_id, delivery_class, recipient_token=""):
    """Simulate successful sender-token consumption with a known hash."""
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


def _setup_route_env(tmp_path, monkeypatch):
    """Set up a real relay and bypass route guards unrelated to blinding."""
    import main
    from services import wormhole_supervisor
    from services.mesh import mesh_hashchain, mesh_wormhole_contacts

    outbox_store = {}
    relay_policy_store = {}

    def _read_outbox_json(_domain, _filename, default_factory, **_kwargs):
        payload = outbox_store.get("payload")
        if payload is None:
            return default_factory()
        return json.loads(json.dumps(payload))

    def _write_outbox_json(_domain, _filename, payload, **_kwargs):
        outbox_store["payload"] = json.loads(json.dumps(payload))

    def _read_relay_policy_json(_domain, _filename, default_factory, **_kwargs):
        payload = relay_policy_store.get("payload")
        if payload is None:
            return default_factory()
        return json.loads(json.dumps(payload))

    def _write_relay_policy_json(_domain, _filename, payload, **_kwargs):
        relay_policy_store["payload"] = json.loads(json.dumps(payload))

    # Real relay with isolated storage.
    monkeypatch.setattr(mesh_private_outbox, "read_sensitive_domain_json", _read_outbox_json)
    monkeypatch.setattr(mesh_private_outbox, "write_sensitive_domain_json", _write_outbox_json)
    monkeypatch.setattr(mesh_relay_policy, "read_sensitive_domain_json", _read_relay_policy_json)
    monkeypatch.setattr(mesh_relay_policy, "write_sensitive_domain_json", _write_relay_policy_json)
    mesh_private_release_worker.reset_private_release_worker_for_tests()
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_transport_manager.reset_private_transport_manager_for_tests()
    mesh_relay_policy.reset_relay_policy_for_tests()
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    get_settings.cache_clear()
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)

    # Verified first contact for request delivery.
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    mesh_wormhole_contacts.observe_remote_prekey_identity("bob", fingerprint="aa" * 32)
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "_derive_expected_contact_sas_phrase",
        lambda *_args, **_kwargs: {"ok": True, "phrase": "able acid", "peer_ref": "bob", "words": 2},
    )
    mesh_wormhole_contacts.confirm_sas_verification("bob", "able acid")

    # Transport tier, signature, sequence, node-binding, secure-DM bypass.
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(main, "_verify_signed_write", lambda **kwargs: (True, ""))
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(mesh_hashchain.infonet, "validate_and_set_sequence", lambda *a, **k: (True, ""))

    from services.mesh import mesh_crypto
    monkeypatch.setattr(mesh_crypto, "verify_node_binding", lambda *a, **k: True)

    # Mock sender-token consumption to return a known hash.
    # main.py imports consume_wormhole_dm_sender_token at module level, so patch
    # the name on main directly (not on the sender_token module).
    monkeypatch.setattr(main, "consume_wormhole_dm_sender_token", _fake_consume_token)

    return relay


def _release_pending_private_dm_once():
    mesh_private_release_worker.private_release_worker.run_once()


# ---------------------------------------------------------------------------
# 1. Route-level hardened request deposits blinded sender_id
# ---------------------------------------------------------------------------


class TestRouteHardenedRequestBlinding:
    """The real `/api/mesh/dm/send` route must deposit `sender_token:{hash}`."""

    def test_hardened_request_send_deposits_blinded_sender(self, tmp_path, monkeypatch):
        """POST with sender_token → relay mailbox stores sender_token:{hash}."""
        relay = _setup_route_env(tmp_path, monkeypatch)
        import main

        req = _json_request(
            "/api/mesh/dm/send",
            {
                "sender_id": "",
                "sender_token": "opaque-sender-token",
                "recipient_id": "bob",
                "delivery_class": "request",
                "recipient_token": "",
                "ciphertext": "x3dh1:sealed-payload",
                "msg_id": "route-blind-1",
                "timestamp": int(time.time()),
                "public_key": "cHVi",
                "public_key_algo": "Ed25519",
                "signature": "sig",
                "sequence": 1,
                "protocol_version": "infonet/2",
                "sender_seal": "v3:test-seal-data",
            },
        )

        response = asyncio.run(main.dm_send(req))

        assert response["ok"] is True
        assert response["queued"] is True
        assert response["msg_id"] == "route-blind-1"
        assert relay._mailboxes == {}
        _release_pending_private_dm_once()

        # Inspect relay mailbox — sender must be blinded.
        mailbox_key = relay.mailbox_key_for_delivery(recipient_id="bob", delivery_class="request")
        stored = relay._mailboxes[mailbox_key][0]
        assert stored.sender_id == f"sender_token:{_KNOWN_TOKEN_HASH}"

    def test_hardened_request_does_not_leak_raw_sender(self, tmp_path, monkeypatch):
        """Relay-visible sender must contain zero trace of the raw sender identity."""
        relay = _setup_route_env(tmp_path, monkeypatch)
        import main

        req = _json_request(
            "/api/mesh/dm/send",
            {
                "sender_id": "",
                "sender_token": "opaque-sender-token",
                "recipient_id": "bob",
                "delivery_class": "request",
                "recipient_token": "",
                "ciphertext": "x3dh1:sealed-payload",
                "msg_id": "route-blind-2",
                "timestamp": int(time.time()),
                "public_key": "cHVi",
                "public_key_algo": "Ed25519",
                "signature": "sig",
                "sequence": 2,
                "protocol_version": "infonet/2",
                "sender_seal": "v3:test-seal-data",
            },
        )

        response = asyncio.run(main.dm_send(req))
        assert response["ok"] is True
        assert response["queued"] is True
        _release_pending_private_dm_once()

        mailbox_key = relay.mailbox_key_for_delivery(recipient_id="bob", delivery_class="request")
        stored = relay._mailboxes[mailbox_key][0]
        assert "alice" not in stored.sender_id
        assert not stored.sender_id.startswith("sealed:")

    def test_hardened_request_collected_message_is_recovery_capable(self, tmp_path, monkeypatch):
        """Collected request message retains sender_seal and blinded sender for recovery."""
        relay = _setup_route_env(tmp_path, monkeypatch)
        import main

        req = _json_request(
            "/api/mesh/dm/send",
            {
                "sender_id": "",
                "sender_token": "opaque-sender-token",
                "recipient_id": "bob",
                "delivery_class": "request",
                "recipient_token": "",
                "ciphertext": "x3dh1:sealed-payload",
                "msg_id": "route-blind-3",
                "timestamp": int(time.time()),
                "public_key": "cHVi",
                "public_key_algo": "Ed25519",
                "signature": "sig",
                "sequence": 3,
                "protocol_version": "infonet/2",
                "sender_seal": "v3:test-seal-data",
            },
        )

        response = asyncio.run(main.dm_send(req))
        assert response["ok"] is True
        assert response["queued"] is True
        _release_pending_private_dm_once()

        messages, _ = relay.collect_claims("bob", REQUEST_CLAIM)
        assert len(messages) == 1
        msg = messages[0]
        # Sender is blinded.
        assert msg["sender_id"] == f"sender_token:{_KNOWN_TOKEN_HASH}"
        # Seal is preserved for recipient-side recovery.
        assert msg["sender_seal"] == "v3:test-seal-data"
        # Raw sender does not leak.
        assert "alice" not in str(msg)

    def test_sealed_request_without_sender_token_is_rejected(self, tmp_path, monkeypatch):
        """Sealed request delivery must not fall back to the legacy unblinded path."""
        _setup_route_env(tmp_path, monkeypatch)
        import main

        req = _json_request(
            "/api/mesh/dm/send",
            {
                "sender_id": "alice",
                "recipient_id": "bob",
                "delivery_class": "request",
                "recipient_token": "",
                "ciphertext": "x3dh1:sealed-payload",
                "msg_id": "route-blind-4",
                "timestamp": int(time.time()),
                "public_key": "cHVi",
                "public_key_algo": "Ed25519",
                "signature": "sig",
                "sequence": 4,
                "protocol_version": "infonet/2",
                "sender_seal": "v3:test-seal-data",
            },
        )

        response = asyncio.run(main.dm_send(req))

        assert response["ok"] is False
        assert response["detail"] == "sender_token required for request delivery"

    def test_unsealed_request_without_sender_token_is_rejected(self, tmp_path, monkeypatch):
        """Unsealed request delivery also fails closed without sender-token blinding."""
        _setup_route_env(tmp_path, monkeypatch)
        import main

        req = _json_request(
            "/api/mesh/dm/send",
            {
                "sender_id": "alice",
                "recipient_id": "bob",
                "delivery_class": "request",
                "recipient_token": "",
                "ciphertext": "x3dh1:payload",
                "msg_id": "route-blind-5",
                "timestamp": int(time.time()),
                "public_key": "cHVi",
                "public_key_algo": "Ed25519",
                "signature": "sig",
                "sequence": 5,
                "protocol_version": "infonet/2",
            },
        )

        response = asyncio.run(main.dm_send(req))

        assert response["ok"] is False
        assert response["detail"] == "sender_token required for request delivery"
