import json

import pytest

from services import qazlake_shadow_feed as feed


def test_client_is_dormant_without_explicit_modes(monkeypatch) -> None:
    monkeypatch.delenv("SHADOW_LAYER_SOURCE_MODES", raising=False)
    payload = {"earthquakes": [{"id": "local-1"}]}

    assert feed.configured_modes() == {}
    assert feed.apply_layer_source_modes(payload, endpoint="slow") is payload


def test_invalid_or_local_modes_do_not_activate_client(monkeypatch) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES",
        json.dumps(
            {
                "geohazards": "local",
                "aviation_public": "unexpected",
                "weather_environment": "compare",
            }
        ),
    )

    assert feed.configured_modes() == {"weather_environment": "compare"}


def test_explicit_cutover_configuration_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"geohazards": "qazpipe"})
    )
    monkeypatch.delenv("QAZLAKE_SHADOW_FEED_URL", raising=False)
    monkeypatch.delenv("QAZLAKE_SHADOW_FEED_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="URL/token"):
        feed.validate_shadow_feed_configuration()


def test_cutover_configuration_rejects_private_or_unknown_family(monkeypatch) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"operator_private": "qazpipe"})
    )

    with pytest.raises(RuntimeError, match="unsupported Shadow source families"):
        feed.validate_shadow_feed_configuration()


def test_cutover_configuration_requires_https_outside_localhost(monkeypatch) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"geohazards": "compare"})
    )
    monkeypatch.setenv("QAZLAKE_SHADOW_FEED_URL", "http://qazlake.internal")
    monkeypatch.setenv("QAZLAKE_SHADOW_FEED_TOKEN", "shadow-feed-token")

    with pytest.raises(RuntimeError, match="HTTPS"):
        feed.validate_shadow_feed_configuration()


def test_local_collection_stops_only_after_family_cutover(monkeypatch) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES",
        json.dumps(
            {
                "geohazards": "compare",
                "transport_public": "qazpipe",
            }
        ),
    )

    assert feed.local_collection_allowed("geohazards") is True
    assert feed.local_collection_allowed("transport_public") is False
    assert feed.local_collection_allowed("operator_private") is True


def test_compare_preserves_public_payload_and_records_receipt(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"geohazards": "compare"})
    )
    receipt_path = tmp_path / "receipts.jsonl"
    monkeypatch.setenv("SHADOW_QAZPIPE_COMPARE_RECEIPT_PATH", str(receipt_path))
    monkeypatch.setattr(
        feed,
        "_items_by_family",
        lambda: {"geohazards": {"earthquakes": [{"id": "candidate-1"}]}},
    )
    with feed._lock:
        feed._state.update(
            {
                "entities": {"candidate-1": {}},
                "stale": False,
                "watermark": {"cursor": 7},
            }
        )
    local = [{"id": "local-1"}]
    payload = {"earthquakes": local}

    result = feed.apply_layer_source_modes(payload, endpoint="slow")

    assert result == {"earthquakes": local}
    assert result["earthquakes"] is local
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "shadow.qazpipe-comparison-receipt/v1"
    assert receipt["accepted"] is False
    assert "canonical_identity" in receipt["failed_gates"]


def test_qazpipe_mode_never_hides_failure_with_local_fallback(monkeypatch) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"geohazards": "qazpipe"})
    )
    monkeypatch.setattr(feed, "_items_by_family", dict)
    with feed._lock:
        feed._state.update({"entities": {}, "stale": True, "watermark": None})

    result = feed.apply_layer_source_modes(
        {"earthquakes": [{"id": "old-local"}]}, endpoint="slow"
    )

    assert result["earthquakes"] == []
    assert result["qazpipe_state"]["status"] == "stale"
    assert result["qazpipe_state"]["available"] is False


def test_transport_cutover_preserves_legacy_layer_shape(monkeypatch) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"transport_public": "qazpipe"})
    )
    monkeypatch.setattr(
        feed,
        "_items_by_family",
        lambda: {
            "transport_public": {
                "trains": [{"id": "train:2026-08-28:1", "speed_mps": 30.0}]
            }
        },
    )
    with feed._lock:
        feed._state.update(
            {
                "entities": {"train:2026-08-28:1": {}},
                "stale": False,
                "watermark": {"cursor": 42},
            }
        )

    result = feed.apply_layer_source_modes(
        {"trains": [{"id": "local-train"}]}, endpoint="fast"
    )

    assert result["trains"] == [{"id": "train:2026-08-28:1", "speed_mps": 30.0}]
    assert result["qazpipe_state"]["status"] == "current"


def test_projection_filters_storage_and_provider_fields() -> None:
    result = feed._public_item(
        {
            "entity_id": "quake-1",
            "provider_id": "internal-provider",
            "source_id": "internal-source",
            "collection_receipt_id": "receipt-1",
            "payload_hash_sha256": "a" * 64,
            "properties": {
                "layer_family": "geohazards",
                "layer_key": "earthquakes",
                "magnitude": 4.2,
                "raw_payload": {"secret": True},
                "source_url": "https://internal.invalid/source",
            },
            "latitude": 43.2,
            "longitude": 76.9,
            "observed_at": "2026-08-28T00:00:00Z",
        }
    )

    assert result["id"] == "quake-1"
    assert result["mag"] == 4.2
    assert result["lat"] == 43.2
    assert result["lng"] == 76.9
    assert {
        "provider_id",
        "source_id",
        "collection_receipt_id",
        "payload_hash_sha256",
        "raw_payload",
        "source_url",
    }.isdisjoint(result)
