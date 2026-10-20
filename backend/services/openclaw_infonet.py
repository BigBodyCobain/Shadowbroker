"""OpenClaw agent delegation for private Infonet / gate / DM actions.

Agents authenticate with OpenClaw HMAC on the command channel. Write
commands require ``OPENCLAW_ACCESS_TIER=full``. Actions use the operator's
local wormhole persona and node runtime — the agent posts on behalf of the
user who configured the skill, not as a separate fleet identity.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from typing import Any

from starlette.requests import Request

logger = logging.getLogger(__name__)


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return asyncio.run(coro)


def _local_agent_request(path: str, *, method: str = "POST") -> Request:
    scope = {
        "type": "http",
        "method": method.upper(),
        "path": path,
        "headers": [],
        "client": ("127.0.0.1", 52421),
    }
    request = Request(scope)
    request.state._private_lane_current_tier = "private_strong"
    request.state._transport_tier = "private_strong"
    return request


def ensure_infonet_ready(*, join_swarm: bool = True) -> dict[str, Any]:
    """Warm Tor, enable the participant node, and optionally join the swarm."""
    from routers.ai_intel import _write_env_value
    from services.config import get_settings
    from services.mesh.mesh_swarm_runtime import join_swarm_with_retries
    from services.node_settings import read_node_settings, write_node_settings
    from services.tor_hidden_service import tor_service
    from services.wormhole_supervisor import _check_arti_ready

    steps: dict[str, Any] = {}

    tor_result = tor_service.start(target_port=8000)
    steps["tor"] = tor_result
    if tor_result.get("ok"):
        try:
            _write_env_value("MESH_ARTI_ENABLED", "true")
            get_settings.cache_clear()
        except Exception as exc:
            logger.debug("failed to persist MESH_ARTI_ENABLED: %s", exc)

    if not _check_arti_ready():
        return {
            "ok": False,
            "detail": "Tor/Arti transport is not ready yet",
            "steps": steps,
        }

    if not bool(read_node_settings().get("enabled")):
        write_node_settings(enabled=True)
        steps["node_enabled"] = True
        try:
            import main as main_mod

            main_mod._refresh_node_peer_store()
            main_mod._start_infonet_node_runtime("openclaw_agent")
        except Exception as exc:
            logger.warning("node runtime start after agent enable failed: %s", exc)
    else:
        steps["node_enabled"] = True

    if join_swarm:
        joined = join_swarm_with_retries()
        steps["announce"] = joined.get("announce") or {}
        steps["manifest_pull"] = joined.get("manifest_pull") or {}
        steps["swarm_attempts"] = joined.get("attempts")
        ok = bool(joined.get("ok"))
    else:
        ok = True

    return {
        "ok": ok,
        "detail": "Infonet participant runtime ready" if ok else "swarm join incomplete",
        "steps": steps,
        "onion_address": str(tor_result.get("onion_address") or ""),
    }


def join_infonet_swarm() -> dict[str, Any]:
    from services.mesh.mesh_swarm_runtime import join_swarm_with_retries

    joined = join_swarm_with_retries()
    return {
        "ok": bool(joined.get("ok")),
        "announce": joined.get("announce") or {},
        "manifest_pull": joined.get("manifest_pull") or {},
        "attempts": joined.get("attempts"),
        "detail": joined.get("detail"),
    }


def get_infonet_status() -> dict[str, Any]:
    from services.mesh.mesh_hashchain import infonet
    from services.wormhole_supervisor import get_wormhole_state

    info = infonet.get_info()
    valid, reason = infonet.validate_chain(verify_signatures=False)
    try:
        wormhole = get_wormhole_state()
    except Exception:
        wormhole = {"configured": False, "ready": False, "arti_ready": False, "rns_ready": False}
    try:
        import main as main_mod

        runtime = main_mod._node_runtime_snapshot()
        private_tier = main_mod._current_private_lane_tier(wormhole)
    except Exception:
        runtime = {}
        private_tier = "public_degraded"

    return {
        "ok": True,
        "chain": info,
        "valid": valid,
        "validation": reason,
        "private_lane_tier": private_tier,
        "wormhole": wormhole,
        "runtime": runtime,
    }


def list_gates() -> dict[str, Any]:
    from services.mesh.mesh_reputation import gate_manager

    return {"ok": True, "gates": gate_manager.list_gates()}


def read_gate_messages(
    gate_id: str,
    *,
    limit: int = 20,
    decrypt: bool = False,
) -> dict[str, Any]:
    from services.mesh.mesh_hashchain import gate_store

    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}

    messages, cursor = gate_store.get_messages_with_cursor(gate_key, limit=max(1, min(int(limit), 100)))
    out = []
    if decrypt:
        from services.mesh.mesh_gate_repair import decrypt_gate_message_with_repair

        for msg in messages:
            item = dict(msg)
            try:
                decrypted = decrypt_gate_message_with_repair(
                    gate_id=gate_key,
                    epoch=int(item.get("epoch") or 0),
                    ciphertext=str(item.get("ciphertext") or ""),
                    nonce=str(item.get("nonce") or item.get("iv") or ""),
                    sender_ref=str(item.get("sender_ref") or ""),
                    gate_envelope=str(item.get("gate_envelope") or ""),
                    envelope_hash=str(item.get("envelope_hash") or ""),
                    event_id=str(item.get("event_id") or ""),
                )
                if decrypted.get("ok"):
                    item["plaintext"] = decrypted.get("plaintext", "")
            except Exception as exc:
                item["decrypt_error"] = str(exc)
            out.append(item)
    else:
        out = [dict(m) for m in messages]

    return {
        "ok": True,
        "gate": gate_key,
        "count": len(out),
        "cursor": cursor,
        "messages": out,
    }


def post_gate_message(
    gate_id: str,
    plaintext: str,
    *,
    reply_to: str = "",
) -> dict[str, Any]:
    """Compose, sign, and post an MLS gate message using the operator persona."""
    from services.mesh.mesh_gate_repair import (
        compose_gate_message_with_repair,
        sign_gate_message_with_repair,
    )
    from services.mesh.mesh_wormhole_persona import bootstrap_wormhole_persona_state, create_gate_persona

    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    if not str(plaintext or "").strip():
        return {"ok": False, "detail": "plaintext required"}

    bootstrap_wormhole_persona_state(force=False)
    try:
        create_gate_persona(gate_key, label="openclaw-agent")
    except Exception:
        pass

    composed = compose_gate_message_with_repair(
        gate_id=gate_key,
        plaintext=str(plaintext),
        reply_to=str(reply_to or ""),
    )
    if not composed.get("ok"):
        return composed

    signed = sign_gate_message_with_repair(
        gate_id=gate_key,
        epoch=int(composed.get("epoch") or 0),
        ciphertext=str(composed.get("ciphertext") or ""),
        nonce=str(composed.get("nonce") or ""),
        payload_format=str(composed.get("format") or "mls1"),
        reply_to=str(reply_to or ""),
        envelope_hash=str(composed.get("envelope_hash") or ""),
        transport_lock="private_strong",
    )
    if not signed.get("ok"):
        return signed

    body = {
        "sender_id": str(signed.get("sender_id") or composed.get("sender_id") or ""),
        "public_key": str(signed.get("public_key") or composed.get("public_key") or ""),
        "public_key_algo": str(signed.get("public_key_algo") or composed.get("public_key_algo") or ""),
        "signature": str(signed.get("signature") or ""),
        "sequence": int(signed.get("sequence") or composed.get("sequence") or 0),
        "protocol_version": str(signed.get("protocol_version") or composed.get("protocol_version") or ""),
        "epoch": int(signed.get("epoch") or composed.get("epoch") or 0),
        "ciphertext": str(signed.get("ciphertext") or composed.get("ciphertext") or ""),
        "nonce": str(signed.get("nonce") or composed.get("nonce") or ""),
        "sender_ref": str(signed.get("sender_ref") or composed.get("sender_ref") or ""),
        "format": str(signed.get("format") or composed.get("format") or "mls1"),
        "gate_envelope": str(signed.get("gate_envelope") or composed.get("gate_envelope") or ""),
        "envelope_hash": str(signed.get("envelope_hash") or composed.get("envelope_hash") or ""),
        "transport_lock": "private_strong",
        "reply_to": str(signed.get("reply_to") or reply_to or ""),
    }

    import main as main_mod

    path = f"/api/mesh/gate/{gate_key}/message"
    request = _local_agent_request(path)
    return main_mod._submit_gate_message_envelope(request, gate_key, body)


def cast_vote(
    target_id: str,
    vote: int,
    *,
    gate: str = "",
) -> dict[str, Any]:
    """Cast a signed reputation vote using the operator gate/transport persona."""
    from services.mesh.mesh_hashchain import infonet
    from services.mesh.mesh_protocol import PROTOCOL_VERSION, normalize_payload
    from services.mesh.mesh_reputation import gate_manager, reputation_ledger
    from services.mesh.mesh_wormhole_persona import (
        bootstrap_wormhole_persona_state,
        sign_gate_wormhole_event,
        sign_public_wormhole_event,
    )

    voter_gate = str(gate or "").strip().lower()
    target = str(target_id or "").strip()
    vote_val = int(vote)
    if not target:
        return {"ok": False, "detail": "target_id required"}
    if vote_val not in (1, -1):
        return {"ok": False, "detail": "vote must be 1 or -1"}

    bootstrap_wormhole_persona_state(force=False)
    vote_payload = {"target_id": target, "vote": vote_val, "gate": voter_gate}
    normalized = normalize_payload("vote", vote_payload)
    ok_payload, reason = True, "ok"
    from services.mesh.mesh_schema import validate_event_payload

    ok_payload, reason = validate_event_payload("vote", normalized)
    if not ok_payload:
        return {"ok": False, "detail": reason}

    if voter_gate:
        signed = sign_gate_wormhole_event(
            gate_id=voter_gate,
            event_type="vote",
            payload=normalized,
        )
    else:
        signed = sign_public_wormhole_event(event_type="vote", payload=normalized)

    if not signed.get("ok", True):
        return signed

    voter_id = str(signed.get("node_id") or "")
    public_key = str(signed.get("public_key") or "")
    public_key_algo = str(signed.get("public_key_algo") or "")
    signature = str(signed.get("signature") or "")
    sequence = int(signed.get("sequence") or 0)

    if voter_gate:
        can_enter, enter_reason = gate_manager.can_enter(voter_id, voter_gate)
        if not can_enter:
            return {"ok": False, "detail": f"Gate vote denied: {enter_reason}"}

    reputation_ledger.register_node(voter_id, public_key, public_key_algo)
    stable_voter_id = voter_id
    try:
        import main as main_mod

        root_nid = main_mod._cached_root_node_id()
        if root_nid:
            stable_voter_id = root_nid
    except Exception:
        pass

    ok, cast_reason, weight = reputation_ledger.cast_vote(
        stable_voter_id,
        target,
        vote_val,
        voter_gate,
    )
    if ok:
        try:
            infonet.append(
                event_type="vote",
                node_id=voter_id,
                payload=normalized,
                signature=signature,
                sequence=sequence,
                public_key=public_key,
                public_key_algo=public_key_algo,
                protocol_version=str(signed.get("protocol_version") or PROTOCOL_VERSION),
            )
        except Exception as exc:
            logger.warning("vote recorded in ledger but infonet append failed: %s", exc)

    return {"ok": ok, "detail": cast_reason, "weight": round(float(weight or 0), 2)}


def _http_post_json(
    url: str,
    body: dict[str, Any],
    *,
    extra_headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    payload_bytes = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=payload_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {"ok": False, "detail": detail or f"http {exc.code}"}
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {"ok": False, "detail": "invalid json response"}


def _issue_sender_token_for_http_send(
    api_base: str,
    *,
    recipient: str,
    delivery: str,
    recipient_token: str,
) -> dict[str, Any]:
    extra_headers: dict[str, str] = {}
    admin_key = str(os.environ.get("ADMIN_KEY") or "").strip()
    if admin_key:
        extra_headers["X-Admin-Key"] = admin_key
    return _http_post_json(
        f"{api_base}/api/wormhole/dm/sender-token",
        {
            "recipient_id": recipient,
            "delivery_class": delivery,
            "recipient_token": recipient_token,
        },
        extra_headers=extra_headers or None,
    )


def _submit_signed_dm_send(
    *,
    recipient: str,
    delivery_class: str,
    recipient_token: str,
    ciphertext: str,
    payload_format: str,
    session_welcome: str = "",
    connect_intent: str = "",
    lookup_peer_url: str = "",
    peer_dh_pub: str = "",
) -> dict[str, Any]:
    import main as main_mod
    from services.mesh.mesh_protocol import (
        PROTOCOL_VERSION,
        SIGNED_CONTEXT_FIELD,
        build_signed_context,
    )
    from services.mesh.mesh_schema import validate_event_payload
    from services.mesh.mesh_wormhole_persona import get_dm_identity, sign_dm_wormhole_event
    from services.mesh.mesh_wormhole_sender_token import issue_wormhole_dm_sender_token

    delivery = str(delivery_class or "shared").strip().lower()
    identity = get_dm_identity()
    sender_id = str(identity.get("node_id") or "")
    msg_id = secrets.token_hex(16)
    timestamp = int(time.time())
    sequence = int(identity.get("sequence", 0) or 0) + 1

    dm_payload: dict[str, Any] = {
        "recipient_id": recipient,
        "delivery_class": delivery,
        "recipient_token": str(recipient_token or ""),
        "ciphertext": str(ciphertext or ""),
        "msg_id": msg_id,
        "timestamp": timestamp,
        "format": str(payload_format or "mls1"),
        "transport_lock": "private_strong",
    }
    if session_welcome:
        dm_payload["session_welcome"] = str(session_welcome)

    try:
        from services.config import get_settings
        from services.mesh.mesh_wormhole_seal import build_sender_seal

        if (
            delivery == "shared"
            and bool(get_settings().MESH_DM_REQUIRE_SENDER_SEAL_SHARED)
            and not str(dm_payload.get("sender_seal", "") or "").strip()
        ):
            seal = build_sender_seal(
                recipient_id=recipient,
                recipient_dh_pub=str(peer_dh_pub or ""),
                msg_id=msg_id,
                timestamp=timestamp,
            )
            if seal.get("ok"):
                dm_payload["sender_seal"] = str(seal.get("sender_seal") or "")
    except Exception:
        pass

    ok_payload, reason = validate_event_payload("dm_message", dm_payload)
    if not ok_payload:
        return {"ok": False, "detail": reason}

    dm_payload[SIGNED_CONTEXT_FIELD] = build_signed_context(
        event_type="dm_message",
        kind="dm_send",
        endpoint="/api/mesh/dm/send",
        lane_floor="private_strong",
        sequence_domain="dm_send",
        node_id=sender_id,
        sequence=sequence,
        payload=dm_payload,
        recipient_id=recipient,
    )
    signed = sign_dm_wormhole_event(
        event_type="dm_message",
        payload=dm_payload,
        sequence=sequence,
    )
    if not signed.get("ok", True):
        return signed

    body = {
        "sender_id": sender_id,
        "sender_token": "",
        "recipient_id": recipient,
        "delivery_class": delivery,
        "recipient_token": str(recipient_token or ""),
        "ciphertext": str(ciphertext or ""),
        "format": str(payload_format or "mls1"),
        "transport_lock": "private_strong",
        "session_welcome": str(session_welcome or ""),
        "msg_id": msg_id,
        "timestamp": timestamp,
        "sender_seal": str(dm_payload.get("sender_seal") or ""),
        "public_key": str(signed.get("public_key") or ""),
        "public_key_algo": str(signed.get("public_key_algo") or ""),
        "signature": str(signed.get("signature") or ""),
        "sequence": int(signed.get("sequence") or 0),
        "protocol_version": str(signed.get("protocol_version") or PROTOCOL_VERSION),
        "signed_context": dict(dm_payload.get(SIGNED_CONTEXT_FIELD) or {}),
    }
    normalized_intent = str(connect_intent or "").strip().lower()
    normalized_lookup_peer = str(lookup_peer_url or "").strip().rstrip("/")
    if normalized_intent:
        body["connect_intent"] = normalized_intent
    if normalized_lookup_peer:
        body["lookup_peer_url"] = normalized_lookup_peer

    api_base = str(os.environ.get("SB_API_BASE", "http://127.0.0.1:8000") or "http://127.0.0.1:8000").rstrip("/")
    result: dict[str, Any] = {"ok": False, "detail": "dm send failed"}
    try:
        import urllib.error

        if delivery in ("request", "shared"):
            issued = _issue_sender_token_for_http_send(
                api_base,
                recipient=recipient,
                delivery=delivery,
                recipient_token=str(recipient_token or ""),
            )
            if not issued.get("ok"):
                return issued
            body["sender_token"] = str(issued.get("sender_token") or "")

        result = _http_post_json(f"{api_base}/api/mesh/dm/send", body)
    except (urllib.error.URLError, TimeoutError):
        if delivery in ("request", "shared"):
            issued = issue_wormhole_dm_sender_token(
                recipient_id=recipient,
                delivery_class=delivery,
                recipient_token=str(recipient_token or ""),
            )
            if not issued.get("ok"):
                return issued
            body["sender_token"] = str(issued.get("sender_token") or "")

        async def _send():
            import json as _json

            raw = _json.dumps(body).encode("utf-8")

            async def receive():
                return {"type": "http.request", "body": raw, "more_body": False}

            req = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/api/mesh/dm/send",
                    "headers": [(b"content-type", b"application/json")],
                    "client": ("127.0.0.1", 52421),
                },
                receive,
            )
            req.state._private_lane_current_tier = "private_strong"
            req.state._transport_tier = "private_strong"
            return await main_mod.dm_send(req)

        result = _run_async(_send())
    except Exception as exc:
        result = {"ok": False, "detail": str(exc) or type(exc).__name__}
    if isinstance(result, dict):
        result.setdefault("msg_id", msg_id)
        result.setdefault("sender_id", sender_id)
        result.setdefault("recipient_id", recipient)
    return result


def send_contact_request(
    *,
    lookup_token: str = "",
    peer_id: str = "",
    note: str = "",
    lookup_peer_url: str = "",
    cached_prekey_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a first-contact request using a short address or peer id."""
    from services.mesh.mesh_wormhole_dead_drop import build_contact_offer
    from services.mesh.mesh_wormhole_persona import get_dm_identity
    from services.mesh.mesh_wormhole_prekey import bootstrap_encrypt_for_peer, fetch_dm_prekey_bundle

    token = str(lookup_token or "").strip()
    peer = str(peer_id or "").strip()
    if not token and not peer:
        return {"ok": False, "detail": "lookup_token or peer_id required"}

    preferred_peer = str(lookup_peer_url or "").strip().rstrip("/")
    if cached_prekey_bundle and cached_prekey_bundle.get("ok"):
        bundle = dict(cached_prekey_bundle)
    else:
        bundle = fetch_dm_prekey_bundle(
            agent_id=peer if not token else "",
            lookup_token=token,
            lookup_peer_urls=[preferred_peer] if preferred_peer else None,
        )
    if not bundle.get("ok"):
        return bundle
    recipient = str(bundle.get("agent_id") or peer).strip()
    if not recipient:
        return {"ok": False, "detail": "recipient unresolved"}

    identity = get_dm_identity()
    offer = build_contact_offer(
        dh_pub_key=str(identity.get("dh_pub_key") or ""),
        dh_algo=str(identity.get("dh_algo") or "X25519"),
        geo_hint=str(note or ""),
    )
    encrypted = bootstrap_encrypt_for_peer(
        recipient,
        offer,
        fetched_bundle=bundle,
    )
    if not encrypted.get("ok"):
        return encrypted

    return _submit_signed_dm_send(
        recipient=recipient,
        delivery_class="request",
        recipient_token="",
        ciphertext=str(encrypted.get("result") or ""),
        payload_format="mls1",
        connect_intent="contact_request",
        lookup_peer_url=preferred_peer,
    )


def send_contact_accept(
    *,
    peer_id: str,
    peer_dh_pub: str = "",
    lookup_token: str = "",
    lookup_peer_url: str = "",
) -> dict[str, Any]:
    """Accept a pending contact request and open the shared DM lane."""
    from services.mesh.mesh_wormhole_dead_drop import build_contact_accept, issue_pairwise_dm_alias
    from services.mesh.mesh_wormhole_prekey import bootstrap_encrypt_for_peer, fetch_dm_prekey_bundle

    peer = str(peer_id or "").strip()
    if not peer:
        return {"ok": False, "detail": "peer_id required"}

    token = str(lookup_token or "").strip()
    preferred_peer = str(lookup_peer_url or "").strip().rstrip("/")
    dh_pub = str(peer_dh_pub or "").strip()
    if not dh_pub:
        bundle = fetch_dm_prekey_bundle(
            agent_id=peer if not token else "",
            lookup_token=token,
            lookup_peer_urls=[preferred_peer] if preferred_peer else None,
        )
        if not bundle.get("ok"):
            return bundle
        dh_pub = str(bundle.get("dh_pub_key") or "").strip()
    if not dh_pub:
        return {"ok": False, "detail": "peer dh_pub_key unavailable"}

    alias = issue_pairwise_dm_alias(peer_id=peer, peer_dh_pub=dh_pub)
    if not alias.get("ok"):
        return alias
    shared_alias = str(alias.get("shared_alias") or "").strip()
    if not shared_alias:
        return {"ok": False, "detail": "shared_alias unavailable"}

    accept_plain = build_contact_accept(shared_alias=shared_alias)
    encrypted = bootstrap_encrypt_for_peer(peer, accept_plain, lookup_token=token)
    if not encrypted.get("ok"):
        return encrypted

    sent = _submit_signed_dm_send(
        recipient=peer,
        delivery_class="request",
        recipient_token="",
        ciphertext=str(encrypted.get("result") or ""),
        payload_format="mls1",
        connect_intent="contact_accept",
        lookup_peer_url=preferred_peer,
    )
    if isinstance(sent, dict):
        sent.setdefault("shared_alias", shared_alias)
    return sent


def send_dm(
    peer_id: str,
    plaintext: str,
    *,
    delivery_class: str = "shared",
    recipient_token: str = "",
) -> dict[str, Any]:
    """Compose and send an encrypted DM on behalf of the operator."""
    import main as main_mod

    recipient = str(peer_id or "").strip()
    if not recipient:
        return {"ok": False, "detail": "peer_id required"}
    if not str(plaintext or "").strip():
        return {"ok": False, "detail": "plaintext required"}

    delivery = str(delivery_class or "shared").strip().lower()
    if delivery not in ("shared", "request"):
        return {"ok": False, "detail": "delivery_class must be shared or request"}

    composed = main_mod.compose_wormhole_dm(
        peer_id=recipient,
        peer_dh_pub="",
        plaintext=str(plaintext),
    )
    if not composed.get("ok"):
        return composed

    return _submit_signed_dm_send(
        recipient=recipient,
        delivery_class=delivery,
        recipient_token=str(recipient_token or ""),
        ciphertext=str(composed.get("ciphertext") or ""),
        payload_format=str(composed.get("format") or "mls1"),
        session_welcome=str(composed.get("session_welcome") or ""),
    )


def poll_dms(*, limit: int = 20) -> dict[str, Any]:
    """Poll encrypted DMs for the operator DM identity."""
    import json

    import main as main_mod
    from services.mesh.mesh_protocol import PROTOCOL_VERSION
    from services.mesh.mesh_wormhole_persona import get_dm_identity, sign_dm_wormhole_event

    identity = get_dm_identity()
    agent_id = str(identity.get("node_id") or "")
    if not agent_id:
        return {"ok": False, "detail": "dm identity is not configured"}

    poll_payload = {"mailbox_claims": [], "agent_id": agent_id}
    signed = sign_dm_wormhole_event(event_type="dm_poll", payload=poll_payload)
    if not signed.get("ok", True):
        return signed

    body = {
        "agent_id": agent_id,
        "mailbox_claims": [],
        "timestamp": int(time.time()),
        "nonce": secrets.token_hex(8),
        "public_key": str(signed.get("public_key") or ""),
        "public_key_algo": str(signed.get("public_key_algo") or ""),
        "signature": str(signed.get("signature") or ""),
        "sequence": int(signed.get("sequence") or 0),
        "protocol_version": str(signed.get("protocol_version") or PROTOCOL_VERSION),
    }

    raw = json.dumps(body).encode("utf-8")

    async def _poll():
        async def receive():
            return {"type": "http.request", "body": raw, "more_body": False}

        req = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/mesh/dm/poll",
                "headers": [(b"content-type", b"application/json")],
                "client": ("127.0.0.1", 52421),
            },
            receive,
        )
        return await main_mod.dm_poll_secure(req)

    result = _run_async(_poll())
    if isinstance(result, dict):
        messages = list(result.get("messages") or [])
        if limit and len(messages) > int(limit):
            result = dict(result)
            result["messages"] = messages[: int(limit)]
            result["count"] = len(result["messages"])
    return result if isinstance(result, dict) else {"ok": False, "detail": "dm poll failed"}
