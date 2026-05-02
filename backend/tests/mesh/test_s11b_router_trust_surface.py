"""S11B remediation: live router compose/encrypt path trust surface.

These tests exercise the router-level compose_wormhole_dm (the function
called by the actual HTTP handlers in backend/routers/wormhole.py) to
prove the live path matches the S11B contract.
"""

import pytest
from typing import Any


@pytest.fixture()
def contacts_env(tmp_path, monkeypatch):
    """Isolate contacts to a temp directory."""
    contacts_file = tmp_path / "wormhole_dm_contacts.json"
    import services.mesh.mesh_wormhole_contacts as mod
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "CONTACTS_FILE", contacts_file)
    return contacts_file


@pytest.fixture()
def stub_compose(contacts_env, monkeypatch):
    """Stub heavy crypto so we can test trust logic in isolation."""
    import main as main_mod

    monkeypatch.setattr(main_mod, "_resolve_dm_aliases", lambda **kw: ("local", "remote"))
    monkeypatch.setattr(main_mod, "has_mls_dm_session", lambda l, r: {"ok": True, "exists": True})
    monkeypatch.setattr(
        main_mod,
        "encrypt_mls_dm",
        lambda l, r, p: {"ok": True, "ciphertext": "ct", "nonce": "nc"},
    )


@pytest.fixture()
def sas_proof(monkeypatch):
    monkeypatch.setattr(
        "services.mesh.mesh_wormhole_contacts._derive_expected_contact_sas_phrase",
        lambda *_args, **_kwargs: {"ok": True, "phrase": "able acid", "peer_ref": "peer-a", "words": 2},
    )
    return "able acid"


# ── Router compose returns trust_level on success ──────────────────────


def test_router_compose_returns_trust_level_tofu(stub_compose):
    """Live router compose path must include trust_level on success."""
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity
    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")

    from routers.wormhole import compose_wormhole_dm
    result = compose_wormhole_dm(
        peer_id="peer-a",
        peer_dh_pub="fakepub",
        plaintext="hello",
    )

    assert result["ok"] is True
    assert result["trust_level"] == "tofu_pinned"


def test_router_compose_returns_trust_level_sas_verified(stub_compose, sas_proof):
    """SAS-verified contacts must show sas_verified in router compose."""
    from services.mesh.mesh_wormhole_contacts import (
        confirm_sas_verification,
        observe_remote_prekey_identity,
    )
    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")
    confirm_sas_verification("peer-a", sas_proof)

    from routers.wormhole import compose_wormhole_dm
    result = compose_wormhole_dm(
        peer_id="peer-a",
        peer_dh_pub="fakepub",
        plaintext="hello",
    )

    assert result["ok"] is True
    assert result["trust_level"] == "sas_verified"


# ── Router compose blocks mismatch with trust_level ────────────────────


def test_router_compose_blocks_mismatch(contacts_env, monkeypatch):
    """Live router path must block compose on mismatch and surface trust_level."""
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity
    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")
    observe_remote_prekey_identity("peer-a", fingerprint="11223344")

    import main as main_mod
    monkeypatch.setattr(main_mod, "_resolve_dm_aliases", lambda **kw: ("local", "remote"))
    monkeypatch.setattr(main_mod, "has_mls_dm_session", lambda l, r: {"ok": True, "exists": False})
    monkeypatch.setattr(
        main_mod,
        "fetch_dm_prekey_bundle",
        lambda pid: {
            "ok": True,
            "trust_fingerprint": "11223344",
            "mls_key_package": "",
        },
    )

    from routers.wormhole import compose_wormhole_dm
    result = compose_wormhole_dm(
        peer_id="peer-a",
        peer_dh_pub="fakepub",
        plaintext="hello",
    )

    assert result["ok"] is False
    assert result["trust_level"] == "mismatch"
    assert result.get("trust_changed") is True


# ── Router compose blocks continuity_broken with trust_level ───────────


def test_router_compose_blocks_continuity_broken(contacts_env, monkeypatch, sas_proof):
    """Live router path must block compose on continuity_broken and surface trust_level."""
    from services.mesh.mesh_wormhole_contacts import (
        confirm_sas_verification,
        observe_remote_prekey_identity,
    )
    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")
    confirm_sas_verification("peer-a", sas_proof)

    import main as main_mod
    monkeypatch.setattr(main_mod, "_resolve_dm_aliases", lambda **kw: ("local", "remote"))
    monkeypatch.setattr(main_mod, "has_mls_dm_session", lambda l, r: {"ok": True, "exists": False})
    monkeypatch.setattr(
        main_mod,
        "fetch_dm_prekey_bundle",
        lambda pid: {
            "ok": True,
            "trust_fingerprint": "newfingerprint",
            "mls_key_package": "",
        },
    )

    from routers.wormhole import compose_wormhole_dm
    result = compose_wormhole_dm(
        peer_id="peer-a",
        peer_dh_pub="fakepub",
        plaintext="hello",
    )

    assert result["ok"] is False
    assert result["trust_level"] == "continuity_broken"
    assert result.get("trust_changed") is True
