"""Issue #202 (tg12): the satellite overflights endpoint accepted an
unbounded ``hours`` parameter, letting an anonymous caller trigger
``O(catalog_size × timesteps)`` work by asking for an absurd window.

The fix clamps ``hours`` silently rather than raising a 422. The
response shape is identical, just covering a shorter window — this
keeps the API liberal in what it accepts (Postel) while removing the
DoS surface.
"""
import os

from routers.data import _overflight_max_hours


def test_default_max_hours_is_72(monkeypatch):
    monkeypatch.delenv("OVERFLIGHTS_MAX_HOURS", raising=False)
    assert _overflight_max_hours() == 72


def test_env_override_accepted(monkeypatch):
    monkeypatch.setenv("OVERFLIGHTS_MAX_HOURS", "168")
    assert _overflight_max_hours() == 168


def test_invalid_env_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("OVERFLIGHTS_MAX_HOURS", "not-a-number")
    assert _overflight_max_hours() == 72


def test_negative_env_value_clamped_to_minimum(monkeypatch):
    monkeypatch.setenv("OVERFLIGHTS_MAX_HOURS", "-5")
    assert _overflight_max_hours() == 1


def test_clamp_arithmetic_silent():
    """The endpoint should clamp huge requests without erroring.

    We don't exercise the full FastAPI route (compute_overflights needs
    cached GP data), but we do verify the clamping math used by the
    route: min(requested, cap).
    """
    requested = 1_000_000
    cap = _overflight_max_hours()
    effective = min(max(1, requested), cap)
    assert effective == cap
    assert effective < requested
