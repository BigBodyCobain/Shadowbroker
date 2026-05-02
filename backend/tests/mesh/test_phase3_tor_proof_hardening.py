"""Phase 3.1 — Tor proof hardening.

Pins fail-closed behavior of the Arti Tor proof check used by
``wormhole_supervisor._check_arti_ready``. The proof must:

- return ``False`` when ``MESH_ARTI_ENABLED`` is off (no proof attempt)
- return ``False`` when the SOCKS5 handshake fails (no live proxy)
- return ``False`` when the SOCKS5 handshake succeeds but the live IP
  check returns ``IsTor=False`` (proxy is reachable but is NOT Tor)
- return ``True`` only when the SOCKS5 handshake succeeds AND the live
  IP check confirms ``IsTor=True``
- honor the proof cache TTL so that a successful proof is not re-issued
  on every call (avoids hammering check.torproject.org)
- bust the cache after the TTL elapses

These are the invariants that make ``arti_ready`` a meaningful claim
rather than a config-flag echo.

NOTE: this is a single-oracle proof (check.torproject.org). The
runbook documents the SPOF; a Phase 3.x followup may add a second
verifier (e.g., a hidden-service self-fetch) to remove the SPOF.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSocket:
    """Minimal socket double that records SOCKS5 traffic."""

    def __init__(self, handshake_response: bytes = b"\x05\x00") -> None:
        self._handshake_response = handshake_response
        self.sent: list[bytes] = []

    def __enter__(self) -> "_FakeSocket":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, _n: int) -> bytes:
        return self._handshake_response


class _FakeResponse:
    def __init__(self, *, ok: bool, payload: dict[str, Any], status_code: int = 200) -> None:
        self.ok = ok
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


def _stub_settings(monkeypatch, *, enabled: bool = True, port: int = 9050) -> None:
    from services import wormhole_supervisor

    fake = SimpleNamespace(
        MESH_ARTI_ENABLED=enabled,
        MESH_ARTI_SOCKS_PORT=port,
    )

    def _get_settings() -> SimpleNamespace:
        return fake

    monkeypatch.setattr(
        "services.config.get_settings", _get_settings, raising=False
    )
    # Reset proof cache so each test starts clean.
    wormhole_supervisor._ARTI_PROOF_CACHE.update({"port": 0, "ok": False, "ts": 0.0})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_phase3_arti_proof_disabled_returns_false(monkeypatch):
    """When MESH_ARTI_ENABLED is false, _check_arti_ready returns False
    without attempting any network I/O."""

    from services import wormhole_supervisor

    _stub_settings(monkeypatch, enabled=False)

    def _no_socket(*_args, **_kwargs):
        raise AssertionError("socket.create_connection must not be called when arti is disabled")

    monkeypatch.setattr(
        wormhole_supervisor.socket, "create_connection", _no_socket, raising=True
    )

    assert wormhole_supervisor._check_arti_ready() is False


def test_phase3_arti_proof_socks_handshake_failure_returns_false(monkeypatch):
    """A failed SOCKS5 handshake (or any socket exception) must fail closed."""

    from services import wormhole_supervisor

    _stub_settings(monkeypatch)

    def _explode(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(
        wormhole_supervisor.socket, "create_connection", _explode, raising=True
    )

    assert wormhole_supervisor._check_arti_ready() is False


def test_phase3_arti_proof_socks_unexpected_response_returns_false(monkeypatch):
    """SOCKS5 server speaks but returns an unexpected greeting → fail closed."""

    from services import wormhole_supervisor

    _stub_settings(monkeypatch)

    def _bad_socket(*_args, **_kwargs):
        return _FakeSocket(handshake_response=b"\x04\xff")

    monkeypatch.setattr(
        wormhole_supervisor.socket, "create_connection", _bad_socket, raising=True
    )

    assert wormhole_supervisor._check_arti_ready() is False


def test_phase3_arti_proof_live_check_is_not_tor_returns_false(monkeypatch):
    """SOCKS handshake passes BUT check.torproject.org reports IsTor=False
    → the proxy is reachable yet not Tor → fail closed."""

    from services import wormhole_supervisor

    _stub_settings(monkeypatch)

    def _good_socket(*_args, **_kwargs):
        return _FakeSocket()

    monkeypatch.setattr(
        wormhole_supervisor.socket, "create_connection", _good_socket, raising=True
    )

    fake_response = _FakeResponse(ok=True, payload={"IsTor": False, "IP": "203.0.113.7"})

    def _fake_get(*_args, **_kwargs):
        return fake_response

    fake_requests = SimpleNamespace(get=_fake_get)
    monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)

    assert wormhole_supervisor._check_arti_ready() is False
    # Cache must hold the negative result for the configured port.
    cache = wormhole_supervisor._ARTI_PROOF_CACHE
    assert cache.get("ok") is False
    assert int(cache.get("port", 0) or 0) == 9050


def test_phase3_arti_proof_live_check_is_tor_returns_true(monkeypatch):
    """SOCKS handshake passes AND check.torproject.org reports IsTor=True
    → proof succeeds and the success is cached."""

    from services import wormhole_supervisor

    _stub_settings(monkeypatch)

    def _good_socket(*_args, **_kwargs):
        return _FakeSocket()

    monkeypatch.setattr(
        wormhole_supervisor.socket, "create_connection", _good_socket, raising=True
    )

    fake_response = _FakeResponse(ok=True, payload={"IsTor": True, "IP": "198.51.100.42"})
    call_count = {"n": 0}

    def _fake_get(*_args, **_kwargs):
        call_count["n"] += 1
        return fake_response

    fake_requests = SimpleNamespace(get=_fake_get)
    monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)

    assert wormhole_supervisor._check_arti_ready() is True
    assert call_count["n"] == 1

    # Second call within TTL must use the cached positive result; no new HTTP call.
    assert wormhole_supervisor._check_arti_ready() is True
    assert call_count["n"] == 1


def test_phase3_arti_proof_cache_expires_after_ttl(monkeypatch):
    """After ``_ARTI_PROOF_CACHE_TTL_S`` elapses, the proof is re-issued.
    A previously-cached True must NOT keep masking a now-failing oracle."""

    from services import wormhole_supervisor

    _stub_settings(monkeypatch)

    # Seed a stale positive cache that is OLDER than the TTL.
    wormhole_supervisor._ARTI_PROOF_CACHE.update(
        {
            "port": 9050,
            "ok": True,
            "ts": 0.0,  # epoch start — definitely older than TTL
        }
    )

    def _good_socket(*_args, **_kwargs):
        return _FakeSocket()

    monkeypatch.setattr(
        wormhole_supervisor.socket, "create_connection", _good_socket, raising=True
    )

    # New oracle reports IsTor=False — the stale cached True must NOT be returned.
    fake_response = _FakeResponse(ok=True, payload={"IsTor": False})

    def _fake_get(*_args, **_kwargs):
        return fake_response

    fake_requests = SimpleNamespace(get=_fake_get)
    monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)

    assert wormhole_supervisor._check_arti_ready() is False
    assert wormhole_supervisor._ARTI_PROOF_CACHE.get("ok") is False
