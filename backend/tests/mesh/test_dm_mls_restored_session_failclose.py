"""S6A Remediation: restored-session fail-closed behavior.

Tests that restored DM sessions (loaded from persisted Rust state) which
raise a PrivacyCoreError during encrypt or decrypt are treated as stale:
- session mapping is cleared
- persisted Rust DM state blob is deleted
- explicit session_expired is returned

Fresh sessions that raise the same error must NOT be intercepted by this
path — they still produce dm_mls_encrypt_failed / dm_mls_decrypt_failed.
"""

import logging
from unittest.mock import patch

import pytest

from services.privacy_core_client import PrivacyCoreError


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from services.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)
    mesh_dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=True)
    return mesh_dm_mls, relay


def _establish_session(dm_mls):
    bob_bundle = dm_mls.export_dm_key_package_for_alias("bob")
    assert bob_bundle["ok"] is True
    initiated = dm_mls.initiate_dm_session("alice", "bob", bob_bundle)
    assert initiated["ok"] is True
    accepted = dm_mls.accept_dm_session("bob", "alice", initiated["welcome"])
    assert accepted["ok"] is True
    return accepted["session_id"]


def _restart_and_restore(dm_mls):
    """Simulate restart: clear in-memory state, keep persistence, trigger lazy load."""
    dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=False)
    # Trigger lazy load so restored sessions are populated.
    dm_mls.has_dm_session("alice", "bob")


def test_restored_session_decrypt_error_returns_session_expired(tmp_path, monkeypatch, caplog):
    """A restored session that raises a non-'unknown handle' PrivacyCoreError
    during decrypt must return session_expired (not dm_mls_decrypt_failed)."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)
    _restart_and_restore(dm_mls)

    # Confirm session is marked restored.
    session = dm_mls._SESSIONS.get("alice::bob")
    assert session is not None
    assert session.restored is True

    # Patch dm_decrypt on the privacy client to raise a non-"unknown handle" error.
    with patch.object(
        dm_mls._privacy_client(),
        "dm_decrypt",
        side_effect=PrivacyCoreError("mls decrypt internal failure"),
    ):
        with caplog.at_level(logging.WARNING):
            result = dm_mls.decrypt_dm("bob", "alice", "Y2lwaGVydGV4dA==", "bm9uY2U=")

    assert result["ok"] is False
    assert result["detail"] == "session_expired"
    assert "restored dm session stale" in caplog.text.lower()


def test_restored_session_decrypt_error_clears_session_mapping(tmp_path, monkeypatch):
    """After a restored-session decrypt failure, the stale session mapping must be gone."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)
    _restart_and_restore(dm_mls)

    # decrypt_dm("bob", "alice") looks up session "bob::alice".
    assert "bob::alice" in dm_mls._SESSIONS

    with patch.object(
        dm_mls._privacy_client(),
        "dm_decrypt",
        side_effect=PrivacyCoreError("mls decrypt internal failure"),
    ):
        dm_mls.decrypt_dm("bob", "alice", "Y2lwaGVydGV4dA==", "bm9uY2U=")

    assert "bob::alice" not in dm_mls._SESSIONS


def test_restored_session_decrypt_error_deletes_rust_blob(tmp_path, monkeypatch):
    """After a restored-session decrypt failure, the persisted Rust blob must be deleted."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)
    _restart_and_restore(dm_mls)

    rust_path = tmp_path / dm_mls.RUST_STATE_DOMAIN / dm_mls.RUST_STATE_FILENAME
    assert rust_path.exists(), "Rust blob must exist before failure"

    with patch.object(
        dm_mls._privacy_client(),
        "dm_decrypt",
        side_effect=PrivacyCoreError("mls decrypt internal failure"),
    ):
        dm_mls.decrypt_dm("bob", "alice", "Y2lwaGVydGV4dA==", "bm9uY2U=")

    assert not rust_path.exists(), "Rust blob must be deleted after restored-session failure"


def test_restored_session_encrypt_error_returns_session_expired(tmp_path, monkeypatch, caplog):
    """A restored session that raises a PrivacyCoreError during encrypt
    must return session_expired and invalidate the Rust blob."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)
    _restart_and_restore(dm_mls)

    rust_path = tmp_path / dm_mls.RUST_STATE_DOMAIN / dm_mls.RUST_STATE_FILENAME
    assert rust_path.exists()

    session = dm_mls._SESSIONS.get("alice::bob")
    assert session is not None
    assert session.restored is True

    with patch.object(
        dm_mls._privacy_client(),
        "dm_encrypt",
        side_effect=PrivacyCoreError("mls encrypt internal failure"),
    ):
        with caplog.at_level(logging.WARNING):
            result = dm_mls.encrypt_dm("alice", "bob", "test message")

    assert result["ok"] is False
    assert result["detail"] == "session_expired"
    assert "alice::bob" not in dm_mls._SESSIONS
    assert not rust_path.exists()
    assert "restored dm session stale" in caplog.text.lower()


def test_fresh_session_error_does_not_trigger_restored_failclose(tmp_path, monkeypatch):
    """A fresh (non-restored) session that raises a PrivacyCoreError must NOT
    be intercepted by the restored-session fail-closed path."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)

    # Confirm session is NOT restored (freshly established, no restart).
    session = dm_mls._SESSIONS.get("alice::bob")
    assert session is not None
    assert session.restored is False

    with patch.object(
        dm_mls._privacy_client(),
        "dm_encrypt",
        side_effect=PrivacyCoreError("mls encrypt internal failure"),
    ):
        result = dm_mls.encrypt_dm("alice", "bob", "test message")

    # Fresh session error must produce the generic failure, not session_expired.
    assert result["ok"] is False
    assert result["detail"] == "dm_mls_encrypt_failed"


def test_restored_session_boot_probe_clears_restored_flag_after_success(tmp_path, monkeypatch):
    from services.config import get_settings
    from services.mesh import mesh_metrics

    monkeypatch.setenv("MESH_DM_RESTORED_SESSION_BOOT_PROBE_ENABLE", "true")
    get_settings.cache_clear()
    mesh_metrics.reset()
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)

    _restart_and_restore(dm_mls)

    assert dm_mls._SESSIONS["alice::bob"].restored is False
    assert dm_mls._SESSIONS["bob::alice"].restored is False
    assert mesh_metrics.snapshot()["counters"].get("session_restore_failures", 0) == 0


def test_restored_session_boot_probe_drops_pair_when_state_does_not_advance(tmp_path, monkeypatch):
    from services.config import get_settings
    from services.mesh import mesh_metrics

    monkeypatch.setenv("MESH_DM_RESTORED_SESSION_BOOT_PROBE_ENABLE", "true")
    get_settings.cache_clear()
    mesh_metrics.reset()
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)

    client = dm_mls._privacy_client()
    monkeypatch.setattr(client, "dm_session_fingerprint", lambda _handle: "static-fingerprint")

    _restart_and_restore(dm_mls)

    assert "alice::bob" not in dm_mls._SESSIONS
    assert "bob::alice" not in dm_mls._SESSIONS
    assert mesh_metrics.snapshot()["counters"]["session_restore_failures"] == 2
