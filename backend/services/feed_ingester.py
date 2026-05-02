"""Feed Ingester — background daemon that refreshes feed-backed pin layers.

Layers with a non-empty `feed_url` are polled at their `feed_interval`
(seconds, minimum 60). The feed is expected to return either:

  1. GeoJSON FeatureCollection — features are converted to pins
  2. JSON array of pin objects — used directly

Each refresh atomically replaces the layer's pins with the new data.
"""

import logging
import threading
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_running = False
_thread: threading.Thread | None = None
_CHECK_INTERVAL = 30  # seconds between scanning for layers that need refresh
_last_fetched: dict[str, float] = {}  # layer_id → last fetch timestamp
_FETCH_TIMEOUT = 20  # seconds

# ---------------------------------------------------------------------------
# GeoJSON → pin conversion
# ---------------------------------------------------------------------------


def _geojson_features_to_pins(features: list[dict]) -> list[dict[str, Any]]:
    """Convert GeoJSON Feature objects to pin dicts."""
    pins: list[dict[str, Any]] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}

        # Extract coordinates
        coords = geom.get("coordinates")
        if geom.get("type") != "Point" or not coords or len(coords) < 2:
            continue

        lng, lat = float(coords[0]), float(coords[1])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue

        pin: dict[str, Any] = {
            "lat": lat,
            "lng": lng,
            "label": str(props.get("label", props.get("name", props.get("title", ""))))[:200],
            "category": str(props.get("category", "custom"))[:50],
            "color": str(props.get("color", ""))[:20],
            "description": str(props.get("description", props.get("summary", "")))[:2000],
            "source": "feed",
            "source_url": str(props.get("source_url", props.get("url", props.get("link", ""))))[:500],
            "confidence": float(props.get("confidence", 1.0)),
        }

        # Entity attachment if present
        entity_type = props.get("entity_type", "")
        entity_id = props.get("entity_id", "")
        if entity_type and entity_id:
            pin["entity_attachment"] = {
                "entity_type": str(entity_type),
                "entity_id": str(entity_id),
                "entity_label": str(props.get("entity_label", "")),
            }

        pins.append(pin)
    return pins


def _parse_feed_response(data: Any) -> list[dict[str, Any]]:
    """Parse a feed response into a list of pin dicts."""
    if isinstance(data, dict):
        # GeoJSON FeatureCollection
        if data.get("type") == "FeatureCollection" and isinstance(data.get("features"), list):
            return _geojson_features_to_pins(data["features"])
        # Single Feature
        if data.get("type") == "Feature":
            return _geojson_features_to_pins([data])
        # Wrapped response like {"ok": true, "data": [...]}
        inner = data.get("data") or data.get("results") or data.get("pins") or data.get("items")
        if isinstance(inner, list):
            return _normalize_pin_list(inner)

    if isinstance(data, list):
        # Check if first item looks like a GeoJSON Feature
        if data and isinstance(data[0], dict) and data[0].get("type") == "Feature":
            return _geojson_features_to_pins(data)
        return _normalize_pin_list(data)

    return []


def _normalize_pin_list(items: list) -> list[dict[str, Any]]:
    """Normalize a list of raw pin objects, ensuring lat/lng are present."""
    pins: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        lat = item.get("lat") or item.get("latitude")
        lng = item.get("lng") or item.get("lon") or item.get("longitude")
        if lat is None or lng is None:
            continue
        try:
            lat, lng = float(lat), float(lng)
        except (ValueError, TypeError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue

        pin: dict[str, Any] = {
            "lat": lat,
            "lng": lng,
            "label": str(item.get("label", item.get("name", item.get("title", ""))))[:200],
            "category": str(item.get("category", "custom"))[:50],
            "color": str(item.get("color", ""))[:20],
            "description": str(item.get("description", item.get("summary", "")))[:2000],
            "source": "feed",
            "source_url": str(item.get("source_url", item.get("url", item.get("link", ""))))[:500],
            "confidence": float(item.get("confidence", 1.0)),
        }

        entity_type = item.get("entity_type", "")
        entity_id = item.get("entity_id", "")
        if entity_type and entity_id:
            pin["entity_attachment"] = {
                "entity_type": str(entity_type),
                "entity_id": str(entity_id),
                "entity_label": str(item.get("entity_label", "")),
            }

        pins.append(pin)
    return pins


# ---------------------------------------------------------------------------
# Fetch a single layer
# ---------------------------------------------------------------------------


def _fetch_layer_feed(layer: dict[str, Any]) -> None:
    """Fetch a feed URL and replace the layer's pins."""
    layer_id = layer["id"]
    feed_url = layer["feed_url"]
    layer_name = layer.get("name", layer_id)

    try:
        resp = requests.get(
            feed_url,
            timeout=_FETCH_TIMEOUT,
            headers={"User-Agent": "ShadowBroker-FeedIngester/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("Feed fetch failed for layer '%s' (%s): %s", layer_name, feed_url, e)
        return
    except (ValueError, TypeError) as e:
        logger.warning("Feed parse failed for layer '%s' (%s): %s", layer_name, feed_url, e)
        return

    pins = _parse_feed_response(data)

    from services.ai_pin_store import replace_layer_pins, update_layer
    count = replace_layer_pins(layer_id, pins)

    # Update layer metadata with last_fetched timestamp
    update_layer(layer_id, feed_last_fetched=time.time())

    _last_fetched[layer_id] = time.time()
    logger.info("Feed refresh for layer '%s': %d pins from %s", layer_name, count, feed_url)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _ingest_loop() -> None:
    """Daemon loop: scan for feed layers and refresh those that are due."""
    while _running:
        try:
            from services.ai_pin_store import get_feed_layers

            layers = get_feed_layers()
            now = time.time()

            for layer in layers:
                layer_id = layer["id"]
                interval = max(60, layer.get("feed_interval", 300))
                last = _last_fetched.get(layer_id, 0)

                if now - last >= interval:
                    try:
                        _fetch_layer_feed(layer)
                    except Exception as e:
                        logger.warning("Feed ingestion error for layer %s: %s",
                                       layer.get("name", layer_id), e)

        except Exception as e:
            logger.error("Feed ingester loop error: %s", e)

        # Sleep in short increments so we can stop cleanly
        for _ in range(int(_CHECK_INTERVAL)):
            if not _running:
                break
            time.sleep(1)


# ---------------------------------------------------------------------------
# Start / stop
# ---------------------------------------------------------------------------


def start_feed_ingester() -> None:
    """Start the feed ingester daemon thread."""
    global _running, _thread
    if _thread and _thread.is_alive():
        return
    _running = True
    _thread = threading.Thread(target=_ingest_loop, daemon=True, name="feed-ingester")
    _thread.start()
    logger.info("Feed ingester daemon started (check interval=%ds)", _CHECK_INTERVAL)


def stop_feed_ingester() -> None:
    """Stop the feed ingester daemon."""
    global _running
    _running = False
