"""Datacenters load from static JSON regardless of layer toggle."""
from services.fetchers import _store
from services.fetchers.infrastructure import fetch_datacenters


def test_fetch_datacenters_populates_store_when_layer_disabled(monkeypatch):
    monkeypatch.setitem(_store.active_layers, "datacenters", False)
    _store.latest_data["datacenters"] = []
    fetch_datacenters()
    assert len(_store.latest_data.get("datacenters") or []) > 0
