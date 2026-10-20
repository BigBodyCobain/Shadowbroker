"""Live-data payload helpers — no telemetry sampling; bbox densify only."""
from __future__ import annotations


def test_sample_items_even_stride():
    from routers.data import _sample_items

    items = [{"id": i} for i in range(100)]
    sampled = _sample_items(items, 10)
    assert len(sampled) == 10
    assert sampled[0]["id"] == 0
    assert sampled[-1]["id"] == 90


def test_world_zoom_does_not_sample_telemetry():
    from routers.data import _cap_fast_dashboard_payload

    flights = [{"lat": 0.0, "lng": float(i), "id": f"f-{i}"} for i in range(2000)]
    cctv = [{"lat": 0.0, "lon": float(i % 180), "id": f"c-{i}"} for i in range(900)]
    payload = {
        "commercial_flights": flights,
        "ships": [{"lat": 1.0, "lng": 1.0, "id": "s1"}],
        "cctv": cctv,
        "cctv_total": 900,
        "satellites": [{"lat": -10.0, "lng": 10.0, "id": "sat"}],
    }
    out = _cap_fast_dashboard_payload(payload)
    assert out["payload_scale"] == "world"
    assert "payload_sampled" not in out
    assert len(out["commercial_flights"]) == 2000
    assert len(out["cctv"]) == 900
    assert out["cctv_total"] == 900
    assert len(out["satellites"]) == 1


def test_regional_zoom_annotates_scale_without_sampling():
    from routers.data import _cap_fast_dashboard_payload

    flights = [{"lat": 35.0, "lng": -75.0, "id": f"f-{i}"} for i in range(1500)]
    out = _cap_fast_dashboard_payload(
        {"commercial_flights": flights},
        s=30,
        w=-80,
        n=40,
        e=-70,
    )
    assert out["payload_scale"] == "regional"
    assert "payload_sampled" not in out
    assert len(out["commercial_flights"]) == 1500


def test_bbox_filter_respects_lon_alias():
    from routers.data import _bbox_filter

    items = [
        {"id": "in", "lat": 35.0, "lon": -75.0},
        {"id": "out", "lat": 35.0, "lon": 100.0},
    ]
    filtered = _bbox_filter(items, 30, -80, 40, -70)
    assert {c["id"] for c in filtered} == {"in"}


def test_get_all_cameras_column_subset(tmp_path, monkeypatch):
    import sqlite3

    from services import cctv_pipeline

    db = tmp_path / "cctv.db"
    monkeypatch.setattr(cctv_pipeline, "DB_PATH", db)
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE cameras (
            id TEXT PRIMARY KEY,
            source_agency TEXT,
            lat REAL,
            lon REAL,
            direction_facing TEXT,
            media_url TEXT,
            media_type TEXT,
            refresh_rate_seconds INTEGER,
            last_updated TIMESTAMP,
            secret_extra TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO cameras VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("cam-1", "dot", 35.0, -75.0, "N", "https://example.com/a.jpg", "image", 60, None, "nope"),
    )
    conn.execute(
        "INSERT INTO cameras VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("cam-2", "dot", 10.0, 10.0, "S", "https://example.com/b.jpg", "image", 60, None, "nope"),
    )
    conn.commit()
    conn.close()

    all_cams = cctv_pipeline.get_all_cameras()
    assert len(all_cams) == 2
    assert "secret_extra" not in all_cams[0]
    assert set(all_cams[0].keys()) <= set(cctv_pipeline._CAMERA_SELECT_COLS)

    # Viewport args are ignored — full catalog always.
    boxed = cctv_pipeline.get_all_cameras(south=30, west=-80, north=40, east=-70)
    assert {c["id"] for c in boxed} == {"cam-1", "cam-2"}
    assert cctv_pipeline.get_camera_count() == 2


def test_live_data_fast_world_keeps_full_telemetry(client, monkeypatch):
    from services.fetchers import _store
    from routers import data as data_router

    with data_router._LIVE_DATA_BYTES_CACHE_LOCK:
        data_router._LIVE_DATA_BYTES_CACHE.clear()
    _store.bump_data_version()

    flights = [{"lat": 0.0, "lng": float(i % 170), "id": f"f-{i}"} for i in range(1500)]
    monkeypatch.setitem(_store.latest_data, "commercial_flights", flights)
    monkeypatch.setitem(_store.active_layers, "flights", True)

    r = client.get("/api/live-data/fast")
    assert r.status_code == 200
    data = r.json()
    assert data.get("payload_scale") == "world"
    assert "payload_sampled" not in data
    assert len(data["commercial_flights"]) == 1500
