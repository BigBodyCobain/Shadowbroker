"""Issue #205 (tg12): the OpenMHZ audio proxy must re-validate the host on
every redirect hop, not just the first one.

Before this fix, ``openmhz_audio_response()`` called
``requests.get(..., stream=True, timeout=...)`` with the default
``allow_redirects=True``. The initial URL host was validated against
``_OPENMHZ_AUDIO_HOSTS``, but any subsequent redirect was silently
followed — even to ``http://127.0.0.1:8000`` or RFC1918 internal ranges.
Classic open-redirect-to-SSRF.

After the fix, redirects are followed manually with per-hop host
re-validation. Same-host redirects (CDN edge selection) still work,
so legitimate audio playback is unaffected.
"""
import pytest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from services.radio_intercept import _OPENMHZ_MAX_REDIRECTS, openmhz_audio_response


class _Resp:
    """Minimal mock for requests.Response."""

    def __init__(self, status_code=200, headers=None, is_redirect=False):
        self.status_code = status_code
        self.headers = headers or {}
        self.is_redirect = is_redirect
        self.closed = False

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size=64 * 1024):
        return iter([])


@patch("services.radio_intercept.requests.get")
def test_redirect_to_internal_address_rejected(mock_get):
    """A 302 from media.openmhz.com -> 127.0.0.1 must be rejected."""
    mock_get.side_effect = [
        _Resp(status_code=302, headers={"Location": "http://127.0.0.1:8000/api/secret"}, is_redirect=True),
    ]
    with pytest.raises(HTTPException) as exc_info:
        openmhz_audio_response("https://media.openmhz.com/audio/abc.mp3")
    assert exc_info.value.status_code == 502


@patch("services.radio_intercept.requests.get")
def test_redirect_to_arbitrary_domain_rejected(mock_get):
    """A 302 to an attacker-controlled domain must be rejected."""
    mock_get.side_effect = [
        _Resp(status_code=302, headers={"Location": "https://evil.example/exfil"}, is_redirect=True),
    ]
    with pytest.raises(HTTPException) as exc_info:
        openmhz_audio_response("https://media.openmhz.com/audio/abc.mp3")
    assert exc_info.value.status_code == 502


@patch("services.radio_intercept.requests.get")
def test_redirect_to_another_openmhz_cdn_followed(mock_get):
    """A 302 from media.openmhz.com -> media2.openmhz.com (same allowlist) is OK."""
    mock_get.side_effect = [
        _Resp(status_code=302, headers={"Location": "https://media2.openmhz.com/audio/abc.mp3"}, is_redirect=True),
        _Resp(status_code=200, headers={"Content-Type": "audio/mpeg"}),
    ]
    resp = openmhz_audio_response("https://media.openmhz.com/audio/abc.mp3")
    # StreamingResponse-shaped object — we just check it was constructed.
    assert resp is not None


@patch("services.radio_intercept.requests.get")
def test_redirect_chain_length_bounded(mock_get):
    """A redirect loop must terminate within _OPENMHZ_MAX_REDIRECTS."""
    mock_get.side_effect = [
        _Resp(status_code=302, headers={"Location": "https://media.openmhz.com/loop"}, is_redirect=True)
        for _ in range(_OPENMHZ_MAX_REDIRECTS + 2)
    ]
    with pytest.raises(HTTPException) as exc_info:
        openmhz_audio_response("https://media.openmhz.com/audio/abc.mp3")
    assert exc_info.value.status_code == 502


@patch("services.radio_intercept.requests.get")
def test_redirect_to_http_scheme_rejected(mock_get):
    """A 302 to http:// (instead of https://) must be rejected even on same host."""
    mock_get.side_effect = [
        _Resp(status_code=302, headers={"Location": "http://media.openmhz.com/audio/abc.mp3"}, is_redirect=True),
    ]
    with pytest.raises(HTTPException) as exc_info:
        openmhz_audio_response("https://media.openmhz.com/audio/abc.mp3")
    assert exc_info.value.status_code == 502
