"""SIGINT fetcher — pulls latest signals from the SIGINT Grid into latest_data.

Merges live MQTT signals with cached Meshtastic map API nodes.
Live MQTT signals always take priority (fresher) — API nodes fill in the gaps
for the thousands of nodes our MQTT listener hasn't heard yet.
"""

import logging
from services.fetchers._store import latest_data, _data_lock, _mark_fresh

logger = logging.getLogger("services.data_fetcher")


def _merge_sigint_snapshot(
    live_signals: list[dict],
    api_nodes: list[dict],
) -> list[dict]:
    """Merge live bridge signals with cached Meshtastic map nodes.

    Live Meshtastic observations always win over map/API nodes for the same callsign
    because they include fresher region/channel metadata.
    """

    merged = list(live_signals)
    live_callsigns = {s["callsign"] for s in merged if s.get("source") == "meshtastic"}
    for node in api_nodes:
        if node.get("callsign") in live_callsigns:
            continue
        merged.append(node)
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

    live_signals = sigint_grid.get_all_signals()
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


def fetch_sigint():
    """Fetch all signals from the SIGINT Grid, merge with Meshtastic map nodes."""
    from services.fetchers._store import is_any_active

    if not is_any_active("sigint_meshtastic", "sigint_aprs"):
        return
    from services.sigint_bridge import sigint_grid

    # Start bridges on first call (idempotent)
    sigint_grid.start()

    signals, channel_stats, totals = refresh_sigint_snapshot()

    status = sigint_grid.status
    logger.info(
        f"SIGINT: {len(signals)} signals "
        f"(APRS:{status['aprs']} MESH:{status['meshtastic']} "
        f"JS8:{status['js8call']} MAP:{totals['meshtastic_map']})"
    )
