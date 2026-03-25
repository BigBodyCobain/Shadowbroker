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
ALL_CATEGORIES_VALUE = "all"
NEWS_CATEGORIES = [
    "Maritime / Shipping",
    "Air Traffic / Aviation",
    "War / Conflict Events",
    "Cyber Hacks",
    "Police Events / Big Crime",
    "Finance",
    "Crypto",
    "OSINT",
]
DEFAULT_SELECTED_CATEGORIES = [ALL_CATEGORIES_VALUE]


def _normalise_categories(value, *, allow_all: bool = False) -> list[str]:
    values = value if isinstance(value, list) else [value]
    cleaned: list[str] = []
    allowed = set(NEWS_CATEGORIES)
    if allow_all:
        allowed = allowed | {ALL_CATEGORIES_VALUE}
    aliases = {
        "Cyber Hacks / Cybersecurity": "Cyber Hacks",
    }

    for item in values:
        if not isinstance(item, str):
            continue
        c = item.strip()
        if not c:
            continue
        c = aliases.get(c, c)
        if c in allowed and c not in cleaned:
            cleaned.append(c)
    return cleaned


def _normalise_weights(value, fallback: int = 3) -> list[int]:
    values = value if isinstance(value, list) else [value]
    cleaned: list[int] = []
    for item in values:
        try:
            w = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= w <= 5 and w not in cleaned:
            cleaned.append(w)
    if not cleaned:
        cleaned = [max(1, min(5, int(fallback)))]
    return sorted(cleaned)

DEFAULT_FEEDS = [
    {"name": "ZeroHedge", "url": "https://cms.zerohedge.com/fullrss2.xml", "weight": 4, "categories": ["War / Conflict Events"]},
    {"name": "BBC", "url": "http://feeds.bbci.co.uk/news/world/rss.xml", "weight": 3, "categories": ["War / Conflict Events"]},
    {"name": "AlJazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "weight": 2, "categories": ["War / Conflict Events"]},
    {"name": "NYT", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "weight": 1, "categories": ["War / Conflict Events"]},
    {"name": "GDACS", "url": "https://www.gdacs.org/xml/rss.xml", "weight": 5, "categories": ["Police Events / Big Crime"]},
    {"name": "NHK", "url": "https://www3.nhk.or.jp/nhkworld/rss/world.xml", "weight": 3, "categories": ["War / Conflict Events"]},
    {"name": "CNA", "url": "https://www.channelnewsasia.com/rssfeed/8395986", "weight": 3, "categories": ["War / Conflict Events"]},
    {"name": "Mercopress", "url": "https://en.mercopress.com/rss/", "weight": 3, "categories": ["Maritime / Shipping", "War / Conflict Events"]},
    {"name": "FocusTaiwan", "url": "https://focustaiwan.tw/rss", "weight": 5, "categories": ["War / Conflict Events"]},
    {"name": "Kyodo", "url": "https://english.kyodonews.net/rss/news.xml", "weight": 4, "categories": ["War / Conflict Events"]},
    {"name": "SCMP", "url": "https://www.scmp.com/rss/91/feed", "weight": 4, "categories": ["War / Conflict Events"]},
    {"name": "The Diplomat", "url": "https://thediplomat.com/feed/", "weight": 4, "categories": ["War / Conflict Events"]},
    {"name": "Stars and Stripes", "url": "https://www.stripes.com/feeds/pacific.rss", "weight": 4, "categories": ["War / Conflict Events", "Air Traffic / Aviation"]},
    {"name": "Yonhap", "url": "https://en.yna.co.kr/RSS/news.xml", "weight": 4, "categories": ["War / Conflict Events"]},
    {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss", "weight": 3, "categories": ["War / Conflict Events"]},
    {"name": "Taipei Times", "url": "https://www.taipeitimes.com/xml/pda.rss", "weight": 4, "categories": ["War / Conflict Events"]},
    {"name": "Asia Times", "url": "https://asiatimes.com/feed/", "weight": 3, "categories": ["War / Conflict Events"]},
    {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/", "weight": 3, "categories": ["Air Traffic / Aviation", "War / Conflict Events"]},
    {"name": "Japan Times", "url": "https://www.japantimes.co.jp/feed/", "weight": 3, "categories": ["War / Conflict Events"]},
]


def get_feeds() -> list[dict]:
    """Load feeds from config file, falling back to defaults."""
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            feeds = data.get("feeds", []) if isinstance(data, dict) else data
            if isinstance(feeds, list) and len(feeds) > 0:
                normalised: list[dict] = []
                for f in feeds:
                    if not isinstance(f, dict):
                        continue
                    name = str(f.get("name", "")).strip()
                    url = str(f.get("url", "")).strip()
                    weight = f.get("weight", 3)
                    if not name or not url:
                        continue
                    try:
                        weight = int(weight)
                    except (TypeError, ValueError):
                        weight = 3
                    weights = _normalise_weights(
                        f.get("weights", [weight]),
                        fallback=weight,
                    )
                    categories = _normalise_categories(
                        f.get("categories", f.get("category", []))
                    )
                    normalised.append({
                        "name": name,
                        "url": url,
                        "weight": max(weights),
                        "weights": weights,
                        "map_visible": bool(f.get("map_visible", False)),
                        "categories": categories,
                    })
                if normalised:
                    return normalised
    except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to read news feed config: {e}")
    return list(DEFAULT_FEEDS)


def save_feeds(feeds: list[dict]) -> bool:
    """Validate and save feeds to config file. Returns True on success."""
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
        weights = _normalise_weights(
            f.get("weights", [weight]),
            fallback=int(weight) if isinstance(weight, (int, float)) else 3,
        )
        categories = _normalise_categories(
            f.get("categories", f.get("category", []))
        )
        # Normalise
        f["name"] = name
        f["url"] = url
        f["weights"] = weights
        f["weight"] = max(weights)
        f["map_visible"] = bool(f.get("map_visible", False))
        f["categories"] = categories
        if "category" in f:
            del f["category"]
    try:
        selected_categories = list(DEFAULT_SELECTED_CATEGORIES)
        if CONFIG_PATH.exists():
            try:
                existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    selected_categories = _normalise_categories(
                        existing.get("selected_categories", DEFAULT_SELECTED_CATEGORIES),
                        allow_all=True,
                    ) or list(DEFAULT_SELECTED_CATEGORIES)
            except (IOError, OSError, json.JSONDecodeError, ValueError):
                pass
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(
                {"feeds": feeds, "selected_categories": selected_categories},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return True
    except (IOError, OSError) as e:
        logger.error(f"Failed to write news feed config: {e}")
        return False


def reset_feeds() -> bool:
    """Reset feeds to defaults."""
    if not save_feeds(list(DEFAULT_FEEDS)):
        return False
    return save_selected_categories(list(DEFAULT_SELECTED_CATEGORIES))


def get_selected_categories() -> list[str]:
    """Load active category filters from config."""
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                selected = _normalise_categories(
                    data.get("selected_categories", DEFAULT_SELECTED_CATEGORIES),
                    allow_all=True,
                )
                return selected or list(DEFAULT_SELECTED_CATEGORIES)
    except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to read selected categories: {e}")
    return list(DEFAULT_SELECTED_CATEGORIES)


def save_selected_categories(categories: list[str]) -> bool:
    """Persist active category filters in news_feeds.json."""
    selected = _normalise_categories(categories, allow_all=True)
    if not selected:
        selected = list(DEFAULT_SELECTED_CATEGORIES)

    feeds = get_feeds()
    if not save_feeds(feeds):
        return False

    try:
        data = {}
        if CONFIG_PATH.exists():
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        data["feeds"] = feeds
        data["selected_categories"] = selected
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to save selected categories: {e}")
        return False
