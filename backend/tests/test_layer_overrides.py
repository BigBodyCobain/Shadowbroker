"""Tests for daemon-driven native layer overrides.

Overrides are an additive map that merges on top of the operator's
``active_layers`` state. They gate fetchers via ``is_any_active`` and are
merged into the four ``data.py`` serving paths, but they never enter
``active_layers`` itself and are never persisted by the frontend.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.fetchers._store import (
    active_layers,
    clear_layer_overrides,
    effective_layers,
    get_layer_overrides,
    is_any_active,
    set_layer_overrides,
)


@pytest.fixture(autouse=True)
def _restore_layer_state():
    """Overrides and operator state must not leak between tests."""
    before = dict(active_layers)
    clear_layer_overrides()
    yield
    clear_layer_overrides()
    active_layers.clear()
    active_layers.update(before)


class TestStoreAccessors:
    def test_override_activates_layer_the_operator_turned_off(self):
        active_layers["military"] = False
        assert is_any_active("military") is False

        set_layer_overrides({"military": True}, 120)

        assert is_any_active("military") is True
        assert get_layer_overrides() == {"military": True}

    def test_override_does_not_mutate_operator_state(self):
        active_layers["military"] = False
        set_layer_overrides({"military": True}, 120)

        assert active_layers["military"] is False
        assert effective_layers()["military"] is True

    def test_override_expires_after_ttl(self):
        import time as _time

        active_layers["military"] = False
        set_layer_overrides({"military": True}, 120)
        assert is_any_active("military") is True

        later = _time.monotonic() + 121
        with patch("services.fetchers._store.time.monotonic", return_value=later):
            assert get_layer_overrides() == {}
            assert is_any_active("military") is False

        # Expiry is sticky — the map was cleared, not merely hidden.
        assert get_layer_overrides() == {}

    def test_clear_restores_operator_view(self):
        active_layers["military"] = False
        set_layer_overrides({"military": True}, 120)
        assert is_any_active("military") is True

        clear_layer_overrides()

        assert get_layer_overrides() == {}
        assert is_any_active("military") is False

    def test_unknown_keys_are_rejected(self):
        accepted = set_layer_overrides({"military": True, "not_a_layer": True}, 120)

        assert accepted == {"military": True}
        assert "not_a_layer" not in get_layer_overrides()
        assert "not_a_layer" not in effective_layers()

    def test_ttl_is_capped(self):
        active_layers["military"] = False
        set_layer_overrides({"military": True}, 10_000_000)

        import time as _time

        later = _time.monotonic() + 3601
        with patch("services.fetchers._store.time.monotonic", return_value=later):
            assert get_layer_overrides() == {}

    def test_empty_override_map_is_a_no_op(self):
        assert get_layer_overrides() == {}
        assert effective_layers() == dict(active_layers)

    def test_setting_bumps_active_layers_version(self):
        from services.fetchers._store import get_active_layers_version

        before = get_active_layers_version()
        set_layer_overrides({"military": True}, 120)
        assert get_active_layers_version() > before

        mid = get_active_layers_version()
        clear_layer_overrides()
        assert get_active_layers_version() > mid


class TestServingPaths:
    """The audit finding: ~70 payload filters read the local ``active_layers``.

    Gating the fetcher is not enough — the response builder must see the
    merged map too, or the payload is stripped on the way out.
    """

    def test_bootstrap_critical_includes_overridden_layer(self, client):
        active_layers["military"] = False
        with patch(
            "services.fetchers._store.get_latest_data_subset_refs",
            side_effect=lambda *keys: {k: ([{"id": "x"}] if k == "military_flights" else None) for k in keys},
        ):
            off = client.get("/api/bootstrap/critical").json()
            assert off["military_flights"] == []

            set_layer_overrides({"military": True}, 120)
            on = client.get("/api/bootstrap/critical").json()

        assert on["military_flights"] == [{"id": "x"}]

    def test_fast_path_includes_overridden_layer(self, client):
        active_layers["military"] = False
        with patch(
            "services.fetchers._store.get_latest_data_subset_refs",
            side_effect=lambda *keys: {k: ([{"id": "x"}] if k == "military_flights" else None) for k in keys},
        ):
            off = client.get("/api/live-data/fast").json()
            assert off["military_flights"] == []

            set_layer_overrides({"military": True}, 120)
            on = client.get("/api/live-data/fast").json()

        assert on["military_flights"] == [{"id": "x"}]

    def test_slow_path_includes_overridden_layer(self, client):
        active_layers["volcanoes"] = False
        with patch(
            "services.fetchers._store.get_latest_data_subset_refs",
            side_effect=lambda *keys: {k: ([{"id": "v"}] if k == "volcanoes" else None) for k in keys},
        ):
            off = client.get("/api/live-data/slow").json()
            assert off["volcanoes"] == []

            set_layer_overrides({"volcanoes": True}, 120)
            on = client.get("/api/live-data/slow").json()

        assert on["volcanoes"] == [{"id": "v"}]

    def test_no_overrides_leaves_payload_unchanged(self, client):
        active_layers["military"] = True
        with patch(
            "services.fetchers._store.get_latest_data_subset_refs",
            side_effect=lambda *keys: {k: ([{"id": "x"}] if k == "military_flights" else None) for k in keys},
        ):
            baseline = client.get("/api/bootstrap/critical").json()
            clear_layer_overrides()
            again = client.get("/api/bootstrap/critical").json()

        assert baseline == again

    def test_write_path_never_sees_overrides(self, client):
        """POST /api/layers writes operator state; overrides must not bleed in."""
        active_layers["military"] = False
        set_layer_overrides({"military": True}, 120)

        r = client.post("/api/layers", json={"layers": {"cctv": True}})
        assert r.status_code == 200

        assert active_layers["military"] is False
        assert active_layers["cctv"] is True


class TestRoutes:
    def test_get_layers_reports_state_and_overrides(self, client):
        r = client.get("/api/layers")
        assert r.status_code == 200
        body = r.json()
        assert body["overrides"] == {}
        assert body["layers"]["military"] == active_layers["military"]

        set_layer_overrides({"military": True}, 120)
        assert client.get("/api/layers").json()["overrides"] == {"military": True}

    def test_put_override_route(self, client):
        r = client.put(
            "/api/ai/layer-overrides",
            json={"layers": {"military": True}, "ttl_seconds": 120},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["overrides"] == {"military": True}
        assert body["ignored"] == []
        assert get_layer_overrides() == {"military": True}

    def test_put_reports_ignored_keys(self, client):
        r = client.put(
            "/api/ai/layer-overrides",
            json={"layers": {"military": True, "not_a_layer": True}, "ttl_seconds": 120},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ignored"] == ["not_a_layer"]
        assert body["overrides"] == {"military": True}

    def test_get_override_route(self, client):
        set_layer_overrides({"military": True}, 120)
        r = client.get("/api/ai/layer-overrides")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "overrides": {"military": True}}

    def test_delete_override_route(self, client):
        set_layer_overrides({"military": True}, 120)
        r = client.delete("/api/ai/layer-overrides")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert get_layer_overrides() == {}

    def test_unsigned_remote_put_is_rejected(self, remote_client):
        r = remote_client.put(
            "/api/ai/layer-overrides",
            json={"layers": {"military": True}, "ttl_seconds": 120},
        )
        assert r.status_code == 403
        assert get_layer_overrides() == {}
