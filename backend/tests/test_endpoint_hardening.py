"""Regression coverage for public-endpoint hardening: CCTV relay limits,
the on-demand Airframes budget, and the AI channel loopback rule."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest
from fastapi import HTTPException


# --- CCTV relay -------------------------------------------------------------

def test_cctv_shared_storage_host_rejects_subdomains_and_other_paths():
    from routers.cctv import _cctv_host_allowed, _cctv_path_allowed

    tfl = "https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.06514.mp4"
    other_bucket = "https://s3-eu-west-1.amazonaws.com/someone-else/page.html"

    assert _cctv_host_allowed("s3-eu-west-1.amazonaws.com")
    assert not _cctv_host_allowed("evil.s3-eu-west-1.amazonaws.com")
    assert _cctv_path_allowed(urlparse(tfl))
    assert not _cctv_path_allowed(urlparse(other_bucket))
    # Ordinary camera hosts keep their subdomains and any path.
    assert _cctv_host_allowed("strmr5.sha.maryland.gov")
    assert _cctv_path_allowed(urlparse("https://images.data.gov.sg/any/path.jpg"))


@pytest.mark.parametrize(
    ("content_type", "allowed"),
    [
        ("image/jpeg", True),
        ("video/mp4", True),
        ("multipart/x-mixed-replace; boundary=frame", True),
        ("application/octet-stream", True),
        ("text/html; charset=utf-8", False),
        ("image/svg+xml", False),
        ("application/javascript", False),
        ("application/xml", False),
    ],
)
def test_cctv_media_type_filter(content_type, allowed):
    from routers.cctv import _cctv_media_type_allowed

    assert _cctv_media_type_allowed(content_type) is allowed


def _upstream(content_type, text=""):
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": content_type}
    resp.text = text
    resp.iter_content = MagicMock(return_value=iter([b""]))
    return resp


def test_cctv_proxy_refuses_non_media_upstream():
    from routers import cctv

    with patch.object(cctv, "_fetch_cctv_upstream_response", return_value=_upstream("text/html")):
        with pytest.raises(HTTPException) as exc:
            cctv._proxy_cctv_media_response(MagicMock(), "https://images.data.gov.sg/cam")
    assert exc.value.status_code == 415


def test_cctv_proxy_refuses_playlist_without_extm3u():
    from routers import cctv

    upstream = _upstream("application/vnd.apple.mpegurl", text="<html><script>x</script></html>")
    with patch.object(cctv, "_fetch_cctv_upstream_response", return_value=upstream):
        with pytest.raises(HTTPException) as exc:
            cctv._proxy_cctv_media_response(MagicMock(), "https://video.deldot.gov/live/cam.m3u8")
    assert exc.value.status_code == 415


def test_cctv_proxy_media_response_sets_nosniff():
    from routers import cctv

    with patch.object(cctv, "_fetch_cctv_upstream_response", return_value=_upstream("image/jpeg")):
        response = cctv._proxy_cctv_media_response(MagicMock(), "https://images.data.gov.sg/cam.jpg")
    assert response.headers["X-Content-Type-Options"] == "nosniff"


# --- Airframes on-demand budget ---------------------------------------------

@pytest.fixture
def airframes_queue(monkeypatch):
    from services.fetchers import airframes

    airframes._queue.clear()
    airframes._queued_aircraft_keys.clear()
    airframes._on_demand_times.clear()
    yield airframes
    airframes._queue.clear()
    airframes._queued_aircraft_keys.clear()
    airframes._on_demand_times.clear()


def test_airframes_on_demand_lookups_are_rate_capped(airframes_queue, monkeypatch):
    monkeypatch.setattr(airframes_queue, "ON_DEMAND_LOOKUPS_PER_MIN", 2)

    assert airframes_queue._prioritize_aircraft_scan({"icao24": "aaa111"})
    assert airframes_queue._prioritize_aircraft_scan({"icao24": "bbb222"})
    assert not airframes_queue._prioritize_aircraft_scan({"icao24": "ccc333"})
    # Re-clicking an aircraft that is already waiting costs nothing.
    assert airframes_queue._prioritize_aircraft_scan({"icao24": "aaa111"})


def test_airframes_on_demand_queue_is_bounded(airframes_queue, monkeypatch):
    monkeypatch.setattr(airframes_queue, "ON_DEMAND_LOOKUPS_PER_MIN", 100)
    monkeypatch.setattr(airframes_queue, "ON_DEMAND_QUEUE_MAX", 3)

    for i in range(6):
        airframes_queue._prioritize_aircraft_scan({"icao24": f"abc{i:03d}"})

    with airframes_queue._queue_lock:
        waiting = [item["icao24"] for item in airframes_queue._queue if item.get("type") == "aircraft"]
        keys = set(airframes_queue._queued_aircraft_keys)
    # Newest clicks win; older ones drop out of the queue and the key set.
    assert waiting == ["abc005", "abc004", "abc003"]
    assert len(keys) == 3


# --- AI channel WebSocket ---------------------------------------------------

def _fake_ws(host):
    return SimpleNamespace(
        client=SimpleNamespace(host=host),
        accept=AsyncMock(),
        close=AsyncMock(),
    )


def test_ai_channel_ws_loopback_needs_hmac_when_loopback_untrusted(monkeypatch):
    from routers import ai_intel

    monkeypatch.setenv("SHADOWBROKER_UNTRUSTED_LOOPBACK", "1")
    verify = AsyncMock(return_value=False)
    monkeypatch.setattr(ai_intel, "_verify_ws_hmac", verify)
    ws = _fake_ws("127.0.0.1")

    asyncio.run(ai_intel.channel_websocket(ws))

    verify.assert_awaited_once()
    ws.close.assert_awaited_once()
    assert ws.close.await_args.kwargs.get("code") == 4001
