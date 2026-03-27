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

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "news_feeds.json"
RUNTIME_CONFIG_PATH = Path(__file__).parent.parent / "data" / "news_feeds.json"
MAX_FEEDS = 50

DEFAULT_FEEDS = [
    {"name": "NPR", "url": "https://feeds.npr.org/1004/rss.xml", "weight": 4},
    {"name": "BBC", "url": "http://feeds.bbci.co.uk/news/world/rss.xml", "weight": 3},
    {"name": "AlJazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "weight": 2},
    {"name": "NYT", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "weight": 1},
    {"name": "GDACS", "url": "https://www.gdacs.org/xml/rss.xml", "weight": 5},
    {"name": "NHK", "url": "https://www3.nhk.or.jp/nhkworld/rss/world.xml", "weight": 3},
    {"name": "CNA", "url": "https://www.channelnewsasia.com/rssfeed/8395986", "weight": 3},
    {"name": "Mercopress", "url": "https://en.mercopress.com/rss/", "weight": 3},
    {"name": "FocusTaiwan", "url": "https://focustaiwan.tw/rss", "weight": 5},
    {"name": "Kyodo", "url": "https://english.kyodonews.net/rss/news.xml", "weight": 4},
    {"name": "SCMP", "url": "https://www.scmp.com/rss/91/feed", "weight": 4},
    {"name": "The Diplomat", "url": "https://thediplomat.com/feed/", "weight": 4},
    {"name": "Stars and Stripes", "url": "https://www.stripes.com/feeds/pacific.rss", "weight": 4},
    {"name": "Yonhap", "url": "https://en.yna.co.kr/RSS/news.xml", "weight": 4},
    {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss", "weight": 3},
    {"name": "Taipei Times", "url": "https://www.taipeitimes.com/xml/pda.rss", "weight": 4},
    {"name": "Asia Times", "url": "https://asiatimes.com/feed/", "weight": 3},
    {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/", "weight": 3},
    {"name": "Japan Times", "url": "https://www.japantimes.co.jp/feed/", "weight": 3},
]


def get_feeds() -> list[dict]:
    """Load runtime feeds first, then checked-in defaults, then constants."""
    try:
        for path in (RUNTIME_CONFIG_PATH, DEFAULT_CONFIG_PATH):
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                feeds = data.get("feeds", []) if isinstance(data, dict) else data
                if isinstance(feeds, list) and len(feeds) > 0:
                    return feeds
    except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to read news feed config: {e}")
    return list(DEFAULT_FEEDS)


def save_feeds(feeds: list[dict]) -> bool:
    """Validate and save feeds to the persistent runtime config."""
    if not isinstance(feeds, list):
        return False
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
        RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_CONFIG_PATH.write_text(
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
