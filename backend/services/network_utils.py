import logging
import json
import subprocess
import shutil
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Find bash for curl fallback — Git bash's curl has the TLS features
# needed to pass CDN fingerprint checks (brotli, zstd, libpsl)
_BASH_PATH = shutil.which("bash") or "bash"

# Cache domains where requests fails — skip straight to curl for 5 minutes
_domain_fail_cache: dict[str, float] = {}
_DOMAIN_FAIL_TTL = 300  # 5 minutes

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

    # Check if this domain recently failed with requests — skip straight to curl
    if domain in _domain_fail_cache and (time.time() - _domain_fail_cache[domain]) < _DOMAIN_FAIL_TTL:
        pass  # Fall through to curl below
    else:
        try:
            import requests
            if method == "POST":
                res = requests.post(url, json=json_data, timeout=timeout, headers=default_headers)
            else:
                res = requests.get(url, timeout=timeout, headers=default_headers)
            res.raise_for_status()
            # Clear failure cache on success
            _domain_fail_cache.pop(domain, None)
            return res
        except Exception as e:
            logger.warning(f"Python requests failed for {url} ({e}), falling back to bash curl...")
            _domain_fail_cache[domain] = time.time()

        # Build curl command string for bash execution
        header_flags = " ".join(f'-H "{k}: {v}"' for k, v in default_headers.items())
        if method == "POST" and json_data:
            payload = json.dumps(json_data).replace('"', '\\"')
            curl_cmd = f'curl -s -w "\\n%{{http_code}}" {header_flags} -X POST -H "Content-Type: application/json" -d "{payload}" "{url}"'
        else:
            curl_cmd = f'curl -s -w "\\n%{{http_code}}" {header_flags} "{url}"'

        try:
            res = subprocess.run(
                [_BASH_PATH, "-c", curl_cmd],
                capture_output=True, text=True, timeout=timeout + 5
            )
            if res.returncode == 0 and res.stdout.strip():
                # Parse HTTP status code from -w output (last line)
                lines = res.stdout.rstrip().rsplit("\n", 1)
                body = lines[0] if len(lines) > 1 else res.stdout
                http_code = int(lines[-1]) if len(lines) > 1 and lines[-1].strip().isdigit() else 200
                return _DummyResponse(http_code, body)
            else:
                logger.error(f"bash curl fallback failed: exit={res.returncode} stderr={res.stderr[:200]}")
                return _DummyResponse(500, "")
        except Exception as curl_e:
            logger.error(f"bash curl fallback exception: {curl_e}")
            return _DummyResponse(500, "")
