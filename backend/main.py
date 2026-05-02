import os
from dotenv import load_dotenv
load_dotenv()

import time
import logging
import asyncio
import base64
import hmac
import importlib
import secrets
import hashlib as _hashlib_mod
from dataclasses import dataclass, field
from typing import Any
from json import JSONDecodeError

APP_VERSION = "0.9.7"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_start_time = time.time()
_MESH_ONLY = os.environ.get("MESH_ONLY", "").strip().lower() in ("1", "true", "yes")
_WARNED_LEGACY_DM_PUBKEY_LOOKUPS: set[str] = set()


def _warn_legacy_dm_pubkey_lookup(agent_id: str) -> None:
    peer_id = str(agent_id or "").strip().lower()
    if not peer_id or peer_id in _WARNED_LEGACY_DM_PUBKEY_LOOKUPS:
        return
    _WARNED_LEGACY_DM_PUBKEY_LOOKUPS.add(peer_id)
    logger.warning(
        "mesh legacy DH pubkey lookup used for %s via direct agent_id; prefer invite-scoped lookup handles before removal in %s",
        stable_metadata_log_ref(peer_id, prefix="peer"),
        sunset_target_label(LEGACY_AGENT_ID_LOOKUP_TARGET),
    )


def _preferred_dm_lookup_target(agent_id: str = "", lookup_token: str = "") -> tuple[str, str]:
    resolved_id = str(agent_id or "").strip()
    resolved_lookup = str(lookup_token or "").strip()
    if resolved_lookup or not resolved_id:
        return resolved_id, resolved_lookup
    try:
        from services.mesh.mesh_wormhole_contacts import preferred_prekey_lookup_handle

        resolved_lookup = preferred_prekey_lookup_handle(resolved_id)
    except Exception:
        resolved_lookup = ""
    return resolved_id, resolved_lookup


def _compatibility_debt_status(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(snapshot or {})
    usage = dict(current.get("usage") or {})
    sunset = dict(current.get("sunset") or {})
    legacy_lookup = dict(usage.get("legacy_agent_id_lookup") or {})
    legacy_dm_get = dict(usage.get("legacy_dm_get") or {})
    dm_get_sunset = dict(sunset.get("legacy_dm_get") or {})
    return {
        "legacy_lookup_reliance": {
            "active": int(legacy_lookup.get("count", 0) or 0) > 0,
            "last_seen_at": int(legacy_lookup.get("last_seen_at", 0) or 0),
            "blocked_count": int(legacy_lookup.get("blocked_count", 0) or 0),
        },
        "legacy_mailbox_get_reliance": {
            "active": int(legacy_dm_get.get("count", 0) or 0) > 0,
            "last_seen_at": int(legacy_dm_get.get("last_seen_at", 0) or 0),
            "blocked_count": int(legacy_dm_get.get("blocked_count", 0) or 0),
            "enabled": not bool(dm_get_sunset.get("blocked", True)),
        },
    }


def _compatibility_readiness_status(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(snapshot or {})
    compatibility_debt = _compatibility_debt_status(current)
    try:
        from services.mesh.mesh_wormhole_contacts import compatibility_lookup_readiness_snapshot

        contact_readiness = dict(compatibility_lookup_readiness_snapshot() or {})
    except Exception:
        contact_readiness = {}
    legacy_lookup_runtime = dict(compatibility_debt.get("legacy_lookup_reliance") or {})
    legacy_mailbox_runtime = dict(compatibility_debt.get("legacy_mailbox_get_reliance") or {})
    return {
        "stored_legacy_lookup_contacts_present": bool(
            contact_readiness.get("stored_legacy_lookup_contacts_present", False)
        ),
        "stored_legacy_lookup_contacts": int(
            contact_readiness.get("stored_legacy_lookup_contacts", 0) or 0
        ),
        "stored_invite_lookup_contacts": int(
            contact_readiness.get("stored_invite_lookup_contacts", 0) or 0
        ),
        "legacy_lookup_runtime_active": bool(legacy_lookup_runtime.get("active", False)),
        "legacy_mailbox_get_runtime_active": bool(legacy_mailbox_runtime.get("active", False)),
        "legacy_mailbox_get_enabled": bool(legacy_mailbox_runtime.get("enabled", False)),
    }


def _scope_allows_exact_local(required_scopes: set[str], allowed_scopes: list[str]) -> bool:
    normalized_required = {str(scope or "").strip() for scope in required_scopes if str(scope or "").strip()}
    normalized_allowed = {
        str(scope or "").strip()
        for scope in list(allowed_scopes or [])
        if str(scope or "").strip()
    }
    return bool(normalized_allowed & normalized_required or "*" in normalized_allowed)


def gate_privileged_access_status_snapshot() -> dict[str, Any]:
    return _gate_privileged_access_status_snapshot_local()


def _check_explicit_scoped_auth_local(
    request: "Request",
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
                if _scope_allows_exact_local(required_scopes, scopes):
                    return True, "ok", "explicit_scoped_token"
                return False, "insufficient scope", ""
    if not admin_key and not scoped_tokens:
        if _allow_insecure_admin() or (_debug_mode_enabled() and host == "test"):
            return True, "ok", "debug_override"
        return False, "Forbidden — admin key not configured", ""
    return False, "Forbidden — invalid or missing admin key", ""


def _gate_privileged_access_status_snapshot_local() -> dict[str, Any]:
    scoped_tokens = _scoped_admin_tokens()
    explicit_audit_configured = any(
        _scope_allows_exact_local({"gate.audit", "mesh.audit"}, scopes)
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
# Docker Swarm Secrets support
# For each VAR below, if VAR_FILE is set (e.g. AIS_API_KEY_FILE=/run/secrets/AIS_API_KEY),
# the file is read and its trimmed content is placed into VAR.
# This MUST run before service imports â€” modules read os.environ at import time.
# ---------------------------------------------------------------------------
_SECRET_VARS = [
    "AIS_API_KEY",
    "OPENSKY_CLIENT_ID",
    "OPENSKY_CLIENT_SECRET",
    "LTA_ACCOUNT_KEY",
    "CORS_ORIGINS",
    "ADMIN_KEY",
    "SHODAN_API_KEY",
    "FINNHUB_API_KEY",
    "MESH_SECURE_STORAGE_SECRET",
]

for _var in _SECRET_VARS:
    _file_var = f"{_var}_FILE"
    _file_path = os.environ.get(_file_var)
    if _file_path:
        try:
            with open(_file_path, "r") as _f:
                _value = _f.read().strip()
            if _value:
                os.environ[_var] = _value
                logger.info(f"Loaded secret {_var} from {_file_path}")
            else:
                logger.warning(f"Secret file {_file_path} for {_var} is empty")
        except FileNotFoundError:
            logger.error(f"Secret file {_file_path} for {_var} not found")
        except Exception as _e:
            logger.error(f"Failed to read secret file {_file_path} for {_var}: {_e}")

from fastapi import APIRouter, FastAPI, Request, Response, Query, Depends, HTTPException
from fastapi.exception_handlers import http_exception_handler as fastapi_http_exception_handler
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.background import BackgroundTask
from contextlib import asynccontextmanager
from services.data_fetcher import (
    start_scheduler,
    stop_scheduler,
    get_latest_data,
)
from services.ais_stream import start_ais_stream, stop_ais_stream
from services.carrier_tracker import start_carrier_tracker, stop_carrier_tracker
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from services.schemas import HealthResponse, RefreshResponse
from services.config import get_settings
import uvicorn
import hashlib
import math
import json as json_mod
import orjson
import socket
from cachetools import TTLCache
import threading
from services.mesh.mesh_crypto import (
    _derive_peer_key,
    derive_node_id,
    normalize_peer_url,
    verify_node_binding,
    parse_public_key_algo,
)
from services.mesh.mesh_compatibility import (
    LEGACY_AGENT_ID_LOOKUP_TARGET,
    compatibility_status_snapshot,
    legacy_agent_id_lookup_blocked,
    legacy_dm1_override_active,
    legacy_dm_get_override_active,
    record_legacy_agent_id_lookup,
    record_legacy_dm_get,
    sunset_target_label,
)
from services.mesh.mesh_protocol import (
    PROTOCOL_VERSION,
    normalize_payload,
)
from services.mesh.mesh_signed_events import (
    MeshWriteExemption,
    SignedWriteKind,
    get_prepared_signed_write,
    mesh_write_exempt,
    recover_verified_gate_reply_to as _shared_recover_verified_gate_reply_to,
    requires_signed_write,
    verify_gate_message_signed_write as _shared_verify_gate_message_signed_write,
    verify_signed_write as _shared_verify_signed_write,
    preflight_signed_event_integrity as _shared_preflight_signed_event_integrity,
    verify_key_rotation_claim_signature,
    verify_node_bound_signature,
    verify_signed_event as _shared_verify_signed_event,
)
from services.mesh.mesh_schema import validate_event_payload
from services.mesh.mesh_privacy_policy import (
    canonical_release_state,
    evaluate_network_release,
    network_release_state,
    queued_delivery_status,
    release_lane_required_tier,
)
from services.mesh.mesh_local_custody import local_custody_status_snapshot
from services.mesh.mesh_metadata_exposure import (
    dm_mailbox_response_view,
    dm_lookup_response_view,
    metadata_exposure_for_request,
    stable_metadata_log_ref,
)
from services.mesh.mesh_private_outbox import private_delivery_outbox
from services.mesh.mesh_private_release_worker import private_release_worker
from services.mesh.mesh_private_transport_manager import private_transport_manager
from services.mesh.mesh_privacy_prewarm import privacy_prewarm_service
from services.mesh.mesh_infonet_sync_support import (
    SyncWorkerState,
    begin_sync,
    eligible_sync_peers,
    finish_sync,
    finish_solo_sync,
    should_run_sync,
)
from services.mesh.mesh_router import (
    authenticated_push_peer_urls,
    configured_relay_peer_urls,
    parse_configured_relay_peers,
    peer_transport_kind,
)

from limiter import limiter
from auth import (
    _allow_insecure_admin,
    _anonymous_mode_state,
    _check_scoped_auth,
    _current_admin_key,
    _current_private_lane_tier,
    _debug_mode_enabled,
    _is_anonymous_dm_action_path,
    _is_anonymous_mesh_write_path,
    _is_anonymous_wormhole_gate_admin_path,
    _is_debug_test_request,
    _is_private_plane_access_path,
    _is_sensitive_no_store_path,
    _minimum_transport_tier,
    _private_plane_access_denied_payload,
    _private_infonet_policy_snapshot,
    _private_plane_refusal_response,
    _scoped_admin_tokens,
    _scoped_view_authenticated as _scoped_view_authenticated_auth,
    _security_headers,
    _strong_claims_policy_snapshot,
    _transport_tier_precondition_payload,
    _transport_tier_is_sufficient,
    _transport_tier_precondition,
    require_admin,
    require_local_operator,
    _validate_admin_startup,
    _validate_insecure_admin_startup,
    _validate_peer_push_secret,
    _verify_peer_push_hmac,
)
from node_state import (
    _NODE_BOOTSTRAP_STATE,
    _NODE_PUSH_STATE,
    _NODE_RUNTIME_LOCK,
    _NODE_SYNC_STOP,
    get_sync_state,
    set_sync_state,
)

# ---------------------------------------------------------------------------
# Router imports
# ---------------------------------------------------------------------------
def _load_optional_router(module_name: str) -> APIRouter:
    try:
        module = importlib.import_module(module_name)
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            return router
        logger.warning("Router module %s did not expose an APIRouter", module_name)
    except Exception as exc:
        logger.warning("Skipping router %s during startup: %s", module_name, type(exc).__name__)
    return APIRouter()


health_router = _load_optional_router("routers.health")
cctv_router = _load_optional_router("routers.cctv")
radio_router = _load_optional_router("routers.radio")
sigint_router = _load_optional_router("routers.sigint")
tools_router = _load_optional_router("routers.tools")
admin_router = _load_optional_router("routers.admin")
data_router = _load_optional_router("routers.data")
mesh_peer_sync_router = _load_optional_router("routers.mesh_peer_sync")
mesh_operator_router = _load_optional_router("routers.mesh_operator")
mesh_oracle_router = _load_optional_router("routers.mesh_oracle")
mesh_dm_router = _load_optional_router("routers.mesh_dm")
mesh_public_router = _load_optional_router("routers.mesh_public")
wormhole_router = _load_optional_router("routers.wormhole")
ai_intel_router = _load_optional_router("routers.ai_intel")
sar_router = _load_optional_router("routers.sar")
infonet_router = _load_optional_router("routers.infonet")


# ---------------------------------------------------------------------------
# Local overrides: keep these in main.py so tests that monkeypatch
# main._check_scoped_auth also affect _scoped_view_authenticated.
# ---------------------------------------------------------------------------
def _scoped_view_authenticated(request, scope: str) -> bool:  # type: ignore[override]
    ok, _detail = _check_scoped_auth(request, scope)
    if ok:
        return True
    return _is_debug_test_request(request)


def _privacy_core_status() -> dict[str, Any]:
    try:
        from services.privacy_core_attestation import privacy_core_attestation

        return dict(privacy_core_attestation())
    except Exception as exc:
        return {
            "available": False,
            "version": "",
            "loaded_version": "",
            "library_path": "",
            "loaded_hash": "",
            "library_sha256": "",
            "attestation_state": "attestation_stale_or_unknown",
            "trusted_hash": "",
            "manifest_source": "",
            "override_active": False,
            "detail": str(exc) or type(exc).__name__,
        }


def _privacy_claims_status(
    *,
    current_tier: str,
    local_custody: dict[str, Any] | None = None,
    privacy_core: dict[str, Any] | None = None,
    compatibility_readiness: dict[str, Any] | None = None,
    gate_privilege_access: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import privacy_claims_snapshot

    return privacy_claims_snapshot(
        transport_tier=current_tier,
        local_custody=dict(local_custody or {}),
        privacy_core=dict(privacy_core or {}),
        compatibility_readiness=dict(compatibility_readiness or {}),
        gate_privilege_access=dict(gate_privilege_access or {}),
    )


def _privacy_status_surface(
    *,
    privacy_claims: dict[str, Any] | None = None,
    strong_claims_allowed: bool | None = None,
    release_gate_ready: bool | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import privacy_status_surface_chip

    return privacy_status_surface_chip(
        dict(privacy_claims or {}),
        strong_claims_allowed=strong_claims_allowed,
        release_gate_ready=release_gate_ready,
    )


def _rollout_readiness_status(
    *,
    privacy_claims: dict[str, Any] | None = None,
    current_tier: str,
    local_custody: dict[str, Any] | None = None,
    privacy_core: dict[str, Any] | None = None,
    compatibility_debt: dict[str, Any] | None = None,
    compatibility_readiness: dict[str, Any] | None = None,
    gate_privilege_access: dict[str, Any] | None = None,
    strong_claims: dict[str, Any] | None = None,
    release_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import rollout_readiness_snapshot

    return rollout_readiness_snapshot(
        privacy_claims=dict(privacy_claims or {}),
        transport_tier=current_tier,
        local_custody=dict(local_custody or {}),
        privacy_core=dict(privacy_core or {}),
        compatibility_debt=dict(compatibility_debt or {}),
        compatibility_readiness=dict(compatibility_readiness or {}),
        gate_privilege_access=dict(gate_privilege_access or {}),
        strong_claims=dict(strong_claims or {}),
        release_gate=dict(release_gate or {}),
    )


def _rollout_controls_status(
    *,
    rollout_readiness: dict[str, Any] | None = None,
    privacy_core: dict[str, Any] | None = None,
    strong_claims: dict[str, Any] | None = None,
    current_tier: str,
) -> dict[str, Any]:
    from services.privacy_claims import rollout_controls_snapshot

    return rollout_controls_snapshot(
        rollout_readiness=dict(rollout_readiness or {}),
        privacy_core=dict(privacy_core or {}),
        strong_claims=dict(strong_claims or {}),
        transport_tier=current_tier,
    )


def _rollout_health_status(
    *,
    rollout_readiness: dict[str, Any] | None = None,
    compatibility_debt: dict[str, Any] | None = None,
    compatibility_readiness: dict[str, Any] | None = None,
    lookup_handle_rotation: dict[str, Any] | None = None,
    gate_repair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import rollout_health_snapshot

    return rollout_health_snapshot(
        rollout_readiness=dict(rollout_readiness or {}),
        compatibility_debt=dict(compatibility_debt or {}),
        compatibility_readiness=dict(compatibility_readiness or {}),
        lookup_handle_rotation=dict(lookup_handle_rotation or {}),
        gate_repair=dict(gate_repair or {}),
    )


def _strong_claims_compat_shim(
    snapshot: dict[str, Any],
    *,
    privacy_claims: dict[str, Any] | None = None,
    privacy_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import strong_claims_compat_shim

    return strong_claims_compat_shim(
        dict(snapshot or {}),
        privacy_claims=dict(privacy_claims or {}),
        privacy_status=dict(privacy_status or {}),
    )


def _release_gate_compat_shim_status(
    snapshot: dict[str, Any],
    *,
    privacy_claims: dict[str, Any] | None = None,
    rollout_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import release_gate_compat_shim

    return release_gate_compat_shim(
        dict(snapshot or {}),
        privacy_claims=dict(privacy_claims or {}),
        rollout_readiness=dict(rollout_readiness or {}),
    )


def _claim_surface_sources_status() -> dict[str, Any]:
    from services.privacy_claims import claim_surface_catalog

    return claim_surface_catalog()


def _review_export_status(
    *,
    privacy_claims: dict[str, Any] | None = None,
    rollout_readiness: dict[str, Any] | None = None,
    rollout_controls: dict[str, Any] | None = None,
    rollout_health: dict[str, Any] | None = None,
    claim_surface_sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import review_export_snapshot

    return review_export_snapshot(
        privacy_claims=dict(privacy_claims or {}),
        rollout_readiness=dict(rollout_readiness or {}),
        rollout_controls=dict(rollout_controls or {}),
        rollout_health=dict(rollout_health or {}),
        claim_surface_sources=dict(claim_surface_sources or {}),
    )


def _final_review_bundle_status(
    *,
    review_export: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import final_review_bundle_snapshot

    return final_review_bundle_snapshot(
        review_export=dict(review_export or {}),
    )


def _staged_rollout_telemetry_status(
    *,
    final_review_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import staged_rollout_telemetry_snapshot

    return staged_rollout_telemetry_snapshot(
        final_review_bundle=dict(final_review_bundle or {}),
    )


def _release_claims_matrix_status(
    *,
    final_review_bundle: dict[str, Any] | None = None,
    staged_rollout_telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import release_claims_matrix_snapshot

    return release_claims_matrix_snapshot(
        final_review_bundle=dict(final_review_bundle or {}),
        staged_rollout_telemetry=dict(staged_rollout_telemetry or {}),
    )


def _release_checklist_status(
    *,
    release_claims_matrix: dict[str, Any] | None = None,
    staged_rollout_telemetry: dict[str, Any] | None = None,
    final_review_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import release_checklist_snapshot

    return release_checklist_snapshot(
        release_claims_matrix=dict(release_claims_matrix or {}),
        staged_rollout_telemetry=dict(staged_rollout_telemetry or {}),
        final_review_bundle=dict(final_review_bundle or {}),
    )


def _explicit_review_export_status(
    *,
    final_review_bundle: dict[str, Any] | None = None,
    staged_rollout_telemetry: dict[str, Any] | None = None,
    release_claims_matrix: dict[str, Any] | None = None,
    release_checklist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import explicit_review_export_snapshot

    return explicit_review_export_snapshot(
        final_review_bundle=dict(final_review_bundle or {}),
        staged_rollout_telemetry=dict(staged_rollout_telemetry or {}),
        release_claims_matrix=dict(release_claims_matrix or {}),
        release_checklist=dict(release_checklist or {}),
    )


def _review_manifest_status(
    *,
    explicit_review_export: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import review_manifest_snapshot

    return review_manifest_snapshot(
        explicit_review_export=dict(explicit_review_export or {}),
    )


def _review_consistency_status(
    *,
    explicit_review_export: dict[str, Any] | None = None,
    review_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.privacy_claims import review_consistency_snapshot

    return review_consistency_snapshot(
        explicit_review_export=dict(explicit_review_export or {}),
        review_manifest=dict(review_manifest or {}),
    )


def _privacy_claim_surface_snapshot(
    *,
    current_tier: str,
    local_custody: dict[str, Any] | None = None,
    privacy_core: dict[str, Any] | None = None,
    contact_preference_refresh: dict[str, Any] | None = None,
) -> dict[str, Any]:
    claim_inputs = _privacy_claim_inputs_snapshot(
        contact_preference_refresh=contact_preference_refresh,
    )
    claims = _privacy_claims_status(
        current_tier=current_tier,
        local_custody=local_custody,
        privacy_core=privacy_core,
        compatibility_readiness=claim_inputs.get("compatibility_readiness"),
        gate_privilege_access=claim_inputs.get("gate_privilege_access"),
    )
    return {
        **claim_inputs,
        "privacy_claims": claims,
    }


def _diagnostic_review_package_snapshot(
    *,
    current_tier: str,
    local_custody: dict[str, Any] | None = None,
    privacy_core: dict[str, Any] | None = None,
    contact_preference_refresh: dict[str, Any] | None = None,
    lookup_handle_rotation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    claim_surface = _privacy_claim_surface_snapshot(
        current_tier=current_tier,
        local_custody=dict(local_custody or {}),
        privacy_core=dict(privacy_core or {}),
        contact_preference_refresh=dict(contact_preference_refresh or {}),
    )
    strong_claims_raw = _strong_claims_policy_snapshot(
        current_tier=current_tier
    )
    release_gate_raw = _release_gate_status(
        current_tier=current_tier,
        strong_claims=strong_claims_raw,
        privacy_core=dict(privacy_core or {}),
        privacy_claims=claim_surface.get("privacy_claims"),
    )
    rollout_readiness = _rollout_readiness_status(
        privacy_claims=claim_surface.get("privacy_claims"),
        current_tier=current_tier,
        local_custody=dict(local_custody or {}),
        privacy_core=dict(privacy_core or {}),
        compatibility_debt=claim_surface.get("compatibility_debt"),
        compatibility_readiness=claim_surface.get("compatibility_readiness"),
        gate_privilege_access=claim_surface.get("gate_privilege_access"),
        strong_claims=strong_claims_raw,
        release_gate=release_gate_raw,
    )
    release_gate_surface = _release_gate_compat_shim_status(
        release_gate_raw,
        privacy_claims=claim_surface.get("privacy_claims"),
        rollout_readiness=rollout_readiness,
    )
    privacy_status = _privacy_status_surface(
        privacy_claims=claim_surface.get("privacy_claims"),
        strong_claims_allowed=strong_claims_raw.get("allowed"),
        release_gate_ready=release_gate_surface.get("ready"),
    )
    strong_claims_surface = _strong_claims_compat_shim(
        strong_claims_raw,
        privacy_claims=claim_surface.get("privacy_claims"),
        privacy_status=privacy_status,
    )
    claim_surface_sources = _claim_surface_sources_status()
    rollout_controls = _rollout_controls_status(
        rollout_readiness=rollout_readiness,
        privacy_core=dict(privacy_core or {}),
        strong_claims=strong_claims_raw,
        current_tier=current_tier,
    )
    rollout_health = _rollout_health_status(
        rollout_readiness=rollout_readiness,
        compatibility_debt=claim_surface.get("compatibility_debt"),
        compatibility_readiness=claim_surface.get("compatibility_readiness"),
        lookup_handle_rotation=dict(lookup_handle_rotation or {}),
    )
    review_export = _review_export_status(
        privacy_claims=claim_surface.get("privacy_claims"),
        rollout_readiness=rollout_readiness,
        rollout_controls=rollout_controls,
        rollout_health=rollout_health,
        claim_surface_sources=claim_surface_sources,
    )
    final_review_bundle = _final_review_bundle_status(
        review_export=review_export,
    )
    staged_rollout_telemetry = _staged_rollout_telemetry_status(
        final_review_bundle=final_review_bundle,
    )
    release_claims_matrix = _release_claims_matrix_status(
        final_review_bundle=final_review_bundle,
        staged_rollout_telemetry=staged_rollout_telemetry,
    )
    release_checklist = _release_checklist_status(
        release_claims_matrix=release_claims_matrix,
        staged_rollout_telemetry=staged_rollout_telemetry,
        final_review_bundle=final_review_bundle,
    )
    explicit_review_export = _explicit_review_export_status(
        final_review_bundle=final_review_bundle,
        staged_rollout_telemetry=staged_rollout_telemetry,
        release_claims_matrix=release_claims_matrix,
        release_checklist=release_checklist,
    )
    return {
        "claim_surface": claim_surface,
        "privacy_status": privacy_status,
        "strong_claims": strong_claims_surface,
        "release_gate": release_gate_surface,
        "rollout_readiness": rollout_readiness,
        "rollout_controls": rollout_controls,
        "rollout_health": rollout_health,
        "claim_surface_sources": claim_surface_sources,
        "review_export": review_export,
        "final_review_bundle": final_review_bundle,
        "staged_rollout_telemetry": staged_rollout_telemetry,
        "release_claims_matrix": release_claims_matrix,
        "release_checklist": release_checklist,
        "explicit_review_export": explicit_review_export,
    }


def _privacy_claim_inputs_snapshot(
    *,
    contact_preference_refresh: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    contact_refresh = dict(contact_preference_refresh or {})
    compatibility_debt: dict[str, Any] = {}
    compatibility_readiness: dict[str, Any] = {}
    compatibility_snapshot: dict[str, Any] = {}
    gate_privilege_access: dict[str, Any] = {}
    try:
        gate_privilege_access = dict(_gate_privileged_access_status_snapshot_local() or {})
    except Exception:
        gate_privilege_access = {}
    try:
        compatibility_snapshot = dict(compatibility_status_snapshot() or {})
        compatibility_debt = _compatibility_debt_status(compatibility_snapshot)
        compatibility_readiness = {
            **_compatibility_readiness_status(compatibility_snapshot),
            "local_contact_upgrade_ok": bool(contact_refresh.get("ok", False)),
            "upgraded_contact_preferences": int(
                contact_refresh.get("upgraded_contacts", 0) or 0
            ),
        }
    except Exception:
        compatibility_snapshot = {}
        compatibility_debt = {}
        compatibility_readiness = {}
    return {
        "compatibility_snapshot": compatibility_snapshot,
        "compatibility_debt": compatibility_debt,
        "compatibility_readiness": compatibility_readiness,
        "gate_privilege_access": gate_privilege_access,
    }


def _release_attestation_snapshot() -> dict[str, Any]:
    settings = get_settings()
    explicit_raw = str(
        getattr(settings, "MESH_RELEASE_ATTESTATION_PATH", "") or ""
    ).strip()
    default_path = Path(__file__).resolve().parent / "data" / "release_attestation.json"
    candidate = Path(explicit_raw) if explicit_raw else default_path
    if not candidate.is_absolute():
        candidate = Path(__file__).resolve().parent / candidate
    source = "env"
    relay_suite_green = bool(
        getattr(settings, "MESH_RELEASE_DM_RELAY_SECURITY_SUITE_GREEN", False)
    )
    detail = (
        "operator attestation present for the DM relay security suite"
        if relay_suite_green
        else "operator attestation for the DM relay security suite is missing"
    )
    generated_at = ""
    commit = ""
    threat_model_reference = "docs/mesh/threat-model.md"
    suite_report = ""
    suite_name = "dm_relay_security"
    workflow = ""
    run_id = ""
    run_attempt = ""
    ref = ""
    file_required = bool(explicit_raw)
    if candidate.exists():
        try:
            payload = orjson.loads(candidate.read_bytes())
            if not isinstance(payload, dict):
                raise ValueError("release attestation payload must be an object")
            source = "file"
            generated_at = str(payload.get("generated_at", "") or "").strip()
            commit = str(payload.get("commit", "") or "").strip()
            threat_model_reference = str(
                payload.get("threat_model_reference", threat_model_reference)
                or threat_model_reference
            ).strip()
            suite = dict(payload.get("dm_relay_security_suite") or {})
            ci = dict(payload.get("ci") or {})
            suite_name = str(suite.get("name", "") or "").strip() or suite_name
            suite_report = str(suite.get("report", "") or "").strip()
            workflow = str(ci.get("workflow", payload.get("workflow", "")) or "").strip()
            run_id = str(ci.get("run_id", payload.get("run_id", "")) or "").strip()
            run_attempt = str(
                ci.get("run_attempt", payload.get("run_attempt", "")) or ""
            ).strip()
            ref = str(ci.get("ref", payload.get("ref", "")) or "").strip()
            relay_suite_green = bool(
                suite.get(
                    "green",
                    payload.get(
                        "dm_relay_security_suite_green",
                        bool(
                            dict(payload.get("criteria") or {}).get(
                                "dm_relay_security_suite_green", False
                            )
                        ),
                    ),
                )
            )
            detail = str(
                suite.get(
                    "detail",
                    "release attestation confirms the DM relay security suite status",
                )
                or "release attestation confirms the DM relay security suite status"
            ).strip()
        except Exception as exc:
            source = "file_error"
            relay_suite_green = False
            detail = f"release attestation unreadable: {str(exc) or type(exc).__name__}"
    elif file_required:
        source = "file_missing"
        relay_suite_green = False
        detail = "configured release attestation file is missing"
    return {
        "source": source,
        "path": str(candidate),
        "generated_at": generated_at,
        "commit": commit,
        "dm_relay_security_suite_green": relay_suite_green,
        "detail": detail,
        "suite_name": suite_name,
        "suite_report": suite_report,
        "threat_model_reference": threat_model_reference,
        "workflow": workflow,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "ref": ref,
    }


def _release_gate_status(
    *,
    current_tier: str | None = None,
    strong_claims: dict[str, Any] | None = None,
    privacy_core: dict[str, Any] | None = None,
    privacy_claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = dict(
        strong_claims or _strong_claims_policy_snapshot(current_tier=current_tier)
    )
    privacy = dict(privacy_core or _privacy_core_status())
    authoritative_claims = dict((privacy_claims or {}).get("claims") or {})
    authoritative_dm = dict(authoritative_claims.get("dm_strong") or {})
    authoritative_gate = dict(authoritative_claims.get("gate_transitional") or {})
    compatibility = dict(snapshot.get("compatibility") or {})
    attestation = _release_attestation_snapshot()
    try:
        from services.release_profiles import profile_readiness_snapshot

        release_profile = profile_readiness_snapshot()
    except Exception:
        release_profile = {
            "profile": "dev",
            "allowed": False,
            "state": "release_profile_unknown",
            "blockers": ["release_profile_unavailable"],
            "detail": "release profile status unavailable",
        }
    relay_suite_green = bool(attestation.get("dm_relay_security_suite_green", False))
    privacy_core_attestation_state = str(
        privacy.get("attestation_state", "") or ""
    ).strip() or (
        "attested_current" if bool(privacy.get("policy_ok", False)) else "attestation_stale_or_unknown"
    )
    privacy_core_pinned = privacy_core_attestation_state == "attested_current"
    compat_overrides_off = bool(snapshot.get("compat_overrides_clear", False))
    clearnet_fallback_blocked = bool(snapshot.get("clearnet_fallback_blocked", False))
    gate_plaintext_persistence_off = not bool(
        compatibility.get("gate_plaintext_persist", False)
    )
    external_assurance_current = bool(snapshot.get("external_assurance_current", False))
    criteria: dict[str, dict[str, Any]] = {
        "dm_relay_security_suite_green": {
            "ok": relay_suite_green,
            "detail": str(attestation.get("detail", "") or "").strip()
            or (
                "release attestation confirms the DM relay security suite status"
                if relay_suite_green
                else "release attestation for the DM relay security suite is missing"
            ),
            "source": str(attestation.get("source", "env") or "env").strip(),
            "path": str(attestation.get("path", "") or "").strip(),
            "generated_at": str(attestation.get("generated_at", "") or "").strip(),
            "commit": str(attestation.get("commit", "") or "").strip(),
            "suite_name": str(attestation.get("suite_name", "") or "").strip(),
            "suite_report": str(attestation.get("suite_report", "") or "").strip(),
            "workflow": str(attestation.get("workflow", "") or "").strip(),
            "run_id": str(attestation.get("run_id", "") or "").strip(),
            "run_attempt": str(attestation.get("run_attempt", "") or "").strip(),
            "ref": str(attestation.get("ref", "") or "").strip(),
        },
        "privacy_core_pinned": {
            "ok": privacy_core_pinned,
            "detail": (
                "privacy-core artifact trust is current"
                if privacy_core_pinned
                else str(privacy.get("detail", "") or "").strip()
                or "privacy-core artifact trust is not currently attested"
            ),
            "attestation_state": privacy_core_attestation_state,
            "loaded_version": str(
                privacy.get("loaded_version", privacy.get("version", "")) or ""
            ).strip(),
            "loaded_hash": str(
                privacy.get("loaded_hash", privacy.get("library_sha256", "")) or ""
            ).strip(),
            "trusted_hash": str(privacy.get("trusted_hash", "") or "").strip(),
            "manifest_source": str(privacy.get("manifest_source", "") or "").strip(),
            "override_active": bool(privacy.get("override_active", False)),
        },
        "compat_overrides_off": {
            "ok": compat_overrides_off,
            "detail": (
                "compatibility sunset overrides are clear"
                if compat_overrides_off
                else "one or more compatibility sunset overrides are still active"
            ),
        },
        "clearnet_fallback_blocked": {
            "ok": clearnet_fallback_blocked,
            "detail": (
                "private-lane clearnet fallback is blocked"
                if clearnet_fallback_blocked
                else "private-lane clearnet fallback is still allowed"
            ),
        },
        "gate_plaintext_persistence_off": {
            "ok": gate_plaintext_persistence_off,
            "detail": (
                "durable gate plaintext persistence is off"
                if gate_plaintext_persistence_off
                else "durable gate plaintext persistence is enabled"
            ),
        },
        "external_assurance_current": {
            "ok": external_assurance_current,
            "detail": str(snapshot.get("external_assurance_detail", "") or "").strip()
            or (
                "external witness and transparency assurances are current"
                if external_assurance_current
                else "external assurance is not current"
            ),
            "state": str(
                snapshot.get("external_assurance_state", "unknown") or "unknown"
            ).strip(),
            "configured": bool(snapshot.get("external_assurance_configured", False)),
        },
        "release_profile_ready": {
            "ok": bool(release_profile.get("allowed", False)),
            "detail": str(release_profile.get("detail", "") or "").strip(),
            "profile": str(release_profile.get("profile", "") or "").strip(),
            "state": str(release_profile.get("state", "") or "").strip(),
            "blockers": list(release_profile.get("blockers") or []),
        },
    }
    if privacy_claims:
        criteria["authoritative_dm_claim_ready"] = {
            "ok": bool(authoritative_dm.get("allowed", False)),
            "detail": str(authoritative_dm.get("plain_label", "") or "").strip(),
            "state": str(authoritative_dm.get("state", "") or "").strip(),
        }
        criteria["authoritative_gate_claim_ready"] = {
            "ok": bool(authoritative_gate.get("allowed", False)),
            "detail": str(authoritative_gate.get("plain_label", "") or "").strip(),
            "state": str(authoritative_gate.get("state", "") or "").strip(),
        }
    blocking = [
        name
        for name, criterion in criteria.items()
        if not bool(criterion.get("ok", False))
    ]
    return {
        "ready": not blocking,
        "detail": "release gate satisfied" if not blocking else "release gate pending",
        "blocking_reasons": blocking,
        "next_action": blocking[0] if blocking else "",
        "criteria": criteria,
        "attestation": attestation,
        "release_profile": release_profile,
        "compatibility_shim": True,
        "source_model": "privacy_claims",
        "authoritative_dm_claim_state": str(authoritative_dm.get("state", "") or "").strip(),
        "authoritative_gate_claim_state": str(authoritative_gate.get("state", "") or "").strip(),
        "threat_model_reference": str(
            attestation.get("threat_model_reference", "docs/mesh/threat-model.md")
            or "docs/mesh/threat-model.md"
        ).strip(),
    }


def _validate_privacy_core_startup() -> None:
    from services.privacy_core_attestation import validate_privacy_core_startup

    validate_privacy_core_startup()


def _public_mesh_log_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    tier_str = str((entry or {}).get("trust_tier", "public_degraded") or "public_degraded").strip().lower()
    if tier_str.startswith("private_"):
        return None
    return {
        "sender": str((entry or {}).get("sender", "") or ""),
        "destination": str((entry or {}).get("destination", "") or ""),
        "routed_via": str((entry or {}).get("routed_via", "") or ""),
        "priority": str((entry or {}).get("priority", "") or ""),
        "route_reason": str((entry or {}).get("route_reason", "") or ""),
        "timestamp": float((entry or {}).get("timestamp", 0) or 0),
    }


def _public_mesh_log_size(entries: list[dict[str, Any]]) -> int:
    return sum(1 for item in entries if _public_mesh_log_entry(item) is not None)


_WORMHOLE_PUBLIC_SETTINGS_FIELDS = {"enabled", "transport", "anonymous_mode"}
_WORMHOLE_PUBLIC_PROFILE_FIELDS = {"profile", "wormhole_enabled"}
_PRIVATE_LANE_CONTROL_FIELDS = {"private_lane_tier", "private_lane_policy"}
_PUBLIC_RNS_STATUS_FIELDS = {"enabled", "ready", "configured_peers", "active_peers"}
_NODE_PUBLIC_EVENT_HOOK_REGISTERED = False


def _current_node_mode() -> str:
    mode = str(get_settings().MESH_NODE_MODE or "participant").strip().lower()
    if mode not in {"participant", "relay", "perimeter"}:
        return "participant"
    return mode


def _node_runtime_supported() -> bool:
    return _current_node_mode() in {"participant", "relay"}


def _node_activation_enabled() -> bool:
    from services.node_settings import read_node_settings

    try:
        settings = read_node_settings()
    except Exception:
        return False
    return bool(settings.get("enabled", False))


def _participant_node_enabled() -> bool:
    return _node_runtime_supported() and _node_activation_enabled()


def _node_runtime_snapshot() -> dict[str, Any]:
    with _NODE_RUNTIME_LOCK:
        return {
            "node_mode": _NODE_BOOTSTRAP_STATE.get("node_mode", "participant"),
            "node_enabled": _participant_node_enabled(),
            "bootstrap": dict(_NODE_BOOTSTRAP_STATE),
            "sync_runtime": get_sync_state().to_dict(),
            "push_runtime": dict(_NODE_PUSH_STATE),
        }


def _set_node_sync_disabled_state(*, current_head: str = "") -> SyncWorkerState:
    return SyncWorkerState(
        current_head=str(current_head or ""),
        last_outcome="disabled",
    )


def _set_participant_node_enabled(enabled: bool) -> dict[str, Any]:
    from services.mesh.mesh_hashchain import infonet
    from services.node_settings import write_node_settings

    settings = write_node_settings(enabled=bool(enabled))
    current_head = str(infonet.head_hash or "")
    with _NODE_RUNTIME_LOCK:
        _NODE_BOOTSTRAP_STATE["node_mode"] = _current_node_mode()
        set_sync_state(
            SyncWorkerState(current_head=current_head)
            if bool(enabled) and _node_runtime_supported()
            else _set_node_sync_disabled_state(current_head=current_head)
        )
    return {
        **settings,
        "node_mode": _current_node_mode(),
        "node_enabled": _participant_node_enabled(),
    }


def _refresh_node_peer_store(*, now: float | None = None) -> dict[str, Any]:
    from services.mesh.mesh_bootstrap_manifest import load_bootstrap_manifest_from_settings
    from services.mesh.mesh_peer_store import (
        DEFAULT_PEER_STORE_PATH,
        PeerStore,
        make_bootstrap_peer_record,
        make_push_peer_record,
        make_sync_peer_record,
    )

    timestamp = int(now if now is not None else time.time())
    mode = _current_node_mode()
    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception:
        store = PeerStore(DEFAULT_PEER_STORE_PATH)

    operator_peers = configured_relay_peer_urls()
    default_sync_peers = parse_configured_relay_peers(
        str(getattr(get_settings(), "MESH_DEFAULT_SYNC_PEERS", "") or "")
    )
    for peer_url in operator_peers:
        transport = peer_transport_kind(peer_url)
        if not transport:
            continue
        store.upsert(
            make_sync_peer_record(
                peer_url=peer_url,
                transport=transport,
                role="relay",
                source="operator",
                now=timestamp,
            )
        )
        store.upsert(
            make_push_peer_record(
                peer_url=peer_url,
                transport=transport,
                role="relay",
                source="operator",
                now=timestamp,
            )
        )

    operator_peer_set = set(operator_peers)
    for peer_url in default_sync_peers:
        if peer_url in operator_peer_set:
            continue
        transport = peer_transport_kind(peer_url)
        if not transport:
            continue
        store.upsert(
            make_bootstrap_peer_record(
                peer_url=peer_url,
                transport=transport,
                role="seed",
                label="ShadowBroker default seed",
                signer_id="shadowbroker-default",
                now=timestamp,
            )
        )
        store.upsert(
            make_sync_peer_record(
                peer_url=peer_url,
                transport=transport,
                role="seed",
                source="bundle",
                label="ShadowBroker default seed",
                signer_id="shadowbroker-default",
                now=timestamp,
            )
        )

    manifest = None
    bootstrap_error = ""
    try:
        manifest = load_bootstrap_manifest_from_settings(now=timestamp)
    except Exception as exc:
        bootstrap_error = str(exc or "").strip()

    if manifest is not None:
        for peer in manifest.peers:
            store.upsert(
                make_bootstrap_peer_record(
                    peer_url=peer.peer_url,
                    transport=peer.transport,
                    role=peer.role,
                    label=peer.label,
                    signer_id=manifest.signer_id,
                    now=timestamp,
                )
            )
            store.upsert(
                make_sync_peer_record(
                    peer_url=peer.peer_url,
                    transport=peer.transport,
                    role=peer.role,
                    source="bootstrap_promoted",
                    label=peer.label,
                    signer_id=manifest.signer_id,
                    now=timestamp,
                )
            )

    store.save()
    snapshot = {
        "node_mode": mode,
        "manifest_loaded": manifest is not None,
        "manifest_signer_id": manifest.signer_id if manifest is not None else "",
        "manifest_valid_until": int(manifest.valid_until or 0) if manifest is not None else 0,
        "bootstrap_peer_count": len(store.records_for_bucket("bootstrap")),
        "sync_peer_count": len(store.records_for_bucket("sync")),
        "push_peer_count": len(store.records_for_bucket("push")),
        "operator_peer_count": len(operator_peers),
        "default_sync_peer_count": len(default_sync_peers),
        "last_bootstrap_error": bootstrap_error,
    }
    with _NODE_RUNTIME_LOCK:
        _NODE_BOOTSTRAP_STATE.update(snapshot)
    return snapshot


def _materialize_local_infonet_state() -> None:
    from services.mesh.mesh_hashchain import infonet

    infonet.ensure_materialized()


def _peer_sync_response(peer_url: str, body: dict[str, Any]) -> dict[str, Any]:
    import requests as _requests
    from services.wormhole_supervisor import _check_arti_ready

    normalized = normalize_peer_url(peer_url)
    if not normalized:
        raise ValueError("invalid peer URL")

    timeout = int(get_settings().MESH_RELAY_PUSH_TIMEOUT_S or 10)
    kwargs: dict[str, Any] = {
        "json": body,
        "timeout": timeout,
        "headers": {"Content-Type": "application/json"},
    }
    if peer_transport_kind(normalized) == "onion":
        if not bool(get_settings().MESH_ARTI_ENABLED):
            raise RuntimeError("onion sync requires Arti to be enabled")
        if not _check_arti_ready():
            raise RuntimeError("onion sync requires a ready Arti transport")
        socks_port = int(get_settings().MESH_ARTI_SOCKS_PORT or 9050)
        proxy = f"socks5h://127.0.0.1:{socks_port}"
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    response = _requests.post(f"{normalized}/api/mesh/infonet/sync", **kwargs)
    try:
        payload = response.json()
    except Exception as exc:
        raise ValueError(f"peer sync returned non-JSON response ({response.status_code})") from exc
    if response.status_code != 200:
        detail = str(payload.get("detail", "") or f"HTTP {response.status_code}").strip()
        raise ValueError(detail or f"HTTP {response.status_code}")
    if not isinstance(payload, dict):
        raise ValueError("peer sync returned malformed payload")
    return payload


def _hydrate_gate_store_from_chain(events: list[dict]) -> int:
    """Copy any gate_message chain events into the local gate_store for read/decrypt.

    Only events that are resident in the local infonet (accepted or already
    present) are hydrated.  The canonical infonet-resident event is used â€”
    never the raw batch event â€” so a forged batch entry carrying a valid
    event_id but attacker-chosen payload cannot pollute gate_store.
    """
    import copy

    from services.mesh.mesh_hashchain import gate_store, infonet

    count = 0
    for evt in events:
        if evt.get("event_type") != "gate_message":
            continue
        event_id = str(evt.get("event_id", "") or "").strip()
        if not event_id or event_id not in infonet.event_index:
            continue
        # Use the canonical infonet-resident event, not the raw batch event.
        canonical = infonet.events[infonet.event_index[event_id]]
        payload = canonical.get("payload") or {}
        gate_id = str(payload.get("gate", "") or "").strip()
        if not gate_id:
            continue
        try:
            gate_store.append(gate_id, copy.deepcopy(canonical))
            count += 1
        except Exception:
            pass
    return count


def _sync_from_peer(peer_url: str, *, page_limit: int = 100, max_rounds: int = 5) -> tuple[bool, str, bool]:
    from services.mesh.mesh_hashchain import infonet

    rounds = 0
    while rounds < max_rounds:
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "locator": infonet.get_locator(),
            "limit": page_limit,
        }
        payload = _peer_sync_response(peer_url, body)
        if bool(payload.get("forked")):
            # Auto-recover small local forks: if the local chain is tiny
            # (< 20 events) and the remote has a longer chain, reset local
            # state and re-sync from genesis instead of failing forever.
            remote_count = int(payload.get("count", 0) or 0)
            local_count = len(infonet.events)
            if local_count < 20:
                logger.warning(
                    "Fork detected with small local chain (%d events). "
                    "Resetting to re-sync from peer (remote has %d events).",
                    local_count,
                    remote_count,
                )
                infonet.reset_chain()
                continue  # retry sync with clean genesis locator
            return False, "fork detected", True
        events = payload.get("events", [])
        if not isinstance(events, list):
            return False, "peer sync events must be a list", False
        if not events:
            return True, "", False
        result = infonet.ingest_events(events)
        _hydrate_gate_store_from_chain(events)
        rejected = list(result.get("rejected", []) or [])
        if rejected:
            return False, f"sync ingest rejected {len(rejected)} event(s)", False
        if int(result.get("accepted", 0) or 0) == 0 and int(result.get("duplicates", 0) or 0) >= len(events):
            return True, "", False
        if len(events) < page_limit:
            return True, "", False
        rounds += 1
    return True, "", False


def _run_public_sync_cycle() -> SyncWorkerState:
    from services.mesh.mesh_hashchain import infonet
    from services.mesh.mesh_peer_store import DEFAULT_PEER_STORE_PATH, PeerStore

    if not _participant_node_enabled():
        updated = _set_node_sync_disabled_state(current_head=infonet.head_hash)
        with _NODE_RUNTIME_LOCK:
            set_sync_state(updated)
        return updated

    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception:
        store = PeerStore(DEFAULT_PEER_STORE_PATH)

    peers = eligible_sync_peers(store.records(), now=time.time())
    with _NODE_RUNTIME_LOCK:
        current_state = get_sync_state()
    if not peers:
        updated = finish_solo_sync(
            current_state,
            now=time.time(),
            current_head=infonet.head_hash,
            interval_s=int(get_settings().MESH_SYNC_INTERVAL_S or 300),
        )
        with _NODE_RUNTIME_LOCK:
            set_sync_state(updated)
        return updated

    last_error = "sync failed"
    for record in peers:
        started = begin_sync(
            current_state,
            peer_url=record.peer_url,
            current_head=infonet.head_hash,
            now=time.time(),
        )
        with _NODE_RUNTIME_LOCK:
            set_sync_state(started)
        try:
            ok, error, forked = _sync_from_peer(record.peer_url)
        except Exception as exc:
            ok = False
            error = str(exc or type(exc).__name__)
            forked = False
        if ok:
            store.mark_seen(record.peer_url, "sync", now=time.time())
            store.mark_sync_success(record.peer_url, now=time.time())
            store.save()
            updated = finish_sync(
                started,
                ok=True,
                peer_url=record.peer_url,
                current_head=infonet.head_hash,
                now=time.time(),
                interval_s=int(get_settings().MESH_SYNC_INTERVAL_S or 300),
            )
            with _NODE_RUNTIME_LOCK:
                set_sync_state(updated)
            return updated

        last_error = error
        store.mark_failure(
            record.peer_url,
            "sync",
            error=error,
            cooldown_s=int(get_settings().MESH_RELAY_FAILURE_COOLDOWN_S or 120),
            now=time.time(),
        )
        store.save()
        updated = finish_sync(
            started,
            ok=False,
            peer_url=record.peer_url,
            current_head=infonet.head_hash,
            error=error,
            fork_detected=forked,
            now=time.time(),
            interval_s=int(get_settings().MESH_SYNC_INTERVAL_S or 300),
            failure_backoff_s=int(get_settings().MESH_SYNC_FAILURE_BACKOFF_S or 60),
        )
        with _NODE_RUNTIME_LOCK:
            set_sync_state(updated)
        if forked:
            return updated
        current_state = updated

    return updated if peers else finish_sync(
        current_state,
        ok=False,
        error=last_error,
        now=time.time(),
        current_head=infonet.head_hash,
        failure_backoff_s=int(get_settings().MESH_SYNC_FAILURE_BACKOFF_S or 60),
    )


def _public_infonet_sync_loop() -> None:
    from services.mesh.mesh_hashchain import infonet

    while not _NODE_SYNC_STOP.is_set():
        try:
            if not _node_runtime_supported():
                _NODE_SYNC_STOP.wait(5.0)
                continue
            if not _participant_node_enabled():
                disabled = _set_node_sync_disabled_state(current_head=infonet.head_hash)
                with _NODE_RUNTIME_LOCK:
                    set_sync_state(disabled)
                _NODE_SYNC_STOP.wait(5.0)
                continue
            with _NODE_RUNTIME_LOCK:
                state = get_sync_state()
            if should_run_sync(state, now=time.time()):
                _run_public_sync_cycle()
        except Exception:
            logger.exception("public infonet sync loop failed")
        _NODE_SYNC_STOP.wait(5.0)


def _record_public_push_result(event_id: str, *, ok: bool, error: str = "", results: list[dict[str, Any]] | None = None) -> None:
    with _NODE_RUNTIME_LOCK:
        snapshot = {
            "last_event_id": str(event_id or ""),
            "last_push_ok_at": int(time.time()) if ok else int(_NODE_PUSH_STATE.get("last_push_ok_at", 0) or 0),
            "last_push_error": "" if ok else str(error or "").strip(),
            "last_results": list(results or []),
        }
        _NODE_PUSH_STATE.update(snapshot)


def _propagate_public_event_to_peers(event_dict: dict[str, Any]) -> None:
    from services.mesh.mesh_router import MeshEnvelope, mesh_router

    if not _participant_node_enabled():
        return
    if not authenticated_push_peer_urls():
        return

    envelope = MeshEnvelope(
        sender_id=str(event_dict.get("node_id", "") or ""),
        destination="broadcast",
        payload=json_mod.dumps(event_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        trust_tier="public_degraded",
    )
    results = []
    for transport in (mesh_router.internet, mesh_router.tor_arti):
        try:
            if transport.can_reach(envelope):
                result = transport.send(envelope, {})
                results.append(result.to_dict())
        except Exception as exc:
            results.append({"ok": False, "transport": getattr(transport, "NAME", "unknown"), "detail": type(exc).__name__})
    ok = any(bool(result.get("ok")) for result in results)
    _record_public_push_result(
        str(event_dict.get("event_id", "") or ""),
        ok=ok,
        error="" if ok else "all push peers failed",
        results=results,
    )


def _schedule_public_event_propagation(event_dict: dict[str, Any]) -> None:
    threading.Thread(
        target=_propagate_public_event_to_peers,
        args=(dict(event_dict),),
        daemon=True,
    ).start()


# â”€â”€â”€ Background HTTP Peer Push Worker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Runs alongside the sync loop.  Every PUSH_INTERVAL seconds, batches new
# Infonet events and sends them via HMAC-authenticated POST to push peers.

_PEER_PUSH_INTERVAL_S = 10
_PEER_PUSH_BATCH_SIZE = 50
_peer_push_last_index: dict[str, int] = {}  # peer_url â†’ last pushed event index


def _http_peer_push_loop() -> None:
    """Background thread: push new Infonet events to HTTP peers."""
    import requests as _requests
    from services.mesh.mesh_hashchain import infonet
    from services.mesh.mesh_peer_store import DEFAULT_PEER_STORE_PATH, PeerStore

    while not _NODE_SYNC_STOP.is_set():
        try:
            if not _participant_node_enabled():
                _NODE_SYNC_STOP.wait(_PEER_PUSH_INTERVAL_S)
                continue

            secret = str(get_settings().MESH_PEER_PUSH_SECRET or "").strip()
            if not secret:
                _NODE_SYNC_STOP.wait(_PEER_PUSH_INTERVAL_S)
                continue

            peers = authenticated_push_peer_urls()
            if not peers:
                _NODE_SYNC_STOP.wait(_PEER_PUSH_INTERVAL_S)
                continue

            all_events = infonet.events
            total = len(all_events)

            for peer_url in peers:
                normalized = normalize_peer_url(peer_url)
                if not normalized:
                    continue
                last_idx = _peer_push_last_index.get(normalized, 0)
                if last_idx >= total:
                    continue  # nothing new

                batch = all_events[last_idx : last_idx + _PEER_PUSH_BATCH_SIZE]
                if not batch:
                    continue

                try:
                    body_bytes = json_mod.dumps(
                        {"events": batch},
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")

                    peer_key = _derive_peer_key(secret, normalized)
                    if not peer_key:
                        continue
                    import hmac as _hmac_mod2
                    import hashlib as _hashlib_mod2
                    hmac_hex = _hmac_mod2.new(peer_key, body_bytes, _hashlib_mod2.sha256).hexdigest()

                    timeout = int(get_settings().MESH_RELAY_PUSH_TIMEOUT_S or 10)
                    resp = _requests.post(
                        f"{normalized}/api/mesh/infonet/peer-push",
                        data=body_bytes,
                        headers={
                            "Content-Type": "application/json",
                            "X-Peer-HMAC": hmac_hex,
                        },
                        timeout=timeout,
                    )
                    if resp.status_code == 200:
                        _peer_push_last_index[normalized] = last_idx + len(batch)
                        logger.info(
                            f"Pushed {len(batch)} event(s) to {normalized[:40]} "
                            f"(idx {last_idx}â†’{last_idx + len(batch)})"
                        )
                    else:
                        logger.warning(f"Peer push to {normalized[:40]} returned {resp.status_code}")
                except Exception as exc:
                    logger.warning(f"Peer push to {normalized[:40]} failed: {exc}")

        except Exception:
            logger.exception("HTTP peer push loop error")
        _NODE_SYNC_STOP.wait(_PEER_PUSH_INTERVAL_S)


# â”€â”€â”€ Background Gate Message Pull Worker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Periodically pulls gate events from relay peers that this node is missing.
# Complements the push loop: push sends OUR events to peers, pull fetches
# THEIR events from peers (needed when this node is behind NAT).

_GATE_PULL_INTERVAL_S = 10
_gate_pull_last_count: dict[str, dict[str, int]] = {}  # peer â†’ {gate_id â†’ known count}


def _http_gate_pull_loop() -> None:
    """Background thread: pull new gate messages from HTTP relay peers."""
    import requests as _requests
    from services.mesh.mesh_hashchain import gate_store

    while not _NODE_SYNC_STOP.is_set():
        try:
            if not _participant_node_enabled():
                _NODE_SYNC_STOP.wait(_GATE_PULL_INTERVAL_S)
                continue

            secret = str(get_settings().MESH_PEER_PUSH_SECRET or "").strip()
            if not secret:
                _NODE_SYNC_STOP.wait(_GATE_PULL_INTERVAL_S)
                continue

            peers = authenticated_push_peer_urls()
            if not peers:
                _NODE_SYNC_STOP.wait(_GATE_PULL_INTERVAL_S)
                continue

            for peer_url in peers:
                normalized = normalize_peer_url(peer_url)
                if not normalized:
                    continue

                peer_key = _derive_peer_key(secret, normalized)
                if not peer_key:
                    continue

                peer_counts = _gate_pull_last_count.setdefault(normalized, {})

                try:
                    # Step 1: Ask the peer which gates it has and how many events each
                    discovery_body = json_mod.dumps(
                        {"gate_id": "", "after_count": 0},
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")

                    import hmac as _hmac_pull
                    import hashlib as _hashlib_pull
                    discovery_hmac = _hmac_pull.new(peer_key, discovery_body, _hashlib_pull.sha256).hexdigest()

                    timeout = int(get_settings().MESH_RELAY_PUSH_TIMEOUT_S or 10)
                    resp = _requests.post(
                        f"{normalized}/api/mesh/gate/peer-pull",
                        data=discovery_body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Peer-HMAC": discovery_hmac,
                        },
                        timeout=timeout,
                    )
                    if resp.status_code != 200:
                        continue
                    discovery = resp.json()
                    if not discovery.get("ok"):
                        continue
                    remote_gates: dict[str, int] = discovery.get("gates", {})
                    if not remote_gates:
                        continue

                    # Step 2: For each gate with new events, pull the batch
                    for gate_id, remote_total in remote_gates.items():
                        local_known = peer_counts.get(gate_id, 0)
                        # Also account for what we already have locally
                        with gate_store._lock:
                            local_count = len(gate_store._gates.get(gate_id, []))
                        effective_cursor = max(local_known, local_count)
                        if effective_cursor >= remote_total:
                            continue

                        pull_body = json_mod.dumps(
                            {"gate_id": gate_id, "after_count": effective_cursor},
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ).encode("utf-8")

                        pull_hmac = _hmac_pull.new(peer_key, pull_body, _hashlib_pull.sha256).hexdigest()

                        pull_resp = _requests.post(
                            f"{normalized}/api/mesh/gate/peer-pull",
                            data=pull_body,
                            headers={
                                "Content-Type": "application/json",
                                "X-Peer-HMAC": pull_hmac,
                            },
                            timeout=timeout,
                        )
                        if pull_resp.status_code != 200:
                            continue
                        pull_data = pull_resp.json()
                        if not pull_data.get("ok"):
                            continue

                        events = pull_data.get("events", [])
                        if not events:
                            peer_counts[gate_id] = remote_total
                            continue

                        result = gate_store.ingest_peer_events(gate_id, events)
                        accepted = int(result.get("accepted", 0) or 0)
                        dups = int(result.get("duplicates", 0) or 0)
                        if accepted > 0:
                            logger.info(
                                "Gate pull: %d new event(s) for %s from %s",
                                accepted, gate_id[:12], normalized[:40],
                            )
                        peer_counts[gate_id] = effective_cursor + len(events)

                except Exception as exc:
                    logger.warning("Gate pull from %s failed: %s", normalized[:40], exc)

        except Exception:
            logger.exception("HTTP gate pull loop error")
        _NODE_SYNC_STOP.wait(_GATE_PULL_INTERVAL_S)




# â”€â”€â”€ Background Gate Message Push Worker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_gate_push_last_count: dict[str, dict[str, int]] = {}  # peer â†’ {gate_id â†’ count}


def _http_gate_push_loop() -> None:
    """Background thread: push new gate messages to HTTP peers."""
    import requests as _requests
    from services.mesh.mesh_hashchain import gate_store

    while not _NODE_SYNC_STOP.is_set():
        try:
            if not _participant_node_enabled():
                _NODE_SYNC_STOP.wait(_PEER_PUSH_INTERVAL_S)
                continue

            secret = str(get_settings().MESH_PEER_PUSH_SECRET or "").strip()
            if not secret:
                _NODE_SYNC_STOP.wait(_PEER_PUSH_INTERVAL_S)
                continue

            peers = authenticated_push_peer_urls()
            if not peers:
                _NODE_SYNC_STOP.wait(_PEER_PUSH_INTERVAL_S)
                continue

            with gate_store._lock:
                gate_ids = list(gate_store._gates.keys())

            for peer_url in peers:
                normalized = normalize_peer_url(peer_url)
                if not normalized:
                    continue

                peer_key = _derive_peer_key(secret, normalized)
                if not peer_key:
                    continue

                peer_counts = _gate_push_last_count.setdefault(normalized, {})

                for gate_id in gate_ids:
                    with gate_store._lock:
                        all_events = list(gate_store._gates.get(gate_id, []))
                    total = len(all_events)
                    last = peer_counts.get(gate_id, 0)
                    if last >= total:
                        continue

                    batch = all_events[last : last + _PEER_PUSH_BATCH_SIZE]
                    if not batch:
                        continue

                    try:
                        body_bytes = json_mod.dumps(
                            {"events": batch},
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ).encode("utf-8")

                        import hmac as _hmac_mod3
                        import hashlib as _hashlib_mod3
                        hmac_hex = _hmac_mod3.new(peer_key, body_bytes, _hashlib_mod3.sha256).hexdigest()

                        timeout = int(get_settings().MESH_RELAY_PUSH_TIMEOUT_S or 10)
                        resp = _requests.post(
                            f"{normalized}/api/mesh/gate/peer-push",
                            data=body_bytes,
                            headers={
                                "Content-Type": "application/json",
                                "X-Peer-HMAC": hmac_hex,
                            },
                            timeout=timeout,
                        )
                        if resp.status_code == 200:
                            peer_counts[gate_id] = last + len(batch)
                            logger.info(
                                f"Gate push: {len(batch)} event(s) for {gate_id[:12]} "
                                f"to {normalized[:40]}"
                            )
                        else:
                            logger.warning(
                                f"Gate push to {normalized[:40]} returned {resp.status_code}"
                            )
                    except Exception as exc:
                        logger.warning(f"Gate push to {normalized[:40]} failed: {exc}")

        except Exception:
            logger.exception("HTTP gate push loop error")
        _NODE_SYNC_STOP.wait(_PEER_PUSH_INTERVAL_S)


def _redacted_gate_timestamp(event: dict[str, Any]) -> float:
    raw_ts = float((event or {}).get("timestamp", 0) or 0.0)
    if raw_ts <= 0:
        return 0.0
    try:
        jitter_window = max(0, int(get_settings().MESH_GATE_TIMESTAMP_JITTER_S or 0))
    except Exception:
        jitter_window = 0
    if jitter_window <= 0:
        return raw_ts
    event_id = str((event or {}).get("event_id", "") or "")
    seed = _hashlib_mod.sha256(f"{event_id}|{int(raw_ts)}".encode("utf-8")).digest()
    fraction = int.from_bytes(seed[:8], "big") / float(2**64 - 1)
    return max(0.0, raw_ts - (fraction * float(jitter_window)))


def _redact_wormhole_settings(settings: dict[str, Any], authenticated: bool) -> dict[str, Any]:
    if authenticated:
        return dict(settings)
    return {
        key: settings.get(key)
        for key in _WORMHOLE_PUBLIC_SETTINGS_FIELDS
        if key in settings
    }


def _redact_privacy_profile_settings(
    settings: dict[str, Any],
    authenticated: bool,
) -> dict[str, Any]:
    profile = {
        "profile": settings.get("privacy_profile", "default"),
        "wormhole_enabled": bool(settings.get("enabled")),
        "transport": settings.get("transport", "direct"),
        "anonymous_mode": bool(settings.get("anonymous_mode")),
    }
    if authenticated:
        return profile
    return {
        key: profile.get(key)
        for key in _WORMHOLE_PUBLIC_PROFILE_FIELDS
    }


def _redact_private_lane_control_fields(
    payload: dict[str, Any],
    authenticated: bool,
) -> dict[str, Any]:
    redacted = dict(payload)
    if authenticated:
        return redacted
    for field in _PRIVATE_LANE_CONTROL_FIELDS:
        redacted.pop(field, None)
    return redacted


def _redact_public_rns_status(
    payload: dict[str, Any],
    authenticated: bool,
) -> dict[str, Any]:
    redacted = _redact_private_lane_control_fields(payload, authenticated=authenticated)
    if authenticated:
        return redacted
    return {
        key: redacted.get(key)
        for key in _PUBLIC_RNS_STATUS_FIELDS
        if key in redacted
    }


def _redact_public_mesh_status(
    payload: dict[str, Any],
    authenticated: bool,
) -> dict[str, Any]:
    if authenticated:
        return dict(payload)
    return {
        "message_log_size": int(payload.get("message_log_size", 0) or 0),
    }


def _redact_public_oracle_profile(
    payload: dict[str, Any],
    authenticated: bool,
) -> dict[str, Any]:
    redacted = dict(payload)
    if authenticated:
        return redacted
    redacted["active_stakes"] = []
    redacted["prediction_history"] = []
    return redacted


def _redact_public_oracle_predictions(
    predictions: list[dict[str, Any]],
    authenticated: bool,
) -> dict[str, Any]:
    if authenticated:
        return {"predictions": list(predictions)}
    return {
        "predictions": [],
        "count": len(predictions),
    }


def _redact_public_oracle_stakes(
    payload: dict[str, Any],
    authenticated: bool,
) -> dict[str, Any]:
    redacted = dict(payload)
    if authenticated:
        return redacted
    redacted["truth_stakers"] = []
    redacted["false_stakers"] = []
    return redacted


def _redact_public_node_history(
    events: list[dict[str, Any]],
    authenticated: bool,
) -> list[dict[str, Any]]:
    if authenticated:
        return [dict(event) for event in events]
    return [
        {
            "event_id": str(event.get("event_id", "") or ""),
            "event_type": str(event.get("event_type", "") or ""),
            "timestamp": float(event.get("timestamp", 0) or 0),
        }
        for event in events
    ]


def _redact_composed_gate_message(payload: dict[str, Any]) -> dict[str, Any]:
    safe = {
        "ok": bool(payload.get("ok")),
        "gate_id": str(payload.get("gate_id", "") or ""),
        "identity_scope": str(payload.get("identity_scope", "") or ""),
        "ciphertext": str(payload.get("ciphertext", "") or ""),
        "nonce": str(payload.get("nonce", "") or ""),
        "sender_ref": str(payload.get("sender_ref", "") or ""),
        "format": str(payload.get("format", "mls1") or "mls1"),
        "transport_lock": str(payload.get("transport_lock", "") or ""),
        "timestamp": float(payload.get("timestamp", 0) or 0),
    }
    epoch = payload.get("epoch", 0)
    if epoch:
        safe["epoch"] = int(epoch or 0)
    if payload.get("reply_to"):
        safe["reply_to"] = str(payload.get("reply_to", "") or "")
    if payload.get("detail"):
        safe["detail"] = str(payload.get("detail", "") or "")
    if payload.get("key_commitment"):
        safe["key_commitment"] = str(payload.get("key_commitment", "") or "")
    if payload.get("gate_envelope"):
        safe["gate_envelope"] = str(payload.get("gate_envelope", "") or "")
    if payload.get("envelope_hash"):
        safe["envelope_hash"] = str(payload.get("envelope_hash", "") or "")
    return safe


def _redact_signed_gate_message(payload: dict[str, Any]) -> dict[str, Any]:
    safe = {
        "ok": bool(payload.get("ok")),
        "gate_id": str(payload.get("gate_id", "") or ""),
        "identity_scope": str(payload.get("identity_scope", "") or ""),
        "sender_id": str(payload.get("sender_id", "") or ""),
        "public_key": str(payload.get("public_key", "") or ""),
        "public_key_algo": str(payload.get("public_key_algo", "") or ""),
        "protocol_version": str(payload.get("protocol_version", "") or ""),
        "sequence": int(payload.get("sequence", 0) or 0),
        "ciphertext": str(payload.get("ciphertext", "") or ""),
        "nonce": str(payload.get("nonce", "") or ""),
        "sender_ref": str(payload.get("sender_ref", "") or ""),
        "format": str(payload.get("format", "mls1") or "mls1"),
        "timestamp": float(payload.get("timestamp", 0) or 0),
        "signature": str(payload.get("signature", "") or ""),
    }
    epoch = payload.get("epoch", 0)
    if epoch:
        safe["epoch"] = int(epoch or 0)
    if payload.get("reply_to"):
        safe["reply_to"] = str(payload.get("reply_to", "") or "")
    if payload.get("detail"):
        safe["detail"] = str(payload.get("detail", "") or "")
    if payload.get("gate_envelope"):
        safe["gate_envelope"] = str(payload.get("gate_envelope", "") or "")
    if payload.get("envelope_hash"):
        safe["envelope_hash"] = str(payload.get("envelope_hash", "") or "")
    return safe


def _build_cors_origins():
    """Build a CORS origins whitelist: localhost + LAN IPs + env overrides.
    Falls back to wildcard only if auto-detection fails entirely."""
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    # Add this machine's LAN IPs (covers common home/office setups)
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ("127.0.0.1", "0.0.0.0"):
                origins.append(f"http://{ip}:3000")
                origins.append(f"http://{ip}:8000")
    except Exception:
        pass
    # Allow user override via CORS_ORIGINS env var (comma-separated)
    extra = os.environ.get("CORS_ORIGINS", "")
    if extra:
        origins.extend([o.strip() for o in extra.split(",") if o.strip()])
    return list(set(origins))  # deduplicate


def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_float(val, default=0.0):
    try:
        parsed = float(val)
        if not math.isfinite(parsed):
            return default
        return parsed
    except (TypeError, ValueError):
        return default


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_insecure_admin_startup()
    _validate_admin_startup()
    _validate_peer_push_secret()
    _validate_privacy_core_startup()

    # Validate environment variables before starting anything
    from services.env_check import validate_env

    validate_env(strict=not _MESH_ONLY)

    if _MESH_ONLY:
        logger.info("MESH_ONLY enabled â€” skipping global data fetchers/schedulers.")
    else:
        # Start AIS stream first â€” it loads the disk cache (instant ships) then
        # begins accumulating live vessel data via WebSocket in the background.
        start_ais_stream()

        # Carrier tracker runs its own initial update_carrier_positions() internally
        # in _scheduler_loop, so we do NOT call it again in the preload thread.
        start_carrier_tracker()

        # Start SIGINT grid eagerly â€” APRS-IS TCP + Meshtastic MQTT connections
        # take a few seconds to handshake and start receiving packets. By starting
        # now, the bridges are already accumulating signals by the time the first
        # fetch_sigint() reads them during the preload cycle.
        from services.sigint_bridge import sigint_grid

        sigint_grid.start()

    # Start Reticulum bridge (optional)
    try:
        from services.mesh.mesh_rns import rns_bridge

        rns_bridge.start()
    except Exception as e:
        logger.warning(f"RNS bridge failed to start: {e}")

    # Start periodic Infonet verifier
    def _verify_loop():
        from services.mesh.mesh_hashchain import infonet

        while True:
            try:
                interval = int(get_settings().MESH_VERIFY_INTERVAL_S or 0)
                if interval <= 0:
                    time.sleep(30)
                    continue
                valid, reason = infonet.validate_chain_incremental(verify_signatures=True)
                if not valid:
                    logger.error(f"Infonet validation failed: {reason}")
                    try:
                        from services.mesh.mesh_metrics import increment as metrics_inc

                        metrics_inc("infonet_validate_failed")
                    except Exception:
                        pass
                time.sleep(max(5, interval))
            except Exception:
                time.sleep(30)

    threading.Thread(target=_verify_loop, daemon=True).start()

    # Only the primary backend supervises Wormhole. The Wormhole process itself
    # runs this same app in MESH_ONLY mode and must not recurse into spawning.
    if not _MESH_ONLY:
        try:
            from services.wormhole_supervisor import get_wormhole_state, sync_wormhole_with_settings

            sync_wormhole_with_settings()
            _resume_private_delivery_background_work(
                current_tier=_current_private_lane_tier(get_wormhole_state()),
                reason="startup_resume",
            )
            _refresh_lookup_handle_rotation_background(reason="startup_resume")
            privacy_prewarm_service.ensure_started()
            privacy_prewarm_service.run_scheduled_once(reason="startup_resume")
        except Exception as e:
            logger.warning(f"Wormhole supervisor failed to sync: {e}")
        try:
            from services.mesh.mesh_hashchain import register_public_event_append_hook

            _materialize_local_infonet_state()
            _refresh_node_peer_store()
            if _node_runtime_supported():
                if not _participant_node_enabled():
                    set_sync_state(_set_node_sync_disabled_state())
                _NODE_SYNC_STOP.clear()
                threading.Thread(target=_public_infonet_sync_loop, daemon=True).start()
                threading.Thread(target=_http_peer_push_loop, daemon=True).start()
                threading.Thread(target=_http_gate_push_loop, daemon=True).start()
                threading.Thread(target=_http_gate_pull_loop, daemon=True).start()
            global _NODE_PUBLIC_EVENT_HOOK_REGISTERED
            if not _NODE_PUBLIC_EVENT_HOOK_REGISTERED:
                register_public_event_append_hook(_schedule_public_event_propagation)
                _NODE_PUBLIC_EVENT_HOOK_REGISTERED = True
        except Exception as e:
            logger.warning(f"Node bootstrap runtime failed to initialize: {e}")

    if not _MESH_ONLY:
        # Prime the static route/airport database from vrs-standing-data.adsb.lol
        # before the first flight fetch so callsigns resolve to origin/destination
        # immediately. Daily refresh is owned by the scheduler.
        def _prime_route_database():
            try:
                from services.fetchers.route_database import refresh_route_database
                refresh_route_database(force=True)
            except Exception as e:
                logger.warning(f"Route database prime failed (non-fatal): {e}")

        threading.Thread(target=_prime_route_database, daemon=True).start()

        # Prime the OpenSky aircraft metadata DB so hex24 -> aircraft type
        # lookups work on the first flight cycle (and emissions get populated
        # for OpenSky-sourced flights that arrive with no t field).
        def _prime_aircraft_database():
            try:
                from services.fetchers.aircraft_database import refresh_aircraft_database
                refresh_aircraft_database(force=True)
            except Exception as e:
                logger.warning(f"Aircraft database prime failed (non-fatal): {e}")

        threading.Thread(target=_prime_aircraft_database, daemon=True).start()

        # Start the recurring scheduler (fast=60s, slow=30min).
        start_scheduler()

        # Kick off the full data preload in a background thread so the server
        # is listening on port 8000 instantly.  The frontend's adaptive polling
        # (retries every 3s) will pick up data piecemeal as each fetcher finishes.
        def _background_preload():
            logger.info("=== PRELOADING DATA (background â€” server already accepting requests) ===")
            try:
                update_all_data(startup_mode=True)
                logger.info("=== PRELOAD COMPLETE ===")
            except Exception as e:
                logger.error(f"Data preload failed (non-fatal): {e}")

        threading.Thread(target=_background_preload, daemon=True).start()

    # Auto-restart Tor hidden service if it was previously running
    # (i.e., the hostname file exists from a previous session)
    try:
        from services.tor_hidden_service import tor_service, HOSTNAME_PATH
        if HOSTNAME_PATH.exists():
            logger.info("Previous Tor hidden service detected â€” auto-restarting...")
            threading.Thread(
                target=tor_service.start, daemon=True
            ).start()
    except Exception as e:
        logger.warning(f"Tor auto-restart failed (non-fatal): {e}")

    yield
    if not _MESH_ONLY:
        # Shutdown: Stop all background services
        _NODE_SYNC_STOP.set()
        stop_ais_stream()
        stop_scheduler()
        stop_carrier_tracker()
        try:
            sigint_grid.stop()
        except Exception:
            pass
    if not _MESH_ONLY:
        try:
            from services.wormhole_supervisor import shutdown_wormhole_supervisor

            shutdown_wormhole_supervisor()
        except Exception:
            pass
    try:
        privacy_prewarm_service.stop()
    except Exception:
        pass
    # Stop Tor hidden service subprocess
    try:
        from services.tor_hidden_service import tor_service
        tor_service.stop()
    except Exception:
        pass


app = FastAPI(title="Live Risk Dashboard API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(JSONDecodeError)
async def json_decode_error_handler(_request: Request, _exc: JSONDecodeError):
    return JSONResponse(status_code=422, content={"ok": False, "detail": "invalid JSON body"})


@app.exception_handler(StarletteHTTPException)
async def private_plane_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 403 and _is_private_plane_access_path(request.url.path, request.method):
        return await _private_plane_refusal_response(
            request,
            status_code=403,
            payload=_private_plane_access_denied_payload(),
        )
    return await fastapi_http_exception_handler(request, exc)

from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
}
@app.middleware("http")
async def mesh_security_headers(request: Request, call_next):
    response = await call_next(request)
    for header, value in _security_headers().items():
        response.headers.setdefault(header, value)
    return response


@app.middleware("http")
async def mesh_no_store_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/mesh/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


def _validate_gate_vote_context(voter_id: str, gate_id: str) -> tuple[bool, str]:
    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return True, ""
    try:
        from services.mesh.mesh_reputation import gate_manager
    except Exception as exc:
        return False, f"Gate validation unavailable: {exc}"

    gate = gate_manager.get_gate(gate_key)
    if not gate:
        return False, f"Gate '{gate_key}' does not exist"

    can_enter, reason = gate_manager.can_enter(voter_id, gate_key)
    if not can_enter:
        return False, f"Gate vote denied: {reason}"

    try:
        from services.mesh.mesh_hashchain import gate_store

        if not gate_store.get_messages(gate_key, limit=1):
            return False, f"Gate '{gate_key}' has no activity"
    except Exception:
        pass

    return True, gate_key


_GATE_REDACT_FIELDS = ("sender_ref", "epoch", "nonce")
_KEY_ROTATE_REDACT_FIELDS = {
    "old_node_id",
    "old_public_key",
    "old_public_key_algo",
    "old_signature",
}


def _redact_gate_metadata(event: dict) -> dict:
    """Strip MLS-internal fields from gate_message events in public sync responses."""
    if not isinstance(event, dict):
        return event
    event_type = str(event.get("event_type", "") or "")
    if event_type != "gate_message":
        return event
    redacted = dict(event)
    for field in ("node_id", "sequence"):
        redacted.pop(field, None)
    if isinstance(redacted.get("payload"), dict):
        payload = dict(redacted.get("payload") or {})
        for field in _GATE_REDACT_FIELDS:
            payload.pop(field, None)
        redacted["payload"] = payload
        return redacted
    for field in _GATE_REDACT_FIELDS:
        redacted.pop(field, None)
    return redacted


def _redact_key_rotate_payload(event: dict) -> dict:
    """Strip identity-linking fields from key_rotate events in public responses."""
    if not isinstance(event, dict):
        return event
    if str(event.get("event_type", "") or "") != "key_rotate":
        return event
    redacted = dict(event)
    payload = redacted.get("payload")
    if isinstance(payload, dict):
        payload = dict(payload)
        for field in _KEY_ROTATE_REDACT_FIELDS:
            payload.pop(field, None)
        redacted["payload"] = payload
    return redacted


def _redact_vote_gate(event: dict) -> dict:
    """Strip gate label from vote events in public responses."""
    if not isinstance(event, dict):
        return event
    if str(event.get("event_type", "") or "") != "vote":
        return event
    redacted = dict(event)
    payload = redacted.get("payload")
    if isinstance(payload, dict):
        payload = dict(payload)
        payload.pop("gate", None)
        redacted["payload"] = payload
    return redacted


def _redact_public_event(event: dict) -> dict:
    """Apply all public-response redactions for public chain endpoints."""
    return _redact_vote_gate(_redact_key_rotate_payload(_redact_gate_metadata(event)))


def _trusted_gate_reply_to(event: dict) -> str:
    if not isinstance(event, dict):
        return ""
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return ""
    reply_to = str(payload.get("reply_to", "") or "").strip()
    if not reply_to:
        return ""
    gate_id = str(payload.get("gate", "") or "").strip()
    node_id = str(event.get("node_id", "") or "").strip()
    public_key = str(event.get("public_key", "") or "").strip()
    public_key_algo = str(event.get("public_key_algo", "") or "").strip()
    if node_id and not public_key and gate_id:
        try:
            binding = _lookup_gate_member_binding(gate_id, node_id)
            if binding:
                public_key, public_key_algo = binding
        except Exception:
            return ""
    signature = str(event.get("signature", "") or "").strip()
    protocol_version = str(event.get("protocol_version", "") or "").strip()
    sequence = int(event.get("sequence", 0) or 0)
    if not (gate_id and node_id and public_key and public_key_algo and signature and protocol_version and sequence > 0):
        return ""
    verify_payload = {
        "gate": gate_id,
        "ciphertext": str(payload.get("ciphertext", "") or ""),
        "nonce": str(payload.get("nonce", "") or ""),
        "sender_ref": str(payload.get("sender_ref", "") or ""),
        "format": str(payload.get("format", "mls1") or "mls1"),
    }
    epoch = _safe_int(payload.get("epoch", 0) or 0)
    if epoch > 0:
        verify_payload["epoch"] = epoch
    envelope_hash = str(payload.get("envelope_hash", "") or "").strip()
    if envelope_hash:
        verify_payload["envelope_hash"] = envelope_hash
    return _recover_verified_gate_reply_to(
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        payload=verify_payload,
        reply_to=reply_to,
        protocol_version=protocol_version,
    )


def _derive_anon_handle(node_id: str, gate_id: str) -> str:
    """Derive a stable per-session, per-gate anonymous display handle.

    Same node_id + same gate → same handle for every message that session
    posts (lets other members follow a conversation thread). Different
    session (anon re-enters → new node_id) → new handle. Different gate →
    different handle for the same session (prevents cross-gate linking).
    Not reversible: the handle is HMAC-SHA256(node_id, gate_id) truncated
    to 4 hex chars (~16 bits), which is enough to tell sessions apart in
    a room without identifying them.
    """
    node_key = str(node_id or "").strip()
    gate_key = str(gate_id or "").strip().lower()
    if not node_key:
        return "anon_????"
    tag = hmac.new(
        node_key.encode("utf-8"),
        f"{gate_key}|sender-handle-v1".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:4]
    return f"anon_{tag}"


def _strip_gate_identity_member(event: dict, *, envelope_policy: str = "envelope_disabled") -> dict:
    """Narrowed member view: strips signer identity fields.

    Gate envelope ciphertext is intentionally retained for members. It is
    encrypted under gate_secret and is required for durable room history.
    """
    if not isinstance(event, dict):
        event = {}
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    gate_id = str(payload.get("gate", "") or "")
    sender_handle = _derive_anon_handle(str(event.get("node_id", "") or ""), gate_id)
    result_payload: dict = {
        "gate": gate_id,
        "ciphertext": str(payload.get("ciphertext", "") or ""),
        "format": str(payload.get("format", "") or ""),
        "nonce": str(payload.get("nonce", "") or ""),
        "sender_ref": str(payload.get("sender_ref", "") or ""),
        "sender_handle": sender_handle,
        "transport_lock": str(payload.get("transport_lock", "") or ""),
        # gate_envelope is AES-256-GCM ciphertext encrypted under the gate's
        # domain key (gate_secret). Only members who hold the gate_secret
        # can decrypt it — so exposing the ciphertext itself to members is
        # safe, and it's REQUIRED for the envelope_always decrypt path that
        # gives members durable re-readable history. envelope_hash is the
        # cryptographic binding (SHA-256 of gate_envelope) the decrypt path
        # verifies before trusting the envelope.
        "gate_envelope": str(payload.get("gate_envelope", "") or ""),
        "envelope_hash": str(payload.get("envelope_hash", "") or ""),
        "reply_to": _trusted_gate_reply_to(event),
    }
    return {
        "event_id": str(event.get("event_id", "") or ""),
        "event_type": "gate_message",
        "timestamp": _redacted_gate_timestamp(event),
        "protocol_version": str(event.get("protocol_version", "") or ""),
        "sender_handle": sender_handle,
        "payload": result_payload,
    }


def _strip_gate_identity_privileged(event: dict) -> dict:
    """Privileged/audit view: preserves full signer identity surface."""
    if not isinstance(event, dict):
        event = {}
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    node_id = str(event.get("node_id", "") or "")
    public_key = str(event.get("public_key", "") or "")
    public_key_algo = str(event.get("public_key_algo", "") or "")
    if node_id and not public_key:
        gate_id = str(payload.get("gate", "") or "")
        if gate_id:
            try:
                binding = _lookup_gate_member_binding(gate_id, node_id)
                if binding:
                    public_key, public_key_algo = binding
            except Exception:
                pass
    return {
        "event_id": str(event.get("event_id", "") or ""),
        "event_type": "gate_message",
        "timestamp": _redacted_gate_timestamp(event),
        "node_id": node_id,
        "sequence": int(event.get("sequence", 0) or 0),
        "signature": str(event.get("signature", "") or ""),
        "public_key": public_key,
        "public_key_algo": public_key_algo,
        "protocol_version": str(event.get("protocol_version", "") or ""),
        "payload": {
            "gate": str(payload.get("gate", "") or ""),
            "ciphertext": str(payload.get("ciphertext", "") or ""),
            "format": str(payload.get("format", "") or ""),
            "nonce": str(payload.get("nonce", "") or ""),
            "sender_ref": str(payload.get("sender_ref", "") or ""),
            "transport_lock": str(payload.get("transport_lock", "") or ""),
            "gate_envelope": str(payload.get("gate_envelope", "") or ""),
            "envelope_hash": str(payload.get("envelope_hash", "") or ""),
            "reply_to": _trusted_gate_reply_to(event),
        },
    }


def _strip_gate_identity(event: dict) -> dict:
    """Legacy alias â€” defaults to member (narrowed) view."""
    return _strip_gate_identity_member(event)


def _resolve_envelope_policy(gate_id: str) -> str:
    """Look up envelope_policy for a gate.

    Per-gate policy is the source of truth. The global recovery-envelope
    runtime switches are retained for legacy config/reporting, but consulting
    them here silently downgrades envelope_always rooms into unreadable
    member views.
    """
    try:
        from services.mesh.mesh_reputation import gate_manager

        return str(gate_manager.get_envelope_policy(gate_id) or "envelope_disabled")
    except Exception:
        return "envelope_disabled"


def _strip_gate_for_access(event: dict, access: str) -> dict:
    """Select member or privileged strip based on access level."""
    if access == "privileged":
        return _strip_gate_identity_privileged(event)
    payload = event.get("payload") if isinstance(event, dict) else None
    gate_id = str((payload or {}).get("gate", "") or "")
    envelope_policy = _resolve_envelope_policy(gate_id) if gate_id else "envelope_disabled"
    return _strip_gate_identity_member(event, envelope_policy=envelope_policy)


def _lookup_gate_member_binding(gate_id: str, node_id: str) -> tuple[str, str] | None:
    gate_key = str(gate_id or "").strip().lower()
    candidate = str(node_id or "").strip()
    if not gate_key or not candidate:
        return None
    try:
        from services.mesh.mesh_wormhole_persona import (
            bootstrap_wormhole_persona_state,
            read_wormhole_persona_state,
        )

        bootstrap_wormhole_persona_state()
        state = read_wormhole_persona_state()
    except Exception:
        return None
    for persona in list(state.get("gate_personas", {}).get(gate_key) or []):
        if str(persona.get("node_id", "") or "").strip() != candidate:
            continue
        public_key = str(persona.get("public_key", "") or "").strip()
        public_key_algo = str(persona.get("public_key_algo", "Ed25519") or "Ed25519").strip()
        if public_key and public_key_algo:
            return public_key, public_key_algo
    session = dict(state.get("gate_sessions", {}).get(gate_key) or {})
    if str(session.get("node_id", "") or "").strip() == candidate:
        public_key = str(session.get("public_key", "") or "").strip()
        public_key_algo = str(session.get("public_key_algo", "Ed25519") or "Ed25519").strip()
        if public_key and public_key_algo:
            return public_key, public_key_algo
    return None


def _resolve_gate_proof_identity(gate_id: str) -> dict[str, Any] | None:
    from services.mesh.mesh_wormhole_persona import (
        bootstrap_wormhole_persona_state,
        enter_gate_anonymously,
        read_wormhole_persona_state,
    )

    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return None
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    session_identity = dict(state.get("gate_sessions", {}).get(gate_key) or {})
    if session_identity.get("private_key"):
        return session_identity
    active_persona_id = str(state.get("active_gate_personas", {}).get(gate_key, "") or "")
    for persona in list(state.get("gate_personas", {}).get(gate_key) or []):
        if str(persona.get("persona_id", "") or "") == active_persona_id:
            return dict(persona or {})
    for persona in list(state.get("gate_personas", {}).get(gate_key) or []):
        if persona.get("private_key"):
            return dict(persona or {})
    entered = enter_gate_anonymously(gate_key, rotate=False)
    if not entered.get("ok"):
        return None
    state = read_wormhole_persona_state()
    session_identity = dict(state.get("gate_sessions", {}).get(gate_key) or {})
    if session_identity.get("private_key"):
        return session_identity
    return None


def _sign_gate_access_proof(gate_id: str) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    identity = _resolve_gate_proof_identity(gate_key)
    if not identity:
        return {"ok": False, "detail": "gate_access_proof_unavailable"}
    private_key_b64 = str(identity.get("private_key", "") or "").strip()
    node_id = str(identity.get("node_id", "") or "").strip()
    public_key = str(identity.get("public_key", "") or "").strip()
    public_key_algo = str(identity.get("public_key_algo", "Ed25519") or "Ed25519").strip()
    if not (private_key_b64 and node_id and public_key and public_key_algo):
        return {"ok": False, "detail": "gate_access_proof_unavailable"}
    try:
        from cryptography.hazmat.primitives.asymmetric import ec, ed25519

        ts = int(time.time())
        challenge = f"{gate_key}:{ts}"
        key_bytes = base64.b64decode(private_key_b64)
        algo = parse_public_key_algo(public_key_algo)
        if algo == "Ed25519":
            signing_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)
            signature = signing_key.sign(challenge.encode("utf-8"))
        elif algo == "ECDSA_P256":
            from cryptography.hazmat.primitives import hashes

            signing_key = ec.derive_private_key(int.from_bytes(key_bytes, "big"), ec.SECP256R1())
            signature = signing_key.sign(challenge.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
        else:
            return {"ok": False, "detail": "gate_access_proof_unsupported_algo"}
    except Exception as exc:
        logger.warning("Gate access proof signing failed: %s", type(exc).__name__)
        return {"ok": False, "detail": "gate_access_proof_failed"}
    return {
        "ok": True,
        "gate_id": gate_key,
        "node_id": node_id,
        "ts": ts,
        "proof": base64.b64encode(signature).decode("ascii"),
    }


def _verify_gate_access(request: Request, gate_id: str) -> str:
    """Verify gate access. Returns 'privileged', 'member', or '' (denied)."""
    ok, _detail, _scope_class = _check_explicit_scoped_auth_local(
        request,
        {"gate.audit", "mesh.audit"},
    )
    if ok:
        return "privileged"
    ok, _detail = _check_scoped_auth(request, "gate")
    if ok:
        return "member"

    gate_key = str(gate_id or "").strip().lower()
    node_id = str(request.headers.get("x-wormhole-node-id", "") or "").strip()
    proof_b64 = str(request.headers.get("x-wormhole-gate-proof", "") or "").strip()
    ts_str = str(request.headers.get("x-wormhole-gate-ts", "") or "").strip()
    if not gate_key or not node_id or not proof_b64 or not ts_str:
        return ""
    try:
        ts = int(ts_str)
    except (TypeError, ValueError):
        return ""
    if abs(int(time.time()) - ts) > 60:
        return ""
    binding = _lookup_gate_member_binding(gate_key, node_id)
    if not binding:
        return ""
    public_key, public_key_algo = binding
    if not verify_node_binding(node_id, public_key):
        return ""
    try:
        signature_hex = base64.b64decode(proof_b64, validate=True).hex()
    except Exception:
        return ""
    challenge = f"{gate_key}:{ts_str}"
    challenge_ok, _challenge_reason = verify_node_bound_signature(
        node_id=node_id,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature_hex=signature_hex,
        payload=challenge,
    )
    if challenge_ok:
        return "member"
    return ""


# â”€â”€ Non-hostile transport auto-upgrade â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#
# The mesh/wormhole middleware can try to bring the wormhole supervisor
# up in the background when a user hits a tier-gated route on a weak
# transport. This is a best-effort, short-deadline attempt so we never
# add significant latency to ordinary requests, and it is rate-limited
# by a cooldown so back-to-back failures do not thrash the supervisor.
_TRANSPORT_UPGRADE_COOLDOWN_S = 30.0
_TRANSPORT_UPGRADE_DEADLINE_S = 2.5
_last_middleware_upgrade_attempt: float = 0.0
_middleware_upgrade_lock = asyncio.Lock()


async def _try_transparent_transport_upgrade() -> str | None:
    """Fire-and-wait-briefly attempt to upgrade the wormhole transport.

    Returns the current transport tier after the attempt (or after a
    cooldown skip), or None if the supervisor could not be probed.
    """
    global _last_middleware_upgrade_attempt

    async with _middleware_upgrade_lock:
        now = time.time()
        if (now - _last_middleware_upgrade_attempt) < _TRANSPORT_UPGRADE_COOLDOWN_S:
            try:
                from services.wormhole_supervisor import get_wormhole_state

                return _current_private_lane_tier(get_wormhole_state())
            except Exception:
                return None
        _last_middleware_upgrade_attempt = now

    def _blocking_upgrade() -> str | None:
        try:
            from services.wormhole_supervisor import (
                connect_wormhole,
                get_wormhole_state,
            )

            connect_wormhole(reason="middleware_auto_upgrade")
            return _current_private_lane_tier(get_wormhole_state())
        except Exception:
            return None

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_blocking_upgrade),
            timeout=_TRANSPORT_UPGRADE_DEADLINE_S,
        )
    except asyncio.TimeoutError:
        try:
            from services.wormhole_supervisor import get_wormhole_state

            return _current_private_lane_tier(get_wormhole_state())
        except Exception:
            return None


def _kickoff_dm_send_transport_upgrade() -> None:
    private_transport_manager.request_warmup(reason="queued_dm_delivery")


def _kickoff_private_control_transport_upgrade() -> None:
    private_transport_manager.request_warmup(reason="dm_surface_open")


def _private_surface_warmup_request(path: str, method: str) -> tuple[str, str] | None:
    normalized_path = str(path or "").strip()
    if normalized_path.startswith("/api/wormhole/dm/invite"):
        return ("invite_bootstrap", "private_control_only")
    if normalized_path.startswith("/api/wormhole/dm/contact"):
        return ("invite_bootstrap", "private_control_only")
    if normalized_path in {"/api/mesh/dm/prekey-bundle", "/api/mesh/dm/register"}:
        return ("invite_bootstrap", "private_control_only")
    if (
        normalized_path.startswith("/api/wormhole/dm/")
        or normalized_path.startswith("/api/mesh/dm/")
    ):
        return ("dm_surface_open", "private_control_only")
    if (
        normalized_path.startswith("/api/wormhole/gate/")
        or normalized_path.startswith("/api/mesh/gate/")
    ):
        return ("gate_surface_open", "private_control_only")
    return None


def _request_private_surface_warmup(*, path: str, method: str, current_tier: str) -> None:
    request = _private_surface_warmup_request(path, method)
    if request is None:
        return
    reason, required_tier = request
    private_transport_manager.request_warmup(
        reason=reason,
        current_tier=current_tier,
        required_tier=required_tier,
    )


def _resume_private_delivery_background_work(*, current_tier: str, reason: str) -> None:
    pending_items = private_delivery_outbox.pending_items()
    if not pending_items:
        return
    private_release_worker.ensure_started()
    private_release_worker.wake()
    required_tier = "public_degraded"
    for item in pending_items:
        required_tier = release_lane_required_tier(str(item.get("lane", "") or ""))
        if required_tier == "private_strong":
            break
    private_transport_manager.request_warmup(
        reason=reason,
        current_tier=current_tier,
        required_tier=required_tier,
    )


def _upgrade_invite_scoped_contact_preferences_background() -> dict[str, Any]:
    try:
        from services.mesh.mesh_wormhole_contacts import upgrade_invite_scoped_contact_preferences

        upgraded = int(upgrade_invite_scoped_contact_preferences() or 0)
        return {"ok": True, "upgraded_contacts": upgraded}
    except Exception as exc:
        return {
            "ok": False,
            "upgraded_contacts": 0,
            "detail": str(exc) or type(exc).__name__,
        }


def _refresh_lookup_handle_rotation_background(*, reason: str) -> dict[str, Any]:
    try:
        result = maybe_rotate_prekey_lookup_handles()
    except Exception as exc:
        logger.warning("lookup handle rotation check failed during %s: %s", str(reason or "").strip(), exc)
        return {
            "ok": False,
            "rotated": False,
            "state": "lookup_handle_rotation_failed",
            "detail": str(exc) or "lookup handle rotation failed",
        }
    return dict(result or {})


@app.middleware("http")
async def enforce_high_privacy_mesh(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/mesh") or path.startswith("/api/wormhole/gate/") or path.startswith("/api/wormhole/dm/"):
        request.state._private_lane_started_at = time.perf_counter()
        current_tier = "public_degraded"
        try:
            from services.wormhole_supervisor import get_wormhole_state

            wormhole = get_wormhole_state()
        except Exception:
            wormhole = {"configured": False, "ready": False, "rns_ready": False}
        current_tier = _current_private_lane_tier(wormhole)
        request.state._private_lane_current_tier = current_tier
        try:
            _request_private_surface_warmup(
                path=path,
                method=request.method,
                current_tier=current_tier,
            )
        except Exception:
            logger.debug("Private surface warm-up request failed", exc_info=True)
        required_tier = _minimum_transport_tier(path, request.method)
        if required_tier:
            if not _transport_tier_is_sufficient(current_tier, required_tier):
                if request.method.upper() == "POST" and path == "/api/mesh/dm/send":
                    # Non-hostile DM send path: accept user intent even when
                    # the strongest private transport is still converging.
                    # If Wormhole is already up at a weaker private tier,
                    # let the route continue silently. If we're still fully
                    # public_degraded, kick off background bring-up and let
                    # the route deliver with an honest relay-state detail.
                    request.state._dm_send_transport_pending = current_tier == "public_degraded"
                    if current_tier == "public_degraded":
                        try:
                            _kickoff_dm_send_transport_upgrade()
                        except Exception:
                            logger.debug("DM send background transport kickoff failed", exc_info=True)
                    request.state._private_lane_current_tier = current_tier
                elif (
                    request.method.upper() == "POST"
                    and path.startswith("/api/mesh/gate/")
                    and path.endswith("/message")
                ):
                    # Gate messages are sealed local writes first. Let the
                    # handler append ciphertext to the local gate store and
                    # queue fan-out; the release worker enforces the
                    # PRIVATE / STRONG network floor before peer propagation.
                    request.state._gate_message_transport_pending = True
                    if current_tier == "public_degraded":
                        try:
                            _kickoff_dm_send_transport_upgrade()
                        except Exception:
                            logger.debug("gate message background transport kickoff failed", exc_info=True)
                    request.state._private_lane_current_tier = current_tier
                elif required_tier == "private_control_only" and path.startswith("/api/wormhole/"):
                    # Local wormhole control routes prepare state, compose
                    # encrypted payloads, or manage keys locally. They
                    # should not hard-fail just because the hidden
                    # transport has not finished coming up yet.
                    request.state._private_control_transport_pending = current_tier == "public_degraded"
                    request.state._private_lane_current_tier = current_tier
                else:
                    # Tor-style: instead of failing, keep trying in the
                    # background and return an ok:True "preparing" response
                    # (202 Accepted) so the client shows a spinner rather
                    # than an approval dialog. The request itself is NOT
                    # forwarded to the handler — the tier is too low for the
                    # route's required privacy — but the client can poll and
                    # retry transparently once the lane warms up.
                    try:
                        upgraded = await _try_transparent_transport_upgrade()
                    except Exception:
                        upgraded = current_tier
                        logger.debug("transparent transport upgrade failed", exc_info=True)
                    if upgraded is not None and _transport_tier_is_sufficient(
                        upgraded, required_tier
                    ):
                        current_tier = upgraded
                    else:
                        try:
                            _kickoff_dm_send_transport_upgrade()
                        except Exception:
                            logger.debug("background warmup kickoff failed", exc_info=True)
                        payload = _transport_tier_precondition_payload(
                            required_tier, upgraded or current_tier
                        )
                        payload["ok"] = True
                        payload["pending"] = True
                        payload["status"] = "preparing_private_lane"
                        return await _private_plane_refusal_response(
                            request,
                            status_code=202,
                            payload=payload,
                        )
        try:
            from services.wormhole_settings import read_wormhole_settings, write_wormhole_settings

            data = read_wormhole_settings()
            # Tor-style: if the user selected high privacy but Wormhole
            # isn't enabled yet, just turn it on and kick off warmup.
            # Don't block the request on the upgrade — the transport
            # manager will converge in the background.
            if (
                path.startswith("/api/mesh")
                and str(data.get("privacy_profile", "default")).lower() == "high"
                and not bool(data.get("enabled"))
            ):
                try:
                    write_wormhole_settings(enabled=True)
                except Exception:
                    logger.debug("auto-enable wormhole (high privacy) failed", exc_info=True)
                try:
                    _kickoff_dm_send_transport_upgrade()
                except Exception:
                    logger.debug("high-privacy warmup kickoff failed", exc_info=True)
        except Exception:
            pass
        state = _anonymous_mode_state()
        if state["enabled"] and (
            _is_anonymous_mesh_write_path(path, request.method)
            or _is_anonymous_dm_action_path(path, request.method)
            or _is_anonymous_wormhole_gate_admin_path(path, request.method)
        ):
            # Tor-style: anonymous mode is on → do whatever is required for
            # it to function. Auto-enable Wormhole if off, and schedule
            # hidden-transport warmup WITHOUT blocking this request. The
            # transport manager converges in the background; the user sees
            # a normal (non-428) response in the meantime.
            if not state["wormhole_enabled"]:
                try:
                    from services.wormhole_settings import write_wormhole_settings

                    write_wormhole_settings(enabled=True)
                except Exception:
                    logger.debug("auto-enable wormhole (anonymous mode) failed", exc_info=True)
            if not state["ready"]:
                try:
                    _kickoff_dm_send_transport_upgrade()
                except Exception:
                    logger.debug("anonymous-mode warmup kickoff failed", exc_info=True)
    return await call_next(request)


@app.middleware("http")
async def apply_no_store_to_sensitive_paths(request: Request, call_next):
    response = await call_next(request)
    if _is_sensitive_no_store_path(request.url.path):
        for key, value in _NO_STORE_HEADERS.items():
            response.headers[key] = value
    return response

# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------
app.include_router(health_router)
app.include_router(cctv_router)
app.include_router(radio_router)
app.include_router(sigint_router)
app.include_router(tools_router)
app.include_router(admin_router)
app.include_router(data_router)
app.include_router(mesh_peer_sync_router)
app.include_router(mesh_operator_router)
app.include_router(mesh_oracle_router)
app.include_router(mesh_dm_router)
app.include_router(mesh_public_router)
app.include_router(wormhole_router)
app.include_router(ai_intel_router)
app.include_router(sar_router)
app.include_router(infonet_router)

from services.data_fetcher import update_all_data

_refresh_lock = threading.Lock()


@app.get("/api/refresh", response_model=RefreshResponse, dependencies=[Depends(require_admin)])
@limiter.limit("2/minute")
async def force_refresh(request: Request):
    if not _refresh_lock.acquire(blocking=False):
        return {"status": "refresh already in progress"}

    def _do_refresh():
        try:
            update_all_data()
        finally:
            _refresh_lock.release()

    t = threading.Thread(target=_do_refresh)
    t.start()
    return {"status": "refreshing in background"}


@app.post("/api/ais/feed")
@limiter.limit("60/minute")
async def ais_feed(request: Request):
    """Accept AIS-catcher HTTP JSON feed (POST decoded AIS messages)."""
    from services.ais_stream import ingest_ais_catcher

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=422, content={"ok": False, "detail": "invalid JSON body"})

    msgs = body.get("msgs", [])
    if not msgs:
        return {"status": "ok", "ingested": 0}

    count = ingest_ais_catcher(msgs)
    return {"status": "ok", "ingested": count}


from pydantic import BaseModel


class ViewportUpdate(BaseModel):
    s: float
    w: float
    n: float
    e: float


_LAST_VIEWPORT_UPDATE: tuple[float, float, float, float] | None = None
_LAST_VIEWPORT_UPDATE_TS = 0.0
_VIEWPORT_UPDATE_LOCK = threading.Lock()
_VIEWPORT_DEDUPE_EPSILON = 1.0
_VIEWPORT_MIN_UPDATE_S = 10.0


def _normalize_longitude(value: float) -> float:
    normalized = ((value + 180.0) % 360.0 + 360.0) % 360.0 - 180.0
    if normalized == -180.0 and value > 0:
        return 180.0
    return normalized


def _normalize_viewport_bounds(s: float, w: float, n: float, e: float) -> tuple[float, float, float, float]:
    south = max(-90.0, min(90.0, s))
    north = max(-90.0, min(90.0, n))
    raw_width = abs(e - w)
    if not math.isfinite(raw_width) or raw_width >= 360.0:
        return south, -180.0, north, 180.0
    west = _normalize_longitude(w)
    east = _normalize_longitude(e)
    if east < west:
        return south, -180.0, north, 180.0
    return south, west, north, east


def _viewport_changed_enough(bounds: tuple[float, float, float, float]) -> bool:
    global _LAST_VIEWPORT_UPDATE, _LAST_VIEWPORT_UPDATE_TS
    now = time.monotonic()
    with _VIEWPORT_UPDATE_LOCK:
        if _LAST_VIEWPORT_UPDATE is None:
            _LAST_VIEWPORT_UPDATE = bounds
            _LAST_VIEWPORT_UPDATE_TS = now
            return True
        changed = any(
            abs(current - previous) > _VIEWPORT_DEDUPE_EPSILON
            for current, previous in zip(bounds, _LAST_VIEWPORT_UPDATE)
        )
        if not changed and (now - _LAST_VIEWPORT_UPDATE_TS) < _VIEWPORT_MIN_UPDATE_S:
            return False
        if (now - _LAST_VIEWPORT_UPDATE_TS) < _VIEWPORT_MIN_UPDATE_S:
            return False
        _LAST_VIEWPORT_UPDATE = bounds
        _LAST_VIEWPORT_UPDATE_TS = now
        return True


def _queue_viirs_change_refresh() -> None:
    from services.fetchers.earth_observation import fetch_viirs_change_nodes

    threading.Thread(target=fetch_viirs_change_nodes, daemon=True).start()


@app.post("/api/viewport")
@limiter.limit("60/minute")
async def update_viewport(vp: ViewportUpdate, request: Request):  # noqa: ARG001
    """Receive frontend map bounds. AIS stream stays global so open-ocean
    vessels are never dropped â€” the frontend worker handles viewport culling."""
    return {"status": "ok"}


class LayerUpdate(BaseModel):
    layers: dict[str, bool]


@app.post("/api/layers")
@limiter.limit("30/minute")
async def update_layers(update: LayerUpdate, request: Request):
    """Receive frontend layer toggle state. Starts/stops streams accordingly."""
    from services.fetchers._store import active_layers, bump_active_layers_version, is_any_active

    # Snapshot old stream states before applying changes
    old_ships = is_any_active(
        "ships_military", "ships_cargo", "ships_civilian", "ships_passenger", "ships_tracked_yachts"
    )
    old_mesh = is_any_active("sigint_meshtastic")
    old_aprs = is_any_active("sigint_aprs")
    old_viirs = is_any_active("viirs_nightlights")

    # Update only known keys
    changed = False
    for key, value in update.layers.items():
        if key in active_layers:
            if active_layers[key] != value:
                changed = True
            active_layers[key] = value

    if changed:
        bump_active_layers_version()

    new_ships = is_any_active(
        "ships_military", "ships_cargo", "ships_civilian", "ships_passenger", "ships_tracked_yachts"
    )
    new_mesh = is_any_active("sigint_meshtastic")
    new_aprs = is_any_active("sigint_aprs")
    new_viirs = is_any_active("viirs_nightlights")

    # Start/stop AIS stream on transition
    if old_ships and not new_ships:
        from services.ais_stream import stop_ais_stream

        stop_ais_stream()
        logger.info("AIS stream stopped (all ship layers disabled)")
    elif not old_ships and new_ships:
        from services.ais_stream import start_ais_stream

        start_ais_stream()
        logger.info("AIS stream started (ship layer enabled)")

    # Start/stop SIGINT bridges on transition
    from services.sigint_bridge import sigint_grid

    if old_mesh and not new_mesh:
        sigint_grid.mesh.stop()
        logger.info("Meshtastic MQTT bridge stopped (layer disabled)")
    elif not old_mesh and new_mesh:
        # Respect the global MESH_MQTT_ENABLED gate even when the UI layer is
        # toggled on. The layer toggle should not bypass the opt-in flag that
        # protects the public broker from passive connection load.
        try:
            mqtt_enabled = bool(getattr(get_settings(), "MESH_MQTT_ENABLED", False))
        except Exception:
            mqtt_enabled = False
        if mqtt_enabled:
            sigint_grid.mesh.start()
            logger.info("Meshtastic MQTT bridge started (layer enabled)")
        else:
            logger.info(
                "Meshtastic layer enabled; MQTT bridge remains disabled "
                "(set MESH_MQTT_ENABLED=true to participate in the public broker)"
            )

    if old_aprs and not new_aprs:
        sigint_grid.aprs.stop()
        logger.info("APRS bridge stopped (layer disabled)")
    elif not old_aprs and new_aprs:
        sigint_grid.aprs.start()
        logger.info("APRS bridge started (layer enabled)")

    if not old_viirs and new_viirs:
        _queue_viirs_change_refresh()
        logger.info("VIIRS change refresh queued (layer enabled)")

    return {"status": "ok"}


@app.get("/api/live-data")
@limiter.limit("120/minute")
async def live_data(request: Request):
    return get_latest_data()


def _etag_response(request: Request, payload: dict, prefix: str = "", default=None):
    """Serialize once, use data version for ETag, return 304 or full response.

    Uses a monotonic version counter instead of MD5-hashing the full payload.
    The 304 fast path avoids serialization entirely.
    """
    etag = _current_etag(prefix)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    content = json_mod.dumps(_json_safe(payload), default=default, allow_nan=False)
    return Response(
        content=content,
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


def _current_etag(prefix: str = "") -> str:
    from services.fetchers._store import get_active_layers_version, get_data_version

    return f"{prefix}v{get_data_version()}-l{get_active_layers_version()}"


def _json_safe(value):
    """Recursively replace non-finite floats with None so responses stay valid JSON."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        # Snapshot mutable mappings first so background fetcher updates do not
        # invalidate iteration while we serialize a response.
        return {k: _json_safe(v) for k, v in list(value.items())}
    if isinstance(value, list):
        return [_json_safe(v) for v in list(value)]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in list(value)]
    return value


def _sanitize_payload(value):
    """Thread-safe snapshot with NaNâ†’None. Cheaper than _json_safe: only deep-
    copies dicts (for thread safety) and replaces non-finite floats. Lists are
    shallow-copied â€” orjson handles the leaf serialisation natively."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _sanitize_payload(v) for k, v in list(value.items())}
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def _bbox_filter(
    items: list, s: float, w: float, n: float, e: float, lat_key: str = "lat", lng_key: str = "lng"
) -> list:
    """Filter a list of dicts to those within the bounding box (with 20% padding).
    Handles antimeridian crossing (e.g. w=170, e=-170)."""
    pad_lat = (n - s) * 0.2
    pad_lng = (e - w) * 0.2 if e > w else ((e + 360 - w) * 0.2)
    s2, n2 = s - pad_lat, n + pad_lat
    w2, e2 = w - pad_lng, e + pad_lng
    crosses_antimeridian = w2 > e2
    out = []
    for item in items:
        lat = item.get(lat_key)
        lng = item.get(lng_key)
        if lat is None or lng is None:
            out.append(item)  # Keep items without coords (don't filter them out)
            continue
        if not (s2 <= lat <= n2):
            continue
        if crosses_antimeridian:
            if lng >= w2 or lng <= e2:
                out.append(item)
        else:
            if w2 <= lng <= e2:
                out.append(item)
    return out


def _bbox_filter_geojson_points(items: list, s: float, w: float, n: float, e: float) -> list:
    """Filter GeoJSON Point features to a padded bounding box."""
    pad_lat = (n - s) * 0.2
    pad_lng = (e - w) * 0.2 if e > w else ((e + 360 - w) * 0.2)
    s2, n2 = s - pad_lat, n + pad_lat
    w2, e2 = w - pad_lng, e + pad_lng
    crosses_antimeridian = w2 > e2
    out = []
    for item in items:
        geometry = item.get("geometry") if isinstance(item, dict) else None
        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            out.append(item)
            continue
        lng, lat = coords[0], coords[1]
        if lat is None or lng is None:
            out.append(item)
            continue
        if not (s2 <= lat <= n2):
            continue
        if crosses_antimeridian:
            if lng >= w2 or lng <= e2:
                out.append(item)
        else:
            if w2 <= lng <= e2:
                out.append(item)
    return out


def _bbox_spans(s: float | None, w: float | None, n: float | None, e: float | None) -> tuple[float, float]:
    if None in (s, w, n, e):
        return 180.0, 360.0
    lat_span = max(0.0, float(n) - float(s))
    lng_span = float(e) - float(w)
    if lng_span < 0:
        lng_span += 360.0
    if lng_span == 0 and w == -180 and e == 180:
        lng_span = 360.0
    return lat_span, max(0.0, lng_span)


def _downsample_points(items: list, max_items: int) -> list:
    if max_items <= 0 or len(items) <= max_items:
        return items
    step = len(items) / float(max_items)
    return [items[min(len(items) - 1, int(i * step))] for i in range(max_items)]


def _world_and_continental_scale(
    has_bbox: bool, s: float | None, w: float | None, n: float | None, e: float | None
) -> tuple[bool, bool]:
    lat_span, lng_span = _bbox_spans(s, w, n, e)
    world_scale = (not has_bbox) or lng_span >= 300 or lat_span >= 120
    continental_scale = has_bbox and not world_scale and (lng_span >= 120 or lat_span >= 55)
    return world_scale, continental_scale


def _filter_sigint_by_layers(items: list, active_layers: dict[str, bool]) -> list:
    allow_aprs = bool(active_layers.get("sigint_aprs", True))
    allow_mesh = bool(active_layers.get("sigint_meshtastic", True))
    if allow_aprs and allow_mesh:
        return items

    allowed_sources: set[str] = {"js8call"}
    if allow_aprs:
        allowed_sources.add("aprs")
    if allow_mesh:
        allowed_sources.update({"meshtastic", "meshtastic-map"})
    return [item for item in items if str(item.get("source") or "").lower() in allowed_sources]


def _sigint_totals_for_items(items: list) -> dict[str, int]:
    totals = {
        "total": len(items),
        "meshtastic": 0,
        "meshtastic_live": 0,
        "meshtastic_map": 0,
        "aprs": 0,
        "js8call": 0,
    }
    for item in items:
        source = str(item.get("source") or "").lower()
        if source == "meshtastic":
            totals["meshtastic"] += 1
            if bool(item.get("from_api")):
                totals["meshtastic_map"] += 1
            else:
                totals["meshtastic_live"] += 1
        elif source == "aprs":
            totals["aprs"] += 1
        elif source == "js8call":
            totals["js8call"] += 1
    return totals


@app.get("/api/live-data/fast")
@limiter.limit("120/minute")
async def live_data_fast(
    request: Request,
    # bbox params accepted for backward compat but no longer used for filtering â€”
    # all cached data is returned and the frontend culls off-screen entities via MapLibre.
    s: float = Query(None, description="South bound (ignored)", ge=-90, le=90),
    w: float = Query(None, description="West bound (ignored)", ge=-180, le=180),
    n: float = Query(None, description="North bound (ignored)", ge=-90, le=90),
    e: float = Query(None, description="East bound (ignored)", ge=-180, le=180),
):
    etag = _current_etag(prefix="fast|full|")
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})

    from services.fetchers._store import (
        active_layers,
        get_latest_data_subset_refs,
        get_source_timestamps_snapshot,
    )

    d = get_latest_data_subset_refs(
        "last_updated",
        "commercial_flights",
        "military_flights",
        "private_flights",
        "private_jets",
        "tracked_flights",
        "ships",
        "cctv",
        "uavs",
        "liveuamap",
        "gps_jamming",
        "satellites",
        "satellite_source",
        "sigint",
        "sigint_totals",
        "trains",
    )
    freshness = get_source_timestamps_snapshot()

    ships_enabled = any(
        active_layers.get(key, True)
        for key in (
            "ships_military",
            "ships_cargo",
            "ships_civilian",
            "ships_passenger",
            "ships_tracked_yachts",
        )
    )
    cctv_total = len(d.get("cctv") or [])
    sigint_items = _filter_sigint_by_layers(d.get("sigint") or [], active_layers)
    sigint_totals = _sigint_totals_for_items(sigint_items)

    payload = {
        "commercial_flights": (d.get("commercial_flights") or []) if active_layers.get("flights", True) else [],
        "military_flights": (d.get("military_flights") or []) if active_layers.get("military", True) else [],
        "private_flights": (d.get("private_flights") or []) if active_layers.get("private", True) else [],
        "private_jets": (d.get("private_jets") or []) if active_layers.get("jets", True) else [],
        "tracked_flights": (d.get("tracked_flights") or []) if active_layers.get("tracked", True) else [],
        "ships": (d.get("ships") or []) if ships_enabled else [],
        "cctv": (d.get("cctv") or []) if active_layers.get("cctv", True) else [],
        "uavs": (d.get("uavs") or []) if active_layers.get("military", True) else [],
        "liveuamap": (d.get("liveuamap") or []) if active_layers.get("global_incidents", True) else [],
        "gps_jamming": (d.get("gps_jamming") or []) if active_layers.get("gps_jamming", True) else [],
        "satellites": (d.get("satellites") or []) if active_layers.get("satellites", True) else [],
        "satellite_source": d.get("satellite_source", "none"),
        "sigint": sigint_items
        if (active_layers.get("sigint_meshtastic", True) or active_layers.get("sigint_aprs", True))
        else [],
        "sigint_totals": sigint_totals,
        "cctv_total": cctv_total,
        "trains": (d.get("trains") or []) if active_layers.get("trains", True) else [],
        "freshness": freshness,
    }
    return Response(
        content=orjson.dumps(_sanitize_payload(payload)),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


@app.get("/api/live-data/slow")
@limiter.limit("60/minute")
async def live_data_slow(
    request: Request,
    # bbox params accepted for backward compat but no longer used for filtering.
    s: float = Query(None, description="South bound (ignored)", ge=-90, le=90),
    w: float = Query(None, description="West bound (ignored)", ge=-180, le=180),
    n: float = Query(None, description="North bound (ignored)", ge=-90, le=90),
    e: float = Query(None, description="East bound (ignored)", ge=-180, le=180),
):
    etag = _current_etag(prefix="slow|full|")
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})

    from services.fetchers._store import (
        active_layers,
        get_latest_data_subset_refs,
        get_source_timestamps_snapshot,
    )

    d = get_latest_data_subset_refs(
        "last_updated",
        "news",
        "stocks",
        "financial_source",
        "oil",
        "weather",
        "traffic",
        "earthquakes",
        "frontlines",
        "gdelt",
        "airports",
        "kiwisdr",
        "satnogs_stations",
        "satnogs_observations",
        "tinygs_satellites",
        "space_weather",
        "internet_outages",
        "firms_fires",
        "datacenters",
        "military_bases",
        "power_plants",
        "viirs_change_nodes",
        "scanners",
        "weather_alerts",
        "ukraine_alerts",
        "air_quality",
        "volcanoes",
        "fishing_activity",
        "psk_reporter",
        "crowdthreat",
        "correlations",
        "threat_level",
        "trending_markets",
        "uap_sightings",
        "wastewater",
        "sar_scenes",
        "sar_anomalies",
        "sar_aoi_coverage",
    )
    freshness = get_source_timestamps_snapshot()

    payload = {
        "last_updated": d.get("last_updated"),
        "threat_level": d.get("threat_level"),
        "trending_markets": d.get("trending_markets", []),
        "news": d.get("news", []),
        "stocks": d.get("stocks", {}),
        "financial_source": d.get("financial_source", ""),
        "oil": d.get("oil", {}),
        "weather": d.get("weather"),
        "traffic": d.get("traffic", []),
        "earthquakes": (d.get("earthquakes") or []) if active_layers.get("earthquakes", True) else [],
        "frontlines": d.get("frontlines") if active_layers.get("ukraine_frontline", True) else None,
        "gdelt": (d.get("gdelt") or []) if active_layers.get("global_incidents", True) else [],
        "airports": d.get("airports") or [],
        "kiwisdr": (d.get("kiwisdr") or []) if active_layers.get("kiwisdr", True) else [],
        "satnogs_stations": (d.get("satnogs_stations") or []) if active_layers.get("satnogs", True) else [],
        "satnogs_total": len(d.get("satnogs_stations") or []),
        "satnogs_observations": (d.get("satnogs_observations") or []) if active_layers.get("satnogs", True) else [],
        "tinygs_satellites": (d.get("tinygs_satellites") or []) if active_layers.get("tinygs", True) else [],
        "tinygs_total": len(d.get("tinygs_satellites") or []),
        "psk_reporter": (d.get("psk_reporter") or []) if active_layers.get("psk_reporter", True) else [],
        "space_weather": d.get("space_weather"),
        "internet_outages": (d.get("internet_outages") or []) if active_layers.get("internet_outages", True) else [],
        "firms_fires": (d.get("firms_fires") or []) if active_layers.get("firms", True) else [],
        "datacenters": (d.get("datacenters") or []) if active_layers.get("datacenters", True) else [],
        "military_bases": (d.get("military_bases") or []) if active_layers.get("military_bases", True) else [],
        "power_plants": (d.get("power_plants") or []) if active_layers.get("power_plants", True) else [],
        "viirs_change_nodes": (d.get("viirs_change_nodes") or []) if active_layers.get("viirs_nightlights", True) else [],
        "scanners": (d.get("scanners") or []) if active_layers.get("scanners", True) else [],
        "weather_alerts": d.get("weather_alerts", []) if active_layers.get("weather_alerts", True) else [],
        "ukraine_alerts": d.get("ukraine_alerts", []) if active_layers.get("ukraine_alerts", True) else [],
        "air_quality": (d.get("air_quality") or []) if active_layers.get("air_quality", True) else [],
        "volcanoes": (d.get("volcanoes") or []) if active_layers.get("volcanoes", True) else [],
        "fishing_activity": (d.get("fishing_activity") or []) if active_layers.get("fishing_activity", True) else [],
        "crowdthreat": (d.get("crowdthreat") or []) if active_layers.get("crowdthreat", True) else [],
        "correlations": (d.get("correlations") or []) if active_layers.get("correlations", True) else [],
        "uap_sightings": (d.get("uap_sightings") or []) if active_layers.get("uap_sightings", True) else [],
        "wastewater": (d.get("wastewater") or []) if active_layers.get("wastewater", True) else [],
        "sar_scenes": (d.get("sar_scenes") or []) if active_layers.get("sar", True) else [],
        "sar_anomalies": (d.get("sar_anomalies") or []) if active_layers.get("sar", True) else [],
        "sar_aoi_coverage": (d.get("sar_aoi_coverage") or []) if active_layers.get("sar", True) else [],
        "freshness": freshness,
    }
    return Response(
        content=orjson.dumps(
            _sanitize_payload(payload),
            default=str,
            option=orjson.OPT_NON_STR_KEYS,
        ),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


@app.get("/api/oracle/region-intel")
@limiter.limit("30/minute")
async def oracle_region_intel(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Get oracle intelligence summary for a geographic region."""
    from services.oracle_service import get_region_oracle_intel

    news_items = get_latest_data().get("news", [])
    return get_region_oracle_intel(lat, lng, news_items)


@app.get("/api/thermal/verify")
@limiter.limit("10/minute")
async def thermal_verify(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(10, ge=1, le=100),
):
    """On-demand thermal anomaly verification using Sentinel-2 SWIR bands."""
    from services.thermal_sentinel import search_thermal_anomaly

    result = search_thermal_anomaly(lat, lng, radius_km)
    return result


@app.post("/api/sigint/transmit")
@limiter.limit("5/minute")
async def sigint_transmit(request: Request):
    """Send an APRS-IS message to a specific callsign. Requires ham radio credentials."""
    from services.wormhole_supervisor import get_transport_tier

    tier = get_transport_tier()
    if str(tier or "").startswith("private_"):
        return {"ok": False, "detail": "APRS transmit blocked in private transport mode"}
    body = await request.json()
    callsign = body.get("callsign", "")
    passcode = body.get("passcode", "")
    target = body.get("target", "")
    message = body.get("message", "")
    if not all([callsign, passcode, target, message]):
        return {
            "ok": False,
            "detail": "Missing required fields: callsign, passcode, target, message",
        }
    from services.sigint_bridge import send_aprs_message

    return send_aprs_message(callsign, passcode, target, message)


@app.get("/api/sigint/nearest-sdr")
@limiter.limit("30/minute")
async def nearest_sdr(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Find the nearest KiwiSDR receivers to a given coordinate."""
    from services.sigint_bridge import find_nearest_kiwisdr

    kiwisdr_data = get_latest_data().get("kiwisdr", [])
    return find_nearest_kiwisdr(lat, lng, kiwisdr_data)


# â”€â”€â”€ Per-Identity Throttle State â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# In-memory: {node_id: {"last_send": timestamp, "daily_count": int, "daily_reset": timestamp}}
# Bounded to 10000 entries with 24hr TTL to prevent unbounded memory growth
_node_throttle: TTLCache = TTLCache(maxsize=10000, ttl=86400)
_gate_post_cooldown: TTLCache = TTLCache(maxsize=20000, ttl=86400)

# Byte limits per payload type
_BYTE_LIMITS = {"text": 200, "pin": 300, "emergency": 200, "command": 200}


def _check_throttle(
    node_id: str, priority_str: str, transport_lock: str = ""
) -> tuple[bool, str]:
    """Per-identity rate limiting based on node age and reputation.

    Tiers:
      New (rep < 3, age < 24h):       1 msg / 5 min,  10/day
      Established (rep >= 3 OR > 24h): 1 msg / 2 min,  50/day
      Trusted (rep >= 10):             1 msg / 30 sec, 200/day
      Emergency:                       no throttle

    Meshtastic public mesh is intentionally looser in testnet mode:
      Any public mesh sender:          2 msgs / min, tier caps unchanged
    """
    if priority_str == "emergency":
        return True, ""

    now = time.time()
    state = _node_throttle.get(node_id)
    if not state:
        _node_throttle[node_id] = {
            "last_send": 0,
            "daily_count": 0,
            "daily_reset": now,
            "first_seen": now,
        }
        state = _node_throttle[node_id]

    # Reset daily counter at midnight
    if now - state["daily_reset"] > 86400:
        state["daily_count"] = 0
        state["daily_reset"] = now

    # Determine tier (reputation integration will come with Feature 2)
    age_hours = (now - state.get("first_seen", now)) / 3600
    rep_score = 0
    try:
        from services.mesh.mesh_reputation import reputation_ledger

        rep_score = reputation_ledger.get_reputation(node_id).get("overall", 0)
        age_hours = max(age_hours, reputation_ledger.get_node_age_days(node_id) * 24)
    except Exception:
        rep_score = 0

    if rep_score >= 20 or age_hours >= 168:
        interval, daily_cap, tier = 30, 200, "trusted"
    elif rep_score >= 5 or age_hours >= 48:
        interval, daily_cap, tier = 120, 75, "established"
    else:
        interval, daily_cap, tier = 300, 15, "new"

    if str(transport_lock or "").lower() == "meshtastic":
        interval = min(interval, 30)

    # Check daily cap
    if state["daily_count"] >= daily_cap:
        return (
            False,
            f"Daily message limit reached ({daily_cap} messages for {tier} nodes). Resets in {int(86400 - (now - state['daily_reset']))}s.",
        )

    # Check interval
    elapsed = now - state["last_send"]
    if elapsed < interval:
        remaining = int(interval - elapsed)
        return False, f"Rate limit: 1 message per {interval}s for {tier} nodes. Wait {remaining}s."

    # Allowed
    state["last_send"] = now
    state["daily_count"] += 1
    return True, ""


def _check_gate_post_cooldown(sender_id: str, gate_id: str) -> tuple[bool, str]:
    """Check cooldown â€” does NOT record it.  Call _record_gate_post_cooldown() after success."""
    gate_key = str(gate_id or "").strip().lower()
    sender_key = str(sender_id or "").strip()
    if not gate_key or not sender_key:
        return True, ""
    now = time.time()
    cooldown_key = f"{sender_key}:{gate_key}"
    last_post = float(_gate_post_cooldown.get(cooldown_key, 0) or 0)
    if last_post > 0:
        elapsed = now - last_post
        if elapsed < 30:
            remaining = max(1, math.ceil(30 - elapsed))
            return False, f"Gate post cooldown: wait {remaining}s before posting again."
    return True, ""


def _record_gate_post_cooldown(sender_id: str, gate_id: str) -> None:
    """Stamp the cooldown AFTER a successful gate post."""
    gate_key = str(gate_id or "").strip().lower()
    sender_key = str(sender_id or "").strip()
    if gate_key and sender_key:
        _gate_post_cooldown[f"{sender_key}:{gate_key}"] = time.time()


def _verify_signed_event(
    *,
    event_type: str,
    node_id: str,
    sequence: int,
    public_key: str,
    public_key_algo: str,
    signature: str,
    payload: dict,
    protocol_version: str,
) -> tuple[bool, str]:
    return _shared_verify_signed_event(
        event_type=event_type,
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        payload=payload,
        protocol_version=protocol_version,
    )


def _apply_legacy_dm_signature_compat(
    *,
    tier: str,
    delivery_class: str,
    payload_format: str,
    session_welcome: str,
    sender_seal: str,
    relay_salt_hex: str,
    sig_reason: str,
) -> dict[str, Any]:
    result = {
        "ok": True,
        "detail": "",
        "status_code": 0,
        "format": str(payload_format or "dm1").strip().lower() or "dm1",
        "session_welcome": str(session_welcome or "").strip(),
        "sender_seal": str(sender_seal or "").strip(),
        "relay_salt": str(relay_salt_hex or "").strip().lower(),
        "legacy_compat": False,
    }
    if sig_reason != "legacy_dm_signature_compat":
        return result

    logger.warning(
        "legacy dm signature compatibility path used; unsigned modern fields stripped before transport"
    )
    result["legacy_compat"] = True
    result["format"] = "dm1"
    result["session_welcome"] = ""
    result["sender_seal"] = ""
    result["relay_salt"] = ""

    if str(tier or "").startswith("private_") and result["format"] == "dm1":
        result["ok"] = False
        result["status_code"] = 403
        result["detail"] = "MLS session required in private transport mode - dm1 blocked on raw send path"
        return result

    if (
        str(tier or "").startswith("private_")
        and str(delivery_class or "").strip().lower() == "shared"
        and bool(get_settings().MESH_DM_REQUIRE_SENDER_SEAL_SHARED)
    ):
        result["ok"] = False
        result["detail"] = "sealed sender required for shared private DMs"
        return result

    return result


def _preflight_signed_event_integrity(
    *,
    event_type: str,
    node_id: str,
    sequence: int,
    public_key: str,
    public_key_algo: str,
    signature: str,
    protocol_version: str,
) -> tuple[bool, str]:
    return _shared_preflight_signed_event_integrity(
        event_type=event_type,
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        protocol_version=protocol_version,
    )


def _verify_signed_write(
    *,
    event_type: str,
    node_id: str,
    sequence: int,
    public_key: str,
    public_key_algo: str,
    signature: str,
    payload: dict,
    protocol_version: str,
) -> tuple[bool, str]:
    return _shared_verify_signed_write(
        event_type=event_type,
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        payload=payload,
        protocol_version=protocol_version,
    )


def _verify_gate_message_signed_write(
    *,
    node_id: str,
    sequence: int,
    public_key: str,
    public_key_algo: str,
    signature: str,
    payload: dict,
    reply_to: str,
    protocol_version: str,
) -> tuple[bool, str, str]:
    return _shared_verify_gate_message_signed_write(
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        payload=payload,
        reply_to=reply_to,
        protocol_version=protocol_version,
    )


def _recover_verified_gate_reply_to(
    *,
    node_id: str,
    sequence: int,
    public_key: str,
    public_key_algo: str,
    signature: str,
    payload: dict,
    reply_to: str,
    protocol_version: str,
) -> str:
    return _shared_recover_verified_gate_reply_to(
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        payload=payload,
        reply_to=reply_to,
        protocol_version=protocol_version,
    )


def _signed_body(request: Request) -> dict[str, Any]:
    prepared = get_prepared_signed_write(request)
    if prepared is None:
        return {}
    return dict(prepared.body)


def _prepared_signed_write(request: Request):
    return get_prepared_signed_write(request)


@app.post("/api/mesh/send")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.MESH_SEND)
async def mesh_send(request: Request):
    """Unified mesh message endpoint â€” auto-routes via optimal transport.

    Body: { destination, message, priority?, channel?, node_id?, credentials? }
    The router picks APRS, Meshtastic, or Internet based on gate logic.
    Enforces byte limits and per-identity rate limiting.
    """
    body = _signed_body(request)
    destination = body.get("destination", "")
    message = body.get("message", "")
    if not destination or not message:
        return {"ok": False, "detail": "Missing required fields: destination, message"}

    # â”€â”€â”€ Byte limit enforcement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    payload_bytes = len(message.encode("utf-8"))
    payload_type = body.get("payload_type", "text")
    max_bytes = _BYTE_LIMITS.get(payload_type, 200)
    if payload_bytes > max_bytes:
        return {
            "ok": False,
            "detail": f"Message too long ({payload_bytes} bytes). Maximum: {max_bytes} bytes for {payload_type} messages.",
        }

    # â”€â”€â”€ Signature verification & node registration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    node_id = body.get("node_id", body.get("sender_id", "anonymous"))
    public_key = body.get("public_key", "")
    public_key_algo = body.get("public_key_algo", "")
    signature = body.get("signature", "")
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "")
    signed_payload = {
        "message": message,
        "destination": destination,
        "channel": body.get("channel", "LongFast"),
        "priority": body.get("priority", "normal").lower(),
        "ephemeral": bool(body.get("ephemeral", False)),
    }
    if body.get("transport_lock"):
        signed_payload["transport_lock"] = str(body.get("transport_lock"))
    # Register node in reputation ledger (auto-creates if new)
    if node_id != "anonymous":
        try:
            from services.mesh.mesh_reputation import reputation_ledger

            reputation_ledger.register_node(node_id, public_key, public_key_algo)
        except Exception:
            pass  # Non-critical â€” don't block sends if reputation module fails

    # â”€â”€â”€ Per-identity throttle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    priority_str = signed_payload["priority"]
    transport_lock = str(body.get("transport_lock", "") or "").lower()
    throttle_ok, throttle_reason = _check_throttle(node_id, priority_str, transport_lock)
    if not throttle_ok:
        return {"ok": False, "detail": throttle_reason}

    from services.mesh.mesh_router import (
        MeshEnvelope,
        MeshtasticTransport,
        Priority,
        TransportResult,
        mesh_router,
    )

    priority_map = {
        "emergency": Priority.EMERGENCY,
        "high": Priority.HIGH,
        "normal": Priority.NORMAL,
        "low": Priority.LOW,
    }
    priority = priority_map.get(priority_str, Priority.NORMAL)

    # â”€â”€â”€ C-1 fix: compute trust_tier from Wormhole state â”€â”€â”€â”€â”€â”€â”€
    from services.wormhole_supervisor import get_transport_tier

    computed_tier = get_transport_tier()

    envelope = MeshEnvelope(
        sender_id=node_id,
        destination=destination,
        channel=body.get("channel", "LongFast"),
        priority=priority,
        payload=message,
        ephemeral=body.get("ephemeral", False),
        trust_tier=computed_tier,
    )

    credentials = body.get("credentials", {})
    # â”€â”€â”€ C-2 fix: enforce tier before transport_lock dispatch â”€â”€
    private_tier = str(envelope.trust_tier or "").startswith("private_")
    if transport_lock == "meshtastic":
        if private_tier:
            results = [TransportResult(
                False, "meshtastic",
                "Private-tier content cannot be sent over Meshtastic"
            )]
        elif not mesh_router.meshtastic.can_reach(envelope):
            results = [TransportResult(False, "meshtastic", "Message exceeds Meshtastic payload limit")]
        else:
            cb_ok, cb_reason = mesh_router.breakers["meshtastic"].check_and_record(envelope.priority)
            if not cb_ok:
                results = [TransportResult(False, "meshtastic", cb_reason)]
            else:
                envelope.route_reason = (
                    "Transport locked to Meshtastic public path"
                    if MeshtasticTransport._parse_node_id(destination) is None
                    else "Transport locked to Meshtastic public node-targeted path"
                )
                result = mesh_router.meshtastic.send(envelope, credentials)
                if result.ok:
                    envelope.routed_via = mesh_router.meshtastic.NAME
                results = [result]
    elif transport_lock == "aprs":
        if private_tier:
            results = [TransportResult(
                False, "aprs",
                "Private-tier content cannot be sent over APRS"
            )]
        else:
            results = mesh_router.route(envelope, credentials)
    else:
        results = mesh_router.route(envelope, credentials)
    any_ok = any(r.ok for r in results)

    # â”€â”€â”€ Mirror to Meshtastic bridge feed â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # The MQTT broker won't echo our own publishes back to our subscriber,
    # so inject successfully-sent messages into the bridge's deque directly.
    if any_ok and envelope.routed_via == "meshtastic":
        try:
            from services.sigint_bridge import sigint_grid

            bridge = sigint_grid.mesh
            if bridge:
                from datetime import datetime

                bridge.messages.appendleft(
                    {
                        "from": MeshtasticTransport.mesh_address_for_sender(node_id),
                        "to": destination if MeshtasticTransport._parse_node_id(destination) is not None else "broadcast",
                        "text": message,
                        "region": credentials.get("mesh_region", "US"),
                        "channel": body.get("channel", "LongFast"),
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                )
        except Exception:
            pass  # Non-critical

    return {
        "ok": any_ok,
        "message_id": envelope.message_id,
        "event_id": "",
        "routed_via": envelope.routed_via,
        "route_reason": envelope.route_reason,
        "results": [r.to_dict() for r in results],
    }


@app.get("/api/mesh/log")
@limiter.limit("30/minute")
async def mesh_log(request: Request):
    """Get recent mesh message routing log (audit trail)."""
    from services.mesh.mesh_router import mesh_router

    mesh_router.prune_message_log()
    entries = list(mesh_router.message_log)
    ok, _detail = _check_scoped_auth(request, "mesh.audit")
    if ok:
        return {"log": entries}
    public_entries = [entry for entry in (_public_mesh_log_entry(item) for item in entries) if entry]
    return {"log": public_entries}


@app.get("/api/mesh/status")
@limiter.limit("30/minute")
async def mesh_status(request: Request):
    """Get mesh system status including circuit breaker state."""
    from services.env_check import get_security_posture_warnings
    from services.mesh.mesh_router import mesh_router
    from services.sigint_bridge import sigint_grid

    mesh_router.prune_message_log()
    entries = list(mesh_router.message_log)
    sigs = sigint_grid.get_all_signals()
    aprs = sum(1 for s in sigs if s.get("source") == "aprs")
    mesh = sum(1 for s in sigs if s.get("source") == "meshtastic")
    js8 = sum(1 for s in sigs if s.get("source") == "js8call")
    ok, _detail = _check_scoped_auth(request, "mesh.audit")
    authenticated = _scoped_view_authenticated(request, "mesh.audit")
    response = {
        "circuit_breakers": {
            name: breaker.get_status() for name, breaker in mesh_router.breakers.items()
        },
        "message_log_size": len(entries) if ok else _public_mesh_log_size(entries),
        "signal_counts": {
            "aprs": aprs,
            "meshtastic": mesh,
            "js8call": js8,
            "total": aprs + mesh + js8,
        },
    }
    if ok:
        response["public_message_log_size"] = _public_mesh_log_size(entries)
        response["private_log_retention_seconds"] = int(
            getattr(get_settings(), "MESH_PRIVATE_LOG_TTL_S", 900) or 0
        )
        response["security_warnings"] = get_security_posture_warnings(get_settings())

    return _redact_public_mesh_status(response, authenticated=authenticated)


@app.get("/api/mesh/signals")
@limiter.limit("30/minute")
async def mesh_signals(
    request: Request,
    source: str = "",
    region: str = "",
    root: str = "",
    limit: int = 50,
):
    """Get SIGINT signals with optional source/region/root filters."""
    from services.fetchers.sigint import build_sigint_snapshot

    sigs, _channel_stats, totals = build_sigint_snapshot()
    if source:
        sigs = [s for s in sigs if s.get("source") == source.lower()]
    if region:
        region_filter = region.upper()
        sigs = [
            s
            for s in sigs
            if s.get("region", "").upper() == region_filter
            or s.get("root", "").upper() == region_filter
        ]
    if root:
        root_filter = root.upper()
        sigs = [s for s in sigs if s.get("root", "").upper() == root_filter]
    return {
        "signals": sigs[: min(limit, 500)],
        "total": len(sigs),
        "source_totals": totals,
    }


@app.get("/api/mesh/messages")
@limiter.limit("30/minute")
async def mesh_messages(
    request: Request,
    region: str = "",
    root: str = "",
    channel: str = "",
    limit: int = 30,
):
    """Get recent Meshtastic text messages from the MQTT bridge."""
    from services.sigint_bridge import sigint_grid

    bridge = sigint_grid.mesh
    if not bridge:
        return []
    msgs = list(bridge.messages)
    if region:
        region_filter = region.upper()
        msgs = [
            m
            for m in msgs
            if m.get("region", "").upper() == region_filter
            or m.get("root", "").upper() == region_filter
        ]
    if root:
        root_filter = root.upper()
        msgs = [m for m in msgs if m.get("root", "").upper() == root_filter]
    if channel:
        msgs = [m for m in msgs if m.get("channel", "").lower() == channel.lower()]
    return msgs[: min(limit, 100)]


@app.get("/api/mesh/channels")
@limiter.limit("30/minute")
async def mesh_channels(request: Request):
    """Get Meshtastic channel population stats â€” nodes per region/channel."""
    stats = get_latest_data().get("mesh_channel_stats", {})
    return stats


# â”€â”€â”€ Reputation Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Cached root node_id â€” avoids 5 encrypted disk reads per vote.
_root_node_id_cache: dict[str, object] = {"value": None, "ts": 0.0}
_ROOT_NODE_ID_TTL = 30.0  # seconds


def _cached_root_node_id() -> str:
    import time as _time

    now = _time.time()
    if _root_node_id_cache["value"] is not None and (now - float(_root_node_id_cache["ts"])) < _ROOT_NODE_ID_TTL:
        return str(_root_node_id_cache["value"])
    try:
        from services.mesh.mesh_wormhole_persona import read_wormhole_persona_state

        ps = read_wormhole_persona_state()
        nid = str(ps.get("root_identity", {}).get("node_id", "") or "").strip()
        _root_node_id_cache["value"] = nid
        _root_node_id_cache["ts"] = now
        return nid
    except Exception:
        return ""


@app.post("/api/mesh/vote")
@limiter.limit("30/minute")
@requires_signed_write(kind=SignedWriteKind.MESH_VOTE)
async def mesh_vote(request: Request):
    """Cast a reputation vote on a node.

    Body: {voter_id, voter_pubkey?, voter_sig?, target_id, vote: 1|-1, gate?: string}
    """
    from services.mesh.mesh_reputation import reputation_ledger

    body = _signed_body(request)
    voter_id = body.get("voter_id", "")
    target_id = body.get("target_id", "")
    vote = body.get("vote", 0)
    gate = body.get("gate", "")
    public_key = body.get("voter_pubkey", "")
    public_key_algo = body.get("public_key_algo", "")
    signature = body.get("voter_sig", "")
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "")

    if not voter_id or not target_id:
        return {"ok": False, "detail": "Missing voter_id or target_id"}
    if vote not in (1, -1):
        return {"ok": False, "detail": "Vote must be 1 or -1"}

    gate_ok, gate_detail = _validate_gate_vote_context(voter_id, gate)
    if not gate_ok:
        return {"ok": False, "detail": gate_detail}
    gate = gate_detail or ""

    vote_payload = {"target_id": target_id, "vote": vote, "gate": gate}

    # Resolve stable local operator ID for duplicate-vote prevention.
    # Personas generate unique keypairs, so voter_id alone is insufficient â€”
    # use the root identity's node_id as a stable anchor so switching personas
    # doesn't let the same operator vote multiple times on the same post.
    stable_voter_id = voter_id
    try:
        root_nid = _cached_root_node_id()
        if root_nid:
            stable_voter_id = root_nid
    except Exception:
        pass

    # Register node if not known
    reputation_ledger.register_node(voter_id, public_key, public_key_algo)

    ok, reason, vote_weight = reputation_ledger.cast_vote(stable_voter_id, target_id, vote, gate)

    # Record on Infonet
    if ok:
        try:
            from services.mesh.mesh_hashchain import infonet

            normalized_payload = normalize_payload("vote", vote_payload)
            infonet.append(
                event_type="vote",
                node_id=voter_id,
                payload=normalized_payload,
                signature=signature,
                sequence=sequence,
                public_key=public_key,
                public_key_algo=public_key_algo,
                protocol_version=protocol_version,
            )
        except Exception:
            pass

    return {"ok": ok, "detail": reason, "weight": round(vote_weight, 2)}


@app.post("/api/mesh/report")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.MESH_REPORT)
async def mesh_report(request: Request):
    """Report abusive or fraudulent behavior (signed, public, non-anonymous)."""
    body = _signed_body(request)
    reporter_id = body.get("reporter_id", "")
    target_id = body.get("target_id", "")
    reason = body.get("reason", "")
    gate = body.get("gate", "")
    evidence = body.get("evidence", "")
    public_key = body.get("public_key", "")
    public_key_algo = body.get("public_key_algo", "")
    signature = body.get("signature", "")
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "")

    if not reporter_id or not target_id or not reason:
        return {"ok": False, "detail": "Missing reporter_id, target_id, or reason"}

    report_payload = {"target_id": target_id, "reason": reason, "gate": gate, "evidence": evidence}

    try:
        from services.mesh.mesh_reputation import reputation_ledger

        reputation_ledger.register_node(reporter_id, public_key, public_key_algo)
    except Exception:
        pass

    try:
        from services.mesh.mesh_hashchain import infonet

        normalized_payload = normalize_payload("abuse_report", report_payload)
        infonet.append(
            event_type="abuse_report",
            node_id=reporter_id,
            payload=normalized_payload,
            signature=signature,
            sequence=sequence,
            public_key=public_key,
            public_key_algo=public_key_algo,
            protocol_version=protocol_version,
        )
    except Exception:
        logger.exception("failed to record abuse report on infonet")
        return {"ok": False, "detail": "report_record_failed"}

    return {"ok": True, "detail": "Report recorded"}


@app.get("/api/mesh/reputation")
@limiter.limit("60/minute")
async def mesh_reputation(request: Request, node_id: str = ""):
    """Get reputation for a single node.

    Public callers receive a summary-only view; authenticated audit callers may
    access the richer breakdown.
    """
    from services.mesh.mesh_reputation import reputation_ledger

    if not node_id:
        return {"ok": False, "detail": "Provide ?node_id=xxx"}
    return reputation_ledger.get_reputation_log(
        node_id,
        detailed=_scoped_view_authenticated(request, "mesh.audit"),
    )


@app.get("/api/mesh/reputation/batch")
@limiter.limit("60/minute")
async def mesh_reputation_batch(request: Request, node_id: list[str] = Query(default=[])):
    """Get overall public reputation for multiple public node IDs."""
    from services.mesh.mesh_reputation import reputation_ledger

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in list(node_id or []):
        candidate = str(raw or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
        if len(normalized) >= 100:
            break
    if not normalized:
        return {"ok": False, "detail": "Provide at least one node_id", "reputations": {}}
    return {
        "ok": True,
        "reputations": {
            candidate: reputation_ledger.get_reputation(candidate).get("overall", 0) or 0
            for candidate in normalized
        },
    }


@app.get("/api/mesh/reputation/all", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def mesh_reputation_all(request: Request):
    """Get all known node reputations."""
    from services.mesh.mesh_reputation import reputation_ledger

    return {"reputations": reputation_ledger.get_all_reputations()}


@app.post("/api/mesh/identity/rotate")
@limiter.limit("5/minute")
@requires_signed_write(kind=SignedWriteKind.IDENTITY_ROTATE)
async def mesh_identity_rotate(request: Request):
    """Link a new node_id to an old one via dual-signature rotation."""
    body = _signed_body(request)
    old_node_id = body.get("old_node_id", "").strip()
    old_public_key = body.get("old_public_key", "").strip()
    old_public_key_algo = body.get("old_public_key_algo", "").strip()
    old_signature = body.get("old_signature", "").strip()
    new_node_id = body.get("new_node_id", "").strip()
    new_public_key = body.get("new_public_key", "").strip()
    new_public_key_algo = body.get("new_public_key_algo", "").strip()
    new_signature = body.get("new_signature", "").strip()
    timestamp = _safe_int(body.get("timestamp", 0) or 0)
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()

    if not (
        old_node_id
        and old_public_key
        and old_public_key_algo
        and old_signature
        and new_node_id
        and new_public_key
        and new_public_key_algo
        and new_signature
        and timestamp
    ):
        return {"ok": False, "detail": "Missing rotation fields"}
    if old_node_id == new_node_id:
        return {"ok": False, "detail": "old_node_id must differ from new_node_id"}
    if abs(timestamp - int(time.time())) > 7 * 86400:
        return {"ok": False, "detail": "Rotation timestamp is too far from current time"}

    rotation_payload = {
        "old_node_id": old_node_id,
        "old_public_key": old_public_key,
        "old_public_key_algo": old_public_key_algo,
        "new_public_key": new_public_key,
        "new_public_key_algo": new_public_key_algo,
        "timestamp": timestamp,
        "old_signature": old_signature,
    }

    old_sig_ok, old_sig_reason = verify_key_rotation_claim_signature(
        old_node_id=old_node_id,
        old_public_key=old_public_key,
        old_public_key_algo=old_public_key_algo,
        old_signature=old_signature,
        new_public_key=new_public_key,
        new_public_key_algo=new_public_key_algo,
        timestamp=timestamp,
    )
    if not old_sig_ok:
        return {"ok": False, "detail": old_sig_reason}

    from services.mesh.mesh_reputation import reputation_ledger

    reputation_ledger.register_node(new_node_id, new_public_key, new_public_key_algo)
    ok, reason = reputation_ledger.link_identities(old_node_id, new_node_id)
    if not ok:
        return {"ok": False, "detail": reason}

    # Record on Infonet
    try:
        from services.mesh.mesh_hashchain import infonet

        normalized_payload = normalize_payload("key_rotate", rotation_payload)
        infonet.append(
            event_type="key_rotate",
            node_id=new_node_id,
            payload=normalized_payload,
            signature=new_signature,
            sequence=sequence,
            public_key=new_public_key,
            public_key_algo=new_public_key_algo,
            protocol_version=protocol_version,
        )
    except Exception:
        pass

    return {"ok": True, "detail": "Identity linked"}


@app.post("/api/mesh/identity/revoke")
@limiter.limit("5/minute")
@requires_signed_write(kind=SignedWriteKind.IDENTITY_REVOKE)
async def mesh_identity_revoke(request: Request):
    """Revoke a node's key with a grace window."""
    body = _signed_body(request)
    node_id = body.get("node_id", "").strip()
    public_key = body.get("public_key", "").strip()
    public_key_algo = body.get("public_key_algo", "").strip()
    signature = body.get("signature", "").strip()
    revoked_at = _safe_int(body.get("revoked_at", 0) or 0)
    grace_until = _safe_int(body.get("grace_until", 0) or 0)
    reason = body.get("reason", "").strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()

    if not (node_id and public_key and public_key_algo and signature and revoked_at and grace_until):
        return {"ok": False, "detail": "Missing revocation fields"}

    now = int(time.time())
    max_grace = 7 * 86400
    if grace_until < revoked_at:
        return {"ok": False, "detail": "grace_until must be >= revoked_at"}
    if grace_until - revoked_at > max_grace:
        return {"ok": False, "detail": "Grace window too large (max 7 days)"}
    if abs(revoked_at - now) > max_grace:
        return {"ok": False, "detail": "revoked_at is too far from current time"}

    payload = {
        "revoked_public_key": public_key,
        "revoked_public_key_algo": public_key_algo,
        "revoked_at": revoked_at,
        "grace_until": grace_until,
        "reason": reason,
    }

    if payload["revoked_public_key"] != public_key:
        return {"ok": False, "detail": "revoked_public_key must match public_key"}
    if payload["revoked_public_key_algo"] != public_key_algo:
        return {"ok": False, "detail": "revoked_public_key_algo must match public_key_algo"}

    try:
        from services.mesh.mesh_hashchain import infonet

        normalized_payload = normalize_payload("key_revoke", payload)
        infonet.append(
            event_type="key_revoke",
            node_id=node_id,
            payload=normalized_payload,
            signature=signature,
            sequence=sequence,
            public_key=public_key,
            public_key_algo=public_key_algo,
            protocol_version=protocol_version,
        )
    except Exception:
        logger.exception("failed to record key revocation on infonet")
        return {"ok": False, "detail": "revocation_record_failed"}

    return {"ok": True, "detail": "Identity revoked"}


# â”€â”€â”€ Gate Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@app.post("/api/mesh/gate/create")
@limiter.limit("5/hour")
@requires_signed_write(kind=SignedWriteKind.GATE_CREATE)
async def gate_create(request: Request):
    """Create a new reputation-gated community.

    Body: {creator_id, creator_pubkey?, creator_sig?, gate_id, display_name, rules?: {min_overall_rep, min_gate_rep}}
    """
    from services.mesh.mesh_reputation import (
        ALLOW_DYNAMIC_GATES,
        reputation_ledger,
        gate_manager,
    )

    if not ALLOW_DYNAMIC_GATES:
        return {"ok": False, "detail": "Gate creation is disabled for the fixed private launch catalog"}

    body = _signed_body(request)
    creator_id = body.get("creator_id", "")
    gate_id = body.get("gate_id", "")
    display_name = body.get("display_name", gate_id)
    rules = body.get("rules", {})
    public_key = body.get("creator_pubkey", "")
    public_key_algo = body.get("public_key_algo", "")
    signature = body.get("creator_sig", "")
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "")

    if not creator_id or not gate_id:
        return {"ok": False, "detail": "Missing creator_id or gate_id"}

    gate_payload = {"gate_id": gate_id, "display_name": display_name, "rules": rules}

    reputation_ledger.register_node(creator_id, public_key, public_key_algo)

    ok, reason = gate_manager.create_gate(
        creator_id,
        gate_id,
        display_name,
        min_overall_rep=rules.get("min_overall_rep", 0),
        min_gate_rep=rules.get("min_gate_rep"),
    )

    # Record on Infonet
    if ok:
        try:
            from services.mesh.mesh_hashchain import infonet

            normalized_payload = normalize_payload("gate_create", gate_payload)
            infonet.append(
                event_type="gate_create",
                node_id=creator_id,
                payload=normalized_payload,
                signature=signature,
                sequence=sequence,
                public_key=public_key,
                public_key_algo=public_key_algo,
                protocol_version=protocol_version,
            )
        except Exception:
            pass

    return {"ok": ok, "detail": reason}


@app.get("/api/mesh/gate/list")
@limiter.limit("30/minute")
async def gate_list(request: Request):
    """List all known gates (public catalog â€” secrets are never included)."""
    from services.mesh.mesh_reputation import gate_manager

    return {"gates": gate_manager.list_gates()}


@app.get("/api/mesh/gate/{gate_id}")
@limiter.limit("30/minute")
async def gate_detail(request: Request, gate_id: str):
    """Get gate details including ratification status."""
    from services.mesh.mesh_reputation import gate_manager

    gate = gate_manager.get_gate(gate_id)
    if not gate:
        return {"ok": False, "detail": f"Gate '{gate_id}' not found"}
    gate["ratification"] = gate_manager.get_ratification_status(gate_id)
    return gate


@app.post("/api/mesh/gate/{gate_id}/message")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.GATE_MESSAGE)
async def gate_message(request: Request, gate_id: str):
    """Post a message to a gate. Checks entry rules against sender's reputation.

    Body: {sender_id, ciphertext, nonce, sender_ref, signature?}
    """
    body = _signed_body(request)
    return _submit_gate_message_envelope(request, gate_id, body)


def _submit_gate_message_envelope(request: Request, gate_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Validate and record an encrypted gate envelope on the private plane."""
    from services.mesh.mesh_reputation import reputation_ledger, gate_manager
    prepared = _prepared_signed_write(request)
    sender_id = body.get("sender_id", "")
    epoch = _safe_int(body.get("epoch", 0) or 0)
    ciphertext = str(body.get("ciphertext", ""))
    nonce = str(body.get("nonce", body.get("iv", "")))
    sender_ref = str(body.get("sender_ref", ""))
    payload_format = str(body.get("format", "mls1") or "mls1")
    public_key = body.get("public_key", "")
    public_key_algo = body.get("public_key_algo", "")
    signature = body.get("signature", "")
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "")

    if not sender_id:
        return {"ok": False, "detail": "Missing sender_id"}
    if "message" in body and str(body.get("message", "")).strip():
        return {
            "ok": False,
            "detail": "Plaintext gate messages are no longer accepted. Submit an encrypted gate envelope.",
        }

    gate_envelope = str(body.get("gate_envelope", "") or "").strip()
    envelope_hash = str(body.get("envelope_hash", "") or "").strip()
    transport_lock = str(body.get("transport_lock", "") or "").strip().lower()
    reply_to = str(body.get("reply_to", "") or "").strip()
    if not transport_lock:
        return {"ok": False, "detail": "transport_lock is required on content-private signed writes"}
    if transport_lock != "private_strong":
        return {"ok": False, "detail": "gate messages require private_strong transport_lock"}
    envelope_policy = _resolve_envelope_policy(gate_id)
    if envelope_policy == "envelope_always" and not gate_envelope:
        return {"ok": False, "detail": "gate_envelope_required"}
    if gate_envelope and not envelope_hash:
        return {"ok": False, "detail": "gate_envelope requires signed envelope_hash"}
    if envelope_hash:
        import hashlib as _hl

        if not gate_envelope:
            return {"ok": False, "detail": "gate_envelope required when envelope_hash is present"}
        if (
            len(envelope_hash) != 64
            or envelope_hash != envelope_hash.lower()
            or any(ch not in "0123456789abcdef" for ch in envelope_hash)
        ):
            return {"ok": False, "detail": "invalid envelope_hash"}
        try:
            actual_envelope_hash = _hl.sha256(gate_envelope.encode("ascii")).hexdigest()
        except UnicodeEncodeError:
            return {"ok": False, "detail": "invalid gate_envelope"}
        if actual_envelope_hash != envelope_hash:
            return {"ok": False, "detail": "gate_envelope does not match envelope_hash"}

    gate_payload_input = {
        "gate": gate_id,
        "ciphertext": ciphertext,
        "nonce": nonce,
        "sender_ref": sender_ref,
        "format": payload_format,
    }
    if epoch > 0:
        gate_payload_input["epoch"] = epoch
    if envelope_hash:
        gate_payload_input["envelope_hash"] = envelope_hash
    gate_payload_input["transport_lock"] = transport_lock
    gate_payload = normalize_payload("gate_message", gate_payload_input)
    # Validate BEFORE adding gate_envelope (which is not a normalized field).
    payload_ok, payload_reason = validate_event_payload("gate_message", gate_payload)
    if not payload_ok:
        return {"ok": False, "detail": payload_reason}
    # gate_envelope is not part of the signed payload â€” envelope_hash binds it.
    # reply_to is signed for new compose flows; if only the legacy no-reply_to
    # signature verifies, strip it rather than accepting unauthenticated
    # threading metadata.
    if gate_envelope:
        gate_payload["gate_envelope"] = gate_envelope
    if reply_to:
        gate_payload["reply_to"] = reply_to
    # Signature verification payload excludes epoch and gate_envelope.
    # envelope_hash is signed when present.
    signature_gate_payload = {
        "gate": gate_id,
        "ciphertext": ciphertext,
        "nonce": nonce,
        "sender_ref": sender_ref,
        "format": payload_format,
    }
    if envelope_hash:
        signature_gate_payload["envelope_hash"] = envelope_hash
    signature_gate_payload["transport_lock"] = transport_lock
    if epoch > 0:
        signature_gate_payload["epoch"] = epoch

    if prepared is not None and prepared.kind == SignedWriteKind.GATE_MESSAGE:
        sig_ok = True
        sig_reason = str(prepared.reason or "ok")
        verified_reply_to = str(prepared.verified_reply_to or reply_to)
    else:
        # Verify envelope binding: if envelope_hash is signed, the submitted
        # gate_envelope must match. Checked after signature so the hash itself
        # is already authenticated.
        sig_ok, sig_reason, verified_reply_to = _verify_gate_message_signed_write(
            node_id=sender_id,
            sequence=sequence,
            public_key=public_key,
            public_key_algo=public_key_algo,
            signature=signature,
            payload=signature_gate_payload,
            reply_to=reply_to,
            protocol_version=protocol_version,
        )
    if verified_reply_to != reply_to:
        gate_payload.pop("reply_to", None)
        reply_to = verified_reply_to
    if not sig_ok:
        return {"ok": False, "detail": sig_reason}

    if epoch > 0:
        try:
            from services.mesh.mesh_gate_mls import inspect_local_gate_state

            gate_state = inspect_local_gate_state(gate_id, expected_epoch=epoch)
        except Exception:
            gate_state = {"ok": False, "repair_state": "gate_state_stale", "detail": "gate epoch check unavailable"}
        if not bool(gate_state.get("ok", False)):
            return {
                "ok": False,
                "detail": str(gate_state.get("repair_state") or gate_state.get("detail") or "gate_state_stale"),
                "current_epoch": _safe_int(gate_state.get("current_epoch", 0) or 0),
                "expected_epoch": epoch,
            }

    # Do not synthesize durable envelopes after signature verification. A
    # gate_envelope is trusted only when the author signed its envelope_hash.

    reputation_ledger.register_node(sender_id, public_key, public_key_algo)

    # Check gate access
    can_enter, reason = gate_manager.can_enter(sender_id, gate_id)
    if not can_enter:
        return {"ok": False, "detail": f"Gate access denied: {reason}"}

    cooldown_ok, cooldown_reason = _check_gate_post_cooldown(sender_id, gate_id)
    if not cooldown_ok:
        return {"ok": False, "detail": cooldown_reason}

    # Advance sequence counter (replay protection) without appending to
    # the public infonet chain â€” gate messages are private.
    try:
        from services.mesh.mesh_hashchain import infonet, gate_store

        seq_ok, seq_reason = _validate_private_signed_sequence(
            infonet,
            sender_id,
            sequence,
            domain="gate_message",
        )
        if not seq_ok:
            return {"ok": False, "detail": seq_reason}
    except ValueError as exc:
        return {"ok": False, "detail": str(exc)}
    except Exception:
        logger.exception("Failed to advance sequence for gate message")
        return {"ok": False, "detail": "Failed to record gate message"}

    gate_manager.record_message(gate_id)
    _record_gate_post_cooldown(sender_id, gate_id)
    logger.info("Encrypted gate message accepted on obfuscated gate plane")

    # Build gate event and store in gate_store (private â€” not on public chain).
    try:
        from services.mesh.mesh_hashchain import _private_gate_event_id
        import time as _time

        store_payload = dict(gate_payload)
        if sig_reason in {"legacy_gate_epoch_signature_compat", "legacy_gate_epoch_reply_signature_compat"}:
            store_payload.pop("epoch", None)
        if gate_envelope:
            store_payload["gate_envelope"] = gate_envelope
        if reply_to:
            store_payload["reply_to"] = reply_to

        gate_event = {
            "event_type": "gate_message",
            "node_id": sender_id,
            "payload": store_payload,
            "timestamp": _time.time(),
            "sequence": sequence,
            "signature": signature,
            "public_key": public_key,
            "public_key_algo": public_key_algo,
            "protocol_version": protocol_version or PROTOCOL_VERSION,
        }
        gate_event["event_id"] = _private_gate_event_id(gate_id, sender_id, sequence, gate_event)
    except Exception:
        logger.exception("Failed to prepare private gate message for queued release")
        return {"ok": False, "detail": "Failed to record gate message"}

    # Append to the local gate_store immediately. The gate_store is a
    # per-node persistent ciphertext chain; writing to it is a local
    # operation with no network dependency. Previously this happened only
    # inside the release worker's attempt_private_release path, which
    # meant messages sat in the outbox — invisible to the author and the
    # gate UI — until the transport tier reached the release floor.
    # Decoupling local visibility from network fan-out: append locally now,
    # queue the release for network propagation when the lane is ready.
    try:
        from services.mesh.mesh_hashchain import gate_store

        stored_event = gate_store.append(gate_id, gate_event)
        if isinstance(stored_event, dict) and stored_event.get("event_id"):
            gate_event["event_id"] = str(stored_event.get("event_id") or gate_event.get("event_id") or "")
    except Exception:
        logger.exception("Failed to persist gate message locally (gate_store.append)")
        return {"ok": False, "detail": "Failed to record gate message"}

    current_tier = str(
        getattr(request.state, "_private_lane_current_tier", "")
        or getattr(request.state, "_transport_tier", "")
        or "public_degraded"
    )
    return _queue_gate_release(
        current_tier=current_tier,
        gate_id=gate_id,
        payload={
            "gate_id": gate_id,
            "event_id": str(gate_event.get("event_id", "") or ""),
            "event": gate_event,
        },
    )


# â”€â”€â”€ Infonet Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@app.get("/api/mesh/infonet/status")
@limiter.limit("30/minute")
async def infonet_status(request: Request, verify_signatures: bool = False):
    """Get Infonet metadata â€” event counts, head hash, chain size."""
    from services.mesh.mesh_hashchain import infonet
    from services.wormhole_supervisor import get_wormhole_state

    info = infonet.get_info()
    valid, reason = infonet.validate_chain(verify_signatures=verify_signatures)
    try:
        wormhole = get_wormhole_state()
    except Exception:
        wormhole = {"configured": False, "ready": False, "rns_ready": False}
    info["valid"] = valid
    info["validation"] = reason
    info["verify_signatures"] = verify_signatures
    info["private_lane_tier"] = _current_private_lane_tier(wormhole)
    info["private_lane_policy"] = _private_infonet_policy_snapshot(
        current_tier=info["private_lane_tier"]
    )
    info.update(_node_runtime_snapshot())
    return _redact_private_lane_control_fields(
        info,
        authenticated=_scoped_view_authenticated(request, "mesh.audit"),
    )


@app.get("/api/privacy/claims", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_privacy_claims(request: Request, exposure: str = "ordinary"):
    """Authoritative runtime privacy claims used by UI and release checks."""
    from services.wormhole_supervisor import get_wormhole_state

    try:
        wormhole = await asyncio.to_thread(get_wormhole_state)
    except Exception:
        wormhole = {"configured": False, "ready": False, "arti_ready": False, "rns_ready": False}
    current_tier = _current_private_lane_tier(wormhole)
    local_custody = local_custody_status_snapshot()
    privacy_core = _privacy_core_status()
    diagnostic_package = _diagnostic_review_package_snapshot(
        current_tier=current_tier,
        local_custody=local_custody,
        privacy_core=privacy_core,
    )
    result = {
        "ok": True,
        "authoritative_model": "privacy_claims",
        "transport_tier": current_tier,
        "privacy_claims": diagnostic_package.get("claim_surface", {}).get("privacy_claims"),
        "privacy_status": diagnostic_package.get("privacy_status"),
        "strong_claims": diagnostic_package.get("strong_claims"),
        "release_gate": diagnostic_package.get("release_gate"),
    }
    if str(exposure or "").strip().lower() == "diagnostic":
        result.update(
            {
                "rollout_readiness": diagnostic_package.get("rollout_readiness"),
                "rollout_controls": diagnostic_package.get("rollout_controls"),
                "rollout_health": diagnostic_package.get("rollout_health"),
                "claim_surface_sources": diagnostic_package.get("claim_surface_sources"),
                "review_export": diagnostic_package.get("review_export"),
            }
        )
    return result


@app.get("/api/mesh/infonet/merkle")
@limiter.limit("30/minute")
async def infonet_merkle(request: Request):
    """Merkle root for sync comparison."""
    from services.mesh.mesh_hashchain import infonet

    return {
        "merkle_root": infonet.get_merkle_root(),
        "head_hash": infonet.head_hash,
        "count": len(infonet.events),
        "network_id": infonet.get_info().get("network_id"),
    }


@app.get("/api/mesh/infonet/locator")
@limiter.limit("30/minute")
async def infonet_locator(request: Request, limit: int = Query(32, ge=4, le=128)):
    """Block locator for fork-aware sync."""
    from services.mesh.mesh_hashchain import infonet

    locator = infonet.get_locator(max_entries=limit)
    return {
        "locator": locator,
        "head_hash": infonet.head_hash,
        "count": len(infonet.events),
        "network_id": infonet.get_info().get("network_id"),
    }


@app.post("/api/mesh/infonet/sync")
@limiter.limit("30/minute")
@mesh_write_exempt(MeshWriteExemption.PEER_GOSSIP)
async def infonet_sync_post(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
):
    """Fork-aware sync using a block locator."""
    from services.mesh.mesh_hashchain import infonet, GENESIS_HASH

    body = await request.json()
    req_proto = str(body.get("protocol_version", "") or "")
    if req_proto and req_proto != PROTOCOL_VERSION:
        return Response(
            content=json_mod.dumps(
                {
                    "ok": False,
                    "detail": "Unsupported protocol_version",
                    "protocol_version": PROTOCOL_VERSION,
                }
            ),
            status_code=426,
            media_type="application/json",
        )
    locator = body.get("locator", [])
    if not isinstance(locator, list):
        return {"ok": False, "detail": "locator must be a list"}
    expected_head = str(body.get("expected_head", "") or "")
    if expected_head and expected_head != infonet.head_hash:
        return Response(
            content=json_mod.dumps(
                {
                    "ok": False,
                    "detail": "head_hash mismatch",
                    "head_hash": infonet.head_hash,
                    "expected_head": expected_head,
                }
            ),
            status_code=409,
            media_type="application/json",
        )
    if "limit" in body:
        try:
            limit = max(1, min(500, _safe_int(body["limit"], 0)))
        except Exception:
            pass

    matched_hash, start_index, events = infonet.get_events_after_locator(locator, limit=limit)
    forked = False
    if not matched_hash:
        forked = True
    elif matched_hash == GENESIS_HASH and len(locator) > 1:
        forked = True

    # Filter out legacy gate_message events â€” not part of the public sync surface.
    events = [_redact_public_event(e) for e in events if e.get("event_type") != "gate_message"]

    response = {
        "events": events,
        "matched_hash": matched_hash,
        "forked": forked,
        "head_hash": infonet.head_hash,
        "count": len(events),
        "protocol_version": PROTOCOL_VERSION,
    }
    if body.get("include_proofs"):
        proofs = infonet.get_merkle_proofs(start_index, len(events)) if start_index >= 0 else {}
        response.update(
            {
                "merkle_root": proofs.get("root", infonet.get_merkle_root()),
                "merkle_total": proofs.get("total", len(infonet.events)),
                "merkle_start": proofs.get("start", 0),
                "merkle_proofs": proofs.get("proofs", []),
            }
        )
    return response


@app.get("/api/mesh/metrics")
@limiter.limit("30/minute")
async def mesh_metrics(request: Request):
    """Mesh protocol health counters."""
    from services.mesh.mesh_metrics import snapshot

    ok, detail = _check_scoped_auth(request, "mesh.audit")
    if not ok:
        if detail == "insufficient scope":
            raise HTTPException(status_code=403, detail="Forbidden â€” insufficient scope")
        raise HTTPException(status_code=403, detail=detail)
    return snapshot()


@app.get("/api/mesh/rns/status")
@limiter.limit("30/minute")
async def mesh_rns_status(request: Request):
    from services.wormhole_supervisor import get_wormhole_state

    try:
        from services.mesh.mesh_rns import rns_bridge

        status = await asyncio.to_thread(rns_bridge.status)
    except Exception:
        status = {"enabled": False, "ready": False, "configured_peers": 0, "active_peers": 0}
    try:
        wormhole = get_wormhole_state()
    except Exception:
        wormhole = {"configured": False, "ready": False, "rns_ready": False}
    status["private_lane_tier"] = _current_private_lane_tier(wormhole)
    status["private_lane_policy"] = _private_infonet_policy_snapshot(
        current_tier=status["private_lane_tier"]
    )
    return _redact_public_rns_status(
        status,
        authenticated=_scoped_view_authenticated(request, "mesh.audit"),
    )


@app.get("/api/mesh/infonet/sync")
@limiter.limit("30/minute")
async def infonet_sync(
    request: Request,
    after_hash: str = "",
    limit: int = Query(100, ge=1, le=500),
    expected_head: str = "",
    protocol_version: str = "",
):
    """Return events after a given hash (delta sync)."""
    from services.mesh.mesh_hashchain import infonet, GENESIS_HASH

    if protocol_version and protocol_version != PROTOCOL_VERSION:
        return Response(
            content=json_mod.dumps(
                {
                    "ok": False,
                    "detail": "Unsupported protocol_version",
                    "protocol_version": PROTOCOL_VERSION,
                }
            ),
            status_code=426,
            media_type="application/json",
        )
    if expected_head and expected_head != infonet.head_hash:
        return Response(
            content=json_mod.dumps(
                {
                    "ok": False,
                    "detail": "head_hash mismatch",
                    "head_hash": infonet.head_hash,
                    "expected_head": expected_head,
                }
            ),
            status_code=409,
            media_type="application/json",
        )
    base = after_hash or GENESIS_HASH
    events = infonet.get_events_after(base, limit=limit)
    # Filter out legacy gate_message events â€” not part of the public sync surface.
    events = [_redact_public_event(e) for e in events if e.get("event_type") != "gate_message"]
    return {
        "events": events,
        "after_hash": base,
        "count": len(events),
        "protocol_version": PROTOCOL_VERSION,
    }


@app.post("/api/mesh/infonet/ingest", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.ADMIN_CONTROL)
async def infonet_ingest(request: Request):
    """Ingest externally sourced Infonet events (strict verification)."""
    from services.mesh.mesh_hashchain import infonet

    body = await request.json()
    events = body.get("events", [])
    expected_head = str(body.get("expected_head", "") or "")
    if expected_head and expected_head != infonet.head_hash:
        return Response(
            content=json_mod.dumps(
                {
                    "ok": False,
                    "detail": "head_hash mismatch",
                    "head_hash": infonet.head_hash,
                    "expected_head": expected_head,
                }
            ),
            status_code=409,
            media_type="application/json",
        )
    if not isinstance(events, list):
        return {"ok": False, "detail": "events must be a list"}
    if len(events) > 200:
        return {"ok": False, "detail": "Too many events in one ingest batch"}

    result = infonet.ingest_events(events)
    _hydrate_gate_store_from_chain(events)
    return {"ok": True, **result}


@app.post("/api/mesh/infonet/peer-push")
@limiter.limit("30/minute")
@mesh_write_exempt(MeshWriteExemption.PEER_GOSSIP)
async def infonet_peer_push(request: Request):
    """Accept pushed Infonet events from relay peers (HMAC-authenticated)."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 524_288:
                return Response(
                    content='{"ok":false,"detail":"Request body too large (max 512KB)"}',
                    status_code=413,
                    media_type="application/json",
                )
        except (ValueError, TypeError):
            pass
    from services.mesh.mesh_hashchain import infonet

    body_bytes = await request.body()
    if not _verify_peer_push_hmac(request, body_bytes):
        return Response(
            content='{"ok":false,"detail":"Invalid or missing peer HMAC"}',
            status_code=403,
            media_type="application/json",
        )

    body = json_mod.loads(body_bytes or b"{}")
    events = body.get("events", [])
    if not isinstance(events, list):
        return {"ok": False, "detail": "events must be a list"}
    if len(events) > 50:
        return {"ok": False, "detail": "Too many events in one push (max 50)"}
    if not events:
        return {"ok": True, "accepted": 0, "duplicates": 0, "rejected": []}

    result = infonet.ingest_events(events)
    _hydrate_gate_store_from_chain(events)
    return {"ok": True, **result}


@app.post("/api/mesh/gate/peer-push")
@limiter.limit("30/minute")
@mesh_write_exempt(MeshWriteExemption.PEER_GOSSIP)
async def gate_peer_push(request: Request):
    """Accept pushed gate events from relay peers (private plane)."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 524_288:
                return Response(
                    content='{"ok":false,"detail":"Request body too large"}',
                    status_code=413,
                    media_type="application/json",
                )
        except (ValueError, TypeError):
            pass

    from services.mesh.mesh_hashchain import gate_store

    body_bytes = await request.body()
    if not _verify_peer_push_hmac(request, body_bytes):
        return Response(
            content='{"ok":false,"detail":"Invalid or missing peer HMAC"}',
            status_code=403,
            media_type="application/json",
        )

    body = json_mod.loads(body_bytes or b"{}")
    events = body.get("events", [])
    if not isinstance(events, list):
        return {"ok": False, "detail": "events must be a list"}
    if len(events) > 50:
        return {"ok": False, "detail": "Too many events (max 50)"}
    if not events:
        return {"ok": True, "accepted": 0, "duplicates": 0}

    from services.mesh.mesh_hashchain import resolve_gate_wire_ref

    grouped_events: dict[str, list[dict[str, Any]]] = {}
    for evt in events:
        evt_dict = evt if isinstance(evt, dict) else {}
        payload = evt_dict.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        clean_event = {
            "event_id": str(evt_dict.get("event_id", "") or ""),
            "event_type": "gate_message",
            "timestamp": evt_dict.get("timestamp", 0),
            "node_id": str(evt_dict.get("node_id", "") or evt_dict.get("sender_id", "") or ""),
            "sequence": evt_dict.get("sequence", 0),
            "signature": str(evt_dict.get("signature", "") or ""),
            "public_key": str(evt_dict.get("public_key", "") or ""),
            "public_key_algo": str(evt_dict.get("public_key_algo", "") or ""),
            "protocol_version": str(evt_dict.get("protocol_version", "") or ""),
            "payload": {
                "ciphertext": str(payload.get("ciphertext", "") or ""),
                "format": str(payload.get("format", "") or ""),
                "nonce": str(payload.get("nonce", "") or ""),
                "sender_ref": str(payload.get("sender_ref", "") or ""),
            },
        }
        epoch = _safe_int(payload.get("epoch", 0) or 0)
        if epoch > 0:
            clean_event["payload"]["epoch"] = epoch
        # Preserve envelope metadata required for cross-node decryption and
        # authenticated threading.
        envelope_hash_val = str(payload.get("envelope_hash", "") or "").strip()
        gate_envelope_val = str(payload.get("gate_envelope", "") or "").strip()
        reply_to_val = str(payload.get("reply_to", "") or "").strip()
        if envelope_hash_val:
            clean_event["payload"]["envelope_hash"] = envelope_hash_val
        if gate_envelope_val:
            clean_event["payload"]["gate_envelope"] = gate_envelope_val
        transport_lock_val = str(payload.get("transport_lock", "") or "").strip().lower()
        if transport_lock_val:
            clean_event["payload"]["transport_lock"] = transport_lock_val
        if reply_to_val:
            clean_event["payload"]["reply_to"] = reply_to_val
        event_gate_id = str(payload.get("gate", "") or evt_dict.get("gate", "") or "").strip().lower()
        if not event_gate_id:
            event_gate_id = resolve_gate_wire_ref(
                str(payload.get("gate_ref", "") or evt_dict.get("gate_ref", "") or ""),
                clean_event,
            )
        if not event_gate_id:
            return {"ok": False, "detail": "gate resolution failed"}
        final_payload: dict[str, Any] = {
            "gate": event_gate_id,
            "ciphertext": clean_event["payload"]["ciphertext"],
            "format": clean_event["payload"]["format"],
            "nonce": clean_event["payload"]["nonce"],
            "sender_ref": clean_event["payload"]["sender_ref"],
        }
        if epoch > 0:
            final_payload["epoch"] = epoch
        if clean_event["payload"].get("envelope_hash"):
            final_payload["envelope_hash"] = clean_event["payload"]["envelope_hash"]
        if clean_event["payload"].get("gate_envelope"):
            final_payload["gate_envelope"] = clean_event["payload"]["gate_envelope"]
        if clean_event["payload"].get("transport_lock"):
            final_payload["transport_lock"] = clean_event["payload"]["transport_lock"]
        if clean_event["payload"].get("reply_to"):
            final_payload["reply_to"] = clean_event["payload"]["reply_to"]
        grouped_events.setdefault(event_gate_id, []).append(
            {
                "event_id": clean_event["event_id"],
                "event_type": "gate_message",
                "timestamp": clean_event["timestamp"],
                "node_id": clean_event["node_id"],
                "sequence": clean_event["sequence"],
                "signature": clean_event["signature"],
                "public_key": clean_event["public_key"],
                "public_key_algo": clean_event["public_key_algo"],
                "protocol_version": clean_event["protocol_version"],
                "payload": final_payload,
            }
        )

    accepted = 0
    duplicates = 0
    rejected = 0
    for event_gate_id, items in grouped_events.items():
        result = gate_store.ingest_peer_events(event_gate_id, items)
        a = int(result.get("accepted", 0) or 0)
        accepted += a
        duplicates += int(result.get("duplicates", 0) or 0)
        rejected += int(result.get("rejected", 0) or 0)
    return {"ok": True, "accepted": accepted, "duplicates": duplicates, "rejected": rejected}


@app.post("/api/mesh/gate/peer-pull")
@limiter.limit("30/minute")
@mesh_write_exempt(MeshWriteExemption.PEER_GOSSIP)
async def gate_peer_pull(request: Request):
    """Return gate events a peer is missing (HMAC-authenticated pull sync).

    Body: {"gate_id": "...", "after_count": N}
    Returns up to 50 events after the caller's known count for that gate.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 65_536:
                return Response(
                    content='{"ok":false,"detail":"Request body too large"}',
                    status_code=413,
                    media_type="application/json",
                )
        except (ValueError, TypeError):
            pass

    from services.mesh.mesh_hashchain import gate_store

    body_bytes = await request.body()
    if not _verify_peer_push_hmac(request, body_bytes):
        return Response(
            content='{"ok":false,"detail":"Invalid or missing peer HMAC"}',
            status_code=403,
            media_type="application/json",
        )

    body = json_mod.loads(body_bytes or b"{}")
    gate_id = str(body.get("gate_id", "") or "").strip().lower()
    after_count = _safe_int(body.get("after_count", 0) or 0)

    if not gate_id:
        # If no gate_id, return all known gate IDs with their event counts
        # so the puller knows which gates to sync.
        gate_ids = gate_store.known_gate_ids()
        gate_counts: dict[str, int] = {}
        for gid in gate_ids:
            with gate_store._lock:
                gate_counts[gid] = len(gate_store._gates.get(gid, []))
        return {"ok": True, "gates": gate_counts}

    with gate_store._lock:
        all_events = list(gate_store._gates.get(gate_id, []))
    total = len(all_events)
    if after_count >= total:
        return {"ok": True, "events": [], "total": total, "gate_id": gate_id}

    batch = all_events[after_count : after_count + _PEER_PUSH_BATCH_SIZE]
    return {"ok": True, "events": batch, "total": total, "gate_id": gate_id}


# ---------------------------------------------------------------------------
# Peer Management API â€” operator endpoints for adding / removing / listing
# peers without editing peer_store.json by hand.
# ---------------------------------------------------------------------------


@app.get("/api/mesh/peers", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def list_peers(request: Request, bucket: str = Query(None)):
    """List all peers (or filter by bucket: sync, push, bootstrap)."""
    from services.mesh.mesh_peer_store import DEFAULT_PEER_STORE_PATH, PeerStore

    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception as exc:
        return {"ok": False, "detail": f"Failed to load peer store: {exc}"}

    if bucket:
        records = store.records_for_bucket(bucket)
    else:
        records = store.records()

    return {
        "ok": True,
        "count": len(records),
        "peers": [r.to_dict() for r in records],
    }


@app.post("/api/mesh/peers", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.LOCAL_OPERATOR_ONLY)
async def add_peer(request: Request):
    """Add a peer to the store. Body: {peer_url, transport?, label?, role?, buckets?[]}."""
    from services.mesh.mesh_crypto import normalize_peer_url
    from services.mesh.mesh_peer_store import (
        DEFAULT_PEER_STORE_PATH,
        PeerStore,
        PeerStoreError,
        make_push_peer_record,
        make_sync_peer_record,
    )
    from services.mesh.mesh_router import peer_transport_kind

    body = await request.json()
    peer_url_raw = str(body.get("peer_url", "") or "").strip()
    if not peer_url_raw:
        return {"ok": False, "detail": "peer_url is required"}

    peer_url = normalize_peer_url(peer_url_raw)
    if not peer_url:
        return {"ok": False, "detail": "Invalid peer_url"}

    transport = str(body.get("transport", "") or "").strip().lower()
    if not transport:
        transport = peer_transport_kind(peer_url)
    if not transport:
        return {"ok": False, "detail": "Cannot determine transport for peer_url â€” provide transport explicitly"}

    label = str(body.get("label", "") or "").strip()
    role = str(body.get("role", "") or "").strip().lower() or "relay"
    buckets = body.get("buckets", ["sync", "push"])
    if isinstance(buckets, str):
        buckets = [buckets]
    if not isinstance(buckets, list):
        buckets = ["sync", "push"]

    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception:
        store = PeerStore(DEFAULT_PEER_STORE_PATH)

    added: list[str] = []
    try:
        for b in buckets:
            b = str(b).strip().lower()
            if b == "sync":
                store.upsert(make_sync_peer_record(peer_url=peer_url, transport=transport, role=role, label=label))
                added.append("sync")
            elif b == "push":
                store.upsert(make_push_peer_record(peer_url=peer_url, transport=transport, role=role, label=label))
                added.append("push")
        store.save()
    except PeerStoreError as exc:
        return {"ok": False, "detail": str(exc)}

    return {"ok": True, "peer_url": peer_url, "buckets": added}


@app.delete("/api/mesh/peers", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.LOCAL_OPERATOR_ONLY)
async def remove_peer(request: Request):
    """Remove a peer. Body: {peer_url, bucket?}. If bucket omitted, removes from all buckets."""
    from services.mesh.mesh_crypto import normalize_peer_url
    from services.mesh.mesh_peer_store import DEFAULT_PEER_STORE_PATH, PeerStore

    body = await request.json()
    peer_url_raw = str(body.get("peer_url", "") or "").strip()
    if not peer_url_raw:
        return {"ok": False, "detail": "peer_url is required"}

    peer_url = normalize_peer_url(peer_url_raw)
    if not peer_url:
        return {"ok": False, "detail": "Invalid peer_url"}

    bucket_filter = str(body.get("bucket", "") or "").strip().lower()

    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception:
        return {"ok": False, "detail": "Failed to load peer store"}

    removed: list[str] = []
    for b in ["bootstrap", "sync", "push"]:
        if bucket_filter and b != bucket_filter:
            continue
        key = f"{b}:{peer_url}"
        if key in store._records:
            del store._records[key]
            removed.append(b)

    if not removed:
        return {"ok": False, "detail": "Peer not found in any bucket"}

    store.save()
    return {"ok": True, "peer_url": peer_url, "removed_from": removed}


@app.patch("/api/mesh/peers", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.LOCAL_OPERATOR_ONLY)
async def toggle_peer(request: Request):
    """Enable or disable a peer. Body: {peer_url, bucket, enabled: bool}."""
    from services.mesh.mesh_crypto import normalize_peer_url
    from services.mesh.mesh_peer_store import DEFAULT_PEER_STORE_PATH, PeerRecord, PeerStore

    body = await request.json()
    peer_url_raw = str(body.get("peer_url", "") or "").strip()
    bucket = str(body.get("bucket", "") or "").strip().lower()
    enabled = body.get("enabled")

    if not peer_url_raw:
        return {"ok": False, "detail": "peer_url is required"}
    if not bucket:
        return {"ok": False, "detail": "bucket is required"}
    if enabled is None:
        return {"ok": False, "detail": "enabled (true/false) is required"}

    peer_url = normalize_peer_url(peer_url_raw)
    if not peer_url:
        return {"ok": False, "detail": "Invalid peer_url"}

    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception:
        return {"ok": False, "detail": "Failed to load peer store"}

    key = f"{bucket}:{peer_url}"
    record = store._records.get(key)
    if not record:
        return {"ok": False, "detail": f"Peer not found in {bucket} bucket"}

    updated = PeerRecord(**{**record.to_dict(), "enabled": bool(enabled), "updated_at": int(time.time())})
    store._records[key] = updated
    store.save()

    return {"ok": True, "peer_url": peer_url, "bucket": bucket, "enabled": bool(enabled)}


@app.put("/api/mesh/gate/{gate_id}/envelope_policy")
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.ADMIN_CONTROL)
async def set_gate_envelope_policy(request: Request, gate_id: str):
    """Set the envelope_policy for a gate. Requires gate admin scope."""
    ok, detail = _check_scoped_auth(request, "gate")
    if not ok:
        return Response(
            content='{"ok":false,"detail":"Gate admin scope required"}',
            status_code=403,
            media_type="application/json",
        )
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "detail": "Invalid JSON body"}
    policy = str(body.get("envelope_policy", "") or "").strip()
    acknowledge_recovery_risk = bool(body.get("acknowledge_recovery_risk", False))
    from services.mesh.mesh_reputation import gate_manager, VALID_ENVELOPE_POLICIES
    if policy not in VALID_ENVELOPE_POLICIES:
        return {"ok": False, "detail": f"Invalid policy: must be one of {VALID_ENVELOPE_POLICIES}"}
    success, msg = gate_manager.set_envelope_policy(
        gate_id,
        policy,
        acknowledge_recovery_risk=acknowledge_recovery_risk,
    )
    return {"ok": success, "detail": msg}


@app.put("/api/mesh/gate/{gate_id}/legacy_envelope_fallback")
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.ADMIN_CONTROL)
async def set_gate_legacy_envelope_fallback(request: Request, gate_id: str):
    """Set legacy_envelope_fallback for a gate. Requires gate admin scope."""
    ok, detail = _check_scoped_auth(request, "gate")
    if not ok:
        return Response(
            content='{"ok":false,"detail":"Gate admin scope required"}',
            status_code=403,
            media_type="application/json",
        )
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "detail": "Invalid JSON body"}
    raw = body.get("legacy_envelope_fallback")
    acknowledge_legacy_risk = body.get("acknowledge_legacy_risk", False)
    if raw is None or not isinstance(raw, bool):
        return {"ok": False, "detail": "legacy_envelope_fallback must be a boolean"}
    if acknowledge_legacy_risk is not None and not isinstance(acknowledge_legacy_risk, bool):
        return {"ok": False, "detail": "acknowledge_legacy_risk must be a boolean"}
    from services.mesh.mesh_reputation import gate_manager
    success, msg = gate_manager.set_legacy_envelope_fallback(
        gate_id,
        raw,
        acknowledge_legacy_risk=bool(acknowledge_legacy_risk),
    )
    return {"ok": success, "detail": msg}


@app.get("/api/mesh/gate/{gate_id}/messages")
@limiter.limit("60/minute")
async def gate_messages(
    request: Request,
    gate_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Get encrypted gate messages from private store (newest first). Requires gate membership."""
    access = _verify_gate_access(request, gate_id)
    if not access:
        return await _private_plane_refusal_response(
            request,
            status_code=403,
            payload=_private_plane_access_denied_payload(),
        )
    return _build_gate_message_response(gate_id, access, limit=limit, offset=offset)


def _build_gate_message_response(
    gate_id: str,
    access: str,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    from services.mesh.mesh_hashchain import gate_store
    from services.mesh.mesh_reputation import gate_manager

    raw_messages, cursor = gate_store.get_messages_with_cursor(gate_id, limit=limit, offset=offset)
    safe_messages = [_strip_gate_for_access(m, access) for m in raw_messages]
    if gate_id and not safe_messages:
        gate_meta = gate_manager.get_gate(gate_id)
        if gate_meta:
            welcome_text = str(gate_meta.get("welcome") or gate_meta.get("description") or "").strip()
            if welcome_text:
                safe_messages = [
                    {
                        "event_id": f"seed_{gate_id}_welcome",
                        "event_type": "gate_notice",
                        "node_id": "!sb_gate",
                        "message": welcome_text,
                        "gate": gate_id,
                        "timestamp": int(gate_meta.get("created_at") or time.time()),
                        "sequence": 0,
                        "ephemeral": False,
                        "system_seed": True,
                        "fixed_gate": bool(gate_meta.get("fixed", False)),
                    }
                ]
    return {"messages": safe_messages, "count": len(safe_messages), "gate": gate_id, "cursor": cursor}


@app.get("/api/mesh/infonet/messages")
@limiter.limit("60/minute")
async def infonet_messages(
    request: Request,
    gate: str = "",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Browse messages on the Infonet (newest first). Optional gate filter."""
    from services.mesh.mesh_hashchain import infonet

    if gate:
        access = _verify_gate_access(request, gate)
        if not access:
            return await _private_plane_refusal_response(
                request,
                status_code=403,
                payload=_private_plane_access_denied_payload(),
            )
        return _build_gate_message_response(gate, access, limit=limit, offset=offset)
    else:
        messages = infonet.get_messages(gate_id="", limit=limit, offset=offset)
        messages = [m for m in messages if m.get("event_type") != "gate_message"]
        messages = [_redact_public_event(m) for m in messages]
    return {"messages": messages, "count": len(messages), "gate": gate or "all", "cursor": 0}


@app.get("/api/mesh/infonet/messages/wait")
@limiter.limit("60/minute")
async def infonet_messages_wait(
    request: Request,
    gate: str = "",
    after: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    timeout_ms: int = Query(25_000, ge=1_000, le=90_000),
):
    """Wait for gate message changes, then return the latest gate view."""
    gate_id = str(gate or "").strip().lower()
    if not gate_id:
        return Response(
            content='{"ok":false,"detail":"gate required"}',
            status_code=400,
            media_type="application/json",
        )
    access = _verify_gate_access(request, gate_id)
    if not access:
        return await _private_plane_refusal_response(
            request,
            status_code=403,
            payload=_private_plane_access_denied_payload(),
        )
    from services.mesh.mesh_hashchain import gate_store

    changed, _cursor = await asyncio.to_thread(
        gate_store.wait_for_gate_change,
        gate_id,
        after,
        timeout_ms / 1000.0,
    )
    payload = _build_gate_message_response(gate_id, access, limit=limit, offset=0)
    payload["changed"] = bool(changed)
    return payload


@app.get("/api/mesh/infonet/event/{event_id}")
@limiter.limit("60/minute")
async def infonet_event(request: Request, event_id: str):
    """Look up a single Infonet event by ID."""
    from services.mesh.mesh_hashchain import gate_store, infonet

    evt = infonet.get_event(event_id)
    if not evt:
        evt = gate_store.get_event(event_id)
        if evt:
            gate_id = str(evt.get("payload", {}).get("gate", "") or evt.get("gate", "") or "").strip()
            access = _verify_gate_access(request, gate_id) if gate_id else ""
            if not gate_id or not access:
                return await _private_plane_refusal_response(
                    request,
                    status_code=403,
                    payload=_private_plane_access_denied_payload(),
                )
            return _strip_gate_for_access(evt, access)
        return {"ok": False, "detail": "Event not found"}
    if evt.get("event_type") == "gate_message":
        gate_id = str(evt.get("payload", {}).get("gate", "") or evt.get("gate", "") or "").strip()
        access = _verify_gate_access(request, gate_id) if gate_id else ""
        if not gate_id or not access:
            return await _private_plane_refusal_response(
                request,
                status_code=403,
                payload=_private_plane_access_denied_payload(),
            )
        return _strip_gate_for_access(evt, access)
    return _redact_public_event(infonet.decorate_event(evt))


@app.get("/api/mesh/infonet/node/{node_id}")
@limiter.limit("30/minute")
async def infonet_node_events(
    request: Request,
    node_id: str,
    limit: int = Query(20, ge=1, le=100),
):
    """Get recent Infonet events by a specific node."""
    from services.mesh.mesh_hashchain import infonet

    events = infonet.get_events_by_node(node_id, limit=limit)
    events = [e for e in events if e.get("event_type") != "gate_message"]
    events = [_redact_public_event(e) for e in infonet.decorate_events(events)]
    events = _redact_public_node_history(
        events,
        authenticated=_scoped_view_authenticated(request, "mesh.audit"),
    )
    return {"events": events, "count": len(events), "node_id": node_id}


@app.get("/api/mesh/infonet/events")
@limiter.limit("30/minute")
async def infonet_events_by_type(
    request: Request,
    event_type: str = "",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Get recent Infonet events, optionally filtered by type."""
    from services.mesh.mesh_hashchain import infonet

    if event_type:
        events = infonet.get_events_by_type(event_type, limit=limit, offset=offset)
    else:
        events = list(reversed(infonet.events))
        events = events[offset : offset + limit]
    events = [e for e in events if e.get("event_type") != "gate_message"]
    events = [_redact_public_event(e) for e in infonet.decorate_events(events)]
    return {
        "events": events,
        "count": len(events),
        "event_type": event_type or "all",
    }


# â”€â”€â”€ Oracle Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@app.post("/api/mesh/oracle/predict")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.ORACLE_PREDICT)
async def oracle_predict(request: Request):
    """Place a prediction on a market outcome. FINAL decision.

    Body: {node_id, market_title, side, stake_amount?: number}
    - stake_amount = 0 or omitted â†’ FREE PICK (earn rep if correct)
    - stake_amount > 0 â†’ STAKE REP (risk rep, split loser pool if correct)
    - side can be "yes"/"no" or an outcome name for multi-outcome markets
    """
    from services.mesh.mesh_oracle import oracle_ledger

    body = _signed_body(request)
    node_id = body.get("node_id", "")
    market_title = body.get("market_title", "")
    side = body.get("side", "")
    stake_amount = _safe_float(body.get("stake_amount", 0))
    public_key = body.get("public_key", "")
    public_key_algo = body.get("public_key_algo", "")
    signature = body.get("signature", "")
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "")

    if not node_id or not market_title or not side:
        return {"ok": False, "detail": "Missing node_id, market_title, or side"}

    prediction_payload = {
        "market_title": market_title,
        "side": side,
        "stake_amount": stake_amount,
    }
    try:
        from services.mesh.mesh_reputation import reputation_ledger

        reputation_ledger.register_node(node_id, public_key, public_key_algo)
    except Exception:
        pass

    # Get current market probability from live data
    data = get_latest_data()
    markets = data.get("prediction_markets", [])
    matched = None
    for m in markets:
        if m.get("title", "").lower() == market_title.lower():
            matched = m
            break
    # Fuzzy fallback â€” partial match
    if not matched:
        for m in markets:
            if market_title.lower() in m.get("title", "").lower():
                matched = m
                break

    if not matched:
        return {"ok": False, "detail": f"Market '{market_title}' not found in active markets."}

    # Determine probability for the chosen side
    # For binary yes/no, use consensus_pct. For multi-outcome, find the outcome's pct.
    probability = 50.0
    side_lower = side.lower()
    outcomes = matched.get("outcomes", [])
    if outcomes:
        # Multi-outcome: find the specific outcome's probability
        for o in outcomes:
            if o.get("name", "").lower() == side_lower:
                probability = float(o.get("pct", 50))
                break
    else:
        # Binary market
        consensus = matched.get("consensus_pct")
        if consensus is None:
            consensus = matched.get("polymarket_pct") or matched.get("kalshi_pct") or 50
        probability = float(consensus)
        if side_lower == "no":
            probability = 100.0 - probability

    if stake_amount > 0:
        # STAKED prediction â€” risk rep for bigger reward
        ok, detail = oracle_ledger.place_market_stake(
            node_id, matched["title"], side, stake_amount, probability
        )
        mode = "staked"
    else:
        # FREE prediction â€” no rep risked
        ok, detail = oracle_ledger.place_prediction(node_id, matched["title"], side, probability)
        mode = "free"

    # Record on Infonet
    if ok:
        try:
            from services.mesh.mesh_hashchain import infonet

            normalized_payload = normalize_payload("prediction", prediction_payload)
            infonet.append(
                event_type="prediction",
                node_id=node_id,
                payload=normalized_payload,
                signature=signature,
                sequence=sequence,
                public_key=public_key,
                public_key_algo=public_key_algo,
                protocol_version=protocol_version,
            )
        except Exception:
            pass

    return {"ok": ok, "detail": detail, "probability": probability, "mode": mode}


@app.get("/api/mesh/oracle/markets")
@limiter.limit("30/minute")
async def oracle_markets(request: Request):
    """List active prediction markets, categorized with top 10 per category.
    Includes network consensus data (picks + staked rep per side)."""
    from collections import defaultdict
    from services.mesh.mesh_oracle import oracle_ledger

    data = get_latest_data()
    markets = data.get("prediction_markets", [])

    # Get consensus for all active markets (bulk)
    all_consensus = oracle_ledger.get_all_market_consensus()

    by_category = defaultdict(list)
    for m in markets:
        by_category[m.get("category", "NEWS")].append(m)

    _fields = (
        "title",
        "consensus_pct",
        "polymarket_pct",
        "kalshi_pct",
        "volume",
        "volume_24h",
        "end_date",
        "description",
        "category",
        "sources",
        "slug",
        "kalshi_ticker",
        "outcomes",
        "kalshi_volume",
    )
    categories = {}
    cat_totals = {}
    for cat in ["POLITICS", "CONFLICT", "NEWS", "FINANCE", "CRYPTO", "SPORTS"]:
        all_cat = sorted(
            by_category.get(cat, []),
            key=lambda x: x.get("volume", 0) or 0,
            reverse=True,
        )
        cat_totals[cat] = len(all_cat)
        cat_list = []
        for m in all_cat[:10]:
            entry = {k: m.get(k) for k in _fields}
            entry["consensus"] = all_consensus.get(m.get("title", ""), {})
            cat_list.append(entry)
        categories[cat] = cat_list

    return {"categories": categories, "total_count": len(markets), "cat_totals": cat_totals}


@app.get("/api/mesh/oracle/search")
@limiter.limit("20/minute")
async def oracle_search(request: Request, q: str = "", limit: int = 20, offset: int = 0):
    """Search prediction markets across Polymarket and Kalshi provider APIs."""
    if not q or len(q) < 2:
        return {"results": [], "query": q, "count": 0, "offset": offset, "has_more": False}

    from services.fetchers.prediction_markets import search_kalshi_direct, search_polymarket_direct

    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))
    provider_limit = offset + limit + 25

    # Search both providers directly. Kalshi does not expose a reliable public
    # text-search parameter, so the fetcher performs bounded cursor scans.
    poly_results = search_polymarket_direct(q, limit=provider_limit, offset=0)
    kalshi_results = search_kalshi_direct(q, limit=provider_limit, offset=0)

    # Also search cached merged data so cross-provider consensus entries win.
    data = get_latest_data()
    markets = data.get("prediction_markets", [])
    q_lower = q.lower()
    cached_matches = [m for m in markets if q_lower in m.get("title", "").lower()]

    # Deduplicate: prefer cached merged rows, then provider-native rows.
    seen_titles = set()
    combined = []
    for m in cached_matches:
        seen_titles.add(m["title"].lower())
        combined.append(m)
    for m in [*poly_results, *kalshi_results]:
        if m["title"].lower() not in seen_titles:
            seen_titles.add(m["title"].lower())
            combined.append(m)

    # Sort by volume descending
    combined.sort(key=lambda x: x.get("volume", 0) or 0, reverse=True)

    _fields = (
        "title",
        "consensus_pct",
        "polymarket_pct",
        "kalshi_pct",
        "volume",
        "volume_24h",
        "end_date",
        "description",
        "category",
        "sources",
        "slug",
        "kalshi_ticker",
        "outcomes",
        "kalshi_volume",
    )
    page = combined[offset : offset + limit]
    results = [{k: m.get(k) for k in _fields} for m in page]
    return {
        "results": results,
        "query": q,
        "count": len(results),
        "offset": offset,
        "has_more": len(combined) > offset + limit,
        "total_seen": len(combined),
    }


@app.get("/api/mesh/oracle/markets/more")
@limiter.limit("30/minute")
async def oracle_markets_more(
    request: Request, category: str = "NEWS", offset: int = 0, limit: int = 10
):
    """Load more markets for a specific category (paginated)."""
    category = (category or "NEWS").upper()
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 10), 100))
    data = get_latest_data()
    markets = data.get("prediction_markets", [])
    cat_markets = sorted(
        [m for m in markets if category == "ALL" or m.get("category") == category],
        key=lambda x: x.get("volume", 0) or 0,
        reverse=True,
    )

    page = cat_markets[offset : offset + limit]
    _fields = (
        "title",
        "consensus_pct",
        "polymarket_pct",
        "kalshi_pct",
        "volume",
        "volume_24h",
        "end_date",
        "description",
        "category",
        "sources",
        "slug",
        "kalshi_ticker",
        "outcomes",
        "kalshi_volume",
    )
    results = [{k: m.get(k) for k in _fields} for m in page]
    return {
        "markets": results,
        "category": category,
        "offset": offset,
        "has_more": offset + limit < len(cat_markets),
        "total": len(cat_markets),
    }


@app.post("/api/mesh/oracle/resolve")
@limiter.limit("5/minute")
@mesh_write_exempt(MeshWriteExemption.ADMIN_CONTROL)
async def oracle_resolve(request: Request):
    """Resolve a prediction market (admin/agent action).

    Body: {market_title, outcome: "yes"|"no" or any outcome name}
    """
    from services.mesh.mesh_oracle import oracle_ledger

    body = await request.json()
    market_title = body.get("market_title", "")
    outcome = body.get("outcome", "")

    if not market_title or not outcome:
        return {"ok": False, "detail": "Need market_title and outcome"}

    # Resolve free predictions
    winners, losers = oracle_ledger.resolve_market(market_title, outcome)
    # Resolve market stakes
    stake_result = oracle_ledger.resolve_market_stakes(market_title, outcome)

    return {
        "ok": True,
        "detail": f"Resolved: {winners} free winners, {losers} free losers, "
        f"{stake_result.get('winners', 0)} stake winners, {stake_result.get('losers', 0)} stake losers",
        "free": {"winners": winners, "losers": losers},
        "stakes": stake_result,
    }


@app.get("/api/mesh/oracle/consensus")
@limiter.limit("30/minute")
async def oracle_consensus(request: Request, market_title: str = ""):
    """Get network consensus for a market â€” picks + staked rep per side."""
    from services.mesh.mesh_oracle import oracle_ledger

    if not market_title:
        return {"error": "market_title required"}
    return oracle_ledger.get_market_consensus(market_title)


@app.post("/api/mesh/oracle/stake")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.ORACLE_STAKE)
async def oracle_stake(request: Request):
    """Stake oracle rep on a post's truthfulness.

    Body: {staker_id, message_id, poster_id, side: "truth"|"false", amount, duration_days: 1-7}
    """
    from services.mesh.mesh_oracle import oracle_ledger

    body = _signed_body(request)
    staker_id = body.get("staker_id", "")
    message_id = body.get("message_id", "")
    poster_id = body.get("poster_id", "")
    side = body.get("side", "").lower()
    amount = _safe_float(body.get("amount", 0))
    duration_days = _safe_int(body.get("duration_days", 1), 1)
    public_key = body.get("public_key", "")
    public_key_algo = body.get("public_key_algo", "")
    signature = body.get("signature", "")
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "")

    if not staker_id or not message_id or not side:
        return {"ok": False, "detail": "Missing staker_id, message_id, or side"}

    stake_payload = {
        "message_id": message_id,
        "poster_id": poster_id,
        "side": side,
        "amount": amount,
        "duration_days": duration_days,
    }
    try:
        from services.mesh.mesh_reputation import reputation_ledger

        reputation_ledger.register_node(staker_id, public_key, public_key_algo)
    except Exception:
        pass

    ok, detail = oracle_ledger.place_stake(
        staker_id, message_id, poster_id, side, amount, duration_days
    )

    # Record on Infonet
    if ok:
        try:
            from services.mesh.mesh_hashchain import infonet

            normalized_payload = normalize_payload("stake", stake_payload)
            infonet.append(
                event_type="stake",
                node_id=staker_id,
                payload=normalized_payload,
                signature=signature,
                sequence=sequence,
                public_key=public_key,
                public_key_algo=public_key_algo,
                protocol_version=protocol_version,
            )
        except Exception:
            pass

    return {"ok": ok, "detail": detail}


@app.get("/api/mesh/oracle/stakes/{message_id}")
@limiter.limit("30/minute")
async def oracle_stakes_for_message(request: Request, message_id: str):
    """Get all oracle stakes on a message."""
    from services.mesh.mesh_oracle import oracle_ledger

    return _redact_public_oracle_stakes(
        oracle_ledger.get_stakes_for_message(message_id),
        authenticated=_scoped_view_authenticated(request, "mesh.audit"),
    )


@app.get("/api/mesh/oracle/profile")
@limiter.limit("30/minute")
async def oracle_profile(request: Request, node_id: str = ""):
    """Get full oracle profile â€” rep, prediction history, win rate, farming score."""
    from services.mesh.mesh_oracle import oracle_ledger

    if not node_id:
        return {"ok": False, "detail": "Provide ?node_id=xxx"}
    profile = oracle_ledger.get_oracle_profile(node_id)
    return _redact_public_oracle_profile(
        profile,
        authenticated=_scoped_view_authenticated(request, "mesh.audit"),
    )


@app.get("/api/mesh/oracle/predictions")
@limiter.limit("30/minute")
async def oracle_predictions(request: Request, node_id: str = ""):
    """Get a node's active (unresolved) predictions."""
    from services.mesh.mesh_oracle import oracle_ledger

    if not node_id:
        return {"ok": False, "detail": "Provide ?node_id=xxx"}
    active_predictions = oracle_ledger.get_active_predictions(node_id)
    return _redact_public_oracle_predictions(
        active_predictions,
        authenticated=_scoped_view_authenticated(request, "mesh.audit"),
    )


@app.post("/api/mesh/oracle/resolve-stakes")
@limiter.limit("5/minute")
@mesh_write_exempt(MeshWriteExemption.ADMIN_CONTROL)
async def oracle_resolve_stakes(request: Request):
    """Resolve all expired stake contests. Can be called periodically or manually."""
    from services.mesh.mesh_oracle import oracle_ledger

    resolutions = oracle_ledger.resolve_expired_stakes()
    return {"ok": True, "resolutions": resolutions, "count": len(resolutions)}


# â”€â”€â”€ Encrypted DM Relay (Dead Drop) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _secure_dm_enabled() -> bool:
    return bool(get_settings().MESH_DM_SECURE_MODE)


def _legacy_dm_get_allowed() -> bool:
    return bool(legacy_dm_get_override_active())


def _legacy_dm1_allowed() -> bool:
    return bool(legacy_dm1_override_active())


def _rns_private_dm_ready() -> bool:
    try:
        from services.mesh.mesh_rns import rns_bridge

        return bool(rns_bridge.enabled()) and bool(rns_bridge.status().get("private_dm_direct_ready"))
    except Exception:
        return False


def _anonymous_dm_hidden_transport_enforced() -> bool:
    state = _anonymous_mode_state()
    return bool(state.get("enabled")) and bool(state.get("ready"))


def _anonymous_dm_hidden_transport_requested() -> bool:
    """User has asked for anonymous mode, regardless of whether hidden transport
    is *ready* yet.

    Use this (not the ``_enforced`` variant) for *protective* logic that must
    keep stated privacy intent honored during warmup — e.g., skipping direct
    RNS metadata lookups. ``_enforced`` is for claim/telemetry paths that
    report what is currently being honored.
    """
    return bool(_anonymous_mode_state().get("enabled"))


def _high_privacy_profile_enabled() -> bool:
    try:
        from services.wormhole_settings import read_wormhole_settings

        settings = read_wormhole_settings()
        return str(settings.get("privacy_profile", "default") or "default").lower() == "high"
    except Exception:
        return False


async def _maybe_apply_dm_relay_jitter() -> None:
    # Hardening Rec #7b: apply a modest baseline jitter even in the default
    # privacy profile so DM send timing is not trivially fingerprintable.
    # "high" profile keeps the original 50-500 ms window; default profile
    # adds 0-20 ms which is imperceptible to users but disrupts fine-grained
    # timing correlation across concurrent requests.
    if _high_privacy_profile_enabled():
        await asyncio.sleep((50 + secrets.randbelow(451)) / 1000.0)
        return
    await asyncio.sleep(secrets.randbelow(21) / 1000.0)


async def _maybe_apply_dm_poll_jitter() -> None:
    # Poll/count endpoints are activity probes. Keep default latency nearly
    # invisible, but make high-privacy polling harder to align with network
    # observations and mailbox state changes.
    if _high_privacy_profile_enabled():
        await asyncio.sleep((100 + secrets.randbelow(901)) / 1000.0)
        return
    await asyncio.sleep(secrets.randbelow(26) / 1000.0)


def _dm_request_fresh(timestamp: int) -> bool:
    now_ts = int(time.time())
    max_age = max(30, int(get_settings().MESH_DM_REQUEST_MAX_AGE_S))
    return abs(timestamp - now_ts) <= max_age


def _validate_private_signed_sequence(
    infonet: Any,
    node_id: str,
    sequence: int,
    *,
    domain: str,
) -> tuple[bool, str]:
    """Advance replay state for a private signed side-effect domain.

    Older test doubles and older runtime objects only accept the historical
    two-argument form. In that case, fold the domain into the node key so
    cross-kind replay separation is still preserved.
    """
    normalized_domain = str(domain or "").strip().lower()
    try:
        return infonet.validate_and_set_sequence(
            node_id,
            sequence,
            domain=normalized_domain,
        )
    except TypeError:
        domain_key = f"{node_id}|{normalized_domain}" if normalized_domain else node_id
        return infonet.validate_and_set_sequence(domain_key, sequence)


def _wake_private_release_worker() -> None:
    private_release_worker.ensure_started()
    private_release_worker.wake()


def _queue_dm_release(*, current_tier: str, payload: dict[str, Any]) -> dict[str, Any]:
    item = private_delivery_outbox.enqueue(
        lane="dm",
        release_key=str(payload.get("msg_id", "") or ""),
        payload=payload,
        current_tier=current_tier,
        required_tier=release_lane_required_tier("dm"),
    )
    if evaluate_network_release("dm", current_tier).should_bootstrap:
        private_transport_manager.request_warmup(
            reason="queued_dm_delivery",
            current_tier=current_tier,
            required_tier=release_lane_required_tier("dm"),
        )
    _wake_private_release_worker()
    return {
        "ok": True,
        "msg_id": str(payload.get("msg_id", "") or ""),
        "outbox_id": str(item.get("id", "") or ""),
        "queued": True,
        "detail": str((item.get("status") or {}).get("label", "") or "Queued for private delivery"),
        "delivery": {
            "state": canonical_release_state(str(item.get("release_state", "") or "queued")),
            "internal_state": str(item.get("release_state", "") or "queued"),
            "local_state": "sealed_local",
            "network_state": network_release_state(
                "dm",
                str(item.get("release_state", "") or "queued"),
                result=dict(item.get("result") or {}),
            ),
            "status": dict(item.get("status") or {}),
            "required_tier": str(item.get("required_tier", "") or ""),
            "current_tier": str(item.get("current_tier", "") or ""),
        },
    }


def _queue_gate_release(*, current_tier: str, gate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    item = private_delivery_outbox.enqueue(
        lane="gate",
        release_key=str(payload.get("event_id", "") or ""),
        payload=payload,
        current_tier=current_tier,
        required_tier=release_lane_required_tier("gate"),
    )
    if evaluate_network_release("gate", current_tier).should_bootstrap:
        private_transport_manager.request_warmup(
            reason="queued_gate_delivery",
            current_tier=current_tier,
            required_tier=release_lane_required_tier("gate"),
        )
    _wake_private_release_worker()
    return {
        "ok": True,
        "detail": str((item.get("status") or {}).get("label", "") or "Queued for private delivery"),
        "gate_id": gate_id,
        "event_id": str(payload.get("event_id", "") or ""),
        "outbox_id": str(item.get("id", "") or ""),
        "queued": True,
        "local_state": "sealed_local",
        "network_state": network_release_state(
            "gate",
            str(item.get("release_state", "") or "queued"),
            result=dict(item.get("result") or {}),
        ),
        "delivery": {
            "state": canonical_release_state(str(item.get("release_state", "") or "queued")),
            "internal_state": str(item.get("release_state", "") or "queued"),
            "local_state": "sealed_local",
            "network_state": network_release_state(
                "gate",
                str(item.get("release_state", "") or "queued"),
                result=dict(item.get("result") or {}),
            ),
            "status": dict(item.get("status") or {}),
            "required_tier": str(item.get("required_tier", "") or ""),
            "current_tier": str(item.get("current_tier", "") or ""),
        },
    }


def _normalize_mailbox_claims(mailbox_claims: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for claim in mailbox_claims[:32]:
        if not isinstance(claim, dict):
            continue
        normalized.append(
            {
                "type": str(claim.get("type", "")).lower(),
                "token": str(claim.get("token", "")),
            }
        )
    return normalized


def _verify_dm_mailbox_request(
    *,
    event_type: str,
    agent_id: str,
    mailbox_claims: list[dict],
    timestamp: int,
    nonce: str,
    public_key: str,
    public_key_algo: str,
    signature: str,
    sequence: int,
    protocol_version: str,
    skip_signature: bool = False,
):
    payload = {
        "mailbox_claims": _normalize_mailbox_claims(mailbox_claims),
        "timestamp": timestamp,
        "nonce": nonce,
    }
    valid, reason = validate_event_payload(event_type, payload)
    if not valid:
        return False, reason, payload
    if not skip_signature:
        sig_ok, sig_reason = _verify_signed_write(
            event_type=event_type,
            node_id=agent_id,
            sequence=sequence,
            public_key=public_key,
            public_key_algo=public_key_algo,
            signature=signature,
            payload=payload,
            protocol_version=protocol_version,
        )
        if not sig_ok:
            return False, sig_reason, payload
    if not _dm_request_fresh(timestamp):
        return False, "Mailbox request timestamp is stale", payload
    return True, "ok", payload


async def _dm_send_from_signed_request(request: Request):
    """Deposit an encrypted DM after decorator-level signed-write verification."""
    from services.wormhole_supervisor import get_transport_tier

    tier = get_transport_tier()
    transport_upgrade_pending = bool(getattr(request.state, "_dm_send_transport_pending", False))
    if tier == "public_degraded":
        transport_upgrade_pending = True
        if not bool(getattr(request.state, "_dm_send_transport_pending", False)):
            _kickoff_dm_send_transport_upgrade()

    # Hardening Rec #9: if anonymous mode is *requested* but hidden transport
    # has not converged to ready, queue the DM via the private release outbox
    # instead of falling through to direct/relay. Without this, a user who
    # flips anonymous_mode on during a warmup window could egress a DM over a
    # non-hidden transport, silently betraying the stated privacy intent. Non-
    # hostile per policy: the response carries private_transport_pending so
    # the client surfaces a "warming up" state rather than a hard deny.
    _anon_state = _anonymous_mode_state()
    if bool(_anon_state.get("enabled")) and not bool(_anon_state.get("ready")):
        transport_upgrade_pending = True
        if not bool(getattr(request.state, "_dm_send_transport_pending", False)):
            _kickoff_dm_send_transport_upgrade()

    prepared = _prepared_signed_write(request)
    body = _signed_body(request)
    sig_reason = str(prepared.reason if prepared is not None else "ok")
    sender_id = str(body.get("sender_id", "")).strip()
    sender_token_hash = str(
        ((prepared.extras if prepared is not None else {}) or {}).get("sender_token_hash", "")
        or body.get("sender_token_hash", "")
        or ""
    ).strip()
    recipient_id = str(body.get("recipient_id", "")).strip()
    delivery_class = str(body.get("delivery_class", "")).strip().lower()
    recipient_token = str(body.get("recipient_token", "")).strip()
    ciphertext = str(body.get("ciphertext", "")).strip()
    payload_format = str(body.get("format", "mls1") or "mls1").strip().lower() or "mls1"
    if str(tier or "").startswith("private_") and payload_format == "dm1":
        return JSONResponse(
            {"ok": False, "detail": "MLS session required in private transport mode - dm1 blocked on raw send path"},
            status_code=403,
        )
    session_welcome = str(body.get("session_welcome", "") or "").strip()
    sender_seal = str(body.get("sender_seal", "")).strip()
    relay_salt_hex = str(body.get("relay_salt", "") or "").strip().lower()
    msg_id = str(body.get("msg_id", "")).strip()
    timestamp = _safe_int(body.get("timestamp", 0) or 0)
    nonce = str(body.get("nonce", "")).strip()

    if not sender_id or not recipient_id or not ciphertext or not msg_id or not timestamp:
        return {"ok": False, "detail": "Missing sender_id, recipient_id, ciphertext, msg_id, or timestamp"}
    now_ts = int(time.time())
    if abs(timestamp - now_ts) > 7 * 86400:
        return {"ok": False, "detail": "DM timestamp is too far from current time"}
    if delivery_class not in ("request", "shared"):
        return {"ok": False, "detail": "delivery_class must be request or shared"}
    if delivery_class == "request":
        try:
            from services.mesh.mesh_wormhole_contacts import verified_first_contact_requirement

            verified_first_contact = verified_first_contact_requirement(recipient_id)
            if not verified_first_contact.get("ok"):
                return {
                    "ok": False,
                    "detail": str(
                        verified_first_contact.get("detail", "")
                        or "signed invite or SAS verification required before secure first contact"
                    ),
                    "trust_level": str(verified_first_contact.get("trust_level", "") or "unpinned"),
                }
        except Exception:
            pass
    if (
        str(tier or "").startswith("private_")
        and delivery_class == "shared"
        and bool(get_settings().MESH_DM_REQUIRE_SENDER_SEAL_SHARED)
        and not sender_seal
    ):
        return {"ok": False, "detail": "sealed sender required for shared private DMs"}
    if delivery_class == "shared" and not recipient_token:
        return {"ok": False, "detail": "recipient_token required for shared delivery"}
    if delivery_class == "shared" and not sender_token_hash:
        return {"ok": False, "detail": "sender_token required for shared delivery"}
    if delivery_class == "request" and not sender_token_hash:
        return {"ok": False, "detail": "sender_token required for request delivery"}
    from services.mesh.mesh_dm_relay import dm_relay

    compat = _apply_legacy_dm_signature_compat(
        tier=tier,
        delivery_class=delivery_class,
        payload_format=payload_format,
        session_welcome=session_welcome,
        sender_seal=sender_seal,
        relay_salt_hex=relay_salt_hex,
        sig_reason=sig_reason,
    )
    if not compat["ok"]:
        if int(compat["status_code"] or 0) > 0:
            return JSONResponse({"ok": False, "detail": compat["detail"]}, status_code=int(compat["status_code"]))
        return {"ok": False, "detail": compat["detail"]}
    payload_format = str(compat["format"])
    session_welcome = str(compat["session_welcome"])
    sender_seal = str(compat["sender_seal"])
    relay_salt_hex = str(compat["relay_salt"])
    if str(tier or "").startswith("private_") and payload_format == "dm1":
        return JSONResponse(
            {"ok": False, "detail": "MLS session required in private transport mode - dm1 blocked on raw send path"},
            status_code=403,
        )

    send_nonce = nonce or msg_id
    nonce_ok, nonce_reason = dm_relay.consume_nonce(sender_id, send_nonce, timestamp)
    if not nonce_ok:
        return {"ok": False, "detail": nonce_reason}
    try:
        from services.mesh.mesh_hashchain import infonet

        ok_seq, seq_reason = _validate_private_signed_sequence(
            infonet,
            sender_id,
            int(body.get("sequence", 0) or 0),
            domain="dm_send",
        )
        if not ok_seq:
            return {"ok": False, "detail": seq_reason}
    except Exception as exc:
        logger.warning("DM send sequence validation unavailable: %s", type(exc).__name__)

    if dm_relay.is_blocked(recipient_id, sender_id):
        return {"ok": False, "detail": "Recipient is not accepting your messages"}

    if sender_seal:
        if relay_salt_hex:
            if len(relay_salt_hex) != 32 or any(ch not in "0123456789abcdef" for ch in relay_salt_hex):
                return {"ok": False, "detail": "relay_salt must be a 32-character hex string"}
        else:
            import os as _os

            relay_salt_hex = _os.urandom(16).hex()

    release_payload = {
        "sender_id": sender_id,
        "sender_token_hash": sender_token_hash,
        "recipient_id": recipient_id,
        "delivery_class": delivery_class,
        "recipient_token": recipient_token if delivery_class == "shared" else "",
        "ciphertext": ciphertext,
        "format": payload_format,
        "session_welcome": session_welcome,
        "msg_id": msg_id,
        "timestamp": timestamp,
        "sender_seal": sender_seal,
        "relay_salt": relay_salt_hex,
    }
    queued_result = _queue_dm_release(current_tier=tier, payload=release_payload)
    if transport_upgrade_pending:
        queued_result["private_transport_pending"] = True
    return queued_result

async def _dm_poll_secure_from_signed_request(request: Request):
    exposure = metadata_exposure_for_request(
        request,
        authenticated=_scoped_view_authenticated(request, "mesh"),
    )
    body = _signed_body(request)
    agent_id = str(body.get("agent_id", "")).strip()
    mailbox_claims = body.get("mailbox_claims", [])
    timestamp = _safe_int(body.get("timestamp", 0) or 0)
    nonce = str(body.get("nonce", "")).strip()
    public_key = str(body.get("public_key", "")).strip()
    public_key_algo = str(body.get("public_key_algo", "")).strip()
    signature = str(body.get("signature", "")).strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = str(body.get("protocol_version", "")).strip()
    if not agent_id:
        return dm_mailbox_response_view(
            {"ok": False, "detail": "Missing agent_id", "messages": [], "count": 0},
            exposure=exposure,
        )
    from services.mesh.mesh_dm_relay import dm_relay

    ok, reason, payload = _verify_dm_mailbox_request(
        event_type="dm_poll",
        agent_id=agent_id,
        mailbox_claims=mailbox_claims,
        timestamp=timestamp,
        nonce=nonce,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        sequence=sequence,
        protocol_version=protocol_version,
        skip_signature=True,
    )
    if not ok:
        return dm_mailbox_response_view(
            {"ok": False, "detail": reason, "messages": [], "count": 0},
            exposure=exposure,
        )
    nonce_ok, nonce_reason = dm_relay.consume_nonce(agent_id, nonce, timestamp)
    if not nonce_ok:
        return dm_mailbox_response_view(
            {"ok": False, "detail": nonce_reason, "messages": [], "count": 0},
            exposure=exposure,
        )
    try:
        from services.mesh.mesh_hashchain import infonet

        ok_seq, seq_reason = _validate_private_signed_sequence(
            infonet,
            agent_id,
            sequence,
            domain="dm_poll",
        )
        if not ok_seq:
            return dm_mailbox_response_view(
                {"ok": False, "detail": seq_reason, "messages": [], "count": 0},
                exposure=exposure,
            )
    except Exception:
        pass
    await _maybe_apply_dm_poll_jitter()
    claims = payload.get("mailbox_claims", [])
    mailbox_keys = dm_relay.claim_mailbox_keys(agent_id, claims)
    relay_msgs, relay_more = dm_relay.collect_claims(agent_id, claims, limit=DM_POLL_BATCH_LIMIT)
    relay_msgs = _annotate_request_recovery_messages(relay_msgs)
    direct_msgs: list[dict] = []
    direct_more = False
    direct_budget = DM_POLL_BATCH_LIMIT - len(relay_msgs)
    # Rec #9: use the *requested* helper so direct-lane metadata lookups are
    # skipped the moment a user opts into anonymous mode, not only after
    # hidden transport finishes warming up.
    if direct_budget > 0 and not _anonymous_dm_hidden_transport_requested():
        try:
            from services.mesh.mesh_rns import rns_bridge

            direct_msgs, direct_more = rns_bridge.collect_private_dm(mailbox_keys, limit=direct_budget)
            direct_msgs = _annotate_request_recovery_messages(direct_msgs)
        except Exception:
            direct_msgs = []
    elif direct_budget <= 0:
        direct_more = not _anonymous_dm_hidden_transport_requested()
    merged = _merge_dm_poll_messages(relay_msgs, direct_msgs)
    has_more = relay_more or direct_more
    msgs = merged[:DM_POLL_BATCH_LIMIT]
    return dm_mailbox_response_view(
        {"ok": True, "messages": msgs, "count": len(msgs), "has_more": has_more},
        exposure=exposure,
        diagnostic={
            "source_counts": {
                "relay": len(relay_msgs),
                "direct": len(direct_msgs),
                "returned": len(msgs),
            },
            "mailbox_claim_count": len(claims),
        },
    )


async def _dm_count_secure_from_signed_request(request: Request):
    exposure = metadata_exposure_for_request(
        request,
        authenticated=_scoped_view_authenticated(request, "mesh"),
    )
    body = _signed_body(request)
    agent_id = str(body.get("agent_id", "")).strip()
    mailbox_claims = body.get("mailbox_claims", [])
    timestamp = _safe_int(body.get("timestamp", 0) or 0)
    nonce = str(body.get("nonce", "")).strip()
    public_key = str(body.get("public_key", "")).strip()
    public_key_algo = str(body.get("public_key_algo", "")).strip()
    signature = str(body.get("signature", "")).strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = str(body.get("protocol_version", "")).strip()
    if not agent_id:
        return dm_mailbox_response_view(
            {"ok": False, "detail": "Missing agent_id", "count": 0},
            exposure=exposure,
        )
    from services.mesh.mesh_dm_relay import dm_relay

    ok, reason, payload = _verify_dm_mailbox_request(
        event_type="dm_count",
        agent_id=agent_id,
        mailbox_claims=mailbox_claims,
        timestamp=timestamp,
        nonce=nonce,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        sequence=sequence,
        protocol_version=protocol_version,
        skip_signature=True,
    )
    if not ok:
        return dm_mailbox_response_view(
            {"ok": False, "detail": reason, "count": 0},
            exposure=exposure,
        )
    nonce_ok, nonce_reason = dm_relay.consume_nonce(agent_id, nonce, timestamp)
    if not nonce_ok:
        return dm_mailbox_response_view(
            {"ok": False, "detail": nonce_reason, "count": 0},
            exposure=exposure,
        )
    try:
        from services.mesh.mesh_hashchain import infonet

        ok_seq, seq_reason = _validate_private_signed_sequence(
            infonet,
            agent_id,
            sequence,
            domain="dm_count",
        )
        if not ok_seq:
            return dm_mailbox_response_view(
                {"ok": False, "detail": seq_reason, "count": 0},
                exposure=exposure,
            )
    except Exception:
        pass
    await _maybe_apply_dm_poll_jitter()
    claims = payload.get("mailbox_claims", [])
    mailbox_keys = dm_relay.claim_mailbox_keys(agent_id, claims)
    relay_ids = dm_relay.claim_message_ids(agent_id, claims)
    direct_ids = set()
    # Rec #9: requested (not merely enforced) — skip direct-lane count probe
    # as soon as anonymous mode is requested, even before ready converges.
    if not _anonymous_dm_hidden_transport_requested():
        try:
            from services.mesh.mesh_rns import rns_bridge

            direct_ids = rns_bridge.private_dm_ids(mailbox_keys)
        except Exception:
            direct_ids = set()
    exact_total = len(relay_ids | direct_ids)
    return dm_mailbox_response_view(
        {"ok": True, "count": _coarsen_dm_count(exact_total)},
        exposure=exposure,
        diagnostic={
            "source_counts": {
                "relay": len(relay_ids),
                "direct": len(direct_ids),
                "exact_total": exact_total,
            },
            "mailbox_claim_count": len(claims),
        },
    )


@app.post("/api/mesh/dm/register")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.DM_REGISTER)
async def dm_register_key(request: Request):
    """Register a DH public key for encrypted DM key exchange."""
    body = _signed_body(request)
    agent_id = body.get("agent_id", "").strip()
    dh_pub_key = body.get("dh_pub_key", "").strip()
    dh_algo = body.get("dh_algo", "").strip()
    timestamp = _safe_int(body.get("timestamp", 0) or 0)
    public_key = body.get("public_key", "").strip()
    public_key_algo = body.get("public_key_algo", "").strip()
    signature = body.get("signature", "").strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()
    if not agent_id or not dh_pub_key or not dh_algo or not timestamp:
        return {"ok": False, "detail": "Missing agent_id, dh_pub_key, dh_algo, or timestamp"}
    if dh_algo.upper() not in ("X25519", "ECDH_P256", "ECDH"):
        return {"ok": False, "detail": "Unsupported dh_algo"}
    now_ts = int(time.time())
    if abs(timestamp - now_ts) > 7 * 86400:
        return {"ok": False, "detail": "DH key timestamp is too far from current time"}
    from services.mesh.mesh_dm_relay import dm_relay

    try:
        from services.mesh.mesh_reputation import reputation_ledger

        reputation_ledger.register_node(agent_id, public_key, public_key_algo)
    except Exception:
        pass

    accepted, detail, metadata = dm_relay.register_dh_key(
        agent_id,
        dh_pub_key,
        dh_algo,
        timestamp,
        signature,
        public_key,
        public_key_algo,
        protocol_version,
        sequence,
    )
    if not accepted:
        return {"ok": False, "detail": detail}

    return {"ok": True, **(metadata or {})}


@app.get("/api/mesh/dm/pubkey")
@limiter.limit("30/minute")
async def dm_get_pubkey(request: Request, agent_id: str = "", lookup_token: str = ""):
    """Fetch an agent's DH public key for key exchange."""
    exposure = metadata_exposure_for_request(
        request,
        authenticated=_scoped_view_authenticated(request, "mesh"),
    )
    if not agent_id and not lookup_token:
        return dm_lookup_response_view(
            {"ok": False, "detail": "Missing agent_id or lookup_token"},
            exposure=exposure,
            lookup_token_present=bool(lookup_token),
        )
    from services.mesh.mesh_dm_relay import dm_relay

    resolved_id, resolved_lookup = _preferred_dm_lookup_target(agent_id, lookup_token)
    key_bundle = None
    lookup_mode = "legacy_agent_id"
    if resolved_lookup:
        key_bundle, resolved_id = dm_relay.get_dh_key_by_lookup(resolved_lookup)
        if key_bundle is None:
            return dm_lookup_response_view(
                {"ok": False, "detail": "Agent not found or has no DH key", "lookup_mode": "invite_lookup_handle"},
                exposure=exposure,
                lookup_token_present=True,
            )
        lookup_mode = "invite_lookup_handle"
    if key_bundle is None and resolved_id:
        blocked = legacy_agent_id_lookup_blocked()
        record_legacy_agent_id_lookup(
            resolved_id,
            lookup_kind="dh_pubkey",
            blocked=blocked,
        )
        _warn_legacy_dm_pubkey_lookup(resolved_id)
        if blocked:
            return dm_lookup_response_view(
                {
                    "ok": False,
                    "detail": "legacy agent_id lookup disabled; use invite lookup handle",
                    "removal_target": sunset_target_label(LEGACY_AGENT_ID_LOOKUP_TARGET),
                },
                exposure=exposure,
                lookup_token_present=False,
            )
        key_bundle = dm_relay.get_dh_key(resolved_id)
    if key_bundle is None:
        return dm_lookup_response_view(
            {"ok": False, "detail": "Agent not found or has no DH key"},
            exposure=exposure,
            lookup_token_present=bool(resolved_lookup),
        )
    return dm_lookup_response_view(
        {"ok": True, "agent_id": resolved_id, "lookup_mode": lookup_mode, **key_bundle},
        exposure=exposure,
        lookup_token_present=bool(resolved_lookup),
    )


@app.get("/api/mesh/dm/prekey-bundle")
@limiter.limit("30/minute")
async def dm_get_prekey_bundle(request: Request, agent_id: str = "", lookup_token: str = ""):
    exposure = metadata_exposure_for_request(
        request,
        authenticated=_scoped_view_authenticated(request, "mesh"),
    )
    if not agent_id and not lookup_token:
        return dm_lookup_response_view(
            {"ok": False, "detail": "Missing agent_id or lookup_token"},
            exposure=exposure,
            lookup_token_present=bool(lookup_token),
        )
    resolved_id, resolved_lookup = _preferred_dm_lookup_target(agent_id, lookup_token)
    result = fetch_dm_prekey_bundle(agent_id=resolved_id, lookup_token=resolved_lookup)
    return dm_lookup_response_view(
        result,
        exposure=exposure,
        lookup_token_present=bool(resolved_lookup),
    )


@app.post("/api/mesh/dm/send")
@limiter.limit("20/minute")
@requires_signed_write(kind=SignedWriteKind.DM_SEND)
async def dm_send(request: Request):
    return await _dm_send_from_signed_request(request)

_REQUEST_V2_REDUCED_VERSION = "request-v2-reduced-v3"
_REQUEST_V2_RECOVERY_STATES = {"pending", "verified", "failed"}


def _is_canonical_reduced_request_message(message: dict[str, Any]) -> bool:
    item = dict(message or {})
    return (
        str(item.get("delivery_class", "") or "").strip().lower() == "request"
        and str(item.get("request_contract_version", "") or "").strip()
        == _REQUEST_V2_REDUCED_VERSION
        and item.get("sender_recovery_required") is True
    )


def _annotate_request_recovery_message(message: dict[str, Any]) -> dict[str, Any]:
    item = dict(message or {})
    delivery_class = str(item.get("delivery_class", "") or "").strip().lower()
    sender_id = str(item.get("sender_id", "") or "").strip()
    sender_seal = str(item.get("sender_seal", "") or "").strip()
    sender_is_blinded = sender_id.startswith("sealed:") or sender_id.startswith("sender_token:")
    if delivery_class != "request" or not sender_is_blinded or not sender_seal.startswith("v3:"):
        return item
    if not str(item.get("request_contract_version", "") or "").strip():
        item["request_contract_version"] = _REQUEST_V2_REDUCED_VERSION
    item["sender_recovery_required"] = True
    state = str(item.get("sender_recovery_state", "") or "").strip().lower()
    if state not in _REQUEST_V2_RECOVERY_STATES:
        state = "pending"
    item["sender_recovery_state"] = state
    return item


def _annotate_request_recovery_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_annotate_request_recovery_message(message) for message in (messages or [])]


def _request_duplicate_authority_rank(message: dict[str, Any]) -> int:
    item = dict(message or {})
    if str(item.get("delivery_class", "") or "").strip().lower() != "request":
        return 0
    if _is_canonical_reduced_request_message(item):
        return 3
    sender_id = str(item.get("sender_id", "") or "").strip()
    if sender_id.startswith("sealed:") or sender_id.startswith("sender_token:"):
        return 1
    if sender_id:
        return 2
    return 0


def _request_duplicate_recovery_rank(message: dict[str, Any]) -> int:
    if not _is_canonical_reduced_request_message(message):
        return 0
    state = str(dict(message or {}).get("sender_recovery_state", "") or "").strip().lower()
    if state == "verified":
        return 2
    if state == "pending":
        return 1
    return 0


def _poll_duplicate_source_rank(source: str) -> int:
    normalized = str(source or "").strip().lower()
    if normalized == "relay":
        return 2
    if normalized == "reticulum":
        return 1
    return 0


def _should_replace_dm_poll_duplicate(
    existing: dict[str, Any],
    existing_source: str,
    candidate: dict[str, Any],
    candidate_source: str,
) -> bool:
    candidate_authority = _request_duplicate_authority_rank(candidate)
    existing_authority = _request_duplicate_authority_rank(existing)
    if candidate_authority != existing_authority:
        return candidate_authority > existing_authority

    candidate_recovery = _request_duplicate_recovery_rank(candidate)
    existing_recovery = _request_duplicate_recovery_rank(existing)
    if candidate_recovery != existing_recovery:
        return candidate_recovery > existing_recovery

    candidate_source_rank = _poll_duplicate_source_rank(candidate_source)
    existing_source_rank = _poll_duplicate_source_rank(existing_source)
    if candidate_source_rank != existing_source_rank:
        return candidate_source_rank > existing_source_rank

    try:
        candidate_ts = float(candidate.get("timestamp", 0) or 0)
    except Exception:
        candidate_ts = 0.0
    try:
        existing_ts = float(existing.get("timestamp", 0) or 0)
    except Exception:
        existing_ts = 0.0
    return candidate_ts > existing_ts


DM_POLL_BATCH_LIMIT = 8
"""Maximum messages returned per DM poll. Overflow stays queued for subsequent polls."""


def _merge_dm_poll_messages(
    relay_messages: list[dict[str, Any]],
    direct_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_msg_id: dict[str, tuple[int, str]] = {}

    def add_messages(items: list[dict[str, Any]], source: str) -> None:
        for original in items or []:
            item = dict(original or {})
            msg_id = str(item.get("msg_id", "") or "").strip()
            if not msg_id:
                merged.append(item)
                continue
            existing = index_by_msg_id.get(msg_id)
            if existing is None:
                index_by_msg_id[msg_id] = (len(merged), source)
                merged.append(item)
                continue
            index, existing_source = existing
            if _should_replace_dm_poll_duplicate(merged[index], existing_source, item, source):
                merged[index] = item
                index_by_msg_id[msg_id] = (index, source)

    add_messages(relay_messages, "relay")
    add_messages(direct_messages, "reticulum")
    return sorted(merged, key=lambda item: float(item.get("timestamp", 0) or 0))


@app.post("/api/mesh/dm/poll")
@limiter.limit("30/minute")
@requires_signed_write(kind=SignedWriteKind.DM_POLL)
async def dm_poll_secure(request: Request):
    return await _dm_poll_secure_from_signed_request(request)

@app.get("/api/mesh/dm/poll")
@limiter.limit("30/minute")
async def dm_poll(
    request: Request,
    agent_id: str = "",
    agent_token: str = "",
    agent_token_prev: str = "",
    agent_tokens: str = "",
):
    """Pick up all pending DMs. Removes them from mailbox after retrieval."""
    exposure = metadata_exposure_for_request(
        request,
        authenticated=_scoped_view_authenticated(request, "mesh"),
    )
    if _secure_dm_enabled() and not _legacy_dm_get_allowed():
        if agent_id or agent_token or agent_token_prev or agent_tokens:
            record_legacy_dm_get(operation="poll", blocked=True)
        return dm_mailbox_response_view(
            {"ok": False, "detail": "Legacy GET polling is disabled in secure mode", "messages": [], "count": 0},
            exposure=exposure,
        )
    if not agent_id and not agent_token and not agent_token_prev and not agent_tokens:
        return dm_mailbox_response_view(
            {"ok": True, "messages": [], "count": 0},
            exposure=exposure,
            diagnostic={"source_counts": {"legacy": 0, "returned": 0}, "token_count": 0},
        )
    from services.mesh.mesh_dm_relay import dm_relay
    tokens: list[str] = []
    if agent_tokens:
        for token in agent_tokens.split(","):
            token = token.strip()
            if token:
                tokens.append(token)
    if agent_token:
        tokens.append(agent_token)
    if agent_token_prev and agent_token_prev != agent_token:
        tokens.append(agent_token_prev)
    # Deduplicate while preserving order
    seen = set()
    unique_tokens: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        unique_tokens.append(token)
    msgs: list[dict] = []
    has_more = False
    if unique_tokens:
        record_legacy_dm_get(operation="poll", blocked=False)
        for token in unique_tokens[:32]:
            batch, more = dm_relay.collect_legacy(agent_token=token, limit=DM_POLL_BATCH_LIMIT - len(msgs))
            msgs.extend(batch)
            if more:
                has_more = True
            if len(msgs) >= DM_POLL_BATCH_LIMIT:
                has_more = True
                msgs = msgs[:DM_POLL_BATCH_LIMIT]
                break
    return dm_mailbox_response_view(
        {"ok": True, "messages": msgs, "count": len(msgs), "has_more": has_more},
        exposure=exposure,
        diagnostic={
            "source_counts": {"legacy": len(msgs), "returned": len(msgs)},
            "token_count": len(unique_tokens),
        },
    )


def _coarsen_dm_count(n: int) -> int:
    """Reduce DM count precision to limit API-observable cardinality metadata."""
    if n <= 1:
        return n
    if n <= 5:
        return 5
    if n <= 20:
        return 20
    return 50


@app.post("/api/mesh/dm/count")
@limiter.limit("60/minute")
@requires_signed_write(kind=SignedWriteKind.DM_COUNT)
async def dm_count_secure(request: Request):
    return await _dm_count_secure_from_signed_request(request)

@app.get("/api/mesh/dm/count")
@limiter.limit("60/minute")
async def dm_count(
    request: Request,
    agent_id: str = "",
    agent_token: str = "",
    agent_token_prev: str = "",
    agent_tokens: str = "",
):
    """Unread DM count (for notification badge). Lightweight poll."""
    exposure = metadata_exposure_for_request(
        request,
        authenticated=_scoped_view_authenticated(request, "mesh"),
    )
    if _secure_dm_enabled() and not _legacy_dm_get_allowed():
        if agent_id or agent_token or agent_token_prev or agent_tokens:
            record_legacy_dm_get(operation="count", blocked=True)
        return dm_mailbox_response_view(
            {"ok": False, "detail": "Legacy GET count is disabled in secure mode", "count": 0},
            exposure=exposure,
        )
    if not agent_id and not agent_token and not agent_token_prev and not agent_tokens:
        return dm_mailbox_response_view(
            {"ok": True, "count": 0},
            exposure=exposure,
            diagnostic={"source_counts": {"legacy": 0, "exact_total": 0}, "token_count": 0},
        )
    from services.mesh.mesh_dm_relay import dm_relay
    tokens: list[str] = []
    if agent_tokens:
        for token in agent_tokens.split(","):
            token = token.strip()
            if token:
                tokens.append(token)
    if agent_token:
        tokens.append(agent_token)
    if agent_token_prev and agent_token_prev != agent_token:
        tokens.append(agent_token_prev)
    # Deduplicate while preserving order
    seen = set()
    unique_tokens: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        unique_tokens.append(token)
    if unique_tokens:
        record_legacy_dm_get(operation="count", blocked=False)
        total = 0
        for token in unique_tokens[:32]:
            total += dm_relay.count_legacy(agent_token=token)
        return dm_mailbox_response_view(
            {"ok": True, "count": _coarsen_dm_count(total)},
            exposure=exposure,
            diagnostic={"source_counts": {"legacy": total, "exact_total": total}, "token_count": len(unique_tokens)},
        )
    return dm_mailbox_response_view(
        {"ok": True, "count": 0},
        exposure=exposure,
        diagnostic={"source_counts": {"legacy": 0, "exact_total": 0}, "token_count": 0},
    )


@app.post("/api/mesh/dm/block")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.DM_BLOCK)
async def dm_block(request: Request):
    """Block or unblock a sender from DMing you."""
    body = _signed_body(request)
    agent_id = body.get("agent_id", "").strip()
    blocked_id = body.get("blocked_id", "").strip()
    action = body.get("action", "block").strip().lower()
    public_key = body.get("public_key", "").strip()
    public_key_algo = body.get("public_key_algo", "").strip()
    signature = body.get("signature", "").strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()
    if not agent_id or not blocked_id:
        return {"ok": False, "detail": "Missing agent_id or blocked_id"}
    from services.mesh.mesh_dm_relay import dm_relay

    try:
        from services.mesh.mesh_hashchain import infonet

        ok_seq, seq_reason = _validate_private_signed_sequence(
            infonet,
            agent_id,
            sequence,
            domain=f"dm_block:{action}",
        )
        if not ok_seq:
            return {"ok": False, "detail": seq_reason}
    except Exception:
        pass

    if action == "unblock":
        dm_relay.unblock(agent_id, blocked_id)
    else:
        dm_relay.block(agent_id, blocked_id)
    return {"ok": True, "action": action, "blocked_id": blocked_id}


@app.post("/api/mesh/dm/witness")
@limiter.limit("20/minute")
@requires_signed_write(kind=SignedWriteKind.DM_WITNESS)
async def dm_key_witness(request: Request):
    """Record a lightweight witness for a DM key (dual-path spot-check)."""
    body = _signed_body(request)
    witness_id = body.get("witness_id", "").strip()
    target_id = body.get("target_id", "").strip()
    dh_pub_key = body.get("dh_pub_key", "").strip()
    timestamp = _safe_int(body.get("timestamp", 0) or 0)
    public_key = body.get("public_key", "").strip()
    public_key_algo = body.get("public_key_algo", "").strip()
    signature = body.get("signature", "").strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()
    if not witness_id or not target_id or not dh_pub_key or not timestamp:
        return {"ok": False, "detail": "Missing witness_id, target_id, dh_pub_key, or timestamp"}
    now_ts = int(time.time())
    if abs(timestamp - now_ts) > 7 * 86400:
        return {"ok": False, "detail": "Witness timestamp is too far from current time"}

    try:
        from services.mesh.mesh_reputation import reputation_ledger

        reputation_ledger.register_node(witness_id, public_key, public_key_algo)
    except Exception:
        pass
    try:
        from services.mesh.mesh_hashchain import infonet

        ok_seq, seq_reason = _validate_private_signed_sequence(
            infonet,
            witness_id,
            sequence,
            domain="dm_witness",
        )
        if not ok_seq:
            return {"ok": False, "detail": seq_reason}
    except Exception:
        pass
    from services.mesh.mesh_dm_relay import dm_relay

    ok, reason = dm_relay.record_witness(witness_id, target_id, dh_pub_key, timestamp)
    return {"ok": ok, "detail": reason}


@app.get("/api/mesh/dm/witness")
@limiter.limit("60/minute")
async def dm_key_witness_get(request: Request, target_id: str = "", dh_pub_key: str = ""):
    """Get witness counts for a target's DH key."""
    if not target_id:
        return {"ok": False, "detail": "Missing target_id"}
    from services.mesh.mesh_dm_relay import dm_relay

    witnesses = dm_relay.get_witnesses(target_id, dh_pub_key if dh_pub_key else None, limit=5)
    response = {
        "ok": True,
        "count": len(witnesses),
    }
    if _scoped_view_authenticated(request, "mesh.audit"):
        response["target_id"] = target_id
        response["dh_pub_key"] = dh_pub_key or ""
        response["witnesses"] = witnesses
    return response


@app.post("/api/mesh/trust/vouch")
@limiter.limit("20/minute")
@requires_signed_write(kind=SignedWriteKind.TRUST_VOUCH)
async def trust_vouch(request: Request):
    """Record a trust vouch for a node (web-of-trust signal)."""
    body = _signed_body(request)
    voucher_id = body.get("voucher_id", "").strip()
    target_id = body.get("target_id", "").strip()
    note = body.get("note", "").strip()
    timestamp = _safe_int(body.get("timestamp", 0) or 0)
    public_key = body.get("public_key", "").strip()
    public_key_algo = body.get("public_key_algo", "").strip()
    signature = body.get("signature", "").strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()
    if not voucher_id or not target_id or not timestamp:
        return {"ok": False, "detail": "Missing voucher_id, target_id, or timestamp"}
    now_ts = int(time.time())
    if abs(timestamp - now_ts) > 7 * 86400:
        return {"ok": False, "detail": "Vouch timestamp is too far from current time"}
    try:
        from services.mesh.mesh_reputation import reputation_ledger
        from services.mesh.mesh_hashchain import infonet

        reputation_ledger.register_node(voucher_id, public_key, public_key_algo)
        ok_seq, seq_reason = _validate_private_signed_sequence(
            infonet,
            voucher_id,
            sequence,
            domain="trust_vouch",
        )
        if not ok_seq:
            return {"ok": False, "detail": seq_reason}
        ok, reason = reputation_ledger.add_vouch(voucher_id, target_id, note, timestamp)
        return {"ok": ok, "detail": reason}
    except Exception:
        return {"ok": False, "detail": "Failed to record vouch"}


@app.get("/api/mesh/trust/vouches", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def trust_vouches(request: Request, node_id: str = "", limit: int = 20):
    """Fetch latest vouches for a node."""
    if not node_id:
        return {"ok": False, "detail": "Missing node_id"}
    try:
        from services.mesh.mesh_reputation import reputation_ledger

        vouches = reputation_ledger.get_vouches(node_id, limit=limit)
        return {"ok": True, "node_id": node_id, "vouches": vouches, "count": len(vouches)}
    except Exception:
        return {"ok": False, "detail": "Failed to fetch vouches"}


@app.get("/api/debug-latest", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def debug_latest_data(request: Request):
    return list(get_latest_data().keys())


# â”€â”€ CCTV media proxy (bypass CORS for cross-origin video/image streams) â”€â”€â”€
_CCTV_PROXY_ALLOWED_HOSTS = {
    "s3-eu-west-1.amazonaws.com",  # TfL JamCams
    "jamcams.tfl.gov.uk",
    "images.data.gov.sg",  # Singapore LTA
    "cctv.austinmobility.io",
    "webcams.nyctmc.org",
    # State DOT camera feeds often resolve to separate media/CDN hosts from the
    # catalog/API hostname. Keep the proxy allowlist aligned with the actual
    # media hosts produced by trusted ingestors so cameras render reliably.
    "cwwp2.dot.ca.gov",  # Caltrans
    "wzmedia.dot.ca.gov",  # Caltrans static media
    "images.wsdot.wa.gov",  # WSDOT
    "olypen.com",  # WSDOT Aviation-linked public camera
    "flyykm.com",  # WSDOT Aviation-linked public camera
    "cam.pangbornairport.com",  # WSDOT Aviation-linked public camera
    "navigator-c2c.dot.ga.gov",  # Georgia DOT
    "navigator-c2c.ga.gov",  # Georgia DOT alternate host variant
    "navigator-csc.dot.ga.gov",  # Georgia DOT alternate catalog/media host
    "vss1live.dot.ga.gov",  # Georgia DOT stream hosts
    "vss2live.dot.ga.gov",
    "vss3live.dot.ga.gov",
    "vss4live.dot.ga.gov",
    "vss5live.dot.ga.gov",
    "511ga.org",  # Georgia public camera images
    "gettingaroundillinois.com",  # Illinois DOT
    "cctv.travelmidwest.com",  # Illinois DOT camera media
    "mdotjboss.state.mi.us",  # Michigan DOT
    "micamerasimages.net",  # Michigan DOT image host
    "publicstreamer1.cotrip.org",  # Colorado DOT / COtrip HLS hosts
    "publicstreamer2.cotrip.org",
    "publicstreamer3.cotrip.org",
    "publicstreamer4.cotrip.org",
    "cocam.carsprogram.org",  # Colorado DOT preview images
    "tripcheck.com",  # Oregon DOT / TripCheck
    "www.tripcheck.com",
    "infocar.dgt.es",  # Spain DGT
    "informo.madrid.es",  # Madrid
    "www.windy.com",
}


@dataclass(frozen=True)
class _CCTVProxyProfile:
    name: str
    timeout: tuple[float, float] = (5.0, 10.0)
    cache_seconds: int = 30
    headers: dict[str, str] = field(default_factory=dict)


def _cctv_host_allowed(hostname: str | None) -> bool:
    host = str(hostname or "").strip().lower()
    if not host:
        return False
    for allowed in _CCTV_PROXY_ALLOWED_HOSTS:
        normalized = str(allowed or "").strip().lower()
        if host == normalized or host.endswith(f".{normalized}"):
            return True
    return False


def _proxied_cctv_url(target_url: str) -> str:
    from urllib.parse import quote

    return f"/api/cctv/media?url={quote(target_url, safe='')}"


def _cctv_proxy_profile_for_url(target_url: str) -> _CCTVProxyProfile:
    from urllib.parse import urlparse

    parsed = urlparse(target_url)
    host = str(parsed.hostname or "").strip().lower()
    path = str(parsed.path or "").strip().lower()

    if host in {"jamcams.tfl.gov.uk", "s3-eu-west-1.amazonaws.com"}:
        return _CCTVProxyProfile(
            name="tfl-jamcam",
            timeout=(5.0, 20.0),
            cache_seconds=15,
            headers={
                "Accept": "video/mp4,image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://tfl.gov.uk/",
            },
        )
    if host == "images.data.gov.sg":
        return _CCTVProxyProfile(
            name="lta-singapore",
            timeout=(5.0, 10.0),
            cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
        )
    if host == "cctv.austinmobility.io":
        return _CCTVProxyProfile(
            name="austin-mobility",
            timeout=(5.0, 8.0),
            cache_seconds=15,
            headers={
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://data.mobility.austin.gov/",
                "Origin": "https://data.mobility.austin.gov",
            },
        )
    if host == "webcams.nyctmc.org":
        return _CCTVProxyProfile(
            name="nyc-dot",
            timeout=(5.0, 10.0),
            cache_seconds=15,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
        )
    if host in {"cwwp2.dot.ca.gov", "wzmedia.dot.ca.gov"}:
        return _CCTVProxyProfile(
            name="caltrans",
            timeout=(5.0, 15.0),
            cache_seconds=15,
            headers={
                "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,video/*,image/*,*/*;q=0.8",
                "Referer": "https://cwwp2.dot.ca.gov/",
            },
        )
    if host in {"images.wsdot.wa.gov", "olypen.com", "flyykm.com", "cam.pangbornairport.com"}:
        return _CCTVProxyProfile(
            name="wsdot",
            timeout=(5.0, 12.0),
            cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
        )
    if host in {"navigator-c2c.dot.ga.gov", "navigator-c2c.ga.gov", "navigator-csc.dot.ga.gov"}:
        read_timeout = 18.0 if "/snapshots/" in path else 12.0
        return _CCTVProxyProfile(
            name="gdot-snapshot",
            timeout=(5.0, read_timeout),
            cache_seconds=15,
            headers={
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "http://navigator-c2c.dot.ga.gov/",
            },
        )
    if host == "511ga.org":
        return _CCTVProxyProfile(
            name="gdot-511ga-image",
            timeout=(5.0, 12.0),
            cache_seconds=15,
            headers={
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://511ga.org/cctv",
            },
        )
    if host.startswith("vss") and host.endswith("dot.ga.gov"):
        return _CCTVProxyProfile(
            name="gdot-hls",
            timeout=(5.0, 20.0),
            cache_seconds=10,
            headers={
                "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,video/*,*/*;q=0.8",
                "Referer": "http://navigator-c2c.dot.ga.gov/",
            },
        )
    if host in {"gettingaroundillinois.com", "cctv.travelmidwest.com"}:
        return _CCTVProxyProfile(
            name="illinois-dot",
            timeout=(5.0, 12.0),
            cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
        )
    if host in {"mdotjboss.state.mi.us", "micamerasimages.net"}:
        return _CCTVProxyProfile(
            name="michigan-dot",
            timeout=(5.0, 12.0),
            cache_seconds=30,
            headers={
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://mdotjboss.state.mi.us/",
            },
        )
    if host in {
        "publicstreamer1.cotrip.org",
        "publicstreamer2.cotrip.org",
        "publicstreamer3.cotrip.org",
        "publicstreamer4.cotrip.org",
    }:
        return _CCTVProxyProfile(
            name="cotrip-hls",
            timeout=(5.0, 20.0),
            cache_seconds=10,
            headers={
                "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,video/*,*/*;q=0.8",
                "Referer": "https://www.cotrip.org/",
            },
        )
    if host == "cocam.carsprogram.org":
        return _CCTVProxyProfile(
            name="cotrip-preview",
            timeout=(5.0, 12.0),
            cache_seconds=20,
            headers={
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://www.cotrip.org/",
            },
        )
    if host in {"tripcheck.com", "www.tripcheck.com"}:
        return _CCTVProxyProfile(
            name="odot-tripcheck",
            timeout=(5.0, 12.0),
            cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
        )
    if host == "infocar.dgt.es":
        return _CCTVProxyProfile(
            name="dgt-spain",
            timeout=(5.0, 8.0),
            cache_seconds=60,
            headers={
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://infocar.dgt.es/",
            },
        )
    if host == "informo.madrid.es":
        return _CCTVProxyProfile(
            name="madrid-city",
            timeout=(5.0, 12.0),
            cache_seconds=30,
            headers={
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://informo.madrid.es/",
            },
        )
    if host == "www.windy.com":
        return _CCTVProxyProfile(
            name="windy-webcams",
            timeout=(5.0, 12.0),
            cache_seconds=60,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
        )
    return _CCTVProxyProfile(
        name="generic-cctv",
        timeout=(5.0, 10.0),
        cache_seconds=30,
        headers={"Accept": "*/*"},
    )


def _cctv_upstream_headers(request: Request, profile: _CCTVProxyProfile) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ShadowBroker CCTV proxy)",
        **profile.headers,
    }
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header
    if_none_match = request.headers.get("if-none-match")
    if if_none_match:
        headers["If-None-Match"] = if_none_match
    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since:
        headers["If-Modified-Since"] = if_modified_since
    return headers


def _cctv_response_headers(resp, cache_seconds: int, include_length: bool = True) -> dict[str, str]:
    headers = {
        "Cache-Control": f"public, max-age={cache_seconds}",
        "Access-Control-Allow-Origin": "*",
    }
    for key in ("Accept-Ranges", "Content-Range", "ETag", "Last-Modified"):
        value = resp.headers.get(key)
        if value:
            headers[key] = value
    if include_length:
        content_length = resp.headers.get("Content-Length")
        if content_length:
            headers["Content-Length"] = content_length
    return headers


def _fetch_cctv_upstream_response(request: Request, target_url: str, profile: _CCTVProxyProfile):
    import requests as _req

    headers = _cctv_upstream_headers(request, profile)
    try:
        resp = _req.get(
            target_url,
            timeout=profile.timeout,
            stream=True,
            allow_redirects=True,
            headers=headers,
        )
    except _req.exceptions.Timeout as exc:
        logger.warning("CCTV upstream timeout [%s] %s", profile.name, target_url)
        raise HTTPException(status_code=504, detail="Upstream timeout") from exc
    except _req.exceptions.RequestException as exc:
        logger.warning("CCTV upstream request failure [%s] %s: %s", profile.name, target_url, exc)
        raise HTTPException(status_code=502, detail="Upstream fetch failed") from exc

    if resp.status_code >= 400:
        logger.info("CCTV upstream HTTP %s [%s] %s", resp.status_code, profile.name, target_url)
        resp.close()
        raise HTTPException(status_code=int(resp.status_code), detail=f"Upstream returned {resp.status_code}")
    return resp


def _proxy_cctv_media_response(request: Request, target_url: str):
    from urllib.parse import urlparse

    parsed = urlparse(target_url)
    profile = _cctv_proxy_profile_for_url(target_url)
    resp = _fetch_cctv_upstream_response(request, target_url, profile)

    content_type = resp.headers.get("Content-Type", "application/octet-stream")
    is_hls_playlist = (
        ".m3u8" in str(parsed.path or "").lower()
        or "mpegurl" in content_type.lower()
        or "vnd.apple.mpegurl" in content_type.lower()
    )
    if is_hls_playlist:
        body = resp.text
        if "#EXTM3U" in body:
            body = _rewrite_cctv_hls_playlist(target_url, body)
        resp.close()
        return Response(
            content=body,
            media_type=content_type,
            headers=_cctv_response_headers(resp, cache_seconds=profile.cache_seconds, include_length=False),
        )
    return StreamingResponse(
        resp.iter_content(chunk_size=65536),
        status_code=resp.status_code,
        media_type=content_type,
        headers=_cctv_response_headers(resp, cache_seconds=profile.cache_seconds),
        background=BackgroundTask(resp.close),
    )


def _rewrite_cctv_hls_playlist(base_url: str, body: str) -> str:
    import re
    from urllib.parse import urljoin, urlparse

    def _rewrite_target(target: str) -> str:
        candidate = str(target or "").strip()
        if not candidate or candidate.startswith("data:"):
            return candidate
        absolute = urljoin(base_url, candidate)
        parsed_target = urlparse(absolute)
        if parsed_target.scheme not in ("http", "https"):
            return candidate
        if not _cctv_host_allowed(parsed_target.hostname):
            return candidate
        return _proxied_cctv_url(absolute)

    rewritten_lines: list[str] = []
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            rewritten_lines.append(raw_line)
            continue
        if stripped.startswith("#"):
            rewritten_lines.append(
                re.sub(
                    r'URI="([^"]+)"',
                    lambda match: f'URI="{_rewrite_target(match.group(1))}"',
                    raw_line,
                )
            )
            continue
        rewritten_lines.append(_rewrite_target(stripped))
    return "\n".join(rewritten_lines) + ("\n" if body.endswith("\n") else "")


@app.get("/api/cctv/media")
@limiter.limit("120/minute")
async def cctv_media_proxy(request: Request, url: str = Query(...)):
    """Proxy CCTV media through the backend to bypass browser CORS restrictions."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not _cctv_host_allowed(parsed.hostname):
        raise HTTPException(status_code=403, detail="Host not allowed")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid scheme")

    return _proxy_cctv_media_response(request, url)


@app.get("/api/health", response_model=HealthResponse)
@limiter.limit("30/minute")
async def health_check(request: Request):
    import time
    from services.fetchers._store import get_source_timestamps_snapshot

    d = get_latest_data()
    last = d.get("last_updated")
    return {
        "status": "ok",
        "version": APP_VERSION,
        "last_updated": last,
        "sources": {
            "flights": len(d.get("commercial_flights", [])),
            "military": len(d.get("military_flights", [])),
            "ships": len(d.get("ships", [])),
            "satellites": len(d.get("satellites", [])),
            "earthquakes": len(d.get("earthquakes", [])),
            "cctv": len(d.get("cctv", [])),
            "news": len(d.get("news", [])),
            "uavs": len(d.get("uavs", [])),
            "firms_fires": len(d.get("firms_fires", [])),
            "liveuamap": len(d.get("liveuamap", [])),
            "gdelt": len(d.get("gdelt", [])),
        },
        "freshness": get_source_timestamps_snapshot(),
        "uptime_seconds": round(time.time() - _start_time),
    }


from services.radio_intercept import (
    get_top_broadcastify_feeds,
    get_openmhz_systems,
    get_recent_openmhz_calls,
    find_nearest_openmhz_system,
)


@app.get("/api/radio/top")
@limiter.limit("30/minute")
async def get_top_radios(request: Request):
    return get_top_broadcastify_feeds()


@app.get("/api/radio/openmhz/systems")
@limiter.limit("30/minute")
async def api_get_openmhz_systems(request: Request):
    return get_openmhz_systems()


@app.get("/api/radio/openmhz/calls/{sys_name}")
@limiter.limit("60/minute")
async def api_get_openmhz_calls(request: Request, sys_name: str):
    return get_recent_openmhz_calls(sys_name)


@app.get("/api/radio/openmhz/audio")
@limiter.limit("120/minute")
async def api_get_openmhz_audio(request: Request, url: str = Query(..., min_length=10)):
    from services.radio_intercept import openmhz_audio_response
    return openmhz_audio_response(url)


@app.get("/api/radio/nearest")
@limiter.limit("60/minute")
async def api_get_nearest_radio(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    return find_nearest_openmhz_system(lat, lng)


from services.radio_intercept import find_nearest_openmhz_systems_list


@app.get("/api/radio/nearest-list")
@limiter.limit("60/minute")
async def api_get_nearest_radios_list(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    limit: int = Query(5, ge=1, le=20),
):
    return find_nearest_openmhz_systems_list(lat, lng, limit=limit)


from services.network_utils import fetch_with_curl


@app.get("/api/route/{callsign}")
@limiter.limit("60/minute")
async def get_flight_route(request: Request, callsign: str, lat: float = 0.0, lng: float = 0.0):
    r = fetch_with_curl(
        "https://api.adsb.lol/api/0/routeset",
        method="POST",
        json_data={"planes": [{"callsign": callsign, "lat": lat, "lng": lng}]},
        timeout=10,
    )
    if r and r.status_code == 200:
        data = r.json()
        route_list = []
        if isinstance(data, dict):
            route_list = data.get("value", [])
        elif isinstance(data, list):
            route_list = data

        if route_list and len(route_list) > 0:
            route = route_list[0]
            airports = route.get("_airports", [])
            if len(airports) >= 2:
                orig = airports[0]
                dest = airports[-1]
                return {
                    "orig_loc": [orig.get("lon", 0), orig.get("lat", 0)],
                    "dest_loc": [dest.get("lon", 0), dest.get("lat", 0)],
                    "origin_name": f"{orig.get('iata', '') or orig.get('icao', '')}: {orig.get('name', 'Unknown')}",
                    "dest_name": f"{dest.get('iata', '') or dest.get('icao', '')}: {dest.get('name', 'Unknown')}",
                }
    return {}


from services.region_dossier import get_region_dossier


@app.get("/api/region-dossier")
@limiter.limit("30/minute")
def api_region_dossier(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Sync def so FastAPI runs it in a threadpool â€” prevents blocking the event loop."""
    return get_region_dossier(lat, lng)


# ---------------------------------------------------------------------------
# Geocoding â€” proxy to Nominatim with caching and proper headers
# ---------------------------------------------------------------------------
from services.geocode import search_geocode, reverse_geocode


@app.get("/api/geocode/search")
@limiter.limit("30/minute")
async def api_geocode_search(
    request: Request,
    q: str = "",
    limit: int = 5,
    local_only: bool = False,
):
    if not q or len(q.strip()) < 2:
        return {"results": [], "query": q, "count": 0}
    results = await asyncio.to_thread(search_geocode, q, limit, local_only)
    return {"results": results, "query": q, "count": len(results)}


@app.get("/api/geocode/reverse")
@limiter.limit("60/minute")
async def api_geocode_reverse(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    local_only: bool = False,
):
    return await asyncio.to_thread(reverse_geocode, lat, lng, local_only)


from services.sentinel_search import search_sentinel2_scene


@app.get("/api/sentinel2/search")
@limiter.limit("30/minute")
def api_sentinel2_search(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Search for latest Sentinel-2 imagery at a point. Sync for threadpool execution."""
    return search_sentinel2_scene(lat, lng)


@app.post("/api/sentinel/token")
@limiter.limit("60/minute")
async def api_sentinel_token(request: Request):
    """Proxy Copernicus CDSE OAuth2 token request (avoids browser CORS block).

    The user's client_id + client_secret are forwarded to the Copernicus
    identity provider and never stored on the server.
    """
    import requests as req

    # Parse URL-encoded form body manually (avoids python-multipart dependency)
    body = await request.body()
    from urllib.parse import parse_qs
    params = parse_qs(body.decode("utf-8"))
    client_id = params.get("client_id", [""])[0]
    client_secret = params.get("client_secret", [""])[0]

    if not client_id or not client_secret:
        raise HTTPException(400, "client_id and client_secret required")

    token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    try:
        resp = await asyncio.to_thread(
            req.post,
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=15,
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type="application/json",
        )
    except Exception as exc:
        logger.exception("Token request failed")
        raise HTTPException(502, "Token request failed")


# Server-side token cache for tile requests (avoids re-auth on every tile)
_sh_token_cache: dict = {"token": None, "expiry": 0, "client_id": ""}


@app.post("/api/sentinel/tile")
@limiter.limit("300/minute")
async def api_sentinel_tile(request: Request):
    """Proxy Sentinel Hub Process API tile request (avoids CORS block).

    Expects JSON body with: client_id, client_secret, preset, date, z, x, y.
    Returns the PNG tile directly.
    """
    import requests as req
    import time as _time

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=422, content={"ok": False, "detail": "invalid JSON body"})

    client_id = body.get("client_id", "")
    client_secret = body.get("client_secret", "")
    preset = body.get("preset", "TRUE-COLOR")
    date_str = body.get("date", "")
    z = body.get("z", 0)
    x = body.get("x", 0)
    y = body.get("y", 0)

    if not client_id or not client_secret or not date_str:
        raise HTTPException(400, "client_id, client_secret, and date required")

    # Reuse cached token if same client_id and not expired
    now = _time.time()
    if (
        _sh_token_cache["token"]
        and _sh_token_cache["client_id"] == client_id
        and now < _sh_token_cache["expiry"] - 30
    ):
        token = _sh_token_cache["token"]
    else:
        # Fetch new token
        token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
        try:
            tresp = await asyncio.to_thread(
                req.post,
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=15,
            )
            if tresp.status_code != 200:
                raise HTTPException(401, f"Token auth failed: {tresp.text[:200]}")
            tdata = tresp.json()
            token = tdata["access_token"]
            _sh_token_cache["token"] = token
            _sh_token_cache["expiry"] = now + tdata.get("expires_in", 300)
            _sh_token_cache["client_id"] = client_id
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Token request failed")
            raise HTTPException(502, "Token request failed")

    # Compute bounding box from tile coordinates (EPSG:3857)
    import math

    half = 20037508.342789244
    tile_size = (2 * half) / math.pow(2, z)
    min_x = -half + x * tile_size
    max_x = min_x + tile_size
    max_y = half - y * tile_size
    min_y = max_y - tile_size
    bbox = [min_x, min_y, max_x, max_y]

    # Evalscripts
    evalscripts = {
        "TRUE-COLOR": '//VERSION=3\nfunction setup(){return{input:["B04","B03","B02"],output:{bands:3}};}\nfunction evaluatePixel(s){return[2.5*s.B04,2.5*s.B03,2.5*s.B02];}',
        "FALSE-COLOR": '//VERSION=3\nfunction setup(){return{input:["B08","B04","B03"],output:{bands:3}};}\nfunction evaluatePixel(s){return[2.5*s.B08,2.5*s.B04,2.5*s.B03];}',
        "NDVI": '//VERSION=3\nfunction setup(){return{input:["B04","B08"],output:{bands:3}};}\nfunction evaluatePixel(s){var n=(s.B08-s.B04)/(s.B08+s.B04);if(n<-0.2)return[0.05,0.05,0.05];if(n<0)return[0.75,0.75,0.75];if(n<0.1)return[0.86,0.86,0.86];if(n<0.2)return[0.92,0.84,0.68];if(n<0.3)return[0.77,0.88,0.55];if(n<0.4)return[0.56,0.80,0.32];if(n<0.5)return[0.35,0.72,0.18];if(n<0.6)return[0.20,0.60,0.08];if(n<0.7)return[0.10,0.48,0.04];return[0.0,0.36,0.0];}',
        "MOISTURE-INDEX": '//VERSION=3\nfunction setup(){return{input:["B8A","B11"],output:{bands:3}};}\nfunction evaluatePixel(s){var m=(s.B8A-s.B11)/(s.B8A+s.B11);var r=Math.max(0,Math.min(1,1.5-3*m));var g=Math.max(0,Math.min(1,m<0?1.5+3*m:1.5-3*m));var b=Math.max(0,Math.min(1,1.5+3*(m-0.5)));return[r,g,b];}',
    }
    evalscript = evalscripts.get(preset, evalscripts["TRUE-COLOR"])

    # Adaptive time range: wider window at lower zoom for better coverage.
    # Sentinel-2 has 5-day revisit â€” a single day often has gaps.
    # At low zoom we mosaic over more days to fill gaps.
    from datetime import datetime as _dt, timedelta as _td

    try:
        end_date = _dt.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        end_date = _dt.utcnow()

    if z <= 6:
        lookback_days = 30  # continent-level: mosaic a full month
    elif z <= 9:
        lookback_days = 14  # region-level: 2 weeks
    elif z <= 11:
        lookback_days = 7   # country-level: 1 week
    else:
        lookback_days = 5   # close-up: 5 days (one revisit cycle)

    start_date = end_date - _td(days=lookback_days)

    process_body = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/3857"},
            },
            "data": [
                {
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {
                            "from": start_date.strftime("%Y-%m-%dT00:00:00Z"),
                            "to": end_date.strftime("%Y-%m-%dT23:59:59Z"),
                        },
                        "maxCloudCoverage": 30,
                        "mosaickingOrder": "leastCC",
                    },
                }
            ],
        },
        "output": {
            "width": 256,
            "height": 256,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": evalscript,
    }

    try:
        resp = await asyncio.to_thread(
            req.post,
            "https://sh.dataspace.copernicus.eu/api/v1/process",
            json=process_body,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "image/png",
            },
            timeout=30,
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "image/png"),
        )
    except Exception as exc:
        logger.exception("Process API failed")
        raise HTTPException(502, "Process API failed")


# ---------------------------------------------------------------------------
# API Settings â€” key registry & management
# ---------------------------------------------------------------------------
from services.api_settings import get_api_keys, get_env_path_info
from services.shodan_connector import (
    ShodanConnectorError,
    count_shodan,
    get_shodan_connector_status,
    lookup_shodan_host,
    search_shodan,
)
from pydantic import BaseModel


class ShodanSearchRequest(BaseModel):
    query: str
    page: int = 1
    facets: list[str] = []


class ShodanCountRequest(BaseModel):
    query: str
    facets: list[str] = []


class ShodanHostRequest(BaseModel):
    ip: str
    history: bool = False


@app.get("/api/settings/api-keys", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_get_keys(request: Request):
    return get_api_keys()


@app.get("/api/settings/api-keys/meta")
@limiter.limit("30/minute")
async def api_get_keys_meta(request: Request):
    return get_env_path_info()


@app.get("/api/tools/shodan/status", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_shodan_status(request: Request):
    return get_shodan_connector_status()


@app.post("/api/tools/shodan/search", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_shodan_search(request: Request, body: ShodanSearchRequest):
    try:
        return search_shodan(body.query, page=body.page, facets=body.facets)
    except ShodanConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/tools/shodan/count", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_shodan_count(request: Request, body: ShodanCountRequest):
    try:
        return count_shodan(body.query, facets=body.facets)
    except ShodanConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/tools/shodan/host", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_shodan_host(request: Request, body: ShodanHostRequest):
    try:
        return lookup_shodan_host(body.ip, history=body.history)
    except ShodanConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# ---------------------------------------------------------------------------
# Finnhub â€” free market intelligence (quotes, congress trades, insider txns)
# ---------------------------------------------------------------------------
from services.unusual_whales_connector import (
    FinnhubConnectorError,
    get_uw_status,
    fetch_congress_trades,
    fetch_insider_transactions,
    fetch_defense_quotes,
)


@app.get("/api/tools/uw/status", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_uw_status(request: Request):
    return get_uw_status()


@app.post("/api/tools/uw/congress", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_uw_congress(request: Request):
    try:
        return fetch_congress_trades()
    except FinnhubConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/tools/uw/darkpool", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_uw_darkpool(request: Request):
    try:
        return fetch_insider_transactions()
    except FinnhubConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/tools/uw/flow", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_uw_flow(request: Request):
    try:
        return fetch_defense_quotes()
    except FinnhubConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# ---------------------------------------------------------------------------
# News Feed Configuration
# ---------------------------------------------------------------------------
from services.news_feed_config import get_feeds, save_feeds, reset_feeds


@app.get("/api/settings/news-feeds")
@limiter.limit("30/minute")
async def api_get_news_feeds(request: Request):
    return get_feeds()


@app.put("/api/settings/news-feeds", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_save_news_feeds(request: Request):
    body = await request.json()
    ok = save_feeds(body)
    if ok:
        return {"status": "updated", "count": len(body)}
    return Response(
        content=json_mod.dumps(
            {
                "status": "error",
                "message": "Validation failed (max 20 feeds, each needs name/url/weight 1-5)",
            }
        ),
        status_code=400,
        media_type="application/json",
    )


@app.post("/api/settings/news-feeds/reset", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_reset_news_feeds(request: Request):
    ok = reset_feeds()
    if ok:
        return {"status": "reset", "feeds": get_feeds()}
    return {"status": "error", "message": "Failed to reset feeds"}


# ---------------------------------------------------------------------------
# Wormhole Settings â€” local agent toggle
# ---------------------------------------------------------------------------
from services.wormhole_settings import read_wormhole_settings, write_wormhole_settings
from services.wormhole_status import read_wormhole_status
from services.wormhole_supervisor import (
    connect_wormhole,
    disconnect_wormhole,
    get_wormhole_state,
    restart_wormhole,
)
from services.mesh import mesh_wormhole_identity as _mesh_wormhole_identity

bootstrap_wormhole_identity = _mesh_wormhole_identity.bootstrap_wormhole_identity
read_wormhole_identity = _mesh_wormhole_identity.read_wormhole_identity
register_wormhole_dm_key = _mesh_wormhole_identity.register_wormhole_dm_key
sign_wormhole_message = _mesh_wormhole_identity.sign_wormhole_message
sign_wormhole_event = _mesh_wormhole_identity.sign_wormhole_event


def _wormhole_identity_unavailable(*_args, **_kwargs) -> dict[str, Any]:
    return {"ok": False, "detail": "wormhole_identity_unavailable"}


export_wormhole_dm_invite = getattr(
    _mesh_wormhole_identity,
    "export_wormhole_dm_invite",
    _wormhole_identity_unavailable,
)
import_wormhole_dm_invite = getattr(
    _mesh_wormhole_identity,
    "import_wormhole_dm_invite",
    _wormhole_identity_unavailable,
)
lookup_handle_rotation_status_snapshot = getattr(
    _mesh_wormhole_identity,
    "lookup_handle_rotation_status_snapshot",
    lambda: {
        "state": "lookup_handle_rotation_unavailable",
        "detail": "wormhole_identity_unavailable",
        "active_handle_count": 0,
        "fresh_handle_available": False,
    },
)
maybe_rotate_prekey_lookup_handles = getattr(
    _mesh_wormhole_identity,
    "maybe_rotate_prekey_lookup_handles",
    lambda **_kwargs: {
        "ok": False,
        "rotated": False,
        "detail": "wormhole_identity_unavailable",
    },
)
from services.mesh.mesh_wormhole_persona import (
    activate_gate_persona,
    bootstrap_wormhole_persona_state,
    clear_active_gate_persona,
    create_gate_persona,
    enter_gate_anonymously,
    get_active_gate_identity,
    get_dm_identity,
    get_transport_identity,
    leave_gate,
    list_gate_personas,
    retire_gate_persona,
    sign_gate_wormhole_event,
    sign_public_wormhole_event,
)
from services.mesh import mesh_wormhole_prekey as _mesh_wormhole_prekey

bootstrap_decrypt_from_sender = _mesh_wormhole_prekey.bootstrap_decrypt_from_sender
bootstrap_encrypt_for_peer = _mesh_wormhole_prekey.bootstrap_encrypt_for_peer
fetch_dm_prekey_bundle = _mesh_wormhole_prekey.fetch_dm_prekey_bundle
register_wormhole_prekey_bundle = _mesh_wormhole_prekey.register_wormhole_prekey_bundle
observe_remote_prekey_bundle = getattr(
    _mesh_wormhole_prekey,
    "observe_remote_prekey_bundle",
    lambda *_args, **_kwargs: {
        "ok": False,
        "detail": "wormhole_prekey_unavailable",
    },
)
from services.mesh.mesh_wormhole_sender_token import (
    consume_wormhole_dm_sender_token,
    issue_wormhole_dm_sender_token,
    issue_wormhole_dm_sender_tokens,
)
from services.mesh.mesh_wormhole_seal import build_sender_seal, open_sender_seal
from services.mesh.mesh_wormhole_dead_drop import (
    AliasRotationReason,
    apply_inbound_alias_binding_frame,
    derive_dead_drop_token_pair,
    derive_dead_drop_tokens_for_contacts,
    derive_sas_phrase,
    issue_pairwise_dm_alias,
    mark_contact_alias_reply_observed,
    maybe_prepare_pairwise_dm_alias_rotation,
    PAIRWISE_ALIAS_GRACE_DEFAULT_MS,
    prepare_outbound_alias_binding_payload,
    register_outbound_alias_rotation_commit,
    rotate_pairwise_dm_alias,
    _unwrap_pairwise_alias_payload,
)
from services.mesh.mesh_gate_mls import (
    compose_encrypted_gate_message,
    decrypt_gate_message_for_local_identity,
    ensure_gate_member_access,
    export_gate_state_snapshot,
    get_local_gate_key_status,
    is_gate_locked_to_mls as is_gate_mls_locked,
    mark_gate_rekey_recommended,
    rotate_gate_epoch,
    sign_encrypted_gate_message,
)
try:
    from services.mesh.mesh_gate_repair import (
        compose_gate_message_with_repair,
        decrypt_gate_message_with_repair,
        export_gate_state_snapshot_with_repair,
        gate_repair_status_snapshot,
        sign_gate_message_with_repair,
    )
except Exception:
    compose_gate_message_with_repair = compose_encrypted_gate_message
    decrypt_gate_message_with_repair = decrypt_gate_message_for_local_identity
    export_gate_state_snapshot_with_repair = export_gate_state_snapshot
    sign_gate_message_with_repair = sign_encrypted_gate_message
    gate_repair_status_snapshot = lambda *_args, **_kwargs: {
        "available": False,
        "state": "gate_repair_unavailable",
    }
from services.mesh.mesh_dm_mls import (
    decrypt_dm as decrypt_mls_dm,
    encrypt_dm as encrypt_mls_dm,
    ensure_dm_session as ensure_mls_dm_session,
    has_dm_session as has_mls_dm_session,
    initiate_dm_session as initiate_mls_dm_session,
    is_dm_locked_to_mls,
)
from services.mesh.mesh_wormhole_ratchet import (
    decrypt_wormhole_dm,
    encrypt_wormhole_dm,
    reset_wormhole_dm_ratchet,
)


class WormholeUpdate(BaseModel):
    enabled: bool
    transport: str | None = None
    socks_proxy: str | None = None
    socks_dns: bool | None = None
    anonymous_mode: bool | None = None


class NodeSettingsUpdate(BaseModel):
    enabled: bool


@app.get("/api/settings/node")
@limiter.limit("30/minute")
async def api_get_node_settings(request: Request):
    from services.node_settings import read_node_settings

    data = await asyncio.to_thread(read_node_settings)
    return {
        **data,
        "node_mode": _current_node_mode(),
        "node_enabled": _participant_node_enabled(),
    }


@app.put("/api/settings/node", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_set_node_settings(request: Request, body: NodeSettingsUpdate):
    _refresh_node_peer_store()
    return _set_participant_node_enabled(bool(body.enabled))


@app.get("/api/settings/wormhole")
@limiter.limit("30/minute")
async def api_get_wormhole_settings(request: Request):
    settings = await asyncio.to_thread(read_wormhole_settings)
    return _redact_wormhole_settings(settings, authenticated=_scoped_view_authenticated(request, "wormhole"))


@app.put("/api/settings/wormhole", dependencies=[Depends(require_admin)])
@limiter.limit("5/minute")
async def api_set_wormhole_settings(request: Request, body: WormholeUpdate):
    existing = read_wormhole_settings()
    updated = write_wormhole_settings(
        enabled=bool(body.enabled),
        transport=body.transport,
        socks_proxy=body.socks_proxy,
        socks_dns=body.socks_dns,
        anonymous_mode=body.anonymous_mode,
    )
    transport_changed = (
        str(existing.get("transport", "direct")) != str(updated.get("transport", "direct"))
        or str(existing.get("socks_proxy", "")) != str(updated.get("socks_proxy", ""))
        or bool(existing.get("socks_dns", True)) != bool(updated.get("socks_dns", True))
    )
    if bool(updated.get("enabled")):
        state = restart_wormhole(reason="settings_update") if transport_changed else connect_wormhole(reason="settings_enable")
    else:
        state = disconnect_wormhole(reason="settings_disable")
    return {**updated, "requires_restart": False, "runtime": state}


class PrivacyProfileUpdate(BaseModel):
    profile: str


class WormholeSignRequest(BaseModel):
    event_type: str
    payload: dict
    sequence: int | None = None
    gate_id: str | None = None


class WormholeSignRawRequest(BaseModel):
    message: str


class WormholeDmEncryptRequest(BaseModel):
    peer_id: str
    peer_dh_pub: str = ""
    plaintext: str
    local_alias: str | None = None
    remote_alias: str | None = None
    remote_prekey_bundle: dict[str, Any] | None = None


class WormholeDmComposeRequest(BaseModel):
    peer_id: str
    peer_dh_pub: str = ""
    plaintext: str
    local_alias: str | None = None
    remote_alias: str | None = None
    remote_prekey_bundle: dict[str, Any] | None = None


class WormholeDmDecryptRequest(BaseModel):
    peer_id: str
    ciphertext: str
    format: str = "dm1"
    nonce: str = ""
    local_alias: str | None = None
    remote_alias: str | None = None
    session_welcome: str | None = None


class WormholeDmResetRequest(BaseModel):
    peer_id: str | None = None


class WormholeDmBootstrapEncryptRequest(BaseModel):
    peer_id: str
    plaintext: str


class WormholeDmBootstrapDecryptRequest(BaseModel):
    sender_id: str = ""
    ciphertext: str


class WormholeDmInviteImportRequest(BaseModel):
    invite: dict[str, Any]
    alias: str = ""


class WormholeRootWitnessImportRequest(BaseModel):
    material: dict[str, Any]


class WormholeRootWitnessImportPathRequest(BaseModel):
    path: str = ""


class WormholeRootTransparencyLedgerPublishRequest(BaseModel):
    path: str = ""
    max_records: int = 64


class WormholeDmSenderTokenRequest(BaseModel):
    recipient_id: str
    delivery_class: str
    recipient_token: str = ""
    count: int = 1


class WormholeOpenSealRequest(BaseModel):
    sender_seal: str
    candidate_dh_pub: str = ""
    recipient_id: str
    expected_msg_id: str


class WormholeBuildSealRequest(BaseModel):
    recipient_id: str
    recipient_dh_pub: str = ""
    msg_id: str
    timestamp: int


class WormholeDeadDropTokenRequest(BaseModel):
    peer_id: str
    peer_dh_pub: str = ""
    peer_ref: str = ""


class WormholePairwiseAliasRequest(BaseModel):
    peer_id: str
    peer_dh_pub: str = ""


class WormholePairwiseAliasRotateRequest(BaseModel):
    peer_id: str
    peer_dh_pub: str = ""
    grace_ms: int = PAIRWISE_ALIAS_GRACE_DEFAULT_MS
    reason: str = AliasRotationReason.MANUAL.value


class WormholeDeadDropContactsRequest(BaseModel):
    contacts: list[dict[str, Any]]
    limit: int = 24


class WormholeSasRequest(BaseModel):
    peer_id: str
    peer_dh_pub: str = ""
    words: int = 8
    peer_ref: str = ""


class WormholeSasConfirmRequest(BaseModel):
    peer_id: str
    sas_phrase: str = ""
    peer_ref: str = ""
    words: int = 8


class WormholeGateRequest(BaseModel):
    gate_id: str
    rotate: bool = False


class WormholeGatePersonaCreateRequest(BaseModel):
    gate_id: str
    label: str = ""


class WormholeGatePersonaActivateRequest(BaseModel):
    gate_id: str
    persona_id: str


class WormholeGateKeyGrantRequest(BaseModel):
    gate_id: str
    recipient_node_id: str
    recipient_dh_pub: str
    recipient_scope: str = "member"


class WormholeGateComposeRequest(BaseModel):
    gate_id: str
    plaintext: str
    reply_to: str = ""
    compat_plaintext: bool = False


class WormholeGateEncryptedSignRequest(BaseModel):
    gate_id: str
    epoch: int = 0
    ciphertext: str
    nonce: str
    format: str = "mls1"
    reply_to: str = ""
    compat_reply_to: bool = False
    recovery_plaintext: str = ""
    envelope_hash: str = ""
    transport_lock: str = "private_strong"


class WormholeGateEncryptedPostRequest(BaseModel):
    gate_id: str
    sender_id: str
    public_key: str
    public_key_algo: str
    signature: str
    sequence: int = 0
    protocol_version: str = ""
    epoch: int = 0
    ciphertext: str
    nonce: str
    sender_ref: str
    format: str = "mls1"
    gate_envelope: str = ""
    envelope_hash: str = ""
    transport_lock: str = "private_strong"
    reply_to: str = ""
    compat_reply_to: bool = False


class WormholeGateDecryptRequest(BaseModel):
    gate_id: str
    epoch: int = 0
    ciphertext: str
    nonce: str = ""
    sender_ref: str = ""
    format: str = "mls1"
    gate_envelope: str = ""
    envelope_hash: str = ""
    recovery_envelope: bool = False
    compat_decrypt: bool = False
    event_id: str = ""


class WormholeGateDecryptBatchRequest(BaseModel):
    messages: list[WormholeGateDecryptRequest]


class WormholeGateRotateRequest(BaseModel):
    gate_id: str
    reason: str = "manual_rotate"

def _default_dm_local_alias(peer_id: str = "") -> str:
    """Generate a per-peer pseudonymous alias for DM conversations."""
    import hashlib
    import hmac as _hmac

    identity = get_dm_identity()
    node_id = str(identity.get("node_id", "") or "").strip()
    if not node_id:
        return "dm-local"
    if not peer_id:
        return node_id[:12]
    derived = _hmac.new(
        node_id.encode("utf-8"),
        peer_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:12]
    return f"dm-{derived}"


def _preferred_remote_dm_alias(peer_id: str) -> str:
    candidate = str(peer_id or "").strip()
    if not candidate:
        return ""
    try:
        from services.mesh.mesh_wormhole_contacts import list_wormhole_dm_contacts

        contact = dict(list_wormhole_dm_contacts().get(candidate) or {})
        shared_alias = str(contact.get("sharedAlias", "") or "").strip()
        if shared_alias:
            return shared_alias
    except Exception:
        pass
    return candidate


def _resolve_dm_aliases(
    *,
    peer_id: str,
    local_alias: str | None,
    remote_alias: str | None,
) -> tuple[str, str]:
    resolved_local = str(local_alias or "").strip() or _default_dm_local_alias(peer_id=peer_id)
    resolved_remote = str(remote_alias or "").strip() or _preferred_remote_dm_alias(peer_id)
    return resolved_local, resolved_remote


def _get_contact_trust_level(peer_id: str) -> str:
    """Look up the current backend-authoritative trust_level for a peer."""
    try:
        from services.mesh.mesh_wormhole_contacts import get_contact_trust_level

        return get_contact_trust_level(str(peer_id or "").strip())
    except Exception:
        return "unpinned"


def compose_wormhole_dm(
    *,
    peer_id: str,
    peer_dh_pub: str,
    plaintext: str,
    local_alias: str | None = None,
    remote_alias: str | None = None,
    remote_prekey_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prepared_alias = maybe_prepare_pairwise_dm_alias_rotation(
        peer_id=str(peer_id or "").strip(),
        peer_dh_pub=str(peer_dh_pub or "").strip(),
    )
    resolved_local, resolved_remote = _resolve_dm_aliases(
        peer_id=peer_id,
        local_alias=local_alias,
        remote_alias=remote_alias,
    )
    alias_wrapped = prepare_outbound_alias_binding_payload(
        peer_id=str(peer_id or "").strip(),
        plaintext=str(plaintext or ""),
    )
    outgoing_plaintext = str(alias_wrapped.get("plaintext", plaintext) or plaintext)
    commit_updates = dict(alias_wrapped.get("commit_updates") or {})
    _compose_trust_level = _get_contact_trust_level(peer_id)

    has_session = has_mls_dm_session(resolved_local, resolved_remote)
    if not has_session.get("ok"):
        return has_session
    if has_session.get("exists"):
        encrypted = encrypt_mls_dm(resolved_local, resolved_remote, outgoing_plaintext)
        if encrypted.get("ok"):
            if commit_updates:
                register_outbound_alias_rotation_commit(
                    peer_id=str(peer_id or "").strip(),
                    payload_format="mls1",
                    ciphertext=str(encrypted.get("ciphertext", "") or ""),
                    updates=commit_updates,
                )
            return {
                "ok": True,
                "peer_id": str(peer_id or "").strip(),
                "local_alias": resolved_local,
                "remote_alias": resolved_remote,
                "ciphertext": str(encrypted.get("ciphertext", "") or ""),
                "nonce": str(encrypted.get("nonce", "") or ""),
                "format": "mls1",
                "session_welcome": "",
                "trust_level": _compose_trust_level,
                "alias_update_embedded": bool(alias_wrapped.get("alias_update_embedded")),
                "alias_update_reason": str(alias_wrapped.get("alias_update_reason", "") or ""),
                "alias_update_seq": int(alias_wrapped.get("alias_update_seq", 0) or 0),
                "alias_prepare_rotated": bool(prepared_alias.get("rotated", False)),
            }
        if str(encrypted.get("detail", "") or "") != "session_expired":
            return encrypted

    bundle = dict(remote_prekey_bundle or {})
    if not bundle and str(peer_id or "").strip():
        fetched_bundle = fetch_dm_prekey_bundle(str(peer_id or "").strip())
        if fetched_bundle.get("ok"):
            bundle = fetched_bundle
    if bundle and str(peer_id or "").strip():
        try:
            trust_state = observe_remote_prekey_bundle(str(peer_id or "").strip(), bundle)
            _compose_trust_level = str(trust_state.get("trust_level", "") or "")
            from services.mesh.mesh_wormhole_contacts import verified_first_contact_requirement

            verified_first_contact = verified_first_contact_requirement(
                str(peer_id or "").strip(),
                trust_level=_compose_trust_level,
            )
            if not verified_first_contact.get("ok"):
                return {
                    "ok": False,
                    "peer_id": str(peer_id or "").strip(),
                    "detail": str(verified_first_contact.get("detail", "") or "verified first contact required"),
                    "trust_changed": _compose_trust_level in ("mismatch", "continuity_broken"),
                    "trust_level": str(
                        verified_first_contact.get("trust_level", "") or _compose_trust_level or "unpinned"
                    ),
                }
        except Exception as exc:
            logger.warning("remote prekey trust pin unavailable: %s", type(exc).__name__)
    try:
        from services.mesh.mesh_wormhole_contacts import verified_first_contact_requirement

        verified_first_contact = verified_first_contact_requirement(
            str(peer_id or "").strip(),
            trust_level=_compose_trust_level,
        )
        if not verified_first_contact.get("ok"):
            return {
                "ok": False,
                "peer_id": str(peer_id or "").strip(),
                "detail": str(verified_first_contact.get("detail", "") or "verified first contact required"),
                "trust_changed": _compose_trust_level in ("mismatch", "continuity_broken"),
                "trust_level": str(verified_first_contact.get("trust_level", "") or _compose_trust_level or "unpinned"),
            }
    except Exception:
        pass
    if str(bundle.get("mls_key_package", "") or "").strip():
        initiated = initiate_mls_dm_session(
            resolved_local,
            resolved_remote,
            bundle,
            str(
                peer_dh_pub
                or bundle.get("welcome_dh_pub")
                or bundle.get("identity_dh_pub_key")
                or ""
            ).strip(),
        )
        if not initiated.get("ok"):
            return initiated
        encrypted = encrypt_mls_dm(resolved_local, resolved_remote, outgoing_plaintext)
        if not encrypted.get("ok"):
            return encrypted
        if commit_updates:
            register_outbound_alias_rotation_commit(
                peer_id=str(peer_id or "").strip(),
                payload_format="mls1",
                ciphertext=str(encrypted.get("ciphertext", "") or ""),
                updates=commit_updates,
            )
        return {
            "ok": True,
            "peer_id": str(peer_id or "").strip(),
            "local_alias": resolved_local,
            "remote_alias": resolved_remote,
            "ciphertext": str(encrypted.get("ciphertext", "") or ""),
            "nonce": str(encrypted.get("nonce", "") or ""),
            "format": "mls1",
            "session_welcome": str(initiated.get("welcome", "") or ""),
            "trust_level": _compose_trust_level,
            "alias_update_embedded": bool(alias_wrapped.get("alias_update_embedded")),
            "alias_update_reason": str(alias_wrapped.get("alias_update_reason", "") or ""),
            "alias_update_seq": int(alias_wrapped.get("alias_update_seq", 0) or 0),
            "alias_prepare_rotated": bool(prepared_alias.get("rotated", False)),
        }

    from services.wormhole_supervisor import get_transport_tier

    current_tier = get_transport_tier()
    if str(current_tier or "").startswith("private_"):
        return {
            "ok": False,
            "detail": "MLS session required in private transport mode - legacy DM fallback blocked",
        }
    contact: dict[str, Any] = {}
    resolved_peer_dh_pub = str(peer_dh_pub or "").strip()
    if not resolved_peer_dh_pub and str(peer_id or "").strip():
        try:
            from services.mesh.mesh_wormhole_contacts import list_wormhole_dm_contacts

            contact = dict(list_wormhole_dm_contacts().get(str(peer_id or "").strip()) or {})
            resolved_peer_dh_pub = str(
                contact.get("dhPubKey") or contact.get("invitePinnedDhPubKey") or ""
            ).strip()
        except Exception:
            contact = {}
            resolved_peer_dh_pub = ""
    elif str(peer_id or "").strip():
        try:
            from services.mesh.mesh_wormhole_contacts import list_wormhole_dm_contacts

            contact = dict(list_wormhole_dm_contacts().get(str(peer_id or "").strip()) or {})
        except Exception:
            contact = {}
    if str(contact.get("invitePinnedPrekeyLookupHandle", "") or "").strip():
        return {
            "ok": False,
            "peer_id": str(peer_id or "").strip(),
            "detail": "invite-scoped bootstrap required; legacy DM fallback disabled",
            "trust_level": _compose_trust_level,
        }
    if not _legacy_dm1_allowed():
        return {
            "ok": False,
            "peer_id": str(peer_id or "").strip(),
            "detail": "legacy dm1 fallback disabled; MLS bootstrap required",
            "trust_level": _compose_trust_level,
        }
    if not resolved_peer_dh_pub:
        return {"ok": False, "detail": "peer_dh_pub required for legacy DM fallback"}

    logger.warning("legacy dm compose path used")
    legacy = encrypt_wormhole_dm(
        peer_id=str(peer_id or ""),
        peer_dh_pub=resolved_peer_dh_pub,
        plaintext=outgoing_plaintext,
    )
    if not legacy.get("ok"):
        return legacy
    if commit_updates:
        register_outbound_alias_rotation_commit(
            peer_id=str(peer_id or "").strip(),
            payload_format="dm1",
            ciphertext=str(legacy.get("result", "") or ""),
            updates=commit_updates,
        )
    return {
        "ok": True,
        "peer_id": str(peer_id or "").strip(),
        "local_alias": resolved_local,
        "remote_alias": resolved_remote,
        "ciphertext": str(legacy.get("result", "") or ""),
        "nonce": "",
        "format": "dm1",
        "session_welcome": "",
        "trust_level": _compose_trust_level,
        "alias_update_embedded": bool(alias_wrapped.get("alias_update_embedded")),
        "alias_update_reason": str(alias_wrapped.get("alias_update_reason", "") or ""),
        "alias_update_seq": int(alias_wrapped.get("alias_update_seq", 0) or 0),
        "alias_prepare_rotated": bool(prepared_alias.get("rotated", False)),
    }


def decrypt_wormhole_dm_envelope(
    *,
    peer_id: str,
    ciphertext: str,
    payload_format: str = "dm1",
    nonce: str = "",
    local_alias: str | None = None,
    remote_alias: str | None = None,
    session_welcome: str | None = None,
) -> dict[str, Any]:
    resolved_local, resolved_remote = _resolve_dm_aliases(
        peer_id=peer_id,
        local_alias=local_alias,
        remote_alias=remote_alias,
    )
    normalized_format = str(payload_format or "dm1").strip().lower() or "dm1"
    if normalized_format != "mls1" and is_dm_locked_to_mls(resolved_local, resolved_remote):
        return {
            "ok": False,
            "detail": "DM session is locked to MLS format",
            "required_format": "mls1",
            "current_format": normalized_format,
        }
    if normalized_format == "mls1":
        has_session = has_mls_dm_session(resolved_local, resolved_remote)
        if not has_session.get("ok"):
            return has_session
        if not has_session.get("exists"):
            local_dh_secret = ""
            local_identity_alias = ""
            try:
                local_identity = read_wormhole_identity()
                local_dh_secret = str(local_identity.get("dh_private_key", "") or "")
                local_identity_alias = str(local_identity.get("node_id", "") or "")
            except Exception:
                local_dh_secret = ""
                local_identity_alias = ""
            ensured = ensure_mls_dm_session(
                resolved_local,
                resolved_remote,
                str(session_welcome or ""),
                local_dh_secret=local_dh_secret,
                identity_alias=local_identity_alias,
            )
            if not ensured.get("ok"):
                return ensured
        decrypted = decrypt_mls_dm(
            resolved_local,
            resolved_remote,
            str(ciphertext or ""),
            str(nonce or ""),
        )
        if not decrypted.get("ok"):
            return decrypted
        plain_text, alias_update = _unwrap_pairwise_alias_payload(str(decrypted.get("plaintext", "") or ""))
        alias_applied = False
        if alias_update:
            alias_result = apply_inbound_alias_binding_frame(
                peer_id=str(peer_id or "").strip(),
                alias_update=alias_update,
            )
            alias_applied = bool(alias_result.get("ok"))
        mark_contact_alias_reply_observed(str(peer_id or "").strip())
        response = {
            "ok": True,
            "peer_id": str(peer_id or "").strip(),
            "local_alias": resolved_local,
            "remote_alias": resolved_remote,
            "plaintext": plain_text,
            "format": "mls1",
        }
        if alias_update:
            response["alias_update_applied"] = alias_applied
        return response

    from services.wormhole_supervisor import get_transport_tier

    current_tier = get_transport_tier()
    if str(current_tier or "").startswith("private_"):
        return {
            "ok": False,
            "detail": "MLS format required in private transport mode â€” legacy DM decrypt blocked",
        }
    if not _legacy_dm1_allowed():
        return {
            "ok": False,
            "detail": "legacy dm1 decrypt disabled; migrate peer to MLS",
        }
    logger.warning("legacy dm decrypt path used")
    legacy = decrypt_wormhole_dm(peer_id=str(peer_id or ""), ciphertext=str(ciphertext or ""))
    if not legacy.get("ok"):
        return legacy
    plain_text, alias_update = _unwrap_pairwise_alias_payload(str(legacy.get("result", "") or ""))
    alias_applied = False
    if alias_update:
        alias_result = apply_inbound_alias_binding_frame(
            peer_id=str(peer_id or "").strip(),
            alias_update=alias_update,
        )
        alias_applied = bool(alias_result.get("ok"))
    mark_contact_alias_reply_observed(str(peer_id or "").strip())
    response = {
        "ok": True,
        "peer_id": str(peer_id or "").strip(),
        "local_alias": resolved_local,
        "remote_alias": resolved_remote,
        "plaintext": plain_text,
        "format": "dm1",
    }
    if alias_update:
        response["alias_update_applied"] = alias_applied
    return response


@app.get("/api/settings/privacy-profile")
@limiter.limit("30/minute")
async def api_get_privacy_profile(request: Request):
    data = await asyncio.to_thread(read_wormhole_settings)
    return _redact_privacy_profile_settings(
        data,
        authenticated=_scoped_view_authenticated(request, "wormhole"),
    )


@app.get("/api/settings/wormhole-status")
@limiter.limit("30/minute")
async def api_get_wormhole_status(request: Request):
    state = await asyncio.to_thread(get_wormhole_state)
    transport_tier = _current_private_lane_tier(state)
    if (
        transport_tier == "public_degraded"
        and bool(state.get("arti_ready"))
        and _is_debug_test_request(request)
    ):
        transport_tier = "private_strong"
    authenticated = _scoped_view_authenticated(request, "wormhole")
    full_state = {
        **state,
        "transport_tier": transport_tier,
    }
    _resume_private_delivery_background_work(
        current_tier=transport_tier,
        reason="startup_resume",
    )
    full_state["private_lane_readiness"] = private_transport_manager.observe_state(
        current_tier=transport_tier,
    )
    full_state["local_custody"] = local_custody_status_snapshot()
    lookup_handle_rotation = {
        **lookup_handle_rotation_status_snapshot(),
        "last_refresh_ok": False,
    }
    private_delivery_exposure = metadata_exposure_for_request(
        request,
        authenticated=authenticated,
    )
    if authenticated:
        contact_preference_refresh = await asyncio.to_thread(
            _upgrade_invite_scoped_contact_preferences_background
        )
        rotation_refresh = await asyncio.to_thread(
            _refresh_lookup_handle_rotation_background,
            reason="status_surface",
        )
        lookup_handle_rotation = {
            **lookup_handle_rotation_status_snapshot(),
            "last_refresh_ok": bool(rotation_refresh.get("ok", False)),
        }
        privacy_core = _privacy_core_status()
        diagnostic_package = _diagnostic_review_package_snapshot(
            current_tier=transport_tier,
            local_custody=full_state.get("local_custody"),
            privacy_core=privacy_core,
            contact_preference_refresh=contact_preference_refresh,
            lookup_handle_rotation=lookup_handle_rotation,
        )
        full_state["privacy_core"] = privacy_core
        full_state["strong_claims"] = diagnostic_package.get("strong_claims")
        full_state["release_gate"] = diagnostic_package.get("release_gate")
        full_state["privacy_status"] = diagnostic_package.get("privacy_status")
        if private_delivery_exposure == "diagnostic":
            full_state["privacy_claims"] = diagnostic_package.get("claim_surface", {}).get("privacy_claims")
            full_state["rollout_readiness"] = diagnostic_package.get("rollout_readiness")
            full_state["rollout_controls"] = diagnostic_package.get("rollout_controls")
            full_state["rollout_health"] = diagnostic_package.get("rollout_health")
            full_state["claim_surface_sources"] = diagnostic_package.get("claim_surface_sources")
            full_state["review_export"] = diagnostic_package.get("review_export")
            full_state["final_review_bundle"] = diagnostic_package.get("final_review_bundle")
            full_state["staged_rollout_telemetry"] = diagnostic_package.get("staged_rollout_telemetry")
            full_state["release_claims_matrix"] = diagnostic_package.get("release_claims_matrix")
            full_state["release_checklist"] = diagnostic_package.get("release_checklist")
    return _redact_wormhole_status(
        full_state,
        authenticated=authenticated,
    )


@app.post("/api/wormhole/join", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_wormhole_join(request: Request):
    existing = read_wormhole_settings()
    updated = write_wormhole_settings(
        enabled=True,
        transport="direct",
        socks_proxy="",
        socks_dns=True,
        anonymous_mode=False,
    )
    transport_changed = (
        str(existing.get("transport", "direct")) != "direct"
        or str(existing.get("socks_proxy", "")) != ""
        or bool(existing.get("socks_dns", True)) is not True
        or bool(existing.get("anonymous_mode", False)) is not False
        or bool(existing.get("enabled", False)) is not True
    )
    bootstrap_wormhole_identity()
    bootstrap_wormhole_persona_state()
    state = (
        restart_wormhole(reason="join_wormhole")
        if transport_changed
        else connect_wormhole(reason="join_wormhole")
    )

    # Enable node participation so the sync/push workers connect to peers.
    # This is the voluntary opt-in â€” the node only joins the network when
    # the user explicitly opens the Wormhole.
    from services.node_settings import write_node_settings

    write_node_settings(enabled=True)
    _refresh_node_peer_store()

    return {
        "ok": True,
        "identity": get_transport_identity(),
        "runtime": state,
        "settings": updated,
    }


@app.post("/api/wormhole/leave", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_wormhole_leave(request: Request):
    updated = write_wormhole_settings(enabled=False)
    state = disconnect_wormhole(reason="leave_wormhole")

    # Disable node participation when the user leaves the Wormhole.
    from services.node_settings import write_node_settings

    write_node_settings(enabled=False)

    return {
        "ok": True,
        "runtime": state,
        "settings": updated,
    }


@app.get("/api/wormhole/identity", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_identity(request: Request):
    try:
        bootstrap_wormhole_persona_state()
        await asyncio.to_thread(_upgrade_invite_scoped_contact_preferences_background)
        await asyncio.to_thread(_refresh_lookup_handle_rotation_background, reason="transport_identity_surface")
        return get_transport_identity()
    except Exception as exc:
        logger.exception("wormhole transport identity fetch failed")
        raise HTTPException(status_code=500, detail="wormhole_identity_failed") from exc


@app.post("/api/wormhole/identity/bootstrap", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_wormhole_identity_bootstrap(request: Request):
    bootstrap_wormhole_identity()
    bootstrap_wormhole_persona_state()
    identity = get_transport_identity()
    dm_key = register_wormhole_dm_key()
    prekeys = register_wormhole_prekey_bundle()
    return {
        **identity,
        "dm_key_ok": bool(dm_key.get("ok")),
        "dm_key_detail": dm_key,
        "prekeys_ok": bool(prekeys.get("ok")),
        "prekey_detail": prekeys,
        "dm_ready": bool(dm_key.get("ok")) and bool(prekeys.get("ok")),
    }


@app.get("/api/wormhole/dm/identity", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_dm_identity(request: Request):
    try:
        bootstrap_wormhole_persona_state()
        await asyncio.to_thread(_upgrade_invite_scoped_contact_preferences_background)
        await asyncio.to_thread(_refresh_lookup_handle_rotation_background, reason="dm_identity_surface")
        return get_dm_identity()
    except Exception as exc:
        logger.exception("wormhole dm identity fetch failed")
        raise HTTPException(status_code=500, detail="wormhole_dm_identity_failed") from exc


@app.get("/api/wormhole/dm/invite", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_dm_invite(request: Request):
    return export_wormhole_dm_invite()


@app.post("/api/wormhole/dm/invite/import", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_invite_import(request: Request, body: WormholeDmInviteImportRequest):
    return import_wormhole_dm_invite(
        dict(body.invite or {}),
        alias=str(body.alias or "").strip(),
    )


def _dm_root_operator_summary(distribution: dict[str, Any], transparency: dict[str, Any]) -> dict[str, Any]:
    def _warning_window_s(configured: int, freshness_window_s: int) -> int:
        window = max(0, _safe_int(freshness_window_s or 0, 0))
        explicit = max(0, _safe_int(configured or 0, 0))
        if window <= 0:
            return explicit
        if explicit <= 0 or explicit >= window:
            if window <= 1:
                return window
            return max(1, min(window - 1, int(window * 0.75)))
        return explicit

    def _append_alert(
        alerts: list[dict[str, Any]],
        *,
        code: str,
        severity: str,
        detail: str,
        action: str,
        target: str,
        blocking: bool,
        age_s: int = 0,
        warning_window_s: int = 0,
        freshness_window_s: int = 0,
    ) -> None:
        alert: dict[str, Any] = {
            "code": str(code or "").strip(),
            "severity": str(severity or "warning").strip(),
            "detail": str(detail or "").strip(),
            "action": str(action or "").strip(),
            "target": str(target or "").strip(),
            "blocking": bool(blocking),
        }
        if age_s > 0:
            alert["age_s"] = _safe_int(age_s, 0)
        if warning_window_s > 0:
            alert["warning_window_s"] = _safe_int(warning_window_s, 0)
        if freshness_window_s > 0:
            alert["freshness_window_s"] = _safe_int(freshness_window_s, 0)
        alerts.append(alert)

    witness_state = str(distribution.get("external_witness_operator_state", "not_configured") or "not_configured")
    transparency_state = str(transparency.get("ledger_operator_state", "not_configured") or "not_configured")
    witness_configured = bool(distribution.get("external_witness_source_configured", False))
    transparency_configured = bool(transparency.get("ledger_readback_configured", False))
    witness_detail = str(distribution.get("external_witness_refresh_detail", "") or "").strip()
    transparency_detail = str(transparency.get("ledger_readback_detail", "") or "").strip()
    witness_age_s = _safe_int(distribution.get("external_witness_source_age_s", 0) or 0, 0)
    transparency_age_s = _safe_int(transparency.get("ledger_readback_export_age_s", 0) or 0, 0)
    witness_freshness_window_s = _safe_int(distribution.get("external_witness_freshness_window_s", 0) or 0, 0)
    transparency_freshness_window_s = _safe_int(transparency.get("ledger_freshness_window_s", 0) or 0, 0)
    witness_warning_window_s = _warning_window_s(
        getattr(get_settings(), "MESH_DM_ROOT_EXTERNAL_WITNESS_WARN_AGE_S", 0),
        witness_freshness_window_s,
    )
    transparency_warning_window_s = _warning_window_s(
        getattr(get_settings(), "MESH_DM_ROOT_TRANSPARENCY_LEDGER_WARN_AGE_S", 0),
        transparency_freshness_window_s,
    )
    witness_warning_due = bool(
        witness_state == "current"
        and witness_warning_window_s > 0
        and witness_age_s >= witness_warning_window_s
    )
    transparency_warning_due = bool(
        transparency_state == "current"
        and transparency_warning_window_s > 0
        and transparency_age_s >= transparency_warning_window_s
    )
    witness_attention = bool(distribution.get("external_witness_reacquire_required", False)) or witness_state in {
        "stale",
        "error",
        "descriptors_only",
    } or witness_warning_due
    transparency_attention = bool(transparency.get("ledger_external_verification_required", False)) or transparency_state in {
        "stale",
        "error",
    } or transparency_warning_due
    any_external_configured = bool(witness_configured or transparency_configured)
    external_assurance_current = witness_state == "current" and transparency_state == "current"
    requires_attention = bool(witness_attention or transparency_attention)
    if external_assurance_current:
        state = "current_external"
        detail = "configured external witness and transparency assurances are current"
        if witness_warning_due or transparency_warning_due:
            detail = "configured external assurance is current but approaching freshness limit"
    elif any_external_configured and requires_attention:
        state = "stale_external"
        detail = "configured external witness or transparency assurance requires refresh"
    else:
        state = "local_cached_only"
        detail = "external witness and transparency assurance are not fully configured"
    if witness_state == "error" or transparency_state == "error":
        health_state = "error"
    elif state == "stale_external":
        health_state = "stale"
    elif witness_warning_due or transparency_warning_due:
        health_state = "warning"
    elif state == "current_external":
        health_state = "ok"
    else:
        health_state = "warning"
    witness_health_state = (
        "warning"
        if witness_state == "current" and witness_warning_due
        else
        "ok"
        if witness_state == "current"
        else "error"
        if witness_state == "error"
        else "stale"
        if witness_state in {"stale", "descriptors_only"}
        else "warning"
    )
    transparency_health_state = (
        "warning"
        if transparency_state == "current" and transparency_warning_due
        else
        "ok"
        if transparency_state == "current"
        else "error"
        if transparency_state == "error"
        else "stale"
        if transparency_state == "stale"
        else "warning"
    )
    strong_trust_blocked = bool(
        (witness_configured and witness_state != "current")
        or (transparency_configured and transparency_state != "current")
    )
    alerts: list[dict[str, Any]] = []
    witness_detail_lower = witness_detail.lower()
    transparency_detail_lower = transparency_detail.lower()
    if not witness_configured:
        _append_alert(
            alerts,
            code="external_witness_not_configured",
            severity="warning",
            detail="external witness source is not configured",
            action="configure_external_witness_source",
            target="external_witness",
            blocking=False,
        )
    elif witness_state == "descriptors_only":
        _append_alert(
            alerts,
            code="external_witness_receipts_missing",
            severity="stale",
            detail=witness_detail or "external witness descriptors are present but current-manifest receipts are missing",
            action="reacquire_external_witness_receipts",
            target="external_witness",
            blocking=True,
        )
    elif witness_state == "stale":
        if any(
            marker in witness_detail_lower
            for marker in (
                "manifest_fingerprint mismatch",
                "waiting for current-manifest receipts",
            )
        ):
            _append_alert(
                alerts,
                code="external_witness_receipts_stale",
                severity="stale",
                detail=witness_detail or "external witness receipts do not match the current manifest",
                action="reacquire_external_witness_receipts",
                target="external_witness",
                blocking=True,
            )
        else:
            _append_alert(
                alerts,
                code="external_witness_source_stale",
                severity="stale",
                detail=witness_detail or "external witness source is stale",
                action="refresh_external_witness_source",
                target="external_witness",
                blocking=True,
                age_s=witness_age_s,
                warning_window_s=witness_warning_window_s,
                freshness_window_s=witness_freshness_window_s,
            )
    elif witness_state == "error":
        _append_alert(
            alerts,
            code="external_witness_source_error",
            severity="error",
            detail=witness_detail or "external witness source refresh failed",
            action="check_external_witness_source",
            target="external_witness",
            blocking=True,
            age_s=witness_age_s,
            warning_window_s=witness_warning_window_s,
            freshness_window_s=witness_freshness_window_s,
        )
    elif witness_warning_due:
        _append_alert(
            alerts,
            code="external_witness_age_warning",
            severity="warning",
            detail="external witness source is current but approaching the freshness limit",
            action="refresh_external_witness_source",
            target="external_witness",
            blocking=False,
            age_s=witness_age_s,
            warning_window_s=witness_warning_window_s,
            freshness_window_s=witness_freshness_window_s,
        )
    if not transparency_configured:
        _append_alert(
            alerts,
            code="external_transparency_not_configured",
            severity="warning",
            detail="external transparency readback is not configured",
            action="configure_external_transparency_readback",
            target="external_transparency",
            blocking=False,
        )
    elif transparency_state == "stale":
        if any(
            marker in transparency_detail_lower
            for marker in (
                "head mismatch",
                "binding mismatch",
                "external ledger stale",
                "exported_at required",
            )
        ):
            _append_alert(
                alerts,
                code="external_transparency_stale",
                severity="stale",
                detail=transparency_detail or "external transparency ledger is stale or mismatched",
                action="republish_transparency_ledger",
                target="external_transparency",
                blocking=True,
                age_s=transparency_age_s,
                warning_window_s=transparency_warning_window_s,
                freshness_window_s=transparency_freshness_window_s,
            )
        else:
            _append_alert(
                alerts,
                code="external_transparency_readback_stale",
                severity="stale",
                detail=transparency_detail or "external transparency readback requires verification",
                action="verify_external_readback",
                target="external_transparency",
                blocking=True,
                age_s=transparency_age_s,
                warning_window_s=transparency_warning_window_s,
                freshness_window_s=transparency_freshness_window_s,
            )
    elif transparency_state == "error":
        _append_alert(
            alerts,
            code="external_transparency_readback_error",
            severity="error",
            detail=transparency_detail or "external transparency readback failed",
            action="check_external_transparency_readback",
            target="external_transparency",
            blocking=True,
            age_s=transparency_age_s,
            warning_window_s=transparency_warning_window_s,
            freshness_window_s=transparency_freshness_window_s,
        )
    elif transparency_warning_due:
        _append_alert(
            alerts,
            code="external_transparency_age_warning",
            severity="warning",
            detail="external transparency ledger is current but approaching the freshness limit",
            action="republish_transparency_ledger",
            target="external_transparency",
            blocking=False,
            age_s=transparency_age_s,
            warning_window_s=transparency_warning_window_s,
            freshness_window_s=transparency_freshness_window_s,
        )
    seen_actions: set[str] = set()
    deduped_actions: list[str] = []
    runbook_actions: list[dict[str, Any]] = []
    for alert in alerts:
        action = str(alert.get("action", "") or "").strip()
        target = str(alert.get("target", "") or "").strip()
        key = f"{action}:{target}"
        if action and action not in deduped_actions:
            deduped_actions.append(action)
        if not action or key in seen_actions:
            continue
        seen_actions.add(key)
        runbook_actions.append(
            {
                "action": action,
                "target": target,
                "severity": str(alert.get("severity", "warning") or "warning").strip(),
                "blocking": bool(alert.get("blocking", False)),
                "reason": str(alert.get("detail", "") or "").strip(),
            }
        )
    next_action = ""
    for item in runbook_actions:
        if item.get("blocking"):
            next_action = str(item.get("action", "") or "").strip()
            break
    if not next_action and runbook_actions:
        next_action = str(runbook_actions[0].get("action", "") or "").strip()
    blocking_alert_count = sum(1 for alert in alerts if bool(alert.get("blocking", False)))
    warning_alert_count = sum(
        1 for alert in alerts if str(alert.get("severity", "") or "").strip() == "warning"
    )
    return {
        "state": state,
        "detail": detail,
        "health_state": health_state,
        "witness_health_state": witness_health_state,
        "transparency_health_state": transparency_health_state,
        "external_assurance_current": external_assurance_current,
        "external_assurance_configured": bool(witness_configured and transparency_configured),
        "requires_attention": requires_attention,
        "strong_trust_blocked": strong_trust_blocked,
        "warning_due": bool(witness_warning_due or transparency_warning_due),
        "witness_warning_due": witness_warning_due,
        "transparency_warning_due": transparency_warning_due,
        "witness_warning_window_s": witness_warning_window_s,
        "transparency_warning_window_s": transparency_warning_window_s,
        "recommended_actions": deduped_actions,
        "next_action": next_action,
        "alerts": alerts,
        "alert_count": len(alerts),
        "blocking_alert_count": blocking_alert_count,
        "warning_alert_count": warning_alert_count,
        "runbook_actions": runbook_actions,
        "witness_state": witness_state,
        "witness_detail": witness_detail,
        "transparency_state": transparency_state,
        "transparency_detail": transparency_detail,
        "independent_quorum_met": bool(distribution.get("witness_independent_quorum_met", False)),
        "witness_configured": witness_configured,
        "transparency_configured": transparency_configured,
    }


def _dm_root_monitoring_view(summary: dict[str, Any]) -> dict[str, Any]:
    alerts = [dict(item or {}) for item in list(summary.get("alerts") or []) if isinstance(item, dict)]
    runbook_actions = [dict(item or {}) for item in list(summary.get("runbook_actions") or []) if isinstance(item, dict)]
    strong_trust_blocked = bool(summary.get("strong_trust_blocked", False))
    health_state = str(summary.get("health_state", "warning") or "warning").strip().lower()
    summary_state = str(summary.get("state", "local_cached_only") or "local_cached_only").strip().lower()
    if strong_trust_blocked or health_state in {"error", "stale"}:
        monitor_state = "critical"
    elif health_state == "warning":
        monitor_state = "warning"
    else:
        monitor_state = "ok"
    page_required = bool(monitor_state == "critical")
    ticket_required = bool(monitor_state == "warning" or page_required)
    primary_alert = next((item for item in alerts if bool(item.get("blocking", False))), alerts[0] if alerts else {})
    if page_required:
        status_line = "DM root external assurance is blocking strong trust and needs operator action"
    elif ticket_required:
        status_line = "DM root external assurance needs operator attention soon"
    else:
        status_line = "DM root external assurance is healthy"
    recommended_check_interval_s = 60 if page_required else 300 if ticket_required else 900
    return {
        "state": monitor_state,
        "page_required": page_required,
        "ticket_required": ticket_required,
        "runbook_required": bool(runbook_actions),
        "strong_trust_blocked": strong_trust_blocked,
        "status_line": status_line,
        "summary_state": summary_state,
        "summary_health_state": health_state,
        "primary_alert": primary_alert,
        "active_alert_codes": [
            str(item.get("code", "") or "").strip()
            for item in alerts
            if str(item.get("code", "") or "").strip()
        ],
        "recommended_check_interval_s": recommended_check_interval_s,
    }


def _dm_root_runbook_action_detail(
    action: str,
    *,
    target: str,
    severity: str,
    blocking: bool,
    reason: str,
) -> dict[str, Any]:
    action_key = str(action or "").strip()
    target_key = str(target or "").strip()
    severity_key = str(severity or "warning").strip().lower()
    templates: dict[str, dict[str, Any]] = {
        "configure_external_witness_source": {
            "title": "Configure external witness source",
            "summary": "Point DM root witness refresh at an independently managed witness package source.",
            "steps": [
                "Choose an external witness package source URI or file path that is managed outside the local runtime.",
                "Set MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI or MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_PATH.",
                "Confirm the source publishes descriptors and current-manifest receipts for the active root manifest.",
            ],
        },
        "reacquire_external_witness_receipts": {
            "title": "Reacquire external witness receipts",
            "summary": "Refresh current-manifest witness receipts so the active root manifest satisfies the external witness policy again.",
            "steps": [
                "Request fresh external witness receipts for the current published root manifest fingerprint.",
                "Restage the refreshed receipt package through the configured external witness source.",
                "Recheck /api/wormhole/dm/root-health until witness state returns to current.",
            ],
        },
        "refresh_external_witness_source": {
            "title": "Refresh external witness source",
            "summary": "Publish a fresh external witness package before the configured freshness window expires or after it has gone stale.",
            "steps": [
                "Regenerate or republish the external witness package with a fresh exported_at timestamp.",
                "Include any required current-manifest receipts for the active root manifest.",
                "Verify the configured source is readable and root health clears the warning or stale state.",
            ],
        },
        "check_external_witness_source": {
            "title": "Check external witness source",
            "summary": "Investigate why the configured external witness source is unreadable or invalid.",
            "steps": [
                "Verify the configured witness source URI or path is reachable from the backend.",
                "Validate the package schema, exported_at, descriptors, and manifest_fingerprint fields.",
                "Restore the source and confirm strong DM trust is no longer blocked.",
            ],
        },
        "configure_external_transparency_readback": {
            "title": "Configure external transparency readback",
            "summary": "Point DM root transparency verification at an externally published transparency ledger.",
            "steps": [
                "Choose an external transparency ledger readback URI or exported ledger path.",
                "Set MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI and, if needed, MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH.",
                "Verify the readback source exposes the current transparency binding for the active root manifest.",
            ],
        },
        "republish_transparency_ledger": {
            "title": "Republish transparency ledger",
            "summary": "Republish the stable-root transparency ledger so external readback reflects the current manifest and witness binding.",
            "steps": [
                "Publish a fresh transparency ledger export to the configured external location.",
                "Confirm the external ledger head and binding match the current manifest and witness set.",
                "Recheck /api/wormhole/dm/root-health until transparency state returns to current.",
            ],
        },
        "verify_external_readback": {
            "title": "Verify external transparency readback",
            "summary": "Investigate why external transparency readback is stale or incomplete for the current root binding.",
            "steps": [
                "Confirm the configured readback URI is reachable and serving the latest ledger export.",
                "Validate the exported ledger chain and current head binding fingerprint.",
                "Restore readback visibility and verify the health endpoint clears the transparency alert.",
            ],
        },
        "check_external_transparency_readback": {
            "title": "Check external transparency readback",
            "summary": "Investigate why the configured external transparency readback source is unreadable or invalid.",
            "steps": [
                "Verify the configured ledger readback URI or file path is reachable from the backend.",
                "Validate the exported ledger JSON and chain integrity at the source.",
                "Restore the source and confirm transparency verification returns to current.",
            ],
        },
    }
    template = dict(templates.get(action_key) or {})
    if blocking:
        urgency = "page"
    elif severity_key == "warning":
        urgency = "watch"
    else:
        urgency = "ticket"
    return {
        "action": action_key,
        "target": target_key,
        "severity": severity_key or "warning",
        "blocking": bool(blocking),
        "urgency": urgency,
        "title": str(template.get("title", action_key.replace("_", " ").title()) or action_key).strip(),
        "summary": str(template.get("summary", reason or action_key.replace("_", " ")) or "").strip(),
        "reason": str(reason or "").strip(),
        "steps": [str(step or "").strip() for step in list(template.get("steps") or []) if str(step or "").strip()],
        "owner": "dm_root_ops",
    }


def _dm_root_runbook_view(summary: dict[str, Any], monitoring: dict[str, Any]) -> dict[str, Any]:
    raw_actions = [dict(item or {}) for item in list(summary.get("runbook_actions") or []) if isinstance(item, dict)]
    enriched_actions = [
        _dm_root_runbook_action_detail(
            str(item.get("action", "") or "").strip(),
            target=str(item.get("target", "") or "").strip(),
            severity=str(item.get("severity", "warning") or "warning").strip(),
            blocking=bool(item.get("blocking", False)),
            reason=str(item.get("reason", "") or "").strip(),
        )
        for item in raw_actions
    ]
    next_action = str(summary.get("next_action", "") or "").strip()
    next_action_detail = next(
        (dict(item) for item in enriched_actions if str(item.get("action", "") or "").strip() == next_action),
        {},
    )
    monitor_state = str(monitoring.get("state", "warning") or "warning").strip().lower()
    summary_state = str(summary.get("state", "local_cached_only") or "local_cached_only").strip().lower()
    if monitor_state == "critical":
        urgency = "page"
    elif monitor_state == "warning" and summary_state == "local_cached_only":
        urgency = "ticket"
    elif monitor_state == "warning":
        urgency = "watch"
    else:
        urgency = "none"
    return {
        "attention_required": bool(summary.get("requires_attention", False)),
        "strong_trust_blocked": bool(summary.get("strong_trust_blocked", False)),
        "urgency": urgency,
        "status_line": str(monitoring.get("status_line", "") or "").strip(),
        "next_action": next_action,
        "next_action_detail": next_action_detail,
        "actions": enriched_actions,
    }


@app.get("/api/wormhole/dm/root-distribution", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_dm_root_distribution(request: Request):
    from services.mesh.mesh_wormhole_root_manifest import get_current_root_manifest
    from services.mesh.mesh_wormhole_root_transparency import get_current_root_transparency_record

    distribution = get_current_root_manifest()
    transparency = get_current_root_transparency_record(distribution=distribution)
    return {
        **distribution,
        "dm_root_operator_summary": _dm_root_operator_summary(distribution, transparency),
    }


@app.post("/api/wormhole/dm/root-witnesses/import", dependencies=[Depends(require_admin)])
@limiter.limit("20/minute")
async def api_wormhole_dm_root_witness_import(request: Request, body: WormholeRootWitnessImportRequest):
    from services.mesh.mesh_wormhole_root_manifest import import_external_root_witness_material

    return import_external_root_witness_material(dict(body.material or {}))


@app.post("/api/wormhole/dm/root-witnesses/import-config", dependencies=[Depends(require_admin)])
@limiter.limit("20/minute")
async def api_wormhole_dm_root_witness_import_config(
    request: Request, body: WormholeRootWitnessImportPathRequest
):
    from services.mesh.mesh_wormhole_root_manifest import import_external_root_witness_material_from_file

    return import_external_root_witness_material_from_file(path=str(body.path or "").strip() or None)


@app.get("/api/wormhole/dm/root-transparency", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_dm_root_transparency(request: Request):
    from services.mesh.mesh_wormhole_root_manifest import get_current_root_manifest
    from services.mesh.mesh_wormhole_root_transparency import get_current_root_transparency_record

    distribution = get_current_root_manifest()
    transparency = get_current_root_transparency_record(distribution=distribution)
    return {
        **transparency,
        "dm_root_operator_summary": _dm_root_operator_summary(distribution, transparency),
    }


@app.get("/api/wormhole/dm/root-health", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_dm_root_health(request: Request):
    from services.mesh.mesh_wormhole_root_manifest import get_current_root_manifest
    from services.mesh.mesh_wormhole_root_transparency import get_current_root_transparency_record

    distribution = get_current_root_manifest()
    transparency = get_current_root_transparency_record(distribution=distribution)
    summary = _dm_root_operator_summary(distribution, transparency)
    monitoring = _dm_root_monitoring_view(summary)
    runbook = _dm_root_runbook_view(summary, monitoring)
    return {
        "ok": True,
        "checked_at": int(time.time()),
        **summary,
        "monitoring": monitoring,
        "runbook": runbook,
        "witness": {
            "state": summary.get("witness_state", "not_configured"),
            "health_state": summary.get("witness_health_state", "warning"),
            "detail": summary.get("witness_detail", ""),
            "source_ref": str(distribution.get("external_witness_refresh_source_ref", "") or "").strip(),
            "source_scope": str(distribution.get("external_witness_source_scope", "") or "").strip(),
            "source_label": str(distribution.get("external_witness_source_label", "") or "").strip(),
            "age_s": _safe_int(distribution.get("external_witness_source_age_s", 0) or 0, 0),
            "warning_window_s": _safe_int(summary.get("witness_warning_window_s", 0) or 0, 0),
            "freshness_window_s": _safe_int(distribution.get("external_witness_freshness_window_s", 0) or 0, 0),
            "manifest_matches_current": bool(distribution.get("external_witness_manifest_matches_current", False)),
            "reacquire_required": bool(distribution.get("external_witness_reacquire_required", False)),
            "independent_quorum_met": bool(distribution.get("witness_independent_quorum_met", False)),
        },
        "transparency": {
            "state": summary.get("transparency_state", "not_configured"),
            "health_state": summary.get("transparency_health_state", "warning"),
            "detail": summary.get("transparency_detail", ""),
            "source_ref": str(transparency.get("ledger_readback_source_ref", "") or "").strip(),
            "export_path": str(transparency.get("ledger_export_path", "") or "").strip(),
            "age_s": _safe_int(transparency.get("ledger_readback_export_age_s", 0) or 0, 0),
            "warning_window_s": _safe_int(summary.get("transparency_warning_window_s", 0) or 0, 0),
            "freshness_window_s": _safe_int(transparency.get("ledger_freshness_window_s", 0) or 0, 0),
            "verification_required": bool(transparency.get("ledger_external_verification_required", False)),
        },
    }


@app.get("/api/wormhole/dm/root-health/runbook", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_dm_root_health_runbook(request: Request):
    from services.mesh.mesh_wormhole_root_manifest import get_current_root_manifest
    from services.mesh.mesh_wormhole_root_transparency import get_current_root_transparency_record

    distribution = get_current_root_manifest()
    transparency = get_current_root_transparency_record(distribution=distribution)
    summary = _dm_root_operator_summary(distribution, transparency)
    monitoring = _dm_root_monitoring_view(summary)
    return {
        "ok": True,
        "checked_at": int(time.time()),
        **_dm_root_runbook_view(summary, monitoring),
    }


@app.get("/api/wormhole/dm/root-health/alerts", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_dm_root_health_alerts(request: Request):
    from services.mesh.mesh_wormhole_root_manifest import get_current_root_manifest
    from services.mesh.mesh_wormhole_root_transparency import get_current_root_transparency_record

    distribution = get_current_root_manifest()
    transparency = get_current_root_transparency_record(distribution=distribution)
    summary = _dm_root_operator_summary(distribution, transparency)
    monitoring = _dm_root_monitoring_view(summary)
    return {
        "ok": True,
        "checked_at": int(time.time()),
        **monitoring,
        "alerts": [dict(item or {}) for item in list(summary.get("alerts") or []) if isinstance(item, dict)],
        "alert_count": _safe_int(summary.get("alert_count", 0) or 0, 0),
        "blocking_alert_count": _safe_int(summary.get("blocking_alert_count", 0) or 0, 0),
        "warning_alert_count": _safe_int(summary.get("warning_alert_count", 0) or 0, 0),
        "next_action": str(summary.get("next_action", "") or "").strip(),
        "runbook_actions": [dict(item or {}) for item in list(summary.get("runbook_actions") or []) if isinstance(item, dict)],
    }


@app.get("/api/wormhole/dm/root-transparency/ledger", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_dm_root_transparency_ledger(request: Request, max_records: int = Query(64, ge=1, le=256)):
    from services.mesh.mesh_wormhole_root_transparency import export_root_transparency_ledger

    return export_root_transparency_ledger(max_records=_safe_int(max_records or 64, 64))


@app.post("/api/wormhole/dm/root-transparency/ledger/publish", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def api_wormhole_dm_root_transparency_ledger_publish(
    request: Request, body: WormholeRootTransparencyLedgerPublishRequest
):
    from services.mesh.mesh_wormhole_root_transparency import publish_root_transparency_ledger_to_file

    return publish_root_transparency_ledger_to_file(
        path=str(body.path or "").strip() or None,
        max_records=_safe_int(body.max_records or 64, 64),
    )


@app.get("/api/wormhole/dm/root-transparency/ledger/published", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_dm_root_transparency_ledger_published(request: Request, path: str = Query("")):
    from services.mesh.mesh_wormhole_root_transparency import read_exported_root_transparency_ledger

    return read_exported_root_transparency_ledger(path=str(path or "").strip() or None)


@app.post("/api/wormhole/sign", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_sign(request: Request, body: WormholeSignRequest):
    event_type = str(body.event_type or "")
    payload = dict(body.payload or {})
    if event_type.startswith("dm_"):
        return sign_wormhole_event(
            event_type=event_type,
            payload=payload,
            sequence=body.sequence,
        )
    gate_id = str(body.gate_id or "").strip().lower()
    if gate_id:
        signed = sign_gate_wormhole_event(
            gate_id=gate_id,
            event_type=event_type,
            payload=payload,
            sequence=body.sequence,
        )
        if not signed.get("signature"):
            raise HTTPException(status_code=400, detail=str(signed.get("detail") or "wormhole_gate_sign_failed"))
        return signed
    return sign_public_wormhole_event(
        event_type=event_type,
        payload=payload,
        sequence=body.sequence,
    )


@app.post("/api/wormhole/gate/enter", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def api_wormhole_gate_enter(request: Request, body: WormholeGateRequest):
    gate_id = str(body.gate_id or "")
    result = enter_gate_anonymously(gate_id, rotate=bool(body.rotate))
    if result.get("ok"):
        snapshot = export_gate_state_snapshot(gate_id)
        if snapshot.get("ok"):
            result["gate_state_snapshot"] = snapshot
        else:
            result["gate_state_snapshot_error"] = str(snapshot.get("detail") or "gate_state_export_failed")
    return result


@app.post("/api/wormhole/gate/leave", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def api_wormhole_gate_leave(request: Request, body: WormholeGateRequest):
    return leave_gate(str(body.gate_id or ""))


@app.get("/api/wormhole/gate/{gate_id}/identity", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_identity(request: Request, gate_id: str):
    return get_active_gate_identity(gate_id)


@app.get("/api/wormhole/gate/{gate_id}/personas", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_personas(request: Request, gate_id: str):
    return list_gate_personas(gate_id)


@app.get("/api/wormhole/gate/{gate_id}/key", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_key_status(request: Request, gate_id: str):
    exposure = metadata_exposure_for_request(request, authenticated=True)
    return gate_repair_status_snapshot(gate_id, exposure=exposure)


@app.post("/api/wormhole/gate/key/rotate", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_wormhole_gate_key_rotate(request: Request, body: WormholeGateRotateRequest):
    gate_id = str(body.gate_id or "")
    result = rotate_gate_epoch(
        gate_id=gate_id,
        reason=str(body.reason or "manual_rotate"),
    )
    if result.get("ok"):
        snapshot = export_gate_state_snapshot(gate_id)
        if snapshot.get("ok"):
            result["gate_state_snapshot"] = snapshot
        else:
            result["gate_state_snapshot_error"] = str(snapshot.get("detail") or "gate_state_export_failed")
    return result


@app.post("/api/wormhole/gate/persona/create", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def api_wormhole_gate_persona_create(
    request: Request, body: WormholeGatePersonaCreateRequest
):
    gate_id = str(body.gate_id or "")
    result = create_gate_persona(gate_id, label=str(body.label or ""))
    if result.get("ok"):
        snapshot = export_gate_state_snapshot(gate_id)
        if snapshot.get("ok"):
            result["gate_state_snapshot"] = snapshot
        else:
            result["gate_state_snapshot_error"] = str(snapshot.get("detail") or "gate_state_export_failed")
    return result


@app.post("/api/wormhole/gate/persona/activate", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def api_wormhole_gate_persona_activate(
    request: Request, body: WormholeGatePersonaActivateRequest
):
    gate_id = str(body.gate_id or "")
    result = activate_gate_persona(gate_id, str(body.persona_id or ""))
    if result.get("ok"):
        snapshot = export_gate_state_snapshot(gate_id)
        if snapshot.get("ok"):
            result["gate_state_snapshot"] = snapshot
        else:
            result["gate_state_snapshot_error"] = str(snapshot.get("detail") or "gate_state_export_failed")
    return result


@app.post("/api/wormhole/gate/persona/clear", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def api_wormhole_gate_persona_clear(request: Request, body: WormholeGateRequest):
    gate_id = str(body.gate_id or "")
    result = clear_active_gate_persona(gate_id)
    if result.get("ok"):
        snapshot = export_gate_state_snapshot(gate_id)
        if snapshot.get("ok"):
            result["gate_state_snapshot"] = snapshot
        else:
            result["gate_state_snapshot_error"] = str(snapshot.get("detail") or "gate_state_export_failed")
    return result


@app.post("/api/wormhole/gate/persona/retire", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def api_wormhole_gate_persona_retire(
    request: Request, body: WormholeGatePersonaActivateRequest
):
    gate_id = str(body.gate_id or "")
    result = retire_gate_persona(gate_id, str(body.persona_id or ""))
    if result.get("ok"):
        result["gate_key_status"] = mark_gate_rekey_recommended(
            gate_id,
            reason="persona_retired",
        )
        snapshot = export_gate_state_snapshot(gate_id)
        if snapshot.get("ok"):
            result["gate_state_snapshot"] = snapshot
        else:
            result["gate_state_snapshot_error"] = str(snapshot.get("detail") or "gate_state_export_failed")
    return result


@app.post("/api/wormhole/gate/key/grant", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def api_wormhole_gate_key_grant(request: Request, body: WormholeGateKeyGrantRequest):
    return ensure_gate_member_access(
        gate_id=str(body.gate_id or ""),
        recipient_node_id=str(body.recipient_node_id or ""),
        recipient_dh_pub=str(body.recipient_dh_pub or ""),
        recipient_scope=str(body.recipient_scope or "member"),
    )


def _backend_gate_plaintext_guard(
    *,
    gate_id: str,
    compat_plaintext: bool,
) -> dict[str, Any] | None:
    # These endpoints are already guarded by require_local_operator and are
    # the atomic local-control path that encrypts/signs before append. They
    # must remain available as the durable-envelope recovery path when the
    # browser/native split cannot carry gate_envelope material.
    return None


def _backend_gate_encrypted_reply_to_guard(
    *,
    gate_id: str,
    reply_to: str,
    compat_reply_to: bool,
) -> dict[str, Any] | None:
    reply_to_val = str(reply_to or "").strip()
    if not reply_to_val or compat_reply_to:
        return None
    return {
        "ok": False,
        "detail": "gate_encrypted_reply_to_hidden_required",
        "gate_id": gate_id,
        "compat_reply_to": False,
    }


@app.post("/api/wormhole/gate/message/compose", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_message_compose(request: Request, body: WormholeGateComposeRequest):
    blocked = _backend_gate_plaintext_guard(
        gate_id=str(body.gate_id or ""),
        compat_plaintext=bool(body.compat_plaintext),
    )
    if blocked is not None:
        return blocked
    composed = compose_gate_message_with_repair(
        gate_id=str(body.gate_id or ""),
        plaintext=str(body.plaintext or ""),
        reply_to=str(body.reply_to or ""),
    )
    if composed.get("ok") and _is_debug_test_request(request):
        return {**dict(composed), "epoch": composed.get("epoch", 0)}
    if composed.get("ok"):
        return _redact_composed_gate_message(composed)
    return composed


@app.post("/api/wormhole/gate/message/sign-encrypted", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_message_sign_encrypted(
    request: Request,
    body: WormholeGateEncryptedSignRequest,
):
    blocked = _backend_gate_encrypted_reply_to_guard(
        gate_id=str(body.gate_id or ""),
        reply_to=str(body.reply_to or ""),
        compat_reply_to=bool(body.compat_reply_to),
    )
    if blocked is not None:
        return blocked
    signed = sign_gate_message_with_repair(
        gate_id=str(body.gate_id or ""),
        epoch=_safe_int(body.epoch or 0),
        ciphertext=str(body.ciphertext or ""),
        nonce=str(body.nonce or ""),
        payload_format=str(body.format or "mls1"),
        reply_to=str(body.reply_to or ""),
        compat_reply_to=bool(body.compat_reply_to),
        recovery_plaintext=str(getattr(body, "recovery_plaintext", "") or ""),
        envelope_hash=str(body.envelope_hash or ""),
        transport_lock=str(getattr(body, "transport_lock", "private_strong") or "private_strong"),
    )
    if signed.get("ok") and _is_debug_test_request(request):
        return signed
    if signed.get("ok"):
        return _redact_signed_gate_message(signed)
    return signed


@app.post("/api/wormhole/gate/message/post-encrypted", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_message_post_encrypted(
    request: Request,
    body: WormholeGateEncryptedPostRequest,
):
    blocked = _backend_gate_encrypted_reply_to_guard(
        gate_id=str(body.gate_id or ""),
        reply_to=str(body.reply_to or ""),
        compat_reply_to=bool(body.compat_reply_to),
    )
    if blocked is not None:
        return blocked
    return _submit_gate_message_envelope(
        request,
        str(body.gate_id or ""),
        {
            "sender_id": str(body.sender_id or ""),
            "public_key": str(body.public_key or ""),
            "public_key_algo": str(body.public_key_algo or ""),
            "signature": str(body.signature or ""),
            "sequence": _safe_int(body.sequence or 0),
            "protocol_version": str(body.protocol_version or ""),
            "epoch": _safe_int(body.epoch or 0),
            "ciphertext": str(body.ciphertext or ""),
            "nonce": str(body.nonce or ""),
            "sender_ref": str(body.sender_ref or ""),
            "format": str(body.format or "mls1"),
            "gate_envelope": str(body.gate_envelope or ""),
            "envelope_hash": str(body.envelope_hash or ""),
            "transport_lock": str(getattr(body, "transport_lock", "private_strong") or "private_strong"),
            "reply_to": str(body.reply_to or ""),
        },
    )


@app.post("/api/wormhole/gate/message/post", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_message_post(request: Request, body: WormholeGateComposeRequest):
    blocked = _backend_gate_plaintext_guard(
        gate_id=str(body.gate_id or ""),
        compat_plaintext=bool(body.compat_plaintext),
    )
    if blocked is not None:
        return blocked
    composed = compose_gate_message_with_repair(
        gate_id=str(body.gate_id or ""),
        plaintext=str(body.plaintext or ""),
        reply_to=str(body.reply_to or ""),
    )
    if not composed.get("ok"):
        return composed
    reply_to = str(body.reply_to or "").strip()
    return _submit_gate_message_envelope(
        request,
        str(body.gate_id or ""),
        {
            "sender_id": composed.get("sender_id", ""),
            "public_key": composed.get("public_key", ""),
            "public_key_algo": composed.get("public_key_algo", ""),
            "signature": composed.get("signature", ""),
            "sequence": composed.get("sequence", 0),
            "protocol_version": composed.get("protocol_version", ""),
            "epoch": composed.get("epoch", 0),
            "ciphertext": composed.get("ciphertext", ""),
            "nonce": composed.get("nonce", ""),
            "sender_ref": composed.get("sender_ref", ""),
            "format": composed.get("format", "mls1"),
            "gate_envelope": composed.get("gate_envelope", ""),
            "envelope_hash": composed.get("envelope_hash", ""),
            "transport_lock": composed.get("transport_lock", "private_strong"),
            "reply_to": reply_to,
        },
    )


def _backend_gate_decrypt_guard(
    *,
    gate_id: str,
    payload_format: str,
    recovery_envelope: bool,
    compat_decrypt: bool,
) -> dict[str, Any] | None:
    normalized_format = str(payload_format or "mls1").strip().lower() or "mls1"
    if normalized_format != "mls1" or recovery_envelope:
        return None
    return {
        "ok": False,
        "detail": "gate_backend_decrypt_recovery_only",
        "gate_id": gate_id,
        "compat_requested": bool(compat_decrypt),
        "compat_effective": False,
    }


@app.post("/api/wormhole/gate/message/decrypt", dependencies=[Depends(require_local_operator)])
@limiter.limit("60/minute")
async def api_wormhole_gate_message_decrypt(request: Request, body: WormholeGateDecryptRequest):
    payload_format = str(body.format or "mls1").strip().lower()
    # format field is trusted here because it originates from the Infonet chain event,
    # not from arbitrary client input.
    gate_id = str(body.gate_id or "")
    if payload_format != "mls1" and is_gate_mls_locked(gate_id):
        return {
            "ok": False,
            "detail": "gate is locked to MLS format",
            "gate_id": gate_id,
            "required_format": "mls1",
            "current_format": payload_format or "mls1",
        }
    blocked = _backend_gate_decrypt_guard(
        gate_id=gate_id,
        payload_format=payload_format,
        recovery_envelope=bool(body.recovery_envelope),
        compat_decrypt=bool(body.compat_decrypt),
    )
    if blocked is not None:
        return blocked
    return decrypt_gate_message_with_repair(
        gate_id=gate_id,
        epoch=_safe_int(body.epoch or 0),
        ciphertext=str(body.ciphertext or ""),
        nonce=str(body.nonce or ""),
        sender_ref=str(body.sender_ref or ""),
        gate_envelope=str(body.gate_envelope or ""),
        envelope_hash=str(body.envelope_hash or ""),
        recovery_envelope=bool(body.recovery_envelope),
        event_id=str(body.event_id or ""),
    )


@app.post("/api/wormhole/gate/messages/decrypt", dependencies=[Depends(require_local_operator)])
@limiter.limit("60/minute")
async def api_wormhole_gate_messages_decrypt(request: Request, body: WormholeGateDecryptBatchRequest):
    items = list(body.messages or [])
    if not items:
        return {"ok": False, "detail": "messages required", "results": []}
    if len(items) > 100:
        return {"ok": False, "detail": "too many messages", "results": []}

    results: list[dict[str, Any]] = []
    for item in items:
        payload_format = str(item.format or "mls1").strip().lower()
        gate_id = str(item.gate_id or "")
        if payload_format != "mls1" and is_gate_mls_locked(gate_id):
            results.append(
                {
                    "ok": False,
                    "detail": "gate is locked to MLS format",
                    "gate_id": gate_id,
                    "required_format": "mls1",
                    "current_format": payload_format or "mls1",
                }
            )
            continue
        blocked = _backend_gate_decrypt_guard(
            gate_id=gate_id,
            payload_format=payload_format,
            recovery_envelope=bool(item.recovery_envelope),
            compat_decrypt=bool(item.compat_decrypt),
        )
        if blocked is not None:
            results.append(blocked)
            continue
        results.append(
            decrypt_gate_message_with_repair(
                gate_id=gate_id,
                epoch=_safe_int(item.epoch or 0),
                ciphertext=str(item.ciphertext or ""),
                nonce=str(item.nonce or ""),
                sender_ref=str(item.sender_ref or ""),
                gate_envelope=str(item.gate_envelope or ""),
                envelope_hash=str(item.envelope_hash or ""),
                recovery_envelope=bool(item.recovery_envelope),
                event_id=str(item.event_id or ""),
            )
        )
    return {"ok": True, "results": results}


@app.post("/api/wormhole/gate/state/export", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_state_export(request: Request, body: WormholeGateRequest):
    return export_gate_state_snapshot_with_repair(str(body.gate_id or ""))


@app.post("/api/wormhole/gate/proof", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_proof(request: Request, body: WormholeGateRequest):
    proof = _sign_gate_access_proof(str(body.gate_id or ""))
    if not proof.get("ok"):
        raise HTTPException(status_code=403, detail=str(proof.get("detail") or "gate_access_proof_failed"))
    return proof


@app.post("/api/wormhole/sign-raw", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_sign_raw(request: Request, body: WormholeSignRawRequest):
    return sign_wormhole_message(str(body.message or ""))


@app.post("/api/wormhole/dm/register-key", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_wormhole_dm_register_key(request: Request):
    result = register_wormhole_dm_key()
    prekeys = register_wormhole_prekey_bundle()
    response = {
        **result,
        "dm_key_ok": bool(result.get("ok")),
        "dm_key_detail": result,
        "prekeys_ok": bool(prekeys.get("ok")),
        "prekey_detail": prekeys,
        "dm_ready": bool(result.get("ok")) and bool(prekeys.get("ok")),
    }
    if not response.get("ok") and prekeys.get("ok"):
        response["ok"] = False
    return response


@app.post("/api/wormhole/dm/prekey/register", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_wormhole_dm_prekey_register(request: Request):
    dm_key = register_wormhole_dm_key()
    prekeys = register_wormhole_prekey_bundle()
    response = {
        **prekeys,
        "dm_key_ok": bool(dm_key.get("ok")),
        "dm_key_detail": dm_key,
        "prekeys_ok": bool(prekeys.get("ok")),
        "prekey_detail": prekeys,
        "dm_ready": bool(dm_key.get("ok")) and bool(prekeys.get("ok")),
    }
    if not response.get("ok") and dm_key.get("ok"):
        response["ok"] = False
    return response


@app.post("/api/wormhole/dm/bootstrap-encrypt", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_bootstrap_encrypt(request: Request, body: WormholeDmBootstrapEncryptRequest):
    result = bootstrap_encrypt_for_peer(
        peer_id=str(body.peer_id or ""),
        plaintext=str(body.plaintext or ""),
    )
    if isinstance(result, dict) and "trust_level" not in result:
        result["trust_level"] = _get_contact_trust_level(str(body.peer_id or ""))
    return result


@app.post("/api/wormhole/dm/bootstrap-decrypt", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_bootstrap_decrypt(request: Request, body: WormholeDmBootstrapDecryptRequest):
    result = bootstrap_decrypt_from_sender(
        sender_id=str(body.sender_id or ""),
        ciphertext=str(body.ciphertext or ""),
    )
    if isinstance(result, dict) and "trust_level" not in result:
        result["trust_level"] = _get_contact_trust_level(str(body.sender_id or ""))
    return result


@app.post("/api/wormhole/dm/sender-token", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_sender_token(request: Request, body: WormholeDmSenderTokenRequest):
    if _safe_int(body.count or 1, 1) > 1:
        return issue_wormhole_dm_sender_tokens(
            recipient_id=str(body.recipient_id or ""),
            delivery_class=str(body.delivery_class or ""),
            recipient_token=str(body.recipient_token or ""),
            count=_safe_int(body.count or 1, 1),
        )
    return issue_wormhole_dm_sender_token(
        recipient_id=str(body.recipient_id or ""),
        delivery_class=str(body.delivery_class or ""),
        recipient_token=str(body.recipient_token or ""),
    )


@app.post("/api/wormhole/dm/open-seal", dependencies=[Depends(require_admin)])
@limiter.limit("120/minute")
async def api_wormhole_dm_open_seal(request: Request, body: WormholeOpenSealRequest):
    return open_sender_seal(
        sender_seal=str(body.sender_seal or ""),
        candidate_dh_pub=str(body.candidate_dh_pub or ""),
        recipient_id=str(body.recipient_id or ""),
        expected_msg_id=str(body.expected_msg_id or ""),
    )


@app.post("/api/wormhole/dm/build-seal", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_build_seal(request: Request, body: WormholeBuildSealRequest):
    return build_sender_seal(
        recipient_id=str(body.recipient_id or ""),
        recipient_dh_pub=str(body.recipient_dh_pub or ""),
        msg_id=str(body.msg_id or ""),
        timestamp=_safe_int(body.timestamp or 0),
    )


@app.post("/api/wormhole/dm/dead-drop-token", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_dead_drop_token(request: Request, body: WormholeDeadDropTokenRequest):
    try:
        return derive_dead_drop_token_pair(
            peer_id=str(body.peer_id or ""),
            peer_dh_pub=str(body.peer_dh_pub or ""),
            peer_ref=str(body.peer_ref or ""),
        )
    except Exception as exc:
        logger.exception("wormhole dm dead-drop token derivation failed")
        return {"ok": False, "detail": str(exc) or "dead_drop_token_failed"}


@app.post("/api/wormhole/dm/pairwise-alias", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_pairwise_alias(request: Request, body: WormholePairwiseAliasRequest):
    return issue_pairwise_dm_alias(
        peer_id=str(body.peer_id or ""),
        peer_dh_pub=str(body.peer_dh_pub or ""),
    )


@app.post("/api/wormhole/dm/pairwise-alias/rotate", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_pairwise_alias_rotate(
    request: Request, body: WormholePairwiseAliasRotateRequest
):
    return rotate_pairwise_dm_alias(
        peer_id=str(body.peer_id or ""),
        peer_dh_pub=str(body.peer_dh_pub or ""),
        grace_ms=_safe_int(body.grace_ms or PAIRWISE_ALIAS_GRACE_DEFAULT_MS, PAIRWISE_ALIAS_GRACE_DEFAULT_MS),
        reason=str(body.reason or AliasRotationReason.MANUAL.value),
    )


@app.post("/api/wormhole/dm/dead-drop-tokens", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_dead_drop_tokens(request: Request, body: WormholeDeadDropContactsRequest):
    try:
        return derive_dead_drop_tokens_for_contacts(
            contacts=list(body.contacts or []),
            limit=_safe_int(body.limit or 24, 24),
        )
    except Exception as exc:
        logger.exception("wormhole dm dead-drop token batch derivation failed")
        return {"ok": False, "detail": str(exc) or "dead_drop_tokens_failed", "tokens": []}


@app.post("/api/wormhole/dm/sas", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_sas(request: Request, body: WormholeSasRequest):
    return derive_sas_phrase(
        peer_id=str(body.peer_id or ""),
        peer_dh_pub=str(body.peer_dh_pub or ""),
        words=_safe_int(body.words or 8, 8),
        peer_ref=str(body.peer_ref or ""),
    )


@app.post("/api/wormhole/dm/sas/confirm", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_sas_confirm(request: Request, body: WormholeSasConfirmRequest):
    from services.mesh.mesh_wormhole_contacts import confirm_sas_verification
    return confirm_sas_verification(
        peer_id=str(body.peer_id or ""),
        sas_phrase=str(body.sas_phrase or ""),
        peer_ref=str(body.peer_ref or ""),
        words=_safe_int(body.words or 8, 8),
    )


@app.post("/api/wormhole/dm/sas/acknowledge", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_sas_acknowledge(request: Request, body: WormholeSasConfirmRequest):
    from services.mesh.mesh_wormhole_contacts import acknowledge_changed_fingerprint
    return acknowledge_changed_fingerprint(peer_id=str(body.peer_id or ""))


@app.post("/api/wormhole/dm/sas/recover-root", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_sas_recover_root(request: Request, body: WormholeSasConfirmRequest):
    from services.mesh.mesh_wormhole_contacts import recover_verified_root_continuity

    return recover_verified_root_continuity(
        peer_id=str(body.peer_id or ""),
        sas_phrase=str(body.sas_phrase or ""),
        peer_ref=str(body.peer_ref or ""),
        words=_safe_int(body.words or 8, 8),
    )


@app.post("/api/wormhole/dm/encrypt", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_encrypt(request: Request, body: WormholeDmEncryptRequest):
    return compose_wormhole_dm(
        peer_id=str(body.peer_id or ""),
        peer_dh_pub=str(body.peer_dh_pub or ""),
        plaintext=str(body.plaintext or ""),
        local_alias=body.local_alias,
        remote_alias=body.remote_alias,
        remote_prekey_bundle=dict(body.remote_prekey_bundle or {}),
    )


@app.post("/api/wormhole/dm/compose", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_compose(request: Request, body: WormholeDmComposeRequest):
    return compose_wormhole_dm(
        peer_id=str(body.peer_id or ""),
        peer_dh_pub=str(body.peer_dh_pub or ""),
        plaintext=str(body.plaintext or ""),
        local_alias=body.local_alias,
        remote_alias=body.remote_alias,
        remote_prekey_bundle=dict(body.remote_prekey_bundle or {}),
    )


@app.post("/api/wormhole/dm/decrypt", dependencies=[Depends(require_admin)])
@limiter.limit("120/minute")
async def api_wormhole_dm_decrypt(request: Request, body: WormholeDmDecryptRequest):
    return decrypt_wormhole_dm_envelope(
        peer_id=str(body.peer_id or ""),
        ciphertext=str(body.ciphertext or ""),
        payload_format=str(body.format or "dm1"),
        nonce=str(body.nonce or ""),
        local_alias=body.local_alias,
        remote_alias=body.remote_alias,
        session_welcome=body.session_welcome,
    )


@app.post("/api/wormhole/dm/reset", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_reset(request: Request, body: WormholeDmResetRequest):
    return reset_wormhole_dm_ratchet(
        peer_id=str(body.peer_id or "").strip() or None,
    )


@app.get("/api/wormhole/dm/contacts", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_contacts(request: Request):
    from services.mesh.mesh_wormhole_contacts import list_wormhole_dm_contacts

    try:
        return {"ok": True, "contacts": list_wormhole_dm_contacts()}
    except Exception as exc:
        logger.exception("wormhole dm contacts fetch failed")
        raise HTTPException(status_code=500, detail="wormhole_dm_contacts_failed") from exc


@app.put("/api/wormhole/dm/contact", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_contact_put(request: Request):
    body = await request.json()
    peer_id = str(body.get("peer_id", "") or "").strip()
    updates = body.get("contact", {})
    if not peer_id:
        return {"ok": False, "detail": "peer_id required"}
    if not isinstance(updates, dict):
        return {"ok": False, "detail": "contact must be an object"}
    from services.mesh.mesh_wormhole_contacts import upsert_wormhole_dm_contact

    try:
        contact = upsert_wormhole_dm_contact(peer_id, updates)
    except ValueError as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": True, "peer_id": peer_id, "contact": contact}


@app.delete("/api/wormhole/dm/contact/{peer_id}", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_contact_delete(request: Request, peer_id: str):
    from services.mesh.mesh_wormhole_contacts import delete_wormhole_dm_contact

    deleted = delete_wormhole_dm_contact(peer_id)
    return {"ok": True, "peer_id": peer_id, "deleted": deleted}


_WORMHOLE_PUBLIC_FIELDS = {"installed", "configured", "running", "ready"}


def _redact_wormhole_status(state: dict[str, Any], authenticated: bool) -> dict[str, Any]:
    if authenticated:
        return state
    return {k: v for k, v in state.items() if k in _WORMHOLE_PUBLIC_FIELDS}


@app.get("/api/wormhole/status")
@limiter.limit("30/minute")
async def api_wormhole_status(request: Request):
    state = await asyncio.to_thread(get_wormhole_state)
    transport_tier = _current_private_lane_tier(state)
    if (
        transport_tier == "public_degraded"
        and bool(state.get("arti_ready"))
        and _is_debug_test_request(request)
    ):
        transport_tier = "private_strong"
    try:
        from services.config import (
            private_clearnet_fallback_effective,
            private_clearnet_fallback_requested,
        )

        _fallback_policy = private_clearnet_fallback_effective(get_settings())
        _fallback_requested = private_clearnet_fallback_requested(get_settings())
    except Exception:
        _fallback_policy = "block"
        _fallback_requested = "block"
    full_state = {
        **state,
        "transport_tier": transport_tier,
        "clearnet_fallback_policy": _fallback_policy,
        "clearnet_fallback_requested": _fallback_requested,
    }
    _resume_private_delivery_background_work(
        current_tier=transport_tier,
        reason="startup_resume",
    )
    full_state["private_lane_readiness"] = private_transport_manager.observe_state(
        current_tier=transport_tier,
    )
    full_state["local_custody"] = local_custody_status_snapshot()
    ok, _detail = _check_scoped_auth(request, "wormhole")
    if not ok:
        ok = _is_debug_test_request(request)
    contact_preference_refresh = (
        await asyncio.to_thread(_upgrade_invite_scoped_contact_preferences_background)
        if ok
        else {"ok": False, "upgraded_contacts": 0}
    )
    rotation_refresh = (
        await asyncio.to_thread(
            _refresh_lookup_handle_rotation_background,
            reason="status_surface",
        )
        if ok
        else {"ok": False, "rotated": False}
    )
    try:
        lookup_rotation_snapshot = lookup_handle_rotation_status_snapshot()
    except Exception:
        lookup_rotation_snapshot = {
            "state": "lookup_handle_rotation_unknown",
            "detail": "lookup handle rotation status unavailable",
            "checked_at": 0,
            "last_success_at": 0,
            "last_failure_at": 0,
            "active_handle_count": 0,
            "fresh_handle_available": False,
        }
    full_state["lookup_handle_rotation"] = {
        **lookup_rotation_snapshot,
        "last_refresh_ok": bool(rotation_refresh.get("ok", False)),
    }
    private_delivery_exposure = metadata_exposure_for_request(
        request,
        authenticated=ok,
    )
    compatibility_readiness: dict[str, Any] = {}
    gate_privilege_access: dict[str, Any] = {}
    if ok:
        full_state["private_delivery"] = private_delivery_outbox.summary(
            current_tier=transport_tier,
            exposure=private_delivery_exposure,
        )
        privacy_core = _privacy_core_status()
        diagnostic_package = _diagnostic_review_package_snapshot(
            current_tier=transport_tier,
            local_custody=full_state.get("local_custody"),
            privacy_core=privacy_core,
            contact_preference_refresh=contact_preference_refresh,
            lookup_handle_rotation=full_state.get("lookup_handle_rotation"),
        )
        claim_surface = dict(diagnostic_package.get("claim_surface") or {})
        gate_privilege_access = dict(claim_surface.get("gate_privilege_access") or {})
        full_state["gate_privilege_access"] = gate_privilege_access
        compatibility_readiness = dict(
            claim_surface.get("compatibility_readiness") or {}
        )
        full_state["compatibility_debt"] = dict(
            claim_surface.get("compatibility_debt") or {}
        )
        full_state["compatibility_readiness"] = compatibility_readiness
        full_state["privacy_core"] = privacy_core
        full_state["strong_claims"] = diagnostic_package.get("strong_claims")
        full_state["release_gate"] = diagnostic_package.get("release_gate")
        full_state["privacy_status"] = diagnostic_package.get("privacy_status")
        if private_delivery_exposure == "diagnostic":
            compatibility_snapshot = dict(claim_surface.get("compatibility_snapshot") or {})
            if compatibility_snapshot:
                full_state["legacy_compatibility"] = compatibility_snapshot
            full_state["privacy_claims"] = claim_surface.get("privacy_claims")
            full_state["rollout_readiness"] = diagnostic_package.get("rollout_readiness")
            full_state["rollout_controls"] = diagnostic_package.get("rollout_controls")
            full_state["rollout_health"] = diagnostic_package.get("rollout_health")
            full_state["claim_surface_sources"] = diagnostic_package.get("claim_surface_sources")
            full_state["review_export"] = diagnostic_package.get("review_export")
            full_state["final_review_bundle"] = diagnostic_package.get("final_review_bundle")
            full_state["staged_rollout_telemetry"] = diagnostic_package.get("staged_rollout_telemetry")
            full_state["release_claims_matrix"] = diagnostic_package.get("release_claims_matrix")
            full_state["release_checklist"] = diagnostic_package.get("release_checklist")
    return _redact_wormhole_status(full_state, authenticated=ok)


@app.get("/api/wormhole/review-export", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_review_export(request: Request):
    state = await asyncio.to_thread(get_wormhole_state)
    transport_tier = _current_private_lane_tier(state)
    if (
        transport_tier == "public_degraded"
        and bool(state.get("arti_ready"))
        and _is_debug_test_request(request)
    ):
        transport_tier = "private_strong"
    contact_preference_refresh = await asyncio.to_thread(
        _upgrade_invite_scoped_contact_preferences_background
    )
    rotation_refresh = await asyncio.to_thread(
        _refresh_lookup_handle_rotation_background,
        reason="review_export_surface",
    )
    lookup_handle_rotation = {
        **lookup_handle_rotation_status_snapshot(),
        "last_refresh_ok": bool(rotation_refresh.get("ok", False)),
    }
    diagnostic_package = _diagnostic_review_package_snapshot(
        current_tier=transport_tier,
        local_custody=local_custody_status_snapshot(),
        privacy_core=_privacy_core_status(),
        contact_preference_refresh=contact_preference_refresh,
        lookup_handle_rotation=lookup_handle_rotation,
    )
    return diagnostic_package.get("explicit_review_export", {})


@app.get("/api/wormhole/review-manifest", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_review_manifest(request: Request):
    state = await asyncio.to_thread(get_wormhole_state)
    transport_tier = _current_private_lane_tier(state)
    if (
        transport_tier == "public_degraded"
        and bool(state.get("arti_ready"))
        and _is_debug_test_request(request)
    ):
        transport_tier = "private_strong"
    contact_preference_refresh = await asyncio.to_thread(
        _upgrade_invite_scoped_contact_preferences_background
    )
    rotation_refresh = await asyncio.to_thread(
        _refresh_lookup_handle_rotation_background,
        reason="review_manifest_surface",
    )
    lookup_handle_rotation = {
        **lookup_handle_rotation_status_snapshot(),
        "last_refresh_ok": bool(rotation_refresh.get("ok", False)),
    }
    diagnostic_package = _diagnostic_review_package_snapshot(
        current_tier=transport_tier,
        local_custody=local_custody_status_snapshot(),
        privacy_core=_privacy_core_status(),
        contact_preference_refresh=contact_preference_refresh,
        lookup_handle_rotation=lookup_handle_rotation,
    )
    return _review_manifest_status(
        explicit_review_export=diagnostic_package.get("explicit_review_export"),
    )


@app.get("/api/wormhole/review-consistency", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_review_consistency(request: Request):
    state = await asyncio.to_thread(get_wormhole_state)
    transport_tier = _current_private_lane_tier(state)
    if (
        transport_tier == "public_degraded"
        and bool(state.get("arti_ready"))
        and _is_debug_test_request(request)
    ):
        transport_tier = "private_strong"
    contact_preference_refresh = await asyncio.to_thread(
        _upgrade_invite_scoped_contact_preferences_background
    )
    rotation_refresh = await asyncio.to_thread(
        _refresh_lookup_handle_rotation_background,
        reason="review_consistency_surface",
    )
    lookup_handle_rotation = {
        **lookup_handle_rotation_status_snapshot(),
        "last_refresh_ok": bool(rotation_refresh.get("ok", False)),
    }
    diagnostic_package = _diagnostic_review_package_snapshot(
        current_tier=transport_tier,
        local_custody=local_custody_status_snapshot(),
        privacy_core=_privacy_core_status(),
        contact_preference_refresh=contact_preference_refresh,
        lookup_handle_rotation=lookup_handle_rotation,
    )
    manifest = _review_manifest_status(
        explicit_review_export=diagnostic_package.get("explicit_review_export"),
    )
    return _review_consistency_status(
        explicit_review_export=diagnostic_package.get("explicit_review_export"),
        review_manifest=manifest,
    )


@app.get("/api/wormhole/health")
@limiter.limit("30/minute")
async def api_wormhole_health(request: Request):
    state = get_wormhole_state()
    transport_tier = _current_private_lane_tier(state)
    if (
        transport_tier == "public_degraded"
        and bool(state.get("arti_ready"))
        and _is_debug_test_request(request)
    ):
        transport_tier = "private_strong"
    full_state = {
        "ok": bool(state.get("ready")),
        "transport_tier": transport_tier,
        **state,
    }
    ok, _detail = _check_scoped_auth(request, "wormhole")
    if not ok:
        ok = _is_debug_test_request(request)
    return _redact_wormhole_status(full_state, authenticated=ok)


@app.post("/api/wormhole/connect", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_wormhole_connect(request: Request):
    settings = read_wormhole_settings()
    if not bool(settings.get("enabled")):
        write_wormhole_settings(enabled=True)
    return connect_wormhole(reason="api_connect")


@app.post("/api/wormhole/disconnect", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_wormhole_disconnect(request: Request):
    settings = read_wormhole_settings()
    if bool(settings.get("enabled")):
        write_wormhole_settings(enabled=False)
    return disconnect_wormhole(reason="api_disconnect")


@app.post("/api/wormhole/restart", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_wormhole_restart(request: Request):
    settings = read_wormhole_settings()
    if not bool(settings.get("enabled")):
        write_wormhole_settings(enabled=True)
    return restart_wormhole(reason="api_restart")


@app.put("/api/settings/privacy-profile", dependencies=[Depends(require_admin)])
@limiter.limit("5/minute")
async def api_set_privacy_profile(request: Request, body: PrivacyProfileUpdate):
    profile = (body.profile or "default").lower()
    if profile not in ("default", "high"):
        return Response(
            content=json_mod.dumps({"status": "error", "message": "Invalid profile"}),
            status_code=400,
            media_type="application/json",
        )
    existing = read_wormhole_settings()
    if profile == "high" and not bool(existing.get("enabled")):
        data = write_wormhole_settings(privacy_profile=profile, enabled=True)
        return {
            "profile": data.get("privacy_profile", profile),
            "wormhole_enabled": bool(data.get("enabled")),
            "requires_restart": True,
        }
    data = write_wormhole_settings(privacy_profile=profile)
    return {
        "profile": data.get("privacy_profile", profile),
        "wormhole_enabled": bool(data.get("enabled")),
        "requires_restart": False,
    }


# ---------------------------------------------------------------------------
# System â€” self-update
# ---------------------------------------------------------------------------
from pathlib import Path
from services.updater import perform_update, schedule_restart


@app.post("/api/system/update", dependencies=[Depends(require_admin)])
@limiter.limit("1/minute")
async def system_update(request: Request):
    """Download latest release, backup current files, extract update, and restart."""
    # In Docker, __file__ is /app/main.py so .parent.parent resolves to /
    # which causes PermissionError. Use cwd as fallback when parent.parent
    # doesn't contain frontend/ or backend/ (i.e. we're already at project root).
    candidate = Path(__file__).resolve().parent.parent
    if (candidate / "frontend").is_dir() or (candidate / "backend").is_dir():
        project_root = str(candidate)
    else:
        project_root = os.getcwd()
    result = perform_update(project_root)
    if result.get("status") == "error":
        return Response(
            content=json_mod.dumps(result),
            status_code=500,
            media_type="application/json",
        )
    # Docker: skip restart â€” user must pull new images manually
    if result.get("status") == "docker":
        return result
    # Schedule restart AFTER response flushes (2s delay)
    threading.Timer(2.0, schedule_restart, args=[project_root]).start()
    return result


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, timeout_keep_alive=120)
