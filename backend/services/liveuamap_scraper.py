import json
import logging
import base64
import urllib.parse
import re
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

logger = logging.getLogger(__name__)


def fetch_liveuamap():
    logger.info("Starting Liveuamap scraper with Playwright Stealth...")

    regions = [
        {"name": "Ukraine", "url": "https://liveuamap.com"},
        {"name": "Middle East", "url": "https://mideast.liveuamap.com"},
        {"name": "Israel-Palestine", "url": "https://israelpalestine.liveuamap.com"},
        {"name": "Syria", "url": "https://syria.liveuamap.com"},
    ]

    all_markers = []
    seen_ids = set()

    with sync_playwright() as p:
        # Launching with a real user agent to bypass Turnstile
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            color_scheme="dark",
        )
        page = context.new_page()
        stealth_sync(page)

        for region in regions:
            try:
                logger.info(f"Scraping Liveuamap region: {region['name']}")
                page.goto(region["url"], timeout=60000, wait_until="domcontentloaded")

                # Wait for the map canvas or markers script to load, max 10s wait
                try:
                    page.wait_for_timeout(5000)
                except (TimeoutError, OSError):  # non-critical: page load delay
                    pass

                html = page.content()

                m = re.search(r"var\s+ovens\s*=\s*(.*?);(?!function)", html, re.DOTALL)
                if not m:
                    logger.warning(f"Could not find 'ovens' data for {region['name']} in raw HTML")
                    # Let's try grabbing the evaluated JavaScript variable if it's there
                    try:
                        ovens_json = page.evaluate(
                            "() => typeof ovens !== 'undefined' ? JSON.stringify(ovens) : null"
                        )
                        if ovens_json:
                            markers = json.loads(ovens_json)
                            # process below
                            html = f"var ovens={ovens_json};"
                            m = re.search(r"var\s+ovens=(.*?);", html, re.DOTALL)
                    except (ValueError, KeyError, OSError) as e:  # non-critical: JS eval fallback
                        logger.debug(
                            f"Could not evaluate ovens JS variable for {region['name']}: {e}"
                        )

                if m:
                    json_str = m.group(1).strip()
                    if json_str.startswith("'") or json_str.startswith('"'):
                        json_str = json_str.strip("\"'")
                        json_str = base64.b64decode(urllib.parse.unquote(json_str)).decode("utf-8")

                    try:
                        markers = json.loads(json_str)
                        for marker in markers:
                            mid = marker.get("id")
                            if mid and mid not in seen_ids:
                                seen_ids.add(mid)
                                title = (marker.get("s") or marker.get("title") or "Unknown Event").strip()
                                # Extract all available fields from the marker
                                description = (marker.get("d") or marker.get("desc") or marker.get("description") or "").strip()
                                category = (marker.get("c") or marker.get("cat") or marker.get("category") or "").strip()
                                img = marker.get("img") or marker.get("image") or marker.get("photo") or ""
                                source = (marker.get("source") or marker.get("src") or "").strip()
                                event_time = marker.get("time") or marker.get("t") or ""
                                link = marker.get("link") or marker.get("url") or ""
                                # Format date from unix timestamp if available
                                date_str = ""
                                if event_time:
                                    try:
                                        from datetime import datetime, timezone
                                        ts = int(event_time) if not isinstance(event_time, int) else event_time
                                        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                                        date_str = dt.strftime("%Y-%m-%d %H:%M UTC")
                                    except (ValueError, TypeError, OSError):
                                        date_str = str(event_time)
                                # Build full link URL
                                if link and not link.startswith("http"):
                                    base = region["url"].rstrip("/")
                                    link = f"{base}/{link.lstrip('/')}"
                                all_markers.append(
                                    {
                                        "id": mid,
                                        "type": "liveuamap",
                                        "title": title,
                                        "description": description[:500] if description else "",
                                        "lat": marker.get("lat"),
                                        "lng": marker.get("lng"),
                                        "timestamp": event_time,
                                        "date": date_str,
                                        "link": link or region["url"],
                                        "region": region["name"],
                                        "category": category,
                                        "image": img,
                                        "source": source,
                                    }
                                )
                    except (json.JSONDecodeError, ValueError, KeyError) as e:
                        logger.error(f"Error parsing JSON for {region['name']}: {e}")

            except Exception as e:
                logger.error(f"Error scraping Liveuamap {region['name']}: {e}")

        browser.close()

    logger.info(f"Liveuamap scraper finished, extracted {len(all_markers)} unique markers.")
    return all_markers


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = fetch_liveuamap()
    print(json.dumps(res[:3], indent=2))
