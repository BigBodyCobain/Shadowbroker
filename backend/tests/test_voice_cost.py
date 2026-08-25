"""Voice cost engine unit suite (voice-agent plan U1, §7.A items 4–10 minus 9).

Ports the pinned figures from the GEV source suite
(``.tmp-gev/src/voice/voiceCost.test.mjs``). The spend guard is the only thing
standing between a hot mic and an open-ended bill, so its arithmetic, its
threshold latches, its unknown-tier fallback, and its normalization invariant
("corrupt must never disarm the cap") are all pinned here.
"""

import json
import math

import pytest

from services.config import Settings
from services.voice_cost import (
    DEFAULT_CAP_USD,
    DEFAULT_WARN_USD,
    FALLBACK_AUDIO_TOKENS_PER_SEC,
    VOICE_COST_LIMIT_OFF,
    VOICE_MODELS,
    VOICE_TIERS,
    VoiceCostTracker,
    estimate_fallback_audio_cost_usd,
    estimate_usage_cost_usd,
    format_cost_usd,
    is_known_voice_tier,
    most_expensive_voice_model,
    normalize_cost_limits,
    resolve_voice_model,
    resolve_voice_model_by_id,
    serialize_cost_limits,
    split_usage_tokens,
)

#: A representative ``response.done`` usage payload with full modality detail.
FULL_USAGE = {
    "total_tokens": 1500,
    "input_tokens": 1000,
    "output_tokens": 500,
    "input_token_details": {
        "cached_tokens": 200,
        "text_tokens": 400,
        "audio_tokens": 600,
        "image_tokens": 0,
        "cached_tokens_details": {"text_tokens": 100, "audio_tokens": 100, "image_tokens": 0},
    },
    "output_token_details": {"text_tokens": 100, "audio_tokens": 400},
}

STANDARD_RATES = VOICE_MODELS["standard"].rates
MINI_RATES = VOICE_MODELS["mini"].rates


def dollars_of_usage(usd: float) -> dict:
    """Usage worth exactly $``usd`` on the STANDARD rate table: audio output
    is $64/1M, so 15,625 audio-output tokens == $1.00 exactly."""
    return {
        "input_tokens": 0,
        "output_tokens": 15625 * usd,
        "output_token_details": {"text_tokens": 0, "audio_tokens": 15625 * usd},
    }


# ---------------------------------------------------------------------------
# Item 4 — hostile tier resolution
# ---------------------------------------------------------------------------


def test_registry_exposes_exactly_the_two_tiers():
    assert tuple(sorted(VOICE_TIERS)) == ("mini", "standard")


def test_mini_is_cheaper_than_standard_on_every_rate():
    assert len(STANDARD_RATES) >= 8, "rate table covers text/audio/image in+cached+out"
    for key in STANDARD_RATES:
        assert MINI_RATES[key] < STANDARD_RATES[key], key


def test_resolve_voice_model_tolerates_case_and_whitespace():
    assert resolve_voice_model("  MINI ").tier == "mini"
    assert resolve_voice_model("Standard").tier == "standard"


@pytest.mark.parametrize(
    "bad",
    [None, "", "   ", "gpt-4o", "MINI; DROP", "constructor", "toString",
     "__proto__", 42, {}, [], True, object()],
)
def test_hostile_tiers_fall_back_to_standard_rather_than_raising(bad):
    resolved = resolve_voice_model(bad)
    assert resolved.tier == "standard"
    assert resolved.id == "gpt-realtime-2"
    assert resolved.recognized is True


def test_is_known_voice_tier_separates_real_tiers_from_fallbacks():
    assert is_known_voice_tier("mini") is True
    assert is_known_voice_tier("standard") is True
    assert is_known_voice_tier("__proto__") is False
    assert is_known_voice_tier(None) is False


# ---------------------------------------------------------------------------
# Item 5 — unknown model id bills worst-case
# ---------------------------------------------------------------------------


def test_known_model_id_resolves_to_its_own_table():
    assert resolve_voice_model_by_id("gpt-realtime-2").tier == "standard"
    assert resolve_voice_model_by_id("gpt-realtime-2").recognized is True
    assert resolve_voice_model_by_id("gpt-realtime-2.1-mini").tier == "mini"


def test_unknown_model_id_bills_at_worst_case_with_recognized_false():
    resolved = resolve_voice_model_by_id("some-future-model")
    assert resolved.recognized is False
    assert dict(resolved.rates) == dict(most_expensive_voice_model().rates)
    assert resolved.id == "some-future-model"


@pytest.mark.parametrize("bad", [None, "", "   ", 42, {}])
def test_garbage_model_ids_still_produce_usable_worst_case_entry(bad):
    resolved = resolve_voice_model_by_id(bad)
    assert resolved.recognized is False
    assert resolved.rates["audioOutput"] > 0


def test_most_expensive_model_is_derived_from_the_registry():
    worst = most_expensive_voice_model()
    for entry in VOICE_MODELS.values():
        assert entry.rates["audioOutput"] <= worst.rates["audioOutput"]


def test_model_id_outranks_tier_when_both_supplied():
    tracker = VoiceCostTracker(tier="mini", model_id="gpt-realtime-2")
    assert tracker.state().model_id == "gpt-realtime-2"
    assert tracker.state().tier == "standard"


# ---------------------------------------------------------------------------
# Usage splitting (item 6 pinned figures live here + below)
# ---------------------------------------------------------------------------


def test_cached_tokens_are_subtracted_from_modality_totals():
    t = split_usage_tokens(FULL_USAGE)
    assert t["text_in"] == 300  # 400 text - 100 cached text
    assert t["audio_in"] == 500  # 600 audio - 100 cached audio
    assert t["text_cached"] == 100
    assert t["audio_cached"] == 100
    assert t["text_out"] == 100
    assert t["audio_out"] == 400


def test_uncached_buckets_never_go_negative():
    t = split_usage_tokens(
        {
            "input_tokens": 100,
            "input_token_details": {
                "text_tokens": 50,
                "audio_tokens": 50,
                "cached_tokens_details": {"text_tokens": 999, "audio_tokens": 999},
            },
        }
    )
    assert t["text_in"] == 0
    assert t["audio_in"] == 0


def test_missing_input_detail_attributes_input_to_audio_over_estimate():
    t = split_usage_tokens({"input_tokens": 800, "output_tokens": 200})
    assert t["audio_in"] == 800
    assert t["text_in"] == 0
    assert t["audio_out"] == 200


def test_aggregate_cached_tokens_without_detail_still_earns_cache_rate():
    t = split_usage_tokens(
        {
            "input_tokens": 1000,
            "input_token_details": {"cached_tokens": 300, "text_tokens": 0, "audio_tokens": 1000},
        }
    )
    assert t["audio_cached"] == 300
    assert t["audio_in"] == 700


def test_partial_input_detail_attributes_residual_to_audio():
    # Item 6: input_tokens says 1000 but details explain only 100 — the other
    # 900 are real and billed upstream; dropping them under-meters.
    t = split_usage_tokens({"input_tokens": 1000, "input_token_details": {"text_tokens": 100}})
    assert t["text_in"] == 100
    assert t["audio_in"] == 900, "residual billed at audio rates"


def test_partial_output_detail_attributes_residual_to_audio():
    t = split_usage_tokens({"output_tokens": 500, "output_token_details": {"text_tokens": 50}})
    assert t["text_out"] == 50
    assert t["audio_out"] == 450


def test_every_billed_token_is_accounted_for_across_partial_fixtures():
    fixtures = [
        {"input_tokens": 1000, "input_token_details": {"text_tokens": 100}},
        {"input_tokens": 800, "input_token_details": {"audio_tokens": 200}},
        {"input_tokens": 640, "input_token_details": {"text_tokens": 40, "image_tokens": 100}},
        {"input_tokens": 500, "input_token_details": {"cached_tokens": 100, "text_tokens": 50}},
        {"output_tokens": 900, "output_token_details": {"text_tokens": 100}},
        {"input_tokens": 300, "output_tokens": 200},
    ]
    for usage in fixtures:
        t = split_usage_tokens(usage)
        input_sum = (
            t["text_in"] + t["audio_in"] + t["image_in"]
            + t["text_cached"] + t["audio_cached"] + t["image_cached"]
        )
        output_sum = t["text_out"] + t["audio_out"]
        assert input_sum >= usage.get("input_tokens", 0), usage
        assert output_sum >= usage.get("output_tokens", 0), usage


def test_partial_payload_never_costs_less_than_fully_described_truth():
    partial = {"input_tokens": 1000, "input_token_details": {"text_tokens": 100}}
    all_text_truth = {"input_tokens": 1000, "input_token_details": {"text_tokens": 1000}}
    assert estimate_usage_cost_usd(partial, STANDARD_RATES) >= estimate_usage_cost_usd(
        all_text_truth, STANDARD_RATES
    )


@pytest.mark.parametrize("junk", [None, {}, {"input_tokens": "abc"}, {"input_tokens": -5}, "nope"])
def test_split_usage_tokens_survives_junk_without_raising(junk):
    t = split_usage_tokens(junk)
    for value in t.values():
        assert math.isfinite(value) and value >= 0


# ---------------------------------------------------------------------------
# Cost arithmetic (item 6 pinned figures)
# ---------------------------------------------------------------------------


def test_standard_cost_is_exact_sum_of_tokens_times_per_million_rates():
    # 300*4 + 100*0.4 + 100*24 + 500*32 + 100*0.4 + 400*64 = 45,280 / 1e6
    usd = estimate_usage_cost_usd(FULL_USAGE, STANDARD_RATES)
    assert abs(usd - 0.04528) < 1e-9


def test_mini_cost_is_exact_sum_on_the_mini_table():
    # 300*0.6 + 100*0.06 + 100*2.4 + 500*10 + 100*0.3 + 400*20 = 13,456 / 1e6
    usd = estimate_usage_cost_usd(FULL_USAGE, MINI_RATES)
    assert abs(usd - 0.013456) < 1e-9


def test_image_input_tokens_are_billed():
    with_image = {
        "input_tokens": 1000,
        "input_token_details": {"text_tokens": 0, "audio_tokens": 0, "image_tokens": 1000},
    }
    usd = estimate_usage_cost_usd(with_image, STANDARD_RATES)
    assert abs(usd - 0.005) < 1e-9


def test_absent_usage_or_rates_cost_nothing():
    assert estimate_usage_cost_usd(None, STANDARD_RATES) == 0
    assert estimate_usage_cost_usd(FULL_USAGE, None) == 0
    assert estimate_usage_cost_usd({}, STANDARD_RATES) == 0


def test_one_dollar_fixture_really_is_one_dollar_on_standard_rates():
    assert abs(estimate_usage_cost_usd(dollars_of_usage(1), STANDARD_RATES) - 1) < 1e-9


# ---------------------------------------------------------------------------
# Limits normalization (item 8 — normalization invariant)
# ---------------------------------------------------------------------------


def test_module_limit_defaults_match_config_schema_defaults():
    fields = Settings.model_fields
    assert DEFAULT_WARN_USD == float(fields["VOICE_COST_WARN_USD"].default)
    assert DEFAULT_CAP_USD == float(fields["VOICE_COST_CAP_USD"].default)


def test_normalize_cost_limits_fills_gaps_from_defaults():
    assert normalize_cost_limits({"warnUsd": 1}) == {"warnUsd": 1, "capUsd": 5}
    assert normalize_cost_limits({}) == {"warnUsd": 2, "capUsd": 5}
    assert normalize_cost_limits(None) == {"warnUsd": 2, "capUsd": 5}


def test_zero_or_negative_threshold_means_disabled_not_stop_immediately():
    limits = normalize_cost_limits({"warnUsd": 0, "capUsd": -1})
    assert limits["warnUsd"] == math.inf
    assert limits["capUsd"] == math.inf
    tracker = VoiceCostTracker(limits=limits)
    state = tracker.record(dollars_of_usage(100))
    assert state.cap_reached is False
    assert state.level == "ok"


def test_unparseable_thresholds_fall_back_to_defaults_never_disarm():
    assert normalize_cost_limits({"warnUsd": "abc", "capUsd": "xyz"}) == {
        "warnUsd": 2,
        "capUsd": 5,
    }


def test_off_sentinel_normalizes_to_disabled_and_survives_json_round_trip():
    encoded = serialize_cost_limits({"warnUsd": 0, "capUsd": 0})
    assert encoded["warnUsd"] == VOICE_COST_LIMIT_OFF
    assert encoded["capUsd"] == VOICE_COST_LIMIT_OFF
    assert json.loads(json.dumps(encoded))["capUsd"] == VOICE_COST_LIMIT_OFF

    limits = normalize_cost_limits(json.loads(json.dumps(encoded)))
    assert limits["warnUsd"] == math.inf
    assert limits["capUsd"] == math.inf


def test_serialize_normalize_round_trip_preserves_disabled_live_and_mixed():
    for raw in [
        {"warnUsd": 0, "capUsd": 0},
        {"warnUsd": 2, "capUsd": 5},
        {"warnUsd": 0, "capUsd": 5},
        {"warnUsd": 1.5, "capUsd": 0},
    ]:
        expected = normalize_cost_limits(raw)
        restored = normalize_cost_limits(
            json.loads(json.dumps(serialize_cost_limits(raw)))
        )
        assert restored == expected, raw


def test_corrupt_constructor_value_restores_default_and_cap_still_arms():
    # Constructor-path normalization invariant: a corrupt stored limit must
    # never disarm the cap.
    tracker = VoiceCostTracker(limits={"warnUsd": "not-a-number", "capUsd": [1]})
    state = tracker.record(dollars_of_usage(6))
    assert state.warn_usd == 2.0
    assert state.cap_usd == 5.0
    assert state.cap_reached is True


def test_direct_env_file_read_path_normalization_invariant():
    # Broker-side parity (R4): values parsed straight from operator env-file
    # rows go through the same single normalization authority before use.
    parsed_rows = {
        "WARN": "off",
        "CAP": "",
        "JUNK": "1e999!",  # unparseable junk
    }
    limits = normalize_cost_limits(
        {
            "warnUsd": parsed_rows["WARN"],
            "capUsd": parsed_rows["CAP"] or parsed_rows["JUNK"],
        }
    )
    assert limits["warnUsd"] == math.inf
    assert limits["capUsd"] == 5.0, "corrupt value restores default, never ∞"


# ---------------------------------------------------------------------------
# Tracker state machine (item 7 — latches)
# ---------------------------------------------------------------------------


def test_fresh_tracker_starts_at_zero_and_ok():
    tracker = VoiceCostTracker(tier="standard")
    state = tracker.state()
    assert state.total_usd == 0
    assert state.level == "ok"
    assert state.cap_reached is False
    assert state.display == "~$0.00"
    assert state.responses == 0


def test_per_response_usage_accumulates_across_the_session():
    tracker = VoiceCostTracker(tier="standard")
    tracker.record(dollars_of_usage(1))
    state = tracker.record(dollars_of_usage(1))
    assert abs(state.total_usd - 2) < 1e-9
    assert state.responses == 2


def test_warn_latch_fires_exactly_once_on_the_crossing_record():
    tracker = VoiceCostTracker(tier="standard")
    assert tracker.record(dollars_of_usage(1)).warn_crossed is False  # $1
    crossing = tracker.record(dollars_of_usage(1))  # $2 — crosses
    assert crossing.warn_crossed is True
    assert crossing.level == "warn"
    assert tracker.record(dollars_of_usage(1)).warn_crossed is False  # latched


def test_cap_latch_fires_exactly_once_and_latches_cap_reached():
    tracker = VoiceCostTracker(tier="standard")
    for _ in range(4):
        assert tracker.record(dollars_of_usage(1)).cap_crossed is False
    crossing = tracker.record(dollars_of_usage(1))  # $5 — crosses
    assert crossing.cap_crossed is True
    assert crossing.cap_reached is True
    assert crossing.level == "cap"
    # Usage keeps arriving while the session tears down; the stop must not be
    # requested a second time.
    after = tracker.record(dollars_of_usage(1))
    assert after.cap_crossed is False
    assert after.cap_reached is True
    assert after.level == "cap"


def test_one_huge_response_crosses_both_thresholds_on_the_same_record():
    tracker = VoiceCostTracker(tier="standard")
    state = tracker.record(dollars_of_usage(50))
    assert state.warn_crossed is True
    assert state.cap_crossed is True
    assert state.level == "cap"


def test_level_is_monotonic_never_steps_back_down():
    tracker = VoiceCostTracker(tier="standard")
    tracker.record(dollars_of_usage(6))
    assert tracker.state().level == "cap"
    tracker.record({})  # a zero-cost response
    assert tracker.state().level == "cap"
    assert tracker.state().cap_reached is True


def test_exact_threshold_equality_counts_as_crossed():
    tracker = VoiceCostTracker(tier="standard", limits={"warnUsd": 1, "capUsd": 2})
    assert tracker.record(dollars_of_usage(1)).warn_crossed is True


def test_zero_cost_responses_do_not_advance_the_counter():
    tracker = VoiceCostTracker(tier="standard")
    state = tracker.record({})
    assert state.responses == 0
    assert state.total_usd == 0


def test_unknown_tier_tracks_at_standard_rates_rather_than_free():
    tracker = VoiceCostTracker(tier="nonsense")
    assert tracker.state().tier == "standard"
    assert tracker.record(FULL_USAGE).total_usd > 0


def test_reset_clears_totals_and_rearms_both_latches():
    tracker = VoiceCostTracker(tier="standard")
    tracker.record(dollars_of_usage(9))
    assert tracker.state().cap_reached is True
    cleared = tracker.reset()
    assert cleared.total_usd == 0
    assert cleared.level == "ok"
    assert cleared.cap_reached is False
    assert tracker.record(dollars_of_usage(2)).warn_crossed is True


# ---------------------------------------------------------------------------
# Item 10 — fallback metering + incomplete teardown
# ---------------------------------------------------------------------------


def test_fallback_estimator_matches_pinned_audio_seconds_math():
    # 60 s in × 50 tok/s × $32/1M + 30 s out × 50 tok/s × $64/1M = $0.096+$0.096
    usd = estimate_fallback_audio_cost_usd(60, 30, STANDARD_RATES)
    assert abs(usd - 0.192) < 1e-9
    assert estimate_fallback_audio_cost_usd(-5, None, STANDARD_RATES) == 0
    assert estimate_fallback_audio_cost_usd(60, 30, None) == 0


def test_fallback_constant_matches_config_schema_default():
    fields = Settings.model_fields
    assert FALLBACK_AUDIO_TOKENS_PER_SEC == int(
        fields["VOICE_FALLBACK_AUDIO_TOKENS_PER_SEC"].default
    )


def test_usage_null_bills_via_fallback_estimator_and_flags_estimated():
    tracker = VoiceCostTracker(tier="standard")
    state = tracker.record(None, input_audio_s=60, output_audio_s=30)
    assert abs(state.total_usd - 0.192) < 1e-9
    assert state.responses == 1
    assert state.estimated is True
    assert state.note is not None
    assert "audio duration" in state.note.lower()
    assert "did not report" in state.note.lower()


def test_estimated_flag_is_sticky_but_exact_responses_do_not_set_it():
    tracker = VoiceCostTracker(tier="standard")
    exact = tracker.record(FULL_USAGE)
    assert exact.estimated is False
    assert exact.note is None
    estimated = tracker.record(None, output_audio_s=100)
    assert estimated.estimated is True
    assert tracker.reset().estimated is False


def test_crafted_long_session_crosses_the_cap_purely_on_estimates():
    tracker = VoiceCostTracker(tier="standard")  # warn $2 / cap $5
    first = tracker.record(None, input_audio_s=1000, output_audio_s=1000)  # $4.80
    assert first.warn_crossed is True
    assert first.level == "warn"
    second = tracker.record(None, input_audio_s=1000, output_audio_s=1000)  # $9.60
    assert second.cap_crossed is True
    assert second.cap_reached is True
    assert second.level == "cap"
    assert second.estimated is True


def test_mark_incomplete_fabricates_no_tokens_and_flags_partial():
    tracker = VoiceCostTracker(tier="standard")
    tracker.record(dollars_of_usage(1))
    assert tracker.state().incomplete is False
    assert tracker.state().display == "~$1.00"

    marked = tracker.mark_incomplete()
    assert marked.incomplete is True
    assert marked.display == "~$1.00*"
    assert "incomplete" in marked.note.lower()
    assert abs(marked.total_usd - 1) < 1e-9
    assert marked.responses == 1, "no fabricated token count for the torn-down response"


def test_incomplete_marker_never_claims_a_floor():
    tracker = VoiceCostTracker(tier="standard")
    tracker.record(dollars_of_usage(1))
    tracker.mark_incomplete()
    snapshot = tracker.state()
    assert "+" not in snapshot.display
    for banned in ("at least", "lower bound", "minimum", "floor", "no less than"):
        assert banned not in snapshot.note.lower()


def test_an_incomplete_total_still_trips_the_cap_on_seen_tokens():
    tracker = VoiceCostTracker(tier="standard")
    tracker.mark_incomplete()
    state = tracker.record(dollars_of_usage(6))
    assert state.cap_reached is True
    assert state.incomplete is True


def test_reset_clears_the_incomplete_marker_for_next_session():
    tracker = VoiceCostTracker(tier="standard")
    tracker.record(dollars_of_usage(1))
    tracker.mark_incomplete()
    cleared = tracker.reset()
    assert cleared.incomplete is False
    assert cleared.display == "~$0.00"


# ---------------------------------------------------------------------------
# Display formatting
# ---------------------------------------------------------------------------


def test_cost_readout_formats_two_decimals_with_tilde():
    assert format_cost_usd(0) == "~$0.00"
    assert format_cost_usd(0.42) == "~$0.42"
    assert format_cost_usd(12.5) == "~$12.50"


def test_subcent_nonzero_never_displays_as_zero():
    assert format_cost_usd(0.0004) == "~$0.01"


def test_format_cost_usd_clamps_junk_to_zero():
    for junk in (float("nan"), -3, None, "abc"):
        assert format_cost_usd(junk) == "~$0.00"
