from __future__ import annotations

from services.mesh import mesh_dm_connect_delivery as connect


def test_should_auto_release_for_connect_intent():
    payload = {
        "delivery_class": "request",
        "connect_intent": "contact_request",
        "recipient_id": "!sb_peer",
    }
    assert connect.should_auto_release_dm_payload(payload) is True


def test_should_auto_release_for_lookup_peer_url():
    payload = {
        "delivery_class": "request",
        "lookup_peer_url": "http://owner.onion:8000",
        "recipient_id": "!sb_peer",
    }
    assert connect.should_auto_release_dm_payload(payload) is True


def test_should_not_auto_release_shared_lane():
    payload = {
        "delivery_class": "shared",
        "connect_intent": "contact_request",
        "recipient_id": "!sb_peer",
    }
    assert connect.should_auto_release_dm_payload(payload) is False


def test_enrich_connect_release_payload_prefers_explicit_lookup():
    enriched = connect.enrich_connect_release_payload(
        {
            "recipient_id": "!sb_peer",
            "lookup_peer_url": "http://owner.onion:8000/",
        }
    )
    assert enriched["lookup_peer_url"] == "http://owner.onion:8000"
    assert enriched["relay_push_peer_urls"] == ["http://owner.onion:8000"]


def test_relay_push_peer_urls_dedupes_and_prioritizes_lookup():
    urls = connect.relay_push_peer_urls_for_payload(
        {
            "lookup_peer_url": "http://owner.onion:8000",
            "relay_push_peer_urls": ["http://relay.onion:8000", "http://owner.onion:8000"],
        }
    )
    assert urls[0] == "http://owner.onion:8000"
    assert "http://relay.onion:8000" in urls
    assert len(urls) == 2
