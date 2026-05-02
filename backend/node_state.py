"""node_state.py — Shared mutable node runtime state and node helper functions.

Extracted from main.py so that background worker functions and route handlers
can reference the same state objects without importing the full application.

_NODE_SYNC_STATE is a reassignable value (SyncWorkerState is replaced whole,
not mutated), so callers must use get_sync_state() / set_sync_state() instead
of binding to the name at import time.

All other _NODE_* objects are mutable containers (Lock, Event, dict) whose
identity never changes; importing them directly by name is safe.
"""

import threading
import time
from typing import Any

from services.mesh.mesh_infonet_sync_support import SyncWorkerState

# ---------------------------------------------------------------------------
# Runtime state objects
# ---------------------------------------------------------------------------

_NODE_RUNTIME_LOCK = threading.RLock()
_NODE_SYNC_STOP = threading.Event()
_NODE_SYNC_STATE = SyncWorkerState()
_NODE_BOOTSTRAP_STATE: dict[str, Any] = {
    "node_mode": "participant",
    "manifest_loaded": False,
    "manifest_signer_id": "",
    "manifest_valid_until": 0,
    "bootstrap_peer_count": 0,
    "sync_peer_count": 0,
    "push_peer_count": 0,
    "operator_peer_count": 0,
    "last_bootstrap_error": "",
}
_NODE_PUSH_STATE: dict[str, Any] = {
    "last_event_id": "",
    "last_push_ok_at": 0,
    "last_push_error": "",
    "last_results": [],
}

# ---------------------------------------------------------------------------
# Getter / setter for _NODE_SYNC_STATE
#
# Use these instead of globals()["_NODE_SYNC_STATE"] = ... in any module that
# imports this package.  The setter modifies *this* module's namespace so
# subsequent get_sync_state() calls see the new value regardless of which
# module calls set_sync_state().
# ---------------------------------------------------------------------------

def get_sync_state() -> SyncWorkerState:
    return _NODE_SYNC_STATE


def set_sync_state(state: SyncWorkerState) -> None:
    global _NODE_SYNC_STATE
    _NODE_SYNC_STATE = state


# ---------------------------------------------------------------------------
# Node helper functions
#
# These were in main.py but are needed by both route handlers and background
# workers, so they live here to avoid circular imports.
# ---------------------------------------------------------------------------

def _current_node_mode() -> str:
    from services.config import get_settings
    mode = str(get_settings().MESH_NODE_MODE or "participant").strip().lower()
    if mode not in {"participant", "relay", "perimeter"}:
        return "participant"
    return mode


def _node_runtime_supported() -> bool:
    return _current_node_mode() in {"participant", "relay"}


def _node_activation_enabled() -> bool:
    from services.node_settings import read_node_settings

    try:
        settings = read_node_settings()
    except Exception:
        return False
    return bool(settings.get("enabled", False))


def _participant_node_enabled() -> bool:
    return _node_runtime_supported() and _node_activation_enabled()


def _node_runtime_snapshot() -> dict[str, Any]:
    with _NODE_RUNTIME_LOCK:
        return {
            "node_mode": _NODE_BOOTSTRAP_STATE.get("node_mode", "participant"),
            "node_enabled": _participant_node_enabled(),
            "bootstrap": dict(_NODE_BOOTSTRAP_STATE),
            "sync_runtime": get_sync_state().to_dict(),
            "push_runtime": dict(_NODE_PUSH_STATE),
        }


def _set_node_sync_disabled_state(*, current_head: str = "") -> SyncWorkerState:
    return SyncWorkerState(
        current_head=str(current_head or ""),
        last_outcome="disabled",
    )


def _set_participant_node_enabled(enabled: bool) -> dict[str, Any]:
    from services.mesh.mesh_hashchain import infonet
    from services.node_settings import write_node_settings

    settings = write_node_settings(enabled=bool(enabled))
    current_head = str(infonet.head_hash or "")
    with _NODE_RUNTIME_LOCK:
        _NODE_BOOTSTRAP_STATE["node_mode"] = _current_node_mode()
        set_sync_state(
            SyncWorkerState(current_head=current_head)
            if bool(enabled) and _node_runtime_supported()
            else _set_node_sync_disabled_state(current_head=current_head)
        )
    return {
        **settings,
        "node_mode": _current_node_mode(),
        "node_enabled": _participant_node_enabled(),
    }


def _refresh_node_peer_store(*, now: float | None = None) -> dict[str, Any]:
    from services.config import get_settings
    from services.mesh.mesh_bootstrap_manifest import load_bootstrap_manifest_from_settings
    from services.mesh.mesh_peer_store import (
        DEFAULT_PEER_STORE_PATH,
        PeerStore,
        make_bootstrap_peer_record,
        make_push_peer_record,
        make_sync_peer_record,
    )
    from services.mesh.mesh_router import (
        configured_relay_peer_urls,
        parse_configured_relay_peers,
        peer_transport_kind,
    )

    timestamp = int(now if now is not None else time.time())
    mode = _current_node_mode()
    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception:
        store = PeerStore(DEFAULT_PEER_STORE_PATH)

    operator_peers = configured_relay_peer_urls()
    default_sync_peers = parse_configured_relay_peers(
        str(getattr(get_settings(), "MESH_DEFAULT_SYNC_PEERS", "") or "")
    )
    for peer_url in operator_peers:
        transport = peer_transport_kind(peer_url)
        if not transport:
            continue
        store.upsert(
            make_sync_peer_record(
                peer_url=peer_url,
                transport=transport,
                role="relay",
                source="operator",
                now=timestamp,
            )
        )
        store.upsert(
            make_push_peer_record(
                peer_url=peer_url,
                transport=transport,
                role="relay",
                source="operator",
                now=timestamp,
            )
        )

    operator_peer_set = set(operator_peers)
    for peer_url in default_sync_peers:
        if peer_url in operator_peer_set:
            continue
        transport = peer_transport_kind(peer_url)
        if not transport:
            continue
        store.upsert(
            make_bootstrap_peer_record(
                peer_url=peer_url,
                transport=transport,
                role="seed",
                label="ShadowBroker default seed",
                signer_id="shadowbroker-default",
                now=timestamp,
            )
        )
        store.upsert(
            make_sync_peer_record(
                peer_url=peer_url,
                transport=transport,
                role="seed",
                source="bundle",
                label="ShadowBroker default seed",
                signer_id="shadowbroker-default",
                now=timestamp,
            )
        )

    manifest = None
    bootstrap_error = ""
    try:
        manifest = load_bootstrap_manifest_from_settings(now=timestamp)
    except Exception as exc:
        bootstrap_error = str(exc or "").strip()

    if manifest is not None:
        for peer in manifest.peers:
            store.upsert(
                make_bootstrap_peer_record(
                    peer_url=peer.peer_url,
                    transport=peer.transport,
                    role=peer.role,
                    label=peer.label,
                    signer_id=manifest.signer_id,
                    now=timestamp,
                )
            )
            store.upsert(
                make_sync_peer_record(
                    peer_url=peer.peer_url,
                    transport=peer.transport,
                    role=peer.role,
                    source="bootstrap_promoted",
                    label=peer.label,
                    signer_id=manifest.signer_id,
                    now=timestamp,
                )
            )

    store.save()
    snapshot = {
        "node_mode": mode,
        "manifest_loaded": manifest is not None,
        "manifest_signer_id": manifest.signer_id if manifest is not None else "",
        "manifest_valid_until": int(manifest.valid_until or 0) if manifest is not None else 0,
        "bootstrap_peer_count": len(store.records_for_bucket("bootstrap")),
        "sync_peer_count": len(store.records_for_bucket("sync")),
        "push_peer_count": len(store.records_for_bucket("push")),
        "operator_peer_count": len(operator_peers),
        "default_sync_peer_count": len(default_sync_peers),
        "last_bootstrap_error": bootstrap_error,
    }
    with _NODE_RUNTIME_LOCK:
        _NODE_BOOTSTRAP_STATE.update(snapshot)
    return snapshot


def _materialize_local_infonet_state() -> None:
    from services.mesh.mesh_hashchain import infonet

    infonet.ensure_materialized()
