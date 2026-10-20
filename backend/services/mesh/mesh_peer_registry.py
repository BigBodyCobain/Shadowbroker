"""Operator-signed peer registry for private Infonet swarm discovery."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from services.mesh.mesh_crypto import normalize_peer_url
from services.mesh.mesh_router import peer_transport_kind

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
DEFAULT_PEER_REGISTRY_PATH = DATA_DIR / "peer_registry.json"
REGISTRY_VERSION = 1
ALLOWED_REGISTRY_ROLES = {"participant", "relay", "seed"}


@dataclass
class RegistryPeer:
    peer_url: str
    transport: str
    role: str
    node_id: str = ""
    label: str = ""
    announced_at: int = 0
    last_seen_at: int = 0
    failure_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def manifest_peer(self) -> dict[str, str]:
        return {
            "peer_url": self.peer_url,
            "transport": self.transport,
            "role": self.role,
            "label": self.label or self.node_id[:16],
        }


class PeerRegistry:
    def __init__(self, path: str | Path = DEFAULT_PEER_REGISTRY_PATH):
        self.path = Path(path)
        self._peers: dict[str, RegistryPeer] = {}

    def load(self) -> list[RegistryPeer]:
        if not self.path.exists():
            self._peers = {}
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("peer registry root must be an object")
        version = int(raw.get("version", 0) or 0)
        if version != REGISTRY_VERSION:
            raise ValueError(f"unsupported peer registry version: {version}")
        entries = raw.get("peers", [])
        if not isinstance(entries, list):
            raise ValueError("peer registry peers must be a list")
        peers: dict[str, RegistryPeer] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            peer = self._normalize_entry(entry)
            peers[peer.peer_url] = peer
        self._peers = peers
        return self.records()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REGISTRY_VERSION,
            "updated_at": int(time.time()),
            "peers": [peer.to_dict() for peer in self.records()],
        }
        self.path.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def records(self) -> list[RegistryPeer]:
        return sorted(self._peers.values(), key=lambda item: (item.role, item.peer_url))

    def upsert_announcement(
        self,
        *,
        peer_url: str,
        transport: str,
        role: str,
        node_id: str = "",
        label: str = "",
        now: float | None = None,
    ) -> RegistryPeer:
        normalized = normalize_peer_url(peer_url)
        if not normalized:
            raise ValueError("peer_url is required")
        resolved_transport = str(transport or "").strip().lower() or str(peer_transport_kind(normalized) or "")
        if resolved_transport not in {"onion", "clearnet"}:
            raise ValueError("unsupported peer transport")
        resolved_role = str(role or "participant").strip().lower()
        if resolved_role not in ALLOWED_REGISTRY_ROLES:
            raise ValueError("unsupported peer role")
        timestamp = int(now if now is not None else time.time())
        existing = self._peers.get(normalized)
        peer = RegistryPeer(
            peer_url=normalized,
            transport=resolved_transport,
            role=resolved_role,
            node_id=str(node_id or (existing.node_id if existing else "") or "").strip(),
            label=str(label or (existing.label if existing else "") or "").strip(),
            announced_at=int(existing.announced_at if existing and existing.announced_at else timestamp),
            last_seen_at=timestamp,
            failure_count=int(existing.failure_count if existing else 0),
        )
        self._peers[normalized] = peer
        return peer

    def prune_stale(self, *, max_age_s: int, now: float | None = None) -> int:
        timestamp = int(now if now is not None else time.time())
        removed = 0
        for peer_url, peer in list(self._peers.items()):
            if peer.role == "seed":
                continue
            last_seen = int(peer.last_seen_at or peer.announced_at or 0)
            if last_seen > 0 and timestamp - last_seen > max(60, int(max_age_s or 0)):
                del self._peers[peer_url]
                removed += 1
        return removed

    def manifest_peers(self) -> list[dict[str, str]]:
        return [peer.manifest_peer() for peer in self.records()]

    def _normalize_entry(self, entry: dict[str, Any]) -> RegistryPeer:
        peer_url = normalize_peer_url(str(entry.get("peer_url", "") or ""))
        if not peer_url:
            raise ValueError("registry peer_url is required")
        transport = str(entry.get("transport", "") or peer_transport_kind(peer_url) or "").strip().lower()
        role = str(entry.get("role", "participant") or "participant").strip().lower()
        if role not in ALLOWED_REGISTRY_ROLES:
            raise ValueError("registry role unsupported")
        return RegistryPeer(
            peer_url=peer_url,
            transport=transport,
            role=role,
            node_id=str(entry.get("node_id", "") or "").strip(),
            label=str(entry.get("label", "") or "").strip(),
            announced_at=int(entry.get("announced_at", 0) or 0),
            last_seen_at=int(entry.get("last_seen_at", 0) or entry.get("announced_at", 0) or 0),
            failure_count=int(entry.get("failure_count", 0) or 0),
        )
