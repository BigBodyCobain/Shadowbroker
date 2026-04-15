from services.fetch_health import record_success, record_failure, get_health_snapshot


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
