"""P2 live-data delta + P8 hashchain memory + P12 mesh-only import guards."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


def test_compute_layer_row_delta_upsert_and_delete(monkeypatch):
    from services.fetchers import _store

    monkeypatch.setitem(_store.latest_data, "ships", [
        {"mmsi": "1", "lat": 1.0, "lng": 1.0},
        {"mmsi": "2", "lat": 2.0, "lng": 2.0},
    ])
    _store._LAYER_ID_RING.clear()
    with _store._data_lock:
        _store._layer_versions["ships"] = 1
        _store._record_delta_layer_snapshot_locked("ships")

    monkeypatch.setitem(_store.latest_data, "ships", [
        {"mmsi": "1", "lat": 1.5, "lng": 1.0},  # moved
        {"mmsi": "3", "lat": 3.0, "lng": 3.0},  # new
    ])
    with _store._data_lock:
        _store._layer_versions["ships"] = 2
        _store._record_delta_layer_snapshot_locked("ships")

    delta = _store.compute_layer_row_delta("ships", 1)
    assert delta is not None
    assert {u["mmsi"] for u in delta["upsert"]} == {"1", "3"}
    assert delta["delete"] == ["2"]
    assert delta["version"] == 2


def test_compute_layer_row_delta_returns_none_when_base_missing():
    from services.fetchers import _store

    _store._LAYER_ID_RING.clear()
    with _store._data_lock:
        _store._layer_versions["ships"] = 5
    # Client holds an older version that is no longer in the ring.
    assert _store.compute_layer_row_delta("ships", 1) is None


def test_live_data_fast_delta_mode(client, monkeypatch):
    from services.fetchers import _store

    ships_v1 = [
        {"mmsi": "10", "lat": 10.0, "lng": 10.0},
        {"mmsi": "20", "lat": 20.0, "lng": 20.0},
    ]
    monkeypatch.setitem(_store.latest_data, "ships", ships_v1)
    monkeypatch.setitem(_store.active_layers, "ships_military", True)
    _store._LAYER_ID_RING.clear()
    with _store._data_lock:
        _store._layer_versions["ships"] = 1
        for key in (
            "commercial_flights",
            "military_flights",
            "tracked_flights",
            "private_flights",
            "private_jets",
            "cctv",
            "uavs",
            "liveuamap",
            "gps_jamming",
            "satellites",
            "sigint",
            "trains",
        ):
            _store._layer_versions.setdefault(key, 1)
        _store._record_delta_layer_snapshot_locked("ships")
        for key in (
            "commercial_flights",
            "military_flights",
            "tracked_flights",
            "private_flights",
            "private_jets",
        ):
            monkeypatch.setitem(_store.latest_data, key, [])
            _store._record_delta_layer_snapshot_locked(key)

    # Advance ships
    monkeypatch.setitem(
        _store.latest_data,
        "ships",
        [
            {"mmsi": "10", "lat": 10.5, "lng": 10.0},
            {"mmsi": "30", "lat": 30.0, "lng": 30.0},
        ],
    )
    with _store._data_lock:
        _store._layer_versions["ships"] = 2
        _store._record_delta_layer_snapshot_locked("ships")

    lv = (
        "ships:1,commercial_flights:1,military_flights:1,tracked_flights:1,"
        "private_flights:1,private_jets:1,cctv:1,uavs:1,liveuamap:1,"
        "gps_jamming:1,satellites:1,sigint:1,trains:1"
    )
    r = client.get(f"/api/live-data/fast?lv={lv}")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "delta"
    assert "ships" in data["deltas"]
    assert {u["mmsi"] for u in data["deltas"]["ships"]["upsert"]} == {"10", "30"}
    assert data["deltas"]["ships"]["delete"] == ["20"]


def test_hashchain_flush_uses_orjson_compact(tmp_path, monkeypatch):
    from services.mesh import mesh_hashchain as hc

    monkeypatch.setattr(hc, "DATA_DIR", tmp_path)
    monkeypatch.setattr(hc, "CHAIN_FILE", tmp_path / "infonet.json")
    monkeypatch.setattr(hc, "WAL_FILE", tmp_path / "infonet.wal")
    monkeypatch.setattr(hc, "CHAIN_COLD_DIR", tmp_path / "infonet_cold")
    monkeypatch.setattr(hc, "MAX_CHAIN_MEMORY", 3)

    net = hc.Infonet()
    net.events = [{"event_id": f"e{i}", "event_type": "message", "payload": {}} for i in range(5)]
    net.head_hash = "e4"
    net._dirty = True
    net._enforce_memory_cap()
    net._flush()

    raw = (tmp_path / "infonet.json").read_bytes()
    assert b"\n  " not in raw  # compact, not indent=2
    data = json.loads(raw)
    assert len(data["events"]) == 3
    assert data["cold_segments"]
    cold_file = tmp_path / "infonet_cold" / data["cold_segments"][0]["filename"]
    assert cold_file.exists()
    cold = json.loads(cold_file.read_bytes())
    assert len(cold) == 2


def test_mesh_only_skips_osint_router_modules():
    """Source-level guard: MESH_ONLY branch must not load routers.data at import."""
    import inspect
    from pathlib import Path

    src = Path("backend/main.py").read_text(encoding="utf-8")
    assert "if _MESH_ONLY:" in src
    assert 'data_router = APIRouter()' in src
    assert "from services.data_fetcher import" in src
    # data_fetcher import is gated
    assert "if not _MESH_ONLY:" in src
