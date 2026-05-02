"""S14A SAS Re-Pin Guard.

Tests:
- tofu_pinned still upgrades to sas_verified
- sas_verified idempotence does not regress
- confirm on mismatch rejects with trust_level and does not mutate state
- confirm on continuity_broken rejects with trust_level and does not mutate state
- acknowledgment on mismatch re-pins observed fingerprint and downgrades to tofu_pinned
- acknowledgment on continuity_broken re-pins observed fingerprint and downgrades to tofu_pinned
- acknowledgment rejects stable-root mismatch and forces recover-root / invite replacement
- after acknowledgment, confirm can promote tofu_pinned -> sas_verified again
- acknowledgment rejects when there is no observed changed fingerprint
- live admin HTTP confirm path reflects the new rejection behavior
- live admin HTTP acknowledgment path works
- do not overclaim that old trust is preserved; this is an explicit reset to new TOFU-pinned state
"""

from unittest.mock import patch

# ── Helpers ──────────────────────────────────────────────────────────────

_CONTACTS: dict[str, dict] = {}


def _fake_read_contacts():
    return dict(_CONTACTS)


def _fake_write_contacts(contacts):
    global _CONTACTS
    _CONTACTS = dict(contacts)


def _patch_io():
    return (
        patch("services.mesh.mesh_wormhole_contacts._read_contacts", side_effect=_fake_read_contacts),
        patch("services.mesh.mesh_wormhole_contacts._write_contacts", side_effect=_fake_write_contacts),
    )


def _patch_expected_sas_phrase(phrase: str = "able acid") -> patch:
    return patch(
        "services.mesh.mesh_wormhole_contacts._derive_expected_contact_sas_phrase",
        return_value={"ok": True, "phrase": phrase, "peer_ref": "peer", "words": len(str(phrase).split())},
    )


def _setup_contact(peer_id, **overrides):
    from services.mesh.mesh_wormhole_contacts import _normalize_contact
    base = {
        "remotePrekeyFingerprint": "aabbccdd",
        "remotePrekeyObservedFingerprint": "aabbccdd",
        "remotePrekeyPinnedAt": 1000,
        "remotePrekeyLastSeenAt": 2000,
        "trust_level": "tofu_pinned",
    }
    base.update(overrides)
    _CONTACTS[peer_id] = _normalize_contact(base)


# ── confirm_sas_verification ─────────────────────────────────────────────


def test_tofu_pinned_upgrades_to_sas_verified():
    """tofu_pinned contact should upgrade to sas_verified on confirm."""
    from services.mesh.mesh_wormhole_contacts import confirm_sas_verification

    p1, p2 = _patch_io()
    p3 = _patch_expected_sas_phrase()
    with p1, p2, p3:
        _setup_contact("peer-a", trust_level="tofu_pinned")
        result = confirm_sas_verification("peer-a", "able acid")
        assert result["ok"] is True
        assert result["trust_level"] == "sas_verified"
        assert _CONTACTS["peer-a"]["trust_level"] == "sas_verified"


def test_sas_verified_idempotent():
    """Re-confirming an already sas_verified contact should succeed (idempotent)."""
    from services.mesh.mesh_wormhole_contacts import confirm_sas_verification

    p1, p2 = _patch_io()
    p3 = _patch_expected_sas_phrase()
    with p1, p2, p3:
        _setup_contact("peer-b", trust_level="sas_verified")
        result = confirm_sas_verification("peer-b", "able acid")
        assert result["ok"] is True
        assert result["trust_level"] == "sas_verified"


def test_confirm_requires_sas_proof():
    """confirm must require an echoed SAS phrase instead of a blind trust click."""
    from services.mesh.mesh_wormhole_contacts import confirm_sas_verification

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact("peer-b2", trust_level="tofu_pinned")
        result = confirm_sas_verification("peer-b2", "")
        assert result["ok"] is False
        assert result["detail"] == "sas proof required"


def test_confirm_rejects_sas_phrase_mismatch():
    """confirm must reject the wrong SAS phrase even when trust state is otherwise valid."""
    from services.mesh.mesh_wormhole_contacts import confirm_sas_verification

    p1, p2 = _patch_io()
    p3 = _patch_expected_sas_phrase("able acid")
    with p1, p2, p3:
        _setup_contact("peer-b3", trust_level="tofu_pinned")
        result = confirm_sas_verification("peer-b3", "wrong phrase")
        assert result["ok"] is False
        assert result["detail"] == "sas phrase mismatch"
        assert _CONTACTS["peer-b3"]["trust_level"] == "tofu_pinned"


def test_confirm_rejects_mismatch():
    """confirm on mismatch must reject with trust_level and not mutate state."""
    from services.mesh.mesh_wormhole_contacts import confirm_sas_verification

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-c",
            trust_level="mismatch",
            remotePrekeyMismatch=True,
            remotePrekeyFingerprint="old-fp",
            remotePrekeyObservedFingerprint="new-fp",
        )
        result = confirm_sas_verification("peer-c", "able acid")
        assert result["ok"] is False
        assert result["trust_level"] == "mismatch"
        assert "mismatch" in result["detail"]
        # State must not be mutated
        assert _CONTACTS["peer-c"]["trust_level"] == "mismatch"
        assert _CONTACTS["peer-c"]["remotePrekeyMismatch"] is True


def test_confirm_rejects_continuity_broken():
    """confirm on continuity_broken must reject with trust_level and not mutate state."""
    from services.mesh.mesh_wormhole_contacts import confirm_sas_verification

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-d",
            trust_level="continuity_broken",
            remotePrekeyMismatch=True,
            remotePrekeyFingerprint="old-fp",
            remotePrekeyObservedFingerprint="new-fp",
        )
        result = confirm_sas_verification("peer-d", "able acid")
        assert result["ok"] is False
        assert result["trust_level"] == "continuity_broken"
        assert "continuity_broken" in result["detail"]
        # State must not be mutated
        assert _CONTACTS["peer-d"]["trust_level"] == "continuity_broken"
        assert _CONTACTS["peer-d"]["remotePrekeyMismatch"] is True


def test_recover_root_continuity_promotes_to_sas_verified():
    """Stable-root recovery must require continuity_broken + SAS and then adopt the observed root."""
    from services.mesh.mesh_wormhole_contacts import recover_verified_root_continuity

    p1, p2 = _patch_io()
    p3 = _patch_expected_sas_phrase()
    p4 = patch(
        "services.mesh.mesh_wormhole_prekey.fetch_dm_prekey_bundle",
        return_value={
            "ok": True,
            "agent_id": "peer-root",
            "identity_dh_pub_key": "new-dh",
            "dh_algo": "X25519",
            "public_key": "new-pub",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
            "bundle": {"identity_dh_pub_key": "new-dh"},
            "trust_fingerprint": "new-fp",
        },
    )
    p5 = patch(
        "services.mesh.mesh_wormhole_prekey.verify_bundle_root_attestation",
        return_value={
            "ok": True,
            "root_fingerprint": "root-new",
            "root_node_id": "!sb_root_new",
            "root_public_key": "root-pub-new",
            "root_public_key_algo": "Ed25519",
        },
    )
    with p1, p2, p3, p4, p5:
        _setup_contact(
            "peer-root",
            trust_level="continuity_broken",
            remotePrekeyMismatch=True,
            remotePrekeyRootMismatch=True,
            remotePrekeyFingerprint="old-fp",
            remotePrekeyObservedFingerprint="new-fp",
            remotePrekeyRootFingerprint="root-old",
            remotePrekeyObservedRootFingerprint="root-new",
            dhPubKey="old-dh",
            invitePinnedTrustFingerprint="old-fp",
            invitePinnedRootFingerprint="root-old",
            invitePinnedDhPubKey="old-dh",
            invitePinnedPrekeyLookupHandle="lookup-new",
        )
        result = recover_verified_root_continuity("peer-root", "able acid")
        assert result["ok"] is True
        assert result["trust_level"] == "sas_verified"
        assert result["detail"] == "stable root continuity recovered via SAS verification"
        c = _CONTACTS["peer-root"]
        assert c["trust_level"] == "sas_verified"
        assert c["dhPubKey"] == "new-dh"
        assert c["remotePrekeyFingerprint"] == "new-fp"
        assert c["remotePrekeyRootFingerprint"] == "root-new"
        assert c["remotePrekeyRootMismatch"] is False
        assert c["invitePinnedTrustFingerprint"] == ""
        assert c["invitePinnedRootFingerprint"] == ""
        assert c["verified"] is True


def test_recover_root_continuity_rejects_without_root_mismatch():
    from services.mesh.mesh_wormhole_contacts import recover_verified_root_continuity

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-root-noop",
            trust_level="continuity_broken",
            remotePrekeyMismatch=True,
            remotePrekeyRootMismatch=False,
            remotePrekeyFingerprint="old-fp",
            remotePrekeyObservedFingerprint="new-fp",
        )
        result = recover_verified_root_continuity("peer-root-noop", "able acid")
        assert result["ok"] is False
        assert result["trust_level"] == "continuity_broken"
        assert "stable root mismatch" in result["detail"]


# ── acknowledge_changed_fingerprint ──────────────────────────────────────


def test_acknowledge_mismatch_repins_to_tofu():
    """Acknowledgment on mismatch must re-pin observed fingerprint and set tofu_pinned."""
    from services.mesh.mesh_wormhole_contacts import acknowledge_changed_fingerprint

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-e",
            trust_level="mismatch",
            remotePrekeyMismatch=True,
            remotePrekeyFingerprint="old-fp",
            remotePrekeyObservedFingerprint="new-fp",
        )
        result = acknowledge_changed_fingerprint("peer-e")
        assert result["ok"] is True
        assert result["trust_level"] == "tofu_pinned"
        c = _CONTACTS["peer-e"]
        assert c["trust_level"] == "tofu_pinned"
        assert c["remotePrekeyFingerprint"] == "new-fp"
        assert c["remotePrekeyMismatch"] is False
        assert c["verified"] is False
        assert c["verify_inband"] is False


def test_acknowledge_continuity_broken_repins_to_tofu():
    """Acknowledgment on continuity_broken must re-pin and set tofu_pinned."""
    from services.mesh.mesh_wormhole_contacts import acknowledge_changed_fingerprint

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-f",
            trust_level="continuity_broken",
            remotePrekeyMismatch=True,
            remotePrekeyFingerprint="old-fp",
            remotePrekeyObservedFingerprint="changed-fp",
            verified=True,
            verify_inband=True,
            verified_at=9999,
        )
        result = acknowledge_changed_fingerprint("peer-f")
        assert result["ok"] is True
        assert result["trust_level"] == "tofu_pinned"
        c = _CONTACTS["peer-f"]
        assert c["remotePrekeyFingerprint"] == "changed-fp"
        assert c["verified"] is False
        assert c["verify_inband"] is False
        assert c["verified_at"] == 0


def test_acknowledge_rejects_stable_root_mismatch():
    """Changed stable roots must not fall back through the old TOFU acknowledge path."""
    from services.mesh.mesh_wormhole_contacts import acknowledge_changed_fingerprint

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-f-root",
            trust_level="continuity_broken",
            remotePrekeyMismatch=True,
            remotePrekeyRootMismatch=True,
            remotePrekeyFingerprint="old-fp",
            remotePrekeyObservedFingerprint="changed-fp",
            remotePrekeyRootFingerprint="root-old",
            remotePrekeyObservedRootFingerprint="root-new",
        )
        result = acknowledge_changed_fingerprint("peer-f-root")
        assert result["ok"] is False
        assert result["trust_level"] == "continuity_broken"
        assert "recover root continuity" in result["detail"]


def test_acknowledge_then_confirm_full_flow():
    """After acknowledgment, confirm should promote tofu_pinned -> sas_verified."""
    from services.mesh.mesh_wormhole_contacts import (
        acknowledge_changed_fingerprint,
        confirm_sas_verification,
    )

    p1, p2 = _patch_io()
    p3 = _patch_expected_sas_phrase()
    with p1, p2, p3:
        _setup_contact(
            "peer-g",
            trust_level="continuity_broken",
            remotePrekeyMismatch=True,
            remotePrekeyFingerprint="old-fp",
            remotePrekeyObservedFingerprint="new-fp",
        )
        # Confirm must fail while continuity_broken
        r1 = confirm_sas_verification("peer-g", "able acid")
        assert r1["ok"] is False

        # Acknowledge resets to tofu_pinned
        r2 = acknowledge_changed_fingerprint("peer-g")
        assert r2["ok"] is True
        assert r2["trust_level"] == "tofu_pinned"

        # Now confirm succeeds
        r3 = confirm_sas_verification("peer-g", "able acid")
        assert r3["ok"] is True
        assert r3["trust_level"] == "sas_verified"


def test_acknowledge_rejects_no_observed_fingerprint():
    """Acknowledgment must reject when no observed fingerprint exists."""
    from services.mesh.mesh_wormhole_contacts import acknowledge_changed_fingerprint

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-h",
            trust_level="mismatch",
            remotePrekeyMismatch=True,
            remotePrekeyObservedFingerprint="",
        )
        result = acknowledge_changed_fingerprint("peer-h")
        assert result["ok"] is False
        assert "no observed fingerprint" in result["detail"]


def test_acknowledge_rejects_tofu_pinned():
    """Acknowledgment must reject when trust is tofu_pinned (not mismatch/broken)."""
    from services.mesh.mesh_wormhole_contacts import acknowledge_changed_fingerprint

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact("peer-i", trust_level="tofu_pinned")
        result = acknowledge_changed_fingerprint("peer-i")
        assert result["ok"] is False
        assert "tofu_pinned" in result["detail"]


def test_acknowledge_rejects_sas_verified():
    """Acknowledgment must reject when trust is sas_verified (not mismatch/broken)."""
    from services.mesh.mesh_wormhole_contacts import acknowledge_changed_fingerprint

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact("peer-j", trust_level="sas_verified")
        result = acknowledge_changed_fingerprint("peer-j")
        assert result["ok"] is False


# ── HTTP endpoints ───────────────────────────────────────────────────────


def _admin_override():
    """No-op admin dependency for testing."""
    return None


def test_http_confirm_rejects_mismatch():
    """Live HTTP confirm endpoint must reflect the new rejection behavior."""
    from fastapi.testclient import TestClient
    from auth import require_admin
    import main

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-http-m",
            trust_level="mismatch",
            remotePrekeyMismatch=True,
            remotePrekeyFingerprint="old",
            remotePrekeyObservedFingerprint="new",
        )
        main.app.dependency_overrides[require_admin] = _admin_override
        try:
            client = TestClient(main.app, raise_server_exceptions=False)
            resp = client.post(
                "/api/wormhole/dm/sas/confirm",
                json={"peer_id": "peer-http-m", "sas_phrase": "able acid"},
            )
            data = resp.json()
            assert data["ok"] is False
            assert data["trust_level"] == "mismatch"
        finally:
            main.app.dependency_overrides.pop(require_admin, None)


def test_http_confirm_rejects_continuity_broken():
    """Live HTTP confirm endpoint must reject continuity_broken."""
    from fastapi.testclient import TestClient
    from auth import require_admin
    import main

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-http-cb",
            trust_level="continuity_broken",
            remotePrekeyMismatch=True,
            remotePrekeyFingerprint="old",
            remotePrekeyObservedFingerprint="new",
        )
        main.app.dependency_overrides[require_admin] = _admin_override
        try:
            client = TestClient(main.app, raise_server_exceptions=False)
            resp = client.post(
                "/api/wormhole/dm/sas/confirm",
                json={"peer_id": "peer-http-cb", "sas_phrase": "able acid"},
            )
            data = resp.json()
            assert data["ok"] is False
            assert data["trust_level"] == "continuity_broken"
        finally:
            main.app.dependency_overrides.pop(require_admin, None)


def test_http_confirm_requires_sas_proof():
    """Live HTTP confirm endpoint must reject a missing SAS phrase."""
    from fastapi.testclient import TestClient
    from auth import require_admin
    import main

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact("peer-http-proof", trust_level="tofu_pinned")
        main.app.dependency_overrides[require_admin] = _admin_override
        try:
            client = TestClient(main.app, raise_server_exceptions=False)
            resp = client.post(
                "/api/wormhole/dm/sas/confirm",
                json={"peer_id": "peer-http-proof"},
            )
            data = resp.json()
            assert data["ok"] is False
            assert data["detail"] == "sas proof required"
        finally:
            main.app.dependency_overrides.pop(require_admin, None)


def test_http_confirm_rejects_sas_phrase_mismatch():
    """Live HTTP confirm endpoint must verify the echoed SAS phrase server-side."""
    from fastapi.testclient import TestClient
    from auth import require_admin
    import main

    p1, p2 = _patch_io()
    p3 = _patch_expected_sas_phrase("able acid")
    with p1, p2, p3:
        _setup_contact("peer-http-proof-mismatch", trust_level="tofu_pinned")
        main.app.dependency_overrides[require_admin] = _admin_override
        try:
            client = TestClient(main.app, raise_server_exceptions=False)
            resp = client.post(
                "/api/wormhole/dm/sas/confirm",
                json={"peer_id": "peer-http-proof-mismatch", "sas_phrase": "wrong phrase"},
            )
            data = resp.json()
            assert data["ok"] is False
            assert data["detail"] == "sas phrase mismatch"
        finally:
            main.app.dependency_overrides.pop(require_admin, None)


def test_http_acknowledge_endpoint_exists():
    """The acknowledge endpoint must exist in main app."""
    import main

    paths = [r.path for r in main.app.routes if hasattr(r, "path")]
    assert "/api/wormhole/dm/sas/acknowledge" in paths
    assert "/api/wormhole/dm/sas/recover-root" in paths


def test_http_acknowledge_works():
    """Live HTTP acknowledge endpoint must re-pin and return tofu_pinned."""
    from fastapi.testclient import TestClient
    from auth import require_admin
    import main

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-http-ack",
            trust_level="continuity_broken",
            remotePrekeyMismatch=True,
            remotePrekeyFingerprint="old",
            remotePrekeyObservedFingerprint="new",
        )
        main.app.dependency_overrides[require_admin] = _admin_override
        try:
            client = TestClient(main.app, raise_server_exceptions=False)
            resp = client.post(
                "/api/wormhole/dm/sas/acknowledge",
                json={"peer_id": "peer-http-ack"},
            )
            data = resp.json()
            assert data["ok"] is True
            assert data["trust_level"] == "tofu_pinned"
        finally:
            main.app.dependency_overrides.pop(require_admin, None)


def test_http_acknowledge_requires_admin():
    """Acknowledge endpoint must require admin auth."""
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app, raise_server_exceptions=False)
    resp = client.post(
        "/api/wormhole/dm/sas/acknowledge",
        json={"peer_id": "any-peer"},
    )
    # Without admin auth, should get 401 or 403
    assert resp.status_code in (401, 403)


def test_http_recover_root_continuity_works():
    """Live HTTP recover-root endpoint must adopt the observed root only after SAS."""
    from fastapi.testclient import TestClient
    from auth import require_admin
    import main

    p1, p2 = _patch_io()
    p3 = _patch_expected_sas_phrase()
    p4 = patch(
        "services.mesh.mesh_wormhole_prekey.fetch_dm_prekey_bundle",
        return_value={
            "ok": True,
            "agent_id": "peer-http-root",
            "identity_dh_pub_key": "new-dh",
            "dh_algo": "X25519",
            "public_key": "new-pub",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
            "bundle": {"identity_dh_pub_key": "new-dh"},
            "trust_fingerprint": "new-fp",
        },
    )
    p5 = patch(
        "services.mesh.mesh_wormhole_prekey.verify_bundle_root_attestation",
        return_value={
            "ok": True,
            "root_fingerprint": "root-new",
            "root_node_id": "!sb_root_new",
            "root_public_key": "root-pub-new",
            "root_public_key_algo": "Ed25519",
        },
    )
    with p1, p2, p3, p4, p5:
        _setup_contact(
            "peer-http-root",
            trust_level="continuity_broken",
            remotePrekeyMismatch=True,
            remotePrekeyRootMismatch=True,
            remotePrekeyFingerprint="old-fp",
            remotePrekeyObservedFingerprint="new-fp",
            remotePrekeyRootFingerprint="root-old",
            remotePrekeyObservedRootFingerprint="root-new",
            dhPubKey="old-dh",
            invitePinnedTrustFingerprint="old-fp",
            invitePinnedRootFingerprint="root-old",
            invitePinnedDhPubKey="old-dh",
            invitePinnedPrekeyLookupHandle="lookup-new",
        )
        main.app.dependency_overrides[require_admin] = _admin_override
        try:
            client = TestClient(main.app, raise_server_exceptions=False)
            resp = client.post(
                "/api/wormhole/dm/sas/recover-root",
                json={"peer_id": "peer-http-root", "sas_phrase": "able acid"},
            )
            data = resp.json()
            assert data["ok"] is True
            assert data["trust_level"] == "sas_verified"
            assert data["contact"]["remotePrekeyRootFingerprint"] == "root-new"
        finally:
            main.app.dependency_overrides.pop(require_admin, None)


# ── No overclaim ─────────────────────────────────────────────────────────


def test_acknowledge_is_reset_not_preservation():
    """Acknowledgment resets to new TOFU-pinned state — old trust is NOT preserved.
    The old pinned fingerprint is gone. verified_at is cleared. This is explicit."""
    from services.mesh.mesh_wormhole_contacts import acknowledge_changed_fingerprint

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-k",
            trust_level="continuity_broken",
            remotePrekeyMismatch=True,
            remotePrekeyFingerprint="original-fp",
            remotePrekeyObservedFingerprint="replacement-fp",
            verified=True,
            verify_inband=True,
            verified_at=5000,
        )
        result = acknowledge_changed_fingerprint("peer-k")
        assert result["ok"] is True
        c = _CONTACTS["peer-k"]
        # Old fingerprint is gone
        assert c["remotePrekeyFingerprint"] == "replacement-fp"
        assert c["remotePrekeyFingerprint"] != "original-fp"
        # Verified state is cleared
        assert c["verified"] is False
        assert c["verified_at"] == 0
        # Trust is tofu_pinned, NOT sas_verified
        assert c["trust_level"] == "tofu_pinned"


def test_confirm_no_fingerprint_still_rejected():
    """Confirm must still reject contacts with no pinned fingerprint at all."""
    from services.mesh.mesh_wormhole_contacts import confirm_sas_verification

    p1, p2 = _patch_io()
    with p1, p2:
        _setup_contact(
            "peer-l",
            trust_level="unpinned",
            remotePrekeyFingerprint="",
        )
        result = confirm_sas_verification("peer-l", "able acid")
        assert result["ok"] is False
        assert "no pinned fingerprint" in result["detail"]
