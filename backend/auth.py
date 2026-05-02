"""auth.py — Router-safe auth, trust, and transport-tier helpers.

Extracted from main.py so that APIRouter modules can import these without
pulling in the full application object.

Do NOT import from main.py here.  All dependencies must be from stdlib,
FastAPI, or the services layer.
"""

import os
import sys
import hmac
import asyncio
import hmac as _hmac_mod
import hashlib as _hashlib_mod
import json as json_mod
import logging
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from services.config import get_settings
from services.mesh.mesh_privacy_policy import (
    TRANSPORT_TIER_ORDER as _CANONICAL_TRANSPORT_TIER_ORDER,
    lane_content_private,
    lane_truth_snapshot,
    local_operation_required_tier,
    network_release_required_tier,
    queued_acceptance_required_tier,
    transport_tier_from_state as _canonical_transport_tier_from_state,
    transport_tier_is_sufficient as _canonical_transport_tier_is_sufficient,
)
from services.mesh.mesh_compatibility import (
    compat_dm_invite_import_override_active,
    compatibility_status_snapshot,
    legacy_agent_id_lookup_blocked,
    legacy_dm1_override_active,
    legacy_dm_get_override_active,
    legacy_dm_signature_compat_override_active,
    legacy_node_id_compat_blocked,
)
from services.mesh.mesh_crypto import (
    _derive_peer_key,
    normalize_peer_url,
    verify_signature,
    verify_node_binding,
    parse_public_key_algo,
)
from services.mesh.mesh_router import authenticated_push_peer_urls

logger = logging.getLogger(__name__)
_PRIVATE_LANE_REFUSAL_FLOOR_S = 0.02

# ---------------------------------------------------------------------------
# Admin key helpers
# ---------------------------------------------------------------------------

def _current_admin_key() -> str:
    try:
        return str(get_settings().ADMIN_KEY or "").strip()
    except Exception:
        return os.environ.get("ADMIN_KEY", "").strip()


def _allow_insecure_admin() -> bool:
    try:
        settings = get_settings()
        return bool(getattr(settings, "ALLOW_INSECURE_ADMIN", False)) and bool(
            getattr(settings, "MESH_DEBUG_MODE", False)
        )
    except Exception:
        return False


def _debug_mode_enabled() -> bool:
    try:
        return bool(getattr(get_settings(), "MESH_DEBUG_MODE", False))
    except Exception:
        return False


def _admin_key_required_in_production() -> bool:
    try:
        settings = get_settings()
        return not bool(getattr(settings, "MESH_DEBUG_MODE", False)) and not bool(_current_admin_key())
    except Exception:
        return False


def _scoped_admin_tokens() -> dict[str, list[str]]:
    raw = str(get_settings().MESH_SCOPED_TOKENS or "").strip()
    if not raw:
        return {}
    try:
        parsed = json_mod.loads(raw)
    except Exception as exc:
        logger.warning("failed to parse MESH_SCOPED_TOKENS: %s", type(exc).__name__)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("MESH_SCOPED_TOKENS must decode to an object mapping token -> scopes")
        return {}
    normalized: dict[str, list[str]] = {}
    for token, scopes in parsed.items():
        token_key = str(token or "").strip()
        if not token_key:
            continue
        values = scopes if isinstance(scopes, list) else [scopes]
        normalized[token_key] = [str(scope or "").strip() for scope in values if str(scope or "").strip()]
    return normalized


def _required_scope_for_request(request: Request) -> str:
    path = str(request.url.path or "")
    if path.startswith("/api/wormhole/gate/"):
        return "gate"
    if path.startswith("/api/wormhole/dm/"):
        return "dm"
    if path.startswith("/api/wormhole") or path in {"/api/settings/wormhole", "/api/settings/privacy-profile"}:
        return "wormhole"
    if path.startswith("/api/mesh/"):
        return "mesh"
    return "admin"


def _scope_allows(required_scope: str, allowed_scopes: list[str]) -> bool:
    for scope in allowed_scopes:
        normalized = str(scope or "").strip()
        if not normalized:
            continue
        if normalized == "*" or required_scope == normalized:
            return True
        if required_scope.startswith(f"{normalized}.") or required_scope.startswith(f"{normalized}/"):
            return True
    return False


def _scope_allows_exact(required_scopes: set[str], allowed_scopes: list[str]) -> bool:
    for scope in allowed_scopes:
        normalized = str(scope or "").strip()
        if not normalized:
            continue
        if normalized == "*" or normalized in required_scopes:
            return True
    return False


def _check_scoped_auth(request: Request, required_scope: str) -> tuple[bool, str]:
    admin_key = _current_admin_key()
    scoped_tokens = _scoped_admin_tokens()
    presented = str(request.headers.get("X-Admin-Key", "") or "").strip()
    client = getattr(request, "client", None)
    host = (getattr(client, "host", "") or "").lower() if client else ""
    if admin_key and hmac.compare_digest(presented.encode(), admin_key.encode()):
        return True, "ok"
    if presented:
        presented_bytes = presented.encode()
        for token_value, scopes in scoped_tokens.items():
            if hmac.compare_digest(presented_bytes, str(token_value or "").encode()):
                if _scope_allows(required_scope, scopes):
                    return True, "ok"
                return False, "insufficient scope"
    if not admin_key and not scoped_tokens:
        if _allow_insecure_admin() or (_debug_mode_enabled() and host == "test"):
            return True, "ok"
        return False, "Forbidden — admin key not configured"
    return False, "Forbidden — invalid or missing admin key"


def _check_explicit_scoped_auth(
    request: Request,
    required_scopes: set[str],
) -> tuple[bool, str, str]:
    admin_key = _current_admin_key()
    scoped_tokens = _scoped_admin_tokens()
    presented = str(request.headers.get("X-Admin-Key", "") or "").strip()
    client = getattr(request, "client", None)
    host = (getattr(client, "host", "") or "").lower() if client else ""
    if admin_key and hmac.compare_digest(presented.encode(), admin_key.encode()):
        return True, "ok", "admin_key"
    if presented:
        presented_bytes = presented.encode()
        for token_value, scopes in scoped_tokens.items():
            if hmac.compare_digest(presented_bytes, str(token_value or "").encode()):
                if _scope_allows_exact(required_scopes, scopes):
                    return True, "ok", "explicit_scoped_token"
                return False, "insufficient scope", ""
    if not admin_key and not scoped_tokens:
        if _allow_insecure_admin() or (_debug_mode_enabled() and host == "test"):
            return True, "ok", "debug_override"
        return False, "Forbidden — admin key not configured", ""
    return False, "Forbidden — invalid or missing admin key", ""


def gate_privileged_access_status_snapshot() -> dict[str, Any]:
    scoped_tokens = _scoped_admin_tokens()
    explicit_audit_configured = any(
        _scope_allows_exact({"gate.audit", "mesh.audit"}, scopes)
        for scopes in scoped_tokens.values()
    )
    admin_enabled = bool(_current_admin_key()) or bool(_allow_insecure_admin()) or bool(
        _debug_mode_enabled()
    )
    return {
        "ordinary_gate_view_scope_class": "gate_member_or_gate_scope",
        "privileged_gate_event_scope_class": "explicit_gate_audit",
        "repair_detail_scope_class": "local_operator_diagnostic",
        "privileged_gate_event_view_enabled": bool(admin_enabled or explicit_audit_configured),
        "repair_detail_view_enabled": True,
    }


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def require_admin(request: Request):
    """FastAPI dependency that rejects requests without a valid X-Admin-Key header."""
    required_scope = _required_scope_for_request(request)
    ok, detail = _check_scoped_auth(request, required_scope)
    if ok:
        return
    if detail == "insufficient scope":
        raise HTTPException(status_code=403, detail="Forbidden — insufficient scope")
    raise HTTPException(status_code=403, detail=detail)


def _is_local_or_docker(host: str) -> bool:
    """Return True only for loopback addresses.

    RFC-1918 ranges (10.*, 172.*, 192.168.*) are no longer implicitly trusted.
    Callers on Docker bridge networks must present a valid admin key.
    """
    return host in {"127.0.0.1", "::1", "localhost"}


def require_local_operator(request: Request):
    """Allow local tooling on loopback / Docker internal network, or a valid admin key."""
    host = (request.client.host or "").lower() if request.client else ""
    if _is_local_or_docker(host) or (_debug_mode_enabled() and host == "test"):
        return
    admin_key = _current_admin_key()
    presented = str(request.headers.get("X-Admin-Key", "") or "").strip()
    if admin_key and hmac.compare_digest(presented.encode(), admin_key.encode()):
        return
    raise HTTPException(status_code=403, detail="Forbidden — local operator access only")


# ---------------------------------------------------------------------------
# OpenClaw HMAC authentication
# ---------------------------------------------------------------------------

# In-memory nonce cache — bounded, auto-expires after 5 minutes.
# Prevents replay attacks without persisting state to disk.
_openclaw_nonce_cache: dict[str, float] = {}
_OPENCLAW_NONCE_MAX = 16384
_OPENCLAW_NONCE_TTL = 300  # 5 minutes
_OPENCLAW_REQUEST_MAX_AGE = 60  # reject requests older than 60s
# Grace period after restart: tighten freshness window to reduce replay risk
# from nonces seen before the restart that we can no longer remember.
_OPENCLAW_STARTUP_TIME: float = time.time()
_OPENCLAW_STARTUP_GRACE = 120  # seconds — stricter freshness for 2 min after boot


def _openclaw_hmac_secret() -> str:
    """Read the HMAC shared secret from settings."""
    try:
        return str(get_settings().OPENCLAW_HMAC_SECRET or "").strip()
    except Exception:
        return os.environ.get("OPENCLAW_HMAC_SECRET", "").strip()


def _prune_nonce_cache() -> None:
    """Evict expired nonces to bound memory usage."""
    now = time.time()
    expired = [k for k, ts in _openclaw_nonce_cache.items() if now - ts > _OPENCLAW_NONCE_TTL]
    for k in expired:
        _openclaw_nonce_cache.pop(k, None)
    # Hard cap — if still too large, drop oldest
    if len(_openclaw_nonce_cache) > _OPENCLAW_NONCE_MAX:
        sorted_keys = sorted(_openclaw_nonce_cache, key=_openclaw_nonce_cache.get)  # type: ignore
        for k in sorted_keys[: len(_openclaw_nonce_cache) - _OPENCLAW_NONCE_MAX]:
            _openclaw_nonce_cache.pop(k, None)


async def _verify_openclaw_hmac(request: Request) -> bool:
    """Verify HMAC-signed request from a remote OpenClaw agent.

    Expected headers (only on direct HTTP, never on mesh wire):
      X-SB-Timestamp: unix timestamp (integer)
      X-SB-Nonce: random hex string (min 16 chars)
      X-SB-Signature: HMAC-SHA256(secret, METHOD|path|timestamp|nonce|sha256(body))

    The signing input includes a SHA-256 digest of the request body so that
    body-bearing requests (POST, PUT, PATCH, etc.) cannot be modified without
    invalidating the signature.  Bodyless requests use sha256(b"").

    Returns True if signature is valid, timestamp is fresh, and nonce is unused.
    """
    secret = _openclaw_hmac_secret()
    if not secret:
        return False

    ts_str = str(request.headers.get("X-SB-Timestamp", "") or "").strip()
    nonce = str(request.headers.get("X-SB-Nonce", "") or "").strip()
    signature = str(request.headers.get("X-SB-Signature", "") or "").strip()

    if not ts_str or not nonce or not signature:
        return False

    # Validate nonce length (prevent trivial collisions)
    if len(nonce) < 16:
        return False

    # Validate timestamp freshness
    try:
        ts = int(ts_str)
    except (TypeError, ValueError):
        return False
    now = int(time.time())
    # During startup grace period, require tighter freshness to limit replay
    # risk from nonces that existed before the restart (cache was lost).
    in_grace = (time.time() - _OPENCLAW_STARTUP_TIME) < _OPENCLAW_STARTUP_GRACE
    max_age = 10 if in_grace else _OPENCLAW_REQUEST_MAX_AGE
    if abs(now - ts) > max_age:
        return False

    # Check nonce hasn't been used (replay protection)
    _prune_nonce_cache()
    if nonce in _openclaw_nonce_cache:
        return False

    # Bind request body: digest the raw bytes so any body tampering
    # invalidates the signature.  Empty/absent bodies hash as sha256(b"").
    body_bytes = await request.body()
    body_digest = _hashlib_mod.sha256(body_bytes).hexdigest()

    # Compute expected signature: HMAC-SHA256(secret, METHOD|path|ts|nonce|body_digest)
    method = str(request.method or "").upper()
    path = str(request.url.path or "")
    message = f"{method}|{path}|{ts_str}|{nonce}|{body_digest}"
    expected = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        _hashlib_mod.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        return False

    # Record nonce to prevent replay
    _openclaw_nonce_cache[nonce] = time.time()
    return True


async def require_openclaw_or_local(request: Request):
    """Allow local operator access, admin key, OR valid OpenClaw HMAC signature.

    This is used on /api/ai/* routes to permit remote agent access
    without exposing the full admin surface.
    """
    host = (request.client.host or "").lower() if request.client else ""

    # 1. Local loopback — always allowed
    if _is_local_or_docker(host) or (_debug_mode_enabled() and host == "test"):
        return

    # 2. Admin key — full trust
    admin_key = _current_admin_key()
    presented = str(request.headers.get("X-Admin-Key", "") or "").strip()
    if admin_key and hmac.compare_digest(presented.encode(), admin_key.encode()):
        return

    # 3. OpenClaw HMAC — agent-scoped trust
    if await _verify_openclaw_hmac(request):
        # Security: reject if agent is also sending Authorization headers.
        # This catches misconfigured proxies forwarding LLM API keys to SB.
        auth_header = str(request.headers.get("Authorization", "") or "").strip()
        if auth_header:
            _llm_key_prefixes = ("sk-", "sk-ant-", "key-", "AIza", "xai-", "Bearer sk-", "Bearer key-")
            if any(auth_header.startswith(p) or auth_header.replace("Bearer ", "").startswith(p)
                   for p in _llm_key_prefixes):
                logger.critical(
                    "BLOCKED: HMAC-authenticated request carries Authorization header "
                    "that looks like an LLM API key — rejecting to prevent key leak"
                )
                raise HTTPException(
                    status_code=400,
                    detail="Request rejected — Authorization header contains what appears "
                           "to be an LLM API key. Remove it from your agent proxy configuration.",
                )
            logger.warning(
                "HMAC-authenticated request carries unexpected Authorization header"
            )
        return

    raise HTTPException(status_code=403, detail="Forbidden — authentication required")


# ---------------------------------------------------------------------------
# Startup validators
# ---------------------------------------------------------------------------

_KNOWN_COMPROMISED_PEER_PUSH_SECRET = "Mv63UvLfwqOEVWeRBXjA8MtFl2nEkkhUlLYVHiX1Zzo"


def _validate_admin_startup() -> None:
    admin_key = _current_admin_key()

    if not admin_key or len(admin_key) < 32:
        import secrets

        reason = "not set" if not admin_key else f"too short ({len(admin_key)} chars, minimum 32)"
        new_key = secrets.token_hex(32)  # 64-char hex string
        try:
            from routers.ai_intel import _write_env_value

            _write_env_value("ADMIN_KEY", new_key)
            os.environ["ADMIN_KEY"] = new_key
            logger.info(
                "ADMIN_KEY was %s — auto-generated a strong 64-character key and "
                "saved it to .env. Admin/mesh endpoints are now secured.",
                reason,
            )
            # Clear settings cache so the rest of startup picks up the new key
            try:
                get_settings.cache_clear()
            except Exception:
                pass
        except Exception as exc:
            logger.warning(
                "ADMIN_KEY is %s and could not auto-generate: %s. "
                "Admin/mesh endpoints may be unavailable.",
                reason,
                exc,
            )


def _validate_insecure_admin_startup() -> None:
    """Exit if ALLOW_INSECURE_ADMIN is enabled outside of debug mode.

    ALLOW_INSECURE_ADMIN=True without MESH_DEBUG_MODE=True would allow admin
    endpoints to bypass authentication in production, which is not permitted.
    """
    try:
        settings = get_settings()
        allow_insecure = bool(getattr(settings, "ALLOW_INSECURE_ADMIN", False))
        debug_mode = bool(getattr(settings, "MESH_DEBUG_MODE", False))
    except Exception:
        return
    if allow_insecure and not debug_mode:
        logger.critical(
            "ALLOW_INSECURE_ADMIN=True requires MESH_DEBUG_MODE=True. "
            "This flag must not be set in production. Refusing to start."
        )
        sys.exit(1)


def _auto_generate_peer_push_secret() -> str | None:
    """Generate a strong peer push secret, persist to .env, return it."""
    import secrets

    new_secret = secrets.token_urlsafe(32)  # 43-char URL-safe string
    try:
        from routers.ai_intel import _write_env_value

        _write_env_value("MESH_PEER_PUSH_SECRET", new_secret)
        os.environ["MESH_PEER_PUSH_SECRET"] = new_secret
        try:
            get_settings.cache_clear()
        except Exception:
            pass
        return new_secret
    except Exception as exc:
        logger.warning("Could not auto-generate MESH_PEER_PUSH_SECRET: %s", exc)
        return None


def _validate_peer_push_secret() -> None:
    """Ensure peer push authentication is properly configured.

    Instead of refusing to start when the secret is missing or compromised,
    auto-generate a strong replacement and persist it to .env.  The only
    hard failure is if auto-generation itself fails AND peers are configured.
    """
    settings = None
    try:
        settings = get_settings()
        secret = str(settings.MESH_PEER_PUSH_SECRET or "").strip()
    except Exception:
        secret = os.environ.get("MESH_PEER_PUSH_SECRET", "").strip()

    # Replace the known-compromised testnet default automatically
    if secret == _KNOWN_COMPROMISED_PEER_PUSH_SECRET:
        logger.warning(
            "MESH_PEER_PUSH_SECRET was the publicly-known testnet default — "
            "auto-generating a secure replacement."
        )
        new_secret = _auto_generate_peer_push_secret()
        if new_secret:
            secret = new_secret
            logger.info("MESH_PEER_PUSH_SECRET replaced and saved to .env.")
        else:
            logger.critical(
                "MESH_PEER_PUSH_SECRET is the publicly-known testnet default "
                "and could not be replaced automatically. "
                "Set a unique secret in your .env file."
            )
            sys.exit(1)

    try:
        from services.env_check import (
            _invalid_peer_push_secret_reason,
            _peer_push_secret_required,
        )

        secret_reason = _invalid_peer_push_secret_reason(secret)
        secret_required = (
            _peer_push_secret_required(settings)
            if settings is not None
            else bool(
                os.environ.get("MESH_RNS_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
                or os.environ.get("MESH_RELAY_PEERS", "").strip()
                or os.environ.get("MESH_RNS_PEERS", "").strip()
            )
        )
    except Exception:
        secret_reason = ""
        secret_required = False

    # Secret is required but invalid — try to auto-fix
    if secret_required and secret_reason:
        logger.warning(
            "MESH_PEER_PUSH_SECRET is invalid (%s) while relay or RNS peers are "
            "configured — auto-generating a secure replacement.",
            secret_reason,
        )
        new_secret = _auto_generate_peer_push_secret()
        if new_secret:
            logger.info("MESH_PEER_PUSH_SECRET auto-generated and saved to .env.")
        else:
            logger.critical(
                "MESH_PEER_PUSH_SECRET is invalid (%s) and could not be replaced "
                "automatically. Set a unique secret of at least 16 characters in .env.",
                secret_reason,
            )
            sys.exit(1)
        return

    if not secret:
        logger.warning(
            "MESH_PEER_PUSH_SECRET is not set — peer push authentication is disabled. "
            "Set MESH_PEER_PUSH_SECRET in your .env file for production use."
        )


# ---------------------------------------------------------------------------
# Path classification helpers
# ---------------------------------------------------------------------------

def _is_anonymous_mesh_write_path(path: str, method: str) -> bool:
    if method.upper() not in {"POST", "PUT", "DELETE"}:
        return False
    if path == "/api/mesh/send":
        return True
    if path in {
        "/api/mesh/vote",
        "/api/mesh/report",
        "/api/mesh/trust/vouch",
        "/api/mesh/gate/create",
        "/api/mesh/oracle/predict",
        "/api/mesh/oracle/resolve",
        "/api/mesh/oracle/stake",
        "/api/mesh/oracle/resolve-stakes",
    }:
        return True
    if path.startswith("/api/mesh/gate/") and path.endswith("/message"):
        return True
    return False


def _is_anonymous_dm_action_path(path: str, method: str) -> bool:
    method_name = method.upper()
    if method_name == "POST" and path in {
        "/api/mesh/dm/register",
        "/api/mesh/dm/send",
        "/api/mesh/dm/poll",
        "/api/mesh/dm/count",
        "/api/mesh/dm/block",
        "/api/mesh/dm/witness",
    }:
        return True
    if method_name == "GET" and path in {
        "/api/mesh/dm/pubkey",
        "/api/mesh/dm/prekey-bundle",
    }:
        return True
    return False


def _is_anonymous_wormhole_gate_admin_path(path: str, method: str) -> bool:
    if method.upper() != "POST":
        return False
    return path in {
        "/api/wormhole/gate/enter",
        "/api/wormhole/gate/persona/create",
        "/api/wormhole/gate/persona/activate",
        "/api/wormhole/gate/persona/retire",
    }


def _is_sensitive_no_store_path(path: str) -> bool:
    if not path.startswith("/api/"):
        return False
    if path.startswith("/api/wormhole/"):
        return True
    if path.startswith("/api/settings/"):
        return True
    if path.startswith("/api/mesh/dm/"):
        return True
    if path in {
        "/api/refresh",
        "/api/debug-latest",
        "/api/system/update",
        "/api/mesh/infonet/ingest",
    }:
        return True
    return False


def _is_debug_test_request(request: Request) -> bool:
    if not _debug_mode_enabled():
        return False
    client_host = (request.client.host or "").lower() if request.client else ""
    url_host = (request.url.hostname or "").lower() if request.url else ""
    return client_host == "test" or url_host == "test"


# ---------------------------------------------------------------------------
# Transport tier / private lane
# ---------------------------------------------------------------------------

_TRANSPORT_TIER_ORDER = _CANONICAL_TRANSPORT_TIER_ORDER


@dataclass(frozen=True)
class RouteTransportPolicy:
    enforcement_tier: str
    published_tier: str
    local_operation_tier: str
    queued_acceptance_tier: str
    network_release_tier: str
    content_private: bool


def _local_only_route_policy(tier: str, *, content_private: bool = True) -> RouteTransportPolicy:
    normalized_tier = str(tier or "").strip()
    return RouteTransportPolicy(
        enforcement_tier=normalized_tier,
        published_tier=normalized_tier,
        local_operation_tier=normalized_tier,
        queued_acceptance_tier=normalized_tier,
        network_release_tier="",
        content_private=content_private,
    )


def _network_delivery_route_policy(*, enforcement_tier: str, lane: str) -> RouteTransportPolicy:
    normalized_lane = str(lane or "").strip().lower()
    return RouteTransportPolicy(
        enforcement_tier=str(enforcement_tier or "").strip(),
        published_tier=network_release_required_tier(normalized_lane),
        local_operation_tier=local_operation_required_tier(normalized_lane),
        queued_acceptance_tier=queued_acceptance_required_tier(normalized_lane),
        network_release_tier=network_release_required_tier(normalized_lane),
        content_private=lane_content_private(normalized_lane),
    )

# ── Single authoritative route → transport-tier policy table ──────────
#
# Every exact-match route that participates in private-lane policy is listed
# here exactly once. Each entry carries:
# - enforcement_tier: what middleware uses for local access gating
# - published_tier: the honest user-facing/private-claim floor
# - queued/network release tiers when the route initiates delivery
#
# _minimum_transport_tier() and the legacy helper _private_infonet_required_tier()
# both derive their answers from this table so that a route cannot silently
# appear in conflicting sets.
#
# Pattern-match routes (POST /api/mesh/gate/{id}/message) cannot be
# expressed as dict keys and are handled by _ROUTE_TRANSPORT_PATTERNS.

_ROUTE_TRANSPORT_POLICY: dict[tuple[str, str], RouteTransportPolicy] = {
    # ── Mesh DM (strong — GET and POST) ───────────────────────────────
    ("GET", "/api/mesh/dm/register"): _local_only_route_policy("private_strong"),
    ("POST", "/api/mesh/dm/register"): _local_only_route_policy("private_strong"),
    ("GET", "/api/mesh/dm/send"): _network_delivery_route_policy(enforcement_tier="private_strong", lane="dm"),
    ("POST", "/api/mesh/dm/send"): _network_delivery_route_policy(enforcement_tier="private_strong", lane="dm"),
    ("GET", "/api/mesh/dm/poll"): _local_only_route_policy("private_strong"),
    ("POST", "/api/mesh/dm/poll"): _local_only_route_policy("private_strong"),
    ("GET", "/api/mesh/dm/count"): _local_only_route_policy("private_strong"),
    ("POST", "/api/mesh/dm/count"): _local_only_route_policy("private_strong"),
    ("GET", "/api/mesh/dm/block"): _local_only_route_policy("private_strong"),
    ("POST", "/api/mesh/dm/block"): _local_only_route_policy("private_strong"),
    ("GET", "/api/mesh/dm/witness"): _local_only_route_policy("private_strong"),
    ("POST", "/api/mesh/dm/witness"): _local_only_route_policy("private_strong"),
    ("GET", "/api/mesh/dm/prekey-bundle"): _local_only_route_policy("private_transitional"),
    # ── Mesh infonet write (transitional) ─────────────────────────────
    ("POST", "/api/mesh/gate/create"): _local_only_route_policy("private_transitional"),
    ("POST", "/api/mesh/vote"): _local_only_route_policy("private_transitional"),
    # Key rotation also changes the cryptographic trust graph; require
    # the strongest private transport so identity-link events are not
    # emitted from a weaker, more correlatable network posture.
    ("POST", "/api/mesh/identity/rotate"): _local_only_route_policy("private_strong"),
    # Key revocation is a chain-wide cryptographic trust change; require
    # the strongest available private transport so the event broadcast
    # cannot be correlated to a clearnet-identifiable source.
    ("POST", "/api/mesh/identity/revoke"): _local_only_route_policy("private_strong"),
    # ── Mesh oracle & trust (transitional) ────────────────────────────
    ("POST", "/api/mesh/report"): _local_only_route_policy("private_transitional"),
    ("POST", "/api/mesh/trust/vouch"): _local_only_route_policy("private_strong"),
    ("POST", "/api/mesh/oracle/predict"): _local_only_route_policy("private_transitional"),
    ("POST", "/api/mesh/oracle/resolve"): _local_only_route_policy("private_transitional"),
    ("POST", "/api/mesh/oracle/stake"): _local_only_route_policy("private_transitional"),
    ("POST", "/api/mesh/oracle/resolve-stakes"): _local_only_route_policy("private_transitional"),
    # ── Wormhole gate lifecycle / local gate-state control (control-only) ───
    ("POST", "/api/wormhole/gate/enter"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/gate/leave"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/gate/persona/create"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/gate/persona/activate"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/gate/persona/clear"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/gate/persona/retire"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/gate/key/grant"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/gate/key/rotate"): _local_only_route_policy("private_control_only"),
    # ── Wormhole gate encrypted messaging ───────────────────────────────
    # compose/sign/decrypt are local control operations; post-encrypted
    # queues locally but publishes a PRIVATE / TRANSITIONAL release floor.
    ("POST", "/api/wormhole/gate/message/compose"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/gate/message/sign-encrypted"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/gate/message/post-encrypted"): _network_delivery_route_policy(
        enforcement_tier="private_control_only",
        lane="gate",
    ),
    ("POST", "/api/wormhole/gate/message/decrypt"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/gate/messages/decrypt"): _local_only_route_policy("private_control_only"),
    # ── Wormhole DM (strong) ──────────────────────────────────────────
    ("POST", "/api/wormhole/dm/compose"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/decrypt"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/register-key"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/prekey/register"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/bootstrap-encrypt"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/bootstrap-decrypt"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/sender-token"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/open-seal"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/build-seal"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/dead-drop-token"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/pairwise-alias"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/pairwise-alias/rotate"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/dead-drop-tokens"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/sas"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/encrypt"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/reset"): _local_only_route_policy("private_control_only"),
    ("POST", "/api/wormhole/dm/selftest"): _local_only_route_policy("private_control_only"),
}

# Pattern-match transport rules that cannot be expressed as exact dict keys.
# Each entry is (method, prefix, suffix, tier).
_ROUTE_TRANSPORT_PATTERNS: list[tuple[str, str, str, RouteTransportPolicy]] = [
    (
        "POST",
        "/api/mesh/gate/",
        "/message",
        _network_delivery_route_policy(enforcement_tier="private_strong", lane="gate"),
    ),
]


def _current_private_lane_tier(wormhole: dict | None) -> str:
    return _canonical_transport_tier_from_state(wormhole)


def _transport_tier_is_sufficient(current_tier: str, required_tier: str) -> bool:
    return _canonical_transport_tier_is_sufficient(current_tier, required_tier)


def _resolve_route_transport_policy(path: str, method: str) -> RouteTransportPolicy | None:
    method_name = method.upper()
    policy = _ROUTE_TRANSPORT_POLICY.get((method_name, path))
    if policy is not None:
        return policy
    for pat_method, prefix, suffix, pat_policy in _ROUTE_TRANSPORT_PATTERNS:
        if method_name == pat_method and path.startswith(prefix) and path.endswith(suffix):
            return pat_policy
    return None


def _resolve_transport_tier(path: str, method: str) -> str:
    """Resolve the enforced access tier for a (method, path) pair."""
    policy = _resolve_route_transport_policy(path, method)
    return str(policy.enforcement_tier or "") if policy is not None else ""


def _published_transport_tier(path: str, method: str) -> str:
    """Resolve the user-facing/private-claim transport floor for a route."""
    policy = _resolve_route_transport_policy(path, method)
    return str(policy.published_tier or "") if policy is not None else ""


# Tier label mapping from full tier names to legacy short labels.
_TIER_SHORT_LABELS = {
    "private_strong": "strong",
    "private_transitional": "transitional",
    "private_control_only": "control_only",
}

# Private-infonet routes are the subset of policy-table entries whose paths
# live under /api/mesh/ (not /api/wormhole/).  Derived once at import time
# so the helper functions contain zero inline path enumeration.
_PRIVATE_INFONET_ROUTES: set[tuple[str, str]] = {
    (method, path)
    for (method, path) in _ROUTE_TRANSPORT_POLICY
    if path.startswith("/api/mesh/")
}


def _is_private_infonet_write_path(path: str, method: str) -> bool:
    """True when the route is a POST private-infonet write with a transport tier."""
    if method.upper() != "POST":
        return False
    # Exact-match routes.
    if ("POST", path) in _PRIVATE_INFONET_ROUTES:
        tier = _ROUTE_TRANSPORT_POLICY[("POST", path)].enforcement_tier
        return tier in {"private_transitional", "private_strong"}
    # Pattern-match routes (e.g. POST /api/mesh/gate/{id}/message).
    for pat_method, prefix, suffix, pat_policy in _ROUTE_TRANSPORT_PATTERNS:
        if pat_method == "POST" and prefix.startswith("/api/mesh/") and path.startswith(prefix) and path.endswith(suffix):
            return pat_policy.enforcement_tier in {"private_transitional", "private_strong"}
    return False


def _private_infonet_required_tier(path: str, method: str) -> str:
    """Derive private-infonet tier label from the consolidated policy source.

    Returns "strong", "transitional", or "" — the legacy short labels used by
    callers outside this module.  Only /api/mesh/* routes are in scope.
    """
    method_name = method.upper()
    # Exact-match routes.
    if (method_name, path) in _PRIVATE_INFONET_ROUTES:
        tier = _ROUTE_TRANSPORT_POLICY[(method_name, path)].enforcement_tier
        return _TIER_SHORT_LABELS.get(tier, "")
    # Pattern-match routes.
    for pat_method, prefix, suffix, pat_policy in _ROUTE_TRANSPORT_PATTERNS:
        if method_name == pat_method and prefix.startswith("/api/mesh/") and path.startswith(prefix) and path.endswith(suffix):
            return _TIER_SHORT_LABELS.get(pat_policy.enforcement_tier, "")
    return ""


def _minimum_transport_tier(path: str, method: str) -> str:
    """Look up the minimum transport tier for a route.

    Delegates to _resolve_transport_tier so that all tier decisions flow
    through the single consolidated policy source.
    """
    return _resolve_transport_tier(path, method)


def _is_private_plane_access_path(path: str, method: str) -> bool:
    normalized_path = str(path or "").strip()
    if _minimum_transport_tier(normalized_path, method):
        return True
    return (
        normalized_path.startswith("/api/wormhole/gate/")
        or normalized_path.startswith("/api/wormhole/dm/")
        or normalized_path.startswith("/api/mesh/gate/")
        or normalized_path.startswith("/api/mesh/infonet/messages")
        or normalized_path.startswith("/api/mesh/infonet/event/")
    )


def _private_plane_access_denied_payload() -> dict[str, Any]:
    return {"ok": False, "detail": "access denied"}


async def _private_plane_refusal_response(
    request: Request,
    *,
    status_code: int,
    payload: dict[str, Any],
) -> JSONResponse:
    started_at = getattr(getattr(request, "state", None), "_private_lane_started_at", None)
    if isinstance(started_at, (int, float)):
        elapsed = time.perf_counter() - float(started_at)
        remaining = _PRIVATE_LANE_REFUSAL_FLOOR_S - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)
    # Tor-style: when the response is a "preparing private lane" 202, advise
    # the client to retry shortly. Standard Retry-After lets any HTTP client
    # (including non-frontend consumers) auto-retry without custom logic.
    headers: dict[str, str] = {}
    if int(status_code) == 202 and bool(payload.get("pending")):
        headers["Retry-After"] = "2"
    return JSONResponse(status_code=status_code, content=payload, headers=headers or None)


def _external_assurance_status_snapshot() -> dict[str, Any]:
    try:
        from services.mesh.mesh_wormhole_root_manifest import get_current_root_manifest
        from services.mesh.mesh_wormhole_root_transparency import (
            get_current_root_transparency_record,
        )

        distribution = get_current_root_manifest()
        transparency = get_current_root_transparency_record(distribution=distribution)
        witness_state = str(
            distribution.get("external_witness_operator_state", "not_configured")
            or "not_configured"
        ).strip()
        transparency_state = str(
            transparency.get("ledger_operator_state", "not_configured")
            or "not_configured"
        ).strip()
        witness_configured = bool(
            distribution.get("external_witness_source_configured", False)
        )
        transparency_configured = bool(
            transparency.get("ledger_readback_configured", False)
        )
        current = witness_state == "current" and transparency_state == "current"
        configured = bool(witness_configured and transparency_configured)
        if current:
            state = "current_external"
            detail = "configured external witness and transparency assurances are current"
        elif witness_configured or transparency_configured:
            state = "stale_external"
            detail = "configured external witness or transparency assurance is incomplete, stale, or missing"
        else:
            state = "local_cached_only"
            detail = "external witness and transparency assurance are not fully configured"
        return {
            "current": current,
            "configured": configured,
            "state": state,
            "detail": detail,
            "witness_state": witness_state,
            "transparency_state": transparency_state,
        }
    except Exception as exc:
        return {
            "current": False,
            "configured": False,
            "state": "unknown",
            "detail": str(exc) or type(exc).__name__,
            "witness_state": "unknown",
            "transparency_state": "unknown",
        }


def _strong_claims_policy_snapshot(
    *,
    current_tier: str | None = None,
    anonymous_mode: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from services.privacy_core_attestation import privacy_core_attestation

        privacy_core = dict(privacy_core_attestation())
    except Exception as exc:
        privacy_core = {
            "attestation_state": "attestation_stale_or_unknown",
            "override_active": False,
            "detail": str(exc) or type(exc).__name__,
        }

    try:
        from services.config import (
            backend_gate_decrypt_compat_effective,
            backend_gate_plaintext_compat_effective,
            gate_plaintext_persist_effective,
            gate_recovery_envelope_effective,
            private_clearnet_fallback_effective,
        )
        from services.mesh.mesh_compatibility import (
            compatibility_status_snapshot,
            legacy_agent_id_lookup_blocked,
            legacy_node_id_compat_blocked,
        )

        settings = get_settings()
        anonymous_state = anonymous_mode or _anonymous_mode_state()
        compatibility = compatibility_status_snapshot().get("sunset", {})
        transport_tier = str(current_tier or "public_degraded")
        clearnet_fallback_policy = private_clearnet_fallback_effective(settings)
        legacy_node_id_blocked = bool(legacy_node_id_compat_blocked())
        legacy_agent_lookup_blocked = bool(legacy_agent_id_lookup_blocked())
        legacy_dm1_enabled = bool(legacy_dm1_override_active())
        legacy_dm_get_enabled = bool(legacy_dm_get_override_active())
        compat_dm_invite_import_enabled = bool(compat_dm_invite_import_override_active())
        legacy_dm_signature_compat_enabled = bool(legacy_dm_signature_compat_override_active())
        gate_backend_decrypt_compat = bool(
            backend_gate_decrypt_compat_effective(settings)
        )
        gate_backend_plaintext_compat = bool(
            backend_gate_plaintext_compat_effective(settings)
        )
        gate_recovery_envelope_enabled = False
        if gate_recovery_envelope_effective(settings):
            try:
                from services.mesh.mesh_reputation import gate_manager

                gate_recovery_envelope_enabled = any(
                    str((gate or {}).get("envelope_policy", "") or "")
                    in {"envelope_recovery", "envelope_always"}
                    for gate in getattr(gate_manager, "gates", {}).values()
                )
            except Exception:
                gate_recovery_envelope_enabled = True
        gate_plaintext_persist = bool(gate_plaintext_persist_effective(settings))
    except Exception:
        anonymous_state = anonymous_mode or _anonymous_mode_state()
        transport_tier = str(current_tier or "public_degraded")
        compatibility = {}
        clearnet_fallback_policy = "block"
        legacy_node_id_blocked = False
        legacy_agent_lookup_blocked = False
        legacy_dm1_enabled = False
        legacy_dm_get_enabled = False
        compat_dm_invite_import_enabled = False
        legacy_dm_signature_compat_enabled = False
        gate_backend_decrypt_compat = False
        gate_backend_plaintext_compat = False
        gate_recovery_envelope_enabled = False
        gate_plaintext_persist = False

    external_assurance = _external_assurance_status_snapshot()
    external_assurance_current = bool(external_assurance.get("current", False))
    external_assurance_configured = bool(external_assurance.get("configured", False))
    external_assurance_state = str(
        external_assurance.get("state", "unknown") or "unknown"
    ).strip()
    external_assurance_detail = str(
        external_assurance.get("detail", "") or ""
    ).strip()
    privacy_core_attestation_state = str(
        privacy_core.get("attestation_state", "attestation_stale_or_unknown")
        or "attestation_stale_or_unknown"
    ).strip()
    privacy_core_override_active = bool(privacy_core.get("override_active", False))
    privacy_core_attested_current = privacy_core_attestation_state == "attested_current"
    privacy_core_detail = str(privacy_core.get("detail", "") or "").strip()
    anonymous_mode_enabled = bool(anonymous_state.get("enabled"))
    hidden_transport_ready = bool(anonymous_state.get("ready"))
    compat_overrides_clear = all(
        (
            legacy_node_id_blocked,
            legacy_agent_lookup_blocked,
            not legacy_dm1_enabled,
            not legacy_dm_get_enabled,
            not compat_dm_invite_import_enabled,
            not legacy_dm_signature_compat_enabled,
            not gate_backend_decrypt_compat,
            not gate_backend_plaintext_compat,
            not gate_plaintext_persist,
        )
    )
    clearnet_fallback_blocked = clearnet_fallback_policy == "block"

    reasons: list[str] = []
    if transport_tier != "private_strong":
        reasons.append("transport_tier_not_private_strong")
    if not anonymous_mode_enabled:
        reasons.append("anonymous_mode_off")
    if not hidden_transport_ready:
        reasons.append("hidden_transport_not_ready")
    if not clearnet_fallback_blocked:
        reasons.append("clearnet_fallback_not_blocked")
    if not compat_overrides_clear:
        reasons.append("compat_overrides_enabled")
    if not privacy_core_attested_current:
        reasons.append("privacy_core_attestation_not_current")
    if (
        transport_tier == "private_strong"
        and anonymous_mode_enabled
        and hidden_transport_ready
        and clearnet_fallback_blocked
        and compat_overrides_clear
        and privacy_core_attested_current
        and not external_assurance_current
    ):
        reasons.append("external_assurance_not_current")
    try:
        from services.release_profiles import profile_readiness_snapshot

        release_profile = profile_readiness_snapshot()
    except Exception:
        release_profile = {
            "profile": "dev",
            "allowed": False,
            "state": "release_profile_unknown",
            "blockers": ["release_profile_unavailable"],
        }
    for blocker in list(release_profile.get("blockers") or []):
        normalized = str(blocker or "").strip()
        if normalized and normalized not in reasons:
            reasons.append(normalized)

    return {
        "allowed": not reasons,
        "release_profile": release_profile,
        "required_transport_tier": "private_strong",
        "current_transport_tier": transport_tier,
        "anonymous_mode_enabled": anonymous_mode_enabled,
        "hidden_transport_ready": hidden_transport_ready,
        "effective_transport": str(anonymous_state.get("effective_transport", "direct") or "direct"),
        "clearnet_fallback_policy": clearnet_fallback_policy,
        "clearnet_fallback_blocked": clearnet_fallback_blocked,
        "compat_overrides_clear": compat_overrides_clear,
        "privacy_core_attested_current": privacy_core_attested_current,
        "privacy_core_attestation_state": privacy_core_attestation_state,
        "privacy_core_override_active": privacy_core_override_active,
        "privacy_core_detail": privacy_core_detail,
        "external_assurance_current": external_assurance_current,
        "external_assurance_configured": external_assurance_configured,
        "external_assurance_state": external_assurance_state,
        "external_assurance_detail": external_assurance_detail,
        "compatibility": {
            "legacy_node_id_compatibility_blocked": legacy_node_id_blocked,
            "legacy_agent_id_lookup_blocked": legacy_agent_lookup_blocked,
            "legacy_dm1_enabled": legacy_dm1_enabled,
            "legacy_dm_get_enabled": legacy_dm_get_enabled,
            "compat_dm_invite_import_enabled": compat_dm_invite_import_enabled,
            "legacy_dm_signature_compat_enabled": legacy_dm_signature_compat_enabled,
            "gate_backend_decrypt_compat": gate_backend_decrypt_compat,
            "gate_backend_plaintext_compat": gate_backend_plaintext_compat,
            "gate_recovery_envelope_enabled": gate_recovery_envelope_enabled,
            "gate_plaintext_persist": gate_plaintext_persist,
            "sunset": compatibility,
        },
        "reasons": reasons,
    }


def _transport_tier_precondition_payload(required_tier: str, current_tier: str) -> dict[str, Any]:
    strong_claims = _strong_claims_policy_snapshot(current_tier=current_tier)
    return {
        "ok": False,
        "detail": "transport tier insufficient",
        "required": required_tier,
        "current": current_tier,
        "policy": {
            "strong_claims_allowed": strong_claims["allowed"],
            "strong_claims_reasons": list(strong_claims.get("reasons") or []),
        },
    }


def _transport_tier_precondition(required_tier: str, current_tier: str) -> JSONResponse:
    return JSONResponse(
        status_code=428,
        content=_transport_tier_precondition_payload(required_tier, current_tier),
    )


def _private_infonet_policy_snapshot(*, current_tier: str | None = None) -> dict[str, Any]:
    try:
        from services.mesh.mesh_compatibility import compatibility_status_snapshot

        compatibility_sunset = compatibility_status_snapshot().get("sunset", {})
    except Exception:
        compatibility_sunset = {}
    strong_claims = _strong_claims_policy_snapshot(current_tier=current_tier)
    gate_truth = lane_truth_snapshot("gate")
    dm_truth = lane_truth_snapshot("dm")
    gate_post_floor = _published_transport_tier("/api/wormhole/gate/message/post-encrypted", "POST") or gate_truth["network_release_tier"]
    dm_release_floor = _published_transport_tier("/api/mesh/dm/send", "POST") or dm_truth["network_release_tier"]
    return {
        "gate_actions": {
            "post_message": gate_post_floor,
            "vote": "private_transitional",
            "create_gate": "private_transitional",
        },
        "gate_chat": {
            "trust_tier": gate_truth["network_release_tier"],
            "local_operation_tier": gate_truth["local_operation_tier"],
            "queued_acceptance_tier": gate_truth["queued_acceptance_tier"],
            "network_release_tier": gate_truth["network_release_tier"],
            "wormhole_required": True,
            "content_private": gate_truth["content_private"],
            "storage_model": "private_gate_store_mls_state_optional_recovery_envelope",
            "notes": [
                "Gate messages stay off the public hashchain and live on the private gate plane.",
                "Anonymous gate sessions use rotating gate-scoped public keys and can participate on the private gate lane.",
                "Durable gate_envelope recovery material is disabled by default and only activates when both a gate policy and the runtime recovery-envelope opt-in are enabled; envelope_always widens ordinary reads further.",
                "Legacy Phase-1 gate envelope fallback is no longer inherited from stored history; re-enabling it is an explicit, time-bounded migration path per gate.",
                "Local gate compose, sign, decrypt, and state-management operations open at PRIVATE / CONTROL_ONLY once Wormhole itself is ready.",
                "Queued private gate delivery can be accepted locally while the private lane is still warming, but actual gate network release is held until PRIVATE / STRONG.",
                "The local service still retains persisted MLS membership state, so gate chat is content-private but not operator-resistant.",
                "Gate access timing and membership activity remain visible to the service on this lane, especially before stronger private carriers are online.",
                "Use the DM/Dead Drop lane for the strongest transport and confidentiality posture currently available.",
            ],
        },
        "wormhole_gate_lifecycle": {
            "trust_tier": "private_control_only",
            "notes": [
                "Entering a room, choosing an anonymous gate session, and switching gate-local personas are local control-plane actions once Wormhole itself is ready.",
                "Those lifecycle actions and ordinary gate compose/decrypt work once Wormhole itself is ready, even when stronger private carriers are still offline.",
            ],
        },
        "dm_lane": {
            "minimum_transport_tier": dm_release_floor,
            "local_operation_tier": dm_truth["local_operation_tier"],
            "queued_acceptance_tier": dm_truth["queued_acceptance_tier"],
            "network_release_tier": dm_truth["network_release_tier"],
            "poll_tier": _published_transport_tier("/api/mesh/dm/poll", "POST") or "private_strong",
            "reticulum_preferred": True,
            "relay_fallback": True,
            "relay_fallback_operator_opt_in": bool(get_settings().MESH_PRIVATE_RELEASE_APPROVAL_ENABLE),
            "public_transports_excluded": True,
            "notes": [
                "Private DMs stay off the public hashchain.",
                "Local DM compose, decrypt, and key/bootstrap operations open at PRIVATE / CONTROL_ONLY once Wormhole itself is ready.",
                "Queued private DM delivery can be accepted locally while the lane is still warming, but actual DM network release is held until PRIVATE / STRONG.",
                "DM poll/count/block/witness remain private control/state operations and do not imply that private network release is currently allowed.",
                "PRIVATE / STRONG remains the required DM delivery floor because it adds the best current transport/privacy resistance on top of the same encrypted content path.",
                "Public perimeter transports are excluded from secure DM carriage.",
                "Invite-scoped lookup handles are the preferred DM bootstrap path; direct agent_id key lookup remains a weaker compatibility surface.",
                "Private-tier clearnet fallback is blocked by default and only becomes available if an operator explicitly sets MESH_PRIVATE_CLEARNET_FALLBACK=allow and MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true.",
            ],
        },
        "compatibility_sunset": compatibility_sunset,
        "strong_claims": strong_claims,
        "reserved_for_private_strong": [],
        "notes": [
            "Wormhole gate lifecycle actions are available at PRIVATE / CONTROL_ONLY once Wormhole is ready.",
            "Encrypted gate chat keeps local compose/decrypt available at PRIVATE / CONTROL_ONLY, queues sealed delivery locally, and only releases on-network at PRIVATE / STRONG.",
            "DM keeps local compose/decrypt available once Wormhole itself is ready, queues sealed delivery locally, and only releases on-network at PRIVATE / STRONG.",
        ],
    }


# ---------------------------------------------------------------------------
# Anonymous mode state
# ---------------------------------------------------------------------------

def _anonymous_mode_state() -> dict[str, Any]:
    try:
        from services.wormhole_settings import read_wormhole_settings
        from services.wormhole_status import read_wormhole_status

        settings = read_wormhole_settings()
        status = read_wormhole_status()
        enabled = bool(settings.get("enabled"))
        anonymous_mode = bool(settings.get("anonymous_mode"))
        transport_configured = str(settings.get("transport", "direct") or "direct").lower()
        transport_active = str(status.get("transport_active", "") or "").lower()
        effective_transport = transport_active or transport_configured
        ready = bool(status.get("running")) and bool(status.get("ready"))
        hidden_transport_ready = enabled and ready and effective_transport in {
            "tor",
            "tor_arti",
            "i2p",
            "mixnet",
        }
        return {
            "enabled": anonymous_mode,
            "wormhole_enabled": enabled,
            "ready": hidden_transport_ready,
            "effective_transport": effective_transport or "direct",
        }
    except Exception:
        return {
            "enabled": False,
            "wormhole_enabled": False,
            "ready": False,
            "effective_transport": "direct",
        }


# ---------------------------------------------------------------------------
# Peer HMAC verification
# ---------------------------------------------------------------------------

def _peer_hmac_url_from_request(request: Request) -> str:
    header_url = normalize_peer_url(str(request.headers.get("x-peer-url", "") or ""))
    if header_url:
        return header_url
    if not request.url:
        return ""
    base_url = f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
    return normalize_peer_url(base_url)


def _verify_peer_push_hmac(request: Request, body_bytes: bytes) -> bool:
    """Verify HMAC-SHA256 peer authentication on push requests."""
    secret = str(get_settings().MESH_PEER_PUSH_SECRET or "").strip()
    if not secret:
        return False

    provided = str(request.headers.get("x-peer-hmac", "") or "").strip()
    if not provided:
        return False

    peer_url = _peer_hmac_url_from_request(request)
    allowed_peers = set(authenticated_push_peer_urls())
    if not peer_url or peer_url not in allowed_peers:
        return False
    peer_key = _derive_peer_key(secret, peer_url)
    if not peer_key:
        return False

    expected = _hmac_mod.new(
        peer_key,
        body_bytes,
        _hashlib_mod.sha256,
    ).hexdigest()
    return _hmac_mod.compare_digest(provided.lower(), expected.lower())


# ---------------------------------------------------------------------------
# Scoped view helper
# ---------------------------------------------------------------------------

def _scoped_view_authenticated(request: Request, scope: str) -> bool:
    ok, _detail = _check_scoped_auth(request, scope)
    if ok:
        return True
    return _is_debug_test_request(request)


# ---------------------------------------------------------------------------
# Security response headers
# ---------------------------------------------------------------------------

_SECURITY_HEADERS_PROD = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' ws: wss: https:; "
        "font-src 'self' data:; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
_SECURITY_HEADERS_DEBUG = {
    **_SECURITY_HEADERS_PROD,
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' ws: wss: http://127.0.0.1:8000 http://127.0.0.1:8787 https:; "
        "font-src 'self' data:; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    ),
}


def _security_headers() -> dict[str, str]:
    return _SECURITY_HEADERS_DEBUG if _debug_mode_enabled() else _SECURITY_HEADERS_PROD
