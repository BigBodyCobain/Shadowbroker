from __future__ import annotations

from typing import Any

from services.mesh.mesh_privacy_policy import (
    release_lane_required_tier,
    transport_tier_is_sufficient,
)
from services.release_profiles import profile_readiness_snapshot


def _normalize_tier(value: str | None) -> str:
    candidate = str(value or "").strip().lower()
    if candidate:
        return candidate
    return "public_degraded"


def _claim_entry(
    *,
    allowed: bool,
    state: str,
    plain_label: str,
    blockers: list[str],
    detail: str,
    required_tier: str = "",
    current_tier: str = "",
) -> dict[str, Any]:
    return {
        "allowed": bool(allowed),
        "state": str(state or ""),
        "plain_label": str(plain_label or ""),
        "blockers": [str(blocker or "") for blocker in blockers if str(blocker or "").strip()],
        "detail": str(detail or ""),
        "required_tier": str(required_tier or ""),
        "current_tier": str(current_tier or ""),
    }


def _dm_claim_blockers(
    *,
    current_tier: str,
    local_custody: dict[str, Any],
    privacy_core: dict[str, Any],
    compatibility_readiness: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    required_tier = release_lane_required_tier("dm")
    if not transport_tier_is_sufficient(current_tier, required_tier):
        blockers.append("transport_tier_not_private_strong")
    if str(privacy_core.get("attestation_state", "") or "") != "attested_current":
        blockers.append("privacy_core_attestation_not_current")
    if not bool(local_custody.get("protected_at_rest", False)):
        blockers.append("local_custody_not_protected_at_rest")
    if bool(compatibility_readiness.get("stored_legacy_lookup_contacts_present", False)):
        blockers.append("compatibility_stored_legacy_lookup_contacts_present")
    if bool(compatibility_readiness.get("legacy_lookup_runtime_active", False)):
        blockers.append("compatibility_legacy_lookup_runtime_active")
    if bool(compatibility_readiness.get("legacy_mailbox_get_runtime_active", False)):
        blockers.append("compatibility_legacy_mailbox_get_runtime_active")
    if bool(compatibility_readiness.get("legacy_mailbox_get_enabled", False)):
        blockers.append("compatibility_legacy_mailbox_get_enabled")
    if compatibility_readiness and not bool(compatibility_readiness.get("local_contact_upgrade_ok", True)):
        blockers.append("compatibility_local_contact_upgrade_incomplete")
    return blockers


def _gate_claim_blockers(
    *,
    current_tier: str,
    local_custody: dict[str, Any],
    privacy_core: dict[str, Any],
    gate_privilege_access: dict[str, Any],
    gate_repair: dict[str, Any] | None,
) -> list[str]:
    blockers: list[str] = []
    required_tier = release_lane_required_tier("gate")
    if not transport_tier_is_sufficient(current_tier, required_tier):
        blockers.append(f"transport_tier_not_{required_tier}")
    if str(privacy_core.get("attestation_state", "") or "") != "attested_current":
        blockers.append("privacy_core_attestation_not_current")
    if not bool(local_custody.get("protected_at_rest", False)):
        blockers.append("local_custody_not_protected_at_rest")
    if str(gate_privilege_access.get("privileged_gate_event_scope_class", "") or "") != "explicit_gate_audit":
        blockers.append("gate_privileged_event_scope_not_explicit_audit")
    if str(gate_privilege_access.get("repair_detail_scope_class", "") or "") != "local_operator_diagnostic":
        blockers.append("gate_repair_scope_not_local_operator_diagnostic")
    try:
        from services.mesh.mesh_rollout_flags import (
            gate_ban_kick_rotation_enabled,
            gate_previous_secret_ttl_s,
        )

        if not bool(gate_ban_kick_rotation_enabled()):
            blockers.append("gate_ban_kick_rotation_disabled")
        if int(gate_previous_secret_ttl_s() or 0) <= 0:
            blockers.append("gate_previous_secret_ttl_disabled")
    except Exception:
        blockers.append("gate_secret_lifecycle_policy_unavailable")
    if gate_repair:
        repair_state = str(gate_repair.get("repair_state", "") or "").strip()
        if repair_state in {"gate_state_stale", "gate_state_resync_failed", "gate_state_recovery_only"}:
            blockers.append(repair_state)
    return blockers


def _detail_from_blockers(blockers: list[str], *, ready_detail: str, blocked_detail: str) -> str:
    if not blockers:
        return ready_detail
    return f"{blocked_detail}: {', '.join(blockers)}"


def _privacy_status_chip(
    *,
    claims: dict[str, dict[str, Any]],
    current_tier: str,
) -> dict[str, Any]:
    degraded = dict(claims.get("degraded_posture") or {})
    control_only = dict(claims.get("control_only_posture") or {})
    dm = dict(claims.get("dm_strong") or {})
    gate = dict(claims.get("gate_transitional") or {})

    if bool(degraded.get("allowed", False)):
        return {
            "state": "degraded_requires_approval",
            "plain_label": "Needs approval for weaker privacy",
            "detail": "Private delivery is unavailable; weaker delivery would require approval.",
            "authoritative_claim": "degraded_posture",
        }
    if bool(control_only.get("allowed", False)):
        return {
            "state": "control_only_local_only",
            "plain_label": "Local private operations only",
            "detail": "Local private work can continue, but network release is still blocked.",
            "authoritative_claim": "control_only_posture",
        }
    if bool(dm.get("allowed", False)):
        return {
            "state": "dm_strong_ready",
            "plain_label": "Strong private delivery ready",
            "detail": "The strongest private delivery claim is currently available.",
            "authoritative_claim": "dm_strong",
        }
    if bool(gate.get("allowed", False)):
        return {
            "state": "gate_transitional_ready",
            "plain_label": "Transitional private delivery ready",
            "detail": "Private delivery is available on the current transitional posture.",
            "authoritative_claim": "gate_transitional",
        }
    if current_tier == "private_strong":
        return {
            "state": "dm_strong_blocked",
            "plain_label": "Strong private delivery blocked",
            "detail": "The strongest private delivery claim is blocked by current safeguards.",
            "authoritative_claim": "dm_strong",
        }
    if current_tier == "private_transitional":
        return {
            "state": "gate_transitional_blocked",
            "plain_label": "Transitional private delivery blocked",
            "detail": "Private delivery is blocked by current safeguards.",
            "authoritative_claim": "gate_transitional",
        }
    return {
        "state": "privacy_claims_pending",
        "plain_label": "Private delivery checks pending",
        "detail": "Private delivery posture is not yet ready.",
        "authoritative_claim": "",
    }


def privacy_status_surface_chip(
    snapshot: dict[str, Any] | None,
    *,
    strong_claims_allowed: bool | None = None,
    release_gate_ready: bool | None = None,
) -> dict[str, Any]:
    claims_snapshot = dict(snapshot or {})
    chip = dict(claims_snapshot.get("chip") or {})
    state = str(chip.get("state", "") or "").strip()
    if state not in {"dm_strong_ready", "gate_transitional_ready"}:
        return chip
    if strong_claims_allowed is not False and release_gate_ready is not False:
        return chip
    if state == "dm_strong_ready":
        return {
            "state": "dm_strong_pending",
            "plain_label": "Strong private delivery checks pending",
            "detail": "Strong private delivery is available, but stricter rollout checks are still pending.",
            "authoritative_claim": "dm_strong",
        }
    return {
        "state": "gate_transitional_pending",
        "plain_label": "Transitional private delivery checks pending",
        "detail": "Transitional private delivery is available, but stricter rollout checks are still pending.",
        "authoritative_claim": "gate_transitional",
    }


def claim_surface_catalog() -> dict[str, Any]:
    return {
        "authoritative_model": "privacy_claims",
        "surfaces": {
            "privacy_status": {
                "surface_class": "coarse_ordinary_summary",
                "source_surface": "privacy_claims",
            },
            "privacy_claims": {
                "surface_class": "authoritative_diagnostic",
                "source_surface": "privacy_claims",
            },
            "rollout_readiness": {
                "surface_class": "authoritative_diagnostic",
                "source_surface": "rollout_readiness",
            },
            "rollout_controls": {
                "surface_class": "authoritative_diagnostic",
                "source_surface": "rollout_controls",
            },
            "rollout_health": {
                "surface_class": "authoritative_diagnostic",
                "source_surface": "rollout_health",
            },
            "strong_claims": {
                "surface_class": "compatibility_shim",
                "source_surface": "privacy_claims",
            },
            "release_gate": {
                "surface_class": "compatibility_shim",
                "source_surface": "rollout_readiness",
            },
            "review_export": {
                "surface_class": "authoritative_export_bundle",
                "source_surface": "privacy_claims",
            },
            "final_review_bundle": {
                "surface_class": "authoritative_export_bundle",
                "source_surface": "review_export",
            },
            "staged_rollout_telemetry": {
                "surface_class": "authoritative_diagnostic",
                "source_surface": "final_review_bundle",
            },
            "release_claims_matrix": {
                "surface_class": "authoritative_diagnostic",
                "source_surface": "final_review_bundle",
            },
            "release_checklist": {
                "surface_class": "authoritative_diagnostic",
                "source_surface": "release_claims_matrix",
            },
            "explicit_review_export": {
                "surface_class": "authoritative_export_bundle",
                "source_surface": "final_review_bundle",
            },
            "review_manifest": {
                "surface_class": "authoritative_review_manifest",
                "source_surface": "explicit_review_export",
            },
            "review_consistency": {
                "surface_class": "authoritative_review_handoff",
                "source_surface": "review_manifest",
            },
        },
    }


def _review_major_blocker_summary(
    rollout_readiness: dict[str, Any],
    rollout_controls: dict[str, Any],
    rollout_health: dict[str, Any],
) -> dict[str, Any]:
    readiness_state = str(rollout_readiness.get("state", "") or "").strip()
    controls_state = str(rollout_controls.get("state", "") or "").strip()
    health_state = str(rollout_health.get("state", "") or "").strip()
    if controls_state == "override_active":
        return {
            "state": "operator_override",
            "plain_label": "Blocked by active override",
            "detail": "An active override still blocks private-default rollout.",
        }
    if health_state == "cleanup_debt_present":
        return {
            "state": "compatibility_debt",
            "plain_label": "Compatibility debt remains",
            "detail": "Compatibility cleanup debt remains before full rollout confidence.",
        }
    blocker_map = {
        "ready_for_private_default": ("none", "No major blocker", "Private-default rollout is ready."),
        "ready_with_compatibility_debt": (
            "compatibility_debt",
            "Compatibility debt remains",
            "Private-default rollout is available, but compatibility cleanup debt remains.",
        ),
        "blocked_by_attestation": (
            "attestation",
            "Blocked by privacy-core attestation",
            "Privacy-core attestation still blocks private-default rollout.",
        ),
        "blocked_by_local_custody": (
            "local_custody",
            "Blocked by local custody",
            "Local custody still blocks private-default rollout.",
        ),
        "blocked_by_compatibility": (
            "compatibility",
            "Blocked by compatibility posture",
            "Compatibility posture still blocks private-default rollout.",
        ),
        "blocked_by_operator_override": (
            "operator_override",
            "Blocked by active override",
            "An active override still blocks private-default rollout.",
        ),
        "requires_operator_attention": (
            "operator_attention",
            "Requires operator attention",
            "Rollout readiness still requires operator attention.",
        ),
        }
    if readiness_state in blocker_map:
        state, plain_label, detail = blocker_map[readiness_state]
        return {
            "state": state,
            "plain_label": plain_label,
            "detail": detail,
        }
    return {
        "state": "unknown",
        "plain_label": "Review export pending",
        "detail": "The review export could not classify the major blocker state.",
    }


def _review_effective_rollout_safety_summary(
    rollout_readiness: dict[str, Any],
    rollout_controls: dict[str, Any],
    rollout_health: dict[str, Any],
) -> dict[str, Any]:
    readiness_state = str(rollout_readiness.get("state", "") or "").strip()
    controls_state = str(rollout_controls.get("state", "") or "").strip()
    health_state = str(rollout_health.get("state", "") or "").strip()
    if controls_state == "override_active":
        return {
            "allowed": False,
            "state": "blocked_by_operator_override",
            "plain_label": "Private default blocked by override",
            "detail": "Private-default rollout is not safe because an active override is still present.",
            "raw_readiness_state": readiness_state,
        }
    if health_state == "cleanup_debt_present":
        return {
            "allowed": False,
            "state": "blocked_by_cleanup_debt",
            "plain_label": "Private default blocked by cleanup debt",
            "detail": "Private-default rollout is not yet safe because cleanup debt still remains.",
            "raw_readiness_state": readiness_state,
        }
    rollout_safe = bool(rollout_controls.get("private_default_enforce_safe", False))
    if rollout_safe:
        return {
            "allowed": True,
            "state": readiness_state or "ready_for_private_default",
            "plain_label": "Private default safe now",
            "detail": "Private-default rollout is safe to enforce now.",
            "raw_readiness_state": readiness_state,
        }
    return {
        "allowed": False,
        "state": readiness_state or "requires_operator_attention",
        "plain_label": "Private default not yet safe",
        "detail": str(rollout_readiness.get("detail", "") or "").strip()
        or "Private-default rollout is not yet safe to enforce.",
        "raw_readiness_state": readiness_state,
    }


def review_export_snapshot(
    *,
    privacy_claims: dict[str, Any] | None = None,
    rollout_readiness: dict[str, Any] | None = None,
    rollout_controls: dict[str, Any] | None = None,
    rollout_health: dict[str, Any] | None = None,
    claim_surface_sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    claims_snapshot = dict(privacy_claims or {})
    claims = dict(claims_snapshot.get("claims") or {})
    dm_claim = dict(claims.get("dm_strong") or {})
    gate_claim = dict(claims.get("gate_transitional") or {})
    readiness = dict(rollout_readiness or {})
    controls = dict(rollout_controls or {})
    health = dict(rollout_health or {})
    sources = dict(claim_surface_sources or claim_surface_catalog())
    effective_rollout_safety = _review_effective_rollout_safety_summary(
        readiness,
        controls,
        health,
    )
    return {
        "schema_version": "privacy_review_export.v1",
        "export_kind": "privacy_review_export",
        "surface_class": "authoritative_export_bundle",
        "authoritative_model": "privacy_claims",
        "identifier_free": True,
        "review_summary": {
            "dm_strong_claim": {
                "allowed": bool(dm_claim.get("allowed", False)),
                "state": str(dm_claim.get("state", "") or "").strip(),
                "plain_label": str(dm_claim.get("plain_label", "") or "").strip(),
                "detail": str(dm_claim.get("detail", "") or "").strip(),
            },
            "gate_transitional_claim": {
                "allowed": bool(gate_claim.get("allowed", False)),
                "state": str(gate_claim.get("state", "") or "").strip(),
                "plain_label": str(gate_claim.get("plain_label", "") or "").strip(),
                "detail": str(gate_claim.get("detail", "") or "").strip(),
            },
            "private_default_rollout_safe": effective_rollout_safety,
            "major_blocker": _review_major_blocker_summary(readiness, controls, health),
        },
        "privacy_claims": claims_snapshot,
        "rollout_readiness": readiness,
        "rollout_controls": controls,
        "rollout_health": health,
        "claim_surface_sources": sources,
    }


def _final_review_verdict(review_export: dict[str, Any]) -> dict[str, Any]:
    summary = dict(review_export.get("review_summary") or {})
    rollout_safe = dict(summary.get("private_default_rollout_safe") or {})
    major_blocker = dict(summary.get("major_blocker") or {})
    blocker_state = str(major_blocker.get("state", "") or "").strip()
    if bool(rollout_safe.get("allowed", False)):
        return {
            "state": "release_ready",
            "plain_label": "Release ready",
            "detail": "The release-readiness package does not show an active blocker.",
        }
    if blocker_state == "compatibility_debt":
        return {
            "state": "release_ready_with_debt",
            "plain_label": "Release ready with debt",
            "detail": "The release is assessable, but compatibility cleanup debt remains.",
        }
    if blocker_state in {"attestation", "local_custody", "compatibility", "operator_override"}:
        return {
            "state": "release_blocked",
            "plain_label": "Release blocked",
            "detail": str(major_blocker.get("detail", "") or "").strip()
            or "A release blocker still remains.",
        }
    return {
        "state": "operator_attention_required",
        "plain_label": "Operator attention required",
        "detail": str(major_blocker.get("detail", "") or "").strip()
        or "The release package still requires operator attention.",
    }


def _final_review_blocker_categories(review_export: dict[str, Any]) -> list[str]:
    categories: list[str] = []
    summary = dict(review_export.get("review_summary") or {})
    major_blocker = dict(summary.get("major_blocker") or {})
    blocker_state = str(major_blocker.get("state", "") or "").strip()
    if blocker_state and blocker_state not in {"none", "unknown"}:
        categories.append(blocker_state)
    rollout_controls = dict(review_export.get("rollout_controls") or {})
    if str(rollout_controls.get("state", "") or "").strip() == "override_active":
        categories.append("operator_override")
    rollout_health = dict(review_export.get("rollout_health") or {})
    if str(rollout_health.get("state", "") or "").strip() == "cleanup_debt_present":
        categories.append("compatibility_debt")
    rollout_readiness = dict(review_export.get("rollout_readiness") or {})
    for blocker in list(rollout_readiness.get("blockers") or []):
        normalized = str(blocker or "").strip()
        if not normalized:
            continue
        if normalized.startswith("privacy_core_"):
            categories.append("attestation")
        elif normalized.startswith("local_custody_"):
            categories.append("local_custody")
        elif normalized.startswith("compatibility_"):
            categories.append("compatibility")
        elif normalized.startswith("operator_override_"):
            categories.append("operator_override")
        elif normalized.startswith("gate_"):
            categories.append("gate_posture")
        elif normalized.startswith("transport_tier_"):
            categories.append("transport_posture")
        else:
            categories.append("operator_attention")
    normalized_categories: list[str] = []
    for category in categories:
        normalized = str(category or "").strip()
        if normalized and normalized not in normalized_categories:
            normalized_categories.append(normalized)
    return normalized_categories


def final_review_bundle_snapshot(
    *,
    review_export: dict[str, Any] | None = None,
) -> dict[str, Any]:
    package = dict(review_export or {})
    claim_surface_sources = dict(package.get("claim_surface_sources") or {})
    surfaces = dict(claim_surface_sources.get("surfaces") or {})
    return {
        "schema_version": "privacy_final_review_bundle.v1",
        "bundle_kind": "final_review_bundle",
        "surface_class": "authoritative_export_bundle",
        "source_surface": "review_export",
        "authoritative_model": str(package.get("authoritative_model", "privacy_claims") or "privacy_claims"),
        "review_completeness": {
            "deterministic": True,
            "identifier_free": True,
            "sourced_from_authoritative_model": True,
        },
        "release_readiness_verdict": _final_review_verdict(package),
        "blocker_categories": _final_review_blocker_categories(package),
        "compatibility_shim_provenance": {
            "strong_claims": dict(surfaces.get("strong_claims") or {}),
            "release_gate": dict(surfaces.get("release_gate") or {}),
        },
        "review_export": package,
    }


def staged_rollout_telemetry_snapshot(
    *,
    final_review_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = dict(final_review_bundle or {})
    review_export = dict(bundle.get("review_export") or {})
    summary = dict(review_export.get("review_summary") or {})
    rollout_safe = dict(summary.get("private_default_rollout_safe") or {})
    rollout_controls = dict(review_export.get("rollout_controls") or {})
    rollout_health = dict(review_export.get("rollout_health") or {})
    verdict = dict(bundle.get("release_readiness_verdict") or {})
    blocker_categories = [
        str(item or "").strip()
        for item in list(bundle.get("blocker_categories") or [])
        if str(item or "").strip()
    ]
    active_overrides = [
        str(item or "").strip()
        for item in list(rollout_controls.get("active_overrides") or [])
        if str(item or "").strip()
    ]
    compatibility_allowances_active = bool(
        rollout_controls.get("compatibility_override_active", False)
        or rollout_controls.get("legacy_compatibility_enabled", False)
    )
    effective_safe_now = bool(rollout_safe.get("allowed", False))
    cleanup_complete = not bool(rollout_health.get("compatibility_cleanup_pending", False))
    if effective_safe_now and cleanup_complete:
        stage_recommendation = "private_default_canary"
        plain_label = "Canary rollout safe"
        detail = "Rollout telemetry indicates a canary private-default rollout is safe now."
    elif str(verdict.get("state", "") or "").strip() == "release_ready_with_debt":
        stage_recommendation = "private_default_canary_with_debt"
        plain_label = "Canary rollout safe with debt"
        detail = "Rollout telemetry indicates canary rollout is possible, but cleanup debt remains."
    elif active_overrides:
        stage_recommendation = "hold_for_override_clearance"
        plain_label = "Hold for override clearance"
        detail = "Rollout telemetry indicates active overrides still need clearance before rollout."
    else:
        stage_recommendation = "hold_for_operator_attention"
        plain_label = "Hold for operator attention"
        detail = "Rollout telemetry indicates rollout is not yet safe and still needs operator attention."
    return {
        "schema_version": "privacy_staged_rollout_telemetry.v1",
        "telemetry_kind": "staged_rollout_telemetry",
        "surface_class": "authoritative_diagnostic",
        "source_surface": "final_review_bundle",
        "authoritative_model": str(bundle.get("authoritative_model", "privacy_claims") or "privacy_claims"),
        "rollout_stage_recommendation": stage_recommendation,
        "plain_label": plain_label,
        "detail": detail,
        "rollout_safe_now": effective_safe_now,
        "migration_cleanup_complete": cleanup_complete,
        "compatibility_debt_present": not cleanup_complete,
        "kill_switch_posture_available": True,
        "kill_switch_posture_active": bool(active_overrides),
        "active_overrides_present": bool(active_overrides),
        "active_compatibility_allowances": compatibility_allowances_active,
        "canary_safe_now": bool(stage_recommendation in {"private_default_canary", "private_default_canary_with_debt"}),
        "operator_attention_required": bool(stage_recommendation in {"hold_for_override_clearance", "hold_for_operator_attention"}),
        "release_readiness_verdict": str(verdict.get("state", "") or "").strip(),
        "blocker_categories": blocker_categories,
    }


def release_claims_matrix_snapshot(
    *,
    final_review_bundle: dict[str, Any] | None = None,
    staged_rollout_telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = dict(final_review_bundle or {})
    telemetry = dict(staged_rollout_telemetry or {})
    review_export = dict(bundle.get("review_export") or {})
    review_summary = dict(review_export.get("review_summary") or {})
    dm_claim = dict(review_summary.get("dm_strong_claim") or {})
    gate_claim = dict(review_summary.get("gate_transitional_claim") or {})
    rollout_safe = dict(review_summary.get("private_default_rollout_safe") or {})
    blocker_categories = [
        str(item or "").strip()
        for item in list(
            telemetry.get("blocker_categories")
            or bundle.get("blocker_categories")
            or []
        )
        if str(item or "").strip()
    ]
    compatibility_cleanup_complete = bool(
        telemetry.get("migration_cleanup_complete", False)
    )
    compatibility_debt_present = bool(
        telemetry.get("compatibility_debt_present", not compatibility_cleanup_complete)
    )
    operator_override_free = not bool(
        telemetry.get("active_overrides_present", False)
        or telemetry.get("kill_switch_posture_active", False)
    )
    return {
        "schema_version": "privacy_release_claims_matrix.v1",
        "matrix_kind": "release_claims_matrix",
        "surface_class": "authoritative_diagnostic",
        "source_surface": "final_review_bundle",
        "authoritative_model": str(
            bundle.get("authoritative_model", "privacy_claims") or "privacy_claims"
        ),
        "claim_truth_metadata": {
            "source_bundle": "final_review_bundle",
            "derived_telemetry": "staged_rollout_telemetry",
            "deterministic": True,
            "identifier_free": True,
            "compatibility_debt_reflected": compatibility_debt_present,
        },
        "blocker_categories": blocker_categories,
        "rows": {
            "dm_strong_claim_now": {
                "allowed": bool(dm_claim.get("allowed", False)),
                "state": str(dm_claim.get("state", "") or "").strip(),
                "plain_label": str(dm_claim.get("plain_label", "") or "").strip(),
                "detail": str(dm_claim.get("detail", "") or "").strip(),
            },
            "gate_transitional_claim_now": {
                "allowed": bool(gate_claim.get("allowed", False)),
                "state": str(gate_claim.get("state", "") or "").strip(),
                "plain_label": str(gate_claim.get("plain_label", "") or "").strip(),
                "detail": str(gate_claim.get("detail", "") or "").strip(),
            },
            "private_default_rollout_claim_now": {
                "allowed": bool(rollout_safe.get("allowed", False)),
                "state": str(rollout_safe.get("state", "") or "").strip(),
                "plain_label": str(rollout_safe.get("plain_label", "") or "").strip(),
                "detail": str(rollout_safe.get("detail", "") or "").strip(),
            },
            "compatibility_cleanup_complete": {
                "allowed": compatibility_cleanup_complete,
                "state": (
                    "compatibility_cleanup_complete"
                    if compatibility_cleanup_complete
                    else "compatibility_cleanup_incomplete"
                ),
                "plain_label": (
                    "Compatibility cleanup complete"
                    if compatibility_cleanup_complete
                    else "Compatibility cleanup incomplete"
                ),
                "detail": (
                    "Compatibility cleanup is complete."
                    if compatibility_cleanup_complete
                    else "Compatibility cleanup or migration debt still remains."
                ),
            },
            "operator_override_free": {
                "allowed": operator_override_free,
                "state": (
                    "operator_override_free"
                    if operator_override_free
                    else "operator_override_active"
                ),
                "plain_label": (
                    "Operator override free"
                    if operator_override_free
                    else "Operator override active"
                ),
                "detail": (
                    "No active override or kill-switch posture is currently affecting rollout."
                    if operator_override_free
                    else "An active override or kill-switch posture is still affecting rollout."
                ),
            },
        },
    }


def release_checklist_snapshot(
    *,
    release_claims_matrix: dict[str, Any] | None = None,
    staged_rollout_telemetry: dict[str, Any] | None = None,
    final_review_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    matrix = dict(release_claims_matrix or {})
    telemetry = dict(staged_rollout_telemetry or {})
    bundle = dict(final_review_bundle or {})
    rows = dict(matrix.get("rows") or {})
    blocker_categories = [
        str(item or "").strip()
        for item in list(
            matrix.get("blocker_categories")
            or telemetry.get("blocker_categories")
            or bundle.get("blocker_categories")
            or []
        )
        if str(item or "").strip()
    ]
    compatibility_provenance = dict(bundle.get("compatibility_shim_provenance") or {})
    strong_provenance = dict(compatibility_provenance.get("strong_claims") or {})
    release_provenance = dict(compatibility_provenance.get("release_gate") or {})

    items = {
        "dm_strong_claim_truth_confirmed": {
            "completed": bool(dict(rows.get("dm_strong_claim_now") or {}).get("allowed", False)),
            "plain_label": "DM strong claim truth confirmed",
            "detail": str(dict(rows.get("dm_strong_claim_now") or {}).get("detail", "") or "").strip(),
        },
        "gate_transitional_claim_truth_confirmed": {
            "completed": bool(dict(rows.get("gate_transitional_claim_now") or {}).get("allowed", False)),
            "plain_label": "Gate transitional claim truth confirmed",
            "detail": str(dict(rows.get("gate_transitional_claim_now") or {}).get("detail", "") or "").strip(),
        },
        "private_default_rollout_claim_truth_confirmed": {
            "completed": bool(dict(rows.get("private_default_rollout_claim_now") or {}).get("allowed", False)),
            "plain_label": "Private-default rollout claim truth confirmed",
            "detail": str(dict(rows.get("private_default_rollout_claim_now") or {}).get("detail", "") or "").strip(),
        },
        "compatibility_cleanup_complete": {
            "completed": bool(dict(rows.get("compatibility_cleanup_complete") or {}).get("allowed", False)),
            "plain_label": "Compatibility cleanup complete",
            "detail": str(dict(rows.get("compatibility_cleanup_complete") or {}).get("detail", "") or "").strip(),
        },
        "no_active_override_posture": {
            "completed": bool(dict(rows.get("operator_override_free") or {}).get("allowed", False)),
            "plain_label": "No active override posture",
            "detail": str(dict(rows.get("operator_override_free") or {}).get("detail", "") or "").strip(),
        },
        "operator_review_package_complete": {
            "completed": bool(
                bundle.get("review_completeness", {}).get("deterministic", False)
                and bundle.get("review_completeness", {}).get("identifier_free", False)
                and bundle.get("review_completeness", {}).get("sourced_from_authoritative_model", False)
                and strong_provenance.get("surface_class") == "compatibility_shim"
                and release_provenance.get("surface_class") == "compatibility_shim"
            ),
            "plain_label": "Operator review package complete",
            "detail": "Deterministic identifier-free review packaging is available with compatibility-shim provenance.",
        },
    }
    completed_count = sum(1 for item in items.values() if bool(item.get("completed", False)))
    pending_count = len(items) - completed_count
    if pending_count == 0:
        checklist_status = "completed"
        plain_label = "Release checklist complete"
        detail = "All rollout-readiness checklist items are complete."
    elif completed_count > 0:
        checklist_status = "pending"
        plain_label = "Release checklist pending"
        detail = "Some rollout-readiness checklist items still remain."
    else:
        checklist_status = "blocked"
        plain_label = "Release checklist blocked"
        detail = "Release checklist items are not yet complete."
    return {
        "schema_version": "privacy_release_checklist.v1",
        "checklist_kind": "release_checklist",
        "surface_class": "authoritative_diagnostic",
        "source_surface": "release_claims_matrix",
        "authoritative_model": str(matrix.get("authoritative_model", "privacy_claims") or "privacy_claims"),
        "checklist_status": checklist_status,
        "completed_count": completed_count,
        "pending_count": pending_count,
        "blocker_categories": blocker_categories,
        "source_surfaces": [
            "release_claims_matrix",
            "staged_rollout_telemetry",
            "final_review_bundle",
        ],
        "items": items,
    }


def explicit_review_export_snapshot(
    *,
    final_review_bundle: dict[str, Any] | None = None,
    staged_rollout_telemetry: dict[str, Any] | None = None,
    release_claims_matrix: dict[str, Any] | None = None,
    release_checklist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = dict(final_review_bundle or {})
    telemetry = dict(staged_rollout_telemetry or {})
    claims_matrix = dict(release_claims_matrix or {})
    checklist = dict(release_checklist or {})
    return {
        "schema_version": "privacy_explicit_review_export.v1",
        "export_kind": "explicit_review_export",
        "surface_class": "authoritative_export_bundle",
        "source_surface": "final_review_bundle",
        "authoritative_model": str(bundle.get("authoritative_model", "privacy_claims") or "privacy_claims"),
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
        "final_review_bundle": bundle,
        "staged_rollout_telemetry": telemetry,
        "release_claims_matrix": claims_matrix,
        "release_checklist": checklist,
    }


def review_manifest_snapshot(
    *,
    explicit_review_export: dict[str, Any] | None = None,
) -> dict[str, Any]:
    export = dict(explicit_review_export or {})
    bundle = dict(export.get("final_review_bundle") or {})
    telemetry = dict(export.get("staged_rollout_telemetry") or {})
    claims_matrix = dict(export.get("release_claims_matrix") or {})
    checklist = dict(export.get("release_checklist") or {})
    review_export = dict(bundle.get("review_export") or {})
    rows = dict(claims_matrix.get("rows") or {})
    checklist_items = dict(checklist.get("items") or {})
    export_metadata = dict(export.get("export_metadata") or {})
    blocker_categories = [
        str(item or "").strip()
        for item in list(
            claims_matrix.get("blocker_categories")
            or checklist.get("blocker_categories")
            or bundle.get("blocker_categories")
            or []
        )
        if str(item or "").strip()
    ]

    def _unique(items: list[str]) -> list[str]:
        result: list[str] = []
        for item in items:
            normalized = str(item or "").strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    claim_summary = {
        key: {
            "allowed": bool(dict(rows.get(key) or {}).get("allowed", False)),
            "state": str(dict(rows.get(key) or {}).get("state", "") or "").strip(),
            "plain_label": str(dict(rows.get(key) or {}).get("plain_label", "") or "").strip(),
            "detail": str(dict(rows.get(key) or {}).get("detail", "") or "").strip(),
        }
        for key in (
            "dm_strong_claim_now",
            "gate_transitional_claim_now",
            "private_default_rollout_claim_now",
            "compatibility_cleanup_complete",
            "operator_override_free",
        )
    }
    checklist_summary = {
        "checklist_status": str(checklist.get("checklist_status", "") or "").strip(),
        "completed_count": int(checklist.get("completed_count", 0) or 0),
        "pending_count": int(checklist.get("pending_count", 0) or 0),
        "completed_items": _unique(
            [key for key, value in checklist_items.items() if bool(dict(value or {}).get("completed", False))]
        ),
        "pending_items": _unique(
            [key for key, value in checklist_items.items() if not bool(dict(value or {}).get("completed", False))]
        ),
    }
    evidence_map = {
        "dm_strong_claim_now": {
            "source_surfaces": [
                "release_claims_matrix",
                "final_review_bundle",
                "review_export",
                "privacy_claims",
            ]
        },
        "gate_transitional_claim_now": {
            "source_surfaces": [
                "release_claims_matrix",
                "final_review_bundle",
                "review_export",
                "privacy_claims",
            ]
        },
        "private_default_rollout_claim_now": {
            "source_surfaces": [
                "release_claims_matrix",
                "staged_rollout_telemetry",
                "final_review_bundle",
                "review_export",
                "rollout_readiness",
                "rollout_controls",
                "rollout_health",
            ]
        },
        "compatibility_cleanup_complete": {
            "source_surfaces": [
                "release_claims_matrix",
                "staged_rollout_telemetry",
                "release_checklist",
            ]
        },
        "operator_override_free": {
            "source_surfaces": [
                "release_claims_matrix",
                "staged_rollout_telemetry",
                "release_checklist",
                "rollout_controls",
            ]
        },
        "dm_strong_claim_truth_confirmed": {
            "source_surfaces": ["release_checklist", "release_claims_matrix"]
        },
        "gate_transitional_claim_truth_confirmed": {
            "source_surfaces": ["release_checklist", "release_claims_matrix"]
        },
        "private_default_rollout_claim_truth_confirmed": {
            "source_surfaces": [
                "release_checklist",
                "release_claims_matrix",
                "staged_rollout_telemetry",
            ]
        },
        "compatibility_cleanup_complete_checklist": {
            "source_surfaces": [
                "release_checklist",
                "release_claims_matrix",
                "staged_rollout_telemetry",
            ]
        },
        "no_active_override_posture": {
            "source_surfaces": [
                "release_checklist",
                "release_claims_matrix",
                "staged_rollout_telemetry",
                "rollout_controls",
            ]
        },
        "operator_review_package_complete": {
            "source_surfaces": [
                "release_checklist",
                "final_review_bundle",
                "review_export",
                "claim_surface_sources",
            ]
        },
    }
    return {
        "schema_version": "privacy_review_manifest.v1",
        "manifest_kind": "review_manifest",
        "surface_class": "authoritative_review_manifest",
        "source_surface": "explicit_review_export",
        "authoritative_model": str(export.get("authoritative_model", "privacy_claims") or "privacy_claims"),
        "manifest_metadata": {
            "deterministic": bool(export_metadata.get("deterministic", True)),
            "identifier_free": bool(export_metadata.get("identifier_free", True)),
            "source_surfaces": _unique(
                list(export_metadata.get("source_surfaces") or [])
                + ["explicit_review_export", "review_export"]
            ),
        },
        "claim_summary_rows": claim_summary,
        "checklist_summary": checklist_summary,
        "blocker_categories": blocker_categories,
        "evidence_surfaces": _unique(
            list(export_metadata.get("source_surfaces") or [])
            + ["explicit_review_export", "review_export"]
        ),
        "evidence_map": {
            key: {
                "source_surfaces": _unique(
                    list(dict(value or {}).get("source_surfaces") or [])
                )
            }
            for key, value in evidence_map.items()
        },
    }


def review_consistency_snapshot(
    *,
    explicit_review_export: dict[str, Any] | None = None,
    review_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    export = dict(explicit_review_export or {})
    manifest = dict(review_manifest or {})
    export_metadata = dict(export.get("export_metadata") or {})
    manifest_metadata = dict(manifest.get("manifest_metadata") or {})
    release_claims_matrix = dict(export.get("release_claims_matrix") or {})
    release_checklist = dict(export.get("release_checklist") or {})
    manifest_claim_rows = dict(manifest.get("claim_summary_rows") or {})
    manifest_checklist_summary = dict(manifest.get("checklist_summary") or {})
    evidence_map = dict(manifest.get("evidence_map") or {})
    evidence_surfaces = [
        str(item or "").strip()
        for item in list(manifest.get("evidence_surfaces") or [])
        if str(item or "").strip()
    ]
    export_blocker_categories = [
        str(item or "").strip()
        for item in list(
            release_claims_matrix.get("blocker_categories")
            or []
        )
        if str(item or "").strip()
    ]
    manifest_blocker_categories = [
        str(item or "").strip()
        for item in list(
            manifest.get("blocker_categories")
            or []
        )
        if str(item or "").strip()
    ]

    def _unique(items: list[str]) -> list[str]:
        result: list[str] = []
        for item in items:
            normalized = str(item or "").strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    missing_surface_classes: list[str] = []
    conflicting_surface_classes: list[str] = []
    if not export:
        missing_surface_classes.append("explicit_review_export")
    elif str(export.get("surface_class", "") or "").strip() != "authoritative_export_bundle":
        conflicting_surface_classes.append("explicit_review_export")
    if not manifest:
        missing_surface_classes.append("review_manifest")
    elif str(manifest.get("surface_class", "") or "").strip() != "authoritative_review_manifest":
        conflicting_surface_classes.append("review_manifest")

    export_blocker_set = set(_unique(export_blocker_categories))
    manifest_blocker_set = set(_unique(manifest_blocker_categories))
    blocker_category_mismatches = {
        "export_only": sorted(export_blocker_set - manifest_blocker_set),
        "manifest_only": sorted(manifest_blocker_set - export_blocker_set),
    }

    claim_row_mismatches: list[str] = []
    claim_rows_missing_evidence: list[str] = []
    for row_name, row_value in dict(release_claims_matrix.get("rows") or {}).items():
        export_row = dict(row_value or {})
        manifest_row = dict(manifest_claim_rows.get(row_name) or {})
        if (
            bool(manifest_row.get("allowed", False)) != bool(export_row.get("allowed", False))
            or str(manifest_row.get("state", "") or "").strip()
            != str(export_row.get("state", "") or "").strip()
        ):
            claim_row_mismatches.append(str(row_name))
        evidence_sources = list(dict(evidence_map.get(row_name) or {}).get("source_surfaces") or [])
        if not evidence_sources:
            claim_rows_missing_evidence.append(str(row_name))

    checklist_item_mismatches: list[str] = []
    checklist_items_missing_evidence: list[str] = []
    completed_items = {
        str(item or "").strip()
        for item in list(manifest_checklist_summary.get("completed_items") or [])
        if str(item or "").strip()
    }
    pending_items = {
        str(item or "").strip()
        for item in list(manifest_checklist_summary.get("pending_items") or [])
        if str(item or "").strip()
    }
    checklist_items = dict(release_checklist.get("items") or {})
    expected_completed_count = sum(
        1 for value in checklist_items.values() if bool(dict(value or {}).get("completed", False))
    )
    expected_pending_count = len(checklist_items) - expected_completed_count
    if int(manifest_checklist_summary.get("completed_count", 0) or 0) != expected_completed_count:
        checklist_item_mismatches.append("completed_count")
    if int(manifest_checklist_summary.get("pending_count", 0) or 0) != expected_pending_count:
        checklist_item_mismatches.append("pending_count")
    for item_name, item_value in checklist_items.items():
        normalized_item = str(item_name or "").strip()
        completed = bool(dict(item_value or {}).get("completed", False))
        if completed and normalized_item not in completed_items:
            checklist_item_mismatches.append(normalized_item)
        if not completed and normalized_item not in pending_items:
            checklist_item_mismatches.append(normalized_item)
        evidence_key = normalized_item
        if evidence_key not in evidence_map and f"{normalized_item}_checklist" in evidence_map:
            evidence_key = f"{normalized_item}_checklist"
        evidence_sources = list(dict(evidence_map.get(evidence_key) or {}).get("source_surfaces") or [])
        if not evidence_sources:
            checklist_items_missing_evidence.append(normalized_item)

    blocker_provenance_requirements = {
        "attestation": ["review_export"],
        "local_custody": ["review_export"],
        "compatibility": ["release_claims_matrix", "staged_rollout_telemetry"],
        "compatibility_debt": ["release_claims_matrix", "staged_rollout_telemetry"],
        "operator_override": ["release_claims_matrix", "staged_rollout_telemetry"],
        "gate_posture": ["review_export"],
        "transport_posture": ["review_export"],
        "operator_attention": ["final_review_bundle", "review_export"],
    }
    blocker_categories_missing_provenance: list[str] = []
    evidence_surface_set = set(evidence_surfaces)
    for category in manifest_blocker_categories:
        required_surfaces = blocker_provenance_requirements.get(category, ["review_export"])
        if not set(required_surfaces).issubset(evidence_surface_set):
            blocker_categories_missing_provenance.append(category)

    deterministic = bool(export_metadata.get("deterministic", True)) and bool(
        manifest_metadata.get("deterministic", True)
    )
    identifier_free = bool(export_metadata.get("identifier_free", True)) and bool(
        manifest_metadata.get("identifier_free", True)
    )
    structural_alignment_ok = not (
        missing_surface_classes
        or conflicting_surface_classes
        or claim_row_mismatches
        or checklist_item_mismatches
        or blocker_category_mismatches["export_only"]
        or blocker_category_mismatches["manifest_only"]
    )
    aligned = not (
        not structural_alignment_ok
    )
    return {
        "schema_version": "privacy_review_consistency.v1",
        "consistency_kind": "review_surface_consistency",
        "surface_class": "authoritative_review_handoff",
        "source_surfaces": ["explicit_review_export", "review_manifest"],
        "authoritative_model": str(export.get("authoritative_model") or manifest.get("authoritative_model") or "privacy_claims"),
        "consistency_flags": {
            "deterministic": deterministic,
            "identifier_free": identifier_free,
        },
        "alignment_verdict": {
            "aligned": aligned,
            "state": "aligned" if aligned else "not_aligned",
            "detail": (
                "Review export and manifest are structurally aligned."
                if aligned
                else "Review export and manifest still have consistency or provenance gaps."
            ),
        },
        "missing_surface_classes": _unique(missing_surface_classes),
        "conflicting_surface_classes": _unique(conflicting_surface_classes),
        "blocker_category_mismatches": blocker_category_mismatches,
        "handoff_summary": {
            "export_and_manifest_aligned_now": {
                "allowed": structural_alignment_ok,
                "state": (
                    "aligned"
                    if structural_alignment_ok
                    else "mismatch_present"
                ),
                "detail": (
                    "Export and manifest claim/checklist summaries are aligned."
                    if structural_alignment_ok
                    else "Export and manifest still contain structural or summary mismatches."
                ),
            },
            "claim_rows_fully_backed_by_evidence_now": {
                "allowed": not bool(claim_rows_missing_evidence),
                "state": "fully_backed" if not claim_rows_missing_evidence else "missing_claim_evidence",
                "detail": (
                    "Every manifest claim row is backed by at least one evidence surface."
                    if not claim_rows_missing_evidence
                    else f"Missing evidence coverage for claim rows: {', '.join(_unique(claim_rows_missing_evidence))}"
                ),
            },
            "checklist_rows_fully_backed_by_evidence_now": {
                "allowed": not bool(checklist_items_missing_evidence),
                "state": "fully_backed" if not checklist_items_missing_evidence else "missing_checklist_evidence",
                "detail": (
                    "Every manifest checklist row is backed by at least one evidence surface."
                    if not checklist_items_missing_evidence
                    else f"Missing evidence coverage for checklist rows: {', '.join(_unique(checklist_items_missing_evidence))}"
                ),
            },
            "blocker_categories_fully_covered_by_provenance": {
                "allowed": not bool(blocker_categories_missing_provenance),
                "state": (
                    "fully_covered" if not blocker_categories_missing_provenance else "missing_blocker_provenance"
                ),
                "detail": (
                    "Every blocker category has provenance coverage in the manifest."
                    if not blocker_categories_missing_provenance
                    else f"Missing provenance coverage for blocker categories: {', '.join(_unique(blocker_categories_missing_provenance))}"
                ),
            },
        },
    }


def strong_claims_compat_shim(
    snapshot: dict[str, Any] | None,
    *,
    privacy_claims: dict[str, Any] | None = None,
    privacy_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shim = dict(snapshot or {})
    claims = dict((privacy_claims or {}).get("claims") or {})
    dm_claim = dict(claims.get("dm_strong") or {})
    status_chip = dict(privacy_status or {})
    status_state = str(status_chip.get("state", "") or "").strip()
    shim["compatibility_shim"] = True
    shim["surface_class"] = "compatibility_shim"
    shim["source_model"] = "privacy_claims"
    shim["source_surface"] = "privacy_claims"
    shim["authoritative_claim"] = "dm_strong"
    shim["authoritative_claim_allowed"] = bool(dm_claim.get("allowed", False))
    shim["authoritative_claim_state"] = str(dm_claim.get("state", "") or "").strip()
    shim["authoritative_claim_label"] = str(dm_claim.get("plain_label", "") or "").strip()
    shim["authoritative_claim_detail"] = str(dm_claim.get("detail", "") or "").strip()
    shim["coarse_surface_state"] = status_state
    shim["coarse_surface_consistent"] = not (
        status_state == "dm_strong_ready" and not bool(shim.get("allowed", False))
    )
    return shim


def release_gate_compat_shim(
    snapshot: dict[str, Any] | None,
    *,
    privacy_claims: dict[str, Any] | None = None,
    rollout_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    legacy = dict(snapshot or {})
    rollout = dict(rollout_readiness or {})
    authoritative_claims = dict((privacy_claims or {}).get("claims") or {})
    authoritative_dm = dict(authoritative_claims.get("dm_strong") or {})
    authoritative_gate = dict(authoritative_claims.get("gate_transitional") or {})
    legacy_ready = bool(legacy.get("ready", False))
    legacy_blockers = [
        str(blocker or "").strip()
        for blocker in list(legacy.get("blocking_reasons") or [])
        if str(blocker or "").strip()
    ]
    rollout_allowed = bool(rollout.get("allowed", legacy_ready))
    rollout_state = str(rollout.get("state", "") or "").strip()
    rollout_blockers = [
        str(blocker or "").strip()
        for blocker in list(rollout.get("blockers") or legacy_blockers)
        if str(blocker or "").strip()
    ]
    shim = dict(legacy)
    shim["ready"] = rollout_allowed
    shim["detail"] = "release gate satisfied" if rollout_allowed else "release gate pending"
    shim["blocking_reasons"] = [] if rollout_allowed else rollout_blockers
    shim["next_action"] = shim["blocking_reasons"][0] if shim["blocking_reasons"] else ""
    shim["compatibility_shim"] = True
    shim["surface_class"] = "compatibility_shim"
    shim["source_model"] = "rollout_readiness"
    shim["source_surface"] = "rollout_readiness"
    shim["legacy_policy_ready"] = legacy_ready
    shim["legacy_policy_blocking_reasons"] = legacy_blockers
    shim["authoritative_rollout_allowed"] = rollout_allowed
    shim["authoritative_rollout_state"] = rollout_state
    shim["authoritative_rollout_detail"] = str(rollout.get("detail", "") or "").strip()
    shim["authoritative_dm_claim_state"] = str(authoritative_dm.get("state", "") or "").strip()
    shim["authoritative_gate_claim_state"] = str(authoritative_gate.get("state", "") or "").strip()
    shim["authoritative_rollout_consistent"] = bool(
        shim["ready"] == shim["authoritative_rollout_allowed"]
    )
    return shim


def _rollout_entry(
    *,
    allowed: bool,
    state: str,
    plain_label: str,
    blockers: list[str],
    detail: str,
) -> dict[str, Any]:
    return {
        "allowed": bool(allowed),
        "state": str(state or ""),
        "plain_label": str(plain_label or ""),
        "blockers": [str(blocker or "") for blocker in blockers if str(blocker or "").strip()],
        "detail": str(detail or ""),
    }


def _rollout_compatibility_blockers(
    compatibility_readiness: dict[str, Any],
    gate_privilege_access: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if bool(compatibility_readiness.get("stored_legacy_lookup_contacts_present", False)):
        blockers.append("compatibility_stored_legacy_lookup_contacts_present")
    if bool(compatibility_readiness.get("legacy_lookup_runtime_active", False)):
        blockers.append("compatibility_legacy_lookup_runtime_active")
    if bool(compatibility_readiness.get("legacy_mailbox_get_runtime_active", False)):
        blockers.append("compatibility_legacy_mailbox_get_runtime_active")
    if bool(compatibility_readiness.get("legacy_mailbox_get_enabled", False)):
        blockers.append("compatibility_legacy_mailbox_get_enabled")
    if compatibility_readiness and not bool(compatibility_readiness.get("local_contact_upgrade_ok", True)):
        blockers.append("compatibility_local_contact_upgrade_incomplete")
    if str(gate_privilege_access.get("privileged_gate_event_scope_class", "") or "") != "explicit_gate_audit":
        blockers.append("gate_privileged_event_scope_not_explicit_audit")
    if str(gate_privilege_access.get("repair_detail_scope_class", "") or "") != "local_operator_diagnostic":
        blockers.append("gate_repair_scope_not_local_operator_diagnostic")
    return blockers


def _rollout_compatibility_debt_flags(compatibility_debt: dict[str, Any]) -> list[str]:
    debt_flags: list[str] = []
    legacy_lookup = dict(compatibility_debt.get("legacy_lookup_reliance") or {})
    legacy_mailbox = dict(compatibility_debt.get("legacy_mailbox_get_reliance") or {})
    if int(legacy_lookup.get("blocked_count", 0) or 0) > 0 or int(legacy_lookup.get("last_seen_at", 0) or 0) > 0:
        debt_flags.append("compatibility_debt_legacy_lookup")
    if int(legacy_mailbox.get("blocked_count", 0) or 0) > 0 or int(legacy_mailbox.get("last_seen_at", 0) or 0) > 0:
        debt_flags.append("compatibility_debt_legacy_mailbox_get")
    return debt_flags


def _rollout_policy_override_blockers(strong_claims: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not bool(strong_claims.get("clearnet_fallback_blocked", True)):
        blockers.append("operator_override_clearnet_fallback_not_blocked")
    compatibility = dict(strong_claims.get("compatibility") or {})
    for key, value in compatibility.items():
        if key == "sunset":
            continue
        if bool(value):
            blockers.append(f"operator_override_{key}")
    return blockers


def rollout_readiness_snapshot(
    *,
    privacy_claims: dict[str, Any] | None = None,
    transport_tier: str,
    local_custody: dict[str, Any] | None = None,
    privacy_core: dict[str, Any] | None = None,
    compatibility_debt: dict[str, Any] | None = None,
    compatibility_readiness: dict[str, Any] | None = None,
    gate_privilege_access: dict[str, Any] | None = None,
    strong_claims: dict[str, Any] | None = None,
    release_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    claims_snapshot = dict(privacy_claims or {})
    claims = dict(claims_snapshot.get("claims") or {})
    dm_claim = dict(claims.get("dm_strong") or {})
    gate_claim = dict(claims.get("gate_transitional") or {})
    custody = dict(local_custody or {})
    attestation = dict(privacy_core or {})
    debt = dict(compatibility_debt or {})
    readiness = dict(compatibility_readiness or {})
    gate_access = dict(gate_privilege_access or {})
    strong = dict(strong_claims or {})
    release = dict(release_gate or {})
    release_profile = profile_readiness_snapshot()
    profile_blockers = [
        str(item or "").strip()
        for item in list(release_profile.get("blockers") or [])
        if str(item or "").strip()
    ]

    if profile_blockers:
        return {
            **_rollout_entry(
                allowed=False,
                state="blocked_by_release_profile",
                plain_label="Blocked by release profile",
                blockers=profile_blockers,
                detail=str(release_profile.get("detail", "") or "")
                or "Release profile requirements are not satisfied.",
            ),
            "surface_class": "authoritative_diagnostic",
            "source_model": "privacy_claims",
            "release_profile": release_profile,
        }

    attestation_state = str(attestation.get("attestation_state", "") or "").strip()
    if attestation_state != "attested_current":
        blockers = ["privacy_core_attestation_not_current"]
        return {
            **_rollout_entry(
            allowed=False,
            state="blocked_by_attestation",
            plain_label="Blocked by privacy-core attestation",
            blockers=blockers,
            detail="Privacy-core attestation is not current enough for private-default rollout.",
            ),
            "surface_class": "authoritative_diagnostic",
            "source_model": "privacy_claims",
            "release_profile": release_profile,
        }

    if not bool(custody.get("protected_at_rest", False)):
        blockers = ["local_custody_not_protected_at_rest"]
        return {
            **_rollout_entry(
            allowed=False,
            state="blocked_by_local_custody",
            plain_label="Blocked by local custody",
            blockers=blockers,
            detail="Local custody is not protected at rest enough for private-default rollout.",
            ),
            "surface_class": "authoritative_diagnostic",
            "source_model": "privacy_claims",
            "release_profile": release_profile,
        }

    override_blockers = _rollout_policy_override_blockers(strong)
    if override_blockers:
        return {
            **_rollout_entry(
            allowed=False,
            state="blocked_by_operator_override",
            plain_label="Blocked by active operator override",
            blockers=override_blockers,
            detail="One or more active policy overrides still block private-default rollout.",
            ),
            "surface_class": "authoritative_diagnostic",
            "source_model": "privacy_claims",
            "release_profile": release_profile,
        }

    compatibility_blockers = _rollout_compatibility_blockers(readiness, gate_access)
    if compatibility_blockers:
        return {
            **_rollout_entry(
            allowed=False,
            state="blocked_by_compatibility",
            plain_label="Blocked by compatibility posture",
            blockers=compatibility_blockers,
            detail="Compatibility readiness or privilege posture still blocks private-default rollout.",
            ),
            "surface_class": "authoritative_diagnostic",
            "source_model": "privacy_claims",
            "release_profile": release_profile,
        }

    debt_flags = _rollout_compatibility_debt_flags(debt)
    if debt_flags:
        return {
            **_rollout_entry(
            allowed=True,
            state="ready_with_compatibility_debt",
            plain_label="Ready with compatibility debt",
            blockers=debt_flags,
            detail="Private-default rollout is available, but recent compatibility debt still needs cleanup.",
            ),
            "surface_class": "authoritative_diagnostic",
            "source_model": "privacy_claims",
            "release_profile": release_profile,
        }

    dm_ready = bool(dm_claim.get("allowed", False))
    gate_ready = bool(gate_claim.get("allowed", False))
    shim_ready = bool(strong.get("allowed", False)) and bool(release.get("ready", False))
    if dm_ready and gate_ready and shim_ready:
        return {
            **_rollout_entry(
            allowed=True,
            state="ready_for_private_default",
            plain_label="Ready for private default",
            blockers=[],
            detail="Private-default rollout checks are satisfied.",
            ),
            "surface_class": "authoritative_diagnostic",
            "source_model": "privacy_claims",
            "release_profile": release_profile,
        }

    blockers: list[str] = []
    if not dm_ready:
        blockers.extend(list(dm_claim.get("blockers") or []))
    if not gate_ready:
        blockers.extend(
            blocker
            for blocker in list(gate_claim.get("blockers") or [])
            if blocker not in blockers
        )
    for blocker in list(strong.get("reasons") or []):
        normalized = str(blocker or "").strip()
        if normalized and normalized not in blockers:
            blockers.append(normalized)
    for blocker in list(release.get("blocking_reasons") or []):
        normalized = str(blocker or "").strip()
        if normalized and normalized not in blockers:
            blockers.append(normalized)
    return {
        **_rollout_entry(
            allowed=False,
            state="requires_operator_attention",
            plain_label="Requires operator attention",
            blockers=blockers,
            detail="Private-default rollout is not yet ready under the current transport or assurance posture.",
        ),
        "surface_class": "authoritative_diagnostic",
        "source_model": "privacy_claims",
        "release_profile": release_profile,
    }


def rollout_controls_snapshot(
    *,
    rollout_readiness: dict[str, Any] | None = None,
    privacy_core: dict[str, Any] | None = None,
    strong_claims: dict[str, Any] | None = None,
    transport_tier: str,
) -> dict[str, Any]:
    readiness = dict(rollout_readiness or {})
    attestation = dict(privacy_core or {})
    strong = dict(strong_claims or {})
    compatibility = dict(strong.get("compatibility") or {})
    active_overrides: list[str] = []
    release_profile = profile_readiness_snapshot()
    profile_blockers = [
        str(item or "").strip()
        for item in list(release_profile.get("blockers") or [])
        if str(item or "").strip()
    ]
    if bool(attestation.get("override_active", False)):
        active_overrides.append("attestation_override_active")
    if not bool(strong.get("compat_overrides_clear", True)):
        active_overrides.append("compatibility_override_active")
    if not bool(strong.get("clearnet_fallback_blocked", True)):
        active_overrides.append("clearnet_fallback_not_blocked")
    legacy_enabled = sorted(
        key
        for key, value in compatibility.items()
        if key != "sunset" and bool(value)
    )
    if legacy_enabled:
        active_overrides.append("legacy_compatibility_paths_enabled")
    active_overrides.extend(
        blocker for blocker in profile_blockers if blocker not in active_overrides
    )
    enforce_safe = str(readiness.get("state", "") or "") == "ready_for_private_default"
    if enforce_safe and not active_overrides:
        state = "private_default_safe"
        plain_label = "Private default safe to enforce"
        detail = "Rollout controls do not show active override or compatibility enforcement blockers."
    elif active_overrides:
        state = "override_active"
        plain_label = "Active rollout override"
        detail = "One or more rollout controls still rely on active overrides or legacy compatibility."
    else:
        state = "requires_operator_attention"
        plain_label = "Rollout controls need attention"
        detail = "Rollout controls are not yet in a safe enforcement posture."
    return {
        "state": state,
        "plain_label": plain_label,
        "detail": detail,
        "surface_class": "authoritative_diagnostic",
        "source_model": "privacy_claims",
        "transport_tier": _normalize_tier(transport_tier),
        "private_default_enforce_safe": bool(enforce_safe and not active_overrides),
        "attestation_override_active": bool(attestation.get("override_active", False)),
        "compatibility_override_active": not bool(strong.get("compat_overrides_clear", True)),
        "legacy_compatibility_enabled": bool(legacy_enabled),
        "legacy_compatibility_paths_enabled": legacy_enabled,
        "clearnet_fallback_blocked": bool(strong.get("clearnet_fallback_blocked", True)),
        "active_overrides": active_overrides,
        "release_profile": release_profile,
    }


def rollout_health_snapshot(
    *,
    rollout_readiness: dict[str, Any] | None = None,
    compatibility_debt: dict[str, Any] | None = None,
    compatibility_readiness: dict[str, Any] | None = None,
    lookup_handle_rotation: dict[str, Any] | None = None,
    gate_repair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    readiness = dict(rollout_readiness or {})
    debt = dict(compatibility_debt or {})
    readiness_inputs = dict(compatibility_readiness or {})
    lookup_rotation = dict(lookup_handle_rotation or {})
    gate_repair_state = str(dict(gate_repair or {}).get("repair_state", "") or "").strip()
    debt_flags = _rollout_compatibility_debt_flags(debt)
    if bool(readiness_inputs.get("stored_legacy_lookup_contacts_present", False)):
        debt_flags.append("stored_legacy_lookup_contacts_present")
    if bool(readiness_inputs.get("legacy_lookup_runtime_active", False)):
        debt_flags.append("legacy_lookup_runtime_active")
    if bool(readiness_inputs.get("legacy_mailbox_get_runtime_active", False)):
        debt_flags.append("legacy_mailbox_get_runtime_active")
    if bool(readiness_inputs.get("legacy_mailbox_get_enabled", False)):
        debt_flags.append("legacy_mailbox_get_enabled")
    if readiness_inputs and not bool(readiness_inputs.get("local_contact_upgrade_ok", True)):
        debt_flags.append("local_contact_upgrade_incomplete")
    rotation_state = str(lookup_rotation.get("state", "") or "").strip()
    if rotation_state == "lookup_handle_rotation_pending":
        debt_flags.append("lookup_handle_rotation_pending")
    elif rotation_state == "lookup_handle_rotation_failed":
        debt_flags.append("lookup_handle_rotation_failed")
    if lookup_rotation and not bool(lookup_rotation.get("last_refresh_ok", True)):
        debt_flags.append("lookup_handle_rotation_refresh_failed")
    if gate_repair_state in {"gate_state_stale", "gate_state_resync_failed", "gate_state_recovery_only"}:
        debt_flags.append(gate_repair_state)
    normalized_debt_flags: list[str] = []
    for item in debt_flags:
        normalized = str(item or "").strip()
        if normalized and normalized not in normalized_debt_flags:
            normalized_debt_flags.append(normalized)
    ready_state = str(readiness.get("state", "") or "")
    if not normalized_debt_flags and ready_state == "ready_for_private_default":
        state = "healthy"
        plain_label = "Rollout health good"
        detail = "Cleanup and migration posture look healthy for rollout."
    elif normalized_debt_flags and bool(readiness.get("allowed", False)):
        state = "cleanup_debt_present"
        plain_label = "Cleanup debt present"
        detail = "Rollout can proceed, but cleanup and migration debt still need attention."
    else:
        state = "attention_required"
        plain_label = "Rollout health needs attention"
        detail = "Cleanup or migration posture still needs operator attention."
    return {
        "state": state,
        "plain_label": plain_label,
        "detail": detail,
        "surface_class": "authoritative_diagnostic",
        "source_model": "privacy_claims",
        "compatibility_cleanup_pending": bool(normalized_debt_flags),
        "local_contact_upgrade_ok": bool(readiness_inputs.get("local_contact_upgrade_ok", False)),
        "upgraded_contact_preferences": int(readiness_inputs.get("upgraded_contact_preferences", 0) or 0),
        "lookup_handle_rotation_state": rotation_state or "lookup_handle_rotation_unknown",
        "lookup_handle_rotation_last_refresh_ok": bool(lookup_rotation.get("last_refresh_ok", True)),
        "legacy_lookup_runtime_active": bool(readiness_inputs.get("legacy_lookup_runtime_active", False)),
        "legacy_mailbox_get_runtime_active": bool(readiness_inputs.get("legacy_mailbox_get_runtime_active", False)),
        "debt_flags": normalized_debt_flags,
    }


def privacy_claims_snapshot(
    *,
    transport_tier: str,
    local_custody: dict[str, Any] | None = None,
    privacy_core: dict[str, Any] | None = None,
    compatibility_readiness: dict[str, Any] | None = None,
    gate_privilege_access: dict[str, Any] | None = None,
    gate_repair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_tier = _normalize_tier(transport_tier)
    custody = dict(local_custody or {})
    attestation = dict(privacy_core or {})
    compatibility = dict(compatibility_readiness or {})
    gate_access = dict(gate_privilege_access or {})
    release_profile = profile_readiness_snapshot()
    profile_blockers = [
        str(item or "").strip()
        for item in list(release_profile.get("blockers") or [])
        if str(item or "").strip()
    ]

    dm_blockers = _dm_claim_blockers(
        current_tier=current_tier,
        local_custody=custody,
        privacy_core=attestation,
        compatibility_readiness=compatibility,
    )
    gate_blockers = _gate_claim_blockers(
        current_tier=current_tier,
        local_custody=custody,
        privacy_core=attestation,
        gate_privilege_access=gate_access,
        gate_repair=gate_repair,
    )
    dm_blockers.extend(blocker for blocker in profile_blockers if blocker not in dm_blockers)
    gate_blockers.extend(blocker for blocker in profile_blockers if blocker not in gate_blockers)

    dm_allowed = not dm_blockers
    gate_allowed = not gate_blockers
    control_only = current_tier == "private_control_only"
    degraded = current_tier == "public_degraded"

    claims = {
        "dm_strong": _claim_entry(
            allowed=dm_allowed,
            state="dm_strong_ready" if dm_allowed else "dm_strong_blocked",
            plain_label="DM strong ready" if dm_allowed else "DM strong blocked",
            blockers=dm_blockers,
            detail=_detail_from_blockers(
                dm_blockers,
                ready_detail="DM delivery meets the current strong private claim posture.",
                blocked_detail="DM strong claim is blocked",
            ),
            required_tier=release_lane_required_tier("dm"),
            current_tier=current_tier,
        ),
        "gate_transitional": _claim_entry(
            allowed=gate_allowed,
            state="gate_transitional_ready" if gate_allowed else "gate_transitional_blocked",
            plain_label="Gate transitional ready" if gate_allowed else "Gate transitional blocked",
            blockers=gate_blockers,
            detail=_detail_from_blockers(
                gate_blockers,
                ready_detail="Gate delivery meets the current transitional private claim posture.",
                blocked_detail="Gate transitional claim is blocked",
            ),
            required_tier=release_lane_required_tier("gate"),
            current_tier=current_tier,
        ),
        "control_only_posture": _claim_entry(
            allowed=control_only,
            state="control_only_local_only",
            plain_label="Control-only local operations"
            if control_only
            else "Not in control-only local posture",
            blockers=[] if control_only else ["transport_tier_not_private_control_only"],
            detail=(
                "Local compose, decrypt, and state operations can proceed, but network release is still blocked."
                if control_only
                else "The node is not currently limited to control-only local operations."
            ),
            required_tier="private_control_only",
            current_tier=current_tier,
        ),
        "degraded_posture": _claim_entry(
            allowed=degraded,
            state="degraded_requires_approval",
            plain_label="Needs approval for weaker privacy"
            if degraded
            else "No weaker-privacy approval posture active",
            blockers=[] if degraded else ["transport_tier_not_public_degraded"],
            detail=(
                "The private lane is unavailable; any weaker delivery path would require explicit approval."
                if degraded
                else "The node is not currently in a degraded weaker-privacy posture."
            ),
            required_tier="public_degraded",
            current_tier=current_tier,
        ),
    }

    return {
        "transport_tier": current_tier,
        "release_profile": release_profile,
        "claims": claims,
        "rollout_ready": bool(dm_allowed and gate_allowed),
        "chip": _privacy_status_chip(claims=claims, current_tier=current_tier),
        "surface_class": "authoritative_diagnostic",
        "source_model": "privacy_claims",
        "summary": {
            "dm_state": str(claims["dm_strong"]["state"] or ""),
            "gate_state": str(claims["gate_transitional"]["state"] or ""),
            "control_only": bool(control_only),
            "degraded_requires_approval": bool(degraded),
        },
    }
