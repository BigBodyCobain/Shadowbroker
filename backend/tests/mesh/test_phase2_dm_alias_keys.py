"""Phase 2 — per-alias HKDF-derived DM identity keys.

These tests pin the wire-level non-linkability invariant introduced in
Phase 2: each alias gets its own Ed25519 public key derived deterministically
from ``dm_identity.private_key`` via HKDF-SHA256. See
``docs/mesh/wormhole-dm-root-operations-runbook.md`` §"Phase 2 — Per-Alias DM
Identity Keys (HKDF-Derived)" for the design rationale.
"""

from __future__ import annotations


def _fresh_persona_state(tmp_path, monkeypatch):
    from services.mesh import mesh_secure_storage, mesh_wormhole_persona

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key"
    )
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json"
    )
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    return mesh_wormhole_persona


def test_phase2_per_alias_keys_are_unlinkable(tmp_path, monkeypatch):
    """Three aliases on the same node must yield three distinct public keys.

    This is the wire-level non-linkability invariant: a passive observer who
    collects two signed alias bindings from the same node must not be able to
    correlate them via a shared dm_identity public key.
    """

    persona = _fresh_persona_state(tmp_path, monkeypatch)
    persona.bootstrap_wormhole_persona_state(force=True)

    sig_a = persona.sign_dm_alias_blob("alias-aaaa", b"binding-payload-1")
    sig_b = persona.sign_dm_alias_blob("alias-bbbb", b"binding-payload-2")
    sig_c = persona.sign_dm_alias_blob("alias-cccc", b"binding-payload-3")

    assert sig_a["ok"] is True
    assert sig_b["ok"] is True
    assert sig_c["ok"] is True

    # Three distinct public keys — the linkability hole is closed.
    assert sig_a["public_key"] != sig_b["public_key"]
    assert sig_b["public_key"] != sig_c["public_key"]
    assert sig_a["public_key"] != sig_c["public_key"]

    # Each per-alias key must also differ from the legacy singleton master key.
    state = persona.read_wormhole_persona_state()
    legacy_pub = str(state.get("dm_identity", {}).get("public_key", "") or "")
    assert legacy_pub
    assert sig_a["public_key"] != legacy_pub
    assert sig_b["public_key"] != legacy_pub
    assert sig_c["public_key"] != legacy_pub

    # Cutover marker must be set after first per-alias derive.
    assert bool(state["dm_identity"].get("legacy_only")) is True

    # The cache survived to disk.
    cached = state.get("dm_alias_keys") or {}
    assert set(cached.keys()) == {"alias-aaaa", "alias-bbbb", "alias-cccc"}
    assert cached["alias-aaaa"]["public_key"] == sig_a["public_key"]


def test_phase2_per_alias_key_is_deterministic(tmp_path, monkeypatch):
    """Re-signing the same alias must produce the same public key.

    Determinism is what lets historical alias bindings remain verifiable
    across restarts without persisting per-alias private keys.
    """

    persona = _fresh_persona_state(tmp_path, monkeypatch)
    persona.bootstrap_wormhole_persona_state(force=True)

    first = persona.sign_dm_alias_blob("alice", b"payload-1")
    second = persona.sign_dm_alias_blob("alice", b"payload-2")

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["public_key"] == second["public_key"]
    # Different payloads → different signatures (sanity).
    assert first["signature"] != second["signature"]

    # Both signatures verify under the per-alias path.
    ok1, _ = persona.verify_dm_alias_blob("alice", b"payload-1", first["signature"])
    ok2, _ = persona.verify_dm_alias_blob("alice", b"payload-2", second["signature"])
    assert ok1 is True
    assert ok2 is True

    # And cross-payload signatures must NOT verify (binding integrity).
    bad, _ = persona.verify_dm_alias_blob("alice", b"payload-1", second["signature"])
    assert bad is False


def test_phase2_legacy_signature_still_verifies(tmp_path, monkeypatch):
    """A signature produced by the pre-Phase-2 singleton path must still
    verify via :func:`verify_dm_alias_blob`'s legacy fallback branch when
    ``dm_identity.legacy_only`` is true.

    This is the historical-verifiability invariant: alias bindings already
    published with the singleton key remain verifiable forever.
    """

    from cryptography.hazmat.primitives.asymmetric import ed25519

    persona = _fresh_persona_state(tmp_path, monkeypatch)
    persona.bootstrap_wormhole_persona_state(force=True)

    # Manually produce a "pre-Phase-2" signature using the legacy singleton
    # private key (simulating a historical record on disk).
    state = persona.read_wormhole_persona_state()
    identity = state["dm_identity"]
    legacy_priv_b64 = str(identity.get("private_key", "") or "")
    assert legacy_priv_b64

    legacy_priv = ed25519.Ed25519PrivateKey.from_private_bytes(
        persona._unb64(legacy_priv_b64)
    )
    bound = persona._bound_dm_alias_blob("legacy-alias", b"historical-payload", legacy=True)
    legacy_signature = legacy_priv.sign(bound).hex()

    # Trigger the cutover marker by signing once via the new path with
    # *some* alias — this is what flips dm_identity.legacy_only=True.
    persona.sign_dm_alias_blob("phase2-trigger", b"trigger-payload")

    # The legacy signature must verify via the fallback branch.
    ok, reason = persona.verify_dm_alias_blob(
        "legacy-alias", b"historical-payload", legacy_signature
    )
    assert ok is True, f"legacy fallback failed: {reason}"

    # Tampered legacy signature must NOT verify.
    tampered = legacy_signature[:-2] + ("00" if legacy_signature[-2:] != "00" else "01")
    bad, _ = persona.verify_dm_alias_blob(
        "legacy-alias", b"historical-payload", tampered
    )
    assert bad is False
