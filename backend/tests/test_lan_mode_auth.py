"""LAN mode removes the implicit operator trust given to the frontend container."""

import pytest
from fastapi import HTTPException

import auth


class _Req:
    def __init__(self, host, headers=None):
        self.client = type("C", (), {"host": host})()
        self.headers = headers or {}


@pytest.fixture(autouse=True)
def _frontend_ip(monkeypatch):
    monkeypatch.setenv("SHADOWBROKER_TRUST_DOCKER_BRIDGE_LOCAL_OPERATOR", "1")
    monkeypatch.setattr(auth, "_resolve_trusted_bridge_ips", lambda: {"172.18.0.5"})
    monkeypatch.setattr(auth, "_current_admin_key", lambda: "k" * 32)


def test_frontend_container_is_trusted_outside_lan_mode(monkeypatch):
    monkeypatch.delenv("SHADOWBROKER_LAN_MODE", raising=False)
    auth.require_local_operator(_Req("172.18.0.5"))


def test_lan_mode_requires_admin_key_from_frontend_container(monkeypatch):
    monkeypatch.setenv("SHADOWBROKER_LAN_MODE", "1")
    with pytest.raises(HTTPException) as exc:
        auth.require_local_operator(_Req("172.18.0.5"))
    assert exc.value.status_code == 403
    # A signed-in browser's session key is forwarded as X-Admin-Key.
    auth.require_local_operator(_Req("172.18.0.5", {"X-Admin-Key": "k" * 32}))


def test_lan_mode_keeps_loopback_tools_working(monkeypatch):
    monkeypatch.setenv("SHADOWBROKER_LAN_MODE", "1")
    auth.require_local_operator(_Req("127.0.0.1"))


def test_untrusted_loopback_requires_admin_key(monkeypatch):
    monkeypatch.setenv("SHADOWBROKER_UNTRUSTED_LOOPBACK", "1")
    with pytest.raises(HTTPException):
        auth.require_local_operator(_Req("127.0.0.1"))
    auth.require_local_operator(_Req("127.0.0.1", {"X-Admin-Key": "k" * 32}))
