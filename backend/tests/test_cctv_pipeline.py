"""Regression tests for CCTV ingestion and persistence."""

import threading

from services import cctv_pipeline


class DummyIngestor(cctv_pipeline.BaseCCTVIngestor):
    def __init__(self, cameras):
        self._cameras = cameras

    def fetch_data(self):
        return self._cameras


def test_ingestor_can_run_from_another_thread(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "cctv.db"
    monkeypatch.setattr(cctv_pipeline, "DB_PATH", db_path)

    ingestor = DummyIngestor(
        [
            {
                "id": "cam-1",
                "source_agency": "Test",
                "lat": 51.5,
                "lon": -0.12,
                "direction_facing": "North",
                "media_url": "https://example.com/camera.jpg",
                "refresh_rate_seconds": 30,
            }
        ]
    )

    thread = threading.Thread(target=ingestor.ingest)
    thread.start()
    thread.join()

    cameras = cctv_pipeline.get_all_cameras()
    assert len(cameras) == 1
    assert cameras[0]["id"] == "cam-1"
    assert cameras[0]["media_type"] == "image"


def test_ingest_updates_existing_rows_in_persistent_data_dir(tmp_path, monkeypatch):
    db_path = tmp_path / "persistent" / "cctv.db"
    monkeypatch.setattr(cctv_pipeline, "DB_PATH", db_path)

    DummyIngestor(
        [
            {
                "id": "cam-2",
                "source_agency": "Test",
                "lat": 40.71,
                "lon": -74.0,
                "direction_facing": "East",
                "media_url": "https://example.com/old.jpg",
                "refresh_rate_seconds": 60,
            }
        ]
    ).ingest()
    DummyIngestor(
        [
            {
                "id": "cam-2",
                "source_agency": "Test",
                "lat": 40.71,
                "lon": -74.0,
                "direction_facing": "East",
                "media_url": "https://example.com/live.m3u8",
                "refresh_rate_seconds": 60,
            }
        ]
    ).ingest()

    cameras = cctv_pipeline.get_all_cameras()
    assert db_path.exists()
    assert len(cameras) == 1
    assert cameras[0]["media_url"] == "https://example.com/live.m3u8"
    assert cameras[0]["media_type"] == "hls"


def test_scheduled_cctv_ingestors_include_asfinag_and_alpr():
    names = {ing.__class__.__name__ for ing, _ in cctv_pipeline.scheduled_cctv_ingestors()}
    assert "AsfinagIngestor" in names
    assert "OSMALPRCameraIngestor" in names
    assert "OSMTrafficCameraIngestor" in names
    assert "Ontario511Ingestor" in names
    assert "Alberta511Ingestor" in names
    assert "Florida511Ingestor" in names
    assert "AustraliaLiveTrafficIngestor" in names
    assert "NetherlandsRWSIngestor" in names
    assert len(names) == 21


def test_fetch_traveliq_v2_cameras_parses_views(monkeypatch):
    class FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return [
                {
                    "Id": 9,
                    "Latitude": 45.0,
                    "Longitude": -75.0,
                    "Location": "Test Highway",
                    "Views": [
                        {
                            "Id": 42,
                            "Url": "/map/Cctv/42",
                            "Status": "Enabled",
                            "Description": "Northbound",
                        }
                    ],
                }
            ]

    monkeypatch.setattr(cctv_pipeline, "fetch_with_curl", lambda *a, **k: FakeResp())
    cameras = cctv_pipeline._fetch_traveliq_v2_cameras(
        api_url="https://511on.ca/api/v2/get/cameras",
        base_url="https://511on.ca",
        id_prefix="ON511",
        source_agency="511 Ontario",
    )
    assert len(cameras) == 1
    assert cameras[0]["id"] == "ON511-9-42"
    assert cameras[0]["media_url"] == "https://511on.ca/map/Cctv/42"


def test_ensure_https_upgrades_http_media_urls():
    assert (
        cctv_pipeline._ensure_https_url("http://example.com/camera.jpg")
        == "https://example.com/camera.jpg"
    )
    assert (
        cctv_pipeline._ensure_https_url("https://secure.example.com/live.m3u8")
        == "https://secure.example.com/live.m3u8"
    )
