"""Phase 0 audit diagnostics — three tests that expose the findings from the
security audit of the private lane. These are diagnostics, not fail-closed
guards: they assert the observed (current) behavior so that when Phase 1
lands, the tests must be updated and any regression flips loudly.

Findings under test:
    1. Singleton DM identity key signs all alias bindings (linkability).
    2. Shipped/default fixed private gates are durable by explicit policy.
    3. DM encrypt_dm() passes the transport gate at private_control_only
       (too permissive — does not require a real private carrier).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Test 1 — DM identity key linkability across aliases
# ---------------------------------------------------------------------------


def test_phase0_dm_identity_is_singleton_across_aliases(monkeypatch):
    """Phase 2 has landed: sign_dm_alias_blob() now returns a *distinct*
    Ed25519 public key per alias, derived deterministically from the
    dm_identity master seed via HKDF-SHA256. A passive observer can no
    longer link two alias bindings on the same node by their signing key.

    This test originally pinned the pre-Phase-2 linkability hole. Phase 2
    flipped it: any regression that re-introduces the singleton signing
    key for alias bindings will fail this assertion."""

    # Stub persona state to an in-memory dict seeded with a single
    # dm_identity keypair. No disk I/O, no real persona files touched.
    from services.mesh import mesh_wormhole_persona as persona

    state = persona._default_state()
    state["dm_identity"] = persona._identity_record(scope="dm_alias", label="dm-alias")

    holder = {"state": state}

    monkeypatch.setattr(persona, "bootstrap_wormhole_persona_state", lambda: None, raising=False)
    monkeypatch.setattr(
        persona, "read_wormhole_persona_state", lambda: holder["state"], raising=False
    )

    def _write(new_state):
        holder["state"] = new_state
        return new_state

    monkeypatch.setattr(persona, "_write_wormhole_persona_state", _write, raising=False)

    r1 = persona.sign_dm_alias_blob("alias-aaaa", b"binding-payload-1")
    r2 = persona.sign_dm_alias_blob("alias-bbbb", b"binding-payload-2")
    r3 = persona.sign_dm_alias_blob("alias-cccc", b"binding-payload-3")

    assert r1["ok"] is True, r1
    assert r2["ok"] is True, r2
    assert r3["ok"] is True, r3

    # PHASE 2 BEHAVIOR: per-alias HKDF derivation → three distinct keys.
    assert r1["public_key"] != r2["public_key"], (
        "Phase 2 regressed: alias-aaaa and alias-bbbb share a public key — "
        "the singleton linkability hole is back."
    )
    assert r2["public_key"] != r3["public_key"], (
        "Phase 2 regressed: alias-bbbb and alias-cccc share a public key."
    )
    assert r1["public_key"] != r3["public_key"], (
        "Phase 2 regressed: alias-aaaa and alias-cccc share a public key."
    )
    assert r1["signature"] != r2["signature"]  # signatures themselves differ


# ---------------------------------------------------------------------------
# Test 2 — Shipped gate envelope policy audit
# ---------------------------------------------------------------------------


def test_phase0_default_private_gates_ship_with_explicit_durable_policy():
    """The shipped fixed-gate catalog now opts into durable recovery envelopes.

    This is a product decision, not an accident: fixed private gates retain
    history for gate-key holders. Unknown or malformed policy must still fail
    closed to ``envelope_disabled`` elsewhere; this diagnostic only asserts the
    shipped catalog is explicit and internally consistent.
    """

    from services.mesh.mesh_reputation import DEFAULT_PRIVATE_GATES, VALID_ENVELOPE_POLICIES

    assert "envelope_always" in VALID_ENVELOPE_POLICIES
    assert DEFAULT_PRIVATE_GATES, "no default private gates defined"

    offenders_missing_policy = {
        gid: seed.get("envelope_policy")
        for gid, seed in DEFAULT_PRIVATE_GATES.items()
        if str(seed.get("envelope_policy", "") or "") not in VALID_ENVELOPE_POLICIES
    }
    offenders_not_durable = {
        gid: seed.get("envelope_policy")
        for gid, seed in DEFAULT_PRIVATE_GATES.items()
        if str(seed.get("envelope_policy", "") or "") != "envelope_always"
    }
    assert not offenders_missing_policy, (
        f"Default private gates must ship with an explicit valid envelope policy; offenders: {offenders_missing_policy}"
    )
    assert not offenders_not_durable, (
        f"Default private gates must ship with envelope_always; offenders: {offenders_not_durable}"
    )


def test_phase0_invalid_envelope_policy_fails_closed_to_disabled():
    """_resolve_gate_envelope_policy() must fail closed to envelope_disabled
    when the gate manager raises or returns an unknown policy."""

    from services.mesh import mesh_gate_mls

    class _Boom:
        def get_envelope_policy(self, _gate_id):
            raise RuntimeError("simulated gate manager failure")

    # Patch the module-level gate_manager used by the resolver.
    import services.mesh.mesh_gate_mls as gmls

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(gmls, "gate_manager", _Boom(), raising=False)
        assert gmls._resolve_gate_envelope_policy("any-gate") == "envelope_disabled"
    finally:
        monkey.undo()


# ---------------------------------------------------------------------------
# Test 3 — DM egress tier floor
# ---------------------------------------------------------------------------


def test_phase0_dm_transport_gate_is_non_hostile(monkeypatch):
    """Tor-style contract: the DM transport gate never prompts for consent.

    - When the wormhole supervisor is already ready at private_control_only
      or higher, the gate lets the DM path run silently.
    - When it is not ready, the gate kicks off a background auto-upgrade
      and returns ok=True anyway so local MLS operations proceed. The
      outbound release path has its own tier floor and queues ciphertext
      until the lane is ready — no user-visible consent prompt.

    This pins the Tor-style behavior: local MLS work never refuses. The
    regression to guard against is reintroducing a consent-required detail
    here."""

    from services.mesh import mesh_dm_mls

    # Happy path: supervisor already ready → gate passes silently.
    monkeypatch.setattr(
        mesh_dm_mls,
        "get_wormhole_state",
        lambda: {
            "configured": True,
            "ready": True,
            "arti_ready": False,
            "rns_ready": False,
        },
    )
    monkeypatch.setattr(mesh_dm_mls, "_last_auto_upgrade_attempt", 0.0, raising=False)
    ok, detail = mesh_dm_mls._require_private_transport()
    assert ok is True
    assert detail == "private_control_only"

    # Sad path: supervisor not ready AND auto-upgrade fails → gate still
    # returns ok=True. The release path queues ciphertext; nothing here
    # should surface the legacy consent-required detail.
    monkeypatch.setattr(
        mesh_dm_mls,
        "get_wormhole_state",
        lambda: {
            "configured": False,
            "ready": False,
            "arti_ready": False,
            "rns_ready": False,
        },
    )
    # Stub auto-upgrade to a no-op so we don't spawn a real subprocess.
    monkeypatch.setattr(
        mesh_dm_mls,
        "connect_wormhole",
        lambda *, reason="": {"ready": False, "configured": False},
    )
    monkeypatch.setattr(mesh_dm_mls, "_last_auto_upgrade_attempt", 0.0, raising=False)
    ok, detail = mesh_dm_mls._require_private_transport()
    assert ok is True, "Tor-style: local MLS work must never refuse for tier"
    assert detail != "needs_private_transport_consent", (
        "Tor-style regression: DM gate must NOT surface a consent-required "
        f"detail. Got {detail!r}."
    )
