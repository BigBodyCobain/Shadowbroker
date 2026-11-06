"""Store-hygiene guards for per-layer freshness stamps (voice-agent plan U0, §7.A).

Three tiers:

1. AST adjacency guard — every ``latest_data[<key>] = …`` write must be paired
   with a ``_mark_fresh(<key>)`` stamp in the same enclosing function, be a
   derived layer whose freshness is inherited from a parent, or sit on an
   explicit allowlist. Deleting a stamp turns this red naming the offending
   function — it kills the exact ``tracked_flights`` / ``correlations``
   defect class where a written-but-never-stamped layer silently disabled
   fast-tier delta delivery for ALL delta layers.
2. Correlations runtime probe — runs the real slow-tier cycle with fetch
   symbols stubbed and asserts the ``correlations`` fingerprint exists.
   A static table-vs-constants comparison cannot catch this gap.
3. Tracked-flights delta recovery — two successive stamped writes feed the
   delta ring; echoing v1 yields non-empty upserts at v2 and
   ``/api/live-data/fast`` answers ``X-SB-Mode: delta``. Without the stamp
   the endpoint falls back to full snapshots (regression-locked).
"""

import ast
from pathlib import Path

import pytest

from services.fetchers import _store
from services.fetchers._store import (
    _data_lock,
    _mark_fresh,
    _layer_versions,
    active_layers,
    compute_layer_row_delta,
    get_layer_version,
    latest_data,
    source_timestamps,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Tier 1 fixtures: exemptions are explicit and commented — anything not listed
# here must be stamped in-function.
# ---------------------------------------------------------------------------

# Metadata companions written alongside real layers. They carry no freshness of
# their own (never narrated, never delta-delivered as a layer).
META_KEYS = frozenset(
    {
        "last_updated",
        "threat_level",
        "satellite_source",
        "satellite_analysis",
        "sigint_totals",
        "mesh_channel_stats",
        "trending_markets",  # companion projection of prediction_markets
        "meshtastic_map_fetched_at",
        "financial_source",
    }
)

# Mirrored from frontend/src/lib/voiceFreshness.ts (U5): layers whose freshness
# disposition is inherited from a parent layer instead of being stamped.
DERIVED_LAYER_FRESHNESS_PARENT = {
    "gps_jamming": "commercial_flights",
}

# File-scoped exceptions. Each entry needs a reason a reviewer can check.
FILE_ALLOWLIST = {
    # Raw merged ADS-B aggregate and snapshot restore; the authoritative
    # military_flights stamp lives in services/fetchers/military.py.
    "services/fetchers/flights.py": frozenset({"flights", "military_flights"}),
    # Static opportunistic reference cache — never narrated on a cadence.
    "services/fetchers/geo.py": frozenset({"airports"}),
    # Meshtastic node map caches; the existing _mark_fresh("meshtastic_map")
    # calls target a legacy key, out of U0's no-other-stamps scope guard.
    "services/fetchers/meshtastic_map.py": frozenset({"meshtastic_map_nodes"}),
}

# Modules covered by the adjacency guard (plan §7.A tier 1 scope).
GUARD_PATHS = ("services", "routers/data.py")


def _iter_guard_modules():
    services_dir = BACKEND_ROOT / "services"
    for path in sorted(services_dir.rglob("*.py")):
        yield path.relative_to(BACKEND_ROOT).as_posix(), path
    yield "routers/data.py", BACKEND_ROOT / "routers" / "data.py"


def _function_facts(tree):
    """Yield (function_name, written_keys, stamped_keys) per function node."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        writes = set()
        stamps = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                for target in sub.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "latest_data"
                    ):
                        key = getattr(target.slice, "value", None)
                        if isinstance(key, str):
                            writes.add(key)
            elif isinstance(sub, ast.Call):
                func = sub.func
                if isinstance(func, ast.Name) and func.id == "_mark_fresh":
                    for arg in sub.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            stamps.add(arg.value)
        yield node.name, writes, stamps


def test_every_written_layer_is_stamped_in_function_or_exempt():
    violations = []
    for rel, path in _iter_guard_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for func_name, writes, stamps in _function_facts(tree):
            for key in sorted(writes - stamps):
                if key in META_KEYS or key in DERIVED_LAYER_FRESHNESS_PARENT:
                    continue
                if key in FILE_ALLOWLIST.get(rel, frozenset()):
                    continue
                violations.append(
                    f"{rel}::{func_name} writes latest_data[{key!r}] without a "
                    f"matching _mark_fresh({key!r}) stamp in the same function"
                )
    assert not violations, (
        "freshness-stamp adjacency violations (delete-class defect):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Shared helpers for the runtime probes
# ---------------------------------------------------------------------------

@pytest.fixture()
def clean_fingerprints():
    """Snapshot and restore ALL shared store state the probes mutate.

    The store is process-global: without a full restore, versions stamped here
    leak into sibling suites that assume pristine counters (e.g. the P2 delta
    tests use ``_layer_versions.setdefault``).
    """
    touched_layers = (
        "tracked_flights",
        "correlations",
        "ships",
        "commercial_flights",
        "military_flights",
        "private_flights",
        "private_jets",
    )
    with _data_lock:
        saved_versions = dict(_layer_versions)
        saved_timestamps = dict(source_timestamps)
        saved_layers = {key: latest_data.get(key) for key in touched_layers}
    yield
    with _data_lock:
        for key, value in saved_layers.items():
            latest_data[key] = [] if value is None else value
        source_timestamps.clear()
        source_timestamps.update(saved_timestamps)
        _layer_versions.clear()
        _layer_versions.update(saved_versions)


def _reset_fingerprint(key):
    with _data_lock:
        source_timestamps.pop(key, None)
        _layer_versions.pop(key, None)


def _write_layer(key, items):
    with _data_lock:
        latest_data[key] = items


# ---------------------------------------------------------------------------
# Tier 2: correlations runtime probe (§7.A item 2)
# ---------------------------------------------------------------------------

def test_slow_tier_cycle_stamps_correlations(monkeypatch, clean_fingerprints):
    import services.data_fetcher as data_fetcher
    import services.correlation_engine as correlation_engine

    _reset_fingerprint("correlations")

    # Stub every slow-tier fetch symbol to a no-op so only the correlation
    # engine's write path executes.
    slow_fetch_symbols = [
        "fetch_news",
        "fetch_earthquakes",
        "fetch_firms_fires",
        "fetch_firms_country_fires",
        "fetch_weather",
        "fetch_space_weather",
        "fetch_internet_outages",
        "fetch_ripe_atlas_probes",
        "fetch_cctv",
        "fetch_kiwisdr",
        "fetch_satnogs",
        "fetch_tinygs",
        "fetch_frontlines",
        "fetch_datacenters",
        "fetch_military_bases",
        "fetch_scanners",
        "fetch_psk_reporter",
        "fetch_air_quality",
        "fetch_fishing_activity",
        "fetch_power_plants",
        "fetch_malware_threats",
        "fetch_cyber_threats",
        "fetch_scm_suppliers",
    ]
    for name in slow_fetch_symbols:
        monkeypatch.setattr(data_fetcher, name, lambda *a, **k: None)
    monkeypatch.setattr(correlation_engine, "compute_correlations", lambda snapshot: [])
    monkeypatch.setitem(active_layers, "correlations", True)

    import analytics.integration as analytics_integration

    monkeypatch.setattr(analytics_integration, "maybe_refresh_gt_analytics", lambda: None)
    monkeypatch.setattr(data_fetcher, "_save_intel_startup_cache", lambda: None)

    data_fetcher.update_slow_data()

    assert source_timestamps.get("correlations"), (
        "update_slow_data wrote correlations without stamping it fresh"
    )
    assert get_layer_version("correlations") == 1


def test_slow_tier_cycle_skips_correlations_stamp_when_overlay_disabled(
    monkeypatch, clean_fingerprints
):
    """Correlation-toggle honesty rule: overlay off ⇒ engine doesn't run ⇒ no stamp."""
    import services.data_fetcher as data_fetcher

    _reset_fingerprint("correlations")

    def _fail_compute(snapshot):  # pragma: no cover - must never run
        raise AssertionError("compute_correlations ran while overlay disabled")

    import services.correlation_engine as correlation_engine

    monkeypatch.setattr(correlation_engine, "compute_correlations", _fail_compute)
    monkeypatch.setitem(active_layers, "correlations", False)

    import analytics.integration as analytics_integration

    monkeypatch.setattr(analytics_integration, "maybe_refresh_gt_analytics", lambda: None)
    monkeypatch.setattr(data_fetcher, "_save_intel_startup_cache", lambda: None)

    monkeypatch.setattr(data_fetcher, "_run_tasks", lambda label, funcs, **kw: None)

    data_fetcher.update_slow_data()

    assert get_layer_version("correlations") == 0


# ---------------------------------------------------------------------------
# Tier 3: tracked-flights delta recovery (§7.A item 3)
# ---------------------------------------------------------------------------

_FLIGHT_A_V1 = {"icao24": "aaa111", "lat": 50.45, "lng": 30.52, "alt": 9000}
_FLIGHT_A_V2 = {"icao24": "aaa111", "lat": 50.61, "lng": 30.71, "alt": 9100}
_FLIGHT_B_V2 = {"icao24": "bbb222", "lat": 51.10, "lng": 31.20, "alt": 8000}


def test_stamped_writes_feed_tracked_flights_delta_ring(clean_fingerprints):
    _reset_fingerprint("tracked_flights")

    _write_layer("tracked_flights", [_FLIGHT_A_V1])
    _mark_fresh("tracked_flights")
    v1 = get_layer_version("tracked_flights")
    assert v1 == 1

    _write_layer("tracked_flights", [_FLIGHT_A_V2, _FLIGHT_B_V2])
    _mark_fresh("tracked_flights")

    delta = compute_layer_row_delta("tracked_flights", v1)
    assert delta is not None
    upserts = delta["upsert"]
    ids = {str(item.get("icao24")) for item in upserts}
    assert "bbb222" in ids, "new tracked flight missing from delta upserts"
    moved = next(item for item in upserts if item.get("icao24") == "aaa111")
    assert moved["lat"] == _FLIGHT_A_V2["lat"], "moved flight not re-upserted"
    assert delta["version"] == v1 + 1


def test_fast_endpoint_reports_tracked_flights_version_then_delta(client, clean_fingerprints):
    _reset_fingerprint("tracked_flights")

    # Steady-state client: the browser echoes a version for EVERY fast-delta
    # layer once seen (useDataPolling.formatLayerVersions). Seed the other
    # five so the echo below matches production conditions.
    for key in ("ships", "commercial_flights", "military_flights", "private_flights", "private_jets"):
        _reset_fingerprint(key)
        _write_layer(key, [])
        _mark_fresh(key)

    _write_layer("tracked_flights", [_FLIGHT_A_V1])
    _mark_fresh("tracked_flights")

    first = client.get("/api/live-data/fast")
    assert first.status_code == 200
    payload = first.json()
    versions = payload.get("layer_versions") or {}
    assert "tracked_flights" in versions, (
        "stamped write must surface tracked_flights in layer_versions"
    )
    echoed = ",".join(f"{key}:{ver}" for key, ver in versions.items())

    # Production-shaped second write + stamp (what fetch_flights/fetch_military_
    # flights do after U0).
    _write_layer("tracked_flights", [_FLIGHT_A_V2, _FLIGHT_B_V2])
    _mark_fresh("tracked_flights")

    second = client.get(f"/api/live-data/fast?lv={echoed}")
    assert second.status_code == 200
    assert second.headers.get("x-sb-mode") == "delta", (
        "one unstamped fast-delta layer must no longer force full snapshots"
    )
    deltas = second.json().get("deltas") or {}
    assert deltas.get("tracked_flights", {}).get("upsert"), (
        "delta payload must contain the changed tracked flights"
    )


def test_unstamped_tracked_write_forces_full_snapshot_fallback(client, clean_fingerprints):
    """Regression lock: deleting the stamps re-disables delta delivery entirely."""
    _reset_fingerprint("tracked_flights")

    # Simulate the pre-U0 defect: data is written but never stamped, so the
    # client can never echo a tracked_flights version.
    _write_layer("tracked_flights", [_FLIGHT_A_V1])
    other_versions = ["ships:1", "commercial_flights:1", "military_flights:1",
                      "private_flights:1", "private_jets:1"]

    response = client.get(f"/api/live-data/fast?lv={','.join(other_versions)}")
    assert response.status_code == 200
    assert response.headers.get("x-sb-mode") != "delta", (
        "missing tracked_flights version must fall back to full snapshot"
    )
