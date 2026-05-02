"""S11B Backend-Authoritative DM Trust State.

Tests:
- first-seen fingerprint becomes tofu_pinned
- repeated same fingerprint preserves tofu_pinned
- SAS confirmation upgrades tofu_pinned -> sas_verified with legacy compat fields
- changed fingerprint on tofu_pinned -> mismatch
- changed fingerprint on sas_verified -> continuity_broken
- signed-prekey rollover with stable identity key does not change trust_level
- compose returns trust_level
- mismatch and continuity_broken block compose
"""

import pytest


@pytest.fixture()
def contacts_env(tmp_path, monkeypatch):
    """Isolate contacts to a temp directory so tests don't touch real data."""
    contacts_file = tmp_path / "wormhole_dm_contacts.json"

    import services.mesh.mesh_wormhole_contacts as mod

    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "CONTACTS_FILE", contacts_file)
    return contacts_file


@pytest.fixture()
def sas_proof(monkeypatch):
    monkeypatch.setattr(
        "services.mesh.mesh_wormhole_contacts._derive_expected_contact_sas_phrase",
        lambda *_args, **_kwargs: {"ok": True, "phrase": "able acid", "peer_ref": "peer-a", "words": 2},
    )
    return "able acid"


# ── First-seen fingerprint -> tofu_pinned ──────────────────────────────


def test_first_seen_fingerprint_becomes_tofu_pinned(contacts_env):
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity

    result = observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")

    assert result["ok"] is True
    assert result["trust_level"] == "tofu_pinned"
    contact = result["contact"]
    assert contact["trust_level"] == "tofu_pinned"
    assert contact["trustSummary"]["state"] == "tofu_pinned"
    assert contact["trustSummary"]["recommendedAction"] == "verify_sas"
    assert contact["remotePrekeyFingerprint"] == "aabbccdd"
    assert contact["remotePrekeyMismatch"] is False


# ── Repeated same fingerprint preserves tofu_pinned ────────────────────


def test_repeated_fingerprint_preserves_tofu_pinned(contacts_env):
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity

    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")
    result = observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")

    assert result["trust_level"] == "tofu_pinned"
    assert result["trust_changed"] is False


# ── SAS confirmation upgrades to sas_verified ──────────────────────────


def test_sas_confirmation_upgrades_to_sas_verified(contacts_env, sas_proof):
    from services.mesh.mesh_wormhole_contacts import (
        confirm_sas_verification,
        observe_remote_prekey_identity,
    )

    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")
    result = confirm_sas_verification("peer-a", sas_proof)

    assert result["ok"] is True
    assert result["trust_level"] == "sas_verified"
    contact = result["contact"]
    assert contact["trust_level"] == "sas_verified"
    assert contact["trustSummary"]["state"] == "sas_verified"
    assert contact["trustSummary"]["verifiedFirstContact"] is True
    assert contact["verified"] is True
    assert contact["verify_inband"] is True
    assert contact["verified_at"] > 0


def test_sas_confirmation_requires_pinned_fingerprint(contacts_env, sas_proof):
    from services.mesh.mesh_wormhole_contacts import confirm_sas_verification

    result = confirm_sas_verification("peer-new", sas_proof)

    assert result["ok"] is False
    assert "no pinned fingerprint" in result.get("detail", "")


# ── Same fingerprint preserves sas_verified ────────────────────────────


def test_same_fingerprint_preserves_sas_verified(contacts_env, sas_proof):
    from services.mesh.mesh_wormhole_contacts import (
        confirm_sas_verification,
        observe_remote_prekey_identity,
    )

    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")
    confirm_sas_verification("peer-a", sas_proof)
    result = observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")

    assert result["trust_level"] == "sas_verified"
    assert result["trust_changed"] is False


# ── Changed fingerprint on tofu_pinned -> mismatch ─────────────────────


def test_changed_fingerprint_on_tofu_becomes_mismatch(contacts_env):
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity

    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")
    result = observe_remote_prekey_identity("peer-a", fingerprint="11223344")

    assert result["trust_level"] == "mismatch"
    assert result["trust_changed"] is True
    assert result["contact"]["remotePrekeyMismatch"] is True


# ── Changed fingerprint on sas_verified -> continuity_broken ───────────


def test_changed_fingerprint_on_sas_verified_becomes_continuity_broken(contacts_env, sas_proof):
    from services.mesh.mesh_wormhole_contacts import (
        confirm_sas_verification,
        observe_remote_prekey_identity,
    )

    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")
    confirm_sas_verification("peer-a", sas_proof)
    result = observe_remote_prekey_identity("peer-a", fingerprint="11223344")

    assert result["trust_level"] == "continuity_broken"
    assert result["trust_changed"] is True
    assert result["contact"]["trustSummary"]["state"] == "continuity_broken"
    assert result["contact"]["trustSummary"]["recommendedAction"] == "reverify"


def test_changed_root_on_invite_pinned_becomes_continuity_broken(contacts_env):
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity, pin_wormhole_dm_invite

    pin_wormhole_dm_invite(
        "peer-a",
        invite_payload={
            "trust_fingerprint": "aabbccdd",
            "public_key": "peer-pub",
            "public_key_algo": "Ed25519",
            "identity_dh_pub_key": "peer-dh",
            "dh_algo": "X25519",
            "root_fingerprint": "root-aa",
            "root_node_id": "!sb_root_a",
            "root_public_key": "root-pub-a",
            "root_public_key_algo": "Ed25519",
        },
        attested=True,
    )
    result = observe_remote_prekey_identity(
        "peer-a",
        fingerprint="aabbccdd",
        root_fingerprint="root-bb",
        root_node_id="!sb_root_b",
        root_public_key="root-pub-b",
        root_public_key_algo="Ed25519",
    )

    assert result["trust_level"] == "continuity_broken"
    assert result["trust_changed"] is True
    assert result["contact"]["remotePrekeyRootMismatch"] is True
    assert result["contact"]["trustSummary"]["rootMismatch"] is True
    assert result["contact"]["trustSummary"]["rootAttested"] is True


def test_internal_only_root_state_surfaces_as_importable_upgrade(contacts_env):
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity

    result = observe_remote_prekey_identity(
        "peer-root",
        fingerprint="aabbccdd",
        root_fingerprint="root-only-1234",
    )

    assert result["trust_level"] == "tofu_pinned"
    assert result["contact"]["trustSummary"]["rootAttested"] is True
    assert result["contact"]["trustSummary"]["rootWitnessed"] is False
    assert result["contact"]["trustSummary"]["rootDistributionState"] == "internal_only"


def test_unproven_witnessed_root_rotation_blocks_verified_first_contact(contacts_env):
    from services.mesh.mesh_wormhole_contacts import pin_wormhole_dm_invite

    pinned = pin_wormhole_dm_invite(
        "peer-rotated",
        invite_payload={
            "trust_fingerprint": "aabbccdd",
            "public_key": "peer-pub",
            "public_key_algo": "Ed25519",
            "identity_dh_pub_key": "peer-dh",
            "dh_algo": "X25519",
            "root_fingerprint": "root-aa",
            "root_manifest_fingerprint": "manifest-aa",
            "root_witness_policy_fingerprint": "policy-aa",
            "root_witness_threshold": 2,
            "root_witness_count": 2,
            "root_manifest_generation": 2,
            "root_rotation_proven": False,
            "root_node_id": "!sb_root_a",
            "root_public_key": "root-pub-a",
            "root_public_key_algo": "Ed25519",
        },
        attested=True,
    )

    assert pinned["trust_level"] == "invite_pinned"
    assert pinned["trustSummary"]["state"] == "invite_pinned"
    assert pinned["trustSummary"]["rootWitnessed"] is True
    assert pinned["trustSummary"]["rootDistributionState"] == "quorum_witnessed"
    assert pinned["trustSummary"]["rootWitnessProvenanceState"] == "local_quorum"
    assert pinned["trustSummary"]["rootWitnessQuorumMet"] is True
    assert pinned["trustSummary"]["rootWitnessThreshold"] == 2
    assert pinned["trustSummary"]["rootWitnessCount"] == 2
    assert pinned["trustSummary"]["rootWitnessDomainCount"] == 1
    assert pinned["trustSummary"]["rootWitnessIndependentQuorumMet"] is False
    assert pinned["trustSummary"]["rootManifestGeneration"] == 2
    assert pinned["trustSummary"]["rootRotationProven"] is False
    assert pinned["trustSummary"]["verifiedFirstContact"] is False
    assert pinned["trustSummary"]["recommendedAction"] == "import_invite"


def test_under_witnessed_root_distribution_downgrades_verified_first_contact(contacts_env):
    from services.mesh.mesh_wormhole_contacts import pin_wormhole_dm_invite

    pinned = pin_wormhole_dm_invite(
        "peer-under",
        invite_payload={
            "trust_fingerprint": "aabbccdd",
            "public_key": "peer-pub",
            "public_key_algo": "Ed25519",
            "identity_dh_pub_key": "peer-dh",
            "dh_algo": "X25519",
            "root_fingerprint": "root-aa",
            "root_manifest_fingerprint": "manifest-aa",
            "root_witness_policy_fingerprint": "policy-aa",
            "root_witness_threshold": 2,
            "root_witness_count": 1,
            "root_manifest_generation": 1,
            "root_rotation_proven": True,
            "root_node_id": "!sb_root_a",
            "root_public_key": "root-pub-a",
            "root_public_key_algo": "Ed25519",
        },
        attested=True,
    )

    assert pinned["trustSummary"]["rootDistributionState"] == "witness_policy_not_met"
    assert pinned["trustSummary"]["rootWitnessQuorumMet"] is False
    assert pinned["trustSummary"]["verifiedFirstContact"] is False
    assert pinned["trustSummary"]["recommendedAction"] == "import_invite"


def test_independent_quorum_root_provenance_surfaces_in_trust_summary(contacts_env):
    from services.mesh.mesh_wormhole_contacts import pin_wormhole_dm_invite

    pinned = pin_wormhole_dm_invite(
        "peer-independent",
        invite_payload={
            "trust_fingerprint": "ddeeff00",
            "public_key": "peer-pub",
            "public_key_algo": "Ed25519",
            "identity_dh_pub_key": "peer-dh",
            "dh_algo": "X25519",
            "root_fingerprint": "root-independent",
            "root_manifest_fingerprint": "manifest-independent",
            "root_witness_policy_fingerprint": "policy-independent",
            "root_witness_threshold": 2,
            "root_witness_count": 2,
            "root_witness_domain_count": 2,
            "root_manifest_generation": 1,
            "root_rotation_proven": True,
            "root_node_id": "!sb_root_independent",
            "root_public_key": "root-pub-independent",
            "root_public_key_algo": "Ed25519",
        },
        attested=True,
    )

    assert pinned["trustSummary"]["rootDistributionState"] == "quorum_witnessed"
    assert pinned["trustSummary"]["rootWitnessProvenanceState"] == "independent_quorum"
    assert pinned["trustSummary"]["rootWitnessDomainCount"] == 2
    assert pinned["trustSummary"]["rootWitnessIndependentQuorumMet"] is True
    assert pinned["trustSummary"]["rootWitnessFinalityMet"] is True
    assert pinned["trustSummary"]["verifiedFirstContact"] is True


def test_local_quorum_root_finality_requires_independent_quorum_only_when_flag_enabled(contacts_env, monkeypatch):
    from services.mesh import mesh_wormhole_contacts as contacts_mod

    pinned = contacts_mod.pin_wormhole_dm_invite(
        "peer-local-finality",
        invite_payload={
            "trust_fingerprint": "1122aabb",
            "public_key": "peer-pub",
            "public_key_algo": "Ed25519",
            "identity_dh_pub_key": "peer-dh",
            "dh_algo": "X25519",
            "root_fingerprint": "root-local-finality",
            "root_manifest_fingerprint": "manifest-local-finality",
            "root_witness_policy_fingerprint": "policy-local-finality",
            "root_witness_threshold": 2,
            "root_witness_count": 2,
            "root_witness_domain_count": 1,
            "root_manifest_generation": 1,
            "root_rotation_proven": True,
            "root_node_id": "!sb_root_local_finality",
            "root_public_key": "root-pub-local-finality",
            "root_public_key_algo": "Ed25519",
        },
        attested=True,
    )

    assert pinned["trustSummary"]["rootWitnessProvenanceState"] == "local_quorum"
    assert pinned["trustSummary"]["rootWitnessFinalityMet"] is False
    assert pinned["trustSummary"]["verifiedFirstContact"] is True
    assert contacts_mod.verified_first_contact_requirement("peer-local-finality") == {
        "ok": True,
        "trust_level": "invite_pinned",
    }

    monkeypatch.setenv("WORMHOLE_ROOT_WITNESS_FINALITY_ENFORCE", "true")
    reloaded = contacts_mod.list_wormhole_dm_contacts()["peer-local-finality"]
    requirement = contacts_mod.verified_first_contact_requirement("peer-local-finality")

    assert reloaded["trustSummary"]["rootDistributionState"] == "quorum_witnessed"
    assert reloaded["trustSummary"]["rootWitnessProvenanceState"] == "local_quorum"
    assert reloaded["trustSummary"]["rootWitnessFinalityMet"] is False
    assert reloaded["trustSummary"]["verifiedFirstContact"] is False
    assert reloaded["trustSummary"]["recommendedAction"] == "import_invite"
    assert requirement == {
        "ok": False,
        "trust_level": "invite_pinned",
        "detail": "independent quorum root witness finality required before secure first contact",
    }


def test_single_witness_root_path_stays_final_when_finality_flag_is_enabled(contacts_env, monkeypatch):
    from services.mesh import mesh_wormhole_contacts as contacts_mod

    monkeypatch.setenv("WORMHOLE_ROOT_WITNESS_FINALITY_ENFORCE", "true")
    pinned = contacts_mod.pin_wormhole_dm_invite(
        "peer-single-finality",
        invite_payload={
            "trust_fingerprint": "3344ccdd",
            "public_key": "peer-pub",
            "public_key_algo": "Ed25519",
            "identity_dh_pub_key": "peer-dh",
            "dh_algo": "X25519",
            "root_fingerprint": "root-single-finality",
            "root_manifest_fingerprint": "manifest-single-finality",
            "root_witness_policy_fingerprint": "policy-single-finality",
            "root_witness_threshold": 1,
            "root_witness_count": 1,
            "root_witness_domain_count": 1,
            "root_manifest_generation": 1,
            "root_rotation_proven": True,
            "root_node_id": "!sb_root_single_finality",
            "root_public_key": "root-pub-single-finality",
            "root_public_key_algo": "Ed25519",
        },
        attested=True,
    )

    assert pinned["trustSummary"]["rootDistributionState"] == "single_witness"
    assert pinned["trustSummary"]["rootWitnessProvenanceState"] == "single_witness"
    assert pinned["trustSummary"]["rootWitnessFinalityMet"] is True
    assert pinned["trustSummary"]["verifiedFirstContact"] is True
    assert contacts_mod.verified_first_contact_requirement("peer-single-finality") == {
        "ok": True,
        "trust_level": "invite_pinned",
    }


def test_legacy_lookup_changes_recommended_action_to_import_invite(contacts_env, sas_proof):
    from services.mesh.mesh_wormhole_contacts import (
        confirm_sas_verification,
        observe_remote_prekey_identity,
        upsert_wormhole_dm_contact,
    )

    observe_remote_prekey_identity("peer-legacy", fingerprint="aabbccdd")
    confirm_sas_verification("peer-legacy", sas_proof)
    contact = upsert_wormhole_dm_contact(
        "peer-legacy",
        {
            "remotePrekeyLookupMode": "legacy_agent_id",
        },
    )

    assert contact["trust_level"] == "sas_verified"
    assert contact["trustSummary"]["state"] == "sas_verified"
    assert contact["trustSummary"]["legacyLookup"] is True
    assert contact["trustSummary"]["recommendedAction"] == "import_invite"
    assert "legacy direct agent ID lookup" in contact["trustSummary"]["detail"]


# ── Signed-prekey rollover (same identity key) doesn't change trust ────


def test_prekey_rollover_stable_identity_preserves_trust(contacts_env):
    """A new signed-prekey sequence with the same identity fingerprint
    must not change trust_level."""
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity

    observe_remote_prekey_identity(
        "peer-a", fingerprint="identity-fp-stable", sequence=1, signed_at=1000
    )
    result = observe_remote_prekey_identity(
        "peer-a", fingerprint="identity-fp-stable", sequence=2, signed_at=2000
    )

    assert result["trust_level"] == "tofu_pinned"
    assert result["trust_changed"] is False
    assert result["contact"]["remotePrekeySequence"] == 2
    assert result["contact"]["remotePrekeySignedAt"] == 2000


def test_same_sequence_new_transparency_head_becomes_mismatch(contacts_env):
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity

    observe_remote_prekey_identity(
        "peer-a",
        fingerprint="identity-fp-stable",
        sequence=1,
        signed_at=1000,
        transparency_head="aa" * 32,
        transparency_size=1,
    )
    result = observe_remote_prekey_identity(
        "peer-a",
        fingerprint="identity-fp-stable",
        sequence=1,
        signed_at=1000,
        transparency_head="bb" * 32,
        transparency_size=1,
    )

    assert result["trust_level"] == "mismatch"
    assert result["trust_changed"] is True
    assert result["contact"]["remotePrekeyTransparencyConflict"] is True


def test_higher_sequence_and_growing_transparency_preserve_trust(contacts_env):
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity

    observe_remote_prekey_identity(
        "peer-a",
        fingerprint="identity-fp-stable",
        sequence=1,
        signed_at=1000,
        transparency_head="aa" * 32,
        transparency_size=1,
    )
    result = observe_remote_prekey_identity(
        "peer-a",
        fingerprint="identity-fp-stable",
        sequence=2,
        signed_at=2000,
        transparency_head="bb" * 32,
        transparency_size=2,
    )

    assert result["trust_level"] == "tofu_pinned"
    assert result["trust_changed"] is False
    assert result["contact"]["remotePrekeyTransparencyConflict"] is False


def test_transparency_conflict_persists_until_explicit_acknowledge(contacts_env):
    from services.mesh.mesh_wormhole_contacts import (
        acknowledge_changed_fingerprint,
        observe_remote_prekey_identity,
    )

    observe_remote_prekey_identity(
        "peer-a",
        fingerprint="identity-fp-stable",
        sequence=1,
        signed_at=1000,
        transparency_head="aa" * 32,
        transparency_size=1,
    )
    conflicted = observe_remote_prekey_identity(
        "peer-a",
        fingerprint="identity-fp-stable",
        sequence=1,
        signed_at=1000,
        transparency_head="bb" * 32,
        transparency_size=1,
    )
    healed = observe_remote_prekey_identity(
        "peer-a",
        fingerprint="identity-fp-stable",
        sequence=2,
        signed_at=2000,
        transparency_head="cc" * 32,
        transparency_size=2,
    )

    assert conflicted["trust_level"] == "mismatch"
    assert healed["trust_level"] == "mismatch"
    assert healed["trust_changed"] is False
    assert healed["contact"]["remotePrekeyMismatch"] is True
    assert healed["contact"]["remotePrekeyTransparencyConflict"] is True

    acknowledged = acknowledge_changed_fingerprint("peer-a")
    assert acknowledged["ok"] is True
    assert acknowledged["trust_level"] == "tofu_pinned"


# ── Compose returns trust_level ────────────────────────────────────────


def test_compose_returns_trust_level(contacts_env, monkeypatch):
    """compose_wormhole_dm must include trust_level in its response."""
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity

    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")

    # Stub out the heavy crypto/session machinery — we only care about the
    # trust_level field in the response.
    import main as main_mod

    monkeypatch.setattr(main_mod, "_resolve_dm_aliases", lambda **kw: ("local", "remote"))
    monkeypatch.setattr(main_mod, "has_mls_dm_session", lambda _local, _remote: {"ok": True, "exists": True})
    monkeypatch.setattr(
        main_mod,
        "encrypt_mls_dm",
        lambda _local, _remote, _plaintext: {"ok": True, "ciphertext": "ct", "nonce": "nc"},
    )

    result = main_mod.compose_wormhole_dm(
        peer_id="peer-a",
        peer_dh_pub="fakepub",
        plaintext="hello",
    )

    assert result["ok"] is True
    assert result["trust_level"] == "tofu_pinned"


# ── Mismatch blocks compose ───────────────────────────────────────────


def test_mismatch_blocks_compose(contacts_env, monkeypatch):
    from services.mesh.mesh_wormhole_contacts import observe_remote_prekey_identity

    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")
    observe_remote_prekey_identity("peer-a", fingerprint="11223344")

    import main as main_mod

    monkeypatch.setattr(main_mod, "_resolve_dm_aliases", lambda **kw: ("local", "remote"))
    monkeypatch.setattr(main_mod, "has_mls_dm_session", lambda _local, _remote: {"ok": True, "exists": False})
    monkeypatch.setattr(
        main_mod,
        "fetch_dm_prekey_bundle",
        lambda pid: {
            "ok": True,
            "trust_fingerprint": "11223344",
            "mls_key_package": "",
        },
    )

    result = main_mod.compose_wormhole_dm(
        peer_id="peer-a",
        peer_dh_pub="fakepub",
        plaintext="hello",
    )

    assert result["ok"] is False
    assert result["trust_level"] == "mismatch"
    assert result.get("trust_changed") is True


# ── Continuity_broken blocks compose ──────────────────────────────────


def test_continuity_broken_blocks_compose(contacts_env, monkeypatch, sas_proof):
    from services.mesh.mesh_wormhole_contacts import (
        confirm_sas_verification,
        observe_remote_prekey_identity,
    )

    observe_remote_prekey_identity("peer-a", fingerprint="aabbccdd")
    confirm_sas_verification("peer-a", sas_proof)

    import main as main_mod

    monkeypatch.setattr(main_mod, "_resolve_dm_aliases", lambda **kw: ("local", "remote"))
    monkeypatch.setattr(main_mod, "has_mls_dm_session", lambda _local, _remote: {"ok": True, "exists": False})
    monkeypatch.setattr(
        main_mod,
        "fetch_dm_prekey_bundle",
        lambda pid: {
            "ok": True,
            "trust_fingerprint": "newfingerprint",
            "mls_key_package": "",
        },
    )

    result = main_mod.compose_wormhole_dm(
        peer_id="peer-a",
        peer_dh_pub="fakepub",
        plaintext="hello",
    )

    assert result["ok"] is False
    assert result["trust_level"] == "continuity_broken"
