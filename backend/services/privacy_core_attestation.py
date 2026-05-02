"""Authoritative privacy-core attestation policy.

This module classifies the loaded privacy-core artifact against an explicit
local trust policy. It does not mutate trust anchors automatically.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable

from services.privacy_core_client import PrivacyCoreClient

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_DEFAULT_MIN_VERSION = "0.1.0"


def candidate_library_paths() -> Iterable[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    for profile in ("debug", "release"):
        target_dir = repo_root.parent / "privacy-core" / "target" / profile
        yield target_dir / "privacy_core.dll"
        yield target_dir / "libprivacy_core.so"
        yield target_dir / "libprivacy_core.dylib"


def _parse_version_triplet(raw: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(str(raw or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _settings_snapshot(settings: Any | None = None) -> Any | None:
    if settings is not None:
        return settings
    try:
        from services.config import get_settings

        return get_settings()
    except Exception:
        return None


def _configured_min_version(settings: Any | None = None) -> str:
    snapshot = _settings_snapshot(settings)
    if snapshot is None:
        raw = os.environ.get("PRIVACY_CORE_MIN_VERSION", "")
    else:
        raw = getattr(snapshot, "PRIVACY_CORE_MIN_VERSION", "")
    value = str(raw or "").strip()
    return value or _DEFAULT_MIN_VERSION


def _configured_allowed_hashes(settings: Any | None = None) -> set[str]:
    snapshot = _settings_snapshot(settings)
    if snapshot is None:
        raw = os.environ.get("PRIVACY_CORE_ALLOWED_SHA256", "")
    else:
        raw = getattr(snapshot, "PRIVACY_CORE_ALLOWED_SHA256", "")
    allowed: set[str] = set()
    for item in str(raw or "").split(","):
        digest = item.strip().lower()
        if len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest):
            allowed.add(digest)
    return allowed


def _configured_development_override(settings: Any | None = None) -> bool:
    snapshot = _settings_snapshot(settings)
    if snapshot is None:
        raw = os.environ.get("PRIVACY_CORE_DEV_OVERRIDE", "")
        return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}
    return bool(getattr(snapshot, "PRIVACY_CORE_DEV_OVERRIDE", False))


def privacy_core_high_privacy_required(settings: Any | None = None) -> bool:
    snapshot = _settings_snapshot(settings)
    if snapshot is None:
        return False
    return bool(
        getattr(snapshot, "MESH_ARTI_ENABLED", False)
        or getattr(snapshot, "MESH_RNS_ENABLED", False)
    )


def _manifest_source(settings: Any | None = None) -> str:
    return "settings.PRIVACY_CORE_ALLOWED_SHA256" if _settings_snapshot(settings) is not None else "env.PRIVACY_CORE_ALLOWED_SHA256"


def _detail_for_state(
    state: str,
    *,
    available: bool,
    version: str,
    minimum_version: str,
    override_active: bool,
) -> str:
    if state == "attested_current":
        return "privacy-core version and trusted artifact hash are current"
    if state == "unattested_unenrolled":
        return "privacy-core loaded, but no trusted artifact hash enrollment is configured"
    if state == "attestation_mismatch":
        return "privacy-core loaded, but its artifact hash does not match the trusted enrollment"
    if state == "development_override":
        return "privacy-core development override is active; artifact trust is not attested"
    if not available:
        return "privacy-core could not be loaded"
    if not version:
        return "privacy-core version is unavailable"
    return (
        f"privacy-core version {version} is below the required minimum {minimum_version}"
        if _parse_version_triplet(version) is not None
        else "privacy-core version is stale or unknown"
    )


def privacy_core_attestation(settings: Any | None = None) -> dict[str, Any]:
    minimum_version = _configured_min_version(settings)
    allowed_hashes = _configured_allowed_hashes(settings)
    override_active = _configured_development_override(settings)
    manifest_source = _manifest_source(settings)

    try:
        client = PrivacyCoreClient.load()
        library_path = client.library_path.resolve()
        digest = hashlib.sha256(library_path.read_bytes()).hexdigest()
        version = str(client.version() or "").strip()
        parsed_version = _parse_version_triplet(version)
        parsed_minimum = _parse_version_triplet(minimum_version)
        version_known = parsed_version is not None
        version_pinned = parsed_minimum is not None
        version_ok = bool(version_known and version_pinned and parsed_version >= parsed_minimum)
        hash_pinned = bool(allowed_hashes)
        hash_ok = digest in allowed_hashes if hash_pinned else False

        if override_active:
            attestation_state = "development_override"
        elif not version_ok:
            attestation_state = "attestation_stale_or_unknown"
        elif not hash_pinned:
            attestation_state = "unattested_unenrolled"
        elif hash_ok:
            attestation_state = "attested_current"
        else:
            attestation_state = "attestation_mismatch"

        detail = _detail_for_state(
            attestation_state,
            available=True,
            version=version,
            minimum_version=minimum_version,
            override_active=override_active,
        )
        return {
            "available": True,
            "version": version,
            "loaded_version": version,
            "library_path": str(library_path),
            "loaded_hash": digest,
            "library_sha256": digest,
            "minimum_version": minimum_version,
            "version_known": version_known,
            "version_pinned": version_pinned,
            "version_ok": version_ok,
            "hash_pinned": hash_pinned,
            "hash_ok": hash_ok,
            "policy_ok": attestation_state == "attested_current",
            "attestation_state": attestation_state,
            "trusted_hash": sorted(allowed_hashes)[0] if allowed_hashes else "",
            "trusted_hashes": sorted(allowed_hashes),
            "manifest_source": manifest_source,
            "enrollment_source": manifest_source,
            "override_active": override_active,
            "detail": detail,
        }
    except Exception as exc:
        detail = str(exc) or type(exc).__name__
        return {
            "available": False,
            "version": "",
            "loaded_version": "",
            "library_path": "",
            "loaded_hash": "",
            "library_sha256": "",
            "minimum_version": minimum_version,
            "version_known": False,
            "version_pinned": _parse_version_triplet(minimum_version) is not None,
            "version_ok": False,
            "hash_pinned": bool(allowed_hashes),
            "hash_ok": False,
            "policy_ok": False,
            "attestation_state": "attestation_stale_or_unknown",
            "trusted_hash": sorted(allowed_hashes)[0] if allowed_hashes else "",
            "trusted_hashes": sorted(allowed_hashes),
            "manifest_source": manifest_source,
            "enrollment_source": manifest_source,
            "override_active": override_active,
            "detail": detail,
        }


def validate_privacy_core_startup(settings: Any | None = None) -> None:
    snapshot = _settings_snapshot(settings)
    if not privacy_core_high_privacy_required(snapshot):
        return

    attestation = privacy_core_attestation(snapshot)
    state = str(attestation.get("attestation_state", "") or "").strip()
    if state == "attested_current":
        return

    logger.critical(
        "privacy-core startup validation failed for private-lane startup: %s",
        str(attestation.get("detail", "") or state or "unknown validation failure"),
    )
    raise SystemExit(1)
