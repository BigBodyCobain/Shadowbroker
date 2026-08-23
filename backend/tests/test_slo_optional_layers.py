from services.slo import compute_all_statuses


def test_disabled_optional_layers_are_not_readiness_failures():
    statuses = compute_all_statuses(
        {"firms_fires": [], "uap_sightings": []},
        {},
        {"firms": False, "uap_sightings": False},
    )

    for source in ("firms_fires", "uap_sightings"):
        assert statuses[source]["status"] == "unconfigured"
        assert statuses[source]["enabled"] is False
        assert statuses[source]["reason"] == "layer_disabled"


def test_enabled_optional_layer_keeps_a_real_upstream_failure_visible():
    statuses = compute_all_statuses(
        {"uap_sightings": []},
        {},
        {"uap_sightings": True},
    )

    assert statuses["uap_sightings"]["status"] == "red"
    assert statuses["uap_sightings"]["never_fetched"] is True
