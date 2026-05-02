"""Wormhole-managed prekey bundles and X3DH-style bootstrap helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from services.mesh.mesh_compatibility import (
    LEGACY_AGENT_ID_LOOKUP_TARGET,
    legacy_agent_id_lookup_blocked,
    record_legacy_agent_id_lookup,
    sunset_target_label,
)
from services.mesh.mesh_metadata_exposure import stable_metadata_log_ref
from services.mesh.mesh_crypto import build_signature_payload, derive_node_id, verify_node_binding, verify_signature
from services.mesh.mesh_wormhole_identity import (
    _write_identity,
    bootstrap_wormhole_identity,
    get_prekey_lookup_handle_records,
    read_wormhole_identity,
    root_identity_fingerprint_for_material,
    sign_wormhole_event,
    sign_wormhole_message,
    trust_fingerprint_for_identity_material,
)
from services.mesh.mesh_wormhole_persona import sign_root_wormhole_event
from services.mesh.mesh_protocol import PROTOCOL_VERSION

PREKEY_TARGET = 8
PREKEY_MIN_THRESHOLD = 3
PREKEY_MAX_THRESHOLD = 5
PREKEY_MIN_TARGET = 7
PREKEY_MAX_TARGET = 9
PREKEY_MIN_REPUBLISH_DELAY_S = 45
PREKEY_MAX_REPUBLISH_DELAY_S = 120
PREKEY_REPUBLISH_THRESHOLD_RANGE = (PREKEY_MIN_THRESHOLD, PREKEY_MAX_THRESHOLD)
PREKEY_REPUBLISH_TARGET_RANGE = (PREKEY_MIN_TARGET, PREKEY_MAX_TARGET)
PREKEY_REPUBLISH_DELAY_RANGE_S = (PREKEY_MIN_REPUBLISH_DELAY_S, PREKEY_MAX_REPUBLISH_DELAY_S)
SIGNED_PREKEY_ROTATE_AFTER_S = 24 * 60 * 60
SIGNED_PREKEY_GRACE_S = 3 * 24 * 60 * 60
DM_PREKEY_ROOT_ATTESTATION_EVENT_TYPE = "dm_prekey_root_attestation"
DM_PREKEY_ROOT_ATTESTATION_TYPE = "stable_dm_root"
logger = logging.getLogger(__name__)
_WARNED_LEGACY_PREKEY_LOOKUPS: set[str] = set()


def _safe_int(val, default=0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _warn_legacy_prekey_lookup(agent_id: str) -> None:
    peer_id = str(agent_id or "").strip().lower()
    if not peer_id or peer_id in _WARNED_LEGACY_PREKEY_LOOKUPS:
        return
    _WARNED_LEGACY_PREKEY_LOOKUPS.add(peer_id)
    logger.warning(
        "mesh legacy prekey lookup used for %s via direct agent_id; prefer invite-scoped lookup handles before removal in %s",
        stable_metadata_log_ref(peer_id, prefix="peer"),
        sunset_target_label(LEGACY_AGENT_ID_LOOKUP_TARGET),
    )


def _fetch_dm_prekey_bundle_from_peer_lookup(lookup_token: str) -> dict[str, Any]:
    """Fetch an invite-scoped prekey bundle from configured authenticated peers.

    This is deliberately limited to lookup handles. Stable agent_id lookup stays
    local/tier-gated so first-contact convenience does not reintroduce broad
    public identity enumeration.
    """
    token = str(lookup_token or "").strip()
    if not token:
        return {"ok": False, "detail": "lookup token required"}
    try:
        from services.config import get_settings
        from services.mesh.mesh_crypto import _derive_peer_key, normalize_peer_url
        from services.mesh.mesh_router import configured_relay_peer_urls

        settings = get_settings()
        secret = str(getattr(settings, "MESH_PEER_PUSH_SECRET", "") or "").strip()
        if not secret:
            return {"ok": False, "detail": "peer prekey lookup unavailable"}
        peers = configured_relay_peer_urls()
        if not peers:
            return {"ok": False, "detail": "peer prekey lookup unavailable"}
        timeout = max(1, _safe_int(getattr(settings, "MESH_RELAY_PUSH_TIMEOUT_S", 10) or 10, 10))
    except Exception as exc:
        logger.debug("peer prekey lookup setup failed: %s", type(exc).__name__)
        return {"ok": False, "detail": "peer prekey lookup unavailable"}

    body = json.dumps(
        {"lookup_token": token},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    last_detail = ""
    for peer_url in peers:
        normalized_peer_url = str(peer_url or "").strip().rstrip("/")
        if not normalized_peer_url:
            continue
        sender_peer_url = normalize_peer_url(
            os.environ.get("MESH_SELF_PEER_URL", "").strip()
            or os.environ.get("SB_TEST_NODE_URL", "").strip()
            or normalized_peer_url
        )
        peer_key = _derive_peer_key(secret, sender_peer_url)
        if not peer_key:
            continue
        headers = {
            "Content-Type": "application/json",
            "X-Peer-Url": sender_peer_url,
            "X-Peer-HMAC": hmac.new(peer_key, body, hashlib.sha256).hexdigest(),
        }
        request = urllib.request.Request(
            f"{normalized_peer_url}/api/mesh/dm/prekey-peer-lookup",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(256 * 1024)
            payload = json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_detail = str(exc) or type(exc).__name__
            continue
        if isinstance(payload, dict) and payload.get("ok"):
            payload["lookup_mode"] = "invite_lookup_handle"
            payload["peer_lookup"] = True
            return payload
        if isinstance(payload, dict):
            last_detail = str(payload.get("detail", "") or last_detail)
    return {"ok": False, "detail": last_detail or "Prekey bundle not found"}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(data: str | bytes | None) -> bytes:
    if not data:
        return b""
    if isinstance(data, bytes):
        return base64.b64decode(data)
    return base64.b64decode(data.encode("ascii"))


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _x25519_pair() -> dict[str, str]:
    priv = x25519.X25519PrivateKey.generate()
    priv_raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {"public_key": _b64(pub_raw), "private_key": _b64(priv_raw)}


def _derive(priv_b64: str, pub_b64: str) -> bytes:
    priv = x25519.X25519PrivateKey.from_private_bytes(_unb64(priv_b64))
    pub = x25519.X25519PublicKey.from_public_bytes(_unb64(pub_b64))
    return priv.exchange(pub)


def _hkdf(ikm: bytes, info: str, length: int = 32) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=b"\xff" * 32,
        info=info.encode("utf-8"),
    ).derive(ikm)


def _bundle_payload(data: dict[str, Any]) -> dict[str, Any]:
    one_time_prekeys = [
        {
            "prekey_id": _safe_int(item.get("prekey_id", 0) or 0),
            "public_key": str(item.get("public_key", "") or ""),
        }
        for item in list(data.get("one_time_prekeys") or [])
        if item.get("public_key")
    ]
    return {
        "identity_dh_pub_key": str(data.get("dh_pub_key", "") or ""),
        "dh_algo": str(data.get("dh_algo", "X25519") or "X25519"),
        "signed_prekey_id": _safe_int(data.get("signed_prekey_id", 0) or 0),
        "signed_prekey_pub": str(data.get("signed_prekey_pub", "") or ""),
        "signed_prekey_signature": str(data.get("signed_prekey_signature", "") or ""),
        "signed_prekey_timestamp": _safe_int(data.get("signed_prekey_generated_at", 0) or 0),
        "signed_at": _safe_int(data.get("prekey_bundle_signed_at", 0) or 0),
        "bundle_signature": str(data.get("prekey_bundle_signature", "") or ""),
        "mls_key_package": str(data.get("mls_key_package", "") or ""),
        "one_time_prekeys": one_time_prekeys,
        "one_time_prekey_count": len(one_time_prekeys),
    }


def _bundle_signature_core_payload(data: dict[str, Any]) -> dict[str, Any]:
    # OTK binding: One-time key hashes are included in the bundle signature
    # as of Sprint 12 (S12-3). Relay substitution of OTKs will now break
    # the bundle signature and be rejected by verify_prekey_bundle().
    otk_hashes = sorted(
        hashlib.sha256(str(item.get("public_key", "")).encode("utf-8")).hexdigest()
        for item in (data.get("one_time_prekeys") or [])
    )
    return {
        "identity_dh_pub_key": str(data.get("identity_dh_pub_key", "") or ""),
        "dh_algo": str(data.get("dh_algo", "X25519") or "X25519"),
        "signed_prekey_id": _safe_int(data.get("signed_prekey_id", 0) or 0),
        "signed_prekey_pub": str(data.get("signed_prekey_pub", "") or ""),
        "signed_prekey_signature": str(data.get("signed_prekey_signature", "") or ""),
        "signed_at": _safe_int(data.get("signed_at", 0) or 0),
        "mls_key_package": str(data.get("mls_key_package", "") or ""),
        "one_time_prekey_hashes": otk_hashes,
    }


def _bundle_root_attestation_binding(attestation: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(attestation or {})
    if not current:
        return {}
    return {
        "type": str(current.get("type", "") or ""),
        "event_type": str(current.get("event_type", "") or ""),
        "protocol_version": str(current.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        "root_node_id": str(current.get("root_node_id", "") or "").strip(),
        "root_public_key": str(current.get("root_public_key", "") or "").strip(),
        "root_public_key_algo": str(current.get("root_public_key_algo", "Ed25519") or "Ed25519").strip(),
        "root_manifest_fingerprint": str(current.get("root_manifest_fingerprint", "") or "").strip().lower(),
        "sequence": _safe_int(current.get("sequence", 0) or 0, 0),
        "signature": str(current.get("signature", "") or "").strip(),
        "signer_scope": str(current.get("signer_scope", "root") or "root"),
    }


def _bundle_signature_payload(data: dict[str, Any]) -> str:
    payload = _bundle_signature_core_payload(data)
    binding = _bundle_root_attestation_binding(dict(data.get("root_attestation") or {}))
    if binding:
        payload["root_attestation"] = binding
    return _stable_json(payload)


def _max_prekey_bundle_age_s() -> int:
    return SIGNED_PREKEY_ROTATE_AFTER_S + SIGNED_PREKEY_GRACE_S


def trust_fingerprint_for_bundle_record(record: dict[str, Any]) -> str:
    bundle = dict(record.get("bundle") or record or {})
    return trust_fingerprint_for_identity_material(
        agent_id=str(record.get("agent_id", "") or ""),
        identity_dh_pub_key=str(bundle.get("identity_dh_pub_key", "") or ""),
        dh_algo=str(bundle.get("dh_algo", "X25519") or "X25519"),
        public_key=str(record.get("public_key", "") or ""),
        public_key_algo=str(record.get("public_key_algo", "") or ""),
        protocol_version=str(record.get("protocol_version", "") or ""),
    )


def transparency_fingerprint_for_bundle_record(record: dict[str, Any]) -> str:
    bundle = dict(record.get("bundle") or record or {})
    payload = {
        "agent_id": str(record.get("agent_id", "") or "").strip(),
        "public_key": str(record.get("public_key", "") or "").strip(),
        "public_key_algo": str(record.get("public_key_algo", "") or "").strip(),
        "protocol_version": str(record.get("protocol_version", "") or "").strip(),
        "sequence": _safe_int(record.get("sequence", 0) or 0),
        "bundle_payload": _bundle_signature_payload(bundle),
        "bundle_signature": str(bundle.get("bundle_signature", "") or "").strip(),
        "relay_signature": str(record.get("signature", "") or "").strip(),
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _bundle_root_attestation_payload(
    *,
    agent_id: str,
    public_key: str,
    public_key_algo: str,
    protocol_version: str,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    current_bundle = dict(bundle or {})
    current_bundle.pop("root_attestation", None)
    root_manifest = dict(current_bundle.get("root_manifest") or {})
    root_manifest_fingerprint = ""
    if root_manifest:
        from services.mesh.mesh_wormhole_root_manifest import manifest_fingerprint_for_envelope

        root_manifest_fingerprint = manifest_fingerprint_for_envelope(root_manifest)
    return {
        "agent_id": str(agent_id or "").strip(),
        "public_key": str(public_key or "").strip(),
        "public_key_algo": str(public_key_algo or "Ed25519") or "Ed25519",
        "protocol_version": str(protocol_version or PROTOCOL_VERSION) or PROTOCOL_VERSION,
        "root_manifest_fingerprint": root_manifest_fingerprint,
        "bundle_signature_payload": _stable_json(_bundle_signature_core_payload(current_bundle)),
    }


def _attach_bundle_root_attestation(
    *,
    agent_id: str,
    public_key: str,
    public_key_algo: str,
    protocol_version: str,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(bundle or {})
    signed = sign_root_wormhole_event(
        event_type=DM_PREKEY_ROOT_ATTESTATION_EVENT_TYPE,
        payload=_bundle_root_attestation_payload(
            agent_id=agent_id,
            public_key=public_key,
            public_key_algo=public_key_algo,
            protocol_version=protocol_version,
            bundle=payload,
        ),
    )
    payload["root_attestation"] = {
        "type": DM_PREKEY_ROOT_ATTESTATION_TYPE,
        "event_type": DM_PREKEY_ROOT_ATTESTATION_EVENT_TYPE,
        "protocol_version": str(signed.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        "root_node_id": str(signed.get("node_id", "") or "").strip(),
        "root_public_key": str(signed.get("public_key", "") or "").strip(),
        "root_public_key_algo": str(signed.get("public_key_algo", "Ed25519") or "Ed25519"),
        "root_manifest_fingerprint": str(signed.get("payload", {}).get("root_manifest_fingerprint", "") or "").strip().lower(),
        "sequence": _safe_int(signed.get("sequence", 0) or 0, 0),
        "signature": str(signed.get("signature", "") or "").strip(),
        "signer_scope": str(signed.get("identity_scope", "root") or "root"),
    }
    return payload


def _attach_bundle_root_distribution(bundle: dict[str, Any]) -> dict[str, Any]:
    payload = dict(bundle or {})
    from services.mesh.mesh_wormhole_root_manifest import get_current_root_manifest
    from services.mesh.mesh_wormhole_root_transparency import get_current_root_transparency_record

    distribution = get_current_root_manifest()
    transparency = get_current_root_transparency_record(distribution=distribution)
    payload["root_manifest"] = dict(distribution.get("manifest") or {})
    payload["root_manifest_witness"] = dict(distribution.get("witness") or {})
    payload["root_manifest_witnesses"] = [
        dict(item or {}) for item in list(distribution.get("witnesses") or []) if isinstance(item, dict)
    ]
    payload["root_transparency_record"] = dict(transparency.get("record") or {})
    return payload


def _verify_bundle_root_distribution_impl(
    record: dict[str, Any],
    *,
    enforce_local_external_sources: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    bundle = dict(record.get("bundle") or record or {})
    manifest = dict(bundle.get("root_manifest") or {})
    witnesses = [
        dict(item or {})
        for item in list(bundle.get("root_manifest_witnesses") or [])
        if isinstance(item, dict)
    ]
    legacy_witness = dict(bundle.get("root_manifest_witness") or {})
    if legacy_witness and not witnesses:
        witnesses = [legacy_witness]
    transparency_record = dict(bundle.get("root_transparency_record") or {})
    if not manifest:
        return False, "prekey bundle root manifest required", {}
    if not witnesses:
        return False, "prekey bundle root witness receipts required", {}
    if not transparency_record:
        return False, "prekey bundle root transparency record required", {}

    from services.mesh.mesh_wormhole_root_manifest import verify_root_manifest, verify_root_manifest_witness_set
    from services.mesh.mesh_wormhole_root_transparency import verify_root_transparency_record

    manifest_verified = verify_root_manifest(manifest)
    if not manifest_verified.get("ok"):
        return False, str(manifest_verified.get("detail", "") or "prekey bundle root manifest invalid"), {}
    witness_verified = verify_root_manifest_witness_set(manifest, witnesses)
    if not witness_verified.get("ok"):
        return False, str(witness_verified.get("detail", "") or "prekey bundle root witness invalid"), {}
    transparency_verified = verify_root_transparency_record(transparency_record, manifest, witnesses)
    if not transparency_verified.get("ok"):
        return (
            False,
            str(transparency_verified.get("detail", "") or "prekey bundle root transparency record invalid"),
            {},
        )
    external_witness_verified = {"configured": False, "ok": True}
    external_transparency_verified = {"configured": False, "ok": True}
    if enforce_local_external_sources:
        from services.mesh.mesh_wormhole_root_manifest import verify_root_manifest_witnesses_against_external_source
        from services.mesh.mesh_wormhole_root_transparency import verify_root_transparency_record_against_external_ledger

        external_witness_verified = verify_root_manifest_witnesses_against_external_source(manifest, witnesses)
        if external_witness_verified.get("configured") and not external_witness_verified.get("ok"):
            return (
                False,
                str(
                    external_witness_verified.get("detail", "")
                    or "prekey bundle external root witness source invalid"
                ),
                {},
            )
        external_transparency_verified = verify_root_transparency_record_against_external_ledger(
            transparency_record
        )
        if external_transparency_verified.get("configured") and not external_transparency_verified.get("ok"):
            return (
                False,
                str(
                    external_transparency_verified.get("detail", "")
                    or "prekey bundle external root transparency invalid"
                ),
                {},
            )
    resolved = {
        "root_manifest_fingerprint": str(manifest_verified.get("manifest_fingerprint", "") or "").strip().lower(),
        "root_manifest_generation": _safe_int(manifest_verified.get("generation", 0) or 0, 0),
        "root_manifest_policy_version": _safe_int(manifest_verified.get("policy_version", 1) or 1, 1),
        "root_witness_policy_fingerprint": str(
            manifest_verified.get("witness_policy_fingerprint", "") or ""
        ).strip().lower(),
        "root_witness_threshold": _safe_int(witness_verified.get("witness_threshold", 0) or 0, 0),
        "root_witness_count": _safe_int(witness_verified.get("witness_count", 0) or 0, 0),
        "root_witness_domain_count": _safe_int(witness_verified.get("witness_domain_count", 0) or 0, 0),
        "root_witness_independent_quorum_met": bool(
            witness_verified.get("witness_independent_quorum_met")
        ),
        "root_witness_finality_met": bool(witness_verified.get("witness_finality_met")),
        "root_rotation_proven": bool(manifest_verified.get("rotation_proven")),
        "root_witness_policy_change_proven": bool(manifest_verified.get("policy_change_proven")),
        "root_transparency_fingerprint": str(
            transparency_verified.get("record_fingerprint", "") or ""
        ).strip().lower(),
        "root_transparency_binding_fingerprint": str(
            transparency_verified.get("binding_fingerprint", "") or ""
        ).strip().lower(),
        "root_node_id": str(manifest_verified.get("root_node_id", "") or "").strip(),
        "root_public_key": str(manifest_verified.get("root_public_key", "") or "").strip(),
        "root_public_key_algo": str(manifest_verified.get("root_public_key_algo", "Ed25519") or "Ed25519"),
        "root_external_witness_source_configured": bool(external_witness_verified.get("configured")),
        "root_external_transparency_readback_configured": bool(external_transparency_verified.get("configured")),
    }
    if resolved["root_manifest_generation"] > 1 and not resolved["root_rotation_proven"]:
        return False, "prekey bundle root rotation proof required", resolved
    if not resolved["root_witness_policy_change_proven"]:
        return False, "prekey bundle root witness policy change proof required", resolved
    return True, "ok", resolved


def _verify_bundle_root_attestation_impl(
    record: dict[str, Any],
    *,
    enforce_local_external_sources: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    resolved = dict(record or {})
    bundle = dict(resolved.get("bundle") or resolved or {})
    attestation = dict(bundle.get("root_attestation") or {})
    if not attestation:
        return False, "prekey bundle root attestation required", {}
    root_distribution_ok, root_distribution_detail, root_distribution = _verify_bundle_root_distribution_impl(
        resolved,
        enforce_local_external_sources=enforce_local_external_sources,
    )
    if not root_distribution_ok:
        return False, root_distribution_detail, root_distribution

    root_node_id = str(attestation.get("root_node_id", "") or "").strip()
    root_public_key = str(attestation.get("root_public_key", "") or "").strip()
    root_public_key_algo = str(
        attestation.get("root_public_key_algo", attestation.get("public_key_algo", "Ed25519")) or "Ed25519"
    ).strip()
    root_manifest_fingerprint = str(attestation.get("root_manifest_fingerprint", "") or "").strip().lower()
    protocol_version = str(attestation.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip()
    sequence = _safe_int(attestation.get("sequence", 0) or 0, 0)
    signature = str(attestation.get("signature", "") or "").strip()
    if not root_node_id or not root_public_key or not root_manifest_fingerprint or sequence <= 0 or not signature:
        return False, "prekey bundle root attestation incomplete", {}
    if protocol_version != str(resolved.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip():
        return False, "prekey bundle root attestation protocol mismatch", {}
    if root_manifest_fingerprint != str(root_distribution.get("root_manifest_fingerprint", "") or "").strip().lower():
        return False, "prekey bundle root attestation manifest mismatch", {}
    if root_node_id != str(root_distribution.get("root_node_id", "") or "").strip():
        return False, "prekey bundle root attestation root mismatch", {}
    if root_public_key != str(root_distribution.get("root_public_key", "") or "").strip():
        return False, "prekey bundle root attestation root mismatch", {}
    if root_public_key_algo != str(root_distribution.get("root_public_key_algo", "Ed25519") or "Ed25519"):
        return False, "prekey bundle root attestation root mismatch", {}
    if not verify_node_binding(root_node_id, root_public_key):
        return False, "prekey bundle root attestation node binding invalid", {}

    signed_payload = build_signature_payload(
        event_type=DM_PREKEY_ROOT_ATTESTATION_EVENT_TYPE,
        node_id=root_node_id,
        sequence=sequence,
        payload=_bundle_root_attestation_payload(
            agent_id=str(resolved.get("agent_id", "") or "").strip(),
            public_key=str(resolved.get("public_key", "") or "").strip(),
            public_key_algo=str(resolved.get("public_key_algo", "Ed25519") or "Ed25519"),
            protocol_version=str(resolved.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
            bundle=bundle,
        ),
    )
    if not verify_signature(
        public_key_b64=root_public_key,
        public_key_algo=root_public_key_algo,
        signature_hex=signature,
        payload=signed_payload,
    ):
        return False, "prekey bundle root attestation invalid", {}
    return True, "ok", {
        "root_node_id": root_node_id,
        "root_public_key": root_public_key,
        "root_public_key_algo": root_public_key_algo,
        "root_manifest_fingerprint": root_manifest_fingerprint,
        "root_manifest_generation": _safe_int(root_distribution.get("root_manifest_generation", 0) or 0, 0),
        "root_manifest_policy_version": _safe_int(root_distribution.get("root_manifest_policy_version", 1) or 1, 1),
        "root_witness_policy_fingerprint": str(
            root_distribution.get("root_witness_policy_fingerprint", "") or ""
        ).strip().lower(),
        "root_witness_threshold": _safe_int(root_distribution.get("root_witness_threshold", 0) or 0, 0),
        "root_witness_count": _safe_int(root_distribution.get("root_witness_count", 0) or 0, 0),
        "root_witness_domain_count": _safe_int(root_distribution.get("root_witness_domain_count", 0) or 0, 0),
        "root_witness_independent_quorum_met": bool(
            root_distribution.get("root_witness_independent_quorum_met")
        ),
        "root_transparency_fingerprint": str(root_distribution.get("root_transparency_fingerprint", "") or "").strip().lower(),
        "root_transparency_binding_fingerprint": str(
            root_distribution.get("root_transparency_binding_fingerprint", "") or ""
        ).strip().lower(),
        "root_rotation_proven": bool(root_distribution.get("root_rotation_proven")),
        "root_fingerprint": root_identity_fingerprint_for_material(
            root_node_id=root_node_id,
            root_public_key=root_public_key,
            root_public_key_algo=root_public_key_algo,
            protocol_version=str(resolved.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        ),
    }


def verify_bundle_root_attestation(
    record: dict[str, Any],
    *,
    enforce_local_external_sources: bool = False,
) -> dict[str, Any]:
    ok, detail, resolved = _verify_bundle_root_attestation_impl(
        record,
        enforce_local_external_sources=enforce_local_external_sources,
    )
    if not ok:
        return {"ok": False, "detail": detail, **resolved}
    return {"ok": True, **resolved}


def observe_remote_prekey_bundle(peer_id: str, bundle: dict[str, Any]) -> dict[str, Any]:
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity

    bundle_record = dict(bundle or {})
    bundle_payload = dict(bundle_record.get("bundle") or bundle_record)
    trust_fingerprint = str(bundle_record.get("trust_fingerprint", "") or bundle_payload.get("trust_fingerprint", "") or "").strip().lower()
    if not trust_fingerprint:
        trust_fingerprint = trust_fingerprint_for_bundle_record(
            {
                "agent_id": str(peer_id or "").strip(),
                "bundle": bundle_payload,
                "public_key": str(bundle_record.get("public_key", "") or bundle_payload.get("public_key", "") or ""),
                "public_key_algo": str(bundle_record.get("public_key_algo", "") or bundle_payload.get("public_key_algo", "") or ""),
                "protocol_version": str(bundle_record.get("protocol_version", "") or bundle_payload.get("protocol_version", "") or ""),
            }
        )
    root_attested = verify_bundle_root_attestation(
        {
            "agent_id": str(peer_id or "").strip(),
            "bundle": bundle_payload,
            "public_key": str(bundle_record.get("public_key", "") or bundle_payload.get("public_key", "") or ""),
            "public_key_algo": str(
                bundle_record.get("public_key_algo", "") or bundle_payload.get("public_key_algo", "") or ""
            ),
            "protocol_version": str(
                bundle_record.get("protocol_version", "") or bundle_payload.get("protocol_version", "") or ""
            ),
        }
    )
    return observe_remote_prekey_identity(
        str(peer_id or "").strip(),
        fingerprint=trust_fingerprint,
        sequence=_safe_int(bundle_record.get("sequence", 0) or 0),
        signed_at=_safe_int(bundle_payload.get("signed_at", 0) or bundle_record.get("signed_at", 0) or 0),
        transparency_head=str(bundle_record.get("prekey_transparency_head", "") or "").strip().lower(),
        transparency_size=_safe_int(bundle_record.get("prekey_transparency_size", 0) or 0),
        witness_count=_safe_int(bundle_record.get("witness_count", 0) or 0),
        witness_latest_at=_safe_int(bundle_record.get("witness_latest_at", 0) or 0),
        root_fingerprint=str(root_attested.get("root_fingerprint", "") or ""),
        root_manifest_fingerprint=str(root_attested.get("root_manifest_fingerprint", "") or ""),
        root_witness_policy_fingerprint=str(root_attested.get("root_witness_policy_fingerprint", "") or ""),
        root_witness_threshold=_safe_int(root_attested.get("root_witness_threshold", 0) or 0, 0),
        root_witness_count=_safe_int(root_attested.get("root_witness_count", 0) or 0, 0),
        root_witness_domain_count=_safe_int(root_attested.get("root_witness_domain_count", 0) or 0, 0),
        root_manifest_generation=_safe_int(root_attested.get("root_manifest_generation", 0) or 0, 0),
        root_rotation_proven=bool(root_attested.get("root_rotation_proven")),
        root_node_id=str(root_attested.get("root_node_id", "") or ""),
        root_public_key=str(root_attested.get("root_public_key", "") or ""),
        root_public_key_algo=str(root_attested.get("root_public_key_algo", "Ed25519") or "Ed25519"),
    )


def _attach_bundle_signature(bundle: dict[str, Any], *, signed_at: int | None = None) -> dict[str, Any]:
    # KNOWN LIMITATION: Bundle signature is self-signed by the identity key it contains.
    # This proves possession of the private key and detects post-registration tampering,
    # but cannot prevent initial impersonation (no external PKI). Mitigated by reputation
    # system in Phase 9 (Oracle Rep). See threat-model.md for full analysis.
    payload = dict(bundle or {})
    resolved_signed_at = _safe_int(payload.get("signed_at", 0) or 0)
    if signed_at is not None:
        resolved_signed_at = int(signed_at)
    elif resolved_signed_at <= 0:
        resolved_signed_at = int(time.time())
    payload["signed_at"] = resolved_signed_at
    signed = sign_wormhole_message(_bundle_signature_payload(payload))
    payload["bundle_signature"] = str(signed.get("signature", "") or "")
    return payload


def _verify_bundle_signature(bundle: dict[str, Any], public_key: str) -> tuple[bool, str]:
    try:
        signing_pub = ed25519.Ed25519PublicKey.from_public_bytes(_unb64(public_key))
        signing_pub.verify(
            bytes.fromhex(str(bundle.get("bundle_signature", "") or "")),
            _bundle_signature_payload(bundle).encode("utf-8"),
        )
    except Exception:
        return False, "Prekey bundle signature invalid"
    return True, "ok"


def _validate_bundle_record(
    record: dict[str, Any],
    *,
    enforce_local_external_sources: bool = False,
) -> tuple[bool, str]:
    bundle = dict(record.get("bundle") or {})
    now = time.time()
    signed_at = _safe_int(bundle.get("signed_at", 0) or 0)
    if signed_at <= 0:
        return False, "Prekey bundle missing signed_at"
    if signed_at > now + 299:
        return False, "Prekey bundle signed_at is in the future"
    if not str(bundle.get("bundle_signature", "") or "").strip():
        return False, "Prekey bundle missing bundle_signature"
    public_key = str(record.get("public_key", "") or "")
    if not public_key:
        return False, "Prekey bundle missing signing key"
    if not dict(bundle.get("root_attestation") or {}):
        return False, "prekey bundle root attestation required"
    ok, reason = _verify_bundle_signature(bundle, public_key)
    if not ok:
        return False, reason
    if (now - signed_at) > _max_prekey_bundle_age_s():
        return False, "Prekey bundle is stale"
    if str(record.get("agent_id", "") or "").strip():
        derived = derive_node_id(public_key)
        if derived != str(record.get("agent_id", "") or "").strip():
            return False, "Prekey bundle public key binding mismatch"
    root_attestation = verify_bundle_root_attestation(
        record,
        enforce_local_external_sources=enforce_local_external_sources,
    )
    if not root_attestation.get("ok"):
        return False, str(root_attestation.get("detail", "") or "Prekey bundle root attestation invalid")
    return True, "ok"


def _local_external_root_sources_configured() -> bool:
    from services.mesh.mesh_wormhole_root_manifest import read_root_distribution_state

    state = read_root_distribution_state()
    return bool(list(state.get("external_witness_descriptors") or []))


def _jittered_republish_policy(data: dict[str, Any], *, reset: bool = False) -> tuple[int, int]:
    threshold = _safe_int(data.get("prekey_republish_threshold", 0) or 0)
    target = _safe_int(data.get("prekey_republish_target", 0) or 0)
    min_threshold, max_threshold = PREKEY_REPUBLISH_THRESHOLD_RANGE
    min_target, max_target = PREKEY_REPUBLISH_TARGET_RANGE
    if reset or threshold < min_threshold or threshold > max_threshold:
        threshold = random.randint(min_threshold, max_threshold)
        data["prekey_republish_threshold"] = threshold
    if reset or target < min_target or target > max_target:
        target = random.randint(min_target, max_target)
        data["prekey_republish_target"] = target
    return threshold, target


def _schedule_next_republish_window(data: dict[str, Any]) -> None:
    min_delay_s, max_delay_s = PREKEY_REPUBLISH_DELAY_RANGE_S
    data["prekey_next_republish_after"] = int(
        time.time() + random.randint(min_delay_s, max_delay_s)
    )


def _archive_current_signed_prekey(data: dict[str, Any], retired_at: int) -> None:
    current_id = _safe_int(data.get("signed_prekey_id", 0) or 0)
    current_pub = str(data.get("signed_prekey_pub", "") or "")
    current_priv = str(data.get("signed_prekey_priv", "") or "")
    current_sig = str(data.get("signed_prekey_signature", "") or "")
    current_generated_at = _safe_int(data.get("signed_prekey_generated_at", 0) or 0)
    if not current_id or not current_pub or not current_priv:
        return
    history = list(data.get("signed_prekey_history") or [])
    history.append(
        {
            "signed_prekey_id": current_id,
            "signed_prekey_pub": current_pub,
            "signed_prekey_priv": current_priv,
            "signed_prekey_signature": current_sig,
            "signed_prekey_generated_at": current_generated_at,
            "retired_at": retired_at,
        }
    )
    cutoff = retired_at - SIGNED_PREKEY_GRACE_S
    data["signed_prekey_history"] = [
        item
        for item in history[-4:]
        if _safe_int(item.get("retired_at", retired_at) or retired_at) >= cutoff
    ]


def _find_signed_prekey_private(data: dict[str, Any], spk_id: int) -> str:
    if _safe_int(data.get("signed_prekey_id", 0) or 0) == spk_id:
        return str(data.get("signed_prekey_priv", "") or "")
    for item in list(data.get("signed_prekey_history") or []):
        if _safe_int(item.get("signed_prekey_id", 0) or 0) == spk_id:
            return str(item.get("signed_prekey_priv", "") or "")
    return ""


def ensure_wormhole_prekeys(force_signed_prekey: bool = False, replenish_target: int = PREKEY_TARGET) -> dict[str, Any]:
    data = read_wormhole_identity()
    if not data.get("bootstrapped"):
        bootstrap_wormhole_identity()
        data = read_wormhole_identity()

    changed = False
    now = int(time.time())
    _, jitter_target = _jittered_republish_policy(data)
    replenish_target = max(1, _safe_int(replenish_target or jitter_target, 1))

    spk_generated_at = _safe_int(data.get("signed_prekey_generated_at", 0) or 0)
    spk_too_old = bool(spk_generated_at and (now - spk_generated_at) >= SIGNED_PREKEY_ROTATE_AFTER_S)
    if force_signed_prekey or spk_too_old or not data.get("signed_prekey_pub") or not data.get("signed_prekey_priv"):
        _archive_current_signed_prekey(data, now)
        pair = _x25519_pair()
        spk_id = _safe_int(data.get("signed_prekey_id", 0) or 0) + 1
        signed_prekey_payload = {
            "signed_prekey_id": spk_id,
            "signed_prekey_pub": pair["public_key"],
            "signed_prekey_timestamp": now,
        }
        signed = sign_wormhole_event(
            event_type="dm_signed_prekey",
            payload=signed_prekey_payload,
        )
        data["signed_prekey_id"] = spk_id
        data["signed_prekey_pub"] = pair["public_key"]
        data["signed_prekey_priv"] = pair["private_key"]
        data["signed_prekey_signature"] = signed["signature"]
        data["signed_prekey_generated_at"] = now
        changed = True

    existing_otks = list(data.get("one_time_prekeys") or [])
    next_id = max([_safe_int(item.get("prekey_id", 0) or 0) for item in existing_otks] + [0])
    while len(existing_otks) < max(1, replenish_target):
        next_id += 1
        pair = _x25519_pair()
        existing_otks.append(
            {
                "prekey_id": next_id,
                "public_key": pair["public_key"],
                "private_key": pair["private_key"],
                "created_at": now,
            }
        )
        changed = True
    data["one_time_prekeys"] = existing_otks
    _jittered_republish_policy(data)

    if changed:
        _write_identity(data)
    return _bundle_payload(data)


def register_wormhole_prekey_bundle(force_signed_prekey: bool = False) -> dict[str, Any]:
    data = read_wormhole_identity()
    if not data.get("bootstrapped"):
        bootstrap_wormhole_identity()
        data = read_wormhole_identity()

    _, jitter_target = _jittered_republish_policy(data, reset=force_signed_prekey)
    if force_signed_prekey:
        _schedule_next_republish_window(data)
        _write_identity(data)
        data = read_wormhole_identity()

    bundle = ensure_wormhole_prekeys(force_signed_prekey=force_signed_prekey, replenish_target=jitter_target)
    from services.mesh.mesh_dm_mls import export_dm_key_package_for_alias

    mls_key_package = export_dm_key_package_for_alias(str(data.get("node_id", "") or ""))
    if not mls_key_package.get("ok"):
        return {"ok": False, "detail": str(mls_key_package.get("detail", "") or "mls key package unavailable")}
    bundle["mls_key_package"] = str(mls_key_package.get("mls_key_package", "") or "")
    bundle_signed_at = int(time.time())
    bundle["signed_at"] = bundle_signed_at
    bundle = _attach_bundle_root_distribution(bundle)
    bundle = _attach_bundle_root_attestation(
        agent_id=str(data.get("node_id", "") or ""),
        public_key=str(data.get("public_key", "") or ""),
        public_key_algo=str(data.get("public_key_algo", "Ed25519") or "Ed25519"),
        protocol_version=PROTOCOL_VERSION,
        bundle=bundle,
    )
    bundle = _attach_bundle_signature(bundle, signed_at=bundle_signed_at)
    enforce_local_external_sources = _local_external_root_sources_configured()
    ok, reason = _validate_bundle_record(
        {
            "bundle": bundle,
            "public_key": str(data.get("public_key", "") or ""),
            "agent_id": str(data.get("node_id", "") or ""),
        },
        enforce_local_external_sources=enforce_local_external_sources,
    )
    if not ok:
        return {"ok": False, "detail": reason}
    signed = sign_wormhole_event(
        event_type="dm_prekey_bundle",
        payload=bundle,
    )

    from services.mesh.mesh_dm_relay import dm_relay

    lookup_aliases = get_prekey_lookup_handle_records()
    accepted, detail, metadata = dm_relay.register_prekey_bundle(
        signed["node_id"],
        bundle,
        signed["signature"],
        signed["public_key"],
        signed["public_key_algo"],
        signed["protocol_version"],
        signed["sequence"],
        lookup_aliases=lookup_aliases,
    )
    if not accepted:
        return {"ok": False, "detail": detail}
    refreshed = read_wormhole_identity()
    refreshed["prekey_bundle_registered_at"] = int(time.time())
    refreshed["prekey_bundle_signed_at"] = _safe_int(bundle.get("signed_at", 0) or 0)
    refreshed["prekey_bundle_signature"] = str(bundle.get("bundle_signature", "") or "")
    refreshed["prekey_transparency_head"] = str(metadata.get("prekey_transparency_head", "") or "") if metadata else ""
    refreshed["prekey_transparency_size"] = _safe_int(
        metadata.get("prekey_transparency_size", 0) if metadata else 0,
        0,
    )
    _schedule_next_republish_window(refreshed)
    _jittered_republish_policy(refreshed, reset=True)
    _write_identity(refreshed)
    return {
        "ok": True,
        "agent_id": signed["node_id"],
        "bundle": bundle,
        "signature": signed["signature"],
        "public_key": signed["public_key"],
        "public_key_algo": signed["public_key_algo"],
        "protocol_version": signed["protocol_version"],
        "sequence": signed["sequence"],
        **(metadata or {}),
    }


def fetch_dm_prekey_bundle(
    agent_id: str = "",
    lookup_token: str = "",
    *,
    allow_peer_lookup: bool = True,
) -> dict[str, Any]:
    from services.mesh.mesh_dm_relay import dm_relay

    resolved_id = str(agent_id or "").strip()
    stored = None
    resolved_lookup = str(lookup_token or "").strip()
    lookup_mode = "legacy_agent_id"

    if not resolved_lookup and resolved_id:
        try:
            from services.mesh.mesh_wormhole_contacts import preferred_prekey_lookup_handle

            resolved_lookup = preferred_prekey_lookup_handle(resolved_id)
        except Exception:
            resolved_lookup = ""

    # Prefer lookup_token to avoid exposing stable agent_id to the relay.
    if resolved_lookup:
        found, found_id = dm_relay.get_prekey_bundle_by_lookup(resolved_lookup)
        if found and found_id:
            stored = found
            resolved_id = found_id
            lookup_mode = "invite_lookup_handle"
        elif allow_peer_lookup:
            peer_found = _fetch_dm_prekey_bundle_from_peer_lookup(resolved_lookup)
            if peer_found.get("ok"):
                return peer_found
            return {"ok": False, "detail": str(peer_found.get("detail", "") or "Prekey bundle not found")}
        else:
            return {"ok": False, "detail": "Prekey bundle not found"}

    # Fallback to direct agent_id lookup (legacy path).
    if not stored and resolved_id:
        blocked = legacy_agent_id_lookup_blocked()
        record_legacy_agent_id_lookup(
            resolved_id,
            lookup_kind="prekey_bundle",
            blocked=blocked,
        )
        _warn_legacy_prekey_lookup(resolved_id)
        if blocked:
            return {
                "ok": False,
                "detail": "legacy agent_id lookup disabled; use invite lookup handle",
                "removal_target": sunset_target_label(LEGACY_AGENT_ID_LOOKUP_TARGET),
            }
        stored = dm_relay.get_prekey_bundle(resolved_id)

    if not stored:
        return {"ok": False, "detail": "Prekey bundle not found"}
    validated_record = {**dict(stored), "agent_id": resolved_id}
    ok, reason = _validate_bundle_record(validated_record)
    if not ok:
        return {"ok": False, "detail": reason}
    full_bundle = dict(stored.get("bundle") or {})
    bundle = dict(full_bundle)
    bundle["one_time_prekeys"] = []
    bundle["one_time_prekey_count"] = _safe_int(bundle.get("one_time_prekey_count", 0) or 0)
    witnesses = dm_relay.get_witnesses(
        resolved_id,
        str(bundle.get("identity_dh_pub_key", "") or "").strip() or None,
        limit=5,
    )
    return {
        "ok": True,
        "agent_id": resolved_id,
        "lookup_mode": lookup_mode,
        **bundle,
        "bundle": full_bundle,
        "signature": str(stored.get("signature", "") or ""),
        "public_key": str(stored.get("public_key", "") or ""),
        "public_key_algo": str(stored.get("public_key_algo", "") or ""),
        "protocol_version": str(stored.get("protocol_version", "") or ""),
        "sequence": _safe_int(stored.get("sequence", 0) or 0),
        "prekey_transparency_head": str(stored.get("prekey_transparency_head", "") or ""),
        "prekey_transparency_size": _safe_int(stored.get("prekey_transparency_size", 0) or 0),
        "prekey_transparency_fingerprint": str(stored.get("prekey_transparency_fingerprint", "") or ""),
        "witness_count": len(witnesses),
        "witness_latest_at": max((_safe_int(item.get("timestamp", 0) or 0) for item in witnesses), default=0),
        "trust_fingerprint": trust_fingerprint_for_bundle_record(validated_record),
    }


def _consume_local_one_time_prekey(prekey_id: int) -> int:
    if prekey_id <= 0:
        data = read_wormhole_identity()
        return len(list(data.get("one_time_prekeys") or []))
    data = read_wormhole_identity()
    existing = list(data.get("one_time_prekeys") or [])
    filtered = [
        item for item in existing if _safe_int(item.get("prekey_id", 0) or 0) != _safe_int(prekey_id)
    ]
    if len(filtered) == len(existing):
        return len(existing)
    data["one_time_prekeys"] = filtered
    _write_identity(data)
    return len(filtered)


def _classify_root_attestation_failure(peer_id: str) -> tuple[str, bool]:
    from services.mesh.mesh_wormhole_contacts import get_contact_trust_level

    current_level = str(get_contact_trust_level(peer_id) or "").strip()
    if current_level in ("invite_pinned", "sas_verified", "continuity_broken"):
        return "continuity_broken", True
    if current_level in ("tofu_pinned", "mismatch"):
        return "mismatch", True
    return "", False


def bootstrap_encrypt_for_peer(peer_id: str, plaintext: str) -> dict[str, Any]:
    fetched_bundle = fetch_dm_prekey_bundle(str(peer_id or "").strip())
    if not fetched_bundle.get("ok"):
        detail = str(fetched_bundle.get("detail", "") or "")
        if "root attestation" in detail.lower():
            trust_level, trust_changed = _classify_root_attestation_failure(str(peer_id or "").strip())
            if trust_level:
                return {
                    "ok": False,
                    "peer_id": str(peer_id or "").strip(),
                    "detail": detail,
                    "trust_changed": trust_changed,
                    "trust_level": trust_level,
                }
        return fetched_bundle

    from services.mesh.mesh_dm_relay import dm_relay

    resolved_peer_id = str(fetched_bundle.get("agent_id", peer_id) or peer_id).strip()
    stored = dm_relay.get_prekey_bundle(resolved_peer_id)
    if not stored:
        return {"ok": False, "detail": "Peer prekey bundle not found"}
    validated_record = {**dict(stored), "agent_id": resolved_peer_id}
    ok, reason = _validate_bundle_record(validated_record)
    if not ok:
        return {"ok": False, "detail": reason}
    trust_state = observe_remote_prekey_bundle(resolved_peer_id, validated_record)
    trust_level = str(trust_state.get("trust_level", "") or "")
    from services.mesh.mesh_wormhole_contacts import verified_first_contact_requirement

    verified_first_contact = verified_first_contact_requirement(
        resolved_peer_id,
        trust_level=trust_level,
    )
    if not verified_first_contact.get("ok"):
        return {
            "ok": False,
            "peer_id": resolved_peer_id,
            "detail": str(verified_first_contact.get("detail", "") or "verified first contact required"),
            "trust_changed": trust_level in ("mismatch", "continuity_broken"),
            "trust_level": str(verified_first_contact.get("trust_level", "") or trust_level or "unpinned"),
        }
    peer_bundle_stored = dm_relay.consume_one_time_prekey(resolved_peer_id)
    if not peer_bundle_stored:
        return {"ok": False, "detail": "Peer prekey bundle not found"}
    peer_bundle = dict(peer_bundle_stored.get("bundle") or {})
    peer_static = str(peer_bundle.get("identity_dh_pub_key", "") or "")
    peer_spk = str(peer_bundle.get("signed_prekey_pub", "") or "")
    peer_spk_id = _safe_int(peer_bundle.get("signed_prekey_id", 0) or 0)
    peer_otk = dict(peer_bundle_stored.get("claimed_one_time_prekey") or {})

    data = read_wormhole_identity()
    if not data.get("bootstrapped"):
        bootstrap_wormhole_identity()
        data = read_wormhole_identity()
    my_static_priv = str(data.get("dh_private_key", "") or "")
    my_static_pub = str(data.get("dh_pub_key", "") or "")
    if not my_static_priv or not my_static_pub or not peer_static or not peer_spk:
        return {"ok": False, "detail": "Missing static or signed prekey material"}

    eph = _x25519_pair()
    dh_parts = [
        _derive(my_static_priv, peer_spk),
        _derive(eph["private_key"], peer_static),
        _derive(eph["private_key"], peer_spk),
    ]
    otk_id = 0
    if peer_otk and peer_otk.get("public_key"):
        dh_parts.append(_derive(eph["private_key"], str(peer_otk.get("public_key"))))
        otk_id = _safe_int(peer_otk.get("prekey_id", 0) or 0)
    secret = _hkdf(b"".join(dh_parts), "SB-X3DH", 32)
    header = {
        "v": 1,
        "alg": "X25519",
        "ik_pub": my_static_pub,
        "ek_pub": eph["public_key"],
        "spk_id": peer_spk_id,
        "otk_id": otk_id,
    }
    aad = _stable_json(header).encode("utf-8")
    iv = os.urandom(12)
    ciphertext = AESGCM(secret).encrypt(iv, plaintext.encode("utf-8"), aad)
    envelope = {
        "h": header,
        "ct": _b64(iv + ciphertext),
    }
    wrapped = _b64(_stable_json(envelope).encode("utf-8"))
    return {
        "ok": True,
        "result": f"x3dh1:{wrapped}",
        "trust_level": trust_level or "unpinned",
    }


def bootstrap_decrypt_from_sender(sender_id: str, ciphertext: str) -> dict[str, Any]:
    if not ciphertext.startswith("x3dh1:"):
        return {"ok": False, "detail": "legacy"}
    try:
        raw = ciphertext[len("x3dh1:") :]
        envelope = json.loads(_unb64(raw).decode("utf-8"))
        header = dict(envelope.get("h") or {})
        combined = _unb64(str(envelope.get("ct") or ""))
        my_data = read_wormhole_identity()
        if not my_data.get("bootstrapped"):
            bootstrap_wormhole_identity()
            my_data = read_wormhole_identity()

        sender_static_pub = str(header.get("ik_pub", "") or "")
        sender_eph_pub = str(header.get("ek_pub", "") or "")
        spk_id = _safe_int(header.get("spk_id", 0) or 0)
        otk_id = _safe_int(header.get("otk_id", 0) or 0)
        if not sender_static_pub or not sender_eph_pub:
            return {"ok": False, "detail": "Missing sender bootstrap keys"}

        try:
            from services.mesh.mesh_wormhole_contacts import list_wormhole_dm_contacts

            contact = dict(list_wormhole_dm_contacts().get(str(sender_id or "").strip(), {}) or {})
            pinned_invite_dh = str(contact.get("invitePinnedDhPubKey", "") or "").strip()
            if pinned_invite_dh and pinned_invite_dh != sender_static_pub:
                return {
                    "ok": False,
                    "detail": "sender bootstrap key mismatches pinned invite",
                    "trust_level": str(contact.get("trust_level", "") or "") or "invite_pinned",
                }
        except Exception:
            pass

        from services.mesh.mesh_dm_relay import dm_relay

        sender_dh = dm_relay.get_dh_key(sender_id)
        if sender_dh and sender_dh.get("dh_pub_key") and str(sender_dh.get("dh_pub_key")) != sender_static_pub:
            return {"ok": False, "detail": "Sender static DH key mismatch"}

        signed_prekey_priv = _find_signed_prekey_private(my_data, spk_id)
        my_static_priv = str(my_data.get("dh_private_key", "") or "")
        if not signed_prekey_priv or not my_static_priv:
            return {"ok": False, "detail": "Missing local bootstrap private keys"}

        dh_parts = [
            _derive(signed_prekey_priv, sender_static_pub),
            _derive(my_static_priv, sender_eph_pub),
            _derive(signed_prekey_priv, sender_eph_pub),
        ]
        if otk_id:
            otk_match = next(
                (
                    item
                    for item in list(my_data.get("one_time_prekeys") or [])
                    if _safe_int(item.get("prekey_id", 0) or 0) == otk_id and item.get("private_key")
                ),
                None,
            )
            if not otk_match:
                return {"ok": False, "detail": "One-time prekey mismatch"}
            dh_parts.append(_derive(str(otk_match.get("private_key", "")), sender_eph_pub))

        secret = _hkdf(b"".join(dh_parts), "SB-X3DH", 32)
        aad = _stable_json(header).encode("utf-8")
        iv = combined[:12]
        ct = combined[12:]
        plaintext = AESGCM(secret).decrypt(iv, ct, aad).decode("utf-8")
        if otk_id:
            remaining_otks = _consume_local_one_time_prekey(otk_id)
            my_data = read_wormhole_identity()
            threshold, target = _jittered_republish_policy(my_data)
            next_republish_after = _safe_int(my_data.get("prekey_next_republish_after", 0) or 0)
            now_ts = int(time.time())
            should_republish = remaining_otks <= 0
            if not should_republish and remaining_otks <= threshold and now_ts >= next_republish_after:
                should_republish = True
            if should_republish:
                register_wormhole_prekey_bundle()
            else:
                _write_identity(my_data)
        return {"ok": True, "result": plaintext}
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or "bootstrap_decrypt_failed"}
