"""Mesh Router — policy-driven multi-transport message routing.

Routes messages through the optimal transport based on:
  - Payload size (LoRa < 200 bytes, APRS < 67 chars, WiFi/Internet unlimited)
  - Urgency (EMERGENCY → all available transports simultaneously)
  - Destination type (APRS callsign → APRS, Meshtastic node → MQTT, etc.)
  - Node reachability (what transports can reach the target?)

Transports:
  - APRS-IS:     Two-way text to ham radio operators (max 67 chars, needs callsign+passcode)
  - Meshtastic:  MQTT publish to LoRa mesh (max ~200 bytes, public LongFast channel)
  - Internet:    Future — Reticulum, direct TCP, WebSocket relay

The router doesn't care about the transport — it cares about getting the
message from A to B as efficiently as possible.
"""

import json
import time
import logging
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional
from collections import deque
from urllib.parse import urlparse
from services.mesh.mesh_crypto import _derive_peer_key, normalize_peer_url
from services.mesh.mesh_metrics import increment as metrics_inc
from services.mesh.mesh_privacy_policy import (
    TRANSPORT_TIER_ORDER as _TIER_RANK,
    normalize_transport_tier,
)
from services.mesh.meshtastic_topics import normalize_root

logger = logging.getLogger("services.mesh_router")

DEDUP_TTL_SECONDS = 300
DEDUP_MAX_ENTRIES = 5000
_TRANSPORT_PAD_BUCKETS = (1024, 2048, 4096, 8192, 16384, 32768)
_TIER_EVENT_MAXLEN = 128


def _peer_audit_label(peer_url: str) -> str:
    normalized = normalize_peer_url(peer_url)
    if not normalized:
        return "peer:unknown"
    parsed = urlparse(normalized)
    scheme = parsed.scheme or "peer"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
    return f"{scheme}:{digest}"


def peer_transport_kind(peer_url: str) -> str:
    normalized = normalize_peer_url(peer_url)
    parsed = urlparse(normalized)
    hostname = str(parsed.hostname or "").strip().lower()
    if parsed.scheme == "http" and hostname.endswith(".onion"):
        return "onion"
    if parsed.scheme == "https" and hostname:
        return "clearnet"
    # Allow plain http for LAN / testnet peers (not .onion)
    if parsed.scheme == "http" and hostname:
        return "clearnet"
    return ""


def parse_configured_relay_peers(raw: str) -> list[str]:
    peers: list[str] = []
    seen: set[str] = set()
    for candidate in str(raw or "").split(","):
        url = normalize_peer_url(candidate)
        transport = peer_transport_kind(url)
        if not url or not transport or url in seen:
            if str(candidate or "").strip():
                logger.warning(
                    "Ignoring peer URL (must be https:// or http://*.onion): %s",
                    str(candidate).strip()[:80],
                )
            continue
        seen.add(url)
        peers.append(url)
    return peers


def configured_relay_peer_urls() -> list[str]:
    from services.config import get_settings

    raw = str(get_settings().MESH_RELAY_PEERS or "").strip()
    return parse_configured_relay_peers(raw)


def _store_peer_urls(bucket: str, *, transport: str | None = None) -> list[str]:
    try:
        from services.mesh.mesh_peer_store import DEFAULT_PEER_STORE_PATH, PeerStore

        store = PeerStore(DEFAULT_PEER_STORE_PATH)
        records = store.load()
    except Exception:
        return []

    seen: set[str] = set()
    urls: list[str] = []
    for record in records:
        if record.bucket != bucket or not record.enabled:
            continue
        if transport and record.transport != transport:
            continue
        if record.peer_url in seen:
            continue
        seen.add(record.peer_url)
        urls.append(record.peer_url)
    return urls


def authenticated_push_peer_urls(*, transport: str | None = None) -> list[str]:
    from_store = _store_peer_urls("push", transport=transport)
    if from_store:
        return from_store
    configured = configured_relay_peer_urls()
    if transport:
        return [url for url in configured if peer_transport_kind(url) == transport]
    return configured


def active_sync_peer_urls() -> list[str]:
    from_store = _store_peer_urls("sync")
    if from_store:
        return from_store
    return configured_relay_peer_urls()


def _high_privacy_profile_blocks_clearnet_fallback() -> bool:
    """Return True when clearnet fallback should be refused on private-tier traffic.

    Sprint 1 / Rec #3: fail-closed. Block is the default. The only way to
    receive False (i.e. allow clearnet fallback) is an explicit operator
    opt-in via MESH_PRIVATE_CLEARNET_FALLBACK=allow AND
    MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true. Any config-read error
    also fails closed.
    """
    try:
        from services.config import private_clearnet_fallback_effective

        return private_clearnet_fallback_effective() != "allow"
    except Exception:
        return True


def _pad_transport_payload(raw_json_bytes: bytes) -> bytes:
    """Pad serialized JSON payload to a fixed-size bucket."""
    raw_len = len(raw_json_bytes)
    for bucket in _TRANSPORT_PAD_BUCKETS:
        if raw_len <= bucket:
            return raw_json_bytes + (b" " * (bucket - raw_len))
    target = (((raw_len - 1) // _TRANSPORT_PAD_BUCKETS[-1]) + 1) * _TRANSPORT_PAD_BUCKETS[-1]
    return raw_json_bytes + (b" " * (target - raw_len))

# ─── Message Envelope ──────────────────────────────────────────────────────


class Priority(str, Enum):
    EMERGENCY = "emergency"  # SOS — broadcast on ALL transports simultaneously
    HIGH = "high"  # Time-sensitive — prefer fastest available
    NORMAL = "normal"  # Standard routing — optimize for efficiency
    LOW = "low"  # Batch-able — wait for optimal conditions


class PayloadType(str, Enum):
    TEXT = "text"  # Short text message (< 200 bytes ideal for LoRa)
    POSITION = "position"  # GPS coordinates + metadata
    TELEMETRY = "telemetry"  # Sensor data, battery, environment
    FILE = "file"  # Binary payload — requires high-bandwidth transport
    COMMAND = "command"  # Control message (channel join, ack, etc.)


def _normalize_trust_tier(value: str | None) -> str:
    return normalize_transport_tier(value)


def _supervisor_verified_trust_tier() -> str:
    """Return the current verified tier from wormhole_supervisor.

    Sprint 2 / Rec #7: single authoritative source of truth for the
    tier the node is actually operating at. Callers should never trust
    a caller-supplied tier without passing it through here. Failing to
    reach the supervisor falls closed to ``public_degraded``.
    """
    try:
        from services.wormhole_supervisor import get_transport_tier

        return _normalize_trust_tier(get_transport_tier())
    except Exception:
        return "public_degraded"


def _clamp_trust_tier(claimed: str | None) -> str:
    """Clamp a claimed tier to what the supervisor can actually deliver.

    Sprint 2 / Rec #2: silent auto-correction. If the caller claims a
    higher tier than the supervisor has verified, we lower the claim to
    match reality — a background safety-net so the user never sees an
    error they didn't cause.
    """
    claim = _normalize_trust_tier(claimed)
    verified = _supervisor_verified_trust_tier()
    if _TIER_RANK[claim] <= _TIER_RANK[verified]:
        return claim
    return verified


def _compute_integrity_hash(
    *,
    sender_id: str,
    destination: str,
    payload: str,
    timestamp: float,
    trust_tier: str,
) -> str:
    """Integrity hash bound to ``trust_tier``.

    Sprint 2 / Rec #2: including trust_tier in the hashed material means
    any attempt to rewrite the tier after the envelope is sealed (e.g.
    replay the same payload at ``public_degraded`` so the audit log
    stops redacting) breaks the hash and the receiver notices.
    """
    h = hashlib.sha256(
        f"{trust_tier}:{sender_id}:{destination}:{payload}:{timestamp}".encode()
    )
    return h.hexdigest()[:16]


@dataclass
class MeshEnvelope:
    """Canonical message format that all transports share.

    Every message in the system is wrapped in this envelope regardless of
    which transport carries it. This is the "lingua franca" of the mesh.
    """

    # Identity
    sender_id: str  # Node ID or callsign of sender
    destination: str  # Target node ID, callsign, or "broadcast"
    channel: str = "LongFast"  # Channel name (LongFast, Shadowbroker, etc.)

    # Routing metadata
    priority: Priority = Priority.NORMAL
    payload_type: PayloadType = PayloadType.TEXT
    ttl: int = 3  # Max hops before discard
    trust_tier: str = ""  # Resolved by __post_init__ via _clamp_trust_tier

    # Payload
    payload: str = ""  # The actual message content
    payload_bytes: int = 0  # Computed size for routing decisions

    # Provenance
    message_id: str = ""  # Unique ID (generated if empty)
    timestamp: float = 0.0  # Unix timestamp (generated if 0)
    # Integrity-only hash over (trust_tier, sender, destination, payload, timestamp).
    # Sprint 2 / Rec #2: trust_tier is now part of the hashed material so
    # downgraded replays don't match. NOT a crypto authentication
    # signature — use ``integrity_hash``.
    integrity_hash: str = ""

    # Retention
    ephemeral: bool = False  # If True, auto-purge after 24h

    # Routing result (filled by router)
    routed_via: str = ""  # Which transport was used
    route_reason: str = ""  # Why this transport was chosen

    def __post_init__(self):
        if not self.message_id:
            self.message_id = secrets.token_hex(8)
        if not self.timestamp:
            self.timestamp = time.time()
        if not self.payload_bytes:
            self.payload_bytes = len(self.payload.encode("utf-8"))
        # Sprint 2 / Rec #7: single authoritative source. Any caller-
        # supplied tier is clamped to what the supervisor has verified.
        self.trust_tier = _clamp_trust_tier(self.trust_tier)
        if not self.integrity_hash:
            self.integrity_hash = _compute_integrity_hash(
                sender_id=self.sender_id,
                destination=self.destination,
                payload=self.payload,
                timestamp=self.timestamp,
                trust_tier=self.trust_tier,
            )

    def reseal_for_tier(self, verified_tier: str) -> None:
        """Re-stamp the envelope for a new verified tier and rehash.

        Used by the router when the supervisor's tier has shifted
        between construction and dispatch. Silent and in-place so the
        user never sees a failure they didn't cause.
        """
        self.trust_tier = _normalize_trust_tier(verified_tier)
        self.integrity_hash = _compute_integrity_hash(
            sender_id=self.sender_id,
            destination=self.destination,
            payload=self.payload,
            timestamp=self.timestamp,
            trust_tier=self.trust_tier,
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Transport Adapters ────────────────────────────────────────────────────


class TransportResult:
    """Result of a transport send attempt.

    ``upgrade_action`` is a structured hint for the UI when a send could
    not complete because private transport is not up yet. When present,
    the frontend should prompt the user (e.g. "Switch to private and
    send?") and, on confirmation, invoke the referenced action
    (typically POST /api/wormhole/connect) then retry the send. This
    turns the safety stop into a one-click upgrade flow rather than a
    refusal.
    """

    def __init__(
        self,
        ok: bool,
        transport: str,
        detail: str = "",
        *,
        upgrade_action: dict | None = None,
    ):
        self.ok = ok
        self.transport = transport
        self.detail = detail
        self.upgrade_action = upgrade_action

    def to_dict(self) -> dict:
        out: dict = {"ok": self.ok, "transport": self.transport, "detail": self.detail}
        if self.upgrade_action:
            out["upgrade_action"] = self.upgrade_action
        return out


def _private_transport_outcomes(results: list[TransportResult]) -> list[dict[str, object]]:
    return [{"transport": result.transport, "ok": bool(result.ok)} for result in results]


class APRSTransport:
    """APRS-IS transport — sends text messages to ham radio callsigns."""

    NAME = "aprs"
    MAX_PAYLOAD = 67  # APRS message length limit

    def can_reach(self, envelope: MeshEnvelope) -> bool:
        """APRS can reach targets that look like ham callsigns."""
        dest = envelope.destination.upper()
        # Ham callsigns: 1-2 letters + digit + 1-3 letters, optional -SSID
        if dest == "broadcast":
            return False  # APRS doesn't support broadcast to all
        # Simple heuristic: contains a digit and is short
        return (
            any(c.isdigit() for c in dest)
            and len(dest.split("-")[0]) <= 6
            and envelope.payload_bytes <= self.MAX_PAYLOAD
        )

    def send(self, envelope: MeshEnvelope, credentials: dict) -> TransportResult:
        """Send via APRS-IS. Requires callsign + passcode in credentials."""
        from services.sigint_bridge import send_aprs_message

        callsign = credentials.get("aprs_callsign", "")
        passcode = credentials.get("aprs_passcode", "")
        if not callsign or not passcode:
            return TransportResult(False, self.NAME, "APRS requires callsign + passcode")

        result = send_aprs_message(callsign, passcode, envelope.destination, envelope.payload)
        return TransportResult(result["ok"], self.NAME, result["detail"])


class MeshtasticTransport:
    """Meshtastic MQTT transport — publishes messages to LoRa mesh via MQTT broker."""

    NAME = "meshtastic"
    MAX_PAYLOAD = 200  # LoRa practical payload limit

    @staticmethod
    def _mqtt_config() -> tuple[str, int, str, str]:
        """Return (broker, port, user, password) from settings."""
        try:
            from services.config import get_settings

            s = get_settings()
            return (
                str(s.MESH_MQTT_BROKER or "mqtt.meshtastic.org"),
                int(s.MESH_MQTT_PORT or 1883),
                str(s.MESH_MQTT_USER or "meshdev"),
                str(s.MESH_MQTT_PASS or "large4cats"),
            )
        except Exception:
            return ("mqtt.meshtastic.org", 1883, "meshdev", "large4cats")

    def can_reach(self, envelope: MeshEnvelope) -> bool:
        """Meshtastic can reach mesh nodes and supports broadcast."""
        # Meshtastic can broadcast to a channel or DM a node ID
        return envelope.payload_bytes <= self.MAX_PAYLOAD

    # Default LongFast PSK (firmware-hardcoded for PSK=0x01)
    DEFAULT_KEY = bytes(
        [
            0xD4,
            0xF1,
            0xBB,
            0x3A,
            0x20,
            0x29,
            0x07,
            0x59,
            0xF0,
            0xBC,
            0xFF,
            0xAB,
            0xCF,
            0x4E,
            0x69,
            0x01,
        ]
    )

    @classmethod
    def _resolve_psk(cls) -> bytes:
        """Return the PSK from config, or the default LongFast key if empty."""
        try:
            from services.config import get_settings
            raw = str(getattr(get_settings(), "MESH_MQTT_PSK", "") or "").strip()
        except Exception:
            raw = ""
        if not raw:
            return cls.DEFAULT_KEY
        return bytes.fromhex(raw)

    @staticmethod
    def _stable_node_id(sender_id: str) -> int:
        """Derive a stable 32-bit node id from sender_id."""
        digest = hashlib.sha256(sender_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big")

    @staticmethod
    def mesh_address_for_sender(sender_id: str) -> str:
        """Return the synthetic public mesh address used for MQTT-originated sends."""
        return f"!{MeshtasticTransport._stable_node_id(sender_id):08x}"

    @staticmethod
    def _parse_node_id(destination: str) -> Optional[int]:
        """Parse a Meshtastic-style node address like !a0cc7a80."""
        dest = (destination or "").strip().lower()
        if dest.startswith("!"):
            dest = dest[1:]
        if len(dest) != 8 or any(c not in "0123456789abcdef" for c in dest):
            return None
        try:
            return int(dest, 16)
        except ValueError:
            return None

    def send(self, envelope: MeshEnvelope, credentials: dict) -> TransportResult:
        """Publish protobuf-encoded, AES-encrypted message to Meshtastic MQTT."""
        try:
            import paho.mqtt.client as mqtt
            import struct
            import random
            from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        except ImportError as e:
            return TransportResult(False, self.NAME, f"Missing dependency: {e}")

        try:
            raw_root = credentials.get("mesh_root") or credentials.get("mesh_region", "US")
            region = normalize_root(str(raw_root or "US")) or "US"
            channel = envelope.channel or "LongFast"

            # Build Data payload
            data_msg = mesh_pb2.Data()
            data_msg.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
            data_msg.payload = envelope.payload.encode("utf-8")
            plaintext = data_msg.SerializeToString()

            # Generate IDs
            packet_id = random.randint(1, 0xFFFFFFFF)
            from_node = self._stable_node_id(envelope.sender_id)
            direct_node = self._parse_node_id(envelope.destination)
            to_node = direct_node if direct_node is not None else 0xFFFFFFFF

            # Encrypt (AES-CTR)
            psk = self._resolve_psk()
            nonce = struct.pack("<QQ", packet_id, from_node)
            cipher = Cipher(algorithms.AES(psk), modes.CTR(nonce))
            encryptor = cipher.encryptor()
            encrypted = encryptor.update(plaintext) + encryptor.finalize()

            # Build ServiceEnvelope protobuf
            se = mqtt_pb2.ServiceEnvelope()
            pkt = se.packet
            pkt.id = packet_id
            setattr(pkt, "from", from_node)
            pkt.to = to_node
            pkt.encrypted = encrypted
            pkt.hop_limit = 3
            pkt.want_ack = False
            se.channel_id = channel
            se.gateway_id = f"!{from_node:08x}"

            topic = f"msh/{region}/2/e/{channel}/!{from_node:08x}"
            payload = se.SerializeToString()

            # Publish with on_connect to avoid race condition
            published = [False]
            error_msg = [""]

            def _on_connect(client, userdata, flags, rc):
                if rc == 0:
                    info = client.publish(topic, payload, qos=0)
                    info.wait_for_publish(timeout=5)
                    published[0] = True
                    client.disconnect()
                else:
                    error_msg[0] = f"MQTT connect refused: rc={rc}"
                    client.disconnect()

            client = mqtt.Client(
                client_id=f"shadowbroker-tx-{envelope.message_id[:8]}", protocol=mqtt.MQTTv311
            )
            broker, port, user, pw = self._mqtt_config()
            client.username_pw_set(user, pw)
            client.on_connect = _on_connect
            client.connect(broker, port, keepalive=10)

            # Run loop until published or timeout
            deadline = time.time() + 8
            while time.time() < deadline and not published[0] and not error_msg[0]:
                client.loop(timeout=0.5)

            if error_msg[0]:
                return TransportResult(False, self.NAME, error_msg[0])
            if not published[0]:
                return TransportResult(False, self.NAME, "Publish timeout")

            target = f"!{to_node:08x}" if direct_node is not None else channel
            logger.info(f"Meshtastic TX [{region}/{channel} -> {target}]: {envelope.payload[:50]}")
            return TransportResult(
                True,
                self.NAME,
                (
                    f"Published direct to !{to_node:08x} via {region}/{channel}"
                    if direct_node is not None
                    else f"Published to {region}/{channel} ({len(payload)}B protobuf)"
                ),
            )
        except Exception as e:
            return TransportResult(False, self.NAME, f"MQTT error: {e}")


class _PeerPushTransportMixin:
    def __init__(self):
        self._peer_failures: dict[str, int] = {}
        self._peer_cooldown_until: dict[str, float] = {}
        self._consecutive_total_failures: int = 0

    def _get_peers(self) -> list[str]:
        if getattr(self, "NAME", "") == "tor_arti":
            return authenticated_push_peer_urls(transport="onion")
        return authenticated_push_peer_urls(transport="clearnet")

    def _is_peer_cooled_down(self, peer_url: str) -> bool:
        expiry = self._peer_cooldown_until.get(peer_url, 0.0)
        return time.time() < expiry

    def _record_peer_failure(self, peer_url: str):
        from services.config import get_settings

        settings = get_settings()
        self._peer_failures[peer_url] = self._peer_failures.get(peer_url, 0) + 1
        if self._peer_failures[peer_url] >= int(settings.MESH_RELAY_MAX_FAILURES or 3):
            cooldown_s = int(settings.MESH_RELAY_FAILURE_COOLDOWN_S or 120)
            self._peer_cooldown_until[peer_url] = time.time() + cooldown_s
            logger.warning(
                "Peer %s exceeded failure threshold — cooling down for %ss",
                peer_url,
                cooldown_s,
            )

    def _reset_peer_failures(self, peer_url: str):
        self._peer_failures.pop(peer_url, None)
        self._peer_cooldown_until.pop(peer_url, None)

    def _build_peer_push_request(
        self, envelope: MeshEnvelope, push_source: str
    ) -> tuple[str, "Callable[[str], bytes]"]:
        """Return ``(endpoint_path, build_for_peer)``.

        Sprint 3 / Rec #4: ``build_for_peer(peer_url)`` yields the padded
        wire bytes for a specific destination peer. Gate messages carry
        a pair-bound ``gate_ref`` that is unique per receiver — a peer
        who sniffs a push intended for another receiver cannot derive
        the matching ref, so enumeration via a global secret is closed.
        The raw length is invariant across peers (gate_ref is always a
        64-char SHA-256 hexdigest) so padding buckets remain stable.
        """
        evt_dict = envelope.to_dict()
        payload_candidate = envelope.payload
        if isinstance(payload_candidate, str):
            try:
                decoded = json.loads(payload_candidate)
            except Exception:
                decoded = None
            if isinstance(decoded, dict) and decoded.get("event_type"):
                evt_dict = decoded

        if evt_dict.get("event_type") == "gate_message":
            from services.mesh.mesh_hashchain import build_gate_wire_ref

            payload_info = evt_dict.get("payload") if isinstance(evt_dict.get("payload"), dict) else {}
            gate_id = str(payload_info.get("gate", "") or "").strip().lower()
            base_evt: dict[str, Any] = {
                "event_type": "gate_message",
                "timestamp": evt_dict.get("timestamp", 0),
                "payload": {
                    "ciphertext": str(payload_info.get("ciphertext", "") or ""),
                    "format": str(payload_info.get("format", "") or ""),
                },
            }
            nonce = str(payload_info.get("nonce", "") or "")
            sender_ref = str(payload_info.get("sender_ref", "") or "")
            epoch = int(payload_info.get("epoch", 0) or 0)
            if nonce:
                base_evt["payload"]["nonce"] = nonce
            if sender_ref:
                base_evt["payload"]["sender_ref"] = sender_ref
            if epoch > 0:
                base_evt["payload"]["epoch"] = epoch
            for field_name in (
                "event_id",
                "node_id",
                "sequence",
                "signature",
                "public_key",
                "public_key_algo",
                "protocol_version",
            ):
                value = evt_dict.get(field_name, "")
                if value not in ("", None):
                    base_evt[field_name] = value

            def _build_for_peer(peer_url: str) -> bytes:
                gate_ref = build_gate_wire_ref(gate_id, base_evt, peer_url=peer_url)
                if not gate_ref:
                    raise ValueError(
                        "private gate forwarding requires MESH_PEER_PUSH_SECRET and a known peer URL"
                    )
                peer_evt = {
                    **base_evt,
                    "payload": {**base_evt["payload"], "gate_ref": gate_ref},
                }
                payload = {"events": [peer_evt], "push_source": push_source}
                return _pad_transport_payload(
                    json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                )

            return "/api/mesh/gate/peer-push", _build_for_peer

        payload = {"events": [evt_dict], "push_source": push_source}
        cached = _pad_transport_payload(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )

        def _build_cached(_peer_url: str) -> bytes:
            return cached

        return "/api/mesh/infonet/peer-push", _build_cached


class InternetTransport(_PeerPushTransportMixin):
    """Clearnet relay transport — pushes events to peers over plain HTTPS/HTTP."""

    NAME = "internet"

    def __init__(self):
        super().__init__()

    def can_reach(self, envelope: MeshEnvelope) -> bool:
        return bool(self._get_peers())

    def send(self, envelope: MeshEnvelope, credentials: dict) -> TransportResult:
        import requests as _requests
        from services.config import get_settings

        settings = get_settings()
        peers = self._get_peers()
        if not peers:
            return TransportResult(False, self.NAME, "No relay peers configured")

        timeout = int(settings.MESH_RELAY_PUSH_TIMEOUT_S or 10)
        try:
            endpoint_path, padded = self._build_peer_push_request(envelope, self.NAME)
        except ValueError as exc:
            return TransportResult(False, self.NAME, str(exc))
        secret = str(settings.MESH_PEER_PUSH_SECRET or "").strip()

        delivered = 0
        last_error = ""
        for peer_url in peers:
            if self._is_peer_cooled_down(peer_url):
                continue
            try:
                normalized_peer_url = normalize_peer_url(peer_url)
                headers = {"Content-Type": "application/json"}
                if secret:
                    peer_key = _derive_peer_key(secret, normalized_peer_url)
                    if not peer_key:
                        raise ValueError("invalid peer URL for HMAC derivation")
                    headers["X-Peer-Url"] = normalized_peer_url
                    headers["X-Peer-HMAC"] = hmac.new(
                        peer_key,
                        padded,
                        hashlib.sha256,
                    ).hexdigest()
                url = f"{peer_url}{endpoint_path}"
                resp = _requests.post(
                    url,
                    data=padded,
                    timeout=timeout,
                    headers=headers,
                )
                ok = resp.status_code == 200
                logger.info(
                    "TRANSPORT_AUDIT_PEER peer=%s transport=%s ok=%s detail=%s",
                    _peer_audit_label(peer_url),
                    self.NAME,
                    ok,
                    f"HTTP {resp.status_code}",
                )
                if ok:
                    self._reset_peer_failures(peer_url)
                    delivered += 1
                else:
                    last_error = f"{peer_url}: HTTP {resp.status_code}"
                    self._record_peer_failure(peer_url)
            except Exception as exc:
                last_error = f"{peer_url}: {type(exc).__name__}"
                logger.info(
                    "TRANSPORT_AUDIT_PEER peer=%s transport=%s ok=%s detail=%s",
                    _peer_audit_label(peer_url),
                    self.NAME,
                    False,
                    type(exc).__name__,
                )
                self._record_peer_failure(peer_url)

        if delivered > 0:
            self._consecutive_total_failures = 0
            return TransportResult(
                True, self.NAME, f"Delivered to {delivered}/{len(peers)} peers via clearnet"
            )

        self._consecutive_total_failures += 1
        return TransportResult(False, self.NAME, f"All peers failed — last: {last_error}")


class TorArtiTransport(_PeerPushTransportMixin):
    """Tor/Arti transport — forwards peer pushes through the local SOCKS5 proxy."""

    NAME = "tor_arti"

    def __init__(self):
        super().__init__()

    def can_reach(self, envelope: MeshEnvelope) -> bool:
        from services.config import get_settings
        from services.wormhole_supervisor import _check_arti_ready

        settings = get_settings()
        return bool(settings.MESH_ARTI_ENABLED) and _check_arti_ready() and bool(self._get_peers())

    def send(self, envelope: MeshEnvelope, credentials: dict) -> TransportResult:
        import requests as _requests
        from services.config import get_settings

        settings = get_settings()
        peers = self._get_peers()
        if not peers:
            return TransportResult(False, self.NAME, "No relay peers configured")

        socks_port = int(settings.MESH_ARTI_SOCKS_PORT or 9050)
        timeout = int(settings.MESH_RELAY_PUSH_TIMEOUT_S or 10)
        proxy = f"socks5h://127.0.0.1:{socks_port}"
        proxies = {"http": proxy, "https": proxy}

        try:
            endpoint_path, padded = self._build_peer_push_request(envelope, self.NAME)
        except ValueError as exc:
            return TransportResult(False, self.NAME, str(exc))
        secret = str(settings.MESH_PEER_PUSH_SECRET or "").strip()

        delivered = 0
        last_error = ""
        for peer_url in peers:
            if self._is_peer_cooled_down(peer_url):
                continue
            try:
                normalized_peer_url = normalize_peer_url(peer_url)
                headers = {"Content-Type": "application/json"}
                if secret:
                    peer_key = _derive_peer_key(secret, normalized_peer_url)
                    if not peer_key:
                        raise ValueError("invalid peer URL for HMAC derivation")
                    headers["X-Peer-Url"] = normalized_peer_url
                    headers["X-Peer-HMAC"] = hmac.new(
                        peer_key,
                        padded,
                        hashlib.sha256,
                    ).hexdigest()
                url = f"{peer_url}{endpoint_path}"
                resp = _requests.post(
                    url,
                    data=padded,
                    proxies=proxies,
                    timeout=timeout,
                    headers=headers,
                )
                ok = resp.status_code == 200
                logger.info(
                    "TRANSPORT_AUDIT_PEER peer=%s transport=%s ok=%s detail=%s",
                    _peer_audit_label(peer_url),
                    self.NAME,
                    ok,
                    f"HTTP {resp.status_code}",
                )
                if ok:
                    self._reset_peer_failures(peer_url)
                    delivered += 1
                else:
                    last_error = f"{peer_url}: HTTP {resp.status_code}"
                    self._record_peer_failure(peer_url)
            except Exception as exc:
                last_error = f"{peer_url}: {type(exc).__name__}"
                logger.info(
                    "TRANSPORT_AUDIT_PEER peer=%s transport=%s ok=%s detail=%s",
                    _peer_audit_label(peer_url),
                    self.NAME,
                    False,
                    type(exc).__name__,
                )
                self._record_peer_failure(peer_url)

        if delivered > 0:
            self._consecutive_total_failures = 0
            return TransportResult(True, self.NAME, f"Delivered to {delivered}/{len(peers)} peers via Tor")

        self._consecutive_total_failures += 1
        if self._consecutive_total_failures >= int(settings.MESH_RELAY_MAX_FAILURES or 3):
            logger.warning(
                "TRANSPORT_DEGRADED: tor_arti has failed %d consecutive sends — will re-check on next supervisor refresh",
                self._consecutive_total_failures,
            )
        return TransportResult(False, self.NAME, f"All peers failed — last: {last_error}")


# ─── Conditional Gate Router ───────────────────────────────────────────────


class CircuitBreaker:
    """Automatic RF safety valve — prevents flooding external radio networks.

    Tracks outbound message counts per transport per 10-minute window.
    Soft limit: log warning, reject low-priority sends.
    Hard limit: disable transport entirely for a cooldown period.
    """

    def __init__(
        self,
        transport_name: str,
        soft_limit: int,
        hard_limit: int,
        cooldown_seconds: int = 1800,
        window_seconds: int = 600,
    ):
        self.transport_name = transport_name
        self.soft_limit = soft_limit
        self.hard_limit = hard_limit
        self.cooldown_seconds = cooldown_seconds
        self.window_seconds = window_seconds
        self.send_times: deque[float] = deque()
        self.air_gapped_until: float = 0.0

    def _prune_window(self):
        """Remove timestamps older than the sliding window."""
        cutoff = time.time() - self.window_seconds
        while self.send_times and self.send_times[0] < cutoff:
            self.send_times.popleft()

    def is_air_gapped(self) -> bool:
        """Check if transport is currently disabled."""
        if self.air_gapped_until and time.time() < self.air_gapped_until:
            return True
        if self.air_gapped_until and time.time() >= self.air_gapped_until:
            self.air_gapped_until = 0.0  # Cooldown expired
        return False

    def check_and_record(self, priority: "Priority") -> tuple[bool, str]:
        """Check if a send is allowed and record it.

        Returns (allowed: bool, reason: str).
        """
        if self.is_air_gapped():
            remaining = int(self.air_gapped_until - time.time())
            return False, (
                f"{self.transport_name} CIRCUIT BREAKER: RF injection suspended "
                f"({remaining}s remaining) — too many outbound messages"
            )

        self._prune_window()
        count = len(self.send_times)

        # Hard limit → air-gap the transport
        if count >= self.hard_limit:
            self.air_gapped_until = time.time() + self.cooldown_seconds
            logger.warning(
                f"CIRCUIT BREAKER [{self.transport_name}]: HARD LIMIT {self.hard_limit} reached — "
                f"transport disabled for {self.cooldown_seconds}s"
            )
            return False, (
                f"{self.transport_name} temporarily suspended (network protection, "
                f"{self.cooldown_seconds}s cooldown). Message will be rerouted."
            )

        # Soft limit → reject non-emergency, non-high priority
        if count >= self.soft_limit and priority not in (Priority.EMERGENCY, Priority.HIGH):
            logger.warning(
                f"CIRCUIT BREAKER [{self.transport_name}]: Soft limit {self.soft_limit} reached — "
                f"rejecting low-priority send ({count}/{self.hard_limit})"
            )
            return False, (
                f"{self.transport_name} approaching rate limit "
                f"({count}/{self.hard_limit}). Only high-priority messages accepted."
            )

        # Allowed — record the send
        self.send_times.append(time.time())
        return True, ""

    def get_status(self) -> dict:
        """Return current circuit breaker status for diagnostics."""
        self._prune_window()
        return {
            "transport": self.transport_name,
            "window_count": len(self.send_times),
            "soft_limit": self.soft_limit,
            "hard_limit": self.hard_limit,
            "air_gapped": self.is_air_gapped(),
            "air_gapped_remaining": (
                max(0, int(self.air_gapped_until - time.time())) if self.air_gapped_until else 0
            ),
        }


class MeshRouter:
    """Policy-driven router that picks the optimal transport for each message.

    Gate logic:
      1. EMERGENCY → blast on ALL available transports simultaneously
      2. Small text (< 67 chars) to APRS callsign → APRS-IS
      3. Small text (< 200 bytes) to mesh or broadcast → Meshtastic MQTT
      4. Large payload → Internet relay (future WiFi mesh / Reticulum)
      5. Fallback → try each transport in capability order

    Circuit breakers protect external radio networks from being flooded.
    """

    def __init__(self):
        self.aprs = APRSTransport()
        self.meshtastic = MeshtasticTransport()
        self.tor_arti = TorArtiTransport()
        self.internet = InternetTransport()
        self.transports = [self.aprs, self.meshtastic, self.tor_arti, self.internet]
        # Message log for audit trail / provenance
        self.message_log: deque[dict] = deque(maxlen=500)
        self.tier_events: deque[dict[str, Any]] = deque(maxlen=_TIER_EVENT_MAXLEN)
        self._dedupe: dict[str, float] = {}
        self._last_supervisor_tier: str = ""
        # Per-process random salt for dedupe keys — prevents a restarted
        # observer from correlating pre- and post-restart dedupe fingerprints
        # across a node.
        self._dedupe_salt: bytes = secrets.token_bytes(16)
        # Circuit breakers — protect external networks
        self.breakers = {
            "aprs": CircuitBreaker("APRS", soft_limit=20, hard_limit=50, cooldown_seconds=1800),
            "meshtastic": CircuitBreaker(
                "Meshtastic", soft_limit=60, hard_limit=150, cooldown_seconds=900
            ),
        }

    def record_tier_event(
        self,
        event: str,
        *,
        previous_tier: str = "",
        current_tier: str = "",
        detail: str = "",
        route_reason: str = "",
        transport: str = "",
        lane: str = "",
        hidden_transport_effective: bool | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "event": str(event or "").strip().lower(),
            "timestamp": time.time(),
        }
        if previous_tier:
            entry["previous_tier"] = str(previous_tier or "").strip().lower()
        if current_tier:
            entry["current_tier"] = str(current_tier or "").strip().lower()
        if detail:
            entry["detail"] = str(detail or "")
        if route_reason:
            entry["route_reason"] = str(route_reason or "")
        if transport:
            entry["transport"] = str(transport or "")
        if lane:
            entry["lane"] = str(lane or "")
        if hidden_transport_effective is not None:
            entry["hidden_transport_effective"] = bool(hidden_transport_effective)
        for key, value in extra.items():
            if value not in ("", None):
                entry[key] = value
        self.tier_events.append(entry)
        return entry

    def prune_message_log(self, now: float | None = None) -> None:
        from services.config import get_settings

        ttl_s = int(getattr(get_settings(), "MESH_PRIVATE_LOG_TTL_S", 900) or 0)
        if ttl_s <= 0 or not self.message_log:
            return
        cutoff = float(now if now is not None else time.time()) - float(ttl_s)
        filtered: list[dict] = []
        changed = False
        for entry in self.message_log:
            tier_str = str((entry or {}).get("trust_tier", "") or "").strip().lower()
            if tier_str.startswith("private_"):
                ts = float((entry or {}).get("timestamp", 0) or 0.0)
                if ts > 0 and ts < cutoff:
                    changed = True
                    continue
            filtered.append(entry)
        if changed:
            self.message_log = deque(filtered, maxlen=self.message_log.maxlen)

    def _dedupe_key(self, envelope: MeshEnvelope) -> str:
        base = f"{envelope.sender_id}:{envelope.destination}:{envelope.payload}"
        return hashlib.sha256(self._dedupe_salt + base.encode("utf-8")).hexdigest()

    def _prune_dedupe(self, now: float):
        cutoff = now - DEDUP_TTL_SECONDS
        for key, ts in list(self._dedupe.items()):
            if ts < cutoff:
                del self._dedupe[key]
        if len(self._dedupe) > DEDUP_MAX_ENTRIES:
            # Drop oldest entries if we exceeded max
            for key, _ in sorted(self._dedupe.items(), key=lambda kv: kv[1])[
                : len(self._dedupe) - DEDUP_MAX_ENTRIES
            ]:
                del self._dedupe[key]

    def _is_duplicate(self, envelope: MeshEnvelope) -> bool:
        now = time.time()
        self._prune_dedupe(now)
        key = self._dedupe_key(envelope)
        if key in self._dedupe:
            return True
        self._dedupe[key] = now
        return False

    def route(self, envelope: MeshEnvelope, credentials: dict) -> list[TransportResult]:
        """Route a message through the optimal transport(s).

        Returns list of TransportResult (multiple for EMERGENCY broadcast).
        """
        results: list[TransportResult] = []
        # Sprint 2 / Rec #2 + #7: re-verify the envelope's trust_tier
        # against the supervisor at dispatch time. If the caller
        # constructed the envelope when private was ready but private
        # has since flapped, silently reseal the envelope for the
        # current verified tier — the user doesn't see a failure, the
        # routing decision just uses truth. We never upgrade a claim
        # beyond what the supervisor confirms.
        verified_tier = _supervisor_verified_trust_tier()
        if verified_tier != self._last_supervisor_tier:
            self.record_tier_event(
                "tier_change",
                previous_tier=self._last_supervisor_tier,
                current_tier=verified_tier,
                detail="supervisor_verified_trust_tier_changed",
            )
            self._last_supervisor_tier = verified_tier
        if _TIER_RANK[_normalize_trust_tier(envelope.trust_tier)] > _TIER_RANK[verified_tier]:
            logger.info(
                "[mesh] trust_tier auto-clamped from %s to %s before dispatch",
                envelope.trust_tier,
                verified_tier,
            )
            self.record_tier_event(
                "tier_fallback",
                previous_tier=str(envelope.trust_tier or ""),
                current_tier=verified_tier,
                detail="dispatch_auto_clamp",
            )
            envelope.reseal_for_tier(verified_tier)
        private_tier = str(envelope.trust_tier or "public_degraded").strip().lower().startswith(
            "private_"
        )

        if self._is_duplicate(envelope):
            envelope.route_reason = "Duplicate suppressed (loop protection)"
            results.append(TransportResult(False, "dedupe", "Duplicate message suppressed"))
            self._log(envelope, results)
            return results

        # ─── Gate 1: EMERGENCY → broadcast on ALL transports ───────────
        if envelope.priority == Priority.EMERGENCY:
            envelope.route_reason = "EMERGENCY — broadcasting on all available transports"
            tier_str = str(envelope.trust_tier or "public_degraded").strip().lower()
            for transport in self.transports:
                if private_tier and transport.NAME in {"aprs", "meshtastic"}:
                    continue
                if private_tier and transport.NAME == "internet":
                    continue
                if transport.can_reach(envelope):
                    r = transport.send(envelope, credentials)
                    results.append(r)
                    if r.ok:
                        envelope.routed_via += f"{transport.NAME},"
            self._log(envelope, results)
            return results

        # ─── Gate 2: APRS callsign target → APRS-IS ───────────────────
        if not private_tier and self.aprs.can_reach(envelope):
            # Check circuit breaker before sending
            cb_ok, cb_reason = self.breakers["aprs"].check_and_record(envelope.priority)
            if not cb_ok:
                results.append(TransportResult(False, self.aprs.NAME, cb_reason))
                # Fall through to Gate 3 instead of failing
            else:
                envelope.route_reason = "Target is APRS callsign, payload fits APRS limit"
                r = self.aprs.send(envelope, credentials)
                if r.ok:
                    envelope.routed_via = self.aprs.NAME
                    results.append(r)
                    self._log(envelope, results)
                    return results
                # APRS failed (no credentials?) — fall through to next gate
                results.append(r)

        # ─── Gate 3: Small payload → Meshtastic LoRa ──────────────────
        if not private_tier and self.meshtastic.can_reach(envelope):
            # Check circuit breaker before sending
            cb_ok, cb_reason = self.breakers["meshtastic"].check_and_record(envelope.priority)
            if not cb_ok:
                results.append(TransportResult(False, self.meshtastic.NAME, cb_reason))
                # Fall through to Gate 4
            else:
                if self.meshtastic._parse_node_id(envelope.destination) is not None:
                    envelope.route_reason = (
                        "Target is Meshtastic node ID, routing as public node-targeted message via Meshtastic MQTT"
                    )
                else:
                    envelope.route_reason = "Payload fits LoRa, routing via Meshtastic MQTT"
                r = self.meshtastic.send(envelope, credentials)
                if r.ok:
                    envelope.routed_via = self.meshtastic.NAME
                    results.append(r)
                    self._log(envelope, results)
                    return results
                results.append(r)

        # ─── Gate 4: Large payload or fallback → Internet relay ───────
        tier_str = str(envelope.trust_tier or "public_degraded").strip().lower()

        if tier_str == "private_strong":
            # private_strong MUST use Tor — no clearnet fallback
            if self.tor_arti.can_reach(envelope):
                envelope.route_reason = "PRIVATE_STRONG — Tor required, no clearnet fallback"
                tor_result = self.tor_arti.send(envelope, credentials)
                results.append(tor_result)
                if tor_result.ok:
                    envelope.routed_via = self.tor_arti.NAME
                    self._log(envelope, results)
                    return results
            envelope.route_reason = (
                "PRIVATE_STRONG — Tor unavailable or failed, prompting upgrade"
            )
            results.append(
                TransportResult(
                    False,
                    "policy",
                    "Private transport (Tor) is not up yet. Switch to private to send?",
                    upgrade_action={
                        "type": "enable_private_transport",
                        "endpoint": "/api/wormhole/connect",
                        "method": "POST",
                        "prompt": "Switch to private transport and send?",
                        "reason": "private_transport_not_ready",
                        "retry_after": True,
                    },
                )
            )
            self._log(envelope, results)
            return results

        elif private_tier:
            # Sprint 1 / Rec #3: private_transitional prefers Tor. If Tor
            # isn't up, we do NOT silently leak the payload over clearnet —
            # instead we return a structured upgrade_action so the UI can
            # ask the user "switch to private and send?" and, on consent,
            # POST /api/wormhole/connect then retry the send. This turns
            # the safety stop into a one-click upgrade rather than a
            # hostile refusal.
            if self.tor_arti.can_reach(envelope):
                envelope.route_reason = "PRIVATE payload prefers tor_arti when available"
                tor_result = self.tor_arti.send(envelope, credentials)
                results.append(tor_result)
                if tor_result.ok:
                    envelope.routed_via = self.tor_arti.NAME
                    self._log(envelope, results)
                    return results
            if _high_privacy_profile_blocks_clearnet_fallback():
                envelope.route_reason = (
                    "PRIVATE_TRANSITIONAL — private transport not ready, prompting upgrade"
                )
                results.append(
                    TransportResult(
                        False,
                        "policy",
                        "Private transport (Tor) is not up yet. Switch to private to send?",
                        upgrade_action={
                            "type": "enable_private_transport",
                            "endpoint": "/api/wormhole/connect",
                            "method": "POST",
                            "prompt": "Switch to private transport and send?",
                            "reason": "private_transport_not_ready",
                            "retry_after": True,
                        },
                    )
                )
                self._log(envelope, results)
                return results
            # Explicit opt-in path: operator set MESH_PRIVATE_CLEARNET_FALLBACK=allow
            # with acknowledgement — log loudly before degrading.
            logger.warning(
                "[mesh] private_transitional falling through to clearnet — operator opted in via MESH_PRIVATE_CLEARNET_FALLBACK=allow"
            )

        envelope.route_reason = (
            "Payload too large for radio or radio transports failed — internet relay"
        )
        if private_tier:
            logger.warning(
                "[mesh] Transport degradation: message sent via clearnet, expected private transport"
            )
            metrics_inc("silent_degradations")
            self.record_tier_event(
                "fallback",
                current_tier=tier_str,
                detail="private_payload_sent_via_clearnet_relay",
                route_reason=envelope.route_reason,
                transport=self.internet.NAME,
            )
        r = self.internet.send(envelope, credentials)
        envelope.routed_via = self.internet.NAME
        results.append(r)
        self._log(envelope, results)
        return results

    def _log(self, envelope: MeshEnvelope, results: list[TransportResult]):
        """Record message in audit log for provenance tracking.

        Private-tier messages get redacted logs — no sender, destination,
        integrity_hash, or payload preview. Only routing metadata is logged.
        """
        tier_str = str(envelope.trust_tier or "public_degraded").strip().lower()
        is_private = tier_str.startswith("private_")

        self.prune_message_log()

        entry = {
            "priority": envelope.priority.value,
            "routed_via": envelope.routed_via,
            "route_reason": envelope.route_reason,
            "timestamp": envelope.timestamp,
            "trust_tier": tier_str,
        }
        if is_private:
            entry["transport_outcomes"] = _private_transport_outcomes(results)
        else:
            entry["message_id"] = envelope.message_id
            entry["channel"] = envelope.channel
            entry["payload_type"] = envelope.payload_type.value
            entry["payload_bytes"] = envelope.payload_bytes
            entry["results"] = [r.to_dict() for r in results]
            entry["sender"] = envelope.sender_id
            entry["destination"] = envelope.destination
            entry["payload_preview"] = envelope.payload[:50]
            entry["integrity_hash"] = envelope.integrity_hash

        self.message_log.append(entry)
        any_ok = any(r.ok for r in results)
        level = "info" if any_ok else "warning"
        if is_private:
            getattr(logger, level)(
                "TRANSPORT_AUDIT tier=%s transports=%s ok=%s reason=%s",
                tier_str,
                ",".join(r.transport for r in results),
                ",".join(str(r.ok) for r in results),
                envelope.route_reason,
            )
        else:
            getattr(logger, level)(
                "TRANSPORT_AUDIT msg_id=%s tier=%s transports=%s ok=%s destination=%s reason=%s",
                envelope.message_id,
                tier_str,
                ",".join(r.transport for r in results),
                ",".join(str(r.ok) for r in results),
                envelope.destination,
                envelope.route_reason,
            )


# Module-level singleton
mesh_router = MeshRouter()
