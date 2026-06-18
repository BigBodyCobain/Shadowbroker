"""Agent shell WebSocket auth regression tests (issue #407)."""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

if sys.platform == "win32":
    fcntl_stub = types.ModuleType("fcntl")
    fcntl_stub.ioctl = lambda *args, **kwargs: None
    sys.modules.setdefault("fcntl", fcntl_stub)
    termios_stub = types.ModuleType("termios")
    termios_stub.TIOCSWINSZ = 0
    termios_stub.TCSAFLUSH = 0
    sys.modules.setdefault("termios", termios_stub)
    pty_stub = types.ModuleType("pty")
    pty_stub.openpty = lambda: (0, 0)
    sys.modules["pty"] = pty_stub

from routers import agent_shell  # noqa: E402
from services.agent_shell_ws_token import (  # noqa: E402
    consume_agent_shell_ws_token,
    mint_agent_shell_ws_token,
    reset_agent_shell_ws_tokens_for_tests,
)


@pytest.fixture()
def shell_client():
    app = FastAPI()
    app.include_router(agent_shell.router)
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def _reset_ws_tokens():
    reset_agent_shell_ws_tokens_for_tests()
    yield
    reset_agent_shell_ws_tokens_for_tests()


class TestAgentShellWsTokenStore:
    def test_mint_and_consume_once(self):
        token, expires_in = mint_agent_shell_ws_token()
        assert expires_in > 0
        assert consume_agent_shell_ws_token(token) is True
        assert consume_agent_shell_ws_token(token) is False


class TestAgentShellWsTokenRoute:
    def test_loopback_can_mint_token(self, shell_client):
        transport = shell_client._transport
        transport.client = ("127.0.0.1", 12345)
        response = shell_client.post("/api/agent-shell/ws-token")
        assert response.status_code == 200
        body = response.json()
        assert body["token"]
        assert body["expires_in"] > 0

    def test_remote_caller_cannot_mint_token(self, shell_client):
        shell_client._transport.client = ("1.2.3.4", 12345)
        with patch("auth._current_admin_key", return_value="test-admin-key-32chars-xxxxxxxxxx"):
            response = shell_client.post("/api/agent-shell/ws-token")
        assert response.status_code == 403


class TestAgentShellWsAuthorization:
    def test_remote_peer_with_spoofed_host_is_denied(self, shell_client):
        shell_client._transport.client = ("1.2.3.4", 12345)
        with pytest.raises((WebSocketDisconnect, Exception)):
            with shell_client.websocket_connect(
                "/api/agent-shell/ws",
                headers={"host": "localhost:8000"},
            ) as ws:
                ws.receive_text()

    def test_remote_peer_with_spoofed_origin_is_denied(self, shell_client):
        shell_client._transport.client = ("1.2.3.4", 12345)
        with pytest.raises((WebSocketDisconnect, Exception)):
            with shell_client.websocket_connect(
                "/api/agent-shell/ws",
                headers={"origin": "http://localhost:3000"},
            ) as ws:
                ws.receive_text()

    def test_remote_peer_with_valid_ws_token_is_accepted(self, shell_client):
        shell_client._transport.client = ("127.0.0.1", 12345)
        token = shell_client.post("/api/agent-shell/ws-token").json()["token"]
        shell_client._transport.client = ("1.2.3.4", 12345)
        with patch("sys.platform", "win32"):
            with shell_client.websocket_connect(f"/api/agent-shell/ws?ws_token={token}") as ws:
                payload = ws.receive_json()
        assert payload["type"] == "error"
        assert "Windows" in payload["message"]

    def test_ws_token_is_single_use(self, shell_client):
        shell_client._transport.client = ("127.0.0.1", 12345)
        token = shell_client.post("/api/agent-shell/ws-token").json()["token"]
        shell_client._transport.client = ("1.2.3.4", 12345)
        with patch("sys.platform", "win32"):
            with shell_client.websocket_connect(f"/api/agent-shell/ws?ws_token={token}") as ws:
                ws.receive_json()
        with pytest.raises((WebSocketDisconnect, Exception)):
            with shell_client.websocket_connect(f"/api/agent-shell/ws?ws_token={token}") as ws:
                ws.receive_text()

    def test_loopback_peer_does_not_need_ws_token(self, shell_client):
        shell_client._transport.client = ("127.0.0.1", 12345)
        with patch("sys.platform", "win32"):
            with shell_client.websocket_connect("/api/agent-shell/ws") as ws:
                payload = ws.receive_json()
        assert payload["type"] == "error"
        assert "Windows" in payload["message"]

    @pytest.mark.asyncio
    async def test_authorize_rejects_spoofed_headers_without_token(self):
        ws = MagicMock()
        ws.client = MagicMock(host="1.2.3.4")
        ws.headers = {"host": "localhost:8000", "origin": "http://localhost:3000"}
        ws.close = AsyncMock()
        with pytest.raises(WebSocketDisconnect):
            await agent_shell._authorize_agent_shell_ws(ws)
