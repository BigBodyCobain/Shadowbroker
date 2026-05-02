"""Compatibility telemetry and sunset targets for legacy Mesh paths."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

from services.config import get_settings

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
COMPATIBILITY_FILE = DATA_DIR / "mesh_compatibility_usage.json"
RECENT_TARGET_LIMIT = 8
_LOCK = threading.Lock()

LEGACY_NODE_ID_BINDING_TARGET = {
    "target_version": "0.10.0",
    "target_date": "2026-06-01",
    "status": "telemetry_only",
    "block_env": "MESH_BLOCK_LEGACY_NODE_ID_COMPAT",
}

LEGACY_AGENT_ID_LOOKUP_TARGET = {
    "target_version": "0.10.0",
    "target_date": "2026-06-01",
    "status": "enforced",
    "block_env": "MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP",
    "override_env": "MESH_ALLOW_LEGACY_AGENT_ID_LOOKUP_UNTIL",
}

LEGACY_DM_SIGNATURE_COMPAT_TARGET = {
    "target_version": "0.10.0",
    "target_date": "2026-06-01",
    "status": "telemetry_only",
    "override_env": "MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL",
}

LEGACY_GATE_SIGNATURE_COMPAT_TARGET = {
    "target_version": "0.10.0",
    "target_date": "2026-06-01",
    "status": "telemetry_only",
    "override_env": "MESH_ALLOW_LEGACY_GATE_SIGNATURE_COMPAT_UNTIL",
}

LEGACY_DM_GET_TARGET = {
    "target_version": "0.10.0",
    "target_date": "2026-06-01",
    "status": "telemetry_only",
    "override_env": "MESH_ALLOW_LEGACY_DM_GET_UNTIL",
}

COMPAT_DM_INVITE_IMPORT_TARGET = {
    "target_version": "0.10.0",
    "target_date": "2026-06-01",
    "status": "telemetry_only",
    "override_env": "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT_UNTIL",
}

LEGACY_DM1_TARGET = {
    "target_version": "0.10.0",
    "target_date": "2026-06-01",
    "status": "telemetry_only",
    "override_env": "MESH_ALLOW_LEGACY_DM1_UNTIL",
}


def sunset_target_label(entry: dict[str, Any]) -> str:
    version = str(entry.get("target_version", "") or "").strip()
    date = str(entry.get("target_date", "") or "").strip()
    if version and date:
        return f"{version} ({date})"
    if version:
        return version
    if date:
        return date
    return "the current compatibility cutoff"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _dev_legacy_compat_override_enabled() -> bool:
    """True only for explicit local/dev migration work.

    Date-based legacy compatibility env vars are intentionally not enough on
    their own anymore. Phase-2 private profiles must not accidentally reopen
    DM1, legacy GET mailbox access, direct agent_id lookup, or legacy signing
    just because an old migration variable is still present.
    """
    return _bool_env("MESH_DEV_ALLOW_LEGACY_COMPAT", False)


def _dated_override_active(raw: str) -> bool:
    value = str(raw or "").strip()
    if not value:
        return False
    try:
        return _today_utc() <= date.fromisoformat(value)
    except ValueError:
        return False


def _default_usage() -> dict[str, Any]:
    return {
        "legacy_node_id_binding": {
            "count": 0,
            "blocked_count": 0,
            "last_seen_at": 0,
            "recent_targets": [],
        },
        "legacy_agent_id_lookup": {
            "count": 0,
            "blocked_count": 0,
            "last_seen_at": 0,
            "recent_targets": [],
        },
        "legacy_dm_get": {
            "count": 0,
            "blocked_count": 0,
            "last_seen_at": 0,
            "recent_kinds": [],
        },
    }


def _normalize_recent_kinds(entries: Any) -> list[str]:
    normalized: list[str] = []
    for raw in list(entries or []):
        kind = str(raw or "").strip().lower()
        if not kind or kind in normalized:
            continue
        normalized.append(kind)
    return normalized[-4:]


def _normalize_recent_targets(kind: str, entries: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in list(entries or []):
        current = dict(raw or {})
        if kind == "legacy_node_id_binding":
            node_id = str(current.get("node_id", "") or "").strip().lower()
            if not node_id:
                continue
            normalized.append(
                {
                    "node_id": node_id,
                    "current_node_id": str(current.get("current_node_id", "") or "").strip().lower(),
                    "count": _safe_int(current.get("count", 0), 0),
                    "blocked_count": _safe_int(current.get("blocked_count", 0), 0),
                    "last_seen_at": _safe_int(current.get("last_seen_at", 0), 0),
                }
            )
        else:
            agent_id = str(current.get("agent_id", "") or "").strip().lower()
            if not agent_id:
                continue
            normalized.append(
                {
                    "agent_id": agent_id,
                    "lookup_kinds": [
                        str(item or "").strip().lower()
                        for item in list(current.get("lookup_kinds") or [])
                        if str(item or "").strip()
                    ][-4:],
                    "count": _safe_int(current.get("count", 0), 0),
                    "blocked_count": _safe_int(current.get("blocked_count", 0), 0),
                    "last_seen_at": _safe_int(current.get("last_seen_at", 0), 0),
                }
            )
    normalized.sort(key=lambda item: _safe_int(item.get("last_seen_at", 0), 0), reverse=True)
    return normalized[:RECENT_TARGET_LIMIT]


def _normalize_usage(payload: dict[str, Any] | None) -> dict[str, Any]:
    current = _default_usage()
    current.update(payload or {})
    for kind in ("legacy_node_id_binding", "legacy_agent_id_lookup"):
        bucket = dict(current.get(kind) or {})
        current[kind] = {
            "count": _safe_int(bucket.get("count", 0), 0),
            "blocked_count": _safe_int(bucket.get("blocked_count", 0), 0),
            "last_seen_at": _safe_int(bucket.get("last_seen_at", 0), 0),
            "recent_targets": _normalize_recent_targets(kind, bucket.get("recent_targets", [])),
        }
    mailbox_bucket = dict(current.get("legacy_dm_get") or {})
    current["legacy_dm_get"] = {
        "count": _safe_int(mailbox_bucket.get("count", 0), 0),
        "blocked_count": _safe_int(mailbox_bucket.get("blocked_count", 0), 0),
        "last_seen_at": _safe_int(mailbox_bucket.get("last_seen_at", 0), 0),
        "recent_kinds": _normalize_recent_kinds(mailbox_bucket.get("recent_kinds", [])),
    }
    return current


def _read_usage() -> dict[str, Any]:
    try:
        if not COMPATIBILITY_FILE.exists():
            return _default_usage()
        return _normalize_usage(json.loads(COMPATIBILITY_FILE.read_text(encoding="utf-8")))
    except Exception:
        return _default_usage()


def _write_usage(payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = COMPATIBILITY_FILE.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temp_path.replace(COMPATIBILITY_FILE)


def _record_recent_node_id(
    entries: list[dict[str, Any]],
    *,
    node_id: str,
    current_node_id: str,
    blocked: bool,
    seen_at: int,
) -> list[dict[str, Any]]:
    key = str(node_id or "").strip().lower()
    current = str(current_node_id or "").strip().lower()
    matched = None
    for entry in entries:
        if str(entry.get("node_id", "") or "").strip().lower() == key:
            matched = entry
            break
    if matched is None:
        matched = {
            "node_id": key,
            "current_node_id": current,
            "count": 0,
            "blocked_count": 0,
            "last_seen_at": 0,
        }
        entries.append(matched)
    matched["current_node_id"] = current
    matched["count"] = _safe_int(matched.get("count", 0), 0) + 1
    matched["blocked_count"] = _safe_int(matched.get("blocked_count", 0), 0) + (1 if blocked else 0)
    matched["last_seen_at"] = seen_at
    entries.sort(key=lambda item: _safe_int(item.get("last_seen_at", 0), 0), reverse=True)
    return entries[:RECENT_TARGET_LIMIT]


def _record_recent_lookup(
    entries: list[dict[str, Any]],
    *,
    agent_id: str,
    lookup_kind: str,
    blocked: bool,
    seen_at: int,
) -> list[dict[str, Any]]:
    key = str(agent_id or "").strip().lower()
    kind = str(lookup_kind or "").strip().lower()
    matched = None
    for entry in entries:
        if str(entry.get("agent_id", "") or "").strip().lower() == key:
            matched = entry
            break
    if matched is None:
        matched = {
            "agent_id": key,
            "lookup_kinds": [],
            "count": 0,
            "blocked_count": 0,
            "last_seen_at": 0,
        }
        entries.append(matched)
    lookup_kinds = [
        str(item or "").strip().lower()
        for item in list(matched.get("lookup_kinds") or [])
        if str(item or "").strip()
    ]
    if kind and kind not in lookup_kinds:
        lookup_kinds.append(kind)
    matched["lookup_kinds"] = lookup_kinds[-4:]
    matched["count"] = _safe_int(matched.get("count", 0), 0) + 1
    matched["blocked_count"] = _safe_int(matched.get("blocked_count", 0), 0) + (1 if blocked else 0)
    matched["last_seen_at"] = seen_at
    entries.sort(key=lambda item: _safe_int(item.get("last_seen_at", 0), 0), reverse=True)
    return entries[:RECENT_TARGET_LIMIT]


def legacy_node_id_compat_blocked() -> bool:
    if _bool_env("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", False):
        return True
    return not legacy_node_id_compat_override_active()


def _today_utc() -> date:
    return date.today()


def legacy_node_id_compat_override_until() -> str:
    return str(os.environ.get("MESH_ALLOW_LEGACY_NODE_ID_COMPAT_UNTIL", "") or "").strip()


def legacy_node_id_compat_override_active() -> bool:
    return _dev_legacy_compat_override_enabled() and _dated_override_active(
        legacy_node_id_compat_override_until()
    )


def legacy_agent_id_lookup_blocked() -> bool:
    if _bool_env("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", True):
        return True
    return not legacy_agent_id_lookup_override_active()


def legacy_agent_id_lookup_override_until() -> str:
    return str(os.environ.get("MESH_ALLOW_LEGACY_AGENT_ID_LOOKUP_UNTIL", "") or "").strip()


def legacy_agent_id_lookup_override_active() -> bool:
    return _dev_legacy_compat_override_enabled() and _dated_override_active(
        legacy_agent_id_lookup_override_until()
    )


def legacy_dm_signature_compat_override_until() -> str:
    return str(os.environ.get("MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL", "") or "").strip()


def legacy_dm_signature_compat_override_active() -> bool:
    return _dev_legacy_compat_override_enabled() and _dated_override_active(
        legacy_dm_signature_compat_override_until()
    )


def legacy_gate_signature_compat_override_until() -> str:
    return str(os.environ.get("MESH_ALLOW_LEGACY_GATE_SIGNATURE_COMPAT_UNTIL", "") or "").strip()


def legacy_gate_signature_compat_override_active() -> bool:
    return _dev_legacy_compat_override_enabled() and _dated_override_active(
        legacy_gate_signature_compat_override_until()
    )


def legacy_dm_get_override_until() -> str:
    return str(os.environ.get("MESH_ALLOW_LEGACY_DM_GET_UNTIL", "") or "").strip()


def legacy_dm_get_override_active() -> bool:
    return _dev_legacy_compat_override_enabled() and _dated_override_active(
        legacy_dm_get_override_until()
    )


def compat_dm_invite_import_override_until() -> str:
    return str(os.environ.get("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT_UNTIL", "") or "").strip()


def compat_dm_invite_import_override_active() -> bool:
    if not _dev_legacy_compat_override_enabled():
        return False
    if "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT" in os.environ:
        return _bool_env("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", False)
    return _dated_override_active(compat_dm_invite_import_override_until())


def legacy_dm1_override_until() -> str:
    return str(os.environ.get("MESH_ALLOW_LEGACY_DM1_UNTIL", "") or "").strip()


def legacy_dm1_override_active() -> bool:
    return _dev_legacy_compat_override_enabled() and _dated_override_active(
        legacy_dm1_override_until()
    )


def _sunset_target(
    entry: dict[str, Any],
    *,
    blocked: bool,
    unblocked_status: str = "telemetry_only",
    override_until: str = "",
) -> dict[str, Any]:
    target = dict(entry)
    target["status"] = "enforced" if blocked else str(unblocked_status or "telemetry_only")
    target["blocked"] = blocked
    if override_until:
        target["override_until"] = override_until
    return target


def record_legacy_node_id_binding(node_id: str, current_node_id: str, *, blocked: bool = False) -> None:
    seen_at = int(time.time())
    with _LOCK:
        usage = _read_usage()
        bucket = usage["legacy_node_id_binding"]
        bucket["count"] = _safe_int(bucket.get("count", 0), 0) + 1
        bucket["blocked_count"] = _safe_int(bucket.get("blocked_count", 0), 0) + (1 if blocked else 0)
        bucket["last_seen_at"] = seen_at
        bucket["recent_targets"] = _record_recent_node_id(
            list(bucket.get("recent_targets") or []),
            node_id=node_id,
            current_node_id=current_node_id,
            blocked=blocked,
            seen_at=seen_at,
        )
        _write_usage(usage)


def record_legacy_agent_id_lookup(
    agent_id: str,
    *,
    lookup_kind: str,
    blocked: bool = False,
) -> None:
    seen_at = int(time.time())
    with _LOCK:
        usage = _read_usage()
        bucket = usage["legacy_agent_id_lookup"]
        bucket["count"] = _safe_int(bucket.get("count", 0), 0) + 1
        bucket["blocked_count"] = _safe_int(bucket.get("blocked_count", 0), 0) + (1 if blocked else 0)
        bucket["last_seen_at"] = seen_at
        bucket["recent_targets"] = _record_recent_lookup(
            list(bucket.get("recent_targets") or []),
            agent_id=agent_id,
            lookup_kind=lookup_kind,
            blocked=blocked,
            seen_at=seen_at,
        )
        _write_usage(usage)


def record_legacy_dm_get(
    *,
    operation: str,
    blocked: bool = False,
) -> None:
    seen_at = int(time.time())
    kind = str(operation or "").strip().lower()
    with _LOCK:
        usage = _read_usage()
        bucket = usage["legacy_dm_get"]
        bucket["count"] = _safe_int(bucket.get("count", 0), 0) + 1
        bucket["blocked_count"] = _safe_int(bucket.get("blocked_count", 0), 0) + (1 if blocked else 0)
        bucket["last_seen_at"] = seen_at
        recent_kinds = [
            str(item or "").strip().lower()
            for item in list(bucket.get("recent_kinds") or [])
            if str(item or "").strip()
        ]
        if kind and kind not in recent_kinds:
            recent_kinds.append(kind)
        bucket["recent_kinds"] = recent_kinds[-4:]
        _write_usage(usage)


def compatibility_status_snapshot() -> dict[str, Any]:
    node_blocked = legacy_node_id_compat_blocked()
    node_override_until = legacy_node_id_compat_override_until() if not node_blocked else ""
    lookup_blocked = legacy_agent_id_lookup_blocked()
    lookup_override_active = legacy_agent_id_lookup_override_active()
    lookup_override_until = legacy_agent_id_lookup_override_until() if lookup_override_active else ""
    dm_sig_override_active = legacy_dm_signature_compat_override_active()
    dm_sig_override_until = legacy_dm_signature_compat_override_until() if dm_sig_override_active else ""
    gate_sig_override_active = legacy_gate_signature_compat_override_active()
    gate_sig_override_until = legacy_gate_signature_compat_override_until() if gate_sig_override_active else ""
    dm_get_override_active = legacy_dm_get_override_active()
    dm_get_override_until = legacy_dm_get_override_until() if dm_get_override_active else ""
    compat_invite_override_active = compat_dm_invite_import_override_active()
    compat_invite_override_until = (
        compat_dm_invite_import_override_until() if compat_invite_override_active else ""
    )
    dm1_override_active = legacy_dm1_override_active()
    dm1_override_until = legacy_dm1_override_until() if dm1_override_active else ""
    return {
        "sunset": {
            "legacy_node_id_binding": _sunset_target(
                LEGACY_NODE_ID_BINDING_TARGET,
                blocked=node_blocked,
                unblocked_status="migration_override",
                override_until=node_override_until,
            ),
            "legacy_agent_id_lookup": _sunset_target(
                LEGACY_AGENT_ID_LOOKUP_TARGET,
                blocked=lookup_blocked,
                unblocked_status="dev_migration_override",
                override_until=lookup_override_until,
            ),
            "legacy_dm_signature_compat": _sunset_target(
                LEGACY_DM_SIGNATURE_COMPAT_TARGET,
                blocked=not dm_sig_override_active,
                unblocked_status="dev_migration_override",
                override_until=dm_sig_override_until,
            ),
            "legacy_gate_signature_compat": _sunset_target(
                LEGACY_GATE_SIGNATURE_COMPAT_TARGET,
                blocked=not gate_sig_override_active,
                unblocked_status="dev_migration_override",
                override_until=gate_sig_override_until,
            ),
            "legacy_dm_get": _sunset_target(
                LEGACY_DM_GET_TARGET,
                blocked=not dm_get_override_active,
                unblocked_status="dev_migration_override",
                override_until=dm_get_override_until,
            ),
            "compat_dm_invite_import": _sunset_target(
                COMPAT_DM_INVITE_IMPORT_TARGET,
                blocked=not compat_invite_override_active,
                unblocked_status="dev_migration_override",
                override_until=compat_invite_override_until,
            ),
            "legacy_dm1": _sunset_target(
                LEGACY_DM1_TARGET,
                blocked=not dm1_override_active,
                unblocked_status="dev_migration_override",
                override_until=dm1_override_until,
            ),
        },
        "usage": _read_usage(),
        "dev_legacy_compat_override_enabled": _dev_legacy_compat_override_enabled(),
    }
