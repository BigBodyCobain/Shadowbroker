"""Wormhole-owned DM contact and alias graph state."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from services.mesh.mesh_secure_storage import read_secure_json, write_secure_json

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CONTACTS_FILE = DATA_DIR / "wormhole_dm_contacts.json"


def _default_contact() -> dict[str, Any]:
    return {
        "alias": "",
        "blocked": False,
        "dhPubKey": "",
        "dhAlgo": "",
        "sharedAlias": "",
        "previousSharedAliases": [],
        "pendingSharedAlias": "",
        "sharedAliasGraceUntil": 0,
        "sharedAliasRotatedAt": 0,
        "verify_inband": False,
        "verify_registry": False,
        "verified": False,
        "verify_mismatch": False,
        "verified_at": 0,
        "remotePrekeyFingerprint": "",
        "remotePrekeyObservedFingerprint": "",
        "remotePrekeyPinnedAt": 0,
        "remotePrekeyLastSeenAt": 0,
        "remotePrekeySequence": 0,
        "remotePrekeySignedAt": 0,
        "remotePrekeyMismatch": False,
        "witness_count": 0,
        "witness_checked_at": 0,
        "vouch_count": 0,
        "vouch_checked_at": 0,
        "updated_at": 0,
    }


def _normalize_contact(value: dict[str, Any] | None) -> dict[str, Any]:
    current = _default_contact()
    current.update(value or {})
    current["alias"] = str(current.get("alias", "") or "")
    current["blocked"] = bool(current.get("blocked"))
    current["dhPubKey"] = str(current.get("dhPubKey", "") or "")
    current["dhAlgo"] = str(current.get("dhAlgo", "") or "")
    current["sharedAlias"] = str(current.get("sharedAlias", "") or "")
    current["previousSharedAliases"] = [
        str(item or "") for item in list(current.get("previousSharedAliases") or []) if str(item or "").strip()
    ][-8:]
    current["pendingSharedAlias"] = str(current.get("pendingSharedAlias", "") or "")
    current["remotePrekeyFingerprint"] = str(current.get("remotePrekeyFingerprint", "") or "")
    current["remotePrekeyObservedFingerprint"] = str(current.get("remotePrekeyObservedFingerprint", "") or "")
    for key in (
        "sharedAliasGraceUntil",
        "sharedAliasRotatedAt",
        "verified_at",
        "remotePrekeyPinnedAt",
        "remotePrekeyLastSeenAt",
        "remotePrekeySequence",
        "remotePrekeySignedAt",
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
        "remotePrekeyMismatch",
    ):
        current[key] = bool(current.get(key))
    return current


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


def _promote_pending_alias_if_due(contact: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    current = _normalize_contact(contact)
    pending = str(current.get("pendingSharedAlias", "") or "").strip()
    grace_until = int(current.get("sharedAliasGraceUntil", 0) or 0)
    if not pending or grace_until <= 0 or grace_until > int(time.time() * 1000):
        return current, False
    active = str(current.get("sharedAlias", "") or "").strip()
    promoted = dict(current)
    promoted["sharedAlias"] = pending or active
    promoted["pendingSharedAlias"] = ""
    promoted["sharedAliasGraceUntil"] = 0
    promoted["sharedAliasRotatedAt"] = int(time.time() * 1000)
    promoted["previousSharedAliases"] = _merge_alias_history(
        active,
        *list(current.get("previousSharedAliases") or []),
    )
    return _normalize_contact(promoted), True


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
        contacts[key] = normalized
        changed = changed or promoted
    if changed:
        _write_contacts(contacts)
    return contacts


def _write_contacts(contacts: dict[str, dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        str(peer_id): _normalize_contact(contact)
        for peer_id, contact in contacts.items()
        if str(peer_id or "").strip()
    }
    write_secure_json(CONTACTS_FILE, payload)


def list_wormhole_dm_contacts() -> dict[str, dict[str, Any]]:
    return _read_contacts()


def upsert_wormhole_dm_contact(peer_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    peer_id = str(peer_id or "").strip()
    if not peer_id:
        raise ValueError("peer_id required")
    contacts = _read_contacts()
    merged = _normalize_contact({**contacts.get(peer_id, _default_contact()), **dict(updates or {})})
    merged["updated_at"] = int(time.time())
    contacts[peer_id] = merged
    _write_contacts(contacts)
    return merged


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

    current["remotePrekeyObservedFingerprint"] = candidate
    current["remotePrekeyLastSeenAt"] = now
    current["remotePrekeySequence"] = int(sequence or 0)
    current["remotePrekeySignedAt"] = int(signed_at or 0)

    trust_changed = False
    if not pinned:
        current["remotePrekeyFingerprint"] = candidate
        current["remotePrekeyPinnedAt"] = now
        current["remotePrekeyMismatch"] = False
        pinned = candidate
    else:
        trust_changed = pinned != candidate
        current["remotePrekeyMismatch"] = trust_changed

    current["updated_at"] = int(time.time())
    contacts[peer_key] = _normalize_contact(current)
    _write_contacts(contacts)
    return {
        "ok": True,
        "peer_id": peer_key,
        "trust_changed": trust_changed,
        "contact": contacts[peer_key],
    }
