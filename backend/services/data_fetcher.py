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
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from services.cctv_pipeline import init_db

# Shared state — all fetcher modules read/write through this
from services.fetchers._store import (
    latest_data,
    source_timestamps,
    _mark_fresh,
    _data_lock,  # noqa: F401 — re-exported for main.py
    get_latest_data_subset,
)

# Domain-specific fetcher modules (already extracted)
from services.fetchers.flights import fetch_flights  # noqa: F401
from services.fetchers.flights import _BLIND_SPOT_REGIONS  # noqa: F401 — re-exported for tests
from services.fetchers.military import fetch_military_flights  # noqa: F401
from services.fetchers.satellites import fetch_satellites  # noqa: F401
from services.fetchers.news import fetch_news  # noqa: F401

# Newly extracted fetcher modules
from services.fetchers.financial import fetch_financial_markets  # noqa: F401
from services.fetchers.unusual_whales import fetch_unusual_whales  # noqa: F401
from services.fetchers.earth_observation import (  # noqa: F401
    fetch_earthquakes,
    fetch_firms_fires,
    fetch_firms_country_fires,
    fetch_space_weather,
    fetch_weather,
    fetch_weather_alerts,
    fetch_air_quality,
    fetch_volcanoes,
    fetch_viirs_change_nodes,
)
from services.fetchers.infrastructure import (  # noqa: F401
    fetch_internet_outages,
    fetch_ripe_atlas_probes,
    fetch_datacenters,
    fetch_military_bases,
    fetch_power_plants,
    fetch_cctv,
    fetch_kiwisdr,
    fetch_scanners,
    fetch_satnogs,
    fetch_tinygs,
    fetch_psk_reporter,
)
from services.fetchers.geo import (  # noqa: F401
    fetch_ships,
    fetch_airports,
    find_nearest_airport,
    cached_airports,
    fetch_frontlines,
    fetch_gdelt,
    fetch_geopolitics,
    update_liveuamap,
    fetch_fishing_activity,
)
from services.fetchers.prediction_markets import fetch_prediction_markets  # noqa: F401
from services.fetchers.sigint import fetch_sigint  # noqa: F401
from services.fetchers.trains import fetch_trains  # noqa: F401
from services.fetchers.ukraine_alerts import fetch_ukraine_air_raid_alerts  # noqa: F401
from services.fetchers.meshtastic_map import (
    fetch_meshtastic_nodes,
    load_meshtastic_cache_if_available,
)  # noqa: F401
from services.fetchers.fimi import fetch_fimi  # noqa: F401
from services.ais_stream import prune_stale_vessels  # noqa: F401

logger = logging.getLogger(__name__)
_SLOW_FETCH_S = float(os.environ.get("FETCH_SLOW_THRESHOLD_S", "5"))

# Shared thread pool — reused across all fetch cycles instead of creating/destroying per tick
_SHARED_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=20, thread_name_prefix="fetch"
)


# ---------------------------------------------------------------------------
# Scheduler & Orchestration
# ---------------------------------------------------------------------------
def _run_tasks(label: str, funcs: list):
    """Run tasks concurrently and log any exceptions (do not fail silently)."""
    if not funcs:
        return
    futures = {_SHARED_EXECUTOR.submit(func): (func.__name__, time.perf_counter()) for func in funcs}
    for future in concurrent.futures.as_completed(futures):
        name, start = futures[future]
        try:
            future.result()
            duration = time.perf_counter() - start
            from services.fetch_health import record_success

            record_success(name, duration_s=duration)
            if duration > _SLOW_FETCH_S:
                logger.warning(f"{label} task slow: {name} took {duration:.2f}s")
        except Exception as e:
            duration = time.perf_counter() - start
            from services.fetch_health import record_failure

            record_failure(name, error=e, duration_s=duration)
            logger.exception(f"{label} task failed: {name}")


def _run_task_with_health(func, name: str | None = None):
    """Run a single task with health tracking."""
    task_name = name or getattr(func, "__name__", "task")
    start = time.perf_counter()
    try:
        func()
        duration = time.perf_counter() - start
        from services.fetch_health import record_success

        record_success(task_name, duration_s=duration)
        if duration > _SLOW_FETCH_S:
            logger.warning(f"task slow: {task_name} took {duration:.2f}s")
    except Exception as e:
        duration = time.perf_counter() - start
        from services.fetch_health import record_failure

        record_failure(task_name, error=e, duration_s=duration)
        logger.exception(f"task failed: {task_name}")


def update_fast_data():
    """Fast-tier: moving entities that need frequent updates (every 60s)."""
    logger.info("Fast-tier data update starting...")
    fast_funcs = [
        fetch_flights,
        fetch_military_flights,
        fetch_ships,
        fetch_satellites,
        fetch_sigint,
        fetch_trains,
        fetch_tinygs,
    ]
    _run_tasks("fast-tier", fast_funcs)
    with _data_lock:
        latest_data["last_updated"] = datetime.utcnow().isoformat()
    from services.fetchers._store import bump_data_version
    bump_data_version()
    logger.info("Fast-tier update complete.")


def update_slow_data():
    """Slow-tier: contextual + enrichment data that refreshes less often (every 5–10 min)."""
    logger.info("Slow-tier data update starting...")
    slow_funcs = [
        fetch_news,
        fetch_prediction_markets,
        fetch_earthquakes,
        fetch_firms_fires,
        fetch_firms_country_fires,
        fetch_weather,
        fetch_space_weather,
        fetch_internet_outages,
        fetch_ripe_atlas_probes,  # runs after IODA to deduplicate
        fetch_cctv,
        fetch_kiwisdr,
        fetch_satnogs,
        fetch_frontlines,
        fetch_datacenters,
        fetch_military_bases,
        fetch_scanners,
        fetch_psk_reporter,
        fetch_weather_alerts,
        fetch_air_quality,
        fetch_fishing_activity,
        fetch_power_plants,
        fetch_ukraine_air_raid_alerts,
    ]
    _run_tasks("slow-tier", slow_funcs)
    # Run correlation engine after all data is fresh
    try:
        from services.correlation_engine import compute_correlations
        with _data_lock:
            snapshot = dict(latest_data)
        correlations = compute_correlations(snapshot)
        with _data_lock:
            latest_data["correlations"] = correlations
    except Exception as e:
        logger.error("Correlation engine failed: %s", e)
    from services.fetchers._store import bump_data_version
    bump_data_version()
    logger.info("Slow-tier update complete.")


def update_all_data(*, startup_mode: bool = False):
    """Full refresh.

    On startup we prefer cached/DB-backed data first, then let scheduled jobs
    perform some heavy top-ups after the app is already responsive.
    """
    logger.info("Full data update starting (parallel)...")
    # Preload Meshtastic map cache immediately (instant, from disk)
    load_meshtastic_cache_if_available()
    with _data_lock:
        meshtastic_seeded = bool(latest_data.get("meshtastic_map_nodes"))
    futures = {
        _SHARED_EXECUTOR.submit(fetch_airports): ("fetch_airports", time.perf_counter()),
        _SHARED_EXECUTOR.submit(update_fast_data): ("update_fast_data", time.perf_counter()),
        _SHARED_EXECUTOR.submit(update_slow_data): ("update_slow_data", time.perf_counter()),
        _SHARED_EXECUTOR.submit(fetch_volcanoes): ("fetch_volcanoes", time.perf_counter()),
        _SHARED_EXECUTOR.submit(fetch_viirs_change_nodes): ("fetch_viirs_change_nodes", time.perf_counter()),
        _SHARED_EXECUTOR.submit(fetch_unusual_whales): ("fetch_unusual_whales", time.perf_counter()),
        _SHARED_EXECUTOR.submit(fetch_fimi): ("fetch_fimi", time.perf_counter()),
        _SHARED_EXECUTOR.submit(fetch_gdelt): ("fetch_gdelt", time.perf_counter()),
        _SHARED_EXECUTOR.submit(update_liveuamap): ("update_liveuamap", time.perf_counter()),
    }
    if not startup_mode or not meshtastic_seeded:
        futures[_SHARED_EXECUTOR.submit(fetch_meshtastic_nodes)] = (
            "fetch_meshtastic_nodes",
            time.perf_counter(),
        )
    else:
        logger.info(
            "Startup preload: Meshtastic cache already loaded, deferring remote map refresh to scheduled cadence"
        )
    for future in concurrent.futures.as_completed(futures):
        name, start = futures[future]
        try:
            future.result()
            duration = time.perf_counter() - start
            from services.fetch_health import record_success

            record_success(name, duration_s=duration)
            if duration > _SLOW_FETCH_S:
                logger.warning(f"full-refresh task slow: {name} took {duration:.2f}s")
        except Exception as e:
            duration = time.perf_counter() - start
            from services.fetch_health import record_failure

            record_failure(name, error=e, duration_s=duration)
            logger.exception(f"full-refresh task failed: {name}")
    logger.info("Full data update complete.")


_scheduler = None
_STARTUP_CCTV_INGEST_DELAY_S = 30
_FINANCIAL_REFRESH_MINUTES = 30


def _oracle_resolution_sweep():
    """Hourly sweep: check if any markets with active predictions have concluded.

    Resolution logic:
    - If a market's end_date has passed AND it's no longer in the active API data → resolved
    - For binary markets: final probability determines outcome (>50% = yes, <50% = no)
    - For multi-outcome: the outcome with highest final probability wins
    """
    try:
        from services.mesh.mesh_oracle import oracle_ledger

        active_titles = oracle_ledger.get_active_markets()
        if not active_titles:
            return

        # Get current market data
        with _data_lock:
            markets = list(latest_data.get("prediction_markets", []))

        # Build lookup of active API markets
        api_titles = {m.get("title", "").lower(): m for m in markets}

        import time as _time

        now = _time.time()
        resolved_count = 0

        for title in active_titles:
            api_market = api_titles.get(title.lower())

            # If market still in API and end_date hasn't passed, skip
            if api_market:
                end_date = api_market.get("end_date")
                if end_date:
                    try:
                        from datetime import datetime, timezone

                        dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                        if dt.timestamp() > now:
                            continue  # Market hasn't ended yet
                    except Exception:
                        continue
                else:
                    continue  # No end date, can't auto-resolve

            # Market has concluded (past end_date or dropped from API)
            # Determine outcome from last known data
            if api_market:
                outcomes = api_market.get("outcomes", [])
                if outcomes and len(outcomes) > 2:
                    # Multi-outcome: highest pct wins
                    best = max(outcomes, key=lambda o: o.get("pct", 0))
                    outcome = best.get("name", "")
                else:
                    # Binary: consensus > 50 = yes
                    pct = api_market.get("consensus_pct") or api_market.get("polymarket_pct") or 50
                    outcome = "yes" if float(pct) > 50 else "no"
            else:
                # Market dropped from API entirely — can't determine outcome, skip
                logger.warning(
                    f"Oracle sweep: market '{title}' no longer in API, cannot auto-resolve"
                )
                continue

            if not outcome:
                continue

            # Resolve both free predictions and market stakes
            winners, losers = oracle_ledger.resolve_market(title, outcome)
            stake_result = oracle_ledger.resolve_market_stakes(title, outcome)
            resolved_count += 1
            logger.info(
                f"Oracle sweep resolved '{title}' → {outcome}: "
                f"{winners}W/{losers}L free, "
                f"{stake_result.get('winners', 0)}W/{stake_result.get('losers', 0)}L staked"
            )

        if resolved_count:
            logger.info(f"Oracle sweep complete: {resolved_count} markets resolved")
        # Also clean up old data periodically
        oracle_ledger.cleanup_old_data()

    except Exception as e:
        logger.error(f"Oracle resolution sweep error: {e}")


def start_scheduler():
    global _scheduler
    init_db()
    _scheduler = BackgroundScheduler(daemon=True)

    # Fast tier — every 60 seconds
    _scheduler.add_job(
        lambda: _run_task_with_health(update_fast_data, "update_fast_data"),
        "interval",
        seconds=60,
        id="fast_tier",
        max_instances=1,
        misfire_grace_time=30,
    )

    # Slow tier — every 5 minutes
    _scheduler.add_job(
        lambda: _run_task_with_health(update_slow_data, "update_slow_data"),
        "interval",
        minutes=5,
        id="slow_tier",
        max_instances=1,
        misfire_grace_time=120,
    )

    # Weather alerts — every 5 minutes (time-critical, separate from slow tier)
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_weather_alerts, "fetch_weather_alerts"),
        "interval",
        minutes=5,
        id="weather_alerts",
        max_instances=1,
        misfire_grace_time=60,
    )

    # Ukraine air raid alerts — every 2 minutes (time-critical)
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_ukraine_air_raid_alerts, "fetch_ukraine_air_raid_alerts"),
        "interval",
        minutes=2,
        id="ukraine_alerts",
        max_instances=1,
        misfire_grace_time=60,
    )

    # AIS vessel pruning — every 5 minutes (prevents unbounded memory growth)
    _scheduler.add_job(
        lambda: _run_task_with_health(prune_stale_vessels, "prune_stale_vessels"),
        "interval",
        minutes=5,
        id="ais_prune",
        max_instances=1,
        misfire_grace_time=60,
    )

    # GDELT — every 30 minutes (downloads 32 ZIP files per call, avoid rate limits)
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_gdelt, "fetch_gdelt"),
        "interval",
        minutes=30,
        id="gdelt",
        max_instances=1,
        misfire_grace_time=120,
    )
    _scheduler.add_job(
        lambda: _run_task_with_health(update_liveuamap, "update_liveuamap"),
        "interval",
        minutes=30,
        id="liveuamap",
        max_instances=1,
        misfire_grace_time=120,
    )

    # CCTV pipeline refresh — runs all ingestors, then refreshes in-memory data.
    # Delay the first run slightly so startup serves cached/DB-backed data first.
    from services.cctv_pipeline import (
        TFLJamCamIngestor,
        LTASingaporeIngestor,
        AustinTXIngestor,
        NYCDOTIngestor,
        CaltransIngestor,
        ColoradoDOTIngestor,
        WSDOTIngestor,
        GeorgiaDOTIngestor,
        IllinoisDOTIngestor,
        MichiganDOTIngestor,
        WindyWebcamsIngestor,
        DGTNationalIngestor,
        MadridCityIngestor,
        OSMTrafficCameraIngestor,
    )

    _cctv_ingestors = [
        (TFLJamCamIngestor(), "cctv_tfl"),
        (LTASingaporeIngestor(), "cctv_lta"),
        (AustinTXIngestor(), "cctv_atx"),
        (NYCDOTIngestor(), "cctv_nyc"),
        (CaltransIngestor(), "cctv_caltrans"),
        (ColoradoDOTIngestor(), "cctv_codot"),
        (WSDOTIngestor(), "cctv_wsdot"),
        (GeorgiaDOTIngestor(), "cctv_gdot"),
        (IllinoisDOTIngestor(), "cctv_idot"),
        (MichiganDOTIngestor(), "cctv_mdot"),
        (WindyWebcamsIngestor(), "cctv_windy"),
        (DGTNationalIngestor(), "cctv_dgt"),
        (MadridCityIngestor(), "cctv_madrid"),
        (OSMTrafficCameraIngestor(), "cctv_osm"),
    ]

    def _run_cctv_ingest_cycle():
        from services.fetchers._store import is_any_active

        if not is_any_active("cctv"):
            return
        for ingestor, name in _cctv_ingestors:
            _run_task_with_health(ingestor.ingest, name)
        # Refresh in-memory CCTV data immediately after ingest
        try:
            from services.cctv_pipeline import get_all_cameras
            from services.fetchers.infrastructure import fetch_cctv
            fetch_cctv()
            logger.info(f"CCTV ingest cycle complete — {len(get_all_cameras())} cameras in DB")
        except Exception as e:
            logger.warning(f"CCTV post-ingest refresh failed: {e}")

    _scheduler.add_job(
        _run_cctv_ingest_cycle,
        "interval",
        minutes=10,
        id="cctv_ingest",
        max_instances=1,
        misfire_grace_time=120,
        next_run_time=datetime.utcnow() + timedelta(seconds=_STARTUP_CCTV_INGEST_DELAY_S),
    )

    # Financial tickers — every 30 minutes (Yahoo Finance rate-limits aggressively)
    def _fetch_financial():
        _run_task_with_health(fetch_financial_markets, "fetch_financial_markets")

    _scheduler.add_job(
        _fetch_financial,
        "interval",
        minutes=_FINANCIAL_REFRESH_MINUTES,
        id="financial_tickers",
        max_instances=1,
        misfire_grace_time=120,
        next_run_time=datetime.utcnow() + timedelta(minutes=_FINANCIAL_REFRESH_MINUTES),
    )

    # Unusual Whales — every 15 minutes (congress trades, dark pool, flow alerts)
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_unusual_whales, "fetch_unusual_whales"),
        "interval",
        minutes=15,
        id="unusual_whales",
        max_instances=1,
        misfire_grace_time=120,
    )

    # Meshtastic map API — every 4 hours, fetch global node positions
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_meshtastic_nodes, "fetch_meshtastic_nodes"),
        "interval",
        hours=4,
        id="meshtastic_map",
        max_instances=1,
        misfire_grace_time=600,
    )

    # Oracle resolution sweep — every hour, check if any markets with predictions have concluded
    _scheduler.add_job(
        lambda: _run_task_with_health(_oracle_resolution_sweep, "oracle_sweep"),
        "interval",
        hours=1,
        id="oracle_sweep",
        max_instances=1,
        misfire_grace_time=300,
    )

    # VIIRS change detection — every 12 hours (monthly composites, no rush)
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_viirs_change_nodes, "fetch_viirs_change_nodes"),
        "interval",
        hours=12,
        id="viirs_change",
        max_instances=1,
        misfire_grace_time=600,
    )

    # FIMI disinformation index — every 12 hours (weekly editorial feed)
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_fimi, "fetch_fimi"),
        "interval",
        hours=12,
        id="fimi",
        max_instances=1,
        misfire_grace_time=600,
    )

    _scheduler.start()
    logger.info("Scheduler started.")


def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown(wait=False)


def get_latest_data():
    return get_latest_data_subset(*latest_data.keys())
