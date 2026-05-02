from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from services.config import (
    backend_gate_decrypt_compat_effective,
    backend_gate_plaintext_compat_effective,
    gate_plaintext_persist_effective,
    get_settings,
    private_clearnet_fallback_effective,
)


VALID_RELEASE_PROFILES = {"dev", "testnet-private", "release-candidate"}


def normalize_release_profile(value: str | None) -> str:
    candidate = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "development": "dev",
        "testnet": "testnet-private",
        "private-testnet": "testnet-private",
        "rc": "release-candidate",
        "release": "release-candidate",
    }
    normalized = aliases.get(candidate, candidate)
    if normalized in VALID_RELEASE_PROFILES:
        return normalized
    return "dev"


def current_release_profile(settings: Any | None = None) -> str:
    env_value = str(os.environ.get("MESH_RELEASE_PROFILE", "") or "").strip()
    if env_value:
        return normalize_release_profile(env_value)
    snapshot = settings or get_settings()
    return normalize_release_profile(getattr(snapshot, "MESH_RELEASE_PROFILE", "dev"))


def _release_attestation_configured(settings: Any) -> bool:
    explicit_raw = str(getattr(settings, "MESH_RELEASE_ATTESTATION_PATH", "") or "").strip()
    if explicit_raw:
        return Path(explicit_raw).exists() or True
    default_path = Path(__file__).resolve().parents[1] / "data" / "release_attestation.json"
    return default_path.exists()


def profile_policy_snapshot(settings: Any | None = None) -> dict[str, Any]:
    snapshot = settings or get_settings()
    profile = current_release_profile(snapshot)
    return {
        "profile": profile,
        "recognized_profiles": sorted(VALID_RELEASE_PROFILES),
        "strict_profile": profile in {"testnet-private", "release-candidate"},
        "release_candidate": profile == "release-candidate",
        "requirements": {
            "signed_transport_lock_required": profile in {"testnet-private", "release-candidate"},
            "private_release_approval_required": profile in {"testnet-private", "release-candidate"},
            "revocation_cache_enforce_required": profile in {"testnet-private", "release-candidate"},
            "ban_kick_rotation_required": profile in {"testnet-private", "release-candidate"},
            "clearnet_fallback_block_required": profile in {"testnet-private", "release-candidate"},
            "legacy_compatibility_disabled_required": profile == "release-candidate",
            "signed_context_required": profile == "release-candidate",
            "debug_disabled_required": profile == "release-candidate",
            "privacy_core_hash_pin_required": profile == "release-candidate",
            "release_attestation_required": profile == "release-candidate",
        },
    }


def profile_blockers(settings: Any | None = None) -> list[str]:
    snapshot = settings or get_settings()
    profile = current_release_profile(snapshot)
    if profile == "dev":
        return []

    blockers: list[str] = []
    try:
        from services.mesh.mesh_rollout_flags import (
            gate_ban_kick_rotation_enabled,
            signed_revocation_cache_enforce,
            signed_write_context_required,
            signed_write_content_private_transport_lock_required,
        )

        if not bool(signed_write_content_private_transport_lock_required()):
            blockers.append("profile_signed_transport_lock_not_required")
        if not bool(signed_revocation_cache_enforce()):
            blockers.append("profile_signed_revocation_cache_not_enforced")
        if not bool(gate_ban_kick_rotation_enabled()):
            blockers.append("profile_gate_ban_kick_rotation_disabled")
        if profile == "release-candidate" and not bool(signed_write_context_required()):
            blockers.append("profile_signed_context_not_required")
    except Exception:
        blockers.append("profile_rollout_flags_unavailable")

    if not bool(getattr(snapshot, "MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", True)):
        blockers.append("profile_private_release_approval_disabled")
    if private_clearnet_fallback_effective(snapshot) != "block":
        blockers.append("profile_clearnet_fallback_not_blocked")

    if profile == "release-candidate":
        if bool(getattr(snapshot, "MESH_DEBUG_MODE", False)):
            blockers.append("profile_debug_mode_enabled")
        if bool(getattr(snapshot, "ALLOW_INSECURE_ADMIN", False)):
            blockers.append("profile_insecure_admin_enabled")
        if not str(getattr(snapshot, "PRIVACY_CORE_ALLOWED_SHA256", "") or "").strip():
            blockers.append("profile_privacy_core_hash_pin_missing")
        if not _release_attestation_configured(snapshot):
            blockers.append("profile_release_attestation_missing")

        try:
            from services.mesh.mesh_compatibility import (
                compat_dm_invite_import_override_active,
                legacy_agent_id_lookup_blocked,
                legacy_dm1_override_active,
                legacy_dm_get_override_active,
                legacy_dm_signature_compat_override_active,
                legacy_node_id_compat_blocked,
            )

            if not bool(legacy_node_id_compat_blocked()):
                blockers.append("profile_legacy_node_id_compat_enabled")
            if not bool(legacy_agent_id_lookup_blocked()):
                blockers.append("profile_legacy_agent_id_lookup_enabled")
            if bool(legacy_dm1_override_active()):
                blockers.append("profile_legacy_dm1_enabled")
            if bool(legacy_dm_get_override_active()):
                blockers.append("profile_legacy_dm_get_enabled")
            if bool(legacy_dm_signature_compat_override_active()):
                blockers.append("profile_legacy_dm_signature_compat_enabled")
            if bool(compat_dm_invite_import_override_active()):
                blockers.append("profile_compat_dm_invite_import_enabled")
        except Exception:
            blockers.append("profile_legacy_compatibility_state_unavailable")

        if bool(backend_gate_decrypt_compat_effective(snapshot)):
            blockers.append("profile_gate_backend_decrypt_compat_enabled")
        if bool(backend_gate_plaintext_compat_effective(snapshot)):
            blockers.append("profile_gate_backend_plaintext_compat_enabled")
        if bool(gate_plaintext_persist_effective(snapshot)):
            blockers.append("profile_gate_plaintext_persist_enabled")

    normalized: list[str] = []
    for blocker in blockers:
        if blocker and blocker not in normalized:
            normalized.append(blocker)
    return normalized


def profile_readiness_snapshot(settings: Any | None = None) -> dict[str, Any]:
    policy = profile_policy_snapshot(settings)
    blockers = profile_blockers(settings)
    profile = str(policy.get("profile", "dev") or "dev")
    return {
        **policy,
        "allowed": not blockers,
        "state": "release_profile_ready" if not blockers else "release_profile_blocked",
        "blockers": blockers,
        "detail": (
            f"{profile} release profile requirements are satisfied."
            if not blockers
            else f"{profile} release profile is blocked by unsafe defaults."
        ),
    }
