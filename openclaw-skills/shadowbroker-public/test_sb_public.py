"""Tests for the ShadowBroker public skill.

Run: python -m pytest openclaw-skills/shadowbroker-public -q

The skill is tested end to end: a real bridge writes real feed files into a
temp folder, a throwaway local web server serves them, and the skill reads
them over HTTP exactly as it would read the public feed.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import sys
import threading
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "viewer" / "bridge"))

import bridge as br  # noqa: E402
import sb_public as sp  # noqa: E402

FAST = {
    "tracked_flights": [
        {"icao24": "a1b2c3", "callsign": "N189AM", "registration": "N189AM", "alert_operator": "Example Holdings",
         "type": "GLF6", "model": "GLF6", "lat": 40.0, "lng": -75.0, "alt": 12496.8, "speed_knots": 480.5,
         "heading": 90},
    ],
    "military_flights": [
        {"icao24": "ae1234", "callsign": "RCH871", "registration": "05-5140", "t": "C17", "lat": 36.9, "lng": -76.2},
        {"icao24": "ae5678", "callsign": "RCH204", "t": "C17", "lat": 51.0, "lng": 0.5},
    ],
    "commercial_flights": [
        {"icao24": "c0ffee", "callsign": "UAL12", "registration": "N12345", "lat": 36.95, "lng": -76.25},
    ],
    "private_jets": [],
    "private_flights": [],
    "ships": [
        {"mmsi": 368207620, "imo": "9811000", "name": "EVER GIVEN", "shipType": "cargo", "lat": 36.86, "lng": -76.31,
         "sog": 12.5, "course": 180},
        {"mmsi": 211514540, "name": "PILOT LABOE", "callsign": "DBLG", "lat": 54.4, "lng": 10.2},
        {"name": "USS Example (CVN-00)", "type": "carrier", "lat": 36.95, "lng": -76.33},
    ],
    "satellites": [{"id": 25544, "name": "ISS (ZARYA)", "lat": 10.0, "lng": 20.0}],
    "uavs": [],
    "sigint_totals": {"meshtastic": 3, "aprs": 1},
    "operator_handle": "must-never-be-published",
}
SLOW = {
    "news": [
        {"title": "Port of Norfolk reopens after storm", "source": "Example Wire", "link": "https://news.example/1",
         "published": "Mon, 23 Nov 2026 10:00:00 GMT", "risk_score": 4, "coords": [36.85, -76.29]},
        {"title": "Markets steady", "source": "Example Wire", "link": "https://news.example/2", "coords": [40.7, -74.0]},
    ],
    "gdelt": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-76.3, 36.9]},
         "properties": {"name": "Norfolk, Virginia, United States", "count": 4, "event_date": "20261123",
                        "_headlines_list": ["Navy exercise begins off Norfolk"],
                        "_urls_list": ["https://news.example/3"]}},
    ],
    "earthquakes": [{"id": "us1", "title": "M 4.1 - offshore", "lat": 37.5, "lng": -75.0}],
    "correlations": [{"id": "c1", "type": "rf_anomaly"}],
    "stocks": {"X": 1},
}


def _policy():
    keys = {k: {"tier": "fast", "public": True} for k in FAST if k != "operator_handle"}
    keys.update({k: {"tier": "slow", "public": True} for k in ("news", "gdelt", "earthquakes", "correlations")})
    keys["stocks"] = {"tier": "slow", "public": False}
    return br.Policy({"schema": 1, "keys": keys, "protocol_keys": []})


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture(params=[0, 1], ids=["no-index", "with-index"])
def client(tmp_path, request):
    bridge = br.Bridge(_policy(), br.DirPublisher(tmp_path), set(), index_s=request.param)
    bridge.publish_tier("fast", FAST)
    bridge.publish_tier("slow", SLOW)
    bridge.write_manifest()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield sp.ShadowBrokerPublicClient(base_url=f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()


def _ask(client, text, **kw):
    out = client.command("ask", {"text": text, **kw})
    assert out["ok"], out
    return out["data"]["route"]["recommended"]["cmd"], out["data"]["result"]["data"]


def test_where_is_a_tail_number(client):
    cmd, data = _ask(client, "where is N189AM")
    assert cmd == "find_entity" and data["resolved"]
    best = data["best_match"]
    assert best["entity_type"] == "aircraft" and best["match"] == "exact"
    assert (best["lat"], best["lng"]) == (40.0, -75.0)
    assert best["owner"] == "Example Holdings" and best["source_layer"] == "tracked_flights"


def test_where_is_a_ship_by_mmsi_and_by_name(client):
    _, by_mmsi = _ask(client, "where is the ship with mmsi 368207620")
    assert by_mmsi["best_match"]["name"] == "EVER GIVEN" and by_mmsi["best_match"]["entity_type"] == "ship"
    _, by_name = _ask(client, "where is the Ever Given boat")
    assert by_name["best_match"]["mmsi"] == 368207620
    assert by_name["best_match"]["lat"] == 36.86


def test_callsign_and_owner_lookups(client):
    _, data = _ask(client, "find flight RCH871")
    assert data["best_match"]["icao24"] == "ae1234"
    owner = client.command("find_entity", {"owner": "example holdings", "entity_type": "aircraft"})["data"]
    assert [r["registration"] for r in owner["results"]] == ["N189AM"]
    nothing = client.command("find_entity", {"query": "ZZZ999", "fallback_search": True})["data"]
    assert nothing["resolved"] is False and nothing["best_match"] is None


def test_find_flights_and_ships_match_like_the_app(client):
    flights = client.command("find_flights", {"callsign": "rch"})["data"]
    assert sorted(r["callsign"] for r in flights["results"]) == ["RCH204", "RCH871"]
    assert flights["truncated"] is False
    capped = client.command("find_flights", {"callsign": "rch", "limit": 1})["data"]
    assert len(capped["results"]) == 1 and capped["truncated"] is True
    only_mil = client.command("find_flights", {"query": "c17", "categories": ["military"]})["data"]
    assert {r["source_layer"] for r in only_mil["results"]} == {"military_flights"}
    ships = client.command("find_ships", {"name": "pilot"})["data"]["results"]
    assert ships == [{"mmsi": 211514540, "imo": "", "name": "PILOT LABOE", "owner": "", "tracked_name": "",
                      "tracked_category": "", "callsign": "DBLG", "type": "", "lat": 54.4, "lng": 10.2,
                      "speed": None, "heading": None}]


def test_entities_near_sorted_by_distance(client):
    cmd, data = _ask(client, "ships near 36.85, -76.3")
    assert cmd == "entities_near"
    labels = [r["label"] for r in data["results"]]
    assert labels[0] == "EVER GIVEN" and "PILOT LABOE" not in labels
    assert data["results"][0]["distance_km"] < 5
    assert all(a["distance_km"] <= b["distance_km"] for a, b in zip(data["results"], data["results"][1:]))
    missing = client.command("entities_near", {"lat": 36.85})
    assert missing == {"ok": False, "detail": "lat and lng required"}


def test_news_search_and_area_brief(client):
    cmd, data = _ask(client, "news about Norfolk")
    assert cmd == "search_news"
    assert {r["source_layer"] for r in data["results"]} == {"news", "gdelt"}
    assert data["results"][0]["url"] == "https://news.example/1"
    brief = client.command("brief_area", {"lat": 36.9, "lng": -76.3, "radius_km": 30, "query": "norfolk"})["data"]
    assert brief["nearby"]["results"] and brief["topic_news"]["results"]
    assert any(r["source_layer"] == "earthquakes" for r in brief["context"]["results"])


def test_summary_status_and_playbooks(client):
    summary = client.command("get_summary")["data"]
    assert summary["counts"]["ships"] == 3 and summary["counts"]["military_flights"] == 2
    assert "ships" in summary["non_empty_layers"] and "uavs" not in summary["non_empty_layers"]
    status = client.command("channel_status")["data"]
    assert status["mode"] == "public_feed" and status["read_only"] is True and status["stale"] is False
    book = client.command("run_playbook", {"name": "status_check"})["data"]
    assert [r["cmd"] for r in book["results"]] == ["channel_status", "get_summary"]
    assert client.command("run_playbook", {"name": "nope"})["ok"] is False
    sliced = client.command("get_layer_slice", {"layers": ["quakes", "stocks"]})["data"]
    assert list(sliced["layers"]) == ["earthquakes"] and sliced["not_published"] == ["stocks"]


def test_nothing_private_is_reachable(client):
    summary = client.command("get_summary")["data"]
    assert "operator_handle" not in summary["available_layers"]
    assert "stocks" not in summary["available_layers"]
    assert client.command("get_layer_slice", {"layers": ["operator_handle"]})["data"]["layers"] == {}


@pytest.mark.parametrize("cmd", sorted(sp.WRITE_COMMANDS))
def test_every_write_command_is_refused_without_any_request(client, cmd, monkeypatch):
    def no_network(*_a, **_k):
        raise AssertionError("a write command must not touch the network")

    monkeypatch.setattr(sp.urllib.request, "urlopen", no_network)
    out = client.command(cmd, {"lat": 1, "lng": 2, "label": "x", "message": "hi"})
    assert out["ok"] is False and out["public_skill"] is True
    assert "not available in the public skill" in out["detail"]


def test_async_surface_matches_the_full_skill(client):
    async def run():
        answer = await client.ask("where is N189AM")
        batch = await client.send_batch([{"cmd": "get_summary"}, {"cmd": "place_pin", "args": {}}])
        pin = await client.place_pin(lat=1, lng=2, label="x")
        return answer, batch, pin

    answer, batch, pin = asyncio.run(run())
    assert answer["data"]["result"]["data"]["resolved"] is True
    assert [r["ok"] for r in batch["results"]] == [True, False]
    assert pin["ok"] is False


@pytest.mark.parametrize(
    "url",
    ["", "http://feed.example.org/data", "https://user:pw@feed.example.org", "https://feed.example.org/x?token=1",
     "ftp://feed.example.org"],
)
def test_feed_address_must_be_plain_https(url, monkeypatch):
    monkeypatch.delenv("SHADOWBROKER_PUBLIC_URL", raising=False)
    with pytest.raises(sp.PublicSkillError):
        sp.ShadowBrokerPublicClient(base_url=url)


def test_feed_file_paths_cannot_be_redirected(client):
    with pytest.raises(sp.PublicSkillError):
        client.feed._get("../secrets.json")
    with pytest.raises(sp.PublicSkillError):
        client.feed._get("https://evil.example/x.json")


# ── Same answers as the app's own search code, on the same data ────────────

@pytest.fixture
def app_telemetry(monkeypatch):
    sys.path.insert(0, str(REPO / "backend"))
    try:
        from services import telemetry
    except Exception as exc:  # backend dependencies not installed here
        pytest.skip(f"backend not importable: {exc}")
    merged = {**FAST, **SLOW}
    monkeypatch.setattr(telemetry, "get_latest_data_subset_refs", lambda *keys: {k: merged.get(k) for k in keys})
    monkeypatch.setattr(telemetry, "get_data_version", lambda: 0)
    return telemetry


def _same_as_app(ours, theirs):
    """Our answer carries everything the app's does, value for value.

    The skill may add fields (units, totals); it must not change or drop any.
    """
    assert ours["truncated"] == theirs["truncated"]
    assert len(ours["results"]) == len(theirs["results"])
    for mine, app in zip(ours["results"], theirs["results"]):
        assert {k: mine[k] for k in app} == app


@pytest.mark.parametrize(
    "args",
    [{"callsign": "rch"}, {"query": "c17"}, {"registration": "n189"}, {"owner": "example"}, {"icao24": "C0FFEE"},
     {"query": "glf6 n189am"}, {"callsign": "rch", "limit": 1}, {"query": "ual", "categories": ["commercial"]}],
)
def test_find_flights_matches_the_app(client, app_telemetry, args):
    _same_as_app(client.command("find_flights", args)["data"], app_telemetry.find_flights(**args))


@pytest.mark.parametrize("args", [{"name": "ever"}, {"mmsi": "368207620"}, {"query": "cargo"}, {"query": "dblg"},
                                  {"imo": "9811000"}, {"query": "nothing-here"}])
def test_find_ships_matches_the_app(client, app_telemetry, args):
    _same_as_app(client.command("find_ships", args)["data"], app_telemetry.find_ships(**args))


@pytest.mark.parametrize("args", [{"lat": 36.85, "lng": -76.3, "radius_km": 50},
                                  {"lat": 36.85, "lng": -76.3, "radius_km": 5000},
                                  {"lat": 54.4, "lng": 10.2, "radius_km": 10, "entity_types": ["ships"]}])
def test_entities_near_matches_the_app(client, app_telemetry, args):
    _same_as_app(client.command("entities_near", args)["data"], app_telemetry.entities_near(**args))


def test_ask_uses_the_radius_the_user_states(client):
    for text, expected in (("ships within 30 km of 36.85, -76.30", 30.0),
                           ("what planes are inside 10 miles of 36.9, -76.2", 16.09),
                           ("ships 5 nm from 36.85, -76.30", 9.26),
                           ("ships near 36.85, -76.30", 50.0)):
        route = sp.route_query(text)
        assert route["recommended"]["cmd"] == "entities_near", text
        assert route["recommended"]["args"]["radius_km"] == expected, text
        assert (route["recommended"]["args"]["lat"], route["recommended"]["args"]["lng"]) in ((36.85, -76.3), (36.9, -76.2))


def test_nearby_reports_the_full_count_when_cut_short(client):
    data = client.command("entities_near", {"lat": 36.9, "lng": -76.3, "radius_km": 5000, "limit": 2})["data"]
    assert len(data["results"]) == 2 and data["truncated"] is True
    assert data["total"] > 2 and data["radius_km"] == 5000.0


def test_flight_results_carry_units(client):
    best = client.command("find_entity", {"registration": "N189AM"})["data"]["best_match"]
    assert best["altitude"] == 12496.8  # metres, as the app stores it
    assert best["altitude_ft"] == 41000
    assert best["speed_knots"] == 480.5 and best["model"] == "GLF6"


def test_gdelt_hits_show_the_matching_headline_and_publisher(client):
    data = client.command("search_news", {"query": "navy exercise"})["data"]
    hit = next(r for r in data["results"] if r["source_layer"] == "gdelt")
    assert hit["title"] == "Navy exercise begins off Norfolk"
    assert hit["source"] == "news.example" and hit["match"] == "headline"
    only_news = client.command("search_news", {"query": "norfolk", "include_gdelt": False})["data"]
    assert {r["source_layer"] for r in only_news["results"]} == {"news"}
