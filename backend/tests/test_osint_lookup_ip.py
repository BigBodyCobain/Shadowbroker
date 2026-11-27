"""lookup_ip: ip-api.com for location and network, VPNDetection for VPN, Tor and relay flags."""

from __future__ import annotations

VPN_ANSWER = {
    "ip": "146.70.116.130",
    "is_vpn": True,
    "is_relay": False,
    "is_tor": False,
    "relay": {},
    "tor": {},
    "location": {"country": "AT", "country_name": "Austria", "timezone": "Europe/Vienna"},
    "asn": {"asn": 9009, "name": "M247 Europe SRL", "type": "hosting"},
}

RELAY_ANSWER = {
    "ip": "172.225.46.10",
    "is_vpn": False,
    "is_relay": True,
    "is_tor": False,
    "relay": {"provider": "apple_private_relay", "provider_name": "Apple iCloud Private Relay"},
    "tor": {},
    "location": {"country": "GU", "country_name": "Guam"},
    "asn": {"asn": 36183, "name": "Akamai Technologies, Inc.", "type": "hosting"},
}


def _fake_get(answers):
    def fake_json_get(url, *, timeout=8.0, headers=None):
        for host, answer in answers.items():
            if f"//{host}/" in url:
                return answer
        raise AssertionError(f"unexpected fetch {url}")

    return fake_json_get


def test_lookup_ip_falls_back_to_vpndetection_when_ip_api_refuses(monkeypatch):
    from services.osint import lookups

    # ip-api.com answers HTTPS on its free tier with 403, which _json_get returns as None.
    monkeypatch.setattr(lookups, "_json_get", _fake_get({"ip-api.com": None, "api.vpndetection.io": VPN_ANSWER}))
    monkeypatch.setattr(lookups, "_sanctions_hits", lambda *values: None)

    result = lookups.lookup_ip("146.70.116.130")

    assert result["geo"]["country"] == "Austria"
    assert result["geo"]["as_number"] == "AS9009 M247 Europe SRL"
    assert result["reputation"]["is_vpn"] is True
    assert result["reputation"]["is_tor"] is False
    assert result["reputation"]["risk_level"] == "HIGH"


def test_lookup_ip_keeps_ip_api_geo_and_adds_relay(monkeypatch):
    from services.osint import lookups

    ip_api = {
        "status": "success",
        "country": "Guam",
        "countryCode": "GU",
        "city": "Hagatna",
        "isp": "Akamai Technologies, Inc.",
        "as": "AS36183 Akamai Technologies, Inc.",
        "proxy": False,
        "hosting": True,
    }
    monkeypatch.setattr(lookups, "_json_get", _fake_get({"ip-api.com": ip_api, "api.vpndetection.io": RELAY_ANSWER}))
    monkeypatch.setattr(lookups, "_sanctions_hits", lambda *values: None)

    result = lookups.lookup_ip("172.225.46.10")

    assert result["geo"]["city"] == "Hagatna"
    assert result["reputation"]["is_hosting"] is True
    assert result["reputation"]["is_relay"] is True
    assert result["reputation"]["relay_provider"] == "Apple iCloud Private Relay"
    assert result["reputation"]["risk_level"] == "MEDIUM"


def test_lookup_ip_without_either_answer_has_no_reputation(monkeypatch):
    from services.osint import lookups

    monkeypatch.setattr(lookups, "_json_get", _fake_get({"ip-api.com": None, "api.vpndetection.io": None}))

    result = lookups.lookup_ip("146.70.116.130")

    assert "geo" not in result
    assert "reputation" not in result
