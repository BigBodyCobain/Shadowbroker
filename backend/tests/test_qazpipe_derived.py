from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers import qazpipe_derived


def _request(token: str = "") -> SimpleNamespace:
    return SimpleNamespace(headers={"x-shadow-derived-token": token})


def test_derived_token_is_dedicated_and_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("SHADOW_DERIVED_SIGNALS_TOKEN", raising=False)
    with pytest.raises(HTTPException) as unconfigured:
        qazpipe_derived._require_derived_token(_request())
    assert unconfigured.value.status_code == 503

    monkeypatch.setenv("SHADOW_DERIVED_SIGNALS_TOKEN", "derived-only")
    for token in ("", "admin-token", "producer-token"):
        with pytest.raises(HTTPException) as rejected:
            qazpipe_derived._require_derived_token(_request(token))
        assert rejected.value.status_code == 403
    qazpipe_derived._require_derived_token(_request("derived-only"))


def test_derived_export_strips_raw_provider_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        qazpipe_derived,
        "get_latest_data_subset_refs",
        lambda *_keys: {
            "last_updated": "2026-08-28T01:00:00Z",
            "correlations": [
                {
                    "id": "corr-1",
                    "entity_id": "entity-1",
                    "risk_score": 0.8,
                    "severity": "high",
                    "source_url": "https://internal.invalid",
                    "raw_payload": {"credential": "no"},
                    "topology": ["private-node"],
                    "geometry": {
                        "type": "Point",
                        "coordinates": [76.9, 43.2],
                        "raw_payload": {"credential": "no"},
                    },
                }
            ],
            "gt_risk": {"enabled": False},
            "threat_level": {},
        },
    )
    exported = qazpipe_derived.build_derived_signals()
    assert exported == [
        {
            "signal_id": "corr-1",
            "signal_type": "correlation",
            "occurred_at": "2026-08-28T01:00:00Z",
            "entity_id": "entity-1",
            "risk_score": 0.8,
            "severity": "high",
            "geometry": {"type": "Point", "coordinates": [76.9, 43.2]},
        }
    ]
