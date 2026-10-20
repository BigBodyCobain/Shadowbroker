"""Madrid CCTV KML prefers HTTPS (#363)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.cctv_pipeline import MadridCityIngestor


def test_madrid_fetch_kml_tries_https_before_http():
    ingestor = MadridCityIngestor()
    calls: list[str] = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        if url == ingestor.KML_URL_HTTPS:
            raise ConnectionError("tls handshake failed")
        res = MagicMock()
        res.status_code = 200
        res.content = b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"></kml>'
        res.raise_for_status = MagicMock()
        return res

    with patch("services.cctv_pipeline.fetch_with_curl", side_effect=fake_fetch):
        response = ingestor._fetch_kml()

    assert response.status_code == 200
    assert calls == [ingestor.KML_URL_HTTPS, ingestor.KML_URL_HTTP]
