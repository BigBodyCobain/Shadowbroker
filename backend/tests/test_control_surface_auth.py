"""Regression coverage for operator-only control surfaces."""

import pytest


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/wormhole/identity", None),
        ("post", "/api/wormhole/identity/bootstrap", {}),
        ("post", "/api/wormhole/gate/enter", {"gate_id": "general-talk"}),
        ("post", "/api/wormhole/gate/leave", {"gate_id": "general-talk"}),
        ("post", "/api/wormhole/sign", {"event_type": "gate_event", "payload": {"ok": True}}),
        ("post", "/api/wormhole/gate/key/rotate", {"gate_id": "general-talk", "reason": "test"}),
        (
            "post",
            "/api/wormhole/gate/key/grant",
            {
                "gate_id": "general-talk",
                "recipient_node_id": "node-test",
                "recipient_dh_pub": "dh-test",
            },
        ),
        ("post", "/api/wormhole/gate/persona/create", {"gate_id": "general-talk", "label": "test"}),
        (
            "post",
            "/api/wormhole/gate/persona/activate",
            {"gate_id": "general-talk", "persona_id": "persona-test"},
        ),
        ("post", "/api/wormhole/gate/persona/clear", {"gate_id": "general-talk"}),
        (
            "post",
            "/api/wormhole/gate/persona/retire",
            {"gate_id": "general-talk", "persona_id": "persona-test"},
        ),
        (
            "post",
            "/api/wormhole/gate/message/sign-encrypted",
            {
                "gate_id": "general-talk",
                "epoch": 1,
                "ciphertext": "ciphertext",
                "nonce": "nonce",
                "format": "mls1",
                "envelope_hash": "hash",
            },
        ),
        ("post", "/api/wormhole/gate/message/compose", {"gate_id": "general-talk", "plaintext": "hello"}),
        ("post", "/api/wormhole/sign-raw", {"message": "raw"}),
        ("post", "/api/wormhole/gate/state/export", {"gate_id": "general-talk"}),
        ("post", "/api/wormhole/gate/proof", {"gate_id": "general-talk"}),
        ("post", "/api/wormhole/connect", {}),
        ("post", "/api/layers", {"layers": {"viirs_nightlights": True}}),
        ("post", "/api/ais/feed", {"msgs": []}),
        # Added in post-#227 gap audit:
        # /api/wormhole/join also calls bootstrap_wormhole_identity() — same
        # identity-takeover surface as /identity/bootstrap. PR #227 hardened
        # the latter but missed the former.
        ("post", "/api/wormhole/join", {}),
        # /api/sigint/transmit relays APRS-IS packets over radio using
        # operator-supplied credentials. Any caller who reaches this endpoint
        # could transmit on the operator's authority. Must be local-only.
        (
            "post",
            "/api/sigint/transmit",
            {
                "callsign": "N0CALL",
                "passcode": "12345",
                "target": "NOCALL",
                "message": "test",
            },
        ),
        # Issue #198 (tg12, May 17): three gate introspection GETs leak the
        # operator's active persona, persona inventory, and key status for
        # any gate_id an anonymous caller knows. Defeats the unlinkability
        # property documented in the privacy threat model.
        ("get", "/api/wormhole/gate/general-talk/identity", None),
        ("get", "/api/wormhole/gate/general-talk/personas", None),
        ("get", "/api/wormhole/gate/general-talk/key", None),
        # Issue #211 (tg12): /api/thermal/verify fans out into an expensive
        # STAC search + remote SWIR raster reads. Unauthenticated abuse
        # could burn Sentinel-Hub quota and outbound bandwidth.
        ("get", "/api/thermal/verify?lat=0&lng=0&radius_km=10", None),
        # Issue #213 (tg12): /api/radio/openmhz/calls/{sys_name} — rotating
        # sys_name bypasses the 20s cache and hammers OpenMHZ. Risks an
        # IP-ban for the project.
        ("get", "/api/radio/openmhz/calls/abc", None),
        # Issue #214 (tg12): /api/radio/openmhz/audio — anonymous bandwidth
        # relay through the backend. 60/minute rate limit is not enough on
        # a streaming endpoint.
        ("get", "/api/radio/openmhz/audio?url=https%3A%2F%2Fmedia.openmhz.com%2Faudio%2Fabc.mp3", None),
    ],
)
def test_remote_control_surface_rejects_without_local_operator_or_admin(
    remote_client, method, path, payload
):
    request = getattr(remote_client, method)
    response = request(path, json=payload) if payload is not None else request(path)

    assert response.status_code == 403


def test_remote_agent_actions_poll_rejects_without_local_operator_or_admin(remote_client):
    response = remote_client.get("/api/ai/agent-actions")

    assert response.status_code == 403
