"""Stable DM root manifest publication and witness receipts.

This module publishes a root-signed manifest for the current Wormhole DM root
identity together with a witness policy and a threshold-satisfying witness
receipt set. Sprint 10 extends the earlier single-witness format so strong
invite/bootstrap trust can depend on quorum-style witnessed distribution rather
than one local witness receipt.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from services.mesh.mesh_crypto import build_signature_payload, derive_node_id, verify_node_binding, verify_signature
from services.mesh.mesh_protocol import PROTOCOL_VERSION
from services.mesh.mesh_secure_storage import read_domain_json, write_domain_json
from services.mesh.mesh_wormhole_identity import root_identity_fingerprint_for_material
from services.mesh.mesh_wormhole_persona import (
    bootstrap_wormhole_persona_state,
    get_root_identity,
    read_previous_root_identity,
    sign_previous_root_wormhole_event,
    sign_root_wormhole_event,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
ROOT_DISTRIBUTION_DOMAIN = "root_distribution"
ROOT_DISTRIBUTION_FILE = "wormhole_root_distribution.json"
STABLE_DM_ROOT_MANIFEST_EVENT_TYPE = "stable_dm_root_manifest"
STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE = "stable_dm_root_manifest_witness"
STABLE_DM_ROOT_MANIFEST_PREVIOUS_ROOT_EVENT_TYPE = "stable_dm_root_manifest_previous_root"
STABLE_DM_ROOT_MANIFEST_POLICY_CHANGE_EVENT_TYPE = "stable_dm_root_manifest_policy_change"
STABLE_DM_ROOT_MANIFEST_TYPE = "stable_dm_root_manifest"
STABLE_DM_ROOT_MANIFEST_WITNESS_TYPE = "stable_dm_root_manifest_witness"
STABLE_DM_ROOT_MANIFEST_WITNESS_POLICY_TYPE = "stable_dm_root_manifest_witness_policy"
STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE = "stable_dm_root_manifest_external_witness_import"
DEFAULT_ROOT_MANIFEST_TTL_S = 7 * 24 * 60 * 60
DEFAULT_ROOT_WITNESS_COUNT = 3
DEFAULT_ROOT_WITNESS_THRESHOLD = 2
DEFAULT_ROOT_WITNESS_MANAGEMENT_SCOPE = "local"
DEFAULT_ROOT_WITNESS_INDEPENDENCE_GROUP = "local_system"
DEFAULT_ROOT_EXTERNAL_WITNESS_MAX_AGE_S = 3600


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _resolve_external_material_path(raw_path: str) -> Path | None:
    raw = str(raw_path or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return BACKEND_DIR / candidate


def _external_root_witness_max_age_s() -> int:
    from services.config import get_settings

    return max(
        0,
        _safe_int(
            getattr(
                get_settings(),
                "MESH_DM_ROOT_EXTERNAL_WITNESS_MAX_AGE_S",
                DEFAULT_ROOT_EXTERNAL_WITNESS_MAX_AGE_S,
            )
            or DEFAULT_ROOT_EXTERNAL_WITNESS_MAX_AGE_S,
            DEFAULT_ROOT_EXTERNAL_WITNESS_MAX_AGE_S,
        ),
    )


def _default_witness_label(index: int) -> str:
    return "root-witness" if index <= 1 else f"root-witness-{index}"


def _normalize_witness_management_scope(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return "external" if normalized == "external" else DEFAULT_ROOT_WITNESS_MANAGEMENT_SCOPE


def _normalize_witness_independence_group(value: Any, *, management_scope: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized:
        return normalized
    return (
        DEFAULT_ROOT_WITNESS_INDEPENDENCE_GROUP
        if management_scope == DEFAULT_ROOT_WITNESS_MANAGEMENT_SCOPE
        else "external_unknown"
    )


def root_witness_finality_met(
    *,
    witness_threshold: int,
    witness_quorum_met: bool,
    witness_independent_quorum_met: bool,
) -> bool:
    threshold = _safe_int(witness_threshold, 0)
    if threshold <= 0 or not bool(witness_quorum_met):
        return False
    if threshold <= 1:
        return True
    return bool(witness_independent_quorum_met)


def _empty_witness_identity(*, index: int = 1) -> dict[str, Any]:
    return {
        "scope": "root_witness",
        "label": _default_witness_label(index),
        "node_id": "",
        "public_key": "",
        "public_key_algo": "Ed25519",
        "management_scope": DEFAULT_ROOT_WITNESS_MANAGEMENT_SCOPE,
        "independence_group": DEFAULT_ROOT_WITNESS_INDEPENDENCE_GROUP,
        "private_key": "",
        "sequence": 0,
        "created_at": 0,
        "last_used_at": 0,
    }


def _default_state() -> dict[str, Any]:
    return {
        "updated_at": 0,
        "witness_identity": _empty_witness_identity(),
        "witness_identities": [],
        "external_witness_descriptors": [],
        "external_witness_source_scope": "",
        "external_witness_source_label": "",
        "external_witness_imported_at": 0,
        "external_witness_source_exported_at": 0,
        "external_witness_refresh_attempted_at": 0,
        "external_witness_refresh_ok": False,
        "external_witness_refresh_detail": "",
        "external_witness_refresh_source_path": "",
        "external_witness_refresh_source_ref": "",
        "external_witness_manifest_fingerprint": "",
        "external_witness_receipts": [],
        "published_manifest": {},
        "published_manifest_fingerprint": "",
        "published_witness": {},
        "published_witnesses": [],
    }


def _witness_identity_record(*, index: int = 1) -> dict[str, Any]:
    signing_priv = ed25519.Ed25519PrivateKey.generate()
    signing_priv_raw = signing_priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    signing_pub_raw = signing_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    now = int(time.time())
    public_key_b64 = base64.b64encode(signing_pub_raw).decode("ascii")
    private_key_b64 = base64.b64encode(signing_priv_raw).decode("ascii")
    return {
        "scope": "root_witness",
        "label": _default_witness_label(index),
        "node_id": derive_node_id(public_key_b64),
        "public_key": public_key_b64,
        "public_key_algo": "Ed25519",
        "management_scope": DEFAULT_ROOT_WITNESS_MANAGEMENT_SCOPE,
        "independence_group": DEFAULT_ROOT_WITNESS_INDEPENDENCE_GROUP,
        "private_key": private_key_b64,
        "sequence": 0,
        "created_at": now,
        "last_used_at": now,
    }


def _public_witness_identity(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": str(identity.get("scope", "root_witness") or "root_witness"),
        "label": str(identity.get("label", "root-witness") or "root-witness"),
        "node_id": str(identity.get("node_id", "") or ""),
        "public_key": str(identity.get("public_key", "") or ""),
        "public_key_algo": str(identity.get("public_key_algo", "Ed25519") or "Ed25519"),
        "management_scope": _normalize_witness_management_scope(identity.get("management_scope")),
        "independence_group": _normalize_witness_independence_group(
            identity.get("independence_group"),
            management_scope=_normalize_witness_management_scope(identity.get("management_scope")),
        ),
        "sequence": _safe_int(identity.get("sequence", 0) or 0, 0),
        "created_at": _safe_int(identity.get("created_at", 0) or 0, 0),
        "last_used_at": _safe_int(identity.get("last_used_at", 0) or 0, 0),
    }


def _public_witness_descriptor(identity: dict[str, Any]) -> dict[str, Any]:
    management_scope = _normalize_witness_management_scope(identity.get("management_scope"))
    return {
        "scope": str(identity.get("scope", "root_witness") or "root_witness"),
        "label": str(identity.get("label", "root-witness") or "root-witness"),
        "node_id": str(identity.get("node_id", "") or "").strip(),
        "public_key": str(identity.get("public_key", "") or "").strip(),
        "public_key_algo": str(identity.get("public_key_algo", "Ed25519") or "Ed25519"),
        "management_scope": management_scope,
        "independence_group": _normalize_witness_independence_group(
            identity.get("independence_group"),
            management_scope=management_scope,
        ),
    }


def _coerce_witness_identity(value: Any, *, index: int = 1) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    identity = {
        **_empty_witness_identity(index=index),
        **dict(value or {}),
    }
    if not str(identity.get("private_key", "") or "").strip():
        return None
    if not str(identity.get("public_key", "") or "").strip():
        return None
    if not str(identity.get("node_id", "") or "").strip():
        identity["node_id"] = derive_node_id(str(identity.get("public_key", "") or "").strip())
    identity["label"] = str(identity.get("label", _default_witness_label(index)) or _default_witness_label(index))
    identity["management_scope"] = _normalize_witness_management_scope(identity.get("management_scope"))
    identity["independence_group"] = _normalize_witness_independence_group(
        identity.get("independence_group"),
        management_scope=identity["management_scope"],
    )
    return identity


def _normalize_witness_identities(
    values: Any,
    *,
    legacy_identity: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    normalized: list[dict[str, Any]] = []
    changed = False
    candidates = list(values or [])
    if legacy_identity:
        candidates.insert(0, legacy_identity)
    seen: set[tuple[str, str]] = set()
    for index, value in enumerate(candidates, start=1):
        identity = _coerce_witness_identity(value, index=index)
        if not identity:
            changed = True
            continue
        key = (
            str(identity.get("node_id", "") or "").strip(),
            str(identity.get("public_key", "") or "").strip(),
        )
        if not key[0] or not key[1] or key in seen:
            changed = True
            continue
        seen.add(key)
        normalized.append(identity)
    if values != normalized:
        changed = True
    return normalized, changed


def _normalize_external_witness_descriptor(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    raw = dict(value or {})
    if not raw.get("management_scope"):
        raw["management_scope"] = "external"
    descriptor = _public_witness_descriptor(raw)
    descriptor["management_scope"] = "external"
    descriptor["independence_group"] = _normalize_witness_independence_group(
        raw.get("independence_group"),
        management_scope="external",
    )
    if not descriptor["node_id"] or not descriptor["public_key"]:
        return None
    if not verify_node_binding(descriptor["node_id"], descriptor["public_key"]):
        return None
    return descriptor


def _normalize_external_witness_descriptors(values: Any) -> tuple[list[dict[str, Any]], bool]:
    normalized: list[dict[str, Any]] = []
    changed = False
    seen: set[tuple[str, str]] = set()
    for value in list(values or []):
        descriptor = _normalize_external_witness_descriptor(value)
        if not descriptor:
            changed = True
            continue
        key = (
            str(descriptor.get("node_id", "") or "").strip(),
            str(descriptor.get("public_key", "") or "").strip(),
        )
        if not key[0] or not key[1] or key in seen:
            changed = True
            continue
        seen.add(key)
        normalized.append(descriptor)
    if list(values or []) != normalized:
        changed = True
    return normalized, changed


def _configured_witness_descriptors(
    state: dict[str, Any],
    local_witness_identities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in list(local_witness_identities or []):
        descriptor = _public_witness_descriptor(value)
        key = (
            str(descriptor.get("node_id", "") or "").strip(),
            str(descriptor.get("public_key", "") or "").strip(),
        )
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        descriptors.append(descriptor)
    for value in list(state.get("external_witness_descriptors") or []):
        descriptor = _normalize_external_witness_descriptor(value)
        if not descriptor:
            continue
        key = (
            str(descriptor.get("node_id", "") or "").strip(),
            str(descriptor.get("public_key", "") or "").strip(),
        )
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        descriptors.append(descriptor)
    return descriptors


def _current_external_witness_receipts(
    state: dict[str, Any],
    *,
    manifest_fingerprint: str,
) -> list[dict[str, Any]]:
    expected_fingerprint = str(manifest_fingerprint or "").strip().lower()
    current_fingerprint = str(state.get("external_witness_manifest_fingerprint", "") or "").strip().lower()
    if not expected_fingerprint or current_fingerprint != expected_fingerprint:
        return []
    return [
        dict(item or {})
        for item in list(state.get("external_witness_receipts") or [])
        if isinstance(item, dict)
    ]


def _record_external_witness_refresh_status(
    state: dict[str, Any],
    *,
    ok: bool,
    detail: str,
    source_path: str = "",
    attempted_at: int | None = None,
) -> None:
    state["external_witness_refresh_attempted_at"] = _safe_int(
        attempted_at or time.time(),
        int(time.time()),
    )
    state["external_witness_refresh_ok"] = bool(ok)
    state["external_witness_refresh_detail"] = str(detail or "").strip()
    state["external_witness_refresh_source_path"] = str(source_path or "").strip()
    state["external_witness_refresh_source_ref"] = str(source_path or "").strip()


def _ensure_witness_identities(
    state: dict[str, Any],
    *,
    count: int = DEFAULT_ROOT_WITNESS_COUNT,
) -> tuple[list[dict[str, Any]], bool]:
    identities, changed = _normalize_witness_identities(
        state.get("witness_identities"),
        legacy_identity=dict(state.get("witness_identity") or {}),
    )
    target_count = max(1, int(count or DEFAULT_ROOT_WITNESS_COUNT))
    while len(identities) < target_count:
        identities.append(_witness_identity_record(index=len(identities) + 1))
        changed = True
    state["witness_identity"] = identities[0] if identities else _empty_witness_identity()
    state["witness_identities"] = identities
    return identities, changed


def _witness_policy(
    identities: list[dict[str, Any]],
    *,
    policy_version: int,
    threshold: int = DEFAULT_ROOT_WITNESS_THRESHOLD,
) -> dict[str, Any]:
    descriptors = [
        _public_witness_descriptor(identity)
        for identity in sorted(
            list(identities or []),
            key=lambda item: (
                str(item.get("node_id", "") or "").strip(),
                str(item.get("public_key", "") or "").strip(),
            ),
        )
        if str(identity.get("node_id", "") or "").strip() and str(identity.get("public_key", "") or "").strip()
    ]
    resolved_threshold = max(1, min(len(descriptors), int(threshold or DEFAULT_ROOT_WITNESS_THRESHOLD or 1)))
    return {
        "type": STABLE_DM_ROOT_MANIFEST_WITNESS_POLICY_TYPE,
        "policy_version": max(1, int(policy_version or 1)),
        "threshold": resolved_threshold,
        "witnesses": descriptors,
    }


def witness_policy_fingerprint(policy: dict[str, Any]) -> str:
    current = dict(policy or {})
    canonical = {
        "type": str(
            current.get("type", STABLE_DM_ROOT_MANIFEST_WITNESS_POLICY_TYPE)
            or STABLE_DM_ROOT_MANIFEST_WITNESS_POLICY_TYPE
        ),
        "policy_version": _safe_int(current.get("policy_version", 1) or 1, 1),
        "threshold": _safe_int(current.get("threshold", 0) or 0, 0),
        "witnesses": [
            {
                "scope": str(item.get("scope", "root_witness") or "root_witness"),
                "label": str(item.get("label", "") or ""),
                "node_id": str(item.get("node_id", "") or "").strip(),
                "public_key": str(item.get("public_key", "") or "").strip(),
                "public_key_algo": str(item.get("public_key_algo", "Ed25519") or "Ed25519"),
                "management_scope": _normalize_witness_management_scope(item.get("management_scope")),
                "independence_group": _normalize_witness_independence_group(
                    item.get("independence_group"),
                    management_scope=_normalize_witness_management_scope(item.get("management_scope")),
                ),
            }
            for item in list(current.get("witnesses") or [])
            if isinstance(item, dict)
        ],
    }
    return hashlib.sha256(_stable_json(canonical).encode("utf-8")).hexdigest()


def read_root_distribution_state() -> dict[str, Any]:
    raw = read_domain_json(
        ROOT_DISTRIBUTION_DOMAIN,
        ROOT_DISTRIBUTION_FILE,
        _default_state,
        base_dir=DATA_DIR,
    )
    state = {**_default_state(), **dict(raw or {})}
    state["witness_identity"] = {**_empty_witness_identity(), **dict(state.get("witness_identity") or {})}
    witness_identities, witness_changed = _normalize_witness_identities(
        state.get("witness_identities"),
        legacy_identity=dict(state.get("witness_identity") or {}),
    )
    state["witness_identities"] = witness_identities
    if witness_identities:
        state["witness_identity"] = witness_identities[0]
    elif witness_changed:
        state["witness_identity"] = _empty_witness_identity()
    external_witness_descriptors, external_changed = _normalize_external_witness_descriptors(
        state.get("external_witness_descriptors")
    )
    state["external_witness_descriptors"] = external_witness_descriptors
    state["external_witness_source_scope"] = str(state.get("external_witness_source_scope", "") or "").strip().lower()
    state["external_witness_source_label"] = str(state.get("external_witness_source_label", "") or "").strip()
    state["external_witness_imported_at"] = _safe_int(state.get("external_witness_imported_at", 0) or 0, 0)
    state["external_witness_source_exported_at"] = _safe_int(
        state.get("external_witness_source_exported_at", 0) or 0,
        0,
    )
    state["external_witness_refresh_attempted_at"] = _safe_int(
        state.get("external_witness_refresh_attempted_at", 0) or 0,
        0,
    )
    state["external_witness_refresh_ok"] = bool(state.get("external_witness_refresh_ok", False))
    state["external_witness_refresh_detail"] = str(state.get("external_witness_refresh_detail", "") or "").strip()
    state["external_witness_refresh_source_path"] = str(
        state.get("external_witness_refresh_source_path", "") or ""
    ).strip()
    state["external_witness_refresh_source_ref"] = str(
        state.get("external_witness_refresh_source_ref", state.get("external_witness_refresh_source_path", "")) or ""
    ).strip()
    state["external_witness_manifest_fingerprint"] = str(
        state.get("external_witness_manifest_fingerprint", "") or ""
    ).strip().lower()
    state["external_witness_receipts"] = [
        dict(item or {}) for item in list(state.get("external_witness_receipts") or []) if isinstance(item, dict)
    ]
    if not state["external_witness_manifest_fingerprint"]:
        state["external_witness_receipts"] = []
    if external_changed and not state["external_witness_descriptors"]:
        state["external_witness_manifest_fingerprint"] = ""
        state["external_witness_receipts"] = []
    state["published_manifest"] = dict(state.get("published_manifest") or {})
    state["published_witness"] = dict(state.get("published_witness") or {})
    state["published_witnesses"] = [
        dict(item or {}) for item in list(state.get("published_witnesses") or []) if isinstance(item, dict)
    ]
    if not state["published_witnesses"] and state["published_witness"]:
        state["published_witnesses"] = [dict(state["published_witness"] or {})]
    state["published_manifest_fingerprint"] = str(state.get("published_manifest_fingerprint", "") or "").strip().lower()
    return state


def _write_root_distribution_state(state: dict[str, Any]) -> dict[str, Any]:
    witness_identities, _ = _normalize_witness_identities(
        (state or {}).get("witness_identities"),
        legacy_identity=dict((state or {}).get("witness_identity") or {}),
    )
    published_witnesses = [
        dict(item or {})
        for item in list((state or {}).get("published_witnesses") or [])
        if isinstance(item, dict)
    ]
    external_witness_descriptors, _ = _normalize_external_witness_descriptors(
        (state or {}).get("external_witness_descriptors")
    )
    external_witness_manifest_fingerprint = str(
        (state or {}).get("external_witness_manifest_fingerprint", "") or ""
    ).strip().lower()
    external_witness_receipts = [
        dict(item or {})
        for item in list((state or {}).get("external_witness_receipts") or [])
        if isinstance(item, dict)
    ]
    if not external_witness_manifest_fingerprint:
        external_witness_receipts = []
    payload = {
        **_default_state(),
        **dict(state or {}),
        "updated_at": int(time.time()),
        "witness_identity": witness_identities[0] if witness_identities else _empty_witness_identity(),
        "witness_identities": witness_identities,
        "external_witness_descriptors": external_witness_descriptors,
        "external_witness_source_scope": str((state or {}).get("external_witness_source_scope", "") or "").strip().lower(),
        "external_witness_source_label": str((state or {}).get("external_witness_source_label", "") or "").strip(),
        "external_witness_imported_at": _safe_int((state or {}).get("external_witness_imported_at", 0) or 0, 0),
        "external_witness_source_exported_at": _safe_int(
            (state or {}).get("external_witness_source_exported_at", 0) or 0,
            0,
        ),
        "external_witness_refresh_attempted_at": _safe_int(
            (state or {}).get("external_witness_refresh_attempted_at", 0) or 0,
            0,
        ),
        "external_witness_refresh_ok": bool((state or {}).get("external_witness_refresh_ok", False)),
        "external_witness_refresh_detail": str(
            (state or {}).get("external_witness_refresh_detail", "") or ""
        ).strip(),
        "external_witness_refresh_source_path": str(
            (state or {}).get("external_witness_refresh_source_path", "") or ""
        ).strip(),
        "external_witness_refresh_source_ref": str(
            (state or {}).get(
                "external_witness_refresh_source_ref",
                (state or {}).get("external_witness_refresh_source_path", ""),
            )
            or ""
        ).strip(),
        "external_witness_manifest_fingerprint": external_witness_manifest_fingerprint,
        "external_witness_receipts": external_witness_receipts,
        "published_manifest": dict((state or {}).get("published_manifest") or {}),
        "published_witness": dict(published_witnesses[0] or {}) if published_witnesses else {},
        "published_witnesses": published_witnesses,
        "published_manifest_fingerprint": str(
            (state or {}).get("published_manifest_fingerprint", "") or ""
        ).strip().lower(),
    }
    write_domain_json(
        ROOT_DISTRIBUTION_DOMAIN,
        ROOT_DISTRIBUTION_FILE,
        payload,
        base_dir=DATA_DIR,
    )
    return payload


def _current_root_view() -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    root_identity = get_root_identity()
    return {
        "root_node_id": str(root_identity.get("node_id", "") or "").strip(),
        "root_public_key": str(root_identity.get("public_key", "") or "").strip(),
        "root_public_key_algo": str(root_identity.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": str(root_identity.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
    }


def manifest_fingerprint_for_envelope(manifest: dict[str, Any]) -> str:
    envelope = dict(manifest or {})
    canonical = {
        "type": str(envelope.get("type", STABLE_DM_ROOT_MANIFEST_TYPE) or STABLE_DM_ROOT_MANIFEST_TYPE),
        "event_type": str(
            envelope.get("event_type", STABLE_DM_ROOT_MANIFEST_EVENT_TYPE) or STABLE_DM_ROOT_MANIFEST_EVENT_TYPE
        ),
        "node_id": str(envelope.get("node_id", "") or "").strip(),
        "public_key": str(envelope.get("public_key", "") or "").strip(),
        "public_key_algo": str(envelope.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": str(envelope.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        "sequence": _safe_int(envelope.get("sequence", 0) or 0, 0),
        "payload": dict(envelope.get("payload") or {}),
        "signature": str(envelope.get("signature", "") or "").strip(),
    }
    return hashlib.sha256(_stable_json(canonical).encode("utf-8")).hexdigest()


def _manifest_payload(
    *,
    current_root: dict[str, Any],
    previous_manifest: dict[str, Any] | None = None,
    issued_at: int,
    expires_at: int,
    policy_version: int,
    witness_policy: dict[str, Any],
) -> dict[str, Any]:
    current_root_node_id = str(current_root.get("root_node_id", "") or "").strip()
    current_root_public_key = str(current_root.get("root_public_key", "") or "").strip()
    current_root_public_key_algo = str(current_root.get("root_public_key_algo", "Ed25519") or "Ed25519")
    protocol_version = str(current_root.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION)
    current_root_fingerprint = root_identity_fingerprint_for_material(
        root_node_id=current_root_node_id,
        root_public_key=current_root_public_key,
        root_public_key_algo=current_root_public_key_algo,
        protocol_version=protocol_version,
    )
    current_witness_policy_fingerprint = witness_policy_fingerprint(dict(witness_policy or {})) if witness_policy else ""
    previous_payload = dict((previous_manifest or {}).get("payload") or {})
    previous_generation = _safe_int(previous_payload.get("generation", 0) or 0, 0)
    previous_manifest_root_fingerprint = str(previous_payload.get("root_fingerprint", "") or "").strip().lower()
    previous_manifest_witness_policy = dict(previous_payload.get("witness_policy") or {})
    previous_manifest_witness_policy_fingerprint = (
        witness_policy_fingerprint(previous_manifest_witness_policy) if previous_manifest_witness_policy else ""
    )
    if not previous_manifest_root_fingerprint and previous_payload:
        previous_manifest_root_fingerprint = root_identity_fingerprint_for_material(
            root_node_id=str(previous_payload.get("root_node_id", "") or "").strip(),
            root_public_key=str(previous_payload.get("root_public_key", "") or "").strip(),
            root_public_key_algo=str(previous_payload.get("root_public_key_algo", "Ed25519") or "Ed25519"),
            protocol_version=str(previous_payload.get("protocol_version", protocol_version) or protocol_version),
        )
    if previous_manifest_root_fingerprint == current_root_fingerprint:
        generation = max(1, previous_generation or 1)
        previous_root_fingerprint = str(previous_payload.get("previous_root_fingerprint", "") or "").strip().lower()
        previous_root_node_id = str(previous_payload.get("previous_root_node_id", "") or "").strip()
        previous_root_public_key = str(previous_payload.get("previous_root_public_key", "") or "").strip()
        previous_root_public_key_algo = str(
            previous_payload.get("previous_root_public_key_algo", "Ed25519") or "Ed25519"
        ).strip()
        previous_root_protocol_version = str(
            previous_payload.get("previous_root_protocol_version", protocol_version) or protocol_version
        ).strip()
        previous_root_cross_sequence = _safe_int(previous_payload.get("previous_root_cross_sequence", 0) or 0, 0)
        previous_root_cross_signature = str(previous_payload.get("previous_root_cross_signature", "") or "").strip()
        if (
            previous_manifest_witness_policy_fingerprint
            and previous_manifest_witness_policy_fingerprint != current_witness_policy_fingerprint
        ):
            previous_witness_policy_fingerprint = previous_manifest_witness_policy_fingerprint
            previous_witness_policy_sequence = 0
            previous_witness_policy_signature = ""
        else:
            previous_witness_policy_fingerprint = str(
                previous_payload.get("previous_witness_policy_fingerprint", "") or ""
            ).strip().lower()
            previous_witness_policy_sequence = _safe_int(
                previous_payload.get("previous_witness_policy_sequence", 0) or 0,
                0,
            )
            previous_witness_policy_signature = str(
                previous_payload.get("previous_witness_policy_signature", "") or ""
            ).strip()
    else:
        generation = max(1, previous_generation + 1)
        previous_root_fingerprint = previous_manifest_root_fingerprint
        previous_root_node_id = str(previous_payload.get("root_node_id", "") or "").strip()
        previous_root_public_key = str(previous_payload.get("root_public_key", "") or "").strip()
        previous_root_public_key_algo = str(previous_payload.get("root_public_key_algo", "Ed25519") or "Ed25519").strip()
        previous_root_protocol_version = str(previous_payload.get("protocol_version", protocol_version) or protocol_version)
        previous_root_cross_sequence = 0
        previous_root_cross_signature = ""
        previous_witness_policy_fingerprint = ""
        previous_witness_policy_sequence = 0
        previous_witness_policy_signature = ""
    return {
        "root_node_id": current_root_node_id,
        "root_public_key": current_root_public_key,
        "root_public_key_algo": current_root_public_key_algo,
        "root_fingerprint": current_root_fingerprint,
        "protocol_version": protocol_version,
        "generation": generation,
        "issued_at": int(issued_at or 0),
        "expires_at": int(expires_at or 0),
        "previous_root_fingerprint": previous_root_fingerprint,
        "previous_root_node_id": previous_root_node_id,
        "previous_root_public_key": previous_root_public_key,
        "previous_root_public_key_algo": previous_root_public_key_algo,
        "previous_root_protocol_version": previous_root_protocol_version,
        "previous_root_cross_sequence": previous_root_cross_sequence,
        "previous_root_cross_signature": previous_root_cross_signature,
        "previous_witness_policy_fingerprint": previous_witness_policy_fingerprint,
        "previous_witness_policy_sequence": previous_witness_policy_sequence,
        "previous_witness_policy_signature": previous_witness_policy_signature,
        "policy_version": _safe_int(policy_version or 1, 1),
        "witness_policy": dict(witness_policy or {}),
    }


def _previous_root_cross_payload(payload: dict[str, Any]) -> dict[str, Any]:
    current = dict(payload or {})
    return {
        "manifest_type": STABLE_DM_ROOT_MANIFEST_TYPE,
        "manifest_event_type": STABLE_DM_ROOT_MANIFEST_EVENT_TYPE,
        "root_node_id": str(current.get("root_node_id", "") or "").strip(),
        "root_public_key": str(current.get("root_public_key", "") or "").strip(),
        "root_public_key_algo": str(current.get("root_public_key_algo", "Ed25519") or "Ed25519").strip(),
        "root_fingerprint": str(current.get("root_fingerprint", "") or "").strip().lower(),
        "protocol_version": str(current.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip(),
        "generation": _safe_int(current.get("generation", 0) or 0, 0),
        "issued_at": _safe_int(current.get("issued_at", 0) or 0, 0),
        "expires_at": _safe_int(current.get("expires_at", 0) or 0, 0),
        "previous_root_fingerprint": str(current.get("previous_root_fingerprint", "") or "").strip().lower(),
        "policy_version": _safe_int(current.get("policy_version", 1) or 1, 1),
    }


def _previous_witness_policy_change_payload(payload: dict[str, Any]) -> dict[str, Any]:
    current = dict(payload or {})
    witness_policy = dict(current.get("witness_policy") or {})
    return {
        "manifest_type": STABLE_DM_ROOT_MANIFEST_TYPE,
        "manifest_event_type": STABLE_DM_ROOT_MANIFEST_EVENT_TYPE,
        "root_node_id": str(current.get("root_node_id", "") or "").strip(),
        "root_public_key": str(current.get("root_public_key", "") or "").strip(),
        "root_public_key_algo": str(current.get("root_public_key_algo", "Ed25519") or "Ed25519").strip(),
        "root_fingerprint": str(current.get("root_fingerprint", "") or "").strip().lower(),
        "protocol_version": str(current.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip(),
        "generation": _safe_int(current.get("generation", 0) or 0, 0),
        "issued_at": _safe_int(current.get("issued_at", 0) or 0, 0),
        "expires_at": _safe_int(current.get("expires_at", 0) or 0, 0),
        "policy_version": _safe_int(current.get("policy_version", 1) or 1, 1),
        "witness_policy_fingerprint": witness_policy_fingerprint(witness_policy) if witness_policy else "",
        "previous_witness_policy_fingerprint": str(
            current.get("previous_witness_policy_fingerprint", "") or ""
        ).strip().lower(),
    }


def _touch(identity: dict[str, Any]) -> None:
    identity["last_used_at"] = int(time.time())


def _next_sequence(identity: dict[str, Any], sequence: int | None = None) -> int:
    if sequence is None:
        next_value = _safe_int(identity.get("sequence", 0) or 0, 0) + 1
    else:
        next_value = max(_safe_int(identity.get("sequence", 0) or 0, 0), int(sequence))
    identity["sequence"] = next_value
    _touch(identity)
    return next_value


def _sign_with_witness_identity(
    *,
    identity: dict[str, Any],
    event_type: str,
    payload: dict[str, Any],
    sequence: int | None = None,
) -> dict[str, Any]:
    signed_sequence = _next_sequence(identity, sequence)
    payload_str = build_signature_payload(
        event_type=event_type,
        node_id=str(identity.get("node_id", "") or ""),
        sequence=signed_sequence,
        payload=dict(payload or {}),
    )
    signing_priv = ed25519.Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(str(identity.get("private_key", "") or "").encode("ascii"))
    )
    signature = signing_priv.sign(payload_str.encode("utf-8")).hex()
    return {
        "type": STABLE_DM_ROOT_MANIFEST_WITNESS_TYPE,
        "event_type": event_type,
        "node_id": str(identity.get("node_id", "") or ""),
        "public_key": str(identity.get("public_key", "") or ""),
        "public_key_algo": str(identity.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": PROTOCOL_VERSION,
        "sequence": signed_sequence,
        "payload": dict(payload or {}),
        "signature": signature,
        "identity_scope": "root_witness",
    }


def _witness_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = dict((manifest or {}).get("payload") or {})
    witness_policy = dict(payload.get("witness_policy") or {})
    return {
        "manifest_type": str((manifest or {}).get("type", STABLE_DM_ROOT_MANIFEST_TYPE) or STABLE_DM_ROOT_MANIFEST_TYPE),
        "manifest_event_type": str(
            (manifest or {}).get("event_type", STABLE_DM_ROOT_MANIFEST_EVENT_TYPE) or STABLE_DM_ROOT_MANIFEST_EVENT_TYPE
        ),
        "manifest_fingerprint": manifest_fingerprint_for_envelope(manifest),
        "root_fingerprint": str(payload.get("root_fingerprint", "") or "").strip().lower(),
        "root_node_id": str(payload.get("root_node_id", "") or "").strip(),
        "generation": _safe_int(payload.get("generation", 0) or 0, 0),
        "issued_at": _safe_int(payload.get("issued_at", 0) or 0, 0),
        "expires_at": _safe_int(payload.get("expires_at", 0) or 0, 0),
        "policy_version": _safe_int(payload.get("policy_version", 1) or 1, 1),
        "witness_policy_fingerprint": witness_policy_fingerprint(witness_policy) if witness_policy else "",
        "witness_threshold": _safe_int(witness_policy.get("threshold", 0) or 0, 0),
    }


def _verify_witness_policy(policy: dict[str, Any]) -> dict[str, Any]:
    current = dict(policy or {})
    if str(current.get("type", STABLE_DM_ROOT_MANIFEST_WITNESS_POLICY_TYPE) or STABLE_DM_ROOT_MANIFEST_WITNESS_POLICY_TYPE) != STABLE_DM_ROOT_MANIFEST_WITNESS_POLICY_TYPE:
        return {"ok": False, "detail": "stable root manifest witness policy type invalid"}
    policy_version = _safe_int(current.get("policy_version", 0) or 0, 0)
    if policy_version <= 0:
        return {"ok": False, "detail": "stable root manifest witness policy version required"}
    witnesses: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in list(current.get("witnesses") or []):
        if not isinstance(item, dict):
            continue
        descriptor = _public_witness_descriptor(item)
        if not descriptor["node_id"] or not descriptor["public_key"]:
            return {"ok": False, "detail": "stable root manifest witness policy witness incomplete"}
        if not verify_node_binding(descriptor["node_id"], descriptor["public_key"]):
            return {"ok": False, "detail": "stable root manifest witness policy witness binding invalid"}
        if not descriptor["independence_group"]:
            return {"ok": False, "detail": "stable root manifest witness policy witness independence group invalid"}
        key = (descriptor["node_id"], descriptor["public_key"])
        if key in seen:
            return {"ok": False, "detail": "stable root manifest witness policy witness duplicated"}
        seen.add(key)
        witnesses.append(descriptor)
    if not witnesses:
        return {"ok": False, "detail": "stable root manifest witness policy witnesses required"}
    threshold = _safe_int(current.get("threshold", 0) or 0, 0)
    if threshold <= 0 or threshold > len(witnesses):
        return {"ok": False, "detail": "stable root manifest witness policy threshold invalid"}
    normalized = {
        "type": STABLE_DM_ROOT_MANIFEST_WITNESS_POLICY_TYPE,
        "policy_version": policy_version,
        "threshold": threshold,
        "witnesses": sorted(
            witnesses,
            key=lambda item: (item["node_id"], item["public_key"]),
        ),
    }
    return {
        "ok": True,
        "policy": normalized,
        "policy_fingerprint": witness_policy_fingerprint(normalized),
        "threshold": threshold,
        "witness_count": len(normalized["witnesses"]),
    }


def publish_current_root_manifest(
    *,
    expires_in_s: int = DEFAULT_ROOT_MANIFEST_TTL_S,
    policy_version: int = 1,
) -> dict[str, Any]:
    state = read_root_distribution_state()
    witness_identities, _ = _ensure_witness_identities(state)
    witness_descriptors = _configured_witness_descriptors(state, witness_identities)
    witness_policy = _witness_policy(witness_descriptors, policy_version=policy_version)
    current_root = _current_root_view()
    now = int(time.time())
    ttl_s = max(1, _safe_int(expires_in_s or DEFAULT_ROOT_MANIFEST_TTL_S, DEFAULT_ROOT_MANIFEST_TTL_S))
    manifest_payload = _manifest_payload(
        current_root=current_root,
        previous_manifest=dict(state.get("published_manifest") or {}),
        issued_at=now,
        expires_at=now + ttl_s,
        policy_version=policy_version,
        witness_policy=witness_policy,
    )
    current_root_fingerprint = str(manifest_payload.get("root_fingerprint", "") or "").strip().lower()
    previous_root_fingerprint = str(manifest_payload.get("previous_root_fingerprint", "") or "").strip().lower()
    if previous_root_fingerprint and previous_root_fingerprint != current_root_fingerprint:
        previous_root_identity = read_previous_root_identity()
        previous_root_identity_fingerprint = root_identity_fingerprint_for_material(
            root_node_id=str(previous_root_identity.get("node_id", "") or "").strip(),
            root_public_key=str(previous_root_identity.get("public_key", "") or "").strip(),
            root_public_key_algo=str(previous_root_identity.get("public_key_algo", "Ed25519") or "Ed25519"),
            protocol_version=str(previous_root_identity.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        )
        if previous_root_identity_fingerprint == previous_root_fingerprint:
            previous_signed = sign_previous_root_wormhole_event(
                event_type=STABLE_DM_ROOT_MANIFEST_PREVIOUS_ROOT_EVENT_TYPE,
                payload=_previous_root_cross_payload(manifest_payload),
            )
            if previous_signed.get("ok"):
                manifest_payload["previous_root_node_id"] = str(previous_signed.get("node_id", "") or "").strip()
                manifest_payload["previous_root_public_key"] = str(previous_signed.get("public_key", "") or "").strip()
                manifest_payload["previous_root_public_key_algo"] = str(
                    previous_signed.get("public_key_algo", "Ed25519") or "Ed25519"
                ).strip()
                manifest_payload["previous_root_protocol_version"] = str(
                    previous_signed.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION
                ).strip()
                manifest_payload["previous_root_cross_sequence"] = _safe_int(
                    previous_signed.get("sequence", 0) or 0,
                    0,
                )
                manifest_payload["previous_root_cross_signature"] = str(
                    previous_signed.get("signature", "") or ""
                ).strip()
    current_policy_fingerprint = witness_policy_fingerprint(dict(manifest_payload.get("witness_policy") or {}))
    previous_policy_fingerprint = str(
        manifest_payload.get("previous_witness_policy_fingerprint", "") or ""
    ).strip().lower()
    if previous_policy_fingerprint and previous_policy_fingerprint != current_policy_fingerprint:
        previous_policy_signed = sign_root_wormhole_event(
            event_type=STABLE_DM_ROOT_MANIFEST_POLICY_CHANGE_EVENT_TYPE,
            payload=_previous_witness_policy_change_payload(manifest_payload),
        )
        manifest_payload["previous_witness_policy_sequence"] = _safe_int(
            previous_policy_signed.get("sequence", 0) or 0,
            0,
        )
        manifest_payload["previous_witness_policy_signature"] = str(
            previous_policy_signed.get("signature", "") or ""
        ).strip()
    signed_manifest = sign_root_wormhole_event(
        event_type=STABLE_DM_ROOT_MANIFEST_EVENT_TYPE,
        payload=manifest_payload,
    )
    manifest = {
        "type": STABLE_DM_ROOT_MANIFEST_TYPE,
        "event_type": STABLE_DM_ROOT_MANIFEST_EVENT_TYPE,
        "node_id": str(signed_manifest.get("node_id", "") or "").strip(),
        "public_key": str(signed_manifest.get("public_key", "") or "").strip(),
        "public_key_algo": str(signed_manifest.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": str(signed_manifest.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        "sequence": _safe_int(signed_manifest.get("sequence", 0) or 0, 0),
        "payload": dict(signed_manifest.get("payload") or {}),
        "signature": str(signed_manifest.get("signature", "") or "").strip(),
        "identity_scope": str(signed_manifest.get("identity_scope", "root") or "root"),
    }
    manifest_fingerprint = manifest_fingerprint_for_envelope(manifest)
    witnesses = [
        _sign_with_witness_identity(
            identity=identity,
            event_type=STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
            payload=_witness_payload(manifest),
        )
        for identity in witness_identities
    ]
    witness_policy_verified = _verify_witness_policy(witness_policy)
    witness_verified = verify_root_manifest_witness_set(manifest, witnesses)
    state["witness_identity"] = witness_identities[0] if witness_identities else _empty_witness_identity()
    state["witness_identities"] = witness_identities
    state["external_witness_manifest_fingerprint"] = ""
    state["external_witness_receipts"] = []
    state["published_manifest"] = manifest
    state["published_manifest_fingerprint"] = manifest_fingerprint
    state["published_witness"] = dict(witnesses[0] or {}) if witnesses else {}
    state["published_witnesses"] = witnesses
    _write_root_distribution_state(state)
    operator_status = _external_witness_operator_status(
        state,
        manifest_fingerprint=manifest_fingerprint,
        external_witnesses=[],
    )
    return {
        "ok": True,
        "manifest": manifest,
        "manifest_fingerprint": manifest_fingerprint,
        "witness": dict(witnesses[0] or {}) if witnesses else {},
        "witnesses": witnesses,
        "witness_identity": _public_witness_identity(witness_identities[0]) if witness_identities else _empty_witness_identity(),
        "witness_identities": [_public_witness_identity(item) for item in witness_identities],
        "external_witness_descriptors": list(state.get("external_witness_descriptors") or []),
        "external_witness_source_scope": str(state.get("external_witness_source_scope", "") or "").strip().lower(),
        "external_witness_source_label": str(state.get("external_witness_source_label", "") or "").strip(),
        "external_witness_imported_at": _safe_int(state.get("external_witness_imported_at", 0) or 0, 0),
        "external_witness_source_exported_at": _safe_int(
            state.get("external_witness_source_exported_at", 0) or 0,
            0,
        ),
        "external_witness_refresh_attempted_at": _safe_int(
            state.get("external_witness_refresh_attempted_at", 0) or 0,
            0,
        ),
        "external_witness_refresh_ok": bool(state.get("external_witness_refresh_ok", False)),
        "external_witness_refresh_detail": str(state.get("external_witness_refresh_detail", "") or "").strip(),
        "external_witness_refresh_source_path": str(
            state.get("external_witness_refresh_source_path", "") or ""
        ).strip(),
        "external_witness_refresh_source_ref": str(
            state.get("external_witness_refresh_source_ref", state.get("external_witness_refresh_source_path", ""))
            or ""
        ).strip(),
        "external_witness_receipt_count": 0,
        "external_witness_receipts_current": False,
        **operator_status,
        "witness_policy": dict(witness_policy_verified.get("policy") or witness_policy),
        "witness_policy_fingerprint": str(witness_policy_verified.get("policy_fingerprint", "") or "").strip().lower(),
        "witness_threshold": _safe_int(witness_policy_verified.get("threshold", 0) or 0, 0),
        "witness_count": _safe_int(witness_policy_verified.get("witness_count", 0) or 0, 0),
        "witness_domain_count": _safe_int(witness_verified.get("witness_domain_count", 0) or 0, 0),
        "witness_independent_quorum_met": bool(witness_verified.get("witness_independent_quorum_met")),
        "witness_finality_met": bool(witness_verified.get("witness_finality_met")),
        "root_fingerprint": str(manifest_payload.get("root_fingerprint", "") or "").strip().lower(),
        "generation": _safe_int(manifest_payload.get("generation", 0) or 0, 0),
        "rotation_proven": bool(
            _safe_int(manifest_payload.get("generation", 0) or 0, 0) <= 1
            or str(manifest_payload.get("previous_root_cross_signature", "") or "").strip()
        ),
        "policy_change_proven": bool(
            not str(manifest_payload.get("previous_witness_policy_fingerprint", "") or "").strip()
            or str(manifest_payload.get("previous_witness_policy_signature", "") or "").strip()
        ),
    }


def _manifest_expired(manifest: dict[str, Any], *, now: int | None = None) -> bool:
    payload = dict((manifest or {}).get("payload") or {})
    expires_at = _safe_int(payload.get("expires_at", 0) or 0, 0)
    if expires_at <= 0:
        return False
    current_time = _safe_int(now or time.time(), int(time.time()))
    return expires_at <= current_time


def _external_witness_source_exported_at(material: dict[str, Any] | None) -> int:
    return _safe_int(dict(material or {}).get("exported_at", 0) or 0, 0)


def _external_witness_source_age_s(exported_at: int, *, now: int | None = None) -> int:
    if exported_at <= 0:
        return 0
    current_time = _safe_int(now or time.time(), int(time.time()))
    return max(0, current_time - exported_at)


def _external_witness_source_stale(exported_at: int, *, now: int | None = None) -> bool:
    max_age_s = _external_root_witness_max_age_s()
    if max_age_s <= 0:
        return False
    if exported_at <= 0:
        return True
    return _external_witness_source_age_s(exported_at, now=now) > max_age_s


def _external_witness_operator_status(
    state: dict[str, Any],
    *,
    manifest_fingerprint: str,
    external_witnesses: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    source_ref = _configured_external_root_witness_source_ref()
    descriptors = [dict(item or {}) for item in list(state.get("external_witness_descriptors") or []) if isinstance(item, dict)]
    source_configured = bool(source_ref or descriptors)
    source_refresh_configured = bool(source_ref)
    attempted_at = _safe_int(state.get("external_witness_refresh_attempted_at", 0) or 0, 0)
    now = int(time.time())
    refresh_age_s = max(0, now - attempted_at) if attempted_at > 0 else 0
    source_exported_at = _safe_int(state.get("external_witness_source_exported_at", 0) or 0, 0)
    source_age_s = _external_witness_source_age_s(source_exported_at, now=now)
    stored_manifest_fingerprint = str(state.get("external_witness_manifest_fingerprint", "") or "").strip().lower()
    manifest_matches_current = bool(
        stored_manifest_fingerprint and manifest_fingerprint and stored_manifest_fingerprint == manifest_fingerprint
    )
    receipts_current = bool(list(external_witnesses or []))
    refresh_ok = bool(state.get("external_witness_refresh_ok", False))
    refresh_detail = str(state.get("external_witness_refresh_detail", "") or "").strip().lower()
    refresh_failed = bool(source_refresh_configured and attempted_at > 0 and not refresh_ok)
    stale_refresh = bool(
        refresh_failed
        and any(
            marker in refresh_detail
            for marker in (
                "manifest_fingerprint mismatch",
                "waiting for current-manifest receipts",
                "source stale",
            )
        )
    )
    if refresh_failed and not stale_refresh:
        operator_state = "error"
    elif stale_refresh:
        operator_state = "stale"
    elif receipts_current:
        operator_state = "current"
    elif descriptors and not stored_manifest_fingerprint and refresh_ok:
        operator_state = "descriptors_only"
    elif descriptors:
        operator_state = "stale"
    elif not source_configured:
        operator_state = "not_configured"
    elif not refresh_ok:
        operator_state = "error"
    else:
        operator_state = "stale"
    return {
        "external_witness_source_configured": source_configured,
        "external_witness_operator_state": operator_state,
        "external_witness_refresh_age_s": refresh_age_s,
        "external_witness_source_exported_at": source_exported_at,
        "external_witness_source_age_s": source_age_s,
        "external_witness_freshness_window_s": _external_root_witness_max_age_s(),
        "external_witness_manifest_fingerprint": stored_manifest_fingerprint,
        "external_witness_manifest_matches_current": manifest_matches_current,
        "external_witness_reacquire_required": bool(
            source_configured and (not receipts_current or refresh_failed or operator_state == "stale")
        ),
    }


def get_current_root_manifest() -> dict[str, Any]:
    state = read_root_distribution_state()
    _refresh_external_root_witness_material_from_source(
        state,
        manifest=dict(state.get("published_manifest") or {}),
    )
    state = read_root_distribution_state()
    manifest = dict(state.get("published_manifest") or {})
    local_witnesses = [dict(item or {}) for item in list(state.get("published_witnesses") or []) if isinstance(item, dict)]
    local_witness = dict(local_witnesses[0] or {}) if local_witnesses else dict(state.get("published_witness") or {})
    current_root = _current_root_view()
    current_root_fingerprint = root_identity_fingerprint_for_material(
        root_node_id=str(current_root.get("root_node_id", "") or "").strip(),
        root_public_key=str(current_root.get("root_public_key", "") or "").strip(),
        root_public_key_algo=str(current_root.get("root_public_key_algo", "Ed25519") or "Ed25519"),
        protocol_version=str(current_root.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
    )
    manifest_payload = dict(manifest.get("payload") or {})
    manifest_root_fingerprint = str(manifest_payload.get("root_fingerprint", "") or "").strip().lower()
    manifest_fingerprint = str(state.get("published_manifest_fingerprint", "") or "").strip().lower()
    if not manifest_fingerprint and manifest:
        manifest_fingerprint = manifest_fingerprint_for_envelope(manifest)
    external_witnesses = _current_external_witness_receipts(
        state,
        manifest_fingerprint=manifest_fingerprint,
    )
    operator_status = _external_witness_operator_status(
        state,
        manifest_fingerprint=manifest_fingerprint,
        external_witnesses=external_witnesses,
    )
    witnesses = [*local_witnesses, *external_witnesses]
    witness = dict(witnesses[0] or {}) if witnesses else local_witness
    manifest_verified = verify_root_manifest(manifest)
    witness_verified = verify_root_manifest_witness_set(manifest, witnesses)
    manifest_valid = bool(manifest_verified.get("ok")) and bool(witness_verified.get("ok"))
    witness_identities, _ = _ensure_witness_identities(state)
    witness_ready = bool(witness_identities)
    desired_policy = _witness_policy(
        _configured_witness_descriptors(state, witness_identities),
        policy_version=_safe_int(manifest_payload.get("policy_version", 1) or 1, 1),
    )
    desired_policy_fingerprint = witness_policy_fingerprint(desired_policy)
    current_policy_fingerprint = str(manifest_payload.get("witness_policy") or "")
    if isinstance(manifest_payload.get("witness_policy"), dict):
        current_policy_fingerprint = witness_policy_fingerprint(dict(manifest_payload.get("witness_policy") or {}))
    if (
        not manifest
        or not witnesses
        or not witness_ready
        or not manifest_valid
        or current_policy_fingerprint != desired_policy_fingerprint
        or (
            _safe_int(manifest_verified.get("generation", 0) or 0, 0) > 1
            and not bool(manifest_verified.get("rotation_proven"))
        )
        or (
            str(manifest_verified.get("previous_witness_policy_fingerprint", "") or "").strip()
            and not bool(manifest_verified.get("policy_change_proven"))
        )
        or _manifest_expired(manifest)
        or manifest_root_fingerprint != current_root_fingerprint
    ):
        return publish_current_root_manifest()
    return {
        "ok": True,
        "manifest": manifest,
        "manifest_fingerprint": manifest_fingerprint or manifest_fingerprint_for_envelope(manifest),
        "witness": witness,
        "witnesses": witnesses,
        "witness_identity": _public_witness_identity(witness_identities[0]) if witness_identities else _empty_witness_identity(),
        "witness_identities": [_public_witness_identity(item) for item in witness_identities],
        "external_witness_descriptors": list(state.get("external_witness_descriptors") or []),
        "external_witness_source_scope": str(state.get("external_witness_source_scope", "") or "").strip().lower(),
        "external_witness_source_label": str(state.get("external_witness_source_label", "") or "").strip(),
        "external_witness_imported_at": _safe_int(state.get("external_witness_imported_at", 0) or 0, 0),
        "external_witness_source_exported_at": _safe_int(
            state.get("external_witness_source_exported_at", 0) or 0,
            0,
        ),
        "external_witness_refresh_attempted_at": _safe_int(
            state.get("external_witness_refresh_attempted_at", 0) or 0,
            0,
        ),
        "external_witness_refresh_ok": bool(state.get("external_witness_refresh_ok", False)),
        "external_witness_refresh_detail": str(state.get("external_witness_refresh_detail", "") or "").strip(),
        "external_witness_refresh_source_path": str(
            state.get("external_witness_refresh_source_path", "") or ""
        ).strip(),
        "external_witness_refresh_source_ref": str(
            state.get("external_witness_refresh_source_ref", state.get("external_witness_refresh_source_path", ""))
            or ""
        ).strip(),
        "external_witness_receipt_count": len(external_witnesses),
        "external_witness_receipts_current": bool(external_witnesses),
        **operator_status,
        "witness_policy": dict(manifest_verified.get("witness_policy") or {}),
        "witness_policy_fingerprint": str(manifest_verified.get("witness_policy_fingerprint", "") or "").strip().lower(),
        "witness_threshold": _safe_int(manifest_verified.get("witness_threshold", 0) or 0, 0),
        "witness_count": _safe_int(witness_verified.get("witness_count", 0) or 0, 0),
        "witness_domain_count": _safe_int(witness_verified.get("witness_domain_count", 0) or 0, 0),
        "witness_independent_quorum_met": bool(witness_verified.get("witness_independent_quorum_met")),
        "witness_finality_met": bool(witness_verified.get("witness_finality_met")),
        "root_fingerprint": manifest_root_fingerprint,
        "generation": _safe_int(manifest_verified.get("generation", 0) or 0, 0),
        "rotation_proven": bool(manifest_verified.get("rotation_proven")),
        "policy_change_proven": bool(manifest_verified.get("policy_change_proven")),
    }


def configure_external_root_witness_descriptors(descriptors: list[dict[str, Any]] | None) -> dict[str, Any]:
    state = read_root_distribution_state()
    normalized, _ = _normalize_external_witness_descriptors(descriptors)
    state["external_witness_descriptors"] = normalized
    state["external_witness_source_exported_at"] = 0
    state["external_witness_manifest_fingerprint"] = ""
    state["external_witness_receipts"] = []
    written = _write_root_distribution_state(state)
    return {
        "ok": True,
        "external_witness_descriptors": list(written.get("external_witness_descriptors") or []),
        "external_witness_count": len(list(written.get("external_witness_descriptors") or [])),
    }


def _configured_external_root_witness_source_ref(path: str | None = None) -> str:
    from services.config import get_settings

    explicit = str(path or "").strip()
    if explicit:
        return explicit
    settings = get_settings()
    configured_uri = str(getattr(settings, "MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", "") or "").strip()
    if configured_uri:
        return configured_uri
    return str(getattr(settings, "MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_PATH", "") or "").strip()


def _read_external_root_witness_material_package(path: str | None = None) -> dict[str, Any]:
    configured_ref = _configured_external_root_witness_source_ref(path)
    if "://" in configured_ref:
        if not configured_ref:
            return {"ok": False, "detail": "external root witness import source not configured"}
        try:
            with urllib.request.urlopen(configured_ref, timeout=10) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError:
            return {
                "ok": False,
                "detail": "external root witness import source unreadable",
                "source_ref": configured_ref,
                "path": "",
            }
        except json.JSONDecodeError:
            return {
                "ok": False,
                "detail": "external root witness import source invalid",
                "source_ref": configured_ref,
                "path": "",
            }
        except OSError:
            return {
                "ok": False,
                "detail": "external root witness import source unreadable",
                "source_ref": configured_ref,
                "path": "",
            }
        if not isinstance(raw, dict):
            return {
                "ok": False,
                "detail": "external root witness import source root must be an object",
                "source_ref": configured_ref,
                "path": "",
            }
        return {
            "ok": True,
            "path": "",
            "source_ref": configured_ref,
            "material": dict(raw or {}),
        }

    resolved_path = _resolve_external_material_path(configured_ref)
    if resolved_path is None:
        return {"ok": False, "detail": "external root witness import path not configured", "source_ref": ""}
    try:
        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "ok": False,
            "detail": "external root witness import path not found",
            "path": str(resolved_path),
            "source_ref": str(resolved_path),
        }
    except json.JSONDecodeError:
        return {
            "ok": False,
            "detail": "external root witness import file invalid",
            "path": str(resolved_path),
            "source_ref": str(resolved_path),
        }
    except OSError:
        return {
            "ok": False,
            "detail": "external root witness import path unreadable",
            "path": str(resolved_path),
            "source_ref": str(resolved_path),
        }
    if not isinstance(raw, dict):
        return {
            "ok": False,
            "detail": "external root witness import file root must be an object",
            "path": str(resolved_path),
            "source_ref": str(resolved_path),
        }
    return {
        "ok": True,
        "path": str(resolved_path),
        "source_ref": str(resolved_path),
        "material": dict(raw or {}),
    }


def _stage_external_witness_receipts_into_state(
    state: dict[str, Any],
    *,
    manifest: dict[str, Any],
    candidate_receipts: list[dict[str, Any]] | None,
    merge_existing: bool,
) -> dict[str, Any]:
    current_manifest = dict(manifest or {})
    current_manifest_fingerprint = manifest_fingerprint_for_envelope(current_manifest) if current_manifest else ""
    if not current_manifest_fingerprint:
        return {"ok": False, "detail": "stable root manifest required"}
    local_witnesses = [
        dict(item or {}) for item in list(state.get("published_witnesses") or []) if isinstance(item, dict)
    ]
    existing_external = (
        _current_external_witness_receipts(state, manifest_fingerprint=current_manifest_fingerprint) if merge_existing else []
    )
    merged_external: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for receipt in [*existing_external, *list(candidate_receipts or [])]:
        verified = verify_root_manifest_witness(current_manifest, dict(receipt or {}))
        if not verified.get("ok"):
            continue
        if str(verified.get("witness_management_scope", "") or "").strip().lower() != "external":
            continue
        key = (
            str(verified.get("witness_node_id", "") or "").strip(),
            str(verified.get("witness_public_key", "") or "").strip(),
        )
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        merged_external.append(dict(receipt or {}))
    state["external_witness_manifest_fingerprint"] = current_manifest_fingerprint
    state["external_witness_receipts"] = merged_external
    _write_root_distribution_state(state)
    witness_verified = verify_root_manifest_witness_set(
        current_manifest,
        [*local_witnesses, *merged_external],
    )
    return {
        "ok": True,
        "manifest_fingerprint": current_manifest_fingerprint,
        "external_witness_count": len(merged_external),
        "witness_count": _safe_int(witness_verified.get("witness_count", 0) or 0, 0),
        "witness_threshold": _safe_int(witness_verified.get("witness_threshold", 0) or 0, 0),
        "witness_domain_count": _safe_int(witness_verified.get("witness_domain_count", 0) or 0, 0),
        "witness_independent_quorum_met": bool(witness_verified.get("witness_independent_quorum_met")),
        "witness_finality_met": bool(witness_verified.get("witness_finality_met")),
    }


def _refresh_external_root_witness_material_from_source(
    state: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    package = _read_external_root_witness_material_package()
    attempted_at = int(time.time())
    if not package.get("ok"):
        _record_external_witness_refresh_status(
            state,
            ok=False,
            detail=str(package.get("detail", "") or "external root witness import unavailable"),
            source_path=str(package.get("source_ref", package.get("path", "")) or "").strip(),
            attempted_at=attempted_at,
        )
        _write_root_distribution_state(state)
        return package

    material = dict(package.get("material") or {})
    source_scope = str(material.get("source_scope", "external_import") or "external_import").strip().lower()
    source_label = str(material.get("source_label", "") or "").strip()
    source_exported_at = _external_witness_source_exported_at(material)
    descriptors_present = "descriptors" in material
    raw_descriptors = list(material.get("descriptors") or [])
    descriptors, _ = _normalize_external_witness_descriptors(raw_descriptors)
    if descriptors_present and raw_descriptors and not descriptors:
        _record_external_witness_refresh_status(
            state,
            ok=False,
            detail="external root witness descriptors invalid",
            source_path=str(package.get("source_ref", package.get("path", "")) or "").strip(),
            attempted_at=attempted_at,
        )
        _write_root_distribution_state(state)
        return {
            "ok": False,
            "detail": "external root witness descriptors invalid",
            "path": package.get("path", ""),
            "source_ref": package.get("source_ref", ""),
        }
    if source_exported_at <= 0:
        state["external_witness_source_exported_at"] = 0
        _record_external_witness_refresh_status(
            state,
            ok=False,
            detail="external root witness source exported_at required",
            source_path=str(package.get("source_ref", package.get("path", "")) or "").strip(),
            attempted_at=attempted_at,
        )
        _write_root_distribution_state(state)
        return {
            "ok": False,
            "detail": "external root witness source exported_at required",
            "path": package.get("path", ""),
            "source_ref": package.get("source_ref", ""),
        }
    state["external_witness_source_exported_at"] = source_exported_at
    if _external_witness_source_stale(source_exported_at, now=attempted_at):
        _record_external_witness_refresh_status(
            state,
            ok=False,
            detail="external root witness source stale",
            source_path=str(package.get("source_ref", package.get("path", "")) or "").strip(),
            attempted_at=attempted_at,
        )
        _write_root_distribution_state(state)
        return {
            "ok": False,
            "detail": "external root witness source stale",
            "path": package.get("path", ""),
            "source_ref": package.get("source_ref", ""),
        }

    if descriptors_present:
        previous_descriptors = list(state.get("external_witness_descriptors") or [])
        state["external_witness_descriptors"] = descriptors
        state["external_witness_source_scope"] = source_scope
        state["external_witness_source_label"] = source_label
        state["external_witness_imported_at"] = attempted_at
        if previous_descriptors != descriptors:
            state["external_witness_manifest_fingerprint"] = ""
            state["external_witness_receipts"] = []

    current_manifest = dict(manifest or {})
    current_manifest_fingerprint = manifest_fingerprint_for_envelope(current_manifest) if current_manifest else ""
    package_witnesses = list(material.get("witnesses") or [])
    package_manifest_fingerprint = str(material.get("manifest_fingerprint", "") or "").strip().lower()
    if current_manifest and package_witnesses:
        if not package_manifest_fingerprint:
            _record_external_witness_refresh_status(
                state,
                ok=False,
                detail="external root witness material manifest_fingerprint required",
                source_path=str(package.get("source_ref", package.get("path", "")) or "").strip(),
                attempted_at=attempted_at,
            )
            _write_root_distribution_state(state)
            return {
                "ok": False,
                "detail": "external root witness material manifest_fingerprint required",
                "source_ref": package.get("source_ref", ""),
            }
        if package_manifest_fingerprint != current_manifest_fingerprint:
            state["external_witness_manifest_fingerprint"] = ""
            state["external_witness_receipts"] = []
            _record_external_witness_refresh_status(
                state,
                ok=False,
                detail="external root witness material manifest_fingerprint mismatch",
                source_path=str(package.get("source_ref", package.get("path", "")) or "").strip(),
                attempted_at=attempted_at,
            )
            _write_root_distribution_state(state)
            return {
                "ok": False,
                "detail": "external root witness material manifest_fingerprint mismatch",
                "source_ref": package.get("source_ref", ""),
            }
        staged = _stage_external_witness_receipts_into_state(
            state,
            manifest=current_manifest,
            candidate_receipts=package_witnesses,
            merge_existing=False,
        )
        _record_external_witness_refresh_status(
            state,
            ok=bool(staged.get("ok")),
            detail=(
                "external root witness receipts refreshed for current manifest"
                if staged.get("ok")
                else str(staged.get("detail", "") or "external root witness refresh failed")
            ),
            source_path=str(package.get("source_ref", package.get("path", "")) or "").strip(),
            attempted_at=attempted_at,
        )
        _write_root_distribution_state(state)
        return {
            **staged,
            "path": str(package.get("path", "") or "").strip(),
            "source_ref": str(package.get("source_ref", "") or "").strip(),
        }

    _record_external_witness_refresh_status(
        state,
        ok=True,
        detail=(
            "external root witness descriptors imported; waiting for current-manifest receipts"
            if descriptors_present
            else "external root witness package loaded"
        ),
        source_path=str(package.get("source_ref", package.get("path", "")) or "").strip(),
        attempted_at=attempted_at,
    )
    _write_root_distribution_state(state)
    return {
        "ok": True,
        "detail": str(state.get("external_witness_refresh_detail", "") or "").strip(),
        "path": str(package.get("path", "") or "").strip(),
        "source_ref": str(package.get("source_ref", "") or "").strip(),
    }


def import_external_root_witness_material(material: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(material or {})
    if str(
        current.get("type", STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE)
        or STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE
    ) != STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE:
        return {"ok": False, "detail": "external root witness material type invalid"}
    schema_version = _safe_int(current.get("schema_version", 0) or 0, 0)
    if schema_version <= 0:
        return {"ok": False, "detail": "external root witness material schema_version required"}

    descriptors_present = "descriptors" in current
    raw_descriptors = list(current.get("descriptors") or [])
    descriptors, _ = _normalize_external_witness_descriptors(raw_descriptors)
    if descriptors_present and raw_descriptors and not descriptors:
        return {"ok": False, "detail": "external root witness descriptors invalid"}

    source_scope = str(current.get("source_scope", "external_import") or "external_import").strip().lower()
    source_label = str(current.get("source_label", "") or "").strip()
    source_exported_at = _external_witness_source_exported_at(current)

    if descriptors_present:
        configured = configure_external_root_witness_descriptors(descriptors)
        if not configured.get("ok"):
            return configured
        state = read_root_distribution_state()
        state["external_witness_source_scope"] = source_scope
        state["external_witness_source_label"] = source_label
        state["external_witness_imported_at"] = int(time.time())
        if source_exported_at > 0:
            state["external_witness_source_exported_at"] = source_exported_at
        _write_root_distribution_state(state)

    resolved = get_current_root_manifest()
    if not resolved.get("ok"):
        return {"ok": False, "detail": str(resolved.get("detail", "") or "stable root manifest unavailable")}

    manifest_fingerprint = str(current.get("manifest_fingerprint", "") or "").strip().lower()
    witnesses = list(current.get("witnesses") or [])
    staged: dict[str, Any] | None = None
    if witnesses:
        if not manifest_fingerprint:
            return {"ok": False, "detail": "external root witness material manifest_fingerprint required"}
        if manifest_fingerprint != str(resolved.get("manifest_fingerprint", "") or "").strip().lower():
            return {"ok": False, "detail": "external root witness material manifest_fingerprint mismatch"}
        staged = stage_external_root_manifest_witnesses(
            witnesses,
            manifest=dict(resolved.get("manifest") or {}),
        )
        if not staged.get("ok"):
            return staged
        state = read_root_distribution_state()
        state["external_witness_source_scope"] = source_scope
        state["external_witness_source_label"] = source_label
        state["external_witness_imported_at"] = int(time.time())
        if source_exported_at > 0:
            state["external_witness_source_exported_at"] = source_exported_at
        _write_root_distribution_state(state)

    latest = get_current_root_manifest()
    if not latest.get("ok"):
        return {"ok": False, "detail": str(latest.get("detail", "") or "stable root manifest unavailable")}
    return {
        "ok": True,
        "manifest_fingerprint": str(latest.get("manifest_fingerprint", "") or "").strip().lower(),
        "external_witness_descriptors": list(latest.get("external_witness_descriptors") or []),
        "external_witness_count": len(list(latest.get("external_witness_descriptors") or [])),
        "external_witness_source_scope": str(latest.get("external_witness_source_scope", "") or "").strip().lower(),
        "external_witness_source_label": str(latest.get("external_witness_source_label", "") or "").strip(),
        "external_witness_imported_at": _safe_int(latest.get("external_witness_imported_at", 0) or 0, 0),
        "external_witness_source_exported_at": _safe_int(
            latest.get("external_witness_source_exported_at", 0) or 0,
            0,
        ),
        "staged_external_witness_count": _safe_int((staged or {}).get("external_witness_count", 0) or 0, 0),
        "witness_count": _safe_int((staged or {}).get("witness_count", latest.get("witness_count", 0)) or 0, 0),
        "witness_threshold": _safe_int((staged or {}).get("witness_threshold", latest.get("witness_threshold", 0)) or 0, 0),
        "witness_independent_quorum_met": bool(
            (staged or {}).get("witness_independent_quorum_met", False)
        ),
        "witness_finality_met": bool((staged or {}).get("witness_finality_met", latest.get("witness_finality_met", False))),
    }


def import_external_root_witness_material_from_file(path: str | None = None) -> dict[str, Any]:
    package = _read_external_root_witness_material_package(path)
    if not package.get("ok"):
        detail = str(package.get("detail", "") or "external root witness import path required")
        if detail == "external root witness import path not configured":
            detail = "external root witness import path required"
        if detail == "external root witness import source not configured":
            detail = "external root witness import path required"
        return {"ok": False, "detail": detail}
    result = import_external_root_witness_material(dict(package.get("material") or {}))
    if not result.get("ok"):
        return result
    return {
        **result,
        "source_path": str(package.get("path", "") or "").strip(),
        "source_ref": str(package.get("source_ref", package.get("path", "")) or "").strip(),
    }


def _witness_receipt_match_key(receipt: dict[str, Any]) -> tuple[str, str, str]:
    envelope = dict(receipt or {})
    return (
        str(envelope.get("node_id", "") or "").strip(),
        str(envelope.get("public_key", "") or "").strip(),
        str(envelope.get("signature", "") or "").strip(),
    )


def verify_root_manifest_witnesses_against_external_source(
    manifest: dict[str, Any],
    witnesses: list[dict[str, Any]] | None,
    *,
    source_ref: str | None = None,
) -> dict[str, Any]:
    configured_ref = _configured_external_root_witness_source_ref(source_ref)
    if not configured_ref:
        return {
            "ok": True,
            "configured": False,
            "detail": "external root witness source not configured",
            "source_ref": "",
        }

    package = _read_external_root_witness_material_package(configured_ref)
    if not package.get("ok"):
        return {
            "ok": False,
            "configured": True,
            "detail": str(package.get("detail", "") or "external root witness source unreadable"),
            "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
        }

    material = dict(package.get("material") or {})
    if str(
        material.get("type", STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE)
        or STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE
    ) != STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE:
        return {
            "ok": False,
            "configured": True,
            "detail": "external root witness source type invalid",
            "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
        }
    if _safe_int(material.get("schema_version", 0) or 0, 0) <= 0:
        return {
            "ok": False,
            "configured": True,
            "detail": "external root witness source schema_version required",
            "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
        }
    source_exported_at = _external_witness_source_exported_at(material)
    if source_exported_at <= 0:
        return {
            "ok": False,
            "configured": True,
            "detail": "external root witness source exported_at required",
            "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
        }
    if _external_witness_source_stale(source_exported_at):
        return {
            "ok": False,
            "configured": True,
            "detail": "external root witness source stale",
            "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
            "source_exported_at": source_exported_at,
        }

    manifest_fingerprint = manifest_fingerprint_for_envelope(dict(manifest or {}))
    source_manifest_fingerprint = str(material.get("manifest_fingerprint", "") or "").strip().lower()
    if not manifest_fingerprint or not source_manifest_fingerprint:
        return {
            "ok": False,
            "configured": True,
            "detail": "external root witness source manifest_fingerprint required",
            "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
        }
    if source_manifest_fingerprint != manifest_fingerprint:
        return {
            "ok": False,
            "configured": True,
            "detail": "external root witness source manifest_fingerprint mismatch",
            "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
        }

    raw_descriptors = list(material.get("descriptors") or [])
    descriptors, _ = _normalize_external_witness_descriptors(raw_descriptors)
    if raw_descriptors and not descriptors:
        return {
            "ok": False,
            "configured": True,
            "detail": "external root witness source descriptors invalid",
            "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
        }
    descriptor_keys = {
        (
            str(item.get("node_id", "") or "").strip(),
            str(item.get("public_key", "") or "").strip(),
        )
        for item in descriptors
    }

    source_receipts = [dict(item or {}) for item in list(material.get("witnesses") or []) if isinstance(item, dict)]
    if not source_receipts:
        return {
            "ok": False,
            "configured": True,
            "detail": "external root witness source receipts required",
            "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
        }

    provided_keys = {
        _witness_receipt_match_key(dict(item or {}))
        for item in list(witnesses or [])
        if isinstance(item, dict)
    }
    matched_receipts: list[dict[str, Any]] = []
    for receipt in source_receipts:
        verified = verify_root_manifest_witness(manifest, receipt)
        if not verified.get("ok"):
            return {
                "ok": False,
                "configured": True,
                "detail": "external root witness source receipt invalid",
                "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
            }
        if str(verified.get("witness_management_scope", "") or "").strip().lower() != "external":
            return {
                "ok": False,
                "configured": True,
                "detail": "external root witness source receipt must be externally managed",
                "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
            }
        signer_key = (
            str(verified.get("witness_node_id", "") or "").strip(),
            str(verified.get("witness_public_key", "") or "").strip(),
        )
        if descriptor_keys and signer_key not in descriptor_keys:
            return {
                "ok": False,
                "configured": True,
                "detail": "external root witness source receipt signer not declared",
                "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
            }
        if _witness_receipt_match_key(receipt) not in provided_keys:
            return {
                "ok": False,
                "configured": True,
                "detail": "external root witness source receipt set mismatch",
                "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
            }
        matched_receipts.append(receipt)

    return {
        "ok": True,
        "configured": True,
        "source_ref": str(package.get("source_ref", configured_ref) or configured_ref).strip(),
        "source_exported_at": source_exported_at,
        "external_witness_count": len(matched_receipts),
        "external_witness_descriptor_count": len(descriptors),
    }


def stage_external_root_manifest_witnesses(
    witnesses: list[dict[str, Any]] | None,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = get_current_root_manifest()
    if not current.get("ok"):
        return {"ok": False, "detail": str(current.get("detail", "") or "stable root manifest unavailable")}
    current_manifest = dict(manifest or current.get("manifest") or {})
    current_manifest_fingerprint = manifest_fingerprint_for_envelope(current_manifest) if current_manifest else ""
    if not current_manifest_fingerprint:
        return {"ok": False, "detail": "stable root manifest required"}
    if current_manifest_fingerprint != str(current.get("manifest_fingerprint", "") or "").strip().lower():
        return {"ok": False, "detail": "external witness receipts must target the current published manifest"}

    state = read_root_distribution_state()
    return _stage_external_witness_receipts_into_state(
        state,
        manifest=current_manifest,
        candidate_receipts=list(witnesses or []),
        merge_existing=True,
    )


def verify_root_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    envelope = dict(manifest or {})
    if str(envelope.get("type", STABLE_DM_ROOT_MANIFEST_TYPE) or STABLE_DM_ROOT_MANIFEST_TYPE) != STABLE_DM_ROOT_MANIFEST_TYPE:
        return {"ok": False, "detail": "stable root manifest type invalid"}
    if str(envelope.get("event_type", "") or "").strip() != STABLE_DM_ROOT_MANIFEST_EVENT_TYPE:
        return {"ok": False, "detail": "stable root manifest event_type invalid"}
    node_id = str(envelope.get("node_id", "") or "").strip()
    public_key = str(envelope.get("public_key", "") or "").strip()
    public_key_algo = str(envelope.get("public_key_algo", "Ed25519") or "Ed25519")
    protocol_version = str(envelope.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION)
    sequence = _safe_int(envelope.get("sequence", 0) or 0, 0)
    signature = str(envelope.get("signature", "") or "").strip()
    payload = dict(envelope.get("payload") or {})
    if not node_id or not public_key or sequence <= 0 or not signature:
        return {"ok": False, "detail": "stable root manifest incomplete"}
    if protocol_version != str(payload.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION):
        return {"ok": False, "detail": "stable root manifest protocol mismatch"}
    if node_id != str(payload.get("root_node_id", "") or "").strip():
        return {"ok": False, "detail": "stable root manifest signer mismatch"}
    if public_key != str(payload.get("root_public_key", "") or "").strip():
        return {"ok": False, "detail": "stable root manifest signer mismatch"}
    if public_key_algo != str(payload.get("root_public_key_algo", "Ed25519") or "Ed25519"):
        return {"ok": False, "detail": "stable root manifest signer mismatch"}
    generation = _safe_int(payload.get("generation", 0) or 0, 0)
    if generation <= 0:
        return {"ok": False, "detail": "stable root manifest generation required"}
    if _safe_int(payload.get("issued_at", 0) or 0, 0) <= 0:
        return {"ok": False, "detail": "stable root manifest issued_at required"}
    if _safe_int(payload.get("expires_at", 0) or 0, 0) <= _safe_int(payload.get("issued_at", 0) or 0, 0):
        return {"ok": False, "detail": "stable root manifest expires_at invalid"}
    if not verify_node_binding(node_id, public_key):
        return {"ok": False, "detail": "stable root manifest node binding invalid"}
    signed_payload = build_signature_payload(
        event_type=STABLE_DM_ROOT_MANIFEST_EVENT_TYPE,
        node_id=node_id,
        sequence=sequence,
        payload=payload,
    )
    if not verify_signature(
        public_key_b64=public_key,
        public_key_algo=public_key_algo,
        signature_hex=signature,
        payload=signed_payload,
    ):
        return {"ok": False, "detail": "stable root manifest invalid"}
    witness_policy_verified = _verify_witness_policy(dict(payload.get("witness_policy") or {}))
    if not witness_policy_verified.get("ok"):
        return {
            "ok": False,
            "detail": str(witness_policy_verified.get("detail", "") or "stable root manifest witness policy invalid"),
        }
    if _safe_int(payload.get("policy_version", 1) or 1, 1) != _safe_int(
        witness_policy_verified.get("policy", {}).get("policy_version", 1) or 1,
        1,
    ):
        return {"ok": False, "detail": "stable root manifest witness policy version mismatch"}
    root_fingerprint = root_identity_fingerprint_for_material(
        root_node_id=node_id,
        root_public_key=public_key,
        root_public_key_algo=public_key_algo,
        protocol_version=protocol_version,
    )
    payload_root_fingerprint = str(payload.get("root_fingerprint", "") or "").strip().lower()
    if payload_root_fingerprint and payload_root_fingerprint != root_fingerprint:
        return {"ok": False, "detail": "stable root manifest fingerprint mismatch"}
    previous_root_fingerprint = str(payload.get("previous_root_fingerprint", "") or "").strip().lower()
    previous_root_node_id = str(payload.get("previous_root_node_id", "") or "").strip()
    previous_root_public_key = str(payload.get("previous_root_public_key", "") or "").strip()
    previous_root_public_key_algo = str(payload.get("previous_root_public_key_algo", "Ed25519") or "Ed25519").strip()
    previous_root_protocol_version = str(
        payload.get("previous_root_protocol_version", protocol_version) or protocol_version
    ).strip()
    previous_root_cross_sequence = _safe_int(payload.get("previous_root_cross_sequence", 0) or 0, 0)
    previous_root_cross_signature = str(payload.get("previous_root_cross_signature", "") or "").strip()
    current_witness_policy_fingerprint = str(
        witness_policy_verified.get("policy_fingerprint", "") or ""
    ).strip().lower()
    previous_witness_policy_fingerprint = str(
        payload.get("previous_witness_policy_fingerprint", "") or ""
    ).strip().lower()
    previous_witness_policy_sequence = _safe_int(payload.get("previous_witness_policy_sequence", 0) or 0, 0)
    previous_witness_policy_signature = str(
        payload.get("previous_witness_policy_signature", "") or ""
    ).strip()
    rotation_proven = generation <= 1
    policy_change_proven = not previous_witness_policy_fingerprint
    if generation > 1:
        if not previous_root_fingerprint:
            return {"ok": False, "detail": "stable root manifest previous root required"}
        previous_root_fields_present = bool(previous_root_node_id or previous_root_public_key)
        proof_signature_present = bool(previous_root_cross_sequence > 0 or previous_root_cross_signature)
        if previous_root_fields_present:
            if not previous_root_node_id or not previous_root_public_key:
                return {"ok": False, "detail": "stable root manifest previous root proof incomplete"}
            if not verify_node_binding(previous_root_node_id, previous_root_public_key):
                return {"ok": False, "detail": "stable root manifest previous root binding invalid"}
            derived_previous_root_fingerprint = root_identity_fingerprint_for_material(
                root_node_id=previous_root_node_id,
                root_public_key=previous_root_public_key,
                root_public_key_algo=previous_root_public_key_algo,
                protocol_version=previous_root_protocol_version,
            )
            if derived_previous_root_fingerprint != previous_root_fingerprint:
                return {"ok": False, "detail": "stable root manifest previous root fingerprint mismatch"}
        if proof_signature_present:
            if not previous_root_node_id or not previous_root_public_key or previous_root_cross_sequence <= 0 or not previous_root_cross_signature:
                return {"ok": False, "detail": "stable root manifest previous root proof incomplete"}
            previous_signed_payload = build_signature_payload(
                event_type=STABLE_DM_ROOT_MANIFEST_PREVIOUS_ROOT_EVENT_TYPE,
                node_id=previous_root_node_id,
                sequence=previous_root_cross_sequence,
                payload=_previous_root_cross_payload(payload),
            )
            if not verify_signature(
                public_key_b64=previous_root_public_key,
                public_key_algo=previous_root_public_key_algo,
                signature_hex=previous_root_cross_signature,
                payload=previous_signed_payload,
            ):
                return {"ok": False, "detail": "stable root manifest previous root proof invalid"}
            rotation_proven = True
    if previous_witness_policy_fingerprint:
        if previous_witness_policy_fingerprint == current_witness_policy_fingerprint:
            return {"ok": False, "detail": "stable root manifest previous witness policy fingerprint invalid"}
        proof_signature_present = bool(
            previous_witness_policy_sequence > 0 or previous_witness_policy_signature
        )
        if proof_signature_present:
            if previous_witness_policy_sequence <= 0 or not previous_witness_policy_signature:
                return {"ok": False, "detail": "stable root manifest witness policy change proof incomplete"}
            previous_policy_signed_payload = build_signature_payload(
                event_type=STABLE_DM_ROOT_MANIFEST_POLICY_CHANGE_EVENT_TYPE,
                node_id=node_id,
                sequence=previous_witness_policy_sequence,
                payload=_previous_witness_policy_change_payload(payload),
            )
            if not verify_signature(
                public_key_b64=public_key,
                public_key_algo=public_key_algo,
                signature_hex=previous_witness_policy_signature,
                payload=previous_policy_signed_payload,
            ):
                return {"ok": False, "detail": "stable root manifest witness policy change proof invalid"}
            policy_change_proven = True
    elif previous_witness_policy_sequence > 0 or previous_witness_policy_signature:
        return {"ok": False, "detail": "stable root manifest witness policy change proof invalid"}
    return {
        "ok": True,
        "manifest_fingerprint": manifest_fingerprint_for_envelope(envelope),
        "root_fingerprint": root_fingerprint,
        "root_node_id": node_id,
        "root_public_key": public_key,
        "root_public_key_algo": public_key_algo,
        "generation": generation,
        "issued_at": _safe_int(payload.get("issued_at", 0) or 0, 0),
        "expires_at": _safe_int(payload.get("expires_at", 0) or 0, 0),
        "policy_version": _safe_int(payload.get("policy_version", 1) or 1, 1),
        "witness_policy": dict(witness_policy_verified.get("policy") or {}),
        "witness_policy_fingerprint": str(witness_policy_verified.get("policy_fingerprint", "") or "").strip().lower(),
        "witness_threshold": _safe_int(witness_policy_verified.get("threshold", 0) or 0, 0),
        "witness_policy_count": _safe_int(witness_policy_verified.get("witness_count", 0) or 0, 0),
        "rotation_proven": rotation_proven,
        "policy_change_proven": policy_change_proven,
        "previous_root_fingerprint": previous_root_fingerprint,
        "previous_root_node_id": previous_root_node_id,
        "previous_root_public_key": previous_root_public_key,
        "previous_root_public_key_algo": previous_root_public_key_algo,
        "previous_root_protocol_version": previous_root_protocol_version,
        "previous_witness_policy_fingerprint": previous_witness_policy_fingerprint,
    }


def verify_root_manifest_witness(manifest: dict[str, Any], witness: dict[str, Any]) -> dict[str, Any]:
    manifest_verified = verify_root_manifest(manifest)
    if not manifest_verified.get("ok"):
        return {"ok": False, "detail": str(manifest_verified.get("detail", "") or "stable root manifest invalid")}
    envelope = dict(witness or {})
    if str(envelope.get("type", STABLE_DM_ROOT_MANIFEST_WITNESS_TYPE) or STABLE_DM_ROOT_MANIFEST_WITNESS_TYPE) != STABLE_DM_ROOT_MANIFEST_WITNESS_TYPE:
        return {"ok": False, "detail": "stable root manifest witness type invalid"}
    if str(envelope.get("event_type", "") or "").strip() != STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE:
        return {"ok": False, "detail": "stable root manifest witness event_type invalid"}
    node_id = str(envelope.get("node_id", "") or "").strip()
    public_key = str(envelope.get("public_key", "") or "").strip()
    public_key_algo = str(envelope.get("public_key_algo", "Ed25519") or "Ed25519")
    sequence = _safe_int(envelope.get("sequence", 0) or 0, 0)
    signature = str(envelope.get("signature", "") or "").strip()
    payload = dict(envelope.get("payload") or {})
    expected_payload = _witness_payload(manifest)
    if not node_id or not public_key or sequence <= 0 or not signature:
        return {"ok": False, "detail": "stable root manifest witness incomplete"}
    if payload != expected_payload:
        return {"ok": False, "detail": "stable root manifest witness payload mismatch"}
    allowed_witnesses = {
        (
            str(item.get("node_id", "") or "").strip(),
            str(item.get("public_key", "") or "").strip(),
        ): dict(item or {})
        for item in list(manifest_verified.get("witness_policy", {}).get("witnesses") or [])
        if isinstance(item, dict)
    }
    matched_witness = allowed_witnesses.get((node_id, public_key))
    if not matched_witness:
        return {"ok": False, "detail": "stable root manifest witness not allowed by policy"}
    if not verify_node_binding(node_id, public_key):
        return {"ok": False, "detail": "stable root manifest witness node binding invalid"}
    signed_payload = build_signature_payload(
        event_type=STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        node_id=node_id,
        sequence=sequence,
        payload=expected_payload,
    )
    if not verify_signature(
        public_key_b64=public_key,
        public_key_algo=public_key_algo,
        signature_hex=signature,
        payload=signed_payload,
    ):
        return {"ok": False, "detail": "stable root manifest witness invalid"}
    return {
        "ok": True,
        "manifest_fingerprint": str(expected_payload.get("manifest_fingerprint", "") or "").strip().lower(),
        "root_fingerprint": str(expected_payload.get("root_fingerprint", "") or "").strip().lower(),
        "witness_node_id": node_id,
        "witness_public_key": public_key,
        "witness_public_key_algo": public_key_algo,
        "generation": _safe_int(expected_payload.get("generation", 0) or 0, 0),
        "issued_at": _safe_int(expected_payload.get("issued_at", 0) or 0, 0),
        "expires_at": _safe_int(expected_payload.get("expires_at", 0) or 0, 0),
        "policy_version": _safe_int(expected_payload.get("policy_version", 1) or 1, 1),
        "witness_policy_fingerprint": str(expected_payload.get("witness_policy_fingerprint", "") or "").strip().lower(),
        "witness_threshold": _safe_int(expected_payload.get("witness_threshold", 0) or 0, 0),
        "witness_management_scope": _normalize_witness_management_scope(matched_witness.get("management_scope")),
        "witness_independence_group": _normalize_witness_independence_group(
            matched_witness.get("independence_group"),
            management_scope=_normalize_witness_management_scope(matched_witness.get("management_scope")),
        ),
        "rotation_proven": bool(manifest_verified.get("rotation_proven")),
        "policy_change_proven": bool(manifest_verified.get("policy_change_proven")),
        "previous_root_fingerprint": str(manifest_verified.get("previous_root_fingerprint", "") or "").strip().lower(),
        "previous_witness_policy_fingerprint": str(
            manifest_verified.get("previous_witness_policy_fingerprint", "") or ""
        ).strip().lower(),
    }


def verify_root_manifest_witness_set(manifest: dict[str, Any], witnesses: list[dict[str, Any]] | None) -> dict[str, Any]:
    manifest_verified = verify_root_manifest(manifest)
    if not manifest_verified.get("ok"):
        return {"ok": False, "detail": str(manifest_verified.get("detail", "") or "stable root manifest invalid")}
    validated: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    independence_groups: set[str] = set()
    for witness in list(witnesses or []):
        verified = verify_root_manifest_witness(manifest, dict(witness or {}))
        if not verified.get("ok"):
            continue
        witness_key = (
            str(verified.get("witness_node_id", "") or "").strip(),
            str(verified.get("witness_public_key", "") or "").strip(),
        )
        if witness_key in seen:
            continue
        seen.add(witness_key)
        validated.append(verified)
        group = str(verified.get("witness_independence_group", "") or "").strip().lower()
        if group:
            independence_groups.add(group)
    threshold = _safe_int(manifest_verified.get("witness_threshold", 0) or 0, 0)
    if not validated:
        return {
            "ok": False,
            "detail": "stable root manifest witness receipts required",
            "witness_threshold": threshold,
            "witness_count": 0,
        }
    if threshold <= 0 or len(validated) < threshold:
        return {
            "ok": False,
            "detail": "stable root manifest witness threshold not met",
            "witness_threshold": threshold,
            "witness_count": len(validated),
        }
    witness_independent_quorum_met = threshold > 0 and len(independence_groups) >= threshold
    return {
        "ok": True,
        "manifest_fingerprint": str(manifest_verified.get("manifest_fingerprint", "") or "").strip().lower(),
        "root_fingerprint": str(manifest_verified.get("root_fingerprint", "") or "").strip().lower(),
        "witness_policy_fingerprint": str(manifest_verified.get("witness_policy_fingerprint", "") or "").strip().lower(),
        "witness_threshold": threshold,
        "witness_count": len(validated),
        "witness_domain_count": len(independence_groups),
        "witness_independent_quorum_met": witness_independent_quorum_met,
        "witness_finality_met": root_witness_finality_met(
            witness_threshold=threshold,
            witness_quorum_met=True,
            witness_independent_quorum_met=witness_independent_quorum_met,
        ),
        "rotation_proven": bool(manifest_verified.get("rotation_proven")),
        "policy_change_proven": bool(manifest_verified.get("policy_change_proven")),
        "validated_witnesses": validated,
    }
