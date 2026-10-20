from __future__ import annotations

import requests

from services import liveuamap_scraper as scraper
from services import liveuamap_settings as settings


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_api_geojson_is_normalized_and_auth_header_is_sent(monkeypatch):
    monkeypatch.setenv("LIVEUAMAP_API_URL", "https://api.example.test/events")
    monkeypatch.setenv("LIVEUAMAP_API_KEY", "secret-key")
    monkeypatch.setenv("LIVEUAMAP_API_TIMEOUT_S", "12")
    monkeypatch.setattr(
        "services.network_utils.outbound_user_agent",
        lambda purpose="": f"operator-test ({purpose})",
    )
    seen = {}

    def fake_get(url, *, headers, timeout, allow_redirects):
        seen.update(url=url, headers=headers, timeout=timeout, allow_redirects=allow_redirects)
        return _Response(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "evt-1",
                        "geometry": {"type": "Point", "coordinates": [30.5, 50.5]},
                        "properties": {"title": "Event", "url": "https://example.test/e/1"},
                    }
                ],
            }
        )

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    markers = scraper._fetch_liveuamap_api()
    assert markers[0]["id"] == "evt-1"
    assert markers[0]["lat"] == 50.5
    assert markers[0]["lng"] == 30.5
    assert markers[0]["provider"] == "api"
    assert seen["headers"]["Authorization"] == "Bearer secret-key"
    assert seen["timeout"] == (5, 12)
    assert seen["allow_redirects"] is False


def test_api_query_token_is_not_exposed_as_marker_fallback(monkeypatch):
    monkeypatch.setenv(
        "LIVEUAMAP_API_URL",
        "https://api.example.test/events?token=super-secret",
    )
    monkeypatch.setattr(
        scraper.requests,
        "get",
        lambda *args, **kwargs: _Response(
            [{"id": "evt", "lat": 10, "lng": 20, "title": "No link"}]
        ),
    )
    markers = scraper._fetch_liveuamap_api()
    assert markers[0]["link"] == "https://liveuamap.com"
    assert "super-secret" not in repr(markers)


def test_non_http_marker_link_is_rejected():
    markers = scraper._format_markers(
        [{"id": "evt", "lat": 10, "lng": 20, "link": "javascript:alert(1)"}],
        region="Ukraine",
        base_url="https://liveuamap.com",
        provider="browser",
    )
    assert markers[0]["link"] == "https://liveuamap.com"
    assert "javascript:" not in repr(markers)


def test_api_redirect_is_refused_before_following_credentials(monkeypatch):
    monkeypatch.setenv("LIVEUAMAP_API_URL", "https://api.example.test/events")
    monkeypatch.setattr(
        scraper.requests,
        "get",
        lambda *args, **kwargs: _Response({}, status_code=302),
    )
    try:
        scraper._fetch_liveuamap_api()
    except requests.HTTPError as exc:
        assert "redirected" in str(exc)
    else:
        raise AssertionError("redirect should have been rejected")


def test_api_failure_falls_back_to_browser_when_browser_is_allowed(monkeypatch):
    monkeypatch.setattr(settings, "liveuamap_api_configured", lambda: True)
    monkeypatch.setattr(settings, "liveuamap_browser_scraper_enabled", lambda: True)
    monkeypatch.setattr(
        scraper,
        "_fetch_liveuamap_api",
        lambda: (_ for _ in ()).throw(requests.Timeout("boom")),
    )
    monkeypatch.setattr(scraper, "_fetch_liveuamap_browser", lambda: [{"id": "browser"}])
    assert scraper.fetch_liveuamap() == [{"id": "browser"}]


def test_api_failure_does_not_force_browser_when_browser_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "liveuamap_api_configured", lambda: True)
    monkeypatch.setattr(settings, "liveuamap_browser_scraper_enabled", lambda: False)
    monkeypatch.setattr(
        scraper,
        "_fetch_liveuamap_api",
        lambda: (_ for _ in ()).throw(requests.Timeout("boom")),
    )
    called = False

    def browser():
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(scraper, "_fetch_liveuamap_browser", browser)
    assert scraper.fetch_liveuamap() == []
    assert called is False


def test_browser_disable_does_not_disable_configured_api_scheduler_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "_OPT_IN_FILE", tmp_path / "choice.json")
    monkeypatch.setattr(settings.os, "name", "nt")
    monkeypatch.setenv("SHADOWBROKER_ENABLE_LIVEUAMAP_SCRAPER", "false")
    monkeypatch.setenv("LIVEUAMAP_API_URL", "https://api.example.test/events")
    assert settings.liveuamap_browser_scraper_enabled() is False
    assert settings.liveuamap_scraper_enabled() is True


def test_api_url_with_embedded_credentials_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "_OPT_IN_FILE", tmp_path / "choice.json")
    monkeypatch.setattr(settings.os, "name", "nt")
    monkeypatch.setenv("LIVEUAMAP_API_URL", "https://user:password@api.example.test/events")
    assert settings.liveuamap_api_configured() is False
    assert scraper._api_url() == ""


def test_http_api_endpoint_is_not_used(monkeypatch):
    monkeypatch.setenv("LIVEUAMAP_API_URL", "http://api.example.test/events")
    monkeypatch.setattr(scraper, "_fetch_liveuamap_browser", lambda: [])
    assert scraper._api_url() == ""
