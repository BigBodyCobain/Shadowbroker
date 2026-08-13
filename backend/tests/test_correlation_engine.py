"""Tests for the correlation engine (previously zero coverage).

Covers the RF-anomaly detector's quality gates and co-location logic, empty/
malformed input safety, and that every emitted alert carries explanatory
``drivers`` (no black-box conclusions).
"""

from services import correlation_engine as ce


def test_empty_data_yields_no_correlations():
    assert ce.compute_correlations({}) == []
    assert ce.compute_correlations({"gps_jamming": [], "internet_outages": []}) == []


def test_rf_anomaly_requires_both_jamming_and_outage():
    # GPS jamming alone -> nothing.
    only_jam = {"gps_jamming": [{"lat": 45.0, "lng": 33.0, "ratio": 0.9}]}
    assert ce._detect_rf_anomalies(only_jam) == []
    # Outage alone -> nothing (no jamming anchor).
    only_outage = {"internet_outages": [{"lat": 45.0, "lng": 33.0, "severity": 80}]}
    assert ce._detect_rf_anomalies(only_outage) == []


def test_rf_anomaly_colocated_triggers_with_drivers():
    data = {
        "gps_jamming": [{"lat": 45.4, "lng": 33.4, "ratio": 0.85}],
        "internet_outages": [{"lat": 45.4, "lng": 33.4, "severity": 60}],
    }
    alerts = ce._detect_rf_anomalies(data)
    assert len(alerts) == 1
    a = alerts[0]
    assert a["type"] == "rf_anomaly"
    assert a["drivers"], "alert must explain why it was raised"
    assert any("GPS jamming" in d for d in a["drivers"])


def test_rf_anomaly_separated_cells_do_not_correlate():
    data = {
        "gps_jamming": [{"lat": 45.4, "lng": 33.4, "ratio": 0.85}],
        "internet_outages": [{"lat": 10.4, "lng": 10.4, "severity": 60}],
    }
    assert ce._detect_rf_anomalies(data) == []


def test_rf_anomaly_marginal_signals_rejected():
    # Ratio below the 0.60 floor and outage below 40% -> no alert.
    data = {
        "gps_jamming": [{"lat": 45.4, "lng": 33.4, "ratio": 0.3}],
        "internet_outages": [{"lat": 45.4, "lng": 33.4, "severity": 20}],
    }
    assert ce._detect_rf_anomalies(data) == []


def test_two_indicator_needs_extreme_values_without_psk():
    # Just above the base floors but below the strict 2-indicator escape
    # hatch (needs ratio>=0.75 AND outage>=50) -> rejected.
    weak = {
        "gps_jamming": [{"lat": 45.4, "lng": 33.4, "ratio": 0.65}],
        "internet_outages": [{"lat": 45.4, "lng": 33.4, "severity": 45}],
    }
    assert ce._detect_rf_anomalies(weak) == []
    # Extreme values pass.
    strong = {
        "gps_jamming": [{"lat": 45.4, "lng": 33.4, "ratio": 0.8}],
        "internet_outages": [{"lat": 45.4, "lng": 33.4, "severity": 55}],
    }
    assert len(ce._detect_rf_anomalies(strong)) == 1


def test_compute_correlations_is_crash_safe_on_garbage():
    # Malformed rows must not raise.
    data = {
        "gps_jamming": [{"lat": None, "lng": None}, {"ratio": 0.9}, "not-a-dict"],
        "internet_outages": [None, {"severity": "x"}],
        "military_flights": "not-a-list",
    }
    try:
        out = ce.compute_correlations(data)
    except Exception as exc:  # pragma: no cover
        raise AssertionError(f"compute_correlations raised on garbage: {exc}")
    assert isinstance(out, list)


def test_all_alerts_carry_type_and_severity():
    data = {
        "gps_jamming": [{"lat": 45.4, "lng": 33.4, "ratio": 0.85}],
        "internet_outages": [{"lat": 45.4, "lng": 33.4, "severity": 60}],
    }
    for alert in ce.compute_correlations(data):
        assert "type" in alert and "severity" in alert
