import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import (
    _private_infonet_policy_snapshot,
    _strong_claims_policy_snapshot,
    require_admin,
    require_local_operator,
)
from limiter import limiter


# ---------------------------------------------------------------------------
# Transition delegates: forward to main.py so test monkeypatches still work.
# ---------------------------------------------------------------------------
def _main_delegate(name):
    def _wrapper(*a, **kw):
        import main as _m
        return getattr(_m, name)(*a, **kw)
    _wrapper.__name__ = name
    return _wrapper


_check_scoped_auth = _main_delegate("_check_scoped_auth")
_current_private_lane_tier = _main_delegate("_current_private_lane_tier")
_is_debug_test_request = _main_delegate("_is_debug_test_request")
_refresh_node_peer_store = _main_delegate("_refresh_node_peer_store")
_sign_gate_access_proof = _main_delegate("_sign_gate_access_proof")
get_wormhole_state = _main_delegate("get_wormhole_state")
_scoped_view_authenticated = _main_delegate("_scoped_view_authenticated")
_privacy_core_status = _main_delegate("_privacy_core_status")
_release_gate_status = _main_delegate("_release_gate_status")
get_transport_identity = _main_delegate("get_transport_identity")
get_active_gate_identity = _main_delegate("get_active_gate_identity")
list_gate_personas = _main_delegate("list_gate_personas")
decrypt_gate_message_for_local_identity = _main_delegate("decrypt_gate_message_for_local_identity")
export_gate_state_snapshot = _main_delegate("export_gate_state_snapshot")
_submit_gate_message_envelope = _main_delegate("_submit_gate_message_envelope")


def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


from services.config import get_settings
from services.wormhole_settings import read_wormhole_settings, write_wormhole_settings
from services.wormhole_status import read_wormhole_status
from services.wormhole_supervisor import (
    connect_wormhole,
    disconnect_wormhole,
    restart_wormhole,
)
from services.mesh import mesh_wormhole_identity as _mesh_wormhole_identity

bootstrap_wormhole_identity = _mesh_wormhole_identity.bootstrap_wormhole_identity
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
verify_wormhole_dm_invite = getattr(
    _mesh_wormhole_identity,
    "verify_wormhole_dm_invite",
    _wormhole_identity_unavailable,
)
from services.mesh.mesh_wormhole_persona import (
    activate_gate_persona,
    bootstrap_wormhole_persona_state,
    clear_active_gate_persona,
    create_gate_persona,
    enter_gate_anonymously,
    get_dm_identity,
    leave_gate,
    retire_gate_persona,
    sign_gate_wormhole_event,
    sign_public_wormhole_event,
)
from services.mesh.mesh_wormhole_prekey import (
    bootstrap_decrypt_from_sender,
    bootstrap_encrypt_for_peer,
    register_wormhole_prekey_bundle,
)
from services.mesh.mesh_wormhole_sender_token import (
    consume_wormhole_dm_sender_token,
    issue_wormhole_dm_sender_token,
    issue_wormhole_dm_sender_tokens,
)
from services.mesh.mesh_wormhole_seal import build_sender_seal, open_sender_seal
from services.mesh.mesh_wormhole_dead_drop import (
    derive_dead_drop_token_pair,
    derive_sas_phrase,
    derive_dead_drop_tokens_for_contacts,
    issue_pairwise_dm_alias,
    rotate_pairwise_dm_alias,
)
from services.mesh.mesh_gate_mls import (
    compose_encrypted_gate_message,
    ensure_gate_member_access,
    get_local_gate_key_status,
    is_gate_locked_to_mls as is_gate_mls_locked,
    mark_gate_rekey_recommended,
    rotate_gate_epoch,
    sign_encrypted_gate_message,
)
from services.mesh.mesh_dm_mls import (
    decrypt_dm as decrypt_mls_dm,
    ensure_dm_session as ensure_mls_dm_session,
    has_dm_session as has_mls_dm_session,
    is_dm_locked_to_mls,
)
from services.mesh.mesh_wormhole_ratchet import (
    decrypt_wormhole_dm,
    reset_wormhole_dm_ratchet,
)
from services.mesh.mesh_dm_selftest import run_dm_selftest

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Constants ---

_WORMHOLE_PUBLIC_SETTINGS_FIELDS = {"enabled", "transport", "anonymous_mode"}
_WORMHOLE_PUBLIC_PROFILE_FIELDS = {"profile", "wormhole_enabled"}
_PRIVATE_LANE_CONTROL_FIELDS = {"private_lane_tier", "private_lane_policy"}
_PUBLIC_RNS_STATUS_FIELDS = {"enabled", "ready", "configured_peers", "active_peers"}
_NODE_PUBLIC_EVENT_HOOK_REGISTERED = False

# --- Redaction helpers ---

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

# --- Composed gate message redaction ---

def _redact_composed_gate_message(payload: dict[str, Any]) -> dict[str, Any]:
    safe = {
        "ok": bool(payload.get("ok")),
        "gate_id": str(payload.get("gate_id", "") or ""),
        "identity_scope": str(payload.get("identity_scope", "") or ""),
        "ciphertext": str(payload.get("ciphertext", "") or ""),
        "nonce": str(payload.get("nonce", "") or ""),
        "sender_ref": str(payload.get("sender_ref", "") or ""),
        "format": str(payload.get("format", "mls1") or "mls1"),
        "timestamp": float(payload.get("timestamp", 0) or 0),
    }
    epoch = payload.get("epoch", 0)
    if epoch:
        safe["epoch"] = int(epoch or 0)
    if payload.get("detail"):
        safe["detail"] = str(payload.get("detail", "") or "")
    if payload.get("key_commitment"):
        safe["key_commitment"] = str(payload.get("key_commitment", "") or "")
    return safe

# --- Wormhole service imports (done lazily in function bodies) ---
# These are imported at module level in main.py but we use lazy imports here.

# --- Pydantic models ---

class WormholeUpdate(BaseModel):
    enabled: bool
    transport: str | None = None
    socks_proxy: str | None = None
    socks_dns: bool | None = None
    anonymous_mode: bool | None = None


class NodeSettingsUpdate(BaseModel):
    enabled: bool


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


class WormholeDmSelftestRequest(BaseModel):
    message: str = ""


class WormholeDmBootstrapEncryptRequest(BaseModel):
    peer_id: str
    plaintext: str


class WormholeDmBootstrapDecryptRequest(BaseModel):
    sender_id: str = ""
    ciphertext: str


class WormholeDmInviteImportRequest(BaseModel):
    invite: dict[str, Any]
    alias: str = ""


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
    grace_ms: int = 45_000


class WormholeDeadDropContactsRequest(BaseModel):
    contacts: list[dict[str, Any]]
    limit: int = 24


class WormholeSasRequest(BaseModel):
    peer_id: str
    peer_dh_pub: str = ""
    words: int = 8
    peer_ref: str = ""


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

# --- DM helper functions ---

def compose_wormhole_dm(
    *,
    peer_id: str,
    peer_dh_pub: str,
    plaintext: str,
    local_alias: str | None = None,
    remote_alias: str | None = None,
    remote_prekey_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Delegate to main.compose_wormhole_dm which owns the S11B trust logic."""
    import main as _m
    return _m.compose_wormhole_dm(
        peer_id=peer_id,
        peer_dh_pub=peer_dh_pub,
        plaintext=plaintext,
        local_alias=local_alias,
        remote_alias=remote_alias,
        remote_prekey_bundle=remote_prekey_bundle,
    )


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
    import main as _m

    return _m.decrypt_wormhole_dm_envelope(
        peer_id=peer_id,
        ciphertext=ciphertext,
        payload_format=payload_format,
        nonce=nonce,
        local_alias=local_alias,
        remote_alias=remote_alias,
        session_welcome=session_welcome,
    )

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
            ensured = ensure_mls_dm_session(resolved_local, resolved_remote, str(session_welcome or ""))
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
        return {
            "ok": True,
            "peer_id": str(peer_id or "").strip(),
            "local_alias": resolved_local,
            "remote_alias": resolved_remote,
            "plaintext": str(decrypted.get("plaintext", "") or ""),
            "format": "mls1",
        }

    from services.wormhole_supervisor import get_transport_tier

    current_tier = get_transport_tier()
    if str(current_tier or "").startswith("private_"):
        return {
            "ok": False,
            "detail": "MLS format required in private transport mode — legacy DM decrypt blocked",
        }
    logger.warning("legacy dm decrypt path used")
    legacy = decrypt_wormhole_dm(peer_id=str(peer_id or ""), ciphertext=str(ciphertext or ""))
    if not legacy.get("ok"):
        return legacy
    return {
        "ok": True,
        "peer_id": str(peer_id or "").strip(),
        "local_alias": resolved_local,
        "remote_alias": resolved_remote,
        "plaintext": str(legacy.get("result", "") or ""),
        "format": "dm1",
    }



# --- Routes ---

@router.get("/api/settings/wormhole")
@limiter.limit("30/minute")
async def api_get_wormhole_settings(request: Request):
    settings = await asyncio.to_thread(read_wormhole_settings)
    return _redact_wormhole_settings(settings, authenticated=_scoped_view_authenticated(request, "wormhole"))


@router.put("/api/settings/wormhole", dependencies=[Depends(require_admin)])
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
    grace_ms: int = 45_000


class WormholeDeadDropContactsRequest(BaseModel):
    contacts: list[dict[str, Any]]
    limit: int = 24


class WormholeSasRequest(BaseModel):
    peer_id: str
    peer_dh_pub: str = ""
    words: int = 8
    peer_ref: str = ""


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
    import main as _m

    return _m.decrypt_wormhole_dm_envelope(
        peer_id=peer_id,
        ciphertext=ciphertext,
        payload_format=payload_format,
        nonce=nonce,
        local_alias=local_alias,
        remote_alias=remote_alias,
        session_welcome=session_welcome,
    )

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
            ensured = ensure_mls_dm_session(resolved_local, resolved_remote, str(session_welcome or ""))
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
        return {
            "ok": True,
            "peer_id": str(peer_id or "").strip(),
            "local_alias": resolved_local,
            "remote_alias": resolved_remote,
            "plaintext": str(decrypted.get("plaintext", "") or ""),
            "format": "mls1",
        }

    from services.wormhole_supervisor import get_transport_tier

    current_tier = get_transport_tier()
    if str(current_tier or "").startswith("private_"):
        return {
            "ok": False,
            "detail": "MLS format required in private transport mode — legacy DM decrypt blocked",
        }
    logger.warning("legacy dm decrypt path used")
    legacy = decrypt_wormhole_dm(peer_id=str(peer_id or ""), ciphertext=str(ciphertext or ""))
    if not legacy.get("ok"):
        return legacy
    return {
        "ok": True,
        "peer_id": str(peer_id or "").strip(),
        "local_alias": resolved_local,
        "remote_alias": resolved_remote,
        "plaintext": str(legacy.get("result", "") or ""),
        "format": "dm1",
    }


@router.get("/api/settings/privacy-profile")
@limiter.limit("30/minute")
async def api_get_privacy_profile(request: Request):
    data = await asyncio.to_thread(read_wormhole_settings)
    return _redact_privacy_profile_settings(
        data,
        authenticated=_scoped_view_authenticated(request, "wormhole"),
    )


@router.get("/api/settings/wormhole-status")
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
    if authenticated:
        strong_claims = _strong_claims_policy_snapshot(
            current_tier=transport_tier
        )
        privacy_core = _privacy_core_status()
        full_state["strong_claims"] = strong_claims
        full_state["privacy_core"] = privacy_core
        full_state["release_gate"] = _release_gate_status(
            current_tier=transport_tier,
            strong_claims=strong_claims,
            privacy_core=privacy_core,
        )
    return _redact_wormhole_status(
        full_state,
        authenticated=authenticated,
    )


@router.post("/api/wormhole/join", dependencies=[Depends(require_local_operator)])
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
    # This is the voluntary opt-in — the node only joins the network when
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


@router.post("/api/wormhole/leave", dependencies=[Depends(require_local_operator)])
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


@router.get("/api/wormhole/identity", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_identity(request: Request):
    try:
        bootstrap_wormhole_persona_state()
        return get_transport_identity()
    except Exception as exc:
        logger.exception("wormhole transport identity fetch failed")
        raise HTTPException(status_code=500, detail="wormhole_identity_failed") from exc


@router.post("/api/wormhole/identity/bootstrap", dependencies=[Depends(require_local_operator)])
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


@router.get("/api/wormhole/dm/identity", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_dm_identity(request: Request):
    try:
        bootstrap_wormhole_persona_state()
        return get_dm_identity()
    except Exception as exc:
        logger.exception("wormhole dm identity fetch failed")
        raise HTTPException(status_code=500, detail="wormhole_dm_identity_failed") from exc


@router.get("/api/wormhole/dm/invite", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_dm_invite(request: Request):
    return export_wormhole_dm_invite()


@router.post("/api/wormhole/dm/invite/import", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_invite_import(request: Request, body: WormholeDmInviteImportRequest):
    return import_wormhole_dm_invite(
        dict(body.invite or {}),
        alias=str(body.alias or "").strip(),
    )


@router.post("/api/wormhole/sign", dependencies=[Depends(require_local_operator)])
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


@router.post("/api/wormhole/gate/enter", dependencies=[Depends(require_local_operator)])
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


@router.post("/api/wormhole/gate/leave", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def api_wormhole_gate_leave(request: Request, body: WormholeGateRequest):
    return leave_gate(str(body.gate_id or ""))


@router.get("/api/wormhole/gate/{gate_id}/identity", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_identity(request: Request, gate_id: str):
    return get_active_gate_identity(gate_id)


@router.get("/api/wormhole/gate/{gate_id}/personas", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_personas(request: Request, gate_id: str):
    return list_gate_personas(gate_id)


@router.get("/api/wormhole/gate/{gate_id}/key", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_key_status(request: Request, gate_id: str):
    import main as _m
    return await _m.api_wormhole_gate_key_status(request, gate_id)


@router.post("/api/wormhole/gate/key/rotate", dependencies=[Depends(require_local_operator)])
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


@router.post("/api/wormhole/gate/persona/create", dependencies=[Depends(require_local_operator)])
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


@router.post("/api/wormhole/gate/persona/activate", dependencies=[Depends(require_local_operator)])
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


@router.post("/api/wormhole/gate/persona/clear", dependencies=[Depends(require_local_operator)])
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


@router.post("/api/wormhole/gate/persona/retire", dependencies=[Depends(require_local_operator)])
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


@router.post("/api/wormhole/gate/key/grant", dependencies=[Depends(require_local_operator)])
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
    return {
        "ok": False,
        "detail": "gate_backend_plaintext_compat_required",
        "gate_id": gate_id,
        "compat_requested": bool(compat_plaintext),
        "compat_effective": False,
    }


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


@router.post("/api/wormhole/gate/message/compose", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_message_compose(request: Request, body: WormholeGateComposeRequest):
    import main as _m
    return await _m.api_wormhole_gate_message_compose(request, body)


@router.post("/api/wormhole/gate/message/sign-encrypted", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_message_sign_encrypted(
    request: Request,
    body: WormholeGateEncryptedSignRequest,
):
    import main as _m
    return await _m.api_wormhole_gate_message_sign_encrypted(request, body)


@router.post("/api/wormhole/gate/message/post-encrypted", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_message_post_encrypted(
    request: Request,
    body: WormholeGateEncryptedPostRequest,
):
    import main as _m
    return await _m.api_wormhole_gate_message_post_encrypted(request, body)


@router.post("/api/wormhole/gate/message/post", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_message_post(request: Request, body: WormholeGateComposeRequest):
    import main as _m
    return await _m.api_wormhole_gate_message_post(request, body)


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


@router.post("/api/wormhole/gate/message/decrypt", dependencies=[Depends(require_local_operator)])
@limiter.limit("60/minute")
async def api_wormhole_gate_message_decrypt(request: Request, body: WormholeGateDecryptRequest):
    import main as _m
    return await _m.api_wormhole_gate_message_decrypt(request, body)


@router.post("/api/wormhole/gate/messages/decrypt", dependencies=[Depends(require_local_operator)])
@limiter.limit("60/minute")
async def api_wormhole_gate_messages_decrypt(request: Request, body: WormholeGateDecryptBatchRequest):
    import main as _m
    return await _m.api_wormhole_gate_messages_decrypt(request, body)


@router.post("/api/wormhole/gate/state/export", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_state_export(request: Request, body: WormholeGateRequest):
    import main as _m
    return await _m.api_wormhole_gate_state_export(request, body)


@router.post("/api/wormhole/gate/proof", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_gate_proof(request: Request, body: WormholeGateRequest):
    proof = _sign_gate_access_proof(str(body.gate_id or ""))
    if not proof.get("ok"):
        raise HTTPException(status_code=403, detail=str(proof.get("detail") or "gate_access_proof_failed"))
    return proof


@router.post("/api/wormhole/sign-raw", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_sign_raw(request: Request, body: WormholeSignRawRequest):
    return sign_wormhole_message(str(body.message or ""))


@router.post("/api/wormhole/dm/register-key", dependencies=[Depends(require_admin)])
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


@router.post("/api/wormhole/dm/prekey/register", dependencies=[Depends(require_admin)])
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


@router.post("/api/wormhole/dm/bootstrap-encrypt", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_bootstrap_encrypt(request: Request, body: WormholeDmBootstrapEncryptRequest):
    return bootstrap_encrypt_for_peer(
        peer_id=str(body.peer_id or ""),
        plaintext=str(body.plaintext or ""),
    )


@router.post("/api/wormhole/dm/bootstrap-decrypt", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_bootstrap_decrypt(request: Request, body: WormholeDmBootstrapDecryptRequest):
    return bootstrap_decrypt_from_sender(
        sender_id=str(body.sender_id or ""),
        ciphertext=str(body.ciphertext or ""),
    )


@router.post("/api/wormhole/dm/sender-token", dependencies=[Depends(require_admin)])
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


@router.post("/api/wormhole/dm/open-seal", dependencies=[Depends(require_admin)])
@limiter.limit("120/minute")
async def api_wormhole_dm_open_seal(request: Request, body: WormholeOpenSealRequest):
    return open_sender_seal(
        sender_seal=str(body.sender_seal or ""),
        candidate_dh_pub=str(body.candidate_dh_pub or ""),
        recipient_id=str(body.recipient_id or ""),
        expected_msg_id=str(body.expected_msg_id or ""),
    )


@router.post("/api/wormhole/dm/build-seal", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_build_seal(request: Request, body: WormholeBuildSealRequest):
    return build_sender_seal(
        recipient_id=str(body.recipient_id or ""),
        recipient_dh_pub=str(body.recipient_dh_pub or ""),
        msg_id=str(body.msg_id or ""),
        timestamp=_safe_int(body.timestamp or 0),
    )


@router.post("/api/wormhole/dm/dead-drop-token", dependencies=[Depends(require_admin)])
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


@router.post("/api/wormhole/dm/pairwise-alias", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_pairwise_alias(request: Request, body: WormholePairwiseAliasRequest):
    return issue_pairwise_dm_alias(
        peer_id=str(body.peer_id or ""),
        peer_dh_pub=str(body.peer_dh_pub or ""),
    )


@router.post("/api/wormhole/dm/pairwise-alias/rotate", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_pairwise_alias_rotate(
    request: Request, body: WormholePairwiseAliasRotateRequest
):
    return rotate_pairwise_dm_alias(
        peer_id=str(body.peer_id or ""),
        peer_dh_pub=str(body.peer_dh_pub or ""),
        grace_ms=_safe_int(body.grace_ms or 45_000, 45_000),
    )


@router.post("/api/wormhole/dm/dead-drop-tokens", dependencies=[Depends(require_admin)])
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


@router.post("/api/wormhole/dm/sas", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_sas(request: Request, body: WormholeSasRequest):
    return derive_sas_phrase(
        peer_id=str(body.peer_id or ""),
        peer_dh_pub=str(body.peer_dh_pub or ""),
        words=_safe_int(body.words or 8, 8),
        peer_ref=str(body.peer_ref or ""),
    )


@router.post("/api/wormhole/dm/encrypt", dependencies=[Depends(require_admin)])
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


@router.post("/api/wormhole/dm/compose", dependencies=[Depends(require_local_operator)])
@limiter.limit("60/minute")
async def api_wormhole_dm_compose(request: Request, body: WormholeDmComposeRequest):
    presented = str(request.headers.get("X-Admin-Key", "") or "").strip()
    if presented:
        ok, _detail = _check_scoped_auth(request, "dm")
        if not ok:
            raise HTTPException(status_code=403, detail="access denied")
    return compose_wormhole_dm(
        peer_id=str(body.peer_id or ""),
        peer_dh_pub=str(body.peer_dh_pub or ""),
        plaintext=str(body.plaintext or ""),
        local_alias=body.local_alias,
        remote_alias=body.remote_alias,
        remote_prekey_bundle=dict(body.remote_prekey_bundle or {}),
    )


@router.post("/api/wormhole/dm/decrypt", dependencies=[Depends(require_admin)])
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


@router.post("/api/wormhole/dm/reset", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_wormhole_dm_reset(request: Request, body: WormholeDmResetRequest):
    return reset_wormhole_dm_ratchet(
        peer_id=str(body.peer_id or "").strip() or None,
    )


@router.post("/api/wormhole/dm/selftest", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_wormhole_dm_selftest(request: Request, body: WormholeDmSelftestRequest):
    presented = str(request.headers.get("X-Admin-Key", "") or "").strip()
    if presented:
        ok, _detail = _check_scoped_auth(request, "dm")
        if not ok:
            raise HTTPException(status_code=403, detail="access denied")
    return run_dm_selftest(message=str(body.message or ""))


@router.get("/api/wormhole/dm/contacts", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def api_wormhole_dm_contacts(request: Request):
    from services.mesh.mesh_wormhole_contacts import list_wormhole_dm_contacts

    try:
        return {"ok": True, "contacts": list_wormhole_dm_contacts()}
    except Exception as exc:
        logger.exception("wormhole dm contacts fetch failed")
        raise HTTPException(status_code=500, detail="wormhole_dm_contacts_failed") from exc


@router.put("/api/wormhole/dm/contact", dependencies=[Depends(require_admin)])
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


@router.delete("/api/wormhole/dm/contact/{peer_id}", dependencies=[Depends(require_admin)])
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


class PrivateDeliveryActionRequest(BaseModel):
    action: str


@router.get("/api/wormhole/status")
@limiter.limit("30/minute")
async def api_wormhole_status(request: Request):
    import main as _m

    return await _m.api_wormhole_status(request)


@router.post("/api/wormhole/private-delivery/{item_id}/action", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_wormhole_private_delivery_action(
    request: Request,
    item_id: str,
    body: PrivateDeliveryActionRequest,
):
    from services.mesh.mesh_private_outbox import private_delivery_outbox
    from services.mesh.mesh_private_release_worker import private_release_worker

    action = str(body.action or "").strip().lower()
    current = private_delivery_outbox.get_item(item_id, exposure="ordinary")
    if current is None:
        raise HTTPException(status_code=404, detail="private_delivery_item_not_found")
    if str(current.get("release_state", "") or "") == "delivered":
        return {
            "ok": False,
            "detail": "private_delivery_item_already_delivered",
            "item": current,
        }
    if action == "relay":
        private_delivery_outbox.approve_relay_release(item_id)
        private_release_worker.wake()
    elif action == "wait":
        private_delivery_outbox.continue_waiting_for_release(item_id)
    else:
        raise HTTPException(status_code=400, detail="private_delivery_action_invalid")
    updated = private_delivery_outbox.get_item(item_id, exposure="ordinary")
    return {
        "ok": True,
        "action": action,
        "item": updated,
    }


@router.get("/api/wormhole/health")
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


@router.post("/api/wormhole/connect", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_wormhole_connect(request: Request):
    settings = read_wormhole_settings()
    if not bool(settings.get("enabled")):
        write_wormhole_settings(enabled=True)
    return connect_wormhole(reason="api_connect")


@router.post("/api/wormhole/disconnect", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_wormhole_disconnect(request: Request):
    settings = read_wormhole_settings()
    if bool(settings.get("enabled")):
        write_wormhole_settings(enabled=False)
    return disconnect_wormhole(reason="api_disconnect")


@router.post("/api/wormhole/restart", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_wormhole_restart(request: Request):
    settings = read_wormhole_settings()
    if not bool(settings.get("enabled")):
        write_wormhole_settings(enabled=True)
    return restart_wormhole(reason="api_restart")


@router.put("/api/settings/privacy-profile", dependencies=[Depends(require_admin)])
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



