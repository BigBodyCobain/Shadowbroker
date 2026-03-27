"""Typed configuration via pydantic-settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Admin/security
    ADMIN_KEY: str = ""
    ALLOW_INSECURE_ADMIN: bool = False
    PUBLIC_API_KEY: str = ""

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
    MESH_RELAY_PEERS: str = "http://cipher0.shadowbroker.info:8000"
    MESH_BOOTSTRAP_DISABLED: bool = False
    MESH_BOOTSTRAP_MANIFEST_PATH: str = "data/bootstrap_peers.json"
    MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY: str = ""
    MESH_NODE_MODE: str = "participant"
    MESH_SYNC_INTERVAL_S: int = 300
    MESH_SYNC_FAILURE_BACKOFF_S: int = 60
    MESH_RELAY_PUSH_TIMEOUT_S: int = 10
    MESH_RELAY_MAX_FAILURES: int = 3
    MESH_RELAY_FAILURE_COOLDOWN_S: int = 120
    MESH_PEER_PUSH_SECRET: str = "Mv63UvLfwqOEVWeRBXjA8MtFl2nEkkhUlLYVHiX1Zzo"
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
    MESH_RNS_COVER_SIZE: int = 64
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
    MESH_VERIFY_SIGNATURES: bool = True
    MESH_DM_SECURE_MODE: bool = True
    MESH_DM_TOKEN_PEPPER: str = ""
    MESH_DM_ALLOW_LEGACY_GET: bool = False
    MESH_DM_PERSIST_SPOOL: bool = False
    MESH_DM_REQUIRE_SENDER_SEAL_SHARED: bool = True
    MESH_DM_NONCE_TTL_S: int = 300
    MESH_DM_NONCE_CACHE_MAX: int = 4096
    MESH_DM_REQUEST_MAX_AGE_S: int = 300
    MESH_DM_REQUEST_MAILBOX_LIMIT: int = 12
    MESH_DM_SHARED_MAILBOX_LIMIT: int = 48
    MESH_DM_SELF_MAILBOX_LIMIT: int = 12
    MESH_DM_MAX_MSG_BYTES: int = 8192
    MESH_DM_ALLOW_SENDER_SEAL: bool = False
    # TTL for DH key and prekey bundle registrations — stale entries are pruned.
    MESH_DM_KEY_TTL_DAYS: int = 30
    # TTL for mailbox binding metadata — shorter = smaller metadata footprint on disk.
    MESH_DM_BINDING_TTL_DAYS: int = 7
    # When False, mailbox bindings are memory-only (agents re-register on restart).
    MESH_DM_METADATA_PERSIST: bool = True
    MESH_SCOPED_TOKENS: str = ""
    MESH_GATE_SESSION_ROTATE_MSGS: int = 50
    MESH_GATE_SESSION_ROTATE_S: int = 3600
    # Add a randomized grace window before anonymous gate-session auto-rotation
    # so threshold-triggered identity swaps are less trivially correlated.
    MESH_GATE_SESSION_ROTATE_JITTER_S: int = 180
    # Private gate APIs expose a backward-jittered timestamp view so observers
    # cannot trivially align exact send times from response metadata alone.
    MESH_GATE_TIMESTAMP_JITTER_S: int = 60
    MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK: bool = False
    MESH_PRIVATE_LOG_TTL_S: int = 900
    # Clearnet fallback policy for private-tier messages.
    # "block" (default) = refuse to send private messages over clearnet.
    # "allow" = fall back to clearnet when Tor/RNS is unavailable (weaker privacy).
    MESH_PRIVATE_CLEARNET_FALLBACK: str = "block"
    # Meshtastic MQTT broker credentials (defaults match public firmware).
    MESH_MQTT_USER: str = "meshdev"
    MESH_MQTT_PASS: str = "large4cats"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
