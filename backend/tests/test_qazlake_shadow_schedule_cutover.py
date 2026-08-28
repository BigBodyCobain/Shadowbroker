import json

from services import data_fetcher


def _named(name):
    def collector():
        return None

    collector.__name__ = name
    return collector


def test_public_collectors_run_in_compare_and_stop_in_qazpipe(monkeypatch) -> None:
    flight = _named("fetch_flights")
    train = _named("fetch_trains")
    ships = _named("fetch_ships")
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES",
        json.dumps(
            {
                "aviation_public": "compare",
                "transport_public": "qazpipe",
            }
        ),
    )

    assert data_fetcher._eligible_collectors([flight, train, ships]) == [
        flight,
        ships,
    ]


def test_operator_and_derived_jobs_are_not_public_collection_families() -> None:
    retained = [
        _named("fetch_ships"),
        _named("fetch_sigint"),
        _named("fetch_sar_products"),
        _named("fetch_unusual_whales"),
        _named("prune_stale_vessels"),
        _named("oracle_sweep"),
    ]

    assert data_fetcher._eligible_collectors(retained) == retained
