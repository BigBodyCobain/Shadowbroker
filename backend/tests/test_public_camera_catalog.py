from unittest.mock import patch
from fastapi.testclient import TestClient


def test_public_live_data_contains_cameras_without_operator_login():
    from main import app
    camera = {"id": "public-camera", "lat": 39.74, "lon": -104.99, "media_url": "https://example.com/camera.jpg", "media_type": "image"}
    with patch("services.fetchers._store.get_latest_data_subset_refs", return_value={"cctv": [camera]}), patch("services.fetchers._store.effective_layers", return_value={"cctv": True}):
        client = TestClient(app)
        try:
            response = client.get("/api/live-data/fast")
        finally:
            client.close()
    assert response.status_code == 200
    assert response.json()["cctv"] == [camera]
    assert response.json()["cctv_total"] == 1
