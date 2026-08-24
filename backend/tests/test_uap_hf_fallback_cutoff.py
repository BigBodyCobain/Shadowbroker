"""HF NUFORC fallback honors the rolling cutoff window.

Background
----------
The UAP sightings layer is sourced primarily from a live scrape of
nuforc.org. When that fails (Cloudflare 403, curl disabled on Windows,
wdtNonce regex stale, etc.) the code falls back to a static CSV mirror
hosted on Hugging Face at ``kcimc/NUFORC/nuforc_str.csv``.

The HF mirror is maintained by a third party and refreshed sporadically.
Pre-fix, the fallback parsed every row, sorted by ``occurred`` descending,
and took the top 250 — **with no date cutoff**. When the HF mirror is
stale (its "newest" rows are ~2-3 years old), users saw a map full of
2022-2023 sightings labeled as the "last 60 days" layer.

These tests pin the new behavior:

* Rows older than ``_NUFORC_RECENT_DAYS`` are dropped before the take-top-N.
* If the HF mirror has nothing in the window, the fallback returns ``[]``
  and logs ERROR (don't silently serve stale data).
* ``fetch_uap_sightings`` records the failure when BOTH paths fail, so
  the layer shows as broken in the health registry instead of "fresh".
"""

from __future__ import annotations

import json
import logging
from datetime import datetime as real_datetime


class _FixedDateTime(real_datetime):
    """A datetime whose utcnow() returns a pinned value, for deterministic
    cutoff math. Subclasses real datetime so existing operations still work."""

    @classmethod
    def utcnow(cls):
        return cls(2026, 5, 1, 12, 0, 0)


class _StubResponse:
    status_code = 200

    def __init__(self, text: str):
        self.text = text


def _stub_geocode_cache(*_args, **_kwargs):
    """Pre-populated location cache so the fallback doesn't try to hit
    Photon during the test."""
    return {
        "Denver, CO, USA": [39.7392, -104.9903],
        "Seattle, WA, USA": [47.6062, -122.3321],
        "Phoenix, AZ, USA": [33.4484, -112.0740],
    }


def test_hf_fallback_drops_rows_older_than_60_days(monkeypatch):
    """Pre-fix: a row from 2023 would make it into the layer if it was
    among the newest 250 in the HF mirror. Post-fix: it's filtered out
    before we even count to 250."""
    from services.fetchers import earth_observation as eo

    # 2026-05-01 - 60 days = 2026-03-02. So 2026-03-01 is one day too old.
    csv_text = (
        "Sighting,Occurred,Location,Shape,Duration,Posted,Summary\n"
        '1,2026-04-15 21:00:00 Local,"Denver, CO, USA",Triangle,5 minutes,2026-04-16,"In-window sighting"\n'
        '2,2023-06-01 21:00:00 Local,"Seattle, WA, USA",Light,30 seconds,2023-06-02,"Three years old"\n'
        '3,2022-01-15 20:00:00 Local,"Phoenix, AZ, USA",Disk,2 minutes,2022-01-16,"Even older"\n'
    )

    monkeypatch.setattr(eo, "datetime", _FixedDateTime)
    monkeypatch.setattr(eo, "fetch_with_curl", lambda *a, **kw: _StubResponse(csv_text))
    monkeypatch.setattr(eo, "_load_nuforc_location_cache", _stub_geocode_cache)
    monkeypatch.setattr(eo, "_save_nuforc_location_cache", lambda cache: None)
    # If the cutoff is missing, the geocoder may still get called for the
    # 2022/2023 rows. We assert geocoder is NEVER invoked for stale rows.
    geocode_calls: list[str] = []

    def _geocode_spy(location, city, state, country=""):
        geocode_calls.append(location)
        return None  # already in cache, shouldn't be hit anyway

    monkeypatch.setattr(eo, "_geocode_uap_location", _geocode_spy)

    sightings = eo._build_uap_sightings_from_hf_mirror()

    ids = [s["id"] for s in sightings]
    assert ids == ["NUFORC-1"], f"only the 2026 row should survive: got {ids}"
    # Stale rows must not have been geocoded — they should be dropped
    # before the geocoding loop is reached.
    assert geocode_calls == []


def test_hf_fallback_returns_empty_when_mirror_is_fully_stale(monkeypatch, caplog):
    """The smoking-gun case: the HF mirror is so stale that NO rows are
    within the rolling window. Pre-fix returned 250 ancient rows. Post-fix
    returns ``[]`` and logs ERROR so the operator knows the layer is dead."""
    from services.fetchers import earth_observation as eo

    csv_text = (
        "Sighting,Occurred,Location,Shape,Duration,Posted,Summary\n"
        '1,2023-04-15 21:00:00 Local,"Denver, CO, USA",Triangle,5 minutes,2023-04-16,"Old"\n'
        '2,2022-06-01 21:00:00 Local,"Seattle, WA, USA",Light,30 seconds,2022-06-02,"Older"\n'
        '3,2021-01-15 20:00:00 Local,"Phoenix, AZ, USA",Disk,2 minutes,2021-01-16,"Ancient"\n'
    )

    monkeypatch.setattr(eo, "datetime", _FixedDateTime)
    monkeypatch.setattr(eo, "fetch_with_curl", lambda *a, **kw: _StubResponse(csv_text))
    monkeypatch.setattr(eo, "_load_nuforc_location_cache", _stub_geocode_cache)
    monkeypatch.setattr(eo, "_save_nuforc_location_cache", lambda cache: None)
    monkeypatch.setattr(eo, "_geocode_uap_location", lambda *a, **kw: None)

    with caplog.at_level(logging.ERROR, logger="services.fetchers.earth_observation"):
        sightings = eo._build_uap_sightings_from_hf_mirror()

    assert sightings == []
    # The error log should mention how many stale rows were dropped so the
    # operator can tell the mirror is the problem (not "we got 0 rows" which
    # could also mean the download failed).
    relevant = [r for r in caplog.records if "HF fallback yielded 0 rows" in r.getMessage()]
    assert relevant, "expected loud ERROR when HF mirror is fully stale"
    # The message should report the count of dropped stale rows.
    assert any("dropped 3" in r.getMessage() for r in relevant)


def test_hf_fallback_still_returns_data_when_some_rows_are_in_window(monkeypatch):
    """Mixed-age mirror: some rows in the window, some not. The fallback
    should return only the in-window rows and not log the doomsday ERROR."""
    from services.fetchers import earth_observation as eo

    csv_text = (
        "Sighting,Occurred,Location,Shape,Duration,Posted,Summary\n"
        '1,2026-04-15 21:00:00 Local,"Denver, CO, USA",Triangle,5 minutes,2026-04-16,"Fresh"\n'
        '2,2026-04-10 21:00:00 Local,"Seattle, WA, USA",Light,30 seconds,2026-04-10,"Also fresh"\n'
        '3,2020-01-15 20:00:00 Local,"Phoenix, AZ, USA",Disk,2 minutes,2020-01-16,"Ancient"\n'
    )

    monkeypatch.setattr(eo, "datetime", _FixedDateTime)
    monkeypatch.setattr(eo, "fetch_with_curl", lambda *a, **kw: _StubResponse(csv_text))
    monkeypatch.setattr(eo, "_load_nuforc_location_cache", _stub_geocode_cache)
    monkeypatch.setattr(eo, "_save_nuforc_location_cache", lambda cache: None)
    monkeypatch.setattr(eo, "_geocode_uap_location", lambda *a, **kw: None)

    sightings = eo._build_uap_sightings_from_hf_mirror()

    ids = sorted(s["id"] for s in sightings)
    assert ids == ["NUFORC-1", "NUFORC-2"], f"only in-window rows should appear: got {ids}"


def test_fetch_uap_sightings_marks_failure_when_both_paths_empty(monkeypatch, caplog):
    """When the live path raises AND the HF fallback returns empty,
    ``fetch_uap_sightings`` must:
      * NOT mark the layer fresh (pre-fix bug: it did, so the layer
        showed as healthy-but-empty for days)
      * call ``assert_canary("uap_sightings", 0)`` so the health
        registry surfaces the broken layer
      * log an ERROR with the live-path exception for debugging
    """
    from services.fetchers import earth_observation as eo
    from services.fetchers import _store

    monkeypatch.setattr(_store, "is_any_active", lambda layer: True)
    monkeypatch.setattr(eo, "_load_nuforc_sightings_cache", lambda force_refresh=False: None)

    def _boom():
        raise RuntimeError("NUFORC live: zero rows pulled across 3 months")

    monkeypatch.setattr(eo, "_build_recent_uap_sightings", _boom)
    monkeypatch.setattr(eo, "_build_uap_sightings_from_hf_mirror", lambda: [])

    marked: list[str] = []
    monkeypatch.setattr(eo, "_mark_fresh", lambda *keys: marked.extend(keys))

    canary_calls: list[tuple[str, int]] = []
    import services.slo as slo
    monkeypatch.setattr(
        slo, "assert_canary", lambda key, value: canary_calls.append((key, int(value)))
    )

    with caplog.at_level(logging.ERROR, logger="services.fetchers.earth_observation"):
        eo.fetch_uap_sightings()

    assert marked == [], "broken layer must NOT be marked fresh"
    assert canary_calls == [("uap_sightings", 0)], (
        f"expected canary trip when both paths fail; got {canary_calls}"
    )
    # The live error message should propagate into the error log so the
    # operator can tell live failed AND fallback was empty (not the other
    # way around).
    assert any(
        "both live NUFORC and HF fallback" in r.getMessage()
        for r in caplog.records
    )


def test_fetch_uap_sightings_succeeds_when_fallback_returns_data(monkeypatch):
    """Positive path: live fails, fallback returns rows. The layer is
    populated and marked fresh; assert_canary is NOT tripped (we only
    trip the canary when the layer has zero data)."""
    from services.fetchers import earth_observation as eo
    from services.fetchers import _store

    monkeypatch.setattr(_store, "is_any_active", lambda layer: True)
    monkeypatch.setattr(eo, "_load_nuforc_sightings_cache", lambda force_refresh=False: None)
    monkeypatch.setattr(
        eo, "_build_recent_uap_sightings", lambda: (_ for _ in ()).throw(RuntimeError("live down"))
    )

    fallback_rows = [{"id": "NUFORC-fb-1", "date_time": "2026-04-20", "lat": 0.0, "lng": 0.0}]
    monkeypatch.setattr(eo, "_build_uap_sightings_from_hf_mirror", lambda: fallback_rows)
    monkeypatch.setattr(eo, "_save_nuforc_sightings_cache", lambda s: None)

    marked: list[str] = []
    monkeypatch.setattr(eo, "_mark_fresh", lambda *keys: marked.extend(keys))

    canary_calls: list[tuple[str, int]] = []
    import services.slo as slo
    monkeypatch.setattr(
        slo, "assert_canary", lambda key, value: canary_calls.append((key, int(value)))
    )

    eo.fetch_uap_sightings()

    assert marked == ["uap_sightings"]
    assert canary_calls == [], "canary should not trip when fallback supplies data"


def test_fetch_uap_sightings_retains_last_known_snapshot_when_refresh_empty(monkeypatch):
    """An empty weekly refresh must not erase the last visible UAP snapshot."""
    from services.fetchers import earth_observation as eo
    from services.fetchers import _store

    monkeypatch.setattr(_store, "is_any_active", lambda layer: True)
    monkeypatch.setattr(eo, "_load_nuforc_sightings_cache", lambda force_refresh=False: None)
    monkeypatch.setattr(
        eo,
        "_build_recent_uap_sightings",
        lambda: (_ for _ in ()).throw(RuntimeError("NUFORC unavailable")),
    )
    monkeypatch.setattr(eo, "_build_uap_sightings_from_hf_mirror", lambda: [])
    last_known = [{"id": "older-uap", "date_time": "2025-01-01", "lat": 39.7, "lng": -104.9}]
    monkeypatch.setattr(eo, "_load_nuforc_last_known_sightings", lambda: last_known)
    monkeypatch.setattr(eo, "_mark_fresh", lambda *keys: None)

    with _store._data_lock:
        _store.latest_data["uap_sightings"] = []

    eo.fetch_uap_sightings()

    with _store._data_lock:
        assert _store.latest_data["uap_sightings"] == last_known


def test_uap_scheduler_runs_weekly():
    """UAP layer refreshes weekly so each install pulls live NUFORC on a steady cadence."""
    from services import data_fetcher

    with open(data_fetcher.__file__, "r", encoding="utf-8") as f:
        text = f.read()

    assert "uap_sightings_weekly" in text
    idx = text.index("uap_sightings_weekly")
    block = text[max(0, idx - 600) : idx + 120]
    assert 'day_of_week="mon"' in block


def test_uap_cache_rejects_stale_rows_on_load(tmp_path, monkeypatch):
    """Disk cache must not resurrect sightings outside the rolling window."""
    from services.fetchers import earth_observation as eo

    cache_file = tmp_path / "nuforc_recent_sightings.json"
    monkeypatch.setattr(eo, "_NUFORC_SIGHTINGS_CACHE_FILE", cache_file)
    monkeypatch.setattr(eo, "datetime", _FixedDateTime)

    cache_file.write_text(
        json.dumps({
            "built": _FixedDateTime.utcnow().isoformat(),
            "cutoff_days": 60,
            "sightings": [
                {"id": "NUFORC-old", "date_time": "2023-06-01", "lat": 39.0, "lng": -105.0},
                {"id": "NUFORC-new", "date_time": "2026-04-20", "lat": 40.0, "lng": -104.0},
            ],
        }),
        encoding="utf-8",
    )

    loaded = eo._load_nuforc_sightings_cache()
    assert loaded is not None
    assert [s["id"] for s in loaded] == ["NUFORC-new"]
