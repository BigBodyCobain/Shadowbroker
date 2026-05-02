"""ai_intel_store — compatibility wrapper around ai_pin_store + layer injection.

openclaw_channel.py and routers/ai_intel.py import from this module name.
All pin/layer logic lives in ai_pin_store.py; this module re-exports with the
expected function signatures and adds the layer injection helper.
"""

import logging
import time
from typing import Any

from services.ai_pin_store import (
    create_pin,
    create_pins_batch,
    get_pins,
    delete_pin,
    clear_pins,
    pin_count,
    pins_as_geojson,
    purge_expired,
    # Layer CRUD
    create_layer,
    get_layers,
    update_layer,
    delete_layer,
    # Feed layers
    get_feed_layers,
    replace_layer_pins,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-exports expected by openclaw_channel._dispatch_command
# ---------------------------------------------------------------------------


def get_all_intel_pins() -> list[dict[str, Any]]:
    """Return all active pins (no filter, generous limit)."""
    return get_pins(limit=2000)


def add_intel_pin(args: dict[str, Any]) -> dict[str, Any]:
    """Create a single pin from a command-channel args dict."""
    ea = args.get("entity_attachment")
    return create_pin(
        lat=float(args.get("lat", 0)),
        lng=float(args.get("lng", 0)),
        label=str(args.get("label", ""))[:200],
        category=str(args.get("category", "custom")),
        layer_id=str(args.get("layer_id", "")),
        color=str(args.get("color", "")),
        description=str(args.get("description", "")),
        source=str(args.get("source", "openclaw")),
        source_url=str(args.get("source_url", "")),
        confidence=float(args.get("confidence", 1.0)),
        ttl_hours=float(args.get("ttl_hours", 0)),
        metadata=args.get("metadata") or {},
        entity_attachment=ea if isinstance(ea, dict) else None,
    )


def delete_intel_pin(pin_id: str) -> bool:
    """Delete a pin by ID."""
    return delete_pin(pin_id)


# Layer helpers for OpenClaw
def create_intel_layer(args: dict[str, Any]) -> dict[str, Any]:
    """Create a layer from a command-channel args dict."""
    return create_layer(
        name=str(args.get("name", "Untitled"))[:100],
        description=str(args.get("description", ""))[:500],
        source=str(args.get("source", "openclaw"))[:50],
        color=str(args.get("color", "")),
        feed_url=str(args.get("feed_url", "")),
        feed_interval=int(args.get("feed_interval", 300)),
    )


def get_intel_layers() -> list[dict[str, Any]]:
    """Return all layers with pin counts."""
    return get_layers()


def update_intel_layer(layer_id: str, args: dict[str, Any]) -> dict[str, Any] | None:
    """Update a layer from a command-channel args dict."""
    return update_layer(layer_id, **{
        k: v for k, v in args.items()
        if k in ("name", "description", "visible", "color", "feed_url", "feed_interval")
    })


def delete_intel_layer(layer_id: str) -> int:
    """Delete a layer and its pins. Returns pin count removed."""
    return delete_layer(layer_id)


# ---------------------------------------------------------------------------
# Layer injection — inserts agent data into native telemetry layers
# ---------------------------------------------------------------------------

# Layers that agents are allowed to inject into.
_INJECTABLE_LAYERS = frozenset({
    "cctv", "ships", "sigint", "kiwisdr", "military_bases",
    "datacenters", "power_plants", "satnogs_stations",
    "volcanoes", "earthquakes", "news", "viirs_change_nodes",
    "air_quality",
})


def inject_layer_data(
    layer: str,
    items: list[dict[str, Any]],
    mode: str = "append",
) -> dict[str, Any]:
    """Inject agent data into a native telemetry layer."""
    from services.fetchers._store import latest_data, _data_lock, bump_data_version

    layer = str(layer or "").strip()
    if layer not in _INJECTABLE_LAYERS:
        return {"ok": False, "detail": f"layer '{layer}' not injectable"}

    items = list(items or [])[:200]
    if not items:
        return {"ok": False, "detail": "no items provided"}

    now = time.time()
    tagged = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        entry["_injected"] = True
        entry["_source"] = "user:openclaw"
        entry["_injected_at"] = now
        tagged.append(entry)

    with _data_lock:
        existing = latest_data.get(layer)
        if not isinstance(existing, list):
            existing = []

        if mode == "replace":
            existing = [e for e in existing if not e.get("_injected")]

        existing.extend(tagged)
        latest_data[layer] = existing

    bump_data_version()

    return {
        "ok": True,
        "layer": layer,
        "injected": len(tagged),
        "mode": mode,
    }


def clear_injected_data(layer: str = "") -> dict[str, Any]:
    """Remove all injected items from a layer (or all layers)."""
    from services.fetchers._store import latest_data, _data_lock, bump_data_version

    removed = 0
    with _data_lock:
        targets = [layer] if layer else list(_INJECTABLE_LAYERS)
        for lyr in targets:
            existing = latest_data.get(lyr)
            if not isinstance(existing, list):
                continue
            before = len(existing)
            latest_data[lyr] = [e for e in existing if not e.get("_injected")]
            removed += before - len(latest_data[lyr])

    if removed:
        bump_data_version()

    return {"ok": True, "removed": removed}
