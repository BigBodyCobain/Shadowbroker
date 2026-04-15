"""Wormhole-managed prekey bundles and X3DH-style bootstrap helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import time
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from services.mesh.mesh_crypto import derive_node_id
from services.mesh.mesh_wormhole_identity import (
    _write_identity,
    bootstrap_wormhole_identity,
    read_wormhole_identity,
    sign_wormhole_event,
    sign_wormhole_message,
)

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


def _safe_int(val, default=0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


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


def _bundle_signature_payload(data: dict[str, Any]) -> str:
    # OTK binding: One-time key hashes are included in the bundle signature
    # as of Sprint 12 (S12-3). Relay substitution of OTKs will now break
    # the bundle signature and be rejected by verify_prekey_bundle().
    otk_hashes = sorted(
        hashlib.sha256(str(item.get("public_key", "")).encode("utf-8")).hexdigest()
        for item in (data.get("one_time_prekeys") or [])
    )
    return _stable_json(
        {
            "identity_dh_pub_key": str(data.get("identity_dh_pub_key", "") or ""),
            "dh_algo": str(data.get("dh_algo", "X25519") or "X25519"),
            "signed_prekey_id": _safe_int(data.get("signed_prekey_id", 0) or 0),
            "signed_prekey_pub": str(data.get("signed_prekey_pub", "") or ""),
            "signed_prekey_signature": str(data.get("signed_prekey_signature", "") or ""),
            "signed_at": _safe_int(data.get("signed_at", 0) or 0),
            "mls_key_package": str(data.get("mls_key_package", "") or ""),
            "one_time_prekey_hashes": otk_hashes,
        }
    )


def _max_prekey_bundle_age_s() -> int:
    return SIGNED_PREKEY_ROTATE_AFTER_S + SIGNED_PREKEY_GRACE_S


def trust_fingerprint_for_bundle_record(record: dict[str, Any]) -> str:
    bundle = dict(record.get("bundle") or record or {})
    material = {
        "agent_id": str(record.get("agent_id", "") or ""),
        "identity_dh_pub_key": str(bundle.get("identity_dh_pub_key", "") or ""),
        "dh_algo": str(bundle.get("dh_algo", "X25519") or "X25519"),
        "public_key": str(record.get("public_key", "") or ""),
        "public_key_algo": str(record.get("public_key_algo", "") or ""),
        "protocol_version": str(record.get("protocol_version", "") or ""),
    }
    return hashlib.sha256(_stable_json(material).encode("utf-8")).hexdigest()


def _attach_bundle_signature(bundle: dict[str, Any], *, signed_at: int | None = None) -> dict[str, Any]:
    # KNOWN LIMITATION: Bundle signature is self-signed by the identity key it contains.
    # This proves possession of the private key and detects post-registration tampering,
    # but cannot prevent initial impersonation (no external PKI). Mitigated by reputation
    # system in Phase 9 (Oracle Rep). See threat-model.md for full analysis.
    payload = dict(bundle or {})
    payload["signed_at"] = int(signed_at if signed_at is not None else time.time())
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


def _validate_bundle_record(record: dict[str, Any]) -> tuple[bool, str]:
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
    ok, reason = _verify_bundle_signature(bundle, public_key)
    if not ok:
        return False, reason
    if (now - signed_at) > _max_prekey_bundle_age_s():
        return False, "Prekey bundle is stale"
    if str(record.get("agent_id", "") or "").strip():
        derived = derive_node_id(public_key)
        if derived != str(record.get("agent_id", "") or "").strip():
            return False, "Prekey bundle public key binding mismatch"
    return True, "ok"


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
    bundle = _attach_bundle_signature(bundle)
    signed = sign_wormhole_event(
        event_type="dm_prekey_bundle",
        payload=bundle,
    )

    from services.mesh.mesh_dm_relay import dm_relay

    accepted, detail, metadata = dm_relay.register_prekey_bundle(
        signed["node_id"],
        bundle,
        signed["signature"],
        signed["public_key"],
        signed["public_key_algo"],
        signed["protocol_version"],
        signed["sequence"],
    )
    if not accepted:
        return {"ok": False, "detail": detail}
    refreshed = read_wormhole_identity()
    refreshed["prekey_bundle_registered_at"] = int(time.time())
    refreshed["prekey_bundle_signed_at"] = _safe_int(bundle.get("signed_at", 0) or 0)
    refreshed["prekey_bundle_signature"] = str(bundle.get("bundle_signature", "") or "")
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


def fetch_dm_prekey_bundle(agent_id: str) -> dict[str, Any]:
    from services.mesh.mesh_dm_relay import dm_relay

    stored = dm_relay.get_prekey_bundle(agent_id)
    if not stored:
        return {"ok": False, "detail": "Prekey bundle not found"}
    validated_record = {**dict(stored), "agent_id": str(agent_id or "").strip()}
    ok, reason = _validate_bundle_record(validated_record)
    if not ok:
        return {"ok": False, "detail": reason}
    bundle = dict(stored.get("bundle") or {})
    bundle["one_time_prekeys"] = []
    bundle["one_time_prekey_count"] = _safe_int(bundle.get("one_time_prekey_count", 0) or 0)
    return {
        "ok": True,
        "agent_id": agent_id,
        **bundle,
        "signature": str(stored.get("signature", "") or ""),
        "public_key": str(stored.get("public_key", "") or ""),
        "public_key_algo": str(stored.get("public_key_algo", "") or ""),
        "protocol_version": str(stored.get("protocol_version", "") or ""),
        "sequence": _safe_int(stored.get("sequence", 0) or 0),
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


def bootstrap_encrypt_for_peer(peer_id: str, plaintext: str) -> dict[str, Any]:
    from services.mesh.mesh_dm_relay import dm_relay

    stored = dm_relay.get_prekey_bundle(peer_id)
    if not stored:
        return {"ok": False, "detail": "Peer prekey bundle not found"}
    validated_record = {**dict(stored), "agent_id": str(peer_id or "").strip()}
    ok, reason = _validate_bundle_record(validated_record)
    if not ok:
        return {"ok": False, "detail": reason}
    peer_bundle_stored = dm_relay.consume_one_time_prekey(peer_id)
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
    return {"ok": True, "result": f"x3dh1:{wrapped}"}


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
