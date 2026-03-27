import asyncio
import base64
import json
import logging
import time
from collections import deque

from cryptography.hazmat.primitives.asymmetric import ed25519
from starlette.requests import Request

import main
from services.mesh.mesh_crypto import build_signature_payload, derive_node_id
from services.mesh.mesh_hashchain import GateMessageStore
from services.mesh import mesh_reputation


def _json_request(path: str, body: dict) -> Request:
    payload = json.dumps(body).encode("utf-8")
    sent = {"value": False}

    async def receive():
        if sent["value"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["value"] = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": path,
        },
        receive,
    )


def _request(path: str, method: str = "GET") -> Request:
    sent = {"value": False}

    async def receive():
        if sent["value"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["value"] = True
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "headers": [],
            "client": ("test", 12345),
            "method": method,
            "path": path,
        },
        receive,
    )


def _signed_gate_event(
    gate_id: str = "finance",
    *,
    private_key: ed25519.Ed25519PrivateKey | None = None,
    sequence: int = 7,
    ciphertext: str = "opaque-ciphertext",
    nonce: str = "nonce-1",
    sender_ref: str = "sender-ref-1",
) -> dict:
    private_key = private_key or ed25519.Ed25519PrivateKey.generate()
    public_key = base64.b64encode(private_key.public_key().public_bytes_raw()).decode("ascii")
    node_id = derive_node_id(public_key)
    payload = {
        "gate": gate_id,
        "ciphertext": ciphertext,
        "nonce": nonce,
        "sender_ref": sender_ref,
        "format": "mls1",
    }
    signature = private_key.sign(
        build_signature_payload(
            event_type="gate_message",
            node_id=node_id,
            sequence=sequence,
            payload=payload,
        ).encode("utf-8")
    ).hex()
    return {
        "event_type": "gate_message",
        "timestamp": float(int(time.time() / 60) * 60),
        "node_id": node_id,
        "sequence": sequence,
        "signature": signature,
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
        "payload": payload,
    }


def _vote_event() -> dict:
    return {
        "event_id": "vote-1",
        "event_type": "vote",
        "node_id": "!node-1",
        "payload": {"gate": "finance", "vote": 1},
        "timestamp": 100.0,
        "sequence": 3,
        "signature": "sig",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
    }


def _key_rotate_event() -> dict:
    return {
        "event_id": "rotate-1",
        "event_type": "key_rotate",
        "node_id": "!node-2",
        "payload": {
            "old_node_id": "!old-node",
            "old_public_key": "old-pub",
            "old_public_key_algo": "Ed25519",
            "old_signature": "old-sig",
            "timestamp": 123,
        },
        "timestamp": 101.0,
        "sequence": 4,
        "signature": "sig",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
    }


def _public_gate_message_event() -> dict:
    return {
        "event_id": "gate-1",
        "event_type": "gate_message",
        "node_id": "!node-3",
        "payload": {
            "gate": "finance",
            "ciphertext": "opaque",
            "epoch": 2,
            "nonce": "nonce-1",
            "sender_ref": "sender-ref-1",
            "format": "mls1",
        },
        "timestamp": 102.0,
        "sequence": 5,
        "signature": "sig",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
    }


def test_private_gate_timestamp_is_stably_jittered_backward(monkeypatch):
    class _Settings:
        MESH_GATE_TIMESTAMP_JITTER_S = 60

    monkeypatch.setattr(main, "get_settings", lambda: _Settings())
    event = {
        "event_id": "gate-event-stable-jitter",
        "event_type": "gate_message",
        "timestamp": 120.0,
        "payload": {
            "gate": "finance",
            "ciphertext": "opaque",
            "format": "mls1",
        },
    }

    first = main._strip_gate_identity(event)
    second = main._strip_gate_identity(dict(event))

    assert first["timestamp"] == second["timestamp"]
    assert 60.0 <= float(first["timestamp"]) < 120.0
    assert first["public_key"] == ""
    assert first["node_id"] == ""


def test_gate_identity_redaction_keeps_gate_member_visible_fields():
    event = {
        "event_id": "gate-event-visible-fields",
        "event_type": "gate_message",
        "timestamp": 120.0,
        "node_id": "!sb_gate_member",
        "sequence": 7,
        "signature": "sig",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
        "payload": {
            "gate": "finance",
            "ciphertext": "opaque",
            "format": "mls1",
            "nonce": "nonce-1",
            "sender_ref": "sender-ref-1",
        },
    }

    stripped = main._strip_gate_identity(event)

    assert stripped["node_id"] == "!sb_gate_member"
    assert stripped["public_key"] == "pub"
    assert stripped["public_key_algo"] == "Ed25519"
    assert stripped["sequence"] == 7
    assert stripped["signature"] == "sig"
    assert stripped["protocol_version"] == "infonet/2"
    assert stripped["payload"]["nonce"] == "nonce-1"
    assert stripped["payload"]["sender_ref"] == "sender-ref-1"


class _FakePublicInfonet:
    def __init__(self):
        self.head_hash = "head-1"
        self.events = [_vote_event(), _key_rotate_event(), _public_gate_message_event()]

    @staticmethod
    def _limit_value(limit: int) -> int:
        try:
            return int(limit)
        except Exception:
            return int(getattr(limit, "default", 100) or 100)

    def decorate_event(self, evt: dict) -> dict:
        return dict(evt)

    def decorate_events(self, events: list[dict]) -> list[dict]:
        return [dict(evt) for evt in events]

    def get_event(self, event_id: str):
        for evt in self.events:
            if evt["event_id"] == event_id:
                return dict(evt)
        return None

    def get_messages(self, gate_id: str = "", limit: int = 50, offset: int = 0):
        resolved_limit = self._limit_value(limit)
        return [dict(evt) for evt in self.events[offset : offset + resolved_limit]]

    def get_events_by_node(self, node_id: str, limit: int = 50):
        return [dict(evt) for evt in self.events if evt["node_id"] == node_id][:limit]

    def get_events_by_type(self, event_type: str, limit: int = 50, offset: int = 0):
        resolved_limit = self._limit_value(limit)
        filtered = [dict(evt) for evt in self.events if evt["event_type"] == event_type]
        return filtered[offset : offset + resolved_limit]

    def get_events_after(self, after_hash: str, limit: int = 100):
        resolved_limit = self._limit_value(limit)
        return [dict(evt) for evt in self.events[:resolved_limit]]

    def get_events_after_locator(self, locator: list[str], limit: int = 100):
        resolved_limit = self._limit_value(limit)
        return self.head_hash, 0, [dict(evt) for evt in self.events[:resolved_limit]]

    def get_merkle_proofs(self, start_index: int, count: int):
        return {"root": "merkle-root", "total": len(self.events), "start": start_index, "proofs": []}

    def get_merkle_root(self):
        return "merkle-root"


def test_gate_store_rejects_unverified_peer_events(tmp_path):
    store = GateMessageStore(data_dir=str(tmp_path / "gate_messages"))

    result = store.ingest_peer_events(
        "finance",
        [
            {
                "event_type": "gate_message",
                "timestamp": time.time(),
                "payload": {
                    "gate": "finance",
                    "ciphertext": "opaque-ciphertext",
                    "format": "mls1",
                    "nonce": "nonce-1",
                    "sender_ref": "sender-ref-1",
                },
            }
        ],
    )

    assert result == {"accepted": 0, "duplicates": 0, "rejected": 1}
    assert store.get_messages("finance", limit=10) == []


def test_gate_store_forwarded_peer_ingest_allows_out_of_order_signed_sequences_today(tmp_path, monkeypatch):
    class _GateManager:
        def can_enter(self, sender_id, gate_id):
            assert sender_id
            assert gate_id == "finance"
            return True, "Access granted"

    monkeypatch.setattr(mesh_reputation, "gate_manager", _GateManager(), raising=False)
    store = GateMessageStore(data_dir=str(tmp_path / "gate_messages"))
    author_key = ed25519.Ed25519PrivateKey.generate()

    first = _signed_gate_event(
        "finance",
        private_key=author_key,
        sequence=7,
        ciphertext="opaque-ciphertext-7",
        nonce="nonce-7",
        sender_ref="sender-ref-7",
    )
    second = _signed_gate_event(
        "finance",
        private_key=author_key,
        sequence=3,
        ciphertext="opaque-ciphertext-3",
        nonce="nonce-3",
        sender_ref="sender-ref-3",
    )

    result = store.ingest_peer_events("finance", [first, second])

    assert result == {"accepted": 2, "duplicates": 0, "rejected": 0}
    stored = store.get_messages("finance", limit=10)
    assert {msg["payload"]["ciphertext"] for msg in stored} == {"opaque-ciphertext-7", "opaque-ciphertext-3"}


def test_gate_store_accepts_verified_peer_events_and_persists_sanitized_shape(tmp_path, monkeypatch):
    class _GateManager:
        def can_enter(self, sender_id, gate_id):
            assert sender_id
            assert gate_id == "finance"
            return True, "Access granted"

    monkeypatch.setattr(mesh_reputation, "gate_manager", _GateManager(), raising=False)
    store = GateMessageStore(data_dir=str(tmp_path / "gate_messages"))

    result = store.ingest_peer_events("finance", [_signed_gate_event("finance")])

    assert result == {"accepted": 1, "duplicates": 0, "rejected": 0}
    stored = store.get_messages("finance", limit=1)[0]
    assert stored["payload"] == {
        "gate": "finance",
        "ciphertext": "opaque-ciphertext",
        "nonce": "nonce-1",
        "sender_ref": "sender-ref-1",
        "format": "mls1",
    }
    assert "node_id" not in stored
    assert "signature" not in stored
    assert "sequence" not in stored


def test_gate_store_rejects_verified_peer_events_from_unauthorized_authors(tmp_path, monkeypatch):
    class _GateManager:
        def can_enter(self, sender_id, gate_id):
            assert sender_id
            assert gate_id == "finance"
            return False, "Need 10 overall rep"

    monkeypatch.setattr(mesh_reputation, "gate_manager", _GateManager(), raising=False)
    store = GateMessageStore(data_dir=str(tmp_path / "gate_messages"))

    result = store.ingest_peer_events("finance", [_signed_gate_event("finance")])

    assert result == {"accepted": 0, "duplicates": 0, "rejected": 1}
    assert store.get_messages("finance", limit=10) == []


def test_mesh_log_hides_private_entries_from_public_callers(monkeypatch):
    from services.mesh.mesh_router import mesh_router

    monkeypatch.setattr(
        mesh_router,
        "message_log",
        deque(
            [
                {
                    "sender": "alice",
                    "destination": "broadcast",
                    "routed_via": "internet",
                    "priority": "normal",
                    "route_reason": "public",
                    "timestamp": 123.0,
                    "trust_tier": "public_degraded",
                },
                {
                    "message_id": "m-private",
                    "routed_via": "tor_arti",
                    "priority": "normal",
                    "route_reason": "private",
                    "timestamp": 456.0,
                    "trust_tier": "private_strong",
                },
            ],
            maxlen=8,
        ),
    )
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))

    response = asyncio.run(main.mesh_log(_request("/api/mesh/log")))

    assert response == {
        "log": [
            {
                "sender": "alice",
                "destination": "broadcast",
                "routed_via": "internet",
                "priority": "normal",
                "route_reason": "public",
                "timestamp": 123.0,
            }
        ]
    }


def test_mesh_status_public_hides_private_activity_volume(monkeypatch):
    from services.mesh.mesh_router import mesh_router
    from services import sigint_bridge

    monkeypatch.setattr(
        mesh_router,
        "message_log",
        deque(
            [
                {
                    "sender": "alice",
                    "destination": "broadcast",
                    "routed_via": "internet",
                    "priority": "normal",
                    "route_reason": "public",
                    "timestamp": 123.0,
                    "trust_tier": "public_degraded",
                },
                {
                    "message_id": "m-private",
                    "routed_via": "tor_arti",
                    "priority": "normal",
                    "route_reason": "private",
                    "timestamp": 456.0,
                    "trust_tier": "private_strong",
                },
            ],
            maxlen=8,
        ),
    )
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(
        sigint_bridge,
        "sigint_grid",
        type("FakeSigintGrid", (), {"get_all_signals": staticmethod(lambda: [])})(),
    )

    response = asyncio.run(main.mesh_status(_request("/api/mesh/status")))

    assert response == {"message_log_size": 1}


def test_mesh_status_admin_gets_full_log_size_and_warning_details(monkeypatch):
    from services.mesh.mesh_router import mesh_router
    from services import sigint_bridge
    now = time.time()

    monkeypatch.setattr(
        mesh_router,
        "message_log",
        deque(
            [
                {"timestamp": now, "trust_tier": "public_degraded"},
                {"timestamp": now, "trust_tier": "private_transitional"},
            ],
            maxlen=8,
        ),
    )
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        sigint_bridge,
        "sigint_grid",
        type("FakeSigintGrid", (), {"get_all_signals": staticmethod(lambda: [])})(),
    )

    response = asyncio.run(main.mesh_status(_request("/api/mesh/status")))

    assert response["message_log_size"] == 2
    assert response["public_message_log_size"] == 1
    assert "private_log_retention_seconds" in response
    assert isinstance(response["security_warnings"], list)


def test_public_oracle_profile_hides_behavioral_lists(monkeypatch):
    from services.mesh import mesh_oracle

    fake_profile = {
        "node_id": "!oracle",
        "oracle_rep": 2.5,
        "oracle_rep_total": 3.0,
        "oracle_rep_locked": 0.5,
        "predictions_won": 4,
        "predictions_lost": 1,
        "win_rate": 80,
        "farming_pct": 25,
        "active_stakes": [{"message_id": "msg-1", "side": "truth", "amount": 0.5, "expires": 123}],
        "prediction_history": [{"market": "Test", "side": "yes", "rep_earned": 0.7}],
    }
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(
        mesh_oracle,
        "oracle_ledger",
        type("FakeOracleLedger", (), {"get_oracle_profile": staticmethod(lambda *_args, **_kwargs: dict(fake_profile))})(),
        raising=False,
    )

    response = asyncio.run(main.oracle_profile(_request("/api/mesh/oracle/profile"), node_id="!oracle"))

    assert response["node_id"] == "!oracle"
    assert response["oracle_rep"] == 2.5
    assert response["active_stakes"] == []
    assert response["prediction_history"] == []


def test_public_oracle_predictions_hide_active_positions(monkeypatch):
    from services.mesh import mesh_oracle

    active_predictions = [
        {"prediction_id": "pred-1", "market_title": "Alpha", "side": "yes", "mode": "free"},
        {"prediction_id": "pred-2", "market_title": "Bravo", "side": "no", "mode": "staked"},
    ]
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(
        mesh_oracle,
        "oracle_ledger",
        type(
            "FakeOracleLedger",
            (),
            {"get_active_predictions": staticmethod(lambda *_args, **_kwargs: list(active_predictions))},
        )(),
        raising=False,
    )

    response = asyncio.run(
        main.oracle_predictions(_request("/api/mesh/oracle/predictions"), node_id="!oracle")
    )

    assert response == {"predictions": [], "count": 2}


def test_public_oracle_stakes_hide_staker_lists(monkeypatch):
    from services.mesh import mesh_oracle

    fake_stakes = {
        "message_id": "msg-1",
        "truth_total": 1.5,
        "false_total": 0.75,
        "truth_stakers": [{"node_id": "!truth", "amount": 1.5, "expires": 123}],
        "false_stakers": [{"node_id": "!false", "amount": 0.75, "expires": 456}],
        "earliest_expiry": 123,
    }
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(
        mesh_oracle,
        "oracle_ledger",
        type(
            "FakeOracleLedger",
            (),
            {"get_stakes_for_message": staticmethod(lambda *_args, **_kwargs: dict(fake_stakes))},
        )(),
        raising=False,
    )

    response = asyncio.run(
        main.oracle_stakes_for_message(_request("/api/mesh/oracle/stakes/msg-1"), message_id="msg-1")
    )

    assert response == {
        "message_id": "msg-1",
        "truth_total": 1.5,
        "false_total": 0.75,
        "truth_stakers": [],
        "false_stakers": [],
        "earliest_expiry": 123,
    }


def test_public_wormhole_settings_redact_sensitive_fields(monkeypatch):
    monkeypatch.setattr(
        main,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "transport": "tor",
            "anonymous_mode": True,
            "socks_proxy": "127.0.0.1:9050",
            "socks_dns": True,
            "privacy_profile": "high",
        },
    )
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)

    response = asyncio.run(main.api_get_wormhole_settings(_request("/api/settings/wormhole")))

    assert response == {
        "enabled": True,
        "transport": "tor",
        "anonymous_mode": True,
    }


def test_admin_wormhole_settings_keep_sensitive_fields(monkeypatch):
    monkeypatch.setattr(
        main,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "transport": "tor",
            "anonymous_mode": True,
            "socks_proxy": "127.0.0.1:9050",
            "socks_dns": True,
            "privacy_profile": "high",
        },
    )
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))

    response = asyncio.run(main.api_get_wormhole_settings(_request("/api/settings/wormhole")))

    assert response["enabled"] is True
    assert response["socks_proxy"] == "127.0.0.1:9050"
    assert response["socks_dns"] is True
    assert response["privacy_profile"] == "high"


def test_public_privacy_profile_hides_transport_metadata(monkeypatch):
    monkeypatch.setattr(
        main,
        "read_wormhole_settings",
        lambda: {
            "enabled": True,
            "privacy_profile": "high",
            "transport": "tor",
            "anonymous_mode": True,
        },
    )
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)

    response = asyncio.run(main.api_get_privacy_profile(_request("/api/settings/privacy-profile")))

    assert response == {
        "profile": "high",
        "wormhole_enabled": True,
    }


def test_public_settings_wormhole_status_uses_redacted_shape(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "last_error": "sensitive",
            "proxy_active": "tor",
            "arti_ready": True,
        },
    )
    monkeypatch.setattr(main, "_current_private_lane_tier", lambda *_args, **_kwargs: "private_strong")
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)

    response = asyncio.run(main.api_get_wormhole_status(_request("/api/settings/wormhole-status")))

    assert response == {
        "installed": True,
        "configured": True,
        "running": True,
        "ready": True,
    }


def test_public_infonet_status_hides_private_lane_policy(monkeypatch):
    monkeypatch.setattr(
        main,
        "_check_scoped_auth",
        lambda *_args, **_kwargs: (False, "no"),
    )
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)

    response = asyncio.run(main.infonet_status(_request("/api/mesh/infonet/status")))

    assert "private_lane_tier" not in response
    assert "private_lane_policy" not in response
    assert "network_id" in response


def test_public_rns_status_hides_private_lane_policy(monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import mesh_rns

    monkeypatch.setattr(
        main,
        "_check_scoped_auth",
        lambda *_args, **_kwargs: (False, "no"),
    )
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        main,
        "_current_private_lane_tier",
        lambda *_args, **_kwargs: "private_strong",
    )

    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(
        mesh_rns,
        "rns_bridge",
        type(
            "FakeRnsBridge",
            (),
            {
                "status": staticmethod(
                    lambda: {
                        "enabled": True,
                        "ready": True,
                        "configured_peers": 3,
                        "active_peers": 2,
                        "local_hash": "abc123",
                        "session_identities": 4,
                        "destination_age_s": 90,
                        "private_dm_direct_ready": True,
                    }
                )
            },
        )(),
    )

    response = asyncio.run(main.mesh_rns_status(_request("/api/mesh/rns/status")))

    assert response == {
        "enabled": True,
        "ready": True,
        "configured_peers": 3,
        "active_peers": 2,
    }


def test_public_dm_witness_hides_graph_details(monkeypatch):
    from services.mesh import mesh_dm_relay

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        mesh_dm_relay,
        "dm_relay",
        type(
            "FakeRelay",
            (),
            {"get_witnesses": staticmethod(lambda *_args, **_kwargs: [{"witness_id": "!alpha"}])},
        )(),
        raising=False,
    )

    response = asyncio.run(
        main.dm_key_witness_get(
            _request("/api/mesh/dm/witness"),
            target_id="!target",
            dh_pub_key="dh-pub",
        )
    )

    assert response == {"ok": True, "count": 1}


def test_audit_dm_witness_keeps_graph_details(monkeypatch):
    from services.mesh import mesh_dm_relay

    witnesses = [{"witness_id": "!alpha"}, {"witness_id": "!bravo"}]
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        mesh_dm_relay,
        "dm_relay",
        type(
            "FakeRelay",
            (),
            {"get_witnesses": staticmethod(lambda *_args, **_kwargs: witnesses)},
        )(),
        raising=False,
    )

    response = asyncio.run(
        main.dm_key_witness_get(
            _request("/api/mesh/dm/witness"),
            target_id="!target",
            dh_pub_key="dh-pub",
        )
    )

    assert response == {
        "ok": True,
        "target_id": "!target",
        "dh_pub_key": "dh-pub",
        "count": 2,
        "witnesses": witnesses,
    }


def test_public_gate_compose_redacts_signer_fields(monkeypatch):
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        main,
        "compose_encrypted_gate_message",
        lambda **_kwargs: {
            "ok": True,
            "gate_id": "finance",
            "identity_scope": "gate_persona",
            "sender_id": "!gate-sender",
            "public_key": "public-key",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
            "sequence": 42,
            "signature": "deadbeef",
            "ciphertext": "ciphertext",
            "nonce": "nonce",
            "sender_ref": "sender-ref",
            "format": "mls1",
            "timestamp": 123.0,
            "epoch": 3,
        },
    )

    response = asyncio.run(
        main.api_wormhole_gate_message_compose(
            _request("/api/wormhole/gate/message/compose", method="POST"),
            main.WormholeGateComposeRequest(gate_id="finance", plaintext="hello"),
        )
    )

    assert response == {
        "ok": True,
        "gate_id": "finance",
        "identity_scope": "gate_persona",
        "ciphertext": "ciphertext",
        "nonce": "nonce",
        "sender_ref": "sender-ref",
        "format": "mls1",
        "timestamp": 123.0,
        "epoch": 3,
    }


def test_dm_relay_auto_msg_id_omits_sender_suffix(tmp_path, monkeypatch):
    from services.mesh import mesh_dm_relay

    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json", raising=False)
    relay = mesh_dm_relay.DMRelay()

    result = relay.deposit(
        sender_id="!alice-1234",
        recipient_id="!bob",
        ciphertext="ciphertext",
        delivery_class="request",
    )

    assert result["ok"] is True
    assert str(result["msg_id"]).startswith("dm_")
    assert "1234" not in str(result["msg_id"])


def test_public_event_endpoints_preserve_redactions(client, monkeypatch):
    from services.mesh import mesh_hashchain

    fake_infonet = _FakePublicInfonet()
    monkeypatch.setattr(mesh_hashchain, "infonet", fake_infonet, raising=False)
    monkeypatch.setattr(
        mesh_hashchain,
        "gate_store",
        type("FakeGateStore", (), {"get_event": staticmethod(lambda *_args, **_kwargs: None)})(),
        raising=False,
    )

    collection_responses = [
        client.get("/api/mesh/infonet/messages").json()["messages"],
        client.get("/api/mesh/infonet/events").json()["events"],
        client.get("/api/mesh/infonet/sync").json()["events"],
        asyncio.run(
            main.infonet_sync_post(
                _json_request("/api/mesh/infonet/sync", {"locator": ["head-1"]})
            )
        )["events"],
    ]
    node_response = client.get("/api/mesh/infonet/node/!node-1").json()["events"]
    single_event = client.get("/api/mesh/infonet/event/rotate-1").json()

    for events in collection_responses:
        assert all(evt.get("event_type") != "gate_message" for evt in events)
        vote = next(evt for evt in events if evt.get("event_type") == "vote")
        rotate = next(evt for evt in events if evt.get("event_type") == "key_rotate")
        assert "gate" not in vote.get("payload", {})
        assert "old_node_id" not in rotate.get("payload", {})
        assert "old_public_key" not in rotate.get("payload", {})
        assert "old_signature" not in rotate.get("payload", {})

    assert len(node_response) == 1
    assert node_response[0]["event_type"] == "vote"
    assert set(node_response[0].keys()) == {"event_id", "event_type", "timestamp"}

    assert single_event["event_type"] == "key_rotate"
    assert "old_node_id" not in single_event.get("payload", {})


def test_mesh_router_private_log_entries_age_out(monkeypatch):
    from services import config as config_mod
    from services.mesh.mesh_router import MeshRouter

    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: type("Settings", (), {"MESH_PRIVATE_LOG_TTL_S": 60})(),
    )

    router = MeshRouter()
    router.message_log = deque(
        [
            {"timestamp": 100.0, "trust_tier": "private_strong"},
            {"timestamp": 100.0, "trust_tier": "public_degraded"},
            {"timestamp": 180.0, "trust_tier": "private_transitional"},
        ],
        maxlen=8,
    )

    router.prune_message_log(now=200.0)

    assert list(router.message_log) == [
        {"timestamp": 100.0, "trust_tier": "public_degraded"},
        {"timestamp": 180.0, "trust_tier": "private_transitional"},
    ]


def test_mesh_router_private_log_entries_strip_metadata(caplog):
    from services.mesh.mesh_router import MeshEnvelope, MeshRouter, Priority, TransportResult

    router = MeshRouter()
    envelope = MeshEnvelope(
        sender_id="alice",
        destination="bob",
        channel="shadow",
        priority=Priority.NORMAL,
        trust_tier="private_strong",
        payload="secret payload",
    )
    envelope.routed_via = "tor_arti"
    envelope.route_reason = "PRIVATE_STRONG — Tor required"

    with caplog.at_level(logging.INFO, logger="services.mesh_router"):
        router._log(envelope, [TransportResult(True, "tor_arti", "Delivered to 1 peer via Tor")])

    entry = list(router.message_log)[0]
    assert entry["trust_tier"] == "private_strong"
    assert entry["routed_via"] == "tor_arti"
    assert entry["transport_outcomes"] == [{"transport": "tor_arti", "ok": True}]
    assert "message_id" not in entry
    assert "channel" not in entry
    assert "payload_type" not in entry
    assert "payload_bytes" not in entry
    assert "results" not in entry
    assert envelope.message_id not in caplog.text


def test_mesh_metrics_requires_audit_scope(client, monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "Forbidden — invalid or missing admin key"))

    response = client.get("/api/mesh/metrics")

    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden — invalid or missing admin key"


def test_mesh_metrics_allows_audit_scope(client, monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))

    response = client.get("/api/mesh/metrics")

    assert response.status_code == 200
    assert "counters" in response.json()


def test_dm_send_rejects_unsealed_shared_private_dm(monkeypatch):
    from services import wormhole_supervisor

    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_strong")

    response = asyncio.run(
        main.dm_send(
            _json_request(
                "/api/mesh/dm/send",
                {
                    "sender_id": "alice",
                    "recipient_id": "bob",
                    "delivery_class": "shared",
                    "recipient_token": "shared-mailbox-token",
                    "ciphertext": "ciphertext",
                    "msg_id": "dm-shared-1",
                    "timestamp": int(time.time()),
                    "public_key": "cHVi",
                    "public_key_algo": "Ed25519",
                    "signature": "sig",
                    "sequence": 1,
                    "protocol_version": "infonet/2",
                },
            )
        )
    )

    assert response == {"ok": False, "detail": "sealed sender required for shared private DMs"}


def test_dm_key_package_error_detail_is_sanitized(monkeypatch):
    from services.mesh import mesh_dm_mls

    def _raise(*_args, **_kwargs):
        raise RuntimeError("sensitive backend detail")

    monkeypatch.setattr(mesh_dm_mls, "_identity_handle_for_alias", _raise)

    response = mesh_dm_mls.export_dm_key_package_for_alias("alpha")

    assert response == {"ok": False, "detail": "dm_mls_key_package_failed"}


def test_gate_compose_error_detail_is_sanitized(monkeypatch):
    from services.mesh import mesh_gate_mls
    from services import wormhole_supervisor

    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(mesh_gate_mls, "_active_gate_persona", lambda *_args, **_kwargs: {"persona_id": "p1"})
    monkeypatch.setattr(mesh_gate_mls, "_sync_binding", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("sensitive gate detail")))

    response = mesh_gate_mls.compose_encrypted_gate_message("finance", "hello")

    assert response == {"ok": False, "detail": "gate_mls_compose_failed"}


def test_dm_alias_blob_sign_error_detail_is_sanitized(monkeypatch):
    from services.mesh import mesh_wormhole_persona

    monkeypatch.setattr(mesh_wormhole_persona, "bootstrap_wormhole_persona_state", lambda: None)
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "read_wormhole_persona_state",
        lambda: {
            "dm_identity": {
                "private_key": "not-base64",
                "public_key": "pub",
                "public_key_algo": "Ed25519",
            }
        },
    )

    response = mesh_wormhole_persona.sign_dm_alias_blob("alpha", b"payload")

    assert response == {"ok": False, "detail": "dm_alias_blob_sign_failed"}


def test_public_mesh_reputation_is_summary_only(client, monkeypatch):
    from services.mesh import mesh_reputation as mesh_reputation_mod

    class _FakeLedger:
        def __init__(self):
            self.calls = []

        def get_reputation_log(self, node_id, detailed=False):
            self.calls.append((node_id, detailed))
            payload = {
                "node_id": node_id,
                "overall": 7,
                "upvotes": 3,
                "downvotes": 1,
            }
            if detailed:
                payload.update(
                    {
                        "gates": {"finance": 5},
                        "recent_votes": [{"voter": "blind-voter"}],
                        "node_age_days": 14.0,
                        "is_agent": True,
                    }
                )
            return payload

    fake_ledger = _FakeLedger()
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)

    response = client.get("/api/mesh/reputation?node_id=!alpha")

    assert response.status_code == 200
    assert response.json() == {
        "node_id": "!alpha",
        "overall": 7,
        "upvotes": 3,
        "downvotes": 1,
    }
    assert fake_ledger.calls == [("!alpha", False)]


def test_audit_mesh_reputation_keeps_detailed_breakdown(client, monkeypatch):
    from services.mesh import mesh_reputation as mesh_reputation_mod

    class _FakeLedger:
        def __init__(self):
            self.calls = []

        def get_reputation_log(self, node_id, detailed=False):
            self.calls.append((node_id, detailed))
            payload = {
                "node_id": node_id,
                "overall": 9,
                "upvotes": 4,
                "downvotes": 1,
            }
            if detailed:
                payload.update(
                    {
                        "gates": {"finance": 6},
                        "recent_votes": [{"voter": "blind-voter"}],
                        "node_age_days": 21.0,
                        "is_agent": False,
                    }
                )
            return payload

    fake_ledger = _FakeLedger()
    monkeypatch.setattr(mesh_reputation_mod, "reputation_ledger", fake_ledger, raising=False)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))

    response = client.get("/api/mesh/reputation?node_id=!bravo")

    assert response.status_code == 200
    assert response.json()["gates"] == {"finance": 6}
    assert response.json()["recent_votes"] == [{"voter": "blind-voter"}]
    assert response.json()["node_age_days"] == 21.0
    assert response.json()["is_agent"] is False
    assert fake_ledger.calls == [("!bravo", True)]


def test_dm_mls_logs_only_hashed_aliases_on_failure(caplog, monkeypatch):
    from services.mesh import mesh_dm_mls

    def _raise(*_args, **_kwargs):
        raise RuntimeError("sensitive backend detail")

    monkeypatch.setattr(mesh_dm_mls, "_identity_handle_for_alias", _raise)

    with caplog.at_level(logging.ERROR, logger="services.mesh.mesh_dm_mls"):
        response = mesh_dm_mls.export_dm_key_package_for_alias("alpha-alias")

    assert response == {"ok": False, "detail": "dm_mls_key_package_failed"}
    assert "alpha-alias" not in caplog.text
    assert "alias#" in caplog.text


def test_gate_mls_logs_only_hashed_gate_ids_on_failure(caplog, monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import mesh_gate_mls

    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(mesh_gate_mls, "_active_gate_persona", lambda *_args, **_kwargs: {"persona_id": "p1"})
    monkeypatch.setattr(
        mesh_gate_mls,
        "_sync_binding",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("gate failure")),
    )

    with caplog.at_level(logging.ERROR, logger="services.mesh.mesh_gate_mls"):
        response = mesh_gate_mls.compose_encrypted_gate_message("finance-ops", "hello")

    assert response == {"ok": False, "detail": "gate_mls_compose_failed"}
    assert "finance-ops" not in caplog.text
    assert "gate#" in caplog.text


def test_gate_persona_sign_logs_hashed_ids_on_failure(caplog, monkeypatch):
    from services.mesh import mesh_wormhole_persona

    monkeypatch.setattr(mesh_wormhole_persona, "bootstrap_wormhole_persona_state", lambda: None)
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "read_wormhole_persona_state",
        lambda: {
            "gate_personas": {
                "finance": [
                    {
                        "persona_id": "persona-raw",
                        "private_key": "not-base64",
                    }
                ]
            }
        },
    )

    with caplog.at_level(logging.ERROR, logger="services.mesh.mesh_wormhole_persona"):
        response = mesh_wormhole_persona.sign_gate_persona_blob("finance", "persona-raw", b"payload")

    assert response == {"ok": False, "detail": "persona_blob_sign_failed"}
    assert "persona-raw" not in caplog.text
    assert "gate#" in caplog.text
    assert "persona#" in caplog.text


def test_reputation_logs_hash_node_and_gate_identifiers(tmp_path, monkeypatch, caplog):
    from services.mesh import mesh_reputation

    monkeypatch.setattr(mesh_reputation, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_reputation, "LEDGER_FILE", tmp_path / "reputation_ledger.json")
    monkeypatch.setattr(mesh_reputation, "GATES_FILE", tmp_path / "gates.json")

    ledger = mesh_reputation.ReputationLedger()

    with caplog.at_level(logging.INFO, logger="services.mesh_reputation"):
        ledger.register_node("!alpha", "pub-a", "Ed25519")
        ledger.register_node("!bravo", "pub-b", "Ed25519")
        ok, _detail = ledger.cast_vote("!alpha", "!bravo", 1, "finance")

    assert ok is True
    assert "!alpha" not in caplog.text
    assert "!bravo" not in caplog.text
    assert "finance" not in caplog.text
    assert "node#" in caplog.text
    assert "gate#" in caplog.text
