"""Phase 3.2 — TOFU (Trust On First Use) hardening.

Pins the refusal behavior of ``verified_first_contact_requirement`` for
peers in compromised trust states. The DM compose path in ``main.py``
already calls this function and bails out with ``ok: False`` when it
returns a non-ok result, so these tests are the regression gate that
prevents a refactor from silently re-enabling DM traffic to a peer
whose remote prekey fingerprint has changed.

Trust-failure refusals are NOT subject to the non-hostile transport
policy: a fingerprint mismatch is a real cryptographic warning that
something is wrong with the peer (key rotation without invite proof,
MITM, or compromised contact store), and the operator must reverify
out-of-band before any further DM traffic. Refusing here is correct.
"""

from __future__ import annotations


def _fresh_contacts(tmp_path, monkeypatch):
    from services.mesh import mesh_secure_storage, mesh_wormhole_contacts

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key"
    )
    monkeypatch.setattr(
        mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_contacts.json"
    )
    return mesh_wormhole_contacts


# ---------------------------------------------------------------------------
# Trust state matrix — every level the requirement function knows about.
# ---------------------------------------------------------------------------


def test_phase3_tofu_refuses_mismatch_trust_level(tmp_path, monkeypatch):
    """A peer with ``trust_level=mismatch`` (changed fingerprint vs. a
    non-verified prior pin) must be refused with a clear detail."""

    contacts = _fresh_contacts(tmp_path, monkeypatch)

    result = contacts.verified_first_contact_requirement(
        peer_id="",  # force the trust-level branch
        trust_level="mismatch",
    )
    assert result == {
        "ok": False,
        "trust_level": "mismatch",
        "detail": "remote prekey identity changed; verification required",
    }


def test_phase3_tofu_refuses_continuity_broken_trust_level(tmp_path, monkeypatch):
    """A peer with ``trust_level=continuity_broken`` (changed fingerprint
    AFTER an invite_pinned or sas_verified pin) must also be refused.
    This is the strongest pre-Phase-3 alarm and must never silently
    fall through to ``tofu_pinned``."""

    contacts = _fresh_contacts(tmp_path, monkeypatch)

    result = contacts.verified_first_contact_requirement(
        peer_id="",
        trust_level="continuity_broken",
    )
    assert result == {
        "ok": False,
        "trust_level": "continuity_broken",
        "detail": "remote prekey identity changed; verification required",
    }


def test_phase3_tofu_refuses_unpinned_trust_level(tmp_path, monkeypatch):
    """A peer with no pin yet (``unpinned``) must be refused unless an
    invite or SAS verification has happened. ``tofu_pinned`` alone is not
    enough — the gate requires ``invite_pinned`` or ``sas_verified``."""

    contacts = _fresh_contacts(tmp_path, monkeypatch)

    result = contacts.verified_first_contact_requirement(
        peer_id="",
        trust_level="unpinned",
    )
    assert result["ok"] is False
    assert result["trust_level"] == "unpinned"
    assert "signed invite or SAS verification required" in result["detail"]


def test_phase3_tofu_refuses_bare_tofu_pinned_without_verification(tmp_path, monkeypatch):
    """``tofu_pinned`` is the *baseline* pin (first-seen). It is NOT a
    verified-first-contact state. The gate must refuse it until the
    operator escalates to ``invite_pinned`` or ``sas_verified``."""

    contacts = _fresh_contacts(tmp_path, monkeypatch)

    result = contacts.verified_first_contact_requirement(
        peer_id="",
        trust_level="tofu_pinned",
    )
    assert result["ok"] is False
    assert result["trust_level"] == "tofu_pinned"


def test_phase3_tofu_allows_invite_pinned(tmp_path, monkeypatch):
    """``invite_pinned`` (operator imported a signed invite) IS a
    verified-first-contact state and must pass the gate."""

    contacts = _fresh_contacts(tmp_path, monkeypatch)

    result = contacts.verified_first_contact_requirement(
        peer_id="",
        trust_level="invite_pinned",
    )
    assert result == {"ok": True, "trust_level": "invite_pinned"}


def test_phase3_tofu_allows_sas_verified(tmp_path, monkeypatch):
    """``sas_verified`` (operator confirmed Short Authentication String
    out-of-band) is the strongest verification level and must pass."""

    contacts = _fresh_contacts(tmp_path, monkeypatch)

    result = contacts.verified_first_contact_requirement(
        peer_id="",
        trust_level="sas_verified",
    )
    assert result == {"ok": True, "trust_level": "sas_verified"}


# ---------------------------------------------------------------------------
# Per-peer lookup branch — when peer_id is supplied the function reads
# the contact store and inspects ``trustSummary`` directly.
# ---------------------------------------------------------------------------


def test_phase3_tofu_per_peer_refuses_continuity_broken_record(tmp_path, monkeypatch):
    """When the peer is found in the contact store and its trust summary
    state is ``continuity_broken``, refusal must take the explicit
    cryptographic-warning branch (not the generic 'unpinned' branch)."""

    contacts = _fresh_contacts(tmp_path, monkeypatch)

    # Seed a contact whose trustSummary state is continuity_broken.
    seeded = {
        "alice-peer": {
            "alias": "alice",
            "trust_level": "continuity_broken",
            "trustSummary": {
                "state": "continuity_broken",
                "verifiedFirstContact": False,
                "rootWitnessed": False,
                "rootManifestGeneration": 0,
                "rootRotationProven": False,
            },
        }
    }
    contacts._write_contacts(seeded)

    result = contacts.verified_first_contact_requirement("alice-peer")
    assert result["ok"] is False
    assert result["trust_level"] == "continuity_broken"
    assert result["detail"] == "remote prekey identity changed; verification required"


def test_phase3_tofu_per_peer_allows_verified_first_contact_flag(tmp_path, monkeypatch):
    """When ``trustSummary.verifiedFirstContact`` is true, the gate must
    pass — this is the canonical happy-path for an operator-verified peer."""

    contacts = _fresh_contacts(tmp_path, monkeypatch)

    seeded = {
        "bob-peer": {
            "alias": "bob",
            "trust_level": "sas_verified",
            "trustSummary": {
                "state": "sas_verified",
                "verifiedFirstContact": True,
                "rootWitnessed": False,
                "rootManifestGeneration": 0,
                "rootRotationProven": False,
            },
        }
    }
    contacts._write_contacts(seeded)

    result = contacts.verified_first_contact_requirement("bob-peer")
    assert result["ok"] is True
    assert result["trust_level"] == "sas_verified"
