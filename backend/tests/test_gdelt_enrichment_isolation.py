"""Regression tests for the GDELT background title enrichment.

The background enrichment thread used to mutate the nested ``properties`` dicts
of GDELT features *after* they were already published into
``latest_data["gdelt"]``. HTTP readers serialize those dicts outside the data
lock, so the in-place mutation raced the serializer and raised
``RuntimeError: dictionary changed size during iteration``.

These tests pin the contract: the enrichment must NOT touch the
already-published feature objects, and must instead publish enriched copies via
an atomic swap (with an identity guard so a newer fetch is not clobbered).
"""

from services.fetchers import _store
from services import geopolitics


def _make_feature():
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        "properties": {"name": "loc", "_urls_list": ["http://example.test/article-1"]},
    }


def test_enrichment_does_not_mutate_published_features(monkeypatch):
    feature = _make_feature()
    features = [feature]
    with _store._data_lock:
        _store.latest_data["gdelt"] = features

    monkeypatch.setattr(
        geopolitics,
        "_batch_fetch_titles",
        lambda urls: {"http://example.test/article-1": "Real Headline"},
    )

    geopolitics._enrich_gdelt_titles_background(features, {"http://example.test/article-1"})

    # The originally-published feature object must be untouched (no in-place
    # mutation of its properties dict — that was the source of the crash).
    assert "_headlines_list" not in feature["properties"]
    assert "_snippets_list" not in feature["properties"]

    # The layer must have been atomically replaced with an enriched COPY.
    published = _store.latest_data["gdelt"]
    assert published is not features
    assert published[0] is not feature
    assert published[0]["properties"]["_headlines_list"] == ["Real Headline"]


def test_enrichment_skips_swap_when_layer_replaced(monkeypatch):
    feature = _make_feature()
    features = [feature]

    # Simulate a newer fetch_gdelt() having already replaced the layer while the
    # background thread was still resolving titles.
    sentinel = [{"properties": {"name": "newer"}}]
    with _store._data_lock:
        _store.latest_data["gdelt"] = sentinel

    monkeypatch.setattr(
        geopolitics,
        "_batch_fetch_titles",
        lambda urls: {"http://example.test/article-1": "Real Headline"},
    )

    geopolitics._enrich_gdelt_titles_background(features, {"http://example.test/article-1"})

    # The identity guard must prevent clobbering the newer layer.
    assert _store.latest_data["gdelt"] is sentinel
