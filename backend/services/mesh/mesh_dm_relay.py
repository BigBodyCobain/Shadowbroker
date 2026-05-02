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
from services.mesh.mesh_wormhole_prekey import (
    _validate_bundle_record,
    transparency_fingerprint_for_bundle_record,
)
from services.mesh.mesh_secure_storage import read_secure_json, write_secure_json

TTL_SECONDS = 3600
EPOCH_SECONDS = 6 * 60 * 60
BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = BACKEND_DIR / "data"
DEFAULT_RELAY_FILE = DEFAULT_DATA_DIR / "dm_relay.json"
DATA_DIR = DEFAULT_DATA_DIR
RELAY_FILE = DEFAULT_RELAY_FILE
logger = logging.getLogger(__name__)


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


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
        self._nonce_caches: dict[str, OrderedDict[str, float]] = {}
        """Per-agent nonce replay caches — keyed by agent_id, values are OrderedDicts of nonce→expiry."""
        self._prekey_lookup_aliases: dict[str, dict[str, Any]] = {}
        """Invite-scoped lookup handle → agent_id for prekey bundle fetch without stable identity."""
        self._stats: dict[str, int] = {"messages_in_memory": 0}
        self._dirty = False
        self._save_timer: threading.Timer | None = None
        self._last_persist_error = ""
        self._SAVE_INTERVAL = 5.0
        atexit.register(self._flush)
        self._load()

    def _settings(self):
        return get_settings()

    def _persist_spool_enabled(self) -> bool:
        return bool(self._settings().MESH_DM_PERSIST_SPOOL)

    def _relay_file(self) -> Path:
        # Unit tests frequently monkeypatch the module-level relay file so each
        # relay instance stays isolated from the shared runtime spool path.
        module_override = Path(RELAY_FILE)
        if module_override != DEFAULT_RELAY_FILE:
            return module_override.expanduser().resolve()
        override = str(getattr(self._settings(), "MESH_DM_RELAY_FILE_PATH", "") or "").strip()
        if override:
            override_path = Path(override).expanduser()
            if not override_path.is_absolute():
                override_path = BACKEND_DIR / override_path
            return override_path.resolve()
        return RELAY_FILE

    def _relay_data_dir(self) -> Path:
        return self._relay_file().parent

    def _auto_reload_enabled(self) -> bool:
        if Path(RELAY_FILE) != DEFAULT_RELAY_FILE:
            return False
        return bool(getattr(self._settings(), "MESH_DM_RELAY_AUTO_RELOAD", False))

    def _refresh_from_shared_relay(self) -> None:
        if self._auto_reload_enabled():
            self._reload_snapshot_from_shared_relay()

    def _reload_snapshot_from_shared_relay(self) -> None:
        relay_file = self._relay_file()
        fresh_mailboxes: defaultdict[str, list[DMMessage]] = defaultdict(list)
        fresh_dh_keys: dict[str, dict[str, Any]] = {}
        fresh_prekey_bundles: dict[str, dict[str, Any]] = {}
        fresh_mailbox_bindings: defaultdict[str, dict[str, Any]] = defaultdict(dict)
        fresh_witnesses: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        fresh_blocks: defaultdict[str, set[str]] = defaultdict(set)
        fresh_nonce_caches: dict[str, OrderedDict[str, float]] = {}
        fresh_prekey_lookup_aliases: dict[str, dict[str, Any]] = {}
        fresh_stats: dict[str, int] = {"messages_in_memory": 0}
        current_mailboxes = defaultdict(list, {k: list(v) for k, v in self._mailboxes.items()})
        current_bindings = defaultdict(
            dict,
            {
                str(agent_id): {
                    str(kind): dict(entry)
                    for kind, entry in bindings.items()
                    if isinstance(entry, dict)
                }
                for agent_id, bindings in self._mailbox_bindings.items()
                if isinstance(bindings, dict)
            },
        )
        if not relay_file.exists():
            if not self._persist_spool_enabled():
                fresh_mailboxes = current_mailboxes
            if not self._metadata_persist_enabled():
                fresh_mailbox_bindings = current_bindings
            self._mailboxes = fresh_mailboxes
            self._dh_keys = fresh_dh_keys
            self._prekey_bundles = fresh_prekey_bundles
            self._mailbox_bindings = fresh_mailbox_bindings
            self._witnesses = fresh_witnesses
            self._blocks = fresh_blocks
            self._nonce_caches = fresh_nonce_caches
            self._prekey_lookup_aliases = fresh_prekey_lookup_aliases
            self._stats = fresh_stats
            return
        try:
            data = read_secure_json(relay_file, lambda: {})
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
                        fresh_mailboxes[str(key)] = restored
        else:
            if not self._persist_spool_enabled():
                fresh_mailboxes = current_mailboxes
        dh_keys = data.get("dh_keys", {})
        if isinstance(dh_keys, dict):
            fresh_dh_keys = {str(k): dict(v) for k, v in dh_keys.items() if isinstance(v, dict)}
        prekey_bundles = data.get("prekey_bundles", {})
        if isinstance(prekey_bundles, dict):
            fresh_prekey_bundles = {
                str(k): dict(v) for k, v in prekey_bundles.items() if isinstance(v, dict)
            }
        prekey_lookup_aliases = data.get("prekey_lookup_aliases", {})
        if isinstance(prekey_lookup_aliases, dict):
            for key, value in prekey_lookup_aliases.items():
                handle = str(key or "").strip()
                record = self._coerce_prekey_lookup_alias_record(value)
                if handle and record:
                    fresh_prekey_lookup_aliases[handle] = record
        now = time.time()
        mailbox_bindings = data.get("mailbox_bindings", {})
        if isinstance(mailbox_bindings, dict) and self._metadata_persist_enabled():
            for agent_id, bindings in mailbox_bindings.items():
                if not isinstance(bindings, dict):
                    continue
                restored_agent: dict[str, dict[str, Any]] = {}
                for kind, entry in bindings.items():
                    token_hash = ""
                    last_used = now
                    if isinstance(entry, dict):
                        token_hash = str(entry.get("token_hash", "") or "").strip()
                        last_used = float(entry.get("last_used", now) or now)
                    else:
                        token_hash = str(entry or "").strip()
                    if token_hash:
                        normalized = self._coerce_mailbox_binding_entry(
                            {
                                "token_hash": token_hash,
                                "bound_at": float(entry.get("bound_at", last_used) or last_used)
                                if isinstance(entry, dict)
                                else last_used,
                                "last_used": last_used,
                                "expires_at": float(entry.get("expires_at", 0) or 0)
                                if isinstance(entry, dict)
                                else 0,
                            },
                            now=now,
                        )
                        if normalized:
                            restored_agent[str(kind)] = normalized
                if restored_agent:
                    fresh_mailbox_bindings[str(agent_id)] = restored_agent
        elif not self._metadata_persist_enabled():
            fresh_mailbox_bindings = current_bindings
        witnesses = data.get("witnesses", {})
        if isinstance(witnesses, dict):
            fresh_witnesses = defaultdict(
                list,
                {str(k): list(v) for k, v in witnesses.items() if isinstance(v, list)},
            )
        blocks = data.get("blocks", {})
        if isinstance(blocks, dict):
            for key, values in blocks.items():
                if isinstance(values, list):
                    fresh_blocks[str(key)] = {
                        self._canonical_blocked_id(str(v))
                        for v in values
                        if str(v or "").strip()
                    }
        nonce_caches = data.get("nonce_caches", {})
        if isinstance(nonce_caches, dict) and nonce_caches:
            for aid, entries in nonce_caches.items():
                if not isinstance(entries, dict):
                    continue
                restored = sorted(
                    ((str(k), float(v)) for k, v in entries.items() if float(v) > now),
                    key=lambda item: item[1],
                )
                if restored:
                    fresh_nonce_caches[str(aid)] = OrderedDict(restored)
        else:
            nonce_cache = data.get("nonce_cache", {})
            if isinstance(nonce_cache, dict):
                for composite_key, expiry in nonce_cache.items():
                    if float(expiry) <= now:
                        continue
                    parts = str(composite_key).split(":", 1)
                    if len(parts) == 2:
                        aid, nonce_val = parts
                        if aid not in fresh_nonce_caches:
                            fresh_nonce_caches[aid] = OrderedDict()
                        fresh_nonce_caches[aid][nonce_val] = float(expiry)
        stats = data.get("stats", {})
        if isinstance(stats, dict):
            fresh_stats = {str(k): int(v) for k, v in stats.items() if isinstance(v, (int, float))}
        self._mailboxes = fresh_mailboxes
        self._dh_keys = fresh_dh_keys
        self._prekey_bundles = fresh_prekey_bundles
        self._mailbox_bindings = fresh_mailbox_bindings
        self._witnesses = fresh_witnesses
        self._blocks = fresh_blocks
        self._nonce_caches = fresh_nonce_caches
        self._prekey_lookup_aliases = fresh_prekey_lookup_aliases
        self._stats = fresh_stats
        self._stats["messages_in_memory"] = sum(len(v) for v in self._mailboxes.values())
        if self._prune_stale_metadata():
            self._dirty = True

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

    def _nonce_per_agent_max(self) -> int:
        return max(1, int(getattr(self._settings(), "MESH_DM_NONCE_PER_AGENT_MAX", 256)))

    def _dm_key_ttl_seconds(self) -> int:
        return max(1, int(getattr(self._settings(), "MESH_DM_KEY_TTL_DAYS", 30) or 30)) * 86400

    def _prekey_lookup_alias_ttl_seconds(self) -> int:
        return max(
            1,
            int(getattr(self._settings(), "MESH_DM_PREKEY_LOOKUP_ALIAS_TTL_DAYS", 14) or 14),
        ) * 86400

    def _witness_ttl_seconds(self) -> int:
        return max(1, int(getattr(self._settings(), "MESH_DM_WITNESS_TTL_DAYS", 14) or 14)) * 86400

    def _mailbox_binding_ttl_seconds(self) -> int:
        return max(1, int(getattr(self._settings(), "MESH_DM_BINDING_TTL_DAYS", 3) or 3)) * 86400

    def _mailbox_binding_idle_ttl_seconds(self) -> int:
        return min(self._mailbox_binding_ttl_seconds(), 12 * 60 * 60)

    def _mailbox_binding_refresh_after_seconds(self) -> int:
        return max(15 * 60, min(self._mailbox_binding_ttl_seconds(), 12 * 60 * 60))

    def _mailbox_binding_expires_at(self, entry: dict[str, Any]) -> float:
        bound_at = float(entry.get("bound_at", 0) or 0)
        last_used = float(entry.get("last_used", bound_at) or bound_at)
        if bound_at <= 0:
            return 0.0
        return min(
            bound_at + self._mailbox_binding_ttl_seconds(),
            last_used + self._mailbox_binding_idle_ttl_seconds(),
        )

    def _coerce_mailbox_binding_entry(self, entry: Any, *, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        token_hash = ""
        bound_at = current
        last_used = current
        if isinstance(entry, dict):
            token_hash = str(entry.get("token_hash", "") or "").strip()
            bound_at = float(entry.get("bound_at", entry.get("last_used", current)) or current)
            last_used = float(entry.get("last_used", bound_at) or bound_at)
        else:
            token_hash = str(entry or "").strip()
        if not token_hash:
            return {}
        normalized = {
            "token_hash": token_hash,
            "bound_at": bound_at,
            "last_used": last_used,
        }
        normalized["expires_at"] = self._mailbox_binding_expires_at(normalized)
        return normalized

    def _alias_updated_at_for_agent(self, agent_id: str) -> float:
        stored = self._prekey_bundles.get(str(agent_id or "").strip(), {})
        if isinstance(stored, dict):
            return float(stored.get("updated_at", stored.get("timestamp", time.time())) or time.time())
        return float(time.time())

    def _make_prekey_lookup_alias_record(
        self,
        agent_id: str,
        *,
        updated_at: float | None = None,
        expires_at: int = 0,
        max_uses: int = 0,
        use_count: int = 0,
        last_used_at: float = 0,
    ) -> dict[str, Any]:
        aid = str(agent_id or "").strip()
        if not aid:
            return {}
        if updated_at is None:
            updated_at = self._alias_updated_at_for_agent(aid)
        return {
            "agent_id": aid,
            "updated_at": float(updated_at or self._alias_updated_at_for_agent(aid)),
            "expires_at": max(0, int(expires_at or 0)),
            "max_uses": max(0, int(max_uses or 0)),
            "use_count": max(0, int(use_count or 0)),
            "last_used_at": float(last_used_at or 0),
        }

    def _coerce_prekey_lookup_alias_record(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            aid = str(value.get("agent_id", "") or "").strip()
            if not aid:
                return {}
            updated_at = float(
                value.get("updated_at", value.get("last_used", self._alias_updated_at_for_agent(aid)))
                or self._alias_updated_at_for_agent(aid)
            )
            return self._make_prekey_lookup_alias_record(
                aid,
                updated_at=updated_at,
                expires_at=int(value.get("expires_at", 0) or 0),
                max_uses=int(value.get("max_uses", 0) or 0),
                use_count=int(value.get("use_count", value.get("uses", 0)) or 0),
                last_used_at=float(value.get("last_used_at", value.get("last_used", 0)) or 0),
            )
        aid = str(value or "").strip()
        if not aid:
            return {}
        return self._make_prekey_lookup_alias_record(aid)

    def _resolve_prekey_lookup_alias(self, lookup_token: str) -> str:
        handle = str(lookup_token or "").strip()
        if not handle:
            return ""
        record = self._coerce_prekey_lookup_alias_record(self._prekey_lookup_aliases.get(handle, {}))
        if not record:
            return ""
        now = time.time()
        expires_at = int(record.get("expires_at", 0) or 0)
        max_uses = int(record.get("max_uses", 0) or 0)
        use_count = int(record.get("use_count", 0) or 0)
        if (expires_at > 0 and now > expires_at) or (max_uses > 0 and use_count >= max_uses):
            self._prekey_lookup_aliases.pop(handle, None)
            self._save()
            return ""
        updated = self._make_prekey_lookup_alias_record(
            str(record.get("agent_id", "") or "").strip(),
            updated_at=float(record.get("updated_at", self._alias_updated_at_for_agent(str(record.get("agent_id", "") or "").strip())) or now),
            expires_at=expires_at,
            max_uses=max_uses,
            use_count=use_count + 1,
            last_used_at=now,
        )
        self._prekey_lookup_aliases[handle] = updated
        self._save()
        try:
            from services.mesh.mesh_wormhole_identity import record_prekey_lookup_handle_use

            record_prekey_lookup_handle_use(handle, now=int(now))
        except Exception:
            pass
        return str(updated.get("agent_id", "") or "").strip()

    def _pepper_token(self, token: str) -> str:
        material = token
        pepper = _get_token_pepper()
        if pepper:
            material = f"{pepper}|{token}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _legacy_sender_block_ref(self, sender_id: str) -> str:
        sender = str(sender_id or "").strip()
        if not sender:
            return ""
        return "ref:" + self._pepper_token(f"block|{sender}")

    def _sender_block_scope(
        self,
        *,
        recipient_id: str = "",
        recipient_token: str = "",
        delivery_class: str = "",
    ) -> str:
        recipient = str(recipient_id or "").strip()
        if recipient:
            return f"recipient|{recipient}"
        token = str(recipient_token or "").strip()
        if token and str(delivery_class or "").strip().lower() == "shared":
            return f"shared|{self._hashed_mailbox_token(token)}"
        return ""

    def _sender_block_ref(self, sender_id: str, *, scope: str = "") -> str:
        sender = str(sender_id or "").strip()
        if not sender:
            return ""
        material = f"block|{scope}|{sender}" if scope else f"block|{sender}"
        return "ref:" + self._pepper_token(material)

    def _sender_block_refs(
        self,
        sender_id: str,
        *,
        recipient_id: str = "",
        recipient_token: str = "",
        delivery_class: str = "",
    ) -> set[str]:
        refs: set[str] = set()
        legacy = self._legacy_sender_block_ref(sender_id)
        if legacy:
            refs.add(legacy)
        scoped = self._sender_block_ref(
            sender_id,
            scope=self._sender_block_scope(
                recipient_id=recipient_id,
                recipient_token=recipient_token,
                delivery_class=delivery_class,
            ),
        )
        if scoped:
            refs.add(scoped)
        return refs

    def _canonical_blocked_id(self, blocked_id: str, *, scope: str = "") -> str:
        blocked = str(blocked_id or "").strip()
        if not blocked:
            return ""
        if blocked.startswith("ref:"):
            return blocked
        return self._sender_block_ref(blocked, scope=scope)

    def _message_block_ref(self, message: DMMessage) -> str:
        block_ref = str(getattr(message, "sender_block_ref", "") or "").strip()
        if block_ref:
            return block_ref
        sender_id = str(message.sender_id or "").strip()
        if not sender_id or sender_id.startswith("sealed:") or sender_id.startswith("sender_token:"):
            return ""
        return self._legacy_sender_block_ref(sender_id)

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
        if self._prune_stale_mailbox_bindings():
            self._save()
        now = time.time()
        agent_key = str(agent_id or "").strip()
        mailbox_key = str(mailbox_type or "").strip().lower()
        token_hash = self._hashed_mailbox_token(token)
        current = self._coerce_mailbox_binding_entry(
            self._mailbox_bindings.get(agent_key, {}).get(mailbox_key, {}),
            now=now,
        )
        refreshed = {
            "token_hash": token_hash,
            "bound_at": now,
            "last_used": now,
        }
        if current and str(current.get("token_hash", "") or "") == token_hash:
            refreshed["bound_at"] = float(current.get("bound_at", now) or now)
            if (now - refreshed["bound_at"]) >= self._mailbox_binding_refresh_after_seconds():
                refreshed["bound_at"] = now
        refreshed["expires_at"] = self._mailbox_binding_expires_at(refreshed)
        self._mailbox_bindings[agent_key][mailbox_key] = refreshed
        self._save()
        return token_hash

    def _bound_mailbox_key(self, agent_id: str, mailbox_type: str) -> str:
        if self._prune_stale_mailbox_bindings():
            self._save()
        agent_key = str(agent_id or "").strip()
        mailbox_key = str(mailbox_type or "").strip().lower()
        entry = self._mailbox_bindings.get(agent_key, {}).get(
            mailbox_key,
            {},
        )
        normalized = self._coerce_mailbox_binding_entry(entry)
        if normalized and normalized != entry:
            self._mailbox_bindings[agent_key][mailbox_key] = normalized
            self._save()
        return str(normalized.get("token_hash", "") or "")

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
                previous_bound = self._bound_mailbox_key(agent_id, "requests")
                bound_key = self._remember_mailbox_binding(agent_id, "requests", token)
                epoch = self._epoch_bucket()
                return [
                    key
                    for key in [
                    previous_bound,
                    bound_key,
                    self._mailbox_key("requests", agent_id, epoch),
                    self._mailbox_key("requests", agent_id, epoch - 1),
                    ]
                    if key
                ]
            metrics_inc("dm_claim_invalid")
            return []
        if claim_type == "self":
            token = str(claim.get("token", "")).strip()
            if token:
                previous_bound = self._bound_mailbox_key(agent_id, "self")
                bound_key = self._remember_mailbox_binding(agent_id, "self", token)
                epoch = self._epoch_bucket()
                return [
                    key
                    for key in [
                    previous_bound,
                    bound_key,
                    self._mailbox_key("self", agent_id, epoch),
                    self._mailbox_key("self", agent_id, epoch - 1),
                    ]
                    if key
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
        with self._lock:
            self._refresh_from_shared_relay()
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
        with self._lock:
            self._refresh_from_shared_relay()
            if self._prune_stale_mailbox_bindings():
                self._save()
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
        relay_file = self._relay_file()
        if self._auto_reload_enabled() or not relay_file.exists() or self._persist_failures_are_fatal():
            self._flush()
            return
        with self._lock:
            if self._save_timer is None or not self._save_timer.is_alive():
                self._save_timer = threading.Timer(self._SAVE_INTERVAL, self._flush)
                self._save_timer.daemon = True
                self._save_timer.start()

    def _persist_failures_are_fatal(self) -> bool:
        return bool(os.environ.get("PYTEST_CURRENT_TEST", "").strip())

    def _record_persist_failure(self, operation: str, exc: Exception) -> None:
        self._last_persist_error = f"{operation}:{type(exc).__name__}:{exc}"
        metrics_inc("dm_relay_persist_failure")
        logger.exception("dm relay %s failed for %s", operation, self._relay_file())

    def _prune_stale_metadata(self) -> bool:
        """Remove expired relay metadata that should not outlive its retention window."""
        now = time.time()
        key_ttl = self._dm_key_ttl_seconds()
        alias_ttl = self._prekey_lookup_alias_ttl_seconds()
        witness_ttl = self._witness_ttl_seconds()
        changed = False

        stale_keys = [
            aid for aid, entry in self._dh_keys.items()
            if (now - float(entry.get("timestamp", 0) or 0)) > key_ttl
        ]
        for aid in stale_keys:
            del self._dh_keys[aid]
            changed = True

        stale_bundles = [
            aid for aid, entry in self._prekey_bundles.items()
            if (now - float(entry.get("updated_at", entry.get("timestamp", 0)) or 0)) > key_ttl
        ]
        for aid in stale_bundles:
            del self._prekey_bundles[aid]
            changed = True

        stale_aliases: list[str] = []
        for alias, value in list(self._prekey_lookup_aliases.items()):
            record = self._coerce_prekey_lookup_alias_record(value)
            if not record:
                stale_aliases.append(alias)
                continue
            if self._prekey_lookup_aliases.get(alias) != record:
                self._prekey_lookup_aliases[alias] = record
                changed = True
            target = str(record.get("agent_id", "") or "").strip()
            updated_at = float(record.get("updated_at", self._alias_updated_at_for_agent(target)) or 0)
            expires_at = int(record.get("expires_at", 0) or 0)
            max_uses = int(record.get("max_uses", 0) or 0)
            use_count = int(record.get("use_count", 0) or 0)
            if (
                not target
                or target not in self._prekey_bundles
                or (now - updated_at) > alias_ttl
                or (expires_at > 0 and now > float(expires_at))
                or (max_uses > 0 and use_count >= max_uses)
            ):
                stale_aliases.append(alias)
        for alias in stale_aliases:
            del self._prekey_lookup_aliases[alias]
            changed = True

        for target_id in list(self._witnesses):
            fresh = [
                witness
                for witness in self._witnesses.get(target_id, [])
                if (now - float(witness.get("timestamp", 0) or 0)) <= witness_ttl
            ]
            if len(fresh) != len(self._witnesses.get(target_id, [])):
                changed = True
            if fresh:
                self._witnesses[target_id] = fresh
            else:
                del self._witnesses[target_id]

        if self._prune_stale_mailbox_bindings(now=now):
            changed = True
        return changed

    def _prune_stale_mailbox_bindings(self, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        changed = False
        stale_agents: list[str] = []
        for agent_id, kinds in self._mailbox_bindings.items():
            normalized_updates: dict[str, dict[str, Any]] = {}
            expired_kinds = [
                k
                for k, v in kinds.items()
                if not self._coerce_mailbox_binding_entry(v, now=current)
                or current > self._mailbox_binding_expires_at(
                    self._coerce_mailbox_binding_entry(v, now=current)
                )
            ]
            for kind, entry in list(kinds.items()):
                normalized = self._coerce_mailbox_binding_entry(entry, now=current)
                if normalized and normalized != entry:
                    normalized_updates[kind] = normalized
            for kind, normalized in normalized_updates.items():
                kinds[kind] = normalized
                changed = True
            for k in expired_kinds:
                del kinds[k]
                changed = True
            if not kinds:
                stale_agents.append(agent_id)
        for agent_id in stale_agents:
            del self._mailbox_bindings[agent_id]
            changed = True
        return changed

    def _metadata_persist_enabled(self) -> bool:
        settings = self._settings()
        return bool(getattr(settings, "MESH_DM_METADATA_PERSIST", False)) and bool(
            getattr(settings, "MESH_DM_METADATA_PERSIST_ACKNOWLEDGE", False)
        )

    def _flush(self) -> None:
        """Actually write to disk (called by timer or atexit)."""
        if not self._dirty:
            return
        try:
            self._prune_stale_metadata()
            relay_file = self._relay_file()
            self._relay_data_dir().mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "saved_at": int(time.time()),
                "dh_keys": self._dh_keys,
                "prekey_bundles": self._prekey_bundles,
                "prekey_lookup_aliases": self._prekey_lookup_aliases,
                "witnesses": self._witnesses,
                "blocks": {k: sorted(v) for k, v in self._blocks.items()},
                "nonce_caches": {aid: dict(c) for aid, c in self._nonce_caches.items()},
                "stats": self._stats,
            }
            if self._metadata_persist_enabled():
                payload["mailbox_bindings"] = {
                    agent_id: {
                        mailbox_type: {
                            "token_hash": str(entry.get("token_hash", "") or "").strip(),
                            "bound_at": float(entry.get("bound_at", 0) or 0),
                            "last_used": float(entry.get("last_used", 0) or 0),
                            "expires_at": float(entry.get("expires_at", 0) or 0),
                        }
                        for mailbox_type, entry in bindings.items()
                        if isinstance(entry, dict) and str(entry.get("token_hash", "") or "").strip()
                    }
                    for agent_id, bindings in self._mailbox_bindings.items()
                    if isinstance(bindings, dict)
                }
            if self._persist_spool_enabled():
                payload["mailboxes"] = {
                    key: [m.__dict__ for m in msgs] for key, msgs in self._mailboxes.items()
                }
            write_secure_json(relay_file, payload)
            self._dirty = False
            self._last_persist_error = ""
        except Exception as exc:
            self._record_persist_failure("flush", exc)
            if self._persist_failures_are_fatal():
                raise

    def _load(self) -> None:
        relay_file = self._relay_file()
        if not relay_file.exists():
            return
        try:
            data = read_secure_json(relay_file, lambda: {})
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
        prekey_lookup_aliases = data.get("prekey_lookup_aliases", {})
        if isinstance(prekey_lookup_aliases, dict):
            restored_aliases: dict[str, dict[str, Any]] = {}
            alias_records_migrated = False
            for key, value in prekey_lookup_aliases.items():
                handle = str(key or "").strip()
                record = self._coerce_prekey_lookup_alias_record(value)
                if not handle or not record:
                    continue
                restored_aliases[handle] = record
                if value != record:
                    alias_records_migrated = True
            self._prekey_lookup_aliases = restored_aliases
            if alias_records_migrated:
                self._dirty = True
        now = time.time()
        mailbox_bindings = data.get("mailbox_bindings", {})
        if isinstance(mailbox_bindings, dict):
            if self._metadata_persist_enabled():
                restored_bindings: dict[str, dict[str, dict[str, Any]]] = {}
                for agent_id, bindings in mailbox_bindings.items():
                    if not isinstance(bindings, dict):
                        continue
                    restored_agent: dict[str, dict[str, Any]] = {}
                    for kind, entry in bindings.items():
                        token_hash = ""
                        last_used = now
                        if isinstance(entry, dict):
                            token_hash = str(entry.get("token_hash", "") or "").strip()
                            last_used = float(entry.get("last_used", now) or now)
                        else:
                            token_hash = str(entry or "").strip()
                        if not token_hash:
                            continue
                        normalized = self._coerce_mailbox_binding_entry(
                            {
                                "token_hash": token_hash,
                                "bound_at": float(entry.get("bound_at", last_used) or last_used)
                                if isinstance(entry, dict)
                                else last_used,
                                "last_used": last_used,
                                "expires_at": float(entry.get("expires_at", 0) or 0)
                                if isinstance(entry, dict)
                                else 0,
                            },
                            now=now,
                        )
                        if normalized:
                            restored_agent[str(kind)] = normalized
                    if restored_agent:
                        restored_bindings[str(agent_id)] = restored_agent
                self._mailbox_bindings = defaultdict(dict, restored_bindings)
            elif mailbox_bindings:
                # Old relay files may still contain persisted mailbox bindings.
                # When metadata persistence is disabled we intentionally do not
                # restore them, and mark dirty so the next flush rewrites the
                # relay state without that graph metadata.
                self._dirty = True
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
        nonce_caches = data.get("nonce_caches", {})
        if isinstance(nonce_caches, dict) and nonce_caches:
            for aid, entries in nonce_caches.items():
                if not isinstance(entries, dict):
                    continue
                restored = sorted(
                    ((str(k), float(v)) for k, v in entries.items() if float(v) > now),
                    key=lambda item: item[1],
                )
                if restored:
                    self._nonce_caches[str(aid)] = OrderedDict(restored)
        else:
            # Backward compatibility: migrate flat nonce_cache → per-agent
            nonce_cache = data.get("nonce_cache", {})
            if isinstance(nonce_cache, dict):
                for composite_key, expiry in nonce_cache.items():
                    if float(expiry) <= now:
                        continue
                    parts = str(composite_key).split(":", 1)
                    if len(parts) == 2:
                        aid, nonce_val = parts
                        if aid not in self._nonce_caches:
                            self._nonce_caches[aid] = OrderedDict()
                        self._nonce_caches[aid][nonce_val] = float(expiry)
        stats = data.get("stats", {})
        if isinstance(stats, dict):
            self._stats = {str(k): int(v) for k, v in stats.items() if isinstance(v, (int, float))}
        self._stats["messages_in_memory"] = sum(len(v) for v in self._mailboxes.values())
        if self._prune_stale_metadata():
            self._dirty = True

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

    def _advance_prekey_transparency(
        self,
        *,
        agent_id: str,
        bundle: dict[str, Any],
        signature: str,
        public_key: str,
        public_key_algo: str,
        protocol_version: str,
        sequence: int,
        existing: dict[str, Any] | None,
    ) -> dict[str, Any]:
        previous_head = str((existing or {}).get("prekey_transparency_head", "") or "").strip().lower()
        previous_size = int((existing or {}).get("prekey_transparency_size", 0) or 0)
        publication_fingerprint = transparency_fingerprint_for_bundle_record(
            {
                "agent_id": agent_id,
                "bundle": bundle,
                "signature": signature,
                "public_key": public_key,
                "public_key_algo": public_key_algo,
                "protocol_version": protocol_version,
                "sequence": int(sequence),
            }
        )
        next_size = previous_size + 1
        head_payload = {
            "agent_id": agent_id,
            "sequence": int(sequence),
            "signed_at": int(bundle.get("signed_at", 0) or 0),
            "publication_fingerprint": publication_fingerprint,
            "previous_head": previous_head,
            "index": next_size,
        }
        head = hashlib.sha256(_stable_json(head_payload).encode("utf-8")).hexdigest()
        history = list((existing or {}).get("prekey_transparency_log") or [])
        history.append(
            {
                "index": next_size,
                "sequence": int(sequence),
                "signed_at": int(bundle.get("signed_at", 0) or 0),
                "publication_fingerprint": publication_fingerprint,
                "previous_head": previous_head,
                "head": head,
                "observed_at": int(time.time()),
            }
        )
        return {
            "prekey_transparency_head": head,
            "prekey_transparency_size": next_size,
            "prekey_transparency_fingerprint": publication_fingerprint,
            "prekey_transparency_log": history[-16:],
        }

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
            self._refresh_from_shared_relay()
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
        with self._lock:
            self._refresh_from_shared_relay()
            self._prune_stale_metadata()
            return self._dh_keys.get(agent_id)

    def get_dh_key_by_lookup(self, lookup_token: str) -> tuple[dict[str, Any] | None, str]:
        """Resolve a prekey lookup alias and return the DH key for the resolved agent."""
        with self._lock:
            self._refresh_from_shared_relay()
            self._prune_stale_metadata()
            resolved_id = self._resolve_prekey_lookup_alias(lookup_token)
            if not resolved_id:
                return None, ""
            stored = self._dh_keys.get(resolved_id)
            if not stored:
                return None, ""
            return dict(stored), resolved_id

    def register_prekey_bundle(
        self,
        agent_id: str,
        bundle: dict[str, Any],
        signature: str,
        public_key: str,
        public_key_algo: str,
        protocol_version: str,
        sequence: int,
        lookup_aliases: list[Any] | None = None,
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
            self._refresh_from_shared_relay()
            existing = self._prekey_bundles.get(agent_id)
            if existing:
                existing_seq = int(existing.get("sequence", 0) or 0)
                if sequence <= existing_seq:
                    return False, "Prekey bundle replay or rollback rejected", None
            transparency = self._advance_prekey_transparency(
                agent_id=agent_id,
                bundle=dict(bundle or {}),
                signature=signature,
                public_key=public_key,
                public_key_algo=public_key_algo,
                protocol_version=protocol_version,
                sequence=int(sequence),
                existing=existing,
            )
            stored = {
                "bundle": dict(bundle or {}),
                "signature": signature,
                "public_key": public_key,
                "public_key_algo": public_key_algo,
                "protocol_version": protocol_version,
                "sequence": int(sequence),
                "updated_at": int(time.time()),
                **transparency,
            }
            self._prekey_bundles[agent_id] = stored
            if lookup_aliases:
                alias_updated_at = float(stored.get("updated_at", time.time()) or time.time())
                for alias in lookup_aliases[:16]:
                    alias_record = self._coerce_prekey_lookup_alias_record(
                        {
                            "agent_id": agent_id,
                            **dict(alias),
                        }
                        if isinstance(alias, dict)
                        else self._make_prekey_lookup_alias_record(agent_id, updated_at=alias_updated_at)
                    )
                    handle = str(alias.get("handle", "") if isinstance(alias, dict) else alias or "").strip()
                    if handle:
                        self._prekey_lookup_aliases[handle] = self._make_prekey_lookup_alias_record(
                            agent_id,
                            updated_at=alias_updated_at,
                            expires_at=int(alias_record.get("expires_at", 0) or 0),
                            max_uses=int(alias_record.get("max_uses", 0) or 0),
                            use_count=int(alias_record.get("use_count", 0) or 0),
                            last_used_at=float(alias_record.get("last_used_at", 0) or 0),
                        )
        self._save()
        return True, "ok", {"accepted_sequence": int(sequence), **transparency}

    def get_prekey_bundle(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._refresh_from_shared_relay()
            self._prune_stale_metadata()
            stored = self._prekey_bundles.get(agent_id)
            if not stored:
                return None
            return dict(stored)

    def get_prekey_bundle_by_lookup(self, lookup_token: str) -> tuple[dict[str, Any] | None, str]:
        """Resolve a lookup alias to a prekey bundle. Returns (bundle, agent_id)."""
        with self._lock:
            self._refresh_from_shared_relay()
            self._prune_stale_metadata()
            resolved_id = self._resolve_prekey_lookup_alias(lookup_token)
            if not resolved_id:
                return None, ""
            stored = self._prekey_bundles.get(resolved_id)
            if not stored:
                return None, ""
            return dict(stored), resolved_id

    def register_prekey_lookup_alias(
        self,
        alias: str,
        agent_id: str,
        *,
        expires_at: int = 0,
        max_uses: int = 0,
        use_count: int = 0,
        last_used_at: int = 0,
    ) -> None:
        """Register a lookup alias for an agent's prekey bundle."""
        handle = str(alias or "").strip()
        aid = str(agent_id or "").strip()
        if handle and aid:
            with self._lock:
                self._refresh_from_shared_relay()
                self._prekey_lookup_aliases[handle] = self._make_prekey_lookup_alias_record(
                    aid,
                    expires_at=expires_at,
                    max_uses=max_uses,
                    use_count=use_count,
                    last_used_at=last_used_at,
                )
            self._save()

    def consume_one_time_prekey(self, agent_id: str) -> dict[str, Any] | None:
        """Atomically claim the next published one-time prekey for a peer bundle."""
        claimed: dict[str, Any] | None = None
        with self._lock:
            self._refresh_from_shared_relay()
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

    def _prune_witnesses(self, target_id: str) -> None:
        cutoff = time.time() - self._witness_ttl_seconds()
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
            self._refresh_from_shared_relay()
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
            self._refresh_from_shared_relay()
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

    def _total_nonce_count(self) -> int:
        return sum(len(c) for c in self._nonce_caches.values())

    def _trim_global_nonce_budget(self, *, preferred_agent_id: str = "") -> int:
        trimmed = 0
        max_entries = self._nonce_cache_max_entries()
        preferred_agent_id = str(preferred_agent_id or "").strip()
        while self._total_nonce_count() >= max_entries:
            oldest_choice: tuple[str, str, float] | None = None
            for aid, cache in self._nonce_caches.items():
                if not cache:
                    continue
                if preferred_agent_id and aid == preferred_agent_id and len(self._nonce_caches) > 1:
                    continue
                nonce_value, expiry = next(iter(cache.items()))
                if oldest_choice is None or float(expiry) < oldest_choice[2]:
                    oldest_choice = (aid, nonce_value, float(expiry))
            if oldest_choice is None and preferred_agent_id:
                for aid, cache in self._nonce_caches.items():
                    if not cache:
                        continue
                    nonce_value, expiry = next(iter(cache.items()))
                    if oldest_choice is None or float(expiry) < oldest_choice[2]:
                        oldest_choice = (aid, nonce_value, float(expiry))
            if oldest_choice is None:
                break
            aid, nonce_value, _expiry = oldest_choice
            cache = self._nonce_caches.get(aid)
            if not cache:
                continue
            cache.pop(nonce_value, None)
            if not cache:
                self._nonce_caches.pop(aid, None)
            trimmed += 1
        if trimmed:
            metrics_inc("dm_nonce_cache_trimmed")
        return trimmed

    def consume_nonce(self, agent_id: str, nonce: str, timestamp: int) -> tuple[bool, str]:
        nonce = str(nonce or "").strip()
        if not nonce:
            return False, "Missing nonce"
        agent_id = str(agent_id or "").strip()
        now = time.time()
        with self._lock:
            self._refresh_from_shared_relay()
            # Expire stale entries across all agents
            for aid in list(self._nonce_caches):
                cache = self._nonce_caches[aid]
                self._nonce_caches[aid] = OrderedDict(
                    (k, exp) for k, exp in cache.items() if float(exp) > now
                )
                if not self._nonce_caches[aid]:
                    del self._nonce_caches[aid]

            agent_cache = self._nonce_caches.get(agent_id)

            # Replay check
            if agent_cache and nonce in agent_cache:
                metrics_inc("dm_nonce_replay")
                return False, "nonce replay detected"

            # Per-agent capacity check
            per_agent_max = self._nonce_per_agent_max()
            if agent_cache and len(agent_cache) >= per_agent_max:
                metrics_inc("dm_nonce_cache_full")
                return False, "nonce cache at capacity"

            # Global capacity is a soft memory bound. Trim the oldest nonce
            # entries first so one busy agent cannot turn the global budget
            # into a cross-agent availability choke point.
            if self._total_nonce_count() >= self._nonce_cache_max_entries():
                self._trim_global_nonce_budget(preferred_agent_id=agent_id)

            expiry = max(now + self._nonce_ttl_seconds(), float(timestamp) + self._nonce_ttl_seconds())
            if agent_cache is None:
                agent_cache = OrderedDict()
                self._nonce_caches[agent_id] = agent_cache
            agent_cache[nonce] = expiry
            agent_cache.move_to_end(nonce)
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
            self._refresh_from_shared_relay()
            authority_sender = str(raw_sender_id or sender_id or "").strip()
            sender_block_ref = self._sender_block_ref(
                authority_sender,
                scope=self._sender_block_scope(
                    recipient_id=recipient_id,
                    recipient_token=str(recipient_token or ""),
                    delivery_class=delivery_class,
                ),
            )
            blocked_refs = self._sender_block_refs(
                authority_sender,
                recipient_id=recipient_id,
                recipient_token=str(recipient_token or ""),
                delivery_class=delivery_class,
            )
            if recipient_id and any(ref in self._blocks.get(recipient_id, set()) for ref in blocked_refs):
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
                if not sender_token_hash:
                    return {"ok": False, "detail": "sender_token required for request delivery"}
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
                if sender_token_hash
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
            self._refresh_from_shared_relay()
            if not recipient_id:
                return False
            blocked_refs = self._sender_block_refs(
                sender_id,
                recipient_id=recipient_id,
                delivery_class="request",
            )
            return any(ref in self._blocks.get(recipient_id, set()) for ref in blocked_refs)

    def _collect_from_keys(
        self, keys: list[str], *, destructive: bool, limit: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        messages: list[DMMessage] = []
        seen: set[str] = set()
        popped: dict[str, list[DMMessage]] = {}
        for key in keys:
            if destructive:
                raw = self._mailboxes.pop(key, [])
                popped[key] = raw
            else:
                raw = list(self._mailboxes.get(key, []))
            for message in raw:
                if message.msg_id in seen:
                    continue
                seen.add(message.msg_id)
                messages.append(message)
        sorted_messages = sorted(messages, key=lambda item: item.timestamp)
        has_more = False
        if limit > 0 and len(sorted_messages) > limit:
            has_more = True
            kept = sorted_messages[:limit]
            if destructive:
                kept_ids = {m.msg_id for m in kept}
                for key, original in popped.items():
                    remaining = [m for m in original if m.msg_id not in kept_ids]
                    if remaining:
                        self._mailboxes.setdefault(key, []).extend(remaining)
            sorted_messages = kept
        if destructive:
            self._stats["messages_in_memory"] = sum(len(v) for v in self._mailboxes.values())
            self._save()
        result = [
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
            for message in sorted_messages
        ]
        return result, has_more

    def collect_claims(
        self, agent_id: str, claims: list[dict[str, Any]], *, limit: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        with self._lock:
            self._refresh_from_shared_relay()
            self._cleanup_expired()
            keys: list[str] = []
            for claim in claims[:32]:
                keys.extend(self._mailbox_keys_for_claim(agent_id, claim))
            return self._collect_from_keys(list(dict.fromkeys(keys)), destructive=True, limit=limit)

    def count_claims(self, agent_id: str, claims: list[dict[str, Any]]) -> int:
        with self._lock:
            self._refresh_from_shared_relay()
            self._cleanup_expired()
            keys: list[str] = []
            for claim in claims[:32]:
                keys.extend(self._mailbox_keys_for_claim(agent_id, claim))
            messages, _ = self._collect_from_keys(list(dict.fromkeys(keys)), destructive=False)
            return len(messages)

    def claim_message_ids(self, agent_id: str, claims: list[dict[str, Any]]) -> set[str]:
        with self._lock:
            self._refresh_from_shared_relay()
            self._cleanup_expired()
            keys: list[str] = []
            for claim in claims[:32]:
                keys.extend(self._mailbox_keys_for_claim(agent_id, claim))
            messages, _ = self._collect_from_keys(list(dict.fromkeys(keys)), destructive=False)
            return {
                str(message.get("msg_id", "") or "")
                for message in messages
                if str(message.get("msg_id", "") or "")
            }

    def collect_legacy(
        self, agent_id: str | None = None, agent_token: str | None = None, *, limit: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        with self._lock:
            self._refresh_from_shared_relay()
            self._cleanup_expired()
            if not agent_token:
                return [], False
            keys = [self._pepper_token(agent_token), agent_token]
            return self._collect_from_keys(list(dict.fromkeys(keys)), destructive=True, limit=limit)

    def count_legacy(self, agent_id: str | None = None, agent_token: str | None = None) -> int:
        with self._lock:
            self._refresh_from_shared_relay()
            self._cleanup_expired()
            if not agent_token:
                return 0
            keys = [self._pepper_token(agent_token), agent_token]
            messages, _ = self._collect_from_keys(list(dict.fromkeys(keys)), destructive=False)
            return len(messages)

    def block(self, agent_id: str, blocked_id: str) -> None:
        with self._lock:
            self._refresh_from_shared_relay()
            blocked_ref = self._canonical_blocked_id(
                blocked_id,
                scope=self._sender_block_scope(recipient_id=agent_id, delivery_class="request"),
            )
            if not blocked_ref:
                return
            self._blocks[agent_id].add(blocked_ref)
            blocked_refs = {blocked_ref}
            blocked_label = str(blocked_id or "").strip()
            if blocked_label and not blocked_label.startswith("ref:"):
                blocked_refs.add(self._legacy_sender_block_ref(blocked_label))
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
                        m for m in self._mailboxes[key] if self._message_block_ref(m) not in blocked_refs
                    ]
            self._stats["messages_in_memory"] = sum(len(v) for v in self._mailboxes.values())
            self._save()

    def unblock(self, agent_id: str, blocked_id: str) -> None:
        with self._lock:
            self._refresh_from_shared_relay()
            blocked_ref = self._canonical_blocked_id(
                blocked_id,
                scope=self._sender_block_scope(recipient_id=agent_id, delivery_class="request"),
            )
            if not blocked_ref:
                return
            self._blocks[agent_id].discard(blocked_ref)
            blocked_label = str(blocked_id or "").strip()
            if blocked_label and not blocked_label.startswith("ref:"):
                self._blocks[agent_id].discard(self._legacy_sender_block_ref(blocked_label))
            self._save()


dm_relay = DMRelay()
