"""DM lane tier alignment for MLS helpers.

Tor-style hardening update: local MLS operations (session setup,
encryption, decryption) never surface a consent-required detail on a
weaker transport tier. The tier gate applies only to *network release*,
which the outbound release path queues silently until the floor is met.

Tests:
- DM MLS helpers proceed at every tier without a consent-required detail
- Gate MLS transport policy remains unaffected (it has no per-call gate)
"""

# Sentinel: the legacy consent-prompt detail. Must never surface from
# local MLS helpers under the Tor-style contract, even when the transport
# tier is public_degraded.
CONSENT_DETAIL = "needs_private_transport_consent"


def _patch_transport_tier(monkeypatch, *, configured: bool, ready: bool, arti_ready: bool, rns_ready: bool):
    from services.mesh import mesh_dm_mls

    monkeypatch.setattr(
        mesh_dm_mls,
        "get_wormhole_state",
        lambda: {
            "configured": configured,
            "ready": ready,
            "arti_ready": arti_ready,
            "rns_ready": rns_ready,
        },
    )
    # Neutralize the auto-upgrade attempt so tests do not spawn real
    # wormhole subprocesses or touch disk.
    monkeypatch.setattr(
        mesh_dm_mls,
        "connect_wormhole",
        lambda *, reason="": {"ready": ready, "configured": configured},
    )
    # Reset the auto-upgrade cooldown so back-to-back tests each get a
    # fresh attempt window.
    monkeypatch.setattr(mesh_dm_mls, "_last_auto_upgrade_attempt", 0.0, raising=False)


def _assert_no_consent_prompt(result: dict) -> None:
    # The local MLS helper may succeed or fail for structural reasons
    # (malformed key package, missing session, etc.), but it MUST NOT
    # surface the legacy consent-required detail — that was the hostile
    # surface Tor-style hardening removed.
    assert CONSENT_DETAIL not in str(result.get("detail", "") or "")


def _assert_transport_passed(result: dict, required: str) -> None:
    if not result["ok"]:
        assert required not in str(result.get("detail", "") or "")


def test_encrypt_dm_proceeds_without_consent_prompt_on_public_degraded(monkeypatch):
    from services.mesh import mesh_dm_mls

    _patch_transport_tier(monkeypatch, configured=False, ready=False, arti_ready=False, rns_ready=False)
    _assert_no_consent_prompt(mesh_dm_mls.encrypt_dm("alice", "bob", "hello"))


def test_decrypt_dm_proceeds_without_consent_prompt_on_public_degraded(monkeypatch):
    from services.mesh import mesh_dm_mls

    _patch_transport_tier(monkeypatch, configured=False, ready=False, arti_ready=False, rns_ready=False)
    _assert_no_consent_prompt(mesh_dm_mls.decrypt_dm("alice", "bob", "Y3Q=", "bm9uY2U="))


def test_initiate_dm_session_proceeds_without_consent_prompt_on_public_degraded(monkeypatch):
    from services.mesh import mesh_dm_mls

    _patch_transport_tier(monkeypatch, configured=False, ready=False, arti_ready=False, rns_ready=False)
    _assert_no_consent_prompt(
        mesh_dm_mls.initiate_dm_session("alice", "bob", {"mls_key_package": "a2V5"}),
    )


def test_accept_dm_session_proceeds_without_consent_prompt_on_public_degraded(monkeypatch):
    from services.mesh import mesh_dm_mls

    _patch_transport_tier(monkeypatch, configured=False, ready=False, arti_ready=False, rns_ready=False)
    _assert_no_consent_prompt(
        mesh_dm_mls.accept_dm_session("alice", "bob", "d2VsY29tZQ=="),
    )


def test_has_dm_session_proceeds_without_consent_prompt_on_public_degraded(monkeypatch):
    from services.mesh import mesh_dm_mls

    _patch_transport_tier(monkeypatch, configured=False, ready=False, arti_ready=False, rns_ready=False)
    _assert_no_consent_prompt(mesh_dm_mls.has_dm_session("alice", "bob"))


def test_encrypt_dm_passes_transport_gate_at_private_control_only(monkeypatch):
    from services.mesh import mesh_dm_mls

    _patch_transport_tier(monkeypatch, configured=True, ready=True, arti_ready=False, rns_ready=False)
    _assert_transport_passed(mesh_dm_mls.encrypt_dm("alice", "bob", "hello"), CONSENT_DETAIL)


def test_decrypt_dm_passes_transport_gate_at_private_control_only(monkeypatch):
    from services.mesh import mesh_dm_mls

    _patch_transport_tier(monkeypatch, configured=True, ready=True, arti_ready=False, rns_ready=False)
    _assert_transport_passed(mesh_dm_mls.decrypt_dm("alice", "bob", "Y3Q=", "bm9uY2U="), CONSENT_DETAIL)


def test_encrypt_dm_passes_transport_gate_at_private_strong(monkeypatch):
    from services.mesh import mesh_dm_mls

    _patch_transport_tier(monkeypatch, configured=True, ready=True, arti_ready=True, rns_ready=True)
    _assert_transport_passed(mesh_dm_mls.encrypt_dm("alice", "bob", "hello"), CONSENT_DETAIL)


def test_decrypt_dm_passes_transport_gate_at_private_strong(monkeypatch):
    from services.mesh import mesh_dm_mls

    _patch_transport_tier(monkeypatch, configured=True, ready=True, arti_ready=True, rns_ready=True)
    _assert_transport_passed(mesh_dm_mls.decrypt_dm("alice", "bob", "Y3Q=", "bm9uY2U="), CONSENT_DETAIL)


def test_gate_mls_transport_check_unchanged():
    import inspect
    from services.mesh import mesh_gate_mls

    source = inspect.getsource(mesh_gate_mls)
    assert "_require_private_transport" not in source
