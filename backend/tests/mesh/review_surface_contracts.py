from __future__ import annotations

from typing import Any

from services.privacy_claims import (
    explicit_review_export_snapshot,
    final_review_bundle_snapshot,
    release_checklist_snapshot,
    release_claims_matrix_snapshot,
    review_consistency_snapshot,
    review_manifest_snapshot,
    staged_rollout_telemetry_snapshot,
)


EXPLICIT_REVIEW_EXPORT_CONTRACT: dict[str, Any] = {
    "schema_version": "privacy_explicit_review_export.v1",
    "surface_class": "authoritative_export_bundle",
    "kind_field": "export_kind",
    "kind_value": "explicit_review_export",
    "required_top_level_keys": [
        "schema_version",
        "export_kind",
        "surface_class",
        "source_surface",
        "authoritative_model",
        "export_metadata",
        "final_review_bundle",
        "staged_rollout_telemetry",
        "release_claims_matrix",
        "release_checklist",
    ],
}


REVIEW_MANIFEST_CONTRACT: dict[str, Any] = {
    "schema_version": "privacy_review_manifest.v1",
    "surface_class": "authoritative_review_manifest",
    "kind_field": "manifest_kind",
    "kind_value": "review_manifest",
    "required_top_level_keys": [
        "schema_version",
        "manifest_kind",
        "surface_class",
        "source_surface",
        "authoritative_model",
        "manifest_metadata",
        "claim_summary_rows",
        "checklist_summary",
        "blocker_categories",
        "evidence_surfaces",
        "evidence_map",
    ],
}


REVIEW_CONSISTENCY_CONTRACT: dict[str, Any] = {
    "schema_version": "privacy_review_consistency.v1",
    "surface_class": "authoritative_review_handoff",
    "kind_field": "consistency_kind",
    "kind_value": "review_surface_consistency",
    "required_top_level_keys": [
        "schema_version",
        "consistency_kind",
        "surface_class",
        "source_surfaces",
        "authoritative_model",
        "consistency_flags",
        "alignment_verdict",
        "missing_surface_classes",
        "conflicting_surface_classes",
        "blocker_category_mismatches",
        "handoff_summary",
    ],
}


def assert_surface_contract(actual: dict[str, Any], contract: dict[str, Any]) -> None:
    required_keys = list(contract.get("required_top_level_keys") or [])
    for key in required_keys:
        assert key in actual, f"missing required key: {key}"
    assert actual["schema_version"] == contract["schema_version"]
    assert actual["surface_class"] == contract["surface_class"]
    kind_field = str(contract.get("kind_field") or "").strip()
    kind_value = contract.get("kind_value")
    assert kind_field in actual
    assert actual[kind_field] == kind_value


def _claim_surface_sources() -> dict[str, Any]:
    return {
        "surfaces": {
            "privacy_claims": {"surface_class": "authoritative_diagnostic"},
            "rollout_readiness": {"surface_class": "authoritative_diagnostic"},
            "rollout_controls": {"surface_class": "authoritative_diagnostic"},
            "rollout_health": {"surface_class": "authoritative_diagnostic"},
            "strong_claims": {"surface_class": "compatibility_shim"},
            "release_gate": {"surface_class": "compatibility_shim"},
        }
    }


def _build_review_surfaces(review_export: dict[str, Any]) -> dict[str, dict[str, Any]]:
    bundle = final_review_bundle_snapshot(review_export=review_export)
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
    return {
        "review_export": review_export,
        "final_review_bundle": bundle,
        "staged_rollout_telemetry": telemetry,
        "release_claims_matrix": matrix,
        "release_checklist": checklist,
        "explicit_review_export": export,
        "review_manifest": manifest,
        "review_consistency": consistency,
    }


def review_surface_corpus() -> dict[str, dict[str, dict[str, Any]]]:
    clean_ready = _build_review_surfaces(
        {
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
            "rollout_controls": {
                "state": "private_default_safe",
                "private_default_enforce_safe": True,
                "active_overrides": [],
                "compatibility_override_active": False,
                "legacy_compatibility_enabled": False,
            },
            "rollout_health": {
                "state": "healthy",
                "compatibility_cleanup_pending": False,
            },
            "claim_surface_sources": _claim_surface_sources(),
        }
    )
    compatibility_debt = _build_review_surfaces(
        {
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
                    "allowed": False,
                    "state": "blocked_by_cleanup_debt",
                    "plain_label": "Private default blocked by cleanup debt",
                    "detail": "cleanup debt remains",
                },
                "major_blocker": {"state": "compatibility_debt"},
            },
            "rollout_controls": {
                "state": "private_default_safe",
                "private_default_enforce_safe": False,
                "active_overrides": [],
                "compatibility_override_active": False,
                "legacy_compatibility_enabled": True,
            },
            "rollout_health": {
                "state": "cleanup_debt_present",
                "compatibility_cleanup_pending": True,
            },
            "claim_surface_sources": _claim_surface_sources(),
        }
    )
    operator_override = _build_review_surfaces(
        {
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
                    "allowed": False,
                    "state": "blocked_by_operator_override",
                    "plain_label": "Private default blocked by override",
                    "detail": "override active",
                },
                "major_blocker": {"state": "operator_override"},
            },
            "rollout_controls": {
                "state": "override_active",
                "private_default_enforce_safe": False,
                "active_overrides": ["attestation_override_active"],
                "compatibility_override_active": True,
                "legacy_compatibility_enabled": True,
            },
            "rollout_health": {
                "state": "healthy",
                "compatibility_cleanup_pending": False,
            },
            "claim_surface_sources": _claim_surface_sources(),
        }
    )
    provenance_gap = {
        **compatibility_debt,
        "review_manifest": {
            **dict(compatibility_debt["review_manifest"]),
            "evidence_surfaces": ["review_export"],
            "evidence_map": {
                "dm_strong_claim_now": {"source_surfaces": ["release_claims_matrix"]},
                "gate_transitional_claim_now": {"source_surfaces": ["release_claims_matrix"]},
                "private_default_rollout_claim_now": {
                    "source_surfaces": ["release_claims_matrix", "staged_rollout_telemetry"]
                },
                "compatibility_cleanup_complete": {
                    "source_surfaces": ["release_claims_matrix"]
                },
                "operator_override_free": {
                    "source_surfaces": ["release_claims_matrix"]
                },
                "dm_strong_claim_truth_confirmed": {
                    "source_surfaces": ["release_checklist", "release_claims_matrix"]
                },
                "gate_transitional_claim_truth_confirmed": {
                    "source_surfaces": ["release_checklist", "release_claims_matrix"]
                },
                "private_default_rollout_claim_truth_confirmed": {
                    "source_surfaces": ["release_checklist", "release_claims_matrix"]
                },
                "compatibility_cleanup_complete_checklist": {
                    "source_surfaces": ["release_checklist", "release_claims_matrix"]
                },
                "no_active_override_posture": {
                    "source_surfaces": ["release_checklist", "release_claims_matrix"]
                },
                "operator_review_package_complete": {
                    "source_surfaces": ["release_checklist"]
                },
            },
        },
    }
    provenance_gap["review_consistency"] = review_consistency_snapshot(
        explicit_review_export=provenance_gap["explicit_review_export"],
        review_manifest=provenance_gap["review_manifest"],
    )
    return {
        "clean_ready": clean_ready,
        "compatibility_debt": compatibility_debt,
        "operator_override": operator_override,
        "provenance_gap": provenance_gap,
    }
