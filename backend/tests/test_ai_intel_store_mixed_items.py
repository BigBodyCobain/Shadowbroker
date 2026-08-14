"""Regression coverage for mixed native entries during injected-data cleanup."""

from services import ai_intel_store
from services.fetchers import _store


def _publish_mixed_layer(monkeypatch):
    published = [
        "native-sentinel",
        {"id": "native"},
        {"id": "old-injected", "_injected": True},
    ]
    monkeypatch.setitem(_store.latest_data, "air_quality", published)
    monkeypatch.setattr(_store, "bump_data_version", lambda: None)
    return published


def test_replace_preserves_non_mapping_native_entries(monkeypatch):
    before = _publish_mixed_layer(monkeypatch)

    result = ai_intel_store.inject_layer_data(
        "air_quality",
        [{"id": "new-injected"}],
        mode="replace",
    )

    after = _store.latest_data["air_quality"]
    assert result["ok"] is True
    assert after is not before
    assert after[0] == "native-sentinel"
    assert [item.get("id") for item in after if isinstance(item, dict)] == [
        "native",
        "new-injected",
    ]


def test_clear_preserves_non_mapping_native_entries(monkeypatch):
    _publish_mixed_layer(monkeypatch)

    result = ai_intel_store.clear_injected_data("air_quality")

    assert result == {"ok": True, "removed": 1}
    assert _store.latest_data["air_quality"] == [
        "native-sentinel",
        {"id": "native"},
    ]
