import json

import pytest

from services import fetch_health
from services.fetch_health import (
    get_agent_health_snapshot,
    get_health_snapshot,
    record_failure,
    record_success,
)


@pytest.fixture(autouse=True)
def clear_fetch_health():
    with fetch_health._lock:
        fetch_health._health.clear()
    yield
    with fetch_health._lock:
        fetch_health._health.clear()


def test_record_success_and_failure():
    record_success("unit_test_source", duration_s=0.1, count=3)
    record_failure("unit_test_source", error=Exception("boom"), duration_s=0.2)

    snap = get_health_snapshot()
    assert "unit_test_source" in snap
    entry = snap["unit_test_source"]
    assert entry["ok_count"] >= 1
    assert entry["error_count"] >= 1
    assert entry["last_ok"] is not None
    assert entry["last_error"] is not None
    assert entry["last_duration_ms"] is not None


def test_agent_health_snapshot_is_sanitized():
    fake_secret = "RECOGNIZABLE_FAKE_SECRET_FOR_FETCH_HEALTH"
    entry = {
        "ok_count": 3,
        "error_count": 2,
        "last_ok": "2026-07-30T12:00:00.000000",
        "last_error": "2026-07-30T11:00:00.000000",
        "last_error_msg": f"upstream failed with {fake_secret}",
        "last_duration_ms": 125.4,
        "avg_duration_ms": 98.7,
        "last_count": 42,
    }
    with fetch_health._lock:
        fetch_health._health["latest_success"] = dict(entry)
        fetch_health._health["latest_failure"] = {
            **entry,
            "last_ok": "2026-07-30T10:00:00.000000",
            "last_error": "2026-07-30T13:00:00.000000",
        }

    snapshot = get_agent_health_snapshot()

    assert {key: value for key, value in snapshot.items() if key != "tasks"} == {
        "scope": "process",
        "persistent": False,
        "observed_only": True,
        "semantics": "latest_recorded_task_outcome",
    }
    safe_fields = {
        "condition",
        "ok_count",
        "error_count",
        "last_ok",
        "last_error",
        "last_duration_ms",
    }
    assert set(snapshot["tasks"]["latest_success"]) == safe_fields
    assert snapshot["tasks"]["latest_success"]["condition"] == "healthy"
    assert snapshot["tasks"]["latest_failure"]["condition"] == "degraded"
    serialized = json.dumps(snapshot)
    assert "last_error_msg" not in serialized
    assert fake_secret not in serialized
