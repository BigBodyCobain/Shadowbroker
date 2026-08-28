import json

from services import qazlake_shadow_feed as feed


def test_qazpipe_mode_never_falls_back_to_local(monkeypatch) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"earthquakes": "qazpipe"})
    )
    monkeypatch.setattr(feed, "_items_by_family", dict)
    with feed._lock:
        feed._state.update({"entities": {}, "stale": True, "watermark": None})
    payload = feed.apply_layer_source_modes(
        {"earthquakes": [{"id": "old-local"}]}, endpoint="slow"
    )
    assert payload["earthquakes"] == []
    assert payload["qazpipe_state"]["status"] == "stale"


def test_compare_preserves_public_payload_and_records_receipt(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"earthquakes": "compare"})
    )
    monkeypatch.setenv(
        "SHADOW_QAZPIPE_COMPARE_RECEIPT_PATH", str(tmp_path / "receipts.jsonl")
    )
    monkeypatch.setattr(
        feed,
        "_items_by_family",
        lambda: {"earthquakes": {"earthquakes": [{"id": "q-1"}]}},
    )
    with feed._lock:
        feed._state.update(
            {"entities": {"q-1": {}}, "stale": False, "watermark": {"cursor": 7}}
        )
    local = [{"id": "local-1"}]
    original = {"earthquakes": local}
    payload = feed.apply_layer_source_modes(original, endpoint="slow")
    assert payload == {"earthquakes": local}
    assert payload["earthquakes"] is local
    receipt = json.loads((tmp_path / "receipts.jsonl").read_text().strip())
    assert receipt["layer_family"] == "earthquakes"
    assert receipt["layer_key"] == "earthquakes"
    assert receipt["local_count"] == 1
    assert receipt["qazlake_count"] == 1
    assert receipt["accepted"] is False
    assert "canonical_identity" in receipt["failed_gates"]


def test_compare_preserves_public_payload_when_receipt_is_unwritable(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"earthquakes": "compare"})
    )
    monkeypatch.setenv("SHADOW_QAZPIPE_COMPARE_RECEIPT_PATH", str(tmp_path))
    monkeypatch.setattr(
        feed,
        "_items_by_family",
        lambda: {"earthquakes": {"earthquakes": [{"id": "q-1"}]}},
    )
    with feed._lock:
        feed._state.update(
            {"entities": {"q-1": {}}, "stale": False, "watermark": {"cursor": 7}}
        )
    local = [{"id": "local-1"}]
    payload = feed.apply_layer_source_modes({"earthquakes": local}, endpoint="slow")
    assert payload == {"earthquakes": local}


def test_deterministic_comparison_requires_exact_ids_and_counts(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"earthquakes": "compare"})
    )
    monkeypatch.setenv(
        "SHADOW_COMPARE_FAMILY_KINDS", json.dumps({"earthquakes": "deterministic"})
    )
    monkeypatch.setenv(
        "SHADOW_COMPARE_REQUIRED_FIELDS", json.dumps({"earthquakes": ["magnitude"]})
    )
    monkeypatch.setenv(
        "SHADOW_COMPARE_CADENCE_SECONDS", json.dumps({"earthquakes": 3600})
    )
    monkeypatch.setenv(
        "SHADOW_QAZPIPE_COMPARE_RECEIPT_PATH", str(tmp_path / "receipt.jsonl")
    )
    rows = [
        {
            "id": "q-1",
            "magnitude": 4.2,
            "observed_at": "2026-08-28T00:00:00Z",
        }
    ]
    monkeypatch.setattr(
        feed,
        "_items_by_family",
        lambda: {"earthquakes": {"earthquakes": rows}},
    )
    with feed._lock:
        feed._state.update(
            {"entities": {"q-1": {}}, "stale": False, "watermark": {"cursor": 7}}
        )
    feed.apply_layer_source_modes({"earthquakes": list(rows)}, endpoint="slow")
    receipt = json.loads((tmp_path / "receipt.jsonl").read_text().strip())
    assert receipt["canonical_ids_exact"] is True
    assert receipt["required_null_rate_delta"] == 0
    assert receipt["watermark_valid"] is True
    assert receipt["accepted"] is True


def test_family_mode_maps_to_existing_public_layer_keys(monkeypatch) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"geohazards": "qazpipe"})
    )
    monkeypatch.setattr(
        feed,
        "_items_by_family",
        lambda: {
            "geohazards": {
                "earthquakes": [{"id": "eq-1"}],
                "volcanoes": [{"id": "volcano-1"}],
            }
        },
    )
    with feed._lock:
        feed._state.update(
            {"entities": {"eq-1": {}}, "stale": False, "watermark": {"cursor": 8}}
        )
    payload = feed.apply_layer_source_modes(
        {"earthquakes": [{"id": "local"}], "volcanoes": [], "unrelated": [1]},
        endpoint="slow",
    )
    assert payload["earthquakes"] == [{"id": "eq-1"}]
    assert payload["volcanoes"] == [{"id": "volcano-1"}]
    assert payload["unrelated"] == [1]
    assert "geohazards" not in payload


def test_public_projection_does_not_expose_provider_or_receipt() -> None:
    item = feed._public_item(
        {
            "entity_id": "entity-1",
            "provider_id": "private-provider",
            "source_id": "source",
            "collection_receipt_id": "receipt",
            "payload_hash_sha256": "a" * 64,
            "properties": {"layer_family": "earthquakes", "magnitude": 4.2},
            "latitude": 43.2,
            "longitude": 76.9,
            "observed_at": "2026-08-28T00:00:00Z",
        }
    )
    assert item["id"] == "entity-1"
    assert {
        "provider_id",
        "source_id",
        "collection_receipt_id",
        "payload_hash_sha256",
    }.isdisjoint(item)
