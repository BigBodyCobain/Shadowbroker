"""Regression tests for news geocoding keywords and feed configuration."""
import json
from pathlib import Path

import pytest

from services.fetchers.news import _resolve_coords
from services.news_feed_config import DEFAULT_FEEDS


CONFIG_PATH = Path(__file__).parent.parent / "config" / "news_feeds.json"


# -- Keyword resolution: East Asia specific locations --------------------------

class TestResolveCoords:
    """_resolve_coords should prefer longer (more specific) keywords."""

    def test_taiwan_strait_not_absorbed_by_taiwan(self):
        result = _resolve_coords("tensions in the taiwan strait")
        assert result == (24.0, 119.5)

    def test_south_china_sea_not_absorbed_by_china(self):
        result = _resolve_coords("south china sea patrol")
        assert result == (15.0, 115.0)

    def test_east_china_sea(self):
        result = _resolve_coords("east china sea tensions")
        assert result == (28.0, 125.0)

    def test_philippine_sea(self):
        result = _resolve_coords("philippine sea exercises")
        assert result == (20.0, 130.0)

    def test_generic_china_still_works(self):
        result = _resolve_coords("china deploys forces")
        assert result == (35.861, 104.195)

    def test_generic_taiwan_still_works(self):
        result = _resolve_coords("taiwan elections")
        assert result == (23.697, 120.960)

    def test_taipei(self):
        result = _resolve_coords("protests in taipei")
        assert result == (25.033, 121.565)

    def test_okinawa(self):
        result = _resolve_coords("okinawa base expansion")
        assert result == (26.334, 127.800)

    # -- Existing inclusion-relationship regressions ---------------------------

    def test_new_delhi_not_absorbed_by_delhi(self):
        result = _resolve_coords("new delhi summit")
        assert result == (28.613, 77.209)

    def test_south_america_not_absorbed_by_america(self):
        result = _resolve_coords("south america trade deal")
        assert result == (-14.200, -51.900)

    def test_north_korea_not_absorbed_by_south_korea(self):
        result = _resolve_coords("north korea missile launch")
        assert result == (40.339, 127.510)

    # -- Space-padded keywords -------------------------------------------------

    def test_us_with_spaces(self):
        result = _resolve_coords("the us military")
        assert result == (38.907, -77.036)

    def test_uk_with_spaces(self):
        result = _resolve_coords("visit the uk soon")
        assert result == (55.378, -3.435)

    # -- New East Asia island/strait keywords ------------------------------------

    def test_pratas(self):
        assert _resolve_coords("china patrols near pratas islands") == (20.71, 116.72)

    def test_dongsha(self):
        assert _resolve_coords("dongsha atoll tensions") == (20.71, 116.72)

    def test_kinmen(self):
        assert _resolve_coords("artillery drill near kinmen") == (24.45, 118.38)

    def test_matsu(self):
        assert _resolve_coords("matsu island cable cut") == (26.16, 119.94)

    def test_scarborough(self):
        assert _resolve_coords("scarborough shoal standoff") == (15.14, 117.77)

    def test_paracel(self):
        assert _resolve_coords("paracel islands dispute") == (16.50, 112.00)

    def test_spratly(self):
        assert _resolve_coords("spratly island reclamation") == (10.00, 114.00)

    def test_miyako_strait(self):
        assert _resolve_coords("PLAN warships transit miyako strait") == (24.78, 125.30)

    def test_bashi_channel(self):
        assert _resolve_coords("submarine detected in bashi channel") == (21.00, 121.50)

    def test_luzon_strait(self):
        assert _resolve_coords("luzon strait patrol") == (20.50, 121.50)

    def test_dmz(self):
        assert _resolve_coords("tension at the dmz border") == (38.00, 127.00)

    def test_yalu(self):
        assert _resolve_coords("troops near yalu river") == (40.00, 124.40)

    def test_yongbyon(self):
        assert _resolve_coords("activity at yongbyon reactor") == (39.80, 125.76)

    def test_wonsan(self):
        assert _resolve_coords("missile launch from wonsan") == (39.18, 127.48)

    def test_busan(self):
        assert _resolve_coords("naval exercise near busan port") == (35.18, 129.07)

    # -- No match --------------------------------------------------------------

    def test_no_match_returns_none(self):
        result = _resolve_coords("unknown location xyz")
        assert result is None


# -- Feed configuration consistency -------------------------------------------

class TestFeedConfig:
    """DEFAULT_FEEDS and news_feeds.json must stay in sync."""

    def test_default_feeds_match_json(self):
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        json_feeds = data["feeds"]

        def normalize(feeds):
            return sorted(
                [{"name": f["name"], "url": f["url"], "weight": f["weight"]} for f in feeds],
                key=lambda f: f["name"],
            )

        assert normalize(DEFAULT_FEEDS) == normalize(json_feeds)

    def test_new_east_asia_feeds_present(self):
        names = {f["name"] for f in DEFAULT_FEEDS}
        expected = {"FocusTaiwan", "Kyodo", "SCMP", "The Diplomat", "Stars and Stripes",
                    "Yonhap", "Nikkei Asia", "Taipei Times", "Asia Times", "Defense News", "Japan Times"}
        assert expected.issubset(names)
