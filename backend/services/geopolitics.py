import requests
import logging
from cachetools import cached, TTLCache
from datetime import datetime
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
        tree_url = "https://api.github.com/repos/cyterat/deepstate-map-data/git/trees/main?recursive=1"
        res_tree = requests.get(tree_url, timeout=10)
        
        if res_tree.status_code == 200:
            tree_data = res_tree.json().get("tree", [])
            # Filter for geojson files in data folder
            geo_files = [item["path"] for item in tree_data if item["path"].startswith("data/deepstatemap_data_") and item["path"].endswith(".geojson")]
            
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
                        3: "Russian-occupied areas", # Crimea / LPR / DPR
                        4: "Directions of UA attacks"
                    }
                    
                    if "features" in data:
                        for idx, feature in enumerate(data["features"]):
                            if "properties" not in feature or feature["properties"] is None:
                                feature["properties"] = {}
                            
                            feature["properties"]["name"] = name_map.get(idx, "Russian-occupied areas")
                            feature["properties"]["zone_id"] = idx
                            
                    return data
                else:
                    logger.error(f"Failed to fetch parsed Github Raw GeoJSON: {res_geo.status_code}")
        else:
            logger.error(f"Failed to fetch Github Tree for Deepstatemap: {res_tree.status_code}")
    except Exception as e:
        logger.error(f"Error fetching DeepStateMap: {e}")
    return None

# Cache GDELT data for 6 hours - heavy aggregation, data doesn't change rapidly
gdelt_cache = TTLCache(maxsize=1, ttl=21600)

def _extract_domain(url):
    """Extract a clean source name from a URL, e.g. 'nytimes.com' from 'https://www.nytimes.com/...'"""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ''
        # Strip www. prefix
        if host.startswith('www.'):
            host = host[4:]
        return host
    except Exception:
        return url[:40]

def _url_to_headline(url):
    """Extract a human-readable headline from a URL path.
    e.g. 'https://nytimes.com/2026/03/us-strikes-iran-nuclear-sites.html' -> 'Us Strikes Iran Nuclear Sites (nytimes.com)'
    """
    try:
        from urllib.parse import urlparse, unquote
        parsed = urlparse(url)
        domain = parsed.hostname or ''
        if domain.startswith('www.'):
            domain = domain[4:]

        # Get last meaningful path segment
        path = unquote(parsed.path).strip('/')
        if not path:
            return domain

        # Take the last path segment (usually the slug)
        slug = path.split('/')[-1]
        # Remove file extensions
        for ext in ['.html', '.htm', '.php', '.asp', '.aspx', '.shtml']:
            if slug.lower().endswith(ext):
                slug = slug[:-len(ext)]
        # If slug is purely numeric or a short ID, try the second-to-last segment
        import re
        if re.match(r'^[a-z]?\d{5,}$', slug, re.IGNORECASE):
            segments = path.split('/')
            if len(segments) >= 2:
                slug = segments[-2]
                for ext in ['.html', '.htm', '.php']:
                    if slug.lower().endswith(ext):
                        slug = slug[:-len(ext)]
        # Remove common ID patterns at start/end
        slug = re.sub(r'^[\d]+-', '', slug)  # leading numbers like "13847569-"
        slug = re.sub(r'-[\da-f]{6,}$', '', slug)  # trailing hex IDs
        slug = re.sub(r'[-_]c-\d+$', '', slug)  # trailing "-c-21803431"
        slug = re.sub(r'^p=\d+$', '', slug)  # WordPress ?p=1234
        # Convert slug separators to spaces
        slug = slug.replace('-', ' ').replace('_', ' ')
        # Clean up multiple spaces
        slug = re.sub(r'\s+', ' ', slug).strip()

        # If slug is still just a number or too short, fall back to domain
        if len(slug) < 5 or re.match(r'^\d+$', slug):
            return domain

        # Title case and truncate
        headline = slug.title()
        if len(headline) > 80:
            headline = headline[:77] + '...'
        return f"{headline} ({domain})"
    except Exception:
        return url[:60]

def _parse_gdelt_export_zip(zip_bytes, conflict_codes, seen_locs, features, loc_index):
    """Parse a single GDELT export ZIP and append conflict features.
    loc_index maps loc_key -> index in features list for fast duplicate merging.
    """
    import csv, io, zipfile
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        csv_name = zf.namelist()[0]
        with zf.open(csv_name) as cf:
            reader = csv.reader(io.TextIOWrapper(cf, encoding='utf-8', errors='replace'), delimiter='\t')
            for row in reader:
                try:
                    if len(row) < 61:
                        continue
                    event_code = row[26][:2] if len(row[26]) >= 2 else ''
                    if event_code not in conflict_codes:
                        continue
                    lat = float(row[56]) if row[56] else None
                    lng = float(row[57]) if row[57] else None
                    if lat is None or lng is None or (lat == 0 and lng == 0):
                        continue

                    source_url = row[60].strip() if len(row) > 60 else ''
                    location = row[52].strip() if len(row) > 52 else 'Unknown'
                    actor1 = row[6].strip() if len(row) > 6 else ''
                    actor2 = row[16].strip() if len(row) > 16 else ''

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

                    name = location or (f"{actor1} vs {actor2}" if actor1 and actor2 else actor1) or "Unknown Incident"
                    domain = _extract_domain(source_url) if source_url else ''
                    loc_index[loc_key] = len(features)
                    features.append({
                        "type": "Feature",
                        "properties": {
                            "name": name,
                            "count": 1,
                            "_urls": [source_url] if source_url else [],
                            "_domains": {domain} if domain else set(),
                        },
                        "geometry": {"type": "Point", "coordinates": [lng, lat]},
                        "_loc_key": loc_key
                    })
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        logger.warning(f"Failed to parse GDELT export zip: {e}")

def _download_gdelt_export(url):
    """Download a single GDELT export file, return bytes or None."""
    try:
        res = fetch_with_curl(url, timeout=15)
        if res.status_code == 200:
            return res.content
    except Exception:
        pass
    return None

@cached(gdelt_cache)
def fetch_global_military_incidents():
    """
    Fetches global military/conflict incidents from GDELT Events Export files.
    Aggregates the last ~8 hours of 15-minute exports to build ~1000 incidents.
    """
    from datetime import timedelta
    from concurrent.futures import ThreadPoolExecutor

    try:
        logger.info("Fetching GDELT events via export CDN (multi-file)...")

        # Get the latest export URL to determine current timestamp
        index_res = fetch_with_curl("http://data.gdeltproject.org/gdeltv2/lastupdate.txt", timeout=10)
        if index_res.status_code != 200:
            logger.error(f"GDELT lastupdate failed: {index_res.status_code}")
            return []

        # Extract latest export URL and its timestamp
        latest_url = None
        for line in index_res.text.strip().split('\n'):
            parts = line.strip().split()
            if len(parts) >= 3 and parts[2].endswith('.export.CSV.zip'):
                latest_url = parts[2]
                break

        if not latest_url:
            logger.error("Could not find GDELT export URL")
            return []

        # Extract timestamp from URL like: http://data.gdeltproject.org/gdeltv2/20260301120000.export.CSV.zip
        import re
        ts_match = re.search(r'(\d{14})\.export\.CSV\.zip', latest_url)
        if not ts_match:
            logger.error("Could not parse GDELT export timestamp")
            return []

        latest_ts = datetime.strptime(ts_match.group(1), '%Y%m%d%H%M%S')

        # Generate URLs for the last 8 hours (32 files at 15-min intervals)
        NUM_FILES = 32
        urls = []
        for i in range(NUM_FILES):
            ts = latest_ts - timedelta(minutes=15 * i)
            fname = ts.strftime('%Y%m%d%H%M%S') + '.export.CSV.zip'
            url = f"http://data.gdeltproject.org/gdeltv2/{fname}"
            urls.append(url)

        logger.info(f"Downloading {len(urls)} GDELT export files...")

        # Download in parallel (8 threads)
        with ThreadPoolExecutor(max_workers=8) as executor:
            zip_results = list(executor.map(_download_gdelt_export, urls))

        successful = sum(1 for r in zip_results if r is not None)
        logger.info(f"Downloaded {successful}/{len(urls)} GDELT exports")

        # Parse all downloaded files
        CONFLICT_CODES = {'14', '17', '18', '19', '20'}
        features = []
        seen_locs = set()
        loc_index = {}  # loc_key -> index in features

        for zip_bytes in zip_results:
            if zip_bytes:
                _parse_gdelt_export_zip(zip_bytes, CONFLICT_CODES, seen_locs, features, loc_index)

        # Build URL + headline arrays for frontend rendering
        for f in features:
            urls = f["properties"].pop("_urls", [])
            f["properties"].pop("_domains", None)
            headlines = [_url_to_headline(u) for u in urls]
            f["properties"]["_urls_list"] = urls
            f["properties"]["_headlines_list"] = headlines
            # Keep html as fallback
            if urls:
                links = [f'<div style="margin-bottom:6px;"><a href="{u}" target="_blank">{h}</a></div>' for u, h in zip(urls, headlines)]
                f["properties"]["html"] = ''.join(links)
            else:
                f["properties"]["html"] = f["properties"]["name"]
            f.pop("_loc_key", None)

        logger.info(f"GDELT multi-file parsed: {len(features)} conflict locations from {successful} files")
        return features

    except Exception as e:
        logger.error(f"Error fetching GDELT data: {e}")
    return []
