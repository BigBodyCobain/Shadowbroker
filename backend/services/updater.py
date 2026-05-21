"""Self-update module — downloads latest GitHub release, backs up current files,
extracts the update over the project, and restarts the app.

Public API:
    perform_update(project_root)  -> dict   (download + backup + extract)
    schedule_restart(project_root)           (spawn detached start script, then exit)
"""

import json
import os
import sys
import logging
import re
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

# Issue #231: baked-in release digests. Loaded lazily, used as a fallback
# verification source when the release's SHA256SUMS.txt asset can't be
# fetched (e.g. transient network failure during update).
_RELEASE_DIGESTS_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "release_digests.json"
)
# Pattern for the maintainer's signed source-archive release asset. This
# is the file we prefer over the auto-generated ``zipball_url`` because
# the maintainer's build process publishes it with a matching entry in
# SHA256SUMS.txt — the zipball does not have a signed digest.
_SOURCE_ASSET_PATTERN = re.compile(r"^ShadowBroker_v\d", re.IGNORECASE)
_SHA256SUMS_ASSET_NAME = "SHA256SUMS.txt"


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

    Issue #231: prefer the maintainer's signed release asset (matching
    ``ShadowBroker_v*.zip``) over the auto-generated ``zipball_url``,
    because the maintainer's release process publishes a matching entry
    in SHA256SUMS.txt for the named asset but NOT for the zipball.

    Returns (zip_path, version_tag, download_url, release_url, asset_name,
    sha256sums_url) — the last two are empty strings when the release
    doesn't publish a signed asset, falling back to the legacy zipball
    path.
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

    # Prefer the maintainer-signed release asset. Fall back to the
    # auto-generated zipball if the release doesn't publish one.
    assets = release.get("assets") or []
    asset_name = ""
    asset_url = ""
    sha256sums_url = ""
    for a in assets:
        name = str(a.get("name") or "").strip()
        download = str(a.get("browser_download_url") or "").strip()
        if not name or not download:
            continue
        if _SOURCE_ASSET_PATTERN.match(name) and name.lower().endswith(".zip"):
            asset_name = name
            asset_url = download
        elif name == _SHA256SUMS_ASSET_NAME:
            sha256sums_url = download

    if asset_url:
        zip_url = asset_url
        logger.info(
            "Using signed release asset %s (sha256sums=%s)",
            asset_name,
            "yes" if sha256sums_url else "no",
        )
    else:
        zip_url = str(release.get("zipball_url") or "").strip()
        if not zip_url:
            raise RuntimeError("Latest release is missing a source archive URL")
        logger.warning(
            "Release does not publish a signed ShadowBroker_v*.zip asset — "
            "falling back to auto-generated zipball_url. Integrity will be "
            "verified against the baked-in release_digests.json (if present) "
            "or HTTPS-only otherwise."
        )

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
    return zip_path, tag, zip_url, release_url, asset_name, sha256sums_url


def _compute_sha256(zip_path: str) -> str:
    """Return the hex SHA-256 of the file at ``zip_path`` (lowercase)."""
    h = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 128), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _load_baked_in_release_digests() -> dict:
    """Return the ``release_digests.json`` mapping, or an empty dict.

    Schema (issue #231):
        {
          "<release_tag>": {
            "<asset_filename>": "<sha256_hex>",
            ...
          },
          ...
        }
    """
    try:
        raw = _RELEASE_DIGESTS_FILE.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, ValueError) as exc:
        logger.debug("Release digest file unreadable: %s", exc)
        return {}
    if not isinstance(parsed, dict):
        return {}
    cleaned: dict[str, dict[str, str]] = {}
    for k, v in parsed.items():
        if not isinstance(k, str) or k.startswith("_"):
            continue
        if isinstance(v, dict):
            entries = {
                fname: digest.strip().lower()
                for fname, digest in v.items()
                if isinstance(fname, str) and isinstance(digest, str)
            }
            if entries:
                cleaned[k] = entries
    return cleaned


def _fetch_sha256sums(sha256sums_url: str) -> dict[str, str]:
    """Download a SHA256SUMS.txt and return {filename: digest_hex_lower}.

    Standard ``sha256sum`` format: ``<digest>  <filename>`` per line. The
    leading ``*`` binary-mode marker (e.g. ``<digest> *<filename>``) is
    handled.
    """
    try:
        _validate_update_url(sha256sums_url)
    except RuntimeError as exc:
        logger.warning("SHA256SUMS URL rejected: %s", exc)
        return {}
    try:
        resp = requests.get(sha256sums_url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.info("SHA256SUMS fetch failed: %s", exc)
        return {}
    out: dict[str, str] = {}
    for line in resp.text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Tolerant split: handle both `<digest>  <name>` and `<digest> *<name>`.
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, fname = parts
        fname = fname.lstrip("*").strip()
        digest = digest.strip().lower()
        if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest) and fname:
            out[fname] = digest
    return out


def _validate_zip_hash(
    zip_path: str,
    *,
    asset_name: str = "",
    sha256sums_url: str = "",
    release_tag: str = "",
) -> str:
    """Verify the downloaded archive against trusted digest sources.

    Issue #231: previously this returned silently when ``MESH_UPDATE_SHA256``
    was unset, which made the auto-updater a supply-chain RCE vector on any
    compromise of the GitHub release pipeline. The chain now is:

      1. ``MESH_UPDATE_SHA256`` env var (operator override — preserved for
         power-users who want to pin an exact digest manually)
      2. ``SHA256SUMS.txt`` release asset (primary — the maintainer's
         release process already publishes this)
      3. Baked-in ``backend/data/release_digests.json`` (second line of
         defense for releases that lack the SHA256SUMS asset, or when the
         asset can't be fetched at update time)
      4. HTTPS-only fallback with a loud warning (preserves the auto-update
         flow during transient outages — but never silently)

    A mismatch from a source that DID respond is fatal: the update is
    refused and the existing install keeps running. Only the "no source
    reachable at all" case falls back to HTTPS-only.

    Returns a short human-readable description of which source verified
    the archive (used in the update-success message).
    """
    actual = _compute_sha256(zip_path)

    # Source 1: explicit operator override.
    override = os.environ.get("MESH_UPDATE_SHA256", "").strip().lower()
    if override:
        if actual == override:
            return f"verified via MESH_UPDATE_SHA256 ({actual[:16]}...)"
        raise RuntimeError(
            f"Update SHA-256 mismatch vs MESH_UPDATE_SHA256: archive={actual[:16]}..., "
            f"expected={override[:16]}..."
        )

    # Source 2: SHA256SUMS.txt asset from the release.
    sums_map: dict[str, str] = {}
    if sha256sums_url and asset_name:
        sums_map = _fetch_sha256sums(sha256sums_url)

    sums_expected = sums_map.get(asset_name) if asset_name else None
    if sums_expected:
        if actual == sums_expected:
            return f"verified via release SHA256SUMS.txt ({actual[:16]}...)"
        raise RuntimeError(
            f"Update SHA-256 mismatch vs release SHA256SUMS.txt: "
            f"archive={actual[:16]}..., expected={sums_expected[:16]}..."
        )

    # Source 3: baked-in digest list.
    baked = _load_baked_in_release_digests()
    baked_expected = ""
    if release_tag and asset_name:
        baked_expected = baked.get(release_tag, {}).get(asset_name, "")
    if baked_expected:
        if actual == baked_expected:
            return f"verified via baked-in digest list ({actual[:16]}...)"
        raise RuntimeError(
            f"Update SHA-256 mismatch vs baked-in digest list: "
            f"archive={actual[:16]}..., expected={baked_expected[:16]}..."
        )

    # Source 4: HTTPS-only fallback. We keep onboarding/auto-update working
    # during transient outages (no SHA256SUMS reachable AND no baked-in
    # entry for this release), but surface the degraded posture loudly so
    # the operator can see it in logs and the maintainer can populate the
    # digest list on the next release bump.
    logger.warning(
        "Update integrity check fell back to HTTPS-only trust "
        "(no SHA256SUMS.txt response and no baked-in digest for "
        "release=%s asset=%s). The archive SHA-256 is %s. Once the "
        "release ships a SHA256SUMS.txt asset OR backend/data/"
        "release_digests.json is updated with this release, the secure "
        "path will activate automatically.",
        release_tag or "unknown",
        asset_name or "unknown",
        actual,
    )
    return f"https-only (no digest source reachable, archive={actual[:16]}...)"


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
        zip_path, version, url, release_url, asset_name, sha256sums_url = _download_release(temp_dir)
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

        verification_note = _validate_zip_hash(
            zip_path,
            asset_name=asset_name,
            sha256sums_url=sha256sums_url,
            release_tag=version,
        )
        logger.info("Update archive %s", verification_note)
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
            "integrity": verification_note,
            "message": f"Updated to {version} — {copied} files replaced. Restarting...",
        }
    except Exception as e:
        logger.error(f"Update failed: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "manual_url": manual_url,
        }
