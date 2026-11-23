"""Tests for the public bridge. Run: python -m pytest viewer/bridge -q"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge as br  # noqa: E402


def _policy(**keys):
    return br.Policy({"schema": 1, "keys": keys, "protocol_keys": ["mode", "layer_versions"]})


def _bridge(tmp_path, policy, secrets=()):
    return br.Bridge(policy, br.DirPublisher(tmp_path), set(secrets))


def _read(tmp_path, rel):
    return json.loads((tmp_path / rel).read_text(encoding="utf-8"))


def test_real_policy_file_loads_and_withholds_private_layers():
    policy = br.Policy.load(br.DEFAULT_POLICY)
    assert policy.is_public("commercial_flights", "fast")
    assert not policy.is_public("commercial_flights", "slow")
    for key in ("cctv", "stocks", "telegram_osint", "scanners", "kiwisdr", "liveuamap"):
        assert not policy.is_public(key, "fast") and not policy.is_public(key, "slow"), key
    # Every engine switch that feeds a withheld or private surface stays off.
    for gate in ("ai_intel", "sar", "scanners", "kiwisdr", "sigint_aprs", "telegram_osint", "cctv"):
        assert policy.engine_layers[gate] is False, gate


def test_unknown_and_withheld_keys_never_published(tmp_path):
    policy = _policy(
        ships={"tier": "fast", "public": True},
        stocks={"tier": "fast", "public": False},
    )
    payload = {
        "mode": "snapshot",
        "ships": [{"name": "A"}],
        "stocks": {"X": 1},
        "operator_handle": "vance",  # a key nobody listed
    }
    report = _bridge(tmp_path, policy).publish_tier("fast", payload)
    bundle = _read(tmp_path, "fast.json")
    assert bundle == {"ships": [{"name": "A"}]}
    assert report["unknown"] == ["operator_handle"]
    assert report["withheld"] == ["stocks"]


def test_key_is_only_published_in_its_own_tier(tmp_path):
    policy = _policy(news={"tier": "slow", "public": True})
    _bridge(tmp_path, policy).publish_tier("fast", {"news": [1]})
    assert _read(tmp_path, "fast.json") == {}


def test_source_filter_and_field_drop(tmp_path):
    policy = _policy(
        sigint={"tier": "fast", "public": True, "only_sources": ["meshtastic"], "drop_fields": ["text"]},
    )
    payload = {
        "sigint": [
            {"source": "meshtastic", "callsign": "!abc", "text": "private chat"},
            {"source": "aprs", "callsign": "N0CALL"},
        ]
    }
    _bridge(tmp_path, policy).publish_tier("fast", payload)
    assert _read(tmp_path, "fast.json") == {"sigint": [{"source": "meshtastic", "callsign": "!abc"}]}


@pytest.mark.parametrize(
    "url",
    [
        "https://cam.example/live.m3u8?token=abc123",
        "https://cam.example/snap.jpg?api_key=abc123&x=1",
        "https://user:pw@cam.example/snap.jpg",
        "https://bucket.s3.amazonaws.com/x?X-Amz-Signature=deadbeef",
    ],
)
def test_credential_urls_are_blanked(tmp_path, url):
    policy = _policy(cams={"tier": "fast", "public": True})
    report = _bridge(tmp_path, policy).publish_tier("fast", {"cams": [{"url": url, "name": "c"}]})
    assert _read(tmp_path, "fast.json") == {"cams": [{"url": "", "name": "c"}]}
    assert report["urls_blanked"] == 1


def test_plain_urls_and_credential_named_fields(tmp_path):
    policy = _policy(cams={"tier": "fast", "public": True})
    payload = {"cams": [{"url": "https://cam.example/snap.jpg?size=big", "api_key": "abc", "nested": {"token": "t"}}]}
    _bridge(tmp_path, policy).publish_tier("fast", payload)
    assert _read(tmp_path, "fast.json") == {"cams": [{"url": "https://cam.example/snap.jpg?size=big", "nested": {}}]}


def test_configured_secret_in_output_drops_the_whole_cycle(tmp_path):
    secret = "sk-live-0123456789abcdef"
    policy = _policy(news={"tier": "slow", "public": True}, gdelt={"tier": "slow", "public": True})
    bridge = _bridge(tmp_path, policy, secrets=[secret])
    with pytest.raises(br.BridgeRefusal) as exc:
        bridge.publish_tier("slow", {"news": [{"title": "ok"}], "gdelt": [{"debug": f"called with {secret}"}]})
    assert secret not in str(exc.value)
    assert not (tmp_path / "slow.json").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_secret_values_come_from_secret_named_env_only(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "OPENSKY_CLIENT_SECRET='abcd1234efgh5678'\nAIS_API_KEY=zzzzzzzz99\nMESH_NODE_MODE=perimeter-mode\nSHORT_KEY=abc\n",
        encoding="utf-8",
    )
    values = br.load_secret_values([env], environ={"ADMIN_KEY": "admin-key-value-1", "PATH": "/usr/bin:/bin"})
    assert values == {"abcd1234efgh5678", "zzzzzzzz99", "admin-key-value-1"}


def test_heavy_key_gets_own_file_and_manifest_tracks_versions(tmp_path):
    policy = _policy(sigint={"tier": "fast", "public": True}, ships={"tier": "fast", "public": True})
    bridge = _bridge(tmp_path, policy)
    heavy = [{"callsign": f"!{i:08x}", "lat": 1.0, "lng": 2.0} for i in range(4000)]
    bridge.publish_tier("fast", {"sigint": heavy, "ships": [{"name": "A"}]})
    bridge.write_manifest()

    manifest = _read(tmp_path, "manifest.json")
    assert manifest["schema"] == 1 and manifest["seq"] == 1
    assert manifest["keys"]["sigint"]["f"] == "k/sigint.json"
    assert manifest["keys"]["sigint"]["count"] == 4000
    assert _read(tmp_path, "k/sigint.json") == heavy
    assert _read(tmp_path, "fast.json") == {"ships": [{"name": "A"}]}

    v1 = manifest["keys"]["sigint"]["v"]
    mtime = (tmp_path / "k/sigint.json").stat().st_mtime_ns
    bridge.publish_tier("fast", {"sigint": heavy, "ships": [{"name": "B"}]})
    bridge.write_manifest()
    manifest = _read(tmp_path, "manifest.json")
    assert manifest["keys"]["sigint"]["v"] == v1
    assert (tmp_path / "k/sigint.json").stat().st_mtime_ns == mtime  # unchanged: not rewritten
    assert manifest["seq"] == 2

    # Shrinks back into the bundle: its own file is removed.
    bridge.publish_tier("fast", {"sigint": heavy[:2], "ships": []})
    bridge.write_manifest()
    assert "sigint" not in _read(tmp_path, "manifest.json")["keys"]
    assert not (tmp_path / "k/sigint.json").exists()
    assert len(_read(tmp_path, "fast.json")["sigint"]) == 2


def test_freshness_is_merged_across_tiers(tmp_path):
    policy = _policy(freshness={"tier": "both", "public": True})
    bridge = _bridge(tmp_path, policy)
    bridge.publish_tier("fast", {"freshness": {"ships": "t1"}})
    bridge.publish_tier("slow", {"freshness": {"news": "t2"}})
    assert _read(tmp_path, "slow.json") == {"freshness": {"ships": "t1", "news": "t2"}}


@pytest.mark.parametrize(
    "url",
    ["https://engine.example.com", "http://10.0.0.5:8011", "http://0.0.0.0:8011", "https://127.0.0.1:8011"],
)
def test_engine_must_be_loopback(url):
    with pytest.raises(br.BridgeRefusal):
        br.check_engine_url(url)


def test_loopback_engine_accepted():
    assert br.check_engine_url("http://127.0.0.1:8011/") == "http://127.0.0.1:8011"
