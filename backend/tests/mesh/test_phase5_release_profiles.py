import pytest

from services.config import get_settings
from services.release_profiles import profile_readiness_snapshot
from services.privacy_claims import (
    privacy_claims_snapshot,
    rollout_controls_snapshot,
    rollout_readiness_snapshot,
)


def setup_function():
    get_settings.cache_clear()


def teardown_function():
    get_settings.cache_clear()


def _protected_custody() -> dict:
    return {"protected_at_rest": True, "provider": "test"}


def _attested_current() -> dict:
    return {"attestation_state": "attested_current", "override_active": False}


def _compatibility_clear() -> dict:
    return {
        "stored_legacy_lookup_contacts_present": False,
        "legacy_lookup_runtime_active": False,
        "legacy_mailbox_get_runtime_active": False,
        "legacy_mailbox_get_enabled": False,
        "local_contact_upgrade_ok": True,
    }


def _gate_privilege_ok() -> dict:
    return {
        "privileged_gate_event_scope_class": "explicit_gate_audit",
        "repair_detail_scope_class": "local_operator_diagnostic",
    }


def _strong_claims_good() -> dict:
    return {
        "allowed": True,
        "compat_overrides_clear": True,
        "clearnet_fallback_blocked": True,
        "compatibility": {},
        "reasons": [],
    }


def _release_gate_good() -> dict:
    return {"ready": True, "blocking_reasons": []}


def test_dev_release_profile_does_not_add_claim_blockers(monkeypatch):
    monkeypatch.delenv("MESH_RELEASE_PROFILE", raising=False)
    get_settings.cache_clear()

    profile = profile_readiness_snapshot()
    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )

    assert profile["profile"] == "dev"
    assert profile["allowed"] is True
    assert claims["claims"]["dm_strong"]["allowed"] is True
    assert claims["claims"]["gate_transitional"]["allowed"] is True


def test_testnet_private_profile_blocks_unsafe_private_release_defaults(monkeypatch):
    monkeypatch.setenv("MESH_RELEASE_PROFILE", "testnet-private")
    monkeypatch.setenv("MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", "false")
    get_settings.cache_clear()

    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )

    dm = claims["claims"]["dm_strong"]
    gate = claims["claims"]["gate_transitional"]
    assert dm["allowed"] is False
    assert gate["allowed"] is False
    assert "profile_private_release_approval_disabled" in dm["blockers"]
    assert claims["release_profile"]["profile"] == "testnet-private"


def test_release_candidate_profile_blocks_rollout_readiness_on_debug_defaults(monkeypatch):
    monkeypatch.setenv("MESH_RELEASE_PROFILE", "release-candidate")
    monkeypatch.setenv("MESH_DEBUG_MODE", "true")
    monkeypatch.delenv("PRIVACY_CORE_ALLOWED_SHA256", raising=False)
    monkeypatch.delenv("MESH_RELEASE_ATTESTATION_PATH", raising=False)
    get_settings.cache_clear()

    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )
    rollout = rollout_readiness_snapshot(
        privacy_claims=claims,
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_debt={},
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )

    assert rollout["allowed"] is False
    assert rollout["state"] == "blocked_by_release_profile"
    assert "profile_debug_mode_enabled" in rollout["blockers"]
    assert "profile_privacy_core_hash_pin_missing" in rollout["blockers"]


def test_rollout_controls_surface_release_profile_blockers(monkeypatch):
    monkeypatch.setenv("MESH_RELEASE_PROFILE", "testnet-private")
    monkeypatch.setenv("MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", "false")
    get_settings.cache_clear()

    controls = rollout_controls_snapshot(
        rollout_readiness={"state": "ready_for_private_default"},
        privacy_core=_attested_current(),
        strong_claims=_strong_claims_good(),
        transport_tier="private_strong",
    )

    assert controls["private_default_enforce_safe"] is False
    assert controls["state"] == "override_active"
    assert "profile_private_release_approval_disabled" in controls["active_overrides"]
    assert controls["release_profile"]["profile"] == "testnet-private"


def test_release_candidate_profile_refuses_unsafe_strict_startup(monkeypatch):
    from services.env_check import validate_env

    monkeypatch.setenv("MESH_RELEASE_PROFILE", "release-candidate")
    monkeypatch.setenv("MESH_DEBUG_MODE", "true")
    monkeypatch.setenv("MESH_DM_TOKEN_PEPPER", "valid-test-pepper-value")
    monkeypatch.delenv("PRIVACY_CORE_ALLOWED_SHA256", raising=False)
    get_settings.cache_clear()

    with pytest.raises(SystemExit):
        validate_env(strict=True)
