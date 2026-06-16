"""Normalize Shadowbroker feed records into GT analytics feed items."""

from __future__ import annotations

import re
from typing import Any, Iterable

_DOMAIN_CONFLICT = "conflict"
_DOMAIN_UNREST = "unrest"
_DOMAIN_FINANCIAL = "financial"

_CONFLICT_HINTS = re.compile(
    r"\b(war|missile|strike|attack|military|invasion|troop|shelling|drone|bomb|nuclear)\b",
    re.I,
)
_UNREST_HINTS = re.compile(
    r"\b(protest|rally|strike|riot|unrest|mobiliz|demonstrat|curfew|purge|coup)\b",
    re.I,
)
_FINANCIAL_HINTS = re.compile(
    r"\b(payroll|loan|default|bankruptcy|liquidity|sanction|supply\s+chain|delay|shortage)\b",
    re.I,
)


def _clean_region(value: Any) -> str:
    region = str(value or "").strip().lower()
    return region or "global"


def _infer_domain(text: str, explicit: str | None = None) -> str:
    if explicit in {_DOMAIN_CONFLICT, _DOMAIN_UNREST, _DOMAIN_FINANCIAL}:
        return explicit
    if _CONFLICT_HINTS.search(text):
        return _DOMAIN_CONFLICT
    if _UNREST_HINTS.search(text):
        return _DOMAIN_UNREST
    if _FINANCIAL_HINTS.search(text):
        return _DOMAIN_FINANCIAL
    return _DOMAIN_FINANCIAL


def _text_from_record(
    record: dict[str, Any],
    *,
    prefer_translation: bool = False,
) -> str:
    """Build ingest text; prefer English translations for Telegram OSINT when set."""
    if prefer_translation:
        translated_parts = [
            record.get("title_translated"),
            record.get("description_translated"),
        ]
        translated = "\n".join(
            str(p).strip() for p in translated_parts if p and str(p).strip()
        )
        if translated:
            return translated

    parts = [
        record.get("title"),
        record.get("description"),
        record.get("text"),
        record.get("summary"),
    ]
    return "\n".join(str(p).strip() for p in parts if p and str(p).strip())


_HASHTAG_REGION = re.compile(r"#([a-z][a-z0-9_-]{2,})", re.I)


def _region_from_hashtags(text: str) -> str | None:
    """Map common theater hashtags (#Ukraine) to dossier/heatmap region keys."""
    for match in _HASHTAG_REGION.finditer(text or ""):
        tag = match.group(1).lower()
        if tag in {
            "ukraine",
            "russia",
            "israel",
            "iran",
            "gaza",
            "syria",
            "taiwan",
            "china",
            "belfast",
            "uk",
            "usa",
        }:
            return tag
    return None


def _region_from_record(record: dict[str, Any], *, text: str = "") -> str:
    for key in ("geotag", "region", "country", "location"):
        if record.get(key):
            return _clean_region(record[key])
    hashtag_region = _region_from_hashtags(text)
    if hashtag_region:
        return hashtag_region
    coords = record.get("coords")
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            lat = float(coords[0])
            lng = float(coords[1])
            return f"{lat:.2f},{lng:.2f}"
        except (TypeError, ValueError):
            pass
    return "global"


def _entities_from_record(record: dict[str, Any]) -> list[str]:
    entities: list[str] = []
    for key in ("entities", "tags", "keywords"):
        raw = record.get(key)
        if isinstance(raw, list):
            entities.extend(str(v).strip() for v in raw if str(v).strip())
        elif isinstance(raw, str) and raw.strip():
            entities.extend(part.strip() for part in raw.split(",") if part.strip())
    channel = str(record.get("channel") or "").strip()
    if channel:
        entities.append(f"channel:{channel}")
    source = str(record.get("source") or "").strip()
    if source:
        entities.append(f"source:{source}")
    return entities


def normalize_feed_item(record: dict[str, Any], *, source_type: str = "generic") -> dict[str, Any]:
    """Map a news/Telegram/GDELT record into the GT engine schema."""
    prefer_translation = source_type == "telegram_osint"
    text = _text_from_record(record, prefer_translation=prefer_translation)
    if prefer_translation and not text.strip():
        text = _text_from_record(record, prefer_translation=False)
    region = _region_from_record(record, text=text)
    domain = _infer_domain(text, record.get("domain"))
    coords = record.get("coords")
    lat = lng = None
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            lat = float(coords[0])
            lng = float(coords[1])
        except (TypeError, ValueError):
            lat = lng = None

    return {
        "id": record.get("id") or record.get("link"),
        "text": text,
        "source": str(record.get("source") or source_type),
        "source_type": source_type,
        "region": region,
        "domain": domain,
        "entities": _entities_from_record(record),
        "coords": [lat, lng] if lat is not None and lng is not None else None,
        "published": record.get("published"),
        "risk_score": record.get("risk_score"),
    }


def iter_telegram_posts(payload: dict[str, Any] | None) -> Iterable[dict[str, Any]]:
    from services.telegram_translate import apply_post_translation, telegram_translate_enabled

    posts = list((payload or {}).get("posts") or [])
    for post in posts:
        if not isinstance(post, dict):
            continue
        if not (post.get("description") or post.get("title")):
            continue
        enriched = (
            apply_post_translation(post)
            if telegram_translate_enabled()
            else post
        )
        yield normalize_feed_item(enriched, source_type="telegram_osint")


def iter_news_items(payload: list[dict[str, Any]] | None) -> Iterable[dict[str, Any]]:
    for item in list(payload or []):
        if not isinstance(item, dict):
            continue
        yield normalize_feed_item(item, source_type="news")
        for article in list(item.get("articles") or []):
            if isinstance(article, dict):
                yield normalize_feed_item(article, source_type="news_cluster")


def iter_gdelt_features(payload: list[dict[str, Any]] | None) -> Iterable[dict[str, Any]]:
    for feature in list(payload or []):
        if not isinstance(feature, dict):
            continue
        props = dict(feature.get("properties") or {})
        geometry = dict(feature.get("geometry") or {})
        coords = None
        if geometry.get("type") == "Point":
            raw = geometry.get("coordinates")
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                coords = [float(raw[1]), float(raw[0])]
        record = {
            "title": props.get("name") or props.get("title"),
            "description": props.get("snippet") or props.get("description"),
            "source": props.get("source") or "gdelt",
            "coords": coords,
            "published": props.get("date") or props.get("published"),
            "region": props.get("location") or props.get("country"),
        }
        if record["title"] or record["description"]:
            yield normalize_feed_item(record, source_type="gdelt")