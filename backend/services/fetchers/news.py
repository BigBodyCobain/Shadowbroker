"""News fetching, geocoding, clustering, and risk assessment."""
import re
import logging
import concurrent.futures
import requests
import feedparser
from services.network_utils import fetch_with_curl
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.fetchers.retry import with_retry
from services.oracle_service import enrich_news_items, compute_global_threat_level, detect_breaking_events

logger = logging.getLogger("services.data_fetcher")


# Keyword -> coordinate mapping for geocoding news articles
_KEYWORD_COORDS = {
    "venezuela": (7.119, -66.589),
    "brazil": (-14.235, -51.925),
    "argentina": (-38.416, -63.616),
    "colombia": (4.570, -74.297),
    "mexico": (23.634, -102.552),
    "united states": (38.907, -77.036),
    " usa ": (38.907, -77.036),
    " us ": (38.907, -77.036),
    "washington": (38.907, -77.036),
    "canada": (56.130, -106.346),
    "ukraine": (49.487, 31.272),
    "kyiv": (50.450, 30.523),
    "russia": (61.524, 105.318),
    "moscow": (55.755, 37.617),
    "israel": (31.046, 34.851),
    "gaza": (31.416, 34.333),
    "iran": (32.427, 53.688),
    "lebanon": (33.854, 35.862),
    "syria": (34.802, 38.996),
    "yemen": (15.552, 48.516),
    # East Asia — specific locations (longer keywords matched first via _SORTED_KEYWORDS)
    "taiwan strait": (24.0, 119.5),
    "south china sea": (15.0, 115.0),
    "east china sea": (28.0, 125.0),
    "philippine sea": (20.0, 130.0),
    "senkaku": (25.740, 123.474),
    "diaoyu": (25.740, 123.474),
    "ryukyu": (26.334, 127.800),
    "okinawa": (26.334, 127.800),
    "kadena": (26.351, 127.767),
    "naha": (26.212, 127.679),
    "yokosuka": (35.283, 139.671),
    "sasebo": (33.159, 129.722),
    "misawa": (40.682, 141.368),
    "iwakuni": (34.144, 132.236),
    "guam": (13.444, 144.793),
    "taipei": (25.033, 121.565),
    "kaohsiung": (22.616, 120.313),
    "xiamen": (24.479, 118.089),
    "fujian": (26.074, 119.296),
    "guangdong": (23.379, 113.763),
    "zhejiang": (29.141, 119.788),
    "hainan": (19.200, 109.999),
    "china": (35.861, 104.195),
    "beijing": (39.904, 116.407),
    "taiwan": (23.697, 120.960),
    "north korea": (40.339, 127.510),
    "south korea": (35.907, 127.766),
    "pyongyang": (39.039, 125.762),
    "seoul": (37.566, 126.978),
    "japan": (36.204, 138.252),
    "tokyo": (35.676, 139.650),
    "afghanistan": (33.939, 67.709),
    "pakistan": (30.375, 69.345),
    "india": (20.593, 78.962),
    " uk ": (55.378, -3.435),
    "london": (51.507, -0.127),
    "france": (46.227, 2.213),
    "paris": (48.856, 2.352),
    "germany": (51.165, 10.451),
    "berlin": (52.520, 13.405),
    "sudan": (12.862, 30.217),
    "congo": (-4.038, 21.758),
    "south africa": (-30.559, 22.937),
    "nigeria": (9.082, 8.675),
    "egypt": (26.820, 30.802),
    "zimbabwe": (-19.015, 29.154),
    "kenya": (-1.292, 36.821),
    "libya": (26.335, 17.228),
    "mali": (17.570, -3.996),
    "niger": (17.607, 8.081),
    "somalia": (5.152, 46.199),
    "ethiopia": (9.145, 40.489),
    "australia": (-25.274, 133.775),
    "middle east": (31.500, 34.800),
    "europe": (48.800, 2.300),
    "africa": (0.000, 25.000),
    "america": (38.900, -77.000),
    "south america": (-14.200, -51.900),
    "asia": (34.000, 100.000),
    "california": (36.778, -119.417),
    "texas": (31.968, -99.901),
    "florida": (27.994, -81.760),
    "new york": (40.712, -74.006),
    "virginia": (37.431, -78.656),
    "british columbia": (53.726, -127.647),
    "ontario": (51.253, -85.323),
    "quebec": (52.939, -73.549),
    "delhi": (28.704, 77.102),
    "new delhi": (28.613, 77.209),
    "mumbai": (19.076, 72.877),
    "shanghai": (31.230, 121.473),
    "hong kong": (22.319, 114.169),
    "istanbul": (41.008, 28.978),
    "dubai": (25.204, 55.270),
    "singapore": (1.352, 103.819),
    "bangkok": (13.756, 100.501),
    "jakarta": (-6.208, 106.845),
    # East Asia — islands, straits, and disputed areas
    "pratas": (20.71, 116.72),
    "dongsha": (20.71, 116.72),
    "kinmen": (24.45, 118.38),
    "matsu": (26.16, 119.94),
    "scarborough": (15.14, 117.77),
    "paracel": (16.50, 112.00),
    "spratly": (10.00, 114.00),
    "miyako strait": (24.78, 125.30),
    "bashi channel": (21.00, 121.50),
    "luzon strait": (20.50, 121.50),
    " dmz ": (38.00, 127.00),
    "yalu": (40.00, 124.40),
    "yongbyon": (39.80, 125.76),
    "wonsan": (39.18, 127.48),
    "busan": (35.18, 129.07),
}

# Immutable after module load — sort by descending keyword length so
# specific locations ("taiwan strait") match before generic ones ("taiwan")
_SORTED_KEYWORDS = sorted(_KEYWORD_COORDS.items(), key=lambda x: len(x[0]), reverse=True)


def _resolve_coords(text: str) -> tuple[float, float] | None:
    """Return (lat, lng) for the most specific keyword match, or None.

    Longer keywords are tried first. Space-padded keywords (" us ", " uk ")
    use substring matching on padded text; all others use word-boundary regex.
    """
    padded_text = f" {text} "
    for kw, coords in _SORTED_KEYWORDS:
        if kw.startswith(" ") or kw.endswith(" "):
            if kw in padded_text:
                return coords
        else:
            if re.search(r'\b' + re.escape(kw) + r'\b', text):
                return coords
    return None


@with_retry(max_retries=1, base_delay=2)
def fetch_news():
    from services.news_feed_config import get_feeds
    feed_config = get_feeds()
    feeds = {f["name"]: f["url"] for f in feed_config}
    source_weights = {f["name"]: f["weight"] for f in feed_config}

    clusters = {}
    _cluster_grid = {}

    def _fetch_feed(item):
        source_name, url = item
        try:
            xml_data = fetch_with_curl(url, timeout=10).text
            return source_name, feedparser.parse(xml_data)
        except (requests.RequestException, ConnectionError, TimeoutError, ValueError, KeyError, OSError) as e:
            logger.warning(f"Feed {source_name} failed: {e}")
            return source_name, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(feeds), 6)) as pool:
        feed_results = list(pool.map(_fetch_feed, feeds.items()))

    for source_name, feed in feed_results:
        if not feed:
            continue
        for entry in feed.entries[:5]:
            title = entry.get('title', '')
            summary = entry.get('summary', '')

            _seismic_kw = ["earthquake", "seismic", "quake", "tremor", "magnitude", "richter"]
            _text_lower = (title + " " + summary).lower()
            if any(kw in _text_lower for kw in _seismic_kw):
                continue

            if source_name == "GDACS":
                alert_level = entry.get("gdacs_alertlevel", "Green")
                if alert_level == "Red": risk_score = 10
                elif alert_level == "Orange": risk_score = 7
                else: risk_score = 4
            else:
                risk_keywords = [
                    'war', 'missile', 'strike', 'attack', 'crisis', 'tension',
                    'military', 'conflict', 'defense', 'clash', 'nuclear',
                    'sanctions', 'ceasefire', 'invasion', 'drone', 'artillery',
                    'blockade', 'escalation', 'casualties', 'airspace',
                    'mobilization', 'proxy', 'insurgent', 'coup',
                    'assassination', 'bioweapon', 'chemical',
                ]
                text = (title + " " + summary).lower()

                risk_score = 1
                for kw in risk_keywords:
                    if kw in text:
                        risk_score += 2
                risk_score = min(10, risk_score)

            lat, lng = None, None

            if 'georss_point' in entry:
                geo_parts = entry['georss_point'].split()
                if len(geo_parts) == 2:
                    lat, lng = float(geo_parts[0]), float(geo_parts[1])
            elif 'where' in entry and hasattr(entry['where'], 'coordinates'):
                coords = entry['where'].coordinates
                lat, lng = coords[1], coords[0]

            if lat is None:
                text = (title + " " + summary).lower()
                result = _resolve_coords(text)
                if result:
                    lat, lng = result

            if lat is not None:
                key = None
                cell_x, cell_y = int(lng // 4), int(lat // 4)
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        for ckey in _cluster_grid.get((cell_x + dx, cell_y + dy), []):
                            parts = ckey.split(",")
                            elat, elng = float(parts[0]), float(parts[1])
                            if ((lat - elat)**2 + (lng - elng)**2)**0.5 < 4.0:
                                key = ckey
                                break
                        if key:
                            break
                    if key:
                        break
                if key is None:
                    key = f"{lat},{lng}"
                    _cluster_grid.setdefault((cell_x, cell_y), []).append(key)
            else:
                key = title

            if key not in clusters:
                clusters[key] = []

            clusters[key].append({
                "title": title,
                "link": entry.get('link', ''),
                "published": entry.get('published', ''),
                "source": source_name,
                "risk_score": risk_score,
                "coords": [lat, lng] if lat is not None else None
            })

    news_items = []
    for key, articles in clusters.items():
        articles.sort(key=lambda x: (x['risk_score'], source_weights.get(x["source"], 0)), reverse=True)
        max_risk = articles[0]['risk_score']

        top_article = articles[0]
        news_items.append({
            "title": top_article["title"],
            "link": top_article["link"],
            "published": top_article["published"],
            "source": top_article["source"],
            "risk_score": max_risk,
            "coords": top_article["coords"],
            "cluster_count": len(articles),
            "articles": articles,
            "machine_assessment": None
        })

    news_items.sort(key=lambda x: x['risk_score'], reverse=True)

    # Oracle enrichment: sentiment, oracle scores, prediction market odds
    try:
        with _data_lock:
            markets = list(latest_data.get("prediction_markets", []))
        enrich_news_items(news_items, source_weights, markets)
        detect_breaking_events(news_items)
    except Exception as e:
        logger.warning(f"Oracle enrichment failed (news still usable): {e}")

    # Global threat level computation (fuses news + markets + military + jamming)
    try:
        with _data_lock:
            markets = list(latest_data.get("prediction_markets", []))
            mil_flights = list(latest_data.get("military_flights", []))
            jam_zones = list(latest_data.get("gps_jamming", []))
            ships = list(latest_data.get("ships", []))
            corr_alerts = list(latest_data.get("correlations", []))
        threat_level = compute_global_threat_level(
            news_items, markets,
            military_flights=mil_flights,
            gps_jamming=jam_zones,
            ships=ships,
            correlations=corr_alerts,
        )
    except Exception as e:
        logger.warning(f"Threat level computation failed: {e}")
        threat_level = {"score": 0, "level": "GREEN", "color": "#22c55e", "drivers": []}

    with _data_lock:
        latest_data['news'] = news_items
        latest_data['threat_level'] = threat_level
    _mark_fresh("news")
