"""DeepState GitHub mirror pinning (#362)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import services.geopolitics as gp


def test_deepstate_mirror_ref_defaults(monkeypatch):
    monkeypatch.delenv("DEEPSTATE_MIRROR_COMMIT", raising=False)
    monkeypatch.delenv("DEEPSTATE_MIRROR_REPO", raising=False)
    repo, ref = gp._deepstate_mirror_ref()
    assert repo == "cyterat/deepstate-map-data"
    assert ref == "main"


def test_deepstate_mirror_ref_pinned_commit(monkeypatch):
    monkeypatch.setenv("DEEPSTATE_MIRROR_COMMIT", "abc123def456")
    monkeypatch.setenv("DEEPSTATE_MIRROR_REPO", "cyterat/deepstate-map-data")
    repo, ref = gp._deepstate_mirror_ref()
    assert repo == "cyterat/deepstate-map-data"
    assert ref == "abc123def456"


def test_fetch_ukraine_frontlines_uses_pinned_tree_url(monkeypatch):
    monkeypatch.setenv("DEEPSTATE_MIRROR_COMMIT", "deadbeef")
    gp.frontline_cache.clear()

    tree_resp = MagicMock(status_code=200)
    tree_resp.json.return_value = {
        "tree": [{"path": "data/deepstatemap_data_20260101.geojson"}]
    }
    geo_resp = MagicMock(status_code=200)
    geo_resp.json.return_value = {"features": []}

    with patch("services.geopolitics.requests.get", side_effect=[tree_resp, geo_resp]) as get:
        result = gp.fetch_ukraine_frontlines()

    assert result == {"features": []}
    tree_call = get.call_args_list[0][0][0]
    raw_call = get.call_args_list[1][0][0]
    assert "/git/trees/deadbeef" in tree_call
    assert "raw.githubusercontent.com/cyterat/deepstate-map-data/deadbeef/" in raw_call

    gp.frontline_cache.clear()
