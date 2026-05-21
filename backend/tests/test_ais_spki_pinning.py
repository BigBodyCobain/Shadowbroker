"""Issue #258 — AIS proxy SPKI pinning.

Most of the SPKI logic lives in ``backend/ais_proxy.js`` (Node) and can't
be unit-tested from Python directly. These tests cover the Python-side
glue: ``services.ais_stream.ais_proxy_status()`` (the snapshot the proxy
populates via stdout markers) and ``routers/health.py`` surfacing the
degraded TLS state.

Additionally, the pin-file structure is validated: it must be parseable
JSON, must contain an entry for ``stream.aisstream.io``, and each pin
must look like a base64-encoded SHA-256 hash.
"""
import base64
import json
import re
from pathlib import Path

import pytest

from services import ais_stream

PIN_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "aisstream_spki_pins.json"
)


def test_pin_file_exists_and_is_valid_json():
    assert PIN_FILE.exists(), f"Expected pin file at {PIN_FILE}"
    data = json.loads(PIN_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_pin_file_has_aisstream_entry():
    data = json.loads(PIN_FILE.read_text(encoding="utf-8"))
    pins = data.get("stream.aisstream.io")
    assert isinstance(pins, list)
    assert len(pins) >= 1


def test_each_pin_looks_like_a_base64_sha256():
    """SPKI pins must be 44-char base64-encoded SHA-256 digests."""
    data = json.loads(PIN_FILE.read_text(encoding="utf-8"))
    pins = data["stream.aisstream.io"]
    for pin in pins:
        assert isinstance(pin, str), f"pin not a string: {pin!r}"
        assert len(pin) == 44, f"pin {pin!r} not 44 chars (SHA-256 base64)"
        # Must base64-decode to exactly 32 bytes (256 bits)
        try:
            raw = base64.b64decode(pin)
        except Exception as exc:
            pytest.fail(f"pin {pin!r} is not valid base64: {exc}")
        assert len(raw) == 32, f"pin {pin!r} decodes to {len(raw)} bytes, expected 32"
        # Should match the canonical base64 alphabet (no URL-safe variants)
        assert re.match(r"^[A-Za-z0-9+/]+=*$", pin), f"pin {pin!r} contains non-base64 chars"


def test_ais_proxy_status_starts_empty():
    """Before the proxy emits any status marker, the snapshot is empty."""
    # Clear any stale state from other tests
    with ais_stream._vessels_lock:
        ais_stream._proxy_status.clear()
    status = ais_stream.ais_proxy_status()
    assert status == {}


def test_ais_proxy_status_returns_copy_not_reference():
    """ais_proxy_status() must return a defensive copy.

    Otherwise a caller could mutate the live dict and confuse later reads.
    """
    with ais_stream._vessels_lock:
        ais_stream._proxy_status.clear()
        ais_stream._proxy_status["degraded_tls"] = True

    snapshot = ais_stream.ais_proxy_status()
    assert snapshot == {"degraded_tls": True}
    snapshot["degraded_tls"] = False  # mutate the returned copy

    # Original should be untouched
    re_snapshot = ais_stream.ais_proxy_status()
    assert re_snapshot == {"degraded_tls": True}

    # Cleanup so other tests start clean
    with ais_stream._vessels_lock:
        ais_stream._proxy_status.clear()


def test_health_includes_ais_proxy_field(client):
    """The /api/health response must include the ais_proxy block."""
    # Inject a known degraded state
    with ais_stream._vessels_lock:
        ais_stream._proxy_status.clear()
        ais_stream._proxy_status["degraded_tls"] = True

    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()

    assert "ais_proxy" in payload
    assert payload["ais_proxy"] == {"degraded_tls": True}
    # Top-level status should escalate from ok to degraded when AIS is
    # in degraded-TLS mode (unless SLOs already report worse).
    assert payload["status"] in {"degraded", "error"}

    # Cleanup
    with ais_stream._vessels_lock:
        ais_stream._proxy_status.clear()


def test_health_ais_proxy_field_when_no_status(client):
    """When the proxy hasn't reported anything yet, ais_proxy is empty."""
    with ais_stream._vessels_lock:
        ais_stream._proxy_status.clear()

    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("ais_proxy") == {}
