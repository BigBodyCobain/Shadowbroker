import time

import pytest


@pytest.fixture(autouse=True)
def _clear_settings_and_revocation_cache():
    from services.config import get_settings
    from services.mesh import mesh_metrics, mesh_signed_events

    get_settings.cache_clear()
    mesh_metrics.reset()
    mesh_signed_events._reset_revocation_ttl_cache()
    yield
    get_settings.cache_clear()
    mesh_metrics.reset()
    mesh_signed_events._reset_revocation_ttl_cache()


def test_revocation_cache_uses_fresh_entries_and_refreshes_stale(monkeypatch):
    from services.mesh import mesh_hashchain, mesh_signed_events

    rebuilds = {"count": 0}

    def _rebuild():
        rebuilds["count"] += 1

    monkeypatch.setattr(mesh_hashchain.infonet, "_rebuild_revocations", _rebuild)
    monkeypatch.setattr(
        mesh_hashchain.infonet,
        "_revocation_status",
        lambda _key: (
            rebuilds["count"] >= 2,
            {"event_id": "evt-2"} if rebuilds["count"] >= 2 else None,
        ),
    )

    first = mesh_signed_events._revocation_status_with_ttl("pub-a")
    second = mesh_signed_events._revocation_status_with_ttl("pub-a")
    mesh_signed_events._REVOCATION_TTL_CACHE["pub-a"]["checked_at"] = time.time() - 1000.0
    third = mesh_signed_events._revocation_status_with_ttl("pub-a")

    assert first == (False, None)
    assert second == (False, None)
    assert third[0] is True
    assert rebuilds["count"] == 2


def test_preflight_allows_refresh_failures_in_observe_mode(monkeypatch):
    from services.mesh import mesh_hashchain, mesh_metrics, mesh_signed_events

    monkeypatch.setenv("MESH_SIGNED_REVOCATION_CACHE_ENFORCE", "false")
    monkeypatch.setattr(mesh_hashchain.infonet, "_rebuild_revocations", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(mesh_hashchain.infonet, "check_replay", lambda *_args, **_kwargs: False)
    mesh_hashchain.infonet.node_sequences.clear()
    mesh_hashchain.infonet.public_key_bindings.clear()

    ok, reason = mesh_signed_events.preflight_signed_event_integrity(
        event_type="message",
        node_id="node-a",
        sequence=7,
        public_key="pub-a",
        public_key_algo="Ed25519",
        signature="sig",
        protocol_version=mesh_signed_events.PROTOCOL_VERSION,
    )

    assert ok is True
    assert reason == "ok"
    snapshot = mesh_metrics.snapshot()
    assert snapshot["counters"]["revocation_refresh_attempts"] == 1
    assert snapshot["counters"]["revocation_refresh_failures"] == 1
    assert snapshot["counters"]["revocation_refresh_fail_open"] == 1
    assert snapshot["counters"].get("revocation_refresh_fail_closed", 0) == 0


def test_preflight_fails_closed_when_refresh_enforcement_is_enabled(monkeypatch):
    from services.mesh import mesh_hashchain, mesh_metrics, mesh_signed_events

    monkeypatch.setenv("MESH_SIGNED_REVOCATION_CACHE_ENFORCE", "true")
    monkeypatch.setattr(mesh_hashchain.infonet, "_rebuild_revocations", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(mesh_hashchain.infonet, "check_replay", lambda *_args, **_kwargs: False)
    mesh_hashchain.infonet.node_sequences.clear()
    mesh_hashchain.infonet.public_key_bindings.clear()

    ok, reason = mesh_signed_events.preflight_signed_event_integrity(
        event_type="message",
        node_id="node-a",
        sequence=7,
        public_key="pub-a",
        public_key_algo="Ed25519",
        signature="sig",
        protocol_version=mesh_signed_events.PROTOCOL_VERSION,
    )

    assert ok is False
    assert reason == "Signed event integrity preflight unavailable"
    snapshot = mesh_metrics.snapshot()
    assert snapshot["counters"]["revocation_refresh_attempts"] == 1
    assert snapshot["counters"]["revocation_refresh_failures"] == 1
    assert snapshot["counters"]["revocation_refresh_fail_closed"] == 1
    assert snapshot["counters"].get("revocation_refresh_fail_open", 0) == 0


def test_revocation_cache_fail_fast_window_skips_repeat_refresh_when_enforcing(monkeypatch):
    from services.mesh import mesh_hashchain, mesh_metrics, mesh_signed_events

    monkeypatch.setenv("MESH_SIGNED_REVOCATION_CACHE_ENFORCE", "true")
    rebuilds = {"count": 0}

    def _rebuild():
        rebuilds["count"] += 1
        raise RuntimeError("offline")

    monkeypatch.setattr(mesh_hashchain.infonet, "_rebuild_revocations", _rebuild)

    with pytest.raises(mesh_signed_events._RevocationRefreshUnavailable):
        mesh_signed_events._revocation_status_with_ttl("pub-a")
    with pytest.raises(mesh_signed_events._RevocationRefreshUnavailable):
        mesh_signed_events._revocation_status_with_ttl("pub-a")

    snapshot = mesh_metrics.snapshot()
    assert rebuilds["count"] == 1
    assert snapshot["counters"]["revocation_refresh_attempts"] == 1
    assert snapshot["counters"]["revocation_refresh_failures"] == 1
    assert snapshot["counters"]["revocation_refresh_fail_closed"] == 1
    assert snapshot["counters"]["revocation_refresh_waits"] == 1
