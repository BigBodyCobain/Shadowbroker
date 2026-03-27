"""
Finnhub API connector.

Provides defense stock quotes, congressional trading data, and insider
transactions — all from Finnhub's free tier (60 calls/min).

File kept at this path for git history; the module is referenced as
services.unusual_whales_connector in main.py imports but the public
surface is entirely Finnhub now.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import math
import requests
from cachetools import TTLCache

logger = logging.getLogger(__name__)

_FINNHUB_BASE = "https://finnhub.io/api/v1"
_USER_AGENT = "ShadowBroker/0.9.6 Finnhub connector"
_REQUEST_TIMEOUT = 12
_MIN_INTERVAL_SECONDS = 0.35  # Stay well under 60 calls/min

# Tickers we poll for congress trades & insider activity
WATCHED_TICKERS = [
    "NVDA", "AAPL", "TSLA", "MSFT", "GOOGL", "AMZN", "META",
    "RTX", "LMT", "NOC", "GD", "BA", "PLTR",
]

# Defense + oil tickers for quotes (replaces yfinance)
QUOTE_TICKERS = [
    ("RTX", "RTX"), ("LMT", "LMT"), ("NOC", "NOC"),
    ("GD", "GD"), ("BA", "BA"), ("PLTR", "PLTR"),
]
CRYPTO_TICKERS = [
    ("BTC", "BINANCE:BTCUSDT"),
    ("ETH", "BINANCE:ETHUSDT"),
]

_quote_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=32, ttl=300)
_congress_cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(maxsize=32, ttl=600)
_insider_cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(maxsize=32, ttl=600)

_request_lock = threading.Lock()
_last_request_at = 0.0


class FinnhubConnectorError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


# Keep old name as alias for main.py imports
UWConnectorError = FinnhubConnectorError


def _get_api_key() -> str:
    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not api_key:
        raise FinnhubConnectorError(
            "Finnhub API key not configured. Add FINNHUB_API_KEY in Settings > API Keys (free at finnhub.io).",
            status_code=428,
        )
    return api_key


def _request(path: str, params: dict[str, Any] | None = None) -> Any:
    """Rate-limited GET to Finnhub. Returns parsed JSON."""
    api_key = _get_api_key()
    payload = dict(params or {})
    payload["token"] = api_key

    global _last_request_at
    with _request_lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < _MIN_INTERVAL_SECONDS:
            time.sleep(_MIN_INTERVAL_SECONDS - elapsed)
        try:
            response = requests.get(
                f"{_FINNHUB_BASE}{path}",
                params=payload,
                timeout=_REQUEST_TIMEOUT,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            )
        finally:
            _last_request_at = time.monotonic()

    if response.status_code == 401:
        raise FinnhubConnectorError("Finnhub rejected the API key. Check FINNHUB_API_KEY.", 401)
    if response.status_code == 403:
        raise FinnhubConnectorError(
            "Finnhub returned 403 — this endpoint may require a premium plan.", 403
        )
    if response.status_code == 429:
        raise FinnhubConnectorError(
            "Finnhub rate limit reached (60/min free). Try again shortly.", 429
        )
    if response.status_code >= 400:
        detail = response.text.strip()[:240] or "Unexpected Finnhub API error."
        raise FinnhubConnectorError(f"Finnhub request failed: {detail}", response.status_code)

    try:
        return response.json()
    except ValueError as exc:
        raise FinnhubConnectorError(f"Finnhub returned invalid JSON: {exc}", 502) from exc


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def get_uw_status() -> dict[str, Any]:
    """Status check — kept as get_uw_status for route compatibility."""
    has_key = bool(os.environ.get("FINNHUB_API_KEY", "").strip())
    return {
        "ok": True,
        "configured": has_key,
        "source": "Finnhub",
        "attribution": "Data from Finnhub",
        "mode": "free-tier market intelligence",
        "local_only": True,
    }


# ---------------------------------------------------------------------------
# Stock Quotes
# ---------------------------------------------------------------------------
def fetch_defense_quotes() -> dict[str, dict[str, Any]]:
    """Fetch real-time quotes for defense tickers. Returns {ticker: {...}}."""
    results: dict[str, dict[str, Any]] = {}
    for label, symbol in QUOTE_TICKERS:
        cache_key = f"quote:{symbol}"
        if cache_key in _quote_cache:
            results[label] = _quote_cache[cache_key]
            continue
        try:
            raw = _request("/quote", {"symbol": symbol})
            if raw and raw.get("c"):
                entry = {
                    "price": round(float(raw["c"]), 2),
                    "change_percent": round(float(raw.get("dp") or 0), 2),
                    "up": float(raw.get("dp") or 0) >= 0,
                }
                results[label] = entry
                _quote_cache[cache_key] = entry
        except FinnhubConnectorError:
            logger.warning(f"Finnhub quote failed for {symbol}")
        except Exception as e:
            logger.warning(f"Finnhub quote error for {symbol}: {e}")
    # Crypto quotes via /crypto/candle
    for label, symbol in CRYPTO_TICKERS:
        cache_key = f"quote:{symbol}"
        if cache_key in _quote_cache:
            results[label] = _quote_cache[cache_key]
            continue
        try:
            now = int(time.time())
            raw = _request("/crypto/candle", {
                "symbol": symbol,
                "resolution": "D",
                "from": now - 172800,  # 2 days back
                "to": now,
            })
            closes = raw.get("c") or []
            if len(closes) >= 1:
                current = float(closes[-1])
                prev = float(closes[-2]) if len(closes) >= 2 else current
                change_pct = ((current - prev) / prev * 100) if prev else 0
                if math.isfinite(current) and math.isfinite(change_pct):
                    entry = {
                        "price": round(current, 2),
                        "change_percent": round(change_pct, 2),
                        "up": change_pct >= 0,
                        "crypto": True,
                    }
                    results[label] = entry
                    _quote_cache[cache_key] = entry
        except FinnhubConnectorError:
            logger.warning(f"Finnhub crypto quote failed for {symbol}")
        except Exception as e:
            logger.warning(f"Finnhub crypto quote error for {symbol}: {e}")

    return results


# ---------------------------------------------------------------------------
# Congressional Trading
# ---------------------------------------------------------------------------
def _normalize_congress_trade(raw: dict[str, Any], symbol: str) -> dict[str, Any]:
    amount_from = raw.get("amountFrom") or 0
    amount_to = raw.get("amountTo") or 0
    if amount_from and amount_to:
        amount_range = f"${int(amount_from):,}–${int(amount_to):,}"
    elif amount_to:
        amount_range = f"Up to ${int(amount_to):,}"
    else:
        amount_range = ""
    return {
        "politician_name": str(raw.get("name") or "Unknown"),
        "chamber": str(raw.get("position") or "unknown").lower(),
        "filing_date": str(raw.get("filingDate") or raw.get("transactionDate") or ""),
        "transaction_date": str(raw.get("transactionDate") or ""),
        "ticker": symbol,
        "asset_name": str(raw.get("assetName") or ""),
        "transaction_type": str(raw.get("transactionType") or ""),
        "amount_range": amount_range,
        "owner_type": str(raw.get("ownerType") or ""),
    }


def fetch_congress_trades() -> dict[str, Any]:
    """Fetch congressional trades across watched tickers."""
    all_trades: list[dict[str, Any]] = []
    for symbol in WATCHED_TICKERS:
        cache_key = f"congress:{symbol}"
        if cache_key in _congress_cache:
            all_trades.extend(_congress_cache[cache_key])
            continue
        try:
            raw = _request("/stock/congressional-trading", {"symbol": symbol})
            data = raw.get("data") or []
            if isinstance(data, list):
                normalized = [_normalize_congress_trade(t, symbol) for t in data[:10] if isinstance(t, dict)]
                _congress_cache[cache_key] = normalized
                all_trades.extend(normalized)
        except FinnhubConnectorError as e:
            if e.status_code in (403, 402):
                logger.info(f"Congressional trading endpoint not available on free tier for {symbol}")
                # Cache empty to avoid re-hitting a premium endpoint
                _congress_cache[cache_key] = []
            else:
                logger.warning(f"Finnhub congress fetch failed for {symbol}: {e.detail}")
        except Exception as e:
            logger.warning(f"Finnhub congress error for {symbol}: {e}")

    # Sort by filing date descending
    all_trades.sort(key=lambda t: t.get("filing_date", ""), reverse=True)
    return {
        "ok": True,
        "source": "Finnhub",
        "attribution": "Data from Finnhub",
        "trades": all_trades[:50],
    }


# ---------------------------------------------------------------------------
# Insider Transactions
# ---------------------------------------------------------------------------
def _normalize_insider(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(raw.get("name") or "Unknown"),
        "ticker": str(raw.get("symbol") or ""),
        "share": int(raw.get("share") or 0),
        "change": int(raw.get("change") or 0),
        "filing_date": str(raw.get("filingDate") or ""),
        "transaction_date": str(raw.get("transactionDate") or ""),
        "transaction_code": str(raw.get("transactionCode") or ""),
        "transaction_price": float(raw.get("transactionPrice") or 0),
    }


def fetch_insider_transactions() -> dict[str, Any]:
    """Fetch insider transactions across watched tickers."""
    all_insiders: list[dict[str, Any]] = []
    for symbol in WATCHED_TICKERS:
        cache_key = f"insider:{symbol}"
        if cache_key in _insider_cache:
            all_insiders.extend(_insider_cache[cache_key])
            continue
        try:
            raw = _request("/stock/insider-transactions", {"symbol": symbol})
            data = raw.get("data") or []
            if isinstance(data, list):
                normalized = [_normalize_insider(t) for t in data[:8] if isinstance(t, dict)]
                _insider_cache[cache_key] = normalized
                all_insiders.extend(normalized)
        except FinnhubConnectorError as e:
            logger.warning(f"Finnhub insider fetch failed for {symbol}: {e.detail}")
        except Exception as e:
            logger.warning(f"Finnhub insider error for {symbol}: {e}")

    all_insiders.sort(key=lambda t: t.get("filing_date", ""), reverse=True)
    return {
        "ok": True,
        "source": "Finnhub",
        "attribution": "Data from Finnhub",
        "transactions": all_insiders[:50],
    }


# ---------------------------------------------------------------------------
# Aliases for backward compatibility with main.py imports
# ---------------------------------------------------------------------------
def fetch_darkpool_recent() -> dict[str, Any]:
    """Replaced — now returns insider transactions instead of dark pool."""
    return fetch_insider_transactions()


def fetch_flow_alerts() -> dict[str, Any]:
    """Replaced — now returns defense quotes formatted as alerts."""
    quotes = fetch_defense_quotes()
    return {
        "ok": True,
        "source": "Finnhub",
        "attribution": "Data from Finnhub",
        "alerts": [],
        "quotes": quotes,
    }
