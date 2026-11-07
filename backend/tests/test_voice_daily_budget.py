"""Daily budget governor unit suite (voice-agent plan U1, §7.A item 9).

Covers: midnight rollover; lazy prune removing >30-day files only when the
hourly throttle stamp is expired (scandir call-counted); corrupt-file
quarantine with verbatim parse-error WARNING, fresh ledger at 0 and the
original preserved as ``.corrupt-*``; prune failure logging a WARNING without
raising; and the session-start budget gate incl. ``suggestTier``.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

import services.voice_daily_budget as vdb
from services.voice_daily_budget import (
    evaluate_daily_budget,
    read_daily_spend,
    record_response,
    record_session_start,
)

UTC = timezone.utc


def _day(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


@pytest.fixture()
def ledger_env(tmp_path, monkeypatch):
    """Point SB_DATA_DIR at an empty temp dir and reset the prune throttle."""
    monkeypatch.setenv("SB_DATA_DIR", str(tmp_path))
    vdb._reset_for_tests()
    yield tmp_path
    vdb._reset_for_tests()


def _write_raw_ledger(root, day: str, payload) -> None:
    path = root / "voice_cost" / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path.write_text(payload, encoding="utf-8")


def _read_raw_ledger(root, day: str):
    return json.loads((root / "voice_cost" / f"{day}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fresh reads + accumulation
# ---------------------------------------------------------------------------


def test_fresh_install_reads_zero_ledger_without_quarantine(ledger_env):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    spend = read_daily_spend(now=now)
    assert spend == {
        "date": "2026-08-24",
        "usdSpent": 0.0,
        "sessions": 0,
        "responses": 0,
        "incompleteSessions": 0,
        "fallbackMeteredResponses": 0,
        "ledgerQuarantined": False,
    }


def test_record_response_accumulates_and_persists(ledger_env):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    record_response(usd=1.25, now=now)
    record_response(
        usd=0.17, incomplete=True, fallback_metered=True, now=now
    )
    spend = read_daily_spend(now=now)
    assert spend["usdSpent"] == pytest.approx(1.42)
    assert spend["responses"] == 2
    assert spend["incompleteSessions"] == 1
    assert spend["fallbackMeteredResponses"] == 1
    # Reload from disk to prove persistence.
    assert _read_raw_ledger(ledger_env, "2026-08-24")["usdSpent"] == pytest.approx(1.42)


def test_session_start_counts_sessions_not_responses(ledger_env):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    record_session_start(now=now)
    record_session_start(now=now)
    spend = read_daily_spend(now=now)
    assert spend["sessions"] == 2
    assert spend["responses"] == 0
    assert spend["usdSpent"] == 0.0


# ---------------------------------------------------------------------------
# Item 9a — midnight rollover
# ---------------------------------------------------------------------------


def test_midnight_rollover_starts_a_fresh_ledger_per_utc_day(ledger_env):
    late = datetime(2026, 8, 24, 23, 59, tzinfo=UTC)
    early = datetime(2026, 8, 25, 0, 1, tzinfo=UTC)
    record_response(usd=3.0, now=late)
    spend = read_daily_spend(now=early)
    assert spend["date"] == "2026-08-25"
    assert spend["usdSpent"] == 0.0
    assert spend["responses"] == 0
    # Yesterday's ledger is preserved untouched.
    assert _read_raw_ledger(ledger_env, "2026-08-24")["usdSpent"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Item 9b — corrupt quarantine
# ---------------------------------------------------------------------------


def test_corrupt_ledger_quarantines_discloses_and_starts_fresh(ledger_env, caplog):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    garbage = "{not valid json!!"
    _write_raw_ledger(ledger_env, "2026-08-24", garbage)

    with caplog.at_level(logging.WARNING, logger="voice_daily_budget"):
        spend = read_daily_spend(now=now)

    assert spend["ledgerQuarantined"] is True
    assert spend["usdSpent"] == 0.0

    # Original preserved as <date>.corrupt-<epoch>.json.
    quarantined = sorted((ledger_env / "voice_cost").glob("2026-08-24.corrupt-*.json"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == garbage
    assert not (ledger_env / "voice_cost" / "2026-08-24.json").exists()

    # Parse error disclosed verbatim in the WARNING (the JSONDecodeError text).
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("corrupt" in r.getMessage() for r in warnings)
    assert any("Expecting property name enclosed in double quotes" in r.getMessage()
               for r in warnings)


@pytest.mark.parametrize(
    "raw",
    [
        "[1, 2, 3]",  # wrong top-level type
        '{"usdSpent": "lots"}',  # non-numeric spend
        '{"usdSpent": NaN}',  # NaN spend cannot be honest
        '{"usdSpent": -5}',  # negative spend cannot be honest
        '{"usdSpent": 1.0, "sessions": "many"}',  # bad counter shape
    ],
)
def test_invalid_shape_quarantines_like_a_parse_failure(ledger_env, raw, caplog):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    path = ledger_env / "voice_cost" / "2026-08-24.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="voice_daily_budget"):
        spend = read_daily_spend(now=now)
    assert spend["ledgerQuarantined"] is True
    assert spend["usdSpent"] == 0.0
    quarantined = sorted((ledger_env / "voice_cost").glob("2026-08-24.corrupt-*.json"))
    assert len(quarantined) == 1


def test_recording_after_quarantine_writes_a_fresh_ledger(ledger_env):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    _write_raw_ledger(ledger_env, "2026-08-24", "garbage{")
    spend = record_response(usd=0.5, now=now)
    assert spend["usdSpent"] == 0.5
    assert _read_raw_ledger(ledger_env, "2026-08-24")["usdSpent"] == 0.5


# ---------------------------------------------------------------------------
# Item 9c — lazy prune with hourly throttle (scandir counted)
# ---------------------------------------------------------------------------


def test_prune_removes_only_ledgers_older_than_retention(ledger_env):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    old_day = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    recent_day = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    edge_day = (now - timedelta(days=31)).strftime("%Y-%m-%d")
    _write_raw_ledger(ledger_env, old_day, {})
    _write_raw_ledger(ledger_env, recent_day, {})
    _write_raw_ledger(ledger_env, edge_day, {})  # 31 days old = >30 → pruned

    spend = read_daily_spend(now=now)
    assert spend["date"] == "2026-08-24"

    voice_dir = ledger_env / "voice_cost"
    assert not (voice_dir / f"{old_day}.json").exists(), ">30-day ledger pruned"
    assert (voice_dir / f"{recent_day}.json").exists(), "recent ledger kept"


def test_prune_runs_again_only_when_hourly_throttle_stamp_expires(ledger_env, monkeypatch):
    hour_one = datetime(2026, 8, 24, 12, 10, tzinfo=UTC)
    same_hour_later = datetime(2026, 8, 24, 12, 50, tzinfo=UTC)
    next_hour = datetime(2026, 8, 24, 13, 5, tzinfo=UTC)
    stale_day = "2026-06-01"

    scans = {"count": 0}
    real_scandir = os.scandir

    def counting_scandir(path):
        scans["count"] += 1
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", counting_scandir)

    _write_raw_ledger(ledger_env, stale_day, {})
    read_daily_spend(now=hour_one)
    first_scan_count = scans["count"]
    assert first_scan_count >= 1

    # A second read inside the SAME UTC hour must not rescan.
    _write_raw_ledger(ledger_env, stale_day, {})
    read_daily_spend(now=same_hour_later)
    assert scans["count"] == first_scan_count, "throttle suppressed the second scan"
    assert (ledger_env / "voice_cost" / f"{stale_day}.json").exists()

    # Once the stamp expires (next UTC hour), the scan runs again and prunes.
    read_daily_spend(now=next_hour)
    assert scans["count"] == first_scan_count + 1
    assert not (ledger_env / "voice_cost" / f"{stale_day}.json").exists()


def test_prune_failure_logs_warning_without_raising(ledger_env, caplog, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)

    def exploding_scandir(path):
        raise OSError("disk gone")

    monkeypatch.setattr(os, "scandir", exploding_scandir)

    with caplog.at_level(logging.WARNING, logger="voice_daily_budget"):
        spend = read_daily_spend(now=now)  # must not raise

    assert spend["date"] == "2026-08-24"
    assert any("prune" in r.getMessage().lower() for r in caplog.records)


def test_prune_never_touches_today_or_unrelated_files(ledger_env):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    _write_raw_ledger(ledger_env, "2026-08-24", {"usdSpent": 2.5})
    stray = ledger_env / "voice_cost" / "notes.txt"
    stray.write_text("keep me", encoding="utf-8")

    spend = read_daily_spend(now=now)
    assert spend["usdSpent"] == 2.5
    assert stray.exists()


# ---------------------------------------------------------------------------
# Budget gate + suggestTier
# ---------------------------------------------------------------------------


def test_unlimited_budget_is_allowed_with_off_sentinel():
    decision = evaluate_daily_budget({"usdSpent": 999.0}, 0.0)
    assert decision["allowed"] is True
    assert decision["remainingUsd"] == "off"
    assert decision["suggestTier"] is None


def test_over_budget_blocks_until_next_utc_midnight():
    now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    spend = {"usdSpent": 5.01}
    decision = evaluate_daily_budget(spend, 5.0, now=now)
    assert decision["allowed"] is False
    assert decision["reason"] == "budget"
    assert decision["resetsAt"] == "2026-08-25T00:00:00+00:00"
    assert decision["remainingUsd"] == 0.0


def test_remaining_under_quarter_suggests_mini_when_configured():
    now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    spend = {"usdSpent": 4.0}  # remaining $1 of $5 = 20%
    suggested = evaluate_daily_budget(spend, 5.0, mini_configured=True, now=now)
    assert suggested["allowed"] is True
    assert suggested["suggestTier"] == "mini"
    # Quality preference degrades, never silently hides the option either way.
    unsuggested = evaluate_daily_budget(spend, 5.0, mini_configured=False, now=now)
    assert unsuggested["suggestTier"] is None
    assert unsuggested["allowed"] is True


def test_remaining_at_or_above_quarter_does_not_suggest_mini():
    now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    spend = {"usdSpent": 3.75}  # remaining exactly 25%
    decision = evaluate_daily_budget(spend, 5.0, mini_configured=True, now=now)
    assert decision["allowed"] is True
    assert decision["suggestTier"] is None


def test_exact_boundary_spent_equals_budget_blocks():
    now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    decision = evaluate_daily_budget({"usdSpent": 5.0}, 5.0, now=now)
    assert decision["allowed"] is False


def test_full_flow_budget_gate_uses_persisted_ledger(ledger_env):
    now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    record_response(usd=4.6, now=now)
    decision = evaluate_daily_budget(read_daily_spend(now=now), 5.0,
                                     mini_configured=True, now=now)
    assert decision["allowed"] is True
    assert decision["remainingUsd"] == pytest.approx(0.4)
    assert decision["suggestTier"] == "mini"
