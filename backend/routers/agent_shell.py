"""Local-operator PTY WebSocket for the Mesh Chat agent shell."""

from __future__ import annotations

import asyncio
import fcntl
import hmac
import json
import logging
import os
import pty
import select
import signal
import struct
import sys
import termios
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from auth import (
    _current_admin_key,
    _debug_mode_enabled,
    _is_trusted_local_runtime_host,
    require_local_operator,
)
from services.agent_shell_settings import (
    get_agent_shell_settings,
    set_agent_shell_working_directory,
)
from services.agent_shell_ws_token import consume_agent_shell_ws_token, mint_agent_shell_ws_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agent-shell"])


class AgentShellSettingsUpdate(BaseModel):
    working_directory: str = Field(min_length=1)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


async def _authorize_agent_shell_ws(
    ws: WebSocket,
    admin_key_query: str = "",
    ws_token_query: str = "",
) -> None:
    host = (ws.client.host or "").lower() if ws.client else ""
    if _is_trusted_local_runtime_host(host) or (_debug_mode_enabled() and host == "test"):
        return
    if consume_agent_shell_ws_token(ws_token_query):
        return
    admin_key = _current_admin_key()
    presented = str(admin_key_query or ws.headers.get("x-admin-key", "") or "").strip()
    if admin_key and presented and hmac.compare_digest(presented.encode(), admin_key.encode()):
        return
    await ws.close(code=4403, reason="local operator access only")
    raise WebSocketDisconnect()


def _resolve_shell_cwd(requested: str) -> str:
    requested = str(requested or "").strip()
    if requested:
        resolved = os.path.abspath(os.path.expanduser(requested))
        if os.path.isdir(resolved):
            return resolved
    return get_agent_shell_settings()["working_directory"]


def _default_shell() -> str:
    if sys.platform == "win32":
        return os.environ.get("COMSPEC", "cmd.exe")
    return os.environ.get("SHELL", "/bin/bash")


async def _relay_pty(master_fd: int, proc: asyncio.subprocess.Process, ws: WebSocket) -> None:
    loop = asyncio.get_running_loop()
    while True:
        if proc.returncode is not None:
            break
        try:
            readable, _, _ = await loop.run_in_executor(
                None, lambda: select.select([master_fd], [], [], 0.05)
            )
        except Exception:
            break
        if master_fd in readable:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            await ws.send_bytes(chunk)
        try:
            message = await asyncio.wait_for(ws.receive(), timeout=0.05)
        except asyncio.TimeoutError:
            continue
        if message.get("type") == "websocket.disconnect":
            break
        if message.get("type") != "websocket.receive":
            continue
        if message.get("bytes"):
            os.write(master_fd, message["bytes"])
            continue
        text = message.get("text")
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            os.write(master_fd, text.encode("utf-8", errors="replace"))
            continue
        if payload.get("type") == "resize":
            rows = int(payload.get("rows") or 24)
            cols = int(payload.get("cols") or 80)
            _set_winsize(master_fd, max(rows, 2), max(cols, 2))


@router.get("/api/agent-shell/settings", dependencies=[Depends(require_local_operator)])
async def read_agent_shell_settings() -> dict[str, Any]:
    return get_agent_shell_settings()


@router.post("/api/agent-shell/ws-token", dependencies=[Depends(require_local_operator)])
async def mint_agent_shell_ws_token_route() -> dict[str, Any]:
    token, expires_in = mint_agent_shell_ws_token()
    return {"token": token, "expires_in": expires_in}


@router.put("/api/agent-shell/settings", dependencies=[Depends(require_local_operator)])
async def write_agent_shell_settings(body: AgentShellSettingsUpdate) -> dict[str, Any]:
    try:
        return set_agent_shell_working_directory(body.working_directory)
    except ValueError as exc:
        detail = str(exc)
        if detail == "working_directory_not_found":
            raise HTTPException(status_code=400, detail="Working directory does not exist") from exc
        raise HTTPException(status_code=400, detail="Working directory is required") from exc


@router.websocket("/api/agent-shell/ws")
async def agent_shell_websocket(
    ws: WebSocket,
    cwd: str = Query(default=""),
    cols: int = Query(default=80),
    rows: int = Query(default=24),
    admin_key: str = Query(default=""),
    ws_token: str = Query(default=""),
) -> None:
    await ws.accept()
    try:
        await _authorize_agent_shell_ws(ws, admin_key, ws_token)
    except WebSocketDisconnect:
        return

    if sys.platform == "win32":
        await ws.send_text(
            json.dumps(
                {
                    "type": "error",
                    "message": "Host PTY is not available on Windows backend builds yet. Use the ShadowBroker desktop app or run the backend in Docker/Linux for an embedded shell.",
                }
            )
        )
        await ws.close(code=1011)
        return

    shell_cwd = _resolve_shell_cwd(cwd)
    shell = _default_shell()
    master_fd, slave_fd = pty.openpty()
    _set_winsize(master_fd, max(rows, 2), max(cols, 2))

    env = os.environ.copy()
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLORTERM", "truecolor")
    home = shell_cwd if os.path.isdir(shell_cwd) else "/app"
    env["HOME"] = home
    env["USER"] = env.get("USER") or "operator"
    path_prefixes = [
        os.path.join(home, ".local", "bin"),
        os.path.join(home, ".hermes", "bin"),
    ]
    path = env.get("PATH", "")
    for prefix in path_prefixes:
        if os.path.isdir(prefix):
            path = f"{prefix}:{path}" if path else prefix
    env["PATH"] = path

    proc = await asyncio.create_subprocess_exec(
        shell,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=shell_cwd,
        env=env,
        preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    try:
        await _relay_pty(master_fd, proc, ws)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
