"""Prediction market fetcher — Polymarket (Gamma API) + Kalshi.

Fetches active prediction market events from both platforms, merges them by
topic similarity, classifies into categories, and stores merged odds with
full metadata (volume, end dates, descriptions, source badges).
"""

import json
import logging
import math
import os
import threading
import time
from urllib.parse import urlencode
from cachetools import TTLCache, cached

logger = logging.getLogger("services.data_fetcher")

# Delta tracking: {market_title: previous_consensus_pct}
_prev_probabilities: dict[str, float] = {}
_market_cache = TTLCache(maxsize=1, ttl=300)
_POLYMARKET_PAGE_DELAY_S = float(os.environ.get("MESH_POLYMARKET_PAGE_DELAY_S", "0.02"))
_KALSHI_PAGE_DELAY_S = float(os.environ.get("MESH_KALSHI_PAGE_DELAY_S", "0.08"))
_provider_pace_lock = threading.Lock()
_provider_last_request_at: dict[str, float] = {}


def _pace_provider(provider: str, min_interval_s: float) -> None:
    if min_interval_s <= 0:
        return
    with _provider_pace_lock:
        now = time.monotonic()
        wait_s = min_interval_s - (now - _provider_last_request_at.get(provider, 0.0))
        if wait_s > 0:
            time.sleep(wait_s)
            now = time.monotonic()
        _provider_last_request_at[provider] = now


def _finite_or_none(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None

# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------
CATEGORIES = ["POLITICS", "CONFLICT", "NEWS", "FINANCE", "CRYPTO", "SPORTS"]

_KALSHI_CATEGORY_MAP = {
    "Politics": "POLITICS",
    "World": "NEWS",
    "Economics": "FINANCE",
    "Financials": "FINANCE",
    "Tech": "FINANCE",
    "Science": "NEWS",
    "Climate and Weather": "NEWS",
    "Sports": "SPORTS",
    "Culture": "NEWS",
}

_TAG_CATEGORY_MAP = {
    "Politics": "POLITICS",
    "Elections": "POLITICS",
    "US Politics": "POLITICS",
    "Trump": "POLITICS",
    "Congress": "POLITICS",
    "Supreme Court": "POLITICS",
    "Geopolitics": "CONFLICT",
    "War": "CONFLICT",
    "Military": "CONFLICT",
    "Finance": "FINANCE",
    "Stocks": "FINANCE",
    "Economy": "FINANCE",
    "Business": "FINANCE",
    "IPOs": "FINANCE",
    "Crypto": "CRYPTO",
    "Bitcoin": "CRYPTO",
    "Ethereum": "CRYPTO",
    "AI": "NEWS",
    "Science": "NEWS",
    "Sports": "SPORTS",
    "NBA": "SPORTS",
    "NFL": "SPORTS",
    "MLB": "SPORTS",
    "NHL": "SPORTS",
    "Soccer": "SPORTS",
    "Tennis": "SPORTS",
    "Golf": "SPORTS",
    "Culture": "NEWS",
    "Entertainment": "NEWS",
    "Tech": "FINANCE",
}

_KEYWORD_CATEGORIES = {
    "CONFLICT": [
        "war",
        "military",
        "attack",
        "missile",
        "invasion",
        "ukraine",
        "russia",
        "gaza",
        "israel",
        "nato",
        "troops",
        "bombing",
        "nuclear",
        "sanctions",
        "ceasefire",
        "houthi",
        "iran",
        "china taiwan",
        "clash",
        "conflict",
        "strike",
        "weapon",
    ],
    "POLITICS": [
        "trump",
        "biden",
        "election",
        "congress",
        "senate",
        "governor",
        "president",
        "democrat",
        "republican",
        "vote",
        "party",
        "cabinet",
        "impeach",
        "legislation",
        "scotus",
        "poll",
        "vance",
        "speaker",
        "parliament",
        "prime minister",
        "macron",
        "starmer",
    ],
    "CRYPTO": [
        "bitcoin",
        "btc",
        "ethereum",
        "eth",
        "crypto",
        "blockchain",
        "solana",
        "defi",
        "nft",
        "binance",
        "coinbase",
        "token",
        "microstrategy",
        "stablecoin",
    ],
    "FINANCE": [
        "stock",
        "fed",
        "interest rate",
        "inflation",
        "gdp",
        "recession",
        "s&p",
        "nasdaq",
        "dow",
        "oil",
        "gold",
        "treasury",
        "tariff",
        "ipo",
        "earnings",
        "market cap",
        "revenue",
    ],
    "SPORTS": [
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "wnba",
        "soccer",
        "football",
        "basketball",
        "baseball",
        "hockey",
        "ufc",
        "mma",
        "tennis",
        "golf",
        "championship",
        "playoffs",
        "world cup",
        "super bowl",
    ],
}


def _classify_category(title: str, poly_tags: list[str], kalshi_category: str) -> str:
    """Classify a market into one of the 5 categories."""
    # 1. Kalshi native category
    if kalshi_category:
        mapped = _KALSHI_CATEGORY_MAP.get(kalshi_category)
        if mapped:
            return mapped
    # 2. Polymarket tag labels
    for tag in poly_tags:
        mapped = _TAG_CATEGORY_MAP.get(tag)
        if mapped:
            return mapped
    # 3. Keyword matching
    title_lower = title.lower()
    for cat, keywords in _KEYWORD_CATEGORIES.items():
        for kw in keywords:
            if kw in title_lower:
                return cat
    # 4. Default
    return "NEWS"


def _polymarket_event_to_entry(ev: dict) -> dict | None:
    title = ev.get("title", "")
    if not title:
        return None

    markets = ev.get("markets", [])
    best_pct = None
    total_volume = 0
    outcomes = []
    for m in markets:
        raw_op = m.get("outcomePrices")
        price = None
        try:
            op = json.loads(raw_op) if isinstance(raw_op, str) else raw_op
            if isinstance(op, list) and len(op) >= 1:
                price = _finite_or_none(op[0])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        if price is None:
            price = _finite_or_none(m.get("lastTradePrice") or m.get("bestBid"))
        pct = None
        if price is not None:
            try:
                pct = round(price * 100, 1)
                if best_pct is None or pct > best_pct:
                    best_pct = pct
            except (ValueError, TypeError):
                pass
        volume = _finite_or_none(m.get("volume", 0) or 0)
        if volume is not None:
            total_volume += volume
        oname = m.get("groupItemTitle") or ""
        if oname and pct is not None:
            outcomes.append({"name": oname, "pct": pct})

    if len(outcomes) > 2:
        outcomes.sort(key=lambda x: x["pct"], reverse=True)
    else:
        outcomes = []

    tag_labels = [t.get("label", "") for t in ev.get("tags", []) if t.get("label")]
    return {
        "title": title,
        "source": "polymarket",
        "pct": best_pct,
        "slug": ev.get("slug", ""),
        "description": ev.get("description") or "",
        "end_date": ev.get("endDate"),
        "volume": round(total_volume, 2),
        "volume_24h": round(_finite_or_none(ev.get("volume24hr", 0) or 0) or 0, 2),
        "tags": tag_labels,
        "outcomes": outcomes,
    }


def _kalshi_market_pct(m: dict) -> float | None:
    bid = _finite_or_none(m.get("yes_bid_dollars"))
    ask = _finite_or_none(m.get("yes_ask_dollars"))
    last = _finite_or_none(m.get("last_price_dollars"))
    if bid is not None and ask is not None and ask >= bid:
        return round(((bid + ask) / 2) * 100, 1)
    if last is not None:
        return round(last * 100, 1)
    cents = _finite_or_none(m.get("yes_price") or m.get("last_price"))
    if cents is None:
        return None
    return round(cents * 100, 1) if cents <= 1 else round(cents, 1)


def _kalshi_market_volume(m: dict) -> float:
    for key in ("volume_24h_fp", "volume_fp", "dollar_volume", "volume"):
        value = _finite_or_none(m.get(key))
        if value is not None:
            return value
    return 0


def _kalshi_market_category(m: dict) -> str:
    text = " ".join(
        str(m.get(k, "") or "")
        for k in ("ticker", "event_ticker", "mve_collection_ticker", "title", "yes_sub_title", "no_sub_title")
    ).lower()
    if any(token in text for token in ("sports", "xnba", "xnfl", "xmlb", "xnhl", "soccer", "tennis", "golf")):
        return "Sports"
    return str(m.get("category", "") or "")


def _kalshi_event_to_entry(ev: dict, markets: list[dict] | None = None) -> dict | None:
    title = ev.get("title", "")
    if not title:
        return None

    markets = markets or ev.get("markets", []) or []
    best_pct = None
    total_volume = 0.0
    close_dates = []
    outcomes = []
    first_ticker = ""
    descriptions = []
    for m in markets:
        first_ticker = first_ticker or m.get("ticker", "")
        pct = _kalshi_market_pct(m)
        if pct is not None:
            if best_pct is None or pct > best_pct:
                best_pct = pct
            oname = m.get("yes_sub_title") or m.get("sub_title") or m.get("title") or ""
            if oname and oname != title:
                outcomes.append({"name": oname, "pct": pct})
        total_volume += _kalshi_market_volume(m)
        cd = m.get("close_time") or m.get("close_date") or m.get("expiration_time")
        if cd:
            close_dates.append(cd)
        desc = (m.get("rules_primary") or m.get("rules_secondary") or "").strip()
        if desc:
            descriptions.append(desc)

    if len(outcomes) > 2:
        outcomes.sort(key=lambda x: x["pct"], reverse=True)
    else:
        outcomes = []

    desc = (ev.get("settle_details") or ev.get("underlying") or "").strip()
    if not desc and descriptions:
        desc = descriptions[0]

    return {
        "title": title,
        "source": "kalshi",
        "pct": best_pct,
        "ticker": first_ticker or ev.get("event_ticker", "") or ev.get("ticker", ""),
        "description": desc,
        "sub_title": ev.get("sub_title", ""),
        "end_date": max(close_dates) if close_dates else None,
        "volume": round(total_volume, 2),
        "category": ev.get("category", ""),
        "outcomes": outcomes,
    }


def _kalshi_market_to_entry(m: dict) -> dict | None:
    title = m.get("title") or m.get("yes_sub_title") or ""
    if not title:
        return None
    pct = _kalshi_market_pct(m)
    volume = _kalshi_market_volume(m)
    desc = (m.get("rules_primary") or m.get("rules_secondary") or "").strip()
    end_date = m.get("close_time") or m.get("expiration_time") or m.get("expected_expiration_time")
    return {
        "title": title,
        "source": "kalshi",
        "pct": pct,
        "ticker": m.get("ticker", "") or m.get("event_ticker", ""),
        "description": desc,
        "sub_title": m.get("subtitle", ""),
        "end_date": end_date,
        "volume": round(volume, 2),
        "category": _kalshi_market_category(m),
        "outcomes": [],
    }


# ---------------------------------------------------------------------------
# Polymarket
# ---------------------------------------------------------------------------
def _fetch_polymarket_events() -> list[dict]:
    """Fetch active events from Polymarket Gamma API (no auth required).

    Fetches paginated active events, bounded by MESH_POLYMARKET_MAX_EVENTS
    so boot-time refresh does not become unbounded.
    """
    from services.network_utils import fetch_with_curl

    all_events = []
    page_size = 250
    max_events = int(os.environ.get("MESH_POLYMARKET_MAX_EVENTS", "5000"))
    for offset in range(0, max_events, page_size):
        try:
            _pace_provider("polymarket", _POLYMARKET_PAGE_DELAY_S)
            resp = fetch_with_curl(
                f"https://gamma-api.polymarket.com/events?active=true&closed=false&limit={page_size}&offset={offset}",
                timeout=15,
            )
            if not resp or resp.status_code != 200:
                break
            page = resp.json()
            if not isinstance(page, list) or not page:
                break
            all_events.extend(page)
            if len(page) < page_size:
                break
        except Exception as e:
            logger.warning(f"Polymarket page offset={offset} error: {e}")
            break

    if not all_events:
        return []

    try:
        results = []
        for ev in all_events:
            title = ev.get("title", "")
            if not title:
                continue
            # Extract best probability + outcomes from markets
            markets = ev.get("markets", [])
            best_pct = None
            total_volume = 0
            outcomes = []
            for m in markets:
                # Use outcomePrices[0] (Yes price) when available — lastTradePrice
                # can be for either Yes or No side, causing "99%" for unlikely events
                raw_op = m.get("outcomePrices")
                price = None
                try:
                    op = json.loads(raw_op) if isinstance(raw_op, str) else raw_op
                    if isinstance(op, list) and len(op) >= 1:
                        price = _finite_or_none(op[0])
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass
                if price is None:
                    price = _finite_or_none(m.get("lastTradePrice") or m.get("bestBid"))
                pct = None
                if price is not None:
                    try:
                        pct = round(price * 100, 1)
                        if best_pct is None or pct > best_pct:
                            best_pct = pct
                    except (ValueError, TypeError):
                        pass
                try:
                    volume = _finite_or_none(m.get("volume", 0) or 0)
                    if volume is not None:
                        total_volume += volume
                except (ValueError, TypeError):
                    pass
                # Collect named outcomes for multi-outcome events
                oname = m.get("groupItemTitle") or ""
                if oname and pct is not None:
                    outcomes.append({"name": oname, "pct": pct})
            # Only keep outcomes for multi-outcome markets (3+ named outcomes)
            if len(outcomes) > 2:
                outcomes.sort(key=lambda x: x["pct"], reverse=True)
            else:
                outcomes = []

            # Extract tag labels
            tag_labels = [t.get("label", "") for t in ev.get("tags", []) if t.get("label")]

            results.append(
                {
                    "title": title,
                    "source": "polymarket",
                    "pct": best_pct,
                    "slug": ev.get("slug", ""),
                    "description": ev.get("description") or "",
                    "end_date": ev.get("endDate"),
                    "volume": round(total_volume, 2),
                    "volume_24h": round(_finite_or_none(ev.get("volume24hr", 0) or 0) or 0, 2),
                    "tags": tag_labels,
                    "outcomes": outcomes,
                }
            )
        logger.info(f"Polymarket: fetched {len(results)} active events")
        return results
    except Exception as e:
        logger.error(f"Polymarket fetch error: {e}")
        return []


# ---------------------------------------------------------------------------
# Kalshi
# ---------------------------------------------------------------------------
def _fetch_kalshi_events() -> list[dict]:
    """Fetch active events from Kalshi public API (no auth required)."""
    from services.network_utils import fetch_with_curl

    try:
        max_events = int(os.environ.get("MESH_KALSHI_MAX_EVENTS", "2000"))
        page_size = 200
        markets = []
        cursor = ""
        while len(markets) < max_events:
            params = {"status": "open", "limit": str(page_size)}
            if cursor:
                params["cursor"] = cursor
            _pace_provider("kalshi", _KALSHI_PAGE_DELAY_S)
            resp = fetch_with_curl(
                f"https://api.elections.kalshi.com/trade-api/v2/markets?{urlencode(params)}",
                timeout=15,
            )
            if not resp or resp.status_code != 200:
                break
            data = resp.json()
            page = data.get("markets", []) if isinstance(data, dict) else []
            if not page:
                break
            markets.extend(page)
            cursor = data.get("cursor") or ""
            if not cursor or len(page) < page_size:
                break

        results = []
        for market in markets:
            entry = _kalshi_market_to_entry(market)
            if entry:
                results.append(entry)
        if results:
            logger.info(f"Kalshi: fetched {len(results)} active events from v2")
            return results
    except Exception as e:
        logger.warning(f"Kalshi v2 fetch error, falling back to legacy v1: {e}")

    try:
        resp = fetch_with_curl(
            "https://api.elections.kalshi.com/v1/events?status=open&limit=100",
            timeout=15,
        )
        if not resp or resp.status_code != 200:
            logger.warning(f"Kalshi API returned {getattr(resp, 'status_code', 'N/A')}")
            return []
        data = resp.json()
        events = data.get("events", []) if isinstance(data, dict) else []

        results = []
        for ev in events:
            title = ev.get("title", "")
            if not title:
                continue
            markets = ev.get("markets", [])
            best_pct = None
            total_volume = 0
            close_dates = []
            outcomes = []
            for m in markets:
                price = m.get("yes_price") or m.get("last_price")
                pct = None
                if price is not None:
                    try:
                        price = _finite_or_none(price)
                        if price is None:
                            raise ValueError("non-finite")
                        pct = round(price, 1)
                        if pct <= 1:
                            pct = round(pct * 100, 1)
                        if best_pct is None or pct > best_pct:
                            best_pct = pct
                    except (ValueError, TypeError):
                        pass
                try:
                        volume = _finite_or_none(
                            m.get("dollar_volume", 0) or m.get("volume", 0) or 0
                        )
                        if volume is not None:
                            total_volume += int(volume)
                except (ValueError, TypeError):
                    pass
                cd = m.get("close_date")
                if cd:
                    close_dates.append(cd)
                # Collect named outcomes for multi-outcome events
                oname = m.get("title") or m.get("subtitle", "")
                if oname and pct is not None:
                    outcomes.append({"name": oname, "pct": pct})
            # Only keep outcomes for multi-outcome markets (3+ named outcomes)
            if len(outcomes) > 2:
                outcomes.sort(key=lambda x: x["pct"], reverse=True)
            else:
                outcomes = []

            # Description: settle_details or underlying
            desc = (ev.get("settle_details") or ev.get("underlying") or "").strip()
            sub = ev.get("sub_title", "")

            results.append(
                {
                    "title": title,
                    "source": "kalshi",
                    "pct": best_pct,
                    "ticker": ev.get("ticker", ""),
                    "description": desc,
                    "sub_title": sub,
                    "end_date": max(close_dates) if close_dates else None,
                    "volume": total_volume,
                    "category": ev.get("category", ""),
                    "outcomes": outcomes,
                }
            )
        logger.info(f"Kalshi: fetched {len(results)} active events")
        return results
    except Exception as e:
        logger.error(f"Kalshi fetch error: {e}")
        return []


# ---------------------------------------------------------------------------
# Merge + classify
# ---------------------------------------------------------------------------
def _jaccard(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _merge_markets(poly_events: list[dict], kalshi_events: list[dict]) -> list[dict]:
    """Merge Polymarket and Kalshi events by title similarity.

    Returns a unified list with full metadata, categorized.
    """
    merged = []
    used_kalshi = set()

    for pe in poly_events:
        best_match = None
        best_score = 0.0
        for i, ke in enumerate(kalshi_events):
            if i in used_kalshi:
                continue
            score = _jaccard(pe["title"], ke["title"])
            if score > best_score and score >= 0.25:
                best_score = score
                best_match = (i, ke)

        poly_pct = _finite_or_none(pe.get("pct"))
        kalshi_pct = None
        kalshi_vol = 0
        kalshi_cat = ""
        kalshi_end = None
        kalshi_desc = ""
        kalshi_ticker = ""

        if best_match:
            used_kalshi.add(best_match[0])
            ke = best_match[1]
            kalshi_pct = _finite_or_none(ke.get("pct"))
            kalshi_vol = _finite_or_none(ke.get("volume", 0)) or 0
            kalshi_cat = ke.get("category", "")
            kalshi_end = ke.get("end_date")
            kalshi_desc = ke.get("description", "")
            kalshi_ticker = ke.get("ticker", "")

        pcts = [p for p in [poly_pct, kalshi_pct] if p is not None]
        consensus = round(sum(pcts) / len(pcts), 1) if pcts else None

        # Build sources list
        sources = []
        if poly_pct is not None:
            sources.append({"name": "POLY", "pct": poly_pct})
        if kalshi_pct is not None:
            sources.append({"name": "KALSHI", "pct": kalshi_pct})

        category = _classify_category(pe["title"], pe.get("tags", []), kalshi_cat)

        # Use best available description
        desc = pe.get("description", "") or kalshi_desc
        end_date = pe.get("end_date") or kalshi_end

        # Use whichever source has more outcomes
        poly_outcomes = pe.get("outcomes", [])
        kalshi_outcomes = best_match[1].get("outcomes", []) if best_match else []
        outcomes = poly_outcomes if len(poly_outcomes) >= len(kalshi_outcomes) else kalshi_outcomes

        merged.append(
            {
                "title": pe["title"],
                "polymarket_pct": poly_pct,
                "kalshi_pct": kalshi_pct,
                "consensus_pct": consensus,
                "description": desc,
                "end_date": end_date,
                "volume": _finite_or_none(pe.get("volume", 0)) or 0,
                "volume_24h": _finite_or_none(pe.get("volume_24h", 0)) or 0,
                "kalshi_volume": kalshi_vol,
                "category": category,
                "sources": sources,
                "slug": pe.get("slug", ""),
                "kalshi_ticker": kalshi_ticker,
                "outcomes": outcomes,
            }
        )

    # Unmatched Kalshi events
    for i, ke in enumerate(kalshi_events):
        if i in used_kalshi:
            continue
        pct = _finite_or_none(ke.get("pct"))
        sources = []
        if pct is not None:
            sources.append({"name": "KALSHI", "pct": pct})
        category = _classify_category(ke["title"], [], ke.get("category", ""))
        merged.append(
            {
                "title": ke["title"],
                "polymarket_pct": None,
                "kalshi_pct": pct,
                "consensus_pct": pct,
                "description": ke.get("description", ""),
                "end_date": ke.get("end_date"),
                "volume": 0,
                "volume_24h": 0,
                "kalshi_volume": _finite_or_none(ke.get("volume", 0)) or 0,
                "category": category,
                "sources": sources,
                "slug": "",
                "kalshi_ticker": ke.get("ticker", ""),
                "outcomes": ke.get("outcomes", []),
            }
        )

    return merged


@cached(_market_cache)
def fetch_prediction_markets_raw() -> list[dict]:
    """Fetch and merge prediction markets from both sources. Cached 5 min."""
    poly = _fetch_polymarket_events()
    kalshi = _fetch_kalshi_events()
    merged = _merge_markets(poly, kalshi)
    logger.info(
        f"Prediction markets: {len(merged)} merged events "
        f"({len(poly)} Polymarket, {len(kalshi)} Kalshi)"
    )
    return merged


def fetch_prediction_markets():
    """Fetcher entry point — writes merged markets to latest_data."""
    from services.fetchers._store import latest_data, _data_lock, _mark_fresh
    global _prev_probabilities

    markets = fetch_prediction_markets_raw()

    # Compute probability deltas vs previous fetch
    new_probs: dict[str, float] = {}
    for m in markets:
        title = m.get("title", "")
        pct = m.get("consensus_pct")
        if title and pct is not None:
            prev = _prev_probabilities.get(title)
            if prev is not None:
                m["delta_pct"] = round(pct - prev, 1)
            else:
                m["delta_pct"] = None
            new_probs[title] = pct
        else:
            m["delta_pct"] = None
    _prev_probabilities = new_probs

    # Build trending list (top 10 by absolute delta)
    trending = sorted(
        [m for m in markets if m.get("delta_pct") is not None and m["delta_pct"] != 0],
        key=lambda x: abs(x["delta_pct"]),
        reverse=True,
    )[:10]

    with _data_lock:
        latest_data["prediction_markets"] = markets
        latest_data["trending_markets"] = trending
    _mark_fresh("prediction_markets")


# ---------------------------------------------------------------------------
# Direct API search (not limited to cached data)
# ---------------------------------------------------------------------------
def search_polymarket_direct(query: str, limit: int = 20, offset: int = 0) -> list[dict]:
    """Search Polymarket by scanning API pages for title matches.

    Prefer Polymarket's public search endpoint, then fall back to scanning
    Gamma event pages if search is unavailable.
    """
    from services.network_utils import fetch_with_curl

    q_lower = query.lower()
    q_words = set(q_lower.split())
    results = []

    try:
        params = urlencode({"q": query, "limit": str(limit), "offset": str(max(0, offset))})
        _pace_provider("polymarket", _POLYMARKET_PAGE_DELAY_S)
        resp = fetch_with_curl(
            f"https://gamma-api.polymarket.com/public-search?{params}",
            timeout=15,
        )
        if resp and resp.status_code == 200:
            data = resp.json()
            events = data.get("events", []) if isinstance(data, dict) else []
            for ev in events:
                if ev.get("closed") or ev.get("active") is False:
                    continue
                entry = _polymarket_event_to_entry(ev)
                if not entry:
                    continue
                category = _classify_category(entry["title"], entry.get("tags", []), "")
                pct = _finite_or_none(entry.get("pct"))
                sources = [{"name": "POLY", "pct": pct}] if pct is not None else []
                results.append(
                    {
                        "title": entry["title"],
                        "polymarket_pct": pct,
                        "kalshi_pct": None,
                        "consensus_pct": pct,
                        "description": entry.get("description", ""),
                        "end_date": entry.get("end_date"),
                        "volume": entry.get("volume", 0),
                        "volume_24h": entry.get("volume_24h", 0),
                        "kalshi_volume": 0,
                        "category": category,
                        "sources": sources,
                        "slug": entry.get("slug", ""),
                        "outcomes": entry.get("outcomes", []),
                    }
                )
            logger.info(f"Polymarket search '{query}': {len(results)} results via public-search")
            return results[:limit]
    except Exception as e:
        logger.warning(f"Polymarket public-search '{query}' error: {e}")

    # Scan up to 2000 events (10 pages of 200) looking for title matches
    for scan_offset in range(0, 3000, 200):
        try:
            _pace_provider("polymarket", _POLYMARKET_PAGE_DELAY_S)
            resp = fetch_with_curl(
                f"https://gamma-api.polymarket.com/events?active=true&closed=false&limit=200&offset={scan_offset}",
                timeout=15,
            )
            if not resp or resp.status_code != 200:
                break
            events = resp.json()
            if not isinstance(events, list) or not events:
                break

            for ev in events:
                title = ev.get("title", "")
                if not title:
                    continue
                title_lower = title.lower()
                # Check if query appears in title or word overlap
                if q_lower not in title_lower and not any(w in title_lower for w in q_words):
                    continue

                # Extract same fields as regular fetch
                markets = ev.get("markets", [])
                best_pct = None
                total_volume = 0
                outcomes = []
                for m in markets:
                    # Use outcomePrices[0] (Yes price) when available
                    raw_op = m.get("outcomePrices")
                    price = None
                    try:
                        op = json.loads(raw_op) if isinstance(raw_op, str) else raw_op
                        if isinstance(op, list) and len(op) >= 1:
                            price = _finite_or_none(op[0])
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
                    if price is None:
                        price = _finite_or_none(m.get("lastTradePrice") or m.get("bestBid"))
                    pct = None
                    if price is not None:
                        try:
                            pct = round(price * 100, 1)
                            if best_pct is None or pct > best_pct:
                                best_pct = pct
                        except (ValueError, TypeError):
                            pass
                    try:
                        volume = _finite_or_none(m.get("volume", 0) or 0)
                        if volume is not None:
                            total_volume += volume
                    except (ValueError, TypeError):
                        pass
                    oname = m.get("groupItemTitle") or ""
                    if oname and pct is not None:
                        outcomes.append({"name": oname, "pct": pct})
                if len(outcomes) > 2:
                    outcomes.sort(key=lambda x: x["pct"], reverse=True)
                else:
                    outcomes = []

                tag_labels = [t.get("label", "") for t in ev.get("tags", []) if t.get("label")]
                category = _classify_category(title, tag_labels, "")
                sources = []
                if best_pct is not None:
                    sources.append({"name": "POLY", "pct": best_pct})

                results.append(
                    {
                        "title": title,
                        "polymarket_pct": best_pct,
                        "kalshi_pct": None,
                        "consensus_pct": best_pct,
                        "description": ev.get("description") or "",
                        "end_date": ev.get("endDate"),
                        "volume": round(total_volume, 2),
                        "volume_24h": round(_finite_or_none(ev.get("volume24hr", 0) or 0) or 0, 2),
                        "kalshi_volume": 0,
                        "category": category,
                        "sources": sources,
                        "slug": ev.get("slug", ""),
                        "outcomes": outcomes,
                    }
                )
            # Stop scanning if we have enough results
            if len(results) >= offset + limit:
                break
        except Exception as e:
            logger.warning(f"Polymarket search scan offset={scan_offset} error: {e}")
            break

    logger.info(f"Polymarket search '{query}': {len(results)} results (scanned API)")
    return results[offset : offset + limit]


def search_kalshi_direct(query: str, limit: int = 20, offset: int = 0) -> list[dict]:
    """Search Kalshi events by scanning API pages for title matches."""
    from services.network_utils import fetch_with_curl

    q_lower = query.lower()
    q_words = set(q_lower.split())
    results = []

    try:
        max_scan = int(os.environ.get("MESH_KALSHI_SEARCH_SCAN_EVENTS", "1200"))
        page_size = 200
        cursor = ""
        scanned = 0
        while scanned < max_scan and len(results) < offset + limit:
            params = {"status": "open", "limit": str(page_size)}
            if cursor:
                params["cursor"] = cursor
            _pace_provider("kalshi", _KALSHI_PAGE_DELAY_S)
            resp = fetch_with_curl(
                f"https://api.elections.kalshi.com/trade-api/v2/markets?{urlencode(params)}",
                timeout=15,
            )
            if not resp or resp.status_code != 200:
                break
            data = resp.json()
            markets = data.get("markets", []) if isinstance(data, dict) else []
            if not markets:
                break
            scanned += len(markets)
            for market in markets:
                haystack = " ".join(
                    str(market.get(k, "") or "")
                    for k in ("title", "yes_sub_title", "no_sub_title", "event_ticker", "ticker")
                ).lower()
                if q_lower not in haystack and not any(w in haystack for w in q_words):
                    continue
                entry = _kalshi_market_to_entry(market)
                if not entry:
                    continue
                pct = _finite_or_none(entry.get("pct"))
                sources = [{"name": "KALSHI", "pct": pct}] if pct is not None else []
                category = _classify_category(entry["title"], [], entry.get("category", ""))
                results.append({
                    "title": entry["title"],
                    "polymarket_pct": None,
                    "kalshi_pct": pct,
                    "consensus_pct": pct,
                    "description": entry.get("description", ""),
                    "end_date": entry.get("end_date"),
                    "volume": 0,
                    "volume_24h": 0,
                    "kalshi_volume": entry.get("volume", 0),
                    "category": category,
                    "sources": sources,
                    "slug": "",
                    "kalshi_ticker": entry.get("ticker", ""),
                    "outcomes": entry.get("outcomes", []),
                })
                if len(results) >= offset + limit:
                    break
            cursor = data.get("cursor") or ""
            if not cursor or len(markets) < page_size:
                break
        if results:
            logger.info(f"Kalshi search '{query}': {len(results)} results via v2 scan")
            return results[offset : offset + limit]
    except Exception as e:
        logger.warning(f"Kalshi v2 search '{query}' error, falling back to legacy v1: {e}")

    try:
        resp = fetch_with_curl(
            "https://api.elections.kalshi.com/v1/events?status=open&limit=200",
            timeout=15,
        )
        if not resp or resp.status_code != 200:
            return []
        data = resp.json()
        events = data.get("events", []) if isinstance(data, dict) else []

        for ev in events:
            title = ev.get("title", "")
            if not title:
                continue
            title_lower = title.lower()
            if q_lower not in title_lower and not any(w in title_lower for w in q_words):
                continue

            markets = ev.get("markets", [])
            best_pct = None
            total_volume = 0
            close_dates = []
            outcomes = []
            for m in markets:
                price = m.get("yes_price") or m.get("last_price")
                pct = None
                if price is not None:
                    try:
                        price = _finite_or_none(price)
                        if price is None:
                            raise ValueError("non-finite")
                        pct = round(price, 1)
                        if pct <= 1:
                            pct = round(pct * 100, 1)
                        if best_pct is None or pct > best_pct:
                            best_pct = pct
                    except (ValueError, TypeError):
                        pass
                try:
                    volume = _finite_or_none(
                        m.get("dollar_volume", 0) or m.get("volume", 0) or 0
                    )
                    if volume is not None:
                        total_volume += int(volume)
                except (ValueError, TypeError):
                    pass
                cd = m.get("close_date")
                if cd:
                    close_dates.append(cd)
                oname = m.get("title") or m.get("subtitle", "")
                if oname and pct is not None:
                    outcomes.append({"name": oname, "pct": pct})
            if len(outcomes) > 2:
                outcomes.sort(key=lambda x: x["pct"], reverse=True)
            else:
                outcomes = []

            desc = (ev.get("settle_details") or ev.get("underlying") or "").strip()
            category = _classify_category(title, [], ev.get("category", ""))
            sources = []
            if best_pct is not None:
                sources.append({"name": "KALSHI", "pct": best_pct})

            results.append({
                "title": title,
                "polymarket_pct": None,
                "kalshi_pct": best_pct,
                "consensus_pct": best_pct,
                "description": desc,
                "end_date": max(close_dates) if close_dates else None,
                "volume": total_volume,
                "volume_24h": 0,
                "kalshi_volume": total_volume,
                "category": category,
                "sources": sources,
                "slug": "",
                "kalshi_ticker": ev.get("ticker", ""),
                "outcomes": outcomes,
            })
            if len(results) >= offset + limit:
                break
    except Exception as e:
        logger.warning(f"Kalshi search '{query}' error: {e}")

    logger.info(f"Kalshi search '{query}': {len(results)} results")
    return results[offset : offset + limit]
