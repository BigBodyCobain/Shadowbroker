"""Wormhole local agent — Reticulum-enabled mesh-only API server."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from services.wormhole_settings import read_wormhole_settings
from services.wormhole_status import write_wormhole_status


def _env_flag(name: str, default: str = "") -> bool:
    value = os.environ.get(name, default).strip().lower()
    return value in ("1", "true", "yes")


os.environ.setdefault("MESH_ONLY", "true")
os.environ.setdefault("MESH_RNS_ENABLED", "true")

HOST = os.environ.get("WORMHOLE_HOST", "127.0.0.1")
PORT = int(os.environ.get("WORMHOLE_PORT", "8787"))
RELOAD = _env_flag("WORMHOLE_RELOAD")

settings = read_wormhole_settings()
TRANSPORT = os.environ.get("WORMHOLE_TRANSPORT", "") or settings.get("transport", "direct")
SOCKS_PROXY = os.environ.get("WORMHOLE_SOCKS_PROXY", "") or settings.get("socks_proxy", "")
SOCKS_DNS = _env_flag("WORMHOLE_SOCKS_DNS", "true" if settings.get("socks_dns") else "false")
TRANSPORT_ACTIVE = "direct"
PROXY_ACTIVE = ""

if TRANSPORT.lower() in ("tor", "i2p", "mixnet") and SOCKS_PROXY:
    try:
        import socks  # type: ignore

        host, port_str = SOCKS_PROXY.split(":")
        socks.set_default_proxy(socks.SOCKS5, host, int(port_str), rdns=SOCKS_DNS)
        socket.socket = socks.socksocket  # type: ignore
        TRANSPORT_ACTIVE = TRANSPORT.lower()
        PROXY_ACTIVE = SOCKS_PROXY
        os.environ["WORMHOLE_TRANSPORT_ACTIVE"] = TRANSPORT_ACTIVE
        print(f"[*] Wormhole transport: {TRANSPORT} via SOCKS5 {SOCKS_PROXY}")
    except Exception as exc:
        print(f"[!] Wormhole transport init failed: {exc}")
        print("[!] Continuing without hidden transport.")
write_wormhole_status(
    reason="startup",
    transport=TRANSPORT,
    proxy=SOCKS_PROXY,
    transport_active=TRANSPORT_ACTIVE,
    proxy_active=PROXY_ACTIVE,
    restart=False,
    installed=True,
    configured=True,
    running=True,
    ready=False,
    pid=os.getpid(),
    started_at=int(time.time()),
    last_error="",
    privacy_level_effective=str(settings.get("privacy_profile", "default")),
)


def _watch_transport_settings() -> None:
    settings_path = Path(__file__).resolve().parent / "data" / "wormhole.json"
    last_mtime = settings_path.stat().st_mtime if settings_path.exists() else 0
    while True:
        time.sleep(2)
        try:
            current_mtime = settings_path.stat().st_mtime if settings_path.exists() else 0
            if current_mtime == last_mtime:
                continue
            last_mtime = current_mtime
            new_settings = read_wormhole_settings()
            new_transport = str(new_settings.get("transport", "direct"))
            new_proxy = str(new_settings.get("socks_proxy", ""))
            new_dns = "true" if bool(new_settings.get("socks_dns", True)) else "false"
            if (
                new_transport.lower() != TRANSPORT.lower()
                or new_proxy != SOCKS_PROXY
                or new_dns != ("true" if SOCKS_DNS else "false")
            ):
                print("[*] Wormhole transport settings changed — restarting agent to apply.")
                write_wormhole_status(
                    reason="transport_change",
                    transport=new_transport,
                    proxy=new_proxy,
                    transport_active="",
                    proxy_active="",
                    restart=True,
                    installed=True,
                    configured=True,
                    running=True,
                    ready=False,
                    pid=os.getpid(),
                    started_at=int(time.time()),
                    last_error="",
                    privacy_level_effective=str(new_settings.get("privacy_profile", "default")),
                )
                os.environ["WORMHOLE_TRANSPORT"] = new_transport
                os.environ["WORMHOLE_SOCKS_PROXY"] = new_proxy
                os.environ["WORMHOLE_SOCKS_DNS"] = new_dns
                os.execv(sys.executable, [sys.executable, __file__])
        except Exception:
            continue


if __name__ == "__main__":
    threading.Thread(target=_watch_transport_settings, daemon=True).start()
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=RELOAD,
        log_level="info",
    )
