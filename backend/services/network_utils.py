import logging
import json
import os
import subprocess
import shutil
import time
import threading
import uuid
import requests
from pathlib import Path
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


# ---------------------------------------------------------------------------
# Per-operator outbound identification
# ---------------------------------------------------------------------------
#
# Issues #289 / #290 / #291 and the retrofit of PR #284 (#218 / #219 / #220):
# every third-party API the backend calls used to identify itself with a
# single "Shadowbroker" aggregate User-Agent. From the upstream's
# perspective, that meant every Shadowbroker install in the world looked
# like one giant entity hammering them. If one install misbehaved, the
# upstream's only recourse was to block "Shadowbroker" as a whole — which
# would take out every other install too.
#
# Fix: give each install a stable pseudonymous handle used as the entire
# User-Agent product token (no shared "Shadowbroker" label). Upstreams see
# ``operator-7f3a92`` (or ``OPERATOR_HANDLE``), not one monolithic app name.
#
# The handle:
#
# - Is auto-generated on first call if no `OPERATOR_HANDLE` is configured
#   (looks like "operator-7f3a92" — 6 hex chars from uuid4()).
# - Is persisted to ``backend/data/operator_handle.json`` so it survives
#   restarts. Under Docker compose that file lives in the volume mount
#   alongside `carrier_cache.json` and the other persistent state.
# - Can be overridden by the operator via the `OPERATOR_HANDLE` setting
#   (env var or settings UI). Operators with their own GitHub handle,
#   organization name, etc. can use that for traceability.
# - Is NEVER mixed into mesh / Wormhole / Infonet identity. This layer is
#   strictly for public third-party API attribution.

_OPERATOR_HANDLE_FILE = (
    Path(__file__).parent.parent / "data" / "operator_handle.json"
)
_OPERATOR_HANDLE_CACHE: str = ""
_OPERATOR_HANDLE_LOCK = threading.Lock()


def _generate_operator_handle() -> str:
    """Produce a stable pseudonymous handle for first-launch installs.

    Format: ``operator-7f3a92`` (6 hex chars from a fresh uuid4()).
    Distinct per install. Carries no real-world identity by default —
    operators who want one can override via ``OPERATOR_HANDLE``.

    Note: the prefix is deliberately neutral. Earlier drafts used
    ``shadow-`` which, while accurate to the project name, looks
    exactly like the kind of pattern a third-party abuse-detection
    system would auto-block as suspicious. ``operator-`` describes
    what the value actually is and doesn't pattern-match malware.
    """
    return f"operator-{uuid.uuid4().hex[:6]}"


def _load_persisted_operator_handle() -> str:
    """Return the previously-saved handle from disk, or empty if none.

    Reads ``backend/data/operator_handle.json`` if it exists. Any read
    error returns empty so a fresh handle gets generated rather than
    crashing the request.
    """
    try:
        if _OPERATOR_HANDLE_FILE.exists():
            data = json.loads(_OPERATOR_HANDLE_FILE.read_text(encoding="utf-8"))
            return str(data.get("handle", "") or "").strip()
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return ""


def _persist_operator_handle(handle: str) -> None:
    """Atomically save the auto-generated handle so subsequent restarts
    use the same one. Failure to persist is non-fatal — the request still
    succeeds with the in-memory handle, we just may generate a different
    one on the next process restart."""
    try:
        _OPERATOR_HANDLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _OPERATOR_HANDLE_FILE.with_suffix(_OPERATOR_HANDLE_FILE.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"handle": handle, "_meta": {
                "purpose": "Per-install operator handle for outbound third-party API attribution.",
                "see": "backend/services/network_utils.py:outbound_user_agent",
            }}, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, _OPERATOR_HANDLE_FILE)
    except OSError as exc:
        logger.debug("Could not persist operator_handle (continuing in-memory): %s", exc)


def get_operator_handle() -> str:
    """Return the stable per-install operator handle.

    Resolution order:
      1. ``OPERATOR_HANDLE`` setting (env var / settings UI) if non-empty.
      2. Process-cached value from previous call this run.
      3. Value persisted to ``operator_handle.json`` (from a previous run).
      4. Newly generated pseudonymous handle, persisted to disk.

    The handle is normalized: stripped of whitespace, lowercased,
    non-alphanumeric chars (except ``-`` and ``_``) replaced with ``-``.
    This both sanitizes any HTTP-header-unsafe characters AND prevents
    the operator from impersonating real third-party projects via
    inventive whitespace.
    """
    global _OPERATOR_HANDLE_CACHE
    with _OPERATOR_HANDLE_LOCK:
        # 1. Configured override always wins.
        configured = ""
        try:
            from services.config import get_settings

            configured = str(getattr(get_settings(), "OPERATOR_HANDLE", "") or "").strip()
        except Exception:
            configured = ""
        if configured:
            return _normalize_handle(configured)

        # 2. In-memory cache (fast path for repeated calls).
        if _OPERATOR_HANDLE_CACHE:
            return _OPERATOR_HANDLE_CACHE

        # 3. On-disk handle from a previous run.
        persisted = _load_persisted_operator_handle()
        if persisted:
            normalized = _normalize_handle(persisted)
            # Migrate legacy auto-generated handles (pre-Round-7a ``shadow-`` prefix).
            if normalized.startswith("shadow-"):
                normalized = f"operator-{normalized[len('shadow-'):]}"
                _persist_operator_handle(normalized)
            _OPERATOR_HANDLE_CACHE = normalized
            return _OPERATOR_HANDLE_CACHE

        # 4. Generate, persist, return.
        fresh = _generate_operator_handle()
        _persist_operator_handle(fresh)
        _OPERATOR_HANDLE_CACHE = fresh
        return fresh


def _normalize_handle(raw: str) -> str:
    """Strip whitespace, lowercase, replace unsafe characters with dashes."""
    safe = "".join(
        ch if (ch.isalnum() or ch in "-_") else "-"
        for ch in raw.strip().lower()
    )
    # Collapse runs of dashes and trim to a reasonable length so an
    # operator can't make our outbound logs unreadable.
    while "--" in safe:
        safe = safe.replace("--", "-")
    safe = safe.strip("-")
    return safe[:48] if safe else "anonymous"


def outbound_user_agent(purpose: str = "") -> str:
    """Build a User-Agent for an outbound third-party HTTP request.

    Returns the per-install handle only, e.g. ``operator-7f3a92`` or
    ``operator-7f3a92 (purpose: wikipedia)``. No shared project name — so
    upstream abuse teams cannot block every install with one ``Shadowbroker``
    rule.

    Set ``SHADOWBROKER_USER_AGENT`` to override the entire string if needed.
    """
    handle = get_operator_handle()
    if purpose:
        purpose_clean = _normalize_handle(purpose)
        return f"{handle} (purpose: {purpose_clean})"
    return handle


def _reset_operator_handle_cache_for_tests() -> None:
    """Test-only: invalidate the in-memory cache so a test can set a
    new ``OPERATOR_HANDLE`` env var and see it picked up immediately."""
    global _OPERATOR_HANDLE_CACHE
    with _OPERATOR_HANDLE_LOCK:
        _OPERATOR_HANDLE_CACHE = ""


def default_user_agent() -> str:
    """Default User-Agent for ``fetch_with_curl`` and legacy call sites."""
    custom = (os.environ.get("SHADOWBROKER_USER_AGENT") or "").strip()
    if custom:
        return custom
    return outbound_user_agent()


# Find bash for curl fallback — Git bash's curl has the TLS features
# needed to pass CDN fingerprint checks (brotli, zstd, libpsl)

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


def _env_truthy(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def external_curl_fallback_enabled() -> bool:
    """Return whether the backend may spawn an external curl process."""
    if os.name != "nt":
        return True
    return _env_truthy("SHADOWBROKER_ENABLE_WINDOWS_CURL_FALLBACK")


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


def fetch_with_curl(url, method="GET", json_data=None, timeout=15, headers=None, follow_redirects=False):
    """Wrapper to bypass aggressive local firewall that blocks Python but permits curl.

    Falls back to running curl through Git bash, which has the TLS features
    (brotli, zstd, libpsl) needed to pass CDN fingerprint checks that block
    both Python requests and the barebones Windows system curl.
    """
    default_headers = {
        "User-Agent": default_user_agent(),
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
            fallback = "falling back to curl" if external_curl_fallback_enabled() else "skipping external curl"
            logger.warning(f"Python requests failed for {url} ({e}), {fallback}...")
            with _cb_lock:
                _domain_fail_cache[domain] = time.time()

    # Curl fallback — reached from both _skip_requests and requests-exception paths
    if not external_curl_fallback_enabled():
        logger.warning(
            "External curl fallback disabled on Windows for %s; set "
            "SHADOWBROKER_ENABLE_WINDOWS_CURL_FALLBACK=1 to opt in.",
            domain,
        )
        with _cb_lock:
            _circuit_breaker[domain] = time.time()
        return _DummyResponse(500, "")

    _CURL_PATH = shutil.which("curl") or "curl"
    cmd = [_CURL_PATH, "-s", "-w", "\n%{http_code}"]
    if follow_redirects:
        cmd.append("-L")
    for k, v in default_headers.items():
        cmd += ["-H", f"{k}: {v}"]
    if method == "POST" and json_data:
        cmd += ["-X", "POST", "-H", "Content-Type: application/json",
                "--data-binary", "@-"]
    cmd.append(url)

    try:
        stdin_data = json.dumps(json_data) if (method == "POST" and json_data) else None
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 5,
            input=stdin_data, encoding="utf-8", errors="replace",
            creationflags=creationflags,
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
            logger.error(f"curl fallback failed: exit={res.returncode} stderr={res.stderr[:200]}")
            with _cb_lock:
                _circuit_breaker[domain] = time.time()
            return _DummyResponse(500, "")
    except (subprocess.SubprocessError, ConnectionError, TimeoutError, OSError) as curl_e:
        logger.error(f"curl fallback exception: {curl_e}")
        with _cb_lock:
            _circuit_breaker[domain] = time.time()
        return _DummyResponse(500, "")
