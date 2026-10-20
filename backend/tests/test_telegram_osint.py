"""Telegram OSINT HTML parsing and geoparsing."""

from services.fetchers import telegram_osint


SAMPLE_HTML = """
<div class="tgme_widget_message_wrap js-widget_message_wrap">
  <div class="tgme_widget_message_text">Missile strike reported near Kyiv overnight.</div>
  <a class="tgme_widget_message_date" href="https://t.me/osintdefender/12345">
    <time datetime="2026-06-02T12:00:00+00:00"></time>
  </a>
</div>
</div>
</div>
"""

SAMPLE_VIDEO_HTML = """
<div class="tgme_widget_message_wrap js-widget_message_wrap">
  <div class="tgme_widget_message_text">Drone footage from Kharkiv.</div>
  <video src="https://cdn4.telesco.pe/file/sample.mp4?token=abc" class="tgme_widget_message_video js-message_video"></video>
  <a class="tgme_widget_message_date" href="https://t.me/osintdefender/99999">
    <time datetime="2026-06-02T13:00:00+00:00"></time>
  </a>
</div>
</div>
</div>
"""


def test_parse_telegram_channel_html_extracts_geolocated_post():
    posts = telegram_osint.parse_telegram_channel_html(SAMPLE_HTML, "osintdefender")
    assert len(posts) == 1
    post = posts[0]
    assert "Kyiv" in post["title"]
    assert post["coords"] == [50.45, 30.523]
    assert post["risk_score"] >= 3
    assert post["link"].startswith("https://t.me/")


def test_resolve_telegram_coords_handles_cyrillic():
    coords = telegram_osint._resolve_telegram_coords("Обстріл біля Харкова")
    assert coords == (49.993, 36.231)


def test_resolve_telegram_coords_uses_metro_anchors_for_country_tags():
    assert telegram_osint._resolve_telegram_coords("#Israel #Iran") == (32.085, 34.781)
    assert telegram_osint._resolve_telegram_coords("China announces policy") == (39.904, 116.407)
    assert telegram_osint._resolve_telegram_coords("#USA response") == (40.712, -74.006)


def test_resolve_telegram_coords_keeps_specific_cities_over_country_anchor():
    assert telegram_osint._resolve_telegram_coords("Strike near Gaza") == (31.416, 34.333)
    assert telegram_osint._resolve_telegram_coords("Missile strike reported near Kyiv overnight") == (
        50.45,
        30.523,
    )


def test_parse_telegram_channel_html_extracts_video_media():
    posts = telegram_osint.parse_telegram_channel_html(SAMPLE_VIDEO_HTML, "osintdefender")
    assert len(posts) == 1
    post = posts[0]
    assert post["media_type"] == "video"
    assert post["media_url"].startswith("https://cdn4.telesco.pe/")
    assert post["embed_url"] == "https://t.me/osintdefender/99999?embed=1"


def test_telegram_media_host_allowed():
    assert telegram_osint.telegram_media_host_allowed("cdn4.telesco.pe")
    assert telegram_osint.telegram_media_host_allowed("cdn4.telegram-cdn.org")
    assert not telegram_osint.telegram_media_host_allowed("evil.example.com")


def test_extract_new_channel_posts_stops_at_known_links():
    known = {"https://t.me/osintdefender/12345"}
    fresh = telegram_osint._extract_new_channel_posts(SAMPLE_HTML, "osintdefender", known)
    assert fresh == []


def test_merge_telegram_posts_keeps_existing_and_adds_only_new():
    existing = [
        {
            "id": "old",
            "link": "https://t.me/osintdefender/111",
            "published": "2026-06-01T12:00:00+00:00",
        }
    ]
    incoming = [
        {
            "id": "dup",
            "link": "https://t.me/osintdefender/111",
            "published": "2026-06-02T12:00:00+00:00",
        },
        {
            "id": "new",
            "link": "https://t.me/osintdefender/222",
            "published": "2026-06-03T12:00:00+00:00",
        },
    ]
    merged, added = telegram_osint._merge_telegram_posts(existing, incoming)
    assert added == 1
    assert len(merged) == 2
    assert merged[0]["link"] == "https://t.me/osintdefender/222"
