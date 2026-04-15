from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from services.mesh.mesh_peer_store import PeerRecord


@dataclass(frozen=True)
class SyncWorkerState:
    last_sync_started_at: int = 0
    last_sync_finished_at: int = 0
    last_sync_ok_at: int = 0
    next_sync_due_at: int = 0
    last_peer_url: str = ""
    last_error: str = ""
    last_outcome: str = "idle"
    current_head: str = ""
    fork_detected: bool = False
    consecutive_failures: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def eligible_sync_peers(records: list[PeerRecord], *, now: float | None = None) -> list[PeerRecord]:
    current_time = int(now if now is not None else time.time())
    candidates = [
        record
        for record in records
        if record.bucket == "sync" and record.enabled and int(record.cooldown_until or 0) <= current_time
    ]
    return sorted(
        candidates,
        key=lambda record: (
            -int(record.last_sync_ok_at or 0),
            int(record.failure_count or 0),
            int(record.added_at or 0),
            record.peer_url,
        ),
    )


def begin_sync(
    state: SyncWorkerState,
    *,
    peer_url: str = "",
    current_head: str = "",
    now: float | None = None,
) -> SyncWorkerState:
    timestamp = int(now if now is not None else time.time())
    return SyncWorkerState(
        last_sync_started_at=timestamp,
        last_sync_finished_at=state.last_sync_finished_at,
        last_sync_ok_at=state.last_sync_ok_at,
        next_sync_due_at=state.next_sync_due_at,
        last_peer_url=peer_url or state.last_peer_url,
        last_error="",
        last_outcome="running",
        current_head=current_head or state.current_head,
        fork_detected=False,
        consecutive_failures=state.consecutive_failures,
    )


def finish_sync(
    state: SyncWorkerState,
    *,
    ok: bool,
    peer_url: str = "",
    current_head: str = "",
    error: str = "",
    fork_detected: bool = False,
    now: float | None = None,
    interval_s: int = 300,
    failure_backoff_s: int = 60,
) -> SyncWorkerState:
    timestamp = int(now if now is not None else time.time())
    if ok:
        return SyncWorkerState(
            last_sync_started_at=state.last_sync_started_at,
            last_sync_finished_at=timestamp,
            last_sync_ok_at=timestamp,
            next_sync_due_at=timestamp + max(0, int(interval_s or 0)),
            last_peer_url=peer_url or state.last_peer_url,
            last_error="",
            last_outcome="ok",
            current_head=current_head or state.current_head,
            fork_detected=bool(fork_detected),
            consecutive_failures=0,
        )

    return SyncWorkerState(
        last_sync_started_at=state.last_sync_started_at,
        last_sync_finished_at=timestamp,
        last_sync_ok_at=state.last_sync_ok_at,
        next_sync_due_at=timestamp + max(0, int(failure_backoff_s or 0)),
        last_peer_url=peer_url or state.last_peer_url,
        last_error=str(error or "").strip(),
        last_outcome="fork" if fork_detected else "error",
        current_head=current_head or state.current_head,
        fork_detected=bool(fork_detected),
        consecutive_failures=state.consecutive_failures + 1,
    )


def should_run_sync(
    state: SyncWorkerState,
    *,
    now: float | None = None,
) -> bool:
    current_time = int(now if now is not None else time.time())
    if state.last_outcome == "running":
        return False
    return int(state.next_sync_due_at or 0) <= current_time
