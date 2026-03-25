"""Financial data fetchers -- defense stocks and oil prices.

Uses yfinance batch download to minimise Yahoo Finance requests and avoid rate limiting.
Falls back to Stooq CSV for oil futures when yfinance returns no data.
"""
import logging
import io
import time
from urllib.request import urlopen

import yfinance as yf
import pandas as pd
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.fetchers.retry import with_retry

logger = logging.getLogger(__name__)


def _batch_fetch(symbols: list[str], period: str = "5d") -> dict:
    """Fetch multiple tickers in a single yfinance request. Returns {symbol: {price, change_percent, up}}."""
    try:
        hist = yf.download(symbols, period=period, auto_adjust=True, progress=False)
        if hist.empty:
            return {}
        close = hist["Close"]
        result = {}
        for sym in symbols:
            try:
                col = close[sym] if len(symbols) > 1 else close
                col = col.dropna()
                if len(col) < 1:
                    continue
                current = float(col.iloc[-1])
                prev = float(col.iloc[0]) if len(col) > 1 else current
                change = ((current - prev) / prev * 100) if prev else 0
                result[sym] = {
                    "price": round(current, 2),
                    "change_percent": round(change, 2),
                    "up": bool(change >= 0),
                }
            except Exception as e:
                logger.warning(f"Could not parse {sym}: {e}")
        return result
    except Exception as e:
        logger.warning(f"Batch fetch failed: {e}")
        return {}


def _fetch_stooq_oil(ticker: str) -> dict | None:
    """Fetch a single oil future from Stooq CSV as fallback."""
    stooq_sym = ticker.replace("=", ".").lower()  # CL=F -> cl.f
    url = f"https://stooq.com/q/l/?s={stooq_sym}&f=sd2t2ohlcv&h&e=csv"
    try:
        raw = urlopen(url, timeout=15).read().decode("utf-8")
        df = pd.read_csv(io.StringIO(raw), on_bad_lines="skip")
        if df.empty or "Close" not in df.columns:
            return None
        close_val = df["Close"].dropna()
        if close_val.empty or str(close_val.iloc[-1]).strip() == "N/D":
            return None
        price = float(close_val.iloc[-1])
        open_val = float(df["Open"].iloc[-1]) if "Open" in df.columns else price
        change = ((price - open_val) / open_val * 100) if open_val else 0
        return {"price": round(price, 2), "change_percent": round(change, 2), "up": bool(change >= 0)}
    except Exception as e:
        logger.warning(f"Stooq oil fallback failed for {ticker}: {e}")
        return None


_STOCK_TICKERS = ["RTX", "LMT", "NOC", "GD", "BA", "PLTR"]
_OIL_MAP = {"WTI Crude": "CL=F", "Brent Crude": "BZ=F"}
_ALL_TICKERS = _STOCK_TICKERS + list(_OIL_MAP.values())

_MARKET_COOLDOWN_SECONDS = 1800  # fetch at most once every 30 minutes
_last_market_fetch: float = 0.0


def _fetch_all_market_data():
    """Single yfinance download for all market tickers to avoid rate limiting."""
    raw = _batch_fetch(_ALL_TICKERS, period="5d")
    stocks = {sym: raw[sym] for sym in _STOCK_TICKERS if sym in raw}
    oil = {name: raw[sym] for name, sym in _OIL_MAP.items() if sym in raw}
    # Stooq fallback for any missing oil tickers
    for name, sym in _OIL_MAP.items():
        if name not in oil:
            fallback = _fetch_stooq_oil(sym)
            if fallback:
                oil[name] = fallback
                logger.info(f"Stooq fallback: {name}=${fallback['price']}")
    return stocks, oil


@with_retry(max_retries=2, base_delay=10)
def fetch_defense_stocks():
    global _last_market_fetch
    if time.time() - _last_market_fetch < _MARKET_COOLDOWN_SECONDS:
        return
    try:
        stocks, oil = _fetch_all_market_data()
        if stocks:
            _last_market_fetch = time.time()
            with _data_lock:
                latest_data['stocks'] = stocks
                if oil:
                    latest_data['oil'] = oil
            _mark_fresh("stocks")
            if oil:
                _mark_fresh("oil")
            logger.info(f"Markets: {len(stocks)} stocks, {len(oil)} oil tickers")
        else:
            logger.warning("Markets: empty result from yfinance (rate limited?)")
    except Exception as e:
        logger.error(f"Error fetching market data: {e}")


@with_retry(max_retries=1, base_delay=10)
def fetch_oil_prices():
    # Oil is now fetched together with stocks in fetch_defense_stocks to use a single request.
    # This function is kept for scheduler compatibility but is a no-op if stocks already ran.
    with _data_lock:
        if latest_data.get('oil'):
            return  # Already populated by fetch_defense_stocks
    try:
        _, oil = _fetch_all_market_data()
        if oil:
            with _data_lock:
                latest_data['oil'] = oil
            _mark_fresh("oil")
    except Exception as e:
        logger.error(f"Error fetching oil: {e}")
