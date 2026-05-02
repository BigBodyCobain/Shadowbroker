"""Automatic gate MLS state repair and coarse repair diagnostics."""

from __future__ import annotations

import threading
import time
from typing import Any

from services.mesh.mesh_gate_mls import (
    MLS_GATE_FORMAT,
    compose_encrypted_gate_message,
    decrypt_gate_message_for_local_identity,
    export_gate_state_snapshot,
    inspect_local_gate_state,
    resync_local_gate_state,
    sign_encrypted_gate_message,
)
from services.mesh.mesh_metadata_exposure import (
    DIAGNOSTIC_METADATA_EXPOSURE,
    normalize_metadata_exposure,
)

_GATE_REPAIR_LOCK = threading.RLock()
_GATE_REPAIR_STATUS: dict[str, dict[str, Any]] = {}
GATE_REPAIR_COOLDOWN_S = 30.0
_GATE_ENVELOPE_REPAIR_DETAILS = {"gate_envelope_required", "gate_envelope_encrypt_failed"}


def reset_gate_repair_manager_for_tests() -> None:
    with _GATE_REPAIR_LOCK:
        _GATE_REPAIR_STATUS.clear()


def _gate_key(gate_id: str) -> str:
    return str(gate_id or "").strip().lower()


def _record_for_gate(gate_id: str) -> dict[str, Any]:
    gate_key = _gate_key(gate_id)
    with _GATE_REPAIR_LOCK:
        record = _GATE_REPAIR_STATUS.get(gate_key)
        if record is None:
            record = {
                "repair_state": "gate_state_ok",
                "detail": "gate access ready",
                "last_attempt_at": 0.0,
                "last_success_at": 0.0,
                "last_failure_at": 0.0,
                "last_reason": "",
                "last_error_detail": "",
                "repair_attempted": False,
                "repair_count": 0,
            }
            _GATE_REPAIR_STATUS[gate_key] = record
        return record


def _cooldown_active(record: dict[str, Any], now: float) -> bool:
    last_failure_at = float(record.get("last_failure_at", 0.0) or 0.0)
    if last_failure_at <= 0:
        return False
    return (now - last_failure_at) < GATE_REPAIR_COOLDOWN_S


def _update_record(gate_id: str, **updates: Any) -> dict[str, Any]:
    record = _record_for_gate(gate_id)
    with _GATE_REPAIR_LOCK:
        record.update(updates)
        return dict(record)


def _ensure_gate_envelope_ready(gate_id: str, *, operation: str) -> dict[str, Any]:
    gate_key = _gate_key(gate_id)
    _update_record(
        gate_key,
        repair_state="gate_envelope_repair_attempted",
        detail="Preparing durable gate envelope state",
        repair_attempted=True,
        last_attempt_at=time.time(),
        last_reason=f"{operation}:gate_envelope_required",
    )
    try:
        from services.mesh.mesh_reputation import gate_manager

        secret = ""
        if hasattr(gate_manager, "ensure_gate_secret"):
            secret = str(gate_manager.ensure_gate_secret(gate_key) or "")
        if not secret and hasattr(gate_manager, "get_gate_secret"):
            secret = str(gate_manager.get_gate_secret(gate_key) or "")
        if not secret:
            return _update_record(
                gate_key,
                repair_state="gate_envelope_repair_failed",
                detail="Gate history key is not available",
                last_failure_at=time.time(),
                last_error_detail="gate_secret_unavailable",
            )
        return _update_record(
            gate_key,
            repair_state="gate_state_ok",
            detail="gate access ready",
            last_success_at=time.time(),
            last_error_detail="",
        )
    except Exception as exc:
        return _update_record(
            gate_key,
            repair_state="gate_envelope_repair_failed",
            detail="Gate history key is not available",
            last_failure_at=time.time(),
            last_error_detail=type(exc).__name__,
        )


def ensure_gate_state_ready(
    gate_id: str,
    *,
    operation: str = "status",
    expected_epoch: int = 0,
) -> dict[str, Any]:
    gate_key = _gate_key(gate_id)
    inspection = inspect_local_gate_state(gate_key, expected_epoch=expected_epoch)
    now = time.time()

    if inspection.get("ok"):
        record = _update_record(
            gate_key,
            repair_state="gate_state_ok",
            detail=str(inspection.get("detail", "gate access ready") or "gate access ready"),
            last_success_at=now,
            last_reason=str(operation or "status"),
            last_error_detail="",
            repair_attempted=False,
        )
        return {**inspection, **record}

    repair_state = str(inspection.get("repair_state", "gate_state_stale") or "gate_state_stale")
    if not bool(inspection.get("repairable", False)):
        record = _update_record(
            gate_key,
            repair_state=repair_state,
            detail=str(inspection.get("detail", "") or "gate state unavailable"),
            last_reason=str(operation or "status"),
            repair_attempted=False,
        )
        return {**inspection, **record}

    record = _record_for_gate(gate_key)
    if _cooldown_active(record, now):
        cooled = _update_record(
            gate_key,
            repair_state="gate_state_resync_failed",
            detail=str(record.get("detail", "") or "gate state resync is cooling down"),
            last_reason=str(operation or "status"),
            repair_attempted=False,
        )
        return {**inspection, **cooled}

    _update_record(
        gate_key,
        repair_state="gate_state_resyncing",
        detail=str(inspection.get("detail", "") or "gate state resyncing"),
        last_attempt_at=now,
        last_reason=str(operation or "status"),
        repair_attempted=True,
        repair_count=int(record.get("repair_count", 0) or 0) + 1,
    )

    repaired = resync_local_gate_state(gate_key, reason=str(operation or "status"))
    if repaired.get("ok"):
        post_repair = inspect_local_gate_state(gate_key, expected_epoch=expected_epoch)
        updated = _update_record(
            gate_key,
            repair_state="gate_state_ok" if post_repair.get("ok") else "gate_state_stale",
            detail=str(post_repair.get("detail", repaired.get("detail", "gate MLS state synchronized")) or "gate MLS state synchronized"),
            last_success_at=time.time(),
            last_error_detail="",
            repair_attempted=True,
        )
        return {**post_repair, **updated, "resynced": True}

    failed = _update_record(
        gate_key,
        repair_state="gate_state_resync_failed",
        detail="gate state resync failed",
        last_failure_at=time.time(),
        last_error_detail=str(repaired.get("error_detail", "") or ""),
        repair_attempted=True,
    )
    return {
        **inspection,
        **failed,
        "ok": False,
        "resynced": False,
    }


def gate_repair_status_snapshot(gate_id: str, *, exposure: str = "") -> dict[str, Any]:
    gate_key = _gate_key(gate_id)
    normalized = normalize_metadata_exposure(exposure)
    status = ensure_gate_state_ready(gate_key, operation="status")
    view = {
        "ok": bool(status.get("ok", False)),
        "gate_id": gate_key,
        "repair_state": str(status.get("repair_state", "gate_state_stale") or "gate_state_stale"),
        "detail": str(status.get("detail", "") or ""),
        "has_local_access": bool(status.get("has_local_access", False)),
        "identity_scope": str(status.get("identity_scope", "") or ""),
        "format": MLS_GATE_FORMAT,
    }
    if normalized == DIAGNOSTIC_METADATA_EXPOSURE:
        view.update(
            {
                "current_epoch": int(status.get("current_epoch", 0) or 0),
                "expected_epoch": int(status.get("expected_epoch", 0) or 0),
                "has_metadata": bool(status.get("has_metadata", False)),
                "has_rust_state": bool(status.get("has_rust_state", False)),
                "repair_attempted": bool(status.get("repair_attempted", False)),
                "last_attempt_at": float(status.get("last_attempt_at", 0.0) or 0.0),
                "last_success_at": float(status.get("last_success_at", 0.0) or 0.0),
                "last_failure_at": float(status.get("last_failure_at", 0.0) or 0.0),
                "last_reason": str(status.get("last_reason", "") or ""),
                "last_error_detail": str(status.get("last_error_detail", "") or ""),
                "repair_count": int(status.get("repair_count", 0) or 0),
            }
        )
    return view


def compose_gate_message_with_repair(gate_id: str, plaintext: str, reply_to: str = "") -> dict[str, Any]:
    result = compose_encrypted_gate_message(gate_id, plaintext, reply_to)
    if result.get("ok"):
        ensure_gate_state_ready(gate_id, operation="compose")
        return result
    detail = str(result.get("detail", "") or "")
    if detail in _GATE_ENVELOPE_REPAIR_DETAILS:
        status = _ensure_gate_envelope_ready(gate_id, operation="compose")
        if status.get("repair_state") == "gate_envelope_repair_failed":
            return result
        retried = compose_encrypted_gate_message(gate_id, plaintext, reply_to)
        if retried.get("ok"):
            return retried
        return result
    if detail != "gate_mls_compose_failed":
        return result
    status = ensure_gate_state_ready(gate_id, operation="compose")
    if not status.get("ok"):
        return result
    return compose_encrypted_gate_message(gate_id, plaintext, reply_to)


def sign_gate_message_with_repair(**kwargs: Any) -> dict[str, Any]:
    result = sign_encrypted_gate_message(**kwargs)
    if result.get("ok"):
        ensure_gate_state_ready(str(kwargs.get("gate_id", "") or ""), operation="sign")
        return result
    detail = str(result.get("detail", "") or "")
    if detail in _GATE_ENVELOPE_REPAIR_DETAILS:
        gate_id = str(kwargs.get("gate_id", "") or "")
        status = _ensure_gate_envelope_ready(gate_id, operation="sign")
        if status.get("repair_state") == "gate_envelope_repair_failed":
            return result
        retried = sign_encrypted_gate_message(**kwargs)
        if retried.get("ok"):
            return retried
        return result
    if detail not in {"gate_mls_sign_failed", "gate_state_stale"}:
        return result
    status = ensure_gate_state_ready(
        str(kwargs.get("gate_id", "") or ""),
        operation="sign",
        expected_epoch=int(kwargs.get("epoch", 0) or 0),
    )
    if not status.get("ok"):
        return result
    return sign_encrypted_gate_message(**kwargs)


def decrypt_gate_message_with_repair(**kwargs: Any) -> dict[str, Any]:
    result = decrypt_gate_message_for_local_identity(**kwargs)
    if result.get("ok"):
        ensure_gate_state_ready(str(kwargs.get("gate_id", "") or ""), operation="decrypt")
        return result
    if str(result.get("detail", "") or "") not in {
        "gate_mls_decrypt_failed",
        "gate_mls_verifier_open_failed",
    }:
        return result
    status = ensure_gate_state_ready(
        str(kwargs.get("gate_id", "") or ""),
        operation="decrypt",
        expected_epoch=int(kwargs.get("epoch", 0) or 0),
    )
    if not status.get("ok"):
        return result
    return decrypt_gate_message_for_local_identity(**kwargs)


def export_gate_state_snapshot_with_repair(gate_id: str) -> dict[str, Any]:
    result = export_gate_state_snapshot(gate_id)
    if result.get("ok"):
        ensure_gate_state_ready(gate_id, operation="export")
        return result
    if str(result.get("detail", "") or "") != "gate_state_export_failed":
        return result
    status = ensure_gate_state_ready(gate_id, operation="export")
    if not status.get("ok"):
        return result
    return export_gate_state_snapshot(gate_id)
