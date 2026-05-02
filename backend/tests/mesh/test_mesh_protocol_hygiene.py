import asyncio


def test_x3dh_hkdf_uses_nonzero_ff_salt():
    from services.mesh.mesh_wormhole_prekey import _hkdf

    derived = _hkdf(b"input-material", "SB-TEST")
    assert derived
    assert derived != _hkdf(b"input-material", "SB-TEST-ALT")


def test_ratchet_padding_extends_large_payloads():
    from services.mesh.mesh_wormhole_ratchet import _build_padded_payload, PAD_MAGIC, PAD_STEP

    plaintext = "x" * 5000
    padded = _build_padded_payload(plaintext)

    assert padded[:4].decode("utf-8") == PAD_MAGIC
    assert len(padded) > len(plaintext.encode("utf-8"))
    assert len(padded) % PAD_STEP == 0


def test_dead_drop_epoch_shortens_in_high_privacy(monkeypatch):
    from services.mesh import mesh_wormhole_dead_drop

    monkeypatch.setattr(
        mesh_wormhole_dead_drop,
        "read_wormhole_settings",
        lambda: {"privacy_profile": "high"},
    )
    assert mesh_wormhole_dead_drop.mailbox_epoch_seconds() == 2 * 60 * 60


def test_relay_jitter_only_applies_in_high_privacy(monkeypatch):
    import main

    sleeps: list[float] = []

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    monkeypatch.setattr(main, "_high_privacy_profile_enabled", lambda: True)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)

    asyncio.run(main._maybe_apply_dm_relay_jitter())

    assert len(sleeps) == 1
    assert 0.05 <= sleeps[0] <= 0.5


def test_high_privacy_refuses_private_tier_clearnet_fallback(monkeypatch):
    from services.mesh.mesh_router import MeshEnvelope, MeshRouter, Priority, TransportResult

    router = MeshRouter()
    internet_attempts: list[str] = []

    monkeypatch.setattr(
        "services.mesh.mesh_router._supervisor_verified_trust_tier",
        lambda: "private_transitional",
    )
    monkeypatch.setattr(
        "services.mesh.mesh_router._high_privacy_profile_blocks_clearnet_fallback",
        lambda: True,
    )
    monkeypatch.setattr(router.tor_arti, "can_reach", lambda _envelope: False)
    monkeypatch.setattr(
        router.internet,
        "send",
        lambda *_args, **_kwargs: (
            internet_attempts.append("internet"),
            TransportResult(True, "internet", "sent"),
        )[1],
    )

    results = router.route(
        MeshEnvelope(
            sender_id="!sb_sender",
            destination="!sb_dest",
            payload="ciphertext",
            trust_tier="private_transitional",
            priority=Priority.NORMAL,
        ),
        {},
    )

    assert internet_attempts == []
    assert len(results) == 1
    assert results[0].transport == "policy"
    assert "Switch to private to send?" in results[0].detail
    assert results[0].upgrade_action["reason"] == "private_transport_not_ready"


def test_default_policy_refuses_private_tier_clearnet_fallback(monkeypatch):
    from services.config import get_settings
    from services.mesh.mesh_router import MeshEnvelope, MeshRouter, Priority, TransportResult

    router = MeshRouter()
    internet_attempts: list[str] = []

    monkeypatch.setattr(
        "services.mesh.mesh_router._supervisor_verified_trust_tier",
        lambda: "private_transitional",
    )
    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "block")
    get_settings.cache_clear()
    monkeypatch.setattr(router.tor_arti, "can_reach", lambda _envelope: False)
    monkeypatch.setattr(
        router.internet,
        "send",
        lambda *_args, **_kwargs: (
            internet_attempts.append("internet"),
            TransportResult(True, "internet", "sent"),
        )[1],
    )

    results = router.route(
        MeshEnvelope(
            sender_id="!sb_sender",
            destination="!sb_dest",
            payload="ciphertext",
            trust_tier="private_transitional",
            priority=Priority.NORMAL,
        ),
        {},
    )

    assert internet_attempts == []
    assert len(results) == 1
    assert results[0].transport == "policy"
    assert "Switch to private to send?" in results[0].detail
    assert results[0].upgrade_action["reason"] == "private_transport_not_ready"


def test_private_tier_clearnet_fallback_requires_explicit_operator_allow(monkeypatch):
    from services.config import get_settings
    from services.mesh.mesh_router import MeshEnvelope, MeshRouter, Priority, TransportResult

    router = MeshRouter()
    internet_attempts: list[str] = []

    monkeypatch.setattr(
        "services.mesh.mesh_router._supervisor_verified_trust_tier",
        lambda: "private_transitional",
    )
    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "allow")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "services.wormhole_settings.read_wormhole_settings",
        lambda: {"privacy_profile": "default"},
    )
    monkeypatch.setattr(router.tor_arti, "can_reach", lambda _envelope: False)
    monkeypatch.setattr(
        router.internet,
        "send",
        lambda *_args, **_kwargs: (
            internet_attempts.append("internet"),
            TransportResult(True, "internet", "sent"),
        )[1],
    )

    results = router.route(
        MeshEnvelope(
            sender_id="!sb_sender",
            destination="!sb_dest",
            payload="ciphertext",
            trust_tier="private_transitional",
            priority=Priority.NORMAL,
        ),
        {},
    )

    assert internet_attempts == []
    assert len(results) == 1
    assert results[0].transport == "policy"
    assert "Switch to private to send?" in results[0].detail
    assert results[0].upgrade_action["reason"] == "private_transport_not_ready"


def test_private_tier_clearnet_fallback_requires_explicit_acknowledge(monkeypatch):
    from services.config import get_settings
    from services.mesh.mesh_router import MeshEnvelope, MeshRouter, Priority, TransportResult

    router = MeshRouter()
    internet_attempts: list[str] = []

    monkeypatch.setattr(
        "services.mesh.mesh_router._supervisor_verified_trust_tier",
        lambda: "private_transitional",
    )
    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK", "allow")
    monkeypatch.setenv("MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "services.wormhole_settings.read_wormhole_settings",
        lambda: {"privacy_profile": "default"},
    )
    monkeypatch.setattr(router.tor_arti, "can_reach", lambda _envelope: False)
    monkeypatch.setattr(
        router.internet,
        "send",
        lambda *_args, **_kwargs: (
            internet_attempts.append("internet"),
            TransportResult(True, "internet", "sent"),
        )[1],
    )

    results = router.route(
        MeshEnvelope(
            sender_id="!sb_sender",
            destination="!sb_dest",
            payload="ciphertext",
            trust_tier="private_transitional",
            priority=Priority.NORMAL,
        ),
        {},
    )

    assert internet_attempts == ["internet"]
    assert results[-1].transport == "internet"
