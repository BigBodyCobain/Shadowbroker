import requests
import logging
import zipfile
import socket
import ipaddress
from cachetools import cached, TTLCache
from datetime import datetime
from urllib.parse import urljoin, urlparse
from services.network_utils import fetch_with_curl

logger = logging.getLogger(__name__)

# Cache Frontline data for 30 minutes, it doesn't move that fast
frontline_cache = TTLCache(maxsize=1, ttl=1800)


@cached(frontline_cache)
def fetch_ukraine_frontlines():
    """
    Fetches the latest GeoJSON data representing the Ukraine frontline.
    We use the cyterat/deepstate-map-data github mirror since the public API is locked.
    """
    try:
        logger.info("Fetching DeepStateMap from GitHub mirror...")

        # First, query the repo tree to find the latest file name
        tree_url = (
            "https://api.github.com/repos/cyterat/deepstate-map-data/git/trees/main?recursive=1"
        )
        res_tree = requests.get(tree_url, timeout=10)

        if res_tree.status_code == 200:
            tree_data = res_tree.json().get("tree", [])
            # Filter for geojson files in data folder
            geo_files = [
                item["path"]
                for item in tree_data
                if item["path"].startswith("data/deepstatemap_data_")
                and item["path"].endswith(".geojson")
            ]

            if geo_files:
                # Get the alphabetically latest file (since it's named with YYYYMMDD)
                latest_file = sorted(geo_files)[-1]

                raw_url = f"https://raw.githubusercontent.com/cyterat/deepstate-map-data/main/{latest_file}"
                logger.info(f"Downloading latest DeepStateMap: {raw_url}")

                res_geo = requests.get(raw_url, timeout=20)
                if res_geo.status_code == 200:
                    data = res_geo.json()

                    # The Cyterat GitHub mirror strips all properties and just provides a raw array of Feature polygons.
                    # Based on DeepStateMap's frontend mapping, the array index corresponds to the zone type:
                    # 0: Russian-occupied areas
                    # 1: Russian advance
                    # 2: Liberated area
                    # 3: Uncontested/Crimea (often folded into occupied)
                    name_map = {
                        0: "Russian-occupied areas",
                        1: "Russian advance",
                        2: "Liberated area",
                        3: "Russian-occupied areas",  # Crimea / LPR / DPR
                        4: "Directions of UA attacks",
                    }

                    if "features" in data:
                        for idx, feature in enumerate(data["features"]):
                            if "properties" not in feature or feature["properties"] is None:
                                feature["properties"] = {}

                            feature["properties"]["name"] = name_map.get(
                                idx, "Russian-occupied areas"
                            )
                            feature["properties"]["zone_id"] = idx

                    return data
                else:
                    logger.error(
                        f"Failed to fetch parsed Github Raw GeoJSON: {res_geo.status_code}"
                    )
        else:
            logger.error(f"Failed to fetch Github Tree for Deepstatemap: {res_tree.status_code}")
    except (requests.RequestException, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        logger.error(f"Error fetching DeepStateMap: {e}")
    return None


# Cache GDELT data for 6 hours - heavy aggregation, data doesn't change rapidly
gdelt_cache = TTLCache(maxsize=1, ttl=21600)


def _extract_domain(url):
    """Extract a clean source name from a URL, e.g. 'nytimes.com' from 'https://www.nytimes.com/...'"""
    try:
        from urllib.parse import urlparse

        host = urlparse(url).hostname or ""
        # Strip www. prefix
        if host.startswith("www."):
            host = host[4:]
        return host
    except (ValueError, AttributeError, KeyError):  # non-critical
        return url[:40]


def _url_to_headline(url):
    """Extract a human-readable headline from a URL path.
    e.g. 'https://nytimes.com/2026/03/us-strikes-iran-nuclear-sites.html' -> 'Us Strikes Iran Nuclear Sites'
    Falls back to domain name if the URL slug is gibberish (hex IDs, UUIDs, etc.).
    """
    import re

    try:
        from urllib.parse import urlparse, unquote

        parsed = urlparse(url)
        domain = parsed.hostname or ""
        if domain.startswith("www."):
            domain = domain[4:]

        # Get last meaningful path segment
        path = unquote(parsed.path).strip("/")
        if not path:
            return domain

        # Try the last path segment first, then walk backwards
        segments = [s for s in path.split("/") if s]
        slug = ""
        for seg in reversed(segments):
            # Remove file extensions
            for ext in [".html", ".htm", ".php", ".asp", ".aspx", ".shtml"]:
                if seg.lower().endswith(ext):
                    seg = seg[: -len(ext)]
            # Skip segments that are clearly not headlines
            if _is_gibberish(seg):
                continue
            slug = seg
            break

        if not slug:
            return domain

        # Remove common ID patterns at start/end
        slug = re.sub(r"^[\d]+-", "", slug)  # leading "13847569-"
        slug = re.sub(r"-[\da-f]{6,}$", "", slug)  # trailing hex IDs
        slug = re.sub(r"[-_]c-\d+$", "", slug)  # trailing "-c-21803431"
        slug = re.sub(r"^p=\d+$", "", slug)  # WordPress ?p=1234
        # Convert slug separators to spaces
        slug = slug.replace("-", " ").replace("_", " ")
        slug = re.sub(r"\s+", " ", slug).strip()

        # Final gibberish check after cleanup
        if len(slug) < 8 or _is_gibberish(slug.replace(" ", "-")):
            return domain

        # Title case and truncate
        headline = slug.title()
        if len(headline) > 90:
            headline = headline[:87] + "..."
        return headline
    except (ValueError, AttributeError, KeyError):  # non-critical
        return url[:60]


def _is_gibberish(text):
    """Detect if a URL segment is gibberish (hex IDs, UUIDs, numeric IDs, etc.)
    rather than a real human-readable slug like 'us-strikes-iran'."""
    import re

    t = text.strip()
    if not t:
        return True
    # Pure numbers
    if re.match(r"^\d+$", t):
        return True
    # UUID pattern (with or without dashes)
    if re.match(
        r"^[0-9a-f]{8}[_-]?[0-9a-f]{4}[_-]?[0-9a-f]{4}[_-]?[0-9a-f]{4}[_-]?[0-9a-f]{12}$", t, re.I
    ):
        return True
    # Hex-heavy string: more than 40% hex digits among alphanumeric chars
    alnum = re.sub(r"[^a-zA-Z0-9]", "", t)
    if alnum:
        hex_chars = sum(1 for c in alnum if c in "0123456789abcdefABCDEF")
        if hex_chars / len(alnum) > 0.4 and len(alnum) > 6:
            return True
    # Mostly digits with a few alpha (like "article8efa6c53")
    digits = sum(1 for c in alnum if c.isdigit())
    if alnum and digits / len(alnum) > 0.5:
        return True
    # Too short to be a headline slug
    if len(t) < 5:
        return True
    # Query-param style segments
    if "=" in t:
        return True
    return False


# Persistent cache for article titles — survives across GDELT cache refreshes
# Bounded to 5000 entries with 24hr TTL to prevent unbounded memory growth
_article_title_cache = TTLCache(maxsize=5000, ttl=86400)
_article_url_safety_cache = TTLCache(maxsize=5000, ttl=3600)
_TITLE_FETCH_MAX_REDIRECTS = 3
_TITLE_FETCH_READ_BYTES = 32768
_ALLOWED_ARTICLE_PORTS = {80, 443, 8080, 8443}


def _hostname_resolves_public(hostname: str, port: int) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return False

    addresses = set()
    for info in infos:
        sockaddr = info[4] if len(info) > 4 else None
        if not sockaddr:
            continue
        raw_addr = str(sockaddr[0] or "").split("%", 1)[0]
        if not raw_addr:
            continue
        try:
            addresses.add(ipaddress.ip_address(raw_addr))
        except ValueError:
            continue

    return bool(addresses) and all(addr.is_global for addr in addresses)


def _is_safe_public_article_url(url: str) -> tuple[bool, str]:
    cached = _article_url_safety_cache.get(url)
    if cached is not None:
        return cached

    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        result = (False, "parse_error")
        _article_url_safety_cache[url] = result
        return result

    scheme = str(parsed.scheme or "").lower()
    host = str(parsed.hostname or "").strip().lower()
    if scheme not in {"http", "https"}:
        result = (False, "scheme")
    elif not host:
        result = (False, "host")
    elif parsed.username or parsed.password:
        result = (False, "userinfo")
    elif host in {"localhost", "localhost.localdomain"}:
        result = (False, "localhost")
    else:
        port = parsed.port or (443 if scheme == "https" else 80)
        if port not in _ALLOWED_ARTICLE_PORTS:
            result = (False, "port")
        else:
            try:
                target_ip = ipaddress.ip_address(host.split("%", 1)[0])
            except ValueError:
                target_ip = None
            if target_ip is not None:
                result = (True, "") if target_ip.is_global else (False, "private_ip")
            else:
                result = (True, "") if _hostname_resolves_public(host, port) else (False, "private_dns")

    _article_url_safety_cache[url] = result
    return result


def _fetch_article_title(url):
    """Fetch the real headline from an article's HTML <title> or og:title tag.
    Returns the title string, or None if it can't be fetched.
    Uses a persistent cache to avoid refetching."""
    if url in _article_title_cache:
        return _article_title_cache[url]

    import re

    try:
        current_url = str(url or "").strip()
        chunk = ""
        for _ in range(_TITLE_FETCH_MAX_REDIRECTS + 1):
            allowed, _reason = _is_safe_public_article_url(current_url)
            if not allowed:
                _article_title_cache[url] = None
                return None

            resp = requests.get(
                current_url,
                timeout=4,
                headers={"User-Agent": "Mozilla/5.0 (compatible; OSINT Dashboard/1.0)"},
                stream=True,
                allow_redirects=False,
            )
            try:
                location = str(resp.headers.get("Location") or "").strip()
                if 300 <= resp.status_code < 400 and location:
                    current_url = urljoin(current_url, location)
                    continue
                if resp.status_code != 200:
                    _article_title_cache[url] = None
                    return None
                chunk = resp.raw.read(_TITLE_FETCH_READ_BYTES).decode("utf-8", errors="replace")
                break
            finally:
                resp.close()
        else:
            _article_title_cache[url] = None
            return None

        title = None

        # Try og:title first (usually the cleanest)
        og_match = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\'>]+)["\']', chunk, re.I
        )
        if not og_match:
            og_match = re.search(
                r'<meta[^>]+content=["\']([^"\'>]+)["\'][^>]+property=["\']og:title["\']',
                chunk,
                re.I,
            )
        if og_match:
            title = og_match.group(1).strip()

        # Fall back to <title> tag
        if not title:
            title_match = re.search(r"<title[^>]*>([^<]+)</title>", chunk, re.I)
            if title_match:
                title = title_match.group(1).strip()

        if title:
            # Clean up HTML entities
            import html as html_mod

            title = html_mod.unescape(title)
            # Remove site name suffixes like " | CNN" or " - BBC News"
            title = re.sub(r"\s*[|\-–—]\s*[^|\-–—]{2,30}$", "", title).strip()
            # Truncate very long titles
            if len(title) > 120:
                title = title[:117] + "..."
            if len(title) > 10:
                _article_title_cache[url] = title
                return title

        _article_title_cache[url] = None
        return None
    except (
        requests.RequestException,
        ConnectionError,
        TimeoutError,
        ValueError,
        AttributeError,
    ):  # non-critical
        _article_title_cache[url] = None
        return None


def _batch_fetch_titles(urls):
    """Fetch real article titles for a list of URLs in parallel.
    Returns a dict of url -> title (or None if fetch failed)."""
    from concurrent.futures import ThreadPoolExecutor

    results = {}
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(_fetch_article_title, u): u for u in urls}
        for future in futures:
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception:  # non-critical: optional title enrichment
                results[url] = None
    return results


def _parse_gdelt_export_zip(zip_bytes, conflict_codes, seen_locs, features, loc_index):
    """Parse a single GDELT export ZIP and append conflict features.
    loc_index maps loc_key -> index in features list for fast duplicate merging.
    """
    import csv, io, zipfile

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        csv_name = zf.namelist()[0]
        with zf.open(csv_name) as cf:
            reader = csv.reader(
                io.TextIOWrapper(cf, encoding="utf-8", errors="replace"), delimiter="\t"
            )
            for row in reader:
                try:
                    if len(row) < 61:
                        continue
                    event_code = row[26][:2] if len(row[26]) >= 2 else ""
                    if event_code not in conflict_codes:
                        continue
                    lat = float(row[56]) if row[56] else None
                    lng = float(row[57]) if row[57] else None
                    if lat is None or lng is None or (lat == 0 and lng == 0):
                        continue

                    source_url = row[60].strip() if len(row) > 60 else ""
                    location = row[52].strip() if len(row) > 52 else "Unknown"
                    actor1 = row[6].strip() if len(row) > 6 else ""
                    actor2 = row[16].strip() if len(row) > 16 else ""

                    loc_key = f"{round(lat, 1)}_{round(lng, 1)}"
                    if loc_key in seen_locs:
                        # Merge: increment count and add source URL if new (dedup by domain)
                        idx = loc_index[loc_key]
                        feat = features[idx]
                        feat["properties"]["count"] = feat["properties"].get("count", 1) + 1
                        urls = feat["properties"].get("_urls", [])
                        seen_domains = feat["properties"].get("_domains", set())
                        if source_url:
                            domain = _extract_domain(source_url)
                            if domain not in seen_domains and len(urls) < 10:
                                urls.append(source_url)
                                seen_domains.add(domain)
                                feat["properties"]["_urls"] = urls
                                feat["properties"]["_domains"] = seen_domains
                        continue
                    seen_locs.add(loc_key)

                    name = (
                        location
                        or (f"{actor1} vs {actor2}" if actor1 and actor2 else actor1)
                        or "Unknown Incident"
                    )
                    domain = _extract_domain(source_url) if source_url else ""
                    loc_index[loc_key] = len(features)
                    features.append(
                        {
                            "type": "Feature",
                            "properties": {
                                "name": name,
                                "count": 1,
                                "_urls": [source_url] if source_url else [],
                                "_domains": {domain} if domain else set(),
                            },
                            "geometry": {"type": "Point", "coordinates": [lng, lat]},
                            "_loc_key": loc_key,
                        }
                    )
                except (ValueError, IndexError):
                    continue
    except (IOError, OSError, ValueError, KeyError, zipfile.BadZipFile) as e:
        logger.warning(f"Failed to parse GDELT export zip: {e}")


def _download_gdelt_export(url):
    """Download a single GDELT export file, return bytes or None."""
    try:
        res = fetch_with_curl(url, timeout=15)
        if res.status_code == 200:
            return res.content
    except (ConnectionError, TimeoutError, OSError):  # non-critical
        pass
    return None


def _build_feature_html(features, fetched_titles=None):
    """Build URL + headline arrays for frontend rendering.
    Uses fetched_titles (real article titles) when available, falls back to URL slug parsing."""
    import html as html_mod

    for f in features:
        urls = f["properties"].pop("_urls", [])
        f["properties"].pop("_domains", None)
        headlines = []
        for u in urls:
            real_title = fetched_titles.get(u) if fetched_titles else None
            headlines.append(real_title if real_title else _url_to_headline(u))
        f["properties"]["_urls_list"] = urls
        f["properties"]["_headlines_list"] = headlines
        if urls:
            links = []
            for u, h in zip(urls, headlines):
                safe_url = u if u.startswith(("http://", "https://")) else "about:blank"
                safe_h = html_mod.escape(h)
                links.append(
                    f'<div style="margin-bottom:6px;"><a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_h}</a></div>'
                )
            f["properties"]["html"] = "".join(links)
        else:
            f["properties"]["html"] = html_mod.escape(f["properties"]["name"])
        f.pop("_loc_key", None)


def _enrich_gdelt_titles_background(features, all_article_urls):
    """Background thread: fetch real article titles then update features in-place."""
    import html as html_mod

    try:
        logger.info(f"[BG] Fetching real article titles for {len(all_article_urls)} URLs...")
        fetched_titles = _batch_fetch_titles(all_article_urls)
        fetched_count = sum(1 for v in fetched_titles.values() if v)
        logger.info(f"[BG] Resolved {fetched_count}/{len(all_article_urls)} article titles")

        # Update features in-place with real titles
        for f in features:
            urls = f["properties"].get("_urls_list", [])
            if not urls:
                continue
            headlines = []
            for u in urls:
                real_title = fetched_titles.get(u)
                headlines.append(real_title if real_title else _url_to_headline(u))
            f["properties"]["_headlines_list"] = headlines
            links = []
            for u, h in zip(urls, headlines):
                safe_url = u if u.startswith(("http://", "https://")) else "about:blank"
                safe_h = html_mod.escape(h)
                links.append(
                    f'<div style="margin-bottom:6px;"><a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_h}</a></div>'
                )
            f["properties"]["html"] = "".join(links)
        logger.info(f"[BG] GDELT title enrichment complete")
    except Exception as e:
        logger.error(f"[BG] GDELT title enrichment failed: {e}")


def fetch_global_military_incidents():
    """
    Fetches global military/conflict incidents from GDELT Events Export files.
    Aggregates the last ~8 hours of 15-minute exports to build ~1000 incidents.
    Returns immediately with URL-slug headlines; enriches with real titles in background.
    """
    import threading
    from datetime import timedelta
    from concurrent.futures import ThreadPoolExecutor

    try:
        logger.info("Fetching GDELT events via export CDN (multi-file)...")

        # Get the latest export URL to determine current timestamp
        index_res = fetch_with_curl(
            "http://data.gdeltproject.org/gdeltv2/lastupdate.txt", timeout=10
        )
        if index_res.status_code != 200:
            logger.error(f"GDELT lastupdate failed: {index_res.status_code}")
            return []

        # Extract latest export URL and its timestamp
        latest_url = None
        for line in index_res.text.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 3 and parts[2].endswith(".export.CSV.zip"):
                latest_url = parts[2]
                break

        if not latest_url:
            logger.error("Could not find GDELT export URL")
            return []

        # Extract timestamp from URL like: http://data.gdeltproject.org/gdeltv2/20260301120000.export.CSV.zip
        import re

        ts_match = re.search(r"(\d{14})\.export\.CSV\.zip", latest_url)
        if not ts_match:
            logger.error("Could not parse GDELT export timestamp")
            return []

        latest_ts = datetime.strptime(ts_match.group(1), "%Y%m%d%H%M%S")

        # Generate URLs for the last 8 hours (32 files at 15-min intervals)
        NUM_FILES = 32
        urls = []
        for i in range(NUM_FILES):
            ts = latest_ts - timedelta(minutes=15 * i)
            fname = ts.strftime("%Y%m%d%H%M%S") + ".export.CSV.zip"
            url = f"http://data.gdeltproject.org/gdeltv2/{fname}"
            urls.append(url)

        logger.info(f"Downloading {len(urls)} GDELT export files...")

        # Download in parallel (8 threads)
        with ThreadPoolExecutor(max_workers=8) as executor:
            zip_results = list(executor.map(_download_gdelt_export, urls))

        successful = sum(1 for r in zip_results if r is not None)
        logger.info(f"Downloaded {successful}/{len(urls)} GDELT exports")

        # Parse all downloaded files
        CONFLICT_CODES = {"14", "17", "18", "19", "20"}
        features = []
        seen_locs = set()
        loc_index = {}  # loc_key -> index in features

        for zip_bytes in zip_results:
            if zip_bytes:
                _parse_gdelt_export_zip(zip_bytes, CONFLICT_CODES, seen_locs, features, loc_index)

        # Collect all unique article URLs
        all_article_urls = set()
        for f in features:
            for u in f["properties"].get("_urls", []):
                if u:
                    all_article_urls.add(u)

        # Build HTML immediately with URL-slug headlines (instant, no network)
        _build_feature_html(features)

        logger.info(
            f"GDELT parsed: {len(features)} conflict locations from {successful} files (titles enriching in background)"
        )

        # Kick off background thread to enrich with real article titles
        # Features list is shared — background thread updates in-place
        t = threading.Thread(
            target=_enrich_gdelt_titles_background,
            args=(features, all_article_urls),
            daemon=True,
        )
        t.start()

        return features

    except (
        requests.RequestException,
        ConnectionError,
        TimeoutError,
        ValueError,
        KeyError,
        OSError,
    ) as e:
        logger.error(f"Error fetching GDELT data: {e}")
    return []
