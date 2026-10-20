"""Integration: layer enable triggers immediate data availability."""
from __future__ import annotations

import time

from services.fetchers._store import active_layers, latest_data, _data_lock


def test_firms_enable_populates_slow_payload(client):
    with _data_lock:
        active_layers["firms"] = False
        latest_data["firms_fires"] = []

    r = client.post("/api/layers", json={"layers": {"firms": True}})
    assert r.status_code == 200

    fires: list = []
    for _ in range(45):
        slow = client.get("/api/live-data/slow")
        assert slow.status_code == 200
        fires = slow.json().get("firms_fires") or []
        if fires:
            break
        time.sleep(2)

    assert len(fires) > 0, "firms layer should populate after async on-enable fetch"
