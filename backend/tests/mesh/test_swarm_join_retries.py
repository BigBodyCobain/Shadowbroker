from services.mesh import mesh_swarm_runtime as swarm


def test_join_swarm_with_retries_succeeds_on_second_attempt(monkeypatch):
    calls = {"n": 0}

    def fake_announce(*, force=True):
        calls["n"] += 1
        if calls["n"] < 2:
            return {"ok": False, "results": [{"ok": False, "status_code": 503}]}
        return {"ok": True, "results": [{"ok": True, "status_code": 200}]}

    def fake_manifest(*, force=True, now=None):
        if calls["n"] < 2:
            return {"ok": False, "detail": "manifest fetch failed"}
        return {"ok": True, "peer_count": 3, "merged_peer_count": 3}

    monkeypatch.setattr(swarm, "announce_local_peer_to_seeds", fake_announce)
    monkeypatch.setattr(swarm, "refresh_swarm_manifest_from_seeds", fake_manifest)
    monkeypatch.setattr(swarm.time, "sleep", lambda _s: None)

    joined = swarm.join_swarm_with_retries(attempts=3, delay_s=1.0)

    assert joined["ok"] is True
    assert joined["attempts"] == 2
