from types import SimpleNamespace
import pytest


def test_build_sigint_snapshot_merges_map_nodes_without_duplicate_meshtastic(monkeypatch):
    from services.fetchers import sigint as sigint_fetcher
    from services.fetchers._store import _data_lock, latest_data
    from services import sigint_bridge as sigint_bridge_mod

    fake_grid = SimpleNamespace(
        get_all_signals=lambda: [
            {
                "callsign": "!live1",
                "source": "meshtastic",
                "timestamp": "2026-03-22T18:00:00+00:00",
                "region": "US",
            },
            {
                "callsign": "K1ABC",
                "source": "aprs",
                "timestamp": "2026-03-22T17:59:00+00:00",
            },
        ],
        get_mesh_channel_stats=lambda api_nodes=None: {"total_api": len(api_nodes or [])},
    )
    monkeypatch.setattr(sigint_bridge_mod, "sigint_grid", fake_grid)
    with _data_lock:
        latest_data["meshtastic_map_nodes"] = [
            {
                "callsign": "!live1",
                "source": "meshtastic",
                "timestamp": "2026-03-22T17:40:00+00:00",
                "from_api": True,
            },
            {
                "callsign": "!map2",
                "source": "meshtastic",
                "timestamp": "2026-03-22T17:58:00+00:00",
                "from_api": True,
            },
        ]

    signals, channel_stats, totals = sigint_fetcher.build_sigint_snapshot()

    assert [sig["callsign"] for sig in signals] == ["!live1", "K1ABC", "!map2"]
    assert channel_stats == {"total_api": 2}
    assert totals == {
        "total": 3,
        "meshtastic": 2,
        "meshtastic_live": 1,
        "meshtastic_map": 1,
        "aprs": 1,
        "js8call": 0,
    }


def test_rewrite_cctv_hls_playlist_proxies_relative_segments_and_keys():
    import main

    playlist = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-KEY:METHOD=AES-128,URI="keys/key.bin"
#EXTINF:5.0,
segment-001.ts
"""

    rewritten = main._rewrite_cctv_hls_playlist(
        "https://navigator-c2c.dot.ga.gov/live/cam/index.m3u8",
        playlist,
    )

    assert '/api/cctv/media?url=https%3A%2F%2Fnavigator-c2c.dot.ga.gov%2Flive%2Fcam%2Fkeys%2Fkey.bin' in rewritten
    assert '/api/cctv/media?url=https%3A%2F%2Fnavigator-c2c.dot.ga.gov%2Flive%2Fcam%2Fsegment-001.ts' in rewritten


def test_cctv_proxy_allows_known_state_dot_media_hosts():
    import main

    allowed_hosts = {
        "wzmedia.dot.ca.gov",
        "511ga.org",
        "cctv.travelmidwest.com",
        "micamerasimages.net",
        "tripcheck.com",
    }

    for host in allowed_hosts:
        assert main._cctv_host_allowed(host)


def test_fetch_satnogs_keeps_last_good_snapshot_on_error(monkeypatch):
    from services.fetchers import infrastructure
    from services.fetchers._store import _data_lock, latest_data
    from services.fetchers import _store as store_mod
    from services import satnogs_fetcher

    with _data_lock:
        latest_data["satnogs_stations"] = [{"id": "station-1"}]
        latest_data["satnogs_observations"] = [{"id": "obs-1"}]

    monkeypatch.setattr(store_mod, "is_any_active", lambda *args: True)
    monkeypatch.setattr(satnogs_fetcher, "fetch_satnogs_stations", lambda: (_ for _ in ()).throw(ValueError("boom")))
    monkeypatch.setattr(satnogs_fetcher, "fetch_satnogs_observations", lambda: [])

    infrastructure.fetch_satnogs()

    with _data_lock:
        assert latest_data["satnogs_stations"] == [{"id": "station-1"}]
        assert latest_data["satnogs_observations"] == [{"id": "obs-1"}]


def test_fetch_tinygs_keeps_last_good_snapshot_on_error(monkeypatch):
    from services.fetchers import infrastructure
    from services.fetchers._store import _data_lock, latest_data
    from services.fetchers import _store as store_mod
    from services import tinygs_fetcher

    with _data_lock:
        latest_data["tinygs_satellites"] = [{"norad_id": 12345}]

    monkeypatch.setattr(store_mod, "is_any_active", lambda *args: True)
    monkeypatch.setattr(tinygs_fetcher, "fetch_tinygs_satellites", lambda: (_ for _ in ()).throw(ValueError("boom")))

    infrastructure.fetch_tinygs()

    with _data_lock:
        assert latest_data["tinygs_satellites"] == [{"norad_id": 12345}]


def test_caltrans_ingestor_prefers_static_image_when_stream_url_is_not_browser_safe(monkeypatch):
    from services import cctv_pipeline

    class _Response:
        status_code = 200

        def json(self):
            return {
                "data": [
                    {
                        "cctv": {
                            "location": {
                                "latitude": "34.123",
                                "longitude": "-118.456",
                                "locationName": "I-5 @ Main",
                                "route": "I-5",
                            },
                            "inService": "true",
                            "imageData": {
                                "streamingVideoURL": "viewer?id=123",
                                "static": {"currentImageURL": "/images/cam123.jpg"},
                            },
                            "index": 123,
                        }
                    }
                ]
            }

    monkeypatch.setattr(cctv_pipeline, "fetch_with_curl", lambda *args, **kwargs: _Response())

    cameras = cctv_pipeline.CaltransIngestor().fetch_data()

    assert cameras[0]["media_url"] == "https://cwwp2.dot.ca.gov/images/cam123.jpg"
    assert cameras[0]["media_type"] == "image"


def test_georgia_ingestor_uses_public_511ga_feed_and_paginates(monkeypatch):
    from services import cctv_pipeline

    class _Response:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    responses = [
        {
            "recordsTotal": 2,
            "data": [
                {
                    "id": 14968,
                    "location": "ALPH-0050: Rucker Rd at Charlotte Dr (Alpharetta)",
                    "latLng": {
                        "geography": {
                            "wellKnownText": "POINT (-84.33039 34.076298)",
                        }
                    },
                    "images": [
                        {
                            "id": 22378,
                            "imageUrl": "/map/Cctv/22378",
                            "blocked": False,
                        }
                    ],
                }
            ],
        },
        {
            "recordsTotal": 2,
            "data": [
                {
                    "id": 14969,
                    "location": "BARR-0034: SR 211 at Pinot Nior Dr (Barrow)",
                    "latLng": {
                        "geography": {
                            "wellKnownText": "POINT (-83.81524 34.10526)",
                        }
                    },
                    "images": [
                        {
                            "id": 22379,
                            "imageUrl": "/map/Cctv/22379",
                            "blocked": False,
                        }
                    ],
                }
            ],
        },
    ]
    calls = []

    def _fake_fetch(url, method="GET", json_data=None, timeout=15, headers=None):
        calls.append(
            {
                "url": url,
                "method": method,
                "json_data": json_data,
                "headers": headers,
            }
        )
        return _Response(responses.pop(0))

    monkeypatch.setattr(cctv_pipeline.GeorgiaDOTIngestor, "PAGE_SIZE", 1)
    monkeypatch.setattr(cctv_pipeline, "fetch_with_curl", _fake_fetch)

    cameras = cctv_pipeline.GeorgiaDOTIngestor().fetch_data()

    assert [cam["id"] for cam in cameras] == ["GDOT-14968", "GDOT-14969"]
    assert cameras[0]["media_url"] == "https://511ga.org/map/Cctv/22378"
    assert cameras[0]["media_type"] == "image"
    assert cameras[0]["lat"] == pytest.approx(34.076298)
    assert cameras[0]["lon"] == pytest.approx(-84.33039)
    assert len(calls) == 2
    assert all(call["url"] == "https://511ga.org/List/GetData/Cameras" for call in calls)
    assert all(call["method"] == "POST" for call in calls)
    assert calls[0]["json_data"] == {"draw": 1, "start": 0, "length": 1}
    assert calls[1]["json_data"] == {"draw": 2, "start": 1, "length": 1}
    assert calls[0]["headers"]["Referer"] == "https://511ga.org/cctv"


def test_michigan_ingestor_absolutizes_relative_image_urls(monkeypatch):
    from services import cctv_pipeline

    class _Response:
        status_code = 200

        def json(self):
            return [
                {
                    "county": "id=42&lat=42.3314&lon=-83.0458",
                    "image": '<img src="/MiDrive/camera/image/42.jpg">',
                    "route": "I-94",
                    "location": "Downtown",
                }
            ]

    monkeypatch.setattr(cctv_pipeline, "fetch_with_curl", lambda *args, **kwargs: _Response())

    cameras = cctv_pipeline.MichiganDOTIngestor().fetch_data()

    assert cameras[0]["media_url"] == "https://mdotjboss.state.mi.us/MiDrive/camera/image/42.jpg"
    assert cameras[0]["media_type"] == "image"


def test_austin_ingestor_prefers_source_screenshot_address_and_filters_disabled(monkeypatch):
    from services import cctv_pipeline

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "camera_id": "316",
                    "camera_status": "TURNED_ON",
                    "location_name": "Austin Camera 316",
                    "screenshot_address": "https://cctv.austinmobility.io/image/316.jpg",
                    "location": {"coordinates": [-97.74, 30.24]},
                },
                {
                    "camera_id": "317",
                    "camera_status": "TURNED_OFF",
                    "location_name": "Austin Camera 317",
                    "screenshot_address": "https://cctv.austinmobility.io/image/317.jpg",
                    "location": {"coordinates": [-97.75, 30.25]},
                },
            ]

    monkeypatch.setattr(cctv_pipeline, "fetch_with_curl", lambda *args, **kwargs: _Response())

    cameras = cctv_pipeline.AustinTXIngestor().fetch_data()

    assert len(cameras) == 1
    assert cameras[0]["id"] == "ATX-316"
    assert cameras[0]["media_url"] == "https://cctv.austinmobility.io/image/316.jpg"
    assert cameras[0]["media_type"] == "image"


def test_cctv_proxy_profiles_are_source_specific():
    import main

    tfl = main._cctv_proxy_profile_for_url("https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.mp4")
    austin = main._cctv_proxy_profile_for_url("https://cctv.austinmobility.io/image/316.jpg")
    georgia = main._cctv_proxy_profile_for_url("https://511ga.org/map/Cctv/22378")
    spain = main._cctv_proxy_profile_for_url("https://infocar.dgt.es/etraffic/data/camaras/1050.jpg")

    assert tfl.name == "tfl-jamcam"
    assert tfl.headers["Accept"].startswith("video/mp4")
    assert austin.name == "austin-mobility"
    assert austin.headers["Origin"] == "https://data.mobility.austin.gov"
    assert georgia.name == "gdot-511ga-image"
    assert georgia.timeout == (5.0, 12.0)
    assert georgia.headers["Referer"] == "https://511ga.org/cctv"
    assert spain.name == "dgt-spain"
    assert spain.headers["Referer"] == "https://infocar.dgt.es/"


def test_cctv_proxy_preserves_upstream_http_status(monkeypatch):
    import main

    class _Response:
        status_code = 404
        headers = {}

        def close(self):
            return None

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: _Response())

    request = SimpleNamespace(headers={})
    profile = main._cctv_proxy_profile_for_url("https://infocar.dgt.es/etraffic/data/camaras/1050.jpg")

    with pytest.raises(main.HTTPException) as exc:
        main._fetch_cctv_upstream_response(request, "https://infocar.dgt.es/etraffic/data/camaras/1050.jpg", profile)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Upstream returned 404"


def test_colorado_ingestor_prefers_preview_image_with_hls_fallback(monkeypatch):
    from services import cctv_pipeline

    class _Response:
        status_code = 200

        def json(self):
            return [
                {
                    "id": 1,
                    "public": True,
                    "active": True,
                    "name": "I-70 EB",
                    "location": {"latitude": 39.7, "longitude": -105.2, "routeId": "I-70"},
                    "cameraOwner": {"name": "Colorado DOT"},
                    "views": [
                        {
                            "url": "https://publicstreamer2.cotrip.org/rtplive/test/playlist.m3u8",
                            "videoPreviewUrl": "https://cocam.carsprogram.org/Snapshots/test.flv.png",
                        }
                    ],
                },
                {
                    "id": 2,
                    "public": True,
                    "active": True,
                    "name": "US-285 NB",
                    "location": {"latitude": 39.6, "longitude": -105.1, "routeId": "US-285"},
                    "cameraOwner": {"name": "Colorado DOT"},
                    "views": [
                        {
                            "url": "",
                            "videoPreviewUrl": "https://cocam.carsprogram.org/Snapshots/test2.flv.png",
                        }
                    ],
                },
            ]

    monkeypatch.setattr(cctv_pipeline, "fetch_with_curl", lambda *args, **kwargs: _Response())

    cameras = cctv_pipeline.ColoradoDOTIngestor().fetch_data()

    assert cameras[0]["media_url"] == "https://cocam.carsprogram.org/Snapshots/test.flv.png"
    assert cameras[0]["media_type"] == "image"
    assert cameras[1]["media_url"] == "https://cocam.carsprogram.org/Snapshots/test2.flv.png"
    assert cameras[1]["media_type"] == "image"


def test_caltrans_ingestor_prefers_static_image_over_flaky_hls(monkeypatch):
    from services import cctv_pipeline

    class _Response:
        status_code = 200

        def json(self):
            return {
                "data": [
                    {
                        "cctv": {
                            "index": "1",
                            "inService": "true",
                            "location": {
                                "latitude": "37.82539",
                                "longitude": "-122.27291",
                                "locationName": "TV102 -- I-580 : West of SR-24",
                            },
                            "imageData": {
                                "streamingVideoURL": "https://wzmedia.dot.ca.gov/D4/W580_JWO_24_IC.stream/playlist.m3u8",
                                "static": {
                                    "currentImageURL": "https://cwwp2.dot.ca.gov/data/d4/cctv/image/tv102i580westofsr24/tv102i580westofsr24.jpg"
                                },
                            },
                        }
                    }
                ]
            }

    monkeypatch.setattr(cctv_pipeline, "fetch_with_curl", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(cctv_pipeline.CaltransIngestor, "DISTRICTS", [4])

    cameras = cctv_pipeline.CaltransIngestor().fetch_data()

    assert len(cameras) == 1
    assert cameras[0]["media_type"] == "image"
    assert cameras[0]["media_url"].endswith("tv102i580westofsr24.jpg")


def test_dgt_ingestor_skips_dead_seed_urls(monkeypatch):
    from services import cctv_pipeline

    monkeypatch.setattr(
        cctv_pipeline,
        "_media_url_reachable",
        lambda url, **kwargs: url.endswith("/1001.jpg"),
    )

    cameras = cctv_pipeline.DGTNationalIngestor().fetch_data()

    assert len(cameras) == 1
    assert cameras[0]["id"] == "DGT-1001"


def test_base_ingestor_prunes_stale_rows_for_successful_source_refresh(tmp_path, monkeypatch):
    import sqlite3
    from services import cctv_pipeline

    db_path = tmp_path / "cctv.db"
    monkeypatch.setattr(cctv_pipeline, "DB_PATH", db_path)
    cctv_pipeline.init_db()

    rows = [
        {
            "id": "DGT-1001",
            "source_agency": "DGT Spain",
            "lat": 40.4,
            "lon": -3.7,
            "direction_facing": "A-6 Madrid",
            "media_url": "https://infocar.dgt.es/etraffic/data/camaras/1001.jpg",
            "media_type": "image",
            "refresh_rate_seconds": 300,
        },
        {
            "id": "DGT-1002",
            "source_agency": "DGT Spain",
            "lat": 40.45,
            "lon": -3.68,
            "direction_facing": "A-2 Madrid",
            "media_url": "https://infocar.dgt.es/etraffic/data/camaras/1002.jpg",
            "media_type": "image",
            "refresh_rate_seconds": 300,
        },
    ]

    class _Ingestor(cctv_pipeline.BaseCCTVIngestor):
        def fetch_data(self):
            return list(rows)

    _Ingestor().ingest()
    rows.pop()
    _Ingestor().ingest()

    conn = sqlite3.connect(db_path)
    try:
        stored_ids = [row[0] for row in conn.execute("select id from cameras order by id")]
    finally:
        conn.close()

    assert stored_ids == ["DGT-1001"]


def test_osm_ingestor_keeps_only_direct_media_urls(monkeypatch):
    from services import cctv_pipeline

    class _Response:
        status_code = 200

        def json(self):
            return {
                "elements": [
                    {
                        "id": 101,
                        "lat": 39.7392,
                        "lon": -104.9903,
                        "tags": {
                            "camera:type": "traffic_monitoring",
                            "camera:url": "https://example.gov/cam101/playlist.m3u8",
                            "camera:direction": "270",
                            "operator": "Colorado DOT",
                        },
                    },
                    {
                        "id": 102,
                        "lat": 39.7400,
                        "lon": -104.9910,
                        "tags": {
                            "camera:type": "traffic_monitoring",
                            "website": "https://example.gov/traffic/cameras",
                        },
                    },
                ]
            }

    monkeypatch.setattr(cctv_pipeline, "fetch_with_curl", lambda *args, **kwargs: _Response())

    cameras = cctv_pipeline.OSMTrafficCameraIngestor().fetch_data()

    assert len(cameras) == 1
    assert cameras[0]["id"] == "OSM-101"
    assert cameras[0]["media_type"] == "hls"
    assert cameras[0]["direction_facing"] == "270"


def test_cctv_proxy_allows_colorado_media_hosts():
    import main

    assert main._cctv_host_allowed("publicstreamer2.cotrip.org")
    assert main._cctv_host_allowed("cocam.carsprogram.org")


def test_data_fetcher_cctv_scheduler_includes_colorado_and_osm():
    from pathlib import Path

    source = Path("backend/services/data_fetcher.py").read_text(encoding="utf-8")

    assert "ColoradoDOTIngestor()" in source
    assert "OSMTrafficCameraIngestor()" in source
