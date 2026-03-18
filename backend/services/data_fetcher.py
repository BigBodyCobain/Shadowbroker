"""Data fetcher orchestrator — schedules and coordinates all data source modules.

Heavy logic has been extracted into services/fetchers/:
  - _store.py             — shared state (latest_data, locks, timestamps)
  - plane_alert.py        — aircraft enrichment DB
  - flights.py            — commercial flights, routes, trails, GPS jamming
  - military.py           — military flights, UAV detection
  - satellites.py         — satellite tracking (SGP4)
  - news.py               — RSS news fetching, clustering, risk assessment
  - yacht_alert.py        — superyacht alert enrichment
  - financial.py          — defense stocks, oil prices
  - earth_observation.py  — earthquakes, FIRMS fires, space weather, weather radar
  - infrastructure.py     — internet outages, data centers, CCTV, KiwiSDR
  - geo.py                — ships, airports, frontlines, GDELT, LiveUAMap
"""
import logging
import concurrent.futures
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from services.cctv_pipeline import init_db

# Shared state — all fetcher modules read/write through this
from services.fetchers._store import (
    latest_data, source_timestamps, _mark_fresh, _data_lock,  # noqa: F401 — re-exported for main.py
)

# Domain-specific fetcher modules (already extracted)
from services.fetchers.flights import fetch_flights  # noqa: F401
from services.fetchers.flights import _BLIND_SPOT_REGIONS  # noqa: F401 — re-exported for tests
from services.fetchers.military import fetch_military_flights  # noqa: F401
from services.fetchers.satellites import fetch_satellites  # noqa: F401
from services.fetchers.news import fetch_news  # noqa: F401

# Newly extracted fetcher modules
from services.fetchers.financial import fetch_defense_stocks, fetch_oil_prices  # noqa: F401
from services.fetchers.earth_observation import (  # noqa: F401
    fetch_earthquakes, fetch_firms_fires, fetch_space_weather, fetch_weather,
)
from services.fetchers.infrastructure import (  # noqa: F401
    fetch_internet_outages, fetch_datacenters, fetch_military_bases, fetch_cctv, fetch_kiwisdr,
    fetch_eth_nodes,
)
from services.fetchers.geo import (  # noqa: F401
    fetch_ships, fetch_airports, find_nearest_airport, cached_airports,
    fetch_frontlines, fetch_gdelt, fetch_geopolitics, update_liveuamap,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scheduler & Orchestration
# ---------------------------------------------------------------------------
def update_fast_data():
    """Fast-tier: moving entities that need frequent updates (every 60s)."""
    logger.info("Fast-tier data update starting...")
    fast_funcs = [
        fetch_flights,
        fetch_military_flights,
        fetch_ships,
        fetch_satellites,
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(fast_funcs)) as executor:
        futures = [executor.submit(func) for func in fast_funcs]
        concurrent.futures.wait(futures)
    with _data_lock:
        latest_data['last_updated'] = datetime.utcnow().isoformat()
    logger.info("Fast-tier update complete.")

def update_slow_data():
    """Slow-tier: contextual + enrichment data that refreshes less often (every 5–10 min)."""
    logger.info("Slow-tier data update starting...")
    slow_funcs = [
        fetch_news,
        fetch_earthquakes,
        fetch_firms_fires,
        fetch_defense_stocks,
        fetch_oil_prices,
        fetch_weather,
        fetch_space_weather,
        fetch_internet_outages,
        fetch_cctv,
        fetch_kiwisdr,
        fetch_frontlines,
        fetch_gdelt,
        fetch_datacenters,
        fetch_military_bases,
        fetch_eth_nodes,
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(slow_funcs)) as executor:
        futures = [executor.submit(func) for func in slow_funcs]
        concurrent.futures.wait(futures)
    logger.info("Slow-tier update complete.")

def update_all_data():
    """Full refresh — all tiers run IN PARALLEL for fastest startup."""
    logger.info("Full data update starting (parallel)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        f0 = pool.submit(fetch_airports)
        f1 = pool.submit(update_fast_data)
        f2 = pool.submit(update_slow_data)
        concurrent.futures.wait([f0, f1, f2])
    logger.info("Full data update complete.")

_scheduler = None

def start_scheduler():
    global _scheduler
    init_db()
    _scheduler = BackgroundScheduler(daemon=True)

    # Fast tier — every 60 seconds
    _scheduler.add_job(update_fast_data, 'interval', seconds=60, id='fast_tier', max_instances=1, misfire_grace_time=30)

    # Slow tier — every 5 minutes
    _scheduler.add_job(update_slow_data, 'interval', minutes=5, id='slow_tier', max_instances=1, misfire_grace_time=120)

    # Very slow — every 15 minutes
    _scheduler.add_job(fetch_gdelt, 'interval', minutes=15, id='gdelt', max_instances=1, misfire_grace_time=120)
    _scheduler.add_job(update_liveuamap, 'interval', minutes=15, id='liveuamap', max_instances=1, misfire_grace_time=120)

    # CCTV pipeline refresh — every 10 minutes
    # Instantiate once and reuse — avoids re-creating DB connections on every tick
    from services.cctv_pipeline import (
        TFLJamCamIngestor, LTASingaporeIngestor,
        AustinTXIngestor, NYCDOTIngestor,
    )
    _cctv_tfl = TFLJamCamIngestor()
    _cctv_lta = LTASingaporeIngestor()
    _cctv_atx = AustinTXIngestor()
    _cctv_nyc = NYCDOTIngestor()
    _scheduler.add_job(_cctv_tfl.ingest, 'interval', minutes=10, id='cctv_tfl', max_instances=1, misfire_grace_time=120)
    _scheduler.add_job(_cctv_lta.ingest, 'interval', minutes=10, id='cctv_lta', max_instances=1, misfire_grace_time=120)
    _scheduler.add_job(_cctv_atx.ingest, 'interval', minutes=10, id='cctv_atx', max_instances=1, misfire_grace_time=120)
    _scheduler.add_job(_cctv_nyc.ingest, 'interval', minutes=10, id='cctv_nyc', max_instances=1, misfire_grace_time=120)

    _scheduler.start()
    logger.info("Scheduler started.")

def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown(wait=False)

def get_latest_data():
    with _data_lock:
        return dict(latest_data)
