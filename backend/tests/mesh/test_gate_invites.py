"""Cross-node gate key distribution over the DM lane."""

import base64
import copy
import json
import os

import pytest


@pytest.fixture()
def env(monkeypatch):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401

    from services.mesh import mesh_gate_invites, mesh_reputation, mesh_wormhole_contacts

    manager = mesh_reputation.gate_manager
    original_gates = copy.deepcopy(manager.gates)
    monkeypatch.setattr(manager, "_save", lambda: None)
    manager.gates["lab"] = {
        "display_name": "Lab",
        "gate_secret": "local-secret",
        "gate_secret_archive": {},
        "envelope_policy": "envelope_always",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
    }

    contacts: dict[str, dict] = {
        "!alice": {"trust_level": "sas_verified"},
        "!bob": {"trust_level": "tofu_pinned"},
        "!carol": {"trust_level": "invite_pinned"},
        "!mallory": {"trust_level": "mismatch"},
    }
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "get_wormhole_dm_contact",
        lambda peer: dict(contacts[peer]) if peer in contacts else None,
    )
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "get_contact_trust_level",
        lambda peer: contacts.get(peer, {}).get("trust_level", "unpinned"),
    )

    pending: dict = {}
    monkeypatch.setattr(mesh_gate_invites, "_read_pending", lambda: copy.deepcopy(pending))

    def _write(value):
        pending.clear()
        pending.update(copy.deepcopy(value))

    monkeypatch.setattr(mesh_gate_invites, "_write_pending", _write)
    monkeypatch.setattr(mesh_gate_invites, "_local_epoch", lambda _gate: 3)

    sent: list[tuple[str, str]] = []

    def _fake_send(peer, plaintext):
        sent.append((peer, plaintext))
        return {"ok": True}

    monkeypatch.setattr(mesh_gate_invites, "_send_dm_impl", _fake_send)
    yield {"mod": mesh_gate_invites, "manager": manager, "sent": sent, "pending": pending, "contacts": contacts}
    manager.gates = original_gates


def _frame(mod, *, op="invite", secret="shared-secret", gate="lab", version=1, exclude=None):
    return mod._build_frame(
        op=op, gate_id=gate, display_name="Lab", secret=secret, version=version, exclude=exclude
    )


def test_frame_roundtrip_and_tamper_rejection(env):
    mod = env["mod"]
    raw = _frame(mod)
    parsed = mod.parse_gate_key_frame(raw)
    assert parsed["secret"] == "shared-secret"
    assert parsed["secret_id"] == mod.secret_fingerprint("shared-secret")

    tampered = json.loads(raw)
    tampered["secret"] = "other"
    assert mod.parse_gate_key_frame(json.dumps(tampered)) is None
    assert mod.parse_gate_key_frame("hello there") is None
    assert mod.parse_gate_key_frame('{"kind":"something_else"}') is None


def test_invite_requires_existing_trusted_contact(env):
    mod = env["mod"]
    assert mod.send_gate_invite("lab", "!stranger")["ok"] is False
    assert mod.send_gate_invite("lab", "!mallory")["ok"] is False
    assert env["sent"] == []


def test_invite_refuses_envelope_disabled_gate(env):
    env["manager"].gates["lab"]["envelope_policy"] = "envelope_disabled"
    assert env["mod"].send_gate_invite("lab", "!alice")["ok"] is False


def test_invite_sends_current_secret_and_records_grant(env):
    mod, manager = env["mod"], env["manager"]
    result = mod.send_gate_invite("lab", "!alice", note="welcome")
    assert result["ok"] is True
    peer, plaintext = env["sent"][0]
    assert peer == "!alice"
    frame = mod.parse_gate_key_frame(plaintext)
    assert frame["op"] == "invite" and frame["secret"] == "local-secret"
    assert "!alice" in manager.get_gate_key_meta("lab")["key_grants"]
    # The status surface never exposes the secret itself.
    status = mod.gate_key_status("lab")
    assert "local-secret" not in json.dumps(status)
    assert status["grantees"] == ["!alice"]


def test_received_invite_is_hidden_pending_then_accepted(env):
    mod, manager = env["mod"], env["manager"]
    text, summary = mod.intercept_dm_plaintext("!alice", _frame(mod, version=4))
    assert "shared-secret" not in text
    assert summary["status"] == "pending"
    assert "shared-secret" not in json.dumps(mod.list_pending_gate_invites())
    # Not applied until the operator accepts.
    assert manager.get_gate_secret("lab") == "local-secret"

    accepted = mod.accept_gate_invite(summary["invite_id"])
    assert accepted["ok"] is True and accepted["changed"] is True
    assert manager.get_gate_secret("lab") == "shared-secret"
    meta = manager.get_gate_key_meta("lab")
    assert meta["key_upstream"] == "!alice"
    assert meta["gate_secret_version"] == 4
    archive = manager.get_gate_secret_archive("lab")
    assert archive["previous_secret"] == "local-secret"
    assert archive["previous_valid_through_epoch"] == 3
    assert mod.list_pending_gate_invites()["invites"] == []


def test_decline_discards_invite(env):
    mod, manager = env["mod"], env["manager"]
    _text, summary = mod.intercept_dm_plaintext("!alice", _frame(mod))
    assert mod.decline_gate_invite(summary["invite_id"])["ok"] is True
    assert manager.get_gate_secret("lab") == "local-secret"
    assert mod.accept_gate_invite(summary["invite_id"])["ok"] is False


def test_frames_from_untrusted_senders_are_rejected(env):
    mod, manager = env["mod"], env["manager"]
    for sender in ("!stranger", "!mallory"):
        _text, summary = mod.intercept_dm_plaintext(sender, _frame(mod))
        assert summary["status"] == "rejected_untrusted_sender"
    assert env["pending"] == {}
    assert manager.get_gate_secret("lab") == "local-secret"


def test_rekey_from_upstream_applies_and_forwards_with_exclusions(env):
    mod, manager = env["mod"], env["manager"]
    _text, summary = mod.intercept_dm_plaintext("!alice", _frame(mod))
    mod.accept_gate_invite(summary["invite_id"])
    manager.record_key_grant("lab", "!bob", secret_id="x", op="invite")
    manager.record_key_grant("lab", "!carol", secret_id="x", op="invite")
    env["sent"].clear()

    rekey = _frame(mod, op="rekey", secret="rotated-secret", version=2, exclude=["!carol"])
    _text, summary = mod.intercept_dm_plaintext("!alice", rekey)
    assert summary["status"] == "applied"
    assert manager.get_gate_secret("lab") == "rotated-secret"
    # Forwarded to bob only: not back to alice, not to excluded carol.
    assert [peer for peer, _ in env["sent"]] == ["!bob"]
    assert mod.parse_gate_key_frame(env["sent"][0][1])["secret"] == "rotated-secret"
    assert "!carol" not in manager.get_gate_key_meta("lab")["key_grants"]

    # Replaying the same rekey is a no-op and does not loop.
    env["sent"].clear()
    _text, summary = mod.intercept_dm_plaintext("!alice", rekey)
    assert summary["status"] == "already_current"
    assert env["sent"] == []


def test_rekey_from_non_upstream_waits_for_operator(env):
    mod, manager = env["mod"], env["manager"]
    _text, summary = mod.intercept_dm_plaintext("!bob", _frame(mod, op="rekey", secret="sneaky"))
    assert summary["status"] == "pending"
    assert manager.get_gate_secret("lab") == "local-secret"


def test_rotate_sends_new_secret_to_grantees_except_excluded(env):
    mod, manager = env["mod"], env["manager"]
    manager.record_key_grant("lab", "!alice", secret_id="x", op="invite")
    manager.record_key_grant("lab", "!bob", secret_id="x", op="invite")
    result = mod.rotate_gate_key("lab", exclude_peer_ids=["!bob"])
    assert result["ok"] is True
    assert result["delivered"] == ["!alice"]
    new_secret = manager.get_gate_secret("lab")
    assert new_secret != "local-secret"
    frame = mod.parse_gate_key_frame(env["sent"][0][1])
    assert frame["op"] == "rekey" and frame["secret"] == new_secret and frame["exclude"] == ["!bob"]
    assert set(manager.get_gate_key_meta("lab")["key_grants"]) == {"!alice"}
    assert manager.get_gate_secret_archive("lab")["previous_secret"] == "local-secret"


def test_adopted_secret_decrypts_envelopes_from_other_node(env, monkeypatch):
    """The point of the feature: a peer's envelope becomes readable here."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from services.mesh import mesh_gate_mls

    mod = env["mod"]
    message_nonce = "msg-nonce-1"
    key = mesh_gate_mls._gate_envelope_key_scoped("lab", "shared-secret", message_nonce=message_nonce)
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, b"hello from node A", f"gate_envelope|lab|{message_nonce}".encode())
    token = base64.b64encode(iv + ct).decode("ascii")

    assert mesh_gate_mls._gate_envelope_decrypt("lab", token, message_nonce=message_nonce) is None
    _text, summary = mod.intercept_dm_plaintext("!alice", _frame(mod))
    mod.accept_gate_invite(summary["invite_id"])
    assert mesh_gate_mls._gate_envelope_decrypt("lab", token, message_nonce=message_nonce) == "hello from node A"


def test_kick_rotation_redistributes_to_grantees(env, monkeypatch):
    from services.config import get_settings
    from services.mesh import mesh_gate_mls

    mod, manager = env["mod"], env["manager"]
    monkeypatch.setenv("MESH_GATE_BAN_KICK_ROTATION_ENABLE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        mesh_gate_mls,
        "remove_gate_member",
        lambda *_a, **_k: {"ok": True, "previous_epoch": 2, "epoch": 3, "previous_valid_through_event_id": ""},
    )
    manager.record_key_grant("lab", "!alice", secret_id="x", op="invite")
    result = manager.remove_member("lab", "persona-1", kind="kick")
    assert result["gate_secret_rotated"] is True
    assert [peer for peer, _ in env["sent"]] == ["!alice"]
    assert mod.parse_gate_key_frame(env["sent"][0][1])["secret"] == manager.get_gate_secret("lab")
    get_settings.cache_clear()


def test_dm_decrypt_strips_gate_key_frame_before_returning(env, monkeypatch):
    import main

    mod = env["mod"]
    frame = _frame(mod)
    monkeypatch.setattr(main, "_resolve_dm_aliases", lambda **_k: ("local", "remote"))
    monkeypatch.setattr(main, "has_mls_dm_session", lambda *_a: {"ok": True, "exists": True})
    monkeypatch.setattr(main, "decrypt_mls_dm", lambda *_a: {"ok": True, "plaintext": frame})
    monkeypatch.setattr(main, "mark_contact_alias_reply_observed", lambda *_a: None)

    result = main.decrypt_wormhole_dm_envelope(peer_id="!alice", ciphertext="ct", payload_format="mls1")
    assert result["ok"] is True
    assert "shared-secret" not in json.dumps(result)
    assert result["gate_key_event"]["status"] == "pending"
    assert result["plaintext"].startswith("[Gate key]")


def test_gate_release_floor_matches_dm_when_rns_is_off():
    from services.mesh.mesh_privacy_policy import evaluate_network_release, release_lane_required_tier

    tor_only = {"rns_enabled": False}
    with_rns = {"rns_enabled": True}
    assert release_lane_required_tier("gate", wormhole_state=tor_only) == "private_transitional"
    assert release_lane_required_tier("dm", wormhole_state=tor_only) == "private_transitional"
    # Enabling RNS keeps the stronger two-transport floor.
    assert release_lane_required_tier("gate", wormhole_state=with_rns) == "private_strong"
    # Other lanes are untouched.
    assert release_lane_required_tier("trust_graph", wormhole_state=tor_only) == "private_strong"
