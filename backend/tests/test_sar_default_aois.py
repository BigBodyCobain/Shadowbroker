"""The SAR layer must have watch areas on a fresh install.

``backend/data`` is not tracked in git, so no seed file can ship with the
repo. Without built-in defaults the layer had nothing to watch and both SAR
fetchers returned without doing anything.
"""

from __future__ import annotations

import json

import pytest

from services.sar import sar_aoi


@pytest.fixture()
def aoi_file(tmp_path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "sar_aois.json"
    monkeypatch.setattr(sar_aoi, "DATA_DIR", tmp_path)
    monkeypatch.setattr(sar_aoi, "AOI_FILE", path)
    monkeypatch.setattr(sar_aoi, "_aoi_cache", None)
    return path


def test_missing_file_uses_built_in_watch_points(aoi_file) -> None:
    aois = sar_aoi.load_aois(force=True)

    assert len(aois) == 5
    assert len({a.id for a in aois}) == 5
    for a in aois:
        assert a.id == a.id.strip().lower()
        assert a.name and a.description
        assert -90.0 <= a.center_lat <= 90.0
        assert -180.0 <= a.center_lon <= 180.0
        assert 1.0 <= a.radius_km <= 500.0
    assert not aoi_file.exists(), "loading must not write the operator's file"


def test_operator_file_wins_even_when_empty(aoi_file) -> None:
    aoi_file.write_text(json.dumps({"aois": []}), encoding="utf-8")
    assert sar_aoi.load_aois(force=True) == []

    aoi_file.write_text(
        json.dumps({"aois": [{"id": "Mine", "name": "Mine", "center": [1.0, 2.0], "radius_km": 10}]}),
        encoding="utf-8",
    )
    assert [a.id for a in sar_aoi.load_aois(force=True)] == ["mine"]


def test_first_edit_keeps_the_defaults_and_writes_the_file(aoi_file) -> None:
    sar_aoi.add_aoi(sar_aoi.SarAoi("extra", "Extra", "", 10.0, 20.0, 25.0))

    saved = json.loads(aoi_file.read_text(encoding="utf-8"))["aois"]
    assert len(saved) == 6
    assert [a.id for a in sar_aoi.load_aois(force=True)][-1] == "extra"

    assert sar_aoi.remove_aoi("suez-canal") is True
    remaining = [a.id for a in sar_aoi.load_aois(force=True)]
    assert "suez-canal" not in remaining
    assert len(remaining) == 5
