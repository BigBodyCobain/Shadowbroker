"""P2B: Prove that invite-scoped prekey lookup handles reduce stable
identity correlation on the DM bootstrap path.

Tests verify:
1. Invite export generates a prekey_lookup_handle and persists it.
2. Prekey bundle registration stores the handle as a relay lookup alias.
3. Prekey bundle fetch by lookup_token succeeds without exposing agent_id.
4. DH key fetch by lookup_token succeeds without exposing agent_id.
5. Legacy agent_id lookup still works (explicit fallback).
6. Invite import stores the lookup handle on the contact record.
7. The lookup handle is opaque (not derivable from agent_id).
"""

import hashlib
import time

from services.config import get_settings
from services.mesh import (
    mesh_compatibility,
    mesh_dm_relay,
    mesh_secure_storage,
    mesh_wormhole_persona,
    mesh_wormhole_root_manifest,
    mesh_wormhole_root_transparency,
)


def _isolated_relay(tmp_path, monkeypatch):
    """Create an isolated DMRelay with tmp_path storage."""
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(mesh_wormhole_persona, "LEGACY_DM_IDENTITY_FILE", tmp_path / "wormhole_identity.json")
    monkeypatch.setattr(mesh_wormhole_root_manifest, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_root_transparency, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_compatibility, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_compatibility, "COMPATIBILITY_FILE", tmp_path / "mesh_compatibility_usage.json")
    get_settings.cache_clear()
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)
    return relay


def _isolated_invite_state(tmp_path, monkeypatch):
    """Create isolated relay/root/persona state for invite export paths."""
    for key in (
        "MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_PATH",
        "MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI",
        "MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH",
        "MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI",
    ):
        monkeypatch.setenv(key, "")
    relay = _isolated_relay(tmp_path, monkeypatch)
    mesh_wormhole_persona.bootstrap_wormhole_persona_state(force=True)
    get_settings.cache_clear()
    return relay


def _valid_bundle_record(agent_id: str):
    """Create a minimal valid prekey bundle record for testing."""
    from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from services.mesh.mesh_crypto import build_signature_payload, derive_node_id
    from services.mesh.mesh_protocol import PROTOCOL_VERSION
    from services.mesh.mesh_wormhole_prekey import (
        _attach_bundle_root_attestation,
        _attach_bundle_root_distribution,
        _bundle_signature_payload,
    )
    import base64

    # Generate signing key
    signing_key = ed25519.Ed25519PrivateKey.generate()
    pub_bytes = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    pub_b64 = base64.b64encode(pub_bytes).decode("ascii")

    # Generate DH key
    dh_key = x25519.X25519PrivateKey.generate()
    dh_pub = dh_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    dh_pub_b64 = base64.b64encode(dh_pub).decode("ascii")

    derived_id = derive_node_id(pub_b64)

    now = int(time.time())
    signed_prekey_payload = {
        "signed_prekey_id": 1,
        "signed_prekey_pub": dh_pub_b64,
        "signed_prekey_timestamp": now,
    }
    signed_prekey_sig_payload = build_signature_payload(
        event_type="dm_signed_prekey",
        node_id=derived_id,
        sequence=1,
        payload=signed_prekey_payload,
    )
    signed_prekey_signature = signing_key.sign(signed_prekey_sig_payload.encode("utf-8")).hex()

    # Build bundle payload with signature
    bundle_content = {
        "identity_dh_pub_key": dh_pub_b64,
        "dh_algo": "X25519",
        "signed_prekey_id": 1,
        "signed_prekey_pub": dh_pub_b64,
        "signed_prekey_signature": signed_prekey_signature,
        "signed_prekey_timestamp": now,
        "signed_at": now,
        "bundle_signature": "",
        "mls_key_package": "",
        "one_time_prekeys": [],
        "one_time_prekey_count": 0,
    }
    bundle_content = _attach_bundle_root_distribution(bundle_content)
    bundle_content = _attach_bundle_root_attestation(
        agent_id=derived_id,
        public_key=pub_b64,
        public_key_algo="Ed25519",
        protocol_version=PROTOCOL_VERSION,
        bundle=bundle_content,
    )
    bundle_sig = signing_key.sign(_bundle_signature_payload(bundle_content).encode("utf-8"))
    bundle_content["bundle_signature"] = bundle_sig.hex()

    return {
        "agent_id": derived_id,
        "bundle": bundle_content,
        "public_key": pub_b64,
        "public_key_algo": "Ed25519",
        "protocol_version": PROTOCOL_VERSION,
        "dh_pub_key": dh_pub_b64,
        "dh_algo": "X25519",
    }


# ---------------------------------------------------------------------------
# 1. Relay alias registration and lookup
# ---------------------------------------------------------------------------


class TestRelayPrekeyLookupAliases:
    """DMRelay supports lookup aliases for prekey bundles."""

    def test_register_with_lookup_aliases(self, tmp_path, monkeypatch):
        """Prekey bundle registered with aliases is retrievable by alias."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        ok, detail, meta = relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
            lookup_aliases=["handle-abc-123"],
        )
        assert ok is True

        # Lookup by alias succeeds.
        found, resolved_id = relay.get_prekey_bundle_by_lookup("handle-abc-123")
        assert found is not None
        assert resolved_id == agent_id

    def test_alias_lookup_returns_none_for_unknown(self, tmp_path, monkeypatch):
        """Unknown alias returns None."""
        relay = _isolated_relay(tmp_path, monkeypatch)

        found, resolved_id = relay.get_prekey_bundle_by_lookup("nonexistent")
        assert found is None
        assert resolved_id == ""

    def test_alias_does_not_leak_in_lookup_response(self, tmp_path, monkeypatch):
        """Alias-resolved bundle contains agent_id but alias is not in the response."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]
        alias = "invite-scoped-handle-xyz"

        relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
            lookup_aliases=[alias],
        )

        found, resolved_id = relay.get_prekey_bundle_by_lookup(alias)
        assert found is not None
        # The alias itself is not in the bundle data.
        assert alias not in str(found)
        # But the resolved agent_id is returned for downstream use.
        assert resolved_id == agent_id

    def test_dh_key_lookup_by_alias(self, tmp_path, monkeypatch):
        """DH key can be fetched via prekey lookup alias without raw agent_id."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]
        alias = "handle-dh-lookup"

        # Register DH key under agent_id.
        relay.register_dh_key(
            agent_id,
            record["dh_pub_key"],
            record["dh_algo"],
            int(time.time()),
            "sig",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
        )

        # Register prekey bundle with alias (establishes alias → agent_id mapping).
        relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
            lookup_aliases=[alias],
        )

        # DH key lookup by alias succeeds.
        dh_key, resolved_id = relay.get_dh_key_by_lookup(alias)
        assert dh_key is not None
        assert resolved_id == agent_id
        assert dh_key["dh_pub_key"] == record["dh_pub_key"]

    def test_legacy_agent_id_lookup_still_works(self, tmp_path, monkeypatch):
        """Direct agent_id lookup remains functional (legacy fallback)."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
            lookup_aliases=["some-alias"],
        )

        # Direct lookup by agent_id still works.
        found = relay.get_prekey_bundle(agent_id)
        assert found is not None

    def test_multiple_aliases_supported(self, tmp_path, monkeypatch):
        """Multiple invites can each have their own lookup alias."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
            lookup_aliases=["alias-1", "alias-2", "alias-3"],
        )

        for alias in ["alias-1", "alias-2", "alias-3"]:
            found, resolved_id = relay.get_prekey_bundle_by_lookup(alias)
            assert found is not None, f"Alias {alias} should resolve"
            assert resolved_id == agent_id

    def test_lookup_alias_expires_after_configured_ttl(self, tmp_path, monkeypatch):
        """Lookup aliases are time-bounded even while the bundle itself is still valid."""
        monkeypatch.setenv("MESH_DM_PREKEY_LOOKUP_ALIAS_TTL_DAYS", "1")
        relay = _isolated_relay(tmp_path, monkeypatch)
        current = {"value": 1_000_000.0}
        monkeypatch.setattr(mesh_dm_relay.time, "time", lambda: current["value"])

        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]
        relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
            lookup_aliases=["ttl-bound-alias"],
        )

        found, resolved_id = relay.get_prekey_bundle_by_lookup("ttl-bound-alias")
        assert found is not None
        assert resolved_id == agent_id

        current["value"] += 2 * 86400
        found, resolved_id = relay.get_prekey_bundle_by_lookup("ttl-bound-alias")
        assert found is None
        assert resolved_id == ""
        assert "ttl-bound-alias" not in relay._prekey_lookup_aliases

    def test_legacy_flat_alias_map_is_migrated_on_load(self, tmp_path, monkeypatch):
        """Older relay files with flat alias mappings are loaded and rewritten safely."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
            lookup_aliases=["legacy-flat-alias"],
        )
        relay._flush()

        payload = mesh_secure_storage.read_secure_json(mesh_dm_relay.RELAY_FILE, lambda: {})
        payload["prekey_lookup_aliases"] = {"legacy-flat-alias": agent_id}
        mesh_secure_storage.write_secure_json(mesh_dm_relay.RELAY_FILE, payload)

        reloaded = mesh_dm_relay.DMRelay()
        found, resolved_id = reloaded.get_prekey_bundle_by_lookup("legacy-flat-alias")
        assert found is not None
        assert resolved_id == agent_id
        assert reloaded._prekey_lookup_aliases["legacy-flat-alias"]["agent_id"] == agent_id
        assert reloaded._prekey_lookup_aliases["legacy-flat-alias"]["updated_at"] > 0

        reloaded._flush()
        rewritten = mesh_secure_storage.read_secure_json(mesh_dm_relay.RELAY_FILE, lambda: {})
        assert isinstance(rewritten["prekey_lookup_aliases"]["legacy-flat-alias"], dict)
        assert rewritten["prekey_lookup_aliases"]["legacy-flat-alias"]["agent_id"] == agent_id

    def test_prekey_transparency_head_advances_append_only(self, tmp_path, monkeypatch):
        """Each accepted prekey publication advances an append-only transparency head."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        ok1, _detail1, meta1 = relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
        )
        ok2, _detail2, meta2 = relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            2,
        )

        assert ok1 is True
        assert ok2 is True
        assert meta1["prekey_transparency_size"] == 1
        assert meta2["prekey_transparency_size"] == 2
        assert meta1["prekey_transparency_head"] != meta2["prekey_transparency_head"]
        stored = relay.get_prekey_bundle(agent_id)
        assert stored["prekey_transparency_head"] == meta2["prekey_transparency_head"]
        assert len(stored["prekey_transparency_log"]) == 2
        assert stored["prekey_transparency_log"][1]["previous_head"] == meta1["prekey_transparency_head"]


# ---------------------------------------------------------------------------
# 2. Invite export generates opaque lookup handle
# ---------------------------------------------------------------------------


class TestInviteExportLookupHandle:
    """Invite export includes an opaque prekey_lookup_handle."""

    def test_invite_contains_lookup_handle(self, tmp_path, monkeypatch):
        """Exported invite payload includes a prekey_lookup_handle."""
        _isolated_invite_state(tmp_path, monkeypatch)

        from services.mesh.mesh_wormhole_identity import export_wormhole_dm_invite

        result = export_wormhole_dm_invite()
        assert result["ok"] is True
        payload = result["invite"]["payload"]
        handle = str(payload.get("prekey_lookup_handle", "") or "")
        assert len(handle) >= 24, "Lookup handle must be a substantial opaque token"

    def test_lookup_handle_is_not_derived_from_agent_id(self, tmp_path, monkeypatch):
        """The handle must not be trivially derivable from the agent_id."""
        _isolated_invite_state(tmp_path, monkeypatch)

        from services.mesh.mesh_wormhole_identity import export_wormhole_dm_invite

        result = export_wormhole_dm_invite()
        agent_id = result["peer_id"]
        handle = result["invite"]["payload"]["prekey_lookup_handle"]

        # Not a simple hash/derivation of agent_id.
        assert handle != agent_id
        assert handle != hashlib.sha256(agent_id.encode()).hexdigest()
        assert agent_id not in handle

    def test_successive_invites_produce_different_handles(self, tmp_path, monkeypatch):
        """Each invite gets a unique handle to prevent cross-invite correlation."""
        _isolated_invite_state(tmp_path, monkeypatch)

        from services.mesh.mesh_wormhole_identity import export_wormhole_dm_invite

        r1 = export_wormhole_dm_invite()
        r2 = export_wormhole_dm_invite()
        h1 = r1["invite"]["payload"]["prekey_lookup_handle"]
        h2 = r2["invite"]["payload"]["prekey_lookup_handle"]
        assert h1 != h2, "Each invite must use a fresh, unique lookup handle"

    def test_expired_lookup_handles_are_pruned_from_identity_state(self, tmp_path, monkeypatch):
        from services.mesh import mesh_wormhole_identity

        _isolated_invite_state(tmp_path, monkeypatch)
        now = [1_700_000_000]
        monkeypatch.setattr(mesh_wormhole_identity.time, "time", lambda: now[0])
        get_settings.cache_clear()

        result = mesh_wormhole_identity.export_wormhole_dm_invite(expires_in_s=60)
        assert result["ok"] is True
        handle = str(result["invite"]["payload"]["prekey_lookup_handle"] or "")

        assert handle in mesh_wormhole_identity.get_prekey_lookup_handles()

        now[0] += 61

        assert handle not in mesh_wormhole_identity.get_prekey_lookup_handles()
        data = mesh_wormhole_identity.read_wormhole_identity()
        assert data["prekey_lookup_handles"] == []

    def test_unbounded_lookup_handles_age_out_on_stale_window(self, tmp_path, monkeypatch):
        from services.mesh import mesh_wormhole_identity

        _isolated_invite_state(tmp_path, monkeypatch)
        monkeypatch.setenv("MESH_DM_PREKEY_LOOKUP_ALIAS_TTL_DAYS", "1")
        now = [1_700_000_000]
        monkeypatch.setattr(mesh_wormhole_identity.time, "time", lambda: now[0])
        get_settings.cache_clear()

        try:
            result = mesh_wormhole_identity.export_wormhole_dm_invite(expires_in_s=0)
            assert result["ok"] is True
            handle = str(result["invite"]["payload"]["prekey_lookup_handle"] or "")

            assert handle in mesh_wormhole_identity.get_prekey_lookup_handles()

            now[0] += 86401

            assert handle not in mesh_wormhole_identity.get_prekey_lookup_handles()
        finally:
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 3. Invite import stores lookup handle on contact
# ---------------------------------------------------------------------------


class TestInviteImportStoresHandle:
    """pin_wormhole_dm_invite stores prekey_lookup_handle on the contact."""

    def test_contact_stores_lookup_handle(self, tmp_path, monkeypatch):
        """After import, the contact record has invitePinnedPrekeyLookupHandle."""
        from services.mesh import mesh_wormhole_contacts

        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "contacts.json")
        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")

        contact = mesh_wormhole_contacts.pin_wormhole_dm_invite(
            "peer-abc",
            invite_payload={
                "trust_fingerprint": "aa" * 32,
                "agent_id": "peer-abc",
                "public_key": "cHVi",
                "public_key_algo": "Ed25519",
                "identity_dh_pub_key": "ZGg=",
                "dh_algo": "X25519",
                "issued_at": int(time.time()),
                "prekey_lookup_handle": "invite-handle-456",
            },
        )

        assert contact["invitePinnedPrekeyLookupHandle"] == "invite-handle-456"

    def test_contact_without_handle_defaults_empty(self, tmp_path, monkeypatch):
        """Legacy invites without handle result in empty string (not error)."""
        from services.mesh import mesh_wormhole_contacts

        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "contacts.json")
        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")

        contact = mesh_wormhole_contacts.pin_wormhole_dm_invite(
            "peer-old",
            invite_payload={
                "trust_fingerprint": "bb" * 32,
                "agent_id": "peer-old",
                "public_key": "cHVi",
                "public_key_algo": "Ed25519",
                "identity_dh_pub_key": "ZGg=",
                "dh_algo": "X25519",
                "issued_at": int(time.time()),
                # No prekey_lookup_handle — legacy invite.
            },
        )

        assert contact["invitePinnedPrekeyLookupHandle"] == ""


# ---------------------------------------------------------------------------
# 4. fetch_dm_prekey_bundle uses lookup_token
# ---------------------------------------------------------------------------


class TestFetchPrekeyBundleByLookup:
    """fetch_dm_prekey_bundle supports lookup_token parameter."""

    def test_fetch_by_lookup_token(self, tmp_path, monkeypatch):
        """Prekey bundle is fetchable via lookup_token without agent_id."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
            lookup_aliases=["lookup-xyz"],
        )

        from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle

        result = fetch_dm_prekey_bundle(lookup_token="lookup-xyz")
        assert result["ok"] is True
        assert result["agent_id"] == agent_id
        assert result["lookup_mode"] == "invite_lookup_handle"

    def test_fetch_by_lookup_token_without_agent_id_arg(self, tmp_path, monkeypatch):
        """Caller does not need to supply agent_id when using lookup_token."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
            lookup_aliases=["handle-only"],
        )

        from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle

        # Only lookup_token, no agent_id.
        result = fetch_dm_prekey_bundle(agent_id="", lookup_token="handle-only")
        assert result["ok"] is True
        assert result["agent_id"] == agent_id
        assert result["lookup_mode"] == "invite_lookup_handle"

    def test_fetch_invalid_lookup_token_does_not_fallback_to_agent_id(self, tmp_path, monkeypatch):
        """If lookup_token is present but invalid, do not silently leak agent_id."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
        )

        from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle

        # Invalid lookup_token + valid agent_id must not silently fall back.
        result = fetch_dm_prekey_bundle(agent_id=agent_id, lookup_token="bogus")
        assert result["ok"] is False
        assert result["detail"] in {
            "Prekey bundle not found",
            "peer prekey lookup unavailable",
        }

    def test_fetch_agent_id_uses_pinned_contact_lookup_handle(self, tmp_path, monkeypatch):
        """Pinned invite lookup handle is used before direct agent_id lookup."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
            lookup_aliases=["contact-bound-handle"],
        )

        from services.mesh import mesh_wormhole_contacts

        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
        mesh_wormhole_contacts.pin_wormhole_dm_invite(
            agent_id,
            invite_payload={
                "trust_fingerprint": "aa" * 32,
                "public_key": record["public_key"],
                "public_key_algo": record["public_key_algo"],
                "identity_dh_pub_key": record["dh_pub_key"],
                "dh_algo": record["dh_algo"],
                "prekey_lookup_handle": "contact-bound-handle",
            },
        )

        from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle

        result = fetch_dm_prekey_bundle(agent_id=agent_id)
        assert result["ok"] is True
        assert result["agent_id"] == agent_id
        assert result["lookup_mode"] == "invite_lookup_handle"

    def test_fetch_fails_when_both_missing(self, tmp_path, monkeypatch):
        """Returns not-found when neither lookup_token nor agent_id resolves."""
        _isolated_relay(tmp_path, monkeypatch)

        from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle

        result = fetch_dm_prekey_bundle(agent_id="", lookup_token="nonexistent")
        assert result["ok"] is False

    def test_fetch_returns_transparency_and_witness_metadata(self, tmp_path, monkeypatch):
        """Bundle fetch surfaces transparency head/size and witness count."""
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        ok, _detail, meta = relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
            lookup_aliases=["metadata-handle"],
        )
        assert ok is True
        relay.record_witness("witness-a", agent_id, record["dh_pub_key"], int(time.time()))

        from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle

        result = fetch_dm_prekey_bundle(lookup_token="metadata-handle")
        assert result["ok"] is True
        assert result["prekey_transparency_head"] == meta["prekey_transparency_head"]
        assert result["prekey_transparency_size"] == 1
        assert result["prekey_transparency_fingerprint"]
        assert result["witness_count"] == 1
        assert result["witness_latest_at"] > 0
        assert result["lookup_mode"] == "invite_lookup_handle"

    def test_legacy_agent_id_fetch_logs_deprecation_once(self, tmp_path, monkeypatch, caplog):
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        ok, _detail, _meta = relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
        )
        assert ok is True

        from services.mesh import mesh_wormhole_prekey
        from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle

        monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "false")
        monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
        monkeypatch.setenv("MESH_ALLOW_LEGACY_AGENT_ID_LOOKUP_UNTIL", "2026-06-01")
        get_settings.cache_clear()
        mesh_wormhole_prekey._WARNED_LEGACY_PREKEY_LOOKUPS.clear()
        caplog.clear()
        caplog.set_level("WARNING")

        try:
            assert fetch_dm_prekey_bundle(agent_id=agent_id)["ok"] is True
            assert fetch_dm_prekey_bundle(agent_id=agent_id)["ok"] is True

            warnings = [
                record.message
                for record in caplog.records
                if "legacy prekey lookup used" in record.message
            ]
            assert len(warnings) == 1
            from services.mesh.mesh_metadata_exposure import stable_metadata_log_ref

            assert stable_metadata_log_ref(agent_id, prefix="peer") in warnings[0]
            assert agent_id not in warnings[0]
        finally:
            get_settings.cache_clear()

    def test_legacy_agent_id_lookup_can_be_blocked_with_telemetry(self, tmp_path, monkeypatch):
        relay = _isolated_relay(tmp_path, monkeypatch)
        record = _valid_bundle_record("test-agent")
        agent_id = record["agent_id"]

        ok, _detail, _meta = relay.register_prekey_bundle(
            agent_id,
            record["bundle"],
            "sig-placeholder",
            record["public_key"],
            record["public_key_algo"],
            record["protocol_version"],
            1,
        )
        assert ok is True

        from services.mesh import mesh_compatibility
        from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle

        monkeypatch.setattr(mesh_compatibility, "DATA_DIR", tmp_path)
        monkeypatch.setattr(
            mesh_compatibility,
            "COMPATIBILITY_FILE",
            tmp_path / "mesh_compatibility_usage.json",
        )
        monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "true")
        get_settings.cache_clear()

        try:
            result = fetch_dm_prekey_bundle(agent_id=agent_id)
            assert result["ok"] is False
            assert "legacy agent_id lookup disabled" in result["detail"]

            snapshot = mesh_compatibility.compatibility_status_snapshot()
            assert snapshot["sunset"]["legacy_agent_id_lookup"]["target_version"] == "0.10.0"
            assert snapshot["sunset"]["legacy_agent_id_lookup"]["target_date"] == "2026-06-01"
            assert snapshot["sunset"]["legacy_agent_id_lookup"]["status"] == "enforced"
            assert snapshot["sunset"]["legacy_agent_id_lookup"]["blocked"] is True
            assert snapshot["usage"]["legacy_agent_id_lookup"]["count"] == 1
            assert snapshot["usage"]["legacy_agent_id_lookup"]["blocked_count"] == 1
            assert (
                snapshot["usage"]["legacy_agent_id_lookup"]["recent_targets"][0]["lookup_kinds"]
                == ["prekey_bundle"]
            )
        finally:
            get_settings.cache_clear()
