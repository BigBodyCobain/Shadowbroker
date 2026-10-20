"""Regression test for SIGINT snapshot dict aliasing.

``_merge_sigint_snapshot`` used to publish the *same* dict objects it received
into ``latest_data["sigint"]``. Those inputs are owned and mutated in place by
other threads (the SIGINT bridge updating live signals, and the
``meshtastic_map_nodes`` layer), so a concurrent mutation could race the
lock-free deepcopy in ``get_latest_data_deepcopy_snapshot`` (/api/health,
/api/live-data) and raise ``dictionary changed size during iteration``.

The merged snapshot must own copies of every entry.
"""

from services.fetchers.sigint import _merge_sigint_snapshot


def test_merged_entries_are_copies_not_aliases():
    live = [{"callsign": "LIVE1", "source": "meshtastic", "timestamp": "2"}]
    api = [{"callsign": "MAP1", "source": "meshtastic", "from_api": True, "timestamp": "1"}]

    merged = _merge_sigint_snapshot(live, api)

    # No published entry may be the *same object* as an input the bridge or the
    # meshtastic_map_nodes layer keeps mutating.
    inputs = {id(live[0]), id(api[0])}
    assert all(id(entry) not in inputs for entry in merged)


def test_mutating_inputs_after_merge_does_not_affect_snapshot():
    live = [{"callsign": "LIVE1", "source": "meshtastic", "timestamp": "2"}]
    api = [{"callsign": "MAP1", "source": "meshtastic", "from_api": True, "timestamp": "1"}]

    merged = _merge_sigint_snapshot(live, api)

    # Simulate the bridge adding a key to a live signal after publication — this
    # must not change the size of any dict reachable from the published list.
    live[0]["region"] = "added-later"
    api[0]["channel"] = "added-later"

    assert all("region" not in entry for entry in merged)
    assert all("channel" not in entry for entry in merged)


def test_merge_preserves_data_and_dedup():
    # Live meshtastic observation wins over the map node for the same callsign.
    live = [{"callsign": "DUP", "source": "meshtastic", "timestamp": "5"}]
    api = [
        {"callsign": "DUP", "source": "meshtastic", "from_api": True, "timestamp": "1"},
        {"callsign": "OTHER", "source": "meshtastic", "from_api": True, "timestamp": "1"},
    ]

    merged = _merge_sigint_snapshot(live, api)

    callsigns = [m["callsign"] for m in merged]
    assert callsigns.count("DUP") == 1
    assert "OTHER" in callsigns
    # The surviving DUP is the live one (no from_api flag).
    dup = next(m for m in merged if m["callsign"] == "DUP")
    assert not dup.get("from_api")
