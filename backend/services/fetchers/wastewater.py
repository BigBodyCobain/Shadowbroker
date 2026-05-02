"""WastewaterSCAN fetcher — pathogen surveillance via wastewater monitoring.

Data source: Stanford/Emory WastewaterSCAN project
  - Plant locations: https://storage.googleapis.com/wastewater-dev-data/json/plants.json
  - Time series:     https://storage.googleapis.com/wastewater-dev-data/json/{uuid}.json

All data is public, no authentication required.  ~192 treatment plants across
the US with daily sampling for COVID (N Gene), Influenza A/B, RSV, Norovirus,
MPXV, Measles, H5N1, and others.
"""

import logging
import time
import concurrent.futures
from datetime import datetime, timedelta
from services.network_utils import fetch_with_curl
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.fetchers.retry import with_retry

logger = logging.getLogger(__name__)

_GCS_BASE = "https://storage.googleapis.com/wastewater-dev-data/json"

# Cache the plants list for 24 hours (it rarely changes)
_plants_cache: list[dict] = []
_plants_cache_ts: float = 0
_PLANTS_CACHE_TTL = 86400  # 24 hours

# Key pathogen targets to extract — maps internal target name to display label
_TARGET_DISPLAY: dict[str, str] = {
    "N Gene": "COVID-19",
    "Influenza A F1R1": "Influenza A",
    "Influenza B": "Influenza B",
    "RSV": "RSV",
    "Noro_G2": "Norovirus",
    "MPXV_G2R_WA": "Mpox",
    "InfA_H5": "H5N1 (Bird Flu)",
    "HMPV_4": "HMPV",
    "Rota": "Rotavirus",
    "HAV": "Hepatitis A",
    "C_auris": "Candida auris",
    "EVD68": "Enterovirus D68",
}

# Activity categories that represent elevated/alert levels
_ALERT_CATEGORIES = {"high", "very high", "above normal"}


def _fetch_plants() -> list[dict]:
    """Fetch the full plants list from GCS, with 24h caching."""
    global _plants_cache, _plants_cache_ts

    if _plants_cache and (time.time() - _plants_cache_ts) < _PLANTS_CACHE_TTL:
        return _plants_cache

    url = f"{_GCS_BASE}/plants.json"
    resp = fetch_with_curl(url, timeout=30)
    if resp.status_code != 200:
        logger.warning(f"WastewaterSCAN plants fetch failed: HTTP {resp.status_code}")
        return _plants_cache  # return stale cache on failure

    data = resp.json()
    plants = data.get("plants", [])
    _plants_cache = plants
    _plants_cache_ts = time.time()
    logger.info(f"WastewaterSCAN: cached {len(plants)} plant locations")
    return plants


def _fetch_plant_latest(plant_id: str) -> dict | None:
    """Fetch the most recent sample for a single plant.

    Returns a dict with pathogen levels or None on failure.
    """
    url = f"{_GCS_BASE}/{plant_id}.json"
    try:
        resp = fetch_with_curl(url, timeout=12)
        if resp.status_code != 200:
            return None
        data = resp.json()
        samples = data.get("samples", [])
        if not samples:
            return None

        # Find the most recent sample (last element, sorted by date)
        latest = samples[-1]
        collection_date = latest.get("collection_date", "")

        # Skip samples older than 30 days
        try:
            sample_dt = datetime.strptime(collection_date, "%Y-%m-%d")
            if sample_dt < datetime.utcnow() - timedelta(days=30):
                return None
        except (ValueError, TypeError):
            pass

        # Extract key pathogen levels
        targets = latest.get("targets", {})
        pathogens: list[dict] = []
        alert_count = 0

        for target_key, display_name in _TARGET_DISPLAY.items():
            target_data = targets.get(target_key)
            if not target_data:
                continue

            concentration = target_data.get("gc_g_dry_weight", 0) or 0
            activity = target_data.get("activity_category", "not calculated")
            normalized = target_data.get("gc_g_dry_weight_pmmov", 0) or 0

            if concentration <= 0 and normalized <= 0:
                continue  # no detection

            is_alert = activity.lower() in _ALERT_CATEGORIES
            if is_alert:
                alert_count += 1

            pathogens.append({
                "name": display_name,
                "target_key": target_key,
                "concentration": round(concentration, 1),
                "normalized": round(normalized, 6),
                "activity": activity,
                "alert": is_alert,
            })

        if not pathogens:
            return None

        return {
            "collection_date": collection_date,
            "pathogens": pathogens,
            "alert_count": alert_count,
        }
    except Exception as e:
        logger.debug(f"WastewaterSCAN: failed to fetch plant {plant_id}: {e}")
        return None


@with_retry(max_retries=1, base_delay=5)
def fetch_wastewater():
    """Fetch WastewaterSCAN plant locations and latest pathogen levels.

    1. Fetches the plant list (cached 24h) for locations.
    2. Concurrently fetches time series for all plants, extracting only
       the most recent sample's pathogen data.
    3. Merges into a flat list suitable for map rendering.
    """
    from services.fetchers._store import is_any_active

    if not is_any_active("wastewater"):
        return

    plants = _fetch_plants()
    if not plants:
        logger.warning("WastewaterSCAN: no plant data available")
        return

    # Build base records from plant metadata
    plant_map: dict[str, dict] = {}
    for p in plants:
        point = p.get("point") or {}
        coords = point.get("coordinates") or []
        if len(coords) < 2:
            continue

        pid = p.get("id") or p.get("uuid", "")
        if not pid:
            continue

        plant_map[pid] = {
            "id": pid,
            "name": p.get("name", ""),
            "site_name": p.get("site_name", ""),
            "city": p.get("city", ""),
            "state": p.get("state", ""),
            "country": p.get("country", "US"),
            "population": p.get("sewershed_pop"),
            "lat": coords[1],
            "lng": coords[0],
            "pathogens": [],
            "alert_count": 0,
            "collection_date": "",
            "source": "WastewaterSCAN",
        }

    # Fetch latest samples concurrently (up to 12 threads)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(_fetch_plant_latest, pid): pid
            for pid in plant_map
        }
        for fut in concurrent.futures.as_completed(futures, timeout=120):
            pid = futures[fut]
            try:
                result = fut.result()
                if result:
                    plant_map[pid]["pathogens"] = result["pathogens"]
                    plant_map[pid]["alert_count"] = result["alert_count"]
                    plant_map[pid]["collection_date"] = result["collection_date"]
            except Exception:
                pass

    nodes = list(plant_map.values())
    active_nodes = [n for n in nodes if n["pathogens"]]

    logger.info(
        f"WastewaterSCAN: {len(nodes)} plants, "
        f"{len(active_nodes)} with recent pathogen data, "
        f"{sum(n['alert_count'] for n in nodes)} total alerts"
    )

    with _data_lock:
        latest_data["wastewater"] = nodes
    if nodes:
        _mark_fresh("wastewater")
