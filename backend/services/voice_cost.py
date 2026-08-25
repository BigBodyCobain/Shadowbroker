"""
Voice model registry + Realtime session cost estimation (voice-agent plan U1, §4.6).

Pure Python port of the GEV module ``.tmp-gev/src/voice/voiceCost.js``,
function-for-function. Dependency-free: no FastAPI imports, no I/O — the
broker (``services/voice_broker.py``, U2) is the sole stateful consumer and
owns enforcement; this module only computes.

Two independent concerns live here:

  - MODEL TIERS: 'standard' (default) vs 'mini' (cheaper). Callers ask for a
    tier by NAME; only this module maps a tier to an OpenAI-compatible model
    id + rate table, so an unknown/hostile tier string can never reach the
    provider as a model id.
  - SPEND GUARD: token usage → USD, with a soft warning and a hard cap whose
    crossings are one-shot latches on a per-session tracker.

Failure-direction invariant (GEV rule): uncertainty must over-estimate,
never under — a spend cap may stop early, but missing payload fields or
unrecognized models must never let metering run past the cap.
"""

import dataclasses
import math
from types import MappingProxyType
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# MODEL REGISTRY
# ---------------------------------------------------------------------------

# ⚠️ VERIFY AT RELEASE — MODEL IDS AND PRICES ARE EXTERNAL FACTS THAT DRIFT. ⚠️
#
# Both model ids and every rate below were read from OpenAI's own model +
# pricing pages on 2026-08-18 (see the GEV source header). Cross-check at
# release time: a wrong rate silently mis-sizes the spend cap, and a wrong
# model id fails the session at connect time.
VOICE_MODEL_RATES_VERIFIED_ON = "2026-08-18"

#: USD per 1M tokens, keyed exactly like the GEV ``rates`` tables so the two
#: registries stay diffable. Keys: text/audio/image × input/cached-input/output.


def _freeze_rates(table: Mapping[str, float]) -> Mapping[str, float]:
    return MappingProxyType({key: float(value) for key, value in table.items()})


@dataclasses.dataclass(frozen=True)
class VoiceModelEntry:
    """One priced realtime-model tier."""

    tier: str
    id: str
    label: str
    rates: Mapping[str, float]


VOICE_MODELS: dict[str, VoiceModelEntry] = {
    "standard": VoiceModelEntry(
        tier="standard",
        id="gpt-realtime-2",
        label="STANDARD",
        rates=_freeze_rates(
            {
                "textInput": 4,
                "textCachedInput": 0.4,
                "textOutput": 24,
                "audioInput": 32,
                "audioCachedInput": 0.4,
                "audioOutput": 64,
                "imageInput": 5,
                "imageCachedInput": 0.5,
            }
        ),
    ),
    "mini": VoiceModelEntry(
        tier="mini",
        id="gpt-realtime-2.1-mini",
        label="MINI",
        rates=_freeze_rates(
            {
                "textInput": 0.6,
                "textCachedInput": 0.06,
                "textOutput": 2.4,
                "audioInput": 10,
                "audioCachedInput": 0.3,
                "audioOutput": 20,
                "imageInput": 0.8,
                "imageCachedInput": 0.08,
            }
        ),
    ),
}

#: The tier used when nothing (or nonsense) was requested.
DEFAULT_VOICE_TIER = "standard"

#: Every tier name callers accept.
VOICE_TIERS = tuple(VOICE_MODELS.keys())


@dataclasses.dataclass(frozen=True)
class ResolvedVoiceModel:
    """A tier resolution result; ``recognized`` is False for worst-case fallbacks."""

    tier: str
    id: str
    label: str
    rates: Mapping[str, float]
    recognized: bool


def resolve_voice_model(tier: Any) -> ResolvedVoiceModel:
    """Map a requested tier name to its model entry, falling back to standard.

    Deliberately total: an unknown, empty, non-string, or hostile value
    resolves to the default rather than raising, so a bad querystring
    degrades to the normal session instead of breaking the mic. Dict
    membership (``key in VOICE_MODELS``) is exact-key in Python, the direct
    analogue of the JS own-property check against prototype pollution keys
    like ``constructor`` / ``__proto__``.
    """
    key = tier.strip().lower() if isinstance(tier, str) else ""
    entry = VOICE_MODELS[key] if key in VOICE_MODELS else VOICE_MODELS[DEFAULT_VOICE_TIER]
    return ResolvedVoiceModel(entry.tier, entry.id, entry.label, entry.rates, True)


def is_known_voice_tier(tier: Any) -> bool:
    """True only for a tier name this build knows."""
    key = tier.strip().lower() if isinstance(tier, str) else ""
    return key in VOICE_MODELS


def most_expensive_voice_model() -> VoiceModelEntry:
    """The priciest known rate table, derived (not hardcoded).

    Used as the conservative default whenever we do not recognise the model a
    session is actually running on. Ranked by audio output — the dominant
    cost in a speech-to-speech session.
    """
    return max(VOICE_MODELS.values(), key=lambda entry: entry.rates["audioOutput"])


def resolve_voice_model_by_id(model_id: Any) -> ResolvedVoiceModel:
    """Resolve the rate table for the model a session is ACTUALLY running on.

    The tier a client asked for is only a request — env overrides can point a
    tier at any model id, so pricing by tier would silently mis-meter.
    An unrecognised id bills at the most expensive known rates rather than
    guessing cheap — under-metering is what lets a cap be overrun. The real
    id is still reported so diagnostics never claim the wrong model.
    """
    resolved_id = model_id.strip() if isinstance(model_id, str) else ""
    for entry in VOICE_MODELS.values():
        if entry.id == resolved_id:
            return ResolvedVoiceModel(entry.tier, entry.id, entry.label, entry.rates, True)
    worst = most_expensive_voice_model()
    return ResolvedVoiceModel(worst.tier, resolved_id or worst.id, worst.label, worst.rates, False)


# ---------------------------------------------------------------------------
# SPEND GUARD CONFIG
# ---------------------------------------------------------------------------

#: Session spend thresholds, USD — deliberately generous runaway guards, not
#: budgets. Must match services/config.py VOICE_COST_WARN_USD/_CAP_USD
#: defaults (pinned by test_voice_cost.py).
DEFAULT_WARN_USD = 2.0
DEFAULT_CAP_USD = 5.0

#: Serialized sentinel for a disabled threshold. A disabled threshold is
#: infinity in memory, but JSON has no Infinity — persist this string instead;
#: :func:`normalize_cost_limits` accepts it on the way in.
VOICE_COST_LIMIT_OFF = "off"


def _clean_limit(value: Any, default: float) -> float:
    """Accepted 'disabled' spellings: 'off', ±inf, and 0/negative numbers.

    Absent values and unparseable junk fall back to the default — a corrupt
    entry must never disarm the cap.
    """
    if isinstance(value, str) and value.strip().lower() == VOICE_COST_LIMIT_OFF:
        return math.inf
    if isinstance(value, float) and math.isinf(value):
        return value
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default  # NaN / inf junk restores the default, never ∞-disarms
    return number if number > 0 else math.inf


def normalize_cost_limits(limits: Any) -> dict:
    """Normalize a partial limits mapping against the defaults.

    Accepts None or any mapping with optional ``warnUsd`` / ``capUsd`` keys.
    """
    get = limits.get if hasattr(limits, "get") else (lambda _k, _d=None: None)
    return {
        "warnUsd": _clean_limit(get("warnUsd"), DEFAULT_WARN_USD),
        "capUsd": _clean_limit(get("capUsd"), DEFAULT_CAP_USD),
    }


def serialize_cost_limits(limits: Any) -> dict:
    """Convert limits to a JSON-safe shape that round-trips a disabled threshold."""
    normalized = normalize_cost_limits(limits)

    def encode(value: float) -> Any:
        return VOICE_COST_LIMIT_OFF if math.isinf(value) else value

    return {"warnUsd": encode(normalized["warnUsd"]), "capUsd": encode(normalized["capUsd"])}


# ---------------------------------------------------------------------------
# USAGE → USD
# ---------------------------------------------------------------------------


def _non_negative(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def split_usage_tokens(usage: Any) -> dict:
    """Split one Realtime ``response.done`` usage object into billable buckets.

    The Realtime usage shape reports per-modality detail with CACHED TOKENS
    INCLUDED in the modality totals, so uncached = modality − cached(modality).

    Older/partial payloads that omit or under-explain ``input_token_details``
    attribute every unexplained residual token to AUDIO — the priciest
    modality — so a partial payload over-estimates, never under.
    """
    usage = usage if isinstance(usage, Mapping) else None
    in_details = usage.get("input_token_details") if usage else None
    out_details = usage.get("output_token_details") if usage else None
    in_details = in_details if isinstance(in_details, Mapping) else None
    out_details = out_details if isinstance(out_details, Mapping) else None
    cached = in_details.get("cached_tokens_details") if in_details else None
    cached = cached if isinstance(cached, Mapping) else None

    input_total = _non_negative(usage.get("input_tokens")) if usage else 0.0
    output_total = _non_negative(usage.get("output_tokens")) if usage else 0.0

    text_in = audio_in = image_in = 0.0
    text_cached = audio_cached = image_cached = 0.0

    if in_details:
        text_cached = _non_negative(cached.get("text_tokens")) if cached else 0.0
        audio_cached = _non_negative(cached.get("audio_tokens")) if cached else 0.0
        image_cached = _non_negative(cached.get("image_tokens")) if cached else 0.0
        # When only an aggregate `cached_tokens` is present, attribute it to
        # audio (dominant modality) so cache savings still register.
        if not cached and _non_negative(in_details.get("cached_tokens")) > 0:
            audio_cached = min(
                _non_negative(in_details.get("cached_tokens")),
                _non_negative(in_details.get("audio_tokens")),
            )
        text_in = max(0.0, _non_negative(in_details.get("text_tokens")) - text_cached)
        audio_in = max(0.0, _non_negative(in_details.get("audio_tokens")) - audio_cached)
        image_in = max(0.0, _non_negative(in_details.get("image_tokens")) - image_cached)
    # else: no detail — conservative all-audio attribution via the residual below.

    # Residual = billed tokens the detail buckets did not account for.
    input_residual = max(
        0.0,
        input_total - (text_in + audio_in + image_in + text_cached + audio_cached + image_cached),
    )
    audio_in += input_residual

    text_out = _non_negative(out_details.get("text_tokens")) if out_details else 0.0
    audio_out = _non_negative(out_details.get("audio_tokens")) if out_details else output_total
    audio_out += max(0.0, output_total - (text_out + audio_out))

    return {
        "text_in": text_in,
        "audio_in": audio_in,
        "image_in": image_in,
        "text_cached": text_cached,
        "audio_cached": audio_cached,
        "image_cached": image_cached,
        "text_out": text_out,
        "audio_out": audio_out,
        "input_total": input_total,
        "output_total": output_total,
    }


def estimate_usage_cost_usd(usage: Any, rates: Any) -> float:
    """Estimate the USD cost of one Realtime response's usage. Finite, ≥ 0."""
    if not usage or not rates:
        return 0.0
    t = split_usage_tokens(usage)
    usd = (
        t["text_in"] * _non_negative(rates.get("textInput"))
        + t["text_cached"] * _non_negative(rates.get("textCachedInput"))
        + t["text_out"] * _non_negative(rates.get("textOutput"))
        + t["audio_in"] * _non_negative(rates.get("audioInput"))
        + t["audio_cached"] * _non_negative(rates.get("audioCachedInput"))
        + t["audio_out"] * _non_negative(rates.get("audioOutput"))
        + t["image_in"] * _non_negative(rates.get("imageInput"))
        + t["image_cached"] * _non_negative(rates.get("imageCachedInput"))
    ) / 1_000_000
    return usd if math.isfinite(usd) and usd > 0 else 0.0


#: Conservative metering fallback constant (tokens of audio per second). Must
#: match services/config.py VOICE_FALLBACK_AUDIO_TOKENS_PER_SEC default — it is
#: a deliberate OVER-estimate (pinned by test_voice_cost.py). Brokers pass the
#: live settings value; the default only exists to keep this module pure.
FALLBACK_AUDIO_TOKENS_PER_SEC = 50


def estimate_fallback_audio_cost_usd(
    input_sec: Any,
    output_sec: Any,
    rates: Any,
    tokens_per_sec: int = FALLBACK_AUDIO_TOKENS_PER_SEC,
) -> float:
    """Tier-2 estimator for gateways that strip ``response.usage``.

    Bills counted audio seconds at ``(sec × tokens_per_sec ÷ 1M)`` against the
    passed table's audio input/output rates. Callers pass the worst-case table
    when the served model is unrecognized. Always finite, ≥ 0.
    """
    tps = _non_negative(tokens_per_sec)
    if not rates or tps <= 0:
        return 0.0
    in_sec = _non_negative(input_sec)
    out_sec = _non_negative(output_sec)
    usd = (
        in_sec * tps * _non_negative(rates.get("audioInput"))
        + out_sec * tps * _non_negative(rates.get("audioOutput"))
    ) / 1_000_000
    return usd if math.isfinite(usd) and usd > 0 else 0.0


def format_cost_usd(usd: Any) -> str:
    """Format a running cost for the compact UI readout ("~$0.42").

    A nonzero sub-cent total never displays as $0.00 — "$0.00" while tokens
    are burning reads as broken/free.
    """
    try:
        n = float(usd)
    except (TypeError, ValueError):
        n = 0.0
    if not math.isfinite(n) or n < 0:
        n = 0.0
    if 0 < n < 0.01:
        return "~$0.01"
    return f"~${n:.2f}"


# ---------------------------------------------------------------------------
# SESSION COST TRACKER (state machine)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CostSnapshot:
    """Immutable per-session accounting view (GEV CostSnapshot semantics)."""

    tier: str
    model_id: str
    #: False when the model was unrecognized and billed at worst-case rates.
    rates_recognized: bool
    total_usd: float
    responses: int
    warn_usd: float
    cap_usd: float
    #: 'ok' | 'warn' | 'cap' — monotonic; never steps back down.
    level: str
    #: True only on the single record() that crossed the soft threshold.
    warn_crossed: bool
    #: True only on the single record() that crossed the hard cap.
    cap_crossed: bool
    #: True once the cap is latched — the session must be stopped.
    cap_reached: bool
    #: True when at least one billed response was metered by the fallback
    #: audio-seconds estimator because the provider stripped its usage.
    estimated: bool
    #: True when a billed response never reported usage (torn down mid-
    #: response), so the accounting is PARTIAL — deliberately not called a
    #: lower bound: residuals, worst-case tables, and sub-cent rounding can
    #: also run high. No token telemetry is invented for unfinished responses.
    incomplete: bool
    #: Compact chip text. The '*' is a see-note mark, NOT a direction claim.
    display: str
    #: Prose for the tooltip; None when the accounting is complete+exact.
    note: str | None


class VoiceCostTracker:
    """Accumulate per-response usage into a running session cost and latch
    the two threshold crossings.

    ``response.done`` usage is PER RESPONSE, not cumulative, so responses sum.
    Both crossings are independent one-shot latches: each fires on the first
    ``record()`` carrying the total at or past its threshold and never again.
    The model binding is fixed at construction; ``model_id`` outranks
    ``tier`` because an env override can point a tier at a different model.
    """

    def __init__(
        self,
        tier: Any = None,
        model_id: Any = None,
        limits: Any = None,
    ) -> None:
        if model_id:
            self.model = resolve_voice_model_by_id(model_id)
        else:
            self.model = resolve_voice_model(tier)
        # Normalization authority lives HERE (single-shot, constructor path) —
        # corrupt limit values restore defaults and can never disarm the cap.
        self.limits = normalize_cost_limits(limits)
        self._total_usd = 0.0
        self._responses = 0
        self._warned = False
        self._capped = False
        self._estimated = False
        self._incomplete = False

    def _snapshot(self, warn_crossed: bool = False, cap_crossed: bool = False) -> CostSnapshot:
        level = "cap" if self._capped else "warn" if self._warned else "ok"
        display = format_cost_usd(self._total_usd) + ("*" if self._incomplete else "")
        if self._incomplete:
            note = (
                "Estimate is incomplete — a response was still in flight when "
                "the session ended, so its usage was never reported."
            )
        elif self._estimated:
            note = (
                "Estimated from audio duration — the provider did not report "
                "token usage."
            )
        else:
            note = None
        return CostSnapshot(
            tier=self.model.tier,
            model_id=self.model.id,
            rates_recognized=self.model.recognized,
            total_usd=self._total_usd,
            responses=self._responses,
            warn_usd=self.limits["warnUsd"],
            cap_usd=self.limits["capUsd"],
            level=level,
            warn_crossed=warn_crossed,
            cap_crossed=cap_crossed,
            cap_reached=self._capped,
            estimated=self._estimated,
            incomplete=self._incomplete,
            display=display,
            note=note,
        )

    def record(
        self,
        usage: Any = None,
        *,
        input_audio_s: float = 0.0,
        output_audio_s: float = 0.0,
    ) -> CostSnapshot:
        """Fold one response into the session total.

        Pass the provider's ``response.usage`` when present (tier-1 exact
        metering). When the provider strips usage, pass the counted audio
        seconds instead — they bill through the conservative fallback
        estimator and flag the snapshot ``estimated``.
        """
        if usage is None:
            usd = estimate_fallback_audio_cost_usd(
                input_audio_s, output_audio_s, self.model.rates
            )
            if usd > 0:
                self._estimated = True
        else:
            usd = estimate_usage_cost_usd(usage, self.model.rates)
        if usd > 0:
            self._total_usd += usd
            self._responses += 1

        warn_crossed = False
        cap_crossed = False
        if not self._warned and self._total_usd >= self.limits["warnUsd"]:
            self._warned = True
            warn_crossed = True
        if not self._capped and self._total_usd >= self.limits["capUsd"]:
            self._capped = True
            cap_crossed = True
        return self._snapshot(warn_crossed, cap_crossed)

    def state(self) -> CostSnapshot:
        """Current state without folding in new usage."""
        return self._snapshot()

    def mark_incomplete(self) -> CostSnapshot:
        """Record that a billed response will never report its usage (torn
        down mid-response). Flags the accounting incomplete rather than
        fabricating a token count for it."""
        self._incomplete = True
        return self._snapshot()

    def reset(self) -> CostSnapshot:
        """Reset for a new session (same model/limits); re-arms both latches."""
        self._total_usd = 0.0
        self._responses = 0
        self._warned = False
        self._capped = False
        self._estimated = False
        self._incomplete = False
        return self._snapshot()
