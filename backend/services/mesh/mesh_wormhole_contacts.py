"""Wormhole-owned DM contact and alias graph state."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from services.mesh.mesh_secure_storage import read_secure_json, write_secure_json

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CONTACTS_FILE = DATA_DIR / "wormhole_dm_contacts.json"


TRUST_LEVELS = (
    "unpinned",
    "tofu_pinned",
    "invite_pinned",
    "sas_verified",
    "mismatch",
    "continuity_broken",
)

VERIFIED_FIRST_CONTACT_TRUST_LEVELS = (
    "invite_pinned",
    "sas_verified",
)

TRUST_RECOMMENDED_ACTIONS = {
    "unpinned": "import_invite",
    "tofu_pinned": "verify_sas",
    "invite_pinned": "show_sas",
    "sas_verified": "show_sas",
    "mismatch": "reverify",
    "continuity_broken": "reverify",
}


def _default_contact() -> dict[str, Any]:
    return {
        "alias": "",
        "blocked": False,
        "dhPubKey": "",
        "dhAlgo": "",
        "sharedAlias": "",
        "sharedAliasCounter": 0,
        "sharedAliasPublicKey": "",
        "sharedAliasPublicKeyAlgo": "Ed25519",
        "dmIdentityId": "",
        "previousSharedAliases": [],
        "pendingSharedAlias": "",
        "pendingSharedAliasCounter": 0,
        "pendingSharedAliasPublicKey": "",
        "pendingSharedAliasPublicKeyAlgo": "Ed25519",
        "pendingSharedAliasGraceMs": 0,
        "sharedAliasGraceUntil": 0,
        "sharedAliasRotatedAt": 0,
        "acceptedPreviousAlias": "",
        "acceptedPreviousAliasCounter": 0,
        "acceptedPreviousAliasPublicKey": "",
        "acceptedPreviousAliasPublicKeyAlgo": "Ed25519",
        "acceptedPreviousGraceUntil": 0,
        "acceptedPreviousHardGraceUntil": 0,
        "acceptedPreviousAwaitingReply": False,
        "aliasBindingSeq": 0,
        "aliasBindingPendingReason": "",
        "aliasBindingPreparedAt": 0,
        "aliasGateJoinAppliedSeq": 0,
        "trust_level": "unpinned",
        "verify_inband": False,
        "verify_registry": False,
        "verified": False,
        "verify_mismatch": False,
        "verified_at": 0,
        "invitePinnedTrustFingerprint": "",
        "invitePinnedNodeId": "",
        "invitePinnedPublicKey": "",
        "invitePinnedPublicKeyAlgo": "",
        "invitePinnedDhPubKey": "",
        "invitePinnedDhAlgo": "",
        "invitePinnedPrekeyLookupHandle": "",
        "invitePinnedRootFingerprint": "",
        "invitePinnedRootManifestFingerprint": "",
        "invitePinnedRootWitnessPolicyFingerprint": "",
        "invitePinnedRootWitnessThreshold": 0,
        "invitePinnedRootWitnessCount": 0,
        "invitePinnedRootWitnessDomainCount": 0,
        "invitePinnedRootManifestGeneration": 0,
        "invitePinnedRootRotationProven": False,
        "invitePinnedRootNodeId": "",
        "invitePinnedRootPublicKey": "",
        "invitePinnedRootPublicKeyAlgo": "",
        "invitePinnedIssuedAt": 0,
        "invitePinnedExpiresAt": 0,
        "invitePinnedAt": 0,
        "remotePrekeyFingerprint": "",
        "remotePrekeyObservedFingerprint": "",
        "remotePrekeyRootFingerprint": "",
        "remotePrekeyRootManifestFingerprint": "",
        "remotePrekeyRootWitnessPolicyFingerprint": "",
        "remotePrekeyRootWitnessThreshold": 0,
        "remotePrekeyRootWitnessCount": 0,
        "remotePrekeyRootWitnessDomainCount": 0,
        "remotePrekeyRootManifestGeneration": 0,
        "remotePrekeyRootRotationProven": False,
        "remotePrekeyObservedRootFingerprint": "",
        "remotePrekeyObservedRootManifestFingerprint": "",
        "remotePrekeyObservedRootWitnessPolicyFingerprint": "",
        "remotePrekeyObservedRootWitnessThreshold": 0,
        "remotePrekeyObservedRootWitnessCount": 0,
        "remotePrekeyObservedRootWitnessDomainCount": 0,
        "remotePrekeyObservedRootManifestGeneration": 0,
        "remotePrekeyObservedRootRotationProven": False,
        "remotePrekeyRootNodeId": "",
        "remotePrekeyRootPublicKey": "",
        "remotePrekeyRootPublicKeyAlgo": "",
        "remotePrekeyRootPinnedAt": 0,
        "remotePrekeyRootLastSeenAt": 0,
        "remotePrekeyRootMismatch": False,
        "remotePrekeyPinnedAt": 0,
        "remotePrekeyLastSeenAt": 0,
        "remotePrekeySequence": 0,
        "remotePrekeySignedAt": 0,
        "remotePrekeyMismatch": False,
        "remotePrekeyTransparencyHead": "",
        "remotePrekeyTransparencySize": 0,
        "remotePrekeyTransparencySeenAt": 0,
        "remotePrekeyTransparencyConflict": False,
        "remotePrekeyLookupMode": "",
        "witness_count": 0,
        "witness_checked_at": 0,
        "vouch_count": 0,
        "vouch_checked_at": 0,
        "updated_at": 0,
    }


CLIENT_MUTABLE_CONTACT_FIELDS = frozenset(
    {
        "alias",
        "blocked",
        "dhPubKey",
        "dhAlgo",
        "sharedAlias",
        "sharedAliasCounter",
        "sharedAliasPublicKey",
        "sharedAliasPublicKeyAlgo",
        "previousSharedAliases",
        "pendingSharedAlias",
        "pendingSharedAliasCounter",
        "pendingSharedAliasPublicKey",
        "pendingSharedAliasPublicKeyAlgo",
        "pendingSharedAliasGraceMs",
        "sharedAliasGraceUntil",
        "sharedAliasRotatedAt",
        "acceptedPreviousAlias",
        "acceptedPreviousAliasCounter",
        "acceptedPreviousAliasPublicKey",
        "acceptedPreviousAliasPublicKeyAlgo",
        "acceptedPreviousGraceUntil",
        "acceptedPreviousHardGraceUntil",
        "acceptedPreviousAwaitingReply",
        "aliasBindingSeq",
        "aliasBindingPendingReason",
        "aliasBindingPreparedAt",
        "aliasGateJoinAppliedSeq",
        "verify_mismatch",
        "remotePrekeyTransparencyHead",
        "remotePrekeyTransparencySize",
        "remotePrekeyTransparencySeenAt",
        "remotePrekeyTransparencyConflict",
        "remotePrekeyLookupMode",
        "witness_count",
        "witness_checked_at",
        "vouch_count",
        "vouch_checked_at",
    }
)


def _sanitize_client_contact_updates(updates: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(updates or {})
    sanitized: dict[str, Any] = {}
    for key in CLIENT_MUTABLE_CONTACT_FIELDS:
        if key in current:
            sanitized[key] = current[key]
    return sanitized


def _contact_root_rotation_view(current: dict[str, Any]) -> tuple[int, bool]:
    root_mismatch = bool(current.get("remotePrekeyRootMismatch"))
    if root_mismatch:
        generation = int(current.get("remotePrekeyObservedRootManifestGeneration", 0) or 0)
        if generation <= 0:
            generation = int(current.get("remotePrekeyRootManifestGeneration", 0) or 0)
        if generation <= 0:
            return 0, False
        return generation, generation <= 1 or bool(current.get("remotePrekeyObservedRootRotationProven"))
    generation = int(current.get("remotePrekeyRootManifestGeneration", 0) or 0)
    proven = bool(current.get("remotePrekeyRootRotationProven"))
    if generation <= 0:
        generation = int(current.get("invitePinnedRootManifestGeneration", 0) or 0)
        proven = bool(current.get("invitePinnedRootRotationProven"))
    if generation <= 0:
        return 0, False
    return generation, generation <= 1 or proven


def _contact_root_witness_view(current: dict[str, Any]) -> tuple[str, int, int, bool, int, bool]:
    root_mismatch = bool(current.get("remotePrekeyRootMismatch"))
    policy_fingerprint = ""
    witness_count = 0
    witness_threshold = 0
    witness_domain_count = 0
    if root_mismatch:
        policy_fingerprint = str(
            current.get("remotePrekeyObservedRootWitnessPolicyFingerprint", "") or ""
        ).strip().lower()
        witness_count = int(current.get("remotePrekeyObservedRootWitnessCount", 0) or 0)
        witness_threshold = int(current.get("remotePrekeyObservedRootWitnessThreshold", 0) or 0)
        witness_domain_count = int(current.get("remotePrekeyObservedRootWitnessDomainCount", 0) or 0)
    else:
        policy_fingerprint = str(current.get("remotePrekeyRootWitnessPolicyFingerprint", "") or "").strip().lower()
        witness_count = int(current.get("remotePrekeyRootWitnessCount", 0) or 0)
        witness_threshold = int(current.get("remotePrekeyRootWitnessThreshold", 0) or 0)
        witness_domain_count = int(current.get("remotePrekeyRootWitnessDomainCount", 0) or 0)
        if witness_threshold <= 0:
            policy_fingerprint = policy_fingerprint or str(
                current.get("invitePinnedRootWitnessPolicyFingerprint", "") or ""
            ).strip().lower()
            witness_count = max(witness_count, int(current.get("invitePinnedRootWitnessCount", 0) or 0))
            witness_threshold = max(witness_threshold, int(current.get("invitePinnedRootWitnessThreshold", 0) or 0))
            witness_domain_count = max(
                witness_domain_count,
                int(current.get("invitePinnedRootWitnessDomainCount", 0) or 0),
            )
    legacy_single_witness = witness_threshold <= 0
    if legacy_single_witness:
        witness_threshold = 1
        if witness_count <= 0:
            witness_count = 1
        if witness_domain_count <= 0:
            witness_domain_count = 1
    elif witness_count > 0 and witness_domain_count <= 0:
        witness_domain_count = 1
    quorum_met = witness_threshold > 0 and witness_count >= witness_threshold
    independent_quorum_met = witness_threshold > 0 and witness_domain_count >= witness_threshold
    return (
        policy_fingerprint,
        max(0, witness_count),
        max(0, witness_threshold),
        quorum_met,
        max(0, witness_domain_count),
        independent_quorum_met,
    )


def describe_contact_trust(contact: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(contact or {})
    from services.mesh.mesh_rollout_flags import wormhole_root_witness_finality_enforce
    from services.mesh.mesh_wormhole_root_manifest import root_witness_finality_met as root_witness_finality_met_view

    level = str(current.get("trust_level", "") or "").strip()
    if level not in TRUST_LEVELS:
        level = "unpinned"
    transparency_conflict = bool(current.get("remotePrekeyTransparencyConflict"))
    registry_mismatch = bool(current.get("verify_mismatch"))
    legacy_lookup = str(current.get("remotePrekeyLookupMode", "") or "").strip().lower() == "legacy_agent_id"
    root_attested = bool(
        str(current.get("invitePinnedRootFingerprint", "") or "").strip()
        or str(current.get("remotePrekeyRootFingerprint", "") or "").strip()
    )
    root_witnessed = bool(
        str(current.get("invitePinnedRootManifestFingerprint", "") or "").strip()
        or str(current.get("remotePrekeyRootManifestFingerprint", "") or "").strip()
        or str(current.get("remotePrekeyObservedRootManifestFingerprint", "") or "").strip()
    )
    root_mismatch = bool(current.get("remotePrekeyRootMismatch"))
    root_manifest_generation, root_rotation_proven = _contact_root_rotation_view(current)
    (
        root_witness_policy_fingerprint,
        root_witness_count,
        root_witness_threshold,
        root_witness_quorum_met,
        root_witness_domain_count,
        root_witness_independent_quorum_met,
    ) = _contact_root_witness_view(current) if root_witnessed else ("", 0, 0, False, 0, False)
    root_rotation_unproven = bool(root_witnessed and root_manifest_generation > 1 and not root_rotation_proven)
    invite_attested = bool(
        str(current.get("invitePinnedTrustFingerprint", "") or "").strip()
        or int(current.get("invitePinnedAt", 0) or 0) > 0
    )
    if not root_attested:
        root_distribution_state = "none"
    elif not root_witnessed:
        root_distribution_state = "internal_only"
    elif not root_witness_quorum_met:
        root_distribution_state = "witness_policy_not_met"
    elif root_witness_threshold <= 1:
        root_distribution_state = "single_witness"
    else:
        root_distribution_state = "quorum_witnessed"
    if not root_attested:
        root_witness_provenance_state = "none"
    elif not root_witnessed:
        root_witness_provenance_state = "internal_only"
    elif not root_witness_quorum_met:
        root_witness_provenance_state = "witness_policy_not_met"
    elif root_witness_threshold <= 1:
        root_witness_provenance_state = "single_witness"
    elif root_witness_independent_quorum_met:
        root_witness_provenance_state = "independent_quorum"
    else:
        root_witness_provenance_state = "local_quorum"
    root_witness_finality_met = root_witness_finality_met_view(
        witness_threshold=root_witness_threshold,
        witness_quorum_met=root_witness_quorum_met,
        witness_independent_quorum_met=root_witness_independent_quorum_met,
    )
    enforce_root_witness_finality = bool(wormhole_root_witness_finality_enforce())
    root_distribution_upgrade_needed = bool(
        root_attested and root_distribution_state in ("internal_only", "single_witness", "witness_policy_not_met")
    )
    root_finality_upgrade_needed = bool(
        root_attested
        and root_distribution_state == "quorum_witnessed"
        and root_witness_threshold > 1
        and not root_witness_finality_met
    )
    witnessed_root_label = (
        "independently quorum-witnessed stable root identity"
        if root_witness_provenance_state == "independent_quorum"
        else (
            "locally quorum-witnessed stable root identity"
            if root_witness_provenance_state == "local_quorum"
            else (
                "single-witness stable root identity"
                if root_witness_provenance_state == "single_witness"
                else "witnessed stable root identity"
            )
        )
    )
    label = "UNVERIFIED"
    severity = "warn"
    detail = "No trusted first-contact anchor. Import a signed invite before secure first contact."
    recommended_action = TRUST_RECOMMENDED_ACTIONS.get(level, "show_sas")
    if level == "tofu_pinned":
        label = "TOFU PINNED"
        detail = (
            "First contact is pinned on first sight only. Verify SAS before sensitive use."
            if not root_attested
            else (
                (
                    (
                        f"Current prekey is seen under one {witnessed_root_label}, but first contact is still TOFU-only. Verify SAS before sensitive use."
                        if root_witness_provenance_state in ("independent_quorum", "local_quorum")
                        else (
                            "Current prekey is seen under one single-witness stable root, but first contact is still TOFU-only. Re-import a current signed invite if you want stronger quorum witness provenance."
                            if root_witness_provenance_state == "single_witness"
                            else "Current prekey is seen under a witnessed stable root, but the current witness policy is not satisfied. Replace or re-import the signed invite before treating this root as strong first-contact provenance."
                        )
                    )
                    if not root_rotation_unproven
                    else "Current prekey is seen under one witnessed stable root, but that root rotation lacks previous-root proof. Replace the signed invite before treating this root as continuous."
                )
                if root_witnessed
                else "Current prekey is seen under one stable root, but first contact is still TOFU-only. Verify SAS before sensitive use."
            )
        )
    elif level == "invite_pinned":
        label = "INVITE PINNED"
        detail = (
            "First contact is anchored to an imported signed invite. SAS is optional but recommended for continuity."
            if not root_attested
            else (
                (
                    (
                        f"First contact is anchored to an imported signed invite and an {witnessed_root_label}. SAS is optional but recommended for continuity."
                        if root_witness_provenance_state in ("independent_quorum", "local_quorum")
                        else (
                            "First contact is anchored to an imported signed invite and a single-witness stable root identity. Re-import a current signed invite if you want stronger quorum witness provenance."
                            if root_witness_provenance_state == "single_witness"
                            else "First contact is anchored to an imported signed invite and a witnessed stable root identity, but the current witness policy is not satisfied. Replace the signed invite before private use."
                        )
                    )
                    if not root_rotation_unproven
                    else "First contact is anchored to an imported signed invite and a witnessed stable root identity, but its current root rotation lacks previous-root proof. Replace the signed invite before private use."
                )
                if root_witnessed
                else "First contact is anchored to an imported signed invite and a stable root identity. Re-import a current signed invite to refresh witnessed root distribution."
            )
        )
        if root_distribution_upgrade_needed or root_rotation_unproven:
            recommended_action = "import_invite"
    elif level == "sas_verified":
        label = "SAS VERIFIED"
        severity = "good"
        detail = (
            "This contact was confirmed with a shared SAS phrase on the current pinned fingerprint."
            if not root_attested
            else (
                (
                    (
                        f"This contact was SAS confirmed on the current pinned fingerprint and an {witnessed_root_label}."
                        if root_witness_provenance_state in ("independent_quorum", "local_quorum")
                        else (
                            "This contact was SAS confirmed on the current pinned fingerprint and single-witness stable root identity. Re-import a current signed invite if you want stronger quorum witness provenance."
                            if root_witness_provenance_state == "single_witness"
                            else "This contact was SAS confirmed on the current pinned fingerprint, but the current witnessed root does not satisfy its witness policy."
                        )
                    )
                    if not root_rotation_unproven
                    else "This contact was SAS confirmed on the current pinned fingerprint, but its current witnessed root rotation lacks previous-root proof."
                )
                if root_witnessed
                else "This contact was SAS confirmed on the current pinned fingerprint and stable root identity, but its root distribution is still internal-only."
            )
        )
        if root_distribution_upgrade_needed or root_rotation_unproven:
            recommended_action = "import_invite"
    elif level == "mismatch":
        label = "REVERIFY"
        severity = "danger"
        detail = (
            "Observed prekey identity changed. Compare SAS before trusting the new key."
            if not root_mismatch
            else (
                (
                    f"Observed {witnessed_root_label} changed. Replace the invite or compare SAS before trusting the new key."
                    if root_witness_provenance_state in ("independent_quorum", "local_quorum")
                    else (
                        "Observed single-witness stable root identity changed. Replace the invite or compare SAS before trusting the new key."
                        if root_witness_provenance_state == "single_witness"
                        else "Observed stable root identity changed and its current witness policy is not satisfied. Replace the invite before trusting the new key."
                    )
                )
                if not root_rotation_unproven
                else "Observed witnessed stable root rotation lacks previous-root proof. Replace the invite before trusting this root change."
            )
        )
    elif level == "continuity_broken":
        label = "CONTINUITY BROKEN"
        severity = "danger"
        detail = (
            "Pinned trust anchor changed. Re-verify SAS or replace the invite before private use."
            if not root_mismatch
            else (
                (
                    f"Pinned {witnessed_root_label} changed. Replace the signed invite or re-verify SAS before private use."
                    if root_witness_provenance_state in ("independent_quorum", "local_quorum")
                    else (
                        "Pinned single-witness stable root identity changed. Replace the signed invite or re-verify SAS before private use."
                        if root_witness_provenance_state == "single_witness"
                        else "Pinned stable root identity changed and its current witness policy is not satisfied. Replace the signed invite or re-verify SAS before private use."
                    )
                )
                if not root_rotation_unproven
                else "Pinned witnessed stable root changed without previous-root proof. Replace the signed invite or re-verify SAS before private use."
            )
        )
    if transparency_conflict:
        detail = (
            "Prekey transparency history conflicted. Trust stays degraded until you explicitly acknowledge the changed fingerprint."
        )
    elif root_rotation_unproven and level not in ("mismatch", "continuity_broken"):
        recommended_action = "import_invite"
    elif root_distribution_state == "witness_policy_not_met" and level not in ("mismatch", "continuity_broken"):
        recommended_action = "import_invite"
    elif enforce_root_witness_finality and root_finality_upgrade_needed and level not in ("mismatch", "continuity_broken"):
        recommended_action = "import_invite"
    elif legacy_lookup and level not in ("mismatch", "continuity_broken"):
        detail = (
            f"{detail} This contact still bootstraps through legacy direct agent ID lookup. "
            "Import or re-import a signed invite to avoid stable-ID lookup before removal."
        )
        recommended_action = "import_invite"
    return {
        "state": level,
        "label": label,
        "severity": severity,
        "detail": detail,
        "verifiedFirstContact": (
            level in VERIFIED_FIRST_CONTACT_TRUST_LEVELS
            and not root_rotation_unproven
            and root_distribution_state != "witness_policy_not_met"
            and not (enforce_root_witness_finality and root_finality_upgrade_needed)
        ),
        "recommendedAction": recommended_action,
        "legacyLookup": legacy_lookup,
        "inviteAttested": invite_attested,
        "rootAttested": root_attested,
        "rootWitnessed": root_witnessed,
        "rootDistributionState": root_distribution_state,
        "rootWitnessPolicyFingerprint": root_witness_policy_fingerprint,
        "rootWitnessCount": root_witness_count,
        "rootWitnessThreshold": root_witness_threshold,
        "rootWitnessQuorumMet": root_witness_quorum_met,
        "rootWitnessProvenanceState": root_witness_provenance_state,
        "rootWitnessDomainCount": root_witness_domain_count,
        "rootWitnessIndependentQuorumMet": root_witness_independent_quorum_met,
        "rootWitnessFinalityMet": root_witness_finality_met,
        "rootManifestGeneration": root_manifest_generation,
        "rootRotationProven": root_rotation_proven,
        "rootMismatch": root_mismatch,
        "registryMismatch": registry_mismatch,
        "transparencyConflict": transparency_conflict,
    }


def describe_contact_alias_state(contact: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(contact or {})
    trust_summary = dict(current.get("trustSummary") or {})
    now_ms = int(time.time() * 1000)
    active_alias = str(current.get("sharedAlias", "") or "").strip()
    pending_alias = str(current.get("pendingSharedAlias", "") or "").strip()
    grace_until = int(current.get("sharedAliasGraceUntil", 0) or 0)
    rotated_at = int(current.get("sharedAliasRotatedAt", 0) or 0)
    has_peer_dh = bool(
        str(
            current.get("dhPubKey")
            or current.get("invitePinnedDhPubKey")
            or ""
        ).strip()
    )
    verified_first_contact = bool(trust_summary.get("verifiedFirstContact"))
    pending_active = bool(pending_alias)
    grace_remaining_ms = max(0, grace_until - now_ms) if pending_alias and grace_until > 0 else 0
    can_prepare_issue = bool(not active_alias and has_peer_dh and not pending_active)
    can_prepare_rotation = bool(active_alias and has_peer_dh and not pending_active)
    background_prepare_allowed = bool(
        verified_first_contact and (can_prepare_issue or can_prepare_rotation)
    )

    if pending_active:
        state = "pending_promotion"
        recommended_action = "wait_for_promotion"
    elif not has_peer_dh:
        state = "needs_peer_dh"
        recommended_action = "refresh_contact"
    elif not active_alias:
        state = "ready_to_issue"
        recommended_action = (
            "issue_alias"
            if verified_first_contact
            else str(trust_summary.get("recommendedAction", "") or "verify_contact")
        )
    else:
        state = "active"
        recommended_action = (
            "rotate_when_needed"
            if verified_first_contact
            else str(trust_summary.get("recommendedAction", "") or "verify_contact")
        )

    return {
        "state": state,
        "hasActiveAlias": bool(active_alias),
        "hasPendingAlias": bool(pending_alias),
        "graceUntil": grace_until,
        "graceRemainingMs": grace_remaining_ms,
        "lastRotatedAt": rotated_at,
        "hasPeerDh": has_peer_dh,
        "verifiedFirstContact": verified_first_contact,
        "canPrepareIssue": can_prepare_issue,
        "canPrepareRotation": can_prepare_rotation,
        "backgroundPrepareAllowed": background_prepare_allowed,
        "recommendedAction": recommended_action,
    }


def accepted_contact_shared_aliases(
    contact: dict[str, Any] | None,
    *,
    now_ms: int | None = None,
) -> list[str]:
    current = _normalize_contact(contact)
    accepted: list[str] = []
    active_alias = str(current.get("sharedAlias", "") or "").strip()
    pending_alias = str(current.get("pendingSharedAlias", "") or "").strip()
    grace_until = int(current.get("sharedAliasGraceUntil", 0) or 0)
    previous_alias = str(current.get("acceptedPreviousAlias", "") or "").strip()
    previous_grace_until = int(current.get("acceptedPreviousGraceUntil", 0) or 0)
    previous_hard_grace_until = int(current.get("acceptedPreviousHardGraceUntil", 0) or 0)
    previous_awaiting_reply = bool(current.get("acceptedPreviousAwaitingReply"))
    if active_alias:
        accepted.append(active_alias)
    current_ms = int(now_ms) if now_ms is not None else int(time.time() * 1000)
    if pending_alias and grace_until > current_ms and pending_alias not in accepted:
        accepted.append(pending_alias)
    if previous_alias and previous_alias not in accepted:
        within_default_grace = previous_grace_until > current_ms
        within_hard_cap = previous_awaiting_reply and previous_hard_grace_until > current_ms
        if within_default_grace or within_hard_cap:
            accepted.append(previous_alias)
    return accepted


def contact_shared_alias_accepted(
    contact: dict[str, Any] | None,
    alias: str,
    *,
    now_ms: int | None = None,
) -> bool:
    alias_key = str(alias or "").strip()
    if not alias_key:
        return False
    return alias_key in accepted_contact_shared_aliases(contact, now_ms=now_ms)


def _normalize_contact(value: dict[str, Any] | None) -> dict[str, Any]:
    defaults = _default_contact()
    merged = dict(defaults)
    if isinstance(value, dict):
        merged.update(value)
    current = {key: merged.get(key, defaults[key]) for key in defaults.keys()}
    current["alias"] = str(current.get("alias", "") or "")
    current["blocked"] = bool(current.get("blocked"))
    current["dhPubKey"] = str(current.get("dhPubKey", "") or "")
    current["dhAlgo"] = str(current.get("dhAlgo", "") or "")
    current["sharedAlias"] = str(current.get("sharedAlias", "") or "")
    current["sharedAliasCounter"] = int(current.get("sharedAliasCounter", 0) or 0)
    current["sharedAliasPublicKey"] = str(current.get("sharedAliasPublicKey", "") or "")
    current["sharedAliasPublicKeyAlgo"] = str(current.get("sharedAliasPublicKeyAlgo", "Ed25519") or "Ed25519")
    raw_dm_identity_id = str(
        current.get("dmIdentityId", "")
        or merged.get("dm_identity_id", "")
        or ""
    ).strip()
    if raw_dm_identity_id:
        try:
            from services.mesh.mesh_wormhole_dead_drop import dead_drop_redact_label

            current["dmIdentityId"] = dead_drop_redact_label(raw_dm_identity_id)
        except Exception:
            current["dmIdentityId"] = raw_dm_identity_id
    else:
        current["dmIdentityId"] = ""
    current["previousSharedAliases"] = [
        str(item or "") for item in list(current.get("previousSharedAliases") or []) if str(item or "").strip()
    ][-2:]
    current["pendingSharedAlias"] = str(current.get("pendingSharedAlias", "") or "")
    current["pendingSharedAliasCounter"] = int(current.get("pendingSharedAliasCounter", 0) or 0)
    current["pendingSharedAliasPublicKey"] = str(current.get("pendingSharedAliasPublicKey", "") or "")
    current["pendingSharedAliasPublicKeyAlgo"] = str(
        current.get("pendingSharedAliasPublicKeyAlgo", "Ed25519") or "Ed25519"
    )
    current["pendingSharedAliasGraceMs"] = int(current.get("pendingSharedAliasGraceMs", 0) or 0)
    current["acceptedPreviousAlias"] = str(current.get("acceptedPreviousAlias", "") or "")
    current["acceptedPreviousAliasCounter"] = int(current.get("acceptedPreviousAliasCounter", 0) or 0)
    current["acceptedPreviousAliasPublicKey"] = str(current.get("acceptedPreviousAliasPublicKey", "") or "")
    current["acceptedPreviousAliasPublicKeyAlgo"] = str(
        current.get("acceptedPreviousAliasPublicKeyAlgo", "Ed25519") or "Ed25519"
    )
    current["aliasBindingSeq"] = int(current.get("aliasBindingSeq", 0) or 0)
    current["aliasBindingPendingReason"] = str(current.get("aliasBindingPendingReason", "") or "")
    current["invitePinnedTrustFingerprint"] = str(current.get("invitePinnedTrustFingerprint", "") or "").strip().lower()
    current["invitePinnedNodeId"] = str(current.get("invitePinnedNodeId", "") or "")
    current["invitePinnedPublicKey"] = str(current.get("invitePinnedPublicKey", "") or "")
    current["invitePinnedPublicKeyAlgo"] = str(current.get("invitePinnedPublicKeyAlgo", "") or "")
    current["invitePinnedDhPubKey"] = str(current.get("invitePinnedDhPubKey", "") or "")
    current["invitePinnedDhAlgo"] = str(current.get("invitePinnedDhAlgo", "") or "")
    current["invitePinnedPrekeyLookupHandle"] = str(current.get("invitePinnedPrekeyLookupHandle", "") or "")
    current["invitePinnedRootFingerprint"] = str(current.get("invitePinnedRootFingerprint", "") or "").strip().lower()
    current["invitePinnedRootManifestFingerprint"] = str(
        current.get("invitePinnedRootManifestFingerprint", "") or ""
    ).strip().lower()
    current["invitePinnedRootWitnessPolicyFingerprint"] = str(
        current.get("invitePinnedRootWitnessPolicyFingerprint", "") or ""
    ).strip().lower()
    current["invitePinnedRootNodeId"] = str(current.get("invitePinnedRootNodeId", "") or "")
    current["invitePinnedRootPublicKey"] = str(current.get("invitePinnedRootPublicKey", "") or "")
    current["invitePinnedRootPublicKeyAlgo"] = str(current.get("invitePinnedRootPublicKeyAlgo", "") or "")
    current["remotePrekeyFingerprint"] = str(current.get("remotePrekeyFingerprint", "") or "")
    current["remotePrekeyObservedFingerprint"] = str(current.get("remotePrekeyObservedFingerprint", "") or "")
    current["remotePrekeyRootFingerprint"] = str(current.get("remotePrekeyRootFingerprint", "") or "").strip().lower()
    current["remotePrekeyRootManifestFingerprint"] = str(
        current.get("remotePrekeyRootManifestFingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyRootWitnessPolicyFingerprint"] = str(
        current.get("remotePrekeyRootWitnessPolicyFingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyObservedRootFingerprint"] = str(
        current.get("remotePrekeyObservedRootFingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyObservedRootManifestFingerprint"] = str(
        current.get("remotePrekeyObservedRootManifestFingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyObservedRootWitnessPolicyFingerprint"] = str(
        current.get("remotePrekeyObservedRootWitnessPolicyFingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyRootNodeId"] = str(current.get("remotePrekeyRootNodeId", "") or "")
    current["remotePrekeyRootPublicKey"] = str(current.get("remotePrekeyRootPublicKey", "") or "")
    current["remotePrekeyRootPublicKeyAlgo"] = str(current.get("remotePrekeyRootPublicKeyAlgo", "") or "")
    current["remotePrekeyTransparencyHead"] = str(
        current.get("remotePrekeyTransparencyHead", "") or ""
    ).strip().lower()
    current["remotePrekeyLookupMode"] = str(current.get("remotePrekeyLookupMode", "") or "").strip().lower()
    tl = str(current.get("trust_level", "") or "").strip()
    current["trust_level"] = tl if tl in TRUST_LEVELS else "unpinned"
    for key in (
        "sharedAliasGraceUntil",
        "sharedAliasRotatedAt",
        "acceptedPreviousGraceUntil",
        "acceptedPreviousHardGraceUntil",
        "aliasBindingPreparedAt",
        "aliasGateJoinAppliedSeq",
        "verified_at",
        "invitePinnedIssuedAt",
        "invitePinnedExpiresAt",
        "invitePinnedAt",
        "invitePinnedRootManifestGeneration",
        "invitePinnedRootWitnessThreshold",
        "invitePinnedRootWitnessCount",
        "invitePinnedRootWitnessDomainCount",
        "remotePrekeyRootPinnedAt",
        "remotePrekeyRootLastSeenAt",
        "remotePrekeyRootWitnessThreshold",
        "remotePrekeyRootWitnessCount",
        "remotePrekeyRootWitnessDomainCount",
        "remotePrekeyRootManifestGeneration",
        "remotePrekeyObservedRootWitnessThreshold",
        "remotePrekeyObservedRootWitnessCount",
        "remotePrekeyObservedRootWitnessDomainCount",
        "remotePrekeyObservedRootManifestGeneration",
        "remotePrekeyPinnedAt",
        "remotePrekeyLastSeenAt",
        "remotePrekeySequence",
        "remotePrekeySignedAt",
        "remotePrekeyTransparencySize",
        "remotePrekeyTransparencySeenAt",
        "witness_count",
        "witness_checked_at",
        "vouch_count",
        "vouch_checked_at",
        "updated_at",
    ):
        current[key] = int(current.get(key, 0) or 0)
    for key in (
        "verify_inband",
        "verify_registry",
        "verified",
        "verify_mismatch",
        "acceptedPreviousAwaitingReply",
        "invitePinnedRootRotationProven",
        "remotePrekeyRootMismatch",
        "remotePrekeyRootRotationProven",
        "remotePrekeyObservedRootRotationProven",
        "remotePrekeyMismatch",
        "remotePrekeyTransparencyConflict",
    ):
        current[key] = bool(current.get(key))
    current["trustSummary"] = describe_contact_trust(current)
    current["aliasSummary"] = describe_contact_alias_state(current)
    return current


def get_contact_trust_level(peer_id: str) -> str:
    peer_key = str(peer_id or "").strip()
    if not peer_key:
        return "unpinned"
    contacts = _read_contacts()
    current = _normalize_contact(contacts.get(peer_key))
    return str(current.get("trust_level", "") or "").strip() or "unpinned"


def verified_first_contact_requirement(peer_id: str = "", trust_level: str | None = None) -> dict[str, Any]:
    peer_key = str(peer_id or "").strip()
    if peer_key:
        contacts = _read_contacts()
        current = _normalize_contact(contacts.get(peer_key))
        trust_summary = dict(current.get("trustSummary") or {})
        state = str(trust_summary.get("state", current.get("trust_level", "")) or "").strip() or "unpinned"
        if bool(trust_summary.get("verifiedFirstContact")):
            return {
                "ok": True,
                "trust_level": state,
            }
        if state in ("mismatch", "continuity_broken"):
            return {
                "ok": False,
                "trust_level": state,
                "detail": "remote prekey identity changed; verification required",
            }
        if bool(trust_summary.get("rootWitnessed")) and int(trust_summary.get("rootManifestGeneration", 0) or 0) > 1 and not bool(
            trust_summary.get("rootRotationProven")
        ):
            return {
                "ok": False,
                "trust_level": state,
                "detail": str(
                    trust_summary.get("detail", "")
                    or "current witnessed root rotation lacks previous-root proof",
                ),
            }
        if (
            state in VERIFIED_FIRST_CONTACT_TRUST_LEVELS
            and
            str(trust_summary.get("rootDistributionState", "") or "") == "quorum_witnessed"
            and int(trust_summary.get("rootWitnessThreshold", 0) or 0) > 1
            and not bool(trust_summary.get("rootWitnessFinalityMet"))
        ):
            return {
                "ok": False,
                "trust_level": state,
                "detail": "independent quorum root witness finality required before secure first contact",
            }
        return {
            "ok": False,
            "trust_level": state,
            "detail": "signed invite or SAS verification required before secure first contact",
        }
    level = str(trust_level or "").strip() or get_contact_trust_level(peer_id)
    if level in VERIFIED_FIRST_CONTACT_TRUST_LEVELS:
        return {
            "ok": True,
            "trust_level": level,
        }
    if level in ("mismatch", "continuity_broken"):
        return {
            "ok": False,
            "trust_level": level,
            "detail": "remote prekey identity changed; verification required",
        }
    return {
        "ok": False,
        "trust_level": level or "unpinned",
        "detail": "signed invite or SAS verification required before secure first contact",
    }


def _merge_alias_history(*aliases: str, limit: int = 2) -> list[str]:
    unique: set[str] = set()
    ordered: list[str] = []
    for alias in aliases:
        value = str(alias or "").strip()
        if not value or value in unique:
            continue
        unique.add(value)
        ordered.append(value)
        if len(ordered) >= limit:
            break
    return ordered


def _promote_pending_alias_if_due(contact: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    return _normalize_contact(contact), False


def _read_contacts() -> dict[str, dict[str, Any]]:
    try:
        raw = read_secure_json(CONTACTS_FILE, lambda: {})
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Contacts file could not be decrypted — starting with empty contacts"
        )
        CONTACTS_FILE.unlink(missing_ok=True)
        return {}
    if not isinstance(raw, dict):
        return {}
    contacts: dict[str, dict[str, Any]] = {}
    changed = False
    for peer_id, value in raw.items():
        key = str(peer_id or "").strip()
        if not key:
            continue
        normalized, promoted = _promote_pending_alias_if_due(value if isinstance(value, dict) else {})
        invite_lookup_upgraded = _promote_invite_lookup_mode(normalized)
        contacts[key] = normalized
        changed = changed or promoted or invite_lookup_upgraded
    if changed:
        _write_contacts(contacts)
    return contacts


def _write_contacts(contacts: dict[str, dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, dict[str, Any]] = {}
    for peer_id, contact in contacts.items():
        key = str(peer_id or "").strip()
        if not key:
            continue
        normalized = _normalize_contact(contact)
        normalized.pop("trustSummary", None)
        normalized.pop("aliasSummary", None)
        payload[key] = normalized
    write_secure_json(CONTACTS_FILE, payload)


def _normalize_sas_phrase(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _derive_expected_contact_sas_phrase(
    peer_id: str,
    *,
    peer_ref: str = "",
    words: int = 8,
    peer_dh_pub_override: str = "",
) -> dict[str, Any]:
    peer_key = str(peer_id or "").strip()
    if not peer_key:
        raise ValueError("peer_id required")
    contacts = _read_contacts()
    current = _normalize_contact(contacts.get(peer_key))
    peer_dh_pub = str(
        peer_dh_pub_override
        or current.get("dhPubKey")
        or current.get("invitePinnedDhPubKey")
        or ""
    ).strip()
    if not peer_dh_pub:
        return {
            "ok": False,
            "detail": "peer dh identity unavailable for sas verification",
        }

    from services.mesh.mesh_wormhole_dead_drop import derive_sas_phrase

    return derive_sas_phrase(
        peer_id=peer_key,
        peer_dh_pub=peer_dh_pub,
        words=words,
        peer_ref=str(peer_ref or ""),
    )


def list_wormhole_dm_contacts() -> dict[str, dict[str, Any]]:
    return _read_contacts()


def _promote_invite_lookup_mode(contact: dict[str, Any], *, now: int | None = None) -> bool:
    current = dict(contact or {})
    lookup_handle = str(current.get("invitePinnedPrekeyLookupHandle", "") or "").strip()
    if not lookup_handle:
        return False
    if str(current.get("remotePrekeyLookupMode", "") or "").strip().lower() == "invite_lookup_handle":
        return False
    current["remotePrekeyLookupMode"] = "invite_lookup_handle"
    current["updated_at"] = int(now if now is not None else time.time())
    contact.clear()
    contact.update(_normalize_contact(current))
    return True


def upgrade_invite_scoped_contact_preferences() -> int:
    contacts = _read_contacts()
    now = int(time.time())
    changed = 0
    for peer_id, raw_contact in list(contacts.items()):
        current = _normalize_contact(raw_contact)
        if _promote_invite_lookup_mode(current, now=now):
            contacts[peer_id] = current
            changed += 1
    if changed:
        _write_contacts(contacts)
    return changed


def preferred_prekey_lookup_handle(peer_id: str) -> str:
    peer_key = str(peer_id or "").strip()
    if not peer_key:
        return ""
    contacts = _read_contacts()
    current = _normalize_contact(contacts.get(peer_key))
    if _promote_invite_lookup_mode(current):
        contacts[peer_key] = current
        _write_contacts(contacts)
    return str(current.get("invitePinnedPrekeyLookupHandle", "") or "").strip()


def compatibility_lookup_readiness_snapshot() -> dict[str, Any]:
    contacts = _read_contacts()
    stored_legacy_lookup_contacts = 0
    stored_invite_lookup_contacts = 0
    for raw_contact in list(contacts.values()):
        current = _normalize_contact(raw_contact)
        lookup_mode = str(current.get("remotePrekeyLookupMode", "") or "").strip().lower()
        lookup_handle = str(current.get("invitePinnedPrekeyLookupHandle", "") or "").strip()
        if lookup_handle:
            stored_invite_lookup_contacts += 1
        if lookup_mode == "legacy_agent_id":
            stored_legacy_lookup_contacts += 1
    return {
        "stored_legacy_lookup_contacts_present": stored_legacy_lookup_contacts > 0,
        "stored_legacy_lookup_contacts": stored_legacy_lookup_contacts,
        "stored_invite_lookup_contacts": stored_invite_lookup_contacts,
    }


def upsert_wormhole_dm_contact(peer_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    return _upsert_wormhole_dm_contact(peer_id, updates, sanitize_updates=True)


def upsert_wormhole_dm_contact_internal(peer_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    return _upsert_wormhole_dm_contact(peer_id, updates, sanitize_updates=False)


def _upsert_wormhole_dm_contact(
    peer_id: str,
    updates: dict[str, Any],
    *,
    sanitize_updates: bool,
) -> dict[str, Any]:
    peer_id = str(peer_id or "").strip()
    if not peer_id:
        raise ValueError("peer_id required")
    contacts = _read_contacts()
    current = _normalize_contact(contacts.get(peer_id))
    safe_updates = _sanitize_client_contact_updates(updates) if sanitize_updates else dict(updates or {})
    merged = _normalize_contact({**current, **safe_updates})
    merged["updated_at"] = int(time.time())
    contacts[peer_id] = merged
    _write_contacts(contacts)
    return merged


def roll_forward_invite_lookup_handles(
    mapping: dict[str, str] | None,
    *,
    invite_node_id: str = "",
) -> int:
    current_mapping = {
        str(old or "").strip(): str(new or "").strip()
        for old, new in dict(mapping or {}).items()
        if str(old or "").strip() and str(new or "").strip() and str(old or "").strip() != str(new or "").strip()
    }
    if not current_mapping:
        return 0
    expected_node_id = str(invite_node_id or "").strip()
    contacts = _read_contacts()
    now = int(time.time())
    changed = 0
    for peer_id, raw_contact in list(contacts.items()):
        current = _normalize_contact(raw_contact)
        if expected_node_id and str(current.get("invitePinnedNodeId", "") or "").strip() != expected_node_id:
            continue
        old_handle = str(current.get("invitePinnedPrekeyLookupHandle", "") or "").strip()
        new_handle = current_mapping.get(old_handle, "")
        if not new_handle:
            continue
        current["invitePinnedPrekeyLookupHandle"] = new_handle
        current["updated_at"] = now
        contacts[peer_id] = _normalize_contact(current)
        changed += 1
    if changed:
        _write_contacts(contacts)
    return changed


def pin_wormhole_dm_invite(
    peer_id: str,
    *,
    invite_payload: dict[str, Any],
    alias: str = "",
    attested: bool = True,
) -> dict[str, Any]:
    peer_key = str(peer_id or "").strip()
    if not peer_key:
        raise ValueError("peer_id required")
    payload = dict(invite_payload or {})
    trust_fingerprint = str(payload.get("trust_fingerprint", "") or "").strip().lower()
    if not trust_fingerprint:
        raise ValueError("invite trust_fingerprint required")

    contacts = _read_contacts()
    current = _normalize_contact(contacts.get(peer_key))
    now = int(time.time())
    trust_level = "invite_pinned" if bool(attested) else "tofu_pinned"
    identity_dh_pub_key = str(payload.get("identity_dh_pub_key", "") or "")
    dh_algo = str(payload.get("dh_algo", "X25519") or "X25519")
    prekey_lookup_handle = str(payload.get("prekey_lookup_handle", "") or "")
    if str(alias or "").strip():
        current["alias"] = str(alias or "").strip()
    current["dhPubKey"] = identity_dh_pub_key
    current["dhAlgo"] = dh_algo
    current["invitePinnedPrekeyLookupHandle"] = prekey_lookup_handle
    current["invitePinnedRootFingerprint"] = str(payload.get("root_fingerprint", "") or "").strip().lower()
    current["invitePinnedRootManifestFingerprint"] = str(
        payload.get("root_manifest_fingerprint", "") or ""
    ).strip().lower()
    current["invitePinnedRootWitnessPolicyFingerprint"] = str(
        payload.get("root_witness_policy_fingerprint", "") or ""
    ).strip().lower()
    current["invitePinnedRootWitnessThreshold"] = int(payload.get("root_witness_threshold", 0) or 0)
    current["invitePinnedRootWitnessCount"] = int(payload.get("root_witness_count", 0) or 0)
    current["invitePinnedRootWitnessDomainCount"] = int(payload.get("root_witness_domain_count", 0) or 0)
    current["invitePinnedRootManifestGeneration"] = int(payload.get("root_manifest_generation", 0) or 0)
    current["invitePinnedRootRotationProven"] = bool(
        int(payload.get("root_manifest_generation", 0) or 0) <= 1 or payload.get("root_rotation_proven")
    )
    current["invitePinnedRootNodeId"] = str(payload.get("root_node_id", "") or "")
    current["invitePinnedRootPublicKey"] = str(payload.get("root_public_key", "") or "")
    current["invitePinnedRootPublicKeyAlgo"] = str(payload.get("root_public_key_algo", "Ed25519") or "Ed25519")
    current["invitePinnedIssuedAt"] = int(payload.get("issued_at", 0) or 0)
    current["invitePinnedExpiresAt"] = int(payload.get("expires_at", 0) or 0)
    current["remotePrekeyLookupMode"] = "invite_lookup_handle" if prekey_lookup_handle else ""
    current["remotePrekeyFingerprint"] = trust_fingerprint
    current["remotePrekeyObservedFingerprint"] = trust_fingerprint
    current["remotePrekeyRootFingerprint"] = str(payload.get("root_fingerprint", "") or "").strip().lower()
    current["remotePrekeyObservedRootFingerprint"] = str(payload.get("root_fingerprint", "") or "").strip().lower()
    current["remotePrekeyRootManifestFingerprint"] = str(
        payload.get("root_manifest_fingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyRootWitnessPolicyFingerprint"] = str(
        payload.get("root_witness_policy_fingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyRootWitnessThreshold"] = int(payload.get("root_witness_threshold", 0) or 0)
    current["remotePrekeyRootWitnessCount"] = int(payload.get("root_witness_count", 0) or 0)
    current["remotePrekeyRootWitnessDomainCount"] = int(payload.get("root_witness_domain_count", 0) or 0)
    current["remotePrekeyObservedRootManifestFingerprint"] = str(
        payload.get("root_manifest_fingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyObservedRootWitnessPolicyFingerprint"] = str(
        payload.get("root_witness_policy_fingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyObservedRootWitnessThreshold"] = int(payload.get("root_witness_threshold", 0) or 0)
    current["remotePrekeyObservedRootWitnessCount"] = int(payload.get("root_witness_count", 0) or 0)
    current["remotePrekeyObservedRootWitnessDomainCount"] = int(payload.get("root_witness_domain_count", 0) or 0)
    current["remotePrekeyRootManifestGeneration"] = int(payload.get("root_manifest_generation", 0) or 0)
    current["remotePrekeyObservedRootManifestGeneration"] = int(payload.get("root_manifest_generation", 0) or 0)
    current["remotePrekeyRootRotationProven"] = bool(
        int(payload.get("root_manifest_generation", 0) or 0) <= 1 or payload.get("root_rotation_proven")
    )
    current["remotePrekeyObservedRootRotationProven"] = bool(
        int(payload.get("root_manifest_generation", 0) or 0) <= 1 or payload.get("root_rotation_proven")
    )
    current["remotePrekeyRootNodeId"] = str(payload.get("root_node_id", "") or "")
    current["remotePrekeyRootPublicKey"] = str(payload.get("root_public_key", "") or "")
    current["remotePrekeyRootPublicKeyAlgo"] = str(payload.get("root_public_key_algo", "Ed25519") or "Ed25519")
    current["remotePrekeyRootPinnedAt"] = now
    current["remotePrekeyRootLastSeenAt"] = now
    current["remotePrekeyRootMismatch"] = False
    current["remotePrekeyPinnedAt"] = now
    current["remotePrekeyLastSeenAt"] = now
    current["remotePrekeyMismatch"] = False
    current["trust_level"] = trust_level
    if attested:
        current["invitePinnedTrustFingerprint"] = trust_fingerprint
        current["invitePinnedNodeId"] = peer_key
        current["invitePinnedPublicKey"] = str(payload.get("public_key", "") or "")
        current["invitePinnedPublicKeyAlgo"] = str(payload.get("public_key_algo", "Ed25519") or "Ed25519")
        current["invitePinnedDhPubKey"] = identity_dh_pub_key
        current["invitePinnedDhAlgo"] = dh_algo
        current["invitePinnedAt"] = now
    else:
        current["invitePinnedTrustFingerprint"] = ""
        current["invitePinnedNodeId"] = ""
        current["invitePinnedPublicKey"] = ""
        current["invitePinnedPublicKeyAlgo"] = ""
        current["invitePinnedDhPubKey"] = ""
        current["invitePinnedDhAlgo"] = ""
        current["invitePinnedRootFingerprint"] = ""
        current["invitePinnedRootManifestFingerprint"] = ""
        current["invitePinnedRootWitnessPolicyFingerprint"] = ""
        current["invitePinnedRootWitnessThreshold"] = 0
        current["invitePinnedRootWitnessCount"] = 0
        current["invitePinnedRootWitnessDomainCount"] = 0
        current["invitePinnedRootManifestGeneration"] = 0
        current["invitePinnedRootRotationProven"] = False
        current["invitePinnedRootNodeId"] = ""
        current["invitePinnedRootPublicKey"] = ""
        current["invitePinnedRootPublicKeyAlgo"] = ""
        current["invitePinnedAt"] = 0
    current["verified"] = False
    current["verify_inband"] = False
    current["verify_registry"] = False
    current["verify_mismatch"] = False
    current["verified_at"] = 0
    current["updated_at"] = now
    contacts[peer_key] = _normalize_contact(current)
    _write_contacts(contacts)
    return contacts[peer_key]


def delete_wormhole_dm_contact(peer_id: str) -> bool:
    peer_id = str(peer_id or "").strip()
    if not peer_id:
        return False
    contacts = _read_contacts()
    if peer_id not in contacts:
        return False
    del contacts[peer_id]
    _write_contacts(contacts)
    return True


def observe_remote_prekey_identity(
    peer_id: str,
    *,
    fingerprint: str,
    sequence: int = 0,
    signed_at: int = 0,
    transparency_head: str = "",
    transparency_size: int = 0,
    witness_count: int | None = None,
    witness_latest_at: int = 0,
    root_fingerprint: str = "",
    root_manifest_fingerprint: str = "",
    root_witness_policy_fingerprint: str = "",
    root_witness_threshold: int = 0,
    root_witness_count: int = 0,
    root_witness_domain_count: int = 0,
    root_manifest_generation: int = 0,
    root_rotation_proven: bool = False,
    root_node_id: str = "",
    root_public_key: str = "",
    root_public_key_algo: str = "Ed25519",
) -> dict[str, Any]:
    peer_key = str(peer_id or "").strip()
    candidate = str(fingerprint or "").strip().lower()
    if not peer_key:
        raise ValueError("peer_id required")
    if not candidate:
        raise ValueError("fingerprint required")

    contacts = _read_contacts()
    current = _normalize_contact(contacts.get(peer_key))
    now = int(time.time())
    pinned = str(current.get("remotePrekeyFingerprint", "") or "").strip().lower()
    invite_pinned = str(current.get("invitePinnedTrustFingerprint", "") or "").strip().lower()
    pinned_root = str(current.get("remotePrekeyRootFingerprint", "") or "").strip().lower()
    pinned_root_manifest = str(current.get("remotePrekeyRootManifestFingerprint", "") or "").strip().lower()
    invite_pinned_root = str(current.get("invitePinnedRootFingerprint", "") or "").strip().lower()
    invite_pinned_root_manifest = str(current.get("invitePinnedRootManifestFingerprint", "") or "").strip().lower()
    observed_root = str(root_fingerprint or "").strip().lower()
    observed_root_manifest = str(root_manifest_fingerprint or "").strip().lower()
    observed_root_witness_policy = str(root_witness_policy_fingerprint or "").strip().lower()
    observed_root_witness_threshold = int(root_witness_threshold or 0)
    observed_root_witness_count = int(root_witness_count or 0)
    observed_root_witness_domain_count = int(root_witness_domain_count or 0)
    observed_root_manifest_generation = int(root_manifest_generation or 0)
    observed_root_rotation_proven = bool(observed_root_manifest_generation <= 1 or root_rotation_proven)
    prior_root_mismatch = bool(current.get("remotePrekeyRootMismatch"))
    prior_sequence = int(current.get("remotePrekeySequence", 0) or 0)
    prior_transparency_head = str(current.get("remotePrekeyTransparencyHead", "") or "").strip().lower()
    prior_transparency_size = int(current.get("remotePrekeyTransparencySize", 0) or 0)
    prior_transparency_conflict = bool(current.get("remotePrekeyTransparencyConflict"))
    observed_transparency_head = str(transparency_head or "").strip().lower()
    observed_transparency_size = int(transparency_size or 0)
    observed_sequence = int(sequence or 0)
    observed_signed_at = int(signed_at or 0)
    transparency_conflict = False

    if observed_transparency_head:
        if prior_sequence > 0 and int(sequence or 0) > 0 and int(sequence or 0) < prior_sequence:
            transparency_conflict = True
        elif (
            prior_sequence > 0
            and int(sequence or 0) > 0
            and int(sequence or 0) == prior_sequence
            and prior_transparency_head
            and observed_transparency_head != prior_transparency_head
        ):
            transparency_conflict = True
        elif prior_transparency_size > 0 and observed_transparency_size > 0 and observed_transparency_size < prior_transparency_size:
            transparency_conflict = True

    current["remotePrekeyObservedFingerprint"] = candidate
    current["remotePrekeyLastSeenAt"] = now
    if observed_root:
        current["remotePrekeyObservedRootFingerprint"] = observed_root
        current["remotePrekeyObservedRootManifestFingerprint"] = observed_root_manifest
        current["remotePrekeyObservedRootWitnessPolicyFingerprint"] = observed_root_witness_policy
        current["remotePrekeyObservedRootWitnessThreshold"] = observed_root_witness_threshold
        current["remotePrekeyObservedRootWitnessCount"] = observed_root_witness_count
        current["remotePrekeyObservedRootWitnessDomainCount"] = observed_root_witness_domain_count
        current["remotePrekeyObservedRootManifestGeneration"] = observed_root_manifest_generation
        current["remotePrekeyObservedRootRotationProven"] = observed_root_rotation_proven
        current["remotePrekeyRootLastSeenAt"] = now
        current["remotePrekeyRootNodeId"] = str(root_node_id or "")
        current["remotePrekeyRootPublicKey"] = str(root_public_key or "")
        current["remotePrekeyRootPublicKeyAlgo"] = str(root_public_key_algo or "Ed25519")
    if not transparency_conflict:
        current["remotePrekeySequence"] = observed_sequence
        current["remotePrekeySignedAt"] = observed_signed_at
    if observed_transparency_head and not transparency_conflict:
        current["remotePrekeyTransparencyHead"] = observed_transparency_head
        current["remotePrekeyTransparencySize"] = observed_transparency_size
        current["remotePrekeyTransparencySeenAt"] = now
    current["remotePrekeyTransparencyConflict"] = transparency_conflict
    if witness_count is not None:
        current["witness_count"] = max(0, int(witness_count or 0))
        current["witness_checked_at"] = int(witness_latest_at or now)

    prior_trust = str(current.get("trust_level", "") or "").strip()
    trust_changed = False

    if not pinned and invite_pinned:
        current["remotePrekeyFingerprint"] = invite_pinned
        current["remotePrekeyPinnedAt"] = int(current.get("invitePinnedAt", 0) or now)
        pinned = invite_pinned
    if not pinned_root and invite_pinned_root:
        current["remotePrekeyRootFingerprint"] = invite_pinned_root
        current["remotePrekeyRootManifestFingerprint"] = invite_pinned_root_manifest
        current["remotePrekeyRootWitnessPolicyFingerprint"] = str(
            current.get("invitePinnedRootWitnessPolicyFingerprint", "") or ""
        ).strip().lower()
        current["remotePrekeyRootWitnessThreshold"] = int(current.get("invitePinnedRootWitnessThreshold", 0) or 0)
        current["remotePrekeyRootWitnessCount"] = int(current.get("invitePinnedRootWitnessCount", 0) or 0)
        current["remotePrekeyRootWitnessDomainCount"] = int(
            current.get("invitePinnedRootWitnessDomainCount", 0) or 0
        )
        current["remotePrekeyRootManifestGeneration"] = int(current.get("invitePinnedRootManifestGeneration", 0) or 0)
        current["remotePrekeyRootRotationProven"] = bool(
            int(current.get("invitePinnedRootManifestGeneration", 0) or 0) <= 1
            or current.get("invitePinnedRootRotationProven")
        )
        current["remotePrekeyRootPinnedAt"] = int(current.get("invitePinnedAt", 0) or now)
        current["remotePrekeyRootNodeId"] = str(current.get("invitePinnedRootNodeId", "") or "")
        current["remotePrekeyRootPublicKey"] = str(current.get("invitePinnedRootPublicKey", "") or "")
        current["remotePrekeyRootPublicKeyAlgo"] = str(current.get("invitePinnedRootPublicKeyAlgo", "") or "")
        pinned_root = invite_pinned_root
        pinned_root_manifest = invite_pinned_root_manifest

    if not pinned:
        # First-seen fingerprint — TOFU pin.
        current["remotePrekeyFingerprint"] = candidate
        current["remotePrekeyPinnedAt"] = now
        current["remotePrekeyMismatch"] = False
        if observed_root:
            current["remotePrekeyRootFingerprint"] = observed_root
            current["remotePrekeyRootManifestFingerprint"] = observed_root_manifest
            current["remotePrekeyRootWitnessPolicyFingerprint"] = observed_root_witness_policy
            current["remotePrekeyRootWitnessThreshold"] = observed_root_witness_threshold
            current["remotePrekeyRootWitnessCount"] = observed_root_witness_count
            current["remotePrekeyRootWitnessDomainCount"] = observed_root_witness_domain_count
            current["remotePrekeyRootManifestGeneration"] = observed_root_manifest_generation
            current["remotePrekeyRootRotationProven"] = observed_root_rotation_proven
            current["remotePrekeyRootPinnedAt"] = now
        current["remotePrekeyRootMismatch"] = False
        current["trust_level"] = "tofu_pinned"
    elif pinned == candidate and (not pinned_root or not observed_root or pinned_root == observed_root):
        # Same fingerprint — preserve existing trust level (tofu or sas_verified).
        current["remotePrekeyMismatch"] = bool(transparency_conflict)
        current["remotePrekeyRootMismatch"] = False
        if observed_root:
            current["remotePrekeyRootFingerprint"] = observed_root
            current["remotePrekeyRootManifestFingerprint"] = observed_root_manifest
            current["remotePrekeyRootWitnessPolicyFingerprint"] = observed_root_witness_policy
            current["remotePrekeyRootWitnessThreshold"] = observed_root_witness_threshold
            current["remotePrekeyRootWitnessCount"] = observed_root_witness_count
            current["remotePrekeyRootWitnessDomainCount"] = observed_root_witness_domain_count
            current["remotePrekeyRootManifestGeneration"] = observed_root_manifest_generation
            current["remotePrekeyRootRotationProven"] = observed_root_rotation_proven
        if transparency_conflict:
            trust_changed = True
            if prior_trust in ("invite_pinned", "sas_verified"):
                current["trust_level"] = "continuity_broken"
            else:
                current["trust_level"] = "mismatch"
        elif prior_trust in ("mismatch", "continuity_broken"):
            current["remotePrekeyMismatch"] = True
            current["remotePrekeyRootMismatch"] = prior_root_mismatch
            current["remotePrekeyTransparencyConflict"] = prior_transparency_conflict
            current["trust_level"] = prior_trust
        elif prior_trust not in ("tofu_pinned", "invite_pinned", "sas_verified"):
            current["trust_level"] = "invite_pinned" if invite_pinned and pinned == invite_pinned else "tofu_pinned"
    else:
        # Changed fingerprint — severity depends on prior verification.
        trust_changed = True
        root_changed = bool(observed_root and pinned_root and pinned_root != observed_root)
        current["remotePrekeyMismatch"] = pinned != candidate
        current["remotePrekeyRootMismatch"] = root_changed
        if observed_root and not pinned_root:
            current["remotePrekeyRootFingerprint"] = observed_root
            current["remotePrekeyRootManifestFingerprint"] = observed_root_manifest
            current["remotePrekeyRootWitnessPolicyFingerprint"] = observed_root_witness_policy
            current["remotePrekeyRootWitnessThreshold"] = observed_root_witness_threshold
            current["remotePrekeyRootWitnessCount"] = observed_root_witness_count
            current["remotePrekeyRootWitnessDomainCount"] = observed_root_witness_domain_count
            current["remotePrekeyRootManifestGeneration"] = observed_root_manifest_generation
            current["remotePrekeyRootRotationProven"] = observed_root_rotation_proven
            current["remotePrekeyRootPinnedAt"] = now
            current["remotePrekeyRootMismatch"] = False
            root_changed = False
        if prior_trust in ("invite_pinned", "sas_verified") or bool(invite_pinned_root):
            current["trust_level"] = "continuity_broken"
        else:
            current["trust_level"] = "mismatch"

    current["updated_at"] = int(time.time())
    contacts[peer_key] = _normalize_contact(current)
    _write_contacts(contacts)
    return {
        "ok": True,
        "peer_id": peer_key,
        "trust_changed": trust_changed,
        "trust_level": contacts[peer_key]["trust_level"],
        "contact": contacts[peer_key],
    }


def confirm_sas_verification(
    peer_id: str,
    sas_phrase: str,
    *,
    peer_ref: str = "",
    words: int = 8,
) -> dict[str, Any]:
    """Record successful SAS verification for a contact.

    Sets trust_level to sas_verified and updates legacy compat fields.
    The contact must already be in a verifiable state (tofu_pinned,
    invite_pinned, or sas_verified for idempotence). Rejects mismatch and
    continuity_broken to prevent silent re-pin of a changed fingerprint.
    """
    peer_key = str(peer_id or "").strip()
    if not peer_key:
        raise ValueError("peer_id required")
    contacts = _read_contacts()
    current = _normalize_contact(contacts.get(peer_key))
    if not str(current.get("remotePrekeyFingerprint", "") or "").strip():
        return {"ok": False, "detail": "no pinned fingerprint to verify"}

    current_trust = str(current.get("trust_level", "") or "").strip()
    if current_trust in ("mismatch", "continuity_broken"):
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": f"cannot verify: trust_level is {current_trust} — acknowledge the changed fingerprint first",
        }

    normalized_phrase = _normalize_sas_phrase(sas_phrase)
    if not normalized_phrase:
        return {
            "ok": False,
            "trust_level": current_trust or "unpinned",
            "detail": "sas proof required",
        }

    expected = _derive_expected_contact_sas_phrase(
        peer_key,
        peer_ref=str(peer_ref or ""),
        words=max(2, min(int(words or 8), 16)),
    )
    if not bool(expected.get("ok")):
        return {
            "ok": False,
            "trust_level": current_trust or "unpinned",
            "detail": str(expected.get("detail", "") or "sas phrase unavailable"),
        }
    expected_phrase = _normalize_sas_phrase(str(expected.get("phrase", "") or ""))
    if normalized_phrase != expected_phrase:
        return {
            "ok": False,
            "trust_level": current_trust or "unpinned",
            "detail": "sas phrase mismatch",
        }

    now = int(time.time())
    current["trust_level"] = "sas_verified"
    current["verified"] = True
    current["verify_inband"] = True
    current["verified_at"] = now
    current["remotePrekeyMismatch"] = False
    current["remotePrekeyRootMismatch"] = False
    current["verify_mismatch"] = False
    current["updated_at"] = now
    contacts[peer_key] = _normalize_contact(current)
    _write_contacts(contacts)
    try:
        from services.mesh.mesh_wormhole_dead_drop import (
            AliasRotationReason,
            maybe_prepare_pairwise_dm_alias_rotation,
        )

        maybe_prepare_pairwise_dm_alias_rotation(
            peer_id=peer_key,
            peer_dh_pub=str(current.get("dhPubKey") or current.get("invitePinnedDhPubKey") or ""),
            reason=AliasRotationReason.CONTACT_VERIFICATION_COMPLETED.value,
        )
    except Exception:
        pass
    return {
        "ok": True,
        "peer_id": peer_key,
        "trust_level": "sas_verified",
        "contact": contacts[peer_key],
    }


def recover_verified_root_continuity(
    peer_id: str,
    sas_phrase: str,
    *,
    peer_ref: str = "",
    words: int = 8,
) -> dict[str, Any]:
    """Explicitly adopt an observed stable-root change after SAS verification.

    This is only valid for contacts in continuity_broken due to root mismatch.
    It fetches the current bundle through the existing lookup path, verifies the
    currently advertised root attestation still matches the observed mismatch,
    then promotes the contact directly to sas_verified. Old invite-pinned trust
    anchors are cleared because continuity is now rooted in SAS, not the prior
    invite chain.
    """
    peer_key = str(peer_id or "").strip()
    if not peer_key:
        raise ValueError("peer_id required")
    contacts = _read_contacts()
    current = _normalize_contact(contacts.get(peer_key))
    current_trust = str(current.get("trust_level", "") or "").strip()
    if current_trust != "continuity_broken":
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": f"root recovery only valid for continuity_broken, current is {current_trust}",
        }
    if not bool(current.get("remotePrekeyRootMismatch")):
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": "root recovery requires an observed stable root mismatch",
        }

    observed = str(current.get("remotePrekeyObservedFingerprint", "") or "").strip().lower()
    observed_root = str(current.get("remotePrekeyObservedRootFingerprint", "") or "").strip().lower()
    if not observed or not observed_root:
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": "no observed stable-root candidate to recover",
        }

    from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle, verify_bundle_root_attestation

    lookup_handle = str(current.get("invitePinnedPrekeyLookupHandle", "") or "").strip()
    fetched = fetch_dm_prekey_bundle(agent_id="" if lookup_handle else peer_key, lookup_token=lookup_handle)
    if not fetched.get("ok"):
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": str(fetched.get("detail", "") or "current prekey bundle unavailable for root recovery"),
        }

    current_bundle_root = verify_bundle_root_attestation(
        {
            "agent_id": str(fetched.get("agent_id", peer_key) or peer_key),
            "bundle": dict(fetched.get("bundle") or {}),
            "public_key": str(fetched.get("public_key", "") or ""),
            "public_key_algo": str(fetched.get("public_key_algo", "Ed25519") or "Ed25519"),
            "protocol_version": str(fetched.get("protocol_version", "") or ""),
        }
    )
    if not current_bundle_root.get("ok"):
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": str(current_bundle_root.get("detail", "") or "root attestation invalid"),
        }

    fetched_fingerprint = str(fetched.get("trust_fingerprint", "") or "").strip().lower()
    fetched_root = str(current_bundle_root.get("root_fingerprint", "") or "").strip().lower()
    if fetched_fingerprint != observed or fetched_root != observed_root:
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": "observed root candidate changed again; refresh and compare SAS again before recovery",
        }

    normalized_phrase = _normalize_sas_phrase(sas_phrase)
    if not normalized_phrase:
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": "sas proof required",
        }
    expected = _derive_expected_contact_sas_phrase(
        peer_key,
        peer_ref=str(peer_ref or ""),
        words=max(2, min(int(words or 8), 16)),
        peer_dh_pub_override=str(fetched.get("identity_dh_pub_key", "") or ""),
    )
    if not bool(expected.get("ok")):
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": str(expected.get("detail", "") or "sas phrase unavailable"),
        }
    expected_phrase = _normalize_sas_phrase(str(expected.get("phrase", "") or ""))
    if normalized_phrase != expected_phrase:
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": "sas phrase mismatch",
        }

    now = int(time.time())
    current["dhPubKey"] = str(fetched.get("identity_dh_pub_key", "") or "")
    current["dhAlgo"] = str(fetched.get("dh_algo", "X25519") or "X25519")
    current["remotePrekeyFingerprint"] = observed
    current["remotePrekeyPinnedAt"] = now
    current["remotePrekeyLastSeenAt"] = now
    current["remotePrekeyMismatch"] = False
    current["remotePrekeyRootFingerprint"] = observed_root
    current["remotePrekeyObservedRootManifestFingerprint"] = str(
        current_bundle_root.get("root_manifest_fingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyRootManifestFingerprint"] = str(
        current_bundle_root.get("root_manifest_fingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyObservedRootWitnessPolicyFingerprint"] = str(
        current_bundle_root.get("root_witness_policy_fingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyRootWitnessPolicyFingerprint"] = str(
        current_bundle_root.get("root_witness_policy_fingerprint", "") or ""
    ).strip().lower()
    current["remotePrekeyObservedRootWitnessThreshold"] = int(
        current_bundle_root.get("root_witness_threshold", 0) or 0
    )
    current["remotePrekeyRootWitnessThreshold"] = int(current_bundle_root.get("root_witness_threshold", 0) or 0)
    current["remotePrekeyObservedRootWitnessCount"] = int(
        current_bundle_root.get("root_witness_count", 0) or 0
    )
    current["remotePrekeyRootWitnessCount"] = int(current_bundle_root.get("root_witness_count", 0) or 0)
    current["remotePrekeyObservedRootWitnessDomainCount"] = int(
        current_bundle_root.get("root_witness_domain_count", 0) or 0
    )
    current["remotePrekeyRootWitnessDomainCount"] = int(
        current_bundle_root.get("root_witness_domain_count", 0) or 0
    )
    current["remotePrekeyObservedRootManifestGeneration"] = int(
        current_bundle_root.get("root_manifest_generation", 0) or 0
    )
    current["remotePrekeyRootManifestGeneration"] = int(current_bundle_root.get("root_manifest_generation", 0) or 0)
    current["remotePrekeyObservedRootRotationProven"] = bool(
        int(current_bundle_root.get("root_manifest_generation", 0) or 0) <= 1
        or current_bundle_root.get("root_rotation_proven")
    )
    current["remotePrekeyRootRotationProven"] = bool(
        int(current_bundle_root.get("root_manifest_generation", 0) or 0) <= 1
        or current_bundle_root.get("root_rotation_proven")
    )
    current["remotePrekeyRootPinnedAt"] = now
    current["remotePrekeyRootLastSeenAt"] = now
    current["remotePrekeyRootNodeId"] = str(current_bundle_root.get("root_node_id", "") or "")
    current["remotePrekeyRootPublicKey"] = str(current_bundle_root.get("root_public_key", "") or "")
    current["remotePrekeyRootPublicKeyAlgo"] = str(
        current_bundle_root.get("root_public_key_algo", "Ed25519") or "Ed25519"
    )
    current["remotePrekeyRootMismatch"] = False
    current["invitePinnedTrustFingerprint"] = ""
    current["invitePinnedNodeId"] = ""
    current["invitePinnedPublicKey"] = ""
    current["invitePinnedPublicKeyAlgo"] = ""
    current["invitePinnedDhPubKey"] = ""
    current["invitePinnedDhAlgo"] = ""
    current["invitePinnedRootFingerprint"] = ""
    current["invitePinnedRootManifestFingerprint"] = ""
    current["invitePinnedRootWitnessPolicyFingerprint"] = ""
    current["invitePinnedRootWitnessThreshold"] = 0
    current["invitePinnedRootWitnessCount"] = 0
    current["invitePinnedRootWitnessDomainCount"] = 0
    current["invitePinnedRootManifestGeneration"] = 0
    current["invitePinnedRootRotationProven"] = False
    current["invitePinnedRootNodeId"] = ""
    current["invitePinnedRootPublicKey"] = ""
    current["invitePinnedRootPublicKeyAlgo"] = ""
    current["invitePinnedIssuedAt"] = 0
    current["invitePinnedExpiresAt"] = 0
    current["invitePinnedAt"] = 0
    current["trust_level"] = "sas_verified"
    current["verified"] = True
    current["verify_inband"] = True
    current["verify_registry"] = False
    current["verify_mismatch"] = False
    current["verified_at"] = now
    current["updated_at"] = now
    contacts[peer_key] = _normalize_contact(current)
    _write_contacts(contacts)
    try:
        from services.mesh.mesh_wormhole_dead_drop import (
            AliasRotationReason,
            maybe_prepare_pairwise_dm_alias_rotation,
        )

        maybe_prepare_pairwise_dm_alias_rotation(
            peer_id=peer_key,
            peer_dh_pub=str(current.get("dhPubKey") or current.get("invitePinnedDhPubKey") or ""),
            reason=AliasRotationReason.CONTACT_VERIFICATION_COMPLETED.value,
        )
    except Exception:
        pass
    return {
        "ok": True,
        "peer_id": peer_key,
        "trust_level": "sas_verified",
        "detail": "stable root continuity recovered via SAS verification",
        "contact": contacts[peer_key],
    }


def acknowledge_changed_fingerprint(peer_id: str) -> dict[str, Any]:
    """Explicitly accept a changed observed fingerprint for a contact.

    Valid only when trust_level is mismatch or continuity_broken and an
    observed fingerprint exists.  Re-pins the current observed fingerprint,
    clears mismatch flags, clears legacy verified state, and sets
    trust_level to tofu_pinned.  This is NOT sas_verified — the operator
    must re-confirm SAS separately.
    """
    peer_key = str(peer_id or "").strip()
    if not peer_key:
        raise ValueError("peer_id required")
    contacts = _read_contacts()
    current = _normalize_contact(contacts.get(peer_key))

    current_trust = str(current.get("trust_level", "") or "").strip()
    if current_trust not in ("mismatch", "continuity_broken"):
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": f"acknowledgment only valid for mismatch or continuity_broken, current is {current_trust}",
        }

    observed = str(current.get("remotePrekeyObservedFingerprint", "") or "").strip().lower()
    if not observed:
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": "no observed fingerprint to re-pin",
        }
    invite_pinned = str(current.get("invitePinnedTrustFingerprint", "") or "").strip().lower()
    if invite_pinned and observed != invite_pinned:
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": "invite-pinned contact requires invite replacement before acknowledging changed fingerprint",
        }
    observed_root = str(current.get("remotePrekeyObservedRootFingerprint", "") or "").strip().lower()
    observed_root_manifest = str(current.get("remotePrekeyObservedRootManifestFingerprint", "") or "").strip().lower()
    invite_pinned_root = str(current.get("invitePinnedRootFingerprint", "") or "").strip().lower()
    if bool(current.get("remotePrekeyRootMismatch")):
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": "stable root changed; recover root continuity with SAS or replace the signed invite before trusting this contact again",
        }
    if invite_pinned_root and observed_root and observed_root != invite_pinned_root:
        return {
            "ok": False,
            "trust_level": current_trust,
            "detail": "invite-pinned contact requires invite replacement before acknowledging changed stable root",
        }

    now = int(time.time())
    current["remotePrekeyFingerprint"] = observed
    current["remotePrekeyPinnedAt"] = now
    current["remotePrekeyMismatch"] = False
    if observed_root:
        current["remotePrekeyRootFingerprint"] = observed_root
        current["remotePrekeyRootManifestFingerprint"] = observed_root_manifest
        current["remotePrekeyObservedRootManifestFingerprint"] = observed_root_manifest
        current["remotePrekeyRootWitnessPolicyFingerprint"] = str(
            current.get("remotePrekeyObservedRootWitnessPolicyFingerprint", "") or ""
        ).strip().lower()
        current["remotePrekeyRootWitnessThreshold"] = int(
            current.get("remotePrekeyObservedRootWitnessThreshold", 0) or 0
        )
        current["remotePrekeyRootWitnessCount"] = int(
            current.get("remotePrekeyObservedRootWitnessCount", 0) or 0
        )
        current["remotePrekeyRootWitnessDomainCount"] = int(
            current.get("remotePrekeyObservedRootWitnessDomainCount", 0) or 0
        )
        current["remotePrekeyRootManifestGeneration"] = int(
            current.get("remotePrekeyObservedRootManifestGeneration", 0) or 0
        )
        current["remotePrekeyRootRotationProven"] = bool(
            int(current.get("remotePrekeyObservedRootManifestGeneration", 0) or 0) <= 1
            or current.get("remotePrekeyObservedRootRotationProven")
        )
        current["remotePrekeyRootPinnedAt"] = now
    current["remotePrekeyRootMismatch"] = False
    current["trust_level"] = "tofu_pinned"
    current["verified"] = False
    current["verify_inband"] = False
    current["verify_mismatch"] = False
    current["verified_at"] = 0
    current["updated_at"] = now
    contacts[peer_key] = _normalize_contact(current)
    _write_contacts(contacts)
    return {
        "ok": True,
        "peer_id": peer_key,
        "trust_level": "tofu_pinned",
        "contact": contacts[peer_key],
    }
