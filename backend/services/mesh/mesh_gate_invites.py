"""Cross-node gate key distribution over the Dead Drop DM lane.

Gate history is readable on another node only through the durable gate
envelope, which is keyed from the per-gate ``gate_secret``. Each node
generates that secret locally, so without distribution two operators in the
same gate cannot read each other. This module moves the secret between
members inside an end-to-end encrypted DM:

- ``invite``: a member hands the current secret to one contact. The
  recipient's operator must accept it explicitly.
- ``rekey``: a member rotates the secret and sends the new one to every
  contact it previously granted. Recipients apply it automatically only when
  it comes from their upstream (the peer they accepted the current key
  from); anything else waits for manual acceptance. A node that applies a
  rekey forwards it to its own grantees, minus the sender and any excluded
  peers, so the whole grant tree converges.

The secret is carried as a control frame inside the DM plaintext and is
stripped on decrypt, so it never reaches the browser or the visible mailbox.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from typing import Any, Callable

from services.mesh.mesh_local_custody import (
    read_sensitive_domain_json,
    write_sensitive_domain_json,
)
from services.mesh.mesh_privacy_logging import privacy_log_label

logger = logging.getLogger(__name__)

GATE_KEY_FRAME_KIND = "sb_gate_key_v1"
PENDING_DOMAIN = "gate_invites"
PENDING_FILENAME = "pending_gate_invites.json"
PENDING_CUSTODY_SCOPE = "gate_invite_pending_store"
PENDING_TTL_S = 14 * 24 * 3600
MAX_PENDING = 64
MAX_EXCLUDE = 64

# Contacts in these trust states never send or receive gate keys.
BLOCKED_TRUST_LEVELS = {"mismatch", "continuity_broken"}

_LOCK = threading.RLock()

# Overridable in tests; production sends through the operator DM lane.
_send_dm_impl: Callable[[str, str], dict[str, Any]] | None = None


def _send_dm(peer_id: str, plaintext: str) -> dict[str, Any]:
    if _send_dm_impl is not None:
        return _send_dm_impl(peer_id, plaintext)
    from services.openclaw_infonet import send_dm

    return send_dm(peer_id, plaintext)


def _gate_manager():
    from services.mesh.mesh_reputation import gate_manager

    return gate_manager


def secret_fingerprint(secret: str) -> str:
    """Short non-reversible id so peers can compare keys without revealing them."""
    return hashlib.sha256(f"sb-gate-secret-id|{secret}".encode("utf-8")).hexdigest()[:16]


def _local_epoch(gate_id: str) -> int:
    try:
        from services.mesh import mesh_gate_mls

        return int(mesh_gate_mls._sync_binding(gate_id).epoch or 0)
    except Exception:
        return 0


def _contact_check(peer_id: str) -> dict[str, Any]:
    from services.mesh.mesh_wormhole_contacts import get_wormhole_dm_contact

    contact = get_wormhole_dm_contact(peer_id)
    if contact is None:
        return {"ok": False, "detail": "recipient is not a DM contact; connect with them first"}
    trust_level = str(contact.get("trust_level", "") or "unpinned").strip().lower()
    if bool(contact.get("blocked")) or trust_level in BLOCKED_TRUST_LEVELS:
        return {"ok": False, "detail": f"contact trust state does not allow gate keys: {trust_level}"}
    return {"ok": True, "trust_level": trust_level}


def _trust_level(peer_id: str) -> str:
    try:
        from services.mesh.mesh_wormhole_contacts import get_contact_trust_level

        return get_contact_trust_level(peer_id)
    except Exception:
        return "unpinned"


def _build_frame(
    *,
    op: str,
    gate_id: str,
    display_name: str,
    secret: str,
    version: int,
    note: str = "",
    exclude: list[str] | None = None,
) -> str:
    frame = {
        "kind": GATE_KEY_FRAME_KIND,
        "op": op,
        "gate_id": gate_id,
        "gate_name": str(display_name or gate_id)[:64],
        "secret": secret,
        "secret_id": secret_fingerprint(secret),
        "version": int(version or 0),
        "issued_at": int(time.time()),
        "frame_id": secrets.token_hex(8),
        "note": str(note or "")[:240],
        "exclude": [str(p) for p in (exclude or [])][:MAX_EXCLUDE],
    }
    return json.dumps(frame, sort_keys=True, separators=(",", ":"))


def parse_gate_key_frame(plaintext: str) -> dict[str, Any] | None:
    raw = str(plaintext or "")
    if not raw.startswith("{") or GATE_KEY_FRAME_KIND not in raw:
        return None
    try:
        frame = json.loads(raw)
    except Exception:
        return None
    if not isinstance(frame, dict) or frame.get("kind") != GATE_KEY_FRAME_KIND:
        return None
    if frame.get("op") not in {"invite", "rekey"}:
        return None
    gate_id = str(frame.get("gate_id", "") or "").strip().lower()
    secret = str(frame.get("secret", "") or "").strip()
    if not gate_id or len(gate_id) > 64 or not secret or len(secret) > 128:
        return None
    if secret_fingerprint(secret) != str(frame.get("secret_id", "") or ""):
        return None
    frame["gate_id"] = gate_id
    frame["secret"] = secret
    exclude = frame.get("exclude")
    frame["exclude"] = [str(p) for p in exclude][:MAX_EXCLUDE] if isinstance(exclude, list) else []
    return frame


# --- pending store --------------------------------------------------------


def _read_pending() -> dict[str, dict[str, Any]]:
    raw = read_sensitive_domain_json(
        PENDING_DOMAIN,
        PENDING_FILENAME,
        lambda: {},
        custody_scope=PENDING_CUSTODY_SCOPE,
    )
    if not isinstance(raw, dict):
        return {}
    now = time.time()
    return {
        str(k): dict(v)
        for k, v in raw.items()
        if isinstance(v, dict) and now - float(v.get("received_at", 0) or 0) < PENDING_TTL_S
    }


def _write_pending(pending: dict[str, dict[str, Any]]) -> None:
    if len(pending) > MAX_PENDING:
        newest = sorted(pending.items(), key=lambda kv: float(kv[1].get("received_at", 0) or 0))[-MAX_PENDING:]
        pending = dict(newest)
    write_sensitive_domain_json(
        PENDING_DOMAIN,
        PENDING_FILENAME,
        pending,
        custody_scope=PENDING_CUSTODY_SCOPE,
    )


def _public_view(invite_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "invite_id": invite_id,
        "op": entry.get("op", "invite"),
        "gate_id": entry.get("gate_id", ""),
        "gate_name": entry.get("gate_name", ""),
        "from_peer_id": entry.get("from_peer_id", ""),
        "from_trust_level": _trust_level(str(entry.get("from_peer_id", "") or "")),
        "secret_id": entry.get("secret_id", ""),
        "version": int(entry.get("version", 0) or 0),
        "note": entry.get("note", ""),
        "received_at": int(entry.get("received_at", 0) or 0),
    }


def list_pending_gate_invites() -> dict[str, Any]:
    with _LOCK:
        pending = _read_pending()
    invites = [_public_view(k, v) for k, v in pending.items()]
    invites.sort(key=lambda item: -item["received_at"])
    return {"ok": True, "invites": invites}


# --- sending --------------------------------------------------------------


def send_gate_invite(gate_id: str, peer_id: str, *, note: str = "") -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    peer = str(peer_id or "").strip()
    if not gate_key or not peer:
        return {"ok": False, "detail": "gate_id and peer_id required"}
    manager = _gate_manager()
    gate = manager.get_gate(gate_key)
    if not gate:
        return {"ok": False, "detail": "Gate not found"}
    if manager.get_envelope_policy(gate_key) == "envelope_disabled":
        return {"ok": False, "detail": "gate has envelopes disabled; members on other nodes could not read it"}
    contact = _contact_check(peer)
    if not contact.get("ok"):
        return contact
    secret = manager.ensure_gate_secret(gate_key)
    if not secret:
        return {"ok": False, "detail": "gate secret unavailable"}
    version = int(manager.get_gate_key_meta(gate_key).get("gate_secret_version", 0) or 0)
    plaintext = _build_frame(
        op="invite",
        gate_id=gate_key,
        display_name=str(gate.get("display_name", "") or gate_key),
        secret=secret,
        version=version,
        note=note,
    )
    sent = _send_dm(peer, plaintext)
    if not isinstance(sent, dict) or not sent.get("ok"):
        detail = sent.get("detail") if isinstance(sent, dict) else "dm send failed"
        return {"ok": False, "detail": str(detail or "dm send failed")}
    manager.record_key_grant(gate_key, peer, secret_id=secret_fingerprint(secret), op="invite")
    logger.info(
        "Gate invite sent for %s to %s",
        privacy_log_label(gate_key, label="gate"),
        privacy_log_label(peer, label="peer"),
    )
    return {
        "ok": True,
        "gate_id": gate_key,
        "peer_id": peer,
        "secret_id": secret_fingerprint(secret),
        "recipient_trust_level": contact.get("trust_level", ""),
    }


def _distribute_rekey(
    gate_id: str,
    *,
    skip_peer_ids: set[str],
    exclude: list[str],
) -> dict[str, Any]:
    manager = _gate_manager()
    gate = manager.get_gate(gate_id) or {}
    secret = manager.get_gate_secret(gate_id)
    meta = manager.get_gate_key_meta(gate_id)
    version = int(meta.get("gate_secret_version", 0) or 0)
    plaintext = _build_frame(
        op="rekey",
        gate_id=gate_id,
        display_name=str(gate.get("display_name", "") or gate_id),
        secret=secret,
        version=version,
        exclude=exclude,
    )
    delivered: list[str] = []
    failed: list[dict[str, str]] = []
    for peer in sorted(meta.get("key_grants", {})):
        if peer in skip_peer_ids:
            continue
        if not _contact_check(peer).get("ok"):
            failed.append({"peer_id": peer, "detail": "contact unavailable"})
            continue
        sent = _send_dm(peer, plaintext)
        if isinstance(sent, dict) and sent.get("ok"):
            manager.record_key_grant(gate_id, peer, secret_id=secret_fingerprint(secret), op="rekey")
            delivered.append(peer)
        else:
            failed.append({"peer_id": peer, "detail": str((sent or {}).get("detail") or "dm send failed")})
    return {"delivered": delivered, "failed": failed}


def rotate_gate_key(gate_id: str, *, exclude_peer_ids: list[str] | None = None, reason: str = "manual") -> dict[str, Any]:
    """Generate a new gate secret and send it to every grantee not excluded."""
    gate_key = str(gate_id or "").strip().lower()
    manager = _gate_manager()
    if not manager.get_gate(gate_key):
        return {"ok": False, "detail": "Gate not found"}
    exclude = sorted({str(p).strip() for p in (exclude_peer_ids or []) if str(p).strip()})[:MAX_EXCLUDE]
    with manager._gate_lock:
        manager._rotate_gate_secret_for_member_removal_locked(
            gate_key,
            reason=f"rekey:{reason}",
            previous_valid_through_epoch=_local_epoch(gate_key),
        )
    manager.drop_key_grants(gate_key, exclude)
    result = _distribute_rekey(gate_key, skip_peer_ids=set(exclude), exclude=exclude)
    return {
        "ok": True,
        "gate_id": gate_key,
        "secret_id": secret_fingerprint(manager.get_gate_secret(gate_key)),
        "excluded": exclude,
        **result,
    }


def redistribute_after_local_rotation(gate_id: str) -> dict[str, Any]:
    """Send the already-rotated local secret to grantees (ban/kick path)."""
    gate_key = str(gate_id or "").strip().lower()
    if not _gate_manager().get_gate_key_meta(gate_key).get("key_grants"):
        return {"delivered": [], "failed": []}
    return _distribute_rekey(gate_key, skip_peer_ids=set(), exclude=[])


# --- receiving ------------------------------------------------------------


def _apply(entry: dict[str, Any], *, from_peer_id: str) -> dict[str, Any]:
    manager = _gate_manager()
    gate_key = str(entry.get("gate_id", "") or "")
    if not manager.get_gate(gate_key):
        return {"ok": False, "detail": "gate is not known on this node"}
    adopted = manager.adopt_gate_secret(
        gate_key,
        str(entry.get("secret", "") or ""),
        version=int(entry.get("version", 0) or 0),
        upstream_peer_id=from_peer_id,
        previous_valid_through_epoch=_local_epoch(gate_key),
    )
    if not adopted.get("ok"):
        return adopted
    forwarded: dict[str, Any] = {"delivered": [], "failed": []}
    if adopted.get("changed") and entry.get("op") == "rekey":
        exclude = list(entry.get("exclude") or [])
        manager.drop_key_grants(gate_key, exclude)
        forwarded = _distribute_rekey(
            gate_key,
            skip_peer_ids={from_peer_id, *exclude},
            exclude=exclude,
        )
    return {
        "ok": True,
        "gate_id": gate_key,
        "changed": bool(adopted.get("changed")),
        "secret_id": entry.get("secret_id", ""),
        "forwarded": forwarded,
    }


def receive_gate_key_frame(from_peer_id: str, frame: dict[str, Any]) -> dict[str, Any]:
    """Handle a decrypted gate-key frame. Returns a summary without the secret."""
    sender = str(from_peer_id or "").strip()
    gate_key = frame["gate_id"]
    summary = {
        "op": frame["op"],
        "gate_id": gate_key,
        "gate_name": str(frame.get("gate_name", "") or gate_key),
        "secret_id": frame["secret_id"],
        "from_peer_id": sender,
    }
    manager = _gate_manager()
    if not sender or not _contact_check(sender).get("ok"):
        summary["status"] = "rejected_untrusted_sender"
        return summary
    if manager.get_gate_secret(gate_key) == frame["secret"]:
        summary["status"] = "already_current"
        return summary
    meta = manager.get_gate_key_meta(gate_key)
    from_upstream = bool(meta) and meta.get("key_upstream") == sender
    if frame["op"] == "rekey" and from_upstream:
        applied = _apply(frame, from_peer_id=sender)
        summary["status"] = "applied" if applied.get("ok") else "apply_failed"
        return summary
    entry = {
        "op": frame["op"],
        "gate_id": gate_key,
        "gate_name": summary["gate_name"],
        "secret": frame["secret"],
        "secret_id": frame["secret_id"],
        "version": int(frame.get("version", 0) or 0),
        "note": str(frame.get("note", "") or ""),
        "exclude": list(frame.get("exclude") or []),
        "from_peer_id": sender,
        "received_at": time.time(),
    }
    invite_id = secrets.token_hex(8)
    with _LOCK:
        pending = _read_pending()
        # One pending entry per (gate, sender): a newer frame supersedes.
        for key, existing in list(pending.items()):
            if existing.get("gate_id") == gate_key and existing.get("from_peer_id") == sender:
                pending.pop(key, None)
        pending[invite_id] = entry
        _write_pending(pending)
    summary["status"] = "pending"
    summary["invite_id"] = invite_id
    return summary


def intercept_dm_plaintext(peer_id: str, plaintext: str) -> tuple[str, dict[str, Any] | None]:
    """Strip a gate-key frame out of decrypted DM text.

    Returns the text to show the user and, when a frame was present, a
    secret-free summary of what happened to it.
    """
    frame = parse_gate_key_frame(plaintext)
    if frame is None:
        return plaintext, None
    try:
        summary = receive_gate_key_frame(peer_id, frame)
    except Exception:
        logger.exception("gate key frame handling failed")
        summary = {"op": frame["op"], "gate_id": frame["gate_id"], "status": "error"}
    name = summary.get("gate_name") or frame["gate_id"]
    status = summary.get("status", "")
    if status == "pending":
        label = "invited you to" if frame["op"] == "invite" else "sent a new key for"
        text = f"[Gate key] This contact {label} '{name}'. Open Gate invites in Messages or the gate's key panel to accept."
    elif status == "applied":
        text = f"[Gate key] Key for '{name}' was rotated by your upstream member and applied."
    elif status == "already_current":
        text = f"[Gate key] You already hold the current key for '{name}'."
    else:
        text = f"[Gate key] A key for '{name}' was received but not accepted ({status or 'error'})."
    return text, summary


def accept_gate_invite(invite_id: str) -> dict[str, Any]:
    with _LOCK:
        pending = _read_pending()
        entry = pending.get(str(invite_id or ""))
        if entry is None:
            return {"ok": False, "detail": "invite not found or expired"}
        sender = str(entry.get("from_peer_id", "") or "")
        check = _contact_check(sender)
        if not check.get("ok"):
            return check
        result = _apply(entry, from_peer_id=sender)
        if result.get("ok"):
            # The sender holds this key already; record them so our own
            # rotations reach them too.
            _gate_manager().record_key_grant(
                entry["gate_id"], sender, secret_id=str(entry.get("secret_id", "")), op="upstream"
            )
            pending.pop(str(invite_id), None)
            _write_pending(pending)
    return result


def decline_gate_invite(invite_id: str) -> dict[str, Any]:
    with _LOCK:
        pending = _read_pending()
        if pending.pop(str(invite_id or ""), None) is None:
            return {"ok": False, "detail": "invite not found or expired"}
        _write_pending(pending)
    return {"ok": True, "invite_id": str(invite_id)}


def gate_key_status(gate_id: str) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    manager = _gate_manager()
    if not manager.get_gate(gate_key):
        return {"ok": False, "detail": "Gate not found"}
    secret = manager.get_gate_secret(gate_key)
    meta = manager.get_gate_key_meta(gate_key)
    return {
        "ok": True,
        "gate_id": gate_key,
        "secret_id": secret_fingerprint(secret) if secret else "",
        "version": int(meta.get("gate_secret_version", 0) or 0),
        "upstream_peer_id": meta.get("key_upstream", ""),
        "shared": bool(meta.get("key_upstream") or meta.get("key_grants")),
        "grantees": sorted(meta.get("key_grants", {})),
    }
