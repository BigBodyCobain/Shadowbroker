"""AI Intel pin storage — layered pin system with JSON file persistence.

Supports:
  - Named pin layers (created by user or AI)
  - Pins with optional entity attachment (track moving objects)
  - Pin source tracking (user vs openclaw)
  - Layer visibility toggles
  - External feed URL per layer (for Phase 5)
  - GeoJSON export per layer or all layers
"""

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pin schema
# ---------------------------------------------------------------------------

PIN_CATEGORIES = {
    "threat", "news", "geolocation", "custom", "anomaly",
    "military", "maritime", "flight", "infrastructure", "weather",
    "sigint", "prediction", "research",
}

PIN_COLORS = {
    "threat": "#ef4444",       # red
    "news": "#f59e0b",         # amber
    "geolocation": "#8b5cf6",  # violet
    "custom": "#3b82f6",       # blue
    "anomaly": "#f97316",      # orange
    "military": "#dc2626",     # dark red
    "maritime": "#0ea5e9",     # sky
    "flight": "#6366f1",       # indigo
    "infrastructure": "#64748b",  # slate
    "weather": "#22d3ee",      # cyan
    "sigint": "#a855f7",       # purple
    "prediction": "#eab308",   # yellow
    "research": "#10b981",     # emerald
}

LAYER_COLORS = [
    "#3b82f6", "#ef4444", "#22d3ee", "#f59e0b", "#8b5cf6",
    "#10b981", "#f97316", "#6366f1", "#ec4899", "#14b8a6",
]

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_layers: list[dict[str, Any]] = []
_pins: list[dict[str, Any]] = []
_lock = threading.Lock()

# Persistence file path
_PERSIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_PERSIST_FILE = os.path.join(_PERSIST_DIR, "pin_layers.json")
_OLD_PERSIST_FILE = os.path.join(_PERSIST_DIR, "ai_pins.json")


def _ensure_persist_dir():
    try:
        os.makedirs(_PERSIST_DIR, exist_ok=True)
    except OSError:
        pass


def _save_to_disk():
    """Persist layers and pins to JSON file. Called under lock."""
    try:
        _ensure_persist_dir()
        with open(_PERSIST_FILE, "w", encoding="utf-8") as f:
            json.dump({"layers": _layers, "pins": _pins}, f, indent=2, default=str)
    except (OSError, IOError) as e:
        logger.warning(f"Failed to persist pin layers: {e}")


def _load_from_disk():
    """Load layers and pins from disk on startup."""
    global _layers, _pins
    try:
        if os.path.exists(_PERSIST_FILE):
            with open(_PERSIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _layers = data.get("layers", [])
                _pins = data.get("pins", [])
                logger.info(f"Loaded {len(_layers)} layers, {len(_pins)} pins from disk")
                return

        # Migrate from old flat pin file
        if os.path.exists(_OLD_PERSIST_FILE):
            with open(_OLD_PERSIST_FILE, "r", encoding="utf-8") as f:
                old_pins = json.load(f)
            if isinstance(old_pins, list) and old_pins:
                legacy_layer = _make_layer("Legacy", "Migrated pins", source="system")
                _layers.append(legacy_layer)
                for p in old_pins:
                    if isinstance(p, dict):
                        p["layer_id"] = legacy_layer["id"]
                        _pins.append(p)
                logger.info(f"Migrated {len(_pins)} pins from ai_pins.json into Legacy layer")
                _save_to_disk()
    except (OSError, IOError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to load pin layers from disk: {e}")


def _make_layer(
    name: str,
    description: str = "",
    source: str = "user",
    color: str = "",
    feed_url: str = "",
    feed_interval: int = 300,
) -> dict[str, Any]:
    """Create a layer dict."""
    layer_id = str(uuid.uuid4())[:12]
    now = time.time()
    return {
        "id": layer_id,
        "name": name[:100],
        "description": description[:500],
        "source": source[:50],
        "visible": True,
        "color": color or LAYER_COLORS[len(_layers) % len(LAYER_COLORS)],
        "created_at": now,
        "created_at_iso": datetime.utcfromtimestamp(now).isoformat() + "Z",
        "feed_url": feed_url[:1000] if feed_url else "",
        "feed_interval": max(60, min(86400, feed_interval)),
        "pin_count": 0,
    }


# Load on import
_load_from_disk()

# One-time cleanup: remove correlation_engine auto-pins (no longer generated)
_corr_before = len(_pins)
_pins[:] = [p for p in _pins if p.get("source") != "correlation_engine"]
if len(_pins) < _corr_before:
    logger.info("Cleaned up %d legacy correlation_engine pins", _corr_before - len(_pins))
    _save_to_disk()


# ---------------------------------------------------------------------------
# Layer CRUD
# ---------------------------------------------------------------------------

def create_layer(
    name: str,
    description: str = "",
    source: str = "user",
    color: str = "",
    feed_url: str = "",
    feed_interval: int = 300,
) -> dict[str, Any]:
    """Create a new pin layer."""
    with _lock:
        layer = _make_layer(name, description, source, color, feed_url, feed_interval)
        _layers.append(layer)
        _save_to_disk()
    return layer


def get_layers() -> list[dict[str, Any]]:
    """Return all layers with current pin counts."""
    now = time.time()
    with _lock:
        result = []
        for layer in _layers:
            count = sum(
                1 for p in _pins
                if p.get("layer_id") == layer["id"]
                and not (p.get("expires_at") and p["expires_at"] < now)
            )
            result.append({**layer, "pin_count": count})
        return result


def update_layer(layer_id: str, **updates) -> Optional[dict[str, Any]]:
    """Update layer fields. Returns updated layer or None if not found."""
    allowed = {"name", "description", "visible", "color", "feed_url", "feed_interval", "feed_last_fetched"}
    with _lock:
        for layer in _layers:
            if layer["id"] == layer_id:
                for k, v in updates.items():
                    if k in allowed and v is not None:
                        if k == "name":
                            layer[k] = str(v)[:100]
                        elif k == "description":
                            layer[k] = str(v)[:500]
                        elif k == "visible":
                            layer[k] = bool(v)
                        elif k == "color":
                            layer[k] = str(v)[:20]
                        elif k == "feed_url":
                            layer[k] = str(v)[:1000]
                        elif k == "feed_interval":
                            layer[k] = max(60, min(86400, int(v)))
                        elif k == "feed_last_fetched":
                            layer[k] = float(v)
                _save_to_disk()
                return dict(layer)
    return None


def delete_layer(layer_id: str) -> int:
    """Delete a layer and all its pins. Returns count of pins removed."""
    with _lock:
        before_layers = len(_layers)
        _layers[:] = [l for l in _layers if l["id"] != layer_id]
        if len(_layers) == before_layers:
            return 0  # not found
        before_pins = len(_pins)
        _pins[:] = [p for p in _pins if p.get("layer_id") != layer_id]
        removed = before_pins - len(_pins)
        _save_to_disk()
        return removed


# ---------------------------------------------------------------------------
# Pin CRUD
# ---------------------------------------------------------------------------

def create_pin(
    lat: float,
    lng: float,
    label: str,
    category: str = "custom",
    *,
    layer_id: str = "",
    color: str = "",
    description: str = "",
    source: str = "openclaw",
    source_url: str = "",
    confidence: float = 1.0,
    ttl_hours: float = 0,
    metadata: Optional[dict] = None,
    entity_attachment: Optional[dict] = None,
) -> dict[str, Any]:
    """Create a single pin and return it."""
    pin_id = str(uuid.uuid4())[:12]
    now = time.time()

    cat = category if category in PIN_CATEGORIES else "custom"
    pin_color = color or PIN_COLORS.get(cat, "#3b82f6")

    # Validate entity_attachment if provided
    attachment = None
    if entity_attachment and isinstance(entity_attachment, dict):
        etype = str(entity_attachment.get("entity_type", "")).strip()
        eid = str(entity_attachment.get("entity_id", "")).strip()
        if etype and eid:
            attachment = {
                "entity_type": etype[:50],
                "entity_id": eid[:100],
                "entity_label": str(entity_attachment.get("entity_label", ""))[:200],
            }

    pin = {
        "id": pin_id,
        "layer_id": layer_id or "",
        "lat": lat,
        "lng": lng,
        "label": label[:200],
        "category": cat,
        "color": pin_color,
        "description": description[:2000],
        "source": source[:100],
        "source_url": source_url[:500],
        "confidence": max(0.0, min(1.0, confidence)),
        "created_at": now,
        "created_at_iso": datetime.utcfromtimestamp(now).isoformat() + "Z",
        "expires_at": now + (ttl_hours * 3600) if ttl_hours > 0 else None,
        "metadata": metadata or {},
        "entity_attachment": attachment,
        "comments": [],
    }

    with _lock:
        _pins.append(pin)
        _save_to_disk()

    return pin


def create_pins_batch(items: list[dict], default_layer_id: str = "") -> list[dict[str, Any]]:
    """Create multiple pins at once."""
    created = []
    now = time.time()

    with _lock:
        for item in items[:200]:  # max 200 per batch
            pin_id = str(uuid.uuid4())[:12]
            cat = item.get("category", "custom")
            if cat not in PIN_CATEGORIES:
                cat = "custom"
            pin_color = item.get("color", "") or PIN_COLORS.get(cat, "#3b82f6")
            ttl = float(item.get("ttl_hours", 0) or 0)

            attachment = None
            ea = item.get("entity_attachment")
            if ea and isinstance(ea, dict):
                etype = str(ea.get("entity_type", "")).strip()
                eid = str(ea.get("entity_id", "")).strip()
                if etype and eid:
                    attachment = {
                        "entity_type": etype[:50],
                        "entity_id": eid[:100],
                        "entity_label": str(ea.get("entity_label", ""))[:200],
                    }

            pin = {
                "id": pin_id,
                "layer_id": item.get("layer_id", default_layer_id) or "",
                "lat": float(item.get("lat", 0)),
                "lng": float(item.get("lng", 0)),
                "label": str(item.get("label", ""))[:200],
                "category": cat,
                "color": pin_color,
                "description": str(item.get("description", ""))[:2000],
                "source": str(item.get("source", "openclaw"))[:100],
                "source_url": str(item.get("source_url", ""))[:500],
                "confidence": max(0.0, min(1.0, float(item.get("confidence", 1.0)))),
                "created_at": now,
                "created_at_iso": datetime.utcfromtimestamp(now).isoformat() + "Z",
                "expires_at": now + (ttl * 3600) if ttl > 0 else None,
                "metadata": item.get("metadata", {}),
                "entity_attachment": attachment,
                "comments": [],
            }
            _pins.append(pin)
            created.append(pin)

        _save_to_disk()
    return created


def get_pins(
    category: str = "",
    source: str = "",
    layer_id: str = "",
    limit: int = 500,
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    """Get pins with optional filters."""
    now = time.time()
    with _lock:
        results = []
        for pin in _pins:
            if not include_expired and pin.get("expires_at") and pin["expires_at"] < now:
                continue
            if category and pin.get("category") != category:
                continue
            if source and pin.get("source") != source:
                continue
            if layer_id and pin.get("layer_id") != layer_id:
                continue
            results.append(pin)
            if len(results) >= limit:
                break
        return results


def get_pin(pin_id: str) -> Optional[dict[str, Any]]:
    """Return a single pin by ID (including comments), or None."""
    with _lock:
        for pin in _pins:
            if pin.get("id") == pin_id:
                # Ensure comments key exists for legacy pins
                if "comments" not in pin:
                    pin["comments"] = []
                return dict(pin)
    return None


def update_pin(pin_id: str, **updates) -> Optional[dict[str, Any]]:
    """Update a pin's editable fields (label, description, category, color)."""
    allowed = {"label", "description", "category", "color"}
    with _lock:
        for pin in _pins:
            if pin.get("id") != pin_id:
                continue
            for k, v in updates.items():
                if k not in allowed or v is None:
                    continue
                if k == "label":
                    pin[k] = str(v)[:200]
                elif k == "description":
                    pin[k] = str(v)[:2000]
                elif k == "category":
                    cat = str(v)
                    if cat in PIN_CATEGORIES:
                        pin[k] = cat
                        # Refresh color if it was the category default
                        if not updates.get("color"):
                            pin["color"] = PIN_COLORS.get(cat, pin.get("color", "#3b82f6"))
                elif k == "color":
                    pin[k] = str(v)[:20]
            pin["updated_at"] = time.time()
            _save_to_disk()
            return dict(pin)
    return None


def add_pin_comment(
    pin_id: str,
    text: str,
    author: str = "user",
    author_label: str = "",
    reply_to: str = "",
) -> Optional[dict[str, Any]]:
    """Append a comment to a pin. Returns the updated pin (with all comments)."""
    text = (text or "").strip()
    if not text:
        return None
    with _lock:
        for pin in _pins:
            if pin.get("id") != pin_id:
                continue
            if "comments" not in pin or not isinstance(pin["comments"], list):
                pin["comments"] = []
            comment = {
                "id": str(uuid.uuid4())[:12],
                "text": text[:4000],
                "author": (author or "user")[:50],
                "author_label": (author_label or "")[:100],
                "reply_to": (reply_to or "")[:12],
                "created_at": time.time(),
                "created_at_iso": datetime.utcnow().isoformat() + "Z",
            }
            pin["comments"].append(comment)
            _save_to_disk()
            return dict(pin)
    return None


def delete_pin_comment(pin_id: str, comment_id: str) -> bool:
    """Remove a single comment from a pin."""
    with _lock:
        for pin in _pins:
            if pin.get("id") != pin_id:
                continue
            comments = pin.get("comments") or []
            before = len(comments)
            pin["comments"] = [c for c in comments if c.get("id") != comment_id]
            if len(pin["comments"]) < before:
                _save_to_disk()
                return True
            return False
    return False


def delete_pin(pin_id: str) -> bool:
    """Delete a single pin by ID."""
    with _lock:
        before = len(_pins)
        _pins[:] = [p for p in _pins if p.get("id") != pin_id]
        if len(_pins) < before:
            _save_to_disk()
            return True
        return False


def clear_pins(category: str = "", source: str = "", layer_id: str = "") -> int:
    """Clear pins, optionally filtered. Returns count removed."""
    with _lock:
        before = len(_pins)

        def keep(p):
            if layer_id and p.get("layer_id") != layer_id:
                return True  # different layer, keep
            if category and source:
                return not (p.get("category") == category and p.get("source") == source)
            if category:
                return p.get("category") != category
            if source:
                return p.get("source") != source
            if layer_id:
                return p.get("layer_id") != layer_id
            return False

        if not category and not source and not layer_id:
            _pins.clear()
        else:
            _pins[:] = [p for p in _pins if keep(p)]

        removed = before - len(_pins)
        if removed:
            _save_to_disk()
        return removed


def get_feed_layers() -> list[dict[str, Any]]:
    """Return layers that have a non-empty feed_url."""
    with _lock:
        return [dict(l) for l in _layers if l.get("feed_url")]


def replace_layer_pins(layer_id: str, new_pins: list[dict[str, Any]]) -> int:
    """Atomically replace all pins in a layer with new_pins. Returns count added."""
    now = time.time()
    with _lock:
        # Remove old pins for this layer
        _pins[:] = [p for p in _pins if p.get("layer_id") != layer_id]
        # Add new pins
        added = 0
        for item in new_pins[:500]:  # cap at 500 per feed
            pin_id = str(uuid.uuid4())[:12]
            cat = item.get("category", "custom")
            if cat not in PIN_CATEGORIES:
                cat = "custom"
            pin_color = item.get("color", "") or PIN_COLORS.get(cat, "#3b82f6")

            attachment = None
            ea = item.get("entity_attachment")
            if ea and isinstance(ea, dict):
                etype = str(ea.get("entity_type", "")).strip()
                eid = str(ea.get("entity_id", "")).strip()
                if etype and eid:
                    attachment = {
                        "entity_type": etype[:50],
                        "entity_id": eid[:100],
                        "entity_label": str(ea.get("entity_label", ""))[:200],
                    }

            pin = {
                "id": pin_id,
                "layer_id": layer_id,
                "lat": float(item.get("lat", 0)),
                "lng": float(item.get("lng", 0)),
                "label": str(item.get("label", item.get("name", "")))[:200],
                "category": cat,
                "color": pin_color,
                "description": str(item.get("description", ""))[:2000],
                "source": str(item.get("source", "feed"))[:100],
                "source_url": str(item.get("source_url", ""))[:500],
                "confidence": max(0.0, min(1.0, float(item.get("confidence", 1.0)))),
                "created_at": now,
                "created_at_iso": datetime.utcfromtimestamp(now).isoformat() + "Z",
                "expires_at": None,
                "metadata": item.get("metadata", {}),
                "entity_attachment": attachment,
                "comments": [],
            }
            _pins.append(pin)
            added += 1
        _save_to_disk()
    return added


def purge_expired() -> int:
    """Remove expired pins. Called periodically."""
    now = time.time()
    with _lock:
        before = len(_pins)
        _pins[:] = [p for p in _pins if not (p.get("expires_at") and p["expires_at"] < now)]
        removed = before - len(_pins)
        if removed:
            _save_to_disk()
        return removed


def pin_count() -> dict[str, int]:
    """Return counts by category."""
    now = time.time()
    counts: dict[str, int] = {}
    with _lock:
        for pin in _pins:
            if pin.get("expires_at") and pin["expires_at"] < now:
                continue
            cat = pin.get("category", "custom")
            counts[cat] = counts.get(cat, 0) + 1
    return counts


def pins_as_geojson(layer_id: str = "") -> dict[str, Any]:
    """Convert active pins to GeoJSON FeatureCollection for the map layer."""
    now = time.time()
    features = []
    with _lock:
        # Build set of visible layer IDs
        visible_layers = {l["id"] for l in _layers if l.get("visible", True)}

        for pin in _pins:
            if pin.get("expires_at") and pin["expires_at"] < now:
                continue
            # Layer filter
            pid_layer = pin.get("layer_id", "")
            if layer_id and pid_layer != layer_id:
                continue
            # Skip pins in hidden layers
            if pid_layer and pid_layer not in visible_layers:
                continue

            props = {
                "id": pin["id"],
                "layer_id": pid_layer,
                "label": pin["label"],
                "category": pin["category"],
                "color": pin["color"],
                "description": pin.get("description", ""),
                "source": pin["source"],
                "source_url": pin.get("source_url", ""),
                "confidence": pin.get("confidence", 1.0),
                "created_at": pin.get("created_at_iso", ""),
                "comment_count": len(pin.get("comments") or []),
            }

            # Entity attachment info (frontend resolves position)
            ea = pin.get("entity_attachment")
            if ea:
                props["entity_attachment"] = ea

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [pin["lng"], pin["lat"]],
                },
                "properties": props,
            })
    return {
        "type": "FeatureCollection",
        "features": features,
    }
