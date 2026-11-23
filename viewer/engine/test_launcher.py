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
