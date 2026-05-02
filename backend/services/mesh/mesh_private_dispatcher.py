from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from enum import Enum
from typing import Any, Callable

from services.config import get_settings
from services.mesh.mesh_metrics import increment as metrics_inc
from services.mesh.mesh_privacy_policy import evaluate_network_release

_LAST_ANONYMOUS_HIDDEN_STATE: bool | None = None


class DMFallbackReason(str, Enum):
    ANONYMOUS_MODE_FORCED_RELAY = "anonymous_mode_forced_relay"
    RELAY_APPROVED_BY_USER = "relay_approved_by_user"
    RNS_TRANSPORT_DISABLED = "rns_transport_disabled"
    RNS_PEER_UNKNOWN = "rns_peer_unknown"
    RNS_PEER_OFFLINE = "rns_peer_offline"
    RNS_LINK_DOWN = "rns_link_down"
    RNS_SEND_FAILED_UNKNOWN = "rns_send_failed_unknown"


def _anonymous_dm_hidden_transport_enforced() -> bool:
    try:
        from services.wormhole_settings import read_wormhole_settings
        from services.wormhole_status import read_wormhole_status

        settings = read_wormhole_settings()
        status = read_wormhole_status()
        anonymous_mode = bool(settings.get("anonymous_mode"))
        effective_transport = str(
            status.get("transport_active", "") or settings.get("transport", "direct") or "direct"
        ).lower()
        ready = bool(status.get("running")) and bool(status.get("ready"))
        hidden_ready = effective_transport in {"tor", "tor_arti", "i2p", "mixnet"}
        return anonymous_mode and ready and hidden_ready
    except Exception:
        return False


def _anonymous_dm_hidden_transport_requested() -> bool:
    """Return True when the user has requested anonymous mode at all.

    This is stricter than the ``_enforced`` helper above. Use it for
    protective logic that must keep anonymous-intent sends from silently
    degrading during warmup or temporary hidden-transport loss.
    """
    try:
        from services.wormhole_settings import read_wormhole_settings

        settings = read_wormhole_settings()
        return bool(settings.get("anonymous_mode"))
    except Exception:
        return False


def _hidden_relay_transport_effective() -> bool:
    try:
        from services.wormhole_settings import read_wormhole_settings
        from services.wormhole_status import read_wormhole_status

        settings = read_wormhole_settings()
        status = read_wormhole_status()
        effective_transport = str(
            status.get("transport_active", "") or settings.get("transport", "direct") or "direct"
        ).lower()
        ready = bool(status.get("running")) and bool(status.get("ready"))
        return ready and effective_transport in {"tor", "tor_arti", "i2p", "mixnet"}
    except Exception:
        return False


def _secure_dm_enabled() -> bool:
    return bool(get_settings().MESH_DM_SECURE_MODE)


def _rns_private_dm_ready() -> bool:
    try:
        from services.mesh.mesh_rns import rns_bridge

        return bool(rns_bridge.enabled()) and bool(rns_bridge.status().get("private_dm_direct_ready"))
    except Exception:
        return False


def _high_privacy_profile_enabled() -> bool:
    try:
        from services.wormhole_settings import read_wormhole_settings

        settings = read_wormhole_settings()
        return str(settings.get("privacy_profile", "default") or "default").lower() == "high"
    except Exception:
        return False


def _maybe_apply_dm_relay_jitter() -> None:
    if not _high_privacy_profile_enabled():
        return
    time.sleep((50 + int.from_bytes(os.urandom(2), "big") % 451) / 1000.0)


def _rns_private_dm_status(direct_ready: bool) -> dict[str, Any]:
    default = {
        "enabled": bool(direct_ready),
        "ready": bool(direct_ready),
        "configured_peers": 1 if direct_ready else 0,
        "active_peers": 1 if direct_ready else 0,
        "private_dm_direct_ready": bool(direct_ready),
    }
    try:
        from services.mesh.mesh_rns import rns_bridge

        status_reader = getattr(rns_bridge, "status", None)
        status = dict(status_reader() or {}) if callable(status_reader) else {}
        enabled_reader = getattr(rns_bridge, "enabled", None)
        if callable(enabled_reader):
            status.setdefault("enabled", bool(enabled_reader()))
        else:
            status.setdefault("enabled", bool(default["enabled"]))
        status.setdefault("ready", bool(status.get("enabled", default["enabled"])))
        status.setdefault("configured_peers", int(default["configured_peers"]))
        status.setdefault("active_peers", int(default["active_peers"]))
        status.setdefault("private_dm_direct_ready", bool(direct_ready))
        return status
    except Exception:
        return default


def _dm_fallback_reason_from_status(
    *,
    direct_attempted: bool,
    rns_status: dict[str, Any],
) -> DMFallbackReason:
    if direct_attempted:
        return DMFallbackReason.RNS_SEND_FAILED_UNKNOWN
    if not bool(rns_status.get("enabled")):
        return DMFallbackReason.RNS_TRANSPORT_DISABLED
    if not bool(rns_status.get("ready")):
        return DMFallbackReason.RNS_LINK_DOWN
    configured_peers = int(rns_status.get("configured_peers", 0) or 0)
    if configured_peers <= 0:
        return DMFallbackReason.RNS_PEER_UNKNOWN
    active_peers = int(rns_status.get("active_peers", 0) or 0)
    if active_peers <= 0:
        return DMFallbackReason.RNS_PEER_OFFLINE
    return DMFallbackReason.RNS_SEND_FAILED_UNKNOWN


def _emit_dm_fallback_observation(
    *,
    mesh_router: Any,
    reason: DMFallbackReason,
    detail: str,
    hidden_transport_effective: bool,
    sampled: bool,
) -> None:
    if sampled:
        metrics_inc("silent_degradations")
    mesh_router.record_tier_event(
        "fallback",
        lane="dm",
        transport="relay",
        detail=detail,
        hidden_transport_effective=hidden_transport_effective,
        reason=reason,
    )


def _dispatch_result(
    *,
    ok: bool,
    lane: str,
    selected_transport: str,
    selected_carrier: str,
    dispatch_reason: str,
    hidden_transport_effective: bool,
    no_acceptable_path: bool,
    detail: str,
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "ok": bool(ok),
        "lane": str(lane or ""),
        "selected_transport": str(selected_transport or ""),
        "selected_carrier": str(selected_carrier or ""),
        "dispatch_reason": str(dispatch_reason or ""),
        "hidden_transport_effective": bool(hidden_transport_effective),
        "no_acceptable_path": bool(no_acceptable_path),
        "detail": str(detail or ""),
        # Compatibility keys preserved for existing callers/tests.
        "transport": str(selected_transport or ""),
        "carrier": str(selected_carrier or ""),
    }
    result.update(extra)
    return result


def _relay_sender_identity(payload: dict[str, Any]) -> str:
    sender_id = str(payload.get("sender_id", "") or "")
    sender_token_hash = str(payload.get("sender_token_hash", "") or "")
    sender_seal = str(payload.get("sender_seal", "") or "")
    relay_salt_hex = str(payload.get("relay_salt", "") or "").strip().lower()

    relay_sender_id = sender_id
    if sender_seal and relay_salt_hex:
        relay_sender_id = "sealed:" + hmac.new(
            bytes.fromhex(relay_salt_hex),
            sender_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:16]
    if sender_token_hash:
        relay_sender_id = f"sender_token:{sender_token_hash}"
    return relay_sender_id


def _dispatch_dm(
    payload: dict[str, Any],
    *,
    secure_dm_enabled: Callable[[], bool],
    rns_private_dm_ready: Callable[[], bool],
    anonymous_dm_hidden_transport_enforced: Callable[[], bool],
    anonymous_dm_hidden_transport_requested: Callable[[], bool],
    apply_dm_relay_jitter: Callable[[], None],
    relay_hidden_transport_effective: Callable[[], bool] | None = None,
    relay_consent_granted: bool = True,
    relay_consent_explicit: bool = False,
) -> dict[str, Any]:
    from services.mesh.mesh_dm_relay import dm_relay
    from services.mesh.mesh_router import mesh_router

    sender_id = str(payload.get("sender_id", "") or "")
    recipient_id = str(payload.get("recipient_id", "") or "")
    delivery_class = str(payload.get("delivery_class", "") or "")
    recipient_token = str(payload.get("recipient_token", "") or "")
    ciphertext = str(payload.get("ciphertext", "") or "")
    payload_format = str(payload.get("format", "mls1") or "mls1")
    session_welcome = str(payload.get("session_welcome", "") or "")
    msg_id = str(payload.get("msg_id", "") or "")
    timestamp = int(payload.get("timestamp", 0) or 0)
    sender_seal = str(payload.get("sender_seal", "") or "")
    sender_token_hash = str(payload.get("sender_token_hash", "") or "")
    relay_sender_id = _relay_sender_identity(payload)
    anonymous_hidden = bool(anonymous_dm_hidden_transport_enforced())
    hidden_relay = bool(anonymous_hidden)
    if not hidden_relay and relay_hidden_transport_effective is not None:
        try:
            hidden_relay = bool(relay_hidden_transport_effective())
        except Exception:
            hidden_relay = False
    secure_dm = bool(secure_dm_enabled())
    direct_ready = bool(rns_private_dm_ready())
    rns_status = _rns_private_dm_status(direct_ready)
    fallback_reason: DMFallbackReason | None = None
    fallback_detail = ""
    global _LAST_ANONYMOUS_HIDDEN_STATE
    if _LAST_ANONYMOUS_HIDDEN_STATE is None or _LAST_ANONYMOUS_HIDDEN_STATE != anonymous_hidden:
        mesh_router.record_tier_event(
            "anonymous_mode_flap",
            lane="dm",
            detail="anonymous_hidden_transport_state_changed",
            hidden_transport_effective=anonymous_hidden,
        )
        _LAST_ANONYMOUS_HIDDEN_STATE = anonymous_hidden

    if bool(anonymous_dm_hidden_transport_requested()) and not anonymous_hidden:
        return _dispatch_result(
            ok=False,
            lane="dm",
            selected_transport="",
            selected_carrier="",
            dispatch_reason="anonymous_mode_waiting_for_hidden_transport",
            hidden_transport_effective=False,
            no_acceptable_path=False,
            detail="The sealed message is waiting for an anonymous route.",
            msg_id=msg_id,
            local_state="sealed_local",
            network_state="queued_private_release",
        )

    if secure_dm and direct_ready and not anonymous_hidden:
        from services.mesh.mesh_rns import rns_bridge

        if dm_relay.is_blocked(recipient_id, sender_id):
            return _dispatch_result(
                ok=False,
                lane="dm",
                selected_transport="reticulum",
                selected_carrier="reticulum_direct",
                dispatch_reason="recipient_blocks_sender",
                hidden_transport_effective=False,
                no_acceptable_path=False,
                detail="Recipient is not accepting your messages",
                msg_id=msg_id,
            )
        mailbox_key = dm_relay.mailbox_key_for_delivery(
            recipient_id=recipient_id,
            delivery_class=delivery_class,
            recipient_token=recipient_token if delivery_class == "shared" else None,
        )
        direct = rns_bridge.send_private_dm(
            mailbox_key=mailbox_key,
            envelope={
                "sender_id": relay_sender_id,
                "ciphertext": ciphertext,
                "format": payload_format,
                "session_welcome": session_welcome,
                "timestamp": timestamp,
                "msg_id": msg_id,
                "delivery_class": delivery_class,
                "sender_seal": sender_seal,
            },
        )
        if direct:
            return _dispatch_result(
                ok=True,
                lane="dm",
                selected_transport="reticulum",
                selected_carrier="reticulum_direct",
                dispatch_reason="direct_private_transport_ready",
                hidden_transport_effective=False,
                no_acceptable_path=False,
                detail="Delivered via Reticulum",
                msg_id=msg_id,
            )
        fallback_reason = _dm_fallback_reason_from_status(
            direct_attempted=True,
            rns_status=rns_status,
        )
        fallback_detail = "reticulum_direct_failed_relay_fallback"
        if not relay_consent_granted:
            return _dispatch_result(
                ok=False,
                lane="dm",
                selected_transport="",
                selected_carrier="",
                dispatch_reason="relay_user_approval_required",
                hidden_transport_effective=False,
                no_acceptable_path=False,
                detail="Direct private delivery is unavailable; relay approval is required.",
                msg_id=msg_id,
                relay_approval_required=True,
                fallback_reason=str(fallback_reason.value),
            )
    elif anonymous_hidden:
        fallback_reason = DMFallbackReason.ANONYMOUS_MODE_FORCED_RELAY
        fallback_detail = "anonymous_hidden_transport_requires_relay"
    elif secure_dm:
        fallback_reason = _dm_fallback_reason_from_status(
            direct_attempted=False,
            rns_status=rns_status,
        )
        fallback_detail = "reticulum_unavailable_relay_fallback"
        if not relay_consent_granted:
            return _dispatch_result(
                ok=False,
                lane="dm",
                selected_transport="",
                selected_carrier="",
                dispatch_reason="relay_user_approval_required",
                hidden_transport_effective=False,
                no_acceptable_path=False,
                detail="Direct private delivery is unavailable; relay approval is required.",
                msg_id=msg_id,
                relay_approval_required=True,
                fallback_reason=str(fallback_reason.value),
            )

    if fallback_reason is not None:
        emitted_reason = fallback_reason
        sampled = bool(secure_dm and not hidden_relay)
        if hidden_relay:
            sampled = False
        elif relay_consent_explicit:
            emitted_reason = DMFallbackReason.RELAY_APPROVED_BY_USER
            sampled = False
        _emit_dm_fallback_observation(
            mesh_router=mesh_router,
            reason=emitted_reason,
            detail=fallback_detail,
            hidden_transport_effective=bool(hidden_relay),
            sampled=sampled,
        )

    apply_dm_relay_jitter()
    relay_result = dm_relay.deposit(
        sender_id=relay_sender_id,
        raw_sender_id=sender_id,
        recipient_id=recipient_id,
        ciphertext=ciphertext,
        msg_id=msg_id,
        delivery_class=delivery_class,
        recipient_token=recipient_token if delivery_class == "shared" else None,
        sender_seal=sender_seal,
        sender_token_hash=sender_token_hash,
        payload_format=payload_format,
        session_welcome=session_welcome,
    )
    if not relay_result.get("ok"):
        return _dispatch_result(
            ok=False,
            lane="dm",
            selected_transport="relay",
            selected_carrier="relay",
            dispatch_reason=(
            "anonymous_hidden_transport_requires_relay"
                if anonymous_hidden
                else "private_relay_delivery_failed"
            ),
            hidden_transport_effective=bool(hidden_relay),
            no_acceptable_path=False,
            detail=str(relay_result.get("detail", "") or "private relay delivery failed"),
            msg_id=msg_id,
        )
    return _dispatch_result(
        ok=True,
        lane="dm",
        selected_transport="relay",
        selected_carrier="relay",
        dispatch_reason=(
            "anonymous_hidden_transport_requires_relay"
                if anonymous_hidden
                else "private_relay_delivery"
        ),
        hidden_transport_effective=bool(hidden_relay),
        no_acceptable_path=False,
        detail=(
            "Anonymous mode keeps private DMs off direct transport; delivered via hidden relay path"
            if anonymous_hidden
            else "Delivered via hidden relay path"
            if hidden_relay
            else str(relay_result.get("detail", "") or "Delivered privately")
        ),
        msg_id=str(relay_result.get("msg_id", "") or msg_id),
    )


def _gate_publish_via_tor(gate_id: str, event: dict[str, Any], *, current_tier: str) -> dict[str, Any]:
    try:
        from services.mesh.mesh_router import MeshEnvelope, PayloadType, Priority, mesh_router

        envelope = MeshEnvelope(
            sender_id=str(event.get("node_id", "") or event.get("sender_id", "") or "gate"),
            destination=f"gate:{gate_id}",
            priority=Priority.NORMAL,
            payload_type=PayloadType.COMMAND,
            trust_tier=str(current_tier or "private_strong"),
            payload=json.dumps(event, separators=(",", ":"), ensure_ascii=False),
            message_id=str(event.get("event_id", "") or ""),
            timestamp=float(event.get("timestamp", 0) or 0.0),
        )
        if not mesh_router.tor_arti.can_reach(envelope):
            return {
                "ok": False,
                "carrier": "tor_arti",
                "detail": "Tor onion peer push is not ready or has no onion peers",
            }
        result = mesh_router.tor_arti.send(envelope, {})
        return {
            "ok": bool(result.ok),
            "carrier": "tor_arti",
            "detail": str(result.detail or ""),
            "transport_result": result.to_dict(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "carrier": "tor_arti",
            "detail": str(exc) or type(exc).__name__,
        }


def _gate_publish_via_rns(gate_id: str, event: dict[str, Any]) -> dict[str, Any]:
    try:
        from services.mesh.mesh_rns import rns_bridge

        rns_bridge.publish_gate_event(gate_id, event)
        return {"ok": True, "carrier": "reticulum", "detail": "published via RNS"}
    except Exception as exc:
        return {
            "ok": False,
            "carrier": "reticulum",
            "detail": str(exc) or type(exc).__name__,
        }


def _dispatch_gate(payload: dict[str, Any], *, current_tier: str) -> dict[str, Any]:
    from services.mesh.mesh_hashchain import gate_store

    gate_id = str(payload.get("gate_id", "") or "")
    event = dict(payload.get("event") or {})
    if not gate_id or not event:
        return _dispatch_result(
            ok=False,
            lane="gate",
            selected_transport="gate_private_store",
            selected_carrier="gate_store_publish",
            dispatch_reason="gate_payload_incomplete",
            hidden_transport_effective=False,
            no_acceptable_path=True,
            detail="No acceptable private gate path is available for an incomplete payload.",
            gate_id=gate_id,
            event_id=str(event.get("event_id", "") or payload.get("event_id", "") or ""),
        )
    stored = gate_store.append(gate_id, event)
    publish_attempts: list[dict[str, Any]] = []
    tor_result = _gate_publish_via_tor(gate_id, stored, current_tier=current_tier)
    publish_attempts.append(tor_result)
    if tor_result.get("ok"):
        return _dispatch_result(
            ok=True,
            lane="gate",
            selected_transport="tor_arti",
            selected_carrier="tor_arti_peer_push",
            dispatch_reason="gate_private_tor_publish",
            hidden_transport_effective=True,
            no_acceptable_path=False,
            detail=f"Message posted to gate '{gate_id}' via Tor",
            gate_id=gate_id,
            event_id=str(stored.get("event_id", "") or event.get("event_id", "") or ""),
            published=True,
            local_state="sealed_local",
            network_state="published_private",
            publish_attempts=publish_attempts,
        )

    rns_result = _gate_publish_via_rns(gate_id, stored)
    publish_attempts.append(rns_result)
    if not rns_result.get("ok"):
        return _dispatch_result(
            ok=False,
            lane="gate",
            selected_transport="gate_private_store",
            selected_carrier="gate_store_only",
            dispatch_reason="gate_private_publish_pending",
            hidden_transport_effective=False,
            no_acceptable_path=False,
            detail=(
                "Gate message is sealed locally and queued for private publication"
            ),
            gate_id=gate_id,
            event_id=str(stored.get("event_id", "") or event.get("event_id", "") or ""),
            published=False,
            local_state="sealed_local",
            network_state="queued_private_release",
            publish_error=str(rns_result.get("detail", "") or tor_result.get("detail", "") or ""),
            publish_attempts=publish_attempts,
        )
    return _dispatch_result(
        ok=True,
        lane="gate",
        selected_transport="reticulum",
        selected_carrier="rns_gate_publish",
        dispatch_reason="gate_private_rns_publish_after_tor_unavailable",
        hidden_transport_effective=False,
        no_acceptable_path=False,
        detail=f"Message posted to gate '{gate_id}' via RNS",
        gate_id=gate_id,
        event_id=str(stored.get("event_id", "") or event.get("event_id", "") or ""),
        published=True,
        local_state="sealed_local",
        network_state="published_private",
        publish_attempts=publish_attempts,
    )


def attempt_private_release(
    *,
    lane: str,
    payload: dict[str, Any],
    current_tier: str,
    secure_dm_enabled: Callable[[], bool] | None = None,
    rns_private_dm_ready: Callable[[], bool] | None = None,
    anonymous_dm_hidden_transport_enforced: Callable[[], bool] | None = None,
    anonymous_dm_hidden_transport_requested: Callable[[], bool] | None = None,
    relay_hidden_transport_effective: Callable[[], bool] | None = None,
    apply_dm_relay_jitter: Callable[[], None] | None = None,
    relay_consent_granted: bool = True,
    relay_consent_explicit: bool = False,
) -> dict[str, Any]:
    normalized_lane = str(lane or "").strip().lower()
    decision = evaluate_network_release(normalized_lane, current_tier)
    if not decision.allowed:
        return _dispatch_result(
            ok=False,
            lane=normalized_lane,
            selected_transport="",
            selected_carrier="",
            dispatch_reason=decision.reason_code,
            hidden_transport_effective=False,
            no_acceptable_path=True,
            detail=decision.plain_reason,
            current_tier=str(decision.current_tier or ""),
            required_tier=str(decision.required_tier or ""),
            policy_status_code=str(decision.status_code or ""),
            policy_reason_code=str(decision.reason_code or ""),
        )
    if normalized_lane == "dm":
        return _dispatch_dm(
            dict(payload or {}),
            secure_dm_enabled=secure_dm_enabled or _secure_dm_enabled,
            rns_private_dm_ready=rns_private_dm_ready or _rns_private_dm_ready,
            anonymous_dm_hidden_transport_enforced=(
                anonymous_dm_hidden_transport_enforced or _anonymous_dm_hidden_transport_enforced
            ),
            anonymous_dm_hidden_transport_requested=(
                anonymous_dm_hidden_transport_requested or _anonymous_dm_hidden_transport_requested
            ),
            relay_hidden_transport_effective=(
                relay_hidden_transport_effective or _hidden_relay_transport_effective
            ),
            apply_dm_relay_jitter=apply_dm_relay_jitter or _maybe_apply_dm_relay_jitter,
            relay_consent_granted=relay_consent_granted,
            relay_consent_explicit=relay_consent_explicit,
        )
    if normalized_lane == "gate":
        return _dispatch_gate(dict(payload or {}), current_tier=str(current_tier or ""))
    return _dispatch_result(
        ok=False,
        lane=normalized_lane,
        selected_transport="",
        selected_carrier="",
        dispatch_reason="unsupported_private_release_lane",
        hidden_transport_effective=False,
        no_acceptable_path=True,
        detail=f"No acceptable private path exists for lane '{normalized_lane}'.",
    )
