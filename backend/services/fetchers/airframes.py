"""Airframes.io ACARS/VDL datalink ingest — staggered queue cache for plane dossiers."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("services.airframes")

API_BASE = os.environ.get("AIRFRAMES_API_BASE", "https://api.airframes.io/v1").rstrip("/")
SYNC_INTERVAL_MINUTES = max(5, int(os.environ.get("AIRFRAMES_SYNC_INTERVAL_MINUTES", "15")))
MAX_BULK_PAGES_PER_CYCLE = max(1, int(os.environ.get("AIRFRAMES_MAX_PAGES_PER_SYNC", "28")))
MESSAGES_PER_AIRCRAFT = max(5, int(os.environ.get("AIRFRAMES_MESSAGES_PER_AIRCRAFT", "40")))
RETENTION_HOURS = max(6, int(os.environ.get("AIRFRAMES_RETENTION_HOURS", "48")))
# 2s between calls => 30/min, safely under Airframes 60/min cap.
REQUEST_PAUSE_S = float(os.environ.get("AIRFRAMES_REQUEST_PAUSE_S", "2.0"))
PRIORITY_LOOKBACK_HOURS = max(6, int(os.environ.get("AIRFRAMES_PRIORITY_LOOKBACK_HOURS", "48")))
FETCH_TIMEOUT_S = max(5, int(os.environ.get("AIRFRAMES_FETCH_TIMEOUT_S", "20")))

_DATA_DIR = Path(os.environ.get("SB_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))
if not _DATA_DIR.is_absolute():
    _DATA_DIR = Path(__file__).resolve().parents[2] / _DATA_DIR
_CACHE_PATH = _DATA_DIR / "airframes_datalink_cache.json"

_lock = threading.Lock()
_queue_lock = threading.Lock()
_worker_guard = threading.Lock()
_queue: deque[dict[str, Any]] = deque()
_queued_aircraft_keys: set[str] = set()
_bulk_cursor: dict[str, Any] = {"since_iso": "", "before_id": None, "pages": 0}
_worker_started = False
_cache_loaded = False
_save_timer: threading.Timer | None = None
_save_timer_lock = threading.Lock()
_api_key_known_configured: bool | None = None
_cache: dict[str, Any] = {
    "last_sync_at": None,
    "last_success_at": None,
    "last_error": None,
    "pages_fetched": 0,
    "messages_ingested": 0,
    "bulk_pages_this_cycle": 0,
    "ticks_processed": 0,
    "by_icao": {},
    "by_tail": {},
    "by_callsign": {},
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        cleaned = value.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).astimezone(timezone.utc)
    except ValueError:
        return None


def api_key_configured() -> bool:
    global _api_key_known_configured
    if os.environ.get("AIRFRAMES_API_KEY", "").strip():
        _api_key_known_configured = True
        return True
    if _api_key_known_configured is False:
        return False
    from services.api_settings import load_persisted_api_keys_into_environ

    load_persisted_api_keys_into_environ()
    _api_key_known_configured = bool(os.environ.get("AIRFRAMES_API_KEY", "").strip())
    return _api_key_known_configured


def _norm_hex(value: str | None) -> str:
    return (value or "").strip().lower()


def _norm_tail(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").strip().upper())


def _norm_callsign(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").strip().upper())


def _aircraft_queue_key(entry: dict[str, str]) -> str:
    return f"{entry.get('icao24', '')}|{entry.get('registration', '')}|{entry.get('callsign', '')}"


def _tail_lookup_keys(value: str | None) -> list[str]:
    tail = _norm_tail(value)
    if not tail:
        return []
    keys = [tail]
    raw = (value or "").strip().upper()
    if raw and raw not in keys:
        keys.append(raw)
    return keys


def _load_cache_if_cold() -> None:
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    loaded: dict[str, Any] | None = None
    if _CACHE_PATH.exists():
        try:
            with _CACHE_PATH.open(encoding="utf-8") as handle:
                parsed = json.load(handle)
            if isinstance(parsed, dict):
                loaded = parsed
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to load Airframes cache: %s", exc)
    with _lock:
        if _cache_loaded:
            return
        if loaded:
            _cache.update(loaded)
            _cache.setdefault("by_callsign", {})
        _cache_loaded = True


def _persist_cache_now() -> None:
    with _lock:
        snapshot = json.dumps(_cache, indent=2, ensure_ascii=False) + "\n"
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(snapshot, encoding="utf-8")
    tmp.replace(_CACHE_PATH)


def _schedule_cache_persist() -> None:
    global _save_timer

    def _flush() -> None:
        global _save_timer
        try:
            _persist_cache_now()
        except OSError as exc:
            logger.warning("Failed to save Airframes cache: %s", exc)
        finally:
            with _save_timer_lock:
                _save_timer = None

    with _save_timer_lock:
        if _save_timer is not None:
            _save_timer.cancel()
        _save_timer = threading.Timer(0.75, _flush)
        _save_timer.daemon = True
        _save_timer.start()


def _save_cache() -> None:
    _schedule_cache_persist()


def _compact_message(raw: dict[str, Any]) -> dict[str, Any] | None:
    text = (raw.get("text") or raw.get("data") or "").strip()
    if not text:
        return None
    msg_id = raw.get("id")
    if msg_id is None:
        return None
    return {
        "id": int(msg_id),
        "timestamp": raw.get("timestamp") or raw.get("createdAt") or "",
        "label": str(raw.get("label") or "").strip(),
        "text": text[:500],
        "source_type": str(raw.get("sourceType") or raw.get("source") or "").strip(),
        "tail": _norm_tail(raw.get("tail")),
        "flight_number": _norm_callsign(raw.get("flightNumber")),
        "from_hex": _norm_hex(raw.get("fromHex")),
        "to_hex": _norm_hex(raw.get("toHex")),
    }


def _bucket_key(store: dict[str, list], key: str, message: dict[str, Any]) -> None:
    if not key:
        return
    bucket = store.setdefault(key, [])
    if any(existing.get("id") == message["id"] for existing in bucket):
        return
    bucket.append(message)
    bucket.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    del bucket[MESSAGES_PER_AIRCRAFT:]


def _index_message(compact: dict[str, Any]) -> None:
    for hex_code in (compact.get("from_hex"), compact.get("to_hex")):
        if hex_code:
            _bucket_key(_cache["by_icao"], hex_code, compact)
    for tail_key in _tail_lookup_keys(compact.get("tail")):
        _bucket_key(_cache["by_tail"], tail_key, compact)
    callsign = compact.get("flight_number")
    if callsign:
        _bucket_key(_cache["by_callsign"], callsign, compact)


def _prune_store(store: dict[str, list]) -> None:
    cutoff = _utc_now() - timedelta(hours=RETENTION_HOURS)
    for key in list(store.keys()):
        kept = []
        for message in store.get(key, []):
            ts = _parse_ts(message.get("timestamp"))
            if ts is None or ts >= cutoff:
                kept.append(message)
        if kept:
            store[key] = kept[:MESSAGES_PER_AIRCRAFT]
        else:
            del store[key]


def _ingest_message(message: dict[str, Any]) -> bool:
    compact = _compact_message(message)
    if not compact:
        return False
    _index_message(compact)
    return True


def _ingest_messages_batch(raw_messages: list[dict[str, Any]]) -> int:
    if not raw_messages:
        return 0
    ingested = 0
    with _lock:
        _cache.setdefault("by_callsign", {})
        for raw in raw_messages:
            if _ingest_message(raw):
                ingested += 1
        if ingested:
            _cache["messages_ingested"] = int(_cache.get("messages_ingested", 0)) + ingested
            _cache["last_success_at"] = _iso(_utc_now())
            _save_cache()
    return ingested


def _fetch_messages(*, api_key: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    response = requests.get(
        f"{API_BASE}/messages",
        headers={"Authorization": f"Bearer {api_key}"},
        params=params,
        timeout=FETCH_TIMEOUT_S,
    )
    if response.status_code == 404:
        logger.debug("Airframes messages 404 for params=%s", params)
        return []
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", "60"))
        raise RuntimeError(f"rate_limited:{retry_after}")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _refill_queue(*, since_iso: str, force: bool = False) -> int:
    """Queue bulk global ingest only — each bulk call returns up to 100 messages
    across many aircraft. Per-plane calls happen only on dossier cache miss."""
    global _bulk_cursor, _queued_aircraft_keys

    with _queue_lock:
        if force:
            _queue.clear()
            _queued_aircraft_keys = set()
            _bulk_cursor = {"since_iso": since_iso, "before_id": None, "pages": 0}

        added = 0
        has_bulk = any(item.get("type") == "bulk" for item in _queue)
        if not has_bulk:
            _bulk_cursor["since_iso"] = since_iso
            _queue.append({"type": "bulk", "since_iso": since_iso, "before_id": None})
            added += 1

    with _lock:
        _cache["bulk_pages_this_cycle"] = 0
        _save_cache()

    return added


def _prioritize_aircraft_scan(entry: dict[str, str]) -> bool:
    """Jump this aircraft to the front of the queue — next API tick (~2s)."""
    key = _aircraft_queue_key(entry)
    if key.replace("|", "").strip() == "":
        return False

    item = {"type": "aircraft", **entry}
    with _queue_lock:
        kept: deque[dict[str, Any]] = deque()
        for queued in _queue:
            if queued.get("type") == "aircraft" and _aircraft_queue_key(queued) == key:
                continue
            kept.append(queued)
        _queue.clear()
        _queue.extend(kept)
        _queued_aircraft_keys.discard(key)
        _queued_aircraft_keys.add(key)
        _queue.appendleft(item)
    return True


def _enqueue_bulk_page(*, since_iso: str, before_id: int | None = None) -> None:
    with _queue_lock:
        _queue.append({"type": "bulk", "since_iso": since_iso, "before_id": before_id})


def _process_aircraft_item(api_key: str, entry: dict[str, str]) -> int:
    since_iso = _iso(_utc_now() - timedelta(hours=PRIORITY_LOOKBACK_HOURS))
    params: dict[str, Any] = {
        "since": since_iso,
        "limit": 100,
        "exclude_errors": "1",
    }
    if entry.get("icao24"):
        params["icao"] = entry["icao24"]
    elif entry.get("registration"):
        params["text"] = entry["registration"]
    elif entry.get("callsign"):
        params["text"] = entry["callsign"]
    else:
        return 0

    try:
        batch = _fetch_messages(api_key=api_key, params=params)
    except Exception as exc:
        logger.debug("Airframes aircraft fetch failed for %s: %s", entry, exc)
        with _lock:
            _cache["last_error"] = str(exc)[:240]
            _save_cache()
        return 0

    return _ingest_messages_batch(batch)


def _process_bulk_item(api_key: str, item: dict[str, Any]) -> int:
    global _bulk_cursor

    params: dict[str, Any] = {
        "since": item["since_iso"],
        "limit": 100,
        "exclude_errors": "1",
    }
    before_id = item.get("before_id")
    if before_id is not None:
        params["before_id"] = before_id

    try:
        batch = _fetch_messages(api_key=api_key, params=params)
    except Exception as exc:
        logger.debug("Airframes bulk fetch failed: %s", exc)
        with _lock:
            _cache["last_error"] = str(exc)[:240]
            _save_cache()
        return 0

    ingested = _ingest_messages_batch(batch)

    with _lock:
        _bulk_cursor["pages"] = int(_bulk_cursor.get("pages", 0)) + 1
        _cache["pages_fetched"] = int(_cache.get("pages_fetched", 0)) + 1
        _save_cache()

    if (
        batch
        and len(batch) >= 100
        and _bulk_cursor.get("pages", 0) < MAX_BULK_PAGES_PER_CYCLE
    ):
        ids = [int(row["id"]) for row in batch if row.get("id") is not None]
        if ids:
            next_before = min(ids)
            if before_id is None or next_before < before_id:
                _enqueue_bulk_page(since_iso=item["since_iso"], before_id=next_before)

    return ingested


def _process_one_staggered_tick() -> int:
    """Process exactly one queued Airframes API call. Used by the background worker."""
    if not api_key_configured():
        return 0

    api_key = os.environ.get("AIRFRAMES_API_KEY", "").strip()
    with _queue_lock:
        if not _queue:
            return 0
        item = _queue.popleft()

    if item.get("type") == "aircraft":
        key = _aircraft_queue_key(item)
        with _queue_lock:
            _queued_aircraft_keys.discard(key)
        ingested = _process_aircraft_item(api_key, item)
    elif item.get("type") == "bulk":
        ingested = _process_bulk_item(api_key, item)
    else:
        ingested = 0

    with _lock:
        _cache["ticks_processed"] = int(_cache.get("ticks_processed", 0)) + 1
        if int(_cache.get("ticks_processed", 0)) % 25 == 0:
            for store_key in ("by_icao", "by_tail", "by_callsign"):
                _prune_store(_cache[store_key])
            _save_cache()

    return ingested


def _stagger_worker_loop() -> None:
    while True:
        time.sleep(REQUEST_PAUSE_S)
        try:
            _process_one_staggered_tick()
        except Exception as exc:
            logger.error("Airframes stagger worker tick failed: %s", exc)


def _ensure_stagger_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    with _worker_guard:
        if _worker_started:
            return
        _worker_started = True
        threading.Thread(
            target=_stagger_worker_loop,
            daemon=True,
            name="airframes-stagger",
        ).start()
        logger.info(
            "Airframes stagger worker started (bulk ingest: 1 call / %.1fs, up to %s msgs/call, refill every %sm)",
            REQUEST_PAUSE_S,
            100,
            SYNC_INTERVAL_MINUTES,
        )


def sync_airframes_messages(*, force: bool = False) -> dict[str, Any]:
    """Queue staggered Airframes fetches — one API call every REQUEST_PAUSE_S."""
    if not api_key_configured():
        return {"ok": False, "skipped": True, "reason": "AIRFRAMES_API_KEY not configured"}

    started = _utc_now()
    _load_cache_if_cold()

    with _lock:
        _cache.setdefault("by_callsign", {})
        last_sync_at = _parse_ts(_cache.get("last_sync_at"))
        if (
            not force
            and last_sync_at is not None
            and started - last_sync_at < timedelta(minutes=SYNC_INTERVAL_MINUTES - 1)
        ):
            return {"ok": True, "skipped": True, "reason": "sync_interval_not_elapsed"}

        if _cache.get("last_success_at"):
            since_dt = _parse_ts(_cache.get("last_success_at")) or (
                started - timedelta(minutes=SYNC_INTERVAL_MINUTES)
            )
            since_dt -= timedelta(minutes=2)
        else:
            since_dt = started - timedelta(hours=PRIORITY_LOOKBACK_HOURS)
        since_iso = _iso(since_dt)
        _cache["last_sync_at"] = _iso(started)
        _cache["last_error"] = None
        _save_cache()

    queued = _refill_queue(since_iso=since_iso, force=force)
    _ensure_stagger_worker()

    with _queue_lock:
        queue_depth = len(_queue)

    logger.info(
        "Airframes cycle queued: added=%s depth=%s interval=%.1fs",
        queued,
        queue_depth,
        REQUEST_PAUSE_S,
    )
    return {
        "ok": True,
        "queued": queued,
        "queue_depth": queue_depth,
        "request_interval_s": REQUEST_PAUSE_S,
        "sync_interval_minutes": SYNC_INTERVAL_MINUTES,
    }


def _lookup_from_cache(
    *,
    hex_key: str,
    tail_keys: list[str],
    callsign_key: str,
) -> tuple[list[dict[str, Any]], str | None]:
    _load_cache_if_cold()
    with _lock:
        _cache.setdefault("by_callsign", {})
        merged: dict[int, dict[str, Any]] = {}
        if hex_key:
            for message in _cache.get("by_icao", {}).get(hex_key, []):
                merged[message["id"]] = message
        for tail_key in tail_keys:
            for message in _cache.get("by_tail", {}).get(tail_key, []):
                merged[message["id"]] = message
        if callsign_key:
            for message in _cache.get("by_callsign", {}).get(callsign_key, []):
                merged[message["id"]] = message
        last_success_at = _cache.get("last_success_at")

    messages = sorted(merged.values(), key=lambda item: item.get("timestamp") or "", reverse=True)
    return messages[:MESSAGES_PER_AIRCRAFT], last_success_at


def get_datalink_status() -> dict[str, Any]:
    configured = api_key_configured()
    _load_cache_if_cold()
    with _queue_lock:
        queue_depth = len(_queue)
    with _lock:
        return {
            "configured": configured,
            "sync_interval_minutes": SYNC_INTERVAL_MINUTES,
            "request_interval_s": REQUEST_PAUSE_S,
            "last_sync_at": _cache.get("last_sync_at"),
            "last_success_at": _cache.get("last_success_at"),
            "last_error": _cache.get("last_error"),
            "pages_fetched": _cache.get("pages_fetched", 0),
            "messages_ingested": _cache.get("messages_ingested", 0),
            "bulk_pages_this_cycle": int(_bulk_cursor.get("pages", 0)),
            "bulk_pages_per_cycle": MAX_BULK_PAGES_PER_CYCLE,
            "messages_per_bulk_call": 100,
            "queue_depth": queue_depth,
            "ticks_processed": _cache.get("ticks_processed", 0),
            "icao_keys": len(_cache.get("by_icao", {})),
            "tail_keys": len(_cache.get("by_tail", {})),
            "callsign_keys": len(_cache.get("by_callsign", {})),
        }


def lookup_datalink_messages(
    *,
    icao24: str = "",
    registration: str = "",
    callsign: str = "",
    allow_live: bool = False,
) -> dict[str, Any]:
    configured = bool(os.environ.get("AIRFRAMES_API_KEY", "").strip()) or api_key_configured()
    if not configured:
        return {
            "configured": False,
            "messages": [],
            "hint": "Add AIRFRAMES_API_KEY in Settings → API Keys to enable ACARS datalink.",
        }

    hex_key = _norm_hex(icao24)
    tail_keys = _tail_lookup_keys(registration)
    callsign_key = _norm_callsign(callsign)

    messages, last_success_at = _lookup_from_cache(
        hex_key=hex_key,
        tail_keys=tail_keys,
        callsign_key=callsign_key,
    )

    queued_refresh = False
    if hex_key or tail_keys or callsign_key:
        queued_refresh = _prioritize_aircraft_scan(
            {
                "icao24": hex_key,
                "registration": _norm_tail(registration),
                "callsign": callsign_key,
            }
        )
        if queued_refresh:
            _ensure_stagger_worker()

    from services.fetchers.acars_summarize import prepare_datalink_display

    display = prepare_datalink_display(messages)

    return {
        "configured": True,
        "messages": display["messages"],
        "hidden_count": display["hidden_count"],
        "total_count": display["total_count"],
        "last_success_at": last_success_at,
        "queued_refresh": queued_refresh,
        "priority_scan": queued_refresh,
    }


_load_cache_if_cold()
