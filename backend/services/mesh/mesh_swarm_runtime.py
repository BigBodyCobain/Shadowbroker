"""Private Infonet swarm discovery and immediate ledger propagation."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from services.config import get_settings
from services.mesh.mesh_bootstrap_manifest import (
    BootstrapManifest,
    BootstrapManifestError,
    BootstrapPeer,
    build_bootstrap_manifest_payload,
    load_bootstrap_manifest,
    parse_bootstrap_manifest_dict,
    sign_bootstrap_manifest_payload,
    write_signed_bootstrap_manifest,
)
from services.mesh.mesh_crypto import normalize_peer_url, resolve_peer_key_for_url
from services.mesh.mesh_peer_registry import DEFAULT_PEER_REGISTRY_PATH, PeerRegistry, RegistryPeer
from services.mesh.mesh_peer_store import (
    DEFAULT_PEER_STORE_PATH,
    PeerStore,
    make_push_peer_record,
    make_sync_peer_record,
)
from services.mesh.mesh_router import parse_configured_relay_peers, peer_transport_kind

logger = logging.getLogger(__name__)

_SWARM_LOCK = threading.Lock()
_LAST_MANIFEST_PULL_AT = 0.0
_LAST_ANNOUNCE_AT = 0.0


def peer_registry_enabled() -> bool:
    settings = get_settings()
    if bool(getattr(settings, "MESH_PEER_REGISTRY_DISABLED", False)):
        return False
    if str(getattr(settings, "MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY", "") or "").strip():
        return True
    return bool(getattr(settings, "MESH_PEER_REGISTRY_ENABLED", False))


def _manifest_path() -> str:
    return str(getattr(get_settings(), "MESH_BOOTSTRAP_MANIFEST_PATH", "") or "data/bootstrap_peers.json")


def _signer_public_key_b64() -> str:
    from services.mesh.mesh_fleet_defaults import effective_bootstrap_signer_public_key_b64

    return effective_bootstrap_signer_public_key_b64()


def _signer_private_key_b64() -> str:
    return str(getattr(settings, "MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY", "") or "").strip() if (settings := get_settings()) else ""


def _signer_id() -> str:
    configured = str(getattr(get_settings(), "MESH_BOOTSTRAP_SIGNER_ID", "") or "").strip()
    return configured or "shadowbroker-seed"


def _private_transport_required() -> bool:
    return not bool(getattr(get_settings(), "MESH_INFONET_ALLOW_CLEARNET_SYNC", False))


def _configured_seed_peer_urls() -> list[str]:
    from services.mesh.mesh_fleet_defaults import configured_bootstrap_seed_peers_with_fleet_default

    settings = get_settings()
    primary = str(getattr(settings, "MESH_BOOTSTRAP_SEED_PEERS", "") or "").strip()
    legacy = str(getattr(settings, "MESH_DEFAULT_SYNC_PEERS", "") or "").strip()
    return configured_bootstrap_seed_peers_with_fleet_default(
        parse_configured_relay_peers(primary or legacy)
    )


def _seed_manifest_peers() -> list[dict[str, str]]:
    peers: list[dict[str, str]] = []
    for peer_url in _configured_seed_peer_urls():
        transport = str(peer_transport_kind(peer_url) or "")
        if _private_transport_required() and transport != "onion":
            continue
        peers.append(
            {
                "peer_url": peer_url,
                "transport": transport,
                "role": "seed",
                "label": "ShadowBroker bootstrap seed",
            }
        )
    return peers


def publish_registry_manifest(*, now: float | None = None, persist: bool = True) -> BootstrapManifest:
    private_key = _signer_private_key_b64()
    public_key = _signer_public_key_b64()
    if not private_key or not public_key:
        raise BootstrapManifestError("bootstrap signer keys are required to publish swarm manifest")

    timestamp = int(now if now is not None else time.time())
    registry = PeerRegistry(DEFAULT_PEER_REGISTRY_PATH)
    try:
        registry.load()
    except Exception:
        registry = PeerRegistry(DEFAULT_PEER_REGISTRY_PATH)
    stale_s = int(getattr(get_settings(), "MESH_PEER_REGISTRY_STALE_S", 0) or 7 * 86400)
    if stale_s > 0:
        registry.prune_stale(max_age_s=stale_s, now=timestamp)

    peers = _seed_manifest_peers() + registry.manifest_peers()
    ttl_s = int(getattr(get_settings(), "MESH_SWARM_MANIFEST_TTL_S", 0) or 4 * 3600)
    payload = build_bootstrap_manifest_payload(
        signer_id=_signer_id(),
        peers=peers,
        issued_at=timestamp,
        valid_until=timestamp + max(300, ttl_s),
    )
    signature = sign_bootstrap_manifest_payload(payload, signer_private_key_b64=private_key)
    manifest = BootstrapManifest(
        version=int(payload["version"]),
        issued_at=int(payload["issued_at"]),
        valid_until=int(payload["valid_until"]),
        signer_id=str(payload["signer_id"]),
        peers=tuple(BootstrapPeer(**dict(peer)) for peer in peers),
        signature=signature,
    )
    if persist:
        registry.save()
        write_signed_bootstrap_manifest(
            _manifest_path(),
            signer_id=manifest.signer_id,
            signer_private_key_b64=private_key,
            peers=[peer.to_dict() for peer in manifest.peers],
            issued_at=manifest.issued_at,
            valid_until=manifest.valid_until,
        )
    return manifest


def load_live_bootstrap_manifest(*, now: float | None = None) -> BootstrapManifest | None:
    public_key = _signer_public_key_b64()
    if not public_key:
        return None
    if peer_registry_enabled():
        try:
            return publish_registry_manifest(now=now, persist=False)
        except BootstrapManifestError:
            logger.warning("live registry manifest unavailable", exc_info=True)
    try:
        return load_bootstrap_manifest(_manifest_path(), signer_public_key_b64=public_key, now=now)
    except BootstrapManifestError:
        return None


def _upsert_swarm_peer_into_store(
    *,
    peer_url: str,
    transport: str,
    role: str,
    label: str = "",
    signer_id: str = "",
    now: float | None = None,
) -> None:
    timestamp = int(now if now is not None else time.time())
    if _private_transport_required() and transport != "onion":
        return
    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception:
        store = PeerStore(DEFAULT_PEER_STORE_PATH)
    store.upsert(
        make_sync_peer_record(
            peer_url=peer_url,
            transport=transport,
            role=role,
            source="swarm",
            label=label,
            signer_id=signer_id,
            now=timestamp,
        )
    )
    store.upsert(
        make_push_peer_record(
            peer_url=peer_url,
            transport=transport,
            role=role if role != "seed" else "relay",
            source="swarm",
            label=label,
            now=timestamp,
        )
    )
    store.save()


def record_peer_announcement(body: dict[str, Any], *, now: float | None = None) -> RegistryPeer:
    if not peer_registry_enabled():
        raise ValueError("peer registry is not enabled on this node")
    registry = PeerRegistry(DEFAULT_PEER_REGISTRY_PATH)
    try:
        registry.load()
    except Exception:
        registry = PeerRegistry(DEFAULT_PEER_REGISTRY_PATH)
    peer = registry.upsert_announcement(
        peer_url=str(body.get("peer_url", "") or ""),
        transport=str(body.get("transport", "") or ""),
        role=str(body.get("role", "participant") or "participant"),
        node_id=str(body.get("node_id", "") or ""),
        label=str(body.get("label", "") or ""),
        now=now,
    )
    registry.save()
    _upsert_swarm_peer_into_store(
        peer_url=peer.peer_url,
        transport=peer.transport,
        role=peer.role,
        label=peer.label,
        signer_id=_signer_id(),
        now=now,
    )
    try:
        publish_registry_manifest(now=now, persist=True)
    except Exception:
        logger.warning("failed to republish swarm manifest after announce", exc_info=True)
    return peer


def merge_manifest_into_peer_store(manifest: BootstrapManifest, *, now: float | None = None) -> int:
    timestamp = int(now if now is not None else time.time())
    merged = 0
    for peer in manifest.peers:
        if _private_transport_required() and peer.transport != "onion":
            continue
        _upsert_swarm_peer_into_store(
            peer_url=peer.peer_url,
            transport=peer.transport,
            role=peer.role,
            label=peer.label,
            signer_id=manifest.signer_id,
            now=timestamp,
        )
        merged += 1
    return merged


def fetch_remote_bootstrap_manifest(seed_peer_url: str, *, now: float | None = None) -> BootstrapManifest | None:
    import requests

    public_key = _signer_public_key_b64()
    if not public_key:
        return None
    normalized = normalize_peer_url(seed_peer_url)
    if not normalized:
        return None

    from main import _infonet_peer_requests_proxies

    proxies = _infonet_peer_requests_proxies(normalized)
    timeout = int(getattr(get_settings(), "MESH_SYNC_TIMEOUT_S", 0) or 45)
    request_kwargs: dict[str, Any] = {"timeout": timeout}
    if proxies:
        request_kwargs["proxies"] = proxies
    try:
        response = requests.get(f"{normalized}/api/mesh/infonet/bootstrap-manifest", **request_kwargs)
    except Exception as exc:
        logger.debug("swarm manifest fetch failed for %s: %s", normalized, exc)
        return None
    if response.status_code != 200:
        return None
    try:
        raw = response.json()
    except Exception:
        return None
    if not isinstance(raw, dict) or raw.get("ok") is False:
        return None
    manifest_body = dict(raw.get("manifest") or raw)
    try:
        return parse_bootstrap_manifest_dict(
            manifest_body,
            signer_public_key_b64=public_key,
            now=now,
        )
    except BootstrapManifestError:
        return None


def refresh_swarm_manifest_from_seeds(*, now: float | None = None, force: bool = False) -> dict[str, Any]:
    global _LAST_MANIFEST_PULL_AT
    interval_s = int(getattr(get_settings(), "MESH_SWARM_MANIFEST_PULL_INTERVAL_S", 0) or 300)
    timestamp = float(now if now is not None else time.time())
    with _SWARM_LOCK:
        if not force and _LAST_MANIFEST_PULL_AT and timestamp - _LAST_MANIFEST_PULL_AT < max(30, interval_s):
            return {"ok": True, "skipped": True, "reason": "manifest_pull_interval"}
        _LAST_MANIFEST_PULL_AT = timestamp

    if not _signer_public_key_b64():
        return {"ok": False, "detail": "MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY is not configured"}

    seed_urls = _configured_seed_peer_urls()
    last_error = "bootstrap seeds unreachable; local node will retry"
    for seed_url in seed_urls:
        manifest = fetch_remote_bootstrap_manifest(seed_url, now=timestamp)
        if manifest is None:
            continue
        try:
            merged = merge_manifest_into_peer_store(manifest, now=timestamp)
            return {
                "ok": True,
                "seed_peer_url": seed_url,
                "tried_seed_count": len(seed_urls),
                "peer_count": len(manifest.peers),
                "merged_peer_count": merged,
            }
        except Exception as exc:
            last_error = str(exc or type(exc).__name__)
    return {
        "ok": False,
        "detail": last_error,
        "tried_seed_count": len(seed_urls),
        "retrying": bool(seed_urls),
    }


def announce_local_peer_to_seeds(*, now: float | None = None, force: bool = False) -> dict[str, Any]:
    global _LAST_ANNOUNCE_AT
    import hashlib as _hashlib_mod
    import hmac as _hmac_mod
    import requests

    from main import _infonet_peer_requests_proxies, _local_infonet_peer_url, _participant_node_enabled

    if not _participant_node_enabled():
        return {"ok": False, "detail": "participant node disabled"}
    peer_url = _local_infonet_peer_url()
    if not peer_url:
        return {"ok": False, "detail": "local peer URL is not ready"}
    peer_key = resolve_peer_key_for_url(peer_url)
    if not peer_key:
        return {"ok": False, "detail": "peer HMAC secret is not configured"}

    timestamp = float(now if now is not None else time.time())
    with _SWARM_LOCK:
        if not force and _LAST_ANNOUNCE_AT and timestamp - _LAST_ANNOUNCE_AT < 300:
            return {"ok": True, "skipped": True, "reason": "announce_interval"}
        _LAST_ANNOUNCE_AT = timestamp

    transport = str(peer_transport_kind(peer_url) or "onion")
    body = {
        "peer_url": peer_url,
        "transport": transport,
        "role": "participant",
        "node_id": "",
        "label": "",
        "ts": int(timestamp),
    }
    body_bytes = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    hmac_hex = _hmac_mod.new(peer_key, body_bytes, _hashlib_mod.sha256).hexdigest()
    timeout = int(getattr(get_settings(), "MESH_RELAY_PUSH_TIMEOUT_S", 0) or 45)
    results: list[dict[str, Any]] = []
    for seed_url in _configured_seed_peer_urls():
        normalized = normalize_peer_url(seed_url)
        if not normalized:
            continue
        proxies = _infonet_peer_requests_proxies(normalized)
        request_kwargs: dict[str, Any] = {
            "data": body_bytes,
            "headers": {
                "Content-Type": "application/json",
                "X-Peer-Url": peer_url,
                "X-Peer-HMAC": hmac_hex,
            },
            "timeout": timeout,
        }
        if proxies:
            request_kwargs["proxies"] = proxies
        try:
            response = requests.post(
                f"{normalized}/api/mesh/infonet/peer-announce",
                **request_kwargs,
            )
            results.append(
                {
                    "seed_peer_url": normalized,
                    "status_code": int(response.status_code),
                    "ok": response.status_code == 200,
                }
            )
        except Exception as exc:
            results.append({"seed_peer_url": normalized, "ok": False, "detail": str(exc)})
    ok = any(bool(item.get("ok")) for item in results)
    return {"ok": ok, "peer_url": peer_url, "results": results}


def _announce_succeeded(announce: dict[str, Any]) -> bool:
    if not bool(announce.get("ok")):
        return False
    results = announce.get("results") or []
    return any(bool(item.get("ok")) and int(item.get("status_code") or 0) == 200 for item in results)


def _manifest_succeeded(manifest: dict[str, Any]) -> bool:
    if not bool(manifest.get("ok")):
        return False
    peer_count = int(manifest.get("merged_peer_count") or manifest.get("peer_count") or 0)
    return peer_count >= 1


def join_swarm_with_retries(
    *,
    attempts: int = 6,
    delay_s: float = 15.0,
    force: bool = True,
) -> dict[str, Any]:
    """Announce to seed and pull manifest, retrying while Tor circuits warm up."""
    last_announce: dict[str, Any] = {"ok": False, "detail": "not attempted"}
    last_manifest: dict[str, Any] = {"ok": False, "detail": "not attempted"}
    tries = max(1, int(attempts))
    pause_s = max(1.0, float(delay_s))
    for attempt in range(tries):
        last_announce = announce_local_peer_to_seeds(force=force)
        last_manifest = refresh_swarm_manifest_from_seeds(force=force)
        if _announce_succeeded(last_announce) and _manifest_succeeded(last_manifest):
            return {
                "ok": True,
                "attempts": attempt + 1,
                "announce": last_announce,
                "manifest_pull": last_manifest,
            }
        if attempt + 1 < tries:
            time.sleep(pause_s)
    return {
        "ok": False,
        "attempts": tries,
        "announce": last_announce,
        "manifest_pull": last_manifest,
        "detail": "swarm join incomplete after retries",
    }


def push_infonet_events_to_http_peers(events: list[dict[str, Any]]) -> dict[str, Any]:
    import hashlib as _hashlib_mod
    import hmac as _hmac_mod
    import requests

    from main import (
        _filter_infonet_peer_urls,
        _infonet_peer_requests_proxies,
        _local_infonet_peer_url,
        _participant_node_enabled,
        _record_public_push_result,
    )
    from services.mesh.mesh_router import authenticated_push_peer_urls

    if not _participant_node_enabled() or not events:
        return {"ok": False, "detail": "nothing to push"}
    peers = _filter_infonet_peer_urls(authenticated_push_peer_urls())
    if not peers:
        return {"ok": False, "detail": "no push peers configured"}

    sender_url = _local_infonet_peer_url()
    peer_key = resolve_peer_key_for_url(sender_url)
    if not peer_key:
        return {"ok": False, "detail": "peer HMAC secret is not configured"}

    body_bytes = json.dumps(
        {"events": events},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    hmac_hex = _hmac_mod.new(peer_key, body_bytes, _hashlib_mod.sha256).hexdigest()
    timeout = int(getattr(get_settings(), "MESH_RELAY_PUSH_TIMEOUT_S", 0) or 45)
    results: list[dict[str, Any]] = []
    for peer_url in peers:
        normalized = normalize_peer_url(peer_url)
        if not normalized:
            continue
        proxies = _infonet_peer_requests_proxies(normalized)
        request_kwargs: dict[str, Any] = {
            "data": body_bytes,
            "headers": {
                "Content-Type": "application/json",
                "X-Peer-Url": sender_url,
                "X-Peer-HMAC": hmac_hex,
            },
            "timeout": timeout,
        }
        if proxies:
            request_kwargs["proxies"] = proxies
        try:
            response = requests.post(f"{normalized}/api/mesh/infonet/peer-push", **request_kwargs)
            results.append(
                {
                    "peer_url": normalized,
                    "ok": response.status_code == 200,
                    "status_code": int(response.status_code),
                }
            )
        except Exception as exc:
            results.append({"peer_url": normalized, "ok": False, "detail": str(exc)})
    ok = any(bool(item.get("ok")) for item in results)
    event_id = str((events[-1] or {}).get("event_id", "") or "")
    _record_public_push_result(
        event_id,
        ok=ok,
        error="" if ok else "immediate peer push failed",
        results=results,
    )
    return {"ok": ok, "results": results}
