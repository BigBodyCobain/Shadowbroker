"""Regression coverage for public and OpenClaw telemetry injection paths."""

import pytest
from fastapi import HTTPException

from routers import ai_intel
from services.fetchers import _store
from services.openclaw_channel import _dispatch_command


def _publish(monkeypatch, items):
    published = list(items)
    monkeypatch.setitem(_store.latest_data, "air_quality", published)
    monkeypatch.setattr(_store, "bump_data_version", lambda: None)
    return published


def test_openclaw_rejects_unknown_mode_without_mutation(monkeypatch):
    before = _publish(monkeypatch, [{"id": "existing"}])
    result = _dispatch_command(
        "inject_data",
        {"layer": "air_quality", "items": [{"id": "new"}], "mode": "overwrite"},
    )
    assert result == {"ok": False, "detail": "mode must be 'append' or 'replace'"}
    assert _store.latest_data["air_quality"] is before


def test_openclaw_all_invalid_replace_preserves_existing(monkeypatch):
    before = _publish(
        monkeypatch,
        [{"id": "native"}, {"id": "old", "_injected": True}],
    )
    result = _dispatch_command(
        "inject_data",
        {"layer": "air_quality", "items": ["invalid"], "mode": "replace"},
    )
    assert result == {"ok": False, "detail": "no valid items provided"}
    assert _store.latest_data["air_quality"] is before


def test_openclaw_valid_replace_preserves_native_non_mapping_entries(monkeypatch):
    _publish(
        monkeypatch,
        ["native-marker", {"id": "native"}, {"id": "old", "_injected": True}],
    )
    result = _dispatch_command(
        "inject_data",
        {"layer": "air_quality", "items": [{"id": "new"}], "mode": "replace"},
    )
    assert result["ok"] is True
    after = _store.latest_data["air_quality"]
    assert after[0] == "native-marker"
    assert after[1] == {"id": "native"}
    assert after[2]["id"] == "new"


@pytest.mark.asyncio
async def test_rest_rejects_unknown_mode_without_mutation(monkeypatch):
    before = _publish(monkeypatch, [{"id": "existing"}])
    body = ai_intel.InjectRequest(
        layer="air_quality", items=[{"id": "new"}], mode="overwrite"
    )
    with pytest.raises(HTTPException) as exc_info:
        await ai_intel.inject_data(None, body)
    assert exc_info.value.status_code == 400
    assert _store.latest_data["air_quality"] is before


@pytest.mark.asyncio
async def test_rest_empty_and_all_invalid_replace_preserve_existing(monkeypatch):
    for invalid_items in ([], ["invalid"]):
        before = _publish(
            monkeypatch,
            [{"id": "native"}, {"id": "old", "_injected": True}],
        )
        body = ai_intel.InjectRequest(
            layer="air_quality", items=invalid_items, mode="replace"
        )
        with pytest.raises(HTTPException) as exc_info:
            await ai_intel.inject_data(None, body)
        assert exc_info.value.status_code == 400
        assert _store.latest_data["air_quality"] is before


@pytest.mark.asyncio
async def test_rest_valid_replace_uses_shared_helper(monkeypatch):
    _publish(
        monkeypatch,
        ["native-marker", {"id": "native"}, {"id": "old", "_injected": True}],
    )
    body = ai_intel.InjectRequest(
        layer="air_quality", items=[{"id": "new"}], mode="replace"
    )
    result = await ai_intel.inject_data(None, body)
    assert result["ok"] is True
    assert result["mode"] == "replace"
    assert result["injected"] == 1
    assert result["total"] == 3
    after = _store.latest_data["air_quality"]
    assert after[0] == "native-marker"
    assert after[1] == {"id": "native"}
    assert after[2]["id"] == "new"
