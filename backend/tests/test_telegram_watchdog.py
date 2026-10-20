"""Telegram OSINT watchdog and search helpers."""

from services import openclaw_watchdog
from services.telegram_osint_text import keyword_matches_telegram_post, telegram_post_search_text


def _telegram_slow_fixture() -> dict:
    return {
        "telegram_osint": {
            "posts": [
                {
                    "id": "tg-uk-1",
                    "title": "Київ 1х БпЛА на Рембазу.",
                    "description": "Київ 1х БпЛА на Рембазу.",
                    "title_translated": "Kyiv 1x UAV on Rembazu.",
                    "description_translated": "Kyiv 1x UAV on Rembazu.",
                    "channel": "war_monitor",
                    "source": "t.me/war_monitor",
                    "link": "https://t.me/war_monitor/101",
                    "risk_score": 3,
                    "source_lang": "uk",
                },
                {
                    "id": "tg-ru-1",
                    "title": "«В Крым поедем несмотря ни на что. Это наша родина!»",
                    "description": "«В Крым поедем несмотря ни на что. Это наша родина!»",
                    "title_translated": "We will go to Crimea no matter what. This is our homeland!",
                    "description_translated": "We will go to Crimea no matter what. This is our homeland!",
                    "channel": "nexta_live",
                    "source": "t.me/nexta_live",
                    "link": "https://t.me/nexta_live/202",
                    "risk_score": 9,
                    "source_lang": "ru",
                },
            ],
            "total": 2,
        }
    }


def test_telegram_post_search_text_includes_translated_fields():
    post = _telegram_slow_fixture()["telegram_osint"]["posts"][0]
    haystack = telegram_post_search_text(post)
    assert "kyiv 1x uav on rembazu" in haystack
    assert "бпла" in haystack


def test_keyword_matches_telegram_post_searches_translated_and_original():
    post = _telegram_slow_fixture()["telegram_osint"]["posts"][1]
    assert keyword_matches_telegram_post(post, "crimea")
    assert keyword_matches_telegram_post(post, "крым")


def test_watchdog_keyword_matches_telegram_translation(monkeypatch):
    monkeypatch.setattr(openclaw_watchdog, "_ensure_running", lambda: None)
    openclaw_watchdog.clear_watches()
    try:
        watch = openclaw_watchdog.add_watch("keyword", {"keyword": "crimea"})
        alert = openclaw_watchdog._check_keyword(watch["id"], {"keyword": "crimea"}, {}, _telegram_slow_fixture())
        assert alert is not None
        assert any(match["source"] == "telegram_osint" for match in alert["data"]["matches"])
        assert alert["data"]["matches"][0]["title"].startswith("We will go to Crimea")
        # Same Telegram post should not re-alert once seen.
        assert openclaw_watchdog._check_keyword(watch["id"], {"keyword": "crimea"}, {}, _telegram_slow_fixture()) is None
    finally:
        openclaw_watchdog.clear_watches()


def test_watchdog_telegram_rhetoric_alerts_on_high_risk_posts(monkeypatch):
    monkeypatch.setattr(openclaw_watchdog, "_ensure_running", lambda: None)
    openclaw_watchdog.clear_watches()
    try:
        watch = openclaw_watchdog.add_watch("telegram_rhetoric", {"min_risk_score": 8})
        alert = openclaw_watchdog._check_telegram_rhetoric(watch["id"], {"min_risk_score": 8}, _telegram_slow_fixture())
        assert alert is not None
        assert "Telegram rhetoric alert" in alert["alert"]
        assert len(alert["data"]["matches"]) == 1
        assert alert["data"]["matches"][0]["channel"] == "nexta_live"
        assert alert["data"]["matches"][0]["risk_score"] == 9
        assert openclaw_watchdog._check_telegram_rhetoric(watch["id"], {"min_risk_score": 8}, _telegram_slow_fixture()) is None
    finally:
        openclaw_watchdog.clear_watches()


def test_watchdog_telegram_rhetoric_supports_channel_filter(monkeypatch):
    monkeypatch.setattr(openclaw_watchdog, "_ensure_running", lambda: None)
    openclaw_watchdog.clear_watches()
    try:
        watch = openclaw_watchdog.add_watch(
            "telegram_rhetoric",
            {"min_risk_score": 7, "channels": ["war_monitor"]},
        )
        alert = openclaw_watchdog._check_telegram_rhetoric(
            watch["id"],
            {"min_risk_score": 7, "channels": ["war_monitor"]},
            _telegram_slow_fixture(),
        )
        assert alert is None  # war_monitor post is only risk 3
    finally:
        openclaw_watchdog.clear_watches()