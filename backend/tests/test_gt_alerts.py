"""Top GT alerts ranking and coordinate filtering."""

from __future__ import annotations

from analytics.gt_alerts import parse_heatmap_alerts, top_gt_alerts


def test_parse_heatmap_filters_invalid_coords() -> None:
    heatmap = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "region": "ukraine",
                    "risk": 0.55,
                    "conflict": 0.62,
                    "financial": 0.15,
                    "unrest": 0.2,
                },
                "geometry": {"type": "Point", "coordinates": [31.0, 48.0]},
            },
            {
                "type": "Feature",
                "properties": {"region": "no_coords", "risk": 0.9},
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            },
            {
                "type": "Feature",
                "properties": {"region": "global", "risk": 0.99},
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            },
        ],
    }
    alerts, plotted = parse_heatmap_alerts(heatmap, limit=5)
    assert plotted == 1
    assert len(alerts) == 1
    assert alerts[0]["region"] == "ukraine"
    assert alerts[0]["lat"] == 48.0
    assert alerts[0]["lng"] == 31.0


def test_region_label_formats_coordinates() -> None:
    from analytics.gt_alerts import _region_label

    assert "48.00" in _region_label("48.00,31.17")
    assert _region_label("ukraine") == "ukraine"


def test_top_gt_alerts_disabled(monkeypatch) -> None:
    monkeypatch.delenv("GT_ANALYTICS_ENABLED", raising=False)
    from analytics.integration import reset_gt_engine

    reset_gt_engine()
    report = top_gt_alerts(limit=3)
    assert report["alerts"] == []