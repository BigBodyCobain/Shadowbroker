"""Tests for camera search and snapshots in the ShadowBroker public skill.

Run: python -m pytest openclaw-skills/shadowbroker-public -q

A throwaway local web server plays both the feed and the cameras, so no test
touches the internet. The safety rules are tested directly: a camera entry
must never reach a private network, this computer, or anything that is not a
picture.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import sb_camera as cam  # noqa: E402
import sb_public as sp  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"picture-one" * 40 + b"\xff\xd9"
JPEG_TWO = b"\xff\xd8\xff\xe0" + b"picture-two" * 40 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 256


def _stream() -> bytes:
    parts = b""
    for frame in (JPEG, JPEG_TWO):
        parts += b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame) + frame + b"\r\n"
    return parts


class _Handler(http.server.BaseHTTPRequestHandler):
    files: dict[str, bytes] = {}
    hits: list[str] = []

    def log_message(self, *_args):
        pass

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server API
        path = self.path.split("?", 1)[0]
        type(self).hits.append(path)
        if path in self.files:
            return self._send(200, self.files[path], "application/json")
        if path == "/cam/a.jpg":
            return self._send(200, JPEG, "image/jpeg")
        if path == "/cam/b.png":
            return self._send(200, PNG, "application/octet-stream")
        if path == "/cam/clip.mp4":
            return self._send(200, MP4, "video/mp4")
        if path == "/cam/stream":
            return self._send(200, _stream(), "multipart/x-mixed-replace; boundary=frame")
        if path == "/cam/page":
            return self._send(200, b"<html>sign in</html>", "image/jpeg")
        if path == "/cam/gone":
            return self._send(404, b"", "text/plain")
        if path == "/cam/moved":
            return self._send(302, b"", "text/plain", {"Location": "/cam/a.jpg"})
        if path == "/cam/to-lan":
            return self._send(302, b"", "text/plain", {"Location": "https://10.0.0.5/admin.jpg"})
        if path == "/cam/to-http":
            return self._send(302, b"", "text/plain", {"Location": "http://192.168.1.1/snap.jpg"})
        if path == "/cam/loop":
            return self._send(302, b"", "text/plain", {"Location": "/cam/loop"})
        return self._send(404, b"", "text/plain")


@pytest.fixture()
def site(monkeypatch):
    """A local server that is both the feed and the cameras. Yields (base url, camera list)."""
    monkeypatch.setattr(cam, "HOST_GAP_S", 0.0)
    _Handler.hits = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def camera(cid, name, lat, lon, path, media_type="image", source="Example DOT"):
        return {"id": cid, "source_agency": source, "lat": lat, "lon": lon, "direction_facing": name,
                "media_url": f"{base}{path}", "media_type": media_type}

    cameras = [
        camera("CAM-A", "Broadway @ 45 St", 40.7580, -73.9855, "/cam/a.jpg"),
        camera("CAM-B", "Harbor Bridge North", 40.7000, -74.0100, "/cam/b.png"),
        camera("CAM-CLIP", "Archway Rd", 51.5700, -0.1400, "/cam/clip.mp4", "video", "TfL"),
        camera("CAM-STREAM", "Tunnel East", 48.0000, 7.8000, "/cam/stream", "mjpeg"),
        camera("CAM-HLS", "Pier 9", 40.7581, -73.9856, "/cam/live.m3u8", "hls"),
        camera("CAM-PAGE", "Login wall", 10.0, 10.0, "/cam/page"),
        camera("CAM-GONE", "Removed", 11.0, 11.0, "/cam/gone"),
        camera("CAM-MOVED", "Moved", 12.0, 12.0, "/cam/moved"),
        camera("CAM-LAN", "Redirects inward", 13.0, 13.0, "/cam/to-lan"),
        camera("CAM-HTTP", "Redirects to plain http", 14.0, 14.0, "/cam/to-http"),
        camera("CAM-LOOP", "Redirects forever", 15.0, 15.0, "/cam/loop"),
    ]
    body = json.dumps(cameras).encode()
    manifest = {"schema": 1, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seq": 7,
                "bundles": {}, "keys": {"cctv": {"f": "k/cctv.json", "v": "abc", "bytes": len(body),
                                                 "count": len(cameras), "tier": "fast"}}}
    _Handler.files = {"/manifest.json": json.dumps(manifest).encode(), "/k/cctv.json": body}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield base, cameras
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def client(site):
    return sp.ShadowBrokerPublicClient(base_url=site[0])


def _snap(client, tmp_path, **args):
    return client.command("camera_snapshot", {"out_dir": str(tmp_path), **args})


# ── finding ────────────────────────────────────────────────────────────────

def test_find_cameras_nearest_first_with_the_full_count(client):
    out = client.command("find_cameras", {"lat": 40.758, "lng": -73.9855, "radius_km": 10, "limit": 2})
    assert out["ok"], out
    data = out["data"]
    assert [row["id"] for row in data["results"]] == ["CAM-A", "CAM-HLS"]
    assert data["total"] == 3 and data["truncated"] is True and data["radius_km"] == 10
    assert data["results"][0]["distance_km"] < 0.1
    assert data["results"][0]["snapshot"] == "image" and data["results"][1]["snapshot"] == "none"


def test_find_cameras_by_words_and_type(client):
    by_words = client.command("find_cameras", {"query": "broadway"})["data"]
    assert [row["id"] for row in by_words["results"]] == ["CAM-A"]
    by_source = client.command("find_cameras", {"query": "tfl"})["data"]
    assert [row["id"] for row in by_source["results"]] == ["CAM-CLIP"]
    videos = client.command("find_cameras", {"query": "a", "media_type": "video"})["data"]
    assert all(row["media_type"] == "video" for row in videos["results"])
    assert client.command("find_cameras", {})["ok"] is False


def test_ask_routes_camera_questions(client):
    route = lambda text: sp.route_query(text)["recommended"]  # noqa: E731
    assert route("cameras near 40.758, -73.9855")["cmd"] == "find_cameras"
    assert route("cameras within 2 km of 40.758, -73.9855")["args"]["radius_km"] == 2
    look = route("look at the camera near 40.758, -73.9855")
    assert look["cmd"] == "camera_snapshot" and look["args"]["lat"] == 40.758
    words = route("traffic cameras on broadway")
    assert words == {"cmd": "find_cameras", "args": {"query": "broadway", "limit": 10}}
    assert route("ships near 36.8, -76.3")["cmd"] == "entities_near"


# ── looking ────────────────────────────────────────────────────────────────

def test_snapshot_by_id_saves_the_picture(client, tmp_path):
    out = _snap(client, tmp_path, id="CAM-A")
    assert out["ok"], out
    data = out["data"]
    saved = Path(data["path"])
    assert saved.parent == tmp_path and saved.read_bytes() == JPEG
    assert cam.FILE_PATTERN.fullmatch(saved.name)
    assert data["kind"] == "image" and data["content_type"] == "image/jpeg" and data["bytes"] == len(JPEG)
    assert data["camera"]["name"] == "Broadway @ 45 St"
    assert "not an instruction" in data["notice"]
    assert "data_base64" not in data


def test_snapshot_of_the_nearest_camera_skips_ones_that_cannot_be_saved(client, tmp_path):
    out = _snap(client, tmp_path, lat=40.7581, lng=-73.9856, radius_km=1)
    assert out["ok"] and out["data"]["camera"]["id"] == "CAM-A"  # CAM-HLS is nearer but is not a picture


def test_the_file_type_comes_from_the_bytes_not_the_server(client, tmp_path):
    out = _snap(client, tmp_path, id="CAM-B")
    assert out["ok"] and out["data"]["content_type"] == "image/png" and out["data"]["path"].endswith(".png")


def test_inline_picture_for_agents_without_a_file_tool(client, tmp_path):
    import base64
    out = _snap(client, tmp_path, id="CAM-A", inline=True)
    assert base64.b64decode(out["data"]["data_base64"]) == JPEG


def test_video_clip_is_saved_and_a_frame_is_optional(client, tmp_path, monkeypatch):
    monkeypatch.setattr(cam.shutil, "which", lambda _name: None)
    out = _snap(client, tmp_path, id="CAM-CLIP")
    assert out["ok"], out
    assert out["data"]["kind"] == "video" and Path(out["data"]["path"]).read_bytes() == MP4
    assert "frame_path" not in out["data"] and "ffmpeg" in out["data"]["how_to_view"]


def test_live_stream_gives_its_first_complete_picture(client, tmp_path):
    out = _snap(client, tmp_path, id="CAM-STREAM")
    assert out["ok"], out
    assert Path(out["data"]["path"]).read_bytes() == JPEG and out["data"]["kind"] == "image"


def test_a_redirect_to_a_picture_is_followed(client, tmp_path):
    assert _snap(client, tmp_path, id="CAM-MOVED")["ok"]


# ── refusing ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("camera_id, reason", [
    ("CAM-HLS", "cannot be saved"),
    ("CAM-PAGE", "did not return a picture"),
    ("CAM-GONE", "HTTP 404"),
    ("CAM-LAN", "private or reserved"),
    ("CAM-HTTP", "not https"),
    ("CAM-LOOP", "too many times"),
    ("NOT-IN-THE-LIST", "No camera with id"),
])
def test_snapshot_refusals(client, tmp_path, camera_id, reason):
    out = _snap(client, tmp_path, id=camera_id)
    assert out["ok"] is False and reason in out["detail"], out
    assert list(tmp_path.iterdir()) == []


def test_only_cameras_from_the_list_can_be_fetched(client, tmp_path, site):
    """A caller cannot hand the skill an address: only ids from the camera list work."""
    before = len(_Handler.hits)
    out = _snap(client, tmp_path, id="", media_url=f"{site[0]}/cam/a.jpg", url=f"{site[0]}/cam/a.jpg")
    assert out["ok"] is False
    assert "/cam/a.jpg" not in _Handler.hits[before:]


@pytest.mark.parametrize("url", [
    "http://cameras.example.org/a.jpg",       # not https
    "https://user:pw@cameras.example.org/a",  # credentials
    "https://127.0.0.1/a.jpg",                # this computer
    "https://localhost/a.jpg",
    "ftp://cameras.example.org/a.jpg",
    "file:///etc/passwd",
    "https:///nohost",
])
def test_bad_camera_addresses_are_refused_before_any_request(url):
    with pytest.raises(cam.CameraError):
        cam.fetch_media(url)


@pytest.mark.parametrize("address", [
    "10.0.0.5", "192.168.1.10", "172.16.0.1", "127.0.0.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
    "::1", "fe80::1", "fd00::1", "::ffff:192.168.1.1", "224.0.0.1",
])
def test_hosts_that_resolve_inward_are_refused(monkeypatch, address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
               (family, socket.SOCK_STREAM, 6, "", (address, 443))]
    monkeypatch.setattr(cam.socket, "getaddrinfo", lambda *_a, **_k: answers)
    monkeypatch.setattr(cam, "_open", lambda *_a, **_k: pytest.fail("a request was made"))
    with pytest.raises(cam.CameraError, match="private or reserved"):
        cam.fetch_media("https://cameras.example.org/a.jpg")


def test_local_cameras_are_refused_unless_the_feed_itself_is_local(site):
    with pytest.raises(cam.CameraError, match="not https"):
        cam.fetch_media(f"{site[0]}/cam/a.jpg", allow_local=False)


def test_oversized_pictures_are_refused(client, tmp_path, monkeypatch):
    monkeypatch.setattr(cam, "IMAGE_MAX_BYTES", 100)
    out = _snap(client, tmp_path, id="CAM-A")
    assert out["ok"] is False and "larger" in out["detail"]


def test_old_snapshots_are_cleaned_up_and_other_files_are_left_alone(client, tmp_path):
    old = tmp_path / "cam-0123456789ab-20260101T000000Z.jpg"
    mine = tmp_path / "holiday.jpg"
    for path in (old, mine):
        path.write_bytes(b"x")
        os.utime(path, (time.time() - 7200, time.time() - 7200))
    assert _snap(client, tmp_path, id="CAM-A")["ok"]
    assert not old.exists() and mine.exists()


def test_both_skills_ship_the_same_camera_code():
    other = REPO / "openclaw-skills" / "shadowbroker" / "sb_camera.py"
    ours = (HERE / "sb_camera.py").read_bytes().replace(b"\r\n", b"\n")
    assert other.read_bytes().replace(b"\r\n", b"\n") == ours
