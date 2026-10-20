#!/usr/bin/env python3
"""Print DM readiness: identities, contacts, peers, transport."""
from __future__ import annotations

import json


def main() -> None:
    out: dict = {"ok": True}

    try:
        from services.wormhole_supervisor import get_wormhole_state, get_transport_tier

        out["wormhole"] = get_wormhole_state()
        out["transport_tier"] = get_transport_tier()
    except Exception as exc:
        out["wormhole_error"] = str(exc)

    try:
        from services.mesh.mesh_wormhole_persona import get_dm_identity

        out["dm_identity"] = get_dm_identity()
    except Exception as exc:
        out["dm_identity_error"] = str(exc)

    try:
        from services.mesh.mesh_wormhole_contacts import list_wormhole_dm_contacts

        contacts = list_wormhole_dm_contacts()
        out["dm_contacts"] = {
            k: {
                "trustLevel": v.get("trustLevel"),
                "dmIdentityId": v.get("dmIdentityId"),
                "invitePinnedPrekeyLookupHandle": bool(v.get("invitePinnedPrekeyLookupHandle")),
                "verifiedFirstContact": v.get("verifiedFirstContact"),
                "remotePrekeyLookupMode": v.get("remotePrekeyLookupMode"),
            }
            for k, v in (contacts or {}).items()
        }
        out["dm_contact_count"] = len(contacts or {})
    except Exception as exc:
        out["dm_contacts_error"] = str(exc)

    try:
        import main as main_mod

        out["local_onion"] = main_mod._local_infonet_peer_url()
        out["node_enabled"] = main_mod._participant_node_enabled()
        out["arti_ready"] = main_mod._check_arti_ready()
        out["push_peers"] = main_mod._filter_infonet_peer_urls(
            __import__(
                "services.mesh.mesh_router", fromlist=["authenticated_push_peer_urls"]
            ).authenticated_push_peer_urls()
        )
    except Exception as exc:
        out["peer_runtime_error"] = str(exc)

    try:
        from services.mesh.mesh_private_outbox import private_delivery_outbox

        pending = private_delivery_outbox.list_items(exposure="ordinary")
        dm_pending = [i for i in pending if str(i.get("lane", "")) == "dm"]
        out["dm_outbox_pending"] = len(dm_pending)
        out["dm_outbox_samples"] = [
            {
                "id": i.get("id"),
                "release_state": i.get("release_state"),
                "status": (i.get("status") or {}).get("code"),
                "recipient_id": (i.get("payload") or {}).get("recipient_id"),
            }
            for i in dm_pending[:5]
        ]
    except Exception as exc:
        out["outbox_error"] = str(exc)

    try:
        from services.mesh.mesh_dm_relay import dm_relay

        out["dm_relay_stats"] = dict(dm_relay._stats)
        out["dm_mailbox_keys"] = len(dm_relay._mailboxes)
    except Exception as exc:
        out["relay_error"] = str(exc)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
