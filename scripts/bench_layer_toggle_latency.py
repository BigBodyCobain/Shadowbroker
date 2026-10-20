#!/usr/bin/env python3
"""Measure layer-toggle → data-visible latency (UX guardrail for perf work).

Simulates what the dashboard does on toggle:
  1. POST /api/layers (layer off → on)
  2. Poll GET /api/live-data/slow until the layer's payload is non-empty

Also reports whether data was already warm in the backend store before toggle
(via /api/health source counts while the layer is still filtered off in the API).

Usage:
  python scripts/bench_layer_toggle_latency.py
  python scripts/bench_layer_toggle_latency.py --base http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

# layer_key → JSON field in /api/live-data/slow + how to count "visible"
LAYER_PROBE: dict[str, tuple[str, Callable[[Any], int]]] = {
    "cctv": ("cctv", lambda _v: 0),  # fast tier — see FAST_LAYER_PROBE
    "firms": ("firms_fires", lambda v: len(v) if isinstance(v, list) else 0),
    "datacenters": ("datacenters", lambda v: len(v) if isinstance(v, list) else 0),
    "power_plants": ("power_plants", lambda v: len(v) if isinstance(v, list) else 0),
    "psk_reporter": ("psk_reporter", lambda v: len(v) if isinstance(v, list) else 0),
}

FAST_LAYER_PROBE = {
    "cctv": ("cctv", lambda v: len(v) if isinstance(v, list) else 0),
}

HEALTH_SOURCE_KEY = {
    "cctv": "cctv",
    "firms": "firms_fires",
    "datacenters": "datacenters",
    "power_plants": "power_plants",
    "psk_reporter": "psk_reporter",
}


@dataclass
class ToggleResult:
    layer: str
    warm_store_count: int | None
    time_to_visible_ms: float | None
    visible_count: int
    timed_out: bool
    on_enable_fetch: bool
    notes: str


def _request(method: str, url: str, body: dict | None = None, timeout: float = 30.0) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return resp.status, json.loads(raw) if raw else None


def get_health(base: str) -> dict:
    _, payload = _request("GET", f"{base}/api/health")
    return payload or {}


def get_slow(base: str) -> dict:
    _, payload = _request("GET", f"{base}/api/live-data/slow")
    return payload or {}


def get_fast(base: str) -> dict:
    _, payload = _request("GET", f"{base}/api/live-data/fast")
    return payload or {}


def set_layer(base: str, layers: dict[str, bool]) -> None:
    _request("POST", f"{base}/api/layers", {"layers": layers})


def count_visible(payload: dict, field: str, counter: Callable[[Any], int]) -> int:
    return counter(payload.get(field))


ON_ENABLE_IMMEDIATE = {"datacenters", "fishing_activity"}


def measure_layer(base: str, layer: str, timeout_s: float = 120.0) -> ToggleResult:
    health = get_health(base)
    warm = None
    hk = HEALTH_SOURCE_KEY.get(layer)
    if hk and isinstance(health.get("sources"), dict):
        warm = health["sources"].get(hk)

    # Ensure layer is off (frontend default for these probes)
    set_layer(base, {layer: False})
    time.sleep(0.25)

    # Confirm API filters it off while toggled off
    if layer in FAST_LAYER_PROBE:
        field, counter = FAST_LAYER_PROBE[layer]
        off_payload = get_fast(base)
    else:
        field, counter = LAYER_PROBE[layer]
        off_payload = get_slow(base)
    off_count = count_visible(off_payload, field, counter)

    # Toggle on — mirrors dashboard POST + immediate slow/fast refetch
    t0 = time.perf_counter()
    set_layer(base, {layer: True})

    visible_count = 0
    timed_out = True
    while (time.perf_counter() - t0) < timeout_s:
        if layer in FAST_LAYER_PROBE:
            payload = get_fast(base)
        else:
            payload = get_slow(base)
        visible_count = count_visible(payload, field, counter)
        if visible_count > 0:
            timed_out = False
            break
        time.sleep(0.25)

    elapsed_ms = None if timed_out else (time.perf_counter() - t0) * 1000.0

    notes_parts = []
    if off_count > 0:
        notes_parts.append(f"unexpected visible while off ({off_count})")
    if warm and warm > 0 and (timed_out or (elapsed_ms or 0) < 500):
        notes_parts.append("warm store — toggle likely instant from prefetch")
    elif warm == 0 and timed_out:
        notes_parts.append("cold store — would feel broken to user")
    elif timed_out:
        notes_parts.append(f"no warm store signal; waited {timeout_s:.0f}s")

    return ToggleResult(
        layer=layer,
        warm_store_count=warm,
        time_to_visible_ms=elapsed_ms,
        visible_count=visible_count,
        timed_out=timed_out,
        on_enable_fetch=layer in ON_ENABLE_IMMEDIATE,
        notes="; ".join(notes_parts) or "ok",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--layers", nargs="*", default=list(LAYER_PROBE.keys()))
    args = parser.parse_args()

    print(f"Backend: {args.base}")
    try:
        health = get_health(args.base)
    except urllib.error.URLError as exc:
        print(f"Health check failed: {exc}", file=sys.stderr)
        return 1

    print(f"Version: {health.get('version')}  uptime: {health.get('uptime_seconds')}s")
    print(f"Runtime profile: {(health.get('runtime') or {}).get('profile')}")
    print()
    print(f"{'layer':<14} {'warm_store':>10} {'visible_ms':>11} {'count':>8} {'on_enable':>10}  notes")
    print("-" * 90)

    results: list[ToggleResult] = []
    for layer in args.layers:
        try:
            r = measure_layer(args.base, layer, timeout_s=args.timeout)
        except urllib.error.URLError as exc:
            print(f"{layer:<14} ERROR: {exc}")
            continue
        results.append(r)
        ms = f"{r.time_to_visible_ms:.0f}" if r.time_to_visible_ms is not None else f">{args.timeout:.0f}s"
        warm = str(r.warm_store_count) if r.warm_store_count is not None else "?"
        on_en = "yes" if r.on_enable_fetch else "no"
        print(f"{layer:<14} {warm:>10} {ms:>11} {r.visible_count:>8} {on_en:>10}  {r.notes}")

    print()
    instant = [r for r in results if r.time_to_visible_ms is not None and r.time_to_visible_ms < 500]
    slow = [r for r in results if r.timed_out or (r.time_to_visible_ms or 0) >= 5000]
    print(f"Summary: {len(instant)}/{len(results)} toggles visible in <500ms; {len(slow)} slow or timed out")
    if slow:
        print("Layers that need on-enable fetch or prefetch to avoid UX pain:")
        for r in slow:
            print(f"  - {r.layer}: {r.notes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
