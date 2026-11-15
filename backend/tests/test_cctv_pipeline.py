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
    assert "IBI511Ingestor" in names
    for name in ("MarylandCHARTIngestor", "IterisCamerasIngestor", "DelDOTIngestor", "TxDOTIngestor",
                 "CARS511Ingestor", "FintrafficWeathercamIngestor", "HongKongTDIngestor",
                 "QueenslandTrafficIngestor", "NZTAIngestor"):
        assert name in names
    for name in ("IcelandVegagerdinIngestor", "TaiwanTHBIngestor", "LithuaniaViaLietuvaIngestor",
                 "BizkaiaTrafficIngestor", "DIRCentreEstIngestor", "DIREstIngestor", "LyonCriterIngestor",
                 "InforouteIngestor", "APRRIngestor", "AutostradeIngestor", "EdmontonTrafficIngestor",
                 "OregonTripCheckIngestor"):
        assert name in names
    assert len(names) == 43


def test_scheduled_cctv_ingestors_register_every_ibi511_site_once():
    scheduled = cctv_pipeline.scheduled_cctv_ingestors()
    keys = [key for _, key in scheduled]
    assert len(keys) == len(set(keys))
    # 21 original, the IBI, CARS and Inforoute site lists, 9 batch-two ingestors
    # (MD, VA, SC, DE, TX, Finland, Hong Kong, Queensland, New Zealand) and 12
    # batch-three ones (NC, Iceland, Taiwan, Lithuania, Bizkaia, DIR Centre-Est,
    # DIR Est, Lyon, APRR, Autostrade, Edmonton, Oregon).
    assert len(scheduled) == (21 + len(cctv_pipeline.IBI511_SITES) + len(cctv_pipeline.CARS511_SITES)
                              + len(cctv_pipeline.INFOROUTE_SITES) + 9 + 12)
    prefixes = [prefix for _, _, prefix, _ in cctv_pipeline.IBI511_SITES]
    prefixes += [prefix for _, _, prefix, _, _ in cctv_pipeline.CARS511_SITES]
    prefixes += ["MDCHART", "VDOT", "SCDOT", "DELDOT", "TXDOT", "FINTRAFFIC", "HKTD", "QLD", "NZTA"]
    prefixes += [prefix for _, _, prefix, _, _ in cctv_pipeline.INFOROUTE_SITES]
    prefixes += ["NCDOT", "ISVEG", "TWTHB", "LTVIA", "BIZKAIA", "DIRCE", "DIREST", "LYON", "APRR", "ASPI",
                 "YEG", "TRIPCHECK"]
    existing = {"GDOT", "FL511", "ON511", "AB511", "ALPR", "ASFINAG", "ATX", "AUS", "CAL", "CODOT", "DGT",
                "IDOT", "MAD", "MDOT", "NLRWS", "NYC", "OSM", "SGP", "TFL", "WINDY", "WSDOT"}
    # ingest() clears old rows by id prefix (SQLite LIKE ignores case), so
    # prefixes must never collide.
    upper = [p.upper() for p in prefixes]
    assert len(upper) == len(set(upper))
    assert not existing & set(upper)


def test_ontario_and_alberta_use_the_511_list_feed(monkeypatch):
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(cctv_pipeline, "_fetch_511_datatables_cameras", fake_fetch)
    cctv_pipeline.Ontario511Ingestor().fetch_data()
    cctv_pipeline.Alberta511Ingestor().fetch_data()
    assert [c["list_url"] for c in calls] == [
        "https://511on.ca/List/GetData/Cameras",
        "https://511.alberta.ca/List/GetData/Cameras",
    ]
    assert [c["id_prefix"] for c in calls] == ["ON511", "AB511"]


def test_dgt_catalog_parses_national_camera_list(monkeypatch):
    class FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "camaras": [
                    {"id": "2", "latitud": "42.0676", "longitud": "-4.2227", "carretera": "A-62",
                     "pk": "57.9", "imagen": "https://etraffic.dgt.es/camarasEtraffic/2.jpg"},
                    {"id": "3", "latitud": "", "longitud": "-4.0", "imagen": "https://etraffic.dgt.es/camarasEtraffic/3.jpg"},
                    {"id": "4", "latitud": "40.0", "longitud": "-3.0", "imagen": ""},
                ]
            }

    monkeypatch.setattr(cctv_pipeline, "fetch_with_curl", lambda *a, **k: FakeResp())
    cameras = cctv_pipeline.DGTNationalIngestor().fetch_data()
    assert len(cameras) == 1
    assert cameras[0]["id"] == "DGT-2"
    assert cameras[0]["direction_facing"] == "A-62 km 57.9"
    assert cameras[0]["media_url"] == "https://etraffic.dgt.es/camarasEtraffic/2.jpg"


def test_netherlands_rws_parses_rwsverkeersinfo_feed(monkeypatch):
    class FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return [
                {"id": 4, "latitude": "52.185241", "longitude": "5.41449", "road": "A1",
                 "near": "Amersfoort", "static_url": "https://stream.inmoves.nl/62",
                 "stream_url": "https://stream.inmoves.nl/62/embed"},
                {"id": 5, "latitude": "x", "longitude": "5.0", "static_url": "https://stream.inmoves.nl/63"},
            ]

    monkeypatch.setattr(cctv_pipeline, "fetch_with_curl", lambda *a, **k: FakeResp())
    cameras = cctv_pipeline.NetherlandsRWSIngestor().fetch_data()
    assert len(cameras) == 1
    assert cameras[0]["id"] == "NLRWS-4"
    assert cameras[0]["direction_facing"] == "A1 near Amersfoort"
    assert cameras[0]["media_url"] == "https://stream.inmoves.nl/62"


def test_cctv_proxy_allows_and_referers_new_hosts():
    from routers import cctv as cctv_router

    for host in ["az511.gov", "511pa.com", "stream.inmoves.nl", "etraffic.dgt.es"]:
        assert cctv_router._cctv_host_allowed(host), host
    profile = cctv_router._cctv_proxy_profile_for_url("https://prod-ut.ibi511.com/map/Cctv/170411")
    assert profile.name == "ibi-511"
    assert profile.headers["Referer"] == "https://prod-ut.ibi511.com/"
    profile = cctv_router._cctv_proxy_profile_for_url("https://stream.inmoves.nl/62")
    assert profile.headers["Referer"] == "https://stream.inmoves.nl/"


class _JsonResp:
    status_code = 200

    def __init__(self, payload, content=b""):
        self._payload = payload
        self.content = content
        self.text = content.decode("utf-8") if isinstance(content, bytes) else str(content)

    def json(self):
        return self._payload


def _serve(monkeypatch, payload=None, content=b""):
    calls = []

    def fake(url, **kwargs):
        calls.append((url, kwargs))
        return _JsonResp(payload, content)

    monkeypatch.setattr(cctv_pipeline, "fetch_with_curl", fake)
    return calls


def test_maryland_chart_builds_hls_urls_on_chart_servers_only(monkeypatch):
    _serve(monkeypatch, {"data": [
        {"id": "7A00A1DC01250075004D823633235DAA", "cctvIp": "strmr5.sha.maryland.gov",
         "lat": 39.2773, "lon": -77.3236, "name": "I-270 & Old Hundred Rd (MD 109)"},
        {"id": "7b00a1dc01250075004d823633235daa", "cctvIp": "evil.example.com", "lat": 39.0, "lon": -77.0},
        {"id": "not-hex", "cctvIp": "strmr5.sha.maryland.gov", "lat": 39.0, "lon": -77.0},
        {"id": "7c00a1dc01250075004d823633235daa", "cctvIp": "strmr1.sha.maryland.gov", "lat": 10.0, "lon": -77.0},
        {"id": "7d00a1dc01250075004d823633235daa", "cctvIp": "strmr1.sha.maryland.gov", "lat": 38.9, "lon": -76.9,
         "name": "12", "description": "US 50 at Church Rd"},
    ]})
    cameras = cctv_pipeline.MarylandCHARTIngestor().fetch_data()
    assert [c["id"] for c in cameras] == ["MDCHART-7a00a1dc01250075004d823633235daa",
                                          "MDCHART-7d00a1dc01250075004d823633235daa"]
    assert cameras[0]["media_url"] == (
        "https://strmr5.sha.maryland.gov/rtplive/7a00a1dc01250075004d823633235daa/playlist.m3u8")
    assert cameras[0]["media_type"] == "hls"
    assert cameras[1]["direction_facing"] == "US 50 at Church Rd"


def test_iteris_feed_uses_agency_snapshots_and_flags(monkeypatch):
    def feature(cam_id, image, **props):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-77.3, 38.8]},
                "properties": {"id": cam_id, "description": "University Dr", "jurisdiction": "Fairfax",
                               "image_url": image, "active": True, "problem_stream": False, **props}}

    _serve(monkeypatch, {"features": [
        feature("1", "https://snapshot.vdotcameras.com/thumbs/a.flv.png"),
        feature("2", "https://snapshot.vdotcameras.com/thumbs/b.flv.png", active=False),
        feature("3", "https://snapshot.vdotcameras.com/thumbs/c.flv.png", problem_stream=True),
        feature("4", "https://elsewhere.example.com/d.png"),
        feature("5", "http://snapshot.vdotcameras.com/thumbs/e.flv.png"),
    ]})
    cameras = cctv_pipeline.IterisCamerasIngestor(
        "https://feed.test", "VDOT", "Virginia VDOT", "vdotcameras.com", (36.4, 39.6, -83.8, -75.1)).fetch_data()
    assert [c["id"] for c in cameras] == ["VDOT-1"]
    assert cameras[0]["direction_facing"] == "University Dr (Fairfax)"
    assert cameras[0]["media_type"] == "image"


def test_deldot_keeps_active_https_playlists_and_drops_port(monkeypatch):
    def row(cam_id, url, **extra):
        return {"id": cam_id, "title": "DE 1 @ MILFORD NECK RD", "county": "Kent", "lat": 38.99, "lon": -75.45,
                "enabled": True, "status": "Active", "urls": {"m3u8s": url}, **extra}

    _serve(monkeypatch, {"videoCameras": [
        row("KCAM001", "https://video.deldot.gov:443/live/KCAM001.stream/playlist.m3u8"),
        row("KCAM002", "https://video.deldot.gov/live/KCAM002.stream/playlist.m3u8", status="Inactive"),
        row("KCAM003", "http://video.deldot.gov:1935/live/KCAM003.stream/playlist.m3u8"),
    ]})
    cameras = cctv_pipeline.DelDOTIngestor().fetch_data()
    assert len(cameras) == 1
    assert cameras[0]["media_url"] == "https://video.deldot.gov/live/KCAM001.stream/playlist.m3u8"
    assert cameras[0]["direction_facing"] == "DE 1 @ MILFORD NECK RD (Kent County)"


def test_txdot_reads_every_district_and_skips_offline(monkeypatch):
    calls = _serve(monkeypatch, {"roadwayCctvStatuses": {"IH20": [
        {"icd_Id": "IH20 @ Dallas-Tarrant CL", "name": "IH20 @ Dallas-Tarrant CL", "hasSnapshot": True,
         "statusDescription": "Device Online", "latitude": 32.676316, "longitude": -97.035836},
        {"icd_Id": "IH20 @ Offline", "hasSnapshot": True, "statusDescription": "Device Offline",
         "latitude": 32.6, "longitude": -97.0},
        {"icd_Id": "IH20 @ NoSnap", "hasSnapshot": False, "statusDescription": "Device Online",
         "latitude": 32.6, "longitude": -97.0},
    ]}})
    cameras = cctv_pipeline.TxDOTIngestor().fetch_data()
    assert len(calls) == len(cctv_pipeline.TXDOT_DISTRICTS) == 25
    assert len(cameras) == 25  # one usable camera per (faked) district
    dal = next(c for c in cameras if c["id"].startswith("TXDOT-DAL-"))
    assert dal["id"] == "TXDOT-DAL-IH20_Dallas_Tarrant_CL"
    assert dal["media_url"] == ("https://its.txdot.gov/its/DistrictIts/GetCctvSnapshotByIcdId"
                                "?districtCode=DAL&icdId=IH20%20%40%20Dallas-Tarrant%20CL")
    assert dal["direction_facing"] == "IH20 @ Dallas-Tarrant CL (Dallas)"


def test_cars511_parses_graphql_cameras_and_skips_closed_icons(monkeypatch):
    def cam(uri, url, lon=-86.26, lat=39.73, **extra):
        return {"title": "I-465: SAM JONES EXPWY", "uri": uri, "__typename": "Camera", "active": True,
                "features": [{"geometry": {"type": "Point", "coordinates": [lon, lat]}}],
                "views": [{"category": "VIDEO", "url": url}], **extra}

    calls = _serve(monkeypatch, {"data": {"mapFeaturesQuery": {"mapFeatures": [
        cam("camera/24638", "https://public.carsprogram.org/cameras/IN/INDOT_10_x.flv.png?1794745320000"),
        cam("camera/2", "/images/icon-camera-closed-fill-solid-padded.svg"),
        cam("camera/3", "https://public.carsprogram.org/cameras/IN/3.jpg", active=False),
        cam("camera/4", "https://public.carsprogram.org/cameras/IN/4.jpg", lat=10.0),
        {"__typename": "Sign", "uri": "sign/5"},
    ]}}})
    cameras = cctv_pipeline.CARS511Ingestor(
        "https://511in.org", "INDOT", "Indiana INDOT", (37.7, 41.9, -88.2, -84.6)).fetch_data()
    assert [c["id"] for c in cameras] == ["INDOT-24638"]
    assert cameras[0]["media_url"] == "https://public.carsprogram.org/cameras/IN/INDOT_10_x.flv.png"
    url, kwargs = calls[0]
    assert url == "https://511in.org/api/graphql"
    assert kwargs["method"] == "POST"
    assert kwargs["json_data"]["variables"]["input"]["zoom"] == 16


def test_fintraffic_uses_first_collected_preset(monkeypatch):
    _serve(monkeypatch, {"features": [
        {"id": "C01503", "geometry": {"coordinates": [23.99616, 60.05374, 0.0]},
         "properties": {"id": "C01503", "name": "kt51_Inkoo", "collectionStatus": "GATHERING",
                        "presets": [{"id": "C0150301", "inCollection": False}, {"id": "C0150302", "inCollection": True}]}},
        {"id": "C09999", "geometry": {"coordinates": [24.0, 60.0]},
         "properties": {"id": "C09999", "collectionStatus": "REMOVED_TEMPORARILY", "presets": [{"id": "C0999901"}]}},
    ]})
    cameras = cctv_pipeline.FintrafficWeathercamIngestor().fetch_data()
    assert len(cameras) == 1
    assert cameras[0]["media_url"] == "https://weathercam.digitraffic.fi/C0150302.jpg"
    assert cameras[0]["direction_facing"] == "kt51 Inkoo"


def test_hong_kong_td_parses_snapshot_list(monkeypatch):
    xml = b"""<?xml version="1.0" encoding="UTF-8"?><image-list>
      <image><key>H429F</key><region>Hong Kong Island</region><district>Southern</district>
        <description>Aberdeen Praya Road near Fish Market [H429F]</description>
        <latitude>22.24845</latitude><longitude>114.1505</longitude>
        <url>https://tdcctv.data.one.gov.hk/H429F.JPG</url></image>
      <image><key>X1</key><latitude>40.0</latitude><longitude>114.1</longitude>
        <url>https://tdcctv.data.one.gov.hk/X1.JPG</url></image>
    </image-list>"""
    _serve(monkeypatch, content=xml)
    cameras = cctv_pipeline.HongKongTDIngestor().fetch_data()
    assert len(cameras) == 1
    assert cameras[0]["id"] == "HKTD-H429F"
    assert cameras[0]["direction_facing"] == "Aberdeen Praya Road near Fish Market (Southern)"


def test_queensland_reads_traffic_and_flood_layers(monkeypatch):
    _serve(monkeypatch, {"features": [
        {"geometry": {"coordinates": [153.0087, -27.5552]},
         "properties": {"id": 1, "description": "Archerfield - Ipswich Motorway",
                        "image_url": "https://cameras.qldtraffic.qld.gov.au/Metropolitan/a.jpg"}},
        {"geometry": {"coordinates": [153.0, -27.5]},
         "properties": {"id": 2, "image_url": "https://elsewhere.example.com/b.jpg"}},
    ]})
    cameras = cctv_pipeline.QueenslandTrafficIngestor().fetch_data()
    assert [c["id"] for c in cameras] == ["QLD-traffic-1", "QLD-flood-1"]
    assert cameras[1]["source_agency"] == "QLDTraffic flood camera"


def test_nzta_skips_offline_and_reads_nested_region(monkeypatch):
    xml = b"""<?xml version="1.0" encoding="UTF-8"?><response>
      <camera><description>South along Hinds Highway</description><direction>Southbound</direction>
        <id>714</id><imageUrl>/camera/714.jpg</imageUrl>
        <journey><id>86</id><name>SH1</name></journey>
        <latitude>-43.919632</latitude><longitude>171.721055</longitude><name>SH1 Tinwald </name>
        <offline>false</offline><region><id>11</id><name>Canterbury</name></region>
        <underMaintenance>false</underMaintenance></camera>
      <camera><id>715</id><imageUrl>/camera/715.jpg</imageUrl><latitude>-43.9</latitude>
        <longitude>171.7</longitude><name>Offline cam</name><offline>true</offline></camera>
    </response>"""
    _serve(monkeypatch, content=xml)
    cameras = cctv_pipeline.NZTAIngestor().fetch_data()
    assert len(cameras) == 1
    assert cameras[0]["id"] == "NZTA-714"
    assert cameras[0]["direction_facing"] == "SH1 Tinwald (Southbound)"
    assert cameras[0]["media_url"] == "https://trafficnz.info/camera/714.jpg"


def test_cctv_proxy_allows_batch_two_hosts_and_profiles():
    from routers import cctv as cctv_router

    for host in ["strmr5.sha.maryland.gov", "video.deldot.gov", "snapshot.vdotcameras.com",
                 "scdotsnap.us-east-1.skyvdn.com", "its.txdot.gov", "public.carsprogram.org",
                 "atmsqf.iowadot.gov", "weathercam.digitraffic.fi", "tdcctv.data.one.gov.hk",
                 "cameras.qldtraffic.qld.gov.au", "trafficnz.info"]:
        assert cctv_router._cctv_host_allowed(host), host
    assert not cctv_router._cctv_host_allowed("maryland.gov.evil.example.com")
    assert cctv_router._cctv_proxy_profile_for_url(
        "https://strmr5.sha.maryland.gov/rtplive/x/playlist.m3u8").name == "dot-hls"
    assert cctv_router._cctv_proxy_profile_for_url(
        cctv_pipeline.txdot_snapshot_url("DAL", "IH20 @ Main")).name == "txdot-snapshot"
    assert cctv_router._cctv_proxy_profile_for_url("https://trafficnz.info/camera/714.jpg").name == "dot-image"


def test_txdot_snapshot_decoder_serves_jpeg_or_404():
    import base64

    import pytest
    from fastapi import HTTPException

    from routers import cctv as cctv_router

    class Resp:
        def __init__(self, payload):
            self.payload = payload
            self.closed = False

        def json(self):
            return self.payload

        def close(self):
            self.closed = True

    profile = cctv_router._cctv_proxy_profile_for_url(cctv_pipeline.txdot_snapshot_url("DAL", "x"))
    jpeg = b"\xff\xd8\xff\xe0rest\xff\xd9"
    resp = Resp({"snippet": base64.b64encode(jpeg).decode()})
    out = cctv_router._decode_txdot_snapshot(resp, profile)
    assert out.body == jpeg
    assert out.media_type == "image/jpeg"
    assert resp.closed
    for payload in (None, {"snippet": None}, {"snippet": base64.b64encode(b"<html>").decode()},
                    {"snippet": "not base64!!"}):
        with pytest.raises(HTTPException) as err:
            cctv_router._decode_txdot_snapshot(Resp(payload), profile)
        assert err.value.status_code == 404


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


# --- Third batch ------------------------------------------------------------

def test_nc_drivenc_requests_the_query_in_the_url(monkeypatch):
    calls = _serve(monkeypatch, {"recordsTotal": 1, "data": [
        {"id": 4020, "location": "CCTV10-I485-30.1O_I85",
         "latLng": {"geography": {"wellKnownText": "POINT (-80.73711 35.35311)"}},
         "images": [{"imageUrl": "/map/Cctv/4020", "blocked": False}]},
    ]})
    cameras = cctv_pipeline.IBI511Ingestor("https://www.drivenc.gov", "NCDOT", "NCDOT DriveNC",
                                           query_in_url=True).fetch_data()
    url, kwargs = calls[0]
    assert url.startswith("https://www.drivenc.gov/List/GetData/Cameras?query=") and url.endswith("&lang=en")
    assert "%22length%22%3A100" in url and kwargs.get("method", "GET") == "GET"
    assert cameras[0]["id"] == "NCDOT-4020"
    assert cameras[0]["media_url"] == "https://www.drivenc.gov/map/Cctv/4020"


def test_iceland_ids_by_file_and_only_vegagerdin_images(monkeypatch):
    _serve(monkeypatch, [
        {"Maelist_nr": 7001, "Myndavel": "Hellisheiði", "Skyring": "Hellisheiði séð til vesturs",
         "Slod": "https://www.vegagerdin.is/vgdata/vefmyndavelar/hellisheidi_1.jpg", "Breidd": 64.0, "Lengd": -21.3},
        {"Maelist_nr": 7001, "Myndavel": "Hellisheiði", "Skyring": "til austurs",
         "Slod": "https://www.vegagerdin.is/vgdata/vefmyndavelar/hellisheidi_2.jpg", "Breidd": 64.0, "Lengd": -21.3},
        {"Maelist_nr": 7002, "Slod": "https://evil.example.com/vgdata/vefmyndavelar/x.jpg", "Breidd": 64.0, "Lengd": -21.3},
        {"Maelist_nr": 7003, "Slod": "https://www.vegagerdin.is/vgdata/vefmyndavelar/y.jpg", "Breidd": 0, "Lengd": 0},
    ])
    cameras = cctv_pipeline.IcelandVegagerdinIngestor().fetch_data()
    assert [c["id"] for c in cameras] == ["ISVEG-hellisheidi_1", "ISVEG-hellisheidi_2"]
    assert cameras[0]["direction_facing"] == "Hellisheiði séð til vesturs"
    assert cameras[1]["direction_facing"] == "Hellisheiði - til austurs"


def test_taiwan_thb_appends_snapshot_and_drops_port(monkeypatch):
    _serve(monkeypatch, [
        {"id": "CCTV-43-0110-020-005", "stakenumber": "台11線020K+685", "gisx": 121.57, "gisy": 23.80,
         "html": "https://cctv-ss01.thb.gov.tw:443/T11-020K+685"},
        {"id": "CCTV-X", "gisx": 121.5, "gisy": 25.0, "html": "https://cctvn.freeway.gov.tw/abc"},
        {"id": "CCTV-Y", "gisx": 0, "gisy": 0, "html": "https://cctv-ss01.thb.gov.tw/T1"},
    ])
    cameras = cctv_pipeline.TaiwanTHBIngestor().fetch_data()
    assert [c["id"] for c in cameras] == ["TWTHB-CCTV-43-0110-020-005"]
    assert cameras[0]["media_url"] == "https://cctv-ss01.thb.gov.tw/T11-020K+685/snapshot"


def test_lithuania_joins_layer_positions_and_drops_stale_frames(monkeypatch):
    import time

    now_ms = int(time.time() * 1000)
    layer = [{"layer": "VKR", "features": [
        {"id": "72", "points": [{"point": [54.64, 25.18]}]},
        {"id": "73", "points": [{"point": [54.70, 25.20]}]},
    ]}]
    table = [
        {"id": 72, "name": "Vilnius A1 10,04", "roadName": "Vilnius–Kaunas–Klaipėda", "date": now_ms - 60_000},
        {"id": 73, "name": "Stale", "date": now_ms - 7 * 3600 * 1000},
        {"id": 74, "name": "No position", "date": now_ms},
    ]
    monkeypatch.setattr(cctv_pipeline, "_get_feed_json",
                        lambda url, **kw: layer if "layer-static" in url else table)
    cameras = cctv_pipeline.LithuaniaViaLietuvaIngestor().fetch_data()
    assert [c["id"] for c in cameras] == ["LTVIA-72"]
    assert cameras[0]["media_url"] == "https://eismoinfo.lt/eismoinfo-backend/image-provider/camera/last?id=72"
    assert cameras[0]["direction_facing"] == "Vilnius A1 10,04 (Vilnius–Kaunas–Klaipėda)"


def test_utm30n_conversion_lands_in_bizkaia():
    lat, lon = cctv_pipeline._utm30n_to_lat_lon(500000.0, 4792953.64)
    # On the zone's central meridian (3°W) the easting maps straight to -3.
    assert abs(lon + 3.0) < 1e-9
    assert 43.25 < lat < 43.33
    lat, lon = cctv_pipeline._utm30n_to_lat_lon(507650.15, 4792953.64)
    assert 43.25 < lat < 43.33 and -2.93 < lon < -2.88


def test_bizkaia_keeps_only_bizkaimove_frames_over_https(monkeypatch):
    pages = {
        1: {"totalPages": 2, "cameras": [
            {"cameraId": "75", "sourceId": "2", "cameraName": "CCTV 232 - Cámara DOMO 232",
             "urlImage": "http://www.bizkaimove.com/camaras/cam22.jpg?t=1", "latitude": "4792953.64",
             "longitude": "507650.15", "road": "N - 637"},
            {"cameraId": "9", "sourceId": "1", "urlImage": "https://trafikoa.eus/a.jpg",
             "latitude": "43.3", "longitude": "-2.9"},
        ]},
        2: {"totalPages": 2, "cameras": [
            {"cameraId": "76", "sourceId": "2", "urlImage": "https://evil.example.com/camaras/cam1.jpg",
             "latitude": "43.3", "longitude": "-2.9"},
        ]},
    }
    monkeypatch.setattr(cctv_pipeline, "_get_feed_json",
                        lambda url, **kw: pages[int(url.rsplit("=", 1)[1])])
    monkeypatch.setattr(cctv_pipeline, "_keep_fresh_frames", lambda cams, **kw: cams)
    cameras = cctv_pipeline.BizkaiaTrafficIngestor().fetch_data()
    assert [c["id"] for c in cameras] == ["BIZKAIA-75"]
    assert cameras[0]["media_url"] == "https://www.bizkaimove.eus/camaras/cam22.jpg"
    assert cameras[0]["direction_facing"] == "N-637 - Cámara DOMO 232"


def test_dir_centre_est_and_dir_est_parse_inline_camera_lists(monkeypatch):
    _serve(monkeypatch, content=(
        'var donneesCamera = [{id: 4, latitude: 47.2979, longitude: 2.95234, zoom: 9, '
        'description:"Pouilly A77", direction:"vers Moulins"}, {id: 1, latitude: 45.7, longitude: 4.8, zoom: 8}];'
    ).encode())
    cameras = cctv_pipeline.DIRCentreEstIngestor().fetch_data()
    assert [c["id"] for c in cameras] == ["DIRCE-4"]
    assert cameras[0]["media_url"].endswith("/streams/last/nce.4.mp4")
    assert cameras[0]["media_type"] == "video"

    _serve(monkeypatch, content=(
        'var liens= [{nom:"Amblans", x : 6.43527 , y : 47.684723 , add:"chargerFenetreModale(1)", etat:1},'
        '{nom:"Off", x : 6.8 , y : 47.8 , add:"chargerFenetreModale(2)", etat:0}];'
    ).encode())
    cameras = cctv_pipeline.DIREstIngestor().fetch_data()
    assert [(c["id"], c["lat"], c["lon"]) for c in cameras] == [("DIREST-1", 47.684723, 6.43527)]
    assert cameras[0]["media_url"] == "https://webcam.dir-est.fr/lastimg/1"


def test_inforoute_picks_the_sites_frame_file_and_mjpeg_encoders(monkeypatch):
    def feature(cam_id, **props):
        return {"geometry": {"coordinates": [6.99, 43.6]},
                "properties": {"id_webcam": cam_id, "actif": "1", "titre": f"cam {cam_id}", **props}}

    payload = {"features": [
        feature("1", config="local", type_media="DEFILEMENT_IMAGE", url_dossier="https://www.inforoutes06.fr/webcam/CAM1/"),
        feature("2", config="local", type_media="VIDEO", url_dossier="https://www.inforoutes06.fr/webcam/CAM2/"),
        feature("3", config="local", type_media="DEFILEMENT_IMAGE", url_dossier="https://evil.example.com/webcam/"),
        feature("4", config="animation", url_distant="https://if57cam.logipro.com:8146/stream46.cgi"),
        feature("5", config="local", type_media="DEFILEMENT_IMAGE", actif="0",
                url_dossier="https://www.inforoutes06.fr/webcam/CAM5/"),
    ]}

    class Resp:
        status_code = 200

        def json(self):
            return payload

    posts = []
    monkeypatch.setattr(cctv_pipeline.requests, "post", lambda url, **kw: posts.append((url, kw)) or Resp())
    monkeypatch.setattr(cctv_pipeline, "_keep_fresh_frames", lambda cams, **kw: cams)
    cameras = cctv_pipeline.InforouteIngestor("www.inforoutes06.fr", "INFOROUTE06", "Alpes-Maritimes",
                                              {"DEFILEMENT_IMAGE": "snap5.jpg"}).fetch_data()
    assert posts[0][0] == "https://www.inforoutes06.fr/mod_turbolead/mod/inforoute/index.php"
    assert posts[0][1]["data"] == {"action": "383"}
    assert [(c["id"], c["media_url"], c["media_type"]) for c in cameras] == [
        ("INFOROUTE06-1", "https://www.inforoutes06.fr/webcam/CAM1/snap5.jpg", "image"),
        ("INFOROUTE06-4", "https://if57cam.logipro.com:8146/stream46.cgi", "mjpeg"),
    ]


def test_aprr_uses_viewsurf_redirects_and_drops_unavailable(monkeypatch):
    pois = [{"id": "96", "coords": {"lat": 48.86, "lon": 2.41}},
            {"id": "98", "coords": {"lat": 47.03, "lon": 4.87}},
            {"id": "99", "coords": {"lat": 47.0, "lon": 4.8}}]
    details = {
        "96": [{"data": {"title": "Porte de Montreuil", "tags": "Paris|boulevard périphérique",
                         "video": "https://gieat.viewsurf.com/?id=5598&action=mediaRedirect"}}],
        "98": [{"data": {"title": "Bifurcation A31/A6", "tags": "A31/A6|KM 304|sens Paris-Lyon",
                         "video": "https://gieat.viewsurf.com/?id=2744&action=mediaRedirect"}}],
        "99": [{"data": {"title": "No video", "video": ""}}],
    }
    monkeypatch.setattr(cctv_pipeline.APRRIngestor, "_details", {})
    monkeypatch.setattr(cctv_pipeline, "_get_feed_json",
                        lambda url, **kw: pois if url.endswith("/pois/webcam") else details[url.rsplit("/", 1)[1]])
    monkeypatch.setattr(cctv_pipeline.APRRIngestor, "_is_live", staticmethod(lambda url: "5598" not in url))
    cameras = cctv_pipeline.APRRIngestor().fetch_data()
    assert [c["id"] for c in cameras] == ["APRR-98"]
    assert cameras[0]["media_url"] == "https://gieat.viewsurf.com/?id=2744&action=mediaRedirect"
    assert cameras[0]["media_type"] == "video"
    # The road is already in the title, so it is not prefixed again.
    assert cameras[0]["direction_facing"] == "Bifurcation A31/A6 (sens Paris-Lyon)"


def test_autostrade_keeps_recent_well_formed_clips(monkeypatch):
    from datetime import datetime, timedelta, timezone

    def stamp(hours_ago):
        t = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        return t.strftime("%d-%m-%Y"), t.strftime("%H:%M")

    clip = "dt4/fdb2dcf0-d228-491f-948b-032d4a12a14e-23.mp4"

    def cam(cam_id, hours_ago, url=clip, lat=46.2):
        day, clock = stamp(hours_ago)
        return {"c_tel": cam_id, "t_day": day, "t_time": clock, "t_des_str": "A23 UDINE-TARVISIO️",
                "t_des": "km. 42,0 Gemona", "n_crd_lat": lat, "n_crd_lon": 13.09, "frames": {"V": {"t_url": url}}}

    _serve(monkeypatch, {"webcams": [cam(1877, 1), cam(1878, 30), cam(1879, 1, "../../etc/passwd.mp4"),
                                     cam(1880, 1, lat=60.0)]})
    cameras = cctv_pipeline.AutostradeIngestor().fetch_data()
    assert [c["id"] for c in cameras] == ["ASPI-1877"]
    assert cameras[0]["media_url"] == f"https://video.autostrade.it/video-mp4_hq/{clip}"
    assert cameras[0]["direction_facing"] == "A23 km. 42,0 Gemona"


def test_edmonton_builds_playlists_on_winkcdn_only(monkeypatch):
    def row(code, host="cityed1-winkcdn1.winkcdn.com", **extra):
        return {"Code": code, "Forge": 2, "Latitude": "53.4538", "Longitude": "-113.493", "MMSUrl": host,
                "PrimaryRoad": "23 Avenue", "SecondaryRoad": "Gateway Boulevard", "Status": "1",
                "StreamCode": "WF05-6212-B834-BD83-1FC4_ab", **extra}

    calls = _serve(monkeypatch, {"d": [row(12), row(13, host="evil.example.com"), row(14, Status="0")]})
    cameras = cctv_pipeline.EdmontonTrafficIngestor().fetch_data()
    assert calls[0][1]["method"] == "POST"
    assert [c["id"] for c in cameras] == ["YEG-12"]
    assert cameras[0]["media_url"] == (
        "https://cityed1-winkcdn1.winkcdn.com/2/public/hls/WF05-6212-B834-BD83-1FC4_ab.m3u8")
    assert cameras[0]["direction_facing"] == "23 Avenue & Gateway Boulevard"


def test_oregon_quotes_file_names_and_rejects_paths(monkeypatch):
    import json

    def feature(cam_id, filename, lat=44.0, title=None):
        return {"attributes": {"cameraId": cam_id, "filename": filename, "latitude": lat, "longitude": -123.0,
                               "title": title or f"Camera {cam_id}"}}

    _serve(monkeypatch, content=json.dumps({"features": [
        feature(1, "I-5@Goshen_pid1504.jpg"), feature(2, "../secret.jpg"), feature(3, "x.jpg", lat=10.0),
        feature(1, "dupe.jpg"),
        # Washington's and California's cameras come from WSDOT and Caltrans.
        feature(4, "w.jpg", lat=45.62, title="I-205 Washington - Vancouver at Mill Plain"),
        feature(5, "c.jpg", lat=41.99, title="I-5 California at Hilt"),
        feature(6, "p.jpg", lat=45.5, title="Washington County - OR217 at Scholls"),
    ]}).encode())
    cameras = cctv_pipeline.OregonTripCheckIngestor().fetch_data()
    assert [c["id"] for c in cameras] == ["TRIPCHECK-1", "TRIPCHECK-6"]
    assert cameras[0]["media_url"] == "https://tripcheck.com/RoadCams/cams/I-5%40Goshen_pid1504.jpg"


def test_wsdot_skips_oregon_tripcheck_cameras(monkeypatch):
    def feat(cam_id, url):
        return {"attributes": {"CameraID": cam_id, "CameraTitl": "t", "ImageURL": url, "CameraOwne": "WSDOT"},
                "geometry": {"x": -122.6, "y": 45.6}}

    _serve(monkeypatch, {"features": [feat(1, "https://images.wsdot.wa.gov/sw/205vc02830.jpg"),
                                      feat(2, "https://www.tripcheck.com/RoadCams/cams/i84grand_pid584.jpg")]})
    assert [c["id"] for c in cctv_pipeline.WSDOTIngestor().fetch_data()] == ["WSDOT-1"]


def test_frame_freshness_reads_last_modified(monkeypatch):
    from email.utils import formatdate
    import time

    class Resp:
        def __init__(self, status, modified):
            self.status_code = status
            self.headers = {"Last-Modified": modified} if modified else {}

        def close(self):
            pass

    replies = {
        "https://a/new.jpg": Resp(206, formatdate(time.time() - 60, usegmt=True)),
        "https://a/old.jpg": Resp(200, formatdate(time.time() - 7 * 3600, usegmt=True)),
        "https://a/stream.cgi": Resp(200, None),
        "https://a/gone.jpg": Resp(404, None),
    }
    monkeypatch.setattr(cctv_pipeline.requests, "get", lambda url, **kw: replies[url])
    cams = [{"media_url": url} for url in replies]
    kept = cctv_pipeline._keep_fresh_frames(cams)
    assert [c["media_url"] for c in kept] == ["https://a/new.jpg", "https://a/stream.cgi"]


def test_cctv_proxy_allows_batch_three_hosts_and_profiles():
    from routers import cctv as cctv_router

    for host in ["www.drivenc.gov", "www.vegagerdin.is", "cctv-ss08.thb.gov.tw", "eismoinfo.lt",
                 "www.bizkaimove.eus", "www.webcams-dir.centre-est.developpement-durable.gouv.fr",
                 "webcam.dir-est.fr", "download.data.grandlyon.com", "www.inforoutes06.fr",
                 "inforoute.alsace.eu", "www.inforoute21.fr", "www.inforoute11.fr", "if57cam.logipro.com",
                 "gieat.viewsurf.com", "filmsgieat.viewsurf.com", "video.autostrade.it",
                 "cityed1-winkcdn1.winkcdn.com", "tripcheck.com"]:
        assert cctv_router._cctv_host_allowed(host), host
    assert not cctv_router._cctv_host_allowed("thb.gov.tw.evil.example.com")
    profile = cctv_router._cctv_proxy_profile_for_url(
        "https://eismoinfo.lt/eismoinfo-backend/image-provider/camera/last?id=72")
    assert profile.name == "eismoinfo" and profile.headers["Referer"] == "https://eismoinfo.lt/"
    profile = cctv_router._cctv_proxy_profile_for_url("https://video.autostrade.it/video-mp4_hq/dt4/a.mp4")
    assert profile.name == "dot-video" and profile.headers["Accept-Encoding"] == "identity"
    assert cctv_router._cctv_proxy_profile_for_url("https://www.drivenc.gov/map/Cctv/4020").name == "ibi-511"
    assert cctv_router._cctv_proxy_profile_for_url(
        "https://cityed1-winkcdn1.winkcdn.com/2/public/hls/x.m3u8").name == "dot-hls"
    assert cctv_router._cctv_proxy_profile_for_url(
        "https://cctv-ss01.thb.gov.tw/T1/snapshot").name == "dot-image"
