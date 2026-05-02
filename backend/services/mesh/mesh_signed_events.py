from __future__ import annotations

import logging
import hashlib
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from services.mesh.mesh_compatibility import (
    legacy_dm_signature_compat_override_active,
    legacy_gate_signature_compat_override_active,
)
from services.mesh.mesh_crypto import (
    build_signature_payload,
    parse_public_key_algo,
    verify_node_binding,
    verify_signature,
)
from services.mesh.mesh_metrics import increment as metrics_inc
from services.mesh.mesh_protocol import (
    PROTOCOL_VERSION,
    SIGNED_CONTEXT_FIELD,
    build_signed_context,
    normalize_dm_message_payload_legacy,
    normalize_payload,
    validate_signed_context,
)

logger = logging.getLogger(__name__)
_REVOCATION_TTL_CACHE: dict[str, dict[str, Any]] = {}
_REVOCATION_TTL_LOCK = threading.Lock()
_REVOCATION_REFRESH_LOCK = threading.Lock()
_REVOCATION_REFRESH_FAIL_FAST_WINDOW_S = 5.0
_REVOCATION_REFRESH_RETRY_AFTER_S = 5
_REVOCATION_PRECHECK_UNAVAILABLE_DETAIL = "Signed event integrity preflight unavailable"


def _is_canonical_sha256_hex(value: str) -> bool:
    candidate = str(value or "").strip()
    return (
        len(candidate) == 64
        and candidate == candidate.lower()
        and all(ch in "0123456789abcdef" for ch in candidate)
    )
_REVOCATION_PRECHECK_UNAVAILABLE_ERROR_CODE = "revocation_refresh_unavailable"
_REVOCATION_REFRESH_STATE: dict[str, Any] = {
    "in_flight": False,
    "last_failure_at": 0.0,
    "last_error": "",
}


class SignedWriteKind(str, Enum):
    DM_REGISTER = "dm_register"
    DM_SEND = "dm_send"
    DM_POLL = "dm_poll"
    DM_COUNT = "dm_count"
    DM_BLOCK = "dm_block"
    DM_WITNESS = "dm_witness"
    TRUST_VOUCH = "trust_vouch"
    MESH_SEND = "mesh_send"
    MESH_VOTE = "mesh_vote"
    MESH_REPORT = "mesh_report"
    IDENTITY_ROTATE = "identity_rotate"
    IDENTITY_REVOKE = "identity_revoke"
    GATE_CREATE = "gate_create"
    GATE_MESSAGE = "gate_message"
    ORACLE_PREDICT = "oracle_predict"
    ORACLE_STAKE = "oracle_stake"


class MeshWriteExemption(str, Enum):
    PEER_GOSSIP = "peer_gossip"
    ADMIN_CONTROL = "admin_control"
    LOCAL_OPERATOR_ONLY = "local_operator_only"


# Hardening Rec #2: kinds whose payload is (or gates access to) content-private
# material. A signed-write transport_lock on these kinds binds the sender to
# a specific transport tier, preventing an attacker (or a misconfigured
# client) from replaying the same signed blob onto a weaker lane.
CONTENT_PRIVATE_SIGNED_WRITE_KINDS = frozenset({
    SignedWriteKind.DM_REGISTER,
    SignedWriteKind.DM_SEND,
    SignedWriteKind.DM_POLL,
    SignedWriteKind.DM_COUNT,
    SignedWriteKind.DM_BLOCK,
    SignedWriteKind.DM_WITNESS,
    SignedWriteKind.GATE_MESSAGE,
    SignedWriteKind.TRUST_VOUCH,
    SignedWriteKind.IDENTITY_ROTATE,
    SignedWriteKind.IDENTITY_REVOKE,
})

_QUEUEABLE_CONTENT_PRIVATE_KINDS = frozenset({
    SignedWriteKind.DM_SEND,
    SignedWriteKind.GATE_MESSAGE,
})


def _content_private_required_transport_tier(kind: SignedWriteKind) -> str:
    if kind == SignedWriteKind.GATE_MESSAGE:
        return "private_strong"
    if kind in {
        SignedWriteKind.DM_REGISTER,
        SignedWriteKind.DM_SEND,
        SignedWriteKind.DM_POLL,
        SignedWriteKind.DM_COUNT,
        SignedWriteKind.DM_BLOCK,
        SignedWriteKind.DM_WITNESS,
    }:
        return "private_strong"
    if kind in {
        SignedWriteKind.TRUST_VOUCH,
        SignedWriteKind.IDENTITY_ROTATE,
        SignedWriteKind.IDENTITY_REVOKE,
    }:
        return "private_strong"
    return "private_strong"


def _signed_context_sequence_domain(prepared: "PreparedSignedWrite") -> str:
    if prepared.kind == SignedWriteKind.DM_BLOCK:
        action = str(prepared.payload.get("action", "block") or "block").strip().lower()
        return f"dm_block:{action}"
    domains = {
        SignedWriteKind.DM_REGISTER: "dm_register",
        SignedWriteKind.DM_SEND: "dm_send",
        SignedWriteKind.DM_POLL: "dm_poll",
        SignedWriteKind.DM_COUNT: "dm_count",
        SignedWriteKind.DM_WITNESS: "dm_witness",
        SignedWriteKind.TRUST_VOUCH: "trust_vouch",
        SignedWriteKind.IDENTITY_ROTATE: "identity_rotate",
        SignedWriteKind.IDENTITY_REVOKE: "identity_revoke",
        SignedWriteKind.GATE_MESSAGE: "gate_message",
    }
    return domains.get(prepared.kind, prepared.event_type)


def _signed_context_target_fields(prepared: "PreparedSignedWrite") -> dict[str, str]:
    if prepared.kind == SignedWriteKind.GATE_MESSAGE:
        return {"gate_id": str(prepared.payload.get("gate", "") or "")}
    if prepared.kind == SignedWriteKind.DM_SEND:
        return {"recipient_id": str(prepared.payload.get("recipient_id", "") or "")}
    if prepared.kind in {SignedWriteKind.DM_WITNESS, SignedWriteKind.TRUST_VOUCH}:
        return {"target_id": str(prepared.payload.get("target_id", "") or "")}
    if prepared.kind == SignedWriteKind.DM_BLOCK:
        return {"target_id": str(prepared.payload.get("blocked_id", "") or "")}
    return {}


def _canonical_signed_write_retry_payload(
    prepared: "PreparedSignedWrite",
    request: Request,
) -> dict[str, Any]:
    target_fields = _signed_context_target_fields(prepared)
    payload = dict(prepared.payload or {})
    payload.pop(SIGNED_CONTEXT_FIELD, None)
    signed_context = build_signed_context(
        event_type=prepared.event_type,
        kind=prepared.kind.value,
        endpoint=str(request.url.path or ""),
        lane_floor=_content_private_required_transport_tier(prepared.kind),
        sequence_domain=_signed_context_sequence_domain(prepared),
        node_id=prepared.node_id,
        sequence=prepared.sequence,
        payload=payload,
        gate_id=target_fields.get("gate_id", ""),
        recipient_id=target_fields.get("recipient_id", ""),
        target_id=target_fields.get("target_id", ""),
    )
    payload[SIGNED_CONTEXT_FIELD] = signed_context
    return {
        "signed_context": signed_context,
        "payload": payload,
        "signature_payload": build_signature_payload(
            event_type=prepared.event_type,
            node_id=prepared.node_id,
            sequence=prepared.sequence,
            payload=payload,
        ),
    }


@dataclass
class PreparedSignedWrite:
    kind: SignedWriteKind
    event_type: str
    body: dict[str, Any]
    node_id: str
    sequence: int
    public_key: str
    public_key_algo: str
    signature: str
    protocol_version: str
    payload: dict[str, Any]
    reason: str = "ok"
    verified_reply_to: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


class _SignedWriteAbort(RuntimeError):
    def __init__(self, response: Any):
        super().__init__("signed write preparation aborted")
        self.response = response


class _RevocationRefreshUnavailable(RuntimeError):
    pass


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:
        return default
    if parsed in {float("inf"), float("-inf")}:
        return default
    return parsed


def _revocation_retry_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": str(_REVOCATION_REFRESH_RETRY_AFTER_S)},
        content={
            "ok": False,
            "detail": _REVOCATION_PRECHECK_UNAVAILABLE_DETAIL,
            "retryable": True,
            "error_code": _REVOCATION_PRECHECK_UNAVAILABLE_ERROR_CODE,
            "retry_after_s": _REVOCATION_REFRESH_RETRY_AFTER_S,
        },
    )


def _revocation_retryable_failure(reason: str) -> bool:
    if str(reason or "").strip() != _REVOCATION_PRECHECK_UNAVAILABLE_DETAIL:
        return False
    now = time.time()
    with _REVOCATION_TTL_LOCK:
        in_flight = bool(_REVOCATION_REFRESH_STATE.get("in_flight"))
        last_failure_at = _safe_float(_REVOCATION_REFRESH_STATE.get("last_failure_at"), 0.0)
    return in_flight or (last_failure_at > 0.0 and (now - last_failure_at) < _REVOCATION_REFRESH_FAIL_FAST_WINDOW_S)


def _handler_module(handler: Callable[..., Any]):
    return sys.modules.get(handler.__module__)


def _handler_attr(handler: Callable[..., Any], name: str, default: Any = None) -> Any:
    owner = _handler_module(handler)
    if owner is None:
        return default
    return getattr(owner, name, default)


def _request_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Request:
    request = kwargs.get("request")
    if isinstance(request, Request):
        return request
    for arg in args:
        if isinstance(arg, Request):
            return arg
    raise RuntimeError("requires_signed_write requires a FastAPI Request parameter")


async def _mesh_body(request: Request) -> dict[str, Any]:
    """The only supported JSON parse path for decorated mesh write handlers."""
    cached = getattr(request.state, "_mesh_body_cache", None)
    if isinstance(cached, dict):
        return cached
    if cached is not None:
        return {}
    try:
        payload = await request.json()
    except Exception:
        request.state._mesh_body_error = "invalid_json"
        request.state._mesh_body_cache = {}
        return {}
    if not isinstance(payload, dict):
        request.state._mesh_body_error = "non_object_json"
        request.state._mesh_body_cache = {}
        return {}
    request.state._mesh_body_cache = dict(payload)
    return request.state._mesh_body_cache


def _revocation_status_with_ttl(public_key: str) -> tuple[bool, dict[str, Any] | None]:
    key = str(public_key or "").strip()
    if not key:
        return False, None

    from services.mesh.mesh_hashchain import infonet
    from services.mesh.mesh_rollout_flags import (
        signed_revocation_cache_enforce,
        signed_revocation_cache_ttl_s,
    )

    enforce = bool(signed_revocation_cache_enforce())
    ttl_s = max(0, int(signed_revocation_cache_ttl_s() or 0))
    now = time.time()
    with _REVOCATION_TTL_LOCK:
        cached = dict(_REVOCATION_TTL_CACHE.get(key) or {})
    checked_at = float(cached.get("checked_at", 0.0) or 0.0)
    if cached and (ttl_s <= 0 or (now - checked_at) < float(ttl_s)):
        return bool(cached.get("revoked")), cached.get("info")

    if enforce:
        with _REVOCATION_TTL_LOCK:
            if bool(_REVOCATION_REFRESH_STATE.get("in_flight")):
                metrics_inc("revocation_refresh_waits")
                raise _RevocationRefreshUnavailable("revocation refresh already in flight")
            last_failure_at = _safe_float(_REVOCATION_REFRESH_STATE.get("last_failure_at"), 0.0)
            if last_failure_at > 0.0 and (now - last_failure_at) < _REVOCATION_REFRESH_FAIL_FAST_WINDOW_S:
                metrics_inc("revocation_refresh_waits")
                raise _RevocationRefreshUnavailable("revocation refresh fail-fast window active")
            _REVOCATION_REFRESH_STATE["in_flight"] = True

    metrics_inc("revocation_refresh_attempts")

    try:
        with _REVOCATION_REFRESH_LOCK:
            if enforce:
                with _REVOCATION_TTL_LOCK:
                    refreshed_cached = dict(_REVOCATION_TTL_CACHE.get(key) or {})
                    refreshed_checked_at = _safe_float(refreshed_cached.get("checked_at"), 0.0)
                    if refreshed_cached and (
                        ttl_s <= 0 or (time.time() - refreshed_checked_at) < float(ttl_s)
                    ):
                        _REVOCATION_REFRESH_STATE["in_flight"] = False
                        return bool(refreshed_cached.get("revoked")), refreshed_cached.get("info")
            infonet._rebuild_revocations()
            revoked, info = infonet._revocation_status(key)
            with _REVOCATION_TTL_LOCK:
                _REVOCATION_TTL_CACHE[key] = {
                    "checked_at": time.time(),
                    "revoked": bool(revoked),
                    "info": dict(info or {}) if isinstance(info, dict) else info,
                }
                _REVOCATION_REFRESH_STATE["in_flight"] = False
                _REVOCATION_REFRESH_STATE["last_failure_at"] = 0.0
                _REVOCATION_REFRESH_STATE["last_error"] = ""
        return revoked, info
    except Exception as exc:
        metrics_inc("revocation_refresh_failures")
        logger.warning(
            "revocation cache refresh failed for %s: %s",
            key[:12],
            type(exc).__name__,
        )
        with _REVOCATION_TTL_LOCK:
            _REVOCATION_REFRESH_STATE["in_flight"] = False
            _REVOCATION_REFRESH_STATE["last_failure_at"] = time.time()
            _REVOCATION_REFRESH_STATE["last_error"] = type(exc).__name__
        if enforce:
            metrics_inc("revocation_refresh_fail_closed")
            raise _RevocationRefreshUnavailable(str(exc) or type(exc).__name__) from exc
        metrics_inc("revocation_refresh_fail_open")
        return False, None
    finally:
        if enforce:
            with _REVOCATION_TTL_LOCK:
                _REVOCATION_REFRESH_STATE["in_flight"] = False


def _reset_revocation_ttl_cache() -> None:
    with _REVOCATION_TTL_LOCK:
        _REVOCATION_TTL_CACHE.clear()
        _REVOCATION_REFRESH_STATE["in_flight"] = False
        _REVOCATION_REFRESH_STATE["last_failure_at"] = 0.0
        _REVOCATION_REFRESH_STATE["last_error"] = ""


def _apply_content_private_transport_lock_policy(prepared: "PreparedSignedWrite") -> None:
    """Hardening Rec #2: bind content-private signed writes to a transport tier.

    If the client supplied ``transport_lock`` in the body, mirror it into the
    signed payload so the downstream signature verifier confirms the sender
    committed to a specific tier (public_degraded is disallowed for
    content-private kinds). If the client did NOT supply ``transport_lock``,
    emit a metric and — when the rollout flag is on — abort with a clear
    error. The rollout flag defaults off so existing clients that don't yet
    emit ``transport_lock`` stay functional; operators flip it on once the
    client side has shipped.
    """
    if prepared.kind not in CONTENT_PRIVATE_SIGNED_WRITE_KINDS:
        return

    from services.mesh.mesh_privacy_policy import (
        normalize_transport_tier,
        transport_tier_is_sufficient,
    )
    from services.mesh.mesh_rollout_flags import (
        signed_write_content_private_transport_lock_required,
    )

    enforce = bool(signed_write_content_private_transport_lock_required())
    transport_lock_raw = str(prepared.body.get("transport_lock", "") or "").strip().lower()

    if not transport_lock_raw:
        metrics_inc("signed_write_missing_transport_lock_content_private")
        if enforce:
            raise _SignedWriteAbort(
                {
                    "ok": False,
                    "detail": "transport_lock is required on content-private signed writes",
                }
            )
        return

    normalized = normalize_transport_tier(transport_lock_raw)
    if normalized == "public_degraded":
        metrics_inc("signed_write_transport_lock_public_on_content_private")
        if enforce:
            raise _SignedWriteAbort(
                {
                    "ok": False,
                    "detail": "transport_lock cannot be public_degraded on a content-private signed write",
                }
            )
        return

    required_lock_tier = _content_private_required_transport_tier(prepared.kind)
    if not transport_tier_is_sufficient(normalized, required_lock_tier):
        metrics_inc("signed_write_transport_lock_below_required_tier")
        if enforce:
            raise _SignedWriteAbort(
                {
                    "ok": False,
                    "detail": (
                        f"transport_lock {normalized} is weaker than required "
                        f"content-private tier {required_lock_tier}"
                    ),
                }
            )
        return

    try:
        from services.wormhole_supervisor import get_transport_tier

        current_tier = get_transport_tier()
    except Exception:
        current_tier = "public_degraded"

    if (
        not transport_tier_is_sufficient(current_tier, normalized)
        and prepared.kind not in _QUEUEABLE_CONTENT_PRIVATE_KINDS
    ):
        metrics_inc("signed_write_transport_lock_tier_mismatch")
        if enforce:
            raise _SignedWriteAbort(
                {
                    "ok": False,
                    "detail": (
                        f"current transport tier {current_tier} does not satisfy "
                        f"signed transport_lock {normalized}"
                    ),
                }
            )
        return

    # Mirror the lock into the signed payload. A well-behaved client signs
    # with ``transport_lock`` already canonicalized into their payload, in
    # which case the downstream signature verifier sees a matching payload
    # and accepts it. A misbehaved client that stuffed ``transport_lock``
    # into the body without signing it will fail signature verification —
    # which is the correct outcome.
    prepared.payload["transport_lock"] = normalized


def _apply_signed_write_freshness_policy(prepared: "PreparedSignedWrite") -> None:
    """Reject stale timestamped signed writes before side effects run.

    Public Infonet ingest has its own max-age guard. This protects the private
    signed-write endpoints that rely on local replay state and may be seen by a
    fresh peer with no sequence history.
    """
    from services.mesh.mesh_rollout_flags import signed_write_max_age_s

    max_age_s = int(signed_write_max_age_s() or 0)
    if max_age_s <= 0:
        return

    timestamp = _safe_int(prepared.payload.get("timestamp", 0) or 0, 0)
    if timestamp <= 0:
        return

    now_ts = int(time.time())
    if abs(now_ts - timestamp) <= max_age_s:
        return

    metrics_inc("signed_write_timestamp_out_of_window")
    raise _SignedWriteAbort(
        {
            "ok": False,
            "detail": "signed write timestamp is outside the freshness window",
            "max_age_s": max_age_s,
        }
    )


def _apply_signed_context_policy(prepared: "PreparedSignedWrite", request: Request) -> None:
    from services.mesh.mesh_rollout_flags import signed_write_context_required

    supplied = prepared.body.get(SIGNED_CONTEXT_FIELD)
    if isinstance(supplied, dict):
        prepared.payload[SIGNED_CONTEXT_FIELD] = supplied
    elif signed_write_context_required() and prepared.kind in CONTENT_PRIVATE_SIGNED_WRITE_KINDS:
        metrics_inc("signed_write_missing_context")
        canonical = _canonical_signed_write_retry_payload(prepared, request)
        raise _SignedWriteAbort(
            {
                "ok": False,
                "detail": "signed_context is required on this signed write",
                "retryable": True,
                "resign_required": True,
                "canonical": canonical,
            }
        )
    else:
        return

    target_fields = _signed_context_target_fields(prepared)
    ok, reason = validate_signed_context(
        event_type=prepared.event_type,
        kind=prepared.kind.value,
        endpoint=str(request.url.path or ""),
        lane_floor=_content_private_required_transport_tier(prepared.kind),
        sequence_domain=_signed_context_sequence_domain(prepared),
        node_id=prepared.node_id,
        sequence=prepared.sequence,
        payload=prepared.payload,
        gate_id=target_fields.get("gate_id", ""),
        recipient_id=target_fields.get("recipient_id", ""),
        target_id=target_fields.get("target_id", ""),
    )
    if not ok:
        metrics_inc("signed_write_context_mismatch")
        raise _SignedWriteAbort(
            {
                "ok": False,
                "detail": reason,
                "retryable": True,
                "resign_required": True,
                "canonical": _canonical_signed_write_retry_payload(prepared, request),
            }
        )


def get_prepared_signed_write(request: Request) -> PreparedSignedWrite | None:
    prepared = getattr(request.state, "_prepared_signed_write", None)
    if isinstance(prepared, PreparedSignedWrite):
        return prepared
    return None


def mesh_write_exempt(reason: MeshWriteExemption):
    def _decorate(func):
        setattr(func, "_mesh_write_exempt", reason)
        return func

    return _decorate


def _normalized_mailbox_claims(mailbox_claims: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for claim in list(mailbox_claims or [])[:32]:
        if not isinstance(claim, dict):
            continue
        normalized.append(
            {
                "type": str(claim.get("type", "") or "").lower(),
                "token": str(claim.get("token", "") or ""),
            }
        )
    return normalized


async def _prepare_signed_write(
    *,
    kind: SignedWriteKind,
    request: Request,
    handler: Callable[..., Any],
) -> PreparedSignedWrite:
    body = dict(await _mesh_body(request))
    body_error = str(getattr(request.state, "_mesh_body_error", "") or "")
    if body_error:
        if body_error == "invalid_json":
            raise _SignedWriteAbort(
                JSONResponse(status_code=422, content={"ok": False, "detail": "invalid JSON body"})
            )
        raise _SignedWriteAbort(
            JSONResponse(status_code=422, content={"ok": False, "detail": "Request body must be a JSON object"})
        )

    if kind == SignedWriteKind.GATE_MESSAGE and str(body.get("message", "") or "").strip():
        raise _SignedWriteAbort(
            {
                "ok": False,
                "detail": "Plaintext gate messages are no longer accepted. Submit an encrypted gate envelope.",
            }
        )

    if kind == SignedWriteKind.MESH_SEND:
        message = body.get("message", "")
        destination = body.get("destination", "")
        payload = {
            "message": message,
            "destination": destination,
            "channel": body.get("channel", "LongFast"),
            "priority": str(body.get("priority", "normal") or "normal").lower(),
            "ephemeral": bool(body.get("ephemeral", False)),
        }
        if body.get("transport_lock"):
            payload["transport_lock"] = str(body.get("transport_lock") or "")
        return PreparedSignedWrite(
            kind=kind,
            event_type="message",
            body=body,
            node_id=str(body.get("node_id", body.get("sender_id", "anonymous")) or "anonymous"),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("public_key", "") or ""),
            public_key_algo=str(body.get("public_key_algo", "") or ""),
            signature=str(body.get("signature", "") or ""),
            protocol_version=str(body.get("protocol_version", "") or ""),
            payload=payload,
        )

    if kind == SignedWriteKind.MESH_VOTE:
        voter_id = str(body.get("voter_id", "") or "")
        gate = str(body.get("gate", "") or "")
        validate_gate_vote_context = _handler_attr(handler, "_validate_gate_vote_context")
        if callable(validate_gate_vote_context):
            gate_ok, gate_detail = validate_gate_vote_context(voter_id, gate)
            if not gate_ok:
                raise _SignedWriteAbort({"ok": False, "detail": gate_detail})
            gate = gate_detail or ""
            body["gate"] = gate
        return PreparedSignedWrite(
            kind=kind,
            event_type="vote",
            body=body,
            node_id=voter_id,
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("voter_pubkey", "") or ""),
            public_key_algo=str(body.get("public_key_algo", "") or ""),
            signature=str(body.get("voter_sig", "") or ""),
            protocol_version=str(body.get("protocol_version", "") or ""),
            payload={
                "target_id": body.get("target_id", ""),
                "vote": body.get("vote", 0),
                "gate": gate,
            },
        )

    if kind == SignedWriteKind.MESH_REPORT:
        return PreparedSignedWrite(
            kind=kind,
            event_type="abuse_report",
            body=body,
            node_id=str(body.get("reporter_id", "") or ""),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("public_key", "") or ""),
            public_key_algo=str(body.get("public_key_algo", "") or ""),
            signature=str(body.get("signature", "") or ""),
            protocol_version=str(body.get("protocol_version", "") or ""),
            payload={
                "target_id": body.get("target_id", ""),
                "reason": body.get("reason", ""),
                "gate": body.get("gate", ""),
                "evidence": body.get("evidence", ""),
            },
        )

    if kind == SignedWriteKind.IDENTITY_ROTATE:
        return PreparedSignedWrite(
            kind=kind,
            event_type="key_rotate",
            body=body,
            node_id=str(body.get("new_node_id", "") or "").strip(),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("new_public_key", "") or "").strip(),
            public_key_algo=str(body.get("new_public_key_algo", "") or "").strip(),
            signature=str(body.get("new_signature", "") or "").strip(),
            protocol_version=str(body.get("protocol_version", "") or "").strip(),
            payload={
                "old_node_id": str(body.get("old_node_id", "") or "").strip(),
                "old_public_key": str(body.get("old_public_key", "") or "").strip(),
                "old_public_key_algo": str(body.get("old_public_key_algo", "") or "").strip(),
                "new_public_key": str(body.get("new_public_key", "") or "").strip(),
                "new_public_key_algo": str(body.get("new_public_key_algo", "") or "").strip(),
                "timestamp": _safe_int(body.get("timestamp", 0) or 0),
                "old_signature": str(body.get("old_signature", "") or "").strip(),
            },
        )

    if kind == SignedWriteKind.IDENTITY_REVOKE:
        public_key = str(body.get("public_key", "") or "").strip()
        public_key_algo = str(body.get("public_key_algo", "") or "").strip()
        return PreparedSignedWrite(
            kind=kind,
            event_type="key_revoke",
            body=body,
            node_id=str(body.get("node_id", "") or "").strip(),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=public_key,
            public_key_algo=public_key_algo,
            signature=str(body.get("signature", "") or "").strip(),
            protocol_version=str(body.get("protocol_version", "") or "").strip(),
            payload={
                "revoked_public_key": public_key,
                "revoked_public_key_algo": public_key_algo,
                "revoked_at": _safe_int(body.get("revoked_at", 0) or 0),
                "grace_until": _safe_int(body.get("grace_until", 0) or 0),
                "reason": str(body.get("reason", "") or "").strip(),
            },
        )

    if kind == SignedWriteKind.GATE_CREATE:
        return PreparedSignedWrite(
            kind=kind,
            event_type="gate_create",
            body=body,
            node_id=str(body.get("creator_id", "") or ""),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("creator_pubkey", "") or ""),
            public_key_algo=str(body.get("public_key_algo", "") or ""),
            signature=str(body.get("creator_sig", "") or ""),
            protocol_version=str(body.get("protocol_version", "") or ""),
            payload={
                "gate_id": body.get("gate_id", ""),
                "display_name": body.get("display_name", body.get("gate_id", "")),
                "rules": body.get("rules", {}),
            },
        )

    if kind == SignedWriteKind.GATE_MESSAGE:
        gate_id = str(request.path_params.get("gate_id", "") or "")
        gate_envelope = str(body.get("gate_envelope", "") or "").strip()
        envelope_hash = str(body.get("envelope_hash", "") or "").strip()
        if gate_envelope and not envelope_hash:
            raise _SignedWriteAbort(
                {
                    "ok": False,
                    "detail": "gate_envelope requires signed envelope_hash",
                }
            )
        if envelope_hash:
            if not gate_envelope:
                raise _SignedWriteAbort(
                    {
                        "ok": False,
                        "detail": "gate_envelope required when envelope_hash is present",
                    }
                )
            if not _is_canonical_sha256_hex(envelope_hash):
                raise _SignedWriteAbort(
                    {
                        "ok": False,
                        "detail": "invalid envelope_hash",
                    }
                )
            try:
                expected_hash = hashlib.sha256(gate_envelope.encode("ascii")).hexdigest()
            except UnicodeEncodeError:
                raise _SignedWriteAbort(
                    {
                        "ok": False,
                        "detail": "invalid gate_envelope",
                    }
                )
            if expected_hash != envelope_hash:
                raise _SignedWriteAbort(
                    {
                        "ok": False,
                        "detail": "gate_envelope does not match envelope_hash",
                    }
                )
        payload = {
            "gate": gate_id,
            "ciphertext": str(body.get("ciphertext", "") or ""),
            "nonce": str(body.get("nonce", body.get("iv", "")) or ""),
            "sender_ref": str(body.get("sender_ref", "") or ""),
            "format": str(body.get("format", "mls1") or "mls1"),
        }
        epoch = _safe_int(body.get("epoch", 0) or 0)
        if epoch > 0:
            payload["epoch"] = epoch
        if envelope_hash:
            payload["envelope_hash"] = envelope_hash
        return PreparedSignedWrite(
            kind=kind,
            event_type="gate_message",
            body=body,
            node_id=str(body.get("sender_id", "") or ""),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("public_key", "") or ""),
            public_key_algo=str(body.get("public_key_algo", "") or ""),
            signature=str(body.get("signature", "") or ""),
            protocol_version=str(body.get("protocol_version", "") or ""),
            payload=payload,
            verified_reply_to=str(body.get("reply_to", "") or "").strip(),
        )

    if kind == SignedWriteKind.DM_REGISTER:
        return PreparedSignedWrite(
            kind=kind,
            event_type="dm_key",
            body=body,
            node_id=str(body.get("agent_id", "") or "").strip(),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("public_key", "") or "").strip(),
            public_key_algo=str(body.get("public_key_algo", "") or "").strip(),
            signature=str(body.get("signature", "") or "").strip(),
            protocol_version=str(body.get("protocol_version", "") or "").strip(),
            payload={
                "dh_pub_key": str(body.get("dh_pub_key", "") or "").strip(),
                "dh_algo": str(body.get("dh_algo", "") or "").strip(),
                "timestamp": _safe_int(body.get("timestamp", 0) or 0),
            },
        )

    if kind == SignedWriteKind.DM_SEND:
        sender_id = str(body.get("sender_id", "") or "").strip()
        sender_token = str(body.get("sender_token", "") or "").strip()
        recipient_id = str(body.get("recipient_id", "") or "").strip()
        delivery_class = str(body.get("delivery_class", "") or "").strip().lower()
        recipient_token = str(body.get("recipient_token", "") or "").strip()
        public_key = str(body.get("public_key", "") or "").strip()
        public_key_algo = str(body.get("public_key_algo", "") or "").strip()
        protocol_version = str(body.get("protocol_version", "") or "").strip()
        sender_token_hash = str(body.get("sender_token_hash", "") or "").strip()
        if sender_token:
            token_consumer = _handler_attr(handler, "consume_wormhole_dm_sender_token")
            if not callable(token_consumer):
                from services.mesh.mesh_wormhole_sender_token import consume_wormhole_dm_sender_token as token_consumer

            token_result = token_consumer(
                sender_token=sender_token,
                recipient_id=recipient_id,
                delivery_class=delivery_class,
                recipient_token=recipient_token,
            )
            if not token_result.get("ok"):
                raise _SignedWriteAbort(token_result)
            if not recipient_id:
                recipient_id = str(token_result.get("recipient_id", "") or "")
            sender_id = str(token_result.get("sender_id", "") or sender_id)
            sender_token_hash = str(token_result.get("sender_token_hash", "") or sender_token_hash)
            public_key = str(token_result.get("public_key", "") or public_key)
            public_key_algo = str(token_result.get("public_key_algo", "") or public_key_algo)
            protocol_version = str(token_result.get("protocol_version", "") or protocol_version)

        from services.mesh.mesh_crypto import derive_node_id, verify_node_binding

        sender_seal = str(body.get("sender_seal", "") or "").strip()
        derived_sender_id = sender_id
        if public_key and not verify_node_binding(sender_id or derived_sender_id, public_key):
            derived_sender_id = derive_node_id(public_key)
        if sender_seal:
            if not derived_sender_id:
                raise _SignedWriteAbort({"ok": False, "detail": "sender_seal requires a valid public key"})
            if sender_id and sender_id != derived_sender_id:
                raise _SignedWriteAbort({"ok": False, "detail": "sender_id does not match sender_seal public key"})
            sender_id = derived_sender_id

        body.update(
            {
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "delivery_class": delivery_class,
                "recipient_token": recipient_token,
                "public_key": public_key,
                "public_key_algo": public_key_algo,
                "protocol_version": protocol_version,
                "sender_token_hash": sender_token_hash,
            }
        )
        relay_salt_hex = str(body.get("relay_salt", "") or "").strip().lower()
        payload = {
            "recipient_id": recipient_id,
            "delivery_class": delivery_class,
            "recipient_token": recipient_token,
            "ciphertext": str(body.get("ciphertext", "") or "").strip(),
            "format": str(body.get("format", "mls1") or "mls1").strip().lower() or "mls1",
            "msg_id": str(body.get("msg_id", "") or "").strip(),
            "timestamp": _safe_int(body.get("timestamp", 0) or 0),
        }
        session_welcome = str(body.get("session_welcome", "") or "").strip()
        if session_welcome:
            payload["session_welcome"] = session_welcome
        if sender_seal:
            payload["sender_seal"] = sender_seal
        if relay_salt_hex:
            payload["relay_salt"] = relay_salt_hex
        return PreparedSignedWrite(
            kind=kind,
            event_type="dm_message",
            body=body,
            node_id=sender_id,
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=public_key,
            public_key_algo=public_key_algo,
            signature=str(body.get("signature", "") or "").strip(),
            protocol_version=protocol_version,
            payload=payload,
            extras={"sender_token_hash": sender_token_hash},
        )

    if kind in {SignedWriteKind.DM_POLL, SignedWriteKind.DM_COUNT}:
        normalized_claims = _normalized_mailbox_claims(body.get("mailbox_claims", []))
        body["mailbox_claims"] = normalized_claims
        event_type = "dm_poll" if kind == SignedWriteKind.DM_POLL else "dm_count"
        return PreparedSignedWrite(
            kind=kind,
            event_type=event_type,
            body=body,
            node_id=str(body.get("agent_id", "") or "").strip(),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("public_key", "") or "").strip(),
            public_key_algo=str(body.get("public_key_algo", "") or "").strip(),
            signature=str(body.get("signature", "") or "").strip(),
            protocol_version=str(body.get("protocol_version", "") or "").strip(),
            payload={
                "mailbox_claims": normalized_claims,
                "timestamp": _safe_int(body.get("timestamp", 0) or 0),
                "nonce": str(body.get("nonce", "") or "").strip(),
            },
        )

    if kind == SignedWriteKind.DM_BLOCK:
        return PreparedSignedWrite(
            kind=kind,
            event_type="dm_block",
            body=body,
            node_id=str(body.get("agent_id", "") or "").strip(),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("public_key", "") or "").strip(),
            public_key_algo=str(body.get("public_key_algo", "") or "").strip(),
            signature=str(body.get("signature", "") or "").strip(),
            protocol_version=str(body.get("protocol_version", "") or "").strip(),
            payload={
                "blocked_id": str(body.get("blocked_id", "") or "").strip(),
                "action": str(body.get("action", "block") or "block").strip().lower(),
            },
        )

    if kind == SignedWriteKind.DM_WITNESS:
        return PreparedSignedWrite(
            kind=kind,
            event_type="dm_key_witness",
            body=body,
            node_id=str(body.get("witness_id", "") or "").strip(),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("public_key", "") or "").strip(),
            public_key_algo=str(body.get("public_key_algo", "") or "").strip(),
            signature=str(body.get("signature", "") or "").strip(),
            protocol_version=str(body.get("protocol_version", "") or "").strip(),
            payload={
                "target_id": str(body.get("target_id", "") or "").strip(),
                "dh_pub_key": str(body.get("dh_pub_key", "") or "").strip(),
                "timestamp": _safe_int(body.get("timestamp", 0) or 0),
            },
        )

    if kind == SignedWriteKind.TRUST_VOUCH:
        return PreparedSignedWrite(
            kind=kind,
            event_type="trust_vouch",
            body=body,
            node_id=str(body.get("voucher_id", "") or "").strip(),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("public_key", "") or "").strip(),
            public_key_algo=str(body.get("public_key_algo", "") or "").strip(),
            signature=str(body.get("signature", "") or "").strip(),
            protocol_version=str(body.get("protocol_version", "") or "").strip(),
            payload={
                "target_id": str(body.get("target_id", "") or "").strip(),
                "note": str(body.get("note", "") or "").strip(),
                "timestamp": _safe_int(body.get("timestamp", 0) or 0),
            },
        )

    if kind == SignedWriteKind.ORACLE_PREDICT:
        return PreparedSignedWrite(
            kind=kind,
            event_type="prediction",
            body=body,
            node_id=str(body.get("node_id", "") or ""),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("public_key", "") or ""),
            public_key_algo=str(body.get("public_key_algo", "") or ""),
            signature=str(body.get("signature", "") or ""),
            protocol_version=str(body.get("protocol_version", "") or ""),
            payload={
                "market_title": body.get("market_title", ""),
                "side": body.get("side", ""),
                "stake_amount": _safe_float(body.get("stake_amount", 0)),
            },
        )

    if kind == SignedWriteKind.ORACLE_STAKE:
        return PreparedSignedWrite(
            kind=kind,
            event_type="stake",
            body=body,
            node_id=str(body.get("staker_id", "") or ""),
            sequence=_safe_int(body.get("sequence", 0) or 0),
            public_key=str(body.get("public_key", "") or ""),
            public_key_algo=str(body.get("public_key_algo", "") or ""),
            signature=str(body.get("signature", "") or ""),
            protocol_version=str(body.get("protocol_version", "") or ""),
            payload={
                "message_id": body.get("message_id", ""),
                "poster_id": body.get("poster_id", ""),
                "side": str(body.get("side", "") or "").lower(),
                "amount": _safe_float(body.get("amount", 0)),
                "duration_days": _safe_int(body.get("duration_days", 1), 1),
            },
        )

    raise RuntimeError(f"Unsupported signed write kind: {kind}")


def requires_signed_write(*, kind: SignedWriteKind):
    def _decorate(func):
        @wraps(func)
        async def _wrapped(*args, **kwargs):
            request = _request_from_call(args, kwargs)
            try:
                prepared = await _prepare_signed_write(kind=kind, request=request, handler=func)
                _apply_content_private_transport_lock_policy(prepared)
                _apply_signed_context_policy(prepared, request)
                _apply_signed_write_freshness_policy(prepared)
            except _SignedWriteAbort as abort:
                return abort.response

            if kind == SignedWriteKind.GATE_MESSAGE:
                gate_verifier = _handler_attr(func, "_verify_gate_message_signed_write", verify_gate_message_signed_write)
                ok, reason, verified_reply_to = gate_verifier(
                    node_id=prepared.node_id,
                    sequence=prepared.sequence,
                    public_key=prepared.public_key,
                    public_key_algo=prepared.public_key_algo,
                    signature=prepared.signature,
                    payload=prepared.payload,
                    reply_to=prepared.verified_reply_to,
                    protocol_version=prepared.protocol_version,
                )
                if not ok:
                    if _revocation_retryable_failure(reason):
                        return _revocation_retry_response()
                    return {"ok": False, "detail": reason}
                prepared.reason = reason
                prepared.verified_reply_to = verified_reply_to
                prepared.body["reply_to"] = verified_reply_to
            else:
                verifier = _handler_attr(func, "_verify_signed_write", verify_signed_write)
                ok, reason = verifier(
                    event_type=prepared.event_type,
                    node_id=prepared.node_id,
                    sequence=prepared.sequence,
                    public_key=prepared.public_key,
                    public_key_algo=prepared.public_key_algo,
                    signature=prepared.signature,
                    payload=prepared.payload,
                    protocol_version=prepared.protocol_version,
                )
                if not ok:
                    if _revocation_retryable_failure(reason):
                        return _revocation_retry_response()
                    return {"ok": False, "detail": reason}
                prepared.reason = reason

            request.state._mesh_body_cache = prepared.body
            request.state._prepared_signed_write = prepared
            return await func(*args, **kwargs)

        setattr(_wrapped, "_requires_signed_write", kind)
        return _wrapped

    return _decorate


def _legacy_dm_signature_compat_enabled() -> bool:
    try:
        return bool(legacy_dm_signature_compat_override_active())
    except Exception:
        return False


def _legacy_gate_signature_compat_enabled() -> bool:
    try:
        return bool(legacy_gate_signature_compat_override_active())
    except Exception:
        return False


def verify_signed_event(
    *,
    event_type: str,
    node_id: str,
    sequence: int,
    public_key: str,
    public_key_algo: str,
    signature: str,
    payload: dict[str, Any],
    protocol_version: str,
) -> tuple[bool, str]:
    if not protocol_version:
        metrics_inc("signature_missing_protocol")
        return False, "Missing protocol_version"

    if protocol_version != PROTOCOL_VERSION:
        metrics_inc("signature_protocol_mismatch")
        return False, f"Unsupported protocol_version: {protocol_version}"

    if not signature or not public_key or not public_key_algo:
        metrics_inc("signature_missing_fields")
        return False, "Missing signature or public key"

    if sequence <= 0:
        metrics_inc("signature_invalid_sequence")
        return False, "Missing or invalid sequence"

    if not verify_node_binding(node_id, public_key):
        metrics_inc("signature_node_mismatch")
        return False, "node_id does not match public key"

    algo = parse_public_key_algo(public_key_algo)
    if not algo:
        metrics_inc("signature_bad_algo")
        return False, "Unsupported public_key_algo"

    normalized = normalize_payload(event_type, payload)
    sig_payload = build_signature_payload(
        event_type=event_type,
        node_id=node_id,
        sequence=sequence,
        payload=normalized,
    )
    if not verify_signature(
        public_key_b64=public_key,
        public_key_algo=algo,
        signature_hex=signature,
        payload=sig_payload,
    ):
        if event_type == "dm_message" and _legacy_dm_signature_compat_enabled():
            legacy_sig_payload = build_signature_payload(
                event_type=event_type,
                node_id=node_id,
                sequence=sequence,
                payload=normalize_dm_message_payload_legacy(payload),
            )
            if verify_signature(
                public_key_b64=public_key,
                public_key_algo=algo,
                signature_hex=signature,
                payload=legacy_sig_payload,
            ):
                return True, "legacy_dm_signature_compat"
        metrics_inc("signature_invalid")
        return False, "Invalid signature"

    return True, "ok"


def preflight_signed_event_integrity(
    *,
    event_type: str,
    node_id: str,
    sequence: int,
    public_key: str,
    public_key_algo: str,
    signature: str,
    protocol_version: str,
) -> tuple[bool, str]:
    if not protocol_version or not signature or not public_key or not public_key_algo:
        return False, "Missing signature or public key"

    if sequence <= 0:
        return False, "Missing or invalid sequence"

    try:
        from services.mesh.mesh_hashchain import infonet
    except Exception as exc:
        logger.error("Signed event integrity preflight unavailable: %s", exc)
        return False, _REVOCATION_PRECHECK_UNAVAILABLE_DETAIL

    if infonet.check_replay(node_id, sequence):
        last = infonet.node_sequences.get(node_id, 0)
        return False, f"Replay detected: sequence {sequence} <= last {last}"

    existing = infonet.public_key_bindings.get(public_key)
    if existing and existing != node_id:
        return False, f"public key already bound to {existing}"

    try:
        revoked, _info = _revocation_status_with_ttl(public_key)
    except _RevocationRefreshUnavailable as exc:
        logger.error("Signed event revocation refresh unavailable: %s", exc)
        return False, _REVOCATION_PRECHECK_UNAVAILABLE_DETAIL
    except Exception as exc:
        logger.error("Signed event revocation refresh unavailable: %s", exc)
        return False, _REVOCATION_PRECHECK_UNAVAILABLE_DETAIL
    if revoked and event_type != "key_revoke":
        return False, "public key is revoked"

    return True, "ok"


def verify_signed_write(
    *,
    event_type: str,
    node_id: str,
    sequence: int,
    public_key: str,
    public_key_algo: str,
    signature: str,
    payload: dict[str, Any],
    protocol_version: str,
) -> tuple[bool, str]:
    sig_ok, sig_reason = verify_signed_event(
        event_type=event_type,
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        payload=payload,
        protocol_version=protocol_version,
    )
    if not sig_ok:
        return False, sig_reason

    integrity_ok, integrity_reason = preflight_signed_event_integrity(
        event_type=event_type,
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        protocol_version=protocol_version,
    )
    if not integrity_ok:
        return False, integrity_reason

    return True, sig_reason


def verify_gate_message_signed_write(
    *,
    node_id: str,
    sequence: int,
    public_key: str,
    public_key_algo: str,
    signature: str,
    payload: dict[str, Any],
    reply_to: str,
    protocol_version: str,
) -> tuple[bool, str, str]:
    normalized_input = normalize_payload("gate_message", payload)
    variants: list[tuple[dict[str, Any], str, str]] = []
    primary = dict(normalized_input)
    if reply_to:
        primary["reply_to"] = reply_to
    variants.append((primary, "ok", reply_to))
    if _legacy_gate_signature_compat_enabled():
        if reply_to:
            no_reply = dict(primary)
            no_reply.pop("reply_to", None)
            variants.append((no_reply, "legacy_gate_reply_signature_compat", ""))
        if "epoch" in primary:
            no_epoch = dict(primary)
            no_epoch.pop("epoch", None)
            variants.append((no_epoch, "legacy_gate_epoch_signature_compat", reply_to))
            if reply_to:
                no_epoch_no_reply = dict(no_epoch)
                no_epoch_no_reply.pop("reply_to", None)
                variants.append((no_epoch_no_reply, "legacy_gate_epoch_reply_signature_compat", ""))

    sig_ok = False
    sig_reason = "Invalid signature"
    effective_reply_to = reply_to
    for candidate_payload, candidate_reason, candidate_reply_to in variants:
        candidate_ok, candidate_sig_reason = verify_signed_event(
            event_type="gate_message",
            node_id=node_id,
            sequence=sequence,
            public_key=public_key,
            public_key_algo=public_key_algo,
            signature=signature,
            payload=candidate_payload,
            protocol_version=protocol_version,
        )
        if candidate_ok:
            sig_ok = True
            sig_reason = candidate_reason
            effective_reply_to = candidate_reply_to
            break
        sig_reason = candidate_sig_reason
    if not sig_ok:
        return False, sig_reason, effective_reply_to

    integrity_ok, integrity_reason = preflight_signed_event_integrity(
        event_type="gate_message",
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        protocol_version=protocol_version,
    )
    if not integrity_ok:
        return False, integrity_reason, effective_reply_to

    return True, sig_reason, effective_reply_to


def recover_verified_gate_reply_to(
    *,
    node_id: str,
    sequence: int,
    public_key: str,
    public_key_algo: str,
    signature: str,
    payload: dict[str, Any],
    reply_to: str,
    protocol_version: str,
) -> str:
    if not reply_to:
        return ""

    verify_payload = normalize_payload("gate_message", payload)
    verify_payload["reply_to"] = reply_to
    signed_ok, _signed_reason = verify_signed_event(
        event_type="gate_message",
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        payload=verify_payload,
        protocol_version=protocol_version,
    )
    if signed_ok:
        return reply_to

    if not _legacy_gate_signature_compat_enabled():
        return ""

    legacy_payload = dict(verify_payload)
    legacy_payload.pop("reply_to", None)
    legacy_ok, _legacy_reason = verify_signed_event(
        event_type="gate_message",
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        payload=legacy_payload,
        protocol_version=protocol_version,
    )
    if legacy_ok:
        return ""
    return ""


def verify_node_bound_signature(
    *,
    node_id: str,
    public_key: str,
    public_key_algo: str,
    signature_hex: str,
    payload: str,
    invalid_detail: str = "Invalid signature",
) -> tuple[bool, str]:
    if not verify_node_binding(node_id, public_key):
        return False, "node_id does not match public key"

    algo = parse_public_key_algo(public_key_algo)
    if not algo:
        return False, "Unsupported public_key_algo"

    if not verify_signature(
        public_key_b64=public_key,
        public_key_algo=algo,
        signature_hex=signature_hex,
        payload=payload,
    ):
        return False, invalid_detail

    return True, "ok"


def verify_key_rotation_claim_signature(
    *,
    old_node_id: str,
    old_public_key: str,
    old_public_key_algo: str,
    old_signature: str,
    new_public_key: str,
    new_public_key_algo: str,
    timestamp: int,
) -> tuple[bool, str]:
    claim_payload = {
        "old_node_id": old_node_id,
        "old_public_key": old_public_key,
        "old_public_key_algo": old_public_key_algo,
        "new_public_key": new_public_key,
        "new_public_key_algo": new_public_key_algo,
        "timestamp": timestamp,
    }
    old_sig_payload = build_signature_payload(
        event_type="key_rotate",
        node_id=old_node_id,
        sequence=0,
        payload=claim_payload,
    )
    return verify_node_bound_signature(
        node_id=old_node_id,
        public_key=old_public_key,
        public_key_algo=old_public_key_algo,
        signature_hex=old_signature,
        payload=old_sig_payload,
        invalid_detail="Invalid old_signature",
    )
