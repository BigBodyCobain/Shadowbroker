"""CISA KEV dateAdded values are date-only; recent ones must still be counted (#666)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from services.fetchers import cyber_status
from services.fetchers.cyber_status import _parse_kev_date


def _kev_date(days_ago: int) -> str:
    # Real catalog format: a bare date with no time or timezone.
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).date().isoformat()


def _fake_catalog(*days_ago: int):
    vulns = [
        {"cveID": f"CVE-2026-{1000 + i}", "dateAdded": _kev_date(d), "vulnerabilityName": "x"}
        for i, d in enumerate(days_ago)
    ]
    return SimpleNamespace(status_code=200, json=lambda: {"vulnerabilities": vulns})


def test_date_only_values_parse_as_aware_utc():
    parsed = _parse_kev_date("2026-11-03")
    assert parsed == datetime(2026, 11, 3, tzinfo=timezone.utc)


def test_full_timestamps_and_bad_values():
    assert _parse_kev_date("2026-11-03T12:00:00Z").tzinfo is not None
    assert _parse_kev_date("") is None
    assert _parse_kev_date("not-a-date") is None


def test_recent_date_only_entries_are_reported(monkeypatch):
    monkeypatch.setitem(cyber_status.latest_data, "cyber_threats", None)
    with (
        patch.object(cyber_status, "is_any_active", return_value=True),
        patch.object(cyber_status, "fetch_with_curl", return_value=_fake_catalog(1, 5, 29, 45, 400)),
    ):
        result = cyber_status.fetch_cyber_threats()

    # 1, 5 and 29 days ago are inside the 30-day window; 45 and 400 are not.
    assert [t["id"] for t in result["threats"]] == ["CVE-2026-1000", "CVE-2026-1001", "CVE-2026-1002"]
    assert result["stats"]["active_cves"] == 3
    assert result["stats"]["cisa_total"] == 5
