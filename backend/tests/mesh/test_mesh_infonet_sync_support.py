from services.mesh.mesh_infonet_sync_support import (
    SyncWorkerState,
    begin_sync,
    eligible_sync_peers,
    finish_sync,
    finish_solo_sync,
    should_run_sync,
)
from services.mesh.mesh_peer_store import make_bootstrap_peer_record, make_sync_peer_record


def test_eligible_sync_peers_filters_bucket_and_cooldown():
    records = [
        make_bootstrap_peer_record(
            peer_url="https://seed.example",
            transport="clearnet",
            role="seed",
            signer_id="bootstrap-a",
            now=100,
        ),
        make_sync_peer_record(
            peer_url="https://active.example",
            transport="clearnet",
            now=100,
        ),
        make_sync_peer_record(
            peer_url="https://cooldown.example",
            transport="clearnet",
            now=100,
        ),
    ]
    cooled = records[2]
    records[2] = type(cooled)(**{**cooled.to_dict(), "cooldown_until": 500})

    candidates = eligible_sync_peers(records, now=200)

    assert [record.peer_url for record in candidates] == ["https://active.example"]


def test_finish_sync_success_updates_schedule():
    state = begin_sync(SyncWorkerState(), peer_url="https://seed.example", now=100)
    finished = finish_sync(
        state,
        ok=True,
        peer_url="https://seed.example",
        current_head="abc123",
        now=110,
        interval_s=300,
    )

    assert finished.last_outcome == "ok"
    assert finished.last_sync_ok_at == 110
    assert finished.next_sync_due_at == 410
    assert finished.current_head == "abc123"
    assert not finished.fork_detected


def test_finish_sync_failure_surfaces_fork_without_auto_merging():
    state = begin_sync(SyncWorkerState(), peer_url="https://seed.example", now=100)
    finished = finish_sync(
        state,
        ok=False,
        peer_url="https://seed.example",
        error="fork detected",
        fork_detected=True,
        now=120,
        failure_backoff_s=45,
    )

    assert finished.last_outcome == "fork"
    assert finished.fork_detected is True
    assert finished.last_error == "fork detected"
    assert finished.consecutive_failures == 1
    assert finished.next_sync_due_at == 165
    assert should_run_sync(finished, now=150) is False
    assert should_run_sync(finished, now=165) is True


def test_finish_solo_sync_marks_first_node_ready_without_peer_failure():
    state = SyncWorkerState(current_head="genesis")
    finished = finish_solo_sync(
        state,
        current_head="abc123",
        now=200,
        interval_s=300,
    )

    assert finished.last_outcome == "solo"
    assert finished.last_error == ""
    assert finished.last_peer_url == ""
    assert finished.current_head == "abc123"
    assert finished.consecutive_failures == 0
    assert finished.next_sync_due_at == 500
    assert should_run_sync(finished, now=499) is False
    assert should_run_sync(finished, now=500) is True
