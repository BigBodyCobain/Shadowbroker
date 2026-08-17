from __future__ import annotations

import asyncio
import hashlib
import inspect
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from routers import agent_shell
from services import agent_shell_ws_token as ws_tokens
from services import updater


class _FakeWebSocket:
    def __init__(self, headers: dict[str, str] | None = None, host: str = "127.0.0.1") -> None:
        self.headers = headers or {}
        self.client = SimpleNamespace(host=host)
        self.closed: tuple[int, str] | None = None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)


def setup_function() -> None:
    ws_tokens.reset_agent_shell_ws_tokens_for_tests()


def teardown_function() -> None:
    ws_tokens.reset_agent_shell_ws_tokens_for_tests()


def test_agent_shell_query_no_longer_accepts_admin_key() -> None:
    parameters = inspect.signature(agent_shell.agent_shell_websocket).parameters
    assert "admin_key" not in parameters
    assert "ws_token" in parameters


def test_loopback_source_ip_is_not_agent_shell_authorization() -> None:
    ws = _FakeWebSocket({"host": "127.0.0.1:8000"})
    with pytest.raises(WebSocketDisconnect):
        asyncio.run(agent_shell._authorize_agent_shell_ws(ws, ""))
    assert ws.closed is not None
    assert ws.closed[0] == 4403


def test_browser_one_time_token_allows_same_host_origin() -> None:
    token, _ = ws_tokens.mint_agent_shell_ws_token()
    ws = _FakeWebSocket(
        {
            "host": "127.0.0.1:8000",
            "origin": "http://127.0.0.1:3000",
        }
    )
    asyncio.run(agent_shell._authorize_agent_shell_ws(ws, token))

    # The capability is single-use.
    second = _FakeWebSocket(
        {
            "host": "127.0.0.1:8000",
            "origin": "http://127.0.0.1:3000",
        }
    )
    with pytest.raises(WebSocketDisconnect):
        asyncio.run(agent_shell._authorize_agent_shell_ws(second, token))


def test_cross_origin_browser_is_rejected_before_token_use() -> None:
    token, _ = ws_tokens.mint_agent_shell_ws_token()
    ws = _FakeWebSocket(
        {
            "host": "127.0.0.1:8000",
            "origin": "https://attacker.example",
        }
    )
    with pytest.raises(WebSocketDisconnect):
        asyncio.run(agent_shell._authorize_agent_shell_ws(ws, token))
    assert ws.closed is not None
    assert ws.closed[0] == 4403
    # Rejection happens before capability consumption.
    assert ws_tokens.consume_agent_shell_ws_token(token) is True


def test_agent_shell_token_store_stays_bounded_without_recursive_locking() -> None:
    minted = [ws_tokens.mint_agent_shell_ws_token()[0] for _ in range(400)]
    assert len(ws_tokens._store) <= ws_tokens._MAX_ACTIVE_TOKENS
    assert ws_tokens.consume_agent_shell_ws_token(minted[-1]) is True


def test_updater_refuses_same_release_checksum_as_sole_trust_root(tmp_path, monkeypatch) -> None:
    archive = tmp_path / "ShadowBroker_v9.9.9.zip"
    archive.write_bytes(b"archive-under-test")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    monkeypatch.delenv("MESH_UPDATE_SHA256", raising=False)
    monkeypatch.setattr(updater, "_load_baked_in_release_digests", lambda: {})
    monkeypatch.setattr(
        updater,
        "_fetch_sha256sums",
        lambda _url: {archive.name: digest},
    )

    with pytest.raises(RuntimeError, match="no independent archive digest"):
        updater._validate_zip_hash(
            str(archive),
            asset_name=archive.name,
            sha256sums_url="https://github.com/BigBodyCobain/Shadowbroker/releases/download/v9.9.9/SHA256SUMS.txt",
            release_tag="v9.9.9",
        )


def test_updater_accepts_preinstalled_baked_digest(tmp_path, monkeypatch) -> None:
    archive = tmp_path / "ShadowBroker_v9.9.9.zip"
    archive.write_bytes(b"trusted-archive")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    monkeypatch.delenv("MESH_UPDATE_SHA256", raising=False)
    monkeypatch.setattr(
        updater,
        "_load_baked_in_release_digests",
        lambda: {"v9.9.9": {archive.name: digest}},
    )

    note = updater._validate_zip_hash(
        str(archive),
        asset_name=archive.name,
        release_tag="v9.9.9",
    )
    assert "baked-in digest" in note
