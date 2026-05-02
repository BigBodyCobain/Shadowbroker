import time

import pytest


@pytest.fixture(autouse=True)
def _reset_alias_rotation_state():
    from services.mesh import mesh_metrics, mesh_wormhole_dead_drop

    mesh_metrics.reset()
    with mesh_wormhole_dead_drop._PENDING_ALIAS_COMMIT_LOCK:
        mesh_wormhole_dead_drop._PENDING_ALIAS_COMMITS.clear()
    yield
    mesh_metrics.reset()
    with mesh_wormhole_dead_drop._PENDING_ALIAS_COMMIT_LOCK:
        mesh_wormhole_dead_drop._PENDING_ALIAS_COMMITS.clear()


def _configure_alias_rotation_runtime(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_metrics,
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_dead_drop,
        mesh_wormhole_persona,
    )

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    mesh_metrics.reset()
    mesh_wormhole_persona.bootstrap_wormhole_persona_state(force=True)
    return mesh_wormhole_contacts, mesh_wormhole_dead_drop, mesh_wormhole_persona, mesh_metrics


def _upsert_verified_contact(
    contacts,
    persona,
    peer_id: str,
    *,
    alias: str = "",
    counter: int = 0,
    include_public_key: bool = True,
    dh_pub_key: str = "dhpub-test",
    verified_at: int = 0,
    rotated_at_ms: int = 0,
    root_public_key: str = "",
    trust_level: str = "sas_verified",
    blocked: bool = False,
    extra: dict | None = None,
):
    contact = contacts.pin_wormhole_dm_invite(
        peer_id,
        invite_payload={
            "trust_fingerprint": f"fp-{peer_id}",
            "identity_dh_pub_key": dh_pub_key,
            "root_public_key": root_public_key,
            "root_public_key_algo": "Ed25519",
        },
        attested=True,
    )
    payload = {
        "trust_level": trust_level,
        "verified": trust_level not in {"unpinned", ""},
        "blocked": blocked,
        "verified_at": int(verified_at or 0),
        "sharedAliasRotatedAt": int(rotated_at_ms or 0),
    }
    if alias:
        payload["sharedAlias"] = alias
        payload["sharedAliasCounter"] = int(counter or 0)
        if include_public_key:
            binding = persona.get_dm_alias_public_key(alias, counter=int(counter or 0))
            payload["sharedAliasPublicKey"] = str(binding.get("public_key", "") or "")
            payload["sharedAliasPublicKeyAlgo"] = str(binding.get("public_key_algo", "Ed25519") or "Ed25519")
    if root_public_key:
        payload["invitePinnedRootPublicKey"] = root_public_key
        payload["invitePinnedRootPublicKeyAlgo"] = "Ed25519"
    if extra:
        payload.update(dict(extra))
    del contact
    return contacts.upsert_wormhole_dm_contact_internal(peer_id, payload)


def _prepared_alias_frame(dead_drop, *, peer_id: str, plaintext: str = "hello") -> dict:
    prepared = dead_drop.prepare_outbound_alias_binding_payload(peer_id=peer_id, plaintext=plaintext)
    assert prepared["ok"] is True
    assert prepared["alias_update_embedded"] is True
    unwrapped_plaintext, frame = dead_drop._unwrap_pairwise_alias_payload(prepared["plaintext"])
    assert unwrapped_plaintext == plaintext
    assert isinstance(frame, dict)
    return {"prepared": prepared, "frame": frame}


def _upsert_root_witnessed_invite_contact(
    contacts,
    persona,
    peer_id: str,
    *,
    witness_domain_count: int,
    trust_level: str = "invite_pinned",
):
    return _upsert_verified_contact(
        contacts,
        persona,
        peer_id,
        alias="",
        trust_level=trust_level,
        dh_pub_key=f"dhpub-{peer_id}",
        root_public_key=f"root-pub-{peer_id}",
        extra={
            "invitePinnedRootFingerprint": f"root-fp-{peer_id}",
            "invitePinnedRootManifestFingerprint": f"manifest-{peer_id}",
            "invitePinnedRootWitnessPolicyFingerprint": f"policy-{peer_id}",
            "invitePinnedRootWitnessThreshold": 2,
            "invitePinnedRootWitnessCount": 2,
            "invitePinnedRootWitnessDomainCount": int(witness_domain_count),
            "invitePinnedRootManifestGeneration": 1,
            "invitePinnedRootRotationProven": True,
        },
    )


def test_missing_alias_is_issued_lazily_for_verified_contact(tmp_path, monkeypatch):
    contacts, dead_drop, persona, _metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)

    _upsert_verified_contact(
        contacts,
        persona,
        "peer_lazy_issue",
        alias="",
        dh_pub_key="dhpub-lazy",
    )

    result = dead_drop.maybe_prepare_pairwise_dm_alias_rotation(
        peer_id="peer_lazy_issue",
        peer_dh_pub="",
    )
    contact = contacts.list_wormhole_dm_contacts()["peer_lazy_issue"]

    assert result["ok"] is True
    assert result["shared_alias"].startswith("dmx_")
    assert contact["sharedAlias"] == result["shared_alias"]
    assert int(contact["sharedAliasCounter"]) >= 1


def test_local_quorum_contact_still_issues_alias_when_finality_flag_is_off(tmp_path, monkeypatch):
    contacts, dead_drop, persona, _metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)

    _upsert_root_witnessed_invite_contact(
        contacts,
        persona,
        "peer_local_quorum_off",
        witness_domain_count=1,
    )

    contact = contacts.list_wormhole_dm_contacts()["peer_local_quorum_off"]
    result = dead_drop.maybe_prepare_pairwise_dm_alias_rotation(
        peer_id="peer_local_quorum_off",
        peer_dh_pub="",
    )

    assert contact["trustSummary"]["rootWitnessProvenanceState"] == "local_quorum"
    assert contact["trustSummary"]["rootWitnessFinalityMet"] is False
    assert contact["trustSummary"]["verifiedFirstContact"] is True
    assert result["ok"] is True
    assert result["shared_alias"].startswith("dmx_")


def test_local_quorum_contact_blocks_alias_issue_when_finality_flag_is_on(tmp_path, monkeypatch):
    contacts, dead_drop, persona, _metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)
    monkeypatch.setenv("WORMHOLE_ROOT_WITNESS_FINALITY_ENFORCE", "true")

    _upsert_root_witnessed_invite_contact(
        contacts,
        persona,
        "peer_local_quorum_on",
        witness_domain_count=1,
    )

    result = dead_drop.maybe_prepare_pairwise_dm_alias_rotation(
        peer_id="peer_local_quorum_on",
        peer_dh_pub="",
    )
    contact = contacts.list_wormhole_dm_contacts()["peer_local_quorum_on"]

    assert contact["trustSummary"]["rootWitnessProvenanceState"] == "local_quorum"
    assert contact["trustSummary"]["rootWitnessFinalityMet"] is False
    assert contact["trustSummary"]["verifiedFirstContact"] is False
    assert result["ok"] is True
    assert result["rotated"] is False
    assert contact["sharedAlias"] == ""


def test_independent_quorum_contact_still_issues_alias_when_finality_flag_is_on(tmp_path, monkeypatch):
    contacts, dead_drop, persona, _metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)
    monkeypatch.setenv("WORMHOLE_ROOT_WITNESS_FINALITY_ENFORCE", "true")

    _upsert_root_witnessed_invite_contact(
        contacts,
        persona,
        "peer_independent_quorum_on",
        witness_domain_count=2,
    )

    result = dead_drop.maybe_prepare_pairwise_dm_alias_rotation(
        peer_id="peer_independent_quorum_on",
        peer_dh_pub="",
    )
    contact = contacts.list_wormhole_dm_contacts()["peer_independent_quorum_on"]

    assert contact["trustSummary"]["rootWitnessProvenanceState"] == "independent_quorum"
    assert contact["trustSummary"]["rootWitnessFinalityMet"] is True
    assert contact["trustSummary"]["verifiedFirstContact"] is True
    assert result["ok"] is True
    assert result["shared_alias"].startswith("dmx_")


@pytest.mark.parametrize(
    ("expected_reason", "rotated_at_ms_offset", "verified_at", "gate_join_seq"),
    [
        ("scheduled_30d", -(30 * 24 * 60 * 60 * 1000 + 1_000), 0, 0),
        ("contact_verification_completed", -5_000, 1_700_000_100, 0),
        ("gate_join", -5_000, 0, 2),
    ],
)
def test_lazy_rotation_triggers_fire_once(
    tmp_path,
    monkeypatch,
    expected_reason,
    rotated_at_ms_offset,
    verified_at,
    gate_join_seq,
):
    contacts, dead_drop, persona, _metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)
    now_seconds = 1_700_000_100
    now_ms = int(now_seconds * 1000)
    monkeypatch.setattr(dead_drop.time, "time", lambda: now_seconds)
    monkeypatch.setattr(contacts.time, "time", lambda: now_seconds)
    monkeypatch.setattr(dead_drop, "_observed_gate_join_seq", lambda: gate_join_seq)

    _upsert_verified_contact(
        contacts,
        persona,
        "peer_trigger",
        alias="dmx_trigger",
        counter=0,
        dh_pub_key="dhpub-trigger",
        verified_at=verified_at,
        rotated_at_ms=now_ms + rotated_at_ms_offset,
        extra={"aliasGateJoinAppliedSeq": 0},
    )

    first = dead_drop.maybe_prepare_pairwise_dm_alias_rotation(peer_id="peer_trigger", peer_dh_pub="")
    second = dead_drop.maybe_prepare_pairwise_dm_alias_rotation(peer_id="peer_trigger", peer_dh_pub="")

    assert first["ok"] is True
    assert first["rotated"] is True
    assert first["reason"] == expected_reason
    assert second["ok"] is True
    assert second["rotated"] is False
    assert second["pending_alias"] == first["pending_alias"]


def test_manual_rotation_noops_during_grace_but_emergency_rolls_forward(tmp_path, monkeypatch):
    contacts, dead_drop, _persona, _metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)

    issued = dead_drop.issue_pairwise_dm_alias(peer_id="peer_emergency_roll", peer_dh_pub="dhpub-roll")
    routine = dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_emergency_roll",
        peer_dh_pub="dhpub-roll",
        reason=dead_drop.AliasRotationReason.MANUAL.value,
    )
    routine_repeat = dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_emergency_roll",
        peer_dh_pub="dhpub-roll",
        reason=dead_drop.AliasRotationReason.MANUAL.value,
    )
    emergency = dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_emergency_roll",
        peer_dh_pub="dhpub-roll",
        reason=dead_drop.AliasRotationReason.SUSPECTED_COMPROMISE.value,
    )
    contact = contacts.list_wormhole_dm_contacts()["peer_emergency_roll"]
    accepted_aliases = contacts.accepted_contact_shared_aliases(contact)

    assert routine["rotated"] is True
    assert routine_repeat["rotated"] is False
    assert routine_repeat["pending_alias"] == routine["pending_alias"]
    assert emergency["rotated"] is True
    assert emergency["pending_alias"] != routine["pending_alias"]
    assert contact["sharedAlias"] == issued["shared_alias"]
    assert contact["pendingSharedAlias"] == emergency["pending_alias"]
    assert len(accepted_aliases) == 2
    assert issued["shared_alias"] in accepted_aliases
    assert emergency["pending_alias"] in accepted_aliases
    assert len(list(contact.get("previousSharedAliases") or [])) <= 2


def test_prepare_outbound_alias_binding_is_side_effect_free_until_commit(tmp_path, monkeypatch):
    contacts, dead_drop, _persona, mesh_metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)

    issued = dead_drop.issue_pairwise_dm_alias(peer_id="peer_commit", peer_dh_pub="dhpub-commit")
    rotated = dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_commit",
        peer_dh_pub="dhpub-commit",
        reason=dead_drop.AliasRotationReason.MANUAL.value,
    )
    before = contacts.list_wormhole_dm_contacts()["peer_commit"]
    prepared = dead_drop.prepare_outbound_alias_binding_payload(peer_id="peer_commit", plaintext="hello commit")
    after_prepare = contacts.list_wormhole_dm_contacts()["peer_commit"]

    assert prepared["alias_update_embedded"] is True
    assert before["sharedAlias"] == issued["shared_alias"]
    assert after_prepare["sharedAlias"] == issued["shared_alias"]
    assert after_prepare["pendingSharedAlias"] == rotated["pending_alias"]
    assert int(after_prepare["aliasBindingSeq"]) == 0

    dead_drop.register_outbound_alias_rotation_commit(
        peer_id="peer_commit",
        payload_format="dm1",
        ciphertext="cipher-ok",
        updates=prepared["commit_updates"],
    )

    assert (
        dead_drop.commit_outbound_alias_rotation_if_present(
            peer_id="peer_commit",
            payload_format="dm1",
            ciphertext="cipher-mismatch",
        )
        is False
    )
    still_pending = contacts.list_wormhole_dm_contacts()["peer_commit"]
    assert still_pending["sharedAlias"] == issued["shared_alias"]
    assert still_pending["pendingSharedAlias"] == rotated["pending_alias"]

    assert (
        dead_drop.commit_outbound_alias_rotation_if_present(
            peer_id="peer_commit",
            payload_format="dm1",
            ciphertext="cipher-ok",
        )
        is True
    )
    committed = contacts.list_wormhole_dm_contacts()["peer_commit"]
    snapshot = mesh_metrics.snapshot()

    assert committed["sharedAlias"] == rotated["pending_alias"]
    assert committed["pendingSharedAlias"] == ""
    assert committed["acceptedPreviousAlias"] == issued["shared_alias"]
    assert committed["acceptedPreviousAwaitingReply"] is True
    assert snapshot["counters"]["alias_rotations_completed"] == 1


def test_offline_previous_alias_acceptance_extends_to_hard_cap_then_stops(tmp_path, monkeypatch):
    contacts, dead_drop, _persona, _metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)

    dead_drop.issue_pairwise_dm_alias(peer_id="peer_offline", peer_dh_pub="dhpub-offline")
    dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_offline",
        peer_dh_pub="dhpub-offline",
        reason=dead_drop.AliasRotationReason.MANUAL.value,
    )
    prepared = dead_drop.prepare_outbound_alias_binding_payload(peer_id="peer_offline", plaintext="hello offline")
    dead_drop.register_outbound_alias_rotation_commit(
        peer_id="peer_offline",
        payload_format="mls1",
        ciphertext="cipher-offline",
        updates=prepared["commit_updates"],
    )
    assert (
        dead_drop.commit_outbound_alias_rotation_if_present(
            peer_id="peer_offline",
            payload_format="mls1",
            ciphertext="cipher-offline",
        )
        is True
    )

    contact = contacts.list_wormhole_dm_contacts()["peer_offline"]
    soft_grace_plus_one = int(contact["acceptedPreviousGraceUntil"]) + 1
    hard_cap_plus_one = int(contact["acceptedPreviousHardGraceUntil"]) + 1

    assert contacts.contact_shared_alias_accepted(contact, contact["acceptedPreviousAlias"], now_ms=soft_grace_plus_one) is True
    assert contacts.contact_shared_alias_accepted(contact, contact["acceptedPreviousAlias"], now_ms=hard_cap_plus_one) is False


def test_routine_binding_replay_is_rejected_and_counted(tmp_path, monkeypatch):
    contacts, dead_drop, _persona, mesh_metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)

    issued = dead_drop.issue_pairwise_dm_alias(peer_id="peer_sender_routine", peer_dh_pub="dhpub-routine")
    dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_sender_routine",
        peer_dh_pub="dhpub-routine",
        reason=dead_drop.AliasRotationReason.MANUAL.value,
    )
    outbound = _prepared_alias_frame(dead_drop, peer_id="peer_sender_routine")
    frame = outbound["frame"]

    _upsert_verified_contact(
        contacts,
        _persona,
        "peer_receiver_routine",
        alias=issued["shared_alias"],
        counter=int(issued["shared_alias_counter"]),
        dh_pub_key="dhpub-routine",
    )

    first = dead_drop.apply_inbound_alias_binding_frame(peer_id="peer_receiver_routine", alias_update=frame)
    replay = dead_drop.apply_inbound_alias_binding_frame(peer_id="peer_receiver_routine", alias_update=frame)
    snapshot = mesh_metrics.snapshot()

    assert first["ok"] is True
    assert replay == {"ok": False, "detail": "alias_update_replay"}
    assert snapshot["counters"]["alias_bindings_rejected_replay"] == 1


def test_routine_binding_rejects_root_signature(tmp_path, monkeypatch):
    contacts, dead_drop, persona, _metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)

    issued = dead_drop.issue_pairwise_dm_alias(peer_id="peer_sender_root_forbidden", peer_dh_pub="dhpub-root")
    dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_sender_root_forbidden",
        peer_dh_pub="dhpub-root",
        reason=dead_drop.AliasRotationReason.MANUAL.value,
    )
    frame = _prepared_alias_frame(dead_drop, peer_id="peer_sender_root_forbidden")["frame"]
    frame["root_signature"] = "deadbeef"

    _upsert_verified_contact(
        contacts,
        persona,
        "peer_receiver_root_forbidden",
        alias=issued["shared_alias"],
        counter=int(issued["shared_alias_counter"]),
        dh_pub_key="dhpub-root",
    )

    rejected = dead_drop.apply_inbound_alias_binding_frame(
        peer_id="peer_receiver_root_forbidden",
        alias_update=frame,
    )

    assert rejected == {"ok": False, "detail": "alias_update_root_sig_forbidden"}


def test_emergency_binding_accepts_root_signature_and_updates_contact(tmp_path, monkeypatch):
    contacts, dead_drop, persona, _metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)

    issued = dead_drop.issue_pairwise_dm_alias(peer_id="peer_sender_emergency", peer_dh_pub="dhpub-emergency")
    dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_sender_emergency",
        peer_dh_pub="dhpub-emergency",
        reason=dead_drop.AliasRotationReason.SUSPECTED_COMPROMISE.value,
    )
    frame = _prepared_alias_frame(dead_drop, peer_id="peer_sender_emergency")["frame"]
    root_identity = dict(persona.read_wormhole_persona_state().get("root_identity") or {})

    _upsert_verified_contact(
        contacts,
        persona,
        "peer_receiver_emergency",
        alias=issued["shared_alias"],
        counter=int(issued["shared_alias_counter"]),
        include_public_key=False,
        dh_pub_key="dhpub-emergency",
        root_public_key=str(root_identity.get("public_key", "") or ""),
    )

    applied = dead_drop.apply_inbound_alias_binding_frame(
        peer_id="peer_receiver_emergency",
        alias_update=frame,
    )
    contact = contacts.list_wormhole_dm_contacts()["peer_receiver_emergency"]

    assert applied["ok"] is True
    assert contact["sharedAlias"] == str(frame["new_alias"])
    assert contact["acceptedPreviousAlias"] == issued["shared_alias"]
    assert str(contact["acceptedPreviousAliasPublicKey"] or "") != ""


def test_emergency_binding_rejects_old_alias_only_signature(tmp_path, monkeypatch):
    contacts, dead_drop, persona, _metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)

    issued = dead_drop.issue_pairwise_dm_alias(peer_id="peer_sender_emergency_oldsig", peer_dh_pub="dhpub-emergency-2")
    dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_sender_emergency_oldsig",
        peer_dh_pub="dhpub-emergency-2",
        reason=dead_drop.AliasRotationReason.SUSPECTED_COMPROMISE.value,
    )
    frame = _prepared_alias_frame(dead_drop, peer_id="peer_sender_emergency_oldsig")["frame"]
    frame["old_alias_signature"] = "deadbeef"
    root_identity = dict(persona.read_wormhole_persona_state().get("root_identity") or {})

    _upsert_verified_contact(
        contacts,
        persona,
        "peer_receiver_emergency_oldsig",
        alias=issued["shared_alias"],
        counter=int(issued["shared_alias_counter"]),
        include_public_key=False,
        dh_pub_key="dhpub-emergency-2",
        root_public_key=str(root_identity.get("public_key", "") or ""),
    )

    rejected = dead_drop.apply_inbound_alias_binding_frame(
        peer_id="peer_receiver_emergency_oldsig",
        alias_update=frame,
    )

    assert rejected == {"ok": False, "detail": "alias_update_old_sig_forbidden"}


def test_revoked_contact_binding_is_ignored_and_counted(tmp_path, monkeypatch):
    contacts, dead_drop, persona, mesh_metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)

    issued = dead_drop.issue_pairwise_dm_alias(peer_id="peer_sender_blocked", peer_dh_pub="dhpub-blocked")
    dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_sender_blocked",
        peer_dh_pub="dhpub-blocked",
        reason=dead_drop.AliasRotationReason.MANUAL.value,
    )
    frame = _prepared_alias_frame(dead_drop, peer_id="peer_sender_blocked")["frame"]

    _upsert_verified_contact(
        contacts,
        persona,
        "peer_receiver_blocked",
        alias=issued["shared_alias"],
        counter=int(issued["shared_alias_counter"]),
        dh_pub_key="dhpub-blocked",
        blocked=True,
    )

    rejected = dead_drop.apply_inbound_alias_binding_frame(
        peer_id="peer_receiver_blocked",
        alias_update=frame,
    )
    snapshot = mesh_metrics.snapshot()

    assert rejected == {"ok": False, "detail": "alias_update_blocked"}
    assert snapshot["counters"]["alias_bindings_rejected_revoked"] == 1


def test_legacy_counter_zero_contacts_migrate_routine_binding_without_prompt(tmp_path, monkeypatch):
    contacts, dead_drop, persona, _metrics = _configure_alias_rotation_runtime(tmp_path, monkeypatch)

    _upsert_verified_contact(
        contacts,
        persona,
        "peer_sender_legacy",
        alias="dmx_legacy",
        counter=0,
        include_public_key=False,
        dh_pub_key="dhpub-legacy",
        verified_at=int(time.time()),
    )
    rotated = dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_sender_legacy",
        peer_dh_pub="dhpub-legacy",
        reason=dead_drop.AliasRotationReason.MANUAL.value,
    )
    sender_contact = contacts.list_wormhole_dm_contacts()["peer_sender_legacy"]
    frame = _prepared_alias_frame(dead_drop, peer_id="peer_sender_legacy")["frame"]

    assert sender_contact["sharedAlias"] == "dmx_legacy"
    assert sender_contact["sharedAliasCounter"] == 0
    assert sender_contact["sharedAliasPublicKey"] != ""
    assert frame["old_counter"] == 0
    assert frame["old_alias_public_key"] != ""

    _upsert_verified_contact(
        contacts,
        persona,
        "peer_receiver_legacy",
        alias="dmx_legacy",
        counter=0,
        include_public_key=False,
        dh_pub_key="dhpub-legacy",
    )

    applied = dead_drop.apply_inbound_alias_binding_frame(
        peer_id="peer_receiver_legacy",
        alias_update=frame,
    )
    receiver_contact = contacts.list_wormhole_dm_contacts()["peer_receiver_legacy"]

    assert rotated["ok"] is True
    assert applied["ok"] is True
    assert receiver_contact["sharedAlias"] == str(frame["new_alias"])
    assert receiver_contact["acceptedPreviousAlias"] == "dmx_legacy"
    assert receiver_contact["acceptedPreviousAliasCounter"] == 0
