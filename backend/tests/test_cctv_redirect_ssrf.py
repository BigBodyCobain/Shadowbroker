"""Issue #192 (tg12): CCTV proxy must re-validate the host on every redirect hop.

Before this fix, the proxy validated only the initial caller-supplied URL
host and then used ``requests.get(..., allow_redirects=True)``, which would
silently follow a 302 to an arbitrary internal address — an open-redirect-
to-SSRF chain.

These tests assert that:

1. A redirect to a disallowed host is rejected (502).
2. A redirect to an allowed host is followed (200).
3. The redirect chain length is bounded.
"""
import pytest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from routers.cctv import _fetch_cctv_upstream_response, _CCTV_MAX_REDIRECTS


class _Resp:
    """Minimal mock for requests.Response that mimics what _fetch needs."""

    def __init__(self, status_code=200, headers=None, is_redirect=False):
        self.status_code = status_code
        self.headers = headers or {}
        self.is_redirect = is_redirect
        self.closed = False

    def close(self):
        self.closed = True


def _profile():
    """Build a tiny _CCTVProxyProfile-shaped mock the function expects."""
    p = MagicMock()
    p.name = "test"
    p.timeout = 5
    p.cache_seconds = 60
    return p


def _request():
    """Build a tiny Request-shaped mock — only headers are read."""
    req = MagicMock()
    req.headers = {}
    return req


@patch("routers.cctv._cctv_upstream_headers", return_value={})
@patch("routers.cctv._cctv_host_allowed", side_effect=lambda host: host == "allowed.example")
@patch("routers.cctv._req" if False else "requests.get")  # patched below per-call
def test_redirect_to_disallowed_host_is_rejected(mock_get, mock_allow, mock_headers):
    """A 302 from allowed.example -> evil.example must be rejected with 502."""
    # First call: 302 with Location: http://evil.example/path
    mock_get.side_effect = [
        _Resp(status_code=302, headers={"Location": "http://evil.example/path"}, is_redirect=True),
    ]
    with pytest.raises(HTTPException) as exc_info:
        _fetch_cctv_upstream_response(_request(), "http://allowed.example/cam", _profile())
    assert exc_info.value.status_code == 502
    assert "disallowed host" in str(exc_info.value.detail).lower()


@patch("routers.cctv._cctv_upstream_headers", return_value={})
@patch("routers.cctv._cctv_host_allowed", side_effect=lambda host: host == "allowed.example")
@patch("requests.get")
def test_redirect_to_localhost_is_rejected(mock_get, mock_allow, mock_headers):
    """A redirect to 127.0.0.1 (internal SSRF target) must be rejected."""
    mock_get.side_effect = [
        _Resp(status_code=302, headers={"Location": "http://127.0.0.1:8000/api/secret"}, is_redirect=True),
    ]
    with pytest.raises(HTTPException) as exc_info:
        _fetch_cctv_upstream_response(_request(), "http://allowed.example/cam", _profile())
    assert exc_info.value.status_code == 502


@patch("routers.cctv._cctv_upstream_headers", return_value={})
@patch("routers.cctv._cctv_host_allowed", side_effect=lambda host: host in {"allowed.example", "other-allowed.example"})
@patch("requests.get")
def test_redirect_to_another_allowed_host_is_followed(mock_get, mock_allow, mock_headers):
    """A 302 from one allowed host to another allowed host should succeed."""
    mock_get.side_effect = [
        _Resp(status_code=302, headers={"Location": "http://other-allowed.example/cam"}, is_redirect=True),
        _Resp(status_code=200, headers={"Content-Type": "image/jpeg"}),
    ]
    resp = _fetch_cctv_upstream_response(_request(), "http://allowed.example/cam", _profile())
    assert resp.status_code == 200


@patch("routers.cctv._cctv_upstream_headers", return_value={})
@patch("routers.cctv._cctv_host_allowed", return_value=True)
@patch("requests.get")
def test_redirect_chain_length_is_bounded(mock_get, mock_allow, mock_headers):
    """A pathological redirect loop must terminate within _CCTV_MAX_REDIRECTS."""
    # Generate enough 302s to exceed the cap.
    mock_get.side_effect = [
        _Resp(status_code=302, headers={"Location": f"http://allowed.example/{i}"}, is_redirect=True)
        for i in range(_CCTV_MAX_REDIRECTS + 2)
    ]
    with pytest.raises(HTTPException) as exc_info:
        _fetch_cctv_upstream_response(_request(), "http://allowed.example/cam", _profile())
    assert exc_info.value.status_code == 502
    assert "too long" in str(exc_info.value.detail).lower()


@patch("routers.cctv._cctv_upstream_headers", return_value={})
@patch("routers.cctv._cctv_host_allowed", return_value=True)
@patch("requests.get")
def test_redirect_to_non_http_scheme_is_rejected(mock_get, mock_allow, mock_headers):
    """A 302 to ``file://`` or ``ftp://`` must be rejected even if the host parses cleanly."""
    mock_get.side_effect = [
        _Resp(status_code=302, headers={"Location": "file:///etc/passwd"}, is_redirect=True),
    ]
    with pytest.raises(HTTPException) as exc_info:
        _fetch_cctv_upstream_response(_request(), "http://allowed.example/cam", _profile())
    assert exc_info.value.status_code == 502
    assert "non-http" in str(exc_info.value.detail).lower()
