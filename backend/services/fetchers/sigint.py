"""SIGINT fetcher — pulls latest signals from the SIGINT Grid into latest_data.

Merges live APRS/MQTT/JS8Call signals with cached Meshtastic map API nodes.
Each external bridge is reconciled independently so enabling one transport does
not implicitly start another.
"""

import logging

from services.aprs_is_bridge import aprs_is_bridge
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.meshtastic_mqtt_settings import mqtt_bridge_enabled

logger = logging.getLogger("services.data_fetcher")


def _merge_sigint_snapshot(
    live_signals: list[dict],
    api_nodes: list[dict],
) -> list[dict]:
    """Merge live bridge signals with cached Meshtastic map nodes.

    Live Meshtastic observations always win over map/API nodes for the same callsign
    because they include fresher region/channel metadata.
    """

    # Shallow-copy every entry so the published list owns its own dicts. The
    # inputs alias objects that other threads keep mutating in place: live
    # signals are the SIGINT bridges' own dicts (updated as packets arrive),
    # and api_nodes are the same objects published under latest_data
    # ["meshtastic_map_nodes"]. Publishing those references into
    # latest_data["sigint"] lets a concurrent mutation race the lock-free
    # deepcopy in get_latest_data_deepcopy_snapshot() (/api/health, /api/live-
    # data) and raise "dictionary changed size during iteration". Copying
    # honors the replace-don't-mutate contract in fetchers/_store.py.
    merged = [dict(s) for s in live_signals]
    live_callsigns = {s["callsign"] for s in merged if s.get("source") == "meshtastic"}
    for node in api_nodes:
        if node.get("callsign") in live_callsigns:
            continue
        merged.append(dict(node))
    merged.sort(key=lambda item: str(item.get("timestamp", "") or ""), reverse=True)
    return merged


def _sigint_totals(signals: list[dict]) -> dict[str, int]:
    totals = {
        "total": len(signals),
        "meshtastic": 0,
        "meshtastic_live": 0,
        "meshtastic_map": 0,
        "aprs": 0,
        "js8call": 0,
    }
    for sig in signals:
        source = str(sig.get("source", "") or "").lower()
        if source == "meshtastic":
            totals["meshtastic"] += 1
            if bool(sig.get("from_api")):
                totals["meshtastic_map"] += 1
            else:
                totals["meshtastic_live"] += 1
        elif source == "aprs":
            totals["aprs"] += 1
        elif source == "js8call":
            totals["js8call"] += 1
    return totals


def build_sigint_snapshot() -> tuple[list[dict], dict[str, object], dict[str, int]]:
    """Build the current merged SIGINT snapshot without hitting the network."""

    from services.sigint_bridge import sigint_grid

    # The legacy APRS member in SIGINTGrid is intentionally never started by
    # the production fetch path after #533. Safe APRS-IS receive traffic comes
    # from aprs_is_bridge, which requires explicit bounded configuration.
    live_signals = sigint_grid.get_all_signals()
    live_signals.extend(aprs_is_bridge.get_signals())
    with _data_lock:
        api_nodes = list(latest_data.get("meshtastic_map_nodes", []))
    merged = _merge_sigint_snapshot(live_signals, api_nodes)
    channel_stats = sigint_grid.get_mesh_channel_stats(api_nodes or None)
    totals = _sigint_totals(merged)
    return merged, channel_stats, totals


def refresh_sigint_snapshot() -> tuple[list[dict], dict[str, object], dict[str, int]]:
    """Refresh latest_data SIGINT state from current bridge + cache state."""

    signals, channel_stats, totals = build_sigint_snapshot()
    with _data_lock:
        latest_data["sigint"] = signals
        latest_data["mesh_channel_stats"] = channel_stats
        latest_data["sigint_totals"] = totals
    _mark_fresh("sigint")
    return signals, channel_stats, totals


def _reconcile_sigint_bridges(aprs_requested: bool, mesh_requested: bool) -> None:
    """Start/stop each bridge independently from current operator state."""
    from services.sigint_bridge import sigint_grid

    # Defense-in-depth: the old SIGINTGrid APRS client used an effectively
    # global range subscription. It is no longer part of the production fetch
    # path; force it stopped even if another caller started it accidentally.
    sigint_grid.aprs.stop()

    aprs_is_bridge.reconcile(aprs_requested)

    try:
        mesh_network_enabled = mqtt_bridge_enabled()
    except Exception:
        mesh_network_enabled = False
    if mesh_requested and mesh_network_enabled:
        sigint_grid.mesh.start()
    else:
        sigint_grid.mesh.stop()

    # JS8Call is localhost-only and historically accompanies the SIGINT view.
    # Keep that behavior without coupling it to either public network bridge.
    if aprs_requested or mesh_requested:
        sigint_grid.js8.start()
    else:
        sigint_grid.js8.stop()


def fetch_sigint():
    """Refresh SIGINT while matching bridge lifecycles to operator settings."""
    from services.fetchers._store import effective_layers

    layers = effective_layers()
    aprs_requested = bool(layers.get("sigint_aprs", False))
    mesh_requested = bool(layers.get("sigint_meshtastic", False))
    _reconcile_sigint_bridges(aprs_requested, mesh_requested)

    if not aprs_requested and not mesh_requested:
        return

    signals, channel_stats, totals = refresh_sigint_snapshot()
    from services.sigint_bridge import sigint_grid

    logger.info(
        "SIGINT: %d signals (APRS:%d MESH:%d JS8:%d MAP:%d)",
        len(signals),
        totals["aprs"],
        totals["meshtastic_live"],
        len(sigint_grid.js8.signals),
        totals["meshtastic_map"],
    )
