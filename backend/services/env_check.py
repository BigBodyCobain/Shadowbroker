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
import json
from pathlib import Path
from services.config import (
    backend_gate_decrypt_compat_effective,
    backend_gate_plaintext_compat_effective,
    gate_plaintext_persist_effective,
    gate_recovery_envelope_effective,
    get_settings,
    private_clearnet_fallback_effective,
    private_clearnet_fallback_requested,
)
from services.mesh.mesh_compatibility import (
    compat_dm_invite_import_override_active,
    legacy_dm1_override_active,
    legacy_dm_get_override_active,
    legacy_dm_signature_compat_override_active,
)
from services.release_profiles import profile_readiness_snapshot

logger = logging.getLogger(__name__)
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_RELEASE_ATTESTATION_PATH = _BACKEND_DIR / "data" / "release_attestation.json"

# Keys grouped by criticality
_REQUIRED = {
    # Empty for now — add keys here only if the app literally cannot function without them
}

_CRITICAL_WARN = {
    "ADMIN_KEY": "Authentication for /api/settings and /api/system/update — endpoints are UNPROTECTED without it!",
    "OPENSKY_CLIENT_ID": "OpenSky Network OAuth2 — REQUIRED for airplane telemetry. Without it the flights layer falls back to ADS-B-only with major gaps in Africa/Asia/LatAm. Free registration at opensky-network.org.",
    "OPENSKY_CLIENT_SECRET": "OpenSky Network OAuth2 — REQUIRED for airplane telemetry (paired with OPENSKY_CLIENT_ID).",
}

_OPTIONAL = {
    "AIS_API_KEY": "AIS vessel streaming (ships layer will be empty without it)",
    "LTA_ACCOUNT_KEY": "Singapore LTA traffic cameras (CCTV layer)",
    "PUBLIC_API_KEY": "Optional client auth for public endpoints (recommended for exposed deployments)",
}


_DEFAULT_MQTT_BROKER = "mqtt.meshtastic.org"
_DEFAULT_MQTT_USER = "meshdev"
_DEFAULT_MQTT_PASS = "large4cats"


def _release_attestation_status(snapshot) -> dict[str, str | bool]:
    explicit_raw = str(
        getattr(snapshot, "MESH_RELEASE_ATTESTATION_PATH", "") or ""
    ).strip()
    manual_flag = bool(
        getattr(snapshot, "MESH_RELEASE_DM_RELAY_SECURITY_SUITE_GREEN", False)
    )
    candidate = Path(explicit_raw) if explicit_raw else _DEFAULT_RELEASE_ATTESTATION_PATH
    if not candidate.is_absolute():
        candidate = _BACKEND_DIR / candidate

    if candidate.exists():
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("release attestation payload must be an object")
            return {
                "state": "file_ok",
                "path": str(candidate),
                "detail": "file-based release attestation present",
                "manual_env_active": manual_flag,
            }
        except Exception as exc:
            return {
                "state": "file_error",
                "path": str(candidate),
                "detail": str(exc) or type(exc).__name__,
                "manual_env_active": manual_flag,
            }

    if explicit_raw:
        return {
            "state": "file_missing",
            "path": str(candidate),
            "detail": "configured release attestation file is missing",
            "manual_env_active": manual_flag,
        }

    if manual_flag:
        return {
            "state": "env_only",
            "path": str(candidate),
            "detail": "manual operator attestation is active without a file-based artifact",
            "manual_env_active": manual_flag,
        }

    return {
        "state": "missing",
        "path": str(candidate),
        "detail": "no release attestation evidence is staged",
        "manual_env_active": manual_flag,
    }


def _release_attestation_warning(snapshot) -> str:
    status = _release_attestation_status(snapshot)
    state = str(status.get("state", "") or "").strip()
    path = str(status.get("path", "") or "").strip()
    if state == "file_error":
        return (
            "MESH_RELEASE_ATTESTATION_PATH points to an unreadable release attestation "
            f"({path}) — authenticated release_gate evidence is broken until CI/release "
            "stages a valid JSON artifact."
        )
    if state == "file_missing":
        return (
            "MESH_RELEASE_ATTESTATION_PATH is set but the release attestation file is missing "
            f"({path}) — authenticated release_gate evidence is blocked until the artifact is restored."
        )
    if state == "env_only":
        return (
            "MESH_RELEASE_DM_RELAY_SECURITY_SUITE_GREEN=true without a file-based release attestation "
            f"({path}) — authenticated release_gate is relying on a manual operator flag instead of CI/release evidence."
        )
    if state == "missing":
        return (
            "No file-based Sprint 8 release attestation is staged "
            f"({path}) — authenticated release_gate will stay blocked until CI/release evidence is present."
        )
    return ""


def validate_mesh_mqtt_psk(value: str) -> str | None:
    """Validate MESH_MQTT_PSK.  Returns an error string, or None if valid."""
    raw = str(value or "").strip()
    if not raw:
        return None  # empty means use default LongFast key
    try:
        decoded = bytes.fromhex(raw)
    except ValueError:
        return "not valid hex"
    if len(decoded) not in (16, 32):
        return f"decoded length is {len(decoded)} bytes, must be 16 or 32"
    return None


def _mqtt_startup_warnings(settings) -> list[str]:
    """Return warnings for risky MQTT broker/credential combinations."""
    warnings: list[str] = []
    broker = str(getattr(settings, "MESH_MQTT_BROKER", _DEFAULT_MQTT_BROKER) or _DEFAULT_MQTT_BROKER).strip()
    user = str(getattr(settings, "MESH_MQTT_USER", _DEFAULT_MQTT_USER) or _DEFAULT_MQTT_USER).strip()
    password = str(getattr(settings, "MESH_MQTT_PASS", _DEFAULT_MQTT_PASS) or _DEFAULT_MQTT_PASS).strip()
    psk_raw = str(getattr(settings, "MESH_MQTT_PSK", "") or "").strip()

    is_custom_broker = broker.lower() != _DEFAULT_MQTT_BROKER.lower()
    is_default_creds = (user == _DEFAULT_MQTT_USER and password == _DEFAULT_MQTT_PASS)
    is_default_psk = not psk_raw  # empty means default LongFast key

    if is_custom_broker and is_default_psk:
        warnings.append(
            f"MESH_MQTT_BROKER={broker} with default public LongFast PSK — "
            "traffic on this broker is decryptable by anyone with the firmware default key."
        )
    if is_custom_broker and is_default_creds:
        warnings.append(
            f"MESH_MQTT_BROKER={broker} with default public credentials (meshdev/large4cats) — "
            "consider using private credentials for a private broker."
        )
    return warnings


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


def _raw_secure_storage_fallback_requested(snapshot) -> bool:
    return os.name != "nt" and bool(
        getattr(snapshot, "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK", False)
    )


def _raw_secure_storage_fallback_acknowledged(snapshot) -> bool:
    return bool(getattr(snapshot, "MESH_ACK_RAW_FALLBACK_AT_OWN_RISK", False))


def _raw_secure_storage_fallback_missing_ack(snapshot) -> bool:
    return _raw_secure_storage_fallback_requested(snapshot) and not _raw_secure_storage_fallback_acknowledged(
        snapshot
    )


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


def _deprecated_get_security_posture_warnings(settings=None) -> list[str]:
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

    if _raw_secure_storage_fallback_missing_ack(snapshot):
        warnings.append(
            "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true without MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true "
            "stores Wormhole keys in raw local files on this platform and should not be used outside development/CI."
        )
    elif _raw_secure_storage_fallback_requested(snapshot):
        warnings.append(
            "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true with MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true "
            "stores Wormhole keys in raw local files on this platform."
        )

    if bool(getattr(snapshot, "MESH_RNS_ENABLED", False)) and int(getattr(snapshot, "MESH_RNS_COVER_INTERVAL_S", 0) or 0) <= 0:
        warnings.append(
            "MESH_RNS_COVER_INTERVAL_S<=0 disables RNS cover traffic outside high-privacy mode, making quiet-node traffic analysis easier."
        )

    fallback_requested = private_clearnet_fallback_requested(snapshot)
    fallback_effective = private_clearnet_fallback_effective(snapshot)
    fallback_ack = bool(getattr(snapshot, "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE", False))
    if fallback_requested == "allow" and not fallback_ack:
        warnings.append(
            "MESH_PRIVATE_CLEARNET_FALLBACK=allow without MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true — "
            "private-tier clearnet fallback remains blocked until you explicitly acknowledge the transport downgrade."
        )
    elif fallback_effective == "allow":
        warnings.append(
            "MESH_PRIVATE_CLEARNET_FALLBACK=allow with MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true — "
            "private-tier messages may fall back to clearnet relay when Tor/RNS is unavailable."
        )

    metadata_persist = bool(getattr(snapshot, "MESH_DM_METADATA_PERSIST", False))
    metadata_persist_ack = bool(getattr(snapshot, "MESH_DM_METADATA_PERSIST_ACKNOWLEDGE", False))
    binding_ttl = int(getattr(snapshot, "MESH_DM_BINDING_TTL_DAYS", 3) or 3)
    if metadata_persist and not metadata_persist_ack:
        warnings.append(
            "MESH_DM_METADATA_PERSIST=true without MESH_DM_METADATA_PERSIST_ACKNOWLEDGE=true — "
            "mailbox binding metadata will remain memory-only until you explicitly acknowledge the at-rest privacy tradeoff."
        )
    if metadata_persist and metadata_persist_ack and binding_ttl > 7:
        warnings.append(
            f"MESH_DM_BINDING_TTL_DAYS={binding_ttl} with MESH_DM_METADATA_PERSIST=true — long-lived mailbox binding metadata persists communication graph structure on disk."
        )

    if bool(getattr(snapshot, "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", False)):
        warnings.append(
            "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT=true â€” legacy/compat v1/v2 DM invites can still import. "
            "Prefer re-exporting current attested v3 invites and disable this migration escape hatch after cleanup."
        )
    if legacy_dm_get_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM_GET_UNTIL is active â€” GET /api/mesh/dm/poll and GET /api/mesh/dm/count remain enabled for migration. "
            "Disable it after older clients move to the signed mailbox-claim POST APIs."
        )
    if legacy_dm_get_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM_GET_UNTIL is active â€” GET /api/mesh/dm/poll and GET /api/mesh/dm/count remain enabled for migration. "
            "Disable it after older clients move to the signed mailbox-claim POST APIs."
        )
    if legacy_dm_get_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM_GET_UNTIL is active â€” GET /api/mesh/dm/poll and GET /api/mesh/dm/count remain enabled for migration. "
            "Disable it after older clients move to the signed mailbox-claim POST APIs."
        )
    if legacy_dm_signature_compat_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL is active â€” dm_message still accepts the legacy signature payload. "
            "Disable it after migration so modern DM fields stay fully signed."
        )

    gate_decrypt_requested = bool(getattr(snapshot, "MESH_GATE_BACKEND_DECRYPT_COMPAT", False))
    gate_decrypt_ack = bool(getattr(snapshot, "MESH_GATE_BACKEND_DECRYPT_COMPAT_ACKNOWLEDGE", False))
    if gate_decrypt_requested or gate_decrypt_ack:
        warnings.append(
            "MESH_GATE_BACKEND_DECRYPT_COMPAT / MESH_GATE_BACKEND_DECRYPT_COMPAT_ACKNOWLEDGE are deprecated and ignored â€” ordinary backend MLS gate decrypt stays retired; service-side decrypt is reserved for explicit recovery reads."
        )

    gate_plaintext_requested = bool(getattr(snapshot, "MESH_GATE_BACKEND_PLAINTEXT_COMPAT", False))
    gate_plaintext_ack = bool(getattr(snapshot, "MESH_GATE_BACKEND_PLAINTEXT_COMPAT_ACKNOWLEDGE", False))
    if gate_plaintext_requested or gate_plaintext_ack:
        warnings.append(
            "MESH_GATE_BACKEND_PLAINTEXT_COMPAT / MESH_GATE_BACKEND_PLAINTEXT_COMPAT_ACKNOWLEDGE are deprecated and ignored â€” ordinary backend gate compose/post stays retired; shipped gate clients keep plaintext local."
        )

    if bool(getattr(snapshot, "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", False)):
        warnings.append(
            "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT=true â€” legacy/compat v1/v2 DM invites can still import. "
            "Prefer re-exporting current attested v3 invites and disable this migration escape hatch after cleanup."
        )
    if legacy_dm_get_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM_GET_UNTIL is active â€” GET /api/mesh/dm/poll and GET /api/mesh/dm/count remain enabled for migration. "
            "Disable it after older clients move to the signed mailbox-claim POST APIs."
        )
    if legacy_dm_signature_compat_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL is active â€” dm_message still accepts the legacy signature payload. "
            "Disable it after migration so modern DM fields stay fully signed."
        )

    if legacy_dm_get_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM_GET_UNTIL is active â€” GET /api/mesh/dm/poll and GET /api/mesh/dm/count remain enabled for migration. "
            "Disable it after older clients move to the signed mailbox-claim POST APIs."
        )
    if legacy_dm_get_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM_GET_UNTIL is active â€” GET /api/mesh/dm/poll and GET /api/mesh/dm/count remain enabled for migration. "
            "Disable it after older clients move to the signed mailbox-claim POST APIs."
        )
    gate_recovery_envelope_requested = bool(getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE", False))
    gate_recovery_envelope_ack = bool(
        getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", False)
    )
    if gate_recovery_envelope_requested and not gate_recovery_envelope_ack:
        warnings.append(
            "MESH_GATE_RECOVERY_ENVELOPE_ENABLE=true without MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE=true â€” envelope_recovery and envelope_always gates remain disabled until you explicitly acknowledge the recovery-material privacy tradeoff."
        )
    elif gate_recovery_envelope_effective(snapshot):
        warnings.append(
            "MESH_GATE_RECOVERY_ENVELOPE_ENABLE=true with MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE=true â€” gates configured for envelope_recovery or envelope_always may retain recovery envelopes."
        )

    gate_recovery_envelope_requested = bool(getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE", False))
    gate_recovery_envelope_ack = bool(
        getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", False)
    )
    if gate_recovery_envelope_requested and not gate_recovery_envelope_ack:
        warnings.append(
            "MESH_GATE_RECOVERY_ENVELOPE_ENABLE=true without MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE=true â€” envelope_recovery and envelope_always gates remain disabled until you explicitly acknowledge the recovery-material privacy tradeoff."
        )
    elif gate_recovery_envelope_effective(snapshot):
        warnings.append(
            "MESH_GATE_RECOVERY_ENVELOPE_ENABLE=true with MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE=true â€” gates configured for envelope_recovery or envelope_always may retain recovery envelopes."
        )

    gate_recovery_envelope_requested = bool(
        getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE", False)
    )
    gate_recovery_envelope_ack = bool(
        getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", False)
    )
    if gate_recovery_envelope_requested and not gate_recovery_envelope_ack:
        warnings.append(
            "MESH_GATE_RECOVERY_ENVELOPE_ENABLE=true without MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE=true Ã¢â‚¬â€ envelope_recovery and envelope_always gates remain disabled until you explicitly acknowledge the recovery-material privacy tradeoff."
        )
    elif gate_recovery_envelope_effective(snapshot):
        warnings.append(
            "MESH_GATE_RECOVERY_ENVELOPE_ENABLE=true with MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE=true Ã¢â‚¬â€ gates configured for envelope_recovery or envelope_always may retain recovery envelopes."
        )

    gate_plaintext_persist_requested = bool(getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST", False))
    gate_plaintext_persist_ack = bool(
        getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE", False)
    )
    if gate_plaintext_persist_requested and not gate_plaintext_persist_ack:
        warnings.append(
            "MESH_GATE_PLAINTEXT_PERSIST=true without MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE=true â€” ordinary gate reads keep plaintext local/in-memory until you explicitly acknowledge durable at-rest retention."
        )
    elif gate_plaintext_persist_effective(snapshot):
        warnings.append(
            "MESH_GATE_PLAINTEXT_PERSIST=true with MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE=true â€” decrypted gate plaintext is retained on disk outside explicit recovery mode."
        )

    gate_plaintext_persist_requested = bool(getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST", False))
    gate_plaintext_persist_ack = bool(
        getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE", False)
    )
    if gate_plaintext_persist_requested and not gate_plaintext_persist_ack:
        warnings.append(
            "MESH_GATE_PLAINTEXT_PERSIST=true without MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE=true â€” ordinary gate reads keep plaintext local/in-memory until you explicitly acknowledge durable at-rest retention."
        )
    elif gate_plaintext_persist_effective(snapshot):
        warnings.append(
            "MESH_GATE_PLAINTEXT_PERSIST=true with MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE=true â€” decrypted gate plaintext is retained on disk outside explicit recovery mode."
        )

    gate_plaintext_persist_requested = bool(getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST", False))
    gate_plaintext_persist_ack = bool(
        getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE", False)
    )
    if gate_plaintext_persist_requested and not gate_plaintext_persist_ack:
        warnings.append(
            "MESH_GATE_PLAINTEXT_PERSIST=true without MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE=true â€” ordinary gate reads keep plaintext local/in-memory until you explicitly acknowledge durable at-rest retention."
        )
    elif gate_plaintext_persist_effective(snapshot):
        warnings.append(
            "MESH_GATE_PLAINTEXT_PERSIST=true with MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE=true â€” decrypted gate plaintext is retained on disk outside explicit recovery mode."
        )

    gate_recovery_envelope_requested = bool(
        getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE", False)
    )
    gate_recovery_envelope_ack = bool(
        getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", False)
    )
    if gate_recovery_envelope_requested and not gate_recovery_envelope_ack:
        warnings.append(
            "MESH_GATE_RECOVERY_ENVELOPE_ENABLE=true without MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE=true — envelope_recovery and envelope_always gates remain disabled until you explicitly acknowledge the recovery-material privacy tradeoff."
        )
    elif gate_recovery_envelope_effective(snapshot):
        warnings.append(
            "MESH_GATE_RECOVERY_ENVELOPE_ENABLE=true with MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE=true — gates configured for envelope_recovery or envelope_always may retain recovery envelopes."
        )

    release_attestation_warning = _release_attestation_warning(snapshot)
    if release_attestation_warning:
        warnings.append(release_attestation_warning)

    warnings.extend(_mqtt_startup_warnings(snapshot))

    return warnings


def _deprecated_audit_security_config(settings) -> None:
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
    if _raw_secure_storage_fallback_requested(settings):
        log_fn = logger.warning if bool(getattr(settings, "MESH_DEBUG_MODE", False)) else logger.critical
        if _raw_secure_storage_fallback_missing_ack(settings):
            log_fn(
                "⚠️  SECURITY: MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true without "
                "MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true leaves Wormhole keys in raw local files. "
                "Startup should fail closed outside tests until the operator explicitly acknowledges this risk."
            )
        else:
            log_fn(
                "⚠️  SECURITY: MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true with "
                "MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true leaves Wormhole keys in raw local files. "
                "Use this only for development/CI until a stronger local custody provider is configured."
            )

    # ── 6. Disabled cover traffic outside forced high-privacy mode ─────────
    if bool(getattr(settings, "MESH_RNS_ENABLED", False)) and int(getattr(settings, "MESH_RNS_COVER_INTERVAL_S", 0) or 0) <= 0:
        logger.warning(
            "⚠️  PRIVACY: MESH_RNS_COVER_INTERVAL_S<=0 disables background RNS cover traffic outside high-privacy mode. "
            "Quiet nodes become easier to fingerprint by silence and burst timing."
        )

    # ── 7. Clearnet fallback policy ──────────────────────────────────
    fallback_requested = private_clearnet_fallback_requested(settings)
    fallback_effective = private_clearnet_fallback_effective(settings)
    fallback_ack = bool(getattr(settings, "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE", False))
    if fallback_requested == "allow" and not fallback_ack:
        logger.warning(
            "⚠️  PRIVACY: MESH_PRIVATE_CLEARNET_FALLBACK=allow without "
            "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true — private-tier clearnet fallback remains blocked "
            "until you explicitly acknowledge the transport downgrade."
        )
    elif fallback_effective == "allow":
        logger.warning(
            "⚠️  PRIVACY: MESH_PRIVATE_CLEARNET_FALLBACK=allow with "
            "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true — private-tier messages will fall "
            "back to clearnet relay when Tor/RNS is unavailable. Set to 'block' for safer defaults."
        )

    # ── 8. MQTT broker / credential / PSK mismatch warnings ──────────
    if bool(getattr(settings, "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", False)):
        logger.warning(
            "âš ï¸  TRUST: MESH_ALLOW_COMPAT_DM_INVITE_IMPORT=true allows importing weaker legacy/compat v1/v2 DM invites. "
            "Re-export attested v3 invites and disable this migration escape hatch after cleanup."
        )
    if legacy_dm_signature_compat_override_active():
        logger.warning(
            "âš ï¸  TRUST: MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL is active and keeps dm_message legacy signature compatibility enabled. "
            "Disable it after migration so modern DM fields stay fully signed."
        )

    gate_decrypt_requested = bool(getattr(settings, "MESH_GATE_BACKEND_DECRYPT_COMPAT", False))
    gate_decrypt_ack = bool(getattr(settings, "MESH_GATE_BACKEND_DECRYPT_COMPAT_ACKNOWLEDGE", False))
    if gate_decrypt_requested or gate_decrypt_ack:
        logger.warning(
            "âš ï¸  PRIVACY: MESH_GATE_BACKEND_DECRYPT_COMPAT* is deprecated and ignored â€” ordinary backend MLS "
            "gate decrypt stays retired; service-side decrypt is reserved for explicit recovery reads."
        )
    gate_decrypt_requested = False
    gate_decrypt_ack = False
    gate_decrypt_effective = backend_gate_decrypt_compat_effective(settings)
    if gate_decrypt_requested and not gate_decrypt_ack:
        logger.warning(
            "⚠️  PRIVACY: MESH_GATE_BACKEND_DECRYPT_COMPAT=true without "
            "MESH_GATE_BACKEND_DECRYPT_COMPAT_ACKNOWLEDGE=true — ordinary backend MLS gate decrypt remains blocked "
            "until you explicitly acknowledge the operator-visible compatibility path."
        )
    elif gate_decrypt_effective:
        logger.warning(
            "⚠️  PRIVACY: MESH_GATE_BACKEND_DECRYPT_COMPAT=true — non-native runtimes may request service-side "
            "MLS gate decrypt, which weakens operator-resistance on that lane."
        )

    gate_plaintext_requested = bool(getattr(settings, "MESH_GATE_BACKEND_PLAINTEXT_COMPAT", False))
    gate_plaintext_ack = bool(getattr(settings, "MESH_GATE_BACKEND_PLAINTEXT_COMPAT_ACKNOWLEDGE", False))
    if gate_plaintext_requested or gate_plaintext_ack:
        logger.warning(
            "âš ï¸  PRIVACY: MESH_GATE_BACKEND_PLAINTEXT_COMPAT* is deprecated and ignored â€” ordinary backend gate "
            "compose/post stays retired; shipped gate clients keep plaintext local."
        )
    gate_plaintext_requested = False
    gate_plaintext_ack = False
    gate_plaintext_effective = backend_gate_plaintext_compat_effective(settings)
    if gate_plaintext_requested and not gate_plaintext_ack:
        logger.warning(
            "⚠️  PRIVACY: MESH_GATE_BACKEND_PLAINTEXT_COMPAT=true without "
            "MESH_GATE_BACKEND_PLAINTEXT_COMPAT_ACKNOWLEDGE=true — ordinary backend gate compose/post remains blocked "
            "until you explicitly acknowledge the plaintext compatibility path."
        )
    elif gate_plaintext_effective:
        logger.warning(
            "⚠️  PRIVACY: MESH_GATE_BACKEND_PLAINTEXT_COMPAT=true — non-native runtimes may submit gate plaintext "
            "to the backend for compose/post, which weakens operator-resistance on that lane."
        )

    for w in _mqtt_startup_warnings(settings):
        logger.warning("⚠️  MQTT: %s", w)


def _get_security_posture_warnings_legacy(settings=None) -> list[str]:
    """Return user-facing security posture warnings for current config."""
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

    if _raw_secure_storage_fallback_missing_ack(snapshot):
        warnings.append(
            "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true without MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true "
            "stores Wormhole keys in raw local files on this platform and should not be used outside development/CI."
        )
    elif _raw_secure_storage_fallback_requested(snapshot):
        warnings.append(
            "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true with MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true "
            "stores Wormhole keys in raw local files on this platform."
        )

    if os.name != "nt" and not str(getattr(snapshot, "MESH_SECURE_STORAGE_SECRET", "") or "").strip():
        if not bool(getattr(snapshot, "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK", False)):
            warnings.append(
                "MESH_SECURE_STORAGE_SECRET is not set on non-Windows — Wormhole secure storage will fail closed. "
                "Set MESH_SECURE_STORAGE_SECRET (or MESH_SECURE_STORAGE_SECRET_FILE for Docker secrets) to enable at-rest key protection."
            )

    if bool(getattr(snapshot, "MESH_RNS_ENABLED", False)) and int(getattr(snapshot, "MESH_RNS_COVER_INTERVAL_S", 0) or 0) <= 0:
        warnings.append(
            "MESH_RNS_COVER_INTERVAL_S<=0 disables RNS cover traffic outside high-privacy mode, making quiet-node traffic analysis easier."
        )

    fallback_requested = private_clearnet_fallback_requested(snapshot)
    fallback_effective = private_clearnet_fallback_effective(snapshot)
    fallback_ack = bool(getattr(snapshot, "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE", False))
    if fallback_requested == "allow" and not fallback_ack:
        warnings.append(
            "MESH_PRIVATE_CLEARNET_FALLBACK=allow without MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true — "
            "private-tier clearnet fallback remains blocked until you explicitly acknowledge the transport downgrade."
        )
    elif fallback_effective == "allow":
        warnings.append(
            "MESH_PRIVATE_CLEARNET_FALLBACK=allow with MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true — "
            "private-tier messages may fall back to clearnet relay when Tor/RNS is unavailable."
        )

    metadata_persist = bool(getattr(snapshot, "MESH_DM_METADATA_PERSIST", False))
    metadata_persist_ack = bool(getattr(snapshot, "MESH_DM_METADATA_PERSIST_ACKNOWLEDGE", False))
    binding_ttl = int(getattr(snapshot, "MESH_DM_BINDING_TTL_DAYS", 3) or 3)
    if metadata_persist and not metadata_persist_ack:
        warnings.append(
            "MESH_DM_METADATA_PERSIST=true without MESH_DM_METADATA_PERSIST_ACKNOWLEDGE=true — mailbox binding metadata will remain memory-only until you explicitly acknowledge the at-rest privacy tradeoff."
        )
    if metadata_persist and metadata_persist_ack:
        warnings.append(
            "MESH_DM_METADATA_PERSIST=true — DM request/self mailbox binding metadata will be written to disk for restart continuity."
        )
    if metadata_persist and metadata_persist_ack and binding_ttl > 7:
        warnings.append(
            f"MESH_DM_BINDING_TTL_DAYS={binding_ttl} with MESH_DM_METADATA_PERSIST=true — long-lived mailbox binding metadata persists communication graph structure on disk."
        )

    if bool(getattr(snapshot, "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", False)):
        warnings.append(
            "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT=true â€” legacy/compat v1/v2 DM invites can still import. "
            "Prefer re-exporting current attested v3 invites and disable this migration escape hatch after cleanup."
        )
    if legacy_dm_signature_compat_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL is active â€” dm_message still accepts the legacy signature payload. "
            "Disable it after migration so modern DM fields stay fully signed."
        )

    gate_plaintext_persist_requested = bool(getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST", False))
    gate_plaintext_persist_ack = bool(
        getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE", False)
    )
    if gate_plaintext_persist_requested and not gate_plaintext_persist_ack:
        warnings.append(
            "MESH_GATE_PLAINTEXT_PERSIST=true without MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE=true â€” ordinary gate reads keep plaintext local/in-memory until you explicitly acknowledge durable at-rest retention."
        )
    elif gate_plaintext_persist_effective(snapshot):
        warnings.append(
            "MESH_GATE_PLAINTEXT_PERSIST=true with MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE=true â€” decrypted gate plaintext is retained on disk outside explicit recovery mode."
        )

    release_attestation_warning = _release_attestation_warning(snapshot)
    if release_attestation_warning:
        warnings.append(release_attestation_warning)

    warnings.extend(_mqtt_startup_warnings(snapshot))

    return warnings


def get_security_posture_warnings(settings=None) -> list[str]:
    """Return user-facing security posture warnings for current config."""
    snapshot = settings or get_settings()
    warnings: list[str] = []
    release_profile = profile_readiness_snapshot(snapshot)
    profile_name = str(release_profile.get("profile", "dev") or "dev")
    for blocker in list(release_profile.get("blockers") or []):
        warnings.append(
            f"MESH_RELEASE_PROFILE={profile_name} blocks private/release claims: {blocker}."
        )

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

    if _raw_secure_storage_fallback_missing_ack(snapshot):
        warnings.append(
            "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true without MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true "
            "stores Wormhole keys in raw local files on this platform and should not be used outside development/CI."
        )
    elif _raw_secure_storage_fallback_requested(snapshot):
        warnings.append(
            "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true with MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true "
            "stores Wormhole keys in raw local files on this platform."
        )

    if os.name != "nt" and not str(getattr(snapshot, "MESH_SECURE_STORAGE_SECRET", "") or "").strip():
        if not bool(getattr(snapshot, "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK", False)):
            warnings.append(
                "MESH_SECURE_STORAGE_SECRET is not set on non-Windows — Wormhole secure storage will fail closed. "
                "Set MESH_SECURE_STORAGE_SECRET (or MESH_SECURE_STORAGE_SECRET_FILE for Docker secrets) to enable at-rest key protection."
            )

    if bool(getattr(snapshot, "MESH_RNS_ENABLED", False)) and int(getattr(snapshot, "MESH_RNS_COVER_INTERVAL_S", 0) or 0) <= 0:
        warnings.append(
            "MESH_RNS_COVER_INTERVAL_S<=0 disables RNS cover traffic outside high-privacy mode, making quiet-node traffic analysis easier."
        )

    fallback_requested = private_clearnet_fallback_requested(snapshot)
    fallback_effective = private_clearnet_fallback_effective(snapshot)
    fallback_ack = bool(getattr(snapshot, "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE", False))
    if fallback_requested == "allow" and not fallback_ack:
        warnings.append(
            "MESH_PRIVATE_CLEARNET_FALLBACK=allow without MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true — "
            "private-tier clearnet fallback remains blocked until you explicitly acknowledge the transport downgrade."
        )
    elif fallback_effective == "allow":
        warnings.append(
            "MESH_PRIVATE_CLEARNET_FALLBACK=allow with MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true — "
            "private-tier messages may fall back to clearnet relay when Tor/RNS is unavailable."
        )

    metadata_persist = bool(getattr(snapshot, "MESH_DM_METADATA_PERSIST", False))
    metadata_persist_ack = bool(getattr(snapshot, "MESH_DM_METADATA_PERSIST_ACKNOWLEDGE", False))
    binding_ttl = int(getattr(snapshot, "MESH_DM_BINDING_TTL_DAYS", 3) or 3)
    if metadata_persist and not metadata_persist_ack:
        warnings.append(
            "MESH_DM_METADATA_PERSIST=true without MESH_DM_METADATA_PERSIST_ACKNOWLEDGE=true — mailbox binding metadata will remain memory-only until you explicitly acknowledge the at-rest privacy tradeoff."
        )
    if metadata_persist and metadata_persist_ack:
        warnings.append(
            "MESH_DM_METADATA_PERSIST=true — DM request/self mailbox binding metadata will be written to disk for restart continuity."
        )
    if metadata_persist and metadata_persist_ack and binding_ttl > 7:
        warnings.append(
            f"MESH_DM_BINDING_TTL_DAYS={binding_ttl} with MESH_DM_METADATA_PERSIST=true — long-lived mailbox binding metadata persists communication graph structure on disk."
        )

    if compat_dm_invite_import_override_active():
        warnings.append(
            "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT_UNTIL is active — legacy/compat v1/v2 DM invites can still import. "
            "Prefer re-exporting current attested v3 invites and disable this migration escape hatch after cleanup."
        )
    if legacy_dm_get_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM_GET_UNTIL is active — GET /api/mesh/dm/poll and GET /api/mesh/dm/count remain enabled for migration. "
            "Disable it after clients leave the legacy pull path."
        )
    if legacy_dm_signature_compat_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL is active — dm_message still accepts the legacy signature payload. "
            "Disable it after migration so modern DM fields stay fully signed."
        )
    if legacy_dm1_override_active():
        warnings.append(
            "MESH_ALLOW_LEGACY_DM1_UNTIL is active — raw dm1 compose/decrypt remains enabled for migration. "
            "Disable it after peers move to MLS."
        )

    gate_recovery_envelope_requested = bool(
        getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE", False)
    )
    gate_recovery_envelope_ack = bool(
        getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", False)
    )
    if gate_recovery_envelope_requested and not gate_recovery_envelope_ack:
        warnings.append(
            "MESH_GATE_RECOVERY_ENVELOPE_ENABLE=true without MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE=true — envelope_recovery and envelope_always gates remain disabled until you explicitly acknowledge the recovery-material privacy tradeoff."
        )
    elif gate_recovery_envelope_effective(snapshot):
        warnings.append(
            "MESH_GATE_RECOVERY_ENVELOPE_ENABLE=true with MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE=true — gates configured for envelope_recovery or envelope_always may retain recovery envelopes."
        )

    gate_plaintext_persist_requested = bool(getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST", False))
    gate_plaintext_persist_ack = bool(
        getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE", False)
    )
    if gate_plaintext_persist_requested and not gate_plaintext_persist_ack:
        warnings.append(
            "MESH_GATE_PLAINTEXT_PERSIST=true without MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE=true — ordinary gate reads keep plaintext local/in-memory until you explicitly acknowledge durable at-rest retention."
        )
    elif gate_plaintext_persist_effective(snapshot):
        warnings.append(
            "MESH_GATE_PLAINTEXT_PERSIST=true with MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE=true — decrypted gate plaintext is retained on disk outside explicit recovery mode."
        )

    release_attestation_warning = _release_attestation_warning(snapshot)
    if release_attestation_warning:
        warnings.append(release_attestation_warning)

    warnings.extend(_mqtt_startup_warnings(snapshot))

    return warnings


def _audit_security_config(settings) -> None:
    """Audit security-critical config combinations and log loud warnings."""

    release_profile = profile_readiness_snapshot(settings)
    profile_name = str(release_profile.get("profile", "dev") or "dev")
    for blocker in list(release_profile.get("blockers") or []):
        logger.critical(
            "RELEASE PROFILE: MESH_RELEASE_PROFILE=%s is blocked by unsafe default: %s",
            profile_name,
            blocker,
        )

    admin_key = (getattr(settings, "ADMIN_KEY", "") or "").strip()
    allow_insecure = bool(getattr(settings, "ALLOW_INSECURE_ADMIN", False))
    if allow_insecure and not admin_key:
        logger.critical(
            "🚨 SECURITY: ALLOW_INSECURE_ADMIN=true with no ADMIN_KEY — "
            "ALL admin/wormhole endpoints are completely unauthenticated. "
            "This is acceptable ONLY for local development. "
            "Set ADMIN_KEY for any networked or production deployment."
        )

    mesh_strict = bool(getattr(settings, "MESH_STRICT_SIGNATURES", True))
    if not mesh_strict:
        logger.warning(
            "⚠️  CONFIG: MESH_STRICT_SIGNATURES=false is deprecated and ignored — "
            "runtime signature enforcement remains mandatory."
        )

    _ensure_dm_token_pepper(settings)

    peer_secret = str(getattr(settings, "MESH_PEER_PUSH_SECRET", "") or "").strip()
    peer_secret_reason = _invalid_peer_push_secret_reason(peer_secret)
    if _peer_push_secret_required(settings) and peer_secret_reason:
        log_fn = logger.warning if bool(getattr(settings, "MESH_DEBUG_MODE", False)) else logger.critical
        log_fn(
            "⚠️  SECURITY: MESH_PEER_PUSH_SECRET is invalid (%s) while relay or RNS peers are enabled — "
            "private peer authentication, opaque gate forwarding, and voter blinding are not secure-by-default until it is set to a non-placeholder secret.",
            peer_secret_reason,
        )

    if _raw_secure_storage_fallback_requested(settings):
        log_fn = logger.warning if bool(getattr(settings, "MESH_DEBUG_MODE", False)) else logger.critical
        if _raw_secure_storage_fallback_missing_ack(settings):
            log_fn(
                "⚠️  SECURITY: MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true without "
                "MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true leaves Wormhole keys in raw local files. "
                "Startup should fail closed outside tests until the operator explicitly acknowledges this risk."
            )
        else:
            log_fn(
                "⚠️  SECURITY: MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true with "
                "MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true leaves Wormhole keys in raw local files. "
                "Use this only for development/CI. Set MESH_SECURE_STORAGE_SECRET for production."
            )

    if os.name != "nt" and not str(getattr(settings, "MESH_SECURE_STORAGE_SECRET", "") or "").strip():
        if not bool(getattr(settings, "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK", False)):
            log_fn = logger.warning if bool(getattr(settings, "MESH_DEBUG_MODE", False)) else logger.critical
            log_fn(
                "⚠️  SECURITY: MESH_SECURE_STORAGE_SECRET is not set on non-Windows — "
                "Wormhole secure storage will fail closed. Set MESH_SECURE_STORAGE_SECRET "
                "(or MESH_SECURE_STORAGE_SECRET_FILE for Docker secrets) to enable at-rest key protection."
            )

    if bool(getattr(settings, "MESH_RNS_ENABLED", False)) and int(getattr(settings, "MESH_RNS_COVER_INTERVAL_S", 0) or 0) <= 0:
        logger.warning(
            "⚠️  PRIVACY: MESH_RNS_COVER_INTERVAL_S<=0 disables background RNS cover traffic outside high-privacy mode. "
            "Quiet nodes become easier to fingerprint by silence and burst timing."
        )

    fallback_requested = private_clearnet_fallback_requested(settings)
    fallback_effective = private_clearnet_fallback_effective(settings)
    fallback_ack = bool(getattr(settings, "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE", False))
    if fallback_requested == "allow" and not fallback_ack:
        logger.warning(
            "⚠️  PRIVACY: MESH_PRIVATE_CLEARNET_FALLBACK=allow without "
            "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true — private-tier clearnet fallback remains blocked "
            "until you explicitly acknowledge the transport downgrade."
        )
    elif fallback_effective == "allow":
        logger.warning(
            "⚠️  PRIVACY: MESH_PRIVATE_CLEARNET_FALLBACK=allow with "
            "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true — private-tier messages will fall "
            "back to clearnet relay when Tor/RNS is unavailable. Set to 'block' for safer defaults."
        )

    metadata_persist = bool(getattr(settings, "MESH_DM_METADATA_PERSIST", False))
    metadata_persist_ack = bool(getattr(settings, "MESH_DM_METADATA_PERSIST_ACKNOWLEDGE", False))
    binding_ttl = int(getattr(settings, "MESH_DM_BINDING_TTL_DAYS", 3) or 3)
    if metadata_persist and not metadata_persist_ack:
        logger.warning(
            "⚠️  PRIVACY: MESH_DM_METADATA_PERSIST=true without MESH_DM_METADATA_PERSIST_ACKNOWLEDGE=true — "
            "mailbox binding metadata will remain memory-only until you explicitly acknowledge the at-rest privacy tradeoff."
        )
    if metadata_persist and metadata_persist_ack:
        logger.warning(
            "⚠️  PRIVACY: MESH_DM_METADATA_PERSIST=true — DM request/self mailbox binding metadata "
            "will be written to disk for restart continuity. Leave this off unless you explicitly need it."
        )
    if metadata_persist and metadata_persist_ack and binding_ttl > 7:
        logger.warning(
            "⚠️  PRIVACY: MESH_DM_BINDING_TTL_DAYS=%s with MESH_DM_METADATA_PERSIST=true — long-lived "
            "mailbox binding metadata persists communication graph structure on disk.",
            binding_ttl,
        )

    for w in _mqtt_startup_warnings(settings):
        logger.warning("⚠️  MQTT: %s", w)

    if bool(getattr(settings, "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT", False)):
        logger.warning(
            "âš ï¸  TRUST: MESH_ALLOW_COMPAT_DM_INVITE_IMPORT=true allows importing weaker legacy/compat v1/v2 DM invites. "
            "Re-export attested v3 invites and disable this migration escape hatch after cleanup."
        )
    if legacy_dm_signature_compat_override_active():
        logger.warning(
            "âš ï¸  TRUST: MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL is active and keeps dm_message legacy signature compatibility enabled. "
            "Disable it after migration so modern DM fields stay fully signed."
        )
    release_attestation_warning = _release_attestation_warning(settings)
    if release_attestation_warning:
        logger.warning("âš ï¸  RELEASE: %s", release_attestation_warning)


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
            if key == "ADMIN_KEY" and allow_insecure:
                logger.critical(
                    "🔓 CRITICAL: %s is not set and ALLOW_INSECURE_ADMIN=True — "
                    "admin endpoints are open without authentication. %s",
                    key,
                    desc,
                )
            else:
                logger.warning(
                    "⚠️  %s is not set — %s",
                    key,
                    desc,
                )

    # Optional keys — warn if missing
    for key, desc in _OPTIONAL.items():
        value = getattr(settings, key, "")
        if isinstance(value, str):
            value = value.strip()
        if not value:
            logger.warning("⚠️  Optional env var %s is not set — %s", key, desc)

    # ── MESH_MQTT_PSK validation (fatal) ────────────────────────────
    psk_error = validate_mesh_mqtt_psk(str(getattr(settings, "MESH_MQTT_PSK", "") or ""))
    if psk_error:
        logger.error(
            "❌ MESH_MQTT_PSK is invalid: %s. "
            "Must be a hex string that decodes to exactly 16 or 32 bytes, or empty for the default LongFast key.",
            psk_error,
        )
        all_ok = False
        if strict:
            logger.critical("Startup aborted — MESH_MQTT_PSK validation failed.")
            sys.exit(1)

    # ── MESH_PEER_PUSH_SECRET with peers configured (fatal in strict) ──
    if _peer_push_secret_required(settings):
        peer_reason = _invalid_peer_push_secret_reason(
            str(getattr(settings, "MESH_PEER_PUSH_SECRET", "") or "")
        )
        if peer_reason:
            logger.error(
                "❌ MESH_PEER_PUSH_SECRET is invalid (%s) while relay or RNS "
                "peers are configured. Private peer authentication requires "
                "a valid secret (at least 16 non-placeholder characters).",
                peer_reason,
            )
            all_ok = False
            if strict:
                logger.critical(
                    "Startup aborted — MESH_PEER_PUSH_SECRET is required "
                    "when MESH_RELAY_PEERS or MESH_RNS_PEERS are configured."
                )
                sys.exit(1)

    # ── Security posture audit ────────────────────────────────────────
    if _raw_secure_storage_fallback_missing_ack(settings):
        logger.error(
            "? MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true without "
            "MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true leaves Wormhole keys in raw local files "
            "on this platform. Add the explicit acknowledgement only for development/CI, or "
            "configure MESH_SECURE_STORAGE_SECRET for protected local custody."
        )
        all_ok = False
        if strict:
            logger.critical(
                "Startup aborted ? raw secure-storage fallback requires "
                "MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true on non-Windows platforms."
            )
            sys.exit(1)

    release_profile = profile_readiness_snapshot(settings)
    profile_blockers = list(release_profile.get("blockers") or [])
    if profile_blockers:
        logger.error(
            "MESH_RELEASE_PROFILE=%s is blocked by unsafe defaults: %s",
            release_profile.get("profile", "dev"),
            ", ".join(str(item) for item in profile_blockers),
        )
        all_ok = False
        if strict and str(release_profile.get("profile", "dev")) == "release-candidate":
            logger.critical(
                "Startup aborted - release-candidate profile cannot boot with unsafe defaults."
            )
            sys.exit(1)

    _audit_security_config(settings)

    if all_ok:
        logger.info("✅ Environment validation passed.")

    return all_ok
