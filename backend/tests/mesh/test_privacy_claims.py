from __future__ import annotations

import asyncio

import main
from .review_surface_contracts import (
    EXPLICIT_REVIEW_EXPORT_CONTRACT,
    REVIEW_CONSISTENCY_CONTRACT,
    REVIEW_MANIFEST_CONTRACT,
    assert_surface_contract,
    review_surface_corpus,
)
from services.privacy_claims import (
    explicit_review_export_snapshot,
    final_review_bundle_snapshot,
    privacy_claims_snapshot,
    release_checklist_snapshot,
    release_claims_matrix_snapshot,
    review_consistency_snapshot,
    review_manifest_snapshot,
    review_export_snapshot,
    rollout_controls_snapshot,
    rollout_health_snapshot,
    rollout_readiness_snapshot,
    staged_rollout_telemetry_snapshot,
)


def _request(path: str):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "headers": [],
            "client": ("test", 12345),
            "method": "GET",
            "path": path.split("?", 1)[0],
            "query_string": path.split("?", 1)[1].encode("utf-8") if "?" in path else b"",
        }
    )


def _protected_custody() -> dict:
    return {
        "code": "protected_at_rest",
        "provider": "passphrase",
        "protected_at_rest": True,
    }


def _review_surface_samples() -> tuple[dict, dict, dict]:
    sample = review_surface_corpus()["clean_ready"]
    return (
        sample["explicit_review_export"],
        sample["review_manifest"],
        sample["review_consistency"],
    )


def _degraded_custody() -> dict:
    return {
        "code": "degraded_local_custody",
        "provider": "raw",
        "protected_at_rest": False,
    }


def _attested_current() -> dict:
    return {
        "attestation_state": "attested_current",
        "override_active": False,
        "detail": "privacy-core version and trusted artifact hash are current",
    }


def _attestation_mismatch() -> dict:
    return {
        "attestation_state": "attestation_mismatch",
        "override_active": False,
        "detail": "privacy-core loaded, but its artifact hash does not match the trusted enrollment",
    }


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
        "ordinary_gate_view_scope_class": "gate_member_or_gate_scope",
        "privileged_gate_event_scope_class": "explicit_gate_audit",
        "repair_detail_scope_class": "local_operator_diagnostic",
        "privileged_gate_event_view_enabled": True,
        "repair_detail_view_enabled": True,
    }


def _compatibility_debt_clear() -> dict:
    return {
        "legacy_lookup_reliance": {
            "active": False,
            "last_seen_at": 0,
            "blocked_count": 0,
        },
        "legacy_mailbox_get_reliance": {
            "active": False,
            "last_seen_at": 0,
            "blocked_count": 0,
            "enabled": False,
        },
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
    return {
        "ready": True,
        "blocking_reasons": [],
    }


def test_private_strong_current_attestation_and_protected_custody_yield_dm_strong_ready():
    snapshot = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )

    dm = snapshot["claims"]["dm_strong"]

    assert dm["allowed"] is True
    assert dm["state"] == "dm_strong_ready"
    assert dm["plain_label"] == "DM strong ready"
    assert dm["blockers"] == []
    assert snapshot["chip"]["state"] == "dm_strong_ready"
    assert snapshot["chip"]["plain_label"] == "Strong private delivery ready"


def test_attestation_mismatch_blocks_strong_claim_honestly():
    snapshot = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attestation_mismatch(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )

    dm = snapshot["claims"]["dm_strong"]

    assert dm["allowed"] is False
    assert dm["state"] == "dm_strong_blocked"
    assert "privacy_core_attestation_not_current" in dm["blockers"]


def test_degraded_local_custody_does_not_overclaim_stronger_local_assurance():
    snapshot = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_degraded_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )

    dm = snapshot["claims"]["dm_strong"]
    gate = snapshot["claims"]["gate_transitional"]

    assert dm["allowed"] is False
    assert gate["allowed"] is False
    assert "local_custody_not_protected_at_rest" in dm["blockers"]
    assert "local_custody_not_protected_at_rest" in gate["blockers"]
    assert snapshot["chip"]["state"] == "dm_strong_blocked"


def test_compatibility_readiness_affects_dm_claim_blockers_honestly():
    snapshot = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness={
            "stored_legacy_lookup_contacts_present": True,
            "legacy_lookup_runtime_active": True,
            "legacy_mailbox_get_runtime_active": True,
            "legacy_mailbox_get_enabled": True,
            "local_contact_upgrade_ok": False,
        },
        gate_privilege_access=_gate_privilege_ok(),
    )

    dm = snapshot["claims"]["dm_strong"]

    assert dm["allowed"] is False
    assert "compatibility_stored_legacy_lookup_contacts_present" in dm["blockers"]
    assert "compatibility_legacy_lookup_runtime_active" in dm["blockers"]
    assert "compatibility_legacy_mailbox_get_runtime_active" in dm["blockers"]
    assert "compatibility_legacy_mailbox_get_enabled" in dm["blockers"]
    assert "compatibility_local_contact_upgrade_incomplete" in dm["blockers"]


def test_control_only_and_degraded_chip_states_map_from_authoritative_model():
    control_only = privacy_claims_snapshot(
        transport_tier="private_control_only",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )
    degraded = privacy_claims_snapshot(
        transport_tier="public_degraded",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )

    assert control_only["chip"]["state"] == "control_only_local_only"
    assert control_only["chip"]["plain_label"] == "Local private operations only"
    assert degraded["chip"]["state"] == "degraded_requires_approval"
    assert degraded["chip"]["plain_label"] == "Needs approval for weaker privacy"


def test_rollout_readiness_strong_good_state_yields_ready_for_private_default():
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
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )

    assert rollout["allowed"] is True
    assert rollout["state"] == "ready_for_private_default"
    assert rollout["blockers"] == []


def test_rollout_readiness_attestation_mismatch_blocks_honestly():
    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attestation_mismatch(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )

    rollout = rollout_readiness_snapshot(
        privacy_claims=claims,
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attestation_mismatch(),
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )

    assert rollout["allowed"] is False
    assert rollout["state"] == "blocked_by_attestation"
    assert rollout["blockers"] == ["privacy_core_attestation_not_current"]


def test_rollout_readiness_degraded_local_custody_blocks_honestly():
    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_degraded_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )

    rollout = rollout_readiness_snapshot(
        privacy_claims=claims,
        transport_tier="private_strong",
        local_custody=_degraded_custody(),
        privacy_core=_attested_current(),
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )

    assert rollout["allowed"] is False
    assert rollout["state"] == "blocked_by_local_custody"
    assert rollout["blockers"] == ["local_custody_not_protected_at_rest"]


def test_rollout_readiness_compatibility_posture_blocks_honestly():
    compatibility = {
        "stored_legacy_lookup_contacts_present": True,
        "legacy_lookup_runtime_active": False,
        "legacy_mailbox_get_runtime_active": False,
        "legacy_mailbox_get_enabled": False,
        "local_contact_upgrade_ok": True,
    }
    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=compatibility,
        gate_privilege_access=_gate_privilege_ok(),
    )

    rollout = rollout_readiness_snapshot(
        privacy_claims=claims,
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=compatibility,
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )

    assert rollout["allowed"] is False
    assert rollout["state"] == "blocked_by_compatibility"
    assert "compatibility_stored_legacy_lookup_contacts_present" in rollout["blockers"]


def test_rollout_readiness_compatibility_debt_downgrades_honestly():
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
        compatibility_debt={
            "legacy_lookup_reliance": {
                "active": False,
                "last_seen_at": 123,
                "blocked_count": 0,
            },
            "legacy_mailbox_get_reliance": {
                "active": False,
                "last_seen_at": 0,
                "blocked_count": 0,
                "enabled": False,
            },
        },
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )

    assert rollout["allowed"] is True
    assert rollout["state"] == "ready_with_compatibility_debt"
    assert "compatibility_debt_legacy_lookup" in rollout["blockers"]


def test_rollout_readiness_active_override_is_surfaced_honestly():
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
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims={
            **_strong_claims_good(),
            "allowed": False,
            "compat_overrides_clear": False,
            "compatibility": {"legacy_dm_get_enabled": True},
            "reasons": ["compat_overrides_enabled"],
        },
        release_gate=_release_gate_good(),
    )

    assert rollout["allowed"] is False
    assert rollout["state"] == "blocked_by_operator_override"
    assert "operator_override_legacy_dm_get_enabled" in rollout["blockers"]


def test_rollout_controls_surface_active_attestation_override():
    controls = rollout_controls_snapshot(
        rollout_readiness={"state": "requires_operator_attention"},
        privacy_core={**_attested_current(), "override_active": True},
        strong_claims=_strong_claims_good(),
        transport_tier="private_strong",
    )

    assert controls["attestation_override_active"] is True
    assert "attestation_override_active" in controls["active_overrides"]


def test_rollout_controls_surface_active_compatibility_override():
    controls = rollout_controls_snapshot(
        rollout_readiness={"state": "blocked_by_operator_override"},
        privacy_core=_attested_current(),
        strong_claims={
            **_strong_claims_good(),
            "compat_overrides_clear": False,
            "compatibility": {"legacy_dm_get_enabled": True},
        },
        transport_tier="private_strong",
    )

    assert controls["compatibility_override_active"] is True
    assert controls["legacy_compatibility_enabled"] is True
    assert controls["legacy_compatibility_paths_enabled"] == ["legacy_dm_get_enabled"]


def test_rollout_health_surfaces_legacy_debt_honestly():
    health = rollout_health_snapshot(
        rollout_readiness={"allowed": True, "state": "ready_with_compatibility_debt"},
        compatibility_debt={
            "legacy_lookup_reliance": {"active": False, "last_seen_at": 1, "blocked_count": 0},
            "legacy_mailbox_get_reliance": {"active": False, "last_seen_at": 0, "blocked_count": 0, "enabled": False},
        },
        compatibility_readiness={
            **_compatibility_clear(),
            "stored_legacy_lookup_contacts_present": True,
            "upgraded_contact_preferences": 2,
        },
        lookup_handle_rotation={
            "state": "lookup_handle_rotation_pending",
            "last_refresh_ok": True,
        },
    )

    assert health["compatibility_cleanup_pending"] is True
    assert "compatibility_debt_legacy_lookup" in health["debt_flags"]
    assert "stored_legacy_lookup_contacts_present" in health["debt_flags"]
    assert "lookup_handle_rotation_pending" in health["debt_flags"]
    assert health["upgraded_contact_preferences"] == 2


def test_review_export_snapshot_contains_authoritative_surfaces_and_schema_metadata():
    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )
    readiness = rollout_readiness_snapshot(
        privacy_claims=claims,
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )
    controls = rollout_controls_snapshot(
        rollout_readiness=readiness,
        privacy_core=_attested_current(),
        strong_claims=_strong_claims_good(),
        transport_tier="private_strong",
    )
    health = rollout_health_snapshot(
        rollout_readiness=readiness,
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        lookup_handle_rotation={
            "state": "lookup_handle_rotation_ok",
            "last_refresh_ok": True,
        },
    )

    export = review_export_snapshot(
        privacy_claims=claims,
        rollout_readiness=readiness,
        rollout_controls=controls,
        rollout_health=health,
    )

    assert export["schema_version"] == "privacy_review_export.v1"
    assert export["export_kind"] == "privacy_review_export"
    assert export["surface_class"] == "authoritative_export_bundle"
    assert export["authoritative_model"] == "privacy_claims"
    assert export["identifier_free"] is True
    assert export["privacy_claims"]["claims"]["dm_strong"]["state"] == "dm_strong_ready"
    assert export["rollout_readiness"]["state"] == "ready_for_private_default"
    assert export["rollout_controls"]["state"] == "private_default_safe"
    assert export["rollout_health"]["state"] == "healthy"


def test_review_export_summary_rows_match_authoritative_inputs():
    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attestation_mismatch(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )
    readiness = rollout_readiness_snapshot(
        privacy_claims=claims,
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attestation_mismatch(),
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )
    controls = rollout_controls_snapshot(
        rollout_readiness=readiness,
        privacy_core=_attestation_mismatch(),
        strong_claims=_strong_claims_good(),
        transport_tier="private_strong",
    )
    health = rollout_health_snapshot(
        rollout_readiness=readiness,
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
    )

    export = review_export_snapshot(
        privacy_claims=claims,
        rollout_readiness=readiness,
        rollout_controls=controls,
        rollout_health=health,
    )

    summary = export["review_summary"]
    assert summary["dm_strong_claim"]["allowed"] is False
    assert summary["dm_strong_claim"]["state"] == "dm_strong_blocked"
    assert summary["gate_transitional_claim"]["allowed"] is False
    assert summary["private_default_rollout_safe"]["allowed"] is False
    assert summary["private_default_rollout_safe"]["state"] == "blocked_by_attestation"
    assert summary["major_blocker"]["state"] == "attestation"


def test_review_export_summary_prefers_override_over_ready_readiness():
    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )
    readiness = rollout_readiness_snapshot(
        privacy_claims=claims,
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )
    controls = rollout_controls_snapshot(
        rollout_readiness=readiness,
        privacy_core={**_attested_current(), "override_active": True},
        strong_claims=_strong_claims_good(),
        transport_tier="private_strong",
    )
    health = rollout_health_snapshot(
        rollout_readiness=readiness,
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        lookup_handle_rotation={
            "state": "lookup_handle_rotation_ok",
            "last_refresh_ok": True,
        },
    )

    export = review_export_snapshot(
        privacy_claims=claims,
        rollout_readiness=readiness,
        rollout_controls=controls,
        rollout_health=health,
    )

    summary = export["review_summary"]
    assert summary["private_default_rollout_safe"]["allowed"] is False
    assert summary["private_default_rollout_safe"]["state"] == "blocked_by_operator_override"
    assert summary["private_default_rollout_safe"]["raw_readiness_state"] == "ready_for_private_default"
    assert summary["major_blocker"]["state"] == "operator_override"


def test_review_export_summary_prefers_cleanup_debt_over_ready_readiness():
    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )
    readiness = rollout_readiness_snapshot(
        privacy_claims=claims,
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )
    controls = rollout_controls_snapshot(
        rollout_readiness=readiness,
        privacy_core=_attested_current(),
        strong_claims=_strong_claims_good(),
        transport_tier="private_strong",
    )
    health = rollout_health_snapshot(
        rollout_readiness={"allowed": True, "state": "ready_for_private_default"},
        compatibility_debt={
            "legacy_lookup_reliance": {"active": False, "last_seen_at": 10, "blocked_count": 0},
            "legacy_mailbox_get_reliance": {"active": False, "last_seen_at": 0, "blocked_count": 0, "enabled": False},
        },
        compatibility_readiness=_compatibility_clear(),
        lookup_handle_rotation={
            "state": "lookup_handle_rotation_ok",
            "last_refresh_ok": True,
        },
    )

    export = review_export_snapshot(
        privacy_claims=claims,
        rollout_readiness=readiness,
        rollout_controls=controls,
        rollout_health=health,
    )

    summary = export["review_summary"]
    assert summary["private_default_rollout_safe"]["allowed"] is False
    assert summary["private_default_rollout_safe"]["state"] == "blocked_by_cleanup_debt"
    assert summary["major_blocker"]["state"] == "compatibility_debt"


def test_final_review_bundle_contains_expected_authoritative_package_and_verdict_metadata():
    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )
    readiness = rollout_readiness_snapshot(
        privacy_claims=claims,
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )
    controls = rollout_controls_snapshot(
        rollout_readiness=readiness,
        privacy_core=_attested_current(),
        strong_claims=_strong_claims_good(),
        transport_tier="private_strong",
    )
    health = rollout_health_snapshot(
        rollout_readiness=readiness,
        compatibility_debt=_compatibility_debt_clear(),
        compatibility_readiness=_compatibility_clear(),
        lookup_handle_rotation={
            "state": "lookup_handle_rotation_ok",
            "last_refresh_ok": True,
        },
    )
    export = review_export_snapshot(
        privacy_claims=claims,
        rollout_readiness=readiness,
        rollout_controls=controls,
        rollout_health=health,
    )

    bundle = final_review_bundle_snapshot(review_export=export)

    assert bundle["schema_version"] == "privacy_final_review_bundle.v1"
    assert bundle["bundle_kind"] == "final_review_bundle"
    assert bundle["surface_class"] == "authoritative_export_bundle"
    assert bundle["source_surface"] == "review_export"
    assert bundle["review_completeness"]["deterministic"] is True
    assert bundle["review_completeness"]["identifier_free"] is True
    assert bundle["review_completeness"]["sourced_from_authoritative_model"] is True
    assert bundle["release_readiness_verdict"]["state"] == "release_ready"
    assert bundle["compatibility_shim_provenance"]["strong_claims"]["surface_class"] == "compatibility_shim"
    assert bundle["compatibility_shim_provenance"]["release_gate"]["surface_class"] == "compatibility_shim"
    assert bundle["review_export"]["schema_version"] == "privacy_review_export.v1"


def test_final_review_bundle_verdict_mapping_is_correct():
    ready_bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "private_default_rollout_safe": {"allowed": True},
                "major_blocker": {"state": "none", "detail": "none"},
            },
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )
    debt_bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "private_default_rollout_safe": {"allowed": False},
                "major_blocker": {"state": "compatibility_debt", "detail": "debt"},
            },
            "rollout_health": {"state": "cleanup_debt_present"},
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )
    blocked_bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "private_default_rollout_safe": {"allowed": False},
                "major_blocker": {"state": "attestation", "detail": "blocked"},
            },
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )
    attention_bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "private_default_rollout_safe": {"allowed": False},
                "major_blocker": {"state": "operator_attention", "detail": "attention"},
            },
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )

    assert ready_bundle["release_readiness_verdict"]["state"] == "release_ready"
    assert debt_bundle["release_readiness_verdict"]["state"] == "release_ready_with_debt"
    assert blocked_bundle["release_readiness_verdict"]["state"] == "release_blocked"
    assert attention_bundle["release_readiness_verdict"]["state"] == "operator_attention_required"


def test_staged_rollout_telemetry_ready_clean_maps_to_safe_canary():
    bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "private_default_rollout_safe": {"allowed": True},
                "major_blocker": {"state": "none", "detail": "none"},
            },
            "rollout_controls": {
                "active_overrides": [],
                "compatibility_override_active": False,
                "legacy_compatibility_enabled": False,
            },
            "rollout_health": {
                "compatibility_cleanup_pending": False,
            },
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )

    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)

    assert telemetry["rollout_stage_recommendation"] == "private_default_canary"
    assert telemetry["rollout_safe_now"] is True
    assert telemetry["migration_cleanup_complete"] is True
    assert telemetry["compatibility_debt_present"] is False
    assert telemetry["canary_safe_now"] is True


def test_staged_rollout_telemetry_debt_maps_to_canary_with_debt():
    bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "private_default_rollout_safe": {"allowed": False},
                "major_blocker": {"state": "compatibility_debt", "detail": "debt"},
            },
            "rollout_controls": {
                "active_overrides": [],
                "compatibility_override_active": False,
                "legacy_compatibility_enabled": False,
            },
            "rollout_health": {
                "compatibility_cleanup_pending": True,
            },
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )

    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)

    assert telemetry["rollout_stage_recommendation"] == "private_default_canary_with_debt"
    assert telemetry["rollout_safe_now"] is False
    assert telemetry["migration_cleanup_complete"] is False
    assert telemetry["compatibility_debt_present"] is True
    assert telemetry["canary_safe_now"] is True


def test_staged_rollout_telemetry_override_maps_to_non_safe_stage():
    bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "private_default_rollout_safe": {"allowed": False},
                "major_blocker": {"state": "operator_override", "detail": "override"},
            },
            "rollout_controls": {
                "active_overrides": ["attestation_override_active"],
                "compatibility_override_active": True,
                "legacy_compatibility_enabled": True,
            },
            "rollout_health": {
                "compatibility_cleanup_pending": False,
            },
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )

    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)

    assert telemetry["rollout_stage_recommendation"] == "hold_for_override_clearance"
    assert telemetry["rollout_safe_now"] is False
    assert telemetry["kill_switch_posture_active"] is True
    assert telemetry["active_overrides_present"] is True
    assert telemetry["active_compatibility_allowances"] is True
    assert telemetry["operator_attention_required"] is True


def test_release_claims_matrix_clean_state_maps_to_claimable_rows():
    bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "dm_strong_claim": {
                    "allowed": True,
                    "state": "dm_strong_ready",
                    "plain_label": "DM strong ready",
                    "detail": "ready",
                },
                "gate_transitional_claim": {
                    "allowed": True,
                    "state": "gate_transitional_ready",
                    "plain_label": "Gate transitional ready",
                    "detail": "ready",
                },
                "private_default_rollout_safe": {
                    "allowed": True,
                    "state": "ready_for_private_default",
                    "plain_label": "Private default safe now",
                    "detail": "safe",
                },
                "major_blocker": {"state": "none", "detail": "none"},
            },
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )
    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)

    matrix = release_claims_matrix_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
    )

    assert matrix["schema_version"] == "privacy_release_claims_matrix.v1"
    assert matrix["rows"]["dm_strong_claim_now"]["allowed"] is True
    assert matrix["rows"]["gate_transitional_claim_now"]["allowed"] is True
    assert matrix["rows"]["private_default_rollout_claim_now"]["allowed"] is True
    assert matrix["rows"]["compatibility_cleanup_complete"]["allowed"] is True
    assert matrix["rows"]["operator_override_free"]["allowed"] is True


def test_release_claims_matrix_keeps_rollout_rows_honest_under_compatibility_debt():
    bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "dm_strong_claim": {
                    "allowed": True,
                    "state": "dm_strong_ready",
                    "plain_label": "DM strong ready",
                    "detail": "ready",
                },
                "gate_transitional_claim": {
                    "allowed": True,
                    "state": "gate_transitional_ready",
                    "plain_label": "Gate transitional ready",
                    "detail": "ready",
                },
                "private_default_rollout_safe": {
                    "allowed": False,
                    "state": "blocked_by_cleanup_debt",
                    "plain_label": "Private default blocked by cleanup debt",
                    "detail": "debt",
                },
                "major_blocker": {"state": "compatibility_debt", "detail": "debt"},
            },
            "rollout_health": {"compatibility_cleanup_pending": True},
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )
    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)

    matrix = release_claims_matrix_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
    )

    assert matrix["claim_truth_metadata"]["compatibility_debt_reflected"] is True
    assert matrix["rows"]["private_default_rollout_claim_now"]["allowed"] is False
    assert matrix["rows"]["compatibility_cleanup_complete"]["allowed"] is False
    assert "compatibility_debt" in matrix["blocker_categories"]


def test_release_claims_matrix_active_override_blocks_relevant_rows_honestly():
    bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "dm_strong_claim": {
                    "allowed": True,
                    "state": "dm_strong_ready",
                    "plain_label": "DM strong ready",
                    "detail": "ready",
                },
                "gate_transitional_claim": {
                    "allowed": True,
                    "state": "gate_transitional_ready",
                    "plain_label": "Gate transitional ready",
                    "detail": "ready",
                },
                "private_default_rollout_safe": {
                    "allowed": False,
                    "state": "blocked_by_operator_override",
                    "plain_label": "Private default blocked by override",
                    "detail": "override",
                },
                "major_blocker": {"state": "operator_override", "detail": "override"},
            },
            "rollout_controls": {
                "active_overrides": ["attestation_override_active"],
                "compatibility_override_active": True,
                "legacy_compatibility_enabled": True,
            },
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )
    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)

    matrix = release_claims_matrix_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
    )

    assert matrix["rows"]["private_default_rollout_claim_now"]["allowed"] is False
    assert matrix["rows"]["operator_override_free"]["allowed"] is False
    assert "operator_override" in matrix["blocker_categories"]


def test_release_checklist_clean_state_yields_fully_completed_checklist():
    bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "dm_strong_claim": {"allowed": True, "detail": "ready"},
                "gate_transitional_claim": {"allowed": True, "detail": "ready"},
                "private_default_rollout_safe": {"allowed": True, "detail": "ready"},
                "major_blocker": {"state": "none", "detail": "none"},
            },
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )
    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)
    matrix = release_claims_matrix_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
    )

    checklist = release_checklist_snapshot(
        release_claims_matrix=matrix,
        staged_rollout_telemetry=telemetry,
        final_review_bundle=bundle,
    )

    assert checklist["schema_version"] == "privacy_release_checklist.v1"
    assert checklist["checklist_status"] == "completed"
    assert checklist["completed_count"] == 6
    assert checklist["pending_count"] == 0
    assert all(item["completed"] for item in checklist["items"].values())


def test_release_checklist_compatibility_debt_leaves_expected_items_pending():
    bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "dm_strong_claim": {"allowed": True, "detail": "ready"},
                "gate_transitional_claim": {"allowed": True, "detail": "ready"},
                "private_default_rollout_safe": {"allowed": False, "detail": "debt"},
                "major_blocker": {"state": "compatibility_debt", "detail": "debt"},
            },
            "rollout_health": {"compatibility_cleanup_pending": True},
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )
    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)
    matrix = release_claims_matrix_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
    )

    checklist = release_checklist_snapshot(
        release_claims_matrix=matrix,
        staged_rollout_telemetry=telemetry,
        final_review_bundle=bundle,
    )

    assert checklist["checklist_status"] == "pending"
    assert checklist["items"]["private_default_rollout_claim_truth_confirmed"]["completed"] is False
    assert checklist["items"]["compatibility_cleanup_complete"]["completed"] is False
    assert "compatibility_debt" in checklist["blocker_categories"]


def test_release_checklist_active_override_leaves_expected_items_pending():
    bundle = final_review_bundle_snapshot(
        review_export={
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "dm_strong_claim": {"allowed": True, "detail": "ready"},
                "gate_transitional_claim": {"allowed": True, "detail": "ready"},
                "private_default_rollout_safe": {"allowed": False, "detail": "override"},
                "major_blocker": {"state": "operator_override", "detail": "override"},
            },
            "rollout_controls": {
                "active_overrides": ["attestation_override_active"],
                "compatibility_override_active": True,
                "legacy_compatibility_enabled": True,
            },
            "claim_surface_sources": {
                "surfaces": {
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )
    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)
    matrix = release_claims_matrix_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
    )

    checklist = release_checklist_snapshot(
        release_claims_matrix=matrix,
        staged_rollout_telemetry=telemetry,
        final_review_bundle=bundle,
    )

    assert checklist["checklist_status"] == "pending"
    assert checklist["items"]["private_default_rollout_claim_truth_confirmed"]["completed"] is False
    assert checklist["items"]["no_active_override_posture"]["completed"] is False
    assert "operator_override" in checklist["blocker_categories"]


def test_explicit_review_export_snapshot_contains_expected_consolidated_package():
    bundle = final_review_bundle_snapshot(
        review_export={
            "schema_version": "privacy_review_export.v1",
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "dm_strong_claim": {"allowed": True},
                "gate_transitional_claim": {"allowed": True},
                "private_default_rollout_safe": {"allowed": True},
                "major_blocker": {"state": "none"},
            },
        }
    )
    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)
    matrix = release_claims_matrix_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
    )
    checklist = release_checklist_snapshot(
        release_claims_matrix=matrix,
        staged_rollout_telemetry=telemetry,
        final_review_bundle=bundle,
    )

    export = explicit_review_export_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
        release_claims_matrix=matrix,
        release_checklist=checklist,
    )

    assert export["schema_version"] == "privacy_explicit_review_export.v1"
    assert export["export_kind"] == "explicit_review_export"
    assert export["surface_class"] == "authoritative_export_bundle"
    assert export["source_surface"] == "final_review_bundle"
    assert export["authoritative_model"] == "privacy_claims"
    assert export["export_metadata"]["deterministic"] is True
    assert export["export_metadata"]["identifier_free"] is True
    assert export["export_metadata"]["source_surfaces"] == [
        "final_review_bundle",
        "staged_rollout_telemetry",
        "release_claims_matrix",
        "release_checklist",
    ]
    assert export["final_review_bundle"] == bundle
    assert export["staged_rollout_telemetry"] == telemetry
    assert export["release_claims_matrix"] == matrix
    assert export["release_checklist"] == checklist


def test_explicit_review_export_contract_fixture_is_stable():
    export, _manifest, _consistency = _review_surface_samples()
    assert_surface_contract(export, EXPLICIT_REVIEW_EXPORT_CONTRACT)


def test_review_manifest_contract_fixture_is_stable():
    _export, manifest, _consistency = _review_surface_samples()
    assert_surface_contract(manifest, REVIEW_MANIFEST_CONTRACT)


def test_review_consistency_contract_fixture_is_stable():
    _export, _manifest, consistency = _review_surface_samples()
    assert_surface_contract(consistency, REVIEW_CONSISTENCY_CONTRACT)


def test_review_manifest_contains_expected_summary_and_provenance_mapping():
    bundle = final_review_bundle_snapshot(
        review_export={
            "schema_version": "privacy_review_export.v1",
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "dm_strong_claim": {
                    "allowed": True,
                    "state": "dm_strong_ready",
                    "plain_label": "Strong private ready",
                    "detail": "ready",
                },
                "gate_transitional_claim": {
                    "allowed": True,
                    "state": "gate_transitional_ready",
                    "plain_label": "Transitional private ready",
                    "detail": "ready",
                },
                "private_default_rollout_safe": {
                    "allowed": True,
                    "state": "ready_for_private_default",
                    "plain_label": "Private default safe now",
                    "detail": "ready",
                },
                "major_blocker": {"state": "none"},
            },
            "claim_surface_sources": {
                "surfaces": {
                    "privacy_claims": {"surface_class": "authoritative_diagnostic"},
                    "rollout_readiness": {"surface_class": "authoritative_diagnostic"},
                    "rollout_controls": {"surface_class": "authoritative_diagnostic"},
                    "rollout_health": {"surface_class": "authoritative_diagnostic"},
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )
    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)
    matrix = release_claims_matrix_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
    )
    checklist = release_checklist_snapshot(
        release_claims_matrix=matrix,
        staged_rollout_telemetry=telemetry,
        final_review_bundle=bundle,
    )
    export = explicit_review_export_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
        release_claims_matrix=matrix,
        release_checklist=checklist,
    )

    manifest = review_manifest_snapshot(explicit_review_export=export)

    assert manifest["schema_version"] == "privacy_review_manifest.v1"
    assert manifest["manifest_kind"] == "review_manifest"
    assert manifest["surface_class"] == "authoritative_review_manifest"
    assert manifest["source_surface"] == "explicit_review_export"
    assert manifest["manifest_metadata"]["deterministic"] is True
    assert manifest["manifest_metadata"]["identifier_free"] is True
    assert manifest["claim_summary_rows"]["dm_strong_claim_now"]["allowed"] is True
    assert manifest["claim_summary_rows"]["private_default_rollout_claim_now"]["state"] == "ready_for_private_default"
    assert manifest["checklist_summary"]["checklist_status"] == "completed"
    assert manifest["checklist_summary"]["completed_count"] == 6
    assert manifest["checklist_summary"]["pending_count"] == 0
    assert manifest["evidence_map"]["dm_strong_claim_now"]["source_surfaces"] == [
        "release_claims_matrix",
        "final_review_bundle",
        "review_export",
        "privacy_claims",
    ]
    assert manifest["evidence_map"]["operator_review_package_complete"]["source_surfaces"] == [
        "release_checklist",
        "final_review_bundle",
        "review_export",
        "claim_surface_sources",
    ]


def test_review_consistency_snapshot_reports_aligned_clean_state():
    bundle = final_review_bundle_snapshot(
        review_export={
            "schema_version": "privacy_review_export.v1",
            "authoritative_model": "privacy_claims",
            "review_summary": {
                "dm_strong_claim": {
                    "allowed": True,
                    "state": "dm_strong_ready",
                    "plain_label": "Strong private ready",
                    "detail": "ready",
                },
                "gate_transitional_claim": {
                    "allowed": True,
                    "state": "gate_transitional_ready",
                    "plain_label": "Transitional private ready",
                    "detail": "ready",
                },
                "private_default_rollout_safe": {
                    "allowed": True,
                    "state": "ready_for_private_default",
                    "plain_label": "Private default safe now",
                    "detail": "ready",
                },
                "major_blocker": {"state": "none"},
            },
            "claim_surface_sources": {
                "surfaces": {
                    "privacy_claims": {"surface_class": "authoritative_diagnostic"},
                    "rollout_readiness": {"surface_class": "authoritative_diagnostic"},
                    "rollout_controls": {"surface_class": "authoritative_diagnostic"},
                    "rollout_health": {"surface_class": "authoritative_diagnostic"},
                    "strong_claims": {"surface_class": "compatibility_shim"},
                    "release_gate": {"surface_class": "compatibility_shim"},
                }
            },
        }
    )
    telemetry = staged_rollout_telemetry_snapshot(final_review_bundle=bundle)
    matrix = release_claims_matrix_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
    )
    checklist = release_checklist_snapshot(
        release_claims_matrix=matrix,
        staged_rollout_telemetry=telemetry,
        final_review_bundle=bundle,
    )
    export = explicit_review_export_snapshot(
        final_review_bundle=bundle,
        staged_rollout_telemetry=telemetry,
        release_claims_matrix=matrix,
        release_checklist=checklist,
    )
    manifest = review_manifest_snapshot(explicit_review_export=export)

    consistency = review_consistency_snapshot(
        explicit_review_export=export,
        review_manifest=manifest,
    )

    assert consistency["schema_version"] == "privacy_review_consistency.v1"
    assert consistency["consistency_kind"] == "review_surface_consistency"
    assert consistency["alignment_verdict"]["aligned"] is True
    assert consistency["alignment_verdict"]["state"] == "aligned"
    assert consistency["alignment_verdict"]["detail"] == "Review export and manifest are structurally aligned."
    assert consistency["blocker_category_mismatches"] == {
        "export_only": [],
        "manifest_only": [],
    }
    assert consistency["handoff_summary"]["export_and_manifest_aligned_now"]["allowed"] is True
    assert consistency["handoff_summary"]["claim_rows_fully_backed_by_evidence_now"]["allowed"] is True
    assert consistency["handoff_summary"]["checklist_rows_fully_backed_by_evidence_now"]["allowed"] is True
    assert consistency["handoff_summary"]["blocker_categories_fully_covered_by_provenance"]["allowed"] is True


def test_review_consistency_snapshot_treats_blocker_category_disagreement_as_mismatch():
    export = {
        "schema_version": "privacy_explicit_review_export.v1",
        "surface_class": "authoritative_export_bundle",
        "authoritative_model": "privacy_claims",
        "export_metadata": {
            "deterministic": True,
            "identifier_free": True,
            "source_surfaces": [
                "final_review_bundle",
                "staged_rollout_telemetry",
                "release_claims_matrix",
                "release_checklist",
            ],
        },
        "release_claims_matrix": {
            "rows": {
                "dm_strong_claim_now": {"allowed": True, "state": "dm_strong_ready"},
            },
            "blocker_categories": ["compatibility_debt"],
        },
        "release_checklist": {
            "items": {
                "dm_strong_claim_truth_confirmed": {"completed": True},
            },
        },
    }
    manifest = {
        "surface_class": "authoritative_review_manifest",
        "manifest_metadata": {"deterministic": True, "identifier_free": True},
        "claim_summary_rows": {
            "dm_strong_claim_now": {"allowed": True, "state": "dm_strong_ready"},
        },
        "checklist_summary": {
            "completed_count": 1,
            "pending_count": 0,
            "completed_items": ["dm_strong_claim_truth_confirmed"],
            "pending_items": [],
        },
        "blocker_categories": ["operator_override"],
        "evidence_surfaces": ["release_claims_matrix", "review_export"],
        "evidence_map": {
            "dm_strong_claim_now": {"source_surfaces": ["release_claims_matrix"]},
            "dm_strong_claim_truth_confirmed": {"source_surfaces": ["release_checklist"]},
        },
    }

    consistency = review_consistency_snapshot(
        explicit_review_export=export,
        review_manifest=manifest,
    )

    assert consistency["alignment_verdict"]["aligned"] is False
    assert consistency["alignment_verdict"]["state"] == "not_aligned"
    assert consistency["blocker_category_mismatches"] == {
        "export_only": ["compatibility_debt"],
        "manifest_only": ["operator_override"],
    }
    assert consistency["handoff_summary"]["export_and_manifest_aligned_now"]["allowed"] is False
    assert consistency["handoff_summary"]["claim_rows_fully_backed_by_evidence_now"]["allowed"] is True
    assert consistency["handoff_summary"]["checklist_rows_fully_backed_by_evidence_now"]["allowed"] is True


def test_review_consistency_snapshot_keeps_provenance_separate_from_alignment():
    export = {
        "schema_version": "privacy_explicit_review_export.v1",
        "surface_class": "authoritative_export_bundle",
        "authoritative_model": "privacy_claims",
        "export_metadata": {
            "deterministic": True,
            "identifier_free": True,
            "source_surfaces": [
                "final_review_bundle",
                "staged_rollout_telemetry",
                "release_claims_matrix",
                "release_checklist",
            ],
        },
        "release_claims_matrix": {
            "rows": {
                "dm_strong_claim_now": {"allowed": True, "state": "dm_strong_ready"},
            },
            "blocker_categories": ["compatibility_debt"],
        },
        "release_checklist": {
            "items": {
                "dm_strong_claim_truth_confirmed": {"completed": True},
            },
        },
    }
    manifest = {
        "surface_class": "authoritative_review_manifest",
        "manifest_metadata": {"deterministic": True, "identifier_free": True},
        "claim_summary_rows": {
            "dm_strong_claim_now": {"allowed": True, "state": "dm_strong_ready"},
        },
        "checklist_summary": {
            "completed_count": 1,
            "pending_count": 0,
            "completed_items": ["dm_strong_claim_truth_confirmed"],
            "pending_items": [],
        },
        "blocker_categories": ["compatibility_debt"],
        "evidence_surfaces": ["review_export"],
        "evidence_map": {
            "dm_strong_claim_now": {"source_surfaces": ["release_claims_matrix"]},
            "dm_strong_claim_truth_confirmed": {"source_surfaces": ["release_checklist"]},
        },
    }

    consistency = review_consistency_snapshot(
        explicit_review_export=export,
        review_manifest=manifest,
    )

    assert consistency["alignment_verdict"]["aligned"] is True
    assert consistency["alignment_verdict"]["detail"] == "Review export and manifest are structurally aligned."
    assert "fully backed by evidence" not in consistency["alignment_verdict"]["detail"]
    assert consistency["handoff_summary"]["export_and_manifest_aligned_now"]["allowed"] is True
    assert consistency["handoff_summary"]["blocker_categories_fully_covered_by_provenance"]["allowed"] is False
    assert consistency["handoff_summary"]["blocker_categories_fully_covered_by_provenance"]["state"] == "missing_blocker_provenance"


def test_review_surface_contract_fixtures_are_identifier_free():
    export, manifest, consistency = _review_surface_samples()
    combined = repr(export) + repr(manifest) + repr(consistency)
    assert "recent_targets" not in combined
    assert "agent_id" not in combined


def test_review_surface_corpus_contracts_cover_all_representative_states():
    corpus = review_surface_corpus()

    for state_name, state in corpus.items():
        export = dict(state["explicit_review_export"])
        manifest = dict(state["review_manifest"])
        consistency = dict(state["review_consistency"])
        assert_surface_contract(export, EXPLICIT_REVIEW_EXPORT_CONTRACT)
        assert_surface_contract(manifest, REVIEW_MANIFEST_CONTRACT)
        assert_surface_contract(consistency, REVIEW_CONSISTENCY_CONTRACT)
        assert export["surface_class"] == "authoritative_export_bundle", state_name
        assert manifest["surface_class"] == "authoritative_review_manifest", state_name
        assert consistency["surface_class"] == "authoritative_review_handoff", state_name


def test_review_surface_corpus_has_expected_state_specific_drift_signals():
    corpus = review_surface_corpus()

    clean_ready = corpus["clean_ready"]
    assert clean_ready["explicit_review_export"]["release_claims_matrix"]["blocker_categories"] == []
    assert clean_ready["review_manifest"]["checklist_summary"]["checklist_status"] == "completed"
    assert clean_ready["review_consistency"]["alignment_verdict"]["aligned"] is True

    compatibility_debt = corpus["compatibility_debt"]
    assert compatibility_debt["explicit_review_export"]["release_claims_matrix"]["blocker_categories"] == ["compatibility_debt"]
    assert compatibility_debt["review_manifest"]["checklist_summary"]["checklist_status"] == "pending"
    assert (
        compatibility_debt["review_manifest"]["claim_summary_rows"]["private_default_rollout_claim_now"]["state"]
        == "blocked_by_cleanup_debt"
    )
    assert compatibility_debt["review_consistency"]["alignment_verdict"]["aligned"] is True

    operator_override = corpus["operator_override"]
    assert operator_override["explicit_review_export"]["release_claims_matrix"]["blocker_categories"] == ["operator_override"]
    assert (
        operator_override["explicit_review_export"]["release_checklist"]["items"]["no_active_override_posture"]["completed"]
        is False
    )
    assert operator_override["review_manifest"]["checklist_summary"]["checklist_status"] == "pending"
    assert operator_override["review_consistency"]["alignment_verdict"]["aligned"] is True

    provenance_gap = corpus["provenance_gap"]
    assert provenance_gap["explicit_review_export"]["release_claims_matrix"]["blocker_categories"] == ["compatibility_debt"]
    assert provenance_gap["review_manifest"]["checklist_summary"]["checklist_status"] == "pending"
    assert provenance_gap["review_consistency"]["alignment_verdict"]["aligned"] is True
    assert (
        provenance_gap["review_consistency"]["handoff_summary"]["blocker_categories_fully_covered_by_provenance"]["allowed"]
        is False
    )


def test_review_surface_corpus_is_identifier_free():
    corpus = review_surface_corpus()
    combined = "".join(repr(state) for state in corpus.values())
    assert "recent_targets" not in combined
    assert "agent_id" not in combined


def test_ordinary_status_omits_explicit_review_surfaces_across_corpus_states(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )

    scenarios = {
        "clean_ready": {
            "privacy_core": _attested_current(),
            "compatibility_snapshot": {"usage": {}, "sunset": {}},
        },
        "compatibility_debt": {
            "privacy_core": _attested_current(),
            "compatibility_snapshot": {
                "usage": {
                    "legacy_agent_id_lookup": {
                        "count": 1,
                        "last_seen_at": 1,
                        "blocked_count": 0,
                    }
                },
                "sunset": {},
            },
        },
        "operator_override": {
            "privacy_core": {**_attested_current(), "override_active": True},
            "compatibility_snapshot": {"usage": {}, "sunset": {}},
        },
        "provenance_gap": {
            "privacy_core": _attested_current(),
            "compatibility_snapshot": {"usage": {}, "sunset": {}},
        },
    }

    for scenario in scenarios.values():
        monkeypatch.setattr(main, "_privacy_core_status", lambda scenario=scenario: scenario["privacy_core"])
        monkeypatch.setattr(
            main,
            "compatibility_status_snapshot",
            lambda scenario=scenario: scenario["compatibility_snapshot"],
        )
        result = asyncio.run(main.api_wormhole_status(_request("/api/wormhole/status")))

        assert "explicit_review_export" not in result
        assert "review_manifest" not in result
        assert "review_consistency" not in result


def test_ordinary_status_omits_detailed_claim_matrix(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "_privacy_core_status", lambda: _attested_current())
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )

    result = asyncio.run(main.api_wormhole_status(_request("/api/wormhole/status")))

    assert "privacy_claims" not in result
    assert "rollout_readiness" not in result
    assert "rollout_controls" not in result
    assert "rollout_health" not in result
    assert "claim_surface_sources" not in result
    assert "review_export" not in result
    assert "final_review_bundle" not in result
    assert "staged_rollout_telemetry" not in result
    assert "release_claims_matrix" not in result
    assert "release_checklist" not in result
    assert "explicit_review_export" not in result
    assert "review_manifest" not in result
    assert "review_consistency" not in result
    assert result["strong_claims"]["allowed"] is False
    assert result["release_gate"]["ready"] is False
    assert result["privacy_status"]["state"] == "dm_strong_pending"
    assert "blockers" not in result["privacy_status"]


def test_diagnostic_status_exposes_detailed_claim_matrix(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "_privacy_core_status", lambda: _attested_current())
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )
    monkeypatch.setattr(
        main,
        "_strong_claims_policy_snapshot",
        lambda **_kwargs: _strong_claims_good(),
    )
    monkeypatch.setattr(
        main,
        "_release_gate_status",
        lambda **_kwargs: {
            **_release_gate_good(),
            "compatibility_shim": True,
            "source_model": "privacy_claims",
            "authoritative_dm_claim_state": "dm_strong_ready",
            "authoritative_gate_claim_state": "gate_transitional_ready",
        },
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )

    result = asyncio.run(
        main.api_wormhole_status(_request("/api/wormhole/status?exposure=diagnostic"))
    )

    assert result["privacy_claims"]["transport_tier"] == "private_strong"
    assert result["privacy_claims"]["claims"]["dm_strong"]["state"] == "dm_strong_ready"
    assert result["privacy_claims"]["claims"]["gate_transitional"]["state"] == "gate_transitional_ready"
    assert result["privacy_claims"]["claims"]["control_only_posture"]["state"] == "control_only_local_only"
    assert result["privacy_claims"]["claims"]["degraded_posture"]["state"] == "degraded_requires_approval"
    assert result["privacy_status"]["state"] == "dm_strong_ready"
    assert result["rollout_readiness"]["state"] == "ready_for_private_default"
    assert result["rollout_controls"]["state"] == "private_default_safe"
    assert result["rollout_health"]["state"] == "healthy"
    assert result["claim_surface_sources"]["authoritative_model"] == "privacy_claims"
    assert result["review_export"]["schema_version"] == "privacy_review_export.v1"
    assert result["review_export"]["review_summary"]["dm_strong_claim"]["allowed"] is True
    assert result["review_export"]["review_summary"]["private_default_rollout_safe"]["allowed"] is True
    assert result["review_export"]["review_summary"]["major_blocker"]["state"] == "none"
    assert result["final_review_bundle"]["schema_version"] == "privacy_final_review_bundle.v1"
    assert result["final_review_bundle"]["release_readiness_verdict"]["state"] == "release_ready"
    assert result["final_review_bundle"]["review_completeness"]["identifier_free"] is True
    assert result["staged_rollout_telemetry"]["schema_version"] == "privacy_staged_rollout_telemetry.v1"
    assert result["staged_rollout_telemetry"]["rollout_stage_recommendation"] == "private_default_canary"
    assert result["staged_rollout_telemetry"]["rollout_safe_now"] is True
    assert result["release_claims_matrix"]["schema_version"] == "privacy_release_claims_matrix.v1"
    assert result["release_claims_matrix"]["rows"]["dm_strong_claim_now"]["allowed"] is True
    assert result["release_claims_matrix"]["rows"]["gate_transitional_claim_now"]["allowed"] is True
    assert result["release_claims_matrix"]["rows"]["private_default_rollout_claim_now"]["allowed"] is True
    assert result["release_checklist"]["schema_version"] == "privacy_release_checklist.v1"
    assert result["release_checklist"]["checklist_status"] == "completed"
    assert result["release_checklist"]["completed_count"] == 6
    assert result["release_checklist"]["pending_count"] == 0
    assert result["claim_surface_sources"]["surfaces"]["privacy_claims"]["surface_class"] == "authoritative_diagnostic"
    assert result["claim_surface_sources"]["surfaces"]["privacy_status"]["surface_class"] == "coarse_ordinary_summary"
    assert result["strong_claims"]["source_model"] == "privacy_claims"
    assert result["strong_claims"]["source_surface"] == "privacy_claims"
    assert result["strong_claims"]["surface_class"] == "compatibility_shim"
    assert result["strong_claims"]["authoritative_claim_state"] == "dm_strong_ready"
    assert result["release_gate"]["source_model"] == "rollout_readiness"
    assert result["release_gate"]["source_surface"] == "rollout_readiness"
    assert result["release_gate"]["surface_class"] == "compatibility_shim"
    assert result["release_gate"]["authoritative_gate_claim_state"] == "gate_transitional_ready"
    assert result["release_gate"]["authoritative_rollout_state"] == "ready_for_private_default"
    assert result["release_gate"]["ready"] == result["rollout_readiness"]["allowed"]


def test_ordinary_settings_status_omits_detailed_claim_matrix(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "_privacy_core_status", lambda: _attested_current())
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )

    result = asyncio.run(
        main.api_get_wormhole_status(_request("/api/settings/wormhole-status"))
    )

    assert "privacy_claims" not in result
    assert "rollout_readiness" not in result
    assert "rollout_controls" not in result
    assert "rollout_health" not in result
    assert "claim_surface_sources" not in result
    assert "review_export" not in result
    assert "final_review_bundle" not in result
    assert "staged_rollout_telemetry" not in result
    assert "release_claims_matrix" not in result
    assert "release_checklist" not in result
    assert "explicit_review_export" not in result
    assert "review_manifest" not in result
    assert "review_consistency" not in result
    assert result["strong_claims"]["allowed"] is False
    assert result["release_gate"]["ready"] is False
    assert result["privacy_status"]["state"] == "dm_strong_pending"
    assert "blockers" not in result["privacy_status"]


def test_diagnostic_settings_status_matches_wormhole_status_claims(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "_privacy_core_status", lambda: _attested_current())
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "_strong_claims_policy_snapshot",
        lambda **_kwargs: _strong_claims_good(),
    )
    monkeypatch.setattr(
        main,
        "_release_gate_status",
        lambda **_kwargs: {
            **_release_gate_good(),
            "compatibility_shim": True,
            "source_model": "privacy_claims",
            "authoritative_dm_claim_state": "dm_strong_ready",
            "authoritative_gate_claim_state": "gate_transitional_ready",
        },
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )

    wormhole = asyncio.run(
        main.api_wormhole_status(_request("/api/wormhole/status?exposure=diagnostic"))
    )
    settings = asyncio.run(
        main.api_get_wormhole_status(
            _request("/api/settings/wormhole-status?exposure=diagnostic")
        )
    )

    assert settings["privacy_claims"] == wormhole["privacy_claims"]
    assert settings["privacy_status"] == wormhole["privacy_status"]
    assert settings["rollout_readiness"] == wormhole["rollout_readiness"]
    assert settings["rollout_controls"] == wormhole["rollout_controls"]
    assert settings["rollout_health"] == wormhole["rollout_health"]
    assert settings["claim_surface_sources"] == wormhole["claim_surface_sources"]
    assert settings["review_export"] == wormhole["review_export"]
    assert settings["final_review_bundle"] == wormhole["final_review_bundle"]
    assert settings["staged_rollout_telemetry"] == wormhole["staged_rollout_telemetry"]
    assert settings["release_claims_matrix"] == wormhole["release_claims_matrix"]
    assert settings["release_checklist"] == wormhole["release_checklist"]
    assert (
        settings["privacy_claims"]["claims"]["gate_transitional"]["state"]
        == "gate_transitional_ready"
    )


def test_settings_gate_transitional_claim_is_not_blocked_by_omitted_inputs(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "_privacy_core_status", lambda: _attested_current())
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 1},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )

    result = asyncio.run(
        main.api_get_wormhole_status(
            _request("/api/settings/wormhole-status?exposure=diagnostic")
        )
    )

    gate = result["privacy_claims"]["claims"]["gate_transitional"]
    assert gate["allowed"] is True
    assert gate["state"] == "gate_transitional_ready"
    assert gate["blockers"] == []


def test_compatibility_shim_surfaces_track_authoritative_claim_states(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "_privacy_core_status", lambda: _attested_current())
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )

    result = asyncio.run(
        main.api_wormhole_status(_request("/api/wormhole/status?exposure=diagnostic"))
    )

    assert result["strong_claims"]["compatibility_shim"] is True
    assert result["strong_claims"]["surface_class"] == "compatibility_shim"
    assert result["strong_claims"]["authoritative_claim"] == "dm_strong"
    assert result["strong_claims"]["authoritative_claim_state"] == result["privacy_claims"]["claims"]["dm_strong"]["state"]
    assert result["strong_claims"]["coarse_surface_consistent"] is True
    assert result["release_gate"]["compatibility_shim"] is True
    assert result["release_gate"]["surface_class"] == "compatibility_shim"
    assert result["release_gate"]["authoritative_dm_claim_state"] == result["privacy_claims"]["claims"]["dm_strong"]["state"]
    assert result["release_gate"]["authoritative_gate_claim_state"] == result["privacy_claims"]["claims"]["gate_transitional"]["state"]
    assert result["release_gate"]["authoritative_rollout_state"] == result["rollout_readiness"]["state"]
    assert result["release_gate"]["ready"] == result["rollout_readiness"]["allowed"]
    assert result["release_gate"]["authoritative_rollout_consistent"] is True


def test_ordinary_wormhole_status_coarse_chip_does_not_contradict_legacy_shim_booleans(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "_privacy_core_status", lambda: _attested_current())
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )

    result = asyncio.run(main.api_wormhole_status(_request("/api/wormhole/status")))

    assert result["strong_claims"]["allowed"] is False
    assert result["release_gate"]["ready"] is False
    assert result["privacy_status"]["state"] not in {"dm_strong_ready", "gate_transitional_ready"}


def test_ordinary_settings_status_coarse_chip_does_not_contradict_legacy_shim_booleans(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "_privacy_core_status", lambda: _attested_current())
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )

    result = asyncio.run(
        main.api_get_wormhole_status(_request("/api/settings/wormhole-status"))
    )

    assert result["strong_claims"]["allowed"] is False
    assert result["release_gate"]["ready"] is False
    assert result["privacy_status"]["state"] not in {"dm_strong_ready", "gate_transitional_ready"}


def test_diagnostic_claim_surface_sources_are_explicit_and_identifier_free(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "_privacy_core_status", lambda: _attested_current())
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )

    result = asyncio.run(
        main.api_wormhole_status(_request("/api/wormhole/status?exposure=diagnostic"))
    )

    annotations = result["claim_surface_sources"]
    assert annotations["authoritative_model"] == "privacy_claims"
    assert annotations["surfaces"]["privacy_status"]["surface_class"] == "coarse_ordinary_summary"
    assert annotations["surfaces"]["strong_claims"]["surface_class"] == "compatibility_shim"
    assert annotations["surfaces"]["release_gate"]["source_surface"] == "rollout_readiness"
    assert "recent_targets" not in repr(annotations)


def test_live_diagnostic_review_export_prefers_override_over_ready_readiness(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "_privacy_core_status", lambda: {**_attested_current(), "override_active": True})
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(main, "compatibility_status_snapshot", lambda: {"usage": {}, "sunset": {}})
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "_strong_claims_policy_snapshot",
        lambda **_kwargs: _strong_claims_good(),
    )
    monkeypatch.setattr(
        main,
        "_release_gate_status",
        lambda **_kwargs: {
            **_release_gate_good(),
            "compatibility_shim": True,
            "source_model": "privacy_claims",
            "authoritative_dm_claim_state": "dm_strong_ready",
            "authoritative_gate_claim_state": "gate_transitional_ready",
        },
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "active_handle_count": 1,
            "fresh_handle_available": True,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )

    result = asyncio.run(
        main.api_wormhole_status(_request("/api/wormhole/status?exposure=diagnostic"))
    )

    assert result["rollout_readiness"]["state"] == "ready_for_private_default"
    assert result["rollout_controls"]["state"] == "override_active"
    assert result["review_export"]["review_summary"]["private_default_rollout_safe"]["allowed"] is False
    assert result["review_export"]["review_summary"]["private_default_rollout_safe"]["state"] == "blocked_by_operator_override"
    assert result["review_export"]["review_summary"]["major_blocker"]["state"] == "operator_override"


def test_rollout_diagnostics_are_identifier_free(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )
    monkeypatch.setattr(main, "_privacy_core_status", lambda: _attested_current())
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: _protected_custody())
    monkeypatch.setattr(
        main,
        "compatibility_status_snapshot",
        lambda: {
            "usage": {
                "legacy_agent_id_lookup": {
                    "count": 1,
                    "last_seen_at": 1,
                    "blocked_count": 0,
                    "recent_targets": [{"agent_id": "sb://raw-id"}],
                }
            },
            "sunset": {},
        },
    )
    monkeypatch.setattr(main, "gate_privileged_access_status_snapshot", _gate_privilege_ok)
    monkeypatch.setattr(
        main,
        "_upgrade_invite_scoped_contact_preferences_background",
        lambda: {"ok": True, "upgraded_contacts": 0},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_pending",
            "detail": "lookup handle rollover pending",
            "active_handle_count": 1,
            "fresh_handle_available": False,
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": False, "rotated": False},
    )

    result = asyncio.run(
        main.api_wormhole_status(_request("/api/wormhole/status?exposure=diagnostic"))
    )

    rollout_text = (
        repr(result["rollout_controls"])
        + repr(result["rollout_health"])
        + repr(result["review_export"])
        + repr(result["final_review_bundle"])
        + repr(result["staged_rollout_telemetry"])
        + repr(result["release_claims_matrix"])
        + repr(result["release_checklist"])
        + repr(
            explicit_review_export_snapshot(
                final_review_bundle=result["final_review_bundle"],
                staged_rollout_telemetry=result["staged_rollout_telemetry"],
                release_claims_matrix=result["release_claims_matrix"],
                release_checklist=result["release_checklist"],
            )
        )
        + repr(
            review_manifest_snapshot(
                explicit_review_export=explicit_review_export_snapshot(
                    final_review_bundle=result["final_review_bundle"],
                    staged_rollout_telemetry=result["staged_rollout_telemetry"],
                    release_claims_matrix=result["release_claims_matrix"],
                    release_checklist=result["release_checklist"],
                )
            )
        )
        + repr(
            review_consistency_snapshot(
                explicit_review_export=explicit_review_export_snapshot(
                    final_review_bundle=result["final_review_bundle"],
                    staged_rollout_telemetry=result["staged_rollout_telemetry"],
                    release_claims_matrix=result["release_claims_matrix"],
                    release_checklist=result["release_checklist"],
                ),
                review_manifest=review_manifest_snapshot(
                    explicit_review_export=explicit_review_export_snapshot(
                        final_review_bundle=result["final_review_bundle"],
                        staged_rollout_telemetry=result["staged_rollout_telemetry"],
                        release_claims_matrix=result["release_claims_matrix"],
                        release_checklist=result["release_checklist"],
                    )
                ),
            )
        )
    )
    assert "recent_targets" not in rollout_text
    assert "sb://raw-id" not in rollout_text
