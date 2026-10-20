"""Snap Map OSINT — guardrails, parsing, baseline/anomaly scoring, reliability, fetch cycle."""
import json
import time

import pytest

from services.fetchers import snapmap_osint as sm
from services.fetchers._store import _data_lock, active_layers, latest_data


@pytest.fixture()
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPMAP_DB_PATH", str(tmp_path / "snap.db"))
    monkeypatch.setenv("SNAPMAP_ZONES_FILE", str(tmp_path / "zones.json"))
    monkeypatch.setenv("SNAPMAP_ARCHIVE_MEDIA", "false")
    return tmp_path


def _element(snap_id, ts, *, video=False, locality="Genève", extra=None):
    el = {
        "id": snap_id,
        "timestamp": str(int(ts * 1000)),
        "snapInfo": {
            "snapMediaType": 1 if video else 0,
            "streamingMediaInfo": {"mediaUrl": f"https://cf-st.sc-cdn.net/d/{snap_id}"},
            "title": {"fallback": locality},
        },
    }
    if extra:
        el.update(extra)
    return el


# --- guardrails -------------------------------------------------------------
def test_zone_radius_is_clamped_and_invalid_coords_rejected():
    tiny = sm.normalize_zone({"label": "Bâtiment", "lat": 46.2, "lon": 6.1, "radius_m": 50})
    huge = sm.normalize_zone({"label": "Pays", "lat": 46.2, "lon": 6.1, "radius_m": 500_000})
    assert tiny["radius_m"] == sm.MIN_RADIUS_M
    assert huge["radius_m"] == sm.MAX_RADIUS_M
    assert sm.normalize_zone({"lat": 999, "lon": 6.1}) is None
    assert sm.normalize_zone({"lat": 0, "lon": 0}) is None
    assert sm.normalize_zone({"lat": "x", "lon": 6.1}) is None


def test_zone_count_is_capped_and_ids_deduplicated():
    raw = [{"id": "z", "lat": 46.0 + i * 0.01, "lon": 6.0} for i in range(3)]
    raw += [{"id": f"z{i}", "lat": 46.0, "lon": 6.0 + i * 0.01} for i in range(60)]
    zones = sm.normalize_zones(raw)
    assert len(zones) == sm.MAX_ZONES
    assert [z["id"] for z in zones].count("z") == 1


def test_save_and_load_zones_roundtrip(tmp_store):
    saved = sm.save_zones([{"label": "Gare Cornavin", "lat": 46.21, "lon": 6.142, "radius_m": 1500}])
    assert saved[0]["id"] == "gare-cornavin"
    assert sm.load_zones() == saved


def test_interval_has_floor(monkeypatch):
    monkeypatch.setenv("SNAPMAP_OSINT_INTERVAL_MINUTES", "1")
    assert sm.scan_interval_minutes() == sm.MIN_INTERVAL_MINUTES


# --- parsing / privacy ------------------------------------------------------
def test_parse_element_drops_everything_but_whitelisted_fields():
    now = time.time()
    el = _element("abc", now, video=True, extra={
        "publicUserInfo": {"username": "someone", "displayName": "Some One"},
    })
    el["snapInfo"]["publisherInfo"] = {"username": "someone"}
    parsed = sm.parse_element(el)
    assert set(parsed) == {"id", "ts", "time", "type", "url", "locality"}
    assert parsed["type"] == "video"
    assert "someone" not in json.dumps(parsed)


def test_parse_element_rejects_garbage():
    assert sm.parse_element({"id": "x"}) is None
    assert sm.parse_element({"timestamp": "123"}) is None


def test_media_host_allowlist():
    assert sm.snap_media_host_allowed("cf-st.sc-cdn.net")
    assert not sm.snap_media_host_allowed("evil.example.com")
    assert not sm.snap_media_host_allowed("sc-cdn.net.evil.com")
    assert not sm.snap_media_host_allowed(None)


# --- scoring ----------------------------------------------------------------
def test_score_anomaly_levels_and_floors():
    assert sm.score_anomaly(10, None, None)[1] == "warmup"
    assert sm.score_anomaly(4, 0.2, 0.4)[1] == "normal"  # absolute floor of 5 snaps
    assert sm.score_anomaly(12, 10, 2)[1] == "normal"
    # Poisson floor: spread = max(std=2, sqrt(10)=3.16) -> z = 7/3.16 = 2.2
    assert sm.score_anomaly(17, 10, 2)[1] == "elevated"
    assert sm.score_anomaly(20, 10, 2)[1] == "high"
    z, level = sm.score_anomaly(40, 10, 2)
    assert level == "critical" and z > 4


def test_baseline_needs_warmup_then_uses_history(tmp_store):
    now = time.time()
    assert sm.compute_baseline("z", now)[0] is None
    for i in range(1, 9):
        sm.record_reading("z", now - i * 300, 50, 10)  # all inside the ±1h seasonal bucket
    mean, std, n = sm.compute_baseline("z", now)
    assert n == 8 and mean == pytest.approx(10.0)


# --- reliability / corroboration -------------------------------------------
def test_reliability_is_c_alone_b_when_corroborated_never_a_automatically():
    assert sm.rate_reliability("high", []) == "C"
    assert sm.rate_reliability("normal", [{"layer": "news"}]) == "C"
    assert sm.rate_reliability("high", [{"layer": "news"}]) == "B"


def test_corroboration_respects_distance_and_time_window():
    now = time.time()
    zone = sm.normalize_zone({"label": "Genève", "lat": 46.2044, "lon": 6.1432, "radius_m": 2000})
    recent = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now - 1800))
    old = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now - 3 * 86400))
    snapshot = {
        "telegram_osint": {"posts": [
            {"title": "Explosion à Genève", "coords": [46.21, 6.14], "published": recent},
            {"title": "Vieux post", "coords": [46.21, 6.14], "published": old},
        ]},
        "news": [{"title": "Paris", "coords": [48.85, 2.35], "published": recent}],
        "gdelt": [],
        "firms_fires": [{"lat": 46.20, "lng": 6.15, "frp": 12.0}],
    }
    found = sm.find_corroboration(zone, snapshot, now)
    layers = {f["layer"] for f in found}
    assert layers == {"telegram_osint", "firms_fires"}
    assert next(f for f in found if f["layer"] == "telegram_osint")["title"] == "Explosion à Genève"


def test_alerts_are_deduplicated_and_confirmation_gives_a(tmp_store):
    zone = sm.normalize_zone({"label": "Zone", "lat": 46.2, "lon": 6.1})
    now = time.time()
    a1 = sm.record_alert(zone, now, "elevated", 2.5, 20, 10.0, "C", [])
    a2 = sm.record_alert(zone, now + 900, "elevated", 2.8, 22, 10.0, "B", [{"layer": "news"}])
    assert a1 == a2
    a3 = sm.record_alert(zone, now + 1800, "critical", 5.0, 50, 10.0, "C", [])
    assert a3 != a1
    alerts = {a["id"]: a for a in sm.list_alerts()}
    assert alerts[a1]["reliability"] == "B" and alerts[a1]["count_1h"] == 22
    confirmed = sm.confirm_alert(a3, "Vérifié : vidéo géolocalisée + dépêche Keystone-ATS")
    assert confirmed["reliability"] == "A" and confirmed["confirmed"] is True


# --- full fetch cycle -------------------------------------------------------
class _Resp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self.text = payload if isinstance(payload, str) else json.dumps(payload)
        self.content = self.text.encode()


def test_fetch_cycle_scores_zone_and_publishes_payload(tmp_store, monkeypatch):
    sm.save_zones([{"id": "gva", "label": "Genève", "lat": 46.2044, "lon": 6.1432, "radius_m": 2000}])
    now = time.time()
    for i in range(1, 9):  # quiet baseline ~2 snaps/hour
        sm.record_reading("gva", now - i * 900, 30, 2)

    elements = [_element(f"s{i}", now - 60 * (i % 50)) for i in range(25)]  # 25 snaps in the last hour

    calls = []

    def fake_fetch(url, method="GET", json_data=None, **kw):
        calls.append(url)
        if url.endswith("/web/getLatestTileSet"):
            return _Resp({"tileSetInfos": [{"id": {"type": "HEAT", "epoch": "123"}}]})
        if url.endswith("/web/getPlaylist"):
            assert json_data["radiusMeters"] == 2000
            return _Resp({"manifest": {"elements": elements}})
        raise AssertionError(url)

    monkeypatch.setattr(sm, "fetch_with_curl", fake_fetch)
    monkeypatch.setitem(active_layers, "snapmap_osint", True)

    payload = sm.fetch_snapmap_osint(sleep_between_zones=0)
    zone = payload["zones"][0]
    assert zone["count_1h"] == 25
    assert zone["level"] == "critical"
    assert zone["reliability"] == "C"
    assert zone["alert_id"] >= 1
    assert len(zone["media"]) == sm.MEDIA_PER_ZONE
    assert payload["anomalies"] == 1 and payload["error"] is None
    with _data_lock:
        assert latest_data["snapmap_osint"]["zones"][0]["id"] == "gva"


def test_rate_limit_keeps_previous_readings(tmp_store, monkeypatch):
    sm.save_zones([{"id": "gva", "label": "Genève", "lat": 46.2, "lon": 6.14}])
    monkeypatch.setattr(sm, "fetch_with_curl", lambda *a, **k: _Resp("Too many requests"))
    monkeypatch.setitem(active_layers, "snapmap_osint", True)
    payload = sm.fetch_snapmap_osint(sleep_between_zones=0)
    assert payload["error"] == "rate_limited"
    assert payload["zones"][0]["status"] == "error"


def test_inactive_layer_does_not_hit_upstream(tmp_store, monkeypatch):
    monkeypatch.setitem(active_layers, "snapmap_osint", False)
    monkeypatch.setattr(sm, "fetch_with_curl", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    sm.fetch_snapmap_osint(sleep_between_zones=0)


# --- API --------------------------------------------------------------------
def test_api_feed_zones_and_confirm(tmp_store, client):
    feed = client.get("/api/snapmap-feed")
    assert feed.status_code == 200 and "zones" in feed.json()

    put = client.put("/api/snapmap/zones", json={"zones": [
        {"label": "Gare", "lat": 46.21, "lon": 6.142, "radius_m": 10},
        {"label": "Invalide", "lat": 500, "lon": 6.1},
    ]})
    assert put.status_code == 200
    body = put.json()
    assert body["accepted"] == 1 and body["zones"][0]["radius_m"] == sm.MIN_RADIUS_M

    zone = sm.load_zones()[0]
    alert_id = sm.record_alert(zone, time.time(), "high", 3.5, 30, 8.0, "C", [])
    assert client.post(f"/api/snapmap/alerts/{alert_id}/confirm", json={}).status_code == 400
    ok = client.post(f"/api/snapmap/alerts/{alert_id}/confirm", json={"note": "vidéo géolocalisée"})
    assert ok.status_code == 200 and ok.json()["reliability"] == "A"
    assert client.get("/api/snapmap/media", params={"url": "https://evil.example.com/x"}).status_code == 403


def test_api_zone_writes_require_local_operator(tmp_store, remote_client):
    assert remote_client.put("/api/snapmap/zones", json={"zones": []}).status_code in (401, 403)
