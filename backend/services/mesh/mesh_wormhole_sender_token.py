"""Short-lived Wormhole sender tokens for DM metadata reduction.

These tokens let the client send a sealed DM without placing the long-term
sender id and public key directly into the DM send request body. The token is
single-use, recipient-bound, and kept in memory only.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from cachetools import TTLCache

from services.mesh.mesh_wormhole_identity import bootstrap_wormhole_identity, read_wormhole_identity
from services.mesh.mesh_protocol import PROTOCOL_VERSION

_SENDER_TOKEN_TTL_S = 5 * 60
_sender_tokens: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=2048, ttl=_SENDER_TOKEN_TTL_S)


def _sender_token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _token_binding_hash(recipient_token: str) -> str:
    return hashlib.sha256((recipient_token or "").encode("utf-8")).hexdigest()


def issue_wormhole_dm_sender_token(
    *,
    recipient_id: str,
    delivery_class: str,
    recipient_token: str = "",
    ttl_seconds: int = _SENDER_TOKEN_TTL_S,
) -> dict[str, Any]:
    recipient_id = str(recipient_id or "").strip()
    delivery_class = str(delivery_class or "").strip().lower()
    if delivery_class not in ("request", "shared"):
        return {"ok": False, "detail": "Invalid delivery_class"}
    if not recipient_id:
        return {"ok": False, "detail": "recipient_id required"}
    if delivery_class == "shared" and not recipient_token:
        return {"ok": False, "detail": "recipient_token required for shared delivery"}

    data = read_wormhole_identity()
    if not data.get("bootstrapped"):
        bootstrap_wormhole_identity()
        data = read_wormhole_identity()
    if not data.get("node_id") or not data.get("public_key"):
        return {"ok": False, "detail": "Wormhole identity unavailable"}

    token = secrets.token_urlsafe(32)
    now = int(time.time())
    expires_at = now + max(30, min(int(ttl_seconds or _SENDER_TOKEN_TTL_S), _SENDER_TOKEN_TTL_S))
    _sender_tokens[token] = {
        "sender_id": str(data.get("node_id", "")),
        "public_key": str(data.get("public_key", "")),
        "public_key_algo": str(data.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": PROTOCOL_VERSION,
        "recipient_id": recipient_id,
        "delivery_class": delivery_class,
        "recipient_token_hash": _token_binding_hash(recipient_token),
        "issued_at": now,
        "expires_at": expires_at,
    }
    return {
        "ok": True,
        "sender_token": token,
        "expires_at": expires_at,
        "delivery_class": delivery_class,
    }


def issue_wormhole_dm_sender_tokens(
    *,
    recipient_id: str,
    delivery_class: str,
    recipient_token: str = "",
    count: int = 3,
    ttl_seconds: int = _SENDER_TOKEN_TTL_S,
) -> dict[str, Any]:
    token_count = max(1, min(int(count or 1), 4))
    tokens: list[dict[str, Any]] = []
    for _ in range(token_count):
        issued = issue_wormhole_dm_sender_token(
            recipient_id=recipient_id,
            delivery_class=delivery_class,
            recipient_token=recipient_token,
            ttl_seconds=ttl_seconds,
        )
        if not issued.get("ok"):
            return issued
        tokens.append(
            {
                "sender_token": str(issued.get("sender_token", "")),
                "expires_at": int(issued.get("expires_at", 0) or 0),
            }
        )
    return {
        "ok": True,
        "delivery_class": delivery_class,
        "tokens": tokens,
    }


def consume_wormhole_dm_sender_token(
    *,
    sender_token: str,
    recipient_id: str,
    delivery_class: str,
    recipient_token: str = "",
) -> dict[str, Any]:
    token = str(sender_token or "").strip()
    if not token:
        return {"ok": False, "detail": "sender_token required"}
    token_hash = _sender_token_hash(token)
    record = _sender_tokens.pop(token, None)
    if not record:
        return {"ok": False, "detail": "sender_token invalid or expired"}
    bound_recipient_id = str(record.get("recipient_id", "") or "")
    normalized_recipient_id = str(recipient_id or "").strip()
    if normalized_recipient_id and bound_recipient_id != normalized_recipient_id:
        return {"ok": False, "detail": "sender_token recipient mismatch"}
    if str(record.get("delivery_class", "")) != str(delivery_class or "").strip().lower():
        return {"ok": False, "detail": "sender_token delivery_class mismatch"}
    if str(record.get("recipient_token_hash", "")) != _token_binding_hash(recipient_token):
        return {"ok": False, "detail": "sender_token mailbox binding mismatch"}
    expires_at = int(record.get("expires_at", 0) or 0)
    if expires_at and expires_at < int(time.time()):
        return {"ok": False, "detail": "sender_token expired"}
    return {"ok": True, "sender_token_hash": token_hash, **record}
