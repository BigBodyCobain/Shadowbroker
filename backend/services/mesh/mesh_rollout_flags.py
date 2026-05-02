from __future__ import annotations

import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def gate_ban_kick_rotation_enabled() -> bool:
    return _env_bool("MESH_GATE_BAN_KICK_ROTATION_ENABLE", True)


def dm_restored_session_boot_probe_enabled() -> bool:
    return _env_bool("MESH_DM_RESTORED_SESSION_BOOT_PROBE_ENABLE", False)


def signed_revocation_cache_ttl_s() -> int:
    return max(0, _env_int("MESH_SIGNED_REVOCATION_CACHE_TTL_S", 300))


def signed_revocation_cache_enforce() -> bool:
    return _env_bool("MESH_SIGNED_REVOCATION_CACHE_ENFORCE", True)


def gate_previous_secret_ttl_s() -> int:
    # Hardening Rec #10: cap how long a rotated-out gate_secret remains
    # recoverable from disk. Epoch/event_id ceilings already bound *policy*
    # reuse in _archived_gate_secret_allowed; this TTL additionally scrubs
    # the secret bytes from state after a generous window so disk-read
    # compromise can't decrypt pre-rotation envelopes indefinitely. Default
    # 7 days is long enough for ordinary rejoin cycles. Set to 0 to disable.
    return max(0, _env_int("MESH_GATE_PREVIOUS_SECRET_TTL_S", 7 * 24 * 3600))


def signed_write_content_private_transport_lock_required() -> bool:
    # Hardening Rec #2: when enabled, content-private signed writes (DMs,
    # gate messages, identity rotations, trust vouches) must carry a
    # ``transport_lock`` field bound into the signature. Default ON: accepting
    # content-private writes without a signed lane commitment is a downgrade
    # path, not a privacy-preserving compatibility mode.
    return _env_bool("MESH_SIGNED_WRITE_CONTENT_PRIVATE_TRANSPORT_LOCK_REQUIRED", True)


def ingest_event_max_age_s() -> int:
    # Hardening Rec #8: freshness bound for ingested hashchain events.
    # The monotonic per-node sequence check catches replays once a node has
    # observed a given author, but a fresh peer (empty sequence state) would
    # otherwise accept arbitrarily old signed events from that author.
    # Default 86400 (24 h) keeps short partition catch-up working while
    # preventing ancient-event replay. 0 disables the check (preserves
    # legacy behavior).
    return max(0, _env_int("MESH_INGEST_EVENT_MAX_AGE_S", 86400))


def signed_write_max_age_s() -> int:
    # Hardening Rec #8: freshness bound for timestamped signed write
    # endpoints that are not materialized as public Infonet events. Per-kind
    # replay domains catch repeats after first observation; this catches
    # ancient signed blobs presented to a fresh peer with empty sequence state.
    # 0 disables the check for controlled compatibility testing.
    return max(0, _env_int("MESH_SIGNED_WRITE_MAX_AGE_S", 86400))


def signed_write_context_required() -> bool:
    # Explicit per-endpoint/per-kind context binding is now a default-on
    # safety property. Operators can still force it off for controlled
    # migration, but doing so should degrade release readiness immediately.
    return _env_bool("MESH_SIGNED_WRITE_CONTEXT_REQUIRED", True)


def pairwise_alias_rotate_after_ms() -> int:
    # Hardening Rec #3: tighten the default per-peer alias rotation cadence.
    # The audit finding was that deterministic HKDF derivation leaves aliases
    # linkable across sessions; the existing rotation infrastructure already
    # issues a fresh random alias (and counter) on schedule / on verification
    # / on gate-join / on DM compose. Shortening the default from 30 days to
    # 7 days bounds the pairwise-alias linkability window to a week without
    # adding significant rotation/commit traffic. Operators can set
    # MESH_PAIRWISE_ALIAS_ROTATE_AFTER_MS to override (minimum 1 h enforced
    # by the caller). Set to 0 to fall back to the 30-day legacy default.
    default_ms = 7 * 24 * 60 * 60 * 1000
    configured = _env_int("MESH_PAIRWISE_ALIAS_ROTATE_AFTER_MS", default_ms)
    if configured <= 0:
        return 30 * 24 * 60 * 60 * 1000
    # Enforce a 1-hour floor to prevent operator footgun configurations that
    # would rotate every request and burn commit traffic.
    return max(60 * 60 * 1000, configured)


def wormhole_root_witness_finality_enforce() -> bool:
    return _env_bool("WORMHOLE_ROOT_WITNESS_FINALITY_ENFORCE", False)
