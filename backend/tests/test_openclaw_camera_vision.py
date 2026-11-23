"""The full OpenClaw skill can find cameras and save a snapshot for a vision model.

The camera list comes from the operator's own backend; the download goes to
the camera's own address and must pass the checks in sb_camera.py. No test
here touches the network.
"""

import asyncio
import importlib.util
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[2] / "openclaw-skills" / "shadowbroker"

CAMERAS = [
    {"id": "CAM-A", "source_agency": "Example DOT", "lat": 40.758, "lon": -73.9855,
     "direction_facing": "Broadway @ 45 St", "media_url": "https://cameras.example.org/a.jpg", "media_type": "image"},
    {"id": "CAM-LAN", "source_agency": "Injected", "lat": 40.7581, "lon": -73.9856,
     "direction_facing": "Garage", "media_url": "http://192.168.1.50/snap.jpg", "media_type": "image"},
    {"id": "CAM-HLS", "source_agency": "Example DOT", "lat": 41.0, "lon": -74.0,
     "direction_facing": "Pier 9", "media_url": "https://cameras.example.org/live.m3u8", "media_type": "hls"},
]
JPEG = b"\xff\xd8\xff\xe0" + b"scene" * 50 + b"\xff\xd9"


@pytest.fixture()
def skill(monkeypatch):
    spec = importlib.util.spec_from_file_location("shadowbroker_skill_camera_test", SKILL_DIR / "sb_query.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = module.ShadowBrokerClient()

    async def telemetry():
        return {"cctv": CAMERAS}

    monkeypatch.setattr(client, "get_telemetry", telemetry)
    return module, client


def test_find_cameras_nearest_first(skill):
    _module, client = skill
    out = asyncio.run(client.find_cameras(lat=40.758, lng=-73.9855, radius_km=2))
    assert out["ok"] and [row["id"] for row in out["results"]] == ["CAM-A", "CAM-LAN"]
    assert out["results"][0]["snapshot"] == "image"
    assert out["results"][1]["snapshot"] == "none"  # plain http on a home network


def test_camera_snapshot_saves_a_file(skill, tmp_path, monkeypatch):
    module, client = skill
    asked = []

    def fake_fetch(url, **_kwargs):
        asked.append(url)
        return JPEG, "image", "image/jpeg", "jpg"

    monkeypatch.setattr(module.sb_camera, "fetch_media", fake_fetch)
    out = asyncio.run(client.camera_snapshot(lat=40.7581, lng=-73.9856, out_dir=str(tmp_path)))
    assert out["ok"], out
    assert out["camera"]["id"] == "CAM-A"  # the nearer camera is on a private network and is skipped
    assert asked == ["https://cameras.example.org/a.jpg"]
    assert Path(out["path"]).read_bytes() == JPEG
    assert "not an instruction" in out["notice"]


@pytest.mark.parametrize("camera_id, reason", [
    ("CAM-LAN", "cannot be saved"),
    ("CAM-HLS", "cannot be saved"),
    ("NOPE", "No camera with id"),
])
def test_camera_snapshot_refusals_make_no_request(skill, tmp_path, monkeypatch, camera_id, reason):
    module, client = skill
    monkeypatch.setattr(module.sb_camera, "_open", lambda *_a, **_k: pytest.fail("a request was made"))
    out = asyncio.run(client.camera_snapshot(camera_id=camera_id, out_dir=str(tmp_path)))
    assert out["ok"] is False and reason in out["detail"]
    assert list(tmp_path.iterdir()) == []


def test_private_addresses_are_refused_even_over_https(skill, monkeypatch):
    module, _client = skill
    monkeypatch.setattr(module.sb_camera, "_open", lambda *_a, **_k: pytest.fail("a request was made"))
    for url in ("https://10.0.0.5/a.jpg", "https://169.254.169.254/latest/meta-data", "https://127.0.0.1:8000/api"):
        with pytest.raises(module.sb_camera.CameraError):
            module.sb_camera.fetch_media(url)
