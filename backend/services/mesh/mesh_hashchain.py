"""Infonet — append-only signed event ledger for decentralized consensus.

The Infonet is ShadowBroker's consensus protocol. Every action on the mesh
(message, vote, gate creation, oracle prediction) becomes a chain event.
Each event references the previous event's hash, creating an immutable
ordered sequence. No mining, no proof-of-work — just cryptographic linking
and signature verification.

This is the consensus layer. The reputation, gates, and oracle systems are the
application layer that sits on top.

Event types:
  - message:      Public broadcast message
  - vote:         Reputation vote (+1/-1 on a node)
  - gate_create:  New gate/community creation
  - prediction:   Oracle market prediction
  - stake:        Oracle truth stake
  - key_rotate:   Link old and new public keys
  - key_revoke:   Revoke a compromised key (with grace window)

Private DM registration, mailbox access, and transport routing metadata are
intentionally kept off-ledger.

Each event contains:
  - event_id:     SHA-256 hash of (prev_hash + type + payload + timestamp + node_id)
  - prev_hash:    Hash of the previous event (chain link)
  - type:         Event type string
  - node_id:      Author's node ID
  - payload:      Event-specific data
  - timestamp:    Unix timestamp
  - sequence:     Per-node monotonic sequence number (replay protection)
  - signature:    Node's cryptographic signature

Persistence: JSON file at backend/data/infonet.json

Encrypted gate chat events are intentionally kept off the public chain and
persisted separately via GateMessageStore.
"""

import json
import os
import time
import hmac
import hashlib
import logging
import threading
import atexit
import tempfile
import base64
import zlib
from pathlib import Path
from collections import deque
from typing import Any

from services.mesh.mesh_secure_storage import read_domain_json, write_domain_json
from services.mesh.mesh_crypto import (
    build_signature_payload,
    parse_public_key_algo,
    verify_node_binding,
    verify_signature,
)
from services.mesh.mesh_protocol import NETWORK_ID, PROTOCOL_VERSION, normalize_payload
from services.mesh.mesh_schema import (
    ACTIVE_PUBLIC_LEDGER_EVENT_TYPES,
    PUBLIC_LEDGER_EVENT_TYPES,
    validate_event_payload,
    validate_protocol_fields,
    validate_public_ledger_payload,
)

logger = logging.getLogger("services.mesh_hashchain")
_PRIVACY_LOGS = os.environ.get("MESH_PRIVACY_LOGS", "").strip().lower() in ("1", "true", "yes")
_MESH_ONLY = os.environ.get("MESH_ONLY", "").strip().lower() in ("1", "true", "yes")


def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _redact_node(node_id: str) -> str:
    if not node_id:
        return ""
    if _PRIVACY_LOGS or _MESH_ONLY:
        return f"{node_id[:6]}…"
    return node_id


def _atomic_write_text(target: Path, content: str, encoding: str = "utf-8") -> None:
    """Write content atomically via temp file + os.replace()."""
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(target))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CHAIN_FILE = DATA_DIR / "infonet.json"
WAL_FILE = DATA_DIR / "infonet.wal"
GATE_STORE_DIR = DATA_DIR / "gate_messages"
GATE_STORAGE_DOMAIN = "gates"

# ─── Constants ────────────────────────────────────────────────────────────

GENESIS_HASH = "0" * 64  # The "previous hash" for the first event
MAX_CHAIN_MEMORY = 50000  # Max events to keep in memory (older ones on disk only)
EPHEMERAL_TTL = 86400  # 24 hours — ephemeral messages auto-purge
MESSAGE_RETENTION_DAYS = 90  # Non-ephemeral messages kept for 90 days
CHAIN_LOCK_DEPTH = 6
GATE_REPLAY_WINDOW_S = 86400 * 30
GATE_REPLAY_PRUNE_INTERVAL = 256
GATE_SEGMENT_EVENT_TARGET = max(1, int(os.environ.get("MESH_GATE_SEGMENT_EVENT_TARGET", "1000") or "1000"))
GATE_SEGMENT_MAX_COMPRESSED_BYTES = max(
    16 * 1024,
    int(os.environ.get("MESH_GATE_SEGMENT_MAX_COMPRESSED_BYTES", str(2 * 1024 * 1024)) or str(2 * 1024 * 1024)),
)
GATE_SEGMENT_STORAGE_VERSION = 1
_PUBLIC_EVENT_APPEND_HOOKS: list[Any] = []
_PUBLIC_EVENT_APPEND_HOOKS_LOCK = threading.Lock()


def register_public_event_append_hook(callback: Any) -> None:
    if callback is None:
        return
    with _PUBLIC_EVENT_APPEND_HOOKS_LOCK:
        if callback not in _PUBLIC_EVENT_APPEND_HOOKS:
            _PUBLIC_EVENT_APPEND_HOOKS.append(callback)


def unregister_public_event_append_hook(callback: Any) -> None:
    with _PUBLIC_EVENT_APPEND_HOOKS_LOCK:
        if callback in _PUBLIC_EVENT_APPEND_HOOKS:
            _PUBLIC_EVENT_APPEND_HOOKS.remove(callback)


def _notify_public_event_append_hooks(event_dict: dict[str, Any]) -> None:
    with _PUBLIC_EVENT_APPEND_HOOKS_LOCK:
        hooks = list(_PUBLIC_EVENT_APPEND_HOOKS)
    for hook in hooks:
        try:
            hook(dict(event_dict))
        except Exception:
            logger.exception("public event append hook failed")


# ─── Network Identity ────────────────────────────────────────────────────
# NETWORK_ID is defined in services.mesh_protocol to avoid circular imports.

# ─── Protocol Constraints ────────────────────────────────────────────────

ACTIVE_APPEND_EVENT_TYPES = set(ACTIVE_PUBLIC_LEDGER_EVENT_TYPES)
"""Event types allowed for new append() calls — gate_message excluded since S3A/S4B."""

ALLOWED_EVENT_TYPES = set(PUBLIC_LEDGER_EVENT_TYPES)
"""Full set including legacy types — used by ingest_events() and apply_fork()."""

MAX_PAYLOAD_BYTES = 4096
REPLAY_FILTER_BITS = 1_000_000
REPLAY_FILTER_HASHES = 3
REPLAY_FILTER_ROTATE_S = 3600
CRITICAL_EVENT_TYPES = {"key_rotate", "key_revoke"}
MIN_CONFIRMATIONS_CRITICAL = 3


def _gate_wire_event_material(event: dict[str, Any]) -> str:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    material = {
        "event_type": str(event.get("event_type", "gate_message") or "gate_message"),
        "timestamp": float(event.get("timestamp", 0) or 0),
        "ciphertext": str(payload.get("ciphertext", "") or ""),
        "format": str(payload.get("format", "") or ""),
    }
    return json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_gate_replay_fingerprint(gate_id: str, event: dict[str, Any]) -> str:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    material = {
        "gate": str(gate_id or "").strip().lower(),
        "event_type": "gate_message",
        "timestamp": float(event.get("timestamp", 0) or 0),
        "ciphertext": str(payload.get("ciphertext", "") or ""),
        "nonce": str(payload.get("nonce", "") or ""),
        "format": str(payload.get("format", "") or ""),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _peer_pair_ref_key(peer_url: str) -> bytes:
    """Derive a per-hop HMAC key for gate wire refs.

    Sprint 3 / Rec #4: the wire ref used to be HMAC-keyed by the
    global ``MESH_PEER_PUSH_SECRET``, which let any authenticated peer
    enumerate gate memberships by HMACing every gate_id they knew. The
    new key is bound to the authenticated *hop* (the receiving peer's
    URL) via the same HKDF chain as the peer-push HMAC, with a fresh
    domain separator. A peer who intercepts push traffic addressed to
    *another* receiver cannot derive the matching key — they only
    learn gate_ids on pushes where they are the intended receiver,
    which they would learn anyway via MLS membership.

    Returns an empty key on misconfiguration so callers fail closed.
    """
    try:
        from services.config import get_settings
        from services.mesh.mesh_crypto import _derive_peer_key, normalize_peer_url

        secret = str(get_settings().MESH_PEER_PUSH_SECRET or "").strip()
    except Exception:
        return b""
    if not secret:
        return b""
    normalized = normalize_peer_url(peer_url or "")
    if not normalized:
        return b""
    peer_key = _derive_peer_key(secret, normalized)
    if not peer_key:
        return b""
    # Domain-separate from the transport HMAC key so the two
    # derivations can't cross-contaminate in analysis.
    return hmac.new(peer_key, b"sb-gate-ref-v2", hashlib.sha256).digest()


def build_gate_wire_ref(
    gate_id: str,
    event: dict[str, Any],
    *,
    peer_url: str = "",
) -> str:
    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return ""
    key = _peer_pair_ref_key(peer_url)
    if not key:
        return ""
    material = f"{gate_key}|{_gate_wire_event_material(event)}".encode("utf-8")
    return hmac.new(key, material, hashlib.sha256).hexdigest()


def resolve_gate_wire_ref(
    gate_ref: str,
    event: dict[str, Any],
    *,
    peer_url: str = "",
) -> str:
    ref = str(gate_ref or "").strip().lower()
    if not ref:
        return ""
    if not peer_url:
        # Sprint 3 / Rec #4: pair-binding is mandatory. Refuse to
        # resolve refs that don't identify the hop — fail-closed
        # stops stale callers from enumerating via a one-sided key.
        return ""
    candidates: set[str] = set()
    try:
        candidates.update(gate_store.known_gate_ids())
    except Exception:
        pass
    try:
        from services.mesh.mesh_reputation import gate_manager

        for gate in gate_manager.list_gates():
            gate_id = str((gate or {}).get("gate_id", "") or "").strip().lower()
            if gate_id:
                candidates.add(gate_id)
    except Exception:
        pass
    for gate_id in sorted(candidates):
        candidate_ref = build_gate_wire_ref(
            gate_id,
            event,
            peer_url=peer_url,
        )
        if candidate_ref and hmac.compare_digest(candidate_ref, ref):
            return gate_id
    return ""


def _private_gate_signature_payload(
    gate_id: str,
    event: dict[str, Any],
    *,
    include_reply_to: bool = True,
) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    normalized = {
        "gate": str(gate_id or "").strip().lower(),
        "ciphertext": str(payload.get("ciphertext", "") or ""),
        "nonce": str(payload.get("nonce", "") or ""),
        "sender_ref": str(payload.get("sender_ref", "") or ""),
        "format": str(payload.get("format", "mls1") or "mls1"),
    }
    epoch = _safe_int(payload.get("epoch", 0) or 0, 0)
    if epoch > 0:
        normalized["epoch"] = epoch
    envelope_hash = str(payload.get("envelope_hash", "") or "").strip()
    if envelope_hash:
        normalized["envelope_hash"] = envelope_hash
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        normalized["transport_lock"] = transport_lock
    reply_to = str(payload.get("reply_to", "") or "").strip()
    if include_reply_to and reply_to:
        normalized["reply_to"] = reply_to
    return normalize_payload("gate_message", normalized)


def _private_gate_event_id(
    gate_id: str,
    node_id: str,
    sequence: int,
    event: dict[str, Any],
    *,
    include_reply_to: bool = True,
) -> str:
    payload_json = json.dumps(
        _private_gate_signature_payload(gate_id, event, include_reply_to=include_reply_to),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    timestamp = float(event.get("timestamp", 0) or 0)
    return hashlib.sha256(
        f"{gate_id}:{node_id}:{payload_json}:{timestamp}:{int(sequence)}".encode("utf-8")
    ).hexdigest()


def _sanitize_private_gate_event(gate_id: str, event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    sanitized = {
        "event_id": str(event.get("event_id", "") or ""),
        "event_type": "gate_message",
        "node_id": str(event.get("node_id", "") or ""),
        "timestamp": float(event.get("timestamp", 0) or 0),
        "sequence": int(event.get("sequence", 0) or 0),
        "signature": str(event.get("signature", "") or ""),
        "public_key": str(event.get("public_key", "") or ""),
        "public_key_algo": str(event.get("public_key_algo", "") or ""),
        "protocol_version": str(event.get("protocol_version", "") or ""),
        "payload": {
            "gate": str(gate_id or "").strip().lower(),
            "ciphertext": str(payload.get("ciphertext", "") or ""),
            "nonce": str(payload.get("nonce", "") or ""),
            "sender_ref": str(payload.get("sender_ref", "") or ""),
            "format": str(payload.get("format", "mls1") or "mls1"),
        },
    }
    epoch = _safe_int(payload.get("epoch", 0) or 0, 0)
    if epoch > 0:
        sanitized["payload"]["epoch"] = epoch
    envelope_hash = str(payload.get("envelope_hash", "") or "").strip()
    if envelope_hash:
        sanitized["payload"]["envelope_hash"] = envelope_hash
    gate_envelope = str(payload.get("gate_envelope", "") or "").strip()
    if gate_envelope:
        sanitized["payload"]["gate_envelope"] = gate_envelope
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        sanitized["payload"]["transport_lock"] = transport_lock
    reply_to = str(payload.get("reply_to", "") or "").strip()
    if reply_to:
        sanitized["payload"]["reply_to"] = reply_to
    # Local-only decrypted plaintext — persisted on the private chain so
    # leave/rejoin and restarts never lose readable messages. These fields are
    # stamped post-decrypt and never leave the node.
    local_pt = payload.get("_local_plaintext")
    if isinstance(local_pt, str) and local_pt:
        sanitized["payload"]["_local_plaintext"] = local_pt
    local_rt = payload.get("_local_reply_to")
    if isinstance(local_rt, str) and local_rt:
        sanitized["payload"]["_local_reply_to"] = local_rt
    return sanitized


def _authorize_private_gate_transport_author(
    gate_id: str,
    node_id: str,
    public_key: str,
    public_key_algo: str,
) -> tuple[bool, str]:
    gate_key = str(gate_id or "").strip().lower()
    candidate = str(node_id or "").strip()
    if not gate_key or not candidate:
        return False, "private gate authorization unavailable"
    try:
        from services.mesh.mesh_reputation import gate_manager, reputation_ledger
    except Exception:
        return False, "private gate authorization unavailable"
    try:
        reputation_ledger.register_node(candidate, public_key, public_key_algo)
    except Exception:
        return False, "private gate authorization unavailable"
    ok, reason = gate_manager.can_enter(candidate, gate_key)
    if ok:
        return True, "ok"
    return False, str(reason or "Gate access denied")


def _verify_private_gate_transport_event(gate_id: str, event: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None]:
    node_id = str(event.get("node_id", "") or event.get("sender_id", "") or "").strip()
    public_key = str(event.get("public_key", "") or "").strip()
    public_key_algo = str(event.get("public_key_algo", "") or "").strip()
    signature = str(event.get("signature", "") or "").strip()
    protocol_version = str(event.get("protocol_version", "") or "").strip()
    sequence = _safe_int(event.get("sequence", 0) or 0, 0)
    if not node_id or not public_key or not public_key_algo or not signature:
        return False, "missing private gate auth fields", None
    if sequence <= 0:
        return False, "invalid private gate sequence", None
    if protocol_version != PROTOCOL_VERSION:
        return False, "Unsupported protocol_version", None
    payload = _private_gate_signature_payload(gate_id, event)
    ok, reason = validate_event_payload("gate_message", payload)
    if not ok:
        return False, reason, None
    if not verify_node_binding(node_id, public_key):
        return False, "node_id mismatch", None
    algo = parse_public_key_algo(public_key_algo)
    if not algo:
        return False, "Unsupported public_key_algo", None
    reply_to = str(((event.get("payload") or {}) if isinstance(event.get("payload"), dict) else {}).get("reply_to", "") or "").strip()
    legacy_unsigned_reply_to = False
    legacy_unsigned_epoch = False
    variants: list[tuple[dict[str, Any], bool, bool]] = [(payload, False, False)]
    if reply_to:
        variants.append((_private_gate_signature_payload(gate_id, event, include_reply_to=False), True, False))
    if "epoch" in payload:
        no_epoch = dict(payload)
        no_epoch.pop("epoch", None)
        variants.append((no_epoch, False, True))
        if reply_to:
            no_epoch_no_reply = _private_gate_signature_payload(gate_id, event, include_reply_to=False)
            no_epoch_no_reply.pop("epoch", None)
            variants.append((no_epoch_no_reply, True, True))
    sig_ok = False
    for candidate_payload, candidate_unsigned_reply, candidate_unsigned_epoch in variants:
        candidate_sig_payload = build_signature_payload(
            event_type="gate_message",
            node_id=node_id,
            sequence=sequence,
            payload=candidate_payload,
        )
        if verify_signature(
            public_key_b64=public_key,
            public_key_algo=algo,
            signature_hex=signature,
            payload=candidate_sig_payload,
        ):
            sig_ok = True
            legacy_unsigned_reply_to = candidate_unsigned_reply
            legacy_unsigned_epoch = candidate_unsigned_epoch
            break
    if not sig_ok:
        return False, "Invalid signature", None
    envelope_hash = str(((event.get("payload") or {}) if isinstance(event.get("payload"), dict) else {}).get("envelope_hash", "") or "").strip()
    gate_envelope = str(((event.get("payload") or {}) if isinstance(event.get("payload"), dict) else {}).get("gate_envelope", "") or "").strip()
    if envelope_hash:
        if not gate_envelope:
            return False, "gate_envelope required when envelope_hash is present", None
        if hashlib.sha256(gate_envelope.encode("ascii")).hexdigest() != envelope_hash:
            return False, "gate_envelope does not match envelope_hash", None
    authorized, reason = _authorize_private_gate_transport_author(gate_id, node_id, public_key, public_key_algo)
    if not authorized:
        return False, f"private gate access denied: {reason}", None
    event_for_id = event
    if legacy_unsigned_epoch:
        event_for_id = dict(event)
        event_payload_for_id = dict((event.get("payload") or {}) if isinstance(event.get("payload"), dict) else {})
        event_payload_for_id.pop("epoch", None)
        event_for_id["payload"] = event_payload_for_id
    expected_event_id = _private_gate_event_id(
        gate_id,
        node_id,
        sequence,
        event_for_id,
        include_reply_to=not legacy_unsigned_reply_to,
    )
    provided_event_id = str(event.get("event_id", "") or "").strip()
    if provided_event_id and provided_event_id != expected_event_id:
        return False, "private gate event_id mismatch", None
    sanitized = _sanitize_private_gate_event(gate_id, event)
    if legacy_unsigned_reply_to:
        sanitized["payload"].pop("reply_to", None)
    if legacy_unsigned_epoch:
        sanitized["payload"].pop("epoch", None)
    sanitized["event_id"] = provided_event_id or expected_event_id
    return True, "ok", sanitized


class GateMessageStore:
    """Private-plane storage for encrypted gate messages."""

    def __init__(self, data_dir: str = ""):
        self._gates: dict[str, list[dict]] = {}
        self._event_index: dict[str, dict] = {}
        self._replay_index: dict[str, dict[str, Any]] = {}
        self._replay_prune_counter = 0
        self._data_dir = Path(data_dir) if data_dir else GATE_STORE_DIR
        self._lock = threading.Lock()
        self._change_condition = threading.Condition(self._lock)
        self._load()

    def _gate_digest(self, gate_id: str) -> str:
        return hashlib.sha256(str(gate_id or "").encode("utf-8")).hexdigest()

    def _gate_file_path(self, gate_id: str) -> Path:
        return self._data_dir / f"gate_{self._gate_digest(gate_id)}.jsonl"

    def _gate_legacy_domain_filename(self, gate_id: str) -> str:
        return f"gate_{self._gate_digest(gate_id)}.jsonl"

    def _gate_manifest_filename_for_digest(self, digest: str) -> str:
        return f"gate_{digest}.manifest.json"

    def _gate_manifest_filename(self, gate_id: str) -> str:
        return self._gate_manifest_filename_for_digest(self._gate_digest(gate_id))

    def _gate_segment_filename_for_digest(self, digest: str, segment_no: int) -> str:
        return f"gate_{digest}_seg_{max(0, int(segment_no)):08d}.gseg"

    def _gate_segment_filename(self, gate_id: str, segment_no: int) -> str:
        return self._gate_segment_filename_for_digest(self._gate_digest(gate_id), segment_no)

    def _gate_storage_base_dir(self) -> Path:
        return self._data_dir.parent

    def _gate_domain_dir(self) -> Path:
        return self._gate_storage_base_dir() / GATE_STORAGE_DOMAIN

    def _sort_gate(self, gate_id: str) -> None:
        events = self._gates.get(gate_id, [])
        events.sort(
            key=lambda evt: (
                float(evt.get("timestamp", 0) or 0),
                _safe_int(evt.get("sequence", 0) or 0, 0),
                str(evt.get("event_id", "") or ""),
            )
        )

    def _remember_replay_fingerprint(self, replay_fingerprint: str, event: dict) -> None:
        self._replay_index[replay_fingerprint] = {
            "event": event,
            "timestamp": float(event.get("timestamp", 0) or 0.0),
        }

    def _replay_existing_event(self, replay_fingerprint: str) -> dict | None:
        entry = self._replay_index.get(replay_fingerprint) or {}
        event = entry.get("event")
        return event if isinstance(event, dict) else None

    def _prune_replay_index(self, now: float | None = None) -> int:
        current = float(now if now is not None else time.time())
        cutoff = current - GATE_REPLAY_WINDOW_S
        stale = [
            fingerprint
            for fingerprint, entry in list(self._replay_index.items())
            if float((entry or {}).get("timestamp", 0) or 0.0) < cutoff
        ]
        for fingerprint in stale:
            self._replay_index.pop(fingerprint, None)
        return len(stale)

    def _maybe_prune_replay_index(self) -> None:
        self._replay_prune_counter += 1
        if self._replay_prune_counter % GATE_REPLAY_PRUNE_INTERVAL == 0:
            self._prune_replay_index()

    def _stable_bytes(self, payload: Any) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def _segment_material_hash(self, payload: dict[str, Any]) -> str:
        material = dict(payload)
        material.pop("segment_hash", None)
        return hashlib.sha256(self._stable_bytes(material)).hexdigest()

    def _encode_segment_events(self, events: list[dict]) -> str:
        raw = self._stable_bytes(events)
        return base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")

    def _decode_segment_events(self, segment_payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(segment_payload, dict):
            return []
        if str(segment_payload.get("codec", "") or "") != "zlib":
            return []
        encoded = str(segment_payload.get("events_b64", "") or "")
        if not encoded:
            return []
        try:
            raw = zlib.decompress(base64.b64decode(encoded.encode("ascii")))
            decoded = json.loads(raw.decode("utf-8"))
        except Exception:
            return []
        return [evt for evt in decoded if isinstance(evt, dict)] if isinstance(decoded, list) else []

    def _build_segment_payload(
        self,
        *,
        gate_digest: str,
        segment_no: int,
        events: list[dict],
        prev_segment_hash: str = "",
    ) -> dict[str, Any]:
        encoded_events = self._encode_segment_events(events)
        first_event_id = str((events[0] or {}).get("event_id", "") or "") if events else ""
        last_event_id = str((events[-1] or {}).get("event_id", "") or "") if events else ""
        payload = {
            "version": GATE_SEGMENT_STORAGE_VERSION,
            "storage": "gate-segment-v1",
            "gate_digest": str(gate_digest or ""),
            "segment_no": int(segment_no),
            "prev_segment_hash": str(prev_segment_hash or ""),
            "count": len(events),
            "first_event_id": first_event_id,
            "last_event_id": last_event_id,
            "codec": "zlib",
            "encoding": "json",
            "events_b64": encoded_events,
        }
        payload["segment_hash"] = self._segment_material_hash(payload)
        return payload

    def _segment_meta_from_payload(self, payload: dict[str, Any], filename: str) -> dict[str, Any]:
        return {
            "segment_no": int(payload.get("segment_no", 0) or 0),
            "filename": str(filename or ""),
            "count": int(payload.get("count", 0) or 0),
            "first_event_id": str(payload.get("first_event_id", "") or ""),
            "last_event_id": str(payload.get("last_event_id", "") or ""),
            "prev_segment_hash": str(payload.get("prev_segment_hash", "") or ""),
            "segment_hash": str(payload.get("segment_hash", "") or ""),
        }

    def _read_gate_manifest(self, gate_id: str) -> dict[str, Any] | None:
        try:
            manifest = read_domain_json(
                GATE_STORAGE_DOMAIN,
                self._gate_manifest_filename(gate_id),
                lambda: {},
                base_dir=self._gate_storage_base_dir(),
            )
        except Exception:
            return None
        if not isinstance(manifest, dict):
            return None
        if str(manifest.get("storage", "") or "") != "gate-segments-v1":
            return None
        return manifest

    def _read_segment_file(self, filename: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        payload = read_domain_json(
            GATE_STORAGE_DOMAIN,
            filename,
            lambda: {},
            base_dir=self._gate_storage_base_dir(),
        )
        if not isinstance(payload, dict):
            return {}, []
        expected_hash = str(payload.get("segment_hash", "") or "")
        if expected_hash and expected_hash != self._segment_material_hash(payload):
            logger.warning("Gate segment hash mismatch for %s", filename)
            return {}, []
        return payload, self._decode_segment_events(payload)

    def _load_segmented_gates(self) -> set[str]:
        encrypted_dir = self._gate_domain_dir()
        loaded_digests: set[str] = set()
        if not encrypted_dir.exists():
            return loaded_digests
        for manifest_path in sorted(encrypted_dir.glob("gate_*.manifest.json")):
            try:
                manifest = read_domain_json(
                    GATE_STORAGE_DOMAIN,
                    manifest_path.name,
                    lambda: {},
                    base_dir=self._gate_storage_base_dir(),
                )
            except Exception:
                continue
            if not isinstance(manifest, dict) or str(manifest.get("storage", "") or "") != "gate-segments-v1":
                continue
            gate_digest = str(manifest.get("gate_digest", "") or "")
            if gate_digest:
                loaded_digests.add(gate_digest)
            segments = manifest.get("segments", [])
            if not isinstance(segments, list):
                continue
            for segment_meta in sorted(
                [item for item in segments if isinstance(item, dict)],
                key=lambda item: int(item.get("segment_no", 0) or 0),
            ):
                filename = str(segment_meta.get("filename", "") or "")
                if not filename:
                    continue
                _payload, events = self._read_segment_file(filename)
                for evt in events:
                    payload = evt.get("payload") or {}
                    if not isinstance(payload, dict):
                        continue
                    gate_id = str(payload.get("gate", "") or "").strip().lower()
                    if not gate_id:
                        continue
                    storage_event = _sanitize_private_gate_event(gate_id, evt)
                    if not str(storage_event.get("event_id", "") or "").strip():
                        storage_event["event_id"] = self._synth_event_id(gate_id, storage_event)
                    replay_fingerprint = build_gate_replay_fingerprint(gate_id, storage_event)
                    if replay_fingerprint in self._replay_index:
                        continue
                    event_id = str(storage_event.get("event_id", "") or "")
                    if event_id and event_id in self._event_index:
                        continue
                    self._gates.setdefault(gate_id, []).append(storage_event)
                    if event_id:
                        self._event_index[event_id] = storage_event
                    self._remember_replay_fingerprint(replay_fingerprint, storage_event)
        return loaded_digests

    def _load(self) -> None:
        encrypted_dir = self._gate_domain_dir()
        if not self._data_dir.exists() and not encrypted_dir.exists():
            return
        segmented_digests = self._load_segmented_gates()
        dirty_gates: set[str] = set()
        file_names = {
            path.name for path in self._data_dir.glob("gate_*.jsonl")
        } | {
            path.name for path in encrypted_dir.glob("gate_*.jsonl")
        }
        for file_name in sorted(file_names):
            digest = file_name.removeprefix("gate_").removesuffix(".jsonl")
            if digest in segmented_digests:
                continue
            events: list[dict[str, Any]] | None = None
            encrypted_path = encrypted_dir / file_name
            loaded_from_legacy_domain_list = False
            if encrypted_path.exists():
                try:
                    loaded = read_domain_json(
                        GATE_STORAGE_DOMAIN,
                        file_name,
                        lambda: [],
                        base_dir=self._gate_storage_base_dir(),
                    )
                    if isinstance(loaded, list):
                        events = [evt for evt in loaded if isinstance(evt, dict)]
                        loaded_from_legacy_domain_list = True
                except Exception:
                    events = None
            if events is None:
                legacy_path = self._data_dir / file_name
                if not legacy_path.exists():
                    continue
                try:
                    lines = legacy_path.read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue
                events = []
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(evt, dict):
                        events.append(evt)
            loaded_gate_ids: set[str] = set()
            for evt in events:
                payload = evt.get("payload") or {}
                if not isinstance(payload, dict):
                    continue
                gate_id = str(payload.get("gate", "") or "").strip().lower()
                if not gate_id:
                    continue
                storage_event = _sanitize_private_gate_event(gate_id, evt)
                if storage_event != evt:
                    dirty_gates.add(gate_id)
                evt = storage_event
                if not str(evt.get("event_id", "") or "").strip():
                    evt["event_id"] = self._synth_event_id(gate_id, evt)
                    dirty_gates.add(gate_id)
                loaded_gate_ids.add(gate_id)
                replay_fingerprint = build_gate_replay_fingerprint(gate_id, evt)
                if replay_fingerprint in self._replay_index:
                    dirty_gates.add(gate_id)
                    continue
                event_id = str(evt.get("event_id", "") or "")
                if event_id and event_id in self._event_index:
                    dirty_gates.add(gate_id)
                    continue
                self._gates.setdefault(gate_id, []).append(evt)
                if event_id:
                    self._event_index[event_id] = evt
                self._remember_replay_fingerprint(replay_fingerprint, evt)
            if loaded_from_legacy_domain_list or not encrypted_path.exists():
                dirty_gates.update(loaded_gate_ids)
        self._prune_replay_index()
        for gate_id in list(self._gates.keys()):
            self._sort_gate(gate_id)
        for gate_id in sorted(dirty_gates):
            self._persist_gate(gate_id)

    def _persist_gate(self, gate_id: str, events: list[dict] | None = None) -> None:
        if events is None:
            events = self._gates.get(gate_id, [])
        gate_key = str(gate_id or "").strip().lower()
        if not gate_key:
            return
        gate_digest = self._gate_digest(gate_key)
        old_manifest = self._read_gate_manifest(gate_key)
        old_segment_files = {
            str(item.get("filename", "") or "")
            for item in list((old_manifest or {}).get("segments", []) or [])
            if isinstance(item, dict)
        }
        clean_events = [_sanitize_private_gate_event(gate_key, evt) for evt in list(events or []) if isinstance(evt, dict)]
        segments: list[dict[str, Any]] = []
        prev_hash = ""
        written_segment_files: set[str] = set()
        for segment_no, start in enumerate(range(0, len(clean_events), GATE_SEGMENT_EVENT_TARGET)):
            chunk = clean_events[start : start + GATE_SEGMENT_EVENT_TARGET]
            filename = self._gate_segment_filename_for_digest(gate_digest, segment_no)
            segment_payload = self._build_segment_payload(
                gate_digest=gate_digest,
                segment_no=segment_no,
                events=chunk,
                prev_segment_hash=prev_hash,
            )
            write_domain_json(
                GATE_STORAGE_DOMAIN,
                filename,
                segment_payload,
                base_dir=self._gate_storage_base_dir(),
            )
            written_segment_files.add(filename)
            segments.append(self._segment_meta_from_payload(segment_payload, filename))
            prev_hash = str(segment_payload.get("segment_hash", "") or "")
        manifest = {
            "version": GATE_SEGMENT_STORAGE_VERSION,
            "storage": "gate-segments-v1",
            "gate_digest": gate_digest,
            "segment_event_target": GATE_SEGMENT_EVENT_TARGET,
            "segment_max_compressed_bytes": GATE_SEGMENT_MAX_COMPRESSED_BYTES,
            "total_events": len(clean_events),
            "segment_count": len(segments),
            "head_segment_hash": prev_hash,
            "segments": segments,
            "updated_at": int(time.time()),
        }
        write_domain_json(
            GATE_STORAGE_DOMAIN,
            self._gate_manifest_filename_for_digest(gate_digest),
            manifest,
            base_dir=self._gate_storage_base_dir(),
        )
        for stale_filename in old_segment_files - written_segment_files:
            if stale_filename:
                (self._gate_domain_dir() / stale_filename).unlink(missing_ok=True)
        legacy_domain_path = self._gate_domain_dir() / self._gate_legacy_domain_filename(gate_key)
        legacy_domain_path.unlink(missing_ok=True)
        self._gate_file_path(gate_id).unlink(missing_ok=True)

    def _persist_gate_new_events(self, gate_id: str, new_events: list[dict]) -> None:
        gate_key = str(gate_id or "").strip().lower()
        clean_new_events = [
            _sanitize_private_gate_event(gate_key, evt)
            for evt in list(new_events or [])
            if isinstance(evt, dict)
        ]
        if not gate_key or not clean_new_events:
            return
        manifest = self._read_gate_manifest(gate_key)
        if not manifest:
            self._persist_gate(gate_key, list(self._gates.get(gate_key, [])) + clean_new_events)
            return

        gate_digest = self._gate_digest(gate_key)
        segments = [
            dict(item)
            for item in list(manifest.get("segments", []) or [])
            if isinstance(item, dict)
        ]
        remaining = list(clean_new_events)
        if not segments:
            segment_no = 0
            events_for_segment: list[dict] = []
            filename = self._gate_segment_filename_for_digest(gate_digest, segment_no)
            prev_for_segment = ""
        else:
            last_meta = dict(segments[-1])
            segment_no = int(last_meta.get("segment_no", len(segments) - 1) or 0)
            filename = str(last_meta.get("filename", "") or self._gate_segment_filename_for_digest(gate_digest, segment_no))
            segment_payload, events_for_segment = self._read_segment_file(filename)
            prev_for_segment = str(segment_payload.get("prev_segment_hash", "") or last_meta.get("prev_segment_hash", "") or "")
            if not events_for_segment:
                self._persist_gate(gate_key, list(self._gates.get(gate_key, [])) + clean_new_events)
                return
        while remaining:
            candidate = events_for_segment + [remaining[0]]
            candidate_payload = self._build_segment_payload(
                gate_digest=gate_digest,
                segment_no=segment_no,
                events=candidate,
                prev_segment_hash=prev_for_segment,
            )
            compressed_len = len(str(candidate_payload.get("events_b64", "") or ""))
            if (
                events_for_segment
                and (
                    len(candidate) > GATE_SEGMENT_EVENT_TARGET
                    or compressed_len > GATE_SEGMENT_MAX_COMPRESSED_BYTES
                )
            ):
                segment_payload = self._build_segment_payload(
                    gate_digest=gate_digest,
                    segment_no=segment_no,
                    events=events_for_segment,
                    prev_segment_hash=prev_for_segment,
                )
                existing_meta_matches = (
                    bool(segments)
                    and _safe_int(segments[-1].get("segment_no", -1), -1) == segment_no
                    and str(segments[-1].get("segment_hash", "") or "") == str(segment_payload.get("segment_hash", "") or "")
                )
                if existing_meta_matches:
                    meta = segments[-1]
                else:
                    write_domain_json(
                        GATE_STORAGE_DOMAIN,
                        filename,
                        segment_payload,
                        base_dir=self._gate_storage_base_dir(),
                    )
                    meta = self._segment_meta_from_payload(segment_payload, filename)
                    if segments and _safe_int(segments[-1].get("segment_no", -1), -1) == segment_no:
                        segments[-1] = meta
                    else:
                        segments.append(meta)
                prev_for_segment = str(meta.get("segment_hash", "") or segment_payload.get("segment_hash", "") or "")
                segment_no += 1
                filename = self._gate_segment_filename_for_digest(gate_digest, segment_no)
                events_for_segment = []
                continue
            events_for_segment = candidate
            remaining.pop(0)

        segment_payload = self._build_segment_payload(
            gate_digest=gate_digest,
            segment_no=segment_no,
            events=events_for_segment,
            prev_segment_hash=prev_for_segment,
        )
        write_domain_json(
            GATE_STORAGE_DOMAIN,
            filename,
            segment_payload,
            base_dir=self._gate_storage_base_dir(),
        )
        meta = self._segment_meta_from_payload(segment_payload, filename)
        if segments and _safe_int(segments[-1].get("segment_no", -1), -1) == segment_no:
            segments[-1] = meta
        else:
            segments.append(meta)
        manifest = {
            "version": GATE_SEGMENT_STORAGE_VERSION,
            "storage": "gate-segments-v1",
            "gate_digest": gate_digest,
            "segment_event_target": GATE_SEGMENT_EVENT_TARGET,
            "segment_max_compressed_bytes": GATE_SEGMENT_MAX_COMPRESSED_BYTES,
            "total_events": int(manifest.get("total_events", 0) or 0) + len(clean_new_events),
            "segment_count": len(segments),
            "head_segment_hash": str(segment_payload.get("segment_hash", "") or ""),
            "segments": segments,
            "updated_at": int(time.time()),
        }
        write_domain_json(
            GATE_STORAGE_DOMAIN,
            self._gate_manifest_filename(gate_key),
            manifest,
            base_dir=self._gate_storage_base_dir(),
        )
        legacy_domain_path = self._gate_domain_dir() / self._gate_legacy_domain_filename(gate_key)
        legacy_domain_path.unlink(missing_ok=True)
        self._gate_file_path(gate_key).unlink(missing_ok=True)

    def _synth_event_id(self, gate_id: str, event: dict) -> str:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        material = {
            "gate": str(gate_id or "").strip().lower(),
            "event_type": str(event.get("event_type", "") or ""),
            "timestamp": float(event.get("timestamp", 0) or 0),
            "ciphertext": str(payload.get("ciphertext", "") or ""),
            "format": str(payload.get("format", "") or ""),
        }
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def append(self, gate_id: str, event: dict) -> dict:
        gate_id = str(gate_id or "").strip().lower()
        if not gate_id:
            return event
        clean_event = _sanitize_private_gate_event(gate_id, event)
        if not str(clean_event.get("event_id", "") or "").strip():
            clean_event["event_id"] = self._synth_event_id(gate_id, clean_event)
        with self._lock:
            self._gates.setdefault(gate_id, [])
            replay_fingerprint = build_gate_replay_fingerprint(gate_id, clean_event)
            existing = self._replay_existing_event(replay_fingerprint)
            if existing is not None:
                return existing
            event_id = str(clean_event.get("event_id", "") or "")
            if event_id and event_id in self._event_index:
                return self._event_index[event_id]
            # Stage: build new gate list without mutating in-memory state yet
            staged = list(self._gates[gate_id]) + [clean_event]
            staged.sort(
                key=lambda evt: (
                    float(evt.get("timestamp", 0) or 0),
                    _safe_int(evt.get("sequence", 0) or 0, 0),
                    str(evt.get("event_id", "") or ""),
                )
            )
            # Persist first — raises on failure, no in-memory mutation yet
            self._persist_gate_new_events(gate_id, [clean_event])
            # Commit in-memory state only after durable persistence
            self._gates[gate_id] = staged
            if event_id:
                self._event_index[event_id] = clean_event
            self._remember_replay_fingerprint(replay_fingerprint, clean_event)
            self._maybe_prune_replay_index()
            self._change_condition.notify_all()
            return clean_event

    def get_messages(self, gate_id: str, limit: int = 20, offset: int = 0) -> list[dict]:
        messages, _cursor = self.get_messages_with_cursor(gate_id, limit=limit, offset=offset)
        return messages

    def get_messages_with_cursor(self, gate_id: str, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
        gate_id = str(gate_id or "").strip().lower()
        with self._lock:
            msgs = self._gates.get(gate_id, [])
            cursor = len(msgs)
            return list(reversed(msgs))[offset : offset + limit], cursor

    def gate_cursor(self, gate_id: str) -> int:
        gate_id = str(gate_id or "").strip().lower()
        with self._lock:
            return len(self._gates.get(gate_id, []))

    def wait_for_gate_change(
        self,
        gate_id: str,
        after_cursor: int = 0,
        timeout_s: float = 20.0,
    ) -> tuple[bool, int]:
        gate_key = str(gate_id or "").strip().lower()
        if not gate_key:
            return False, 0
        target_cursor = max(0, _safe_int(after_cursor, 0))
        deadline = time.monotonic() + max(0.0, float(timeout_s or 0.0))
        with self._lock:
            current_cursor = len(self._gates.get(gate_key, []))
            if current_cursor > target_cursor:
                return True, current_cursor
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False, len(self._gates.get(gate_key, []))
                self._change_condition.wait(timeout=remaining)
                current_cursor = len(self._gates.get(gate_key, []))
                if current_cursor > target_cursor:
                    return True, current_cursor

    def wait_for_any_gate_change(
        self,
        gate_cursors: dict[str, int],
        timeout_s: float = 20.0,
    ) -> dict[str, int]:
        normalized = {
            str(gate_id or "").strip().lower(): max(0, _safe_int(cursor, 0))
            for gate_id, cursor in dict(gate_cursors or {}).items()
            if str(gate_id or "").strip()
        }
        if not normalized:
            return {}
        deadline = time.monotonic() + max(0.0, float(timeout_s or 0.0))

        def _changed() -> dict[str, int]:
            updates: dict[str, int] = {}
            for gate_id, after_cursor in normalized.items():
                current_cursor = len(self._gates.get(gate_id, []))
                if current_cursor > after_cursor:
                    updates[gate_id] = current_cursor
            return updates

        with self._lock:
            updates = _changed()
            if updates:
                return updates
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {}
                self._change_condition.wait(timeout=remaining)
                updates = _changed()
                if updates:
                    return updates

    def known_gate_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._gates.keys())

    def get_event(self, event_id: str) -> dict | None:
        with self._lock:
            return self._event_index.get(str(event_id or ""))

    def stamp_local_plaintext(
        self,
        gate_id: str,
        event_id: str,
        plaintext: str,
        reply_to: str = "",
    ) -> bool:
        """Stamp decrypted plaintext onto a stored event and re-persist.

        This is the durable path for the leave/rejoin invariant: once a message
        is decrypted (by any path — MLS, envelope, self-echo), the plaintext is
        written into the private chain so it survives restarts and MLS epoch
        resets.  The ``_local_plaintext`` / ``_local_reply_to`` fields are
        local-only and never transmitted to peers.
        """
        gate_id = str(gate_id or "").strip().lower()
        event_id = str(event_id or "").strip()
        if not gate_id or not event_id or not plaintext:
            return False
        with self._lock:
            evt = self._event_index.get(event_id)
            if evt is None:
                return False
            payload = evt.get("payload")
            if not isinstance(payload, dict):
                return False
            if payload.get("_local_plaintext"):
                return True  # already stamped
            payload["_local_plaintext"] = plaintext
            if reply_to:
                payload["_local_reply_to"] = reply_to
            self._persist_gate(gate_id)
            return True

    def lookup_local_plaintext(
        self,
        gate_id: str,
        event_id: str,
    ) -> tuple[str, str] | None:
        """Return stamped plaintext for an event, or None."""
        event_id = str(event_id or "").strip()
        if not event_id:
            return None
        with self._lock:
            evt = self._event_index.get(event_id)
            if evt is None:
                return None
            payload = evt.get("payload")
            if not isinstance(payload, dict):
                return None
            pt = payload.get("_local_plaintext")
            if not isinstance(pt, str) or not pt:
                return None
            return pt, str(payload.get("_local_reply_to", "") or "")

    def ingest_peer_events(self, gate_id: str, events: list[dict]) -> dict:
        gate_id = str(gate_id or "").strip().lower()
        duplicates = 0
        rejected = 0
        if not gate_id:
            return {"accepted": 0, "duplicates": 0, "rejected": 0}
        with self._lock:
            self._gates.setdefault(gate_id, [])
            # Collect validated candidates without mutating in-memory state
            candidates: list[tuple[dict, str, str]] = []  # (clean_event, event_id, fingerprint)
            batch_fingerprints: set[str] = set()
            batch_event_ids: set[str] = set()
            for evt in events:
                if not isinstance(evt, dict):
                    rejected += 1
                    continue
                event_id = str(evt.get("event_id", "") or "")
                payload = evt.get("payload")
                if not isinstance(payload, dict):
                    rejected += 1
                    continue
                if not payload.get("ciphertext"):
                    rejected += 1
                    continue
                if evt.get("event_type") != "gate_message":
                    rejected += 1
                    continue
                ts = evt.get("timestamp", 0)
                now = time.time()
                if not isinstance(ts, (int, float)) or ts > now + 300 or ts < now - 86400 * 30:
                    rejected += 1
                    continue
                replay_fingerprint = build_gate_replay_fingerprint(gate_id, evt)
                if replay_fingerprint in self._replay_index or replay_fingerprint in batch_fingerprints:
                    duplicates += 1
                    continue
                if event_id:
                    if len(event_id) != 64:
                        rejected += 1
                        continue
                    try:
                        int(event_id, 16)
                    except ValueError:
                        rejected += 1
                        continue
                else:
                    event_id = ""
                if event_id and (event_id in self._event_index or event_id in batch_event_ids):
                    duplicates += 1
                    continue
                ok, reason, clean_event = _verify_private_gate_transport_event(gate_id, evt)
                if not ok or clean_event is None:
                    logger.warning("Rejected private gate peer event: %s", reason)
                    rejected += 1
                    continue
                event_id = str(clean_event.get("event_id", "") or "")
                if event_id in self._event_index or event_id in batch_event_ids:
                    duplicates += 1
                    continue
                candidates.append((clean_event, event_id, replay_fingerprint))
                batch_fingerprints.add(replay_fingerprint)
                if event_id:
                    batch_event_ids.add(event_id)
            if not candidates:
                return {"accepted": 0, "duplicates": duplicates, "rejected": rejected}
            # Stage: build new gate list without mutating in-memory state
            staged = list(self._gates[gate_id])
            for clean_event, _, _ in candidates:
                staged.append(clean_event)
            staged.sort(
                key=lambda evt: (
                    float(evt.get("timestamp", 0) or 0),
                    _safe_int(evt.get("sequence", 0) or 0, 0),
                    str(evt.get("event_id", "") or ""),
                )
            )
            # Persist first — raises on failure, no in-memory mutation yet
            self._persist_gate_new_events(gate_id, [clean_event for clean_event, _, _ in candidates])
            # Commit in-memory state only after durable persistence
            self._gates[gate_id] = staged
            for clean_event, event_id, replay_fingerprint in candidates:
                if event_id:
                    self._event_index[event_id] = clean_event
                self._remember_replay_fingerprint(replay_fingerprint, clean_event)
            self._maybe_prune_replay_index()
        return {"accepted": len(candidates), "duplicates": duplicates, "rejected": rejected}


class ReplayFilter:
    """Bounded bloom-style replay filter with rotation."""

    def __init__(
        self,
        *,
        size_bits: int = REPLAY_FILTER_BITS,
        hash_count: int = REPLAY_FILTER_HASHES,
        rotate_s: int = REPLAY_FILTER_ROTATE_S,
    ) -> None:
        self._size_bits = max(1024, int(size_bits))
        self._hash_count = max(2, int(hash_count))
        self._rotate_s = max(60, int(rotate_s))
        self._salt = os.urandom(16)
        self._active = bytearray(self._size_bits // 8 + 1)
        self._previous = bytearray(self._size_bits // 8 + 1)
        self._last_rotate = time.time()

    def _rotate_if_needed(self) -> None:
        now = time.time()
        if now - self._last_rotate < self._rotate_s:
            return
        self._previous = self._active
        self._active = bytearray(self._size_bits // 8 + 1)
        self._last_rotate = now

    def _positions(self, value: str) -> list[int]:
        positions: list[int] = []
        data = value.encode("utf-8")
        for idx in range(self._hash_count):
            digest = hashlib.sha256(self._salt + idx.to_bytes(2, "big") + data).digest()
            pos = int.from_bytes(digest[:8], "big") % self._size_bits
            positions.append(pos)
        return positions

    def add(self, value: str) -> None:
        self._rotate_if_needed()
        for pos in self._positions(value):
            byte_idx = pos // 8
            bit = 1 << (pos % 8)
            self._active[byte_idx] |= bit

    def seen(self, value: str) -> bool:
        self._rotate_if_needed()
        for pos in self._positions(value):
            byte_idx = pos // 8
            bit = 1 << (pos % 8)
            if not (self._active[byte_idx] & bit or self._previous[byte_idx] & bit):
                return False
        return True


class ChainEvent:
    """Single event on the Infonet."""

    __slots__ = (
        "event_id",
        "prev_hash",
        "event_type",
        "node_id",
        "payload",
        "timestamp",
        "sequence",
        "signature",
        "network_id",
        "public_key",
        "public_key_algo",
        "protocol_version",
    )

    def __init__(
        self,
        prev_hash: str,
        event_type: str,
        node_id: str,
        payload: dict,
        timestamp: float = 0,
        sequence: int = 0,
        signature: str = "",
        network_id: str = "",
        public_key: str = "",
        public_key_algo: str = "",
        protocol_version: str = "",
    ):
        self.prev_hash = prev_hash
        self.event_type = event_type
        self.node_id = node_id
        self.payload = payload
        self.timestamp = timestamp or time.time()
        self.sequence = sequence
        self.signature = signature
        self.network_id = network_id or NETWORK_ID
        self.public_key = public_key
        self.public_key_algo = public_key_algo
        self.protocol_version = protocol_version or PROTOCOL_VERSION
        # Compute deterministic event ID
        self.event_id = self._compute_hash()

    def _compute_hash(self) -> str:
        """Deterministic SHA-256 hash of the event content."""
        content = (
            f"{self.prev_hash}:{self.event_type}:{self.node_id}:"
            f"{json.dumps(self.payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)}:"
            f"{self.timestamp}:{self.sequence}:{self.network_id}"
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "prev_hash": self.prev_hash,
            "event_type": self.event_type,
            "node_id": self.node_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "sequence": self.sequence,
            "signature": self.signature,
            "network_id": self.network_id,
            "public_key": self.public_key,
            "public_key_algo": self.public_key_algo,
            "protocol_version": self.protocol_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChainEvent":
        evt = cls(
            prev_hash=d["prev_hash"],
            event_type=d["event_type"],
            node_id=d["node_id"],
            payload=d["payload"],
            timestamp=d["timestamp"],
            sequence=d.get("sequence", 0),
            signature=d.get("signature", ""),
            network_id=d.get("network_id", NETWORK_ID),
            public_key=d.get("public_key", ""),
            public_key_algo=d.get("public_key_algo", ""),
            protocol_version=d.get("protocol_version", PROTOCOL_VERSION),
        )
        # Verify hash matches
        if evt.event_id != d.get("event_id"):
            raise ValueError(
                f"Hash mismatch on event load: computed {evt.event_id[:16]}, "
                f"stored {d.get('event_id', '?')[:16]}"
            )
        return evt


class Infonet:
    """The Infonet — ShadowBroker's append-only signed event ledger.

    The Infonet is the single source of truth. All actions go through here.
    The reputation ledger, gates, and oracle are computed views of Infonet state.
    """

    def __init__(self):
        self.events: list[dict] = []  # Stored as dicts for efficiency
        self.head_hash: str = GENESIS_HASH  # Hash of the latest event
        self.node_sequences: dict[str, int] = {}  # {node_id: last_sequence}
        self.sequence_domains: dict[str, int] = {}  # {node_id|domain: last_sequence}
        self.event_index: dict[str, int] = {}  # {event_id: index in events list}
        self.public_key_bindings: dict[str, str] = {}  # {public_key: canonical node_id}
        self.revocations: dict[str, dict] = {}
        self._replay_filter = ReplayFilter()
        self._last_validated_index: int = 0  # For incremental validation
        # Running counters — avoid O(N) scans in get_info()
        self._type_counts: dict[str, int] = {}
        self._active_count: int = 0
        self._chain_bytes: int = 2  # Start with "[]" empty JSON array
        self._dirty = False
        self._save_lock = threading.Lock()
        self._save_timer: threading.Timer | None = None
        self._SAVE_INTERVAL = 5.0  # seconds — coalesce writes
        atexit.register(self._flush)
        self._load()

    # ─── Persistence ──────────────────────────────────────────────────

    def _load(self):
        """Load Infonet from disk, self-healing on corruption.

        Sprint 2 / Rec #8: if the chain file or WAL is unreadable we
        quarantine the bad files, reset to genesis, and let the peer
        sync worker rebuild state from the network. The user never sees
        a crashed backend — recovery happens in the background.
        """
        if CHAIN_FILE.exists():
            try:
                data = json.loads(CHAIN_FILE.read_text(encoding="utf-8"))
                loaded_events = data.get("events", [])
                if not isinstance(loaded_events, list):
                    raise ValueError("Malformed chain: events must be a list")
                for evt in loaded_events:
                    if not isinstance(evt, dict):
                        raise ValueError("Malformed chain: event entry must be an object")
                    ChainEvent.from_dict(evt)
                self.events = loaded_events
                self.head_hash = data.get("head_hash", GENESIS_HASH)
                self.node_sequences = data.get("node_sequences", {})
                self.sequence_domains = data.get("sequence_domains", {})
                self._rebuild_state()
                self._rebuild_revocations()
                self._rebuild_counters()
                logger.info(
                    f"Loaded Infonet: {len(self.events)} events, head={self.head_hash[:16]}..."
                )
            except Exception as e:
                logger.error("Failed to load Infonet: %s — quarantining and resetting", e)
                self._quarantine_chain_file(reason=f"load_failed:{e}")
                self._reset_to_genesis()
        try:
            self._replay_wal()
        except RuntimeError as exc:
            # WAL quarantine already happened inside _replay_wal — the
            # chain advances we lost will re-flow from peers. Degraded
            # state, not a crash.
            logger.error("[infonet] WAL replay failed, continuing in re-sync mode: %s", exc)
            self._reset_to_genesis()

    def _quarantine_chain_file(self, *, reason: str) -> None:
        """Move a corrupt chain file aside so the next boot starts clean."""
        try:
            if not CHAIN_FILE.exists():
                return
            stamp = int(time.time())
            dest = CHAIN_FILE.with_suffix(f".json.quarantine.{stamp}")
            CHAIN_FILE.rename(dest)
            logger.error(
                "[infonet] Chain file quarantined (%s) → %s. Node will re-sync from peers.",
                reason,
                dest.name,
            )
        except Exception as exc:
            logger.error("[infonet] Failed to quarantine chain file: %s", exc)

    def _reset_to_genesis(self) -> None:
        """In-memory reset to empty state so peer sync can rebuild."""
        self.events = []
        self.head_hash = GENESIS_HASH
        self.node_sequences = {}
        self.sequence_domains = {}
        self.event_index = {}
        self.public_key_bindings = {}
        self.revocations = {}
        self._replay_filter = ReplayFilter()
        self._last_validated_index = 0
        self._type_counts = {}
        self._active_count = 0
        self._chain_bytes = 2

    def _rebuild_state(self) -> None:
        self.event_index = {}
        self.node_sequences = {}
        # Keep private signed-write replay domains across public-chain
        # rebuilds; these domains protect local side effects that are not
        # represented as public Infonet events.
        if not isinstance(getattr(self, "sequence_domains", None), dict):
            self.sequence_domains = {}
        self.public_key_bindings = {}
        self.revocations = {}
        self._replay_filter = ReplayFilter()
        for idx, evt in enumerate(self.events):
            event_id = evt.get("event_id", "")
            if event_id:
                self.event_index[event_id] = idx
                self._replay_filter.add(event_id)
            node_id = evt.get("node_id", "")
            sequence = _safe_int(evt.get("sequence", 0) or 0, 0)
            if node_id and sequence:
                last = self.node_sequences.get(node_id, 0)
                if sequence > last:
                    self.node_sequences[node_id] = sequence
            public_key = str(evt.get("public_key", "") or "")
            if public_key and node_id:
                existing = self.public_key_bindings.get(public_key)
                if not existing:
                    self.public_key_bindings[public_key] = node_id
                elif existing != node_id:
                    logger.warning(
                        "Public key binding conflict in stored chain for %s: %s vs %s",
                        public_key[:12],
                        _redact_node(existing),
                        _redact_node(node_id),
                    )
            if evt.get("event_type") == "key_revoke":
                self._apply_revocation(evt)
        if self.events:
            self.head_hash = self.events[-1].get("event_id", GENESIS_HASH)
        else:
            self.head_hash = GENESIS_HASH

    def _rebuild_counters(self) -> None:
        """Rebuild running counters from the full event list (called on load)."""
        now = time.time()
        self._type_counts = {}
        self._active_count = 0
        self._chain_bytes = 2  # "[]"
        for evt in self.events:
            t = evt.get("event_type", "unknown")
            self._type_counts[t] = self._type_counts.get(t, 0) + 1
            is_eph = evt.get("payload", {}).get("ephemeral") or evt.get("payload", {}).get("_ephemeral")
            if not is_eph or (now - evt.get("timestamp", 0)) < EPHEMERAL_TTL:
                self._active_count += 1
            self._chain_bytes += len(json.dumps(evt)) + 2  # +2 for ", " separator

    def _update_counters_for_event(self, evt: dict) -> None:
        """Incrementally update counters when a new event is appended."""
        t = evt.get("event_type", "unknown")
        self._type_counts[t] = self._type_counts.get(t, 0) + 1
        self._active_count += 1
        self._chain_bytes += len(json.dumps(evt)) + 2

    def _write_wal(self, event_dict: dict) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(WAL_FILE, json.dumps({"event": event_dict}), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to write WAL: {e}")

    def _clear_wal(self) -> None:
        try:
            if WAL_FILE.exists():
                WAL_FILE.unlink()
        except Exception as e:
            logger.error(f"Failed to clear WAL: {e}")

    def _replay_wal(self) -> None:
        """Replay any surviving WAL entry after a crash, fail-closed.

        Sprint 2 / Rec #8: a corrupt or unreplayable WAL means the node
        crashed mid-append — we do NOT silently discard it. Instead we
        quarantine the WAL file, log loudly, and raise so the caller
        (__init__ via _load) can surface the degraded state rather than
        pretending the chain is healthy. The user never gets a silent
        data-loss window.
        """
        if not WAL_FILE.exists():
            return
        try:
            data = json.loads(WAL_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            self._quarantine_wal(f"corrupt_json:{exc}")
            raise RuntimeError(
                "Infonet WAL is corrupt — quarantined. Chain is in a degraded state; "
                "recover by re-syncing from peers."
            ) from exc
        evt = data.get("event") if isinstance(data, dict) else None
        if not isinstance(evt, dict):
            self._quarantine_wal("malformed_shape")
            raise RuntimeError(
                "Infonet WAL shape invalid — quarantined. Chain is in a degraded state."
            )
        if evt.get("event_id") in self.event_index:
            # Already durable in the chain file — WAL is stale but safe.
            self._clear_wal()
            return
        if evt.get("prev_hash") != self.head_hash:
            # The WAL entry is for an older head — the chain advanced past
            # it through another path. Safe to drop.
            self._clear_wal()
            return
        try:
            result = self.ingest_events([evt])
        except Exception as exc:
            self._quarantine_wal(f"replay_raised:{exc}")
            raise RuntimeError(
                "Infonet WAL event failed to replay — quarantined. Recover by re-syncing."
            ) from exc
        if not result.get("accepted"):
            self._quarantine_wal("replay_rejected")
            raise RuntimeError(
                f"Infonet WAL event rejected on replay: {result.get('rejected') or 'unknown'}"
            )
        logger.info("Replayed WAL event after restart")
        # Force a synchronous flush so the replayed event is durable
        # before we hand control back to the rest of the boot sequence.
        # _flush() clears the WAL as part of a successful write.
        self._flush()

    def _quarantine_wal(self, reason: str) -> None:
        """Move a bad WAL file aside so subsequent boots don't loop on it."""
        try:
            if not WAL_FILE.exists():
                return
            stamp = int(time.time())
            dest = WAL_FILE.with_suffix(f".wal.quarantine.{stamp}")
            WAL_FILE.rename(dest)
            logger.error(
                "[infonet] WAL quarantined (%s) → %s. Node is degraded until re-sync.",
                reason,
                dest.name,
            )
        except Exception as exc:
            logger.error("[infonet] Failed to quarantine WAL: %s", exc)

    def reset_chain(self) -> None:
        """Wipe local chain state so the next sync starts from genesis.

        Used for automatic fork recovery when the local chain is small and
        has diverged from the network.  Does NOT touch gate_store or WAL.
        """
        prev_len = len(self.events)
        self.events = []
        self.head_hash = GENESIS_HASH
        self.node_sequences = {}
        self.sequence_domains = {}
        self.event_index = {}
        self.public_key_bindings = {}
        self.revocations = {}
        self._replay_filter = ReplayFilter()
        self._last_validated_index = 0
        self._type_counts = {}
        self._active_count = 0
        self._chain_bytes = 2
        self._dirty = True
        self._flush()
        logger.warning("Chain reset: discarded %d local events for fork recovery", prev_len)

    def _save(self):
        """Mark dirty and schedule a coalesced disk write.

        Instead of writing multi-MB JSON on every event, we set a dirty flag
        and schedule a single write after _SAVE_INTERVAL seconds. Multiple
        rapid calls collapse into one I/O operation.
        """
        self._dirty = True
        with self._save_lock:
            if self._save_timer is None or not self._save_timer.is_alive():
                self._save_timer = threading.Timer(self._SAVE_INTERVAL, self._flush)
                self._save_timer.daemon = True
                self._save_timer.start()

    def _flush(self):
        """Actually write to disk (called by timer or atexit).

        Sprint 2 / Rec #8: clears the WAL only after the chain file has
        been durably written. A crash before _flush() succeeds leaves
        the WAL in place so _replay_wal() can recover on next boot.
        """
        if not self._dirty:
            return
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "protocol": "infonet",
                "network_id": NETWORK_ID,
                "head_hash": self.head_hash,
                "node_sequences": self.node_sequences,
                "sequence_domains": self.sequence_domains,
                "events": self.events,
            }
            _atomic_write_text(CHAIN_FILE, json.dumps(data, indent=2), encoding="utf-8")
            self._dirty = False
            # Chain file is now durable — safe to retire the WAL entry.
            self._clear_wal()
        except Exception as e:
            logger.error(f"Failed to save Infonet: {e}")

    def ensure_materialized(self) -> None:
        """Write the current chain state to disk even if nothing is dirty yet."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "protocol": "infonet",
                "network_id": NETWORK_ID,
                "head_hash": self.head_hash,
                "node_sequences": self.node_sequences,
                "sequence_domains": self.sequence_domains,
                "events": self.events,
            }
            _atomic_write_text(CHAIN_FILE, json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to materialize Infonet: {e}")
            raise

    def confirmations_for_event(self, event_id: str) -> int:
        idx = self.event_index.get(event_id)
        if idx is None:
            return 0
        return max(0, len(self.events) - 1 - idx)

    def decorate_event(self, evt: dict) -> dict:
        if evt.get("event_type") not in CRITICAL_EVENT_TYPES:
            return evt
        confirmations = self.confirmations_for_event(evt.get("event_id", ""))
        decorated = dict(evt)
        decorated["confirmations"] = confirmations
        decorated["confirmed"] = confirmations >= MIN_CONFIRMATIONS_CRITICAL
        return decorated

    def decorate_events(self, events: list[dict]) -> list[dict]:
        return [self.decorate_event(evt) for evt in events]

    def chain_lock(self) -> dict:
        if len(self.events) <= CHAIN_LOCK_DEPTH:
            return {"depth": CHAIN_LOCK_DEPTH, "event_id": "", "active": False}
        idx = max(0, len(self.events) - 1 - CHAIN_LOCK_DEPTH)
        return {
            "depth": CHAIN_LOCK_DEPTH,
            "event_id": self.events[idx].get("event_id", ""),
            "active": True,
        }

    def _bind_public_key(self, public_key: str, node_id: str) -> tuple[bool, str]:
        key = str(public_key or "")
        node = str(node_id or "")
        if not key or not node:
            return False, "Missing public key binding fields"
        existing = self.public_key_bindings.get(key)
        if existing and existing != node:
            return False, f"public key already bound to {existing}"
        self.public_key_bindings[key] = node
        return True, "ok"

    def _apply_revocation(self, evt: dict) -> None:
        payload = evt.get("payload", {})
        public_key = payload.get("revoked_public_key") or evt.get("public_key", "")
        if not public_key:
            return
        revoked_at = _safe_int(payload.get("revoked_at", 0) or 0, 0)
        grace_until = _safe_int(payload.get("grace_until", revoked_at) or revoked_at, revoked_at)
        info = {
            "public_key": public_key,
            "public_key_algo": payload.get("revoked_public_key_algo") or evt.get("public_key_algo"),
            "revoked_at": revoked_at,
            "grace_until": grace_until,
            "reason": payload.get("reason", ""),
            "event_id": evt.get("event_id", ""),
            "node_id": evt.get("node_id", ""),
        }
        existing = self.revocations.get(public_key)
        if not existing or revoked_at >= _safe_int(existing.get("revoked_at", 0), 0):
            self.revocations[public_key] = info

    def _rebuild_revocations(self) -> None:
        self.revocations = {}
        for evt in self.events:
            if evt.get("event_type") == "key_revoke":
                self._apply_revocation(evt)

    def _revocation_status(self, public_key: str) -> tuple[bool, dict | None]:
        info = self.revocations.get(public_key)
        if not info:
            return False, None
        now = time.time()
        if now > _safe_int(info.get("grace_until", 0) or 0, 0):
            return True, info
        return False, info

    # ─── Append ───────────────────────────────────────────────────────

    def validate_and_set_sequence(
        self,
        node_id: str,
        sequence: int,
        *,
        domain: str = "",
    ) -> tuple[bool, str]:
        """Validate monotonic sequence and update last-seen value if valid."""
        if sequence <= 0:
            return False, "Sequence must be a positive integer"
        normalized_domain = str(domain or "").strip().lower()
        table = self.sequence_domains if normalized_domain else self.node_sequences
        key = f"{node_id}|{normalized_domain}" if normalized_domain else node_id
        last = table.get(key, 0)
        if sequence <= last:
            from services.mesh.mesh_metrics import increment as metrics_inc

            metrics_inc("replay_attempts")
            return False, f"Replay detected: sequence {sequence} <= last {last}"
        table[key] = sequence
        self._save()
        return True, "ok"

    def append(
        self,
        event_type: str,
        node_id: str,
        payload: dict,
        signature: str = "",
        sequence: int = 0,
        ephemeral: bool = False,
        public_key: str = "",
        public_key_algo: str = "",
        protocol_version: str = "",
        timestamp_bucket_s: int = 0,
    ) -> dict:
        """Append a new event to the Infonet. Returns the event dict.

        Args:
            event_type: Type of event (message, vote, gate_create, etc.)
            node_id: Author node ID
            payload: Event-specific data
            signature: Cryptographic signature from node's private key
            ephemeral: If True, event auto-purges after 24h

        Returns:
            The event dict with computed event_id
        """
        from services.mesh.mesh_crypto import (
            build_signature_payload,
            parse_public_key_algo,
            verify_node_binding,
            verify_signature,
        )

        if event_type not in ACTIVE_APPEND_EVENT_TYPES:
            raise ValueError(f"Unsupported event_type: {event_type}")

        if sequence <= 0:
            raise ValueError("sequence is required and must be > 0")
        last = self.node_sequences.get(node_id, 0)
        if sequence <= last:
            raise ValueError(f"Replay detected: sequence {sequence} <= last {last}")

        payload = normalize_payload(event_type, dict(payload or {}))

        ok, reason = validate_event_payload(event_type, payload)
        if not ok:
            raise ValueError(reason)
        ok, reason = validate_public_ledger_payload(event_type, payload)
        if not ok:
            raise ValueError(reason)

        if event_type == "message":
            if "ephemeral" not in payload:
                payload["ephemeral"] = bool(ephemeral)
        else:
            payload.pop("ephemeral", None)

        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload exceeds max size")

        protocol_version = str(protocol_version or PROTOCOL_VERSION)
        ok, reason = validate_protocol_fields(protocol_version, NETWORK_ID)
        if not ok:
            raise ValueError(reason)

        if not (signature and public_key and public_key_algo):
            raise ValueError("Missing signature fields")
        if not parse_public_key_algo(public_key_algo):
            raise ValueError("Unsupported public_key_algo")
        if not verify_node_binding(node_id, public_key):
            raise ValueError("node_id mismatch")
        bound, bind_reason = self._bind_public_key(public_key, node_id)
        if not bound:
            raise ValueError(bind_reason)
        sig_payload = build_signature_payload(
            event_type=event_type,
            node_id=node_id,
            sequence=sequence,
            payload=payload,
        )
        if not verify_signature(
            public_key_b64=public_key,
            public_key_algo=public_key_algo,
            signature_hex=signature,
            payload=sig_payload,
        ):
            raise ValueError("Invalid signature")

        if public_key:
            revoked, _info = self._revocation_status(public_key)
            if revoked and event_type != "key_revoke":
                raise ValueError("public key is revoked")

        if event_type == "key_revoke":
            if payload.get("revoked_public_key") and payload.get("revoked_public_key") != public_key:
                raise ValueError("revoked_public_key must match event public_key")
            if payload.get("revoked_public_key_algo") and payload.get(
                "revoked_public_key_algo"
            ) != public_key_algo:
                raise ValueError("revoked_public_key_algo must match event public_key_algo")

        if timestamp_bucket_s > 0:
            ts = time.time()
            ts = float(int(ts / timestamp_bucket_s) * timestamp_bucket_s)
        else:
            ts = time.time()

        # Create event
        event = ChainEvent(
            prev_hash=self.head_hash,
            event_type=event_type,
            node_id=node_id,
            payload=payload,
            timestamp=ts,
            sequence=sequence,
            signature=signature,
            public_key=public_key,
            public_key_algo=public_key_algo,
            protocol_version=protocol_version,
        )

        event_dict = event.to_dict()
        self._write_wal(event_dict)
        self.events.append(event_dict)
        self.event_index[event.event_id] = len(self.events) - 1
        self.head_hash = event.event_id
        self.node_sequences[node_id] = sequence
        self._replay_filter.add(event.event_id)
        self._update_counters_for_event(event_dict)

        if event_type == "key_revoke":
            self._apply_revocation(event_dict)

        # Sprint 2 / Rec #8: do NOT clear the WAL here. _save() only
        # schedules a coalesced flush; clearing now would open a crash
        # window where the event is gone from the WAL but not yet in
        # the chain file. _flush() clears the WAL only after a
        # successful durable write.
        self._save()

        try:
            from services.mesh.mesh_rns import rns_bridge

            rns_bridge.publish_event(event_dict)
        except Exception:
            pass
        _notify_public_event_append_hooks(event_dict)

        logger.info(
            f"Infonet append [{event_type}] by {_redact_node(node_id)} seq={sequence} "
            f"id={event.event_id[:16]}..."
        )
        return event_dict

    def ingest_events(self, events: list[dict]) -> dict:
        """Ingest a sequence of external events. Requires contiguous prev_hash."""
        accepted = 0
        duplicates = 0
        rejected: list[dict] = []
        expected_prev = self.head_hash

        for idx, evt in enumerate(events):
            if not isinstance(evt, dict):
                rejected.append({"index": idx, "reason": "Event is not an object"})
                continue

            event_type = evt.get("event_type", "")
            node_id = evt.get("node_id", "")
            event_id = evt.get("event_id", "")
            prev_hash = evt.get("prev_hash", "")
            sequence = _safe_int(evt.get("sequence", 0) or 0, 0)

            if event_type not in ALLOWED_EVENT_TYPES:
                rejected.append({"index": idx, "reason": "Unsupported event_type"})
                continue
            if not event_id or not prev_hash:
                rejected.append({"index": idx, "reason": "Missing event_id or prev_hash"})
                continue
            if prev_hash != expected_prev:
                try:
                    from services.mesh.mesh_metrics import increment as metrics_inc

                    metrics_inc("ingest_prev_hash_mismatch")
                except Exception:
                    pass
                rejected.append({"index": idx, "reason": "prev_hash does not match head"})
                continue
            if evt.get("network_id") != NETWORK_ID:
                try:
                    from services.mesh.mesh_metrics import increment as metrics_inc

                    metrics_inc("ingest_network_mismatch")
                except Exception:
                    pass
                rejected.append({"index": idx, "reason": "network_id mismatch"})
                continue
            if event_id in self.event_index:
                duplicates += 1
                continue
            if self._replay_filter.seen(event_id):
                try:
                    from services.mesh.mesh_metrics import increment as metrics_inc

                    metrics_inc("ingest_replay_seen")
                except Exception:
                    pass
                duplicates += 1
                continue
            if prev_hash != self.head_hash:
                rejected.append({"index": idx, "reason": "prev_hash does not match head"})
                continue
            if sequence <= 0:
                rejected.append({"index": idx, "reason": "Invalid sequence"})
                continue
            last = self.node_sequences.get(node_id, 0)
            if sequence <= last:
                rejected.append({"index": idx, "reason": "Replay detected"})
                continue
            # Hardening Rec #8: timestamp freshness bound. The sequence check
            # above catches replays once a node has observed the author, but
            # a fresh peer (node_sequences[node_id] == 0) accepts any
            # sequence > 0 — so an attacker could replay an ancient signed
            # event into a node that's never seen the author. Rejecting
            # events whose timestamp is outside a bounded freshness window
            # closes that hole without breaking catch-up sync for
            # short-lived network partitions.
            try:
                from services.mesh.mesh_rollout_flags import ingest_event_max_age_s

                max_age_s = int(ingest_event_max_age_s() or 0)
            except Exception:
                max_age_s = 0
            if max_age_s > 0:
                evt_ts = _safe_int(evt.get("timestamp", 0) or 0, 0)
                if evt_ts > 0 and abs(int(time.time()) - evt_ts) > max_age_s:
                    try:
                        from services.mesh.mesh_metrics import increment as metrics_inc

                        metrics_inc("ingest_timestamp_stale")
                    except Exception:
                        pass
                    rejected.append({"index": idx, "reason": "Event timestamp outside freshness window"})
                    continue

            payload = evt.get("payload", {})
            ok, reason = validate_event_payload(event_type, payload)
            if not ok:
                rejected.append({"index": idx, "reason": reason})
                continue
            ok, reason = validate_public_ledger_payload(event_type, payload)
            if not ok:
                rejected.append({"index": idx, "reason": reason})
                continue
            if event_type == "message" and "ephemeral" not in payload:
                rejected.append({"index": idx, "reason": "Missing ephemeral flag"})
                continue

            payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if len(payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES:
                try:
                    from services.mesh.mesh_metrics import increment as metrics_inc

                    metrics_inc("ingest_payload_too_large")
                except Exception:
                    pass
                rejected.append({"index": idx, "reason": "Payload too large"})
                continue

            proto = evt.get("protocol_version") or PROTOCOL_VERSION
            if proto != PROTOCOL_VERSION:
                try:
                    from services.mesh.mesh_metrics import increment as metrics_inc

                    metrics_inc("ingest_proto_mismatch")
                except Exception:
                    pass
                rejected.append({"index": idx, "reason": "Unsupported protocol_version"})
                continue

            signature = evt.get("signature", "")
            public_key = evt.get("public_key", "")
            public_key_algo = evt.get("public_key_algo", "")
            if not (signature and public_key and public_key_algo):
                try:
                    from services.mesh.mesh_metrics import increment as metrics_inc

                    metrics_inc("ingest_signature_missing")
                except Exception:
                    pass
                rejected.append({"index": idx, "reason": "Missing signature fields"})
                continue
            from services.mesh.mesh_crypto import parse_public_key_algo

            if not parse_public_key_algo(public_key_algo):
                rejected.append({"index": idx, "reason": "Unsupported public_key_algo"})
                continue

            if event_type == "key_revoke":
                if payload.get("revoked_public_key") and payload.get(
                    "revoked_public_key"
                ) != public_key:
                    rejected.append(
                        {"index": idx, "reason": "revoked_public_key must match public_key"}
                    )
                    continue
                if payload.get("revoked_public_key_algo") and payload.get(
                    "revoked_public_key_algo"
                ) != public_key_algo:
                    rejected.append(
                        {
                            "index": idx,
                            "reason": "revoked_public_key_algo must match public_key_algo",
                        }
                    )
                    continue
            revoked, _info = self._revocation_status(public_key)
            if revoked and event_type != "key_revoke":
                try:
                    from services.mesh.mesh_metrics import increment as metrics_inc

                    metrics_inc("ingest_key_revoked")
                except Exception:
                    pass
                rejected.append({"index": idx, "reason": "public key is revoked"})
                continue
            last_seq = self.node_sequences.get(node_id, 0)
            if sequence <= last_seq:
                try:
                    from services.mesh.mesh_metrics import increment as metrics_inc

                    metrics_inc("ingest_replay_sequence")
                except Exception:
                    pass
                rejected.append(
                    {
                        "index": idx,
                        "reason": f"Replay detected: sequence {sequence} <= last {last_seq}",
                    }
                )
                continue

            from services.mesh.mesh_crypto import (
                build_signature_payload,
                verify_signature,
                verify_node_binding,
            )

            if not verify_node_binding(node_id, public_key):
                try:
                    from services.mesh.mesh_metrics import increment as metrics_inc

                    metrics_inc("ingest_node_mismatch")
                except Exception:
                    pass
                rejected.append({"index": idx, "reason": "node_id mismatch"})
                continue
            bound, bind_reason = self._bind_public_key(public_key, node_id)
            if not bound:
                rejected.append({"index": idx, "reason": bind_reason})
                continue

            sig_payload = build_signature_payload(
                event_type=event_type,
                node_id=node_id,
                sequence=sequence,
                payload=payload,
            )
            if not verify_signature(
                public_key_b64=public_key,
                public_key_algo=public_key_algo,
                signature_hex=signature,
                payload=sig_payload,
            ):
                try:
                    from services.mesh.mesh_metrics import increment as metrics_inc

                    metrics_inc("ingest_signature_invalid")
                except Exception:
                    pass
                rejected.append({"index": idx, "reason": "Invalid signature"})
                continue

            # Verify event_id/hash linkage
            try:
                computed = ChainEvent.from_dict(evt).event_id
            except (ValueError, KeyError, TypeError) as exc:
                rejected.append({"index": idx, "reason": f"event_id hash mismatch: {exc}"})
                continue
            if computed != event_id:
                try:
                    from services.mesh.mesh_metrics import increment as metrics_inc

                    metrics_inc("ingest_event_id_mismatch")
                except Exception:
                    pass
                rejected.append({"index": idx, "reason": "event_id mismatch"})
                continue

            # Accept
            self.events.append(evt)
            self.event_index[event_id] = len(self.events) - 1
            self.head_hash = event_id
            self.node_sequences[node_id] = sequence
            accepted += 1
            expected_prev = event_id
            self._replay_filter.add(event_id)
            if event_type == "key_revoke":
                self._apply_revocation(evt)

        if accepted:
            self._save()
        return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}

    # ─── Validation ───────────────────────────────────────────────────

    def validate_chain(self, verify_signatures: bool = False) -> tuple[bool, str]:
        """Verify the entire Infonet's integrity.

        Checks that each event's prev_hash matches the previous event's event_id,
        and that each event's hash is correct.

        Returns (valid, reason)
        """
        if not self.events:
            return True, "Empty chain"

        prev = GENESIS_HASH
        seen_public_keys: dict[str, str] = {}
        for i, evt_dict in enumerate(self.events):
            # Check prev_hash linkage
            if evt_dict["prev_hash"] != prev:
                return False, (
                    f"Broken link at index {i}: expected prev_hash "
                    f"{prev[:16]}..., got {evt_dict['prev_hash'][:16]}..."
                )

            # Recompute hash and verify
            evt = ChainEvent.from_dict(evt_dict)
            if evt.event_id != evt_dict["event_id"]:
                return False, (
                    f"Hash mismatch at index {i}: computed "
                    f"{evt.event_id[:16]}..., stored {evt_dict['event_id'][:16]}..."
                )

            if verify_signatures:
                proto = evt_dict.get("protocol_version") or PROTOCOL_VERSION
                if proto != PROTOCOL_VERSION:
                    return False, f"Unsupported protocol_version at index {i}: {proto}"
                signature = evt_dict.get("signature", "")
                public_key = evt_dict.get("public_key", "")
                public_key_algo = evt_dict.get("public_key_algo", "")
                if not (signature and public_key and public_key_algo):
                    return False, f"Missing signature fields at index {i}"

                from services.mesh.mesh_crypto import (
                    build_signature_payload,
                    parse_public_key_algo,
                    verify_signature,
                    verify_node_binding,
                )

                node_id = evt_dict.get("node_id", "")
                if not parse_public_key_algo(public_key_algo):
                    return False, f"Unsupported public_key_algo at index {i}"
                if not verify_node_binding(node_id, public_key):
                    return False, f"node_id mismatch at index {i}"
                existing = seen_public_keys.get(public_key)
                if existing and existing != node_id:
                    return False, f"public key binding conflict at index {i}"
                seen_public_keys[public_key] = node_id

                normalized = normalize_payload(
                    evt_dict.get("event_type", ""), evt_dict.get("payload", {})
                )
                sig_payload = build_signature_payload(
                    event_type=evt_dict.get("event_type", ""),
                    node_id=node_id,
                    sequence=_safe_int(evt_dict.get("sequence", 0) or 0, 0),
                    payload=normalized,
                )
                if not verify_signature(
                    public_key_b64=public_key,
                    public_key_algo=public_key_algo,
                    signature_hex=signature,
                    payload=sig_payload,
                ):
                    return False, f"Invalid signature at index {i}"

            prev = evt_dict["event_id"]

        if prev != self.head_hash:
            return (
                False,
                f"Head hash mismatch: chain ends at {prev[:16]}... but head is {self.head_hash[:16]}...",
            )

        return True, f"Valid Infonet: {len(self.events)} events"

    def validate_chain_incremental(self, verify_signatures: bool = False) -> tuple[bool, str]:
        """Validate only events appended since last successful validation.

        Much faster than full validate_chain() on large chains — O(new) vs O(N).
        Falls back to full validation if the chain has been restructured.
        """
        total = len(self.events)
        start = self._last_validated_index
        if start > total:
            # Chain was truncated (fork resolution) — fall back to full
            self._last_validated_index = 0
            return self.validate_chain(verify_signatures=verify_signatures)
        if start >= total:
            return True, f"No new events (chain has {total} events)"

        # Determine expected prev_hash at the start index
        if start == 0:
            prev = GENESIS_HASH
        else:
            prev = self.events[start - 1]["event_id"]

        for i in range(start, total):
            evt_dict = self.events[i]
            if evt_dict["prev_hash"] != prev:
                return False, (
                    f"Broken link at index {i}: expected prev_hash "
                    f"{prev[:16]}..., got {evt_dict['prev_hash'][:16]}..."
                )
            evt = ChainEvent.from_dict(evt_dict)
            if evt.event_id != evt_dict["event_id"]:
                return False, (
                    f"Hash mismatch at index {i}: computed "
                    f"{evt.event_id[:16]}..., stored {evt_dict['event_id'][:16]}..."
                )

            if verify_signatures:
                proto = evt_dict.get("protocol_version") or PROTOCOL_VERSION
                if proto != PROTOCOL_VERSION:
                    return False, f"Unsupported protocol_version at index {i}: {proto}"
                signature = evt_dict.get("signature", "")
                public_key = evt_dict.get("public_key", "")
                public_key_algo = evt_dict.get("public_key_algo", "")
                if not (signature and public_key and public_key_algo):
                    return False, f"Missing signature fields at index {i}"

                from services.mesh.mesh_crypto import (
                    build_signature_payload,
                    parse_public_key_algo,
                    verify_signature,
                    verify_node_binding,
                )

                node_id = evt_dict.get("node_id", "")
                if not parse_public_key_algo(public_key_algo):
                    return False, f"Unsupported public_key_algo at index {i}"
                if not verify_node_binding(node_id, public_key):
                    return False, f"node_id mismatch at index {i}"

                normalized = normalize_payload(
                    evt_dict.get("event_type", ""), evt_dict.get("payload", {})
                )
                sig_payload = build_signature_payload(
                    event_type=evt_dict.get("event_type", ""),
                    node_id=node_id,
                    sequence=_safe_int(evt_dict.get("sequence", 0) or 0, 0),
                    payload=normalized,
                )
                if not verify_signature(
                    public_key_b64=public_key,
                    public_key_algo=public_key_algo,
                    signature_hex=signature,
                    payload=sig_payload,
                ):
                    return False, f"Invalid signature at index {i}"
            prev = evt_dict["event_id"]

        if prev != self.head_hash:
            return False, (
                f"Head hash mismatch: chain ends at {prev[:16]}... but head is {self.head_hash[:16]}..."
            )

        self._last_validated_index = total
        return True, f"Valid Infonet: {total} events ({total - start} new)"

    def _order_chain_from(self, prev_hash: str, events: list[dict]) -> list[dict] | None:
        by_prev: dict[str, dict] = {}
        for evt in events:
            p = evt.get("prev_hash", "")
            if not p:
                return None
            if p in by_prev:
                return None
            by_prev[p] = evt
        ordered = []
        current = prev_hash
        while current in by_prev:
            evt = by_prev[current]
            ordered.append(evt)
            current = evt.get("event_id", "")
            if not current:
                return None
        if len(ordered) != len(events):
            return None
        return ordered

    def apply_fork(self, events: list[dict], head_hash: str, proof_count: int, quorum: int) -> tuple[bool, str]:
        if not events:
            return False, "empty fork"
        if proof_count < max(2, int(quorum)):
            return False, "insufficient quorum"
        prev_hash = events[0].get("prev_hash", "")
        if not prev_hash:
            return False, "missing prev_hash"
        prev_index = self.event_index.get(prev_hash)
        if prev_index is None:
            return False, "unknown ancestor"
        depth_from_head = len(self.events) - 1 - prev_index
        if depth_from_head > CHAIN_LOCK_DEPTH:
            return False, "chain lock prevents reorg"
        ordered = self._order_chain_from(prev_hash, events)
        if not ordered:
            return False, "non-contiguous fork"
        if ordered[-1].get("event_id", "") != head_hash:
            return False, "head_hash mismatch"
        current_tail_len = len(self.events) - 1 - prev_index
        if len(ordered) <= current_tail_len:
            return False, "fork not longer"

        # Validate events and sequences against prefix
        prefix = self.events[: prev_index + 1]
        last_seq: dict[str, int] = {}
        seen_public_keys: dict[str, str] = {}
        for evt in prefix:
            node_id = evt.get("node_id", "")
            sequence = _safe_int(evt.get("sequence", 0) or 0, 0)
            if node_id and sequence:
                last_seq[node_id] = max(last_seq.get(node_id, 0), sequence)
            public_key = str(evt.get("public_key", "") or "")
            if public_key and node_id:
                seen_public_keys.setdefault(public_key, node_id)

        for evt in ordered:
            event_type = evt.get("event_type", "")
            node_id = evt.get("node_id", "")
            event_id = evt.get("event_id", "")
            sequence = _safe_int(evt.get("sequence", 0) or 0, 0)
            payload = evt.get("payload", {})
            if event_type not in ALLOWED_EVENT_TYPES:
                return False, "unsupported event_type"
            if not event_id or not node_id:
                return False, "missing fields"
            if evt.get("network_id") != NETWORK_ID:
                return False, "network mismatch"
            existing_idx = self.event_index.get(event_id)
            if existing_idx is not None and existing_idx <= prev_index:
                return False, "duplicate event_id"
            payload = normalize_payload(event_type, dict(payload or {}))
            ok, reason = validate_event_payload(event_type, payload)
            if not ok:
                return False, reason
            proto = evt.get("protocol_version") or PROTOCOL_VERSION
            if proto != PROTOCOL_VERSION:
                return False, "unsupported protocol_version"
            signature = evt.get("signature", "")
            public_key = evt.get("public_key", "")
            public_key_algo = evt.get("public_key_algo", "")
            if not (signature and public_key and public_key_algo):
                return False, "missing signature fields"
            revoked, _info = self._revocation_status(public_key)
            if revoked and event_type != "key_revoke":
                return False, "public key revoked"
            last = last_seq.get(node_id, 0)
            if sequence <= last:
                return False, "sequence replay"
            from services.mesh.mesh_crypto import (
                build_signature_payload,
                parse_public_key_algo,
                verify_signature,
                verify_node_binding,
            )

            if not parse_public_key_algo(public_key_algo):
                return False, "unsupported public_key_algo"
            if not verify_node_binding(node_id, public_key):
                return False, "node_id mismatch"
            existing = seen_public_keys.get(public_key)
            if existing and existing != node_id:
                return False, "public key binding conflict"
            seen_public_keys[public_key] = node_id
            sig_payload = build_signature_payload(
                event_type=event_type,
                node_id=node_id,
                sequence=sequence,
                payload=payload,
            )
            if not verify_signature(
                public_key_b64=public_key,
                public_key_algo=public_key_algo,
                signature_hex=signature,
                payload=sig_payload,
            ):
                return False, "invalid signature"
            computed = ChainEvent.from_dict(evt).event_id
            if computed != event_id:
                return False, "event_id mismatch"
            last_seq[node_id] = sequence

        # Apply fork
        self.events = prefix + ordered
        self._rebuild_state()
        self._save()
        try:
            from services.mesh.mesh_metrics import increment as metrics_inc

            metrics_inc("fork_applied")
        except Exception:
            pass
        return True, "applied"

    def check_replay(self, node_id: str, sequence: int) -> bool:
        """Check if a sequence number has already been used by this node.

        Returns True if this is a REPLAY (bad), False if fresh (good).
        """
        return sequence <= self.node_sequences.get(node_id, 0)

    # ─── Queries ──────────────────────────────────────────────────────

    def get_event(self, event_id: str) -> dict | None:
        """Look up a single event by ID."""
        idx = self.event_index.get(event_id)
        if idx is not None and idx < len(self.events):
            return self.events[idx]
        return None

    def annotate_event(self, event_id: str, meta: dict) -> bool:
        """Attach non-consensus metadata to an event (not part of hash)."""
        idx = self.event_index.get(event_id)
        if idx is None or idx >= len(self.events):
            return False
        self.events[idx]["meta"] = meta
        self._save()
        return True

    def get_events_by_type(
        self,
        event_type: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Get recent events of a specific type (newest first)."""
        matching = []
        for e in reversed(self.events):
            if e["event_type"] != event_type:
                continue
            matching.append(e)
        return matching[offset : offset + limit]

    def get_events_by_node(self, node_id: str, limit: int = 50) -> list[dict]:
        """Get recent events by a specific node (newest first)."""
        matching = []
        for e in reversed(self.events):
            if e["node_id"] != node_id:
                continue
            matching.append(e)
        return matching[:limit]

    def get_messages(
        self,
        gate_id: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Get messages, optionally filtered by gate.

        Returns public-plane 'message' events only.
        Returns newest first with message-specific fields extracted.
        """
        results = []
        for evt in reversed(self.events):
            if evt["event_type"] != "message":
                continue
            payload = evt.get("payload", {})
            # Skip ephemeral messages that have expired
            if payload.get("ephemeral") or payload.get("_ephemeral"):
                age = time.time() - evt["timestamp"]
                if age > EPHEMERAL_TTL:
                    continue
            # Gate filter
            msg_gate = payload.get("gate", "")
            if gate_id and msg_gate != gate_id:
                continue
            # Skip transport-routed messages (Meshtastic/APRS) from InfoNet feed —
            # they belong in their own tab. Only direct InfoNet/gate posts appear here.
            meta = evt.get("meta", {})
            if payload.get("routed_via") or meta.get("routed_via"):
                continue

            results.append(
                {
                    "event_id": evt["event_id"],
                    "event_type": evt.get("event_type", ""),
                    "node_id": evt["node_id"],
                    "message": payload.get("message", payload.get("text", "")),
                    "ciphertext": payload.get("ciphertext", ""),
                    "epoch": payload.get("epoch", 0),
                    "nonce": payload.get("nonce", payload.get("iv", "")),
                    "sender_ref": payload.get("sender_ref", ""),
                    "format": payload.get("format", ""),
                    "destination": payload.get("destination", "broadcast"),
                    "channel": payload.get("channel", "LongFast"),
                    "priority": payload.get("priority", "normal"),
                    "gate": msg_gate,
                    "timestamp": evt["timestamp"],
                    "sequence": evt.get("sequence", 0),
                    "ephemeral": payload.get("ephemeral", payload.get("_ephemeral", False)),
                    "signature": evt.get("signature", ""),
                    "public_key": evt.get("public_key", ""),
                    "public_key_algo": evt.get("public_key_algo", ""),
                    "protocol_version": evt.get("protocol_version", ""),
                }
            )

            if len(results) >= offset + limit:
                break

        return results[offset : offset + limit]

    def get_info(self) -> dict:
        """Infonet metadata for status display. O(1) via running counters."""
        return {
            "protocol": "infonet",
            "network_id": NETWORK_ID,
            "total_events": len(self.events),
            "active_events": self._active_count,
            "head_hash": self.head_hash[:16] + "...",
            "head_hash_full": self.head_hash,
            "chain_lock": self.chain_lock(),
            "known_nodes": len(self.node_sequences),
            "event_types": dict(self._type_counts),
            "chain_size_kb": round(self._chain_bytes / 1024, 1),
            "unsigned_events": 0,
        }

    # ─── Cleanup ──────────────────────────────────────────────────────

    def cleanup(self):
        """Remove expired ephemeral events and old events beyond retention window.

        Note: This breaks the chain linkage for removed events, so we only
        remove from the beginning (oldest events). The chain remains valid
        from the first remaining event forward.
        """
        now = time.time()
        retention_cutoff = now - (MESSAGE_RETENTION_DAYS * 86400)
        before = len(self.events)

        # Remove events that are both old AND ephemeral-expired
        new_events = []
        for evt in self.events:
            payload = evt.get("payload", {})
            is_ephemeral = payload.get("ephemeral", payload.get("_ephemeral", False))
            age = now - evt["timestamp"]

            # Keep if: not ephemeral-expired AND within retention window
            if is_ephemeral and age > EPHEMERAL_TTL:
                continue  # Expired ephemeral — drop
            if evt["timestamp"] < retention_cutoff and is_ephemeral:
                continue  # Old ephemeral — drop

            new_events.append(evt)

        if len(new_events) != before:
            self.events = new_events
            # Rebuild index
            self.event_index = {e["event_id"]: i for i, e in enumerate(self.events)}
            self._save()
            logger.info(f"Infonet cleanup: removed {before - len(new_events)} expired events")

    # ─── Gossip Sync (Future) ────────────────────────────────────────

    def get_merkle_root(self) -> str:
        """Compute a Merkle root hash of the Infonet for sync comparison.

        Two nodes with the same Merkle root have identical chains.
        """
        if not self.events:
            return GENESIS_HASH

        from services.mesh.mesh_merkle import merkle_root

        leaves = [e["event_id"] for e in self.events]
        root = merkle_root(leaves)
        return root or GENESIS_HASH

    def get_merkle_proofs(self, start_index: int, count: int) -> dict:
        """Return merkle proofs for a contiguous range of events."""
        leaves = [e["event_id"] for e in self.events]
        total = len(leaves)
        if total == 0:
            return {"root": GENESIS_HASH, "total": 0, "start": 0, "proofs": []}

        from services.mesh.mesh_merkle import build_merkle_levels, merkle_proof_from_levels

        start = max(0, start_index)
        end = min(total, start + max(0, count))
        levels = build_merkle_levels(leaves)
        root = levels[-1][0] if levels else GENESIS_HASH

        proofs = []
        for idx in range(start, end):
            proofs.append(
                {
                    "index": idx,
                    "leaf": leaves[idx],
                    "proof": merkle_proof_from_levels(levels, idx),
                }
            )

        return {"root": root, "total": total, "start": start, "proofs": proofs}

    def get_locator(self, max_entries: int = 32) -> list[str]:
        """Build a block locator for fork-aware sync."""
        if not self.events:
            return [GENESIS_HASH]

        locator: list[str] = []
        idx = len(self.events) - 1
        step = 1
        count = 0

        while idx >= 0 and len(locator) < max_entries - 1:
            locator.append(self.events[idx]["event_id"])
            if count >= 9:
                step *= 2
            idx -= step
            count += 1

        locator.append(GENESIS_HASH)
        return locator

    def get_events_after_locator(
        self, locator: list[str], limit: int = 100
    ) -> tuple[str, int, list[dict]]:
        """Find a common ancestor in the locator and return events after it."""
        if not locator:
            locator = [GENESIS_HASH]

        for hsh in locator:
            if hsh == GENESIS_HASH:
                return GENESIS_HASH, 0, self.events[:limit]
            idx = self.event_index.get(hsh)
            if idx is not None:
                start = idx + 1
                return hsh, start, self.events[start : start + limit]

        return "", -1, []

    def get_events_after(self, after_hash: str, limit: int = 100) -> list[dict]:
        """Get events after a given hash (for delta sync).

        If after_hash is GENESIS_HASH, returns from the beginning.
        """
        if after_hash == GENESIS_HASH:
            return self.events[:limit]

        # Find the event with this hash
        idx = self.event_index.get(after_hash)
        if idx is None:
            return []  # Hash not found — full sync needed

        return self.events[idx + 1 : idx + 1 + limit]


# ─── Module-level singleton ─────────────────────────────────────────────

infonet = Infonet()
gate_store = GateMessageStore(data_dir=str(GATE_STORE_DIR))

# Backwards-compatible alias so existing imports don't break
hashchain = infonet
