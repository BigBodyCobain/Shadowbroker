"""Tor Hidden Service auto-provisioner.

Manages a Tor hidden service that points to the local ShadowBroker backend.
Tor is started as a subprocess with a generated torrc — no manual config needed.
Auto-installs the Tor Expert Bundle on Windows if not present.

Usage:
    from services.tor_hidden_service import tor_service
    status = tor_service.start()   # -> {"ok": True, "onion_address": "http://xxxx.onion:8000"}
    tor_service.stop()
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import urlretrieve

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
TOR_DIR = DATA_DIR / "tor_hidden_service"
TORRC_PATH = TOR_DIR / "torrc"
HOSTNAME_PATH = TOR_DIR / "hidden_service" / "hostname"
TOR_DATA_DIR = TOR_DIR / "data"
PIDFILE_PATH = TOR_DIR / "tor.pid"

# Bundled Tor install location (inside our data dir so no admin rights needed)
TOR_INSTALL_DIR = TOR_DIR / "tor_bin"

# How long to wait for Tor to generate the hostname file
_STARTUP_TIMEOUT_S = 90
_POLL_INTERVAL_S = 1.0

# Tor Expert Bundle download URL (Windows x86_64)
_TOR_EXPERT_BUNDLE_URL = "https://dist.torproject.org/torbrowser/15.0.8/tor-expert-bundle-windows-x86_64-15.0.8.tar.gz"


def _find_tor_binary() -> str | None:
    """Locate the tor binary on the system, including our bundled install."""
    # Check our bundled install first
    bundled = TOR_INSTALL_DIR / "tor" / "tor.exe"
    if bundled.exists():
        return str(bundled)
    # Also check for extracted layout variants
    for sub in TOR_INSTALL_DIR.rglob("tor.exe"):
        return str(sub)

    tor = shutil.which("tor")
    if tor:
        return tor
    # Common locations on Windows
    for candidate in [
        r"C:\Program Files\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
        r"C:\Program Files (x86)\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
        os.path.expanduser(r"~\Desktop\Tor Browser\Browser\TorBrowser\Tor\tor.exe"),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return None


def _auto_install_tor() -> str | None:
    """Download and extract the Tor Expert Bundle. Returns path to tor binary or None."""
    if os.name != "nt":
        # On Linux/Mac, try package manager
        try:
            if shutil.which("apt-get"):
                subprocess.run(["sudo", "apt-get", "install", "-y", "tor"], check=True, capture_output=True, timeout=120)
            elif shutil.which("brew"):
                subprocess.run(["brew", "install", "tor"], check=True, capture_output=True, timeout=120)
            elif shutil.which("pacman"):
                subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "tor"], check=True, capture_output=True, timeout=120)
            else:
                logger.warning("No supported package manager found for auto-install")
                return None
            return shutil.which("tor")
        except Exception as exc:
            logger.error("Failed to auto-install Tor via package manager: %s", exc)
            return None

    # Windows: download Tor Expert Bundle (no admin needed)
    TOR_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = TOR_INSTALL_DIR / "tor-expert-bundle.tar.gz"

    try:
        logger.info("Downloading Tor Expert Bundle over HTTPS from dist.torproject.org...")
        urlretrieve(_TOR_EXPERT_BUNDLE_URL, str(archive_path))

        # Verify SHA-256 of the downloaded archive
        sha256_url = _TOR_EXPERT_BUNDLE_URL + ".sha256sum"
        sha256_file = TOR_INSTALL_DIR / "sha256sum.txt"
        try:
            urlretrieve(sha256_url, str(sha256_file))
            expected_hash = sha256_file.read_text().strip().split()[0].lower()
            import hashlib
            actual_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest().lower()
            sha256_file.unlink(missing_ok=True)
            if actual_hash != expected_hash:
                logger.error("SHA-256 MISMATCH — download may be compromised! Expected %s, got %s", expected_hash, actual_hash)
                archive_path.unlink(missing_ok=True)
                return None
            logger.info("SHA-256 verified: %s", actual_hash[:16] + "...")
        except Exception as hash_err:
            # If we can't fetch the hash file, warn but proceed (HTTPS provides baseline integrity)
            logger.warning("Could not verify SHA-256 (hash file unavailable): %s — proceeding with HTTPS-only verification", hash_err)

        logger.info("Download complete, extracting...")

        # Extract .tar.gz with path traversal protection
        import tarfile
        with tarfile.open(str(archive_path), "r:gz") as tar:
            for member in tar.getmembers():
                member_path = (TOR_INSTALL_DIR / member.name).resolve()
                if not str(member_path).startswith(str(TOR_INSTALL_DIR.resolve())):
                    logger.error("Tar path traversal blocked: %s", member.name)
                    archive_path.unlink(missing_ok=True)
                    return None
            tar.extractall(path=str(TOR_INSTALL_DIR))

        # Clean up archive
        archive_path.unlink(missing_ok=True)

        # Find the tor.exe in extracted files
        for p in TOR_INSTALL_DIR.rglob("tor.exe"):
            logger.info("Tor installed at: %s", p)
            return str(p)

        logger.error("tor.exe not found after extraction")
        return None
    except Exception as exc:
        logger.error("Failed to download/extract Tor: %s", exc)
        archive_path.unlink(missing_ok=True)
        return None


class TorHiddenService:
    """Manages a Tor hidden service subprocess."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._onion_address: str = ""
        self._running = False
        self._error: str = ""

        # Check if we already have a hostname from a previous run
        if HOSTNAME_PATH.exists():
            try:
                hostname = HOSTNAME_PATH.read_text().strip()
                if hostname.endswith(".onion"):
                    self._onion_address = f"http://{hostname}:8000"
            except Exception:
                pass

    @property
    def onion_address(self) -> str:
        return self._onion_address

    @property
    def running(self) -> bool:
        with self._lock:
            if self._process and self._process.poll() is not None:
                self._running = False
                self._process = None
            return self._running

    @property
    def error(self) -> str:
        return self._error

    def status(self) -> dict:
        return {
            "ok": True,
            "running": self.running,
            "onion_address": self._onion_address,
            "tor_available": _find_tor_binary() is not None,
            "error": self._error,
            "has_previous_address": bool(self._onion_address and not self._running),
        }

    def start(self, target_port: int = 8000) -> dict:
        """Start Tor hidden service pointing to target_port on localhost."""
        with self._lock:
            if self._running and self._process and self._process.poll() is None:
                return {
                    "ok": True,
                    "onion_address": self._onion_address,
                    "detail": "already running",
                }

            self._error = ""
            tor_bin = _find_tor_binary()
            if not tor_bin:
                logger.info("Tor not found, attempting auto-install...")
                tor_bin = _auto_install_tor()
            if not tor_bin:
                self._error = "Failed to auto-install Tor. Please install it manually."
                return {"ok": False, "detail": self._error}

            # Create directories
            TOR_DIR.mkdir(parents=True, exist_ok=True)
            TOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
            hidden_service_dir = TOR_DIR / "hidden_service"
            hidden_service_dir.mkdir(parents=True, exist_ok=True)

            # On non-Windows, Tor requires strict permissions on HiddenServiceDir
            if os.name != "nt":
                try:
                    os.chmod(str(hidden_service_dir), 0o700)
                    os.chmod(str(TOR_DATA_DIR), 0o700)
                except OSError:
                    pass

            # Write torrc — enables both hidden service (inbound) and SOCKS proxy
            # (outbound) so the mesh/wormhole system can route node-to-node
            # traffic through Tor as well.
            torrc_content = (
                f"DataDirectory {TOR_DATA_DIR.as_posix()}\n"
                f"HiddenServiceDir {hidden_service_dir.as_posix()}\n"
                f"HiddenServicePort {target_port} 127.0.0.1:{target_port}\n"
                f"SocksPort 9050\n"
                f"Log notice stderr\n"
            )
            TORRC_PATH.write_text(torrc_content, encoding="utf-8")

            # Start Tor
            try:
                self._process = subprocess.Popen(
                    [tor_bin, "-f", str(TORRC_PATH)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self._running = True
                logger.info("Tor process started (PID %d)", self._process.pid)
            except Exception as exc:
                self._error = f"Failed to start Tor: {exc}"
                logger.error(self._error)
                return {"ok": False, "detail": self._error}

            # Wait for hostname file to appear
            deadline = time.monotonic() + _STARTUP_TIMEOUT_S
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    # Tor exited prematurely
                    stdout = self._process.stdout.read() if self._process.stdout else ""
                    self._error = f"Tor exited with code {self._process.returncode}"
                    if stdout:
                        # Get last few lines for error context
                        lines = stdout.strip().split("\n")
                        self._error += ": " + " | ".join(lines[-3:])
                    self._running = False
                    self._process = None
                    logger.error(self._error)
                    return {"ok": False, "detail": self._error}

                if HOSTNAME_PATH.exists():
                    hostname = HOSTNAME_PATH.read_text().strip()
                    if hostname.endswith(".onion"):
                        self._onion_address = f"http://{hostname}:8000"
                        logger.info("Tor hidden service ready: %s", self._onion_address)
                        return {
                            "ok": True,
                            "onion_address": self._onion_address,
                        }

                time.sleep(_POLL_INTERVAL_S)

            # Timeout
            self._error = f"Tor did not generate hostname within {_STARTUP_TIMEOUT_S}s"
            self.stop()
            return {"ok": False, "detail": self._error}

    def stop(self) -> dict:
        """Stop the Tor subprocess."""
        with self._lock:
            if self._process:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=10)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                self._process = None
            self._running = False
            # Keep the onion_address — it persists across restarts
            # since the key is stored in hidden_service_dir
            return {"ok": True, "detail": "stopped"}


# Singleton
tor_service = TorHiddenService()
