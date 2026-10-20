from services.scm.suppliers import _seismic_risk_level


def test_micro_quakes_ignored():
    assert _seismic_risk_level(10.0, 3.9) is None
    assert _seismic_risk_level(10.0, 4.4) is None


def test_meaningful_quake_thresholds():
    assert _seismic_risk_level(30.0, 4.6) == "HIGH"
    assert _seismic_risk_level(80.0, 5.2) == "HIGH"
    assert _seismic_risk_level(50.0, 5.6) == "CRITICAL"
    assert _seismic_risk_level(150.0, 6.1) == "CRITICAL"
