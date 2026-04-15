"""
News feed configuration — manages the user-customisable RSS feed list.
Feeds are stored in backend/config/news_feeds.json and persist across restarts.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "news_feeds.json"
MAX_FEEDS = 50
_FEED_URL_REPLACEMENTS = {
    "https://www.channelnewsasia.com/rssfeed/8395986": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml",
}
_DEAD_FEED_URLS = {
    "https://www3.nhk.or.jp/nhkworld/rss/world.xml",
    "https://focustaiwan.tw/rss",
    "https://english.kyodonews.net/rss/news.xml",
    "https://www.stripes.com/feeds/pacific.rss",
    "https://asia.nikkei.com/rss",
    "https://www.taipeitimes.com/xml/pda.rss",
}

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
    {"name": "CSM", "url": "https://www.csmonitor.com/rss/world", "weight": 4},
    {"name": "PBS NewsHour", "url": "https://www.pbs.org/newshour/feeds/rss/world", "weight": 4},
    {"name": "France 24", "url": "https://www.france24.com/en/rss", "weight": 4},
    {"name": "DW", "url": "https://rss.dw.com/xml/rss-en-world", "weight": 4},
]


def _normalise_feeds(feeds: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        item = dict(feed)
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        if url in _FEED_URL_REPLACEMENTS:
            item["url"] = _FEED_URL_REPLACEMENTS[url]
            url = item["url"]
        if url in _DEAD_FEED_URLS:
            logger.warning("Dropping dead RSS feed URL from configuration: %s", url)
            continue
        cleaned.append(item)
    return cleaned


def get_feeds() -> list[dict]:
    """Load feeds from config file, falling back to defaults."""
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            feeds = data.get("feeds", []) if isinstance(data, dict) else data
            if isinstance(feeds, list) and len(feeds) > 0:
                normalised = _normalise_feeds(feeds)
                if normalised != feeds:
                    save_feeds(normalised)
                return normalised
    except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to read news feed config: {e}")
    return list(DEFAULT_FEEDS)


def save_feeds(feeds: list[dict]) -> bool:
    """Validate and save feeds to config file. Returns True on success."""
    if not isinstance(feeds, list):
        return False
    feeds = _normalise_feeds(feeds)
    if len(feeds) > MAX_FEEDS:
        return False
    # Validate each feed entry
    for f in feeds:
        if not isinstance(f, dict):
            return False
        name = f.get("name", "").strip()
        url = f.get("url", "").strip()
        weight = f.get("weight", 3)
        if not name or not url:
            return False
        if not isinstance(weight, (int, float)) or weight < 1 or weight > 5:
            return False
        # Normalise
        f["name"] = name
        f["url"] = url
        f["weight"] = int(weight)
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps({"feeds": feeds}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except (IOError, OSError) as e:
        logger.error(f"Failed to write news feed config: {e}")
        return False


def reset_feeds() -> bool:
    """Reset feeds to defaults."""
    return save_feeds(list(DEFAULT_FEEDS))
