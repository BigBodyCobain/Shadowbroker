"""Sprint 2B: Data Access and Subscription Correctness — regression tests.

Covers:
1. _store.get_latest_data_subset: deep copy prevents caller-side mutation from
   affecting the live store (nested dict items are independent copies).
2. MaplibreViewer: no longer imports useDataSnapshot (full-store subscription);
   instead imports useDataKeys with exactly the 7 map-relevant keys.
"""


# ---------------------------------------------------------------------------
# 1. _store.get_latest_data_subset — deep copy aliasing fix
# ---------------------------------------------------------------------------

class TestGetLatestDataSubsetDeepCopy:
    """Snapshot values must be fully independent of the live store."""

    def _fresh_store(self):
        """Return a reference to _store with a clean slate for testing."""
        from services.fetchers import _store
        return _store

    def test_list_mutation_does_not_affect_store(self):
        """Mutating a nested dict inside a returned list must not touch latest_data."""
        store = self._fresh_store()

        original_item = {"hex": "aaa111", "lat": 10.0, "lon": 20.0}
        with store._data_lock:
            store.latest_data["tracked_flights"] = [original_item]

        snap = store.get_latest_data_subset("tracked_flights")
        # Mutate the item in the snapshot
        snap["tracked_flights"][0]["lat"] = 999.0

        # The live store must be unchanged
        with store._data_lock:
            live = store.latest_data["tracked_flights"]
        assert live[0]["lat"] == 10.0, (
            "Caller mutation of snapshot must not propagate to latest_data"
        )

    def test_dict_mutation_does_not_affect_store(self):
        """Mutating a value inside a returned dict must not touch latest_data."""
        store = self._fresh_store()

        with store._data_lock:
            store.latest_data["stocks"] = {"SPY": {"price": 500.0}}

        snap = store.get_latest_data_subset("stocks")
        snap["stocks"]["SPY"]["price"] = 0.0

        with store._data_lock:
            live = store.latest_data["stocks"]
        assert live["SPY"]["price"] == 500.0, (
            "Caller mutation of snapshot dict must not propagate to latest_data"
        )

    def test_list_append_does_not_affect_store(self):
        """Appending to a returned list must not affect the store list."""
        store = self._fresh_store()

        with store._data_lock:
            store.latest_data["ships"] = [{"mmsi": "123456789"}]

        snap = store.get_latest_data_subset("ships")
        snap["ships"].append({"mmsi": "INJECTED"})

        with store._data_lock:
            live = store.latest_data["ships"]
        assert len(live) == 1, (
            "Appending to snapshot list must not grow latest_data list"
        )

    def test_snapshot_contains_equal_values(self):
        """The snapshot must be value-equal to the store at time of call."""
        store = self._fresh_store()

        payload = [{"id": 1, "data": {"nested": True}}]
        with store._data_lock:
            store.latest_data["news"] = payload

        snap = store.get_latest_data_subset("news")
        assert snap["news"] == payload

    def test_import_copy_present(self):
        """copy must be imported in _store (required for deepcopy)."""
        import inspect
        from services.fetchers import _store
        source = inspect.getsource(_store)
        assert "import copy" in source

    def test_deepcopy_used_not_shallow(self):
        """get_latest_data_subset must call copy.deepcopy, not list() or dict()."""
        import inspect
        from services.fetchers import _store
        source = inspect.getsource(_store.get_latest_data_subset)
        assert "copy.deepcopy" in source, (
            "get_latest_data_subset must use copy.deepcopy for isolation"
        )
        # Shallow-copy patterns must be absent from the touched path
        assert "list(value)" not in source, (
            "list(value) shallow copy must be removed from get_latest_data_subset"
        )
        assert "dict(value)" not in source, (
            "dict(value) shallow copy must be removed from get_latest_data_subset"
        )

    def test_refs_function_unchanged(self):
        """get_latest_data_subset_refs must NOT use deepcopy — it is the
        intentional read-only direct-reference hot path."""
        import inspect
        from services.fetchers import _store
        source = inspect.getsource(_store.get_latest_data_subset_refs)
        assert "copy.deepcopy" not in source, (
            "get_latest_data_subset_refs must remain a direct-reference path"
        )


# ---------------------------------------------------------------------------
# 2. MaplibreViewer.tsx — keyed subscription (source-level checks)
# ---------------------------------------------------------------------------

class TestMaplibreViewerKeyedSubscription:
    """MaplibreViewer must use useDataKeys, not useDataSnapshot."""

    _MAP_KEYS = {
        "tracked_flights",
        "news",
        "ships",
        "uavs",
        "earthquakes",
        "gdelt",
        "liveuamap",
    }

    def _read_source(self) -> str:
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "frontend", "src", "components", "MaplibreViewer.tsx",
        )
        with open(os.path.normpath(path), encoding="utf-8") as fh:
            return fh.read()

    def test_use_data_snapshot_not_imported(self):
        """MaplibreViewer must not import useDataSnapshot."""
        source = self._read_source()
        assert "useDataSnapshot" not in source, (
            "MaplibreViewer must not import or call useDataSnapshot "
            "(full-store global listener subscription)"
        )

    def test_use_data_keys_imported(self):
        """MaplibreViewer must import useDataKeys."""
        source = self._read_source()
        assert "useDataKeys" in source, (
            "MaplibreViewer must import useDataKeys for a keyed subscription"
        )

    def test_use_data_keys_called(self):
        """MaplibreViewer must call useDataKeys(...)."""
        source = self._read_source()
        assert "useDataKeys(" in source, (
            "MaplibreViewer must call useDataKeys with the map-relevant key list"
        )

    def test_all_map_keys_present_in_subscription(self):
        """Every key accessed from data must appear in the useDataKeys call."""
        source = self._read_source()
        for key in self._MAP_KEYS:
            assert f"'{key}'" in source or f'"{key}"' in source, (
                f"Key '{key}' must appear in the useDataKeys subscription list"
            )

    def test_exactly_seven_keys_in_subscription(self):
        """The subscription must cover exactly the 7 map-relevant keys — no more,
        no less — so unrelated updates do not trigger unnecessary re-renders."""
        import re
        source = self._read_source()
        # Find the useDataKeys call line
        match = re.search(r"useDataKeys\(\[([^\]]+)\]", source)
        assert match is not None, "useDataKeys call with array literal not found"
        keys_str = match.group(1)
        # Extract quoted identifiers
        found_keys = set(re.findall(r"['\"](\w+)['\"]", keys_str))
        assert found_keys == self._MAP_KEYS, (
            f"useDataKeys key set mismatch.\n"
            f"  Expected: {sorted(self._MAP_KEYS)}\n"
            f"  Found:    {sorted(found_keys)}"
        )
