"""Oracle Service — deterministic intelligence ranking for news items.

Enriches news items with:
- oracle_score: risk_score weighted by source confidence (0–10)
- sentiment: VADER compound score (-1.0 to +1.0)
- prediction_odds: matched prediction market probabilities (or None)
- machine_assessment: structured human-readable analysis string
"""

import logging

logger = logging.getLogger(__name__)

_analyzer = None


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


def compute_sentiment(headline: str) -> float:
    """VADER compound sentiment score for a headline. Range: -1.0 to +1.0."""
    if not headline:
        return 0.0
    return _get_analyzer().polarity_scores(headline)["compound"]


def compute_oracle_score(risk_score: int, source_weight: float) -> float:
    """Weighted oracle score: risk_score scaled by source confidence.

    source_weight is 1–5 (from feed config). Normalised to 0.2–1.0 multiplier.
    Result range: 0.0–10.0.
    """
    multiplier = source_weight / 5.0  # 1→0.2, 5→1.0
    return round(risk_score * multiplier, 1)


_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "if", "not", "no", "so", "as", "up",
    "out", "about", "into", "over", "after", "before", "between", "under",
    "than", "then", "more", "most", "other", "some", "such", "only", "own",
    "same", "also", "just", "how", "what", "which", "who", "whom", "when",
    "where", "why", "all", "each", "every", "both", "few", "many", "much",
    "any", "very", "too", "here", "there", "now", "new", "says", "said",
    "-", "--", "—", "vs", "vs.", "&", "he", "she", "they", "we", "you",
    "his", "her", "my", "our", "your", "their", "him", "us", "them",
})


def _tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, remove stop words."""
    import re
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def _match_prediction_markets(title: str, markets: list[dict]) -> dict | None:
    """Find best-matching prediction market for a news headline.

    Uses Jaccard similarity on meaningful tokens (stop words removed).
    Requires at least 2 meaningful keyword overlaps AND Jaccard >= 0.15.
    """
    if not markets or not title:
        return None

    title_words = _tokenize(title)
    if len(title_words) < 2:
        return None

    best_match = None
    best_score = 0.0

    for market in markets:
        market_title = market.get("title", "")
        market_words = _tokenize(market_title)
        if len(market_words) < 2:
            continue

        intersection = title_words & market_words
        if len(intersection) < 2:
            continue

        union = title_words | market_words
        jaccard = len(intersection) / len(union) if union else 0.0

        if jaccard > best_score and jaccard >= 0.15:
            best_score = jaccard
            best_match = market

    if not best_match:
        return None

    return {
        "title": best_match.get("title", ""),
        "polymarket_pct": best_match.get("polymarket_pct"),
        "kalshi_pct": best_match.get("kalshi_pct"),
        "consensus_pct": best_match.get("consensus_pct"),
        "match_score": round(best_score, 2),
    }


def _build_assessment(oracle_score: float, sentiment: float, prediction: dict | None) -> str:
    """Build structured machine_assessment string."""
    parts = []

    # Oracle tier
    if oracle_score >= 7:
        tier = "CRITICAL"
    elif oracle_score >= 4:
        tier = "ELEVATED"
    else:
        tier = "ROUTINE"
    parts.append(f"ORACLE: {oracle_score}/10 [{tier}]")

    # Sentiment
    if sentiment >= 0.05:
        sdir = "POSITIVE"
    elif sentiment <= -0.05:
        sdir = "NEGATIVE"
    else:
        sdir = "NEUTRAL"
    parts.append(f"SENTIMENT: {sentiment:+.2f} [{sdir}]")

    # Prediction market
    if prediction:
        consensus = prediction.get("consensus_pct")
        if consensus is not None:
            parts.append(f"MKT CONSENSUS: {consensus}%")
            poly = prediction.get("polymarket_pct")
            kalshi = prediction.get("kalshi_pct")
            sources = []
            if poly is not None:
                sources.append(f"Polymarket {poly}%")
            if kalshi is not None:
                sources.append(f"Kalshi {kalshi}%")
            if sources:
                parts.append(f"  Sources: {' | '.join(sources)}")

    return " // ".join(parts[:3]) + ("\n" + parts[3] if len(parts) > 3 else "")


def enrich_news_items(
    news_items: list[dict], source_weights: dict[str, float], markets: list[dict] | None = None
) -> list[dict]:
    """Enrich news items with oracle scores, sentiment, and prediction market odds.

    Args:
        news_items: list of news item dicts (modified in-place)
        source_weights: {source_name: weight} from feed config (1–5 scale)
        markets: merged prediction market events list (or None)

    Returns:
        The same list, enriched with oracle_score, sentiment, prediction_odds, machine_assessment.
    """
    if markets is None:
        markets = []

    for item in news_items:
        title = item.get("title", "")
        source = item.get("source", "")
        risk_score = item.get("risk_score", 1)
        weight = source_weights.get(source, 3)  # default weight 3 (mid-range)

        sentiment = compute_sentiment(title)
        oracle_score = compute_oracle_score(risk_score, weight)
        prediction = _match_prediction_markets(title, markets)

        item["sentiment"] = sentiment
        item["oracle_score"] = oracle_score
        item["prediction_odds"] = prediction
        item["machine_assessment"] = _build_assessment(oracle_score, sentiment, prediction)

    return news_items


# ---------------------------------------------------------------------------
# Global threat level
# ---------------------------------------------------------------------------

_THREAT_TIERS = [
    (80, "SEVERE",   "#ef4444"),  # red
    (60, "HIGH",     "#f97316"),  # orange
    (40, "ELEVATED", "#eab308"),  # yellow
    (20, "GUARDED",  "#3b82f6"),  # blue
    (0,  "GREEN",    "#22c55e"),  # green
]


def compute_global_threat_level(
    news_items: list[dict],
    markets: list[dict] | None = None,
    military_flights: list[dict] | None = None,
    gps_jamming: list[dict] | None = None,
    ships: list[dict] | None = None,
    correlations: list[dict] | None = None,
) -> dict:
    """Fuse news sentiment, prediction-market conflict odds, event frequency,
    military activity, GPS jamming, and cross-layer correlations into a single
    0-100 threat score.

    Formula (weights sum to 1.0):
        0.25 × negative_sentiment_intensity
        0.25 × conflict_market_avg_probability
        0.10 × high_risk_event_ratio
        0.10 × max_oracle_score (normalised to 0-100)
        0.10 × military_activity_anomaly
        0.10 × gps_jamming_indicator
        0.10 × correlation_alerts
    """
    if not news_items:
        return {"score": 0, "level": "GREEN", "color": "#22c55e", "drivers": []}

    # --- Component 1: negative sentiment intensity (0-100) ---
    neg_scores = [abs(it.get("sentiment", 0)) for it in news_items if (it.get("sentiment") or 0) <= -0.05]
    neg_intensity = (sum(neg_scores) / len(news_items)) * 100 if news_items else 0
    neg_intensity = min(100, neg_intensity * 2.5)  # scale up — avg abs sentiment rarely > 0.4

    # --- Component 2: conflict market avg probability (0-100) ---
    conflict_probs: list[float] = []
    for m in (markets or []):
        if m.get("category") == "CONFLICT":
            pct = m.get("consensus_pct") or m.get("polymarket_pct") or m.get("kalshi_pct")
            if pct is not None:
                conflict_probs.append(float(pct))
    conflict_avg = sum(conflict_probs) / len(conflict_probs) if conflict_probs else 0

    # --- Component 3: high-risk event ratio (0-100) ---
    high_risk = sum(1 for it in news_items if (it.get("risk_score") or 0) >= 7)
    event_ratio = (high_risk / len(news_items)) * 100 if news_items else 0

    # --- Component 4: max oracle score (0-100) ---
    max_oracle = max((it.get("oracle_score") or 0) for it in news_items)
    max_oracle_pct = max_oracle * 10  # 0-10 → 0-100

    # --- Component 5: military activity anomaly (0-100) ---
    mil_count = len(military_flights or [])
    # Baseline: ~20-50 military flights is normal. Spike above 80 is anomalous.
    mil_anomaly = min(100, max(0, (mil_count - 30) * 2)) if mil_count > 30 else 0

    # --- Component 6: GPS jamming indicator (0-100) ---
    jam_zones = gps_jamming or []
    high_jam = sum(1 for z in jam_zones if z.get("severity") == "high")
    med_jam = sum(1 for z in jam_zones if z.get("severity") == "medium")
    jam_score = min(100, high_jam * 25 + med_jam * 10)

    # --- Component 7: cross-layer correlation alerts (0-100) ---
    corr_list: list[dict] = correlations if correlations else []
    corr_points = sum(
        15 if a.get("severity") == "high" else 8 if a.get("severity") == "medium" else 3
        for a in corr_list
    )
    corr_score = min(100, corr_points)

    # --- Weighted fusion ---
    score = (
        0.25 * neg_intensity
        + 0.25 * conflict_avg
        + 0.10 * event_ratio
        + 0.10 * max_oracle_pct
        + 0.10 * mil_anomaly
        + 0.10 * jam_score
        + 0.10 * corr_score
    )
    score = max(0, min(100, round(score)))

    # --- Tier ---
    level, color = "GREEN", "#22c55e"
    for threshold, name, c in _THREAT_TIERS:
        if score >= threshold:
            level, color = name, c
            break

    # --- Drivers (top reasons for current level) ---
    drivers: list[str] = []
    if high_risk:
        drivers.append(f"{high_risk} CRITICAL-tier news item{'s' if high_risk != 1 else ''}")
    if conflict_avg >= 30:
        drivers.append(f"CONFLICT markets avg {conflict_avg:.0f}%")
    if neg_intensity >= 40:
        drivers.append(f"Negative sentiment intensity {neg_intensity:.0f}/100")
    if max_oracle >= 7:
        drivers.append(f"Max oracle score {max_oracle}/10")
    if mil_anomaly >= 30:
        drivers.append(f"Military flight spike: {mil_count} tracked")
    if jam_score >= 25:
        drivers.append(f"GPS jamming: {high_jam} HIGH + {med_jam} MED zones")
    if corr_score >= 15:
        corr_high = sum(1 for a in corr_list if a.get("severity") == "high")
        corr_med = sum(1 for a in corr_list if a.get("severity") == "medium")
        drivers.append(f"Cross-layer correlations: {corr_high} HIGH + {corr_med} MED")
    if not drivers:
        drivers.append("Baseline — no significant threat indicators")

    return {
        "score": score,
        "level": level,
        "color": color,
        "drivers": drivers[:4],
    }


def detect_breaking_events(news_items: list[dict]) -> None:
    """Mark news items as 'breaking' when multiple credible sources converge.

    Criteria: cluster_count >= 3 AND risk_score >= 7.
    Modifies items in-place by setting ``breaking = True``.
    """
    for item in news_items:
        cluster = item.get("cluster_count", 1)
        risk = item.get("risk_score", 0)
        if cluster >= 3 and risk >= 7:
            item["breaking"] = True


# ---------------------------------------------------------------------------
# Region oracle intel (for map entity tooltips)
# ---------------------------------------------------------------------------

_region_cache: dict[str, tuple[float, dict]] = {}  # "lat,lng" -> (timestamp, result)
_REGION_CACHE_TTL = 60  # seconds
_REGION_RADIUS_DEG = 5.0  # ~500km at equator


def get_region_oracle_intel(lat: float, lng: float, news_items: list[dict]) -> dict:
    """Get oracle intelligence summary for a geographic region.

    Finds news items within ~5 degrees, returns top oracle_score item,
    average sentiment, and best market match. Cached on 0.5-degree grid.
    """
    import time

    # Grid-snap for cache key (0.5 degree grid)
    grid_lat = round(lat * 2) / 2
    grid_lng = round(lng * 2) / 2
    cache_key = f"{grid_lat},{grid_lng}"

    now = time.time()
    if cache_key in _region_cache:
        ts, cached_result = _region_cache[cache_key]
        if now - ts < _REGION_CACHE_TTL:
            return cached_result

    # Find nearby news items
    nearby = []
    for item in news_items:
        coords = item.get("coords")
        if not coords or len(coords) < 2:
            continue
        ilat, ilng = coords[0], coords[1]
        if abs(ilat - lat) <= _REGION_RADIUS_DEG and abs(ilng - lng) <= _REGION_RADIUS_DEG:
            nearby.append(item)

    if not nearby:
        result = {"found": False}
        _region_cache[cache_key] = (now, result)
        return result

    # Top oracle score item
    top = max(nearby, key=lambda x: x.get("oracle_score", 0))
    avg_sentiment = sum(it.get("sentiment", 0) for it in nearby) / len(nearby)

    # Best market match from nearby items
    best_market = None
    for it in nearby:
        po = it.get("prediction_odds")
        if po and po.get("consensus_pct") is not None:
            if best_market is None or (po.get("consensus_pct") or 0) > (best_market.get("consensus_pct") or 0):
                best_market = po

    # Oracle tier
    oracle_score = top.get("oracle_score", 0)
    tier = "CRITICAL" if oracle_score >= 7 else "ELEVATED" if oracle_score >= 4 else "ROUTINE"

    result = {
        "found": True,
        "top_headline": top.get("title", ""),
        "oracle_score": oracle_score,
        "tier": tier,
        "avg_sentiment": round(avg_sentiment, 2),
        "nearby_count": len(nearby),
        "market": {
            "title": best_market.get("title", ""),
            "consensus_pct": best_market.get("consensus_pct"),
        } if best_market else None,
    }
    _region_cache[cache_key] = (now, result)
    return result
