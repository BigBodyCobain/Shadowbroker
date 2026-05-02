"""S8A RNS Cover Traffic Normalization.

Tests:
- Default cover size is at least 512 bytes (DM minimum bucket floor)
- _cover_interval() does not expand based on queued real traffic
- Generated cover traffic still respects MESH_RNS_MAX_PAYLOAD
- Cover-loop jitter stays within the intended 0.7..1.3 window
- Does not claim full indistinguishability — only size/rate normalization
"""

import json

from services.config import Settings
from services.mesh.mesh_rns import RNSBridge


def _make_bridge() -> RNSBridge:
    return RNSBridge()


# ── Default cover size >= 512 ───────────────────────────────────────────


def test_default_cover_size_at_least_512():
    """Default MESH_RNS_COVER_SIZE must be >= 512 to match DM bucket floor."""
    s = Settings()
    assert s.MESH_RNS_COVER_SIZE >= 512


def test_default_cover_size_exactly_512():
    """Verify the default is exactly 512 (the DM minimum bucket size)."""
    s = Settings()
    assert s.MESH_RNS_COVER_SIZE == 512


# ── Cover interval does not expand on queue activity ────────────────────


def test_cover_interval_ignores_batch_queue(monkeypatch):
    """_cover_interval() must not increase when _batch_queue has items."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_INTERVAL_S=30),
    )
    # Force high-privacy so interval is not zero.
    monkeypatch.setattr(bridge, "_is_high_privacy", lambda: True)

    baseline = bridge._cover_interval()

    # Simulate queued real traffic.
    bridge._batch_queue = [{"fake": i} for i in range(30)]
    with_queue = bridge._cover_interval()

    assert with_queue == baseline, (
        f"cover interval expanded from {baseline} to {with_queue} with queued traffic"
    )


def test_cover_interval_stable_at_various_queue_depths(monkeypatch):
    """Cover interval must be constant regardless of queue depth."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_INTERVAL_S=20),
    )
    monkeypatch.setattr(bridge, "_is_high_privacy", lambda: True)

    baseline = bridge._cover_interval()
    for depth in [1, 5, 10, 25, 50, 100]:
        bridge._batch_queue = [{"fake": i} for i in range(depth)]
        assert bridge._cover_interval() == baseline


def test_cover_lambda_matches_recorded_curve(monkeypatch):
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_INTERVAL_S=30),
    )

    bridge._active_peers = ["peer-1"]
    assert bridge._cover_lambda_per_minute() == 1.0

    bridge._active_peers = [f"peer-{index}" for index in range(10)]
    assert bridge._cover_lambda_per_minute() == 4.0

    bridge._active_peers = [f"peer-{index}" for index in range(100)]
    assert bridge._cover_lambda_per_minute() == 6.0


def test_cover_interval_disabled_when_interval_nonpositive(monkeypatch):
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_INTERVAL_S=0),
    )
    monkeypatch.setattr(bridge, "_is_high_privacy", lambda: True)

    assert bridge._cover_lambda_per_minute() == 0.0
    assert bridge._cover_interval() == 0.0


# ── Cover respects MAX_PAYLOAD ──────────────────────────────────────────


def test_cover_size_clamped_to_max_payload(monkeypatch):
    """If MESH_RNS_COVER_SIZE exceeds MAX_PAYLOAD, the on-wire cover fits."""
    bridge = _make_bridge()
    # Set cover size larger than max payload.
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_SIZE=99999, MESH_RNS_MAX_PAYLOAD=4096),
    )

    sent_payloads: list[bytes] = []

    def fake_send(peer, data):
        sent_payloads.append(data)

    def fake_pick():
        return "fake_peer_hash"

    monkeypatch.setattr(bridge, "_send_to_peer", fake_send)
    monkeypatch.setattr(bridge, "_pick_stem_peer", fake_pick)

    bridge._send_cover_traffic()

    # The implementation reserves headroom before bucket selection so the
    # final encoded message still fits within MAX_PAYLOAD on the wire.
    assert len(sent_payloads) == 1
    assert len(sent_payloads[0]) <= 4096


def test_cover_sent_when_size_fits_max_payload(monkeypatch):
    """Cover traffic is sent when the encoded message fits within MAX_PAYLOAD."""
    bridge = _make_bridge()
    # 512-byte payload + base64 + envelope < 8192
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_SIZE=512, MESH_RNS_MAX_PAYLOAD=8192),
    )

    sent_payloads: list[bytes] = []

    def fake_send(peer, data):
        sent_payloads.append(data)

    def fake_pick():
        return "fake_peer_hash"

    monkeypatch.setattr(bridge, "_send_to_peer", fake_send)
    monkeypatch.setattr(bridge, "_pick_stem_peer", fake_pick)

    bridge._send_cover_traffic()

    assert len(sent_payloads) == 1
    assert len(sent_payloads[0]) <= 8192


def test_cover_default_size_under_max_payload():
    """Default cover size (512) must be well under default MAX_PAYLOAD (8192)."""
    s = Settings()
    assert s.MESH_RNS_COVER_SIZE <= s.MESH_RNS_MAX_PAYLOAD


def test_cover_loop_uses_poisson_delay_from_recorded_mean(monkeypatch):
    bridge = _make_bridge()
    monkeypatch.setattr(bridge, "enabled", lambda: True)
    monkeypatch.setattr(bridge, "_is_high_privacy", lambda: True)
    monkeypatch.setattr(bridge, "_cover_interval", lambda: 20.0)

    send_calls = {"count": 0}
    sleep_calls: list[float] = []

    def fake_send_cover():
        send_calls["count"] += 1

    def fake_sleep(delay: float):
        sleep_calls.append(delay)
        raise SystemExit("stop-cover-loop")

    monkeypatch.setattr(bridge, "_send_cover_traffic", fake_send_cover)
    monkeypatch.setattr("random.expovariate", lambda rate: 26.0)
    monkeypatch.setattr("services.mesh.mesh_rns.time.sleep", fake_sleep)

    try:
        bridge._cover_loop()
    except SystemExit as exc:
        assert str(exc) == "stop-cover-loop"

    assert send_calls["count"] == 1
    assert sleep_calls == [26.0]


def test_cover_auth_marker_flag_off_preserves_private_dm_shape_without_transport_auth(monkeypatch):
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(
            MESH_RNS_COVER_SIZE=512,
            MESH_RNS_MAX_PAYLOAD=8192,
            MESH_RNS_COVER_AUTH_MARKER_ENABLE=False,
        ),
    )

    sent_payloads: list[bytes] = []
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: "fake-peer")
    monkeypatch.setattr(bridge, "_send_to_peer", lambda _peer, payload: sent_payloads.append(payload) or True)

    bridge._send_cover_traffic()

    msg = json.loads(sent_payloads[0])
    assert "transport_auth" not in msg["body"]["envelope"]
