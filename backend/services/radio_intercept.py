import requests
from bs4 import BeautifulSoup
import logging
from cachetools import cached, TTLCache
import cloudscraper
import reverse_geocoder as rg

logger = logging.getLogger(__name__)

# Cache the top feeds for 5 minutes so we don't hammer Broadcastify
radio_cache = TTLCache(maxsize=1, ttl=300)


@cached(radio_cache)
def get_top_broadcastify_feeds():
    """
    Scrapes the Broadcastify Top 50 live audio feeds public dashboard.
    Returns a list of dictionaries containing feed metadata and direct stream URLs.
    """
    logger.info("Scraping Broadcastify Top Feeds (Cache Miss)")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        res = requests.get("https://www.broadcastify.com/listen/top", headers=headers, timeout=10)
        if res.status_code != 200:
            logger.error(f"Broadcastify Scrape Failed: HTTP {res.status_code}")
            return []

        soup = BeautifulSoup(res.text, "html.parser")

        table = soup.find("table", {"class": "btable"})
        if not table:
            logger.error("Could not find feeds table on Broadcastify.")
            return []

        feeds = []
        rows = table.find_all("tr")[1:]  # Skip header row

        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 5:
                # Top layout: [Listeners, Feed ID (hidden), Location, Feed Name, Category, Genre]
                listeners_str = cols[0].text.strip().replace(",", "")
                listeners = int(listeners_str) if listeners_str.isdigit() else 0

                link_tag = cols[2].find("a")
                if not link_tag:
                    continue

                href = link_tag.get("href", "")
                feed_id = href.split("/")[-1] if "/listen/feed/" in href else None

                if not feed_id:
                    continue

                location = cols[1].text.strip()
                name = cols[2].text.strip()
                category = cols[3].text.strip()

                feeds.append(
                    {
                        "id": feed_id,
                        "listeners": listeners,
                        "location": location,
                        "name": name,
                        "category": category,
                        "stream_url": f"https://broadcastify.cdnstream1.com/{feed_id}",
                    }
                )

        logger.info(f"Successfully scraped {len(feeds)} top feeds from Broadcastify.")
        return feeds

    except (requests.RequestException, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        logger.error(f"Broadcastify Scrape Exception: {e}")
        return []


# Cache OpenMHZ systems mapping so we don't have to fetch all 450+ every time
openmhz_systems_cache = TTLCache(maxsize=1, ttl=3600)


@cached(openmhz_systems_cache)
def get_openmhz_systems():
    """Fetches the full directory of OpenMHZ systems."""
    logger.info("Scraping OpenMHZ Systems (Cache Miss)")
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )

    try:
        res = scraper.get("https://api.openmhz.com/systems", timeout=15)
        if res.status_code == 200:
            data = res.json()
            # Return list of systems
            return data.get("systems", []) if isinstance(data, dict) else []
        return []
    except (requests.RequestException, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        logger.error(f"OpenMHZ Systems Scrape Exception: {e}")
        return []


# Cache specific city calls briefly (15-30s) to limit our polling rate
openmhz_calls_cache = TTLCache(maxsize=100, ttl=20)


@cached(openmhz_calls_cache)
def get_recent_openmhz_calls(sys_name: str):
    """Fetches the actual audio burst .m4a URLs for a specific system (e.g., 'wmata')."""
    logger.info(f"Fetching OpenMHZ calls for {sys_name} (Cache Miss)")
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )

    try:
        url = f"https://api.openmhz.com/{sys_name}/calls"
        res = scraper.get(url, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data.get("calls", []) if isinstance(data, dict) else []
        return []
    except (requests.RequestException, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        logger.error(f"OpenMHZ Calls Scrape Exception ({sys_name}): {e}")
        return []


US_STATES = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
    "Washington, D.C.": "DC",
    "District of Columbia": "DC",
}

import math


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 3958.8  # Earth radius in miles
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat / 2) * math.sin(dLat / 2) + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dLon / 2) * math.sin(dLon / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def find_nearest_openmhz_systems_list(lat: float, lng: float, limit: int = 5):
    """
    Finds the strictly nearest OpenMHZ systems by distance.
    """
    systems = get_openmhz_systems()
    if not systems:
        return []

    # Calculate distance for all systems that provide coordinates
    valid_systems = []
    for s in systems:
        s_lat = s.get("lat")
        s_lng = s.get("lng")
        if s_lat is not None and s_lng is not None:
            dist = haversine_distance(lat, lng, float(s_lat), float(s_lng))
            s["distance_miles"] = dist
            valid_systems.append(s)

    if not valid_systems:
        return []

    # Sort strictly by distance
    valid_systems.sort(key=lambda x: x["distance_miles"])
    return valid_systems[:limit]


def find_nearest_openmhz_system(lat: float, lng: float):
    """
    Returns the single closest OpenMHZ system by distance.
    """
    nearest = find_nearest_openmhz_systems_list(lat, lng, limit=1)
    if nearest:
        return nearest[0]
    return None
