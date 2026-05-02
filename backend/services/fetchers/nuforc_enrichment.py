"""NUFORC Enrichment — downloads the Hugging Face NUFORC dataset and builds
a compact spatial+temporal index for enriching tilequery hits with shape,
duration, city, and summary text.

The full CSV (~170 MB) is streamed once and processed into a lightweight JSON
cache (~1-3 MB) stored at ``backend/data/nuforc_enrichment.json``.  Subsequent
startups load from cache until it expires (30 days).

Index structure::

    {
        "built": "2026-04-08T12:00:00",
        "count": 12345,
        "by_state": {
            "AZ": [
                {"d": "2024-01-15", "city": "Tucson", "shape": "triangle",
                 "dur": "5 minutes", "summary": "Bright triangular object..."},
                ...
            ],
            ...
        }
    }

Entries within each state are sorted by date descending (newest first).
"""

import csv
import gzip
import io
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from services.network_utils import fetch_with_curl

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_CACHE_FILE = _DATA_DIR / "nuforc_enrichment.json"
_CACHE_TTL_DAYS = 1  # Rebuild daily — fresh data each cycle

# HuggingFace dataset — use the structured string export, not the old flat blob.
_HF_CSV_URL = (
    "https://huggingface.co/datasets/kcimc/NUFORC/resolve/main/nuforc_str.csv"
)

# Only keep sightings from the last N years for the enrichment index
_KEEP_YEARS = 5

# ── In-memory index ────────────────────────────────────────────────────────
_index: dict | None = None
_index_lock = threading.Lock()
_building = False

# US state abbreviations for parsing "City, ST" locations
_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}


def _parse_location(loc: str) -> tuple[str, str]:
    """Parse 'City, ST' or 'City, ST (explanation)' → (city, state_abbr).

    Returns ('', '') if unparseable.
    """
    if not loc:
        return "", ""
    loc = re.sub(r"\s*\(.*\)\s*$", "", loc).strip()
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if len(parts) < 2:
        return "", ""
    for idx in range(len(parts) - 1):
        candidate = parts[idx + 1].upper().strip()
        if candidate in _US_STATES:
            city = ", ".join(parts[: idx + 1]).strip()
            return city, candidate
    candidate = parts[-1].upper().strip()
    if candidate in _US_STATES:
        return ", ".join(parts[:-1]).strip(), candidate
    return parts[0], ""


def _parse_date(date_str: str) -> str:
    """Best-effort parse NUFORC date strings → 'YYYY-MM-DD'.

    Returns '' on failure.
    """
    if not date_str:
        return ""
    cleaned = str(date_str).strip()
    cleaned = re.sub(r"\s+local$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+utc$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("T", " ")
    for fmt in (
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", cleaned)
    if match:
        return match.group(1)
    return ""


def _load_cache() -> dict | None:
    """Load the on-disk cache if it exists and is fresh enough."""
    if not _CACHE_FILE.exists():
        return None
    try:
        raw = _CACHE_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        built = data.get("built", "")
        if built:
            built_dt = datetime.fromisoformat(built)
            if datetime.utcnow() - built_dt < timedelta(days=_CACHE_TTL_DAYS):
                if int(data.get("count", 0) or 0) <= 0:
                    logger.info("NUFORC enrichment: cache is fresh but empty; rebuilding")
                    return None
                logger.info(
                    "NUFORC enrichment: loaded cache (%d entries, built %s)",
                    data.get("count", 0), built,
                )
                return data
            else:
                logger.info("NUFORC enrichment: cache expired (built %s)", built)
    except Exception as e:
        logger.warning("NUFORC enrichment: cache load error: %s", e)
    return None


def _save_cache(data: dict):
    """Persist the enrichment index to disk."""
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        logger.info("NUFORC enrichment: saved cache (%d entries)", data.get("count", 0))
    except Exception as e:
        logger.warning("NUFORC enrichment: cache save error: %s", e)


def _download_and_build() -> dict | None:
    """Stream-download the HF CSV and build the enrichment index.

    Returns the index dict or None on failure.
    """
    cutoff = datetime.utcnow() - timedelta(days=_KEEP_YEARS * 365)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    logger.info("NUFORC enrichment: downloading HF dataset (this may take a minute)...")
    try:
        resp = fetch_with_curl(_HF_CSV_URL, timeout=180, follow_redirects=True)
        if not resp or resp.status_code != 200:
            logger.warning(
                "NUFORC enrichment: download failed HTTP %s",
                getattr(resp, "status_code", "None"),
            )
            return None
    except Exception as e:
        logger.error("NUFORC enrichment: download error: %s", e)
        return None

    # Parse CSV from response text
    by_state: dict[str, list[dict]] = {}
    total = 0
    kept = 0

    try:
        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            total += 1
            occurred = _parse_date(
                row.get("Occurred", "")
                or row.get("Date / Time", "")
                or row.get("Date", "")
            )
            if not occurred or occurred < cutoff_str:
                continue

            city, state = _parse_location(
                row.get("Location", "")
                or row.get("City", "")
                or row.get("location", "")
            )
            if not state:
                continue  # can't index without state

            shape = (row.get("Shape", "") or row.get("shape", "") or "").strip()
            duration = (row.get("Duration", "") or row.get("duration", "") or "").strip()
            summary = (
                row.get("Summary", "")
                or row.get("summary", "")
                or row.get("Text", "")
                or row.get("text", "")
                or ""
            ).strip()
            if summary and len(summary) > 200:
                summary = summary[:197] + "..."

            entry = {"d": occurred, "city": city, "shape": shape}
            if duration:
                entry["dur"] = duration
            if summary:
                entry["sum"] = summary

            by_state.setdefault(state, []).append(entry)
            kept += 1
    except Exception as e:
        logger.error("NUFORC enrichment: CSV parse error: %s", e)
        return None

    # Sort each state's entries by date descending (newest first)
    for st in by_state:
        by_state[st].sort(key=lambda e: e["d"], reverse=True)

    data = {
        "built": datetime.utcnow().isoformat(),
        "count": kept,
        "by_state": by_state,
    }
    logger.info(
        "NUFORC enrichment: built index — %d entries from %d total rows (%d states)",
        kept, total, len(by_state),
    )
    return data


def _ensure_index():
    """Load or build the enrichment index (thread-safe, non-blocking)."""
    global _index, _building

    with _index_lock:
        if _index is not None:
            return
        if _building:
            return  # another thread is already building
        _building = True

    # Try loading from disk first
    cached = _load_cache()
    if cached:
        with _index_lock:
            _index = cached
            _building = False
        return

    # Download and build in background so we don't block startup
    def _build():
        global _index, _building
        try:
            result = _download_and_build()
            if result:
                _save_cache(result)
                with _index_lock:
                    _index = result
            else:
                logger.warning("NUFORC enrichment: build failed, enrichment unavailable")
        finally:
            with _index_lock:
                _building = False

    thread = threading.Thread(target=_build, name="nuforc-enrichment", daemon=True)
    thread.start()


def refresh_enrichment_index():
    """Force-rebuild the enrichment index.  Called by the daily cron job.

    Downloads the latest HF CSV, rebuilds the in-memory + disk cache.
    Runs synchronously (meant to be called from a background thread).
    """
    global _index
    logger.info("NUFORC enrichment: daily refresh starting...")
    result = _download_and_build()
    if result:
        _save_cache(result)
        with _index_lock:
            _index = result
        logger.info("NUFORC enrichment: daily refresh complete (%d entries)", result.get("count", 0))
    else:
        logger.warning("NUFORC enrichment: daily refresh failed, keeping stale index")


def enrich_sighting(state: str, from_date: str, to_date: str) -> dict:
    """Look up enrichment data for a tilequery hit.

    Args:
        state: 2-letter US state code (from reverse geocode)
        from_date: earliest sighting date (YYYY-MM-DD)
        to_date: latest sighting date (YYYY-MM-DD)

    Returns:
        Dict with optional keys: city, shape, duration, summary.
        Empty dict if no match found.
    """
    _ensure_index()

    with _index_lock:
        idx = _index

    if not idx or not state:
        return {}

    entries = idx.get("by_state", {}).get(state, [])
    if not entries:
        return {}

    # Find the best match by date proximity
    target = to_date or from_date
    if not target:
        # No date filter — just return the most recent entry for this state
        e = entries[0]
    else:
        best = None
        best_dist = 999999
        for e in entries:
            # Simple string distance on dates (YYYY-MM-DD sorts lexicographically)
            try:
                t = datetime.strptime(target, "%Y-%m-%d")
                d = datetime.strptime(e["d"], "%Y-%m-%d")
                dist = abs((t - d).days)
            except (ValueError, TypeError):
                continue
            if dist < best_dist:
                best_dist = dist
                best = e
            if dist == 0:
                break  # exact date match

        if best is None or best_dist > 90:
            return {}  # no match within 3 months
        e = best

    result = {}
    if e.get("city"):
        result["city"] = e["city"]
    if e.get("shape"):
        result["shape"] = e["shape"]
        result["shape_raw"] = e["shape"]
    if e.get("dur"):
        result["duration"] = e["dur"]
    if e.get("sum"):
        result["summary"] = e["sum"]
    return result
