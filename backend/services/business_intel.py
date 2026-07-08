from __future__ import annotations

import time
from collections import deque
from typing import Any

from services.market_intel import build_market_intel


BUSINESS_INTEL_KEYS = (
    "news",
    "gdelt",
    "weather_alerts",
    "internet_outages",
    "wastewater",
    "telegram_osint",
    "correlations",
    "scm_suppliers",
    "road_corridor_trends",
    "commercial_flights",
    "private_flights",
    "private_jets",
    "military_flights",
    "tracked_flights",
    "ships",
    "sigint",
    "trains",
)

_MAX_STORED_SIGNALS = 600
_SIGNAL_TTL_SECONDS = 7 * 24 * 3600
_SANITIZED_SIGNALS: deque[dict[str, Any]] = deque(maxlen=_MAX_STORED_SIGNALS)


def score_business_intel(
    *,
    text: str = "",
    events: list[dict[str, Any]] | None = None,
    market: str = "local_services",
    objective: str = "demand",
    source_label: str = "authorized_notes",
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float = 150.0,
    persist: bool = True,
    fuse_local: bool = True,
    data: dict[str, Any] | None = None,
    freshness: dict[str, str] | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    payload = build_market_intel(
        text=text,
        events=events or [],
        market=market,
        objective=objective,
        source_label=source_label,
        lat=lat,
        lng=lng,
        radius_km=radius_km,
        fuse_local=fuse_local,
        data=data or {},
        freshness=freshness or {},
        limit=limit,
    )
    if persist:
        _store_sanitized_signals(payload.get("action_queue") or [])
    payload["stored_signal_count"] = len(_active_stored_signals())
    payload["graph"] = build_business_graph(payload.get("action_queue") or [], data=data or {})
    return payload


def business_dashboard(
    *,
    data: dict[str, Any],
    freshness: dict[str, str] | None = None,
    market: str = "local_services",
    objective: str = "demand",
    limit: int = 30,
) -> dict[str, Any]:
    live_events = _events_from_live_data(data)
    stored = _active_stored_signals()
    payload = build_market_intel(
        events=[*stored, *live_events],
        market=market,
        objective=objective,
        source_label="shadowbroker_cached",
        fuse_local=False,
        freshness=freshness or {},
        limit=limit,
    )
    payload["stored_signal_count"] = len(stored)
    payload["live_event_count"] = len(live_events)
    payload["watchlist"] = _watchlist(payload.get("action_queue") or [])
    payload["stale_sources"] = _stale_sources(freshness or {})
    payload["graph"] = build_business_graph(payload.get("action_queue") or [], data=data)
    return payload


def build_business_graph(signals: list[dict[str, Any]], *, data: dict[str, Any] | None = None) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def node(node_id: str, label: str, node_type: str, **props: Any) -> None:
        current = nodes.setdefault(
            node_id,
            {
                "id": node_id,
                "label": label,
                "type": node_type,
                "score": 0.0,
                "count": 0,
                "properties": {},
            },
        )
        current["score"] = max(float(current.get("score") or 0), float(props.pop("score", 0) or 0))
        current["count"] = int(current.get("count") or 0) + int(props.pop("count", 1) or 1)
        current["properties"].update({k: v for k, v in props.items() if v not in (None, "")})

    def edge(source: str, target: str, label: str, weight: float = 1.0) -> None:
        if source == target:
            return
        edges.append({"source": source, "target": target, "label": label, "weight": round(weight, 2)})

    node("market:local_services", "Local services", "market", score=60)
    node("objective:demand", "Demand", "objective", score=50)
    edge("market:local_services", "objective:demand", "optimizes", 2)

    for item in signals[:80]:
        signal_id = f"signal:{item.get('id') or len(nodes)}"
        category = str(item.get("category") or "signal")
        source = str(item.get("source") or "unknown")
        grade = str(item.get("grade") or "watch")
        label = str(item.get("label") or "Market signal")
        score = float(item.get("score") or 0)
        area = str(item.get("area") or "")
        node(signal_id, label, "signal", score=score, grade=grade, detail=item.get("detail"), lat=item.get("lat"), lng=item.get("lng"))
        node(f"category:{category}", category.title(), "category", score=score)
        node(f"source:{source}", source, "source", score=score)
        edge("objective:demand", signal_id, "prioritizes", max(1, score / 30))
        edge(signal_id, f"category:{category}", "classified_as", 1.5)
        edge(signal_id, f"source:{source}", "evidenced_by", 1.2)
        if area:
            node(f"area:{area.lower()}", area, "area", score=score)
            edge(signal_id, f"area:{area.lower()}", "located_near", 1.4)

    for key, label, node_type in (
        ("commercial_flights", "Commercial flights", "mobility"),
        ("private_jets", "Private jets", "mobility"),
        ("military_flights", "Military aircraft", "risk"),
        ("sigint", "RF/SIGINT", "source"),
        ("gdelt", "GDELT clusters", "source"),
        ("weather_alerts", "Weather alerts", "risk"),
        ("internet_outages", "Internet outages", "risk"),
        ("wastewater", "Wastewater signals", "risk"),
        ("telegram_osint", "Telegram OSINT", "source"),
    ):
        count = _count_data(data or {}, key)
        if count:
            node(f"feed:{key}", label, node_type, score=min(100, count / 4), count=count, feed_key=key)
            edge("market:local_services", f"feed:{key}", "monitors", min(8, max(1, count / 250)))

    return {
        "nodes": sorted(nodes.values(), key=lambda n: (-float(n.get("score") or 0), str(n.get("id"))))[:120],
        "links": edges[:220],
    }


def _store_sanitized_signals(signals: list[dict[str, Any]]) -> None:
    now = int(time.time())
    for item in signals[:100]:
        if not isinstance(item, dict):
            continue
        sanitized = {
            "id": str(item.get("id") or f"stored:{now}:{len(_SANITIZED_SIGNALS)}"),
            "kind": item.get("kind"),
            "category": item.get("category"),
            "market": item.get("market"),
            "objective": item.get("objective"),
            "source": item.get("source"),
            "label": item.get("label"),
            "detail": item.get("detail"),
            "lat": item.get("lat"),
            "lng": item.get("lng"),
            "area": item.get("area"),
            "metrics": item.get("metrics") or [],
            "confidence": item.get("confidence"),
            "impact_rank": item.get("impact_rank"),
            "urgency_rank": item.get("urgency_rank"),
            "timestamp": int(item.get("timestamp") or now),
            "action": item.get("action"),
            "score": item.get("score"),
            "grade": item.get("grade"),
        }
        _SANITIZED_SIGNALS.append(sanitized)


def _active_stored_signals() -> list[dict[str, Any]]:
    cutoff = int(time.time()) - _SIGNAL_TTL_SECONDS
    active = [item for item in _SANITIZED_SIGNALS if int(item.get("timestamp") or 0) >= cutoff]
    if len(active) != len(_SANITIZED_SIGNALS):
        _SANITIZED_SIGNALS.clear()
        _SANITIZED_SIGNALS.extend(active)
    return active


def _events_from_live_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for article in _iter_entries(data.get("news"))[:40]:
        events.append(
            {
                "id": f"news:{article.get('id') or len(events)}",
                "category": "risk" if float(article.get("risk_score") or 0) >= 0.55 else "sentiment",
                "source": f"news:{article.get('source') or 'feed'}",
                "label": article.get("title") or "News signal",
                "detail": article.get("summary") or article.get("title") or "",
                "lat": article.get("lat"),
                "lng": article.get("lng"),
                "confidence": 0.58,
                "impact_rank": 3 if float(article.get("risk_score") or 0) >= 0.55 else 2,
                "urgency_rank": 2,
            }
        )
    for incident in _iter_entries(data.get("gdelt"))[:60]:
        props = incident.get("properties") if isinstance(incident, dict) else {}
        coords = ((incident.get("geometry") or {}).get("coordinates") or []) if isinstance(incident, dict) else []
        count = int((props or {}).get("count") or 0)
        events.append(
            {
                "id": f"gdelt:{len(events)}",
                "category": "risk" if count >= 12 else "sentiment",
                "source": "shadowbroker:gdelt",
                "label": (props or {}).get("name") or "GDELT cluster",
                "detail": _first((props or {}).get("_headlines_list")) or f"{count} event cluster",
                "lat": coords[1] if len(coords) >= 2 else None,
                "lng": coords[0] if len(coords) >= 2 else None,
                "confidence": 0.54,
                "impact_rank": 3 if count >= 12 else 2,
                "urgency_rank": 2,
            }
        )
    for key, category, impact in (
        ("weather_alerts", "risk", 3),
        ("internet_outages", "risk", 3),
        ("wastewater", "risk", 2),
        ("telegram_osint", "sentiment", 2),
    ):
        for entry in _iter_nested_entries(data.get(key))[:35]:
            events.append(
                {
                    "id": f"{key}:{len(events)}",
                    "category": category,
                    "source": f"shadowbroker:{key}",
                    "label": _label_for_entry(entry),
                    "detail": _detail_for_entry(entry),
                    "lat": entry.get("lat") or (entry.get("coords") or [None, None])[0],
                    "lng": entry.get("lng") or entry.get("lon") or (entry.get("coords") or [None, None, None])[1],
                    "confidence": 0.5,
                    "impact_rank": impact,
                    "urgency_rank": 3 if category == "risk" else 1,
                }
            )
    return events[:250]


def _watchlist(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in signals
        if str(item.get("grade")) in {"alpha", "strong"} or int(item.get("urgency_rank") or 0) >= 3
    ][:12]


def _stale_sources(freshness: dict[str, str]) -> list[str]:
    now = time.time()
    stale = []
    for key in BUSINESS_INTEL_KEYS:
        stamp = freshness.get(key)
        if not stamp:
            stale.append(key)
            continue
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            age = now - dt.timestamp()
        except Exception:
            continue
        if age > 6 * 3600:
            stale.append(key)
    return stale[:12]


def _iter_entries(value: Any) -> list[dict[str, Any]]:
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def _iter_nested_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return _iter_entries(value)
    if isinstance(value, dict):
        for key in ("posts", "threats", "suppliers", "corridors", "features"):
            if isinstance(value.get(key), list):
                return _iter_entries(value.get(key))
    return []


def _count_data(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for nested in ("posts", "threats", "suppliers", "corridors", "features"):
            if isinstance(value.get(nested), list):
                return len(value[nested])
    return 0


def _first(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return ""


def _label_for_entry(entry: dict[str, Any]) -> str:
    for key in ("title", "event", "headline", "region_name", "site_name", "name", "description"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value[:120]
    return "Cached signal"


def _detail_for_entry(entry: dict[str, Any]) -> str:
    for key in ("summary", "description", "headline", "country_name", "city", "source", "route"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value[:240]
    return _label_for_entry(entry)
