"""Regression coverage for OpenClaw layer injection."""

from services import ai_intel_store
from services.fetchers import _store


def _publish_test_layer(monkeypatch, items):
    published = list(items)
    monkeypatch.setitem(_store.latest_data, "air_quality", published)
    monkeypatch.setattr(_store, "bump_data_version", lambda: None)
    return published


def test_append_does_not_mutate_previously_published_list(monkeypatch):
    before = _publish_test_layer(monkeypatch, [{"id": "existing"}])
    result = ai_intel_store.inject_layer_data(
        "air_quality", [{"id": "injected"}], mode="append"
    )
    after = _store.latest_data["air_quality"]
    assert result["ok"] is True
    assert after is not before
    assert before == [{"id": "existing"}]
    assert [item["id"] for item in after] == ["existing", "injected"]


def test_replace_does_not_mutate_previously_published_list(monkeypatch):
    before = _publish_test_layer(
        monkeypatch,
        [{"id": "native"}, {"id": "old-injected", "_injected": True}],
    )
    result = ai_intel_store.inject_layer_data(
        "air_quality", [{"id": "new-injected"}], mode="replace"
    )
    after = _store.latest_data["air_quality"]
    assert result["ok"] is True
    assert after is not before
    assert before == [
        {"id": "native"}, {"id": "old-injected", "_injected": True}
    ]
    assert [item["id"] for item in after] == ["native", "new-injected"]


def test_replace_rejects_invalid_items_without_clearing_existing_data(monkeypatch):
    before = _publish_test_layer(
        monkeypatch,
        [{"id": "native"}, {"id": "old-injected", "_injected": True}],
    )
    result = ai_intel_store.inject_layer_data(
        "air_quality", ["not-a-mapping"], mode="replace"
    )
    assert result == {"ok": False, "detail": "no valid items provided"}
    assert _store.latest_data["air_quality"] is before


def test_unknown_mode_is_rejected_without_mutating_layer(monkeypatch):
    before = _publish_test_layer(monkeypatch, [{"id": "existing"}])
    result = ai_intel_store.inject_layer_data(
        "air_quality", [{"id": "injected"}], mode="overwrite"
    )
    assert result == {
        "ok": False, "detail": "mode must be 'append' or 'replace'"
    }
    assert _store.latest_data["air_quality"] is before
