"""S16D signed DM invite bootstrap regressions.

Tests:
- exported DM invites no longer expose the stable DM alias in the invite blob
- imported invites resolve the stable DM alias through the invite lookup handle and pin contacts as invite_pinned
- invite-pinned contacts can still be upgraded to sas_verified
- invite-pinned mismatches escalate to continuity_broken and reject acknowledgment
- compose/bootstrap flows fail closed when a pinned invite disagrees with relay identity material
- bootstrap decrypt rejects sender static keys that disagree with a pinned invite
"""

from __future__ import annotations

import base64
import json
import time

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from services.config import get_settings
from services.mesh.mesh_protocol import PROTOCOL_VERSION


def _b64_pub(pub: x25519.X25519PublicKey) -> str:
    return base64.b64encode(pub.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode("ascii")


def _fresh_wormhole_state(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_dm_relay,
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_identity,
        mesh_wormhole_persona,
        mesh_wormhole_prekey,
        mesh_wormhole_root_manifest,
        mesh_wormhole_root_transparency,
    )
    from services.config import get_settings

    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(mesh_wormhole_root_manifest, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_root_transparency, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    monkeypatch.setattr(mesh_secure_storage, "_MASTER_KEY_CACHE", None)
    monkeypatch.setattr(mesh_secure_storage, "_DOMAIN_KEY_CACHE", {})
    for key in (
        "MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_PATH",
        "MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI",
        "MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH",
        "MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI",
    ):
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()

    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)

    mesh_wormhole_identity.bootstrap_wormhole_identity(force=True)
    return relay, mesh_wormhole_identity, mesh_wormhole_contacts, mesh_wormhole_prekey


def _export_verified_invite(identity_mod):
    exported = identity_mod.export_wormhole_dm_invite()
    assert exported["ok"] is True
    verified = identity_mod.verify_wormhole_dm_invite(exported["invite"])
    assert verified["ok"] is True
    return exported, verified


def _import_invite(identity_mod, *, alias: str = ""):
    exported, verified = _export_verified_invite(identity_mod)
    imported = identity_mod.import_wormhole_dm_invite(exported["invite"], alias=alias)
    assert imported["ok"] is True
    return exported, verified, imported


def _export_compat_invite(identity_mod):
    exported, _verified = _export_verified_invite(identity_mod)
    payload = {
        **dict(exported["invite"]["payload"] or {}),
        "invite_version": identity_mod.DM_INVITE_VERSION_COMPAT,
        "attestations": [],
    }
    invite_node_id, invite_public_key, invite_private_key = identity_mod._generate_invite_signing_identity()
    signed = identity_mod._sign_dm_invite_payload(
        node_id=invite_node_id,
        public_key=invite_public_key,
        private_key=invite_private_key,
        payload=payload,
    )
    invite = {
        "event_type": identity_mod.DM_INVITE_EVENT_TYPE,
        "payload": payload,
        "node_id": str(signed.get("node_id", "") or ""),
        "public_key": str(signed.get("public_key", "") or ""),
        "public_key_algo": str(signed.get("public_key_algo", "") or ""),
        "protocol_version": str(signed.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        "sequence": int(signed.get("sequence", 0) or 0),
        "signature": str(signed.get("signature", "") or ""),
        "identity_scope": str(signed.get("identity_scope", "dm_alias") or "dm_alias"),
    }
    verified = identity_mod.verify_wormhole_dm_invite(invite)
    assert verified["ok"] is True
    return invite, verified


def _export_legacy_invite(identity_mod):
    data = identity_mod.read_wormhole_identity()
    payload = {
        "invite_version": identity_mod.DM_INVITE_VERSION_LEGACY,
        "protocol_version": PROTOCOL_VERSION,
        "issued_at": int(time.time()),
        "expires_at": 0,
        "label": "legacy",
        "agent_id": str(data.get("node_id", "") or ""),
        "public_key": str(data.get("public_key", "") or ""),
        "public_key_algo": str(data.get("public_key_algo", "Ed25519") or "Ed25519"),
        "identity_dh_pub_key": str(data.get("dh_pub_key", "") or ""),
        "dh_algo": str(data.get("dh_algo", "X25519") or "X25519"),
    }
    payload["trust_fingerprint"] = identity_mod.trust_fingerprint_for_identity_material(
        agent_id=payload["agent_id"],
        identity_dh_pub_key=payload["identity_dh_pub_key"],
        dh_algo=payload["dh_algo"],
        public_key=payload["public_key"],
        public_key_algo=payload["public_key_algo"],
        protocol_version=payload["protocol_version"],
    )
    signed = identity_mod._sign_dm_invite_payload(
        node_id=str(data.get("node_id", "") or ""),
        public_key=str(data.get("public_key", "") or ""),
        private_key=str(data.get("private_key", "") or ""),
        payload=payload,
    )
    invite = {
        "event_type": identity_mod.DM_INVITE_EVENT_TYPE,
        "payload": payload,
        "node_id": str(signed.get("node_id", "") or ""),
        "public_key": str(signed.get("public_key", "") or ""),
        "public_key_algo": str(signed.get("public_key_algo", "") or ""),
        "protocol_version": str(signed.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        "sequence": int(signed.get("sequence", 0) or 0),
        "signature": str(signed.get("signature", "") or ""),
        "identity_scope": str(signed.get("identity_scope", "dm_alias") or "dm_alias"),
    }
    verified = identity_mod.verify_wormhole_dm_invite(invite)
    assert verified["ok"] is True
    return invite, verified


def test_exported_dm_invite_verifies_and_tamper_fails(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.mesh import mesh_wormhole_persona

    exported, verified = _export_verified_invite(identity_mod)
    local_identity = identity_mod.read_wormhole_identity()
    persona_state = mesh_wormhole_persona.read_wormhole_persona_state()
    root_identity = persona_state["root_identity"]
    attestations = list(exported["invite"]["payload"].get("attestations") or [])
    stable_attestation = next(
        (
            item
            for item in attestations
            if isinstance(item, dict) and str(item.get("type", "")).strip().lower() == "stable_dm_identity"
        ),
        None,
    )

    assert verified["peer_id"] == exported["peer_id"]
    assert verified["trust_fingerprint"] == exported["trust_fingerprint"]
    assert exported["peer_id"] != local_identity["node_id"]
    assert exported["invite"]["payload"]["invite_version"] == identity_mod.DM_INVITE_VERSION
    assert stable_attestation is not None
    assert stable_attestation["event_type"] == identity_mod.DM_INVITE_ATTESTATION_EVENT_TYPE
    assert stable_attestation["signer_scope"] == "root"
    assert stable_attestation["root_node_id"] == root_identity["node_id"]
    assert stable_attestation["root_public_key"] == root_identity["public_key"]
    assert stable_attestation["root_manifest_fingerprint"]
    assert stable_attestation["root_node_id"] != local_identity["node_id"]
    assert stable_attestation["root_public_key"] != local_identity["public_key"]
    assert exported["invite"]["payload"]["root_manifest"]["payload"]["root_fingerprint"]
    assert exported["invite"]["payload"]["root_manifest_witness"]["payload"]["manifest_fingerprint"]
    assert len(exported["invite"]["payload"]["root_manifest_witnesses"]) == 3
    assert "agent_id" not in exported["invite"]["payload"]
    assert "public_key" not in exported["invite"]["payload"]
    assert "identity_dh_pub_key" not in exported["invite"]["payload"]
    assert local_identity["node_id"] not in json.dumps(exported["invite"]["payload"], sort_keys=True)
    assert local_identity["public_key"] not in json.dumps(exported["invite"]["payload"], sort_keys=True)

    tampered = dict(exported["invite"])
    tampered["payload"] = {
        **dict(exported["invite"]["payload"]),
        "identity_commitment": "ff" * 32,
    }
    rejected = identity_mod.verify_wormhole_dm_invite(tampered)

    assert rejected["ok"] is False
    assert rejected["detail"] == "invite signature invalid"


def test_exported_dm_invite_requires_stable_identity_attestation(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)

    exported, _verified = _export_verified_invite(identity_mod)
    tampered = dict(exported["invite"])
    tampered["payload"] = {
        **dict(exported["invite"]["payload"]),
        "attestations": [],
    }

    rejected = identity_mod.verify_wormhole_dm_invite(tampered)

    assert rejected["ok"] is False
    assert rejected["detail"] == "invite stable identity attestation required"


def test_exported_dm_invite_requires_root_manifest_distribution(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)

    exported, _verified = _export_verified_invite(identity_mod)
    tampered = dict(exported["invite"])
    tampered["payload"] = {
        **dict(exported["invite"]["payload"]),
        "root_manifest": {},
    }

    rejected = identity_mod.verify_wormhole_dm_invite(tampered)

    assert rejected["ok"] is False
    assert rejected["detail"] == "invite root manifest required"


def test_exported_dm_invite_carries_staged_external_witness_receipts(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.mesh import mesh_wormhole_root_manifest as manifest_mod

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    manifest_mod.configure_external_root_witness_descriptors(
        [manifest_mod._public_witness_descriptor(external_identity)]
    )
    published = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    external_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(published["manifest"]),
    )
    staged = manifest_mod.stage_external_root_manifest_witnesses(
        [external_receipt],
        manifest=published["manifest"],
    )

    exported, verified = _export_verified_invite(identity_mod)
    manifest = dict(exported["invite"]["payload"].get("root_manifest") or {})
    witness_set = list(exported["invite"]["payload"].get("root_manifest_witnesses") or [])
    external_receipts = [
        item
        for item in witness_set
        if str(item.get("node_id", "") or "").strip() == str(external_identity.get("node_id", "") or "").strip()
        and str(item.get("public_key", "") or "").strip() == str(external_identity.get("public_key", "") or "").strip()
    ]
    witness_verified = manifest_mod.verify_root_manifest_witness_set(manifest, witness_set)

    assert staged["ok"] is True
    assert staged["external_witness_count"] == 1
    assert staged["witness_independent_quorum_met"] is True
    assert verified["ok"] is True
    assert len(witness_set) == 4
    assert len(external_receipts) == 1
    assert witness_verified["ok"] is True
    assert witness_verified["witness_domain_count"] == 2
    assert witness_verified["witness_independent_quorum_met"] is True


def test_exported_dm_invite_requires_proven_witnessed_root_rotation(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.mesh import mesh_wormhole_persona
    from services.mesh import mesh_wormhole_root_manifest
    from services.mesh import mesh_wormhole_root_transparency

    _export_verified_invite(identity_mod)
    mesh_wormhole_persona.bootstrap_wormhole_persona_state(force=True)
    exported, _verified = _export_verified_invite(identity_mod)

    tampered_manifest_payload = {
        **dict(exported["invite"]["payload"]["root_manifest"]["payload"] or {}),
        "previous_root_cross_sequence": 0,
        "previous_root_cross_signature": "",
    }
    resigned_manifest = mesh_wormhole_persona.sign_root_wormhole_event(
        event_type=mesh_wormhole_root_manifest.STABLE_DM_ROOT_MANIFEST_EVENT_TYPE,
        payload=tampered_manifest_payload,
    )
    tampered_manifest = {
        "type": mesh_wormhole_root_manifest.STABLE_DM_ROOT_MANIFEST_TYPE,
        "event_type": mesh_wormhole_root_manifest.STABLE_DM_ROOT_MANIFEST_EVENT_TYPE,
        "node_id": str(resigned_manifest.get("node_id", "") or ""),
        "public_key": str(resigned_manifest.get("public_key", "") or ""),
        "public_key_algo": str(resigned_manifest.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": str(resigned_manifest.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        "sequence": int(resigned_manifest.get("sequence", 0) or 0),
        "payload": dict(resigned_manifest.get("payload") or {}),
        "signature": str(resigned_manifest.get("signature", "") or ""),
        "identity_scope": "root",
    }
    witness_state = mesh_wormhole_root_manifest.read_root_distribution_state()
    witness_identities = list(witness_state.get("witness_identities") or [])
    tampered_witnesses = [
        mesh_wormhole_root_manifest._sign_with_witness_identity(
            identity=dict(identity or {}),
            event_type=mesh_wormhole_root_manifest.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
            payload=mesh_wormhole_root_manifest._witness_payload(tampered_manifest),
        )
        for identity in witness_identities
    ]
    tampered_transparency = mesh_wormhole_root_transparency.publish_root_transparency_record(
        distribution={"manifest": tampered_manifest, "witnesses": tampered_witnesses}
    )

    rejected = identity_mod._verify_dm_invite_root_distribution(
        {
            **dict(exported["invite"]["payload"] or {}),
            "root_manifest": tampered_manifest,
            "root_manifest_witness": dict(tampered_witnesses[0] or {}),
            "root_manifest_witnesses": tampered_witnesses,
            "root_transparency_record": dict(tampered_transparency.get("record") or {}),
        }
    )

    assert rejected["ok"] is False
    assert rejected["detail"] == "invite root rotation proof required"


def test_exported_dm_invite_requires_witness_threshold(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)

    exported, _verified = _export_verified_invite(identity_mod)
    rejected = identity_mod._verify_dm_invite_root_distribution(
        {
            **dict(exported["invite"]["payload"] or {}),
            "root_manifest_witnesses": [dict(exported["invite"]["payload"]["root_manifest_witnesses"][0] or {})],
        }
    )

    assert rejected["ok"] is False
    assert rejected["detail"] == "stable root manifest witness threshold not met"


def test_exported_dm_invite_requires_root_transparency_record(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)

    exported, _verified = _export_verified_invite(identity_mod)
    rejected = identity_mod._verify_dm_invite_root_distribution(
        {
            **dict(exported["invite"]["payload"] or {}),
            "root_transparency_record": {},
        }
    )

    assert rejected["ok"] is False
    assert rejected["detail"] == "invite root transparency record required"


def test_exported_dm_invite_requires_witness_policy_change_proof(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.mesh import mesh_wormhole_persona
    from services.mesh import mesh_wormhole_root_manifest
    from services.mesh import mesh_wormhole_root_transparency

    _export_verified_invite(identity_mod)
    republished = mesh_wormhole_root_manifest.publish_current_root_manifest(expires_in_s=3600, policy_version=2)

    tampered_manifest_payload = {
        **dict(republished["manifest"]["payload"] or {}),
        "previous_witness_policy_sequence": 0,
        "previous_witness_policy_signature": "",
    }
    resigned_manifest = mesh_wormhole_persona.sign_root_wormhole_event(
        event_type=mesh_wormhole_root_manifest.STABLE_DM_ROOT_MANIFEST_EVENT_TYPE,
        payload=tampered_manifest_payload,
    )
    tampered_manifest = {
        "type": mesh_wormhole_root_manifest.STABLE_DM_ROOT_MANIFEST_TYPE,
        "event_type": mesh_wormhole_root_manifest.STABLE_DM_ROOT_MANIFEST_EVENT_TYPE,
        "node_id": str(resigned_manifest.get("node_id", "") or ""),
        "public_key": str(resigned_manifest.get("public_key", "") or ""),
        "public_key_algo": str(resigned_manifest.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": str(resigned_manifest.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        "sequence": int(resigned_manifest.get("sequence", 0) or 0),
        "payload": dict(resigned_manifest.get("payload") or {}),
        "signature": str(resigned_manifest.get("signature", "") or ""),
        "identity_scope": "root",
    }
    witness_state = mesh_wormhole_root_manifest.read_root_distribution_state()
    witness_identities = list(witness_state.get("witness_identities") or [])
    tampered_witnesses = [
        mesh_wormhole_root_manifest._sign_with_witness_identity(
            identity=dict(identity or {}),
            event_type=mesh_wormhole_root_manifest.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
            payload=mesh_wormhole_root_manifest._witness_payload(tampered_manifest),
        )
        for identity in witness_identities
    ]
    tampered_transparency = mesh_wormhole_root_transparency.publish_root_transparency_record(
        distribution={"manifest": tampered_manifest, "witnesses": tampered_witnesses}
    )

    rejected = identity_mod._verify_dm_invite_root_distribution(
        {
            **dict(republished["manifest"]["payload"] or {}),
            "root_manifest": tampered_manifest,
            "root_manifest_witness": dict(tampered_witnesses[0] or {}),
            "root_manifest_witnesses": tampered_witnesses,
            "root_transparency_record": dict(tampered_transparency.get("record") or {}),
        }
    )

    assert rejected["ok"] is False
    assert rejected["detail"] == "invite root witness policy change proof required"


def test_imported_dm_invite_pins_contact_as_invite_pinned(tmp_path, monkeypatch):
    _relay, identity_mod, contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    exported, verified, imported = _import_invite(identity_mod, alias="alice")
    contact = imported["contact"]
    local_identity = identity_mod.read_wormhole_identity()

    assert contact["alias"] == "alice"
    assert contact["trust_level"] == "invite_pinned"
    assert contact["trustSummary"]["state"] == "invite_pinned"
    assert contact["trustSummary"]["verifiedFirstContact"] is True
    assert contact["trustSummary"]["rootWitnessed"] is True
    assert contact["trustSummary"]["rootDistributionState"] == "quorum_witnessed"
    assert contact["trustSummary"]["rootWitnessQuorumMet"] is True
    assert contact["trustSummary"]["rootWitnessProvenanceState"] == "local_quorum"
    assert contact["trustSummary"]["rootWitnessFinalityMet"] is False
    assert contact["trustSummary"]["rootWitnessThreshold"] == 2
    assert contact["trustSummary"]["rootWitnessCount"] == 3
    assert imported["peer_id"] == local_identity["node_id"]
    assert imported["invite_peer_id"] == verified["peer_id"]
    assert contact["invitePinnedTrustFingerprint"] == imported["trust_fingerprint"]
    assert contact["invitePinnedRootFingerprint"]
    assert contact["remotePrekeyRootFingerprint"] == contact["invitePinnedRootFingerprint"]
    assert contact["remotePrekeyFingerprint"] == imported["trust_fingerprint"]
    assert contact["invitePinnedDhPubKey"] == local_identity["dh_pub_key"]
    assert contact["invitePinnedPrekeyLookupHandle"] == exported["invite"]["payload"]["prekey_lookup_handle"]
    assert contacts_mod.list_wormhole_dm_contacts()[imported["peer_id"]]["trust_level"] == "invite_pinned"


def test_imported_dm_invite_requires_root_attested_prekey_bundle(tmp_path, monkeypatch):
    relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)

    exported, _verified = _export_verified_invite(identity_mod)
    local_identity = identity_mod.read_wormhole_identity()
    agent_id = str(local_identity.get("node_id", "") or "")
    relay._prekey_bundles[agent_id]["bundle"] = {
        **dict(relay._prekey_bundles[agent_id]["bundle"] or {}),
        "root_attestation": {},
    }

    imported = identity_mod.import_wormhole_dm_invite(exported["invite"], alias="alice")

    assert imported["ok"] is False
    assert imported["detail"] == "prekey bundle root attestation required"


def test_imported_dm_invite_requires_same_witnessed_root_manifest(tmp_path, monkeypatch):
    relay, identity_mod, _contacts_mod, prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.mesh import mesh_wormhole_root_manifest
    from services.mesh import mesh_wormhole_root_transparency

    exported, _verified = _export_verified_invite(identity_mod)
    local_identity = identity_mod.read_wormhole_identity()
    agent_id = str(local_identity.get("node_id", "") or "")

    republished = mesh_wormhole_root_manifest.publish_current_root_manifest(expires_in_s=3600, policy_version=2)
    republished_transparency = mesh_wormhole_root_transparency.publish_root_transparency_record(
        distribution={
            "manifest": dict(republished.get("manifest") or {}),
            "witnesses": list(republished.get("witnesses") or []),
        }
    )
    stored = dict(relay._prekey_bundles[agent_id] or {})
    tampered_bundle = dict(stored.get("bundle") or {})
    tampered_bundle["root_manifest"] = dict(republished.get("manifest") or {})
    tampered_bundle["root_manifest_witness"] = dict(republished.get("witness") or {})
    tampered_bundle["root_manifest_witnesses"] = list(republished.get("witnesses") or [])
    tampered_bundle["root_transparency_record"] = dict(republished_transparency.get("record") or {})
    tampered_bundle = prekey_mod._attach_bundle_root_attestation(
        agent_id=agent_id,
        public_key=str(stored.get("public_key", "") or ""),
        public_key_algo=str(stored.get("public_key_algo", "Ed25519") or "Ed25519"),
        protocol_version=str(stored.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        bundle=tampered_bundle,
    )
    tampered_bundle = prekey_mod._attach_bundle_signature(
        tampered_bundle,
        signed_at=int(tampered_bundle.get("signed_at", 0) or time.time()),
    )
    relay._prekey_bundles[agent_id]["bundle"] = tampered_bundle

    imported = identity_mod.import_wormhole_dm_invite(exported["invite"], alias="alice")

    assert imported["ok"] is False
    assert imported["detail"] == "invite root manifest mismatch"


def test_imported_dm_invite_requires_matching_root_transparency_binding(tmp_path, monkeypatch):
    relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.mesh import mesh_wormhole_root_transparency

    exported, _verified = _export_verified_invite(identity_mod)
    local_identity = identity_mod.read_wormhole_identity()
    agent_id = str(local_identity.get("node_id", "") or "")

    stored = dict(relay._prekey_bundles[agent_id] or {})
    tampered_bundle = dict(stored.get("bundle") or {})
    tampered_bundle["root_manifest_witnesses"] = [
        dict(item or {}) for item in list(tampered_bundle.get("root_manifest_witnesses") or [])[:2]
    ]
    tampered_bundle["root_manifest_witness"] = dict(tampered_bundle["root_manifest_witnesses"][0] or {})
    tampered_transparency = mesh_wormhole_root_transparency.publish_root_transparency_record(
        distribution={
            "manifest": dict(tampered_bundle.get("root_manifest") or {}),
            "witnesses": list(tampered_bundle.get("root_manifest_witnesses") or []),
        }
    )
    tampered_bundle["root_transparency_record"] = dict(tampered_transparency.get("record") or {})
    relay._prekey_bundles[agent_id]["bundle"] = tampered_bundle

    imported = identity_mod.import_wormhole_dm_invite(exported["invite"], alias="alice")

    assert imported["ok"] is False
    assert imported["detail"] == "invite root transparency mismatch"


def test_imported_dm_invite_accepts_configured_external_witness_and_transparency_sources(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.mesh import mesh_wormhole_root_manifest as manifest_mod
    from services.mesh import mesh_wormhole_root_transparency as transparency_mod

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    manifest_mod.configure_external_root_witness_descriptors(
        [manifest_mod._public_witness_descriptor(external_identity)]
    )
    published = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    external_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(published["manifest"]),
    )
    manifest_mod.stage_external_root_manifest_witnesses(
        [external_receipt],
        manifest=published["manifest"],
    )

    exported, _verified = _export_verified_invite(identity_mod)
    ledger_path = tmp_path / "external_readback_ledger.json"
    package_path = tmp_path / "external_witness_source.json"
    transparency_mod.publish_root_transparency_ledger_to_file(path=str(ledger_path), max_records=8)
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                "manifest_fingerprint": str(
                    exported["invite"]["payload"]["attestations"][0]["root_manifest_fingerprint"]
                ),
                "witnesses": [external_receipt],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", ledger_path.as_uri())
    get_settings.cache_clear()

    imported = identity_mod.import_wormhole_dm_invite(exported["invite"], alias="alice")

    assert imported["ok"] is True
    assert imported["contact"]["trustSummary"]["state"] == "invite_pinned"
    assert imported["contact"]["trustSummary"]["rootWitnessProvenanceState"] == "independent_quorum"
    assert imported["contact"]["trustSummary"]["rootWitnessFinalityMet"] is True
    assert imported["contact"]["trustSummary"]["verifiedFirstContact"] is True


def test_imported_dm_invite_downgrades_verified_first_contact_when_finality_enforcement_is_enabled(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    monkeypatch.setenv("WORMHOLE_ROOT_WITNESS_FINALITY_ENFORCE", "true")
    get_settings.cache_clear()
    try:
        _exported, _verified, imported = _import_invite(identity_mod, alias="alice")
        contact = imported["contact"]

        assert imported["ok"] is True
        assert contact["trust_level"] == "invite_pinned"
        assert contact["trustSummary"]["rootDistributionState"] == "quorum_witnessed"
        assert contact["trustSummary"]["rootWitnessProvenanceState"] == "local_quorum"
        assert contact["trustSummary"]["rootWitnessFinalityMet"] is False
        assert contact["trustSummary"]["verifiedFirstContact"] is False
        assert contact["trustSummary"]["recommendedAction"] == "import_invite"
    finally:
        get_settings.cache_clear()


def test_exported_dm_invite_rejects_configured_external_transparency_readback_mismatch(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.config import get_settings
    from services.mesh import mesh_wormhole_root_manifest as manifest_mod
    from services.mesh import mesh_wormhole_root_transparency as transparency_mod

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    manifest_mod.configure_external_root_witness_descriptors(
        [manifest_mod._public_witness_descriptor(external_identity)]
    )
    published = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    external_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(published["manifest"]),
    )

    package_path = tmp_path / "external_witness_source.json"
    bad_ledger_path = tmp_path / "external_readback_bad_ledger.json"
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                "manifest_fingerprint": published["manifest_fingerprint"],
                "witnesses": [external_receipt],
            }
        ),
        encoding="utf-8",
    )
    bad_ledger_path.write_text(
        json.dumps(
            {
                "type": transparency_mod.STABLE_DM_ROOT_TRANSPARENCY_LEDGER_TYPE,
                "schema_version": 1,
                "transparency_scope": transparency_mod.ROOT_TRANSPARENCY_SCOPE,
                "exported_at": int(time.time()),
                "record_count": 0,
                "current_record_fingerprint": "",
                "head_binding_fingerprint": "",
                "chain_fingerprint": transparency_mod.transparency_record_chain_fingerprint([]),
                "records": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", bad_ledger_path.as_uri())
    get_settings.cache_clear()

    exported = identity_mod.export_wormhole_dm_invite()

    assert exported["ok"] is False
    assert exported["detail"] == "root transparency external ledger head mismatch"


def test_exported_dm_invite_rejects_stale_configured_external_witness_source(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.config import get_settings
    from services.mesh import mesh_wormhole_root_manifest as manifest_mod

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    manifest_mod.configure_external_root_witness_descriptors(
        [manifest_mod._public_witness_descriptor(external_identity)]
    )
    published = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    external_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(published["manifest"]),
    )
    package_path = tmp_path / "stale_external_witness_source.json"
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()) - 120,
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                "manifest_fingerprint": published["manifest_fingerprint"],
                "witnesses": [external_receipt],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_MAX_AGE_S", "60")
    get_settings.cache_clear()

    exported = identity_mod.export_wormhole_dm_invite()

    assert exported["ok"] is False
    assert exported["detail"] == "external root witness source stale"


def test_exported_dm_invite_rejects_stale_configured_external_transparency_readback(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.config import get_settings
    from services.mesh import mesh_wormhole_root_manifest as manifest_mod
    from services.mesh import mesh_wormhole_root_transparency as transparency_mod

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    manifest_mod.configure_external_root_witness_descriptors(
        [manifest_mod._public_witness_descriptor(external_identity)]
    )
    published = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    external_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(published["manifest"]),
    )
    package_path = tmp_path / "fresh_external_witness_source.json"
    readback_path = tmp_path / "stale_external_readback_ledger.json"
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                "manifest_fingerprint": published["manifest_fingerprint"],
                "witnesses": [external_receipt],
            }
        ),
        encoding="utf-8",
    )
    current_distribution = manifest_mod.get_current_root_manifest()
    current_transparency = transparency_mod.get_current_root_transparency_record(distribution=current_distribution)
    stale_ledger = transparency_mod.export_root_transparency_ledger()["ledger"]
    stale_ledger["exported_at"] = int(time.time()) - 120
    readback_path.write_text(json.dumps(stale_ledger), encoding="utf-8")

    assert current_transparency["ok"] is True

    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", readback_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_MAX_AGE_S", "60")
    get_settings.cache_clear()

    exported = identity_mod.export_wormhole_dm_invite()

    assert exported["ok"] is False
    assert exported["detail"] == "root transparency external ledger stale"


def test_external_witness_source_loss_downgrades_operator_state_and_blocks_strong_export(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.config import get_settings
    from services.mesh import mesh_wormhole_root_manifest as manifest_mod

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    package_path = tmp_path / "external_witness_source_loss.json"

    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    get_settings.cache_clear()

    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
            }
        ),
        encoding="utf-8",
    )

    first_distribution = manifest_mod.get_current_root_manifest()
    current_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(first_distribution["manifest"]),
    )
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                "manifest_fingerprint": first_distribution["manifest_fingerprint"],
                "witnesses": [current_receipt],
            }
        ),
        encoding="utf-8",
    )

    current_distribution = manifest_mod.get_current_root_manifest()
    package_path.unlink()

    source_lost_distribution = manifest_mod.get_current_root_manifest()
    failed_export = identity_mod.export_wormhole_dm_invite()

    assert current_distribution["external_witness_operator_state"] == "current"
    assert current_distribution["external_witness_reacquire_required"] is False
    assert source_lost_distribution["external_witness_refresh_ok"] is False
    assert "source unreadable" in str(source_lost_distribution["external_witness_refresh_detail"] or "")
    assert source_lost_distribution["external_witness_receipts_current"] is True
    assert source_lost_distribution["external_witness_operator_state"] == "error"
    assert source_lost_distribution["external_witness_reacquire_required"] is True
    assert failed_export["ok"] is False
    assert "external root witness import source unreadable" in str(failed_export.get("detail", "") or "")


def test_imported_dm_invite_ignores_local_external_source_and_readback_mismatch(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.mesh import mesh_wormhole_root_manifest as manifest_mod
    from services.mesh import mesh_wormhole_root_transparency as transparency_mod

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    manifest_mod.configure_external_root_witness_descriptors(
        [manifest_mod._public_witness_descriptor(external_identity)]
    )
    published = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    external_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(published["manifest"]),
    )
    manifest_mod.stage_external_root_manifest_witnesses(
        [external_receipt],
        manifest=published["manifest"],
    )

    exported, _verified = _export_verified_invite(identity_mod)
    bad_ledger_path = tmp_path / "external_readback_bad_ledger.json"
    package_path = tmp_path / "external_witness_source.json"
    bad_ledger_path.write_text(
        json.dumps(
            {
                "type": transparency_mod.STABLE_DM_ROOT_TRANSPARENCY_LEDGER_TYPE,
                "schema_version": 1,
                "transparency_scope": transparency_mod.ROOT_TRANSPARENCY_SCOPE,
                "exported_at": int(time.time()),
                "record_count": 0,
                "current_record_fingerprint": "",
                "head_binding_fingerprint": "",
                "chain_fingerprint": transparency_mod.transparency_record_chain_fingerprint([]),
                "records": [],
            }
        ),
        encoding="utf-8",
    )
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                "manifest_fingerprint": "00" * 32,
                "witnesses": [external_receipt],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", bad_ledger_path.as_uri())
    get_settings.cache_clear()

    verified = identity_mod.verify_wormhole_dm_invite(exported["invite"])
    imported = identity_mod.import_wormhole_dm_invite(exported["invite"], alias="alice")

    assert verified["ok"] is True
    assert imported["ok"] is True


def test_deployment_style_external_reacquisition_restores_strong_invite_bootstrap(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    from services.config import get_settings
    from services.mesh import mesh_wormhole_root_manifest as manifest_mod
    from services.mesh import mesh_wormhole_root_transparency as transparency_mod

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    package_path = tmp_path / "deployment_external_witness.json"
    ledger_path = tmp_path / "deployment_external_ledger.json"

    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH", str(ledger_path))
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", ledger_path.as_uri())
    get_settings.cache_clear()

    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
            }
        ),
        encoding="utf-8",
    )

    first_distribution = manifest_mod.get_current_root_manifest()
    assert first_distribution["external_witness_operator_state"] == "descriptors_only"

    first_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(first_distribution["manifest"]),
    )
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                "manifest_fingerprint": first_distribution["manifest_fingerprint"],
                "witnesses": [first_receipt],
            }
        ),
        encoding="utf-8",
    )

    current_distribution = manifest_mod.get_current_root_manifest()
    current_transparency = transparency_mod.get_current_root_transparency_record(distribution=current_distribution)
    initial_import = _import_invite(identity_mod, alias="alice")

    assert current_distribution["external_witness_operator_state"] == "current"
    assert current_transparency["ledger_operator_state"] == "current"
    assert initial_import[2]["ok"] is True

    republished = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=2)
    stale_distribution = manifest_mod.get_current_root_manifest()
    stale_transparency = transparency_mod.get_current_root_transparency_record(distribution=republished)
    stale_export = identity_mod.export_wormhole_dm_invite()

    assert stale_distribution["external_witness_operator_state"] == "stale"
    assert stale_distribution["external_witness_reacquire_required"] is True
    assert stale_transparency["ledger_operator_state"] == "current"
    assert stale_export["ok"] is False
    assert "external root witness source manifest_fingerprint mismatch" in str(
        stale_export.get("detail", "")
    )

    refreshed_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(stale_distribution["manifest"]),
    )
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                "manifest_fingerprint": stale_distribution["manifest_fingerprint"],
                "witnesses": [refreshed_receipt],
            }
        ),
        encoding="utf-8",
    )

    refreshed_distribution = manifest_mod.get_current_root_manifest()
    refreshed_transparency = transparency_mod.get_current_root_transparency_record(distribution=refreshed_distribution)
    recovered_export = identity_mod.export_wormhole_dm_invite()
    recovered_import = identity_mod.import_wormhole_dm_invite(recovered_export["invite"], alias="alice-recovered")

    assert refreshed_distribution["external_witness_operator_state"] == "current"
    assert refreshed_distribution["external_witness_reacquire_required"] is False
    assert refreshed_transparency["ledger_operator_state"] == "current"
    assert recovered_import["ok"] is True


def test_compat_dm_invite_import_is_blocked_by_default(tmp_path, monkeypatch):
    _relay, identity_mod, contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    invite, verified = _export_compat_invite(identity_mod)

    imported = identity_mod.import_wormhole_dm_invite(invite, alias="compat")

    assert imported["ok"] is False
    assert imported["detail"] == "compat dm invite import disabled; ask the sender to re-export a current signed invite"
    assert verified["ok"] is True
    assert contacts_mod.list_wormhole_dm_contacts() == {}


def test_compat_dm_invite_import_downgrades_to_tofu_pinned_when_compat_enabled(tmp_path, monkeypatch):
    _relay, identity_mod, contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    invite, verified = _export_compat_invite(identity_mod)
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    monkeypatch.setenv("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT_UNTIL", "2099-01-01")
    get_settings.cache_clear()

    try:
        imported = identity_mod.import_wormhole_dm_invite(invite, alias="compat")
    finally:
        get_settings.cache_clear()

    contact = imported["contact"]
    local_identity = identity_mod.read_wormhole_identity()

    assert imported["ok"] is True
    assert imported["invite_attested"] is False
    assert imported["detail"] == "legacy invite imported as tofu_pinned; SAS verification required before first contact"
    assert imported["peer_id"] == local_identity["node_id"]
    assert imported["invite_peer_id"] == verified["peer_id"]
    assert imported["trust_level"] == "tofu_pinned"
    assert contact["trust_level"] == "tofu_pinned"
    assert contact["trustSummary"]["state"] == "tofu_pinned"
    assert contact["alias"] == "compat"
    assert contact["remotePrekeyFingerprint"] == imported["trust_fingerprint"]
    assert contact["invitePinnedTrustFingerprint"] == ""
    assert contact["invitePinnedAt"] == 0
    assert contact["invitePinnedPrekeyLookupHandle"] == invite["payload"]["prekey_lookup_handle"]
    assert contacts_mod.list_wormhole_dm_contacts()[imported["peer_id"]]["trust_level"] == "tofu_pinned"


def test_legacy_dm_invite_import_is_blocked_by_default(tmp_path, monkeypatch):
    _relay, identity_mod, contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    invite, _verified = _export_legacy_invite(identity_mod)

    imported = identity_mod.import_wormhole_dm_invite(invite, alias="legacy")

    assert imported["ok"] is False
    assert imported["detail"] == "legacy dm invite import disabled; ask the sender to re-export a current signed invite"
    assert contacts_mod.list_wormhole_dm_contacts() == {}


def test_legacy_dm_invite_import_downgrades_to_tofu_pinned_when_compat_enabled(tmp_path, monkeypatch):
    _relay, identity_mod, contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    invite, _verified = _export_legacy_invite(identity_mod)
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    monkeypatch.setenv("MESH_ALLOW_COMPAT_DM_INVITE_IMPORT_UNTIL", "2099-01-01")
    get_settings.cache_clear()

    try:
        imported = identity_mod.import_wormhole_dm_invite(invite, alias="legacy")
    finally:
        get_settings.cache_clear()

    contact = imported["contact"]
    local_identity = identity_mod.read_wormhole_identity()

    assert imported["ok"] is True
    assert imported["invite_attested"] is False
    assert imported["detail"] == "legacy invite imported as tofu_pinned; SAS verification required before first contact"
    assert imported["peer_id"] == local_identity["node_id"]
    assert imported["trust_level"] == "tofu_pinned"
    assert contact["trust_level"] == "tofu_pinned"
    assert contact["trustSummary"]["state"] == "tofu_pinned"
    assert contact["alias"] == "legacy"
    assert contact["remotePrekeyFingerprint"] == imported["trust_fingerprint"]
    assert contact["invitePinnedTrustFingerprint"] == ""
    assert contact["invitePinnedAt"] == 0
    assert contact["invitePinnedPrekeyLookupHandle"] == ""
    assert contacts_mod.list_wormhole_dm_contacts()[imported["peer_id"]]["trust_level"] == "tofu_pinned"


def test_invite_pinned_contact_can_upgrade_to_sas_verified(tmp_path, monkeypatch):
    _relay, identity_mod, contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    _exported, _verified, imported = _import_invite(identity_mod)
    monkeypatch.setattr(
        contacts_mod,
        "_derive_expected_contact_sas_phrase",
        lambda *_args, **_kwargs: {"ok": True, "phrase": "able acid", "peer_ref": imported["peer_id"], "words": 2},
    )

    result = contacts_mod.confirm_sas_verification(imported["peer_id"], "able acid")

    assert result["ok"] is True
    assert result["trust_level"] == "sas_verified"


def test_invite_pinned_mismatch_becomes_continuity_broken_and_ack_rejects(tmp_path, monkeypatch):
    _relay, identity_mod, contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    _exported, _verified, imported = _import_invite(identity_mod)

    mismatch = contacts_mod.observe_remote_prekey_identity(
        imported["peer_id"],
        fingerprint="ff" * 32,
        sequence=2,
        signed_at=int(time.time()),
    )
    ack = contacts_mod.acknowledge_changed_fingerprint(imported["peer_id"])

    assert mismatch["trust_level"] == "continuity_broken"
    assert ack["ok"] is False
    assert "invite-pinned" in ack["detail"]


def test_reimport_with_changed_root_fails_closed_and_marks_continuity_broken(tmp_path, monkeypatch):
    _relay, identity_mod, contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    _exported, _verified, imported = _import_invite(identity_mod)

    from services.mesh import mesh_wormhole_persona

    persona_state = mesh_wormhole_persona.read_wormhole_persona_state()
    persona_state["previous_root_identity"] = {
        **dict(persona_state.get("root_identity") or {}),
        "scope": "previous_root",
    }
    persona_state["root_identity"] = mesh_wormhole_persona._identity_record(scope="root", label="root")
    mesh_wormhole_persona._write_wormhole_persona_state(persona_state)

    rotated = identity_mod.export_wormhole_dm_invite()
    assert rotated["ok"] is True

    result = identity_mod.import_wormhole_dm_invite(rotated["invite"], alias="alice-reimport")

    assert result["ok"] is False
    assert result["trust_level"] == "continuity_broken"
    assert "root continuity mismatch" in result["detail"]
    assert result["contact"]["trustSummary"]["state"] == "continuity_broken"
    assert result["contact"]["trustSummary"]["rootMismatch"] is True
    refreshed = contacts_mod.list_wormhole_dm_contacts()[imported["peer_id"]]
    assert refreshed["trust_level"] == "continuity_broken"


def test_compose_wormhole_dm_fails_closed_on_pinned_invite_mismatch(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    _exported, _verified, imported = _import_invite(identity_mod)
    local_identity = identity_mod.read_wormhole_identity()

    import main

    monkeypatch.setattr(main, "_resolve_dm_aliases", lambda **_kw: ("local", "remote"))
    monkeypatch.setattr(main, "has_mls_dm_session", lambda *_a, **_kw: {"ok": True, "exists": False})
    monkeypatch.setattr(
        main,
        "fetch_dm_prekey_bundle",
        lambda _peer_id: {
            "ok": True,
            "agent_id": imported["peer_id"],
            "identity_dh_pub_key": local_identity["dh_pub_key"],
            "public_key": local_identity["public_key"],
            "public_key_algo": local_identity["public_key_algo"],
            "protocol_version": PROTOCOL_VERSION,
            "sequence": 2,
            "signed_at": int(time.time()),
            "mls_key_package": "ZmFrZQ==",
            "trust_fingerprint": "ff" * 32,
        },
    )

    result = main.compose_wormhole_dm(
        peer_id=imported["peer_id"],
        peer_dh_pub=local_identity["dh_pub_key"],
        plaintext="hello",
    )

    assert result["ok"] is False
    assert result["trust_level"] == "continuity_broken"


def test_compose_wormhole_dm_blocks_unverified_first_contact(tmp_path, monkeypatch):
    _relay, _identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)

    import main

    initiated = {"called": False}
    monkeypatch.setattr(main, "_resolve_dm_aliases", lambda **_kw: ("local", "remote"))
    monkeypatch.setattr(main, "has_mls_dm_session", lambda *_a, **_kw: {"ok": True, "exists": False})
    monkeypatch.setattr(
        main,
        "initiate_mls_dm_session",
        lambda *_a, **_kw: initiated.__setitem__("called", True) or {"ok": True, "welcome": "welcome"},
    )
    monkeypatch.setattr(
        main,
        "fetch_dm_prekey_bundle",
        lambda _peer_id: {
            "ok": True,
            "agent_id": "peer-unverified",
            "identity_dh_pub_key": "peer-dh-pub",
            "public_key": "peer-signing-pub",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
            "sequence": 2,
            "signed_at": int(time.time()),
            "mls_key_package": "ZmFrZQ==",
            "trust_fingerprint": "11" * 32,
        },
    )

    result = main.compose_wormhole_dm(
        peer_id="peer-unverified",
        peer_dh_pub="peer-dh-pub",
        plaintext="hello",
    )

    assert result["ok"] is False
    assert result["detail"] == "signed invite or SAS verification required before secure first contact"
    assert result["trust_level"] == "tofu_pinned"
    assert initiated["called"] is False


def test_compose_wormhole_dm_blocks_legacy_fallback_for_invite_scoped_contact(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    _exported, _verified, imported = _import_invite(identity_mod)

    import main

    legacy_called = {"value": False}
    monkeypatch.setattr(main, "_resolve_dm_aliases", lambda **_kw: ("local", "remote"))
    monkeypatch.setattr(main, "has_mls_dm_session", lambda *_a, **_kw: {"ok": True, "exists": False})
    monkeypatch.setattr(main, "fetch_dm_prekey_bundle", lambda _peer_id: {"ok": False, "detail": "Prekey bundle not found"})
    monkeypatch.setattr(
        main,
        "encrypt_wormhole_dm",
        lambda **_kwargs: legacy_called.__setitem__("value", True) or {"ok": True, "result": "legacy"},
    )

    result = main.compose_wormhole_dm(
        peer_id=imported["peer_id"],
        peer_dh_pub="fallback-dh",
        plaintext="hello",
    )

    assert result["ok"] is False
    assert result["detail"] == "invite-scoped bootstrap required; legacy DM fallback disabled"
    assert result["trust_level"] == "invite_pinned"
    assert legacy_called["value"] is False


def test_bootstrap_encrypt_fails_closed_without_claiming_otk_on_pinned_invite_mismatch(tmp_path, monkeypatch):
    relay, identity_mod, _contacts_mod, prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    registered = prekey_mod.register_wormhole_prekey_bundle(force_signed_prekey=True)
    assert registered["ok"] is True

    _exported, _verified, imported = _import_invite(identity_mod)

    agent_id = registered["agent_id"]
    before = len(list((relay.get_prekey_bundle(agent_id) or {}).get("bundle", {}).get("one_time_prekeys") or []))
    tampered_bundle = dict((relay.get_prekey_bundle(agent_id) or {}).get("bundle") or {})
    tampered_bundle["identity_dh_pub_key"] = _b64_pub(x25519.X25519PrivateKey.generate().public_key())
    tampered_bundle = prekey_mod._attach_bundle_signature(tampered_bundle, signed_at=int(time.time()))
    relay._prekey_bundles[agent_id]["bundle"] = tampered_bundle

    result = prekey_mod.bootstrap_encrypt_for_peer(agent_id, "hello")
    after = len(list((relay.get_prekey_bundle(agent_id) or {}).get("bundle", {}).get("one_time_prekeys") or []))

    assert result["ok"] is False
    assert result["trust_level"] == "continuity_broken"
    assert before == after


def test_bootstrap_encrypt_blocks_unverified_first_contact_without_claiming_otk(tmp_path, monkeypatch):
    from services.config import get_settings

    relay, _identity_mod, _contacts_mod, prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    registered = prekey_mod.register_wormhole_prekey_bundle(force_signed_prekey=True)
    assert registered["ok"] is True

    agent_id = registered["agent_id"]
    before = len(list((relay.get_prekey_bundle(agent_id) or {}).get("bundle", {}).get("one_time_prekeys") or []))
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "false")
    get_settings.cache_clear()

    try:
        result = prekey_mod.bootstrap_encrypt_for_peer(agent_id, "hello")
        after = len(list((relay.get_prekey_bundle(agent_id) or {}).get("bundle", {}).get("one_time_prekeys") or []))

        assert result["ok"] is False
        assert result["detail"] == "legacy agent_id lookup disabled; use invite lookup handle"
        assert before == after
    finally:
        get_settings.cache_clear()


def test_bootstrap_encrypt_requires_independent_quorum_finality_when_enforced(tmp_path, monkeypatch):
    relay, identity_mod, _contacts_mod, prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    registered = prekey_mod.register_wormhole_prekey_bundle(force_signed_prekey=True)
    assert registered["ok"] is True
    _exported, _verified, imported = _import_invite(identity_mod)

    agent_id = registered["agent_id"]
    before = len(list((relay.get_prekey_bundle(agent_id) or {}).get("bundle", {}).get("one_time_prekeys") or []))
    monkeypatch.setenv("WORMHOLE_ROOT_WITNESS_FINALITY_ENFORCE", "true")
    get_settings.cache_clear()

    try:
        result = prekey_mod.bootstrap_encrypt_for_peer(agent_id, "hello")
        after = len(list((relay.get_prekey_bundle(agent_id) or {}).get("bundle", {}).get("one_time_prekeys") or []))

        assert result["ok"] is False
        assert result["detail"] == "independent quorum root witness finality required before secure first contact"
        assert result["trust_level"] == "invite_pinned"
        assert imported["contact"]["trustSummary"]["rootWitnessProvenanceState"] == "local_quorum"
        assert before == after
    finally:
        get_settings.cache_clear()


def test_bootstrap_decrypt_rejects_sender_static_key_that_mismatches_pinned_invite(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, prekey_mod = _fresh_wormhole_state(tmp_path, monkeypatch)
    _exported, _verified, imported = _import_invite(identity_mod)

    fake_envelope = {
        "h": {
            "ik_pub": _b64_pub(x25519.X25519PrivateKey.generate().public_key()),
            "ek_pub": "ZmFrZQ==",
            "spk_id": 1,
            "otk_id": 0,
        },
        "ct": base64.b64encode(b"0" * 16).decode("ascii"),
    }
    ciphertext = "x3dh1:" + base64.b64encode(
        json.dumps(fake_envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    result = prekey_mod.bootstrap_decrypt_from_sender(imported["peer_id"], ciphertext)

    assert result["ok"] is False
    assert result["detail"] == "sender bootstrap key mismatches pinned invite"
