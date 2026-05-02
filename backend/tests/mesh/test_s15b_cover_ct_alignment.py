"""S15B Cover Ciphertext Size Alignment (grounded family).

Tests:
- grounded family matches actual live DM output lengths for representative pad-bucket classes
- cover ciphertext length is in the grounded family, not arbitrary raw size
- default settings still send valid cover traffic under max payload
- configured cover size/cap selects from the grounded family
- cover does not exceed MESH_RNS_MAX_PAYLOAD on the wire
- existing route-shape behavior does not regress (private_dm type, envelope fields, stem + delayed diffuse)
- do not overclaim deep-inspection indistinguishability
"""

import base64
import math

from services.mesh.mesh_rns import (
    _DM_CT_FAMILY,
    _dm_cover_buckets,
)


# ── Grounding tests ──────────────────────────────────────────────────────

def _fresh_dm_mls_state(tmp_path, monkeypatch):
    """Establish a DM MLS session and return the dm_mls module."""
    from services import wormhole_supervisor
    from services.mesh import mesh_dm_mls, mesh_dm_relay, mesh_secure_storage, mesh_wormhole_persona

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(mesh_dm_mls, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_mls, "STATE_FILE", tmp_path / "wormhole_dm_mls.json")
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(
        mesh_dm_mls,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)
    mesh_dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=True)

    bob_bundle = mesh_dm_mls.export_dm_key_package_for_alias("bob")
    assert bob_bundle["ok"] is True
    initiated = mesh_dm_mls.initiate_dm_session("alice", "bob", bob_bundle)
    assert initiated["ok"] is True
    accepted = mesh_dm_mls.accept_dm_session("bob", "alice", initiated["welcome"])
    assert accepted["ok"] is True

    return mesh_dm_mls


def test_grounded_family_matches_live_dm(tmp_path, monkeypatch):
    """_DM_CT_FAMILY raw sizes must match actual dm_encrypt output for each pad-bucket class."""
    dm_mls = _fresh_dm_mls_state(tmp_path, monkeypatch)
    from services.mesh.mesh_dm_mls import PAD_BUCKET_STEP, PAD_HEADER_SIZE, _pad_plaintext

    for i, expected_raw in enumerate(_DM_CT_FAMILY):
        n = i + 1
        padded_size = PAD_BUCKET_STEP * n
        data_len = padded_size - PAD_HEADER_SIZE
        padded = _pad_plaintext(b"x" * data_len)
        assert len(padded) == padded_size

        binding = dm_mls._session_binding("alice", "bob")
        raw_ct = dm_mls._privacy_client().dm_encrypt(binding.session_handle, padded)
        assert len(raw_ct) == expected_raw, (
            f"pad-bucket {n}: dm_encrypt produced {len(raw_ct)} bytes, "
            f"expected {expected_raw} — _DM_CT_FAMILY is stale"
        )


def test_grounded_family_b64_lengths_match_live_dm(tmp_path, monkeypatch):
    """Base64-encoded lengths of grounded family must match live DM ciphertext b64 lengths."""
    dm_mls = _fresh_dm_mls_state(tmp_path, monkeypatch)
    from services.mesh.mesh_dm_mls import PAD_BUCKET_STEP, PAD_HEADER_SIZE, _pad_plaintext

    for i, expected_raw in enumerate(_DM_CT_FAMILY):
        n = i + 1
        padded_size = PAD_BUCKET_STEP * n
        padded = _pad_plaintext(b"x" * (padded_size - PAD_HEADER_SIZE))

        binding = dm_mls._session_binding("alice", "bob")
        raw_ct = dm_mls._privacy_client().dm_encrypt(binding.session_handle, padded)
        live_b64_len = len(base64.b64encode(raw_ct))
        cover_b64_len = len(base64.b64encode(b"\x00" * expected_raw))
        assert live_b64_len == cover_b64_len, (
            f"pad-bucket {n}: live DM b64 len {live_b64_len} != "
            f"cover b64 len {cover_b64_len}"
        )


# ── Bucket filter tests ──────────────────────────────────────────────────


def test_bucket_filter_respects_max():
    """Buckets must not exceed the given max."""
    buckets = _dm_cover_buckets(2000)
    assert all(b <= 2000 for b in buckets)
    assert 734 in buckets   # pad-bucket 1
    assert 1374 in buckets  # pad-bucket 2
    assert 1886 in buckets  # pad-bucket 3
    assert 2654 not in buckets  # pad-bucket 4 exceeds 2000


def test_bucket_filter_empty_when_max_too_small():
    """If max is below smallest family entry, return empty list."""
    buckets = _dm_cover_buckets(100)
    assert buckets == []


def test_bucket_filter_returns_all_when_large():
    """With a large max, all family entries are returned."""
    buckets = _dm_cover_buckets(99999)
    assert buckets == list(_DM_CT_FAMILY)


def test_bucket_filter_preserves_order():
    """Returned buckets must be in ascending order."""
    buckets = _dm_cover_buckets(99999)
    assert buckets == sorted(buckets)


def test_bucket_b64_lengths_form_discrete_family():
    """Base64 lengths of grounded buckets must form a discrete set, not a continuum."""
    b64_lengths = [math.ceil(b / 3) * 4 for b in _DM_CT_FAMILY]
    # Adjacent b64 lengths must have non-trivial gaps (not just +4)
    steps = [b64_lengths[i + 1] - b64_lengths[i] for i in range(len(b64_lengths) - 1)]
    assert all(s >= 100 for s in steps), f"b64 length steps too small — not discrete: {steps}"


# ── Cover traffic integration ──────────────────────────────────────────


def test_cover_ciphertext_in_grounded_family(monkeypatch):
    """Cover envelope.ciphertext b64 length must be in the grounded DM family."""
    from unittest.mock import MagicMock
    from services.mesh import mesh_rns

    allowed_b64_lengths = {
        len(base64.b64encode(b"\x00" * size)) for size in _DM_CT_FAMILY
    }

    class _Settings:
        MESH_RNS_COVER_SIZE = 8192
        MESH_RNS_MAX_PAYLOAD = 16384
        MESH_RNS_DANDELION_DELAY_MS = 400

    monkeypatch.setattr(mesh_rns, "get_settings", lambda: _Settings())

    bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
    bridge._peers = {}
    bridge._peer_failures = {}
    bridge._peer_cooldowns = {}
    bridge._message_log = []
    bridge._message_log_max = 256
    bridge._lock = __import__("threading").Lock()
    bridge._pick_stem_peer = MagicMock(return_value=None)
    bridge._send_diffuse = MagicMock()
    bridge._dandelion_hops = MagicMock(return_value=2)
    bridge._make_message_id = MagicMock(return_value="test-id")

    for _ in range(20):
        bridge._send_cover_traffic()

    assert bridge._send_diffuse.call_count == 20
    for call in bridge._send_diffuse.call_args_list:
        msg_bytes = call[0][0]
        msg = __import__("json").loads(msg_bytes)
        ct_str = msg["body"]["envelope"]["ciphertext"]
        assert len(ct_str) in allowed_b64_lengths, (
            f"ciphertext b64 length {len(ct_str)} not in grounded family {sorted(allowed_b64_lengths)}"
        )


def test_cover_not_arbitrary_512_raw(monkeypatch):
    """Cover ciphertext must NOT be base64(512 raw bytes) = 684 chars."""
    from unittest.mock import MagicMock
    from services.mesh import mesh_rns

    class _Settings:
        MESH_RNS_COVER_SIZE = 512
        MESH_RNS_MAX_PAYLOAD = 8192
        MESH_RNS_DANDELION_DELAY_MS = 400

    monkeypatch.setattr(mesh_rns, "get_settings", lambda: _Settings())

    bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
    bridge._peers = {}
    bridge._peer_failures = {}
    bridge._peer_cooldowns = {}
    bridge._message_log = []
    bridge._message_log_max = 256
    bridge._lock = __import__("threading").Lock()
    bridge._pick_stem_peer = MagicMock(return_value=None)
    bridge._send_diffuse = MagicMock()
    bridge._dandelion_hops = MagicMock(return_value=2)
    bridge._make_message_id = MagicMock(return_value="test-id")

    bridge._send_cover_traffic()
    msg = __import__("json").loads(bridge._send_diffuse.call_args[0][0])
    ct_len = len(msg["body"]["envelope"]["ciphertext"])
    # base64(512 raw bytes) = 684 chars — old unaligned behavior
    assert ct_len != 684, "cover ciphertext length is still 684 (unaligned 512 raw bytes)"


def test_cover_under_max_payload(monkeypatch):
    """Full cover message must not exceed MESH_RNS_MAX_PAYLOAD."""
    from unittest.mock import MagicMock
    from services.mesh import mesh_rns

    class _Settings:
        MESH_RNS_COVER_SIZE = 4096
        MESH_RNS_MAX_PAYLOAD = 8192
        MESH_RNS_DANDELION_DELAY_MS = 400

    monkeypatch.setattr(mesh_rns, "get_settings", lambda: _Settings())

    bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
    bridge._peers = {}
    bridge._peer_failures = {}
    bridge._peer_cooldowns = {}
    bridge._message_log = []
    bridge._message_log_max = 256
    bridge._lock = __import__("threading").Lock()
    bridge._pick_stem_peer = MagicMock(return_value=None)
    bridge._send_diffuse = MagicMock()
    bridge._dandelion_hops = MagicMock(return_value=2)
    bridge._make_message_id = MagicMock(return_value="test-id")

    for _ in range(10):
        bridge._send_cover_traffic()

    for call in bridge._send_diffuse.call_args_list:
        msg_bytes = call[0][0]
        assert len(msg_bytes) <= 8192, f"cover message {len(msg_bytes)} exceeds max payload"


def test_configured_cap_selects_from_grounded_family(monkeypatch):
    """MESH_RNS_COVER_SIZE acts as a cap — selected size must be a grounded family entry."""
    from unittest.mock import MagicMock
    from services.mesh import mesh_rns

    for cap in (256, 800, 1500, 3000, 8192):

        class _Settings:
            MESH_RNS_COVER_SIZE = cap
            MESH_RNS_MAX_PAYLOAD = 16384
            MESH_RNS_DANDELION_DELAY_MS = 400

        monkeypatch.setattr(mesh_rns, "get_settings", lambda: _Settings())

        bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
        bridge._peers = {}
        bridge._peer_failures = {}
        bridge._peer_cooldowns = {}
        bridge._message_log = []
        bridge._message_log_max = 256
        bridge._lock = __import__("threading").Lock()
        bridge._pick_stem_peer = MagicMock(return_value=None)
        bridge._send_diffuse = MagicMock()
        bridge._dandelion_hops = MagicMock(return_value=2)
        bridge._make_message_id = MagicMock(return_value="test-id")

        bridge._send_cover_traffic()
        msg = __import__("json").loads(bridge._send_diffuse.call_args[0][0])
        ct_b64 = msg["body"]["envelope"]["ciphertext"]
        ct_raw_len = len(base64.b64decode(ct_b64))
        assert ct_raw_len in _DM_CT_FAMILY, (
            f"cap={cap}: raw ciphertext {ct_raw_len} is not a grounded family entry"
        )


# ── Route-shape preservation ───────────────────────────────────────────


def test_cover_is_private_dm_type(monkeypatch):
    """Cover messages must still use msg_type private_dm."""
    from unittest.mock import MagicMock
    from services.mesh import mesh_rns

    class _Settings:
        MESH_RNS_COVER_SIZE = 512
        MESH_RNS_MAX_PAYLOAD = 8192
        MESH_RNS_DANDELION_DELAY_MS = 400

    monkeypatch.setattr(mesh_rns, "get_settings", lambda: _Settings())

    bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
    bridge._peers = {}
    bridge._peer_failures = {}
    bridge._peer_cooldowns = {}
    bridge._message_log = []
    bridge._message_log_max = 256
    bridge._lock = __import__("threading").Lock()
    bridge._pick_stem_peer = MagicMock(return_value=None)
    bridge._send_diffuse = MagicMock()
    bridge._dandelion_hops = MagicMock(return_value=2)
    bridge._make_message_id = MagicMock(return_value="test-id")

    bridge._send_cover_traffic()
    msg = __import__("json").loads(bridge._send_diffuse.call_args[0][0])
    assert msg["type"] == "private_dm"


def test_cover_envelope_has_required_fields(monkeypatch):
    """Cover envelope must have same fields as real DM envelope."""
    from unittest.mock import MagicMock
    from services.mesh import mesh_rns

    class _Settings:
        MESH_RNS_COVER_SIZE = 512
        MESH_RNS_MAX_PAYLOAD = 8192
        MESH_RNS_DANDELION_DELAY_MS = 400

    monkeypatch.setattr(mesh_rns, "get_settings", lambda: _Settings())

    bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
    bridge._peers = {}
    bridge._peer_failures = {}
    bridge._peer_cooldowns = {}
    bridge._message_log = []
    bridge._message_log_max = 256
    bridge._lock = __import__("threading").Lock()
    bridge._pick_stem_peer = MagicMock(return_value=None)
    bridge._send_diffuse = MagicMock()
    bridge._dandelion_hops = MagicMock(return_value=2)
    bridge._make_message_id = MagicMock(return_value="test-id")

    bridge._send_cover_traffic()
    msg = __import__("json").loads(bridge._send_diffuse.call_args[0][0])
    envelope = msg["body"]["envelope"]
    required = {"msg_id", "sender_id", "ciphertext", "timestamp", "delivery_class", "sender_seal"}
    assert required.issubset(set(envelope.keys()))


def test_cover_uses_stem_phase(monkeypatch):
    """Cover dandelion metadata must start in stem phase."""
    from unittest.mock import MagicMock
    from services.mesh import mesh_rns

    class _Settings:
        MESH_RNS_COVER_SIZE = 512
        MESH_RNS_MAX_PAYLOAD = 8192
        MESH_RNS_DANDELION_DELAY_MS = 400

    monkeypatch.setattr(mesh_rns, "get_settings", lambda: _Settings())

    bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
    bridge._peers = {}
    bridge._peer_failures = {}
    bridge._peer_cooldowns = {}
    bridge._message_log = []
    bridge._message_log_max = 256
    bridge._lock = __import__("threading").Lock()
    bridge._pick_stem_peer = MagicMock(return_value=None)
    bridge._send_diffuse = MagicMock()
    bridge._dandelion_hops = MagicMock(return_value=2)
    bridge._make_message_id = MagicMock(return_value="test-id")

    bridge._send_cover_traffic()
    msg = __import__("json").loads(bridge._send_diffuse.call_args[0][0])
    dandelion = msg.get("meta", {}).get("dandelion", {})
    assert dandelion.get("phase") == "stem"


def test_cover_stem_then_delayed_diffuse(monkeypatch):
    """When a stem peer is available, cover must send to peer then schedule diffuse."""
    import threading
    from unittest.mock import MagicMock, patch
    from services.mesh import mesh_rns

    class _Settings:
        MESH_RNS_COVER_SIZE = 512
        MESH_RNS_MAX_PAYLOAD = 8192
        MESH_RNS_DANDELION_DELAY_MS = 400

    monkeypatch.setattr(mesh_rns, "get_settings", lambda: _Settings())

    bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
    bridge._peers = {}
    bridge._peer_failures = {}
    bridge._peer_cooldowns = {}
    bridge._message_log = []
    bridge._message_log_max = 256
    bridge._lock = __import__("threading").Lock()
    bridge._pick_stem_peer = MagicMock(return_value="peer-1")
    bridge._send_to_peer = MagicMock(return_value=True)
    bridge._send_diffuse = MagicMock()
    bridge._dandelion_hops = MagicMock(return_value=2)
    bridge._make_message_id = MagicMock(return_value="test-id")

    timers = []
    original_timer = threading.Timer

    def _capture_timer(delay, fn):
        t = original_timer(delay, fn)
        timers.append((delay, fn))
        return t

    with patch.object(threading, "Timer", side_effect=_capture_timer):
        bridge._send_cover_traffic()

    bridge._send_to_peer.assert_called_once()
    assert bridge._send_to_peer.call_args[0][0] == "peer-1"
    assert len(timers) == 1
    assert timers[0][0] == 0.4  # MESH_RNS_DANDELION_DELAY_MS / 1000


# ── No overclaim ───────────────────────────────────────────────────────


def test_no_overclaim_cover_is_not_real_mls():
    """Cover ciphertext is random bytes, not real MLS output.
    Size alignment does not make it indistinguishable under deep inspection."""
    import os
    size = _DM_CT_FAMILY[0]  # smallest grounded bucket
    cover_ct = os.urandom(size)
    # Cover is just random bytes — no SBP1 magic, no MLS framing
    assert cover_ct[:4] != b"SBP1"  # not padded plaintext structure
    # base64 length matches the DM family
    b64_len = len(base64.b64encode(cover_ct).decode("ascii"))
    expected = math.ceil(size / 3) * 4
    assert b64_len == expected
