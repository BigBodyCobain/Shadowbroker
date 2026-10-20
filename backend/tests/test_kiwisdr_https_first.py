"""KiwiSDR mirror prefers HTTPS (#364)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.kiwisdr_fetcher import (
    _SOURCE_URL_HTTP,
    _SOURCE_URL_HTTPS,
    _fetch_mirror_payload_text,
)


def test_fetch_mirror_tries_https_before_http():
    calls: list[str] = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        if url == _SOURCE_URL_HTTPS:
            raise ConnectionError("tls not available")
        res = MagicMock()
        res.status_code = 200
        res.text = "var kiwisdr_com = [];"
        return res

    with patch("services.network_utils.fetch_with_curl", side_effect=fake_fetch):
        body = _fetch_mirror_payload_text()

    assert body == "var kiwisdr_com = [];"
    assert calls == [_SOURCE_URL_HTTPS, _SOURCE_URL_HTTP]
