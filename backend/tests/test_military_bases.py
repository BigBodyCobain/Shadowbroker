"""Tests for military bases data and fetcher."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from services.fetchers._store import latest_data, _data_lock


BASES_PATH = Path(__file__).parent.parent / "data" / "military_bases.json"


class TestMilitaryBasesData:
    """Validate the static military_bases.json file."""

    def test_json_file_exists(self):
        assert BASES_PATH.exists()

    def test_all_entries_have_required_fields(self):
        raw = json.loads(BASES_PATH.read_text(encoding="utf-8"))
        assert len(raw) > 0
        for entry in raw:
            assert "name" in entry and entry["name"]
            assert "country" in entry and entry["country"]
            assert "operator" in entry and entry["operator"]
            assert "branch" in entry and entry["branch"]
            assert "lat" in entry and isinstance(entry["lat"], (int, float))
            assert "lng" in entry and isinstance(entry["lng"], (int, float))

    def test_coordinates_in_valid_range(self):
        raw = json.loads(BASES_PATH.read_text(encoding="utf-8"))
        for entry in raw:
            assert -90 <= entry["lat"] <= 90, f"{entry['name']} has invalid lat"
            assert -180 <= entry["lng"] <= 180, f"{entry['name']} has invalid lng"

    def test_branch_values_are_known(self):
        known_branches = {
            "air_force", "navy", "marines", "army", "gsdf", "msdf", "asdf",
            "missile", "nuclear", "kpa_army", "kpa_air_force", "kpa_navy",
        }
        raw = json.loads(BASES_PATH.read_text(encoding="utf-8"))
        for entry in raw:
            assert entry["branch"] in known_branches, f"{entry['name']} has unknown branch: {entry['branch']}"

    def test_adversary_bases_present(self):
        raw = json.loads(BASES_PATH.read_text(encoding="utf-8"))
        countries = {entry["country"] for entry in raw}
        for expected in ("China", "Russia", "North Korea", "Taiwan"):
            assert expected in countries, f"Missing bases for {expected}"

    def test_no_duplicate_names(self):
        raw = json.loads(BASES_PATH.read_text(encoding="utf-8"))
        names = [entry["name"] for entry in raw]
        assert len(names) == len(set(names)), "Duplicate base names found"


class TestFetchMilitaryBases:
    """Test the fetcher populates latest_data correctly."""

    def test_fetch_populates_store(self):
        from services.fetchers.infrastructure import fetch_military_bases
        fetch_military_bases()
        with _data_lock:
            bases = latest_data["military_bases"]
        assert len(bases) > 0
        assert all("name" in b and "lat" in b and "lng" in b for b in bases)

    def test_includes_key_bases(self):
        from services.fetchers.infrastructure import fetch_military_bases
        fetch_military_bases()
        with _data_lock:
            names = {b["name"] for b in latest_data["military_bases"]}
        assert "Kadena Air Base" in names
        assert "Fleet Activities Yokosuka" in names
        assert "Andersen Air Force Base" in names

    def test_includes_jsdf_bases(self):
        from services.fetchers.infrastructure import fetch_military_bases
        fetch_military_bases()
        with _data_lock:
            names = {b["name"] for b in latest_data["military_bases"]}
        assert "Yonaguni Garrison" in names
        assert "Naha Air Base" in names
        assert "Kure Naval Base" in names

    def test_includes_north_korea_facilities(self):
        from services.fetchers.infrastructure import fetch_military_bases
        fetch_military_bases()
        with _data_lock:
            names = {b["name"] for b in latest_data["military_bases"]}
        assert "Sohae Satellite Launching Station" in names
        assert "Yongbyon Nuclear Complex" in names
        assert "Punggye-ri Nuclear Test Site" in names
        assert "Kaechon Air Base" in names

    def test_north_korea_facility_count(self):
        from services.fetchers.infrastructure import fetch_military_bases
        fetch_military_bases()
        with _data_lock:
            nk = [b for b in latest_data["military_bases"] if b.get("country") == "North Korea"]
        assert len(nk) >= 15

    def test_north_korea_branches(self):
        from services.fetchers.infrastructure import fetch_military_bases
        fetch_military_bases()
        with _data_lock:
            nk_branches = {b["branch"] for b in latest_data["military_bases"] if b.get("country") == "North Korea"}
        assert "missile" in nk_branches
        assert "nuclear" in nk_branches

    def test_colocated_bases_have_separate_entries(self):
        from services.fetchers.infrastructure import fetch_military_bases
        fetch_military_bases()
        with _data_lock:
            misawa_entries = [b for b in latest_data["military_bases"] if "Misawa" in b["name"]]
        assert len(misawa_entries) == 2, f"Expected 2 Misawa entries, got {len(misawa_entries)}"
