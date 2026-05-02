"""Declarative DSL executor — the type-safe, no-eval petition applier.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §1.2 (the
governance section comment block) + §5.4 step 5.

CRITICAL design property: this module **cannot execute arbitrary
code**. It is a switch over four typed payload variants, each with a
fully-validated key/value or feature-flag operation. There is NO use
of ``eval``, ``exec``, ``compile``, ``ast.parse``, ``getattr`` with a
runtime key, ``__import__``, ``subprocess``, ``os.system``, or any
other dynamic-execution primitive.

The whole class of code-injection attacks is eliminated by design —
even if an attacker passes a maliciously crafted petition payload, the
executor either applies a typed value or rejects with
``InvalidPetition``. There is no path to executing the attacker's
input as code.

Sprint 7's adversarial tests assert this invariant by reading this
file's source bytes and confirming none of the forbidden builtins
appear (``forbidden_attributes_check``).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from services.infonet.config import (
    CONFIG,
    CONFIG_SCHEMA,
    IMMUTABLE_PRINCIPLES,
    InvalidPetition,
    validate_cross_field_invariants,
    validate_petition_value,
)


_ALLOWED_PAYLOAD_TYPES = frozenset({
    "UPDATE_PARAM",
    "BATCH_UPDATE_PARAMS",
    "ENABLE_FEATURE",
    "DISABLE_FEATURE",
})


@dataclass
class DSLExecutionResult:
    """Outcome of applying a petition payload.

    ``new_config`` is a fresh dict — the caller decides whether to
    swap the live ``CONFIG`` with it. Sprint 7's tests apply the
    result and verify the swap; production callers wire this through
    the ``petition_execute`` event handler.
    """
    new_config: dict[str, Any]
    changed_keys: tuple[str, ...] = field(default_factory=tuple)


def _check_payload_shape(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise InvalidPetition("petition_payload must be an object")
    payload_type = payload.get("type")
    if payload_type not in _ALLOWED_PAYLOAD_TYPES:
        raise InvalidPetition(
            f"unknown petition_payload type: {payload_type!r}; "
            f"allowed: {sorted(_ALLOWED_PAYLOAD_TYPES)}"
        )
    return str(payload_type)


def _check_key_writeable(key: str) -> None:
    """Reject writes to keys not in CONFIG_SCHEMA. ``IMMUTABLE_PRINCIPLES``
    keys never appear in ``CONFIG_SCHEMA``, so this also rejects them.
    """
    if not isinstance(key, str) or not key:
        raise InvalidPetition("CONFIG key must be a non-empty string")
    if key not in CONFIG_SCHEMA:
        # Also surface a clearer diagnostic if the user attempted to
        # mutate an IMMUTABLE_PRINCIPLES key.
        if key in IMMUTABLE_PRINCIPLES:
            raise InvalidPetition(
                f"key {key!r} is in IMMUTABLE_PRINCIPLES — only an "
                f"upgrade-hash governance hard fork can change it"
            )
        raise InvalidPetition(f"unknown CONFIG key: {key!r}")


def _apply_update_param(
    payload: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    if "key" not in payload or "value" not in payload:
        raise InvalidPetition("UPDATE_PARAM requires key + value")
    key = payload["key"]
    value = payload["value"]
    _check_key_writeable(key)
    validate_petition_value(key, value, candidate)
    candidate[key] = value
    return candidate, [key]


def _apply_batch_update(
    payload: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    updates = payload.get("updates")
    if not isinstance(updates, list) or not updates:
        raise InvalidPetition("BATCH_UPDATE_PARAMS requires a non-empty 'updates' list")
    seen_keys: set[str] = set()
    changed: list[str] = []
    for u in updates:
        if not isinstance(u, dict) or "key" not in u or "value" not in u:
            raise InvalidPetition("BATCH_UPDATE_PARAMS entries must be {key, value}")
        key = u["key"]
        if key in seen_keys:
            raise InvalidPetition(f"duplicate key in BATCH_UPDATE_PARAMS: {key!r}")
        seen_keys.add(key)
        _check_key_writeable(key)
        validate_petition_value(key, u["value"], candidate)
        candidate[key] = u["value"]
        changed.append(key)
    return candidate, changed


def _apply_feature_toggle(
    payload: dict[str, Any],
    candidate: dict[str, Any],
    *,
    enable: bool,
) -> tuple[dict[str, Any], list[str]]:
    feature = payload.get("feature")
    if not isinstance(feature, str) or not feature:
        raise InvalidPetition("ENABLE_FEATURE / DISABLE_FEATURE requires non-empty 'feature'")
    _check_key_writeable(feature)
    schema = CONFIG_SCHEMA.get(feature)
    if schema is None or schema.get("type") != "bool":
        raise InvalidPetition(
            f"feature {feature!r} is not a boolean CONFIG key"
        )
    candidate[feature] = bool(enable)
    return candidate, [feature]


def apply_petition_payload(
    payload: dict[str, Any],
    current_config: dict[str, Any] | None = None,
) -> DSLExecutionResult:
    """Apply a validated petition payload to a CANDIDATE copy of CONFIG.

    Transactional: validation runs against the candidate; if any check
    fails, the candidate is discarded and ``InvalidPetition`` is
    raised. The live ``CONFIG`` is never partially mutated.

    Pass ``current_config`` when applying against a hypothetical state
    (testing, upgrade-hash dry-runs). Otherwise the live ``CONFIG`` is
    deep-copied as the starting point.
    """
    payload_type = _check_payload_shape(payload)
    candidate = deepcopy(current_config) if current_config is not None else deepcopy(CONFIG)

    if payload_type == "UPDATE_PARAM":
        candidate, changed = _apply_update_param(payload, candidate)
    elif payload_type == "BATCH_UPDATE_PARAMS":
        candidate, changed = _apply_batch_update(payload, candidate)
    elif payload_type == "ENABLE_FEATURE":
        candidate, changed = _apply_feature_toggle(payload, candidate, enable=True)
    elif payload_type == "DISABLE_FEATURE":
        candidate, changed = _apply_feature_toggle(payload, candidate, enable=False)
    else:  # pragma: no cover — _check_payload_shape gated this
        raise InvalidPetition(f"unhandled payload type: {payload_type}")

    # Cross-field invariants validated against the FINAL candidate.
    validate_cross_field_invariants(candidate)

    return DSLExecutionResult(new_config=candidate, changed_keys=tuple(changed))


# ─── No-eval guard ──────────────────────────────────────────────────────

# Forbidden attribute names whose presence in this module's source
# would violate the "no arbitrary code execution" property. Sprint 7's
# adversarial test reads this file and asserts none of these substrings
# appear (outside of this list and the guard function below — the
# guard's job is to *name* the forbidden surface, not use it).

_FORBIDDEN_ATTRIBUTES: frozenset[str] = frozenset({
    # Call-syntax tokens. Scanned against this module's source by the
    # Sprint 7 adversarial test. Bare module names (``subprocess``,
    # ``os``, etc.) are deliberately NOT in this set — their mere
    # mention in prose is harmless; what we forbid is the CALL.
    "eval(",
    "exec(",
    "compile(",
    "__import__(",
    "ast.parse(",
    "subprocess.run(",
    "subprocess.Popen(",
    "subprocess.call(",
    "subprocess.check_output(",
    "os.system(",
    "os.popen(",
    "pickle.loads(",
    "marshal.loads(",
})


def forbidden_attributes_check() -> tuple[str, ...]:
    """Return the curated list of forbidden surface names.

    Used by the Sprint 7 adversarial test to scan this module's source
    for any forbidden token. Exposed as a function so the test stays
    decoupled from the module's internal layout.
    """
    return tuple(sorted(_FORBIDDEN_ATTRIBUTES))


__all__ = [
    "DSLExecutionResult",
    "apply_petition_payload",
    "forbidden_attributes_check",
]
