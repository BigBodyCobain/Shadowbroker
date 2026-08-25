"""
Persisted daily budget governor for the voice agent (voice-agent plan U1, §4.5).

Ledger layout: ``${SB_DATA_DIR:-backend/data}/voice_cost/<YYYY-MM-DD>.json``
(UTC day keys, per §1.6), shaped like::

    {"date":"2026-08-24","usdSpent":1.42,"sessions":6,"responses":118,
     "incompleteSessions":1,"fallbackMeteredResponses":9}

Design rules from the plan:

  - Atomic writes (temp + ``os.replace``, the api_settings discipline).
  - ``POST /api/voice/session`` consults the ledger first: over
    VOICE_DAILY_BUDGET_USD ⇒ budget-blocked with next-UTC-midnight reset.
    Remaining daily budget <25% ⇒ ``suggestTier: "mini"`` when configured —
    quality preference degrades, never silently.
  - Corrupt-ledger policy: quarantine (rename ``<date>.corrupt-<epoch>.json``,
    WARNING with parse error verbatim), fresh ledger at 0, quarantined flag
    disclosed; issuance is never blocked.
  - Lazy pruning only — NO APScheduler entry for voice (§1.5). Pruning of
    >30-day ledgers runs inside :func:`_prune_old_ledgers`, invoked from
    :func:`read_daily_spend` and :func:`record_response`, throttled by a
    module-level ``_LAST_PRUNE_UTC_HOUR`` stamp (≤1 scan/UTC hour); failures
    log WARNING and never fail the caller. The throttle state is module-level
    and monkeypatchable for deterministic tests.

Pure stdlib; no FastAPI imports (AST-freeze safe, §1.5).
"""

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("voice_daily_budget")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = BACKEND_ROOT / "data"

LEDGER_DIR_NAME = "voice_cost"
#: Ledgers strictly older than this many days are pruned (>30-day rule, §4.5).
LEDGER_RETENTION_DAYS = 30

_LEDGER_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")
_CORRUPT_SUFFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.corrupt-\d+\.json$")

#: UTC-hour stamp of the last prune scan (≤1 scan per hour). None = never run.
_LAST_PRUNE_UTC_HOUR: int | None = None


def _now_utc(now: datetime | None = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _ledger_dir() -> Path:
    """Resolve the voice_cost directory against SB_DATA_DIR at call time so
    tests can redirect persistence without import-order coupling."""
    raw = os.environ.get("SB_DATA_DIR")
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
    else:
        path = DEFAULT_DATA_DIR
    return path / LEDGER_DIR_NAME


def _reset_for_tests() -> None:
    """Test-only: clear the prune throttle between deterministic tests."""
    global _LAST_PRUNE_UTC_HOUR
    _LAST_PRUNE_UTC_HOUR = None


# ---------------------------------------------------------------------------
# Ledger primitives
# ---------------------------------------------------------------------------


def _zero_ledger(date_str: str) -> dict:
    return {
        "date": date_str,
        "usdSpent": 0.0,
        "sessions": 0,
        "responses": 0,
        "incompleteSessions": 0,
        "fallbackMeteredResponses": 0,
    }


def _coerce_ledger(raw: Any, date_str: str) -> dict | None:
    """Return a normalized ledger dict, or None if the payload is corrupt."""
    if not isinstance(raw, dict):
        return None
    try:
        usd_spent = float(raw.get("usdSpent", 0.0))
    except (TypeError, ValueError):
        return None
    if usd_spent != usd_spent or usd_spent < 0:  # NaN / negative = corrupt
        return None
    ledger = _zero_ledger(date_str)
    ledger["usdSpent"] = usd_spent
    for key in ("sessions", "responses", "incompleteSessions", "fallbackMeteredResponses"):
        value = raw.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        ledger[key] = value
    return ledger


def _write_ledger_atomic(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.tmp.")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(ledger, handle, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


def read_daily_spend(*, now: datetime | None = None) -> dict:
    """Load today's (UTC) ledger, quarantining a corrupt file if found.

    Returns the ledger dict plus ``ledgerQuarantined`` disclosure. Never
    raises for bad ledger content; disk errors other than corruption surface
    as a zero ledger with the error logged (issuance decisions must not crash).
    """
    moment = _now_utc(now)
    date_str = moment.strftime("%Y-%m-%d")
    _prune_old_ledgers(moment)

    path = _ledger_dir() / f"{date_str}.json"
    if not path.exists():
        return {**_zero_ledger(date_str), "ledgerQuarantined": False}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        ledger = _coerce_ledger(raw, date_str)
    except (OSError, ValueError) as exc:
        logger.warning(
            "Voice daily ledger at %s is corrupt (%s); quarantining and "
            "starting fresh at $0",
            path,
            exc,
        )
        _quarantine(path, moment)
        return {**_zero_ledger(date_str), "ledgerQuarantined": True}
    if ledger is None:
        logger.warning(
            "Voice daily ledger at %s has an invalid shape; quarantining and "
            "starting fresh at $0",
            path,
        )
        _quarantine(path, moment)
        return {**_zero_ledger(date_str), "ledgerQuarantined": True}
    return {**ledger, "ledgerQuarantined": False}


def _quarantine(path: Path, moment: datetime) -> None:
    target = path.with_name(f"{path.stem}.corrupt-{int(moment.timestamp())}.json")
    try:
        os.replace(path, target)
    except OSError as exc:  # disclose loudly either way; never block issuance
        logger.warning("Could not quarantine corrupt voice ledger %s: %s", path, exc)


def record_response(
    *,
    usd: float = 0.0,
    incomplete: bool = False,
    fallback_metered: bool = False,
    sessions_started: bool = False,
    now: datetime | None = None,
) -> dict:
    """Fold one metered response (or one session start) into today's ledger
    and persist it atomically. Returns the updated spend view."""
    moment = _now_utc(now)
    date_str = moment.strftime("%Y-%m-%d")
    _prune_old_ledgers(moment)

    path = _ledger_dir() / f"{date_str}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = None
    except (OSError, ValueError) as exc:
        logger.warning(
            "Voice daily ledger at %s is corrupt (%s); quarantining and "
            "starting fresh at $0",
            path,
            exc,
        )
        _quarantine(path, moment)
        raw = None

    ledger = _coerce_ledger(raw, date_str) or _zero_ledger(date_str)
    try:
        delta_usd = float(usd)
    except (TypeError, ValueError):
        delta_usd = 0.0
    if delta_usd != delta_usd or delta_usd < 0:  # NaN / negative → ignore
        delta_usd = 0.0
    ledger["usdSpent"] = round(ledger["usdSpent"] + delta_usd, 6)
    if sessions_started:
        ledger["sessions"] += 1
    if delta_usd > 0 or incomplete or fallback_metered:
        # A session start alone does not count as a metered response.
        ledger["responses"] += 1
    if incomplete:
        ledger["incompleteSessions"] += 1
    if fallback_metered:
        ledger["fallbackMeteredResponses"] += 1

    try:
        _write_ledger_atomic(path, ledger)
    except OSError as exc:  # in-memory view still returned; caller keeps working
        logger.warning("Could not persist voice daily ledger %s: %s", path, exc)
    return {**ledger, "ledgerQuarantined": False}


def record_session_start(*, now: datetime | None = None) -> dict:
    """Count one voice session against today's ledger."""
    return record_response(sessions_started=True, now=now)


# ---------------------------------------------------------------------------
# Budget gate (consumed by POST /api/voice/session, U2)
# ---------------------------------------------------------------------------


def evaluate_daily_budget(
    spend: dict,
    budget_usd: Any,
    *,
    mini_configured: bool = False,
    now: datetime | None = None,
) -> dict:
    """Gate one session-start request against the persisted daily ledger.

    - budget ≤ 0 (or 'off') = unlimited: allowed, ``remainingUsd: "off"``.
    - spent ≥ budget: not allowed; ``resetsAt`` is the next UTC midnight.
    - remaining < 25% of budget with a mini tier configured: ``suggestTier:
      "mini"`` — quality preference degrades, never silently.
    """
    try:
        budget = float(budget_usd)
    except (TypeError, ValueError):
        budget = 0.0
    if budget != budget or budget <= 0:
        return {
            "allowed": True,
            "reason": None,
            "resetsAt": None,
            "remainingUsd": "off",
            "suggestTier": None,
        }

    spent = spend.get("usdSpent", 0.0) if isinstance(spend, dict) else 0.0
    remaining = max(0.0, budget - float(spent))
    resets_at = _next_utc_midnight(_now_utc(now))
    if remaining <= 0:
        return {
            "allowed": False,
            "reason": "budget",
            "resetsAt": resets_at,
            "remainingUsd": 0.0,
            "suggestTier": None,
        }
    suggest = "mini" if mini_configured and remaining < 0.25 * budget else None
    return {
        "allowed": True,
        "reason": None,
        "resetsAt": resets_at,
        "remainingUsd": remaining,
        "suggestTier": suggest,
    }


def _next_utc_midnight(moment: datetime) -> str:
    tomorrow = (moment + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Lazy pruning (no scheduler job — §1.5)
# ---------------------------------------------------------------------------


def _prune_old_ledgers(moment: datetime | None = None) -> int:
    """Delete ledgers older than LEDGER_RETENTION_DAYS. ≤1 scan/UTC hour via
    the module-level throttle stamp; failures log WARNING, never raise."""
    global _LAST_PRUNE_UTC_HOUR
    moment = _now_utc(moment)
    current_hour = int(moment.timestamp() // 3600)
    if _LAST_PRUNE_UTC_HOUR == current_hour:
        return 0
    _LAST_PRUNE_UTC_HOUR = current_hour

    removed = 0
    try:
        entries = list(os.scandir(_ledger_dir()))
    except OSError as exc:
        logger.warning("Voice ledger prune scan failed: %s", exc)
        return 0

    cutoff_date = (moment - timedelta(days=LEDGER_RETENTION_DAYS)).date()
    cutoff_ts = moment.timestamp() - LEDGER_RETENTION_DAYS * 86400
    for entry in entries:
        stale = False
        name_match = _LEDGER_FILENAME_RE.match(entry.name)
        if name_match:
            try:
                stale = datetime.strptime(name_match.group(1), "%Y-%m-%d").date() < cutoff_date
            except ValueError:
                stale = False
        elif _CORRUPT_SUFFIX_RE.match(entry.name):
            try:
                stale = entry.stat().st_mtime < cutoff_ts
            except OSError:
                stale = False
        if not stale:
            continue
        try:
            os.remove(entry.path)
            removed += 1
        except OSError as exc:
            logger.warning("Could not prune old voice ledger %s: %s", entry.path, exc)
    return removed
