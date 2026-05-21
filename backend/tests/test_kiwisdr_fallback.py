"""Issue #206 (tg12): KiwiSDR upstream is HTTP-only and cannot be upgraded
to TLS. We defend with content validation + a bundled static directory
so the layer always renders something useful and a MITM injecting
garbage can't corrupt the map.
"""
import json
from pathlib import Path

import pytest

from services import kiwisdr_fetcher
from services.kiwisdr_fetcher import (
    _MIN_HEALTHY_RECEIVER_COUNT,
    _load_bundled_fallback,
    _validate_fetched_nodes,
)


def test_bundled_fallback_file_exists_and_is_nonempty():
    """The codebase ships a static snapshot for last-resort use."""
    bundle = _load_bundled_fallback()
    assert isinstance(bundle, list)
    assert len(bundle) >= _MIN_HEALTHY_RECEIVER_COUNT


def test_validation_rejects_too_few_entries():
    too_short = [{"name": "x", "lat": 0.0, "lon": 0.0, "url": ""}] * (_MIN_HEALTHY_RECEIVER_COUNT - 1)
    assert _validate_fetched_nodes(too_short) is False


def test_validation_accepts_healthy_response():
    healthy = [
        {"name": f"Receiver {i}", "lat": 50.0, "lon": -1.0, "url": "http://example"}
        for i in range(_MIN_HEALTHY_RECEIVER_COUNT)
    ]
    assert _validate_fetched_nodes(healthy) is True


def test_validation_rejects_non_list():
    assert _validate_fetched_nodes(None) is False  # type: ignore[arg-type]
    assert _validate_fetched_nodes("a string") is False  # type: ignore[arg-type]
    assert _validate_fetched_nodes({}) is False  # type: ignore[arg-type]


def test_validation_rejects_too_many_malformed_entries():
    """If more than 5% of entries lack a name or numeric lat, reject."""
    nodes = []
    # 100 entries, 20 of them malformed — well over the 5% threshold.
    for i in range(_MIN_HEALTHY_RECEIVER_COUNT + 50):
        if i % 5 == 0:
            nodes.append({})  # missing name + lat
        else:
            nodes.append({"name": f"R{i}", "lat": 50.0, "lon": -1.0, "url": ""})
    assert _validate_fetched_nodes(nodes) is False


def test_fallback_used_when_validation_fails(monkeypatch, tmp_path):
    """If a fetch returns garbage, the fallback chain reaches the bundle."""
    # Force disk cache miss
    fake_cache = tmp_path / "kiwisdr_cache.json"
    monkeypatch.setattr(kiwisdr_fetcher, "_CACHE_FILE", fake_cache)

    # Make fetch_with_curl return a parseable but UNHEALTHY response
    # (only 3 entries — well below the validation threshold).
    class _GarbageResp:
        status_code = 200
        text = "var kiwisdr_com = [{\"name\":\"x\",\"gps\":\"(0,0)\"}];"

    monkeypatch.setattr(
        "services.network_utils.fetch_with_curl", lambda *a, **kw: _GarbageResp()
    )

    # Bypass the @cached decorator
    kiwisdr_fetcher.kiwisdr_cache.clear()

    result = kiwisdr_fetcher.fetch_kiwisdr_nodes()
    # Should be the bundled fallback (798 entries), not the garbage (1 entry)
    assert isinstance(result, list)
    assert len(result) >= _MIN_HEALTHY_RECEIVER_COUNT
