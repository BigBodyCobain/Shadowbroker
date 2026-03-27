import logging
import json
import subprocess
import shutil
import time
import threading
import requests
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Reusable session with connection pooling and retry logic.
# Only retry once (total=1) to fail fast — the curl fallback is the real safety net.
_session = requests.Session()
_retry = Retry(total=1, backoff_factor=0.3, status_forcelist=[502, 503, 504])
_session.mount("https://", HTTPAdapter(max_retries=_retry, pool_maxsize=20))
_session.mount("http://", HTTPAdapter(max_retries=_retry, pool_maxsize=10))

# Find bash for curl fallback — Git bash's curl has the TLS features
# needed to pass CDN fingerprint checks (brotli, zstd, libpsl)
_BASH_PATH = shutil.which("bash") or "bash"

# Cache domains where requests fails — skip straight to curl for 5 minutes
_domain_fail_cache: dict[str, float] = {}
_DOMAIN_FAIL_TTL = 300  # 5 minutes

# Circuit breaker: track domains where BOTH requests AND curl fail
# If a domain failed completely within the last 2 minutes, skip it entirely
_circuit_breaker: dict[str, float] = {}
_CIRCUIT_BREAKER_TTL = 120  # 2 minutes

# Lock protecting _domain_fail_cache and _circuit_breaker mutations
_cb_lock = threading.Lock()


class UpstreamCircuitBreakerError(OSError):
    """Raised when a domain recently failed hard and is temporarily skipped."""


class _DummyResponse:
    """Minimal response object matching requests.Response interface."""
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.content = text.encode('utf-8', errors='replace')

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}: {self.text[:100]}")


def fetch_with_curl(url, method="GET", json_data=None, timeout=15, headers=None):
    """Wrapper to bypass aggressive local firewall that blocks Python but permits curl.

    Falls back to running curl through Git bash, which has the TLS features
    (brotli, zstd, libpsl) needed to pass CDN fingerprint checks that block
    both Python requests and the barebones Windows system curl.
    """
    default_headers = {
        "User-Agent": "ShadowBroker-OSINT/1.0 (live-risk-dashboard)",
    }
    if headers:
        default_headers.update(headers)

    domain = urlparse(url).netloc

    # Circuit breaker: if domain failed completely <2min ago, fail fast
    with _cb_lock:
        if domain in _circuit_breaker and (time.time() - _circuit_breaker[domain]) < _CIRCUIT_BREAKER_TTL:
            raise UpstreamCircuitBreakerError(
                f"Circuit breaker open for {domain} (failed <{_CIRCUIT_BREAKER_TTL}s ago)"
            )

    # Check if this domain recently failed with requests — skip straight to curl
    with _cb_lock:
        _skip_requests = domain in _domain_fail_cache and (time.time() - _domain_fail_cache[domain]) < _DOMAIN_FAIL_TTL
    if not _skip_requests:
        try:
            # Use a short connect timeout (3s) so firewall blocks fail fast,
            # but allow the full timeout for reading the response body.
            req_timeout = (min(3, timeout), timeout)
            if method == "POST":
                res = _session.post(url, json=json_data, timeout=req_timeout, headers=default_headers)
            else:
                res = _session.get(url, timeout=req_timeout, headers=default_headers)
            if res.status_code == 429:
                logger.warning(f"Upstream rate limit hit for {url}; not bypassing with curl.")
                return res
            res.raise_for_status()
            # Clear failure caches on success
            with _cb_lock:
                _domain_fail_cache.pop(domain, None)
                _circuit_breaker.pop(domain, None)
            return res
        except (requests.RequestException, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Python requests failed for {url} ({e}), falling back to bash curl...")
            with _cb_lock:
                _domain_fail_cache[domain] = time.time()

    # Curl fallback — reached from both _skip_requests and requests-exception paths
    _CURL_PATH = shutil.which("curl") or "curl"
    cmd = [_CURL_PATH, "-s", "-w", "\n%{http_code}"]
    for k, v in default_headers.items():
        cmd += ["-H", f"{k}: {v}"]
    if method == "POST" and json_data:
        cmd += ["-X", "POST", "-H", "Content-Type: application/json",
                "--data-binary", "@-"]
    cmd.append(url)

    try:
        stdin_data = json.dumps(json_data) if (method == "POST" and json_data) else None
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 5,
            input=stdin_data, encoding="utf-8", errors="replace"
        )
        if res.returncode == 0 and (res.stdout or "").strip():
            # Parse HTTP status code from -w output (last line)
            lines = res.stdout.rstrip().rsplit("\n", 1)
            body = lines[0] if len(lines) > 1 else res.stdout
            http_code = int(lines[-1]) if len(lines) > 1 and lines[-1].strip().isdigit() else 200
            if http_code < 400:
                with _cb_lock:
                    _circuit_breaker.pop(domain, None)  # Clear circuit breaker on success
            return _DummyResponse(http_code, body)
        else:
            logger.error(f"bash curl fallback failed: exit={res.returncode} stderr={res.stderr[:200]}")
            with _cb_lock:
                _circuit_breaker[domain] = time.time()
            return _DummyResponse(500, "")
    except (subprocess.SubprocessError, ConnectionError, TimeoutError, OSError) as curl_e:
        logger.error(f"bash curl fallback exception: {curl_e}")
        with _cb_lock:
            _circuit_breaker[domain] = time.time()
        return _DummyResponse(500, "")
