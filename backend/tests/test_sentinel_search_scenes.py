"""Right-click dossier returns up to 3 signed Sentinel-2 scenes."""

from unittest.mock import MagicMock, patch

import pytest

from services import sentinel_search as ss


@pytest.fixture(autouse=True)
def clear_sentinel_cache():
    ss._sentinel_cache.clear()
    yield
    ss._sentinel_cache.clear()


def _stac_feature(scene_id: str, dt: str, cloud: float) -> dict:
    href = f"https://sentinel2euwest.blob.core.windows.net/sentinel2-l2a/{scene_id}.tif"
    return {
        "id": scene_id,
        "bbox": [0, 0, 1, 1],
        "properties": {
            "datetime": dt,
            "eo:cloud_cover": cloud,
            "platform": "Sentinel-2A",
        },
        "assets": {
            "rendered_preview": {"href": href},
            "thumbnail": {"href": href},
        },
    }


@patch("services.sentinel_search.requests.get")
@patch("services.sentinel_search.requests.post")
def test_search_returns_three_scenes(mock_post, mock_get):
    mock_post.return_value = MagicMock(
        ok=True,
        raise_for_status=MagicMock(),
        json=lambda: {
            "features": [
                _stac_feature("s1", "2026-05-28T10:00:00Z", 5.0),
                _stac_feature("s2", "2026-05-20T10:00:00Z", 12.0),
                _stac_feature("s3", "2026-05-10T10:00:00Z", 18.0),
            ],
        },
    )
    mock_get.return_value = MagicMock(
        ok=True,
        raise_for_status=MagicMock(),
        json=lambda: {"token": "sig=test"},
    )

    result = ss.search_sentinel2_scene(29.0, 51.0)

    assert result["found"] is True
    assert result["scene_id"] == "s1"
    assert len(result["scenes"]) == 3
    assert result["scenes"][1]["scene_id"] == "s2"
    assert "sig=test" in (result["scenes"][0]["fullres_url"] or "")


@patch("services.sentinel_search.requests.post")
def test_search_esri_fallback_has_no_scenes(mock_post):
    mock_post.return_value = MagicMock(
        ok=True,
        raise_for_status=MagicMock(),
        json=lambda: {"features": []},
    )

    result = ss.search_sentinel2_scene(29.0, 51.0)

    assert result["fallback"] is True
    assert "scenes" not in result
