from __future__ import annotations

import math
import re
import time
from typing import Any

from services.local_intel import build_local_intel


MARKET_INTEL_KEYS = (
    "commercial_flights",
    "private_flights",
    "private_jets",
    "military_flights",
    "tracked_flights",
    "uavs",
    "ships",
    "earthquakes",
    "firms_fires",
    "weather_alerts",
    "air_quality",
    "internet_outages",
    "cctv",
    "scanners",
    "news",
    "gdelt",
    "liveuamap",
    "wastewater",
    "trains",
)

MAX_TEXT_CHARS = 24_000
MAX_EVENTS = 250

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,32}\b")
_COORD_RE = re.compile(r"(?<!\d)(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)(?!\d)")
_MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%")

_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "risk",
        (
            "outage",
            "closed",
            "closure",
            "delay",
            "delayed",
            "blocked",
            "accident",
            "flood",
            "warning",
            "storm",
            "fire",
            "crime",
            "theft",
            "police",
            "shortage",
            "recall",
            "strike",
            "permit denied",
        ),
    ),
    (
        "demand",
        (
            "need",
            "needs",
            "looking for",
            "recommend",
            "recommendation",
            "anyone know",
            "iso",
            "quote",
            "estimate",
            "repair",
            "broken",
            "urgent",
            "waitlist",
            "booked",
            "sold out",
        ),
    ),
    (
        "supply",
        (
            "available",
            "in stock",
            "inventory",
            "surplus",
            "warehouse",
            "restocked",
            "delivery",
            "shipment",
            "lead time",
        ),
    ),
    (
        "competitor",
        (
            "competitor",
            "opened",
            "opening",
            "closed permanently",
            "hiring",
            "coupon",
            "discount",
            "ad campaign",
            "review",
            "price cut",
            "new location",
        ),
    ),
    (
        "pricing",
        (
            "price",
            "pricing",
            "expensive",
            "cheap",
            "quote",
            "bid",
            "rate",
            "fee",
            "margin",
        ),
    ),
    (
        "labor",
        (
            "hiring",
            "staff",
            "crew",
            "contractor",
            "driver",
            "technician",
            "installer",
            "overtime",
        ),
    ),
    (
        "mobility",
        (
            "traffic",
            "road",
            "route",
            "delivery",
            "parking",
            "train",
            "port",
            "airport",
            "bridge",
        ),
    ),
)

_URGENCY_WORDS = (
    "urgent",
    "asap",
    "today",
    "now",
    "emergency",
    "warning",
    "critical",
    "sold out",
    "blocked",
    "closed",
)


def build_market_intel(
    *,
    text: str = "",
    events: list[dict[str, Any]] | None = None,
    market: str = "local_services",
    objective: str = "demand",
    source_label: str = "operator_input",
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float = 150.0,
    fuse_local: bool = True,
    data: dict[str, Any] | None = None,
    freshness: dict[str, str] | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Build an operational market view from authorized local notes plus cached feeds.

    This is intentionally stateless: raw input is scored in memory and not persisted.
    """
    radius = _clamp(radius_km, 5.0, 1000.0)
    origin = (lat, lng) if lat is not None and lng is not None and _valid_point(lat, lng) else None
    market_id = _slug(market or "local_services")
    objective_id = _slug(objective or "demand")
    now = int(time.time())

    signals: list[dict[str, Any]] = []
    redactions = {"email": 0, "phone": 0, "url": 0, "handle": 0}
    for line in _split_text(text[:MAX_TEXT_CHARS]):
        sanitized, counts = _sanitize(line)
        _merge_counts(redactions, counts)
        if len(sanitized) < 8:
            continue
        signals.append(
            _signal_from_text(
                sanitized,
                market=market_id,
                objective=objective_id,
                source_label=source_label or "operator_input",
                now=now,
            )
        )

    for record in list(events or [])[:MAX_EVENTS]:
        if isinstance(record, dict):
            signals.append(
                _signal_from_record(
                    record,
                    market=market_id,
                    objective=objective_id,
                    source_label=source_label or "operator_input",
                    now=now,
                )
            )

    local_payload: dict[str, Any] | None = None
    if fuse_local and origin and data is not None:
        local_payload = build_local_intel(
            lat=float(origin[0]),
            lng=float(origin[1]),
            radius_km=radius,
            data=data,
            freshness=freshness or {},
            limit=max(80, min(100, int(limit or 40) * 2)),
        )
        for item in list(local_payload.get("items") or [])[:80]:
            if isinstance(item, dict):
                signals.append(
                    _signal_from_local_item(
                        item,
                        market=market_id,
                        objective=objective_id,
                        now=now,
                    )
                )

    for signal in signals:
        _finalize_signal(signal, objective=objective_id)

    signals.sort(
        key=lambda item: (
            -float(item.get("score", 0)),
            -float(item.get("confidence", 0)),
            str(item.get("label") or ""),
        )
    )
    capped = signals[: max(1, min(100, int(limit or 40)))]

    return {
        "query": {
            "market": market_id,
            "objective": objective_id,
            "lat": round(float(origin[0]), 6) if origin else None,
            "lng": round(float(origin[1]), 6) if origin else None,
            "radius_km": radius,
            "generated_at": now,
            "fused_local": bool(local_payload),
        },
        "summary": _summary(signals, capped),
        "action_queue": capped,
        "heat": _heat(signals),
        "source_matrix": _source_matrix(signals),
        "timeline": _timeline(signals, now=now),
        "privacy": {
            "stored": False,
            "redacted": sum(redactions.values()),
            "redactions": redactions,
            "guidance": "Use authorized exports, public data, licensed feeds, or operator notes.",
        },
        "local_summary": (local_payload or {}).get("summary", {}),
    }


def _signal_from_text(
    text: str,
    *,
    market: str,
    objective: str,
    source_label: str,
    now: int,
) -> dict[str, Any]:
    category = _classify(text)
    kind = "risk" if category == "risk" else "opportunity"
    lat, lng = _extract_point(text)
    metrics = _extract_metrics(text)
    urgency = _urgency(text)
    evidence = 1 + len(metrics)
    label = _label_from_text(text, category)
    confidence = 0.42 + (0.1 if lat is not None and lng is not None else 0) + min(0.12, len(metrics) * 0.04)
    confidence += 0.08 if urgency >= 3 else 0
    return {
        "id": f"operator:{abs(hash((text, now))) % 10_000_000}",
        "kind": kind,
        "category": category,
        "market": market,
        "objective": objective,
        "source": _truncate(source_label, 40) or "operator_input",
        "label": label,
        "detail": _truncate(text, 220),
        "lat": lat,
        "lng": lng,
        "area": _extract_area(text),
        "metrics": metrics,
        "evidence_count": evidence,
        "confidence": _clamp(confidence, 0.1, 0.92),
        "impact_rank": _impact_rank(category, urgency, metrics),
        "urgency_rank": urgency,
        "timestamp": now,
        "action": _action_for(category, objective),
    }


def _signal_from_record(
    record: dict[str, Any],
    *,
    market: str,
    objective: str,
    source_label: str,
    now: int,
) -> dict[str, Any]:
    text = str(record.get("detail") or record.get("text") or record.get("summary") or record.get("title") or "").strip()
    sanitized, _counts = _sanitize(text)
    category = _slug(str(record.get("category") or "")) or _classify(sanitized)
    if category not in {entry[0] for entry in _CATEGORY_KEYWORDS}:
        category = _classify(sanitized)
    lat = _to_float(record.get("lat", record.get("latitude")))
    lng = _to_float(record.get("lng", record.get("lon", record.get("longitude"))))
    if lat is None or lng is None or not _valid_point(lat, lng):
        lat, lng = _extract_point(sanitized)
    evidence = int(_to_float(record.get("evidence_count")) or 1)
    confidence = _to_float(record.get("confidence"))
    if confidence is None:
        confidence = 0.5 + min(0.2, max(0, evidence - 1) * 0.04)
    urgency = int(_to_float(record.get("urgency_rank")) or _urgency(sanitized))
    return {
        "id": str(record.get("id") or f"record:{abs(hash((sanitized, now))) % 10_000_000}"),
        "kind": str(record.get("kind") or ("risk" if category == "risk" else "opportunity")),
        "category": category,
        "market": _slug(str(record.get("market") or market)),
        "objective": _slug(str(record.get("objective") or objective)),
        "source": _truncate(str(record.get("source") or source_label or "operator_input"), 40),
        "label": _truncate(str(record.get("label") or record.get("title") or _label_from_text(sanitized, category)), 92),
        "detail": _truncate(sanitized or str(record.get("label") or "Structured market signal"), 220),
        "lat": lat,
        "lng": lng,
        "area": _truncate(str(record.get("area") or _extract_area(sanitized)), 80),
        "metrics": _extract_metrics(sanitized),
        "evidence_count": max(1, min(99, evidence)),
        "confidence": _clamp(float(confidence), 0.1, 0.98),
        "impact_rank": int(_to_float(record.get("impact_rank")) or _impact_rank(category, urgency, [])),
        "urgency_rank": max(1, min(4, urgency)),
        "timestamp": int(_to_float(record.get("timestamp")) or now),
        "action": _truncate(str(record.get("action") or _action_for(category, objective)), 120),
    }


def _signal_from_local_item(item: dict[str, Any], *, market: str, objective: str, now: int) -> dict[str, Any]:
    local_category = str(item.get("category") or "intel")
    source_key = str(item.get("source_key") or local_category)
    severity_rank = int(_to_float(item.get("severity_rank")) or 1)
    category = _local_market_category(local_category, str(item.get("kind") or ""))
    muted_sources = {
        "commercial_flights",
        "private_flights",
        "private_jets",
        "military_flights",
        "tracked_flights",
        "uavs",
        "cctv",
        "scanners",
    }
    risk_sources = {
        "weather_alerts",
        "earthquakes",
        "firms_fires",
        "air_quality",
        "internet_outages",
        "wastewater",
        "trains",
    }
    impact_rank = min(severity_rank, 2) if source_key in muted_sources else severity_rank
    urgency_rank = 1 if source_key in muted_sources else 4 if severity_rank >= 4 else 3 if severity_rank >= 3 else 1
    kind = "risk" if source_key in risk_sources and impact_rank >= 2 else "opportunity"
    source = f"shadowbroker:{source_key}"
    confidence = 0.48 + min(0.26, severity_rank * 0.055)
    if item.get("lat") is not None and item.get("lng") is not None:
        confidence += 0.08
    return {
        "id": f"local:{item.get('id') or abs(hash(str(item))) % 10_000_000}",
        "kind": kind,
        "category": category,
        "market": market,
        "objective": objective,
        "source": _truncate(source, 40),
        "label": _truncate(str(item.get("label") or item.get("kind") or "Local signal"), 92),
        "detail": _truncate(str(item.get("detail") or item.get("kind") or "Cached local signal"), 220),
        "lat": _to_float(item.get("lat")),
        "lng": _to_float(item.get("lng")),
        "area": "",
        "metrics": [f"{item.get('distance_km')}km"] if item.get("distance_km") is not None else [],
        "evidence_count": 1,
        "confidence": _clamp(confidence, 0.1, 0.96),
        "impact_rank": max(1, min(4, impact_rank)),
        "urgency_rank": max(1, min(4, urgency_rank)),
        "timestamp": now,
        "action": _action_for(category, objective),
    }


def _finalize_signal(signal: dict[str, Any], *, objective: str) -> None:
    impact = max(1, min(4, int(_to_float(signal.get("impact_rank")) or 1)))
    urgency = max(1, min(4, int(_to_float(signal.get("urgency_rank")) or 1)))
    confidence = _clamp(float(_to_float(signal.get("confidence")) or 0.4), 0.1, 0.98)
    evidence = max(1, min(99, int(_to_float(signal.get("evidence_count")) or 1)))
    objective_bonus = 5 if str(signal.get("category")) in _objective_categories(objective) else 0
    score = impact * 18 + urgency * 7 + confidence * 28 + min(12, evidence * 2) + objective_bonus
    signal["impact_rank"] = impact
    signal["urgency_rank"] = urgency
    signal["confidence"] = round(confidence, 2)
    signal["score"] = round(score, 2)
    signal["grade"] = _grade(score)
    signal["kind"] = "risk" if str(signal.get("category")) in {"risk", "mobility"} else str(signal.get("kind") or "opportunity")


def _summary(all_signals: list[dict[str, Any]], returned: list[dict[str, Any]]) -> dict[str, Any]:
    opportunity_count = sum(1 for item in all_signals if item.get("kind") != "risk")
    risk_count = sum(1 for item in all_signals if item.get("kind") == "risk")
    avg_conf = (
        sum(float(item.get("confidence") or 0) for item in all_signals) / len(all_signals)
        if all_signals
        else 0.0
    )
    return {
        "total": len(all_signals),
        "returned": len(returned),
        "opportunities": opportunity_count,
        "risks": risk_count,
        "average_confidence": round(avg_conf, 2),
        "top_grade": returned[0]["grade"] if returned else "none",
        "primary_categories": _top_counts(all_signals, "category", limit=5),
        "primary_sources": _top_counts(all_signals, "source", limit=5),
    }


def _heat(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in signals:
        category = str(item.get("category") or "uncategorized")
        bucket = buckets.setdefault(
            category,
            {"category": category, "count": 0, "score": 0.0, "risk": 0, "opportunity": 0},
        )
        bucket["count"] += 1
        bucket["score"] += float(item.get("score") or 0)
        if item.get("kind") == "risk":
            bucket["risk"] += 1
        else:
            bucket["opportunity"] += 1
    rows = list(buckets.values())
    for row in rows:
        row["score"] = round(float(row["score"]) / max(1, int(row["count"])), 2)
    rows.sort(key=lambda row: (-float(row["score"]), -int(row["count"]), str(row["category"])))
    return rows


def _source_matrix(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matrix: dict[tuple[str, str], dict[str, Any]] = {}
    for item in signals:
        key = (str(item.get("source") or "unknown"), str(item.get("category") or "uncategorized"))
        row = matrix.setdefault(
            key,
            {"source": key[0], "category": key[1], "count": 0, "max_score": 0.0, "confidence": 0.0},
        )
        row["count"] += 1
        row["max_score"] = max(float(row["max_score"]), float(item.get("score") or 0))
        row["confidence"] += float(item.get("confidence") or 0)
    rows = list(matrix.values())
    for row in rows:
        row["confidence"] = round(float(row["confidence"]) / max(1, int(row["count"])), 2)
        row["max_score"] = round(float(row["max_score"]), 2)
    rows.sort(key=lambda row: (-float(row["max_score"]), -int(row["count"])))
    return rows[:16]


def _timeline(signals: list[dict[str, Any]], *, now: int) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in signals:
        ts = int(_to_float(item.get("timestamp")) or now)
        age_hours = max(0, int((now - ts) / 3600))
        bucket_id = "now" if age_hours == 0 else f"{age_hours}h"
        bucket = buckets.setdefault(bucket_id, {"bucket": bucket_id, "count": 0, "risk": 0, "opportunity": 0})
        bucket["count"] += 1
        if item.get("kind") == "risk":
            bucket["risk"] += 1
        else:
            bucket["opportunity"] += 1
    rows = list(buckets.values())
    rows.sort(key=lambda row: 0 if row["bucket"] == "now" else int(str(row["bucket"]).rstrip("h")))
    return rows[:12]


def _split_text(text: str) -> list[str]:
    chunks: list[str] = []
    for raw in re.split(r"[\r\n]+", text or ""):
        line = raw.strip(" -\t")
        if not line:
            continue
        if len(line) <= 320:
            chunks.append(line)
            continue
        chunks.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+", line) if len(part.strip()) >= 8)
    return chunks[:MAX_EVENTS]


def _sanitize(text: str) -> tuple[str, dict[str, int]]:
    counts = {
        "email": len(_EMAIL_RE.findall(text)),
        "phone": len(_PHONE_RE.findall(text)),
        "url": len(_URL_RE.findall(text)),
        "handle": len(_HANDLE_RE.findall(text)),
    }
    text = _EMAIL_RE.sub("[email]", text)
    text = _PHONE_RE.sub("[phone]", text)
    text = _URL_RE.sub("[url]", text)
    text = _HANDLE_RE.sub("[handle]", text)
    return " ".join(text.split()), counts


def _merge_counts(target: dict[str, int], counts: dict[str, int]) -> None:
    for key, value in counts.items():
        target[key] = int(target.get(key, 0)) + int(value or 0)


def _classify(text: str) -> str:
    lower = text.lower()
    scored: list[tuple[int, str]] = []
    for category, words in _CATEGORY_KEYWORDS:
        score = sum(1 for word in words if word in lower)
        if category == "pricing":
            score += len(_MONEY_RE.findall(text))
        if score:
            scored.append((score, category))
    if not scored:
        return "sentiment"
    scored.sort(key=lambda entry: (-entry[0], _category_priority(entry[1])))
    return scored[0][1]


def _category_priority(category: str) -> int:
    order = {"risk": 0, "demand": 1, "pricing": 2, "supply": 3, "competitor": 4, "labor": 5, "mobility": 6}
    return order.get(category, 99)


def _extract_point(text: str) -> tuple[float | None, float | None]:
    match = _COORD_RE.search(text)
    if not match:
        return None, None
    lat = _to_float(match.group(1))
    lng = _to_float(match.group(2))
    if lat is None or lng is None or not _valid_point(lat, lng):
        return None, None
    return lat, lng


def _extract_metrics(text: str) -> list[str]:
    metrics = []
    metrics.extend(match.group(0).replace(" ", "") for match in _MONEY_RE.finditer(text))
    metrics.extend(match.group(0).replace(" ", "") for match in _PERCENT_RE.finditer(text))
    return metrics[:6]


def _extract_area(text: str) -> str:
    lower = text.lower()
    for marker in (" near ", " at ", " in ", " around "):
        idx = lower.find(marker)
        if idx == -1:
            continue
        area = text[idx + len(marker) :].split(".")[0].split(",")[0]
        area = re.sub(r"\s+", " ", area).strip()
        if 2 <= len(area) <= 80:
            return area
    return ""


def _urgency(text: str) -> int:
    lower = text.lower()
    hits = sum(1 for word in _URGENCY_WORDS if word in lower)
    if hits >= 3:
        return 4
    if hits == 2:
        return 3
    if hits == 1:
        return 2
    return 1


def _impact_rank(category: str, urgency: int, metrics: list[str]) -> int:
    if category == "risk" and urgency >= 3:
        return 4
    if category in {"demand", "pricing"} and (metrics or urgency >= 2):
        return 3
    if category in {"competitor", "supply", "mobility"}:
        return 2 + (1 if urgency >= 3 else 0)
    return 2 if category != "sentiment" else 1


def _label_from_text(text: str, category: str) -> str:
    prefix = {
        "risk": "Operational risk",
        "demand": "Demand signal",
        "supply": "Supply signal",
        "competitor": "Competitor move",
        "pricing": "Pricing signal",
        "labor": "Labor signal",
        "mobility": "Mobility friction",
        "sentiment": "Market chatter",
    }.get(category, "Market signal")
    clean = re.sub(r"\s+", " ", text).strip()
    return _truncate(f"{prefix}: {clean}", 92)


def _action_for(category: str, objective: str) -> str:
    if category == "risk":
        return "Check exposure, reroute work, and watch for corroboration."
    if category == "demand":
        return "Package an offer, quote quickly, and log the unmet need."
    if category == "pricing":
        return "Compare spread, test a premium bid, and watch response time."
    if category == "competitor":
        return "Review competitor move and adjust positioning if the signal repeats."
    if category == "supply":
        return "Check available inventory and match it to nearby demand."
    if category == "labor":
        return "Assess staffing constraint and price capacity-sensitive work accordingly."
    if category == "mobility":
        return "Review routes, service windows, and delivery promises."
    if objective == "operations":
        return "Add to watch queue and review with the next operations check."
    return "Monitor for a second source before acting."


def _local_market_category(local_category: str, kind: str) -> str:
    text = f"{local_category} {kind}".lower()
    if local_category in {"hazard", "health"}:
        return "risk"
    if local_category in {"mobility", "maritime"} or any(word in text for word in ("train", "ship", "aircraft")):
        return "mobility"
    if local_category == "infrastructure":
        return "risk" if "outage" in text else "supply"
    if local_category == "intel":
        return "sentiment"
    if local_category in {"air", "rf", "space"}:
        return "mobility"
    return "sentiment"


def _objective_categories(objective: str) -> set[str]:
    return {
        "demand": {"demand", "pricing", "supply"},
        "pricing": {"pricing", "demand", "competitor"},
        "operations": {"risk", "mobility", "labor", "supply"},
        "expansion": {"demand", "competitor", "sentiment", "supply"},
    }.get(objective, {"demand", "pricing", "risk"})


def _top_counts(signals: list[dict[str, Any]], key: str, *, limit: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in signals:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))[:limit])


def _grade(score: float) -> str:
    if score >= 105:
        return "alpha"
    if score >= 85:
        return "strong"
    if score >= 65:
        return "watch"
    return "low"


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text[:48]


def _truncate(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _valid_point(lat: float, lng: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lng <= 180


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
