import time

import pytest


@pytest.fixture()
def contacts_env(tmp_path, monkeypatch):
    from services.mesh import mesh_secure_storage, mesh_wormhole_contacts

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    mesh_secure_storage._MASTER_KEY_CACHE = None
    mesh_secure_storage._DOMAIN_KEY_CACHE.clear()
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    return mesh_wormhole_contacts


def _invite_payload(*, trust_fingerprint: str) -> dict:
    now = int(time.time())
    return {
        "trust_fingerprint": trust_fingerprint,
        "identity_dh_pub_key": "dhpub-invite",
        "dh_algo": "X25519",
        "prekey_lookup_handle": "handle-123",
        "issued_at": now,
        "expires_at": now + 3600,
        "public_key": "sign-pub",
        "public_key_algo": "Ed25519",
    }


def _admin_override():
    return None


def test_generic_contact_upsert_ignores_trust_anchor_promotion(contacts_env):
    contact = contacts_env.upsert_wormhole_dm_contact(
        "peer-alpha",
        {
            "alias": "alpha",
            "blocked": True,
            "dhPubKey": "dhpub-alpha",
            "verify_inband": True,
            "verify_registry": True,
            "verified": True,
            "verified_at": 999,
            "trust_level": "sas_verified",
            "invitePinnedTrustFingerprint": "ff" * 32,
            "invitePinnedNodeId": "!forged",
            "invitePinnedAt": 999,
            "remotePrekeyFingerprint": "aa" * 32,
            "remotePrekeyObservedFingerprint": "bb" * 32,
            "remotePrekeyPinnedAt": 123,
            "remotePrekeyLastSeenAt": 456,
            "remotePrekeySequence": 7,
            "remotePrekeySignedAt": 8,
            "remotePrekeyMismatch": True,
        },
    )

    assert contact["alias"] == "alpha"
    assert contact["blocked"] is True
    assert contact["dhPubKey"] == "dhpub-alpha"
    assert contact["verify_inband"] is False
    assert contact["verify_registry"] is False
    assert contact["verified"] is False
    assert contact["verified_at"] == 0
    assert contact["trust_level"] == "unpinned"
    assert contact["trustSummary"]["state"] == "unpinned"
    assert contact["invitePinnedTrustFingerprint"] == ""
    assert contact["invitePinnedNodeId"] == ""
    assert contact["invitePinnedAt"] == 0
    assert contact["remotePrekeyFingerprint"] == ""
    assert contact["remotePrekeyObservedFingerprint"] == ""
    assert contact["remotePrekeyPinnedAt"] == 0
    assert contact["remotePrekeySequence"] == 0
    assert contact["remotePrekeyMismatch"] is False


def test_generic_contact_upsert_preserves_authoritative_tofu_anchor(contacts_env):
    observed = contacts_env.observe_remote_prekey_identity("peer-bravo", fingerprint="11" * 32)

    contact = contacts_env.upsert_wormhole_dm_contact(
        "peer-bravo",
        {
            "alias": "bravo",
            "trust_level": "sas_verified",
            "remotePrekeyFingerprint": "22" * 32,
            "remotePrekeyObservedFingerprint": "22" * 32,
            "remotePrekeyPinnedAt": 999,
            "remotePrekeySequence": 99,
            "remotePrekeySignedAt": 999,
            "remotePrekeyMismatch": True,
        },
    )

    assert observed["trust_level"] == "tofu_pinned"
    assert contact["alias"] == "bravo"
    assert contact["trust_level"] == "tofu_pinned"
    assert contact["trustSummary"]["state"] == "tofu_pinned"
    assert contact["remotePrekeyFingerprint"] == "11" * 32
    assert contact["remotePrekeyObservedFingerprint"] == "11" * 32
    assert contact["remotePrekeyPinnedAt"] > 0
    assert contact["remotePrekeySequence"] == 0
    assert contact["remotePrekeyMismatch"] is False


def test_generic_contact_upsert_preserves_authoritative_invite_pin(contacts_env):
    pinned = contacts_env.pin_wormhole_dm_invite(
        "peer-charlie",
        invite_payload=_invite_payload(trust_fingerprint="33" * 32),
        alias="charlie",
        attested=True,
    )

    contact = contacts_env.upsert_wormhole_dm_contact(
        "peer-charlie",
        {
            "alias": "charlie-2",
            "trust_level": "unpinned",
            "invitePinnedTrustFingerprint": "44" * 32,
            "invitePinnedNodeId": "!forged",
            "invitePinnedAt": 1,
            "remotePrekeyFingerprint": "44" * 32,
            "remotePrekeyObservedFingerprint": "44" * 32,
        },
    )

    assert pinned["trust_level"] == "invite_pinned"
    assert contact["alias"] == "charlie-2"
    assert contact["trust_level"] == "invite_pinned"
    assert contact["trustSummary"]["state"] == "invite_pinned"
    assert contact["invitePinnedTrustFingerprint"] == "33" * 32
    assert contact["invitePinnedNodeId"] == "peer-charlie"
    assert contact["invitePinnedAt"] > 0
    assert contact["remotePrekeyFingerprint"] == "33" * 32
    assert contact["remotePrekeyObservedFingerprint"] == "33" * 32


def test_http_dm_contact_put_ignores_trust_anchor_mutation(contacts_env):
    from auth import require_admin
    from fastapi.testclient import TestClient
    import main

    main.app.dependency_overrides[require_admin] = _admin_override
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        response = client.put(
            "/api/wormhole/dm/contact",
            json={
                "peer_id": "peer-http",
                "contact": {
                    "alias": "http-contact",
                    "blocked": True,
                    "dhPubKey": "forged-dh",
                    "verify_inband": True,
                    "verify_registry": True,
                    "verified": True,
                    "verified_at": 777,
                    "trust_level": "invite_pinned",
                    "invitePinnedTrustFingerprint": "55" * 32,
                    "remotePrekeyFingerprint": "66" * 32,
                    "remotePrekeyObservedFingerprint": "77" * 32,
                },
            },
        )
        data = response.json()
    finally:
        main.app.dependency_overrides.pop(require_admin, None)

    assert data["ok"] is True
    assert data["contact"]["alias"] == "http-contact"
    assert data["contact"]["blocked"] is True
    assert data["contact"]["dhPubKey"] == "forged-dh"
    assert data["contact"]["verify_inband"] is False
    assert data["contact"]["verify_registry"] is False
    assert data["contact"]["verified"] is False
    assert data["contact"]["verified_at"] == 0
    assert data["contact"]["trust_level"] == "unpinned"
    assert data["contact"]["trustSummary"]["state"] == "unpinned"
    assert data["contact"]["invitePinnedTrustFingerprint"] == ""
    assert data["contact"]["remotePrekeyFingerprint"] == ""
    assert data["contact"]["remotePrekeyObservedFingerprint"] == ""
