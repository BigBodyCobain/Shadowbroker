"""Tests for the shared in-memory data store."""

import threading
import time
import pytest
from services.fetchers._store import latest_data, source_timestamps, _mark_fresh, _data_lock


class TestLatestDataStructure:
    """Verify the store has the expected keys and default values."""

    def test_has_all_required_keys(self):
        expected_keys = {
            "last_updated",
            "news",
            "stocks",
            "oil",
            "flights",
            "ships",
            "military_flights",
            "tracked_flights",
            "cctv",
            "weather",
            "earthquakes",
            "uavs",
            "frontlines",
            "gdelt",
            "liveuamap",
            "kiwisdr",
            "space_weather",
            "internet_outages",
            "firms_fires",
            "datacenters",
        }
        assert expected_keys.issubset(set(latest_data.keys()))

    def test_list_keys_default_to_empty_list(self):
        list_keys = [
            "news",
            "flights",
            "ships",
            "military_flights",
            "tracked_flights",
            "cctv",
            "earthquakes",
            "uavs",
            "gdelt",
            "liveuamap",
            "kiwisdr",
            "internet_outages",
            "firms_fires",
            "datacenters",
        ]
        for key in list_keys:
            assert isinstance(latest_data[key], list), f"{key} should default to list"

    def test_dict_keys_default_to_empty_dict(self):
        dict_keys = ["stocks", "oil"]
        for key in dict_keys:
            assert isinstance(latest_data[key], dict), f"{key} should default to dict"


class TestMarkFresh:
    """Tests for _mark_fresh timestamp helper."""

    def test_records_timestamp_for_single_key(self):
        _mark_fresh("test_key_1")
        assert "test_key_1" in source_timestamps
        assert isinstance(source_timestamps["test_key_1"], str)

    def test_records_timestamps_for_multiple_keys(self):
        _mark_fresh("multi_a", "multi_b", "multi_c")
        assert "multi_a" in source_timestamps
        assert "multi_b" in source_timestamps
        assert "multi_c" in source_timestamps

    def test_timestamps_are_iso_format(self):
        _mark_fresh("iso_test")
        ts = source_timestamps["iso_test"]
        # ISO format: YYYY-MM-DDTHH:MM:SS.ffffff
        assert "T" in ts
        assert len(ts) >= 19  # At least YYYY-MM-DDTHH:MM:SS

    def test_successive_calls_update_timestamp(self):
        _mark_fresh("update_test")
        ts1 = source_timestamps["update_test"]
        time.sleep(0.01)
        _mark_fresh("update_test")
        ts2 = source_timestamps["update_test"]
        assert ts2 >= ts1


class TestDataLock:
    """Verify the data lock works for thread safety."""

    def test_lock_exists_and_is_a_lock(self):
        assert isinstance(_data_lock, type(threading.Lock()))

    def test_concurrent_writes_dont_corrupt(self):
        """Simulate concurrent writes to latest_data through the lock."""
        errors = []

        def writer(key, value, iterations=100):
            try:
                for _ in range(iterations):
                    with _data_lock:
                        latest_data[key] = value
                        # Read back immediately — should be our value
                        assert latest_data[key] == value
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=("test_concurrent", [1, 2, 3])),
            threading.Thread(target=writer, args=("test_concurrent", [4, 5, 6])),
            threading.Thread(target=writer, args=("test_concurrent", [7, 8, 9])),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        # Restore default
        latest_data["test_concurrent"] = []
