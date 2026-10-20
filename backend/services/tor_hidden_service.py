"""Tor hidden-service auto-provisioner.

Manages a Tor hidden service that points to the local ShadowBroker backend.
Tor is started as a subprocess with a generated torrc. Windows source installs
can download the Tor Expert Bundle into backend/data without admin rights.
Docker images should already include the `tor` package.
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

# Bundled Tor install location (inside data dir so no admin rights are needed).
TOR_INSTALL_DIR = TOR_DIR / "tor_bin"

_STARTUP_TIMEOUT_S = 90
_POLL_INTERVAL_S = 1.0


def _arti_socks_port() -> int:
    from services.config import get_settings

    return int(get_settings().MESH_ARTI_SOCKS_PORT or 9050)


def _torrc_socks_line(socks_port: int) -> str:
    return f"SocksPort {socks_port}\n"


def _torrc_has_socks_port(socks_port: int) -> bool:
    if not TORRC_PATH.exists():
        return False
    return _torrc_socks_line(socks_port) in TORRC_PATH.read_text(encoding="utf-8")


def _local_socks_listening(socks_port: int) -> bool:
    return _local_socks_handshake_ready(socks_port, timeout=0.75)


def _local_socks_handshake_ready(socks_port: int, *, timeout: float = 5.0) -> bool:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", socks_port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"\x05\x01\x00")
            return sock.recv(2) == b"\x05\x00"
    except OSError:
        return False


def _write_torrc(*, target_port: int, socks_port: int) -> None:
    TOR_DIR.mkdir(parents=True, exist_ok=True)
    hidden_service_dir = TOR_DIR / "hidden_service"
    hidden_service_dir.mkdir(parents=True, exist_ok=True)
    torrc_content = (
        f"DataDirectory {TOR_DATA_DIR.as_posix()}\n"
        f"HiddenServiceDir {hidden_service_dir.as_posix()}\n"
        f"HiddenServicePort {target_port} 127.0.0.1:{target_port}\n"
        f"{_torrc_socks_line(socks_port)}"
        "Log notice stderr\n"
    )
    TORRC_PATH.write_text(torrc_content, encoding="utf-8")

# Windows x86_64 Tor Expert Bundle URLs. Keep a fallback so first-run
# onboarding does not break when Tor rotates point releases.
_TOR_EXPERT_BUNDLE_URLS = [
    "https://dist.torproject.org/torbrowser/15.0.11/tor-expert-bundle-windows-x86_64-15.0.11.tar.gz",
    "https://dist.torproject.org/torbrowser/15.0.8/tor-expert-bundle-windows-x86_64-15.0.8.tar.gz",
]


def _find_tor_binary() -> str | None:
    """Locate the tor binary on the system, including our bundled install."""
    bundled = TOR_INSTALL_DIR / "tor" / "tor.exe"
    if bundled.exists():
        return str(bundled)

    for sub in TOR_INSTALL_DIR.rglob("tor.exe"):
        return str(sub)

    tor = shutil.which("tor")
    if tor:
        return tor

    for candidate in [
        r"C:\Program Files\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
        r"C:\Program Files (x86)\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
        os.path.expanduser(r"~\Desktop\Tor Browser\Browser\TorBrowser\Tor\tor.exe"),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return None


# Baked-in expected digest list. Loaded lazily; populated by maintainers
# when a new Tor Expert Bundle URL is added to _TOR_EXPERT_BUNDLE_URLS.
# See issue #201 for rationale.
_TOR_DIGEST_FILE = Path(__file__).resolve().parent.parent / "data" / "tor_bundle_digests.json"
_DIGEST_PLACEHOLDER = "PLACEHOLDER_REPLACE_BEFORE_RELEASE"


def _load_baked_in_digests() -> dict[str, str]:
    """Return {url: expected_sha256_lower} for URLs we ship a known digest for.

    Entries whose value is the placeholder sentinel are filtered out — they
    represent versions the maintainer has not yet pinned, and we don't
    want to trust them via this layer.
    """
    if not _TOR_DIGEST_FILE.exists():
        return {}
    try:
        import json as _json
        raw = _json.loads(_TOR_DIGEST_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Tor bundle digests file unreadable: %s", exc)
        return {}
    result: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or k.startswith("_"):
            continue
        if not isinstance(v, str) or v == _DIGEST_PLACEHOLDER:
            continue
        result[k] = v.strip().lower()
    return result


def _verify_tor_bundle(archive_path: Path, bundle_url: str) -> tuple[bool, str]:
    """Verify the downloaded Tor bundle against any source we trust.

    Returns (verified, reason). The bundle is considered verified if EITHER:

      * The upstream ``.sha256sum`` file is reachable AND its digest matches
        what we just downloaded, OR
      * Our baked-in digest list (``backend/data/tor_bundle_digests.json``)
        contains this URL AND that digest matches.

    If both sources are unavailable (e.g. fresh checkout before the
    maintainer has populated the digest file AND the upstream
    ``.sha256sum`` is unreachable), we **fall back to HTTPS-only trust**
    with a warning so first-run onboarding does not break. As soon as the
    digest file is populated for a shipped Tor version, the secure path
    activates automatically — no operator action required.

    Issue #201.
    """
    import hashlib

    actual_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest().lower()

    # Source 1: upstream .sha256sum
    upstream_hash: str | None = None
    sha256_url = bundle_url + ".sha256sum"
    sha256_file = TOR_INSTALL_DIR / "sha256sum.txt"
    try:
        urlretrieve(sha256_url, str(sha256_file))
        upstream_hash = sha256_file.read_text().strip().split()[0].lower()
        sha256_file.unlink(missing_ok=True)
    except Exception as hash_err:
        logger.info("Tor bundle upstream .sha256sum unreachable: %s", hash_err)
        sha256_file.unlink(missing_ok=True)

    if upstream_hash and upstream_hash == actual_hash:
        return True, f"verified via upstream .sha256sum ({actual_hash[:16]}...)"

    # Source 2: baked-in digest list
    baked = _load_baked_in_digests()
    baked_hash = baked.get(bundle_url)
    if baked_hash and baked_hash == actual_hash:
        return True, f"verified via baked-in digest list ({actual_hash[:16]}...)"

    # If we got an upstream digest AND a baked-in digest AND neither
    # matched, the bundle is genuinely suspect — refuse it.
    if upstream_hash and baked_hash:
        return False, (
            f"SHA-256 mismatch: archive={actual_hash[:16]}..., "
            f"upstream={upstream_hash[:16]}..., baked={baked_hash[:16]}..."
        )
    if upstream_hash and upstream_hash != actual_hash:
        return False, (
            f"SHA-256 mismatch vs upstream: archive={actual_hash[:16]}..., "
            f"upstream={upstream_hash[:16]}..."
        )
    if baked_hash and baked_hash != actual_hash:
        return False, (
            f"SHA-256 mismatch vs baked-in digest: archive={actual_hash[:16]}..., "
            f"expected={baked_hash[:16]}..."
        )

    # Neither verification source available. This is the fallback path for
    # the case where the upstream .sha256sum is temporarily unreachable
    # AND the maintainer hasn't yet pinned this Tor version. Trust HTTPS
    # only (current behavior pre-#201) with a clear warning. Onboarding
    # works; once we populate the digest file, the secure path activates.
    logger.warning(
        "Tor bundle integrity check fell back to HTTPS-only trust "
        "(upstream .sha256sum unreachable AND no baked-in digest for %s). "
        "Add this URL's SHA-256 to backend/data/tor_bundle_digests.json "
        "to enable the secure path.",
        bundle_url,
    )
    return True, f"https-only (no digest source reachable, archive={actual_hash[:16]}...)"


def _extract_tor_bundle_safely(archive_path: Path, install_dir: Path) -> bool:
    """Extract a Tor Expert Bundle tar.gz safely.

    Issue #251: the previous extractor checked tarinfo.name against path
    traversal but never inspected tarinfo.linkname for symlink/hardlink
    members. Python 3.11's tarfile honors symlinks during extractall(),
    so a malicious archive could ship a member like::

        name     = "innocent.txt"          # passes the path check
        type     = SYMTYPE
        linkname = "C:\\Windows\\System32\\config\\system"

    and extractall() would then create that symlink. Subsequent reads
    of innocent.txt deference to a sensitive system file; subsequent
    writes corrupt one. Tor bundles never legitimately contain symlinks
    or hardlinks, so we refuse all link members categorically rather
    than trying to validate linkname targets (which has its own pitfalls
    around relative path resolution).

    Also refuses non-regular-non-directory members (devices, FIFOs,
    character/block special files) for completeness — none of those
    belong in a Tor Expert Bundle and accepting them is a category of
    bug we don't need to debug later.

    Returns True on success, False on rejection (and logs the reason).
    The caller is responsible for cleaning up the archive file.
    """
    import tarfile

    install_resolved = install_dir.resolve()

    try:
        with tarfile.open(str(archive_path), "r:gz") as tar:
            for member in tar.getmembers():
                # Reject anything that isn't a regular file or directory.
                # Symlinks (SYMTYPE) and hardlinks (LNKTYPE) are the
                # path-traversal vectors; the others (CHRTYPE, BLKTYPE,
                # FIFOTYPE, CONTTYPE) have no legitimate use in a Tor
                # Expert Bundle.
                if member.issym() or member.islnk():
                    logger.error(
                        "Tor bundle extraction blocked: link member %s -> %s "
                        "(symlinks/hardlinks are not allowed in Tor bundles; "
                        "this archive is malformed or hostile)",
                        member.name,
                        member.linkname,
                    )
                    return False
                if not (member.isfile() or member.isdir()):
                    logger.error(
                        "Tor bundle extraction blocked: unexpected member type "
                        "for %s (only regular files and directories are allowed)",
                        member.name,
                    )
                    return False

                # Path traversal check (preserves the original guard).
                try:
                    member_path = (install_dir / member.name).resolve()
                except OSError as exc:
                    logger.error(
                        "Tor bundle extraction blocked: cannot resolve member "
                        "path %s: %s",
                        member.name,
                        exc,
                    )
                    return False
                try:
                    member_path.relative_to(install_resolved)
                except ValueError:
                    logger.error(
                        "Tor bundle extraction blocked: path traversal on %s "
                        "(resolves to %s, outside install dir %s)",
                        member.name,
                        member_path,
                        install_resolved,
                    )
                    return False

            # All members validated — extract.
            tar.extractall(path=str(install_dir))
    except tarfile.TarError as exc:
        logger.error("Tor bundle extraction failed: malformed tar (%s)", exc)
        return False

    return True


def _auto_install_tor() -> str | None:
    """Install or download Tor when it is safe to do so."""
    if os.name != "nt":
        # In Docker this should already be baked into the image. For source
        # installs we avoid unattended sudo prompts from a web request path.
        logger.warning("Tor is not installed. Install the tor package or use the Docker image with Tor baked in.")
        return None

    TOR_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    for bundle_url in _TOR_EXPERT_BUNDLE_URLS:
        archive_path = TOR_INSTALL_DIR / "tor-expert-bundle.tar.gz"
        try:
            logger.info("Downloading Tor Expert Bundle over HTTPS from %s...", bundle_url)
            urlretrieve(bundle_url, str(archive_path))

            # Issue #201: multi-source verification. If neither upstream
            # .sha256sum nor a baked-in digest matches, we refuse this URL
            # and try the next one in _TOR_EXPERT_BUNDLE_URLS. If neither
            # source is reachable at all, we fall back to HTTPS-only trust
            # (current behavior) rather than blocking onboarding.
            verified, reason = _verify_tor_bundle(archive_path, bundle_url)
            if not verified:
                logger.error("Tor bundle verification failed for %s: %s", bundle_url, reason)
                archive_path.unlink(missing_ok=True)
                continue
            logger.info("Tor bundle %s", reason)

            logger.info("Download complete, extracting...")
            import tarfile

            if not _extract_tor_bundle_safely(archive_path, TOR_INSTALL_DIR):
                archive_path.unlink(missing_ok=True)
                return None

            archive_path.unlink(missing_ok=True)

            for p in TOR_INSTALL_DIR.rglob("tor.exe"):
                logger.info("Tor installed at: %s", p)
                return str(p)

            logger.error("tor.exe not found after extracting %s", bundle_url)
        except Exception as exc:
            logger.error("Failed to download/extract Tor from %s: %s", bundle_url, exc)
        finally:
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
            socks_port = _arti_socks_port()
            if self._running and self._process and self._process.poll() is None:
                if _torrc_has_socks_port(socks_port) and _local_socks_handshake_ready(socks_port, timeout=1.5):
                    return {
                        "ok": True,
                        "onion_address": self._onion_address,
                        "detail": "already running",
                    }
                logger.info(
                    "Tor is running without a ready SOCKS proxy on port %s — restarting",
                    socks_port,
                )
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

            self._error = ""
            tor_bin = _find_tor_binary()
            if not tor_bin:
                logger.info("Tor not found, attempting bootstrap...")
                tor_bin = _auto_install_tor()
            if not tor_bin:
                self._error = (
                    "Could not prepare Tor automatically. Check network access to dist.torproject.org "
                    "or install Tor, then try again."
                )
                return {"ok": False, "detail": self._error}

            TOR_DIR.mkdir(parents=True, exist_ok=True)
            TOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
            hidden_service_dir = TOR_DIR / "hidden_service"
            hidden_service_dir.mkdir(parents=True, exist_ok=True)

            if os.name != "nt":
                try:
                    os.chmod(str(hidden_service_dir), 0o700)
                    os.chmod(str(TOR_DATA_DIR), 0o700)
                except OSError:
                    pass

            # Mesh "Arti" transport uses Tor's local SOCKS proxy for .onion peers.
            # Always publish SocksPort — MESH_ARTI_ENABLED only gates callers, not Tor.
            _write_torrc(target_port=target_port, socks_port=socks_port)

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

            deadline = time.monotonic() + _STARTUP_TIMEOUT_S
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    stdout = self._process.stdout.read() if self._process.stdout else ""
                    self._error = f"Tor exited with code {self._process.returncode}"
                    if stdout:
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
                        if _local_socks_handshake_ready(socks_port, timeout=3.0):
                            logger.info(
                                "Tor hidden service ready: %s (SOCKS %s)",
                                self._onion_address,
                                socks_port,
                            )
                            return {
                                "ok": True,
                                "onion_address": self._onion_address,
                            }

                time.sleep(_POLL_INTERVAL_S)

            self._error = (
                f"Tor did not publish a ready hidden service and SOCKS proxy "
                f"on port {socks_port} within {_STARTUP_TIMEOUT_S}s"
            )
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
            return {"ok": True, "detail": "stopped"}


tor_service = TorHiddenService()
