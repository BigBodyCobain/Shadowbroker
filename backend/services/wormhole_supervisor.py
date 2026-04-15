from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from services.wormhole_settings import read_wormhole_settings
from services.wormhole_status import read_wormhole_status, write_wormhole_status

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_PROCESS: subprocess.Popen[str] | None = None
_STATE_CACHE: dict[str, Any] | None = None
_STATE_CACHE_TS = 0.0
_STATE_CACHE_TTL_S = 2.0
_ARTI_PROOF_CACHE: dict[str, Any] = {"port": 0, "ok": False, "ts": 0.0}
_ARTI_PROOF_CACHE_TTL_S = 30.0
_PRIVATE_CLEARNET_FALLBACK_WINDOW_S = 300.0

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
WORMHOLE_SCRIPT = BACKEND_DIR / "wormhole_server.py"
WORMHOLE_STDOUT = DATA_DIR / "wormhole_stdout.log"
WORMHOLE_STDERR = DATA_DIR / "wormhole_stderr.log"
WORMHOLE_HOST = "127.0.0.1"
WORMHOLE_PORT = 8787
_WORMHOLE_ENV_ALLOWLIST = {
    "APPDATA",
    "COMSPEC",
    "HOME",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "PYTHONHOME",
    "PYTHONIOENCODING",
    "PYTHONPATH",
    "PYTHONUTF8",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "SYSTEMROOT",
    "SystemRoot",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "VIRTUAL_ENV",
    "WINDIR",
}
_WORMHOLE_ENV_EXPLICIT = {
    "ADMIN_KEY",
    "ALLOW_INSECURE_ADMIN",
    "CORS_ORIGINS",
    "PUBLIC_API_KEY",
}


def transport_tier_from_state(state: dict[str, Any] | None) -> str:
    snapshot = state or {}
    if not bool(snapshot.get("configured")):
        return "public_degraded"
    if not bool(snapshot.get("ready")):
        return "public_degraded"
    arti = bool(snapshot.get("arti_ready"))
    rns = bool(snapshot.get("rns_ready"))
    if arti and rns:
        return "private_strong"
    if arti or rns:
        return "private_transitional"
    # Once Wormhole is configured and ready, the private lane is online for
    # transitional gate/chat use even if the strongest transports are still warming.
    return "private_transitional"


def _check_arti_ready() -> bool:
    from services.config import get_settings

    settings = get_settings()
    if not bool(settings.MESH_ARTI_ENABLED):
        return False
    socks_port = int(settings.MESH_ARTI_SOCKS_PORT or 9050)
    try:
        with socket.create_connection((WORMHOLE_HOST, socks_port), timeout=2.0) as sock:
            # SOCKS5 greeting: version 5, 1 auth method, no-auth.
            sock.sendall(b"\x05\x01\x00")
            response = sock.recv(2)
            if response != b"\x05\x00":
                logger.warning("Arti SOCKS5 handshake failed: unexpected response %r", response)
                return False
    except Exception as exc:
        logger.warning("Arti SOCKS check failed on port %s: %s", socks_port, exc)
        return False

    now = time.time()
    if (
        int(_ARTI_PROOF_CACHE.get("port", 0) or 0) == socks_port
        and (now - float(_ARTI_PROOF_CACHE.get("ts", 0.0) or 0.0)) < _ARTI_PROOF_CACHE_TTL_S
    ):
        return bool(_ARTI_PROOF_CACHE.get("ok"))

    try:
        import requests as _requests

        proxy = f"socks5h://127.0.0.1:{socks_port}"
        response = _requests.get(
            "https://check.torproject.org/api/ip",
            proxies={"http": proxy, "https": proxy},
            timeout=3.0,
            headers={"Accept": "application/json"},
        )
        payload = response.json() if response.ok else {}
        is_tor = bool(payload.get("IsTor")) or bool(payload.get("is_tor"))
        if not (response.ok and is_tor):
            logger.warning(
                "Arti Tor proof failed (status=%s is_tor=%s) — proxy is not trusted as Tor",
                getattr(response, "status_code", "unknown"),
                payload.get("IsTor", payload.get("is_tor")),
            )
            _ARTI_PROOF_CACHE.update({"port": socks_port, "ok": False, "ts": now})
            return False
        _ARTI_PROOF_CACHE.update({"port": socks_port, "ok": True, "ts": now})
        return True
    except Exception as exc:
        logger.warning("Arti Tor proof request failed on port %s: %s", socks_port, exc)
        _ARTI_PROOF_CACHE.update({"port": socks_port, "ok": False, "ts": now})
        return False


def get_transport_tier() -> str:
    return transport_tier_from_state(get_wormhole_state())


def _recent_private_clearnet_fallback_warning(now: float | None = None) -> dict[str, Any]:
    current = float(now if now is not None else time.time())
    try:
        from services.mesh.mesh_router import mesh_router
    except Exception:
        return {
            "recent_private_clearnet_fallback": False,
            "recent_private_clearnet_fallback_at": 0,
            "recent_private_clearnet_fallback_reason": "",
        }

    message_log = list(getattr(mesh_router, "message_log", ()) or ())
    for entry in reversed(message_log):
        routed_via = str(entry.get("routed_via", "") or "").strip().lower()
        trust_tier = str(entry.get("trust_tier", "") or "").strip().lower()
        ts = float(entry.get("timestamp", 0) or 0.0)
        if ts > 0 and (current - ts) > _PRIVATE_CLEARNET_FALLBACK_WINDOW_S:
            break
        if routed_via != "internet" or not trust_tier.startswith("private_"):
            continue
        return {
            "recent_private_clearnet_fallback": True,
            "recent_private_clearnet_fallback_at": int(ts) if ts > 0 else 0,
            "recent_private_clearnet_fallback_reason": (
                str(entry.get("route_reason", "") or "").strip()
                or "A private-tier payload recently used internet relay instead of a hidden transport."
            ),
        }

    return {
        "recent_private_clearnet_fallback": False,
        "recent_private_clearnet_fallback_at": 0,
        "recent_private_clearnet_fallback_reason": "",
    }


def _python_bin() -> str:
    venv_python = BACKEND_DIR / "venv" / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python3"
    )
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _wormhole_subprocess_env(
    settings: dict[str, Any],
    *,
    settings_obj: Any | None = None,
) -> dict[str, str]:
    snapshot = settings_obj
    if snapshot is None:
        from services.config import get_settings

        snapshot = get_settings()

    env: dict[str, str] = {}
    for key in _WORMHOLE_ENV_ALLOWLIST:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    for key, value in os.environ.items():
        if key.startswith("MESH_") or key in _WORMHOLE_ENV_EXPLICIT:
            env[key] = value
    env.update(
        {
            "MESH_ONLY": "true",
            "MESH_RNS_ENABLED": "true" if bool(getattr(snapshot, "MESH_RNS_ENABLED", False)) else "false",
            "WORMHOLE_TRANSPORT": str(settings.get("transport", "direct") or "direct"),
            "WORMHOLE_SOCKS_PROXY": str(settings.get("socks_proxy", "") or ""),
            "WORMHOLE_SOCKS_DNS": "true" if bool(settings.get("socks_dns", True)) else "false",
            "WORMHOLE_HOST": WORMHOLE_HOST,
            "WORMHOLE_PORT": str(WORMHOLE_PORT),
        }
    )
    return env


def _installed() -> bool:
    return Path(_python_bin()).exists() and WORMHOLE_SCRIPT.exists()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _probe_ready(timeout_s: float = 1.5) -> bool:
    try:
        with urlopen(f"http://{WORMHOLE_HOST}:{WORMHOLE_PORT}/api/health", timeout=timeout_s) as resp:
            return 200 <= getattr(resp, "status", 0) < 300
    except (URLError, OSError, TimeoutError):
        return False


def _probe_json(path: str, timeout_s: float = 1.5) -> dict[str, Any] | None:
    try:
        with urlopen(f"http://{WORMHOLE_HOST}:{WORMHOLE_PORT}{path}", timeout=timeout_s) as resp:
            if not (200 <= getattr(resp, "status", 0) < 300):
                return None
            payload = resp.read().decode("utf-8", errors="replace")
            data = json.loads(payload or "{}")
            return data if isinstance(data, dict) else None
    except (URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None


def _current_runtime_state() -> dict[str, Any]:
    settings = read_wormhole_settings()
    status = read_wormhole_status()
    running = False
    pid = int(status.get("pid", 0) or 0)
    if _PROCESS and _PROCESS.poll() is None:
        running = True
        pid = int(_PROCESS.pid or 0)
    elif _pid_alive(pid):
        running = True
    ready = running and _probe_ready()
    transport_active = status.get("transport_active", "") if ready else ""
    proxy_active = status.get("proxy_active", "") if ready else ""
    effective_transport = str(transport_active or settings.get("transport", "direct") or "direct").lower()
    from services.config import get_settings
    settings_obj = get_settings()
    arti_enabled = bool(settings_obj.MESH_ARTI_ENABLED)
    arti_ready = _check_arti_ready()
    if arti_ready:
        try:
            from services.mesh.mesh_router import mesh_router

            if mesh_router.tor_arti._consecutive_total_failures >= int(
                settings_obj.MESH_RELAY_MAX_FAILURES or 3
            ):
                logger.info(
                    "Arti SOCKS5 is up but transport has %d consecutive failures — marking degraded",
                    mesh_router.tor_arti._consecutive_total_failures,
                )
                arti_ready = False
        except Exception:
            logger.warning(
                "Failed to check tor_arti transport health — fail-closed, marking arti_ready=False"
            )
            arti_ready = False
    if arti_ready and not transport_active:
        transport_active = "tor_arti"
    if arti_ready:
        effective_transport = "tor_arti"
    rns_data = _probe_json("/api/mesh/rns/status", timeout_s=1.0) if ready else None
    rns_enabled = bool(rns_data.get("enabled")) if rns_data else False
    rns_ready = bool(rns_data.get("ready")) if rns_data else False
    rns_configured_peers = int(rns_data.get("configured_peers", 0) or 0) if rns_data else 0
    rns_active_peers = int(rns_data.get("active_peers", 0) or 0) if rns_data else 0
    rns_private_dm_direct_ready = (
        bool(rns_data.get("private_dm_direct_ready")) if rns_data else False
    )
    downgrade_warning = _recent_private_clearnet_fallback_warning()
    anonymous_mode = bool(settings.get("anonymous_mode"))
    anonymous_mode_ready = bool(
        anonymous_mode
        and settings.get("enabled")
        and ready
        and effective_transport in {"tor", "tor_arti", "i2p", "mixnet"}
    )
    snapshot = {
        "installed": _installed(),
        "configured": bool(settings.get("enabled")),
        "running": running,
        "ready": ready,
        "transport_configured": str(settings.get("transport", "direct") or "direct"),
        "transport_active": transport_active,
        "proxy_active": proxy_active,
        "last_error": str(status.get("last_error", "") or ""),
        "started_at": int(status.get("started_at", status.get("last_start", 0)) or 0),
        "pid": pid,
        "privacy_level_effective": str(settings.get("privacy_profile", "default") or "default"),
        "reason": str(status.get("reason", "") or ""),
        "last_restart": int(status.get("last_restart", 0) or 0),
        "last_start": int(status.get("last_start", 0) or 0),
        "transport": str(settings.get("transport", "direct") or "direct"),
        "proxy": str(settings.get("socks_proxy", "") or ""),
        "anonymous_mode": anonymous_mode,
        "anonymous_mode_ready": anonymous_mode_ready,
        "arti_ready": arti_ready,
        "arti_enabled": arti_enabled,
        "rns_enabled": rns_enabled,
        "rns_ready": rns_ready,
        "rns_configured_peers": rns_configured_peers,
        "rns_active_peers": rns_active_peers,
        "rns_private_dm_direct_ready": rns_private_dm_direct_ready,
        **downgrade_warning,
    }
    snapshot["transport_tier"] = transport_tier_from_state(snapshot)
    write_wormhole_status(
        installed=snapshot["installed"],
        configured=snapshot["configured"],
        running=snapshot["running"],
        ready=snapshot["ready"],
        pid=snapshot["pid"],
        started_at=snapshot["started_at"],
        last_error=snapshot["last_error"],
        privacy_level_effective=snapshot["privacy_level_effective"],
        transport=snapshot["transport"],
        proxy=snapshot["proxy"],
        transport_active=snapshot["transport_active"],
        proxy_active=snapshot["proxy_active"],
    )
    return snapshot


def _invalidate_state_cache() -> None:
    global _STATE_CACHE, _STATE_CACHE_TS
    _STATE_CACHE = None
    _STATE_CACHE_TS = 0.0


def _store_state_cache(snapshot: dict[str, Any]) -> dict[str, Any]:
    global _STATE_CACHE, _STATE_CACHE_TS
    _STATE_CACHE = dict(snapshot)
    _STATE_CACHE_TS = time.monotonic()
    return snapshot


def get_wormhole_state() -> dict[str, Any]:
    global _STATE_CACHE, _STATE_CACHE_TS
    with _LOCK:
        now = time.monotonic()
        if _STATE_CACHE is not None and (now - _STATE_CACHE_TS) < _STATE_CACHE_TTL_S:
            return dict(_STATE_CACHE)
        snapshot = _current_runtime_state()
        return _store_state_cache(snapshot)


def connect_wormhole(*, reason: str = "connect") -> dict[str, Any]:
    with _LOCK:
        _invalidate_state_cache()
        settings = read_wormhole_settings()
        if not settings.get("enabled"):
            settings = settings.copy()
            settings["enabled"] = True
        current = _current_runtime_state()
        if current["ready"]:
            return current
        if not current["installed"]:
            write_wormhole_status(
                reason=reason,
                installed=False,
                configured=True,
                running=False,
                ready=False,
                last_error="Wormhole runtime is not installed.",
                privacy_level_effective=str(settings.get("privacy_profile", "default")),
                transport=str(settings.get("transport", "direct")),
                proxy=str(settings.get("socks_proxy", "")),
            )
            return _current_runtime_state()

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        stdout = open(WORMHOLE_STDOUT, "a", encoding="utf-8")
        stderr = open(WORMHOLE_STDERR, "a", encoding="utf-8")
        from services.config import get_settings

        env = _wormhole_subprocess_env(settings, settings_obj=get_settings())
        kwargs: dict[str, Any] = {
            "cwd": str(BACKEND_DIR),
            "env": env,
            "stdout": stdout,
            "stderr": stderr,
            "text": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

        process = subprocess.Popen([_python_bin(), str(WORMHOLE_SCRIPT)], **kwargs)
        global _PROCESS
        _PROCESS = process
        started_at = int(time.time())
        write_wormhole_status(
            reason=reason,
            restart=False,
            installed=True,
            configured=True,
            running=True,
            ready=False,
            pid=int(process.pid or 0),
            started_at=started_at,
            last_error="",
            privacy_level_effective=str(settings.get("privacy_profile", "default")),
            transport=str(settings.get("transport", "direct")),
            proxy=str(settings.get("socks_proxy", "")),
        )

        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                err = f"Wormhole exited with code {process.returncode}."
                write_wormhole_status(
                    reason="crash",
                    installed=True,
                    configured=True,
                    running=False,
                    ready=False,
                    pid=0,
                    last_error=err,
                )
                return _store_state_cache(_current_runtime_state())
            if _probe_ready(timeout_s=0.75):
                write_wormhole_status(
                    reason=reason,
                    installed=True,
                    configured=True,
                    running=True,
                    ready=True,
                    pid=int(process.pid or 0),
                    started_at=started_at,
                    last_error="",
                    privacy_level_effective=str(settings.get("privacy_profile", "default")),
                    transport=str(settings.get("transport", "direct")),
                    proxy=str(settings.get("socks_proxy", "")),
                )
                break
            time.sleep(0.5)
        return _store_state_cache(_current_runtime_state())


def disconnect_wormhole(*, reason: str = "disconnect") -> dict[str, Any]:
    with _LOCK:
        _invalidate_state_cache()
        current = _current_runtime_state()
        pid = int(current.get("pid", 0) or 0)
        global _PROCESS
        if _PROCESS and _PROCESS.poll() is None:
            try:
                _PROCESS.terminate()
                _PROCESS.wait(timeout=5)
            except Exception:
                try:
                    _PROCESS.kill()
                except Exception:
                    pass
        elif _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        _PROCESS = None
        write_wormhole_status(
            reason=reason,
            running=False,
            ready=False,
            pid=0,
            transport_active="",
            proxy_active="",
            last_error="",
        )
        return _store_state_cache(_current_runtime_state())


def restart_wormhole(*, reason: str = "restart") -> dict[str, Any]:
    with _LOCK:
        _invalidate_state_cache()
        disconnect_wormhole(reason=f"{reason}_stop")
        write_wormhole_status(reason=reason, restart=True)
        return connect_wormhole(reason=reason)


def sync_wormhole_with_settings() -> dict[str, Any]:
    settings = read_wormhole_settings()
    if settings.get("enabled"):
        return connect_wormhole(reason="sync")
    return disconnect_wormhole(reason="sync_disabled")


def shutdown_wormhole_supervisor() -> None:
    disconnect_wormhole(reason="backend_shutdown")
