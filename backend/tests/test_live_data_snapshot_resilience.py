"""The full-store snapshot must survive a transient concurrent-mutation race.

``get_latest_data_deepcopy_snapshot`` deep-copies each top-level layer outside
the data lock. If a misbehaving writer mutates a nested object in place during
the copy, ``copy.deepcopy`` raises ``RuntimeError: dictionary changed size
during iteration``. The snapshot retries a few times (the mutation window is
tiny) so /api/health and /api/live-data do not 500 on a transient race.
"""

import copy

from services.fetchers import _store


def test_snapshot_retries_then_succeeds(monkeypatch):
    real_deepcopy = copy.deepcopy
    calls = {"n": 0}

    def flaky_deepcopy(value, *args, **kwargs):
        calls["n"] += 1
        # Fail only on the very first deepcopy call, then behave normally.
        if calls["n"] == 1:
            raise RuntimeError("dictionary changed size during iteration")
        return real_deepcopy(value, *args, **kwargs)

    monkeypatch.setattr(_store.copy, "deepcopy", flaky_deepcopy)

    snapshot = _store.get_latest_data_deepcopy_snapshot()

    assert isinstance(snapshot, dict)
    assert calls["n"] >= 2  # it retried after the simulated race


def test_snapshot_reraises_if_race_never_clears(monkeypatch):
    def always_racing(value, *args, **kwargs):
        raise RuntimeError("dictionary changed size during iteration")

    monkeypatch.setattr(_store.copy, "deepcopy", always_racing)

    # A persistent (non-transient) violation is a real bug — surface it rather
    # than hang or return corrupt data.
    raised = False
    try:
        _store.get_latest_data_deepcopy_snapshot()
    except RuntimeError:
        raised = True
    assert raised
