from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from services.mesh.mesh_crypto import normalize_peer_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
DEFAULT_PEER_STORE_PATH = DATA_DIR / "peer_store.json"
PEER_STORE_VERSION = 1
ALLOWED_PEER_BUCKETS = {"bootstrap", "sync", "push"}
ALLOWED_PEER_SOURCES = {"bundle", "operator", "bootstrap_promoted", "runtime"}
ALLOWED_PEER_TRANSPORTS = {"clearnet", "onion"}
ALLOWED_PEER_ROLES = {"participant", "relay", "seed"}


class PeerStoreError(ValueError):
    pass


def _atomic_write_text(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
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


@dataclass(frozen=True)
class PeerRecord:
    bucket: str
    source: str
    peer_url: str
    transport: str
    role: str
    label: str = ""
    signer_id: str = ""
    enabled: bool = True
    added_at: int = 0
    updated_at: int = 0
    last_seen_at: int = 0
    last_sync_ok_at: int = 0
    last_push_ok_at: int = 0
    last_error: str = ""
    failure_count: int = 0
    cooldown_until: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_key(self) -> str:
        return f"{self.bucket}:{self.peer_url}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_peer_record(data: dict[str, Any]) -> PeerRecord:
    bucket = str(data.get("bucket", "") or "").strip().lower()
    source = str(data.get("source", "") or "").strip().lower()
    peer_url = str(data.get("peer_url", "") or "").strip()
    transport = str(data.get("transport", "") or "").strip().lower()
    role = str(data.get("role", "") or "").strip().lower()
    label = str(data.get("label", "") or "").strip()
    signer_id = str(data.get("signer_id", "") or "").strip()
    enabled = bool(data.get("enabled", True))
    metadata = data.get("metadata", {})

    if bucket not in ALLOWED_PEER_BUCKETS:
        raise PeerStoreError(f"unsupported peer bucket: {bucket or 'missing'}")
    if source not in ALLOWED_PEER_SOURCES:
        raise PeerStoreError(f"unsupported peer source: {source or 'missing'}")
    if transport not in ALLOWED_PEER_TRANSPORTS:
        raise PeerStoreError(f"unsupported peer transport: {transport or 'missing'}")
    if role not in ALLOWED_PEER_ROLES:
        raise PeerStoreError(f"unsupported peer role: {role or 'missing'}")

    normalized = normalize_peer_url(peer_url)
    if not normalized or normalized != peer_url:
        raise PeerStoreError("peer_url must be normalized")
    parsed = urlparse(normalized)
    hostname = str(parsed.hostname or "").strip().lower()
    if transport == "clearnet":
        if parsed.scheme not in ("https", "http") or hostname.endswith(".onion"):
            raise PeerStoreError("clearnet peers must use https:// (or http:// for LAN/testnet)")
    elif transport == "onion":
        if parsed.scheme != "http" or not hostname.endswith(".onion"):
            raise PeerStoreError("onion peers must use http://*.onion")

    if not isinstance(metadata, dict):
        raise PeerStoreError("peer metadata must be an object")

    return PeerRecord(
        bucket=bucket,
        source=source,
        peer_url=normalized,
        transport=transport,
        role=role,
        label=label,
        signer_id=signer_id,
        enabled=enabled,
        added_at=int(data.get("added_at", 0) or 0),
        updated_at=int(data.get("updated_at", 0) or 0),
        last_seen_at=int(data.get("last_seen_at", 0) or 0),
        last_sync_ok_at=int(data.get("last_sync_ok_at", 0) or 0),
        last_push_ok_at=int(data.get("last_push_ok_at", 0) or 0),
        last_error=str(data.get("last_error", "") or ""),
        failure_count=int(data.get("failure_count", 0) or 0),
        cooldown_until=int(data.get("cooldown_until", 0) or 0),
        metadata=dict(metadata),
    )


def make_bootstrap_peer_record(
    *,
    peer_url: str,
    transport: str,
    role: str,
    signer_id: str,
    label: str = "",
    now: float | None = None,
) -> PeerRecord:
    timestamp = int(now if now is not None else time.time())
    return _normalize_peer_record(
        {
            "bucket": "bootstrap",
            "source": "bundle",
            "peer_url": peer_url,
            "transport": transport,
            "role": role,
            "label": label,
            "signer_id": signer_id,
            "enabled": True,
            "added_at": timestamp,
            "updated_at": timestamp,
        }
    )


def make_sync_peer_record(
    *,
    peer_url: str,
    transport: str,
    role: str = "participant",
    source: str = "operator",
    label: str = "",
    signer_id: str = "",
    now: float | None = None,
) -> PeerRecord:
    timestamp = int(now if now is not None else time.time())
    return _normalize_peer_record(
        {
            "bucket": "sync",
            "source": source,
            "peer_url": peer_url,
            "transport": transport,
            "role": role,
            "label": label,
            "signer_id": signer_id,
            "enabled": True,
            "added_at": timestamp,
            "updated_at": timestamp,
        }
    )


def make_push_peer_record(
    *,
    peer_url: str,
    transport: str,
    role: str = "relay",
    source: str = "operator",
    label: str = "",
    now: float | None = None,
) -> PeerRecord:
    timestamp = int(now if now is not None else time.time())
    return _normalize_peer_record(
        {
            "bucket": "push",
            "source": source,
            "peer_url": peer_url,
            "transport": transport,
            "role": role,
            "label": label,
            "enabled": True,
            "added_at": timestamp,
            "updated_at": timestamp,
        }
    )


class PeerStore:
    def __init__(self, path: str | Path = DEFAULT_PEER_STORE_PATH):
        self.path = Path(path)
        self._records: dict[str, PeerRecord] = {}

    def load(self) -> list[PeerRecord]:
        if not self.path.exists():
            self._records = {}
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PeerStoreError("peer store is not valid JSON") from exc

        if not isinstance(raw, dict):
            raise PeerStoreError("peer store root must be an object")
        version = int(raw.get("version", 0) or 0)
        if version != PEER_STORE_VERSION:
            raise PeerStoreError(f"unsupported peer store version: {version}")
        records_raw = raw.get("records", [])
        if not isinstance(records_raw, list):
            raise PeerStoreError("peer store records must be a list")

        records: dict[str, PeerRecord] = {}
        for entry in records_raw:
            if not isinstance(entry, dict):
                raise PeerStoreError("peer store records must be objects")
            record = _normalize_peer_record(entry)
            records[record.record_key()] = record
        self._records = records
        return self.records()

    def save(self) -> None:
        payload = {
            "version": PEER_STORE_VERSION,
            "records": [record.to_dict() for record in self.records()],
        }
        _atomic_write_text(
            self.path,
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        )

    def records(self) -> list[PeerRecord]:
        return sorted(self._records.values(), key=lambda item: (item.bucket, item.peer_url))

    def records_for_bucket(self, bucket: str) -> list[PeerRecord]:
        normalized_bucket = str(bucket or "").strip().lower()
        return [record for record in self.records() if record.bucket == normalized_bucket]

    def upsert(self, record: PeerRecord) -> PeerRecord:
        existing = self._records.get(record.record_key())
        if existing is None:
            self._records[record.record_key()] = record
            return record

        merged = PeerRecord(
            bucket=record.bucket,
            source=record.source,
            peer_url=record.peer_url,
            transport=record.transport,
            role=record.role,
            label=record.label or existing.label,
            signer_id=record.signer_id or existing.signer_id,
            enabled=record.enabled,
            added_at=existing.added_at or record.added_at,
            updated_at=max(existing.updated_at, record.updated_at),
            last_seen_at=max(existing.last_seen_at, record.last_seen_at),
            last_sync_ok_at=max(existing.last_sync_ok_at, record.last_sync_ok_at),
            last_push_ok_at=max(existing.last_push_ok_at, record.last_push_ok_at),
            last_error=record.last_error or existing.last_error,
            failure_count=max(existing.failure_count, record.failure_count),
            cooldown_until=max(existing.cooldown_until, record.cooldown_until),
            metadata={**existing.metadata, **record.metadata},
        )
        self._records[record.record_key()] = merged
        return merged

    def mark_seen(self, peer_url: str, bucket: str, *, now: float | None = None) -> PeerRecord:
        record = self._require_record(peer_url, bucket)
        timestamp = int(now if now is not None else time.time())
        updated = PeerRecord(
            **{
                **record.to_dict(),
                "last_seen_at": timestamp,
                "updated_at": timestamp,
            }
        )
        self._records[updated.record_key()] = updated
        return updated

    def mark_sync_success(self, peer_url: str, bucket: str = "sync", *, now: float | None = None) -> PeerRecord:
        record = self._require_record(peer_url, bucket)
        timestamp = int(now if now is not None else time.time())
        updated = PeerRecord(
            **{
                **record.to_dict(),
                "last_sync_ok_at": timestamp,
                "last_error": "",
                "failure_count": 0,
                "cooldown_until": 0,
                "updated_at": timestamp,
            }
        )
        self._records[updated.record_key()] = updated
        return updated

    def mark_push_success(self, peer_url: str, bucket: str = "push", *, now: float | None = None) -> PeerRecord:
        record = self._require_record(peer_url, bucket)
        timestamp = int(now if now is not None else time.time())
        updated = PeerRecord(
            **{
                **record.to_dict(),
                "last_push_ok_at": timestamp,
                "last_error": "",
                "failure_count": 0,
                "cooldown_until": 0,
                "updated_at": timestamp,
            }
        )
        self._records[updated.record_key()] = updated
        return updated

    def mark_failure(
        self,
        peer_url: str,
        bucket: str,
        *,
        error: str,
        cooldown_s: int = 0,
        now: float | None = None,
    ) -> PeerRecord:
        record = self._require_record(peer_url, bucket)
        timestamp = int(now if now is not None else time.time())
        updated = PeerRecord(
            **{
                **record.to_dict(),
                "last_error": str(error or "").strip(),
                "failure_count": int(record.failure_count) + 1,
                "cooldown_until": timestamp + max(0, int(cooldown_s or 0)),
                "updated_at": timestamp,
            }
        )
        self._records[updated.record_key()] = updated
        return updated

    def _require_record(self, peer_url: str, bucket: str) -> PeerRecord:
        normalized_url = normalize_peer_url(peer_url)
        key = f"{str(bucket or '').strip().lower()}:{normalized_url}"
        if key not in self._records:
            raise PeerStoreError(f"peer record not found: {key}")
        return self._records[key]
