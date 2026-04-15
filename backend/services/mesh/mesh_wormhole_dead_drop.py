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
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric import x25519

from services.mesh.mesh_wormhole_identity import bootstrap_wormhole_identity, read_wormhole_identity
from services.mesh.mesh_wormhole_contacts import list_wormhole_dm_contacts, upsert_wormhole_dm_contact
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


def _merge_alias_history(*aliases: str, limit: int = 8) -> list[str]:
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


def issue_pairwise_dm_alias(*, peer_id: str, peer_dh_pub: str = "") -> dict[str, Any]:
    peer_id = str(peer_id or "").strip()
    peer_dh_pub = str(peer_dh_pub or "").strip()
    if not peer_id:
        return {"ok": False, "detail": "peer_id required"}

    from services.mesh.mesh_wormhole_persona import (
        bootstrap_wormhole_persona_state,
        get_dm_identity,
    )

    bootstrap_wormhole_persona_state()
    dm_identity = get_dm_identity()
    current = dict(list_wormhole_dm_contacts().get(peer_id) or {})
    previous_alias = str(current.get("sharedAlias", "") or "").strip()
    shared_alias = _new_pairwise_alias()
    while shared_alias == previous_alias:
        shared_alias = _new_pairwise_alias()

    rotated_at_ms = int(time.time() * 1000)
    contact_updates: dict[str, Any] = {
        "sharedAlias": shared_alias,
        "pendingSharedAlias": "",
        "sharedAliasGraceUntil": 0,
        "sharedAliasRotatedAt": rotated_at_ms,
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

    contact = upsert_wormhole_dm_contact(peer_id, contact_updates)
    return {
        "ok": True,
        "peer_id": peer_id,
        "shared_alias": shared_alias,
        "replaced_alias": previous_alias,
        "identity_scope": "dm_alias",
        "dm_identity_id": str(dm_identity.get("node_id", "") or ""),
        "contact": contact,
    }


def rotate_pairwise_dm_alias(
    *,
    peer_id: str,
    peer_dh_pub: str = "",
    grace_ms: int = 45_000,
) -> dict[str, Any]:
    peer_id = str(peer_id or "").strip()
    peer_dh_pub = str(peer_dh_pub or "").strip()
    if not peer_id:
        return {"ok": False, "detail": "peer_id required"}

    from services.mesh.mesh_wormhole_persona import (
        bootstrap_wormhole_persona_state,
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
    if pending_alias and grace_until > now_ms:
        return {
            "ok": True,
            "peer_id": peer_id,
            "active_alias": active_alias,
            "pending_alias": pending_alias,
            "grace_until": grace_until,
            "identity_scope": "dm_alias",
            "dm_identity_id": str(dm_identity.get("node_id", "") or ""),
            "contact": current,
            "rotated": False,
        }

    next_alias = _new_pairwise_alias()
    reserved = {
        active_alias,
        pending_alias,
        *[str(item or "").strip() for item in list(current.get("previousSharedAliases") or [])],
    }
    while next_alias in reserved:
        next_alias = _new_pairwise_alias()

    clamped_grace_ms = max(5_000, min(int(grace_ms or 45_000), 5 * 60 * 1000))
    next_grace_until = now_ms + clamped_grace_ms
    contact_updates: dict[str, Any] = {
        "pendingSharedAlias": next_alias,
        "sharedAliasGraceUntil": next_grace_until,
        "sharedAliasRotatedAt": now_ms,
        "previousSharedAliases": _merge_alias_history(
            active_alias,
            pending_alias,
            *list(current.get("previousSharedAliases") or []),
        ),
    }
    if peer_dh_pub:
        contact_updates["dhPubKey"] = peer_dh_pub
    elif str(current.get("dhPubKey", "") or "").strip():
        contact_updates["dhPubKey"] = str(current.get("dhPubKey", "") or "").strip()
    if str(current.get("dhAlgo", "") or "").strip():
        contact_updates["dhAlgo"] = str(current.get("dhAlgo", "") or "").strip()

    contact = upsert_wormhole_dm_contact(peer_id, contact_updates)
    return {
        "ok": True,
        "peer_id": peer_id,
        "active_alias": active_alias,
        "pending_alias": next_alias,
        "grace_until": next_grace_until,
        "identity_scope": "dm_alias",
        "dm_identity_id": str(dm_identity.get("node_id", "") or ""),
        "contact": contact,
        "rotated": True,
    }


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


def _token_for(secret: bytes, peer_id: str, my_node_id: str, epoch: int) -> str:
    ids = "|".join(sorted([str(my_node_id or ""), str(peer_id or "")]))
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


def derive_dead_drop_token_pair(*, peer_id: str, peer_dh_pub: str) -> dict[str, Any]:
    peer_id = str(peer_id or "").strip()
    peer_dh_pub = str(peer_dh_pub or "").strip()
    if not peer_id or not peer_dh_pub:
        return {"ok": False, "detail": "peer_id and peer_dh_pub required"}

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
        "epoch": epoch,
        "current": _token_for(secret, peer_id, my_node_id, epoch),
        "previous": _token_for(secret, peer_id, my_node_id, epoch - 1),
    }


def derive_dead_drop_tokens_for_contacts(*, contacts: list[dict[str, Any]], limit: int = 24) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in contacts[: max(1, min(int(limit or 24), 64))]:
        peer_id = str((item or {}).get("peer_id", "") or "").strip()
        peer_dh_pub = str((item or {}).get("peer_dh_pub", "") or "").strip()
        if not peer_id or not peer_dh_pub:
            continue
        pair = derive_dead_drop_token_pair(peer_id=peer_id, peer_dh_pub=peer_dh_pub)
        if pair.get("ok"):
            results.append(
                {
                    "peer_id": peer_id,
                    "current": str(pair.get("current", "") or ""),
                    "previous": str(pair.get("previous", "") or ""),
                    "epoch": int(pair.get("epoch", 0) or 0),
                }
            )
    return {"ok": True, "tokens": results}


def derive_sas_phrase(*, peer_id: str, peer_dh_pub: str, words: int = 8) -> dict[str, Any]:
    peer_id = str(peer_id or "").strip()
    peer_dh_pub = str(peer_dh_pub or "").strip()
    word_count = max(2, min(int(words or 8), 16))
    if not peer_id or not peer_dh_pub:
        return {"ok": False, "detail": "peer_id and peer_dh_pub required"}

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

    ids = "|".join(sorted([my_node_id, peer_id]))
    digest = hmac.new(secret, f"sb_sas|v1|{ids}".encode("utf-8"), hashlib.sha256).digest()
    phrase = " ".join(_sas_words_from_digest(digest, word_count))
    return {"ok": True, "peer_id": peer_id, "phrase": phrase, "words": word_count}
