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
import json
import math
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
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
    fetch_uap_sightings,
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
from services.fetchers.crowdthreat import fetch_crowdthreat  # noqa: F401
from services.fetchers.wastewater import fetch_wastewater  # noqa: F401
from services.fetchers.sar_catalog import fetch_sar_catalog  # noqa: F401
from services.fetchers.sar_products import fetch_sar_products  # noqa: F401
from services.fetchers.snapmap_osint import fetch_snapmap_osint, scan_interval_minutes as _snapmap_interval  # noqa: F401
from services.ais_stream import prune_stale_vessels  # noqa: F401

logger = logging.getLogger(__name__)
_SLOW_FETCH_S = float(os.environ.get("FETCH_SLOW_THRESHOLD_S", "5"))
# Hard wall-clock limit per individual fetch task.  A task that exceeds this
# is treated as a failure so it cannot block an entire fetch tier indefinitely.
_TASK_HARD_TIMEOUT_S = float(os.environ.get("FETCH_TASK_TIMEOUT_S", "120"))
_FAST_STARTUP_CACHE_MAX_AGE_S = float(os.environ.get("FAST_STARTUP_CACHE_MAX_AGE_S", "21600"))
_FAST_STARTUP_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "fast_startup_cache.json"
_FAST_STARTUP_CACHE_KEYS = (
    "commercial_flights",
    "military_flights",
    "private_flights",
    "private_jets",
    "tracked_flights",
    "ships",
    "uavs",
    "gps_jamming",
    "satellites",
    "satellite_source",
    "satellite_analysis",
    "sigint",
    "sigint_totals",
    "trains",
)
_INTEL_STARTUP_CACHE_MAX_AGE_S = float(os.environ.get("INTEL_STARTUP_CACHE_MAX_AGE_S", "21600"))
_INTEL_STARTUP_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "intel_startup_cache.json"
_INTEL_STARTUP_CACHE_KEYS = (
    "news",
    "gdelt",
    "liveuamap",
    "threat_level",
    "trending_markets",
    "correlations",
    "fimi",
    "crowdthreat",
    "uap_sightings",
    "military_bases",
    "wastewater",
)
_STARTUP_PRIORITY_TIMEOUT_S = float(os.environ.get("SHADOWBROKER_STARTUP_PRIORITY_TIMEOUT_S", "18"))
_STARTUP_HEAVY_REFRESH_DELAY_S = float(os.environ.get("SHADOWBROKER_STARTUP_HEAVY_REFRESH_DELAY_S", "90"))
_STARTUP_HEAVY_REFRESH_STARTED = False
_STARTUP_HEAVY_REFRESH_LOCK = threading.Lock()
_FETCH_WORKERS = int(os.environ.get("SHADOWBROKER_FETCH_WORKERS", "8"))
_SLOW_FETCH_CONCURRENCY = int(os.environ.get("SHADOWBROKER_SLOW_FETCH_CONCURRENCY", "4"))
_STARTUP_HEAVY_CONCURRENCY = int(os.environ.get("SHADOWBROKER_STARTUP_HEAVY_CONCURRENCY", "2"))

# Shared thread pool — reused across all fetch cycles instead of creating/destroying per tick
_SHARED_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(2, _FETCH_WORKERS), thread_name_prefix="fetch"
)


def _cache_json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _cache_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_cache_json_safe(v) for v in value]
    return value


def _has_cache_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _load_fast_startup_cache_if_available() -> bool:
    """Seed moving layers from a recent disk cache while live fetches warm up."""
    if _FAST_STARTUP_CACHE_MAX_AGE_S <= 0 or not _FAST_STARTUP_CACHE_PATH.exists():
        return False
    try:
        with _FAST_STARTUP_CACHE_PATH.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        cached_at = float(payload.get("cached_at") or 0)
        age_s = time.time() - cached_at
        if cached_at <= 0 or age_s > _FAST_STARTUP_CACHE_MAX_AGE_S:
            logger.info("Skipping stale fast startup cache (age %.1fs)", age_s)
            return False
        layers = payload.get("layers") or {}
        freshness = payload.get("freshness") or {}
        loaded: list[str] = []
        with _data_lock:
            for key in _FAST_STARTUP_CACHE_KEYS:
                if key in layers:
                    latest_data[key] = layers[key]
                    loaded.append(key)
            for key, ts in freshness.items():
                source_timestamps[str(key)] = ts
            if payload.get("last_updated"):
                latest_data["last_updated"] = payload.get("last_updated")
        if not loaded:
            return False
        from services.fetchers._store import bump_data_version

        bump_data_version()
        logger.info(
            "Loaded fast startup cache for %d layers (age %.1fs) so the map can paint before remote feeds finish",
            len(loaded),
            age_s,
        )
        return True
    except Exception as e:
        logger.warning("Fast startup cache load failed (non-fatal): %s", e)
        return False


def _save_fast_startup_cache() -> None:
    """Persist recent moving layers for the next cold start."""
    try:
        with _data_lock:
            layers = {
                key: latest_data.get(key)
                for key in _FAST_STARTUP_CACHE_KEYS
                if _has_cache_value(latest_data.get(key))
            }
            payload = {
                "cached_at": time.time(),
                "last_updated": latest_data.get("last_updated"),
                "layers": layers,
                "freshness": {
                    key: source_timestamps.get(key)
                    for key in _FAST_STARTUP_CACHE_KEYS
                    if source_timestamps.get(key)
                },
            }
        safe_payload = _cache_json_safe(payload)
        _FAST_STARTUP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _FAST_STARTUP_CACHE_PATH.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(safe_payload, fh, separators=(",", ":"))
        tmp_path.replace(_FAST_STARTUP_CACHE_PATH)
    except Exception as e:
        logger.debug("Fast startup cache save skipped: %s", e)


def _load_intel_startup_cache_if_available() -> bool:
    """Seed the right-side intelligence panel from disk while live feeds warm up."""
    if _INTEL_STARTUP_CACHE_MAX_AGE_S <= 0 or not _INTEL_STARTUP_CACHE_PATH.exists():
        return False
    try:
        with _INTEL_STARTUP_CACHE_PATH.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        cached_at = float(payload.get("cached_at") or 0)
        age_s = time.time() - cached_at
        if cached_at <= 0 or age_s > _INTEL_STARTUP_CACHE_MAX_AGE_S:
            logger.info("Skipping stale intel startup cache (age %.1fs)", age_s)
            return False
        layers = payload.get("layers") or {}
        freshness = payload.get("freshness") or {}
        loaded: list[str] = []
        with _data_lock:
            for key in _INTEL_STARTUP_CACHE_KEYS:
                if key in layers:
                    latest_data[key] = layers[key]
                    loaded.append(key)
            for key, ts in freshness.items():
                source_timestamps[str(key)] = ts
            if payload.get("last_updated"):
                latest_data["last_updated"] = payload.get("last_updated")
        if not loaded:
            return False
        from services.fetchers._store import bump_data_version

        bump_data_version()
        logger.info(
            "Loaded intel startup cache for %d layers (age %.1fs) so Global Threat Intercept can paint early",
            len(loaded),
            age_s,
        )
        return True
    except Exception as e:
        logger.warning("Intel startup cache load failed (non-fatal): %s", e)
        return False


def _save_intel_startup_cache() -> None:
    """Persist compact right-side intelligence data for the next cold start."""
    try:
        with _data_lock:
            layers = {
                key: latest_data.get(key)
                for key in _INTEL_STARTUP_CACHE_KEYS
                if _has_cache_value(latest_data.get(key))
            }
            payload = {
                "cached_at": time.time(),
                "last_updated": latest_data.get("last_updated"),
                "layers": layers,
                "freshness": {
                    key: source_timestamps.get(key)
                    for key in _INTEL_STARTUP_CACHE_KEYS
                    if source_timestamps.get(key)
                },
            }
        safe_payload = _cache_json_safe(payload)
        _INTEL_STARTUP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _INTEL_STARTUP_CACHE_PATH.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(safe_payload, fh, separators=(",", ":"))
        tmp_path.replace(_INTEL_STARTUP_CACHE_PATH)
    except Exception as e:
        logger.debug("Intel startup cache save skipped: %s", e)


def seed_startup_caches() -> None:
    """Load disk-backed first-paint caches without touching remote services."""
    load_meshtastic_cache_if_available()
    _load_fast_startup_cache_if_available()
    _load_intel_startup_cache_if_available()


# ---------------------------------------------------------------------------
# Scheduler & Orchestration
# ---------------------------------------------------------------------------
def _run_tasks(label: str, funcs: list, *, max_concurrency: int | None = None):
    """Run tasks concurrently and log any exceptions (do not fail silently)."""
    if not funcs:
        return
    if max_concurrency is None:
        if label.startswith("slow-tier"):
            max_concurrency = _SLOW_FETCH_CONCURRENCY
        elif label.startswith("startup-heavy"):
            max_concurrency = _STARTUP_HEAVY_CONCURRENCY
        else:
            max_concurrency = len(funcs)
    max_concurrency = max(1, min(max_concurrency, len(funcs)))

    remaining_funcs = list(funcs)
    while remaining_funcs:
        batch, remaining_funcs = remaining_funcs[:max_concurrency], remaining_funcs[max_concurrency:]
        futures = {_SHARED_EXECUTOR.submit(func): (func.__name__, time.perf_counter()) for func in batch}
        _drain_task_futures(label, futures)


def _drain_task_futures(label: str, futures: dict):
    # Iterate directly so future.result(timeout=...) is the blocking call.
    # as_completed() blocks inside __next__() waiting for completion — the timeout
    # on result() would never be reached for a hanging task under that pattern.
    for future, (name, start) in futures.items():
        try:
            future.result(timeout=_TASK_HARD_TIMEOUT_S)
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
    ]
    _run_tasks("fast-tier", fast_funcs)
    with _data_lock:
        latest_data["last_updated"] = datetime.utcnow().isoformat()
    from services.fetchers._store import bump_data_version
    bump_data_version()
    _save_fast_startup_cache()
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
        fetch_tinygs,
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
    _save_intel_startup_cache()
    logger.info("Slow-tier update complete.")


def _record_fetch_success(label: str, name: str, start: float) -> None:
    duration = time.perf_counter() - start
    from services.fetch_health import record_success

    record_success(name, duration_s=duration)
    if duration > _SLOW_FETCH_S:
        logger.warning(f"{label} task slow: {name} took {duration:.2f}s")


def _record_fetch_failure(label: str, name: str, start: float, error: Exception) -> None:
    duration = time.perf_counter() - start
    from services.fetch_health import record_failure

    record_failure(name, error=error, duration_s=duration)
    logger.exception(f"{label} task failed: {name}")


def _load_cctv_cache_for_startup() -> None:
    """Load cached CCTV rows without running remote ingestors during first paint."""
    try:
        fetch_cctv()
    except Exception as e:
        logger.warning("Startup CCTV cache load failed (non-fatal): %s", e)


def _run_delayed_startup_heavy_refresh() -> None:
    if _STARTUP_HEAVY_REFRESH_DELAY_S > 0:
        logger.info(
            "Startup heavy synthesis delayed %.0fs so the dashboard can finish first paint",
            _STARTUP_HEAVY_REFRESH_DELAY_S,
        )
        time.sleep(_STARTUP_HEAVY_REFRESH_DELAY_S)
    logger.info("Startup heavy synthesis beginning (slow feeds, enrichment, daily products)...")
    _run_tasks(
        "startup-heavy",
        [
            update_slow_data,
            fetch_volcanoes,
            fetch_viirs_change_nodes,
            fetch_unusual_whales,
            fetch_fimi,
            fetch_uap_sightings,
            fetch_wastewater,
            fetch_sar_catalog,
            fetch_sar_products,
        ],
    )
    logger.info("Startup heavy synthesis complete.")


def _schedule_delayed_startup_heavy_refresh() -> None:
    global _STARTUP_HEAVY_REFRESH_STARTED
    if _STARTUP_HEAVY_REFRESH_DELAY_S < 0:
        logger.info("Startup heavy synthesis disabled by SHADOWBROKER_STARTUP_HEAVY_REFRESH_DELAY_S")
        return
    with _STARTUP_HEAVY_REFRESH_LOCK:
        if _STARTUP_HEAVY_REFRESH_STARTED:
            return
        _STARTUP_HEAVY_REFRESH_STARTED = True
    threading.Thread(
        target=_run_delayed_startup_heavy_refresh,
        name="startup-heavy-refresh",
        daemon=True,
    ).start()


def update_all_data(*, startup_mode: bool = False):
    """Full refresh.

    On startup we prefer cached/DB-backed data first, then let scheduled jobs
    perform some heavy top-ups after the app is already responsive.
    """
    logger.info("Full data update starting (parallel)...")
    # Preload Meshtastic map cache immediately (instant, from disk)
    seed_startup_caches()
    with _data_lock:
        meshtastic_seeded = bool(latest_data.get("meshtastic_map_nodes"))
    if startup_mode:
        _load_cctv_cache_for_startup()
        priority_funcs = [
            fetch_airports,
            update_fast_data,
            fetch_news,
            fetch_gdelt,
            fetch_crowdthreat,
            fetch_firms_fires,
            fetch_weather_alerts,
        ]
        if not meshtastic_seeded:
            priority_funcs.append(fetch_meshtastic_nodes)
        else:
            logger.info(
                "Startup preload: Meshtastic cache already loaded, deferring remote map refresh to scheduled cadence"
            )
        logger.info("Startup priority preload starting (%d tasks)...", len(priority_funcs))
        cycle_start = time.perf_counter()
        futures = {
            _SHARED_EXECUTOR.submit(func): (func.__name__, time.perf_counter())
            for func in priority_funcs
        }
        for future, (name, start) in futures.items():
            remaining = _STARTUP_PRIORITY_TIMEOUT_S - (time.perf_counter() - cycle_start)
            if remaining <= 0:
                logger.info("Startup priority budget reached; %s will continue in background", name)
                continue
            try:
                future.result(timeout=remaining)
                _record_fetch_success("startup-priority", name, start)
            except concurrent.futures.TimeoutError:
                logger.info(
                    "Startup priority task still warming after %.1fs: %s",
                    time.perf_counter() - start,
                    name,
                )
            except Exception as e:
                _record_fetch_failure("startup-priority", name, start, e)
        logger.info("Startup preload: deferring Playwright Liveuamap scraper to scheduled cadence")
        _save_intel_startup_cache()
        _schedule_delayed_startup_heavy_refresh()
        logger.info("Startup priority preload complete; slow synthesis is warming in background.")
        return
    refresh_funcs = [
        fetch_airports,
        update_fast_data,
        update_slow_data,
        fetch_volcanoes,
        fetch_viirs_change_nodes,
        fetch_unusual_whales,
        fetch_fimi,
        fetch_gdelt,
        fetch_uap_sightings,
        fetch_wastewater,
        fetch_crowdthreat,
        fetch_sar_catalog,
        fetch_sar_products,
    ]
    if not startup_mode or not meshtastic_seeded:
        refresh_funcs.append(fetch_meshtastic_nodes)
    else:
        logger.info(
            "Startup preload: Meshtastic cache already loaded, deferring remote map refresh to scheduled cadence"
        )
    if not startup_mode:
        refresh_funcs.append(update_liveuamap)
    else:
        logger.info("Startup preload: deferring Playwright Liveuamap scraper to scheduled cadence")
    _run_tasks("full-refresh", refresh_funcs, max_concurrency=_STARTUP_HEAVY_CONCURRENCY)
    # Run CCTV ingest immediately so cameras are available on first request
    # (the scheduled job also runs every 10 min for ongoing refresh).
    if startup_mode:
        try:
            from services.cctv_pipeline import (
                TFLJamCamIngestor, LTASingaporeIngestor, AustinTXIngestor,
                NYCDOTIngestor, CaltransIngestor, ColoradoDOTIngestor,
                WSDOTIngestor, GeorgiaDOTIngestor, IllinoisDOTIngestor,
                MichiganDOTIngestor, WindyWebcamsIngestor, DGTNationalIngestor,
                MadridCityIngestor, OSMTrafficCameraIngestor, get_all_cameras,
            )
            from services.cctv_pipeline import OSMALPRCameraIngestor
            _startup_ingestors = [
                TFLJamCamIngestor(), LTASingaporeIngestor(), AustinTXIngestor(),
                NYCDOTIngestor(), CaltransIngestor(), ColoradoDOTIngestor(),
                WSDOTIngestor(), GeorgiaDOTIngestor(), IllinoisDOTIngestor(),
                MichiganDOTIngestor(), WindyWebcamsIngestor(), DGTNationalIngestor(),
                MadridCityIngestor(), OSMTrafficCameraIngestor(),
                OSMALPRCameraIngestor(),
            ]
            logger.info("Running CCTV ingest at startup (%d ingestors)...", len(_startup_ingestors))
            ingest_futures = {
                _SHARED_EXECUTOR.submit(ing.ingest): ing.__class__.__name__
                for ing in _startup_ingestors
            }
            for fut in concurrent.futures.as_completed(ingest_futures, timeout=90):
                name = ingest_futures[fut]
                try:
                    fut.result()
                except Exception as e:
                    logger.warning("CCTV startup ingest %s failed: %s", name, e)
            fetch_cctv()
            logger.info("CCTV startup ingest complete — %d cameras in DB", len(get_all_cameras()))
        except Exception as e:
            logger.warning("CCTV startup ingest failed (non-fatal): %s", e)

    logger.info("Full data update complete.")


_scheduler = None
_STARTUP_CCTV_INGEST_DELAY_S = int(os.environ.get("SHADOWBROKER_STARTUP_CCTV_INGEST_DELAY_S", "180"))
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

    # Flight observation pruning — drops icao24 → first_seen_at entries we
    # haven't seen in an hour. Same cadence as AIS prune for symmetry; the
    # per-tick scan is O(in-flight aircraft) so it's cheap.
    from services.fetchers.flight_observations import prune as _prune_flight_observations
    _scheduler.add_job(
        lambda: _run_task_with_health(_prune_flight_observations, "prune_flight_observations"),
        "interval",
        minutes=5,
        id="flight_observation_prune",
        max_instances=1,
        misfire_grace_time=60,
    )

    # AISHub REST fallback — slow polling when the AISStream WebSocket
    # primary is offline. Configurable interval via
    # AISHUB_POLL_INTERVAL_MINUTES env (default 20 min). Operator must
    # set AISHUB_USERNAME to opt in. The fetcher is gated internally on
    # the primary being disconnected, so this job is cheap when the
    # WebSocket is healthy (early-returns after a status check).
    from services.fetchers.aishub_fallback import (
        aishub_poll_interval_minutes,
        fetch_aishub_vessels,
    )
    _aishub_interval = aishub_poll_interval_minutes()
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_aishub_vessels, "fetch_aishub_vessels"),
        "interval",
        minutes=_aishub_interval,
        id="aishub_fallback",
        max_instances=1,
        misfire_grace_time=120,
    )

    # Route database — bulk refresh from vrs-standing-data.adsb.lol every 5
    # days. Replaces the legacy /api/0/routeset POST (blocked under our UA,
    # and broken upstream). Airline schedules change on a quarterly cycle,
    # so 5 days is well within the staleness budget; new flight numbers
    # added within the window simply fall back to UNKNOWN until refresh.
    from services.fetchers.route_database import refresh_route_database

    _scheduler.add_job(
        lambda: _run_task_with_health(refresh_route_database, "refresh_route_database"),
        "interval",
        days=5,
        id="route_database",
        max_instances=1,
        misfire_grace_time=3600,
    )

    # Aircraft metadata database — bulk refresh from OpenSky's public S3
    # bucket every 5 days. Provides hex24 -> ICAO type so OpenSky-sourced
    # flights (which lack 't' in /states/all) get aircraft category and
    # fuel/CO2 emissions populated. Snapshots are monthly; 5 days catches
    # newer drops without hammering the bucket.
    from services.fetchers.aircraft_database import refresh_aircraft_database

    _scheduler.add_job(
        lambda: _run_task_with_health(refresh_aircraft_database, "refresh_aircraft_database"),
        "interval",
        days=5,
        id="aircraft_database",
        max_instances=1,
        misfire_grace_time=3600,
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

    # Meshtastic map API — once per day with a per-install random offset to
    # avoid thundering the one-person hobby service at the top of the hour.
    # The fetcher also short-circuits on a fresh on-disk cache, so the
    # practical network cadence is closer to "once per day per install".
    import random as _random_jitter

    _meshtastic_jitter_minutes = _random_jitter.randint(0, 180)
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_meshtastic_nodes, "fetch_meshtastic_nodes"),
        "interval",
        hours=24,
        minutes=_meshtastic_jitter_minutes,
        id="meshtastic_map",
        max_instances=1,
        misfire_grace_time=3600,
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

    # UAP sightings (NUFORC) — weekly on Mondays at 12:00 UTC. The layer is a
    # rolling last-60-days digest; refreshing once a week is enough cadence
    # for human-readable map exploration and keeps load on nuforc.org light.
    _scheduler.add_job(
        lambda: _run_task_with_health(
            lambda: fetch_uap_sightings(force_refresh=True),
            "fetch_uap_sightings",
        ),
        "cron",
        day_of_week="mon",
        hour=12,
        minute=0,
        id="uap_sightings_weekly",
        max_instances=1,
        misfire_grace_time=3600,
    )

    # WastewaterSCAN pathogen surveillance — daily at 12:00 UTC (samples update ~daily)
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_wastewater, "fetch_wastewater"),
        "cron",
        hour=12,
        minute=0,
        id="wastewater_daily",
        max_instances=1,
        misfire_grace_time=3600,
    )

    # CrowdThreat verified threat intelligence — daily at 12:00 UTC
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_crowdthreat, "fetch_crowdthreat"),
        "cron",
        hour=12,
        minute=0,
        id="crowdthreat_daily",
        max_instances=1,
        misfire_grace_time=3600,
    )

    # Snap Map OSINT — watch-zone density scan (own cadence, min 10 min, default 15).
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_snapmap_osint, "fetch_snapmap_osint"),
        "interval",
        minutes=_snapmap_interval(),
        next_run_time=datetime.utcnow() + timedelta(seconds=90),
        id="snapmap_osint",
        max_instances=1,
        misfire_grace_time=600,
    )

    # SAR catalog (Mode A) — every hour, free metadata from ASF Search.
    # No account, no downloads, no DSP.  Pure scene catalog + coverage hints.
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_sar_catalog, "fetch_sar_catalog"),
        "interval",
        hours=1,
        id="sar_catalog",
        max_instances=1,
        misfire_grace_time=600,
        next_run_time=datetime.utcnow() + timedelta(minutes=3),
    )

    # SAR products (Mode B) — every 30 minutes, opt-in only.
    # Pre-processed deformation/flood/damage anomalies from OPERA, EGMS, GFM,
    # EMS, UNOSAT.  Disabled until both MESH_SAR_PRODUCTS_FETCH=allow and
    # MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE=true are set.
    _scheduler.add_job(
        lambda: _run_task_with_health(fetch_sar_products, "fetch_sar_products"),
        "interval",
        minutes=30,
        id="sar_products",
        max_instances=1,
        misfire_grace_time=600,
        next_run_time=datetime.utcnow() + timedelta(minutes=5),
    )

    # ── Time Machine auto-snapshots ─────────────────────────────────────
    # Compressed snapshots taken on two profiles (high_freq + standard).
    # Intervals are read from _timemachine_config at each invocation so
    # config changes via the API take effect without restarting.

    def _auto_snapshot_high_freq():
        """Auto-snapshot fast-moving layers (flights, ships, satellites)."""
        try:
            from services.node_settings import read_node_settings
            if not read_node_settings().get("timemachine_enabled", False):
                return  # Time Machine is off — skip
            from routers.ai_intel import _timemachine_config, _take_snapshot_internal
            cfg = _timemachine_config["profiles"]["high_freq"]
            if cfg["interval_minutes"] <= 0:
                return  # disabled
            layers = cfg["layers"]
            result = _take_snapshot_internal(layers=layers, profile="auto_high_freq", compress=True)
            logger.info("Time Machine auto-snapshot (high_freq): %s — %s layers",
                        result.get("snapshot_id"), len(result.get("layers", [])))
        except Exception as e:
            logger.warning("Time Machine auto-snapshot (high_freq) failed: %s", e)

    def _auto_snapshot_standard():
        """Auto-snapshot contextual layers (news, earthquakes, weather, etc.)."""
        try:
            from services.node_settings import read_node_settings
            if not read_node_settings().get("timemachine_enabled", False):
                return  # Time Machine is off — skip
            from routers.ai_intel import _timemachine_config, _take_snapshot_internal
            cfg = _timemachine_config["profiles"]["standard"]
            if cfg["interval_minutes"] <= 0:
                return  # disabled
            layers = cfg["layers"]
            result = _take_snapshot_internal(layers=layers, profile="auto_standard", compress=True)
            logger.info("Time Machine auto-snapshot (standard): %s — %s layers",
                        result.get("snapshot_id"), len(result.get("layers", [])))
        except Exception as e:
            logger.warning("Time Machine auto-snapshot (standard) failed: %s", e)

    _scheduler.add_job(
        _auto_snapshot_high_freq,
        "interval",
        minutes=15,
        id="timemachine_high_freq",
        max_instances=1,
        misfire_grace_time=60,
        next_run_time=datetime.utcnow() + timedelta(minutes=2),  # first snapshot 2m after startup
    )
    _scheduler.add_job(
        _auto_snapshot_standard,
        "interval",
        minutes=120,
        id="timemachine_standard",
        max_instances=1,
        misfire_grace_time=300,
        next_run_time=datetime.utcnow() + timedelta(minutes=5),  # first snapshot 5m after startup
    )

    _scheduler.start()
    logger.info("Scheduler started.")

    # Start the feed ingester daemon (refreshes feed-backed pin layers)
    try:
        from services.feed_ingester import start_feed_ingester
        start_feed_ingester()
    except Exception as e:
        logger.warning("Failed to start feed ingester: %s", e)


def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown(wait=False)


def get_latest_data():
    return get_latest_data_subset(*latest_data.keys())
