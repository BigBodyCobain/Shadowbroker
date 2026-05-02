"""Self-update module — downloads latest GitHub release, backs up current files,
extracts the update over the project, and restarts the app.

Public API:
    perform_update(project_root)  -> dict   (download + backup + extract)
    schedule_restart(project_root)           (spawn detached start script, then exit)
"""

import os
import sys
import logging
import shutil
import subprocess
import tempfile
import time
import zipfile
import hashlib
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

GITHUB_RELEASES_URL = "https://api.github.com/repos/BigBodyCobain/Shadowbroker/releases/latest"
GITHUB_RELEASES_PAGE_URL = "https://github.com/BigBodyCobain/Shadowbroker/releases/latest"
DOCKER_UPDATE_COMMANDS = (
    "docker compose pull && docker compose up -d"
)


def _is_docker() -> bool:
    """Detect if we're running inside a Docker container."""
    if os.path.isfile("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r") as f:
            return "docker" in f.read()
    except (FileNotFoundError, PermissionError):
        pass
    return os.environ.get("container") == "docker"
_EXPECTED_SHA256 = os.environ.get("MESH_UPDATE_SHA256", "").strip().lower()
_ALLOWED_UPDATE_HOSTS = {
    "api.github.com",
    "codeload.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
}

# ---------------------------------------------------------------------------
# Protected patterns — files/dirs that must NEVER be overwritten during update
# ---------------------------------------------------------------------------
_PROTECTED_DIRS = {
    "venv", "node_modules", ".next", "__pycache__", ".git", ".github", ".claude",
    "_domain_keys", "node-local", "gate_persona", "gate_session", "dm_alias",
    "root", "transport", "reputation",
}
_PROTECTED_EXTENSIONS = {".db", ".sqlite", ".key", ".pem", ".bin"}
_PROTECTED_NAMES = {
    ".env",
    "ais_cache.json",
    "carrier_cache.json",
    "geocode_cache.json",
    "infonet.json",
    "infonet.json.bak",
    "peer_store.json",
    "node.json",
    "wormhole.json",
    "wormhole_status.json",
    "wormhole_secure_store.key",
    "dm_token_pepper.key",
    "voter_blind_salt.bin",
    "reputation_ledger.json",
    "gates.json",
}


def _is_protected(rel_path: str) -> bool:
    """Return True if *rel_path* (forward-slash separated) should be skipped."""
    parts = rel_path.replace("\\", "/").split("/")
    name = parts[-1]

    # Check directory components
    for part in parts[:-1]:
        if part in _PROTECTED_DIRS:
            return True

    # Check filename
    if name in _PROTECTED_NAMES:
        return True
    _, ext = os.path.splitext(name)
    if ext.lower() in _PROTECTED_EXTENSIONS:
        return True

    return False


def _validate_update_url(url: str, *, allow_release_page: bool = False) -> str:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme != "https":
        raise RuntimeError("Updater refused a non-HTTPS release URL")
    if parsed.username or parsed.password:
        raise RuntimeError("Updater refused a credentialed release URL")
    if not host or host not in _ALLOWED_UPDATE_HOSTS:
        raise RuntimeError(f"Updater refused an untrusted release host: {host or 'unknown'}")
    if parsed.port not in (None, 443):
        raise RuntimeError("Updater refused a non-standard release port")
    if not allow_release_page and host == "github.com" and "/releases/" not in parsed.path:
        raise RuntimeError("Updater refused a non-release GitHub URL")
    return parsed.geturl()


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def _download_release(temp_dir: str) -> tuple:
    """Fetch latest release info and download the source zip archive.
    Returns (zip_path, version_tag, download_url, release_url).
    """
    logger.info("Fetching latest release info from GitHub...")
    _validate_update_url(GITHUB_RELEASES_URL)
    resp = requests.get(GITHUB_RELEASES_URL, timeout=15)
    resp.raise_for_status()
    _validate_update_url(resp.url)
    release = resp.json()

    tag = release.get("tag_name", "unknown")
    release_url = str(release.get("html_url") or GITHUB_RELEASES_PAGE_URL).strip()
    _validate_update_url(release_url, allow_release_page=True)
    zip_url = str(release.get("zipball_url") or "").strip()
    if not zip_url:
        raise RuntimeError("Latest release is missing a source archive URL")
    _validate_update_url(zip_url)

    logger.info(f"Downloading {zip_url} ...")
    zip_path = os.path.join(temp_dir, "update.zip")
    with requests.get(zip_url, stream=True, timeout=120) as dl:
        dl.raise_for_status()
        _validate_update_url(dl.url)
        with open(zip_path, "wb") as f:
            for chunk in dl.iter_content(chunk_size=1024 * 64):
                f.write(chunk)

    if not zipfile.is_zipfile(zip_path):
        raise RuntimeError("Downloaded file is not a valid ZIP archive")

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    logger.info(f"Downloaded {size_mb:.1f} MB — ZIP validated OK")
    return zip_path, tag, zip_url, release_url


def _validate_zip_hash(zip_path: str) -> None:
    if not _EXPECTED_SHA256:
        return
    h = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 128), b""):
            h.update(chunk)
    digest = h.hexdigest().lower()
    if digest != _EXPECTED_SHA256:
        raise RuntimeError("Update SHA-256 mismatch")


def _is_source_checkout(project_root: str) -> bool:
    root = Path(project_root)
    return (root / "frontend").is_dir() and (root / "backend").is_dir()


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
def _backup_current(project_root: str, temp_dir: str) -> str:
    """Create a backup zip of backend/ and frontend/ in temp_dir."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(temp_dir, f"backup_{stamp}.zip")
    logger.info(f"Backing up current files to {backup_path} ...")

    dirs_to_backup = ["backend", "frontend"]
    count = 0

    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dir_name in dirs_to_backup:
            dir_path = os.path.join(project_root, dir_name)
            if not os.path.isdir(dir_path):
                continue
            for root, dirs, files in os.walk(dir_path):
                # Prune protected directories from walk
                dirs[:] = [d for d in dirs if d not in _PROTECTED_DIRS]
                for fname in files:
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, project_root)
                    if _is_protected(rel):
                        continue
                    try:
                        zf.write(full, rel)
                        count += 1
                    except (PermissionError, OSError) as e:
                        logger.warning(f"Backup skip (locked): {rel} — {e}")

    logger.info(f"Backup complete: {count} files archived")
    return backup_path


# ---------------------------------------------------------------------------
# Extract & Copy
# ---------------------------------------------------------------------------
def _extract_and_copy(zip_path: str, project_root: str, temp_dir: str) -> int:
    """Extract the update zip and copy files over the project, skipping protected files.
    Returns count of files copied.
    """
    extract_dir = os.path.join(temp_dir, "extracted")
    logger.info("Extracting update zip...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        extract_root = Path(extract_dir).resolve()
        for member in zf.infolist():
            try:
                target = (extract_root / member.filename).resolve()
            except OSError as exc:
                raise RuntimeError(f"Updater refused archive entry {member.filename}: {exc}") from exc
            try:
                target.relative_to(extract_root)
            except ValueError:
                raise RuntimeError(f"Updater refused archive path traversal entry: {member.filename}")
        zf.extractall(extract_dir)

    # Detect wrapper folder: if extracted root has a single directory that
    # itself contains frontend/ or backend/, use it as the real base.
    base = extract_dir
    entries = [e for e in os.listdir(base) if not e.startswith(".")]
    if len(entries) == 1:
        candidate = os.path.join(base, entries[0])
        if os.path.isdir(candidate):
            sub = os.listdir(candidate)
            if "frontend" in sub or "backend" in sub:
                base = candidate
                logger.info(f"Detected wrapper folder: {entries[0]}")

    copied = 0
    skipped = 0

    for root, dirs, files in os.walk(base):
        # Prune protected directories so os.walk never descends into them
        dirs[:] = [d for d in dirs if d not in _PROTECTED_DIRS]

        for fname in files:
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, base).replace("\\", "/")

            if _is_protected(rel):
                skipped += 1
                continue

            dst = os.path.abspath(os.path.join(project_root, rel))
            # Safety: never write outside the project root (zip path traversal)
            if not dst.startswith(os.path.abspath(project_root)):
                logger.warning(f"Safety skip (path traversal): {rel}")
                skipped += 1
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
            except (PermissionError, OSError) as e:
                logger.warning(f"Copy failed (skipping): {rel} — {e}")
                skipped += 1

    logger.info(f"Update applied: {copied} files copied, {skipped} skipped/protected")
    return copied


# ---------------------------------------------------------------------------
# Restart
# ---------------------------------------------------------------------------
def schedule_restart(project_root: str):
    """Spawn a detached process that re-runs start.bat / start.sh after a short
    delay, then forcefully exit the current Python process."""
    tmp = tempfile.mkdtemp(prefix="sb_restart_")

    if sys.platform == "win32":
        script = os.path.join(tmp, "restart.bat")
        with open(script, "w") as f:
            f.write("@echo off\n")
            f.write("timeout /t 3 /nobreak >nul\n")
            f.write(f'cd /d "{project_root}"\n')
            f.write("call start.bat\n")

        CREATE_NEW_PROCESS_GROUP = 0x00000200
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(
            ["cmd", "/c", script],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        script = os.path.join(tmp, "restart.sh")
        with open(script, "w") as f:
            f.write("#!/bin/bash\n")
            f.write("sleep 3\n")
            f.write(f'cd "{project_root}"\n')
            f.write("bash start.sh\n")
        os.chmod(script, 0o755)
        subprocess.Popen(
            ["bash", script],
            start_new_session=True,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    logger.info("Restart script spawned — exiting current process")
    os._exit(0)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def perform_update(project_root: str) -> dict:
    """Download the latest release, back up current files, and extract the update.

    Returns a dict with status info on success, or {"status": "error", "message": ...}
    on failure.  Does NOT trigger restart — caller should call schedule_restart()
    separately after the HTTP response has been sent.

    In Docker, file extraction is skipped because containers run from immutable
    images.  Instead the response tells the frontend to show pull instructions.
    """
    in_docker = _is_docker()
    temp_dir = tempfile.mkdtemp(prefix="sb_update_")
    manual_url = GITHUB_RELEASES_PAGE_URL
    try:
        zip_path, version, url, release_url = _download_release(temp_dir)
        manual_url = release_url or manual_url

        if in_docker:
            logger.info("Docker detected — skipping file extraction")
            return {
                "status": "docker",
                "version": version,
                "manual_url": manual_url,
                "release_url": release_url,
                "download_url": url,
                "docker_commands": DOCKER_UPDATE_COMMANDS,
                "message": (
                    f"Version {version} is available. "
                    "Docker containers must be updated by pulling the new images."
                ),
            }

        if not _is_source_checkout(project_root):
            logger.info("Non-source runtime detected — refusing in-place source update")
            return {
                "status": "manual",
                "version": version,
                "manual_url": manual_url,
                "release_url": release_url,
                "download_url": url,
                "message": (
                    "This runtime does not support in-place source updates. "
                    "Download the latest release package manually."
                ),
            }

        _validate_zip_hash(zip_path)
        backup_path = _backup_current(project_root, temp_dir)
        copied = _extract_and_copy(zip_path, project_root, temp_dir)

        return {
            "status": "ok",
            "version": version,
            "files_updated": copied,
            "backup_path": backup_path,
            "manual_url": manual_url,
            "release_url": release_url,
            "download_url": url,
            "message": f"Updated to {version} — {copied} files replaced. Restarting...",
        }
    except Exception as e:
        logger.error(f"Update failed: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "manual_url": manual_url,
        }
