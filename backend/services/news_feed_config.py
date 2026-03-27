"""
News feed configuration — manages the user-customisable RSS feed list.

Defaults live in backend/config/news_feeds.json.
Runtime/user-saved feeds are stored in backend/data/news_feeds.json so they
survive Docker container rebuilds when /app/data is mounted as a volume.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


DEFAULT_FEEDS = [
    {"name": "NPR", "url": "https://feeds.npr.org/1004/rss.xml", "weight": 4},
    {"name": "BBC", "url": "http://feeds.bbci.co.uk/news/world/rss.xml", "weight": 3},
    {"name": "AlJazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "weight": 2},
    {"name": "NYT", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "weight": 1},
    {"name": "GDACS", "url": "https://www.gdacs.org/xml/rss.xml", "weight": 5},
    {"name": "CNA", "url": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml", "weight": 3},
    {"name": "Mercopress", "url": "https://en.mercopress.com/rss/", "weight": 3},
    {"name": "SCMP", "url": "https://www.scmp.com/rss/91/feed", "weight": 4},
    {"name": "The Diplomat", "url": "https://thediplomat.com/feed/", "weight": 4},
    {"name": "Yonhap", "url": "https://en.yna.co.kr/RSS/news.xml", "weight": 4},
    {"name": "Asia Times", "url": "https://asiatimes.com/feed/", "weight": 3},
    {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/", "weight": 3},
    {"name": "Japan Times", "url": "https://www.japantimes.co.jp/feed/", "weight": 3},


def get_feeds() -> list[dict]:
    """Load runtime feeds first, then merge in any missing checked-in defaults."""
    try:



def save_feeds(feeds: list[dict]) -> bool:
    """Validate and save feeds to the persistent runtime config."""
    if not isinstance(feeds, list):
        return False
    feeds = _normalise_feeds(feeds)
    if len(feeds) > MAX_FEEDS:
        return False
    normalized_feeds: list[dict] = []
    seen_names: set[str] = set()
    for feed in feeds:
        normalized = _normalize_feed(feed)
        if not normalized:
            return False
        key = normalized["name"].casefold()
        if key in seen_names:
            return False
        seen_names.add(key)
        normalized_feeds.append(normalized)
    try:
        RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_CONFIG_PATH.write_text(
            json.dumps({"feeds": normalized_feeds}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except (IOError, OSError) as e:
        logger.error(f"Failed to write news feed config: {e}")
        return False


def reset_feeds() -> bool:
    """Reset feeds to defaults."""
    return save_feeds(list(DEFAULT_FEEDS))
