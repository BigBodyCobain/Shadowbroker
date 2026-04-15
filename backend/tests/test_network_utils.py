"""Tests for network_utils — fetch_with_curl, circuit breaker, domain fail cache."""

import time
import pytest
from unittest.mock import patch, MagicMock
from services.network_utils import (
    fetch_with_curl,
    _circuit_breaker,
    _domain_fail_cache,
    _cb_lock,
    _DummyResponse,
)


class TestDummyResponse:
    """Tests for the minimal response object used as curl fallback."""

    def test_status_code_and_text(self):
        resp = _DummyResponse(200, '{"ok": true}')
        assert resp.status_code == 200
        assert resp.text == '{"ok": true}'

    def test_json_parsing(self):
        resp = _DummyResponse(200, '{"key": "value", "num": 42}')
        data = resp.json()
        assert data["key"] == "value"
        assert data["num"] == 42

    def test_content_bytes(self):
        resp = _DummyResponse(200, "hello")
        assert resp.content == b"hello"

    def test_raise_for_status_ok(self):
        resp = _DummyResponse(200, "ok")
        resp.raise_for_status()  # Should not raise

    def test_raise_for_status_error(self):
        resp = _DummyResponse(500, "server error")
        with pytest.raises(Exception, match="HTTP 500"):
            resp.raise_for_status()

    def test_raise_for_status_404(self):
        resp = _DummyResponse(404, "not found")
        with pytest.raises(Exception, match="HTTP 404"):
            resp.raise_for_status()


class TestCircuitBreaker:
    """Tests for the circuit breaker and domain fail cache."""

    def setup_method(self):
        """Clear caches before each test."""
        with _cb_lock:
            _circuit_breaker.clear()
            _domain_fail_cache.clear()

    def test_circuit_breaker_blocks_request(self):
        """If a domain is in circuit breaker, fetch_with_curl should fail fast."""
        with _cb_lock:
            _circuit_breaker["example.com"] = time.time()

        with pytest.raises(Exception, match="Circuit breaker open"):
            fetch_with_curl("https://example.com/test")

    def test_circuit_breaker_expires_after_ttl(self):
        """Circuit breaker entries older than TTL should be ignored."""
        with _cb_lock:
            _circuit_breaker["expired.com"] = time.time() - 200  # > 120s TTL

        # Should not raise — circuit breaker expired
        # Will fail for other reasons (network) but won't raise circuit breaker
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"
        mock_resp.raise_for_status = MagicMock()

        with patch("services.network_utils._session") as mock_session:
            mock_session.get.return_value = mock_resp
            result = fetch_with_curl("https://expired.com/test")
            assert result.status_code == 200

    def test_domain_fail_cache_skips_to_curl(self):
        """If a domain recently failed with requests, skip straight to curl."""
        with _cb_lock:
            _domain_fail_cache["skip-to-curl.com"] = time.time()

        # Mock subprocess to simulate curl success
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"data": true}\n200'
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = fetch_with_curl("https://skip-to-curl.com/api")
            assert result.status_code == 200
            assert result.json()["data"] is True
            # Verify subprocess.run was called (curl fallback)
            mock_run.assert_called_once()

    def test_successful_request_clears_caches(self):
        """Successful requests should clear both domain_fail_cache and circuit_breaker."""
        domain = "success-clears.com"
        with _cb_lock:
            _domain_fail_cache[domain] = time.time() - 400  # Expired, won't skip
            _circuit_breaker[domain] = time.time() - 200  # Expired, won't block

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"
        mock_resp.raise_for_status = MagicMock()

        with patch("services.network_utils._session") as mock_session:
            mock_session.get.return_value = mock_resp
            fetch_with_curl(f"https://{domain}/test")

        with _cb_lock:
            assert domain not in _domain_fail_cache
            assert domain not in _circuit_breaker


class TestFetchWithCurl:
    """Tests for the primary fetch_with_curl function."""

    def setup_method(self):
        with _cb_lock:
            _circuit_breaker.clear()
            _domain_fail_cache.clear()

    def test_successful_get_returns_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"result": 42}'
        mock_resp.raise_for_status = MagicMock()

        with patch("services.network_utils._session") as mock_session:
            mock_session.get.return_value = mock_resp
            result = fetch_with_curl("https://api.example.com/data")
            assert result.status_code == 200

    def test_post_with_json_data(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"created": true}'
        mock_resp.raise_for_status = MagicMock()

        with patch("services.network_utils._session") as mock_session:
            mock_session.post.return_value = mock_resp
            result = fetch_with_curl(
                "https://api.example.com/create", method="POST", json_data={"name": "test"}
            )
            assert result.status_code == 200
            mock_session.post.assert_called_once()

    def test_custom_headers_merged(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"
        mock_resp.raise_for_status = MagicMock()

        with patch("services.network_utils._session") as mock_session:
            mock_session.get.return_value = mock_resp
            fetch_with_curl(
                "https://api.example.com/data", headers={"Authorization": "Bearer token123"}
            )
            call_args = mock_session.get.call_args
            headers = call_args.kwargs.get("headers", {})
            assert "Authorization" in headers
            assert headers["Authorization"] == "Bearer token123"
