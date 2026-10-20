"""Third-party fetchers that phone home to politically/commercially
sensitive upstreams must be operator opt-in only.

Companion to ``test_crowdthreat_opt_in.py`` — extends the same default-off
posture to:

* EUvsDisinfo FIMI (``FIMI_ENABLED``)
* Polymarket + Kalshi (``PREDICTION_MARKETS_ENABLED``)
* Finnhub / yfinance financial data (``FINANCIAL_ENABLED`` /
  ``FINNHUB_API_KEY``)
* NUFORC HuggingFace dataset (``NUFORC_ENABLED``)

Each test asserts that with the env var unset (or set to a falsy value)
the fetcher's network entry point is NOT called.
"""


def _explode(*_args, **_kwargs):
    raise AssertionError("upstream called while fetcher was meant to be disabled")


def test_fimi_disabled_by_default_does_not_call_upstream(monkeypatch):
    from services.fetchers import _store, fimi

    monkeypatch.delenv("FIMI_ENABLED", raising=False)
    monkeypatch.setitem(_store.latest_data, "fimi", [{"id": "old"}])
    monkeypatch.setattr(fimi, "fetch_with_curl", _explode)

    fimi.fetch_fimi()

    assert _store.latest_data["fimi"] == []


def test_fimi_falsy_value_does_not_call_upstream(monkeypatch):
    from services.fetchers import _store, fimi

    monkeypatch.setenv("FIMI_ENABLED", "false")
    monkeypatch.setitem(_store.latest_data, "fimi", [{"id": "old"}])
    monkeypatch.setattr(fimi, "fetch_with_curl", _explode)

    fimi.fetch_fimi()

    assert _store.latest_data["fimi"] == []


def test_prediction_markets_disabled_by_default(monkeypatch):
    from services.fetchers import _store, prediction_markets
    from services import prediction_markets_settings as pm_settings

    monkeypatch.delenv("PREDICTION_MARKETS_ENABLED", raising=False)
    monkeypatch.setattr(pm_settings, "get_prediction_markets_ui_opt_in", lambda: False)
    monkeypatch.setitem(_store.latest_data, "prediction_markets", [{"id": "old"}])
    monkeypatch.setattr(
        prediction_markets, "fetch_prediction_markets_raw", _explode
    )

    prediction_markets.fetch_prediction_markets()

    assert _store.latest_data["prediction_markets"] == []


def test_financial_disabled_when_no_optin_or_api_key(monkeypatch):
    """yfinance fallback path must not run silently — needs FINANCIAL_ENABLED."""
    from services.fetchers import _store, financial

    monkeypatch.delenv("FINANCIAL_ENABLED", raising=False)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.setitem(_store.latest_data, "financial", {"BTC": {"price": 1}})
    monkeypatch.setattr(financial, "_fetch_finnhub_quote", _explode)
    monkeypatch.setattr(financial, "_fetch_yfinance_single", _explode)

    financial.fetch_financial_markets()

    assert _store.latest_data["financial"] == {}


def test_financial_enabled_via_finnhub_api_key(monkeypatch):
    """Presence of FINNHUB_API_KEY counts as explicit opt-in."""
    from services.fetchers import financial

    monkeypatch.delenv("FINANCIAL_ENABLED", raising=False)
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")

    assert financial.financial_fetch_enabled() is True


def test_nuforc_disabled_by_default_skips_download(monkeypatch):
    from services.fetchers import nuforc_enrichment

    monkeypatch.delenv("NUFORC_ENABLED", raising=False)
    monkeypatch.setattr(nuforc_enrichment, "fetch_with_curl", _explode)

    result = nuforc_enrichment._download_and_build()

    assert result is None


def test_news_default_on_but_killable(monkeypatch):
    """News defaults on (kill switch only), but NEWS_ENABLED=false must disable it."""
    from services.fetchers import _store, news

    monkeypatch.setenv("NEWS_ENABLED", "false")
    monkeypatch.setitem(_store.latest_data, "news", [{"id": "old"}])
    monkeypatch.setattr(news, "fetch_with_curl", _explode)

    news.fetch_news()

    assert _store.latest_data["news"] == []
