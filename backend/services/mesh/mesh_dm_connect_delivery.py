"""Invite-scoped DM connect delivery: auto relay release and contact severance."""

from __future__ import annotations

from typing import Any

CONNECT_AUTO_RELEASE_INTENTS = frozenset(
    {
        "invite_short_address",
        "invite_import",
        "contact_request",
        "contact_accept",
        "contact_offer",
    }
)

INVITE_CONNECT_TRUST_LEVELS = frozenset({"invite_pinned", "sas_verified"})


def _release_profile() -> str:
    try:
        from services.release_profiles import current_release_profile

        return str(current_release_profile() or "dev")
    except Exception:
        return "dev"


def grant_connect_relay_policy(
    recipient_id: str,
    *,
    reason: str = "connect_scoped_auto_release",
) -> dict[str, Any]:
    """Pre-authorize hidden relay delivery for an explicit connect target."""
    peer_key = str(recipient_id or "").strip()
    if not peer_key:
        return {"ok": False, "detail": "recipient_id required"}
    try:
        from services.mesh.mesh_relay_policy import grant_relay_policy

        return grant_relay_policy(
            scope_type="dm_contact",
            scope_id=peer_key,
            profile=_release_profile(),
            hidden_transport_required=True,
            reason=str(reason or "connect_scoped_auto_release"),
        )
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def revoke_connect_relay_policy(recipient_id: str) -> dict[str, Any]:
    peer_key = str(recipient_id or "").strip()
    if not peer_key:
        return {"ok": False, "detail": "recipient_id required"}
    try:
        from services.mesh.mesh_relay_policy import revoke_relay_policy

        revoked = int(
            revoke_relay_policy(
                scope_type="dm_contact",
                scope_id=peer_key,
                profile=_release_profile(),
            )
            or 0
        )
        return {"ok": True, "revoked": revoked}
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def recipient_has_invite_connect_scope(recipient_id: str) -> bool:
    peer_key = str(recipient_id or "").strip()
    if not peer_key:
        return False
    try:
        from services.mesh.mesh_wormhole_contacts import get_wormhole_dm_contact

        contact = get_wormhole_dm_contact(peer_key) or {}
    except Exception:
        return False
    if str(contact.get("invitePinnedPrekeyLookupHandle", "") or "").strip():
        return True
    if str(contact.get("invitePinnedLookupPeerUrl", "") or "").strip():
        return True
    trust = str(contact.get("trust_level", "") or "").strip().lower()
    return trust in INVITE_CONNECT_TRUST_LEVELS


def relay_push_peer_urls_for_payload(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for raw in list(payload.get("relay_push_peer_urls") or []):
        normalized = str(raw or "").strip().rstrip("/")
        if normalized and normalized not in urls:
            urls.append(normalized)
    lookup_peer_url = str(payload.get("lookup_peer_url", "") or "").strip().rstrip("/")
    if lookup_peer_url:
        urls = [url for url in urls if url != lookup_peer_url]
        urls.insert(0, lookup_peer_url)
    recipient_id = str(payload.get("recipient_id", "") or "").strip()
    if recipient_id and not urls:
        try:
            from services.mesh.mesh_wormhole_contacts import get_wormhole_dm_contact

            contact = get_wormhole_dm_contact(recipient_id) or {}
            pinned = str(contact.get("invitePinnedLookupPeerUrl", "") or "").strip().rstrip("/")
            if pinned:
                urls.append(pinned)
        except Exception:
            pass
    return urls


def should_auto_release_dm_payload(payload: dict[str, Any]) -> bool:
    if str(payload.get("delivery_class", "") or "").strip().lower() != "request":
        return False
    intent = str(payload.get("connect_intent", "") or "").strip().lower()
    if intent in CONNECT_AUTO_RELEASE_INTENTS:
        return True
    if str(payload.get("lookup_peer_url", "") or "").strip():
        return True
    recipient_id = str(payload.get("recipient_id", "") or "").strip()
    return bool(recipient_id and recipient_has_invite_connect_scope(recipient_id))


def enrich_connect_release_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach invite-owner relay hints used during private release."""
    enriched = dict(payload or {})
    recipient_id = str(enriched.get("recipient_id", "") or "").strip()
    lookup_peer_url = str(enriched.get("lookup_peer_url", "") or "").strip().rstrip("/")
    if not lookup_peer_url and recipient_id:
        try:
            from services.mesh.mesh_wormhole_contacts import get_wormhole_dm_contact

            contact = get_wormhole_dm_contact(recipient_id) or {}
            lookup_peer_url = str(contact.get("invitePinnedLookupPeerUrl", "") or "").strip().rstrip("/")
        except Exception:
            lookup_peer_url = ""
    if lookup_peer_url:
        enriched["lookup_peer_url"] = lookup_peer_url
    push_urls = relay_push_peer_urls_for_payload(enriched)
    if push_urls:
        enriched["relay_push_peer_urls"] = push_urls
    return enriched


def auto_release_connect_dm_outbox(*, outbox_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Grant scoped relay policy and approve release for invite-scoped connect traffic."""
    normalized_outbox = str(outbox_id or "").strip()
    enriched = enrich_connect_release_payload(payload)
    if not normalized_outbox:
        return {"ok": False, "detail": "missing outbox_id"}
    if not should_auto_release_dm_payload(enriched):
        return {"ok": True, "skipped": True, "reason": "not_connect_scoped"}
    recipient_id = str(enriched.get("recipient_id", "") or "").strip()
    if not recipient_id:
        return {"ok": False, "detail": "missing recipient_id"}
    grant = grant_connect_relay_policy(recipient_id)
    try:
        from services.mesh.mesh_private_outbox import private_delivery_outbox
        from services.mesh.mesh_private_release_worker import private_release_worker

        private_delivery_outbox.approve_relay_release(normalized_outbox)
        private_release_worker.ensure_started()
        private_release_worker.wake()
    except Exception as exc:
        return {
            "ok": False,
            "detail": str(exc) or type(exc).__name__,
            "grant": grant,
        }
    return {
        "ok": True,
        "auto_released": True,
        "outbox_id": normalized_outbox,
        "recipient_id": recipient_id,
        "grant": grant,
        "relay_push_peer_urls": relay_push_peer_urls_for_payload(enriched),
    }
