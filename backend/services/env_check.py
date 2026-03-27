"""Startup environment validation — called once in the FastAPI lifespan hook.

Ensures required env vars are present before the scheduler starts.
Logs warnings for optional keys that degrade functionality when missing.
Audits security-critical config for dangerous combinations.
"""

import os
import secrets
import sys
import time
import logging
from pathlib import Path
from services.config import get_settings

logger = logging.getLogger(__name__)

# Keys grouped by criticality
_REQUIRED = {
    # Empty for now — add keys here only if the app literally cannot function without them
}

_CRITICAL_WARN = {
    "ADMIN_KEY": "Authentication for /api/settings and /api/system/update — endpoints are UNPROTECTED without it!",
}

_OPTIONAL = {
    "AIS_API_KEY": "AIS vessel streaming (ships layer will be empty without it)",
    "OPENSKY_CLIENT_ID": "OpenSky OAuth2 — gap-fill flights in Africa/Asia/LatAm",
    "OPENSKY_CLIENT_SECRET": "OpenSky OAuth2 — gap-fill flights in Africa/Asia/LatAm",
    "LTA_ACCOUNT_KEY": "Singapore LTA traffic cameras (CCTV layer)",
    "PUBLIC_API_KEY": "Optional client auth for public endpoints (recommended for exposed deployments)",
}


def _invalid_dm_token_pepper_reason(value: str) -> str:
    raw = str(value or "").strip()
    lowered = raw.lower()
    if not raw:
        return "empty"
    if lowered in {"change-me", "changeme"}:
        return "placeholder"
    if len(raw) < 16:
        return "too short"
    return ""


def _invalid_peer_push_secret_reason(value: str) -> str:
    raw = str(value or "").strip()
    lowered = raw.lower()
    if not raw:
        return "empty"
    if lowered in {"change-me", "changeme"}:
        return "placeholder"
    if len(raw) < 16:
        return "too short"
    return ""


_PEPPER_FILE = Path(__file__).resolve().parents[1] / "data" / "dm_token_pepper.key"


def _ensure_dm_token_pepper(settings) -> str:
    token_pepper = str(getattr(settings, "MESH_DM_TOKEN_PEPPER", "") or "").strip()
    pepper_reason = _invalid_dm_token_pepper_reason(token_pepper)
    if not pepper_reason:
        return token_pepper

    # Try loading a previously persisted pepper before generating a new one.
    try:
        from services.mesh.mesh_secure_storage import read_secure_json

        stored = read_secure_json(_PEPPER_FILE, lambda: {})
        stored_pepper = str(stored.get("pepper", "") or "").strip()
        if stored_pepper and not _invalid_dm_token_pepper_reason(stored_pepper):
            os.environ["MESH_DM_TOKEN_PEPPER"] = stored_pepper
            get_settings.cache_clear()
            logger.info("Loaded persisted DM token pepper from %s", _PEPPER_FILE.name)
            return stored_pepper
    except Exception:
        pass

    generated = secrets.token_hex(32)
    os.environ["MESH_DM_TOKEN_PEPPER"] = generated
    get_settings.cache_clear()
    log_fn = logger.warning if bool(getattr(settings, "MESH_DEBUG_MODE", False)) else logger.critical
    log_fn(
        "⚠️  SECURITY: MESH_DM_TOKEN_PEPPER is invalid (%s) — mailbox tokens "
        "would be predictably derivable. Auto-generated a random pepper for "
        "this session.",
        pepper_reason,
    )

    # Persist so the same pepper survives restarts.
    try:
        from services.mesh.mesh_secure_storage import write_secure_json

        _PEPPER_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_secure_json(_PEPPER_FILE, {"pepper": generated, "generated_at": int(time.time())})
        logger.info("Persisted auto-generated DM token pepper to %s", _PEPPER_FILE.name)
    except Exception:
        logger.warning("Could not persist auto-generated DM token pepper to disk — will regenerate on next restart")

    return generated


def _peer_push_secret_required(settings) -> bool:
    relay_peers = str(getattr(settings, "MESH_RELAY_PEERS", "") or "").strip()
    rns_peers = str(getattr(settings, "MESH_RNS_PEERS", "") or "").strip()
    return bool(getattr(settings, "MESH_RNS_ENABLED", False) or relay_peers or rns_peers)


def get_security_posture_warnings(settings=None) -> list[str]:
    snapshot = settings or get_settings()
    warnings: list[str] = []

    admin_key = str(getattr(snapshot, "ADMIN_KEY", "") or "").strip()
    allow_insecure = bool(getattr(snapshot, "ALLOW_INSECURE_ADMIN", False))
    if allow_insecure and not admin_key:
        warnings.append(
            "ALLOW_INSECURE_ADMIN=true with no ADMIN_KEY leaves admin and Wormhole endpoints unauthenticated."
        )

    if not bool(getattr(snapshot, "MESH_STRICT_SIGNATURES", True)):
        warnings.append(
            "MESH_STRICT_SIGNATURES=false is deprecated and ignored; signature enforcement remains mandatory."
        )

    peer_secret = str(getattr(snapshot, "MESH_PEER_PUSH_SECRET", "") or "").strip()
    peer_secret_reason = _invalid_peer_push_secret_reason(peer_secret)
    if _peer_push_secret_required(snapshot) and peer_secret_reason:
        warnings.append(
            "MESH_PEER_PUSH_SECRET is invalid "
            f"({peer_secret_reason}) while relay or RNS peers are enabled; private peer authentication, opaque gate forwarding, and voter blinding are not secure-by-default."
        )

    if os.name != "nt" and bool(getattr(snapshot, "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK", False)):
        warnings.append(
            "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true stores Wormhole keys in raw local files on this platform."
        )

    if bool(getattr(snapshot, "MESH_RNS_ENABLED", False)) and int(getattr(snapshot, "MESH_RNS_COVER_INTERVAL_S", 0) or 0) <= 0:
        warnings.append(
            "MESH_RNS_COVER_INTERVAL_S<=0 disables RNS cover traffic outside high-privacy mode, making quiet-node traffic analysis easier."
        )

    fallback_policy = str(getattr(snapshot, "MESH_PRIVATE_CLEARNET_FALLBACK", "block") or "block").strip().lower()
    if fallback_policy == "allow":
        warnings.append(
            "MESH_PRIVATE_CLEARNET_FALLBACK=allow — private-tier messages may fall back to clearnet relay when Tor/RNS is unavailable."
        )

    metadata_persist = bool(getattr(snapshot, "MESH_DM_METADATA_PERSIST", True))
    binding_ttl = int(getattr(snapshot, "MESH_DM_BINDING_TTL_DAYS", 7) or 7)
    if metadata_persist and binding_ttl > 14:
        warnings.append(
            f"MESH_DM_BINDING_TTL_DAYS={binding_ttl} with MESH_DM_METADATA_PERSIST=true — long-lived mailbox binding metadata persists communication graph structure on disk."
        )

    return warnings


def _audit_security_config(settings) -> None:
    """Audit security-critical config combinations and log loud warnings.

    This does not block startup (dev ergonomics), but makes dangerous
    settings impossible to miss in the logs.
    """
    # ── 1. ALLOW_INSECURE_ADMIN without ADMIN_KEY ─────────────────────
    admin_key = (getattr(settings, "ADMIN_KEY", "") or "").strip()
    allow_insecure = bool(getattr(settings, "ALLOW_INSECURE_ADMIN", False))
    if allow_insecure and not admin_key:
        logger.critical(
            "🚨 SECURITY: ALLOW_INSECURE_ADMIN=true with no ADMIN_KEY — "
            "ALL admin/wormhole endpoints are completely unauthenticated. "
            "This is acceptable ONLY for local development. "
            "Set ADMIN_KEY for any networked or production deployment."
        )

    # ── 2. Signature enforcement ──────────────────────────────────────
    mesh_strict = bool(getattr(settings, "MESH_STRICT_SIGNATURES", True))
    if not mesh_strict:
        logger.warning(
            "⚠️  CONFIG: MESH_STRICT_SIGNATURES=false is deprecated and ignored — "
            "runtime signature enforcement remains mandatory."
        )

    # ── 3. Empty DM token pepper ──────────────────────────────────────
    _ensure_dm_token_pepper(settings)

    # ── 4. Peer push secret / private-plane integrity ─────────────────
    peer_secret = str(getattr(settings, "MESH_PEER_PUSH_SECRET", "") or "").strip()
    peer_secret_reason = _invalid_peer_push_secret_reason(peer_secret)
    if _peer_push_secret_required(settings) and peer_secret_reason:
        log_fn = logger.warning if bool(getattr(settings, "MESH_DEBUG_MODE", False)) else logger.critical
        log_fn(
            "⚠️  SECURITY: MESH_PEER_PUSH_SECRET is invalid (%s) while relay or RNS peers are enabled — "
            "private peer authentication, opaque gate forwarding, and voter blinding are not secure-by-default until it is set to a non-placeholder secret.",
            peer_secret_reason,
        )

    # ── 5. Raw secure-storage fallback on non-Windows ────────────────
    if os.name != "nt" and bool(getattr(settings, "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK", False)):
        log_fn = logger.warning if bool(getattr(settings, "MESH_DEBUG_MODE", False)) else logger.critical
        log_fn(
            "⚠️  SECURITY: MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true leaves Wormhole keys in raw local files. "
            "Use this only for development/CI until a native keyring provider is available."
        )

    # ── 6. Disabled cover traffic outside forced high-privacy mode ─────────
    if bool(getattr(settings, "MESH_RNS_ENABLED", False)) and int(getattr(settings, "MESH_RNS_COVER_INTERVAL_S", 0) or 0) <= 0:
        logger.warning(
            "⚠️  PRIVACY: MESH_RNS_COVER_INTERVAL_S<=0 disables background RNS cover traffic outside high-privacy mode. "
            "Quiet nodes become easier to fingerprint by silence and burst timing."
        )

    # ── 7. Clearnet fallback policy ──────────────────────────────────
    fallback_policy = str(getattr(settings, "MESH_PRIVATE_CLEARNET_FALLBACK", "block") or "block").strip().lower()
    if fallback_policy == "allow":
        logger.warning(
            "⚠️  PRIVACY: MESH_PRIVATE_CLEARNET_FALLBACK=allow — private-tier messages will fall "
            "back to clearnet relay when Tor/RNS is unavailable. Set to 'block' for safer defaults."
        )


def validate_env(*, strict: bool = True) -> bool:
    """Validate environment variables at startup.

    Args:
        strict: If True, exit the process on missing required keys.
                If False, only log errors (useful for tests).

    Returns:
        True if all required keys are present, False otherwise.
    """
    all_ok = True

    settings = get_settings()

    # Required keys — must be set
    for key, desc in _REQUIRED.items():
        value = getattr(settings, key, "")
        if isinstance(value, str):
            value = value.strip()
        if not value:
            logger.error(
                "❌ REQUIRED env var %s is not set. %s\n"
                "   Set it in .env or via Docker secrets (%s_FILE).",
                key,
                desc,
                key,
            )
            all_ok = False

    if not all_ok and strict:
        logger.critical("Startup aborted — required environment variables are missing.")
        sys.exit(1)

    # Critical-warn keys — app works but security/functionality is degraded
    for key, desc in _CRITICAL_WARN.items():
        value = getattr(settings, key, "")
        if isinstance(value, str):
            value = value.strip()
        if not value:
            allow_insecure = bool(getattr(settings, "ALLOW_INSECURE_ADMIN", False))
            logger.warning(
                "⚠️  ADMIN_KEY is not set%s — %s",
                " and ALLOW_INSECURE_ADMIN=true" if allow_insecure else "",
                desc,
            )
            if not allow_insecure:
                logger.critical(
                    "🔓 CRITICAL: env var %s is not set — this MUST be set in production.",
                    key,
                )

    # Optional keys — warn if missing
    for key, desc in _OPTIONAL.items():
        value = getattr(settings, key, "")
        if isinstance(value, str):
            value = value.strip()
        if not value:
            logger.warning("⚠️  Optional env var %s is not set — %s", key, desc)

    # ── Security posture audit ────────────────────────────────────────
    _audit_security_config(settings)

    if all_ok:
        logger.info("✅ Environment validation passed.")

    return all_ok
