"""Finnhub scheduled fetcher — congress trades, insider transactions, defense quotes.

Runs on a 15-minute schedule and stores results in latest_data["unusual_whales"].
Also updates latest_data["stocks"] with Finnhub quotes (replaces yfinance for defense tickers).
Falls back gracefully if no API key is configured.
"""

import logging
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.fetchers.retry import with_retry

logger = logging.getLogger(__name__)


@with_retry(max_retries=1, base_delay=2)
def fetch_unusual_whales():
    """Fetch congress trades, insider txns, and defense quotes from Finnhub."""
    import os

    if not os.environ.get("FINNHUB_API_KEY", "").strip():
        logger.debug("FINNHUB_API_KEY not set — skipping scheduled fetch.")
        return

    from services.unusual_whales_connector import (
        fetch_congress_trades,
        fetch_insider_transactions,
        fetch_defense_quotes,
        FinnhubConnectorError,
    )

    result: dict = {}

    # Defense stock quotes (also populates latest_data["stocks"])
    try:
        quotes = fetch_defense_quotes()
        if quotes:
            result["quotes"] = quotes
            # Mirror into stocks for backward compat with existing MarketsPanel fallback
            with _data_lock:
                latest_data["stocks"] = quotes
            _mark_fresh("stocks")
    except FinnhubConnectorError as e:
        logger.warning(f"Finnhub quotes fetch failed: {e.detail}")
    except Exception as e:
        logger.warning(f"Finnhub quotes fetch error: {e}")

    # Congress trades
    try:
        congress = fetch_congress_trades()
        result["congress_trades"] = congress.get("trades", [])
    except FinnhubConnectorError as e:
        logger.warning(f"Finnhub congress trades fetch failed: {e.detail}")
    except Exception as e:
        logger.warning(f"Finnhub congress trades fetch error: {e}")

    # Insider transactions
    try:
        insiders = fetch_insider_transactions()
        result["insider_transactions"] = insiders.get("transactions", [])
    except FinnhubConnectorError as e:
        logger.warning(f"Finnhub insider fetch failed: {e.detail}")
    except Exception as e:
        logger.warning(f"Finnhub insider fetch error: {e}")

    if not result:
        logger.warning("Finnhub update produced no data; keeping previous cache.")
        return

    with _data_lock:
        latest_data["unusual_whales"] = result
    _mark_fresh("unusual_whales")
    logger.info(
        f"Finnhub updated: {len(result.get('congress_trades', []))} congress, "
        f"{len(result.get('insider_transactions', []))} insider, "
        f"{len(result.get('quotes', {}))} quotes"
    )
