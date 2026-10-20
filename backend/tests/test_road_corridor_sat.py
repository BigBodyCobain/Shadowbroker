"""Tests for opt-in Sentinel-2 road corridor trend layer."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from services.fetchers._store import active_layers, latest_data
from services.fetchers.road_corridor_sat import fetch_road_corridor_trends
from services.road_corridor_sat.presets import get_preset


class TestRoadCorridorGates:
    def test_fetch_skips_when_layer_disabled(self, monkeypatch):
        monkeypatch.setenv("ROAD_CORRIDOR_SAT_ENABLED", "true")
        active_layers["road_corridor_trends"] = False
        with patch("services.road_corridor_sat.pipeline.analyze_preset") as analyze:
            fetch_road_corridor_trends(force=True)
            analyze.assert_not_called()

    def test_fetch_skips_when_feature_disabled(self, monkeypatch):
        active_layers["road_corridor_trends"] = True
        monkeypatch.delenv("ROAD_CORRIDOR_SAT_ENABLED", raising=False)
        with patch("services.road_corridor_sat.pipeline.analyze_preset") as analyze:
            fetch_road_corridor_trends(force=True)
            analyze.assert_not_called()

    def test_fetch_runs_when_enabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ROAD_CORRIDOR_SAT_ENABLED", "true")
        monkeypatch.setenv("SENTINEL_CLIENT_ID", "test-id")
        monkeypatch.setenv("SENTINEL_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("ROAD_CORRIDOR_DATA_DIR", str(tmp_path))
        active_layers["road_corridor_trends"] = True

        fake_result = {
            "preset_id": "laredo_i35",
            "label": "Laredo I-35",
            "status": "ok",
            "daily_counts": [{"date": "2026-05-01", "count": 3}],
            "total_detections": 3,
        }
        with patch("services.road_corridor_sat.config.optional_deps_available", return_value=True):
            with patch(
                "services.road_corridor_sat.pipeline.analyze_preset",
                return_value=fake_result,
            ) as analyze:
                fetch_road_corridor_trends(force=True)
                analyze.assert_called_once_with("laredo_i35")

        assert latest_data["road_corridor_trends"]["corridors"]


class TestAnalyzeHere:
    def test_analyze_requires_credentials(self, monkeypatch):
        from main import app

        monkeypatch.setattr("routers.road_corridors.optional_deps_available", lambda: True)
        monkeypatch.setattr("routers.road_corridors.sentinel_credentials_configured", lambda: False)
        client = TestClient(app)
        resp = client.post(
            "/api/road-corridors/analyze",
            json={"lat": 27.51, "lon": -99.53},
        )
        assert resp.status_code == 503

    def test_analyze_starts_job(self, monkeypatch):
        from main import app

        monkeypatch.setattr("routers.road_corridors.optional_deps_available", lambda: True)
        monkeypatch.setattr("routers.road_corridors.sentinel_credentials_configured", lambda: True)

        def fake_enqueue(lat, lon, label=None):
            from services.road_corridor_sat.jobs import AnalyzeJob

            return AnalyzeJob(job_id="job123", lat=lat, lon=lon, status="queued")

        monkeypatch.setattr("routers.road_corridors.enqueue_analyze", fake_enqueue)
        client = TestClient(app)
        resp = client.post(
            "/api/road-corridors/analyze",
            json={"lat": 27.51, "lon": -99.53},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == "job123"
        assert body["status"] == "queued"


class TestRoadCorridorApi:
    def test_list_presets(self):
        from main import app

        client = TestClient(app)
        resp = client.get("/api/road-corridors")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        ids = {p["id"] for p in body["presets"]}
        assert "laredo_i35" in ids

    def test_get_preset_detail(self):
        from main import app

        client = TestClient(app)
        resp = client.get("/api/road-corridors/laredo_i35")
        assert resp.status_code == 200
        body = resp.json()
        assert body["preset"]["id"] == "laredo_i35"
        assert body["result"]["preset_id"] == "laredo_i35"

    def test_unknown_preset_404(self):
        from main import app

        client = TestClient(app)
        resp = client.get("/api/road-corridors/not-a-real-preset")
        assert resp.status_code == 404


class TestStorage:
    def test_store_analysis_result_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.road_corridor_sat.storage.DATA_ROOT", tmp_path)
        monkeypatch.setattr(
            "services.road_corridor_sat.storage.STATE_PATH",
            tmp_path / "_refresh_state.json",
        )
        from services.road_corridor_sat.storage import load_preset_result, store_analysis_result

        preset = get_preset("laredo_i35")
        assert preset is not None
        store_analysis_result(
            preset["id"],
            label=preset["label"],
            bbox=preset["bbox"],
            country=preset["country"],
            category=preset["category"],
            road_count=4,
            frame_count=2,
            detections=[{"timestamp": "2026-05-01T12:00:00Z", "confidence": 0.9}],
        )
        loaded = load_preset_result("laredo_i35")
        assert loaded is not None
        assert loaded["total_detections"] == 1
        assert loaded["daily_counts"] == [{"date": "2026-05-01", "count": 1}]
        on_disk = json.loads((tmp_path / "laredo_i35.json").read_text(encoding="utf-8"))
        assert on_disk["status"] == "ok"
