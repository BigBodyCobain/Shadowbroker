"""Metadata-minimized DM relay for request and shared mailboxes.

This relay never decrypts application payloads. In secure mode it keeps
pending ciphertext in memory only and persists just the minimum metadata
needed for continuity: accepted DH bundles, block lists, witness data,
and nonce replay windows.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.config import get_settings
from services.mesh.mesh_metrics import increment as metrics_inc
from services.mesh.mesh_wormhole_prekey import _validate_bundle_record
from services.mesh.mesh_secure_storage import read_secure_json, write_secure_json

TTL_SECONDS = 3600
EPOCH_SECONDS = 6 * 60 * 60
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RELAY_FILE = DATA_DIR / "dm_relay.json"
logger = logging.getLogger(__name__)


def _get_token_pepper() -> str:
    """Read token pepper lazily so auto-generated values from startup audit take effect."""
    pepper = os.environ.get("MESH_DM_TOKEN_PEPPER", "").strip()
    if not pepper:
        try:
            from services.config import get_settings
            from services.env_check import _ensure_dm_token_pepper

            pepper = _ensure_dm_token_pepper(get_settings())
        except Exception:
            pepper = os.environ.get("MESH_DM_TOKEN_PEPPER", "").strip()
    if not pepper:
        raise RuntimeError("MESH_DM_TOKEN_PEPPER is unavailable at runtime")
    return pepper


@dataclass
class DMMessage:
    sender_id: str
    ciphertext: str
    timestamp: float
    msg_id: str
    delivery_class: str
    sender_seal: str = ""
    relay_salt: str = ""
    sender_block_ref: str = ""
    payload_format: str = "dm1"
    session_welcome: str = ""


class DMRelay:
    """Relay for encrypted request/shared mailboxes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mailboxes: dict[str, list[DMMessage]] = defaultdict(list)
        self._dh_keys: dict[str, dict[str, Any]] = {}
        self._prekey_bundles: dict[str, dict[str, Any]] = {}
        self._mailbox_bindings: dict[str, dict[str, Any]] = defaultdict(dict)
        self._witnesses: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._blocks: dict[str, set[str]] = defaultdict(set)
        self._nonce_cache: OrderedDict[str, float] = OrderedDict()
        self._stats: dict[str, int] = {"messages_in_memory": 0}
        self._dirty = False
        self._save_timer: threading.Timer | None = None
        self._SAVE_INTERVAL = 5.0
        atexit.register(self._flush)
        self._load()

    def _settings(self):
        return get_settings()

    def _persist_spool_enabled(self) -> bool:
        return bool(self._settings().MESH_DM_PERSIST_SPOOL)

    def _request_mailbox_limit(self) -> int:
        return max(1, int(self._settings().MESH_DM_REQUEST_MAILBOX_LIMIT))

    def _shared_mailbox_limit(self) -> int:
        return max(1, int(self._settings().MESH_DM_SHARED_MAILBOX_LIMIT))

    def _self_mailbox_limit(self) -> int:
        return max(1, int(self._settings().MESH_DM_SELF_MAILBOX_LIMIT))

    def _nonce_ttl_seconds(self) -> int:
        return max(30, int(self._settings().MESH_DM_NONCE_TTL_S))

    def _nonce_cache_max_entries(self) -> int:
        return max(1, int(getattr(self._settings(), "MESH_DM_NONCE_CACHE_MAX", 4096)))

    def _pepper_token(self, token: str) -> str:
        material = token
        pepper = _get_token_pepper()
        if pepper:
            material = f"{pepper}|{token}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _sender_block_ref(self, sender_id: str) -> str:
        sender = str(sender_id or "").strip()
        if not sender:
            return ""
        return "ref:" + self._pepper_token(f"block|{sender}")

    def _canonical_blocked_id(self, blocked_id: str) -> str:
        blocked = str(blocked_id or "").strip()
        if not blocked:
            return ""
        if blocked.startswith("ref:"):
            return blocked
        return self._sender_block_ref(blocked)

    def _message_block_ref(self, message: DMMessage) -> str:
        block_ref = str(getattr(message, "sender_block_ref", "") or "").strip()
        if block_ref:
            return block_ref
        sender_id = str(message.sender_id or "").strip()
        if not sender_id or sender_id.startswith("sealed:") or sender_id.startswith("sender_token:"):
            return ""
        return self._sender_block_ref(sender_id)

    def _mailbox_key(self, mailbox_type: str, mailbox_value: str, epoch: int | None = None) -> str:
        if mailbox_type in {"self", "requests"}:
            bucket = self._epoch_bucket() if epoch is None else int(epoch)
            identifier = f"{mailbox_type}|{bucket}|{mailbox_value}"
        else:
            identifier = f"{mailbox_type}|{mailbox_value}"
        return self._pepper_token(identifier)

    def _hashed_mailbox_token(self, token: str) -> str:
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    def _remember_mailbox_binding(self, agent_id: str, mailbox_type: str, token: str) -> str:
        token_hash = self._hashed_mailbox_token(token)
        self._mailbox_bindings[str(agent_id or "").strip()][str(mailbox_type or "").strip().lower()] = {
            "token_hash": token_hash,
            "last_used": time.time(),
        }
        self._save()
        return token_hash

    def _bound_mailbox_key(self, agent_id: str, mailbox_type: str) -> str:
        entry = self._mailbox_bindings.get(str(agent_id or "").strip(), {}).get(
            str(mailbox_type or "").strip().lower(),
            "",
        )
        if isinstance(entry, dict):
            return str(entry.get("token_hash", "") or "")
        return str(entry or "")

    def _mailbox_keys_for_claim(self, agent_id: str, claim: dict[str, Any]) -> list[str]:
        claim_type = str(claim.get("type", "")).strip().lower()
        if claim_type == "shared":
            token = str(claim.get("token", "")).strip()
            if not token:
                metrics_inc("dm_claim_invalid")
                return []
            return [self._hashed_mailbox_token(token)]
        if claim_type == "requests":
            token = str(claim.get("token", "")).strip()
            if token:
                bound_key = self._remember_mailbox_binding(agent_id, "requests", token)
                epoch = self._epoch_bucket()
                return [
                    bound_key,
                    self._mailbox_key("requests", agent_id, epoch),
                    self._mailbox_key("requests", agent_id, epoch - 1),
                ]
            metrics_inc("dm_claim_invalid")
            return []
        if claim_type == "self":
            token = str(claim.get("token", "")).strip()
            if token:
                bound_key = self._remember_mailbox_binding(agent_id, "self", token)
                epoch = self._epoch_bucket()
                return [
                    bound_key,
                    self._mailbox_key("self", agent_id, epoch),
                    self._mailbox_key("self", agent_id, epoch - 1),
                ]
            metrics_inc("dm_claim_invalid")
            return []
        metrics_inc("dm_claim_invalid")
        return []

    def mailbox_key_for_delivery(
        self,
        *,
        recipient_id: str,
        delivery_class: str,
        recipient_token: str | None = None,
    ) -> str:
        delivery_class = str(delivery_class or "").strip().lower()
        if delivery_class == "request":
            bound_key = self._bound_mailbox_key(recipient_id, "requests")
            if bound_key:
                return bound_key
            return self._mailbox_key("requests", str(recipient_id or "").strip())
        if delivery_class == "shared":
            token = str(recipient_token or "").strip()
            if not token:
                raise ValueError("recipient_token required for shared delivery")
            return self._hashed_mailbox_token(token)
        raise ValueError("Unsupported delivery_class")

    def claim_mailbox_keys(self, agent_id: str, claims: list[dict[str, Any]]) -> list[str]:
        keys: list[str] = []
        for claim in claims[:32]:
            keys.extend(self._mailbox_keys_for_claim(agent_id, claim))
        return list(dict.fromkeys(keys))

    def _legacy_mailbox_token(self, agent_id: str, epoch: int) -> str:
        raw = f"sb_dm|{epoch}|{agent_id}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _legacy_token_candidates(self, agent_id: str) -> list[str]:
        epoch = self._epoch_bucket()
        raw = [self._legacy_mailbox_token(agent_id, epoch), self._legacy_mailbox_token(agent_id, epoch - 1)]
        peppered = [self._pepper_token(token) for token in raw]
        return list(dict.fromkeys(peppered + raw))

    def _save(self) -> None:
        """Mark dirty and schedule a coalesced disk write."""
        self._dirty = True
        if not RELAY_FILE.exists():
            self._flush()
            return
        with self._lock:
            if self._save_timer is None or not self._save_timer.is_alive():
                self._save_timer = threading.Timer(self._SAVE_INTERVAL, self._flush)
                self._save_timer.daemon = True
                self._save_timer.start()

    def _prune_stale_metadata(self) -> None:
        """Remove expired DH keys, prekey bundles, and mailbox bindings."""
        now = time.time()
        settings = self._settings()
        key_ttl = max(1, int(getattr(settings, "MESH_DM_KEY_TTL_DAYS", 30) or 30)) * 86400
        binding_ttl = max(1, int(getattr(settings, "MESH_DM_BINDING_TTL_DAYS", 7) or 7)) * 86400

        stale_keys = [
            aid for aid, entry in self._dh_keys.items()
            if (now - float(entry.get("timestamp", 0) or 0)) > key_ttl
        ]
        for aid in stale_keys:
            del self._dh_keys[aid]

        stale_bundles = [
            aid for aid, entry in self._prekey_bundles.items()
            if (now - float(entry.get("updated_at", entry.get("timestamp", 0)) or 0)) > key_ttl
        ]
        for aid in stale_bundles:
            del self._prekey_bundles[aid]

        stale_agents: list[str] = []
        for agent_id, kinds in self._mailbox_bindings.items():
            expired_kinds = [
                k for k, v in kinds.items()
                if isinstance(v, dict) and (now - float(v.get("last_used", 0) or 0)) > binding_ttl
            ]
            for k in expired_kinds:
                del kinds[k]
            if not kinds:
                stale_agents.append(agent_id)
        for agent_id in stale_agents:
            del self._mailbox_bindings[agent_id]

    def _metadata_persist_enabled(self) -> bool:
        return bool(getattr(self._settings(), "MESH_DM_METADATA_PERSIST", True))

    def _flush(self) -> None:
        """Actually write to disk (called by timer or atexit)."""
        if not self._dirty:
            return
        try:
            self._prune_stale_metadata()
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "saved_at": int(time.time()),
                "dh_keys": self._dh_keys,
                "prekey_bundles": self._prekey_bundles,
                "witnesses": self._witnesses,
                "blocks": {k: sorted(v) for k, v in self._blocks.items()},
                "nonce_cache": dict(self._nonce_cache),
                "stats": self._stats,
            }
            if self._metadata_persist_enabled():
                payload["mailbox_bindings"] = self._mailbox_bindings
            if self._persist_spool_enabled():
                payload["mailboxes"] = {
                    key: [m.__dict__ for m in msgs] for key, msgs in self._mailboxes.items()
                }
            write_secure_json(RELAY_FILE, payload)
            self._dirty = False
        except Exception:
            pass

    def _load(self) -> None:
        if not RELAY_FILE.exists():
            return
        try:
            data = read_secure_json(RELAY_FILE, lambda: {})
        except Exception:
            return
        if self._persist_spool_enabled():
            mailboxes = data.get("mailboxes", {})
            if isinstance(mailboxes, dict):
                for key, items in mailboxes.items():
                    if not isinstance(items, list):
                        continue
                    restored: list[DMMessage] = []
                    for item in items:
                        try:
                            restored.append(
                                DMMessage(
                                    sender_id=str(item.get("sender_id", "")),
                                    ciphertext=str(item.get("ciphertext", "")),
                                    timestamp=float(item.get("timestamp", 0)),
                                    msg_id=str(item.get("msg_id", "")),
                                    delivery_class=str(item.get("delivery_class", "shared")),
                                    sender_seal=str(item.get("sender_seal", "")),
                                    relay_salt=str(item.get("relay_salt", "") or ""),
                                    sender_block_ref=str(item.get("sender_block_ref", "") or ""),
                                    payload_format=str(item.get("payload_format", item.get("format", "dm1")) or "dm1"),
                                    session_welcome=str(item.get("session_welcome", "") or ""),
                                )
                            )
                        except Exception:
                            continue
                    for message in restored:
                        if not message.sender_block_ref:
                            message.sender_block_ref = self._message_block_ref(message)
                    if restored:
                        self._mailboxes[key] = restored
        dh_keys = data.get("dh_keys", {})
        if isinstance(dh_keys, dict):
            self._dh_keys = {str(k): dict(v) for k, v in dh_keys.items() if isinstance(v, dict)}
        prekey_bundles = data.get("prekey_bundles", {})
        if isinstance(prekey_bundles, dict):
            self._prekey_bundles = {
                str(k): dict(v) for k, v in prekey_bundles.items() if isinstance(v, dict)
            }
        mailbox_bindings = data.get("mailbox_bindings", {})
        if isinstance(mailbox_bindings, dict):
            self._mailbox_bindings = defaultdict(
                dict,
                {
                    str(agent_id): {
                        str(kind): str(token_hash)
                        for kind, token_hash in dict(bindings or {}).items()
                        if str(token_hash or "").strip()
                    }
                    for agent_id, bindings in mailbox_bindings.items()
                    if isinstance(bindings, dict)
                },
            )
        witnesses = data.get("witnesses", {})
        if isinstance(witnesses, dict):
            self._witnesses = defaultdict(
                list,
                {
                    str(k): list(v)
                    for k, v in witnesses.items()
                    if isinstance(v, list)
                },
            )
        blocks = data.get("blocks", {})
        if isinstance(blocks, dict):
            for key, values in blocks.items():
                if isinstance(values, list):
                    self._blocks[str(key)] = {
                        self._canonical_blocked_id(str(v))
                        for v in values
                        if str(v or "").strip()
                    }
        nonce_cache = data.get("nonce_cache", {})
        if isinstance(nonce_cache, dict):
            now = time.time()
            restored = sorted(
                (
                    (str(k), float(v))
                    for k, v in nonce_cache.items()
                    if float(v) > now
                ),
                key=lambda item: item[1],
            )
            self._nonce_cache = OrderedDict(restored)
        stats = data.get("stats", {})
        if isinstance(stats, dict):
            self._stats = {str(k): int(v) for k, v in stats.items() if isinstance(v, (int, float))}
        self._stats["messages_in_memory"] = sum(len(v) for v in self._mailboxes.values())

    def _bundle_fingerprint(
        self,
        *,
        dh_pub_key: str,
        dh_algo: str,
        public_key: str,
        public_key_algo: str,
        protocol_version: str,
    ) -> str:
        material = "|".join(
            [
                dh_pub_key,
                dh_algo,
                public_key,
                public_key_algo,
                protocol_version,
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def register_dh_key(
        self,
        agent_id: str,
        dh_pub_key: str,
        dh_algo: str,
        timestamp: int,
        signature: str,
        public_key: str,
        public_key_algo: str,
        protocol_version: str,
        sequence: int,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Register/update an agent's DH public key bundle with replay protection."""
        fingerprint = self._bundle_fingerprint(
            dh_pub_key=dh_pub_key,
            dh_algo=dh_algo,
            public_key=public_key,
            public_key_algo=public_key_algo,
            protocol_version=protocol_version,
        )
        with self._lock:
            existing = self._dh_keys.get(agent_id)
            if existing:
                existing_seq = int(existing.get("sequence", 0) or 0)
                existing_ts = int(existing.get("timestamp", 0) or 0)
                if sequence <= existing_seq:
                    metrics_inc("dm_key_replay")
                    return False, "DM key replay or rollback rejected", None
                if timestamp < existing_ts:
                    metrics_inc("dm_key_stale")
                    return False, "DM key timestamp is older than the current bundle", None
            self._dh_keys[agent_id] = {
                "dh_pub_key": dh_pub_key,
                "dh_algo": dh_algo,
                "timestamp": timestamp,
                "signature": signature,
                "public_key": public_key,
                "public_key_algo": public_key_algo,
                "protocol_version": protocol_version,
                "sequence": sequence,
                "bundle_fingerprint": fingerprint,
            }
            self._save()
        return True, "ok", {
            "accepted_sequence": sequence,
            "bundle_fingerprint": fingerprint,
        }

    def get_dh_key(self, agent_id: str) -> dict[str, Any] | None:
        return self._dh_keys.get(agent_id)

    def register_prekey_bundle(
        self,
        agent_id: str,
        bundle: dict[str, Any],
        signature: str,
        public_key: str,
        public_key_algo: str,
        protocol_version: str,
        sequence: int,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        ok, reason = _validate_bundle_record(
            {
                "bundle": bundle,
                "public_key": public_key,
                "agent_id": agent_id,
            }
        )
        if not ok:
            return False, reason, None
        with self._lock:
            existing = self._prekey_bundles.get(agent_id)
            if existing:
                existing_seq = int(existing.get("sequence", 0) or 0)
                if sequence <= existing_seq:
                    return False, "Prekey bundle replay or rollback rejected", None
            stored = {
                "bundle": dict(bundle or {}),
                "signature": signature,
                "public_key": public_key,
                "public_key_algo": public_key_algo,
                "protocol_version": protocol_version,
                "sequence": int(sequence),
                "updated_at": int(time.time()),
            }
            self._prekey_bundles[agent_id] = stored
        self._save()
        return True, "ok", {"accepted_sequence": int(sequence)}

    def get_prekey_bundle(self, agent_id: str) -> dict[str, Any] | None:
        stored = self._prekey_bundles.get(agent_id)
        if not stored:
            return None
        return dict(stored)

    def consume_one_time_prekey(self, agent_id: str) -> dict[str, Any] | None:
        """Atomically claim the next published one-time prekey for a peer bundle."""
        claimed: dict[str, Any] | None = None
        with self._lock:
            stored = self._prekey_bundles.get(agent_id)
            if not stored:
                return None
            bundle = dict(stored.get("bundle") or {})
            otks = list(bundle.get("one_time_prekeys") or [])
            if not otks:
                return dict(stored)
            claimed = dict(otks.pop(0) or {})
            bundle["one_time_prekeys"] = otks
            bundle["one_time_prekey_count"] = len(otks)
            stored = dict(stored)
            stored["bundle"] = bundle
            stored["updated_at"] = int(time.time())
            self._prekey_bundles[agent_id] = stored
        self._save()
        result = dict(stored)
        result["claimed_one_time_prekey"] = claimed
        return result

    def _prune_witnesses(self, target_id: str, ttl_days: int = 30) -> None:
        cutoff = time.time() - (ttl_days * 86400)
        self._witnesses[target_id] = [
            w for w in self._witnesses.get(target_id, []) if float(w.get("timestamp", 0)) >= cutoff
        ]
        if not self._witnesses[target_id]:
            del self._witnesses[target_id]

    def record_witness(
        self,
        witness_id: str,
        target_id: str,
        dh_pub_key: str,
        timestamp: int,
    ) -> tuple[bool, str]:
        if not witness_id or not target_id or not dh_pub_key:
            return False, "Missing witness_id, target_id, or dh_pub_key"
        if witness_id == target_id:
            return False, "Cannot witness yourself"
        with self._lock:
            self._prune_witnesses(target_id)
            entries = self._witnesses.get(target_id, [])
            for entry in entries:
                if entry.get("witness_id") == witness_id and entry.get("dh_pub_key") == dh_pub_key:
                    return False, "Duplicate witness"
            entries.append(
                {
                    "witness_id": witness_id,
                    "dh_pub_key": dh_pub_key,
                    "timestamp": int(timestamp),
                }
            )
            self._witnesses[target_id] = entries[-50:]
            self._save()
        return True, "ok"

    def get_witnesses(self, target_id: str, dh_pub_key: str | None = None, limit: int = 5) -> list[dict]:
        with self._lock:
            self._prune_witnesses(target_id)
            entries = list(self._witnesses.get(target_id, []))
        if dh_pub_key:
            entries = [e for e in entries if e.get("dh_pub_key") == dh_pub_key]
        entries = sorted(entries, key=lambda e: e.get("timestamp", 0), reverse=True)
        return entries[: max(1, limit)]

    def _epoch_bucket(self, ts: float | None = None) -> int:
        now = ts if ts is not None else time.time()
        return int(now // EPOCH_SECONDS)

    def _mailbox_limit_for_class(self, delivery_class: str) -> int:
        if delivery_class == "request":
            return self._request_mailbox_limit()
        if delivery_class == "shared":
            return self._shared_mailbox_limit()
        return self._self_mailbox_limit()

    def _cleanup_expired(self) -> bool:
        now = time.time()
        changed = False
        for mailbox_id in list(self._mailboxes):
            fresh = [m for m in self._mailboxes[mailbox_id] if now - m.timestamp < TTL_SECONDS]
            if len(fresh) != len(self._mailboxes[mailbox_id]):
                changed = True
            self._mailboxes[mailbox_id] = fresh
            if not self._mailboxes[mailbox_id]:
                del self._mailboxes[mailbox_id]
                changed = True
        self._stats["messages_in_memory"] = sum(len(v) for v in self._mailboxes.values())
        return changed

    def consume_nonce(self, agent_id: str, nonce: str, timestamp: int) -> tuple[bool, str]:
        nonce = str(nonce or "").strip()
        if not nonce:
            return False, "Missing nonce"
        now = time.time()
        with self._lock:
            self._nonce_cache = OrderedDict(
                (key, expiry)
                for key, expiry in self._nonce_cache.items()
                if float(expiry) > now
            )
            key = f"{agent_id}:{nonce}"
            if key in self._nonce_cache:
                metrics_inc("dm_nonce_replay")
                return False, "nonce replay detected"
            if len(self._nonce_cache) >= self._nonce_cache_max_entries():
                metrics_inc("dm_nonce_cache_full")
                return False, "nonce cache at capacity"
            expiry = max(now + self._nonce_ttl_seconds(), float(timestamp) + self._nonce_ttl_seconds())
            self._nonce_cache[key] = expiry
            self._nonce_cache.move_to_end(key)
            self._save()
        return True, "ok"

    def deposit(
        self,
        *,
        sender_id: str,
        raw_sender_id: str = "",
        recipient_id: str = "",
        ciphertext: str,
        msg_id: str = "",
        delivery_class: str,
        recipient_token: str | None = None,
        sender_seal: str = "",
        relay_salt: str = "",
        sender_token_hash: str = "",
        payload_format: str = "dm1",
        session_welcome: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            authority_sender = str(raw_sender_id or sender_id or "").strip()
            sender_block_ref = self._sender_block_ref(authority_sender)
            if recipient_id and sender_block_ref in self._blocks.get(recipient_id, set()):
                metrics_inc("dm_drop_blocked")
                return {"ok": False, "detail": "Recipient is not accepting your messages"}
            if len(ciphertext) > int(self._settings().MESH_DM_MAX_MSG_BYTES):
                metrics_inc("dm_drop_oversize")
                return {
                    "ok": False,
                    "detail": f"Message too large ({len(ciphertext)} > {int(self._settings().MESH_DM_MAX_MSG_BYTES)})",
                }
            self._cleanup_expired()
            if delivery_class == "request":
                mailbox_key = self._mailbox_key("requests", recipient_id)
            elif delivery_class == "shared":
                if not recipient_token:
                    metrics_inc("dm_claim_invalid")
                    return {"ok": False, "detail": "recipient_token required for shared delivery"}
                mailbox_key = self._hashed_mailbox_token(recipient_token)
            else:
                return {"ok": False, "detail": "Unsupported delivery_class"}
            if len(self._mailboxes[mailbox_key]) >= self._mailbox_limit_for_class(delivery_class):
                metrics_inc("dm_drop_full")
                return {"ok": False, "detail": "Recipient mailbox full"}
            if not msg_id:
                msg_id = f"dm_{int(time.time() * 1000)}_{secrets.token_hex(6)}"
            elif any(m.msg_id == msg_id for m in self._mailboxes[mailbox_key]):
                return {"ok": True, "msg_id": msg_id}
            relay_sender_id = (
                f"sender_token:{sender_token_hash}"
                if sender_token_hash and delivery_class == "shared"
                else sender_id
            )
            self._mailboxes[mailbox_key].append(
                DMMessage(
                    sender_id=relay_sender_id,
                    ciphertext=ciphertext,
                    timestamp=time.time(),
                    msg_id=msg_id,
                    delivery_class=delivery_class,
                    sender_seal=sender_seal,
                    sender_block_ref=sender_block_ref,
                    payload_format=str(payload_format or "dm1"),
                    session_welcome=str(session_welcome or ""),
                )
            )
            self._stats["messages_in_memory"] = sum(len(v) for v in self._mailboxes.values())
            self._save()
            return {"ok": True, "msg_id": msg_id}

    def is_blocked(self, recipient_id: str, sender_id: str) -> bool:
        with self._lock:
            blocked_ref = self._sender_block_ref(sender_id)
            if not recipient_id or not blocked_ref:
                return False
            return blocked_ref in self._blocks.get(recipient_id, set())

    def _collect_from_keys(self, keys: list[str], *, destructive: bool) -> list[dict[str, Any]]:
        messages: list[DMMessage] = []
        seen: set[str] = set()
        for key in keys:
            mailbox = self._mailboxes.pop(key, []) if destructive else list(self._mailboxes.get(key, []))
            for message in mailbox:
                if message.msg_id in seen:
                    continue
                seen.add(message.msg_id)
                messages.append(message)
        if destructive:
            self._stats["messages_in_memory"] = sum(len(v) for v in self._mailboxes.values())
            self._save()
        return [
            {
                "sender_id": message.sender_id,
                "ciphertext": message.ciphertext,
                "timestamp": message.timestamp,
                "msg_id": message.msg_id,
                "delivery_class": message.delivery_class,
                "sender_seal": message.sender_seal,
                "format": message.payload_format,
                "session_welcome": message.session_welcome,
            }
            for message in sorted(messages, key=lambda item: item.timestamp)
        ]

    def collect_claims(self, agent_id: str, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._lock:
            self._cleanup_expired()
            keys: list[str] = []
            for claim in claims[:32]:
                keys.extend(self._mailbox_keys_for_claim(agent_id, claim))
            return self._collect_from_keys(list(dict.fromkeys(keys)), destructive=True)

    def count_claims(self, agent_id: str, claims: list[dict[str, Any]]) -> int:
        with self._lock:
            self._cleanup_expired()
            keys: list[str] = []
            for claim in claims[:32]:
                keys.extend(self._mailbox_keys_for_claim(agent_id, claim))
            messages = self._collect_from_keys(list(dict.fromkeys(keys)), destructive=False)
            return len(messages)

    def claim_message_ids(self, agent_id: str, claims: list[dict[str, Any]]) -> set[str]:
        with self._lock:
            self._cleanup_expired()
            keys: list[str] = []
            for claim in claims[:32]:
                keys.extend(self._mailbox_keys_for_claim(agent_id, claim))
            messages = self._collect_from_keys(list(dict.fromkeys(keys)), destructive=False)
            return {
                str(message.get("msg_id", "") or "")
                for message in messages
                if str(message.get("msg_id", "") or "")
            }

    def collect_legacy(self, agent_id: str | None = None, agent_token: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._cleanup_expired()
            if not agent_token:
                return []
            keys = [self._pepper_token(agent_token), agent_token]
            return self._collect_from_keys(list(dict.fromkeys(keys)), destructive=True)

    def count_legacy(self, agent_id: str | None = None, agent_token: str | None = None) -> int:
        with self._lock:
            self._cleanup_expired()
            if not agent_token:
                return 0
            keys = [self._pepper_token(agent_token), agent_token]
            return len(self._collect_from_keys(list(dict.fromkeys(keys)), destructive=False))

    def block(self, agent_id: str, blocked_id: str) -> None:
        with self._lock:
            blocked_ref = self._canonical_blocked_id(blocked_id)
            if not blocked_ref:
                return
            self._blocks[agent_id].add(blocked_ref)
            purge_keys = self._legacy_token_candidates(agent_id)
            bound_request = self._bound_mailbox_key(agent_id, "requests")
            bound_self = self._bound_mailbox_key(agent_id, "self")
            if bound_request:
                purge_keys.append(bound_request)
            if bound_self:
                purge_keys.append(bound_self)
            purge_keys.extend(
                [
                    self._mailbox_key("self", agent_id),
                    self._mailbox_key("requests", agent_id),
                    self._mailbox_key("self", agent_id, self._epoch_bucket() - 1),
                    self._mailbox_key("requests", agent_id, self._epoch_bucket() - 1),
                ]
            )
            for key in set(purge_keys):
                if key in self._mailboxes:
                    self._mailboxes[key] = [
                        m for m in self._mailboxes[key] if self._message_block_ref(m) != blocked_ref
                    ]
            self._stats["messages_in_memory"] = sum(len(v) for v in self._mailboxes.values())
            self._save()

    def unblock(self, agent_id: str, blocked_id: str) -> None:
        with self._lock:
            blocked_ref = self._canonical_blocked_id(blocked_id)
            if not blocked_ref:
                return
            self._blocks[agent_id].discard(blocked_ref)
            self._save()


dm_relay = DMRelay()
