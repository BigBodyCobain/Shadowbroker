"""Prekey and pubkey lookups don't block the event loop while they wait on the network."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest


def _request(path: str):
    import main

    return main.Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


def _slow_lookup(*_args, **_kwargs):
    # Stands in for a fleet lookup waiting on a slow or unreachable peer.
    time.sleep(1.0)
    return {"ok": False, "detail": "Prekey bundle not found"}


async def _longest_stall(endpoint) -> float:
    """Runs the endpoint while a 50 ms ticker runs; returns the longest gap between ticks."""
    gaps: list[float] = []
    done = asyncio.Event()

    async def ticker():
        last = time.monotonic()
        while not done.is_set():
            await asyncio.sleep(0.05)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    try:
        await endpoint()
    finally:
        done.set()
        await task
    return max(gaps)


@pytest.mark.asyncio
async def test_prekey_bundle_lookup_does_not_block_the_event_loop():
    import main

    request = _request("/api/mesh/dm/prekey-bundle")
    with patch("main.fetch_dm_prekey_bundle", side_effect=_slow_lookup):
        stall = await _longest_stall(
            lambda: main.dm_get_prekey_bundle(request, lookup_token="unknown-handle-token")
        )
    # A 1 s lookup on the loop stalls it about 1 s; off the loop, a 50 ms tick stays well under 0.5 s.
    assert stall < 0.5, f"the event loop stalled for {stall:.2f}s during the lookup"


@pytest.mark.asyncio
async def test_pubkey_fleet_lookup_does_not_block_the_event_loop():
    import main

    request = _request("/api/mesh/dm/pubkey")
    with patch("services.mesh.mesh_dm_relay.dm_relay") as relay, patch(
        "services.mesh.mesh_wormhole_prekey.fetch_dm_prekey_bundle",
        side_effect=_slow_lookup,
    ):
        relay.get_dh_key_by_lookup.return_value = (None, "")
        stall = await _longest_stall(
            lambda: main.dm_get_pubkey(request, lookup_token="unknown-handle-token")
        )
    # A 1 s lookup on the loop stalls it about 1 s; off the loop, a 50 ms tick stays well under 0.5 s.
    assert stall < 0.5, f"the event loop stalled for {stall:.2f}s during the lookup"
