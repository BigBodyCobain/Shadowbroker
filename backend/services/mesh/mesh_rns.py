"""Reticulum (RNS) bridge for Infonet event propagation.

Backend-hosted: the API server runs a Reticulum node and gossips signed events.
This module is optional and safely no-ops if Reticulum isn't installed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from services.config import get_settings
from services.mesh.mesh_ibf import IBLT, build_iblt, minhash_sketch, minhash_similarity
from services.wormhole_settings import read_wormhole_settings

logger = logging.getLogger("services.mesh_rns")


def _safe_int(val, default=0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _blind_mailbox_key(mailbox_key: str | bytes | None) -> str:
    if isinstance(mailbox_key, bytes):
        key_bytes = mailbox_key
    else:
        key_bytes = str(mailbox_key or "").encode("utf-8")
    if not key_bytes:
        return ""
    return hmac.new(key_bytes, b"rns-mailbox-blind-v1", hashlib.sha256).hexdigest()


@dataclass
class RNSMessage:
    msg_type: str
    body: dict[str, Any]
    meta: dict[str, Any]

    def encode(self) -> bytes:
        return json.dumps(
            {"type": self.msg_type, "body": self.body, "meta": self.meta},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


class RNSBridge:
    def __init__(self) -> None:
        self._enabled = False
        self._ready = False
        self._lock = threading.Lock()
        self._dedupe: dict[str, float] = {}
        self._last_churn = 0.0
        self._active_peers: list[str] = []
        self._reticulum = None
        self._identity = None
        self._destination = None
        self._destinations_extra: list[dict[str, Any]] = []
        self._destination_created = 0.0
        self._last_identity_rotate = 0.0
        self._last_ibf_sync = 0.0
        self._ibf_thread: threading.Thread | None = None
        self._peer_stats: dict[str, dict[str, float]] = {}
        self._peer_lock = threading.Lock()
        self._shard_cache: dict[str, dict[str, Any]] = {}
        self._shard_lock = threading.Lock()
        self._privacy_cache: dict[str, Any] = {"value": "default", "ts": 0.0}
        self._batch_lock = threading.Lock()
        self._batch_queue: list[dict] = []
        self._batch_timer: threading.Timer | None = None
        self._cover_thread: threading.Thread | None = None
        self._pending_sync: dict[str, dict[str, Any]] = {}
        self._sync_lock = threading.Lock()
        self._ibf_lock = threading.Lock()
        self._ibf_fail_count = 0
        self._ibf_cooldown_until = 0.0
        self._dedupe_lock = threading.Lock()
        self._dm_lock = threading.Lock()
        self._dm_mailboxes: dict[str, list[dict[str, Any]]] = {}

    def enabled(self) -> bool:
        return self._enabled and self._ready

    def status(self) -> dict:
        settings = get_settings()
        dest_age = 0
        if self._destination_created:
            dest_age = max(0, int(time.time() - self._destination_created))
        cooldown_remaining = 0
        if self._ibf_cooldown_until:
            cooldown_remaining = max(0, int(self._ibf_cooldown_until - time.time()))
        return {
            "enabled": bool(self._enabled),
            "ready": bool(self._ready),
            "local_hash": self._local_hash(),
            "configured_peers": len(self._parse_peers()),
            "active_peers": len(self._active_peers),
            "dandelion_hops": settings.MESH_RNS_DANDELION_HOPS,
            "ibf_interval_s": settings.MESH_RNS_IBF_INTERVAL_S,
            "ibf_cooldown_s": cooldown_remaining,
            "session_rotate_s": self._session_rotate_interval(),
            "destination_age_s": dest_age,
            "session_identities": len(self._destinations_extra) + (1 if self._destination else 0),
            "private_dm_direct_ready": bool(self.enabled() and (self._active_peers or self._parse_peers())),
        }

    def start(self) -> None:
        settings = get_settings()
        if not settings.MESH_RNS_ENABLED:
            return
        try:
            import RNS  # type: ignore
        except Exception as exc:
            logger.warning(f"RNS disabled: Reticulum import failed ({exc})")
            return

        with self._lock:
            if self._ready:
                return
            try:
                self._reticulum = RNS.Reticulum()
                identity = None
                if settings.MESH_RNS_IDENTITY_PATH:
                    try:
                        identity = RNS.Identity.from_file(settings.MESH_RNS_IDENTITY_PATH)
                    except Exception as exc:
                        logger.warning(f"RNS identity load failed: {exc}")
                if identity is None:
                    identity = RNS.Identity()
                    if settings.MESH_RNS_IDENTITY_PATH:
                        try:
                            identity.to_file(settings.MESH_RNS_IDENTITY_PATH)
                        except Exception as exc:
                            logger.warning(f"RNS identity save failed: {exc}")

                self._identity = identity
                self._destination = self._create_destination(identity)
                now = time.time()
                self._destination_created = now
                self._last_identity_rotate = now
                self._destinations_extra = []

                self._enabled = True
                self._ready = True
                logger.info("RNS bridge started")

                if settings.MESH_RNS_IBF_INTERVAL_S > 0:
                    self._ibf_thread = threading.Thread(target=self._ibf_sync_loop, daemon=True)
                    self._ibf_thread.start()
                if self._cover_thread is None:
                    self._cover_thread = threading.Thread(target=self._cover_loop, daemon=True)
                    self._cover_thread.start()
            except Exception as exc:
                logger.warning(f"RNS disabled: init failed ({exc})")
                self._enabled = False
                self._ready = False

    def _prune_dedupe(self) -> None:
        cutoff = time.time() - 300
        with self._dedupe_lock:
            for key, ts in list(self._dedupe.items()):
                if ts < cutoff:
                    del self._dedupe[key]

    def _session_rotate_interval(self) -> int:
        settings = get_settings()
        interval = int(settings.MESH_RNS_SESSION_ROTATE_S or 0)
        if self._is_high_privacy() and interval <= 0:
            interval = 600
        return max(0, int(interval))

    def _rotation_enabled(self) -> bool:
        settings = get_settings()
        if settings.MESH_RNS_IDENTITY_PATH:
            return False
        return self._session_rotate_interval() > 0

    def _create_destination(self, identity: Any) -> Any:
        settings = get_settings()
        import RNS  # type: ignore

        destination = RNS.Destination(
            identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            settings.MESH_RNS_APP_NAME,
            settings.MESH_RNS_ASPECT,
        )
        callback = getattr(destination, "set_packet_callback", None)
        if callable(callback):
            callback(self._on_packet)
        else:
            logger.warning("RNS destination has no packet callback; inbound disabled")
        return destination

    def _prune_rotated_destinations(self, interval: int | None = None) -> None:
        if not self._destinations_extra:
            return
        settings = get_settings()
        interval = self._session_rotate_interval() if interval is None else int(interval)
        grace = max(
            120,
            int(interval) * 2,
            int(settings.MESH_RNS_IBF_QUORUM_TIMEOUT_S or 0) * 2,
        )
        cutoff = time.time() - grace
        self._destinations_extra = [
            entry for entry in self._destinations_extra if entry.get("created", 0) >= cutoff
        ]

    def _maybe_rotate_session(self, force: bool = False) -> None:
        if not self.enabled():
            return
        if not self._rotation_enabled():
            return
        interval = self._session_rotate_interval()
        if interval <= 0:
            return
        now = time.time()
        if not force and (now - self._last_identity_rotate) < interval:
            return
        try:
            import RNS  # type: ignore
        except Exception:
            return
        if self._destination is not None:
            self._destinations_extra.append(
                {"dest": self._destination, "created": self._destination_created or now}
            )
        identity = RNS.Identity()
        try:
            destination = self._create_destination(identity)
        except Exception as exc:
            logger.warning(f"RNS session rotate failed: {exc}")
            return
        self._identity = identity
        self._destination = destination
        self._destination_created = now
        self._last_identity_rotate = now
        self._prune_rotated_destinations(interval)
        logger.info("RNS session identity rotated")

    def _privacy_profile(self) -> str:
        now = time.time()
        if now - float(self._privacy_cache.get("ts", 0)) > 5:
            try:
                data = read_wormhole_settings()
                profile = str(data.get("privacy_profile", "default") or "default").lower()
            except Exception:
                profile = "default"
            self._privacy_cache = {"value": profile, "ts": now}
        return str(self._privacy_cache.get("value", "default"))

    def _is_high_privacy(self) -> bool:
        return self._privacy_profile() == "high"

    def _prune_shards(self) -> None:
        ttl = max(5, int(get_settings().MESH_RNS_SHARD_TTL_S))
        cutoff = time.time() - ttl
        with self._shard_lock:
            for shard_id, entry in list(self._shard_cache.items()):
                if entry.get("created", 0) < cutoff:
                    del self._shard_cache[shard_id]

    def _prune_sync_rounds(self) -> None:
        settings = get_settings()
        timeout = int(settings.MESH_RNS_IBF_QUORUM_TIMEOUT_S or 0)
        if timeout <= 0:
            return
        timeout = max(3, timeout)
        now = time.time()
        merged_sets: list[list[dict]] = []
        with self._sync_lock:
            for sync_id, entry in list(self._pending_sync.items()):
                if now - float(entry.get("created", now)) < timeout:
                    continue
                # Fallback: choose the largest agreement bucket, if any
                buckets = entry.get("responses", {})
                best_hash = ""
                best_count = 0
                for head_hash, bucket in buckets.items():
                    count = int(bucket.get("count", 0) or 0)
                    if count > best_count:
                        best_count = count
                        best_hash = head_hash
                if best_hash:
                    merged = self._merge_bucket_events(buckets.get(best_hash, {}))
                    if merged:
                        merged_sets.append(merged)
                del self._pending_sync[sync_id]
        for merged in merged_sets:
            self._ingest_ordered(merged)

    def _ibf_in_cooldown(self) -> bool:
        with self._ibf_lock:
            return time.time() < self._ibf_cooldown_until

    def _note_ibf_failure(self) -> None:
        settings = get_settings()
        threshold = int(settings.MESH_RNS_IBF_FAIL_THRESHOLD or 0)
        cooldown = int(settings.MESH_RNS_IBF_COOLDOWN_S or 0)
        if threshold <= 0 or cooldown <= 0:
            return
        with self._ibf_lock:
            self._ibf_fail_count += 1
            if self._ibf_fail_count >= threshold:
                self._ibf_cooldown_until = time.time() + cooldown
                self._ibf_fail_count = 0
        try:
            from services.mesh.mesh_metrics import increment as metrics_inc

            metrics_inc("ibf_sync_failure")
        except Exception:
            pass

    def _note_ibf_success(self) -> None:
        with self._ibf_lock:
            self._ibf_fail_count = 0

    @staticmethod
    def _xor_bytes(a: bytes, b: bytes) -> bytes:
        return bytes(x ^ y for x, y in zip(a, b))

    def _rs_parity_shards(self, data: list[bytes], parity_shards: int) -> list[bytes] | None:
        try:
            import reedsolo  # type: ignore
        except Exception:
            return None
        if parity_shards <= 0 or not data:
            return []
        data_shards = len(data)
        if data_shards + parity_shards > 255:
            logger.warning("RNS RS FEC requires data+parity <= 255; falling back to XOR")
            return None
        try:
            rsc = reedsolo.RSCodec(parity_shards)
        except Exception:
            return None
        shard_size = len(data[0])
        parity = [bytearray(shard_size) for _ in range(parity_shards)]
        for pos in range(shard_size):
            row = bytes(chunk[pos] for chunk in data)
            encoded = rsc.encode(row)
            parity_bytes = encoded[-parity_shards:]
            for p in range(parity_shards):
                parity[p][pos] = parity_bytes[p]
        return [bytes(p) for p in parity]

    def _rs_recover_missing(
        self,
        data_map: dict[int, bytes],
        parity_map: dict[int, bytes],
        data_shards: int,
        parity_shards: int,
        shard_size: int,
    ) -> dict[int, bytes] | None:
        try:
            import reedsolo  # type: ignore
        except Exception:
            return None
        missing = [i for i in range(data_shards) if i not in data_map]
        if not missing or len(missing) > parity_shards:
            return None
        total = data_shards + parity_shards
        if total > 255:
            return None
        try:
            rsc = reedsolo.RSCodec(parity_shards)
        except Exception:
            return None
        recovered: dict[int, bytearray] = {idx: bytearray(shard_size) for idx in missing}
        for pos in range(shard_size):
            codeword = bytearray(total)
            erasures: list[int] = []
            for idx in range(total):
                if idx < data_shards:
                    if idx in data_map:
                        codeword[idx] = data_map[idx][pos]
                    else:
                        codeword[idx] = 0
                        erasures.append(idx)
                else:
                    if idx in parity_map:
                        codeword[idx] = parity_map[idx][pos]
                    else:
                        codeword[idx] = 0
                        erasures.append(idx)
            if len(erasures) > parity_shards:
                return None
            decoded, _ecc, _err = rsc.decode(bytes(codeword), erase_pos=erasures)
            for shard_idx in missing:
                recovered[shard_idx][pos] = decoded[shard_idx]
        return {idx: bytes(buf) for idx, buf in recovered.items()}

    def _split_payload(self, payload: bytes, data_shards: int) -> tuple[list[bytes], int]:
        if data_shards <= 0:
            return [payload], len(payload)
        total_len = len(payload)
        shard_size = int(math.ceil(total_len / float(data_shards)))
        shards: list[bytes] = []
        for idx in range(data_shards):
            start = idx * shard_size
            end = start + shard_size
            chunk = payload[start:end]
            if len(chunk) < shard_size:
                chunk = chunk + b"\x00" * (shard_size - len(chunk))
            shards.append(chunk)
        return shards, total_len

    def _send_sharded_payload(self, payload: bytes, message_id: str) -> bool:
        settings = get_settings()
        data_shards = max(1, int(settings.MESH_RNS_SHARD_DATA_SHARDS))
        parity_shards = max(0, int(settings.MESH_RNS_SHARD_PARITY_SHARDS))
        fec = str(settings.MESH_RNS_FEC_CODEC or "xor").lower()
        if fec not in ("xor", "rs"):
            fec = "xor"
        if self._is_high_privacy() and fec == "xor":
            fec = "rs"
        if fec == "xor" and parity_shards > 1:
            parity_shards = 1
        payload_len = len(payload)
        if payload_len <= 1024:
            return False
        if payload_len <= 4096:
            data_shards = min(data_shards, 2) if data_shards else 2
            parity_shards = min(max(parity_shards, 1), 2)
        peers = self._active_peers or self._select_peers(self._parse_peers())
        if not peers:
            return False
        import random

        peers = list(peers)
        random.shuffle(peers)

        data, total_len = self._split_payload(payload, data_shards)
        shard_size = len(data[0]) if data else len(payload)
        parity_blobs: list[bytes] = []
        if parity_shards > 0 and data:
            if fec == "rs":
                parity_blobs = self._rs_parity_shards(data, parity_shards) or []
                if len(parity_blobs) != parity_shards:
                    fec = "xor"
                    parity_blobs = []
            if fec == "xor":
                parity_blob = data[0]
                for chunk in data[1:]:
                    parity_blob = self._xor_bytes(parity_blob, chunk)
                parity_blobs = [parity_blob]

        shard_id = uuid.uuid4().hex
        total = data_shards + len(parity_blobs)
        shard_messages: list[bytes] = []

        for idx, chunk in enumerate(data):
            body = {
                "shard_id": shard_id,
                "index": idx,
                "total": total,
                "data_shards": data_shards,
                "parity_shards": len(parity_blobs),
                "size": shard_size,
                "length": total_len,
                "parity": False,
                "fec": fec,
                "data": base64.b64encode(chunk).decode("ascii"),
            }
            shard_messages.append(
                RNSMessage(
                    msg_type="infonet_shard",
                    body=body,
                    meta={"message_id": f"shard:{shard_id}:{idx}", "ts": int(time.time())},
                ).encode()
            )

        for p, parity_blob in enumerate(parity_blobs):
            idx = data_shards + p
            body = {
                "shard_id": shard_id,
                "index": idx,
                "total": total,
                "data_shards": data_shards,
                "parity_shards": len(parity_blobs),
                "size": shard_size,
                "length": total_len,
                "parity": True,
                "fec": fec,
                "data": base64.b64encode(parity_blob).decode("ascii"),
            }
            shard_messages.append(
                RNSMessage(
                    msg_type="infonet_shard",
                    body=body,
                    meta={"message_id": f"shard:{shard_id}:{idx}", "ts": int(time.time())},
                ).encode()
            )

        random.shuffle(shard_messages)
        if any(len(msg) > settings.MESH_RNS_MAX_PAYLOAD for msg in shard_messages):
            logger.warning("RNS shard payload too large; falling back to direct send")
            return False

        for i, msg in enumerate(shard_messages):
            peer = peers[i % len(peers)]
            self._send_to_peer(peer, msg)
        return True

    def _seen(self, message_id: str) -> bool:
        self._prune_dedupe()
        with self._dedupe_lock:
            if message_id in self._dedupe:
                return True
            self._dedupe[message_id] = time.time()
            return False

    def _parse_peers(self) -> list[str]:
        settings = get_settings()
        raw = settings.MESH_RNS_PEERS or ""
        peers = [p.strip().lower() for p in raw.split(",") if p.strip()]
        return peers[: settings.MESH_RNS_MAX_PEERS]

    def _peer_bucket(self, peer_hash: str) -> str:
        prefix_len = max(1, int(get_settings().MESH_RNS_PEER_BUCKET_PREFIX))
        return peer_hash[:prefix_len]

    def _peer_in_cooldown(self, peer_hash: str) -> bool:
        settings = get_settings()
        with self._peer_lock:
            stats = self._peer_stats.get(peer_hash)
        if not stats:
            return False
        fails = int(stats.get("fail", 0))
        last_fail = float(stats.get("last_fail", 0))
        if fails < settings.MESH_RNS_PEER_FAIL_THRESHOLD:
            return False
        return (time.time() - last_fail) < settings.MESH_RNS_PEER_COOLDOWN_S

    def _select_peers(self, peers: list[str]) -> list[str]:
        settings = get_settings()
        if not peers:
            return []
        import random

        random.shuffle(peers)
        buckets: dict[str, int] = {}
        selected: list[str] = []
        for peer in peers:
            if self._peer_in_cooldown(peer):
                continue
            bucket = self._peer_bucket(peer)
            if buckets.get(bucket, 0) >= settings.MESH_RNS_MAX_PEERS_PER_BUCKET:
                continue
            buckets[bucket] = buckets.get(bucket, 0) + 1
            selected.append(peer)
            if len(selected) >= settings.MESH_RNS_MAX_PEERS:
                break
        return selected

    def _maybe_churn(self) -> None:
        settings = get_settings()
        if not settings.MESH_RNS_CHURN_INTERVAL_S:
            return
        now = time.time()
        interval = settings.MESH_RNS_CHURN_INTERVAL_S
        if self._is_high_privacy():
            interval = min(interval, 60)
        if now - self._last_churn < interval:
            return
        peers = self._parse_peers()
        self._active_peers = self._select_peers(peers)
        self._last_churn = now

    def _pick_stem_peer(self) -> str | None:
        self._maybe_churn()
        peers = self._active_peers or self._select_peers(self._parse_peers())
        if not peers:
            return None
        import random

        return random.choice(peers)

    def _dandelion_hops(self) -> int:
        settings = get_settings()
        base = max(1, int(settings.MESH_RNS_DANDELION_HOPS))
        if not self._is_high_privacy():
            return base
        peer_count = len(self._active_peers) or len(self._parse_peers())
        if peer_count <= 3:
            return min(base, 1)
        if peer_count <= 7:
            return min(base, 2) if base >= 2 else base
        return base

    def _send_to_peer(self, peer_hash: str, payload: bytes) -> bool:
        settings = get_settings()
        if not self._reticulum or not self._enabled:
            return False
        try:
            import RNS  # type: ignore

            dest = RNS.Destination(
                None,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                settings.MESH_RNS_APP_NAME,
                settings.MESH_RNS_ASPECT,
            )
            # Best-effort: assign destination hash directly if supported
            try:
                dest.hash = bytes.fromhex(peer_hash)
            except Exception:
                pass
            packet = RNS.Packet(dest, payload)
            packet.send()
            with self._peer_lock:
                stats = self._peer_stats.get(peer_hash) or {
                    "fail": 0,
                    "success": 0,
                    "last_fail": 0,
                }
                stats["success"] = float(stats.get("success", 0)) + 1
                self._peer_stats[peer_hash] = stats
            return True
        except Exception as exc:
            logger.debug(f"RNS send failed: {exc}")
            with self._peer_lock:
                stats = self._peer_stats.get(peer_hash) or {
                    "fail": 0,
                    "success": 0,
                    "last_fail": 0,
                }
                stats["fail"] = float(stats.get("fail", 0)) + 1
                stats["last_fail"] = time.time()
                self._peer_stats[peer_hash] = stats
            return False

    def _local_hash(self) -> str:
        if not self._destination:
            return ""
        try:
            return self._destination.hash.hex()
        except Exception:
            return ""

    def _make_message_id(self, prefix: str) -> str:
        return f"{prefix}:{uuid.uuid4().hex}"

    def _send_message(self, peer_hash: str, msg_type: str, body: dict, meta: dict | None = None) -> bool:
        settings = get_settings()
        base_meta = {
            "message_id": self._make_message_id(msg_type),
            "reply_to": self._local_hash(),
            "ts": int(time.time()),
        }
        if meta:
            base_meta.update(meta)
        payload = RNSMessage(msg_type=msg_type, body=body, meta=base_meta).encode()
        if len(payload) > settings.MESH_RNS_MAX_PAYLOAD:
            logger.warning(f"RNS payload too large for {msg_type}; dropped")
            return False
        return self._send_to_peer(peer_hash, payload)

    def _send_events(self, peer_hash: str, events: list[dict]) -> None:
        settings = get_settings()
        if not events:
            return
        limited = events[: settings.MESH_RNS_IBF_MAX_EVENTS]
        while limited:
            payload = RNSMessage(
                msg_type="ibf_sync_events",
                body={"events": limited},
                meta={
                    "message_id": self._make_message_id("ibf_sync_events"),
                    "reply_to": self._local_hash(),
                    "ts": int(time.time()),
                },
            ).encode()
            if len(payload) <= settings.MESH_RNS_MAX_PAYLOAD:
                self._send_to_peer(peer_hash, payload)
                return
            limited = limited[: max(1, len(limited) // 2)]
        logger.warning("RNS payload too large for ibf_sync_events; dropped")

    def _recent_event_ids(self, window: int) -> list[str]:
        if window <= 0:
            return []
        try:
            from services.mesh.mesh_hashchain import infonet

            events = infonet.events
            tail = events[-window:] if len(events) > window else events[:]
            out = []
            for evt in tail:
                if isinstance(evt, dict):
                    if evt.get("event_type") == "gate_message":
                        continue
                    eid = evt.get("event_id", "")
                    if eid:
                        out.append(eid)
            return out
        except Exception:
            return []

    def _build_ibf_table(self, window: int, table_size: int) -> tuple[IBLT, list[int], int]:
        event_ids = self._recent_event_ids(window)
        keys = []
        for eid in event_ids:
            try:
                keys.append(bytes.fromhex(eid))
            except Exception:
                continue
        iblt = build_iblt(keys, table_size)
        minhash = minhash_sketch(keys, k=get_settings().MESH_RNS_IBF_MINHASH_SIZE)
        return iblt, minhash, len(keys)

    def _build_ibf_init_payload(self, sync_id: str) -> bytes | None:
        settings = get_settings()
        base_window = settings.MESH_RNS_IBF_WINDOW
        jitter = max(0, int(settings.MESH_RNS_IBF_WINDOW_JITTER))
        if self._is_high_privacy() and jitter == 0:
            jitter = 32
        if jitter:
            import random

            window = max(32, base_window + random.randint(-jitter, jitter))
        else:
            window = base_window
        table_sizes = [
            settings.MESH_RNS_IBF_TABLE_SIZE,
            max(16, settings.MESH_RNS_IBF_TABLE_SIZE // 2),
            max(16, settings.MESH_RNS_IBF_TABLE_SIZE // 4),
        ]
        table_sizes = list(dict.fromkeys([s for s in table_sizes if s > 0]))

        for size in table_sizes:
            iblt, minhash, key_count = self._build_ibf_table(window, size)
            body = {
                "window": window,
                "table": iblt.to_compact_dict(),
                "minhash": minhash,
                "keys": key_count,
            }
            payload = RNSMessage(
                msg_type="ibf_sync_init",
                body=body,
                meta={
                    "message_id": self._make_message_id("ibf_sync_init"),
                    "reply_to": self._local_hash(),
                    "ts": int(time.time()),
                    "sync_id": sync_id,
                },
            ).encode()
            if len(payload) <= settings.MESH_RNS_MAX_PAYLOAD:
                return payload
        logger.warning("RNS payload too large for ibf_sync_init; dropped")
        return None

    def _ibf_sync_loop(self) -> None:
        settings = get_settings()
        interval = max(10, settings.MESH_RNS_IBF_INTERVAL_S)
        while True:
            try:
                if not self.enabled():
                    time.sleep(interval)
                    continue
                self._maybe_rotate_session()
                if self._ibf_in_cooldown():
                    time.sleep(interval)
                    continue
                now = time.time()
                if now - self._last_ibf_sync >= interval:
                    self._last_ibf_sync = now
                    self._send_ibf_sync_init()
                self._prune_sync_rounds()
            except Exception:
                pass
            time.sleep(interval)

    def _send_ibf_sync_init(self) -> None:
        peers = self._select_sync_peers()
        if not peers:
            return
        sync_id = uuid.uuid4().hex
        payload = self._build_ibf_init_payload(sync_id)
        if not payload:
            return
        with self._sync_lock:
            self._pending_sync[sync_id] = {
                "created": time.time(),
                "expected": set(peers),
                "quorum": max(1, (len(peers) // 2) + 1),
                "responses": {},
                "responders": set(),
            }
        for peer in peers:
            self._send_to_peer(peer, payload)

    def _ingest_ordered(self, events: list[dict]) -> None:
        if not events:
            return
        try:
            from services.mesh.mesh_hashchain import infonet

            by_prev: dict[str, dict] = {}
            for evt in events:
                if not isinstance(evt, dict):
                    continue
                prev = evt.get("prev_hash", "")
                eid = evt.get("event_id", "")
                if not prev or not eid:
                    continue
                if prev not in by_prev:
                    by_prev[prev] = evt

            ordered = []
            current = infonet.head_hash
            while current in by_prev:
                evt = by_prev[current]
                ordered.append(evt)
                current = evt.get("event_id", "")
                if not current:
                    break

            if ordered:
                infonet.ingest_events(ordered)
        except Exception:
            pass

    def _handle_ibf_sync_init(self, body: dict, meta: dict) -> None:
        reply_to = str(meta.get("reply_to", "") or "")
        if not reply_to:
            return
        sync_id = str(meta.get("sync_id", "") or "")
        try:
            remote_table = IBLT.from_compact_dict(body.get("table") or {})
        except Exception:
            return

        window = _safe_int(body.get("window", 0) or 0)
        if window <= 0:
            return
        window = min(window, get_settings().MESH_RNS_IBF_WINDOW)
        remote_minhash = body.get("minhash") or []
        local_table, local_minhash, _keys = self._build_ibf_table(window, remote_table.size)
        threshold = float(get_settings().MESH_RNS_IBF_MINHASH_THRESHOLD or 0.0)
        if remote_minhash and local_minhash and threshold > 0:
            similarity = minhash_similarity(remote_minhash, local_minhash)
            if similarity < threshold:
                self._send_message(
                    reply_to,
                    "ibf_sync_nak",
                    {"reason": "low_similarity", "similarity": similarity},
                )
                return

        diff = remote_table.subtract(local_table)
        ok, plus, minus = diff.decode()
        if not ok:
            self._send_message(
                reply_to,
                "ibf_sync_nak",
                {"reason": "decode_failed", "suggested_table": remote_table.size * 2},
            )
            return

        request_ids = [key.hex() for key in plus]
        request_ids = request_ids[: get_settings().MESH_RNS_IBF_MAX_REQUEST_IDS]

        events_out: list[dict] = []
        if minus:
            from services.mesh.mesh_hashchain import infonet

            for key in minus:
                eid = key.hex()
                evt = infonet.get_event(eid)
                if evt and evt.get("event_type") != "gate_message":
                    events_out.append(evt)
                if len(events_out) >= get_settings().MESH_RNS_IBF_MAX_EVENTS:
                    break
        settings = get_settings()
        request_ids = request_ids[: settings.MESH_RNS_IBF_MAX_REQUEST_IDS]
        while True:
            head_hash = ""
            try:
                from services.mesh.mesh_hashchain import infonet

                head_hash = infonet.head_hash
            except Exception:
                head_hash = ""
            payload = RNSMessage(
                msg_type="ibf_sync_delta",
                body={"request": request_ids, "events": events_out},
                meta={
                    "message_id": self._make_message_id("ibf_sync_delta"),
                    "reply_to": self._local_hash(),
                    "ts": int(time.time()),
                    "sync_id": sync_id,
                    "head_hash": head_hash,
                },
            ).encode()
            if len(payload) <= settings.MESH_RNS_MAX_PAYLOAD:
                self._send_to_peer(reply_to, payload)
                return
            if events_out:
                events_out = events_out[: max(1, len(events_out) // 2)]
                continue
            if request_ids:
                request_ids = request_ids[: max(1, len(request_ids) // 2)]
                continue
            break

    def _handle_ibf_sync_delta(self, body: dict, meta: dict) -> None:
        reply_to = str(meta.get("reply_to", "") or "")
        events = body.get("events") or []
        if isinstance(events, list):
            self._note_ibf_success()
            self._ingest_with_quorum(events, meta)

        request_ids = body.get("request") or []
        if reply_to and isinstance(request_ids, list) and request_ids:
            from services.mesh.mesh_hashchain import infonet

            events_out = []
            for eid in request_ids[: get_settings().MESH_RNS_IBF_MAX_REQUEST_IDS]:
                evt = infonet.get_event(str(eid))
                if evt and evt.get("event_type") != "gate_message":
                    events_out.append(evt)
            if events_out:
                self._send_events(reply_to, events_out)

    def _handle_ibf_sync_events(self, body: dict) -> None:
        events = body.get("events") or []
        if isinstance(events, list):
            self._note_ibf_success()
            self._ingest_ordered(events)

    def _handle_infonet_shard(self, body: dict) -> None:
        self._prune_shards()
        shard_id = str(body.get("shard_id", "") or "")
        if not shard_id:
            return
        try:
            index = _safe_int(body.get("index", 0) or 0)
            total = _safe_int(body.get("total", 0) or 0)
            data_shards = _safe_int(body.get("data_shards", 0) or 0)
            parity_shards = _safe_int(body.get("parity_shards", 0) or 0)
            size = _safe_int(body.get("size", 0) or 0)
            length = _safe_int(body.get("length", 0) or 0)
            parity = bool(body.get("parity", False))
            fec = str(body.get("fec", "xor") or "xor").lower()
            blob = base64.b64decode(str(body.get("data", "")))
        except Exception:
            return

        assembled: bytes | None = None
        with self._shard_lock:
            entry = self._shard_cache.get(shard_id)
            if not entry:
                entry = {
                    "created": time.time(),
                    "total": total,
                    "data_shards": data_shards,
                    "parity_shards": parity_shards,
                    "size": size,
                    "length": length,
                    "data": {},
                    "parity": {},
                    "fec": fec,
                }
                self._shard_cache[shard_id] = entry

            if parity:
                entry["parity"][index] = blob
            else:
                entry["data"][index] = blob

            data_map: dict[int, bytes] = entry.get("data", {})
            parity_map: dict[int, bytes] = entry.get("parity", {})
            if data_shards > 0 and len(data_map) >= data_shards:
                assembled = b"".join(data_map[i] for i in range(data_shards) if i in data_map)
                assembled = assembled[:length] if length else assembled
                del self._shard_cache[shard_id]
            elif data_shards > 0:
                fec = str(entry.get("fec", "xor") or "xor").lower()
                if fec == "rs" and parity_shards > 0:
                    recovered = self._rs_recover_missing(
                        data_map, parity_map, data_shards, parity_shards, size
                    )
                    if recovered:
                        data_map.update(recovered)
                        assembled = b"".join(
                            data_map[i] for i in range(data_shards) if i in data_map
                        )
                        assembled = assembled[:length] if length else assembled
                        del self._shard_cache[shard_id]
                elif fec == "xor" and parity_map and len(data_map) == data_shards - 1:
                    missing = [i for i in range(data_shards) if i not in data_map]
                    if len(missing) == 1:
                        parity_blob = next(iter(parity_map.values()))
                        recovered = parity_blob
                        for i in range(data_shards):
                            if i == missing[0]:
                                continue
                            recovered = self._xor_bytes(recovered, data_map[i])
                        data_map[missing[0]] = recovered
                        assembled = b"".join(
                            data_map[i] for i in range(data_shards) if i in data_map
                        )
                        assembled = assembled[:length] if length else assembled
                        del self._shard_cache[shard_id]
        if assembled:
            self._on_packet(assembled)

    def _send_diffuse(self, payload: bytes, exclude: str | None = None) -> int:
        sent = 0
        peers = self._active_peers or self._select_peers(self._parse_peers())
        for peer in peers:
            if exclude and peer == exclude:
                continue
            if self._send_to_peer(peer, payload):
                sent += 1
        return sent

    def send_private_dm(self, *, mailbox_key: str, envelope: dict[str, Any]) -> bool:
        if not self.enabled():
            return False
        if not mailbox_key or not isinstance(envelope, dict):
            return False
        blinded_mailbox_key = _blind_mailbox_key(mailbox_key)
        if not blinded_mailbox_key:
            return False
        message_id = str(envelope.get("msg_id", "") or self._make_message_id("private_dm"))
        payload = RNSMessage(
            msg_type="private_dm",
            body={"mailbox_key": blinded_mailbox_key, "envelope": envelope},
            meta={
                "message_id": f"private_dm:{message_id}",
                "dandelion": {"phase": "stem", "hops": 0, "max_hops": self._dandelion_hops()},
            },
        ).encode()
        if len(payload) > get_settings().MESH_RNS_MAX_PAYLOAD:
            logger.warning("RNS private DM payload too large; falling back to relay")
            return False
        stem_peer = self._pick_stem_peer()
        if stem_peer:
            if not self._send_to_peer(stem_peer, payload):
                return False

            def _diffuse_dm() -> None:
                diffuse = RNSMessage(
                    msg_type="private_dm",
                    body={"mailbox_key": blinded_mailbox_key, "envelope": envelope},
                    meta={"message_id": f"private_dm:{message_id}", "dandelion": {"phase": "diffuse"}},
                ).encode()
                self._send_diffuse(diffuse, exclude=stem_peer)

            delay_s = max(0, get_settings().MESH_RNS_DANDELION_DELAY_MS / 1000.0)
            threading.Timer(delay_s, _diffuse_dm).start()
            return True
        return self._send_diffuse(payload) > 0

    def _store_private_dm(self, mailbox_key: str, envelope: dict[str, Any]) -> None:
        msg_id = str(envelope.get("msg_id", "") or "")
        if not mailbox_key or not msg_id:
            return
        with self._dm_lock:
            mailbox = self._dm_mailboxes.setdefault(mailbox_key, [])
            if any(str(item.get("msg_id", "") or "") == msg_id for item in mailbox):
                return
            mailbox.append(
                {
                    "sender_id": str(envelope.get("sender_id", "") or ""),
                    "ciphertext": str(envelope.get("ciphertext", "") or ""),
                    "timestamp": float(envelope.get("timestamp", 0) or time.time()),
                    "msg_id": msg_id,
                    "delivery_class": str(envelope.get("delivery_class", "shared") or "shared"),
                    "sender_seal": str(envelope.get("sender_seal", "") or ""),
                    "transport": "reticulum",
                }
            )

    def collect_private_dm(self, mailbox_keys: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        with self._dm_lock:
            for key in mailbox_keys:
                blinded_key = _blind_mailbox_key(key)
                if not blinded_key:
                    continue
                mailbox = self._dm_mailboxes.pop(blinded_key, [])
                for item in mailbox:
                    msg_id = str(item.get("msg_id", "") or "")
                    if not msg_id or msg_id in seen:
                        continue
                    seen.add(msg_id)
                    out.append(item)
        return sorted(out, key=lambda item: float(item.get("timestamp", 0) or 0))

    def count_private_dm(self, mailbox_keys: list[str]) -> int:
        seen: set[str] = set()
        with self._dm_lock:
            for key in mailbox_keys:
                blinded_key = _blind_mailbox_key(key)
                if not blinded_key:
                    continue
                for item in self._dm_mailboxes.get(blinded_key, []):
                    msg_id = str(item.get("msg_id", "") or "")
                    if msg_id:
                        seen.add(msg_id)
        return len(seen)

    def private_dm_ids(self, mailbox_keys: list[str]) -> set[str]:
        seen: set[str] = set()
        with self._dm_lock:
            for key in mailbox_keys:
                blinded_key = _blind_mailbox_key(key)
                if not blinded_key:
                    continue
                for item in self._dm_mailboxes.get(blinded_key, []):
                    msg_id = str(item.get("msg_id", "") or "")
                    if msg_id:
                        seen.add(msg_id)
        return seen

    def _publish_now(self, event: dict, message_id: str) -> None:
        if not self.enabled():
            return
        settings = get_settings()
        priority = ""
        payload_info = event.get("payload", {})
        if isinstance(payload_info, dict):
            priority = str(payload_info.get("priority", "")).lower()
        payload = RNSMessage(
            msg_type="infonet_event",
            body={"event": event},
            meta={
                "message_id": message_id,
                "dandelion": {
                    "phase": "stem",
                    "hops": 0,
                    "max_hops": self._dandelion_hops(),
                },
            },
        ).encode()

        if len(payload) > settings.MESH_RNS_MAX_PAYLOAD:
            logger.warning("RNS payload too large; event not sent")
            return

        if settings.MESH_RNS_SHARD_ENABLED or self._is_high_privacy():
            if priority in ("emergency", "high") and len(payload) <= settings.MESH_RNS_MAX_PAYLOAD:
                pass
            elif self._send_sharded_payload(payload, message_id):
                return

        stem_peer = self._pick_stem_peer()
        if stem_peer:
            self._send_to_peer(stem_peer, payload)

            def _diffuse():
                diffuse_payload = RNSMessage(
                    msg_type="infonet_event",
                    body={"event": event},
                    meta={"message_id": message_id, "dandelion": {"phase": "diffuse"}},
                ).encode()
                self._send_diffuse(diffuse_payload, exclude=stem_peer)

            delay_s = max(0, settings.MESH_RNS_DANDELION_DELAY_MS / 1000.0)
            threading.Timer(delay_s, _diffuse).start()
        else:
            self._send_diffuse(payload)

    def _flush_batch(self) -> None:
        with self._batch_lock:
            queued = list(self._batch_queue)
            self._batch_queue.clear()
            if self._batch_timer:
                self._batch_timer.cancel()
            self._batch_timer = None
        for event in queued:
            message_id = event.get("event_id", "") or self._make_message_id("event")
            self._publish_now(event, message_id)

    def _queue_event(self, event: dict) -> None:
        settings = get_settings()
        max_batch = 25
        should_flush = False
        with self._batch_lock:
            self._batch_queue.append(event)
            if len(self._batch_queue) >= max_batch:
                should_flush = True
            else:
                if self._batch_timer is None:
                    delay = max(0, settings.MESH_RNS_BATCH_MS) / 1000.0
                    timer = threading.Timer(delay, self._flush_batch)
                    timer.daemon = True
                    self._batch_timer = timer
                    timer.start()
        if should_flush:
            self._flush_batch()

    def publish_event(self, event: dict) -> None:
        if not self.enabled():
            return
        self._maybe_rotate_session()
        settings = get_settings()
        message_id = event.get("event_id", "")
        if message_id and self._seen(message_id):
            return
        if self._is_high_privacy() and settings.MESH_RNS_BATCH_MS > 0:
            self._queue_event(event)
            return
        self._publish_now(event, message_id or self._make_message_id("event"))

    def publish_gate_event(self, gate_id: str, event: dict) -> None:
        """Publish a gate message on the private plane using the current signer-carried v1 envelope."""
        if not self.enabled():
            return
        self._maybe_rotate_session()
        local_event_id = str(event.get("event_id", "") or "")
        if local_event_id and self._seen(local_event_id):
            return

        payload_info = event.get("payload") if isinstance(event, dict) else {}
        if not isinstance(payload_info, dict):
            payload_info = {}
        from services.mesh.mesh_hashchain import build_gate_wire_ref

        safe_event = {
            "event_type": "gate_message",
            "timestamp": event.get("timestamp", 0),
            "payload": {
                "ciphertext": str(payload_info.get("ciphertext", "") or ""),
                "format": str(payload_info.get("format", "") or ""),
            },
        }
        nonce = str(payload_info.get("nonce", "") or "")
        sender_ref = str(payload_info.get("sender_ref", "") or "")
        epoch = int(payload_info.get("epoch", 0) or 0)
        if nonce:
            safe_event["payload"]["nonce"] = nonce
        if sender_ref:
            safe_event["payload"]["sender_ref"] = sender_ref
        if epoch > 0:
            safe_event["payload"]["epoch"] = epoch
        for field_name in (
            "event_id",
            "node_id",
            "sequence",
            "signature",
            "public_key",
            "public_key_algo",
            "protocol_version",
        ):
            value = event.get(field_name, "")
            if value not in ("", None):
                safe_event[field_name] = value
        gate_ref = build_gate_wire_ref(str(payload_info.get("gate", "") or gate_id), safe_event)
        if not gate_ref:
            logger.warning("RNS private gate forwarding requires MESH_PEER_PUSH_SECRET; event not sent")
            return
        safe_event["payload"]["gate_ref"] = gate_ref
        wire_message_id = self._make_message_id("gate")
        payload = RNSMessage(
            msg_type="gate_event",
            body={"event": safe_event},
            meta={
                "message_id": wire_message_id,
                "dandelion": {
                    "phase": "stem",
                    "hops": 0,
                    "max_hops": self._dandelion_hops(),
                },
            },
        ).encode()
        if len(payload) > get_settings().MESH_RNS_MAX_PAYLOAD:
            logger.warning("RNS gate payload too large; event not sent")
            return
        stem_peer = self._pick_stem_peer()
        if stem_peer:
            self._send_to_peer(stem_peer, payload)

            def _diffuse_gate() -> None:
                diffuse_payload = RNSMessage(
                    msg_type="gate_event",
                    body={"event": safe_event},
                    meta={"message_id": wire_message_id, "dandelion": {"phase": "diffuse"}},
                ).encode()
                self._send_diffuse(diffuse_payload, exclude=stem_peer)

            delay_s = max(0, get_settings().MESH_RNS_DANDELION_DELAY_MS / 1000.0)
            threading.Timer(delay_s, _diffuse_gate).start()
            return
        self._send_diffuse(payload)

    def _cover_interval(self) -> float:
        settings = get_settings()
        interval = float(settings.MESH_RNS_COVER_INTERVAL_S or 0)
        if self._is_high_privacy() and interval <= 0:
            interval = 15.0
        if self._batch_queue:
            qlen = len(self._batch_queue)
            if qlen >= 25:
                interval *= 3
            elif qlen >= 10:
                interval *= 2
        return interval

    def _send_cover_traffic(self) -> None:
        settings = get_settings()
        size = max(16, int(settings.MESH_RNS_COVER_SIZE))
        payload = os.urandom(size)
        msg = RNSMessage(
            msg_type="cover_traffic",
            body={"pad": base64.b64encode(payload).decode("ascii"), "size": size},
            meta={"message_id": self._make_message_id("cover"), "ts": int(time.time())},
        ).encode()
        if len(msg) > settings.MESH_RNS_MAX_PAYLOAD:
            return
        peer = self._pick_stem_peer()
        if peer:
            self._send_to_peer(peer, msg)

    def _cover_loop(self) -> None:
        import random

        while True:
            try:
                if not self.enabled() or not self._is_high_privacy():
                    time.sleep(3)
                    continue
                interval = self._cover_interval()
                if interval <= 0:
                    time.sleep(5)
                    continue
                self._send_cover_traffic()
                jitter = random.uniform(0.7, 1.3)
                time.sleep(interval * jitter)
            except Exception:
                time.sleep(5)

    def _peer_score(self, peer_hash: str) -> float:
        with self._peer_lock:
            stats = self._peer_stats.get(peer_hash, {})
        success = float(stats.get("success", 0))
        fail = float(stats.get("fail", 0))
        return success - (fail * 2)

    def _select_sync_peers(self) -> list[str]:
        settings = get_settings()
        peers = self._active_peers or self._select_peers(self._parse_peers())
        if not peers:
            return []
        scored = sorted(peers, key=self._peer_score, reverse=True)
        max_peers = max(1, int(settings.MESH_RNS_IBF_SYNC_PEERS))
        return scored[: max_peers]

    def _merge_bucket_events(self, bucket: dict[str, Any]) -> list[dict]:
        events = []
        seen = set()
        for evt_list in bucket.get("events", []):
            if not isinstance(evt_list, list):
                continue
            for evt in evt_list:
                if not isinstance(evt, dict):
                    continue
                eid = evt.get("event_id", "")
                if eid and eid in seen:
                    continue
                if eid:
                    seen.add(eid)
                events.append(evt)
        return events

    def _ingest_with_quorum(self, events: list[dict], meta: dict) -> None:
        sync_id = str(meta.get("sync_id", "") or "")
        head_hash = str(meta.get("head_hash", "") or "")
        if not sync_id or not head_hash:
            self._ingest_ordered(events)
            return
        merged: list[dict] | None = None
        quorum = 1
        bucket_count = 0
        bucket_events: list[list[dict]] | None = None
        with self._sync_lock:
            entry = self._pending_sync.get(sync_id)
            if not entry:
                self._ingest_ordered(events)
                return
            peer_id = str(meta.get("reply_to", "") or "")
            responders = entry.get("responders", set())
            if peer_id and peer_id in responders:
                return
            if peer_id:
                responders.add(peer_id)
            buckets = entry.get("responses", {})
            bucket = buckets.get(head_hash) or {"count": 0, "events": []}
            bucket["count"] = int(bucket.get("count", 0) or 0) + 1
            bucket["events"].append(events)
            buckets[head_hash] = bucket
            entry["responses"] = buckets
            entry["responders"] = responders
            quorum = int(entry.get("quorum", 1) or 1)
            bucket_count = int(bucket.get("count", 0) or 0)
            if bucket_count >= quorum:
                bucket_events = list(bucket.get("events", []))
                del self._pending_sync[sync_id]
        if bucket_events is not None:
            merged = self._merge_bucket_events({"events": bucket_events})
        if merged:
            try:
                from services.mesh.mesh_hashchain import infonet

                if head_hash and head_hash != infonet.head_hash:
                    applied, reason = infonet.apply_fork(
                        merged, head_hash, bucket_count, quorum
                    )
                    if not applied:
                        logger.info(f"Fork rejected: {reason}")
                        try:
                            from services.mesh.mesh_metrics import increment as metrics_inc

                            metrics_inc("fork_rejected")
                        except Exception:
                            pass
                    else:
                        logger.info("Fork applied by quorum")
                else:
                    self._ingest_ordered(merged)
            except Exception:
                self._ingest_ordered(merged)
        else:
            self._prune_sync_rounds()

    def _on_packet(self, data: bytes, packet: Any = None) -> None:
        settings = get_settings()
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            return
        msg_type = msg.get("type", "")
        meta = msg.get("meta", {}) or {}
        message_id = meta.get("message_id", "")
        if message_id and self._seen(message_id):
            return

        if msg_type == "ibf_sync_init":
            body = msg.get("body") or {}
            if isinstance(body, dict):
                self._handle_ibf_sync_init(body, meta)
            return
        if msg_type == "ibf_sync_delta":
            body = msg.get("body") or {}
            if isinstance(body, dict):
                self._handle_ibf_sync_delta(body, meta)
            return
        if msg_type == "ibf_sync_events":
            body = msg.get("body") or {}
            if isinstance(body, dict):
                self._handle_ibf_sync_events(body)
            return
        if msg_type == "ibf_sync_nak":
            self._note_ibf_failure()
            return
        if msg_type == "infonet_shard":
            body = msg.get("body") or {}
            if isinstance(body, dict):
                self._handle_infonet_shard(body)
            return
        if msg_type == "cover_traffic":
            return
        if msg_type == "private_dm":
            body = msg.get("body") or {}
            if not isinstance(body, dict):
                return
            mailbox_key = str(body.get("mailbox_key", "") or "")
            envelope = body.get("envelope") or {}
            if not mailbox_key or not isinstance(envelope, dict):
                return

            dandelion = meta.get("dandelion", {}) or {}
            phase = dandelion.get("phase", "diffuse")
            hops = int(dandelion.get("hops", 0) or 0)
            max_hops = int(dandelion.get("max_hops", settings.MESH_RNS_DANDELION_HOPS) or 0)

            if phase == "stem" and hops < max_hops:
                peer = self._pick_stem_peer()
                if peer:
                    next_meta = {
                        "message_id": message_id,
                        "dandelion": {"phase": "stem", "hops": hops + 1, "max_hops": max_hops},
                    }
                    forward = RNSMessage(
                        msg_type="private_dm",
                        body={"mailbox_key": mailbox_key, "envelope": envelope},
                        meta=next_meta,
                    ).encode()
                    self._send_to_peer(peer, forward)
            elif phase == "stem":
                diffuse = RNSMessage(
                    msg_type="private_dm",
                    body={"mailbox_key": mailbox_key, "envelope": envelope},
                    meta={"message_id": message_id, "dandelion": {"phase": "diffuse"}},
                ).encode()
                self._send_diffuse(diffuse)

            self._store_private_dm(mailbox_key, envelope)
            return

        if msg_type == "infonet_event":
            event = (msg.get("body") or {}).get("event")
            if not isinstance(event, dict):
                return

            dandelion = meta.get("dandelion", {}) or {}
            phase = dandelion.get("phase", "diffuse")
            hops = int(dandelion.get("hops", 0) or 0)
            max_hops = int(dandelion.get("max_hops", settings.MESH_RNS_DANDELION_HOPS) or 0)

            if phase == "stem" and hops < max_hops:
                peer = self._pick_stem_peer()
                if peer:
                    next_meta = {
                        "message_id": message_id,
                        "dandelion": {"phase": "stem", "hops": hops + 1, "max_hops": max_hops},
                    }
                    forward = RNSMessage(
                        msg_type="infonet_event",
                        body={"event": event},
                        meta=next_meta,
                    ).encode()
                    self._send_to_peer(peer, forward)
            elif phase == "stem":
                diffuse = RNSMessage(
                    msg_type="infonet_event",
                    body={"event": event},
                    meta={"message_id": message_id, "dandelion": {"phase": "diffuse"}},
                ).encode()
                self._send_diffuse(diffuse)

            # Ingest locally
            try:
                from services.mesh.mesh_hashchain import infonet

                infonet.ingest_events([event])
            except Exception:
                pass
            return

        if msg_type == "gate_event":
            body = msg.get("body") or {}
            if not isinstance(body, dict):
                return
            event = body.get("event")
            if not isinstance(event, dict):
                return
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            gate_id = str(payload.get("gate", "") or "").strip().lower()
            if not gate_id:
                try:
                    from services.mesh.mesh_hashchain import resolve_gate_wire_ref

                    gate_id = resolve_gate_wire_ref(str(payload.get("gate_ref", "") or ""), event)
                except Exception:
                    gate_id = ""
            if not gate_id:
                # Non-members can still forward opaque gate events even if they
                # cannot resolve the local gate identifier.
                gate_id = ""

            dandelion = meta.get("dandelion", {}) or {}
            phase = dandelion.get("phase", "diffuse")
            hops = int(dandelion.get("hops", 0) or 0)
            max_hops = int(dandelion.get("max_hops", settings.MESH_RNS_DANDELION_HOPS) or 0)

            if phase == "stem" and hops < max_hops:
                peer = self._pick_stem_peer()
                if peer:
                    next_meta = {
                        "message_id": message_id,
                        "dandelion": {"phase": "stem", "hops": hops + 1, "max_hops": max_hops},
                    }
                    forward = RNSMessage(
                        msg_type="gate_event",
                        body={"event": event},
                        meta=next_meta,
                    ).encode()
                    self._send_to_peer(peer, forward)
            elif phase == "stem":
                diffuse = RNSMessage(
                    msg_type="gate_event",
                    body={"event": event},
                    meta={"message_id": message_id, "dandelion": {"phase": "diffuse"}},
                ).encode()
                self._send_diffuse(diffuse)

            if gate_id:
                try:
                    from services.mesh.mesh_hashchain import gate_store

                    event_for_store = dict(event)
                    payload_for_store = payload.copy()
                    payload_for_store["gate"] = gate_id
                    event_for_store["payload"] = payload_for_store
                    gate_store.ingest_peer_events(gate_id, [event_for_store])
                except Exception:
                    pass


rns_bridge = RNSBridge()
