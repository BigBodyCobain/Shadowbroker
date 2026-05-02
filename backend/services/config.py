"""Typed configuration via pydantic-settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Admin/security
    ADMIN_KEY: str = ""
    ALLOW_INSECURE_ADMIN: bool = False
    PUBLIC_API_KEY: str = ""

    # OpenClaw agent connectivity
    OPENCLAW_HMAC_SECRET: str = ""        # HMAC shared secret for direct mode (auto-generated if empty)
    OPENCLAW_ACCESS_TIER: str = "restricted"  # "full" or "restricted"

    # Data sources
    AIS_API_KEY: str = ""
    OPENSKY_CLIENT_ID: str = ""
    OPENSKY_CLIENT_SECRET: str = ""
    LTA_ACCOUNT_KEY: str = ""

    # Runtime
    CORS_ORIGINS: str = ""
    FETCH_SLOW_THRESHOLD_S: float = 5.0
    MESH_STRICT_SIGNATURES: bool = True
    MESH_DEBUG_MODE: bool = False
    MESH_MQTT_EXTRA_ROOTS: str = ""
    MESH_MQTT_EXTRA_TOPICS: str = ""
    MESH_MQTT_INCLUDE_DEFAULT_ROOTS: bool = True
    MESH_RNS_ENABLED: bool = False
    MESH_ARTI_ENABLED: bool = False
    MESH_ARTI_SOCKS_PORT: int = 9050
    MESH_RELAY_PEERS: str = ""
    MESH_DEFAULT_SYNC_PEERS: str = "https://node.shadowbroker.info"
    MESH_BOOTSTRAP_DISABLED: bool = False
    MESH_BOOTSTRAP_MANIFEST_PATH: str = "data/bootstrap_peers.json"
    MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY: str = ""
    MESH_NODE_MODE: str = "participant"
    MESH_SYNC_INTERVAL_S: int = 300
    MESH_SYNC_FAILURE_BACKOFF_S: int = 60
    MESH_RELAY_PUSH_TIMEOUT_S: int = 10
    MESH_RELAY_MAX_FAILURES: int = 3
    MESH_RELAY_FAILURE_COOLDOWN_S: int = 120
    MESH_PEER_PUSH_SECRET: str = ""
    MESH_RNS_APP_NAME: str = "shadowbroker"
    MESH_RNS_ASPECT: str = "infonet"
    MESH_RNS_IDENTITY_PATH: str = ""
    MESH_RNS_PEERS: str = ""
    MESH_RNS_DANDELION_HOPS: int = 2
    MESH_RNS_DANDELION_DELAY_MS: int = 400
    MESH_RNS_CHURN_INTERVAL_S: int = 300
    MESH_RNS_MAX_PEERS: int = 32
    MESH_RNS_MAX_PAYLOAD: int = 8192
    MESH_RNS_PEER_BUCKET_PREFIX: int = 4
    MESH_RNS_MAX_PEERS_PER_BUCKET: int = 4
    MESH_RNS_PEER_FAIL_THRESHOLD: int = 3
    MESH_RNS_PEER_COOLDOWN_S: int = 300
    MESH_RNS_SHARD_ENABLED: bool = False
    MESH_RNS_SHARD_DATA_SHARDS: int = 3
    MESH_RNS_SHARD_PARITY_SHARDS: int = 1
    MESH_RNS_SHARD_TTL_S: int = 30
    MESH_RNS_FEC_CODEC: str = "xor"  # xor | rs
    MESH_RNS_BATCH_MS: int = 200
    # Keep a low background cadence on private RNS links so quiet nodes are less
    # trivially fingerprintable by silence alone. Set to 0 to disable explicitly.
    MESH_RNS_COVER_INTERVAL_S: int = 30
    MESH_RNS_COVER_SIZE: int = 512
    MESH_DM_MAILBOX_TTL_S: int = 900
    MESH_RNS_IBF_WINDOW: int = 256
    MESH_RNS_IBF_TABLE_SIZE: int = 64
    MESH_RNS_IBF_MINHASH_SIZE: int = 16
    MESH_RNS_IBF_MINHASH_THRESHOLD: float = 0.25
    MESH_RNS_IBF_WINDOW_JITTER: int = 32
    MESH_RNS_IBF_INTERVAL_S: int = 120
    MESH_RNS_IBF_SYNC_PEERS: int = 3
    MESH_RNS_IBF_QUORUM_TIMEOUT_S: int = 6
    MESH_RNS_IBF_MAX_REQUEST_IDS: int = 64
    MESH_RNS_IBF_MAX_EVENTS: int = 64
    MESH_RNS_SESSION_ROTATE_S: int = 1800
    MESH_RNS_IBF_FAIL_THRESHOLD: int = 3
    MESH_RNS_IBF_COOLDOWN_S: int = 120
    MESH_VERIFY_INTERVAL_S: int = 600
    # MESH_VERIFY_SIGNATURES is intentionally removed — the audit loop in main.py
    # always calls validate_chain_incremental(verify_signatures=True). Any value
    # set in the environment is ignored.
    MESH_DM_SECURE_MODE: bool = True
    MESH_DM_TOKEN_PEPPER: str = ""
    MESH_ALLOW_LEGACY_DM1_UNTIL: str = ""
    MESH_ALLOW_LEGACY_DM_GET_UNTIL: str = ""
    MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL: str = ""
    MESH_DM_PERSIST_SPOOL: bool = False
    MESH_DM_RELAY_FILE_PATH: str = ""
    MESH_DM_RELAY_AUTO_RELOAD: bool = False
    MESH_DM_REQUIRE_SENDER_SEAL_SHARED: bool = True
    MESH_DM_NONCE_TTL_S: int = 300
    MESH_DM_NONCE_CACHE_MAX: int = 4096
    MESH_DM_NONCE_PER_AGENT_MAX: int = 256
    MESH_DM_REQUEST_MAX_AGE_S: int = 300
    MESH_DM_REQUEST_MAILBOX_LIMIT: int = 12
    MESH_DM_SHARED_MAILBOX_LIMIT: int = 48
    MESH_DM_SELF_MAILBOX_LIMIT: int = 12
    MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP: bool = True
    MESH_ALLOW_COMPAT_DM_INVITE_IMPORT: bool = False
    MESH_ALLOW_COMPAT_DM_INVITE_IMPORT_UNTIL: str = ""
    MESH_ALLOW_LEGACY_NODE_ID_COMPAT_UNTIL: str = ""
    # Rotate voter-blinding salts on a rolling cadence so new reputation
    # events do not reuse one forever-stable blinded identity.
    MESH_VOTER_BLIND_SALT_ROTATE_DAYS: int = 30
    # Keep historical salts long enough to cover live vote records, so
    # duplicate-vote detection and wallet-cost accounting survive rotation.
    MESH_VOTER_BLIND_SALT_GRACE_DAYS: int = 30
    MESH_DM_MAX_MSG_BYTES: int = 8192
    MESH_DM_ALLOW_SENDER_SEAL: bool = False
    # TTL for DH key and prekey bundle registrations — stale entries are pruned.
    MESH_DM_KEY_TTL_DAYS: int = 30
    # TTL for invite-scoped prekey lookup aliases; shorter windows reduce
    # long-lived relay linkage between opaque lookup handles and agent IDs.
    MESH_DM_PREKEY_LOOKUP_ALIAS_TTL_DAYS: int = 14
    # TTL for relay witness history; keep continuity metadata bounded instead
    # of relying on a hidden hardcoded retention window.
    MESH_DM_WITNESS_TTL_DAYS: int = 14
    # TTL for mailbox binding metadata — shorter = smaller metadata footprint on disk.
    MESH_DM_BINDING_TTL_DAYS: int = 3
    # When False, mailbox bindings are memory-only (agents re-register on restart).
    # Enable explicitly only if restart continuity is worth persisting DM graph metadata.
    MESH_DM_METADATA_PERSIST: bool = False
    # Second explicit opt-in for at-rest DM metadata persistence. This keeps a
    # single boolean flip from silently writing mailbox graph metadata to disk.
    MESH_DM_METADATA_PERSIST_ACKNOWLEDGE: bool = False
    # Optional import path for externally managed root witness material packages.
    # Relative paths resolve from the backend directory.
    MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_PATH: str = ""
    # Optional URI for externally managed root witness material packages.
    # Supports file:// and http(s):// sources; when set it overrides the local path.
    MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI: str = ""
    # Maximum acceptable age for externally sourced root witness packages.
    # Strong DM trust fails closed when the imported package exported_at is older than this.
    MESH_DM_ROOT_EXTERNAL_WITNESS_MAX_AGE_S: int = 3600
    # Warning threshold for externally sourced root witness packages.
    # When current external witness material reaches this age, operator health degrades to warning
    # before the strong path eventually fails closed at MAX_AGE.
    MESH_DM_ROOT_EXTERNAL_WITNESS_WARN_AGE_S: int = 2700
    # Optional export path for the append-only stable-root transparency ledger.
    # Relative paths resolve from the backend directory.
    MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH: str = ""
    # Optional URI used to read back and verify published transparency ledgers.
    # Supports file:// and http(s):// sources.
    MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI: str = ""
    # Maximum acceptable age for externally read transparency ledgers.
    # Strong DM trust fails closed when exported_at is older than this.
    MESH_DM_ROOT_TRANSPARENCY_LEDGER_MAX_AGE_S: int = 3600
    # Warning threshold for externally read transparency ledgers.
    # When current external transparency readback reaches this age, operator health degrades to warning
    # before the strong path eventually fails closed at MAX_AGE.
    MESH_DM_ROOT_TRANSPARENCY_LEDGER_WARN_AGE_S: int = 2700
    MESH_SCOPED_TOKENS: str = ""
    # Deprecated legacy env vars kept for backward config compatibility only.
    # Ordinary shipped gate flows keep MLS decrypt local; backend decrypt is
    # reserved for explicit recovery reads.
    MESH_GATE_BACKEND_DECRYPT_COMPAT: bool = False
    MESH_GATE_BACKEND_DECRYPT_COMPAT_ACKNOWLEDGE: bool = False
    MESH_BACKEND_GATE_DECRYPT_COMPAT: bool = False
    # Deprecated legacy env vars kept for backward config compatibility only.
    # Ordinary shipped gate flows keep compose/post local and submit encrypted
    # payloads to the backend for sign/post only.
    MESH_GATE_BACKEND_PLAINTEXT_COMPAT: bool = False
    MESH_GATE_BACKEND_PLAINTEXT_COMPAT_ACKNOWLEDGE: bool = False
    MESH_BACKEND_GATE_PLAINTEXT_COMPAT: bool = False
    # Runtime gate for recovery envelopes. When off, per-gate
    # envelope_recovery / envelope_always policies fail closed to
    # envelope_disabled. Default True so the Reddit-like durable history
    # model works out of the box: any member with the gate_secret can
    # decrypt every envelope encrypted from the moment they had that key.
    # Set MESH_GATE_RECOVERY_ENVELOPE_ENABLE=false to revert to MLS-only
    # forward-secret behavior (your own history becomes unreadable after
    # the sending ratchet advances).
    MESH_GATE_RECOVERY_ENVELOPE_ENABLE: bool = True
    MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE: bool = True
    # Durable gate plaintext retention is disabled by default. Enable only
    # when the operator explicitly accepts the at-rest privacy tradeoff.
    MESH_GATE_PLAINTEXT_PERSIST: bool = False
    MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE: bool = False
    MESH_GATE_SESSION_ROTATE_MSGS: int = 50
    MESH_GATE_SESSION_ROTATE_S: int = 3600
    MESH_GATE_LEGACY_ENVELOPE_FALLBACK_MAX_DAYS: int = 30
    # Add a randomized grace window before anonymous gate-session auto-rotation
    # so threshold-triggered identity swaps are less trivially correlated.
    MESH_GATE_SESSION_ROTATE_JITTER_S: int = 180
    # Gate persona (named identity) rotation thresholds.  Rotating the signing
    # key limits the linkability window.  Zero = disabled.
    MESH_GATE_PERSONA_ROTATE_MSGS: int = 200
    MESH_GATE_PERSONA_ROTATE_S: int = 604800  # 7 days
    MESH_GATE_PERSONA_ROTATE_JITTER_S: int = 600
    # Feature-flagged session stream for multiplexed gate room updates.
    # Disabled by default so rollout stays explicit while stream-first rooms bake.
    MESH_GATE_SESSION_STREAM_ENABLED: bool = False
    MESH_GATE_SESSION_STREAM_HEARTBEAT_S: int = 20
    MESH_GATE_SESSION_STREAM_BATCH_MS: int = 1500
    MESH_GATE_SESSION_STREAM_MAX_GATES: int = 16
    # Private gate APIs expose a backward-jittered timestamp view so observers
    # cannot trivially align exact send times from response metadata alone.
    MESH_GATE_TIMESTAMP_JITTER_S: int = 60
    # Ban/kick gate-secret rotation is on by default (hardening Rec #10): the
    # invariant has baked and a ban that does not rotate is effectively a
    # display-only removal. Set MESH_GATE_BAN_KICK_ROTATION_ENABLE=false to
    # revert to observe-only during incident triage.
    MESH_GATE_BAN_KICK_ROTATION_ENABLE: bool = True
    MESH_BLOCK_LEGACY_NODE_ID_COMPAT: bool = True
    MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK: bool = False
    MESH_ACK_RAW_FALLBACK_AT_OWN_RISK: bool = False
    MESH_SECURE_STORAGE_SECRET: str = ""
    MESH_PRIVATE_LOG_TTL_S: int = 900
    # Sprint 1 rollout: restored DM boot probes stay disabled by default until
    # the architect reviews false positives from the observe-only path.
    MESH_DM_RESTORED_SESSION_BOOT_PROBE_ENABLE: bool = False
    # Queued DM release requires explicit per-item approval before any weaker
    # relay fallback. Silent fallback is not a safe private-mode default.
    MESH_PRIVATE_RELEASE_APPROVAL_ENABLE: bool = True
    # Expiry for user-approved scoped private relay fallback policy. The policy
    # is still bounded by hidden-transport checks before it can auto-release.
    MESH_PRIVATE_RELAY_POLICY_TTL_S: int = 3600
    # Background privacy prewarm prepares keys/aliases/transport readiness
    # before send-time. Anonymous mode uses a cadence gate so user clicks do
    # not directly create hidden-transport activity.
    MESH_PRIVACY_PREWARM_ENABLE: bool = True
    MESH_PRIVACY_PREWARM_INTERVAL_S: int = 300
    MESH_PRIVACY_PREWARM_ANON_CADENCE_S: int = 300
    # Sprint 4 rollout: authenticated RNS cover markers remain disabled until
    # the observer-equivalence and receive-path DoS tests are green.
    MESH_RNS_COVER_AUTH_MARKER_ENABLE: bool = False
    # Signed-write revocation lookups use a short local TTL; stale entries force
    # a local rebuild before honor. Offline/local-refresh failures remain
    # observe-only until the later enforcement sprint.
    MESH_SIGNED_REVOCATION_CACHE_TTL_S: int = 300
    MESH_SIGNED_REVOCATION_CACHE_ENFORCE: bool = True
    MESH_SIGNED_WRITE_CONTEXT_REQUIRED: bool = True
    # Sprint 5 rollout: when enabled, root witness finality requires
    # independent quorum for threshold>1 witnessed roots before they count as
    # verified first-contact provenance.
    WORMHOLE_ROOT_WITNESS_FINALITY_ENFORCE: bool = False
    # Optional JSON artifact generated by CI/release workflow for the Sprint 8
    # release gate. Relative paths resolve from the backend directory.
    # dev = permissive local/dev behavior; testnet-private = strict private
    # defaults; release-candidate = no compatibility/debug escape hatches.
    MESH_RELEASE_PROFILE: str = "dev"
    MESH_RELEASE_ATTESTATION_PATH: str = ""
    # Operator release attestation for the Sprint 8 release gate. This does
    # not change runtime behavior; it only records that the DM relay security
    # suite was run and passed for the release candidate.
    MESH_RELEASE_DM_RELAY_SECURITY_SUITE_GREEN: bool = False
    PRIVACY_CORE_MIN_VERSION: str = "0.1.0"
    PRIVACY_CORE_ALLOWED_SHA256: str = ""
    PRIVACY_CORE_DEV_OVERRIDE: bool = False
    # Sprint 4 rollout: fail fast when the loaded privacy-core artifact is
    # missing required FFI symbols expected by the current Python bridge.
    PRIVACY_CORE_EXPORT_SET_AUDIT_ENABLE: bool = True
    # Clearnet fallback policy for private-tier messages.
    # "block" (default) = refuse to send private messages over clearnet.
    # "allow" = fall back to clearnet when Tor/RNS is unavailable (weaker privacy).
    MESH_PRIVATE_CLEARNET_FALLBACK: str = "block"
    # Second explicit opt-in for private-tier clearnet fallback. Without this
    # acknowledgement, "allow" remains requested but not effective.
    MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE: bool = False
    # Meshtastic MQTT bridge — disabled by default to avoid hammering the
    # public broker.  Users opt in explicitly.
    MESH_MQTT_ENABLED: bool = False
    # Meshtastic MQTT broker credentials (defaults match public firmware).
    MESH_MQTT_BROKER: str = "mqtt.meshtastic.org"
    MESH_MQTT_PORT: int = 1883
    MESH_MQTT_USER: str = "meshdev"
    MESH_MQTT_PASS: str = "large4cats"
    # Hex-encoded PSK — empty string means use the default LongFast key.
    # Must decode to exactly 16 or 32 bytes when set.
    MESH_MQTT_PSK: str = ""
    # Optional operator-provided Meshtastic node ID (e.g. "!abcd1234") included
    # in the User-Agent when fetching from meshtastic.liamcottle.net so the
    # service operator can identify per-install traffic instead of a generic
    # "ShadowBroker" aggregate.
    MESHTASTIC_OPERATOR_CALLSIGN: str = ""

    # SAR (Synthetic Aperture Radar) data layer
    # Mode A — free catalog metadata, no account, default-on
    MESH_SAR_CATALOG_ENABLED: bool = True
    # Mode B — free pre-processed anomalies (OPERA / EGMS / GFM / EMS / UNOSAT)
    # Two-step opt-in: must be "allow" AND _ACKNOWLEDGE must be true
    MESH_SAR_PRODUCTS_FETCH: str = "block"
    MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE: bool = False
    # NASA Earthdata Login (free) — required for OPERA products
    MESH_SAR_EARTHDATA_USER: str = ""
    MESH_SAR_EARTHDATA_TOKEN: str = ""
    # Copernicus Data Space (free) — required for EGMS / EMS products
    MESH_SAR_COPERNICUS_USER: str = ""
    MESH_SAR_COPERNICUS_TOKEN: str = ""
    # Whether OpenClaw agents may read/act on the SAR layer
    MESH_SAR_OPENCLAW_ENABLED: bool = True
    # Require private-tier transport before signing/broadcasting SAR anomalies
    MESH_SAR_REQUIRE_PRIVATE_TIER: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def private_clearnet_fallback_requested(settings: Settings | None = None) -> str:
    snapshot = settings or get_settings()
    policy = str(getattr(snapshot, "MESH_PRIVATE_CLEARNET_FALLBACK", "block") or "block").strip().lower()
    return "allow" if policy == "allow" else "block"


def private_clearnet_fallback_effective(settings: Settings | None = None) -> str:
    snapshot = settings or get_settings()
    requested = private_clearnet_fallback_requested(snapshot)
    acknowledged = bool(getattr(snapshot, "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE", False))
    if requested == "allow" and acknowledged:
        return "allow"
    return "block"


def backend_gate_decrypt_compat_effective(settings: Settings | None = None) -> bool:
    snapshot = settings or get_settings()
    return bool(
        getattr(snapshot, "MESH_BACKEND_GATE_DECRYPT_COMPAT", False)
        or getattr(snapshot, "MESH_GATE_BACKEND_DECRYPT_COMPAT", False)
    )


def backend_gate_plaintext_compat_effective(settings: Settings | None = None) -> bool:
    snapshot = settings or get_settings()
    return bool(
        getattr(snapshot, "MESH_BACKEND_GATE_PLAINTEXT_COMPAT", False)
        or getattr(snapshot, "MESH_GATE_BACKEND_PLAINTEXT_COMPAT", False)
    )


def gate_recovery_envelope_effective(settings: Settings | None = None) -> bool:
    snapshot = settings or get_settings()
    requested = bool(getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE", False))
    acknowledged = bool(getattr(snapshot, "MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", False))
    return requested and acknowledged


def gate_plaintext_persist_effective(settings: Settings | None = None) -> bool:
    snapshot = settings or get_settings()
    requested = bool(getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST", False))
    acknowledged = bool(getattr(snapshot, "MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE", False))
    return requested and acknowledged


def gate_ban_kick_rotation_enabled(settings: Settings | None = None) -> bool:
    snapshot = settings or get_settings()
    return bool(getattr(snapshot, "MESH_GATE_BAN_KICK_ROTATION_ENABLE", False))


def dm_restored_session_boot_probe_enabled(settings: Settings | None = None) -> bool:
    snapshot = settings or get_settings()
    return bool(getattr(snapshot, "MESH_DM_RESTORED_SESSION_BOOT_PROBE_ENABLE", False))


def signed_revocation_cache_ttl_s(settings: Settings | None = None) -> int:
    snapshot = settings or get_settings()
    return max(0, int(getattr(snapshot, "MESH_SIGNED_REVOCATION_CACHE_TTL_S", 300) or 0))


def signed_revocation_cache_enforce(settings: Settings | None = None) -> bool:
    snapshot = settings or get_settings()
    return bool(getattr(snapshot, "MESH_SIGNED_REVOCATION_CACHE_ENFORCE", False))


def wormhole_root_witness_finality_enforce(settings: Settings | None = None) -> bool:
    snapshot = settings or get_settings()
    return bool(getattr(snapshot, "WORMHOLE_ROOT_WITNESS_FINALITY_ENFORCE", False))
