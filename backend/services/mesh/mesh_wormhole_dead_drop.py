"""Wormhole-owned dead-drop token derivation helpers.

These helpers move mailbox token derivation off the browser when Wormhole is the
secure trust anchor. The browser supplies only peer identifiers and peer DH
public keys; Wormhole derives the shared secret locally and returns mailbox
tokens for the current and previous epochs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from enum import Enum
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from services.mesh.mesh_metrics import increment as metrics_inc
from services.mesh.mesh_protocol import PROTOCOL_VERSION
from services.mesh.mesh_secure_storage import read_domain_json, write_domain_json
from services.mesh.mesh_secure_storage import _load_master_key
from services.mesh.mesh_wormhole_identity import bootstrap_wormhole_identity, read_wormhole_identity
from services.mesh.mesh_wormhole_contacts import (
    accepted_contact_shared_aliases,
    list_wormhole_dm_contacts,
    upsert_wormhole_dm_contact_internal,
)
from services.wormhole_settings import read_wormhole_settings

DEFAULT_DM_EPOCH_SECONDS = 6 * 60 * 60
HIGH_PRIVACY_DM_EPOCH_SECONDS = 2 * 60 * 60
SAS_PREFIXES = [
    "amber",
    "apex",
    "atlas",
    "birch",
    "cinder",
    "cobalt",
    "delta",
    "ember",
    "falcon",
    "frost",
    "glint",
    "harbor",
    "juno",
    "kepler",
    "lumen",
    "nova",
]
SAS_SUFFIXES = [
    "anchor",
    "arrow",
    "bloom",
    "cabin",
    "cedar",
    "cipher",
    "comet",
    "field",
    "grove",
    "harvest",
    "meadow",
    "mesa",
    "orbit",
    "signal",
    "summit",
    "thunder",
]
SAS_WORDS = [f"{prefix}-{suffix}" for prefix in SAS_PREFIXES for suffix in SAS_SUFFIXES]
DM_CONSENT_PREFIX = "DM_CONSENT:"
PAIRWISE_ALIAS_PREFIX = "dmx_"
# Legacy fixed value retained for tests that assert the previous 30-day
# default. Runtime rotation decisions use
# ``pairwise_alias_rotate_after_ms()`` (see mesh_rollout_flags) which
# defaults to 7 days per hardening Rec #3 and honors
# MESH_PAIRWISE_ALIAS_ROTATE_AFTER_MS.
PAIRWISE_ALIAS_ROTATE_AFTER_MS = 30 * 24 * 60 * 60 * 1000
PAIRWISE_ALIAS_GRACE_DEFAULT_MS = 14 * 24 * 60 * 60 * 1000
PAIRWISE_ALIAS_GRACE_MIN_MS = 5_000
PAIRWISE_ALIAS_GRACE_MAX_MS = PAIRWISE_ALIAS_GRACE_DEFAULT_MS
PAIRWISE_ALIAS_OFFLINE_HARD_CAP_MS = 90 * 24 * 60 * 60 * 1000
PAIRWISE_ALIAS_STATE_DOMAIN = "wormhole_alias_rotation"
PAIRWISE_ALIAS_STATE_FILE = "wormhole_alias_rotation_state.json"
PAIRWISE_ALIAS_PENDING_COMMIT_TTL_MS = 24 * 60 * 60 * 1000
PAIRWISE_ALIAS_PAYLOAD_KIND = "sb_dm_alias_payload_v1"
PAIRWISE_ALIAS_UPDATE_KIND = "sb_dm_alias_update_v1"
_PENDING_ALIAS_COMMIT_LOCK = threading.Lock()
_PENDING_ALIAS_COMMITS: dict[str, dict[str, Any]] = {}


class AliasRotationReason(str, Enum):
    SCHEDULED_30D = "scheduled_30d"
    CONTACT_VERIFICATION_COMPLETED = "contact_verification_completed"
    GATE_JOIN = "gate_join"
    SUSPECTED_COMPROMISE = "suspected_compromise"
    MANUAL = "manual"


_ROUTINE_ALIAS_ROTATION_REASONS = frozenset(
    {
        AliasRotationReason.SCHEDULED_30D,
        AliasRotationReason.CONTACT_VERIFICATION_COMPLETED,
        AliasRotationReason.GATE_JOIN,
        AliasRotationReason.MANUAL,
    }
)


def _normalize_rotation_reason(reason: AliasRotationReason | str | None) -> AliasRotationReason:
    try:
        return AliasRotationReason(str(reason or AliasRotationReason.MANUAL.value))
    except Exception as exc:
        raise ValueError("alias rotation reason invalid") from exc


def _rotation_state_default() -> dict[str, Any]:
    return {
        "known_gate_ids": [],
        "gate_join_seq": 0,
    }


def _canonical_alias_payload(payload: dict[str, Any]) -> str:
    return json.dumps(dict(payload or {}), sort_keys=True, separators=(",", ":"))


def _pending_alias_commit_key(*, peer_id: str, payload_format: str, ciphertext: str) -> str:
    message = "|".join(
        [
            str(peer_id or "").strip(),
            str(payload_format or "").strip().lower(),
            str(ciphertext or ""),
        ]
    )
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def _cleanup_pending_alias_commits(now_ms: int | None = None) -> None:
    current_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    expired: list[str] = []
    for key, payload in list(_PENDING_ALIAS_COMMITS.items()):
        created_at = int(dict(payload or {}).get("created_at_ms", 0) or 0)
        if created_at <= 0 or current_ms - created_at > PAIRWISE_ALIAS_PENDING_COMMIT_TTL_MS:
            expired.append(key)
    for key in expired:
        _PENDING_ALIAS_COMMITS.pop(key, None)


def _register_pending_alias_commit(
    *,
    peer_id: str,
    payload_format: str,
    ciphertext: str,
    updates: dict[str, Any],
) -> None:
    if not str(peer_id or "").strip() or not str(ciphertext or "").strip():
        return
    with _PENDING_ALIAS_COMMIT_LOCK:
        _cleanup_pending_alias_commits()
        _PENDING_ALIAS_COMMITS[_pending_alias_commit_key(
            peer_id=peer_id,
            payload_format=payload_format,
            ciphertext=ciphertext,
        )] = {
            "created_at_ms": int(time.time() * 1000),
            "updates": dict(updates or {}),
        }


def _consume_pending_alias_commit(
    *,
    peer_id: str,
    payload_format: str,
    ciphertext: str,
) -> dict[str, Any] | None:
    if not str(peer_id or "").strip() or not str(ciphertext or "").strip():
        return None
    with _PENDING_ALIAS_COMMIT_LOCK:
        _cleanup_pending_alias_commits()
        payload = _PENDING_ALIAS_COMMITS.pop(
            _pending_alias_commit_key(
                peer_id=peer_id,
                payload_format=payload_format,
                ciphertext=ciphertext,
            ),
            None,
        )
    if not isinstance(payload, dict):
        return None
    updates = dict(payload.get("updates") or {})
    return updates or None


def _read_rotation_state() -> dict[str, Any]:
    raw = read_domain_json(PAIRWISE_ALIAS_STATE_DOMAIN, PAIRWISE_ALIAS_STATE_FILE, _rotation_state_default)
    state = _rotation_state_default()
    if isinstance(raw, dict):
        state.update(raw)
    state["known_gate_ids"] = [
        str(item or "").strip().lower()
        for item in list(state.get("known_gate_ids") or [])
        if str(item or "").strip()
    ]
    state["gate_join_seq"] = int(state.get("gate_join_seq", 0) or 0)
    return state


def _write_rotation_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = _rotation_state_default()
    payload.update(dict(state or {}))
    payload["known_gate_ids"] = [
        str(item or "").strip().lower()
        for item in list(payload.get("known_gate_ids") or [])
        if str(item or "").strip()
    ]
    payload["gate_join_seq"] = int(payload.get("gate_join_seq", 0) or 0)
    write_domain_json(PAIRWISE_ALIAS_STATE_DOMAIN, PAIRWISE_ALIAS_STATE_FILE, payload)
    return payload


def _observed_gate_join_seq() -> int:
    state = _read_rotation_state()
    try:
        from services.mesh.mesh_reputation import gate_manager

        current_gate_ids = sorted(
            str(gate_id or "").strip().lower()
            for gate_id in dict(getattr(gate_manager, "gates", {}) or {}).keys()
            if str(gate_id or "").strip()
        )
    except Exception:
        current_gate_ids = list(state.get("known_gate_ids") or [])
    previous_gate_ids = {
        str(item or "").strip().lower()
        for item in list(state.get("known_gate_ids") or [])
        if str(item or "").strip()
    }
    joined = [gate_id for gate_id in current_gate_ids if gate_id not in previous_gate_ids]
    if joined:
        state["gate_join_seq"] = int(state.get("gate_join_seq", 0) or 0) + 1
    state["known_gate_ids"] = current_gate_ids
    return int(_write_rotation_state(state).get("gate_join_seq", 0) or 0)


def _contact_alias_counter(contact: dict[str, Any], alias: str) -> int:
    alias_key = str(alias or "").strip()
    if not alias_key:
        return 0
    if alias_key == str(contact.get("sharedAlias", "") or "").strip():
        return int(contact.get("sharedAliasCounter", 0) or 0)
    if alias_key == str(contact.get("pendingSharedAlias", "") or "").strip():
        return int(contact.get("pendingSharedAliasCounter", 0) or 0)
    if alias_key == str(contact.get("acceptedPreviousAlias", "") or "").strip():
        return int(contact.get("acceptedPreviousAliasCounter", 0) or 0)
    return 0


def _contact_alias_public_binding(contact: dict[str, Any], alias: str) -> tuple[str, str]:
    alias_key = str(alias or "").strip()
    if not alias_key:
        return "", "Ed25519"
    if alias_key == str(contact.get("sharedAlias", "") or "").strip():
        return (
            str(contact.get("sharedAliasPublicKey", "") or ""),
            str(contact.get("sharedAliasPublicKeyAlgo", "Ed25519") or "Ed25519"),
        )
    if alias_key == str(contact.get("pendingSharedAlias", "") or "").strip():
        return (
            str(contact.get("pendingSharedAliasPublicKey", "") or ""),
            str(contact.get("pendingSharedAliasPublicKeyAlgo", "Ed25519") or "Ed25519"),
        )
    if alias_key == str(contact.get("acceptedPreviousAlias", "") or "").strip():
        return (
            str(contact.get("acceptedPreviousAliasPublicKey", "") or ""),
            str(contact.get("acceptedPreviousAliasPublicKeyAlgo", "Ed25519") or "Ed25519"),
        )
    return "", "Ed25519"


def _migrate_local_contact_alias_bindings(peer_id: str, contact: dict[str, Any]) -> dict[str, Any]:
    peer_key = str(peer_id or "").strip()
    current = dict(contact or {})
    if not peer_key:
        return current
    updates: dict[str, Any] = {}
    binding_fields = (
        ("sharedAlias", "sharedAliasCounter", "sharedAliasPublicKey", "sharedAliasPublicKeyAlgo"),
        ("pendingSharedAlias", "pendingSharedAliasCounter", "pendingSharedAliasPublicKey", "pendingSharedAliasPublicKeyAlgo"),
        (
            "acceptedPreviousAlias",
            "acceptedPreviousAliasCounter",
            "acceptedPreviousAliasPublicKey",
            "acceptedPreviousAliasPublicKeyAlgo",
        ),
    )
    for alias_field, counter_field, public_key_field, public_key_algo_field in binding_fields:
        alias = str(current.get(alias_field, "") or "").strip()
        if not alias or str(current.get(public_key_field, "") or "").strip():
            continue
        binding = _alias_public_key(alias, int(current.get(counter_field, 0) or 0))
        if not binding.get("ok"):
            continue
        updates[public_key_field] = str(binding.get("public_key", "") or "")
        updates[public_key_algo_field] = str(binding.get("public_key_algo", "Ed25519") or "Ed25519")
    if not updates:
        return current
    return upsert_wormhole_dm_contact_internal(peer_key, updates)


def _contact_alias_updates_blocked(contact: dict[str, Any]) -> bool:
    if bool(contact.get("blocked")):
        return True
    trust_level = str(contact.get("trust_level", "") or "").strip().lower()
    return trust_level in {"mismatch", "continuity_broken"}


def _build_pairwise_alias_payload(plaintext: str, alias_update: dict[str, Any] | None = None) -> str:
    if not isinstance(alias_update, dict) or not alias_update:
        return str(plaintext or "")
    return json.dumps(
        {
            "kind": PAIRWISE_ALIAS_PAYLOAD_KIND,
            "plaintext": str(plaintext or ""),
            "alias_update": dict(alias_update or {}),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _unwrap_pairwise_alias_payload(plaintext: str) -> tuple[str, dict[str, Any] | None]:
    raw_text = str(plaintext or "")
    if not raw_text.startswith("{"):
        return raw_text, None
    try:
        payload = json.loads(raw_text)
    except Exception:
        return raw_text, None
    if not isinstance(payload, dict) or str(payload.get("kind", "") or "") != PAIRWISE_ALIAS_PAYLOAD_KIND:
        return raw_text, None
    return str(payload.get("plaintext", "") or ""), dict(payload.get("alias_update") or {})


def _alias_public_key(alias: str, counter: int) -> dict[str, Any]:
    from services.mesh.mesh_wormhole_persona import get_dm_alias_public_key

    return get_dm_alias_public_key(alias, counter=counter)


def _sign_alias_binding(alias: str, payload: str, *, counter: int) -> dict[str, Any]:
    from services.mesh.mesh_wormhole_persona import sign_dm_alias_blob

    return sign_dm_alias_blob(alias, payload.encode("utf-8"), counter=counter)


def _sign_root_alias_binding(payload: str) -> dict[str, Any]:
    from services.mesh.mesh_wormhole_persona import (
        bootstrap_wormhole_persona_state,
        read_wormhole_persona_state,
    )

    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    identity = dict(state.get("root_identity") or {})
    try:
        signing_priv = ed25519.Ed25519PrivateKey.from_private_bytes(
            _unb64(str(identity.get("private_key", "") or ""))
        )
    except Exception:
        return {"ok": False, "detail": "root identity unavailable"}
    signature = signing_priv.sign(str(payload or "").encode("utf-8")).hex()
    return {
        "node_id": str(identity.get("node_id", "") or ""),
        "public_key": str(identity.get("public_key", "") or ""),
        "public_key_algo": str(identity.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": PROTOCOL_VERSION,
        "signature": signature,
        "message": str(payload or ""),
        "identity_scope": "root",
    }


def _verify_alias_binding_signature(
    alias: str,
    payload: str,
    signature: str,
    *,
    counter: int,
    public_key: str,
    public_key_algo: str,
) -> bool:
    if str(public_key_algo or "Ed25519").strip().upper() not in {"ED25519", "EDDSA"}:
        return False
    try:
        signing_pub = ed25519.Ed25519PublicKey.from_public_bytes(_unb64(public_key))
        signing_pub.verify(
            bytes.fromhex(str(signature or "")),
            (
                f"dm-mls-binding|{str(alias or '').strip().lower()}|r{max(0, int(counter or 0))}|".encode("utf-8")
                + payload.encode("utf-8")
            ),
        )
        return True
    except Exception:
        return False


def _verify_root_binding_signature(
    payload: str,
    *,
    signature: str,
    public_key: str,
    public_key_algo: str,
) -> bool:
    if str(public_key_algo or "Ed25519").strip().upper() not in {"ED25519", "EDDSA"}:
        return False
    try:
        signing_pub = ed25519.Ed25519PublicKey.from_public_bytes(_unb64(public_key))
        signing_pub.verify(bytes.fromhex(str(signature or "")), payload.encode("utf-8"))
        return True
    except Exception:
        return False

def _unb64(data: str | bytes | None) -> bytes:
    if not data:
        return b""
    if isinstance(data, bytes):
        return base64.b64decode(data)
    return base64.b64decode(data.encode("ascii"))


def build_contact_offer(*, dh_pub_key: str, dh_algo: str, geo_hint: str = "") -> str:
    return (
        f"{DM_CONSENT_PREFIX}"
        + json.dumps(
            {
                "kind": "contact_offer",
                "dh_pub_key": str(dh_pub_key or ""),
                "dh_algo": str(dh_algo or ""),
                "geo_hint": str(geo_hint or ""),
            },
            separators=(",", ":"),
        )
    )


def build_contact_accept(*, shared_alias: str) -> str:
    return (
        f"{DM_CONSENT_PREFIX}"
        + json.dumps(
            {
                "kind": "contact_accept",
                "shared_alias": str(shared_alias or ""),
            },
            separators=(",", ":"),
        )
    )


def build_contact_deny(*, reason: str = "") -> str:
    return (
        f"{DM_CONSENT_PREFIX}"
        + json.dumps(
            {
                "kind": "contact_deny",
                "reason": str(reason or ""),
            },
            separators=(",", ":"),
        )
    )


def parse_contact_consent(message: str) -> dict[str, Any] | None:
    text = str(message or "").strip()
    if not text.startswith(DM_CONSENT_PREFIX):
        return None
    try:
        payload = json.loads(text[len(DM_CONSENT_PREFIX) :])
    except Exception:
        return None
    kind = str(payload.get("kind", "") or "").strip().lower()
    if kind == "contact_offer":
        dh_pub_key = str(payload.get("dh_pub_key", "") or "").strip()
        if not dh_pub_key:
            return None
        return {
            "kind": kind,
            "dh_pub_key": dh_pub_key,
            "dh_algo": str(payload.get("dh_algo", "") or "").strip() or "X25519",
            "geo_hint": str(payload.get("geo_hint", "") or "").strip(),
        }
    if kind == "contact_accept":
        shared_alias = str(payload.get("shared_alias", "") or "").strip()
        if not shared_alias:
            return None
        return {"kind": kind, "shared_alias": shared_alias}
    if kind == "contact_deny":
        return {
            "kind": kind,
            "reason": str(payload.get("reason", "") or "").strip(),
        }
    return None


def _new_pairwise_alias() -> str:
    return f"{PAIRWISE_ALIAS_PREFIX}{secrets.token_hex(12)}"


def dead_drop_redact_label(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("ddid_"):
        return raw
    digest = hmac.new(
        _load_master_key(),
        f"dead-drop:dm_identity_id:{raw}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:20]
    return f"ddid_{digest}"


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


def _next_pairwise_alias_counter(contact: dict[str, Any]) -> int:
    return max(
        int(contact.get("sharedAliasCounter", 0) or 0),
        int(contact.get("pendingSharedAliasCounter", 0) or 0),
        int(contact.get("acceptedPreviousAliasCounter", 0) or 0),
    ) + 1


def issue_pairwise_dm_alias(*, peer_id: str, peer_dh_pub: str = "") -> dict[str, Any]:
    peer_id = str(peer_id or "").strip()
    peer_dh_pub = _resolve_peer_dh_pub(peer_id, peer_dh_pub)
    if not peer_id:
        return {"ok": False, "detail": "peer_id required"}

    from services.mesh.mesh_wormhole_persona import (
        bootstrap_wormhole_persona_state,
        get_dm_alias_public_key,
        get_dm_identity,
    )

    bootstrap_wormhole_persona_state()
    dm_identity = get_dm_identity()
    current = dict(list_wormhole_dm_contacts().get(peer_id) or {})
    previous_alias = str(current.get("sharedAlias", "") or "").strip()
    shared_alias = _new_pairwise_alias()
    while shared_alias == previous_alias:
        shared_alias = _new_pairwise_alias()
    shared_alias_counter = _next_pairwise_alias_counter(current)
    binding = get_dm_alias_public_key(shared_alias, counter=shared_alias_counter)
    if not binding.get("ok"):
        return {"ok": False, "detail": str(binding.get("detail", "") or "dm_alias_public_key_failed")}

    rotated_at_ms = int(time.time() * 1000)
    contact_updates: dict[str, Any] = {
        "sharedAlias": shared_alias,
        "sharedAliasCounter": shared_alias_counter,
        "sharedAliasPublicKey": str(binding.get("public_key", "") or ""),
        "sharedAliasPublicKeyAlgo": str(binding.get("public_key_algo", "Ed25519") or "Ed25519"),
        "pendingSharedAlias": "",
        "pendingSharedAliasCounter": 0,
        "pendingSharedAliasPublicKey": "",
        "pendingSharedAliasPublicKeyAlgo": "Ed25519",
        "pendingSharedAliasGraceMs": 0,
        "sharedAliasGraceUntil": 0,
        "sharedAliasRotatedAt": rotated_at_ms,
        "acceptedPreviousAlias": "",
        "acceptedPreviousAliasCounter": 0,
        "acceptedPreviousAliasPublicKey": "",
        "acceptedPreviousAliasPublicKeyAlgo": "Ed25519",
        "acceptedPreviousGraceUntil": 0,
        "acceptedPreviousHardGraceUntil": 0,
        "acceptedPreviousAwaitingReply": False,
        "aliasBindingPendingReason": "",
        "aliasBindingPreparedAt": 0,
        "dmIdentityId": dead_drop_redact_label(str(dm_identity.get("node_id", "") or "")),
        "previousSharedAliases": _merge_alias_history(
            previous_alias,
            *list(current.get("previousSharedAliases") or []),
        ),
    }
    if peer_dh_pub:
        contact_updates["dhPubKey"] = peer_dh_pub
    elif str(current.get("dhPubKey", "") or "").strip():
        contact_updates["dhPubKey"] = str(current.get("dhPubKey", "") or "").strip()
    if str(current.get("dhAlgo", "") or "").strip():
        contact_updates["dhAlgo"] = str(current.get("dhAlgo", "") or "").strip()

    contact = upsert_wormhole_dm_contact_internal(peer_id, contact_updates)
    return {
        "ok": True,
        "peer_id": peer_id,
        "shared_alias": shared_alias,
        "shared_alias_counter": shared_alias_counter,
        "replaced_alias": previous_alias,
        "identity_scope": "dm_alias",
        "dm_identity_id": dead_drop_redact_label(str(dm_identity.get("node_id", "") or "")),
        "contact": contact,
    }


def rotate_pairwise_dm_alias(
    *,
    peer_id: str,
    peer_dh_pub: str = "",
    grace_ms: int = PAIRWISE_ALIAS_GRACE_DEFAULT_MS,
    reason: AliasRotationReason | str = AliasRotationReason.MANUAL.value,
) -> dict[str, Any]:
    peer_id = str(peer_id or "").strip()
    peer_dh_pub = _resolve_peer_dh_pub(peer_id, peer_dh_pub)
    if not peer_id:
        return {"ok": False, "detail": "peer_id required"}
    normalized_reason = _normalize_rotation_reason(reason)

    from services.mesh.mesh_wormhole_persona import (
        bootstrap_wormhole_persona_state,
        get_dm_alias_public_key,
        get_dm_identity,
    )

    bootstrap_wormhole_persona_state()
    dm_identity = get_dm_identity()
    current = dict(list_wormhole_dm_contacts().get(peer_id) or {})
    active_alias = str(current.get("sharedAlias", "") or "").strip()
    if not active_alias:
        return issue_pairwise_dm_alias(peer_id=peer_id, peer_dh_pub=peer_dh_pub)

    now_ms = int(time.time() * 1000)
    pending_alias = str(current.get("pendingSharedAlias", "") or "").strip()
    grace_until = int(current.get("sharedAliasGraceUntil", 0) or 0)
    if pending_alias and normalized_reason in _ROUTINE_ALIAS_ROTATION_REASONS:
        return {
            "ok": True,
            "peer_id": peer_id,
            "active_alias": active_alias,
            "active_alias_counter": int(current.get("sharedAliasCounter", 0) or 0),
            "pending_alias": pending_alias,
            "pending_alias_counter": int(current.get("pendingSharedAliasCounter", 0) or 0),
            "grace_until": grace_until,
            "reason": normalized_reason.value,
            "identity_scope": "dm_alias",
            "dm_identity_id": dead_drop_redact_label(str(dm_identity.get("node_id", "") or "")),
            "contact": current,
            "rotated": False,
        }

    next_alias = _new_pairwise_alias()
    reserved = {
        active_alias,
        pending_alias,
        str(current.get("acceptedPreviousAlias", "") or "").strip(),
        *[str(item or "").strip() for item in list(current.get("previousSharedAliases") or [])],
    }
    while next_alias in reserved:
        next_alias = _new_pairwise_alias()
    next_alias_counter = _next_pairwise_alias_counter(current)
    binding = get_dm_alias_public_key(next_alias, counter=next_alias_counter)
    if not binding.get("ok"):
        return {"ok": False, "detail": str(binding.get("detail", "") or "dm_alias_public_key_failed")}

    clamped_grace_ms = max(
        PAIRWISE_ALIAS_GRACE_MIN_MS,
        min(int(grace_ms or PAIRWISE_ALIAS_GRACE_DEFAULT_MS), PAIRWISE_ALIAS_GRACE_MAX_MS),
    )
    next_grace_until = now_ms + clamped_grace_ms
    contact_updates: dict[str, Any] = {
        "pendingSharedAlias": next_alias,
        "pendingSharedAliasCounter": next_alias_counter,
        "pendingSharedAliasPublicKey": str(binding.get("public_key", "") or ""),
        "pendingSharedAliasPublicKeyAlgo": str(binding.get("public_key_algo", "Ed25519") or "Ed25519"),
        "pendingSharedAliasGraceMs": clamped_grace_ms,
        "sharedAliasGraceUntil": next_grace_until,
        "sharedAliasRotatedAt": now_ms,
        "aliasBindingPendingReason": normalized_reason.value,
        "aliasBindingPreparedAt": now_ms,
        "dmIdentityId": dead_drop_redact_label(str(dm_identity.get("node_id", "") or "")),
        "previousSharedAliases": _merge_alias_history(
            active_alias,
            str(current.get("acceptedPreviousAlias", "") or ""),
            *list(current.get("previousSharedAliases") or []),
        ),
    }
    active_binding = get_dm_alias_public_key(
        active_alias,
        counter=int(current.get("sharedAliasCounter", 0) or 0),
    )
    if active_binding.get("ok"):
        contact_updates["sharedAliasPublicKey"] = str(active_binding.get("public_key", "") or "")
        contact_updates["sharedAliasPublicKeyAlgo"] = str(
            active_binding.get("public_key_algo", "Ed25519") or "Ed25519"
        )
    if peer_dh_pub:
        contact_updates["dhPubKey"] = peer_dh_pub
    elif str(current.get("dhPubKey", "") or "").strip():
        contact_updates["dhPubKey"] = str(current.get("dhPubKey", "") or "").strip()
    if str(current.get("dhAlgo", "") or "").strip():
        contact_updates["dhAlgo"] = str(current.get("dhAlgo", "") or "").strip()

    contact = upsert_wormhole_dm_contact_internal(peer_id, contact_updates)
    return {
        "ok": True,
        "peer_id": peer_id,
        "active_alias": active_alias,
        "active_alias_counter": int(current.get("sharedAliasCounter", 0) or 0),
        "pending_alias": next_alias,
        "pending_alias_counter": next_alias_counter,
        "grace_until": next_grace_until,
        "reason": normalized_reason.value,
        "identity_scope": "dm_alias",
        "dm_identity_id": dead_drop_redact_label(str(dm_identity.get("node_id", "") or "")),
        "contact": contact,
        "rotated": True,
    }


def maybe_prepare_pairwise_dm_alias_rotation(
    *,
    peer_id: str,
    peer_dh_pub: str = "",
    reason: AliasRotationReason | str | None = None,
) -> dict[str, Any]:
    peer_key = str(peer_id or "").strip()
    if not peer_key:
        return {"ok": False, "detail": "peer_id required"}
    contact = _migrate_local_contact_alias_bindings(
        peer_key,
        dict(list_wormhole_dm_contacts().get(peer_key) or {}),
    )
    has_peer_dh = bool(
        str(peer_dh_pub or contact.get("dhPubKey") or contact.get("invitePinnedDhPubKey") or "").strip()
    )
    trust_summary = dict(contact.get("trustSummary") or {})
    verified_first_contact = bool(trust_summary.get("verifiedFirstContact"))
    active_alias = str(contact.get("sharedAlias", "") or "").strip()
    pending_alias = str(contact.get("pendingSharedAlias", "") or "").strip()
    normalized_reason = _normalize_rotation_reason(reason) if reason is not None else None

    if normalized_reason is None:
        if not active_alias and has_peer_dh and verified_first_contact:
            return issue_pairwise_dm_alias(peer_id=peer_key, peer_dh_pub=peer_dh_pub)
        if pending_alias:
            return {
                "ok": True,
                "peer_id": peer_key,
                "active_alias": active_alias,
                "pending_alias": pending_alias,
                "rotated": False,
                "reason": str(contact.get("aliasBindingPendingReason", "") or ""),
                "contact": contact,
            }
        if not verified_first_contact:
            return {"ok": True, "peer_id": peer_key, "rotated": False, "contact": contact}
        now_ms = int(time.time() * 1000)
        if active_alias and int(contact.get("sharedAliasRotatedAt", 0) or 0) > 0:
            rotated_at = int(contact.get("sharedAliasRotatedAt", 0) or 0)
            from services.mesh.mesh_rollout_flags import pairwise_alias_rotate_after_ms

            rotate_threshold_ms = pairwise_alias_rotate_after_ms()
            if now_ms - rotated_at >= rotate_threshold_ms:
                # Enum value retained for backward compatibility with
                # existing telemetry dashboards; the label no longer implies
                # a 30-day cadence — see pairwise_alias_rotate_after_ms().
                normalized_reason = AliasRotationReason.SCHEDULED_30D
        if normalized_reason is None and active_alias and verified_first_contact:
            verified_at_s = int(contact.get("verified_at", 0) or 0)
            if verified_at_s > 0 and verified_at_s * 1000 > int(contact.get("sharedAliasRotatedAt", 0) or 0):
                normalized_reason = AliasRotationReason.CONTACT_VERIFICATION_COMPLETED
        if normalized_reason is None and active_alias:
            gate_join_seq = _observed_gate_join_seq()
            if gate_join_seq > int(contact.get("aliasGateJoinAppliedSeq", 0) or 0):
                normalized_reason = AliasRotationReason.GATE_JOIN
        if normalized_reason is None:
            return {"ok": True, "peer_id": peer_key, "rotated": False, "contact": contact}

    return rotate_pairwise_dm_alias(
        peer_id=peer_key,
        peer_dh_pub=peer_dh_pub,
        grace_ms=int(contact.get("pendingSharedAliasGraceMs", 0) or 0) or PAIRWISE_ALIAS_GRACE_DEFAULT_MS,
        reason=normalized_reason.value,
    )


def _alias_binding_payload_for_contact(contact: dict[str, Any], *, now_ms: int | None = None) -> dict[str, Any] | None:
    current = dict(contact or {})
    active_alias = str(current.get("sharedAlias", "") or "").strip()
    pending_alias = str(current.get("pendingSharedAlias", "") or "").strip()
    if not active_alias or not pending_alias:
        return None
    reason_value = str(current.get("aliasBindingPendingReason", "") or "").strip()
    if not reason_value:
        return None
    normalized_reason = _normalize_rotation_reason(reason_value)
    current_counter = int(current.get("sharedAliasCounter", 0) or 0)
    pending_counter = int(current.get("pendingSharedAliasCounter", 0) or 0)
    active_public_key = str(current.get("sharedAliasPublicKey", "") or "").strip()
    active_public_key_algo = str(current.get("sharedAliasPublicKeyAlgo", "Ed25519") or "Ed25519")
    pending_public_key = str(current.get("pendingSharedAliasPublicKey", "") or "").strip()
    pending_public_key_algo = str(current.get("pendingSharedAliasPublicKeyAlgo", "Ed25519") or "Ed25519")
    if not pending_public_key:
        return None
    if normalized_reason in _ROUTINE_ALIAS_ROTATION_REASONS and not active_public_key:
        return None
    current_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    grace_ms = int(current.get("pendingSharedAliasGraceMs", 0) or 0) or PAIRWISE_ALIAS_GRACE_DEFAULT_MS
    next_seq = int(current.get("aliasBindingSeq", 0) or 0) + 1
    payload_core = {
        "kind": PAIRWISE_ALIAS_UPDATE_KIND,
        "seq": next_seq,
        "reason": normalized_reason.value,
        "old_alias": active_alias,
        "old_counter": current_counter,
        "new_alias": pending_alias,
        "new_counter": pending_counter,
        "grace_until": current_ms + grace_ms,
        "hard_cap_until": current_ms + PAIRWISE_ALIAS_OFFLINE_HARD_CAP_MS,
        "issued_at": current_ms,
    }
    canonical = _canonical_alias_payload(payload_core)
    new_signature = _sign_alias_binding(pending_alias, canonical, counter=pending_counter)
    if not new_signature.get("ok"):
        return None
    frame: dict[str, Any] = {
        **payload_core,
        "new_alias_public_key": pending_public_key,
        "new_alias_public_key_algo": pending_public_key_algo,
        "new_alias_signature": str(new_signature.get("signature", "") or ""),
    }
    if normalized_reason in _ROUTINE_ALIAS_ROTATION_REASONS:
        old_signature = _sign_alias_binding(active_alias, canonical, counter=current_counter)
        if not old_signature.get("ok"):
            return None
        frame.update(
            {
                "old_alias_public_key": active_public_key,
                "old_alias_public_key_algo": active_public_key_algo,
                "old_alias_signature": str(old_signature.get("signature", "") or ""),
            }
        )
    else:
        root_signature = _sign_root_alias_binding(canonical)
        if not root_signature.get("signature"):
            return None
        frame.update(
            {
                "old_alias_public_key": active_public_key,
                "old_alias_public_key_algo": active_public_key_algo,
                "root_public_key": str(root_signature.get("public_key", "") or ""),
                "root_public_key_algo": str(root_signature.get("public_key_algo", "Ed25519") or "Ed25519"),
                "root_signature": str(root_signature.get("signature", "") or ""),
                "root_node_id": str(root_signature.get("node_id", "") or ""),
            }
        )
    return frame


def _commit_updates_for_alias_frame(contact: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
    current = dict(contact or {})
    old_alias = str(frame.get("old_alias", "") or "").strip()
    new_alias = str(frame.get("new_alias", "") or "").strip()
    old_public_key = str(frame.get("old_alias_public_key", current.get("sharedAliasPublicKey", "")) or "")
    old_public_key_algo = str(
        frame.get("old_alias_public_key_algo", current.get("sharedAliasPublicKeyAlgo", "Ed25519")) or "Ed25519"
    )
    return {
        "sharedAlias": new_alias,
        "sharedAliasCounter": int(frame.get("new_counter", 0) or 0),
        "sharedAliasPublicKey": str(frame.get("new_alias_public_key", "") or ""),
        "sharedAliasPublicKeyAlgo": str(frame.get("new_alias_public_key_algo", "Ed25519") or "Ed25519"),
        "pendingSharedAlias": "",
        "pendingSharedAliasCounter": 0,
        "pendingSharedAliasPublicKey": "",
        "pendingSharedAliasPublicKeyAlgo": "Ed25519",
        "pendingSharedAliasGraceMs": 0,
        "sharedAliasGraceUntil": 0,
        "sharedAliasRotatedAt": int(frame.get("issued_at", 0) or int(time.time() * 1000)),
        "acceptedPreviousAlias": old_alias,
        "acceptedPreviousAliasCounter": int(frame.get("old_counter", 0) or 0),
        "acceptedPreviousAliasPublicKey": old_public_key,
        "acceptedPreviousAliasPublicKeyAlgo": old_public_key_algo,
        "acceptedPreviousGraceUntil": int(frame.get("grace_until", 0) or 0),
        "acceptedPreviousHardGraceUntil": int(frame.get("hard_cap_until", 0) or 0),
        "acceptedPreviousAwaitingReply": True,
        "aliasBindingSeq": int(frame.get("seq", 0) or 0),
        "aliasBindingPendingReason": "",
        "aliasBindingPreparedAt": 0,
        "aliasGateJoinAppliedSeq": _observed_gate_join_seq(),
        "previousSharedAliases": _merge_alias_history(
            old_alias,
            str(current.get("acceptedPreviousAlias", "") or ""),
            *list(current.get("previousSharedAliases") or []),
        ),
    }


def prepare_outbound_alias_binding_payload(*, peer_id: str, plaintext: str) -> dict[str, Any]:
    peer_key = str(peer_id or "").strip()
    if not peer_key:
        return {"ok": True, "plaintext": str(plaintext or ""), "alias_update_embedded": False}
    current = _migrate_local_contact_alias_bindings(
        peer_key,
        dict(list_wormhole_dm_contacts().get(peer_key) or {}),
    )
    frame = _alias_binding_payload_for_contact(current)
    if not frame:
        return {"ok": True, "plaintext": str(plaintext or ""), "alias_update_embedded": False}
    wrapped = _build_pairwise_alias_payload(str(plaintext or ""), frame)
    return {
        "ok": True,
        "plaintext": wrapped,
        "alias_update_embedded": True,
        "alias_update_reason": str(frame.get("reason", "") or ""),
        "alias_update_seq": int(frame.get("seq", 0) or 0),
        "commit_updates": _commit_updates_for_alias_frame(current, frame),
    }


def register_outbound_alias_rotation_commit(
    *,
    peer_id: str,
    payload_format: str,
    ciphertext: str,
    updates: dict[str, Any],
) -> None:
    _register_pending_alias_commit(
        peer_id=peer_id,
        payload_format=payload_format,
        ciphertext=ciphertext,
        updates=updates,
    )


def commit_outbound_alias_rotation_if_present(
    *,
    peer_id: str,
    payload_format: str,
    ciphertext: str,
) -> bool:
    updates = _consume_pending_alias_commit(
        peer_id=peer_id,
        payload_format=payload_format,
        ciphertext=ciphertext,
    )
    if not updates:
        return False
    upsert_wormhole_dm_contact_internal(str(peer_id or "").strip(), updates)
    metrics_inc("alias_rotations_completed")
    return True


def mark_contact_alias_reply_observed(peer_id: str) -> bool:
    peer_key = str(peer_id or "").strip()
    if not peer_key:
        return False
    contact = dict(list_wormhole_dm_contacts().get(peer_key) or {})
    if not bool(contact.get("acceptedPreviousAwaitingReply")):
        return False
    updates = {
        "acceptedPreviousAwaitingReply": False,
    }
    upsert_wormhole_dm_contact_internal(peer_key, updates)
    return True


def apply_inbound_alias_binding_frame(*, peer_id: str, alias_update: dict[str, Any] | None) -> dict[str, Any]:
    peer_key = str(peer_id or "").strip()
    frame = dict(alias_update or {})
    if not peer_key or not frame:
        return {"ok": False, "detail": "alias_update_missing"}
    if str(frame.get("kind", "") or "") != PAIRWISE_ALIAS_UPDATE_KIND:
        return {"ok": False, "detail": "alias_update_kind_invalid"}
    contact = dict(list_wormhole_dm_contacts().get(peer_key) or {})
    if _contact_alias_updates_blocked(contact):
        metrics_inc("alias_bindings_rejected_revoked")
        return {"ok": False, "detail": "alias_update_blocked"}
    seq = int(frame.get("seq", 0) or 0)
    if seq <= int(contact.get("aliasBindingSeq", 0) or 0):
        metrics_inc("alias_bindings_rejected_replay")
        return {"ok": False, "detail": "alias_update_replay"}
    reason = _normalize_rotation_reason(frame.get("reason", ""))
    canonical = _canonical_alias_payload(
        {
            "kind": PAIRWISE_ALIAS_UPDATE_KIND,
            "seq": seq,
            "reason": reason.value,
            "old_alias": str(frame.get("old_alias", "") or ""),
            "old_counter": int(frame.get("old_counter", 0) or 0),
            "new_alias": str(frame.get("new_alias", "") or ""),
            "new_counter": int(frame.get("new_counter", 0) or 0),
            "grace_until": int(frame.get("grace_until", 0) or 0),
            "hard_cap_until": int(frame.get("hard_cap_until", 0) or 0),
            "issued_at": int(frame.get("issued_at", 0) or 0),
        }
    )
    old_alias = str(frame.get("old_alias", "") or "").strip()
    old_counter = int(frame.get("old_counter", 0) or 0)
    new_alias = str(frame.get("new_alias", "") or "").strip()
    new_counter = int(frame.get("new_counter", 0) or 0)
    new_public_key = str(frame.get("new_alias_public_key", "") or "").strip()
    new_public_key_algo = str(frame.get("new_alias_public_key_algo", "Ed25519") or "Ed25519")
    old_public_key, old_public_key_algo = _contact_alias_public_binding(contact, old_alias)
    if reason == AliasRotationReason.SUSPECTED_COMPROMISE:
        if str(frame.get("old_alias_signature", "") or "").strip():
            return {"ok": False, "detail": "alias_update_old_sig_forbidden"}
        contact_root_public_key = str(
            contact.get("invitePinnedRootPublicKey")
            or contact.get("remotePrekeyRootPublicKey")
            or ""
        ).strip()
        contact_root_public_key_algo = str(
            contact.get("invitePinnedRootPublicKeyAlgo")
            or contact.get("remotePrekeyRootPublicKeyAlgo")
            or "Ed25519"
        )
        if not contact_root_public_key or contact_root_public_key != str(frame.get("root_public_key", "") or "").strip():
            return {"ok": False, "detail": "alias_update_root_unknown"}
        if not _verify_root_binding_signature(
            canonical,
            signature=str(frame.get("root_signature", "") or ""),
            public_key=contact_root_public_key,
            public_key_algo=contact_root_public_key_algo,
        ):
            return {"ok": False, "detail": "alias_update_root_invalid"}
    else:
        if str(frame.get("root_signature", "") or "").strip():
            return {"ok": False, "detail": "alias_update_root_sig_forbidden"}
        if (
            not old_public_key
            and old_counter == 0
            and seq == 1
            and old_alias == str(contact.get("sharedAlias", "") or "").strip()
        ):
            old_public_key = str(frame.get("old_alias_public_key", "") or "").strip()
            old_public_key_algo = str(frame.get("old_alias_public_key_algo", "Ed25519") or "Ed25519")
        if not old_public_key:
            return {"ok": False, "detail": "alias_update_old_alias_unknown"}
        if not _verify_alias_binding_signature(
            old_alias,
            canonical,
            str(frame.get("old_alias_signature", "") or ""),
            counter=old_counter,
            public_key=old_public_key,
            public_key_algo=old_public_key_algo,
        ):
            return {"ok": False, "detail": "alias_update_old_alias_invalid"}
    if not old_public_key:
        old_public_key = str(frame.get("old_alias_public_key", "") or "").strip()
        old_public_key_algo = str(frame.get("old_alias_public_key_algo", "Ed25519") or "Ed25519")
    if not _verify_alias_binding_signature(
        new_alias,
        canonical,
        str(frame.get("new_alias_signature", "") or ""),
        counter=new_counter,
        public_key=new_public_key,
        public_key_algo=new_public_key_algo,
    ):
        return {"ok": False, "detail": "alias_update_new_alias_invalid"}
    updates = {
        "sharedAlias": new_alias,
        "sharedAliasCounter": new_counter,
        "sharedAliasPublicKey": new_public_key,
        "sharedAliasPublicKeyAlgo": new_public_key_algo,
        "acceptedPreviousAlias": old_alias,
        "acceptedPreviousAliasCounter": old_counter,
        "acceptedPreviousAliasPublicKey": old_public_key,
        "acceptedPreviousAliasPublicKeyAlgo": old_public_key_algo,
        "acceptedPreviousGraceUntil": int(frame.get("grace_until", 0) or 0),
        "acceptedPreviousHardGraceUntil": int(frame.get("hard_cap_until", 0) or 0),
        "acceptedPreviousAwaitingReply": False,
        "sharedAliasRotatedAt": int(frame.get("issued_at", 0) or int(time.time() * 1000)),
        "aliasBindingSeq": seq,
        "pendingSharedAlias": "",
        "pendingSharedAliasCounter": 0,
        "pendingSharedAliasPublicKey": "",
        "pendingSharedAliasPublicKeyAlgo": "Ed25519",
        "pendingSharedAliasGraceMs": 0,
        "sharedAliasGraceUntil": 0,
        "aliasBindingPendingReason": "",
        "aliasBindingPreparedAt": 0,
        "previousSharedAliases": _merge_alias_history(
            old_alias,
            str(contact.get("acceptedPreviousAlias", "") or ""),
            *list(contact.get("previousSharedAliases") or []),
        ),
    }
    updated = upsert_wormhole_dm_contact_internal(peer_key, updates)
    return {"ok": True, "contact": updated, "seq": seq, "reason": reason.value}


def mailbox_epoch_seconds() -> int:
    try:
        settings = read_wormhole_settings()
        if str(settings.get("privacy_profile", "default") or "default").lower() == "high":
            return HIGH_PRIVACY_DM_EPOCH_SECONDS
    except Exception:
        pass
    return DEFAULT_DM_EPOCH_SECONDS


def current_mailbox_epoch(ts_seconds: int | None = None) -> int:
    now = int(ts_seconds) if ts_seconds is not None else int(time.time())
    return now // mailbox_epoch_seconds()


def _derive_shared_secret(my_private_b64: str, peer_public_b64: str) -> bytes:
    priv = x25519.X25519PrivateKey.from_private_bytes(_unb64(my_private_b64))
    pub = x25519.X25519PublicKey.from_public_bytes(_unb64(peer_public_b64))
    return priv.exchange(pub)


def _mailbox_peer_refs(
    peer_id: str,
    *,
    peer_ref: str = "",
    peer_refs: list[str] | None = None,
) -> list[str]:
    explicit_refs = [
        str(value or "").strip()
        for value in list(peer_refs or [])
        if str(value or "").strip()
    ]
    if explicit_refs:
        return list(dict.fromkeys(explicit_refs))[:4]

    explicit_ref = str(peer_ref or "").strip()
    if explicit_ref:
        return [explicit_ref]

    contact = dict(list_wormhole_dm_contacts().get(str(peer_id or "").strip()) or {})
    refs: list[str] = []
    accepted_aliases = accepted_contact_shared_aliases(contact)
    previous_aliases = [
        str(value or "").strip()
        for value in list(contact.get("previousSharedAliases") or [])[:2]
        if str(value or "").strip()
    ]

    for candidate in [*accepted_aliases, *previous_aliases]:
        if candidate and candidate not in refs:
            refs.append(candidate)
        if len(refs) >= 4:
            break

    if refs:
        return refs
    fallback = str(peer_id or "").strip()
    return [fallback] if fallback else []


def _resolve_peer_dh_pub(peer_id: str, peer_dh_pub: str = "") -> str:
    explicit = str(peer_dh_pub or "").strip()
    if explicit:
        return explicit
    contact = dict(list_wormhole_dm_contacts().get(str(peer_id or "").strip()) or {})
    return str(contact.get("dhPubKey") or contact.get("invitePinnedDhPubKey") or "").strip()


def _token_for(secret: bytes, peer_ref: str, my_node_id: str, epoch: int) -> str:
    ids = "|".join(sorted([str(my_node_id or ""), str(peer_ref or "")]))
    message = f"sb_dd|v1|{int(epoch)}|{ids}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _sas_words_from_digest(digest: bytes, count: int) -> list[str]:
    out: list[str] = []
    acc = 0
    acc_bits = 0
    for byte in digest:
        acc = (acc << 8) | byte
        acc_bits += 8
        while acc_bits >= 8 and len(out) < count:
            idx = (acc >> (acc_bits - 8)) & 0xFF
            out.append(SAS_WORDS[idx])
            acc_bits -= 8
        if len(out) >= count:
            break
    return out


def derive_dead_drop_token_pair(*, peer_id: str, peer_dh_pub: str, peer_ref: str = "") -> dict[str, Any]:
    peer_id = str(peer_id or "").strip()
    peer_dh_pub = _resolve_peer_dh_pub(peer_id, peer_dh_pub)
    if not peer_id or not peer_dh_pub:
        return {"ok": False, "detail": "peer_id and peer_dh_pub required"}
    peer_refs = _mailbox_peer_refs(peer_id, peer_ref=peer_ref)
    if not peer_refs:
        return {"ok": False, "detail": "peer reference unavailable"}
    resolved_peer_ref = peer_refs[0]

    identity = read_wormhole_identity()
    if not identity.get("bootstrapped"):
        bootstrap_wormhole_identity()
        identity = read_wormhole_identity()

    my_private = str(identity.get("dh_private_key", "") or "")
    my_node_id = str(identity.get("node_id", "") or "")
    if not my_private or not my_node_id:
        return {"ok": False, "detail": "Wormhole DH identity unavailable"}

    try:
        secret = _derive_shared_secret(my_private, peer_dh_pub)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or "dead_drop_secret_failed"}

    epoch = current_mailbox_epoch()
    return {
        "ok": True,
        "peer_id": peer_id,
        "peer_ref": resolved_peer_ref,
        "epoch": epoch,
        "current": _token_for(secret, resolved_peer_ref, my_node_id, epoch),
        "previous": _token_for(secret, resolved_peer_ref, my_node_id, epoch - 1),
    }


def derive_dead_drop_tokens_for_contacts(*, contacts: list[dict[str, Any]], limit: int = 24) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in contacts[: max(1, min(int(limit or 24), 64))]:
        peer_id = str((item or {}).get("peer_id", "") or "").strip()
        peer_dh_pub = _resolve_peer_dh_pub(
            peer_id,
            str((item or {}).get("peer_dh_pub", "") or "").strip(),
        )
        if not peer_id or not peer_dh_pub:
            continue
        peer_refs = _mailbox_peer_refs(
            peer_id,
            peer_ref=str((item or {}).get("peer_ref", "") or ""),
            peer_refs=list((item or {}).get("peer_refs") or []),
        )
        for ref in peer_refs:
            pair = derive_dead_drop_token_pair(peer_id=peer_id, peer_dh_pub=peer_dh_pub, peer_ref=ref)
            if pair.get("ok"):
                results.append(
                    {
                        "peer_id": peer_id,
                        "peer_ref": str(pair.get("peer_ref", "") or ref),
                        "current": str(pair.get("current", "") or ""),
                        "previous": str(pair.get("previous", "") or ""),
                        "epoch": int(pair.get("epoch", 0) or 0),
                    }
                )
            if len(results) >= max(1, min(int(limit or 24), 64)):
                break
        if len(results) >= max(1, min(int(limit or 24), 64)):
            break
    return {"ok": True, "tokens": results}


def derive_sas_phrase(*, peer_id: str, peer_dh_pub: str, words: int = 8, peer_ref: str = "") -> dict[str, Any]:
    peer_id = str(peer_id or "").strip()
    peer_dh_pub = _resolve_peer_dh_pub(peer_id, peer_dh_pub)
    word_count = max(2, min(int(words or 8), 16))
    if not peer_id or not peer_dh_pub:
        return {"ok": False, "detail": "peer_id and peer_dh_pub required"}
    peer_refs = _mailbox_peer_refs(peer_id, peer_ref=peer_ref)
    if not peer_refs:
        return {"ok": False, "detail": "peer reference unavailable"}
    resolved_peer_ref = peer_refs[0]

    identity = read_wormhole_identity()
    if not identity.get("bootstrapped"):
        bootstrap_wormhole_identity()
        identity = read_wormhole_identity()

    my_private = str(identity.get("dh_private_key", "") or "")
    my_node_id = str(identity.get("node_id", "") or "")
    if not my_private or not my_node_id:
        return {"ok": False, "detail": "Wormhole DH identity unavailable"}

    try:
        secret = _derive_shared_secret(my_private, peer_dh_pub)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or "sas_secret_failed"}

    ids = "|".join(sorted([my_node_id, resolved_peer_ref]))
    digest = hmac.new(secret, f"sb_sas|v1|{ids}".encode("utf-8"), hashlib.sha256).digest()
    phrase = " ".join(_sas_words_from_digest(digest, word_count))
    return {
        "ok": True,
        "peer_id": peer_id,
        "peer_ref": resolved_peer_ref,
        "phrase": phrase,
        "words": word_count,
    }
