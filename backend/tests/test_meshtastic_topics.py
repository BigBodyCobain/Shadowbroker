from services.mesh.meshtastic_topics import (
    build_subscription_topics,
    normalize_root,
    parse_topic_metadata,
)


def test_normalize_root_accepts_custom_subroots():
    assert normalize_root("msh/US/rob/snd/#") == "US/rob/snd"
    assert normalize_root(" PL ") == "PL"


def test_build_subscription_topics_keeps_defaults_and_extras():
    topics = build_subscription_topics(extra_roots="PL,US/rob/snd", extra_topics="msh/+/2/json/#")
    assert "msh/US/#" in topics
    assert "msh/PL/#" in topics
    assert "msh/US/rob/snd/#" in topics
    assert "msh/+/2/json/#" in topics


def test_parse_topic_metadata_preserves_root_and_channel():
    meta = parse_topic_metadata("msh/US/rob/snd/2/e/LongFast/!abcd1234")
    assert meta == {
        "region": "US",
        "root": "US/rob/snd",
        "channel": "LongFast",
        "mode": "e",
        "version": "2",
    }


def test_parse_topic_metadata_handles_json_topics():
    meta = parse_topic_metadata("msh/PL/2/json/PKI/!cafefeed")
    assert meta["region"] == "PL"
    assert meta["root"] == "PL"
    assert meta["channel"] == "PKI"
    assert meta["mode"] == "json"
