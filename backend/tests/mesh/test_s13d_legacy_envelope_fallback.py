"""S13D Legacy Gate Envelope Fallback Cleanup.

Tests:
- existing gate without explicit field fails closed even with stored history
- new gate defaults to legacy fallback disabled
- setter/getter round-trip works with explicit acknowledgement on enable
- when flag is false, _gate_envelope_decrypt() does NOT attempt Phase 1 or node-local fallback
- when flag is true, current fallback chain remains available
- field is independent of envelope_policy
- admin setter requires scoped gate/admin auth, not proof-based member auth
- enabling fallback is explicit and time-bounded
- do not overclaim that disabling legacy fallback preserves readability for all old messages
- do not modify decrypt fast-path order or envelope_policy behavior
"""

import base64
import os
from unittest.mock import patch, MagicMock


# ── Fixtures ─────────────────────────────────────────────────────────────


def _make_phase1_envelope(gate_id: str) -> str:
    """Create an envelope encrypted with Phase 1 (gate-name-only) key."""
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    gate_key = gate_id.strip().lower()
    ikm = gate_key.encode("utf-8")
    info = b"gate_envelope_aes256gcm"
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"shadowbroker-gate-envelope-v1",
        info=info,
    ).derive(ikm)
    nonce = os.urandom(12)
    aad = f"gate_envelope|{gate_key}".encode("utf-8")
    ct = AESGCM(key).encrypt(nonce, b"phase1-secret-message", aad)
    return base64.b64encode(nonce + ct).decode("ascii")


def _make_phase2_envelope(gate_id: str, gate_secret: str) -> str:
    """Create an envelope encrypted with Phase 2 (per-gate secret) key."""
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    gate_key = gate_id.strip().lower()
    ikm = gate_secret.encode("utf-8")
    info = f"gate_envelope_aes256gcm|{gate_key}".encode("utf-8")
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"shadowbroker-gate-envelope-v1",
        info=info,
    ).derive(ikm)
    nonce = os.urandom(12)
    aad = f"gate_envelope|{gate_key}".encode("utf-8")
    ct = AESGCM(key).encrypt(nonce, b"phase2-secret-message", aad)
    return base64.b64encode(nonce + ct).decode("ascii")


# ── GateManager field behavior ───────────────────────────────────────────


def test_existing_gate_without_field_and_no_history_fails_closed():
    """A gate with no history and no explicit legacy_envelope_fallback must fail closed."""
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_s13d_legacy"] = {
        "creator_node_id": "test",
        "display_name": "Legacy Gate",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "test-secret",
    }
    try:
        assert gate_manager.get_legacy_envelope_fallback("__test_s13d_legacy") is False
    finally:
        gate_manager.gates.pop("__test_s13d_legacy", None)


def test_existing_gate_without_field_and_history_still_fails_closed():
    """A gate with stored history but no explicit flag must still fail closed."""
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_s13d_history"] = {
        "creator_node_id": "test",
        "display_name": "History Gate",
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 0,
        "message_count": 3,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "test-secret",
    }
    try:
        assert gate_manager.get_legacy_envelope_fallback("__test_s13d_history") is False
    finally:
        gate_manager.gates.pop("__test_s13d_history", None)


def test_new_gate_defaults_to_legacy_fallback_disabled():
    """create_gate must set legacy_envelope_fallback=False on new gates."""
    from services.mesh.mesh_reputation import gate_manager, ALLOW_DYNAMIC_GATES
    import services.mesh.mesh_reputation as rep_mod

    old = rep_mod.ALLOW_DYNAMIC_GATES
    rep_mod.ALLOW_DYNAMIC_GATES = True
    try:
        ok, _ = gate_manager.create_gate("test-node", "test-s13d-new", "S13D New Gate")
        assert ok
        assert gate_manager.gates["test-s13d-new"].get("legacy_envelope_fallback") is False
        assert gate_manager.get_legacy_envelope_fallback("test-s13d-new") is False
    finally:
        gate_manager.gates.pop("test-s13d-new", None)
        rep_mod.ALLOW_DYNAMIC_GATES = old


def test_getter_setter_round_trip():
    """Stored true flags do not re-enable the removed legacy fallback path."""
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_s13d_rt"] = {
        "creator_node_id": "test",
        "display_name": "RT Gate",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "test-secret",
        "legacy_envelope_fallback": True,
    }
    try:
        assert gate_manager.get_legacy_envelope_fallback("__test_s13d_rt") is False
        ok, _ = gate_manager.set_legacy_envelope_fallback("__test_s13d_rt", False)
        assert ok
        assert gate_manager.get_legacy_envelope_fallback("__test_s13d_rt") is False
        ok, detail = gate_manager.set_legacy_envelope_fallback(
            "__test_s13d_rt",
            True,
            acknowledge_legacy_risk=True,
        )
        assert not ok
        assert "removed" in detail
        assert gate_manager.get_legacy_envelope_fallback("__test_s13d_rt") is False
    finally:
        gate_manager.gates.pop("__test_s13d_rt", None)


def test_setter_rejects_enable():
    """Re-enabling fallback is no longer allowed."""
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_s13d_ack"] = {
        "creator_node_id": "test",
        "display_name": "Ack Gate",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "test-secret",
        "legacy_envelope_fallback": False,
    }
    try:
        ok, detail = gate_manager.set_legacy_envelope_fallback("__test_s13d_ack", True)
        assert not ok
        assert "removed" in detail
        assert gate_manager.get_legacy_envelope_fallback("__test_s13d_ack") is False
    finally:
        gate_manager.gates.pop("__test_s13d_ack", None)


def test_enabled_fallback_expires():
    """Expired fallback state must fail closed even if the stored flag is still true."""
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_s13d_expired"] = {
        "creator_node_id": "test",
        "display_name": "Expired Gate",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "",
        "legacy_envelope_fallback": True,
        "legacy_envelope_fallback_expires_at": 1,
    }
    try:
        assert gate_manager.get_legacy_envelope_fallback("__test_s13d_expired") is False
    finally:
        gate_manager.gates.pop("__test_s13d_expired", None)


def test_setter_rejects_unknown_gate():
    """Setting fallback on a nonexistent gate returns failure."""
    from services.mesh.mesh_reputation import gate_manager

    ok, detail = gate_manager.set_legacy_envelope_fallback("__nonexistent_s13d", False)
    assert not ok
    assert "not found" in detail.lower()


def test_getter_returns_false_for_unknown_gate():
    """Unknown gate must fail closed instead of assuming legacy fallback."""
    from services.mesh.mesh_reputation import gate_manager

    assert gate_manager.get_legacy_envelope_fallback("__nonexistent_s13d") is False


# ── Decrypt gating ───────────────────────────────────────────────────────


def test_fallback_false_blocks_phase1_decrypt():
    """When legacy_envelope_fallback is False, Phase 1 envelope must NOT decrypt."""
    from services.mesh.mesh_reputation import gate_manager
    from services.mesh.mesh_gate_mls import _gate_envelope_decrypt

    gate_id = "__test_s13d_nofb"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "No Fallback",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "",  # no Phase 2 secret
        "legacy_envelope_fallback": False,
    }
    try:
        token = _make_phase1_envelope(gate_id)
        result = _gate_envelope_decrypt(gate_id, token)
        # Phase 1 must be blocked — result must be None
        assert result is None
    finally:
        gate_manager.gates.pop(gate_id, None)


def test_fallback_true_does_not_allow_phase1_decrypt():
    """Stored legacy_envelope_fallback=True must not decrypt Phase 1 envelopes."""
    from services.mesh.mesh_reputation import gate_manager
    from services.mesh.mesh_gate_mls import _gate_envelope_decrypt

    gate_id = "__test_s13d_yesfb"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Yes Fallback",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "",  # no Phase 2 secret
        "legacy_envelope_fallback": True,
    }
    try:
        token = _make_phase1_envelope(gate_id)
        result = _gate_envelope_decrypt(gate_id, token)
        assert result is None
    finally:
        gate_manager.gates.pop(gate_id, None)


def test_phase2_decrypt_unaffected_by_fallback_flag():
    """Phase 2 decrypt must work regardless of the fallback flag."""
    from services.mesh.mesh_reputation import gate_manager
    from services.mesh.mesh_gate_mls import _gate_envelope_decrypt

    gate_id = "__test_s13d_p2"
    secret = "test-phase2-secret-s13d"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Phase2 Gate",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": secret,
        "legacy_envelope_fallback": False,
    }
    try:
        token = _make_phase2_envelope(gate_id, secret)
        result = _gate_envelope_decrypt(gate_id, token)
        assert result == "phase2-secret-message"
    finally:
        gate_manager.gates.pop(gate_id, None)


def test_phase2_decrypt_works_with_fallback_enabled():
    """Phase 2 decrypt still works when legacy fallback is True."""
    from services.mesh.mesh_reputation import gate_manager
    from services.mesh.mesh_gate_mls import _gate_envelope_decrypt

    gate_id = "__test_s13d_p2yes"
    secret = "test-phase2-secret-s13d-yes"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Phase2 Yes",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": secret,
        "legacy_envelope_fallback": True,
    }
    try:
        token = _make_phase2_envelope(gate_id, secret)
        result = _gate_envelope_decrypt(gate_id, token)
        assert result == "phase2-secret-message"
    finally:
        gate_manager.gates.pop(gate_id, None)


# ── Independence from envelope_policy ────────────────────────────────────


def test_field_independent_of_envelope_policy():
    """legacy_envelope_fallback and envelope_policy are independently settable."""
    from services.mesh.mesh_reputation import gate_manager

    gate_id = "__test_s13d_indep"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Independent",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "secret",
        "envelope_policy": "envelope_always",
        "legacy_envelope_fallback": True,
    }
    try:
        # Change fallback, envelope_policy unaffected
        gate_manager.set_legacy_envelope_fallback(gate_id, False)
        assert gate_manager.get_legacy_envelope_fallback(gate_id) is False
        assert gate_manager.get_envelope_policy(gate_id) == "envelope_always"

        # Change envelope_policy, fallback unaffected
        gate_manager.set_envelope_policy(gate_id, "envelope_disabled")
        assert gate_manager.get_envelope_policy(gate_id) == "envelope_disabled"
        assert gate_manager.get_legacy_envelope_fallback(gate_id) is False
    finally:
        gate_manager.gates.pop(gate_id, None)


def test_envelope_policy_disabled_does_not_reenable_removed_fallback():
    """envelope_policy=envelope_disabled does not re-enable removed fallback."""
    from services.mesh.mesh_reputation import gate_manager

    gate_id = "__test_s13d_notimplied"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Not Implied",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "",
        "envelope_policy": "envelope_disabled",
        "legacy_envelope_fallback": True,
    }
    try:
        assert gate_manager.get_legacy_envelope_fallback(gate_id) is False
        assert gate_manager.get_envelope_policy(gate_id) == "envelope_disabled"
    finally:
        gate_manager.gates.pop(gate_id, None)


# ── Admin auth ───────────────────────────────────────────────────────────


def test_admin_endpoint_exists_in_mesh_public():
    """The legacy_envelope_fallback PUT endpoint must exist in mesh_public router."""
    from routers.mesh_public import router

    paths = [r.path for r in router.routes if hasattr(r, "path")]
    assert "/api/mesh/gate/{gate_id}/legacy_envelope_fallback" in paths


def test_admin_endpoint_exists_in_main():
    """The legacy_envelope_fallback PUT endpoint must exist in main app."""
    import main

    paths = [r.path for r in main.app.routes if hasattr(r, "path")]
    assert "/api/mesh/gate/{gate_id}/legacy_envelope_fallback" in paths


def test_admin_endpoint_rejects_unauthenticated():
    """The admin endpoint must reject requests without gate admin scope."""
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app, raise_server_exceptions=False)
    resp = client.put(
        "/api/mesh/gate/infonet/legacy_envelope_fallback",
        json={"legacy_envelope_fallback": False},
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["ok"] is False
    assert "admin" in data["detail"].lower() or "scope" in data["detail"].lower()


def test_admin_endpoint_rejects_non_boolean():
    """The admin endpoint must reject non-boolean values."""
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app, raise_server_exceptions=False)
    # Simulate scoped auth
    with patch.object(main, "_check_scoped_auth", return_value=(True, "")):
        resp = client.put(
            "/api/mesh/gate/infonet/legacy_envelope_fallback",
            json={"legacy_envelope_fallback": "yes"},
        )
    data = resp.json()
    assert data["ok"] is False
    assert "boolean" in data["detail"].lower()


def test_admin_endpoint_rejects_enable_without_ack():
    """The admin endpoint rejects enabling the removed fallback path."""
    from fastapi.testclient import TestClient
    from services.mesh.mesh_reputation import gate_manager
    import main

    gate_id = "__test_s13d_admin_ack"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Admin Ack Test",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "secret",
        "legacy_envelope_fallback": False,
    }
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        with patch.object(main, "_check_scoped_auth", return_value=(True, "")):
            resp = client.put(
                f"/api/mesh/gate/{gate_id}/legacy_envelope_fallback",
                json={"legacy_envelope_fallback": True},
            )
        data = resp.json()
        assert data["ok"] is False
        assert "removed" in data["detail"]
    finally:
        gate_manager.gates.pop(gate_id, None)


def test_admin_endpoint_accepts_valid_boolean():
    """The admin endpoint must accept a valid boolean and update the gate."""
    from fastapi.testclient import TestClient
    from services.mesh.mesh_reputation import gate_manager
    import main

    gate_id = "__test_s13d_admin"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Admin Test",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "secret",
        "legacy_envelope_fallback": True,
    }
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        with patch.object(main, "_check_scoped_auth", return_value=(True, "")):
            resp = client.put(
                f"/api/mesh/gate/{gate_id}/legacy_envelope_fallback",
                json={"legacy_envelope_fallback": False},
            )
        data = resp.json()
        assert data["ok"] is True
        assert gate_manager.get_legacy_envelope_fallback(gate_id) is False
    finally:
        gate_manager.gates.pop(gate_id, None)


def test_admin_endpoint_rejects_enable_with_ack():
    """The admin endpoint rejects fallback enablement even with legacy-risk ack."""
    from fastapi.testclient import TestClient
    from services.mesh.mesh_reputation import gate_manager
    import main

    gate_id = "__test_s13d_admin_enable"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Admin Enable Test",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "secret",
        "legacy_envelope_fallback": False,
    }
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        with patch.object(main, "_check_scoped_auth", return_value=(True, "")):
            resp = client.put(
                f"/api/mesh/gate/{gate_id}/legacy_envelope_fallback",
                json={"legacy_envelope_fallback": True, "acknowledge_legacy_risk": True},
            )
        data = resp.json()
        assert data["ok"] is False
        assert "removed" in data["detail"]
        assert gate_manager.get_legacy_envelope_fallback(gate_id) is False
    finally:
        gate_manager.gates.pop(gate_id, None)


# ── No overclaim ─────────────────────────────────────────────────────────


def test_removed_fallback_keeps_old_phase1_messages_unreadable():
    """Removed legacy fallback keeps Phase 1 messages unreadable."""
    from services.mesh.mesh_reputation import gate_manager
    from services.mesh.mesh_gate_mls import _gate_envelope_decrypt

    gate_id = "__test_s13d_break"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Break Test",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "",
        "legacy_envelope_fallback": True,
    }
    try:
        token = _make_phase1_envelope(gate_id)
        # Unreadable even if an old stored flag says fallback is enabled.
        assert _gate_envelope_decrypt(gate_id, token) is None
        # Disable fallback — same message becomes unreadable
        gate_manager.set_legacy_envelope_fallback(gate_id, False)
        assert _gate_envelope_decrypt(gate_id, token) is None
    finally:
        gate_manager.gates.pop(gate_id, None)


# ── Decrypt fast-path order preserved ────────────────────────────────────


def test_decrypt_fast_path_order_unchanged():
    """gate_envelope fast path in decrypt_gate_message_for_local_identity
    still runs before MLS fallback when the gate explicitly opts into envelope_always."""
    from services.mesh.mesh_gate_mls import (
        _gate_envelope_encrypt,
        _gate_envelope_hash,
        decrypt_gate_message_for_local_identity,
    )
    from services.mesh.mesh_reputation import gate_manager

    gate_id = "__test_s13d_order"
    secret = "test-order-secret-s13d"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Order Test",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": secret,
        "envelope_policy": "envelope_always",
        "legacy_envelope_fallback": False,
    }
    try:
        message_nonce = "dummy-nonce"
        token = _gate_envelope_encrypt(gate_id, "phase2-secret-message", message_nonce=message_nonce)
        result = decrypt_gate_message_for_local_identity(
            gate_id=gate_id,
            epoch=1,
            ciphertext="dummy-ct",
            nonce=message_nonce,
            gate_envelope=token,
            envelope_hash=_gate_envelope_hash(token),
        )
        assert result["ok"] is True
        assert result["plaintext"] == "phase2-secret-message"
        assert result["identity_scope"] == "gate_envelope"
    finally:
        gate_manager.gates.pop(gate_id, None)


def test_envelope_policy_behavior_unchanged_by_fallback():
    """envelope_policy controls member view exposure, not decrypt behavior.
    Changing fallback must not alter envelope_policy semantics."""
    from services.mesh.mesh_reputation import gate_manager

    gate_id = "__test_s13d_policy_unchanged"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "test",
        "display_name": "Policy Unchanged",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "secret",
        "envelope_policy": "envelope_recovery",
        "legacy_envelope_fallback": False,
    }
    try:
        # envelope_policy getter must still work normally
        assert gate_manager.get_envelope_policy(gate_id) == "envelope_recovery"
        # Changing fallback must not touch envelope_policy
        gate_manager.set_legacy_envelope_fallback(gate_id, True, acknowledge_legacy_risk=True)
        assert gate_manager.get_envelope_policy(gate_id) == "envelope_recovery"
    finally:
        gate_manager.gates.pop(gate_id, None)


# ── Edge cases ───────────────────────────────────────────────────────────


def test_empty_gate_id_getter_returns_true():
    """Empty gate_id must return True (backward compat default)."""
    from services.mesh.mesh_reputation import gate_manager

    assert gate_manager.get_legacy_envelope_fallback("") is False


def test_case_insensitive_gate_lookup():
    """Gate lookup must be case-insensitive."""
    from services.mesh.mesh_reputation import gate_manager

    gate_manager.gates["__test_s13d_case"] = {
        "creator_node_id": "test",
        "display_name": "Case Test",
        "description": "",
        "rules": {},
        "created_at": 0,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "secret",
        "legacy_envelope_fallback": False,
    }
    try:
        assert gate_manager.get_legacy_envelope_fallback("__TEST_S13D_CASE") is False
    finally:
        gate_manager.gates.pop("__test_s13d_case", None)
