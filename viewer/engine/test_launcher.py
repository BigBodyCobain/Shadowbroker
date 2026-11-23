"""Tests for the public engine launcher. Run: python -m pytest viewer/engine -q"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_public_engine as launcher  # noqa: E402


def _policy(tmp_path, **aprs):
    path = tmp_path / "public-layers.json"
    path.write_text(json.dumps({"aprs_listen": aprs, "engine_keys": ["AIS_API_KEY"]}), encoding="utf-8")
    return path


def test_aprs_listen_is_receive_only_and_bounded(tmp_path):
    env = {
        "APRS_IS_PRIVATE_SERVER": "true",
        "APRS_IS_FILTER": "t/poimqstunw",
        "APRS_IS_HOST": "example.invalid",
        "APRS_IS_CALLSIGN": "W1AW",
    }
    summary = launcher.apply_aprs_listen(_policy(tmp_path, enabled=True, lat=40.7, lon=-74.0, radius_km=9000), env)
    assert summary.startswith("on, 500 km")
    assert env["APRS_IS_ENABLED"] == "true"
    assert env["APRS_IS_RADIUS_KM"] == "500"
    assert env["APRS_IS_CALLSIGN"] == "N0CALL"
    # Nothing inherited that could widen the feed or point it elsewhere.
    for name in ("APRS_IS_PRIVATE_SERVER", "APRS_IS_FILTER", "APRS_IS_HOST"):
        assert name not in env


def test_aprs_listen_adds_bounded_extra_regions(tmp_path):
    more = [
        {"name": "London", "lat": 51.5074, "lon": -0.1278, "radius_km": 9000},
        {"lat": "x", "lon": 1},
        {"lat": 95, "lon": 0, "radius_km": 100},
        "not a region",
        {"lat": 35.6762, "lon": 139.6503},
    ]
    env = {"APRS_IS_EXTRA_RANGES": "0,0,500", "APRS_IS_MAX_SIGNALS": "99999"}
    summary = launcher.apply_aprs_listen(_policy(tmp_path, enabled=True, lat=40.7, lon=-74.0, radius_km=500, more=more), env)
    assert summary.endswith("2 more region(s)")
    # Bad entries are dropped, radius is capped, the default radius is small.
    assert env["APRS_IS_EXTRA_RANGES"] == "51.50740,-0.12780,500;35.67620,139.65030,100"
    assert env["APRS_IS_MAX_SIGNALS"] == "15000"

    many = [{"lat": 10 + n, "lon": 10, "radius_km": 50} for n in range(20)]
    env = {}
    launcher.apply_aprs_listen(_policy(tmp_path, enabled=True, lat=40.7, lon=-74.0, more=many), env)
    assert len(env["APRS_IS_EXTRA_RANGES"].split(";")) == 8

    # One region only: nothing inherited, nothing added.
    env = {"APRS_IS_EXTRA_RANGES": "0,0,500", "APRS_IS_MAX_SIGNALS": "99999"}
    launcher.apply_aprs_listen(_policy(tmp_path, enabled=True, lat=40.7, lon=-74.0), env)
    assert "APRS_IS_EXTRA_RANGES" not in env and "APRS_IS_MAX_SIGNALS" not in env


def _layers_policy(tmp_path, **layers):
    path = tmp_path / "public-layers.json"
    path.write_text(json.dumps({"engine_layers": layers}), encoding="utf-8")
    return path


def test_radar_layer_uses_no_account_and_never_broadcasts(tmp_path):
    inherited = {
        "MESH_SAR_EARTHDATA_USER": "someone",
        "MESH_SAR_EARTHDATA_TOKEN": "token-value",
        "MESH_SAR_COPERNICUS_TOKEN": "token-value",
        "MESH_SAR_REQUIRE_PRIVATE_TIER": "false",
        "MESH_SAR_OPENCLAW_ENABLED": "true",
    }
    env = dict(inherited)
    assert launcher.apply_radar(_layers_policy(tmp_path, sar=True), env).startswith("on")
    assert env["MESH_SAR_PRODUCTS_FETCH"] == "allow"
    assert env["MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE"] == "true"
    assert env["MESH_SAR_CATALOG_ENABLED"] == "true"
    assert env["MESH_SAR_REQUIRE_PRIVATE_TIER"] == "true"
    assert env["MESH_SAR_OPENCLAW_ENABLED"] == "false"
    for name in ("MESH_SAR_EARTHDATA_USER", "MESH_SAR_EARTHDATA_TOKEN", "MESH_SAR_COPERNICUS_TOKEN"):
        assert name not in env

    for policy in (_layers_policy(tmp_path, sar=False), _layers_policy(tmp_path)):
        env = dict(inherited, MESH_SAR_PRODUCTS_FETCH="allow", MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE="true")
        assert launcher.apply_radar(policy, env) == "off"
        assert env["MESH_SAR_PRODUCTS_FETCH"] == "block"
        assert env["MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE"] == "false"
        assert env["MESH_SAR_CATALOG_ENABLED"] == "false"
        assert "MESH_SAR_EARTHDATA_TOKEN" not in env


def test_aprs_listen_off_by_default_and_on_bad_input(tmp_path):
    env = {"APRS_IS_ENABLED": "true", "APRS_IS_LAT": "1", "APRS_IS_LON": "2"}
    assert launcher.apply_aprs_listen(_policy(tmp_path), env) == "off"
    assert env == {"APRS_IS_ENABLED": "false"}
    for bad in ({"enabled": True}, {"enabled": True, "lat": "x", "lon": 1}, {"enabled": True, "lat": 95, "lon": 0}):
        env = {}
        assert launcher.apply_aprs_listen(_policy(tmp_path, **bad), env).startswith("off")
        assert env == {"APRS_IS_ENABLED": "false"}


def test_borrow_feed_keys_reads_only_listed_names(tmp_path, monkeypatch):
    env_file = tmp_path / "other-install.env"
    env_file.write_text("AIS_API_KEY=ais-value-123\nADMIN_KEY=admin-value-456\nexport OTHER=x\n", encoding="utf-8")
    monkeypatch.delenv("AIS_API_KEY", raising=False)
    monkeypatch.delenv("ADMIN_KEY", raising=False)
    try:
        loaded = launcher.borrow_feed_keys(env_file, _policy(tmp_path))
        assert loaded == ["AIS_API_KEY"]
        assert os.environ["AIS_API_KEY"] == "ais-value-123"
        assert "ADMIN_KEY" not in os.environ
    finally:
        os.environ.pop("AIS_API_KEY", None)


def test_real_policy_aprs_region_is_valid():
    cfg = json.loads((Path(__file__).resolve().parents[1] / "public-layers.json").read_text(encoding="utf-8"))
    aprs = cfg["aprs_listen"]
    assert 1 <= aprs["radius_km"] <= launcher.APRS_MAX_RADIUS_KM
    assert -90 <= aprs["lat"] <= 90 and -180 <= aprs["lon"] <= 180
