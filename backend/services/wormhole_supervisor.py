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
from services.mesh.mesh_privacy_policy import transport_tier_from_state

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_PROCESS: subprocess.Popen[str] | None = None
_STATE_CACHE: dict[str, Any] | None = None
_STATE_CACHE_TS = 0.0
_STATE_CACHE_TTL_S = 2.0
_ARTI_PROOF_CACHE: dict[str, Any] = {"port": 0, "ok": False, "ts": 0.0}
_ARTI_PROOF_CACHE_TTL_S = 30.0
_ARTI_STATUS_CACHE: dict[str, Any] = {"port": 0, "ready": False, "ts": 0.0}
_ARTI_STATUS_FAIL_TTL_S = 4.0
_ARTI_PROBE_LOCK = threading.Lock()
_ARTI_SOCKS_FAILURES = 0
_ARTI_LAST_TOR_RECOVERY_TS = 0.0
_ARTI_TOR_RECOVERY_COOLDOWN_S = 45.0
_ARTI_SOCKS_CONNECT_TIMEOUT_S = 5.0
_PRIVATE_CLEARNET_FALLBACK_WINDOW_S = 300.0

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
VENV_MARKER = BACKEND_DIR / ".venv-dir"
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
    "PRIVACY_CORE_ALLOWED_SHA256",
    "PRIVACY_CORE_DEV_OVERRIDE",
    "PRIVACY_CORE_LIB",
    "PRIVACY_CORE_MIN_VERSION",
}

def invalidate_arti_ready_cache() -> None:
    _ARTI_PROOF_CACHE.update({"port": 0, "ok": False, "ts": 0.0})
    _ARTI_STATUS_CACHE.update({"port": 0, "ready": False, "ts": 0.0})


def _maybe_recover_tor_socks_transport(socks_port: int) -> None:
    global _ARTI_SOCKS_FAILURES, _ARTI_LAST_TOR_RECOVERY_TS

    _ARTI_SOCKS_FAILURES += 1
    if _ARTI_SOCKS_FAILURES < 3:
        return
    now = time.time()
    if (now - _ARTI_LAST_TOR_RECOVERY_TS) < _ARTI_TOR_RECOVERY_COOLDOWN_S:
        return
    _ARTI_LAST_TOR_RECOVERY_TS = now
    _ARTI_SOCKS_FAILURES = 0
    try:
        from services.tor_hidden_service import tor_service

        logger.warning(
            "Tor SOCKS on port %s is wedged — recycling Tor hidden service",
            socks_port,
        )
        tor_service.stop()
        tor_service.start(target_port=8000)
        invalidate_arti_ready_cache()
    except Exception as exc:
        logger.warning("Tor SOCKS recovery failed: %s", exc)


def _probe_arti_socks_ready(socks_port: int) -> bool:
    try:
        with socket.create_connection(
            (WORMHOLE_HOST, socks_port),
            timeout=_ARTI_SOCKS_CONNECT_TIMEOUT_S,
        ) as sock:
            sock.settimeout(_ARTI_SOCKS_CONNECT_TIMEOUT_S)
            sock.sendall(b"\x05\x01\x00")
            response = sock.recv(2)
            if response != b"\x05\x00":
                logger.warning("Arti SOCKS5 handshake failed: unexpected response %r", response)
                return False
    except Exception as exc:
        logger.warning("Arti SOCKS check failed on port %s: %s", socks_port, exc)
        return False
    return True


def _check_arti_ready(*, force: bool = False) -> bool:
    from services.config import get_settings

    settings = get_settings()
    if not bool(settings.MESH_ARTI_ENABLED):
        return False
    socks_port = int(settings.MESH_ARTI_SOCKS_PORT or 9050)
    now = time.time()
    if not force:
        if (
            int(_ARTI_STATUS_CACHE.get("port", 0) or 0) == socks_port
            and (now - float(_ARTI_STATUS_CACHE.get("ts", 0.0) or 0.0)) < _ARTI_STATUS_FAIL_TTL_S
        ):
            return bool(_ARTI_STATUS_CACHE.get("ready"))
        if (
            int(_ARTI_PROOF_CACHE.get("port", 0) or 0) == socks_port
            and bool(_ARTI_PROOF_CACHE.get("ok"))
            and (now - float(_ARTI_PROOF_CACHE.get("ts", 0.0) or 0.0)) < _ARTI_PROOF_CACHE_TTL_S
        ):
            return True

    with _ARTI_PROBE_LOCK:
        now = time.time()
        if not force:
            if (
                int(_ARTI_STATUS_CACHE.get("port", 0) or 0) == socks_port
                and (now - float(_ARTI_STATUS_CACHE.get("ts", 0.0) or 0.0)) < _ARTI_STATUS_FAIL_TTL_S
            ):
                return bool(_ARTI_STATUS_CACHE.get("ready"))
            if (
                int(_ARTI_PROOF_CACHE.get("port", 0) or 0) == socks_port
                and bool(_ARTI_PROOF_CACHE.get("ok"))
                and (now - float(_ARTI_PROOF_CACHE.get("ts", 0.0) or 0.0)) < _ARTI_PROOF_CACHE_TTL_S
            ):
                return True

        if not _probe_arti_socks_ready(socks_port):
            _ARTI_STATUS_CACHE.update({"port": socks_port, "ready": False, "ts": now})
            _maybe_recover_tor_socks_transport(socks_port)
            return False

        global _ARTI_SOCKS_FAILURES
        _ARTI_SOCKS_FAILURES = 0
        _ARTI_STATUS_CACHE.update({"port": socks_port, "ready": True, "ts": now})

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
                "Arti Tor proof failed (status=%s is_tor=%s)",
                getattr(response, "status_code", "unknown"),
                payload.get("IsTor", payload.get("is_tor")),
            )
            _ARTI_PROOF_CACHE.update({"port": socks_port, "ok": False, "ts": now})
            _ARTI_STATUS_CACHE.update({"port": socks_port, "ready": False, "ts": now})
            return False
        _ARTI_PROOF_CACHE.update({"port": socks_port, "ok": True, "ts": now})
        return True
    except Exception as exc:
        logger.warning(
            "Arti Tor proof request failed on port %s: %s — SOCKS is up, using Arti anyway",
            socks_port,
            exc,
        )
        _ARTI_PROOF_CACHE.update({"port": socks_port, "ok": True, "ts": now})
        return True


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
    candidate_dirs: list[Path] = []
    try:
        persisted = VENV_MARKER.read_text(encoding="utf-8").strip()
    except OSError:
        persisted = ""
    if persisted:
        persisted_dir = Path(persisted)
        if not persisted_dir.is_absolute():
            persisted_dir = BACKEND_DIR / persisted_dir
        candidate_dirs.append(persisted_dir)
    candidate_dirs.append(BACKEND_DIR / "venv")

    for venv_dir in candidate_dirs:
        venv_python = venv_dir / ("Scripts" if os.name == "nt" else "bin") / (
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
    if os.name == "nt":
        # Windows PIDs are reused and os.kill(pid, 0) is not a reliable
        # ownership check. A persisted wormhole_status.json PID from an older
        # run must never be treated as a process we own.
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except SystemError as exc:
        logger.warning("Wormhole supervisor PID probe failed for %s: %s", pid, exc)
        return False
    except Exception as exc:
        logger.warning("Unexpected Wormhole PID probe failure for %s: %s", pid, exc)
        return False
    return True


def _find_wormhole_server_pid() -> int:
    if os.name == "nt":
        return 0
    proc_dir = Path("/proc")
    if not proc_dir.exists():
        return 0
    current_pid = os.getpid()
    script_name = WORMHOLE_SCRIPT.name
    script_path = str(WORMHOLE_SCRIPT)
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == current_pid:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
        if script_path in cmdline or script_name in cmdline:
            return pid
    return 0


def _terminate_pid(pid: int, *, timeout_s: float = 5.0) -> None:
    if os.name == "nt" or pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        return
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.1)
    if _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def _trust_wormhole_file_ready(status: dict[str, Any] | None = None) -> bool:
    try:
        from services.config import get_settings

        if not bool(getattr(get_settings(), "MESH_WORMHOLE_TRUST_FILE_READY", False)):
            return False
    except Exception:
        return False
    snapshot = status if status is not None else read_wormhole_status()
    if not bool(snapshot.get("ready")):
        return False
    started_at = int(snapshot.get("started_at", 0) or 0)
    if started_at <= 0:
        return False
    return (time.time() - started_at) < 3600


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
    configured = bool(settings.get("enabled"))
    running = False
    ready = False
    pid = int(status.get("pid", 0) or 0)
    if not configured:
        # Disabled private transport must stay disabled even if a stale local
        # wormhole process is still answering on the health port. Public
        # MeshChat relies on this state to keep the MQTT and Wormhole lanes
        # mutually exclusive.
        pid = 0
        ready = False
    elif _PROCESS and _PROCESS.poll() is None:
        running = True
        pid = int(_PROCESS.pid or 0)
    else:
        if _pid_alive(pid):
            running = True
        else:
            discovered_pid = _find_wormhole_server_pid()
            if discovered_pid > 0:
                running = True
                pid = discovered_pid
        if not running and _probe_ready(timeout_s=0.35):
            running = True
            pid = 0
        if running and _trust_wormhole_file_ready(status):
            ready = True
        else:
            ready = running and _probe_ready()
    if not running:
        pid = 0
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
        and configured
        and ready
        and effective_transport in {"tor", "tor_arti", "i2p", "mixnet"}
    )
    snapshot = {
        "installed": _installed(),
        "configured": configured,
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
        try:
            from services.transport_lane_isolation import disable_public_mesh_lane

            disable_public_mesh_lane(reason=f"wormhole_{reason}")
        except Exception as exc:
            logger.warning("Failed to enforce public/private lane isolation during %s: %s", reason, exc)
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

        startup_deadline_s = float(os.environ.get("WORMHOLE_STARTUP_DEADLINE_S", "60") or 60)
        deadline = time.monotonic() + max(20.0, startup_deadline_s)
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
        status = read_wormhole_status()
        pid = int(status.get("pid", 0) or 0)
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
        if os.name != "nt":
            _terminate_pid(pid)
            discovered_pid = _find_wormhole_server_pid()
            if discovered_pid > 0 and discovered_pid != pid:
                _terminate_pid(discovered_pid)
        _PROCESS = None
        write_wormhole_status(
            reason=reason,
            configured=False,
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


def kickoff_wormhole_bootstrap(*, reason: str = "background_bootstrap") -> bool:
    def _run() -> None:
        try:
            connect_wormhole(reason=reason)
        except Exception:
            logger.debug("Background wormhole bootstrap failed", exc_info=True)

    threading.Thread(target=_run, daemon=True, name="wormhole-background-bootstrap").start()
    return True
