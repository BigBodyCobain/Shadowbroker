"""Sprint 2C: Critical Mesh/Runtime Exception Visibility — regression tests.

Covers:
1. mesh_secure_storage._raw_fallback_allowed: settings-load failure is logged
   at DEBUG and does not propagate (safe-fail returns False).
2. mesh_rns._ibf_sync_loop: loop body exception is logged at WARNING and does
   not cause the loop to exit silently.
3. mesh_rns._ingest_ordered (IBF delta path): ingest failure is logged at WARNING.
4. mesh_rns._cover_loop: exception is logged at DEBUG before sleep(5).
5. mesh_rns fork-resolution fallback: exception is logged at WARNING before
   falling back to _ingest_ordered.
6. mesh_rns infonet_event handler: ingest_events failure is logged at WARNING.
7. mesh_rns gate_event handler: gate_store failure is logged at DEBUG.
8. mesh_dm_mls release_identity cleanup: failure is logged at DEBUG.
9. mesh_dm_mls release_dm_session (duplicate-session path): failure is logged at DEBUG.
10. mesh_dm_mls initiate finally — release_key_package: failure logged at DEBUG.
11. mesh_dm_mls initiate finally — release_dm_session: failure logged at DEBUG.
12. mesh_dm_mls accept finally — release_dm_session: failure logged at DEBUG.
13. Sensitive values (key handles, payloads) are not emitted in log messages.
"""

import logging
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_records(caplog, logger_name: str, level: int = logging.DEBUG) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith(logger_name) and r.levelno >= level]


def _log_messages(caplog, logger_name: str, level: int = logging.DEBUG) -> list[str]:
    return [r.getMessage() for r in _log_records(caplog, logger_name, level)]


def _make_rns_bridge():
    """Instantiate an RNSBridge with the minimum attributes needed by _on_packet."""
    from services.mesh import mesh_rns
    bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
    bridge._enabled = True
    bridge._ready = True
    bridge._peer_lock = threading.Lock()
    bridge._peer_stats = {}
    bridge._sync_rounds = {}
    bridge._dedupe_lock = threading.Lock()
    bridge._dedupe = {}
    bridge._sync_lock = threading.Lock()
    bridge._pending_sync = {}
    bridge._message_cache = {}
    bridge._message_cache_lock = threading.Lock()
    return bridge


# ---------------------------------------------------------------------------
# 1. mesh_secure_storage._raw_fallback_allowed — settings failure is logged
# ---------------------------------------------------------------------------

class TestSecureStorageRawFallback:
    """_raw_fallback_allowed must log at DEBUG and return False when settings fail.

    get_settings is imported locally inside the function, so the patch target
    is services.config.get_settings (not the mesh_secure_storage module attribute).
    The PYTEST_CURRENT_TEST env var causes early-return in test runs, so we
    bypass that by also patching _is_docker_container to False.
    """

    def test_settings_failure_logs_debug(self, caplog):
        """If get_settings() raises, _raw_fallback_allowed must log at DEBUG
        and return False (safe-fail) without re-raising."""
        import services.mesh.mesh_secure_storage as mss

        with patch.object(mss, "_is_windows", return_value=False), \
             patch.object(mss, "_is_docker_container", return_value=False), \
             patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}, clear=False), \
             patch("services.config.get_settings",
                   side_effect=RuntimeError("config unavailable")), \
             caplog.at_level(logging.DEBUG, logger="services.mesh.mesh_secure_storage"):
            result = mss._raw_fallback_allowed()

        assert result is False, "_raw_fallback_allowed must return False on settings failure"
        msgs = _log_messages(caplog, "services.mesh.mesh_secure_storage", logging.DEBUG)
        assert any("RuntimeError" in m for m in msgs), (
            "Settings-load failure must be logged at DEBUG with exception type"
        )

    def test_settings_failure_does_not_leak_exception_text(self, caplog):
        """The debug log must not include raw exception messages that could
        contain path or config secrets."""
        import services.mesh.mesh_secure_storage as mss

        secret_path = "/very/secret/config/path"
        with patch.object(mss, "_is_windows", return_value=False), \
             patch.object(mss, "_is_docker_container", return_value=False), \
             patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}, clear=False), \
             patch("services.config.get_settings",
                   side_effect=RuntimeError(secret_path)), \
             caplog.at_level(logging.DEBUG, logger="services.mesh.mesh_secure_storage"):
            mss._raw_fallback_allowed()

        msgs = _log_messages(caplog, "services.mesh.mesh_secure_storage", logging.DEBUG)
        for msg in msgs:
            assert secret_path not in msg, (
                "Raw exception message must not appear in logs — use type(exc).__name__ only"
            )


# ---------------------------------------------------------------------------
# 2. mesh_rns._ibf_sync_loop — exception is logged, loop continues
# ---------------------------------------------------------------------------

class TestRNSIbfSyncLoop:

    def test_ibf_loop_body_exception_is_logged(self, caplog):
        """An exception inside _ibf_sync_loop must be logged at WARNING."""
        from services.mesh import mesh_rns

        bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
        bridge._enabled = True
        bridge._ready = True
        bridge._last_ibf_sync = 0.0
        bridge._ibf_cooldown_until = 0.0
        bridge._ibf_fail_count = 0
        bridge._sync_rounds = {}
        bridge._peer_lock = threading.Lock()
        bridge._peer_stats = {}
        bridge._privacy_cache = {}

        call_count = [0]

        def boom():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("forced ibf sync failure")
            raise SystemExit  # terminate loop after second call

        with patch.object(bridge, "enabled", return_value=True), \
             patch.object(bridge, "_maybe_rotate_session", side_effect=boom), \
             patch.object(bridge, "_ibf_in_cooldown", return_value=False), \
             patch("time.sleep"), \
             caplog.at_level(logging.WARNING, logger="services.mesh_rns"):
            try:
                bridge._ibf_sync_loop()
            except SystemExit:
                pass

        msgs = _log_messages(caplog, "services.mesh_rns", logging.WARNING)
        assert any("IBF sync loop error" in m for m in msgs), (
            "_ibf_sync_loop exception must be logged at WARNING"
        )


# ---------------------------------------------------------------------------
# 3. mesh_rns._ingest_ordered (IBF delta path) — failure is logged
# ---------------------------------------------------------------------------

class TestRNSIbfIngestOrdered:

    def test_ibf_ingest_ordered_failure_is_logged(self, caplog):
        """infonet.ingest_events raising inside _ingest_ordered must be logged at WARNING."""
        from services.mesh import mesh_rns

        bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
        bridge._enabled = True
        bridge._ready = True
        bridge._peer_lock = threading.Lock()
        bridge._peer_stats = {}
        bridge._sync_rounds = {}

        fake_event = {
            "event_id": "a" * 64,
            "prev_hash": "b" * 64,
            "event_type": "test",
        }

        fake_infonet = MagicMock()
        fake_infonet.head_hash = "b" * 64
        fake_infonet.get_event.return_value = None
        fake_infonet.ingest_events.side_effect = RuntimeError("ingest forced failure")

        fake_hc_module = MagicMock()
        fake_hc_module.infonet = fake_infonet

        with patch.dict(sys.modules, {"services.mesh.mesh_hashchain": fake_hc_module}), \
             caplog.at_level(logging.WARNING, logger="services.mesh_rns"):
            bridge._ingest_ordered([fake_event])

        msgs = _log_messages(caplog, "services.mesh_rns", logging.WARNING)
        assert any("IBF ordered ingest failed" in m for m in msgs), (
            "IBF ingest failure must be logged at WARNING"
        )


# ---------------------------------------------------------------------------
# 4. mesh_rns._cover_loop — exception is logged at DEBUG
# ---------------------------------------------------------------------------

class TestRNSCoverLoop:

    def test_cover_loop_exception_is_logged(self, caplog):
        """Exception in _cover_loop must be logged at DEBUG before the sleep."""
        from services.mesh import mesh_rns

        bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
        bridge._privacy_cache = {}
        bridge._enabled = True
        bridge._ready = True

        call_count = [0]

        def boom():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("forced cover failure")
            raise SystemExit

        with patch.object(bridge, "enabled", return_value=True), \
             patch.object(bridge, "_is_high_privacy", return_value=True), \
             patch.object(bridge, "_cover_interval", return_value=30), \
             patch.object(bridge, "_send_cover_traffic", side_effect=boom), \
             patch("time.sleep"), \
             caplog.at_level(logging.DEBUG, logger="services.mesh_rns"):
            try:
                bridge._cover_loop()
            except SystemExit:
                pass

        msgs = _log_messages(caplog, "services.mesh_rns", logging.DEBUG)
        assert any("Cover loop error" in m for m in msgs), (
            "_cover_loop exception must be logged at DEBUG"
        )


# ---------------------------------------------------------------------------
# 5. mesh_rns _ingest_with_quorum fork fallback — logged, ingest still called
# ---------------------------------------------------------------------------

class TestRNSForkFallback:

    def test_fork_resolution_failure_is_logged_source_check(self):
        """_ingest_with_quorum must have 'Fork resolution failed' in its source."""
        import inspect
        from services.mesh import mesh_rns
        source = inspect.getsource(mesh_rns.RNSBridge._ingest_with_quorum)
        assert "Fork resolution failed" in source, (
            "_ingest_with_quorum must log 'Fork resolution failed' on exception "
            "before falling back to _ingest_ordered"
        )

    def test_fork_fallback_logs_warning(self, caplog):
        """When apply_fork raises, WARNING is logged before fallback to _ingest_ordered."""
        from services.mesh import mesh_rns

        bridge = mesh_rns.RNSBridge.__new__(mesh_rns.RNSBridge)
        bridge._peer_lock = threading.Lock()
        bridge._peer_stats = {}
        bridge._sync_rounds = {}
        bridge._enabled = True
        bridge._ready = True
        bridge._sync_lock = threading.Lock()
        bridge._pending_sync = {}

        # local head != remote head_hash → triggers apply_fork
        local_head = "aaaa1111"
        remote_head = "bbbb2222"

        fake_infonet = MagicMock()
        fake_infonet.head_hash = local_head
        fake_infonet.apply_fork.side_effect = RuntimeError("forced fork failure")

        fake_hc_module = MagicMock()
        fake_hc_module.infonet = fake_infonet

        ingest_called = []
        def fake_ingest_ordered(events):
            ingest_called.extend(events)

        merged_events = [{"event_id": "c" * 64, "event_type": "test"}]

        # Synthesize a pending sync entry so _ingest_with_quorum reaches fork code
        sync_id = "test-sync-001"
        head_hash = remote_head
        bridge._pending_sync[sync_id] = {
            "quorum": 1,
            "responders": set(),
            "responses": {
                head_hash: {"count": 1, "events": [merged_events]},
            },
        }

        meta = {"sync_id": sync_id, "head_hash": head_hash, "reply_to": "peer1"}

        with patch.dict(sys.modules, {"services.mesh.mesh_hashchain": fake_hc_module}), \
             patch.object(bridge, "_ingest_ordered", side_effect=fake_ingest_ordered), \
             patch.object(bridge, "_merge_bucket_events", return_value=merged_events), \
             caplog.at_level(logging.WARNING, logger="services.mesh_rns"):
            bridge._ingest_with_quorum(merged_events, meta)

        msgs = _log_messages(caplog, "services.mesh_rns", logging.WARNING)
        assert any("Fork resolution failed" in m for m in msgs), (
            "_ingest_with_quorum exception must be logged at WARNING"
        )
        assert ingest_called, "Fallback to _ingest_ordered must still be called"


# ---------------------------------------------------------------------------
# 6. mesh_rns infonet_event ingest failure — logged at WARNING
# ---------------------------------------------------------------------------

class TestRNSInfonetEventIngest:

    def test_ingest_events_failure_is_logged(self, caplog):
        """infonet.ingest_events raising in the infonet_event handler must be
        logged at WARNING."""
        from services.mesh import mesh_rns
        import json

        bridge = _make_rns_bridge()

        fake_infonet = MagicMock()
        fake_infonet.ingest_events.side_effect = RuntimeError("forced ingest failure")

        fake_hc_module = MagicMock()
        fake_hc_module.infonet = fake_infonet

        event = {
            "event_id": "d" * 64,
            "prev_hash": "e" * 64,
            "event_type": "test",
            "payload": {},
            "signature": "sig",
            "public_key": "pk",
        }
        raw_msg = json.dumps({
            "type": "infonet_event",
            "body": {"event": event},
            "meta": {"message_id": "test-msg-id-001", "dandelion": {"phase": "diffuse"}},
        }).encode()

        with patch.dict(sys.modules, {"services.mesh.mesh_hashchain": fake_hc_module}), \
             patch.object(bridge, "_send_to_peer", return_value=None), \
             patch.object(bridge, "_send_diffuse", return_value=None), \
             patch.object(bridge, "_pick_stem_peer", return_value=None), \
             caplog.at_level(logging.WARNING, logger="services.mesh_rns"):
            bridge._on_packet(raw_msg)

        msgs = _log_messages(caplog, "services.mesh_rns", logging.WARNING)
        assert any("infonet ingest_events failed" in m for m in msgs), (
            "infonet.ingest_events failure must be logged at WARNING"
        )

    def test_ingest_failure_log_does_not_contain_event_data(self, caplog):
        """The WARNING log for ingest failure must not contain event payload data."""
        from services.mesh import mesh_rns
        import json

        bridge = _make_rns_bridge()

        sentinel = "SENSITIVE_PAYLOAD_DATA_XYZ"
        fake_infonet = MagicMock()
        fake_infonet.ingest_events.side_effect = RuntimeError(sentinel)

        fake_hc_module = MagicMock()
        fake_hc_module.infonet = fake_infonet

        event = {
            "event_id": "f" * 64,
            "prev_hash": "0" * 64,
            "event_type": "test",
            "payload": {"secret": sentinel},
        }
        raw_msg = json.dumps({
            "type": "infonet_event",
            "body": {"event": event},
            "meta": {"message_id": "test-msg-002", "dandelion": {"phase": "diffuse"}},
        }).encode()

        with patch.dict(sys.modules, {"services.mesh.mesh_hashchain": fake_hc_module}), \
             patch.object(bridge, "_send_to_peer", return_value=None), \
             patch.object(bridge, "_send_diffuse", return_value=None), \
             patch.object(bridge, "_pick_stem_peer", return_value=None), \
             caplog.at_level(logging.WARNING, logger="services.mesh_rns"):
            bridge._on_packet(raw_msg)

        all_msgs = " ".join(_log_messages(caplog, "services.mesh_rns", logging.WARNING))
        assert sentinel not in all_msgs, (
            "Ingest failure log must not contain exception message text (possible payload leak)"
        )


# ---------------------------------------------------------------------------
# 7. mesh_rns gate_event handler — gate_store failure logged at DEBUG
# ---------------------------------------------------------------------------

class TestRNSGateEventIngest:

    def test_gate_store_failure_is_logged(self, caplog):
        """gate_store.ingest_peer_events raising must be logged at DEBUG."""
        from services.mesh import mesh_rns
        import json

        bridge = _make_rns_bridge()

        fake_gate_store = MagicMock()
        fake_gate_store.ingest_peer_events.side_effect = RuntimeError("forced gate failure")
        fake_hc_module = MagicMock()
        fake_hc_module.gate_store = fake_gate_store
        fake_hc_module.resolve_gate_wire_ref.return_value = "testgate"

        event = {
            "event_id": "a1" * 32,
            "prev_hash": "b2" * 32,
            "event_type": "gate_message",
            "payload": {"gate": "testgate", "data": "x"},
        }
        raw_msg = json.dumps({
            "type": "gate_event",
            "body": {"event": event},
            "meta": {"message_id": "test-gate-001", "dandelion": {"phase": "diffuse"}},
        }).encode()

        with patch.dict(sys.modules, {"services.mesh.mesh_hashchain": fake_hc_module}), \
             patch.object(bridge, "_send_to_peer", return_value=None), \
             patch.object(bridge, "_send_diffuse", return_value=None), \
             patch.object(bridge, "_pick_stem_peer", return_value=None), \
             caplog.at_level(logging.DEBUG, logger="services.mesh_rns"):
            bridge._on_packet(raw_msg)

        msgs = _log_messages(caplog, "services.mesh_rns", logging.DEBUG)
        assert any("gate_store ingest_peer_events failed" in m for m in msgs), (
            "gate_store.ingest_peer_events failure must be logged at DEBUG"
        )


# ---------------------------------------------------------------------------
# 8-12. mesh_dm_mls — cleanup-path failures are logged at DEBUG
# ---------------------------------------------------------------------------

class TestDMMlsCleanupLogging:
    """All resource-release paths in mesh_dm_mls that previously had
    'except Exception: pass' must now emit a DEBUG log."""

    def test_release_identity_cleanup_logged(self, caplog):
        """release_identity failure during binding-failed cleanup must be logged at DEBUG."""
        from services.mesh import mesh_dm_mls

        failing_client = MagicMock()
        failing_client.create_identity.return_value = 42
        failing_client.export_public_bundle.return_value = b"bundle"
        failing_client.release_identity.side_effect = RuntimeError("release_identity boom")

        with patch("services.mesh.mesh_dm_mls._load_state"), \
             patch("services.mesh.mesh_dm_mls._privacy_client", return_value=failing_client), \
             patch("services.mesh.mesh_dm_mls._ALIAS_IDENTITIES", {}), \
             patch("services.mesh.mesh_dm_mls.sign_dm_alias_blob",
                   return_value={"ok": False, "detail": "forced_fail"}), \
             caplog.at_level(logging.DEBUG, logger="services.mesh.mesh_dm_mls"):
            with pytest.raises(Exception):
                mesh_dm_mls._identity_handle_for_alias("testalias")

        msgs = _log_messages(caplog, "services.mesh.mesh_dm_mls", logging.DEBUG)
        assert any("release_identity cleanup failed" in m for m in msgs), (
            "release_identity cleanup failure must be logged at DEBUG"
        )

    def test_release_identity_cleanup_does_not_log_handle(self, caplog):
        """The DEBUG log for release_identity must not contain the handle integer."""
        from services.mesh import mesh_dm_mls

        handle_value = 99999  # sentinel
        failing_client = MagicMock()
        failing_client.create_identity.return_value = handle_value
        failing_client.export_public_bundle.return_value = b"bundle"
        failing_client.release_identity.side_effect = RuntimeError("boom")

        with patch("services.mesh.mesh_dm_mls._load_state"), \
             patch("services.mesh.mesh_dm_mls._privacy_client", return_value=failing_client), \
             patch("services.mesh.mesh_dm_mls._ALIAS_IDENTITIES", {}), \
             patch("services.mesh.mesh_dm_mls.sign_dm_alias_blob",
                   return_value={"ok": False, "detail": "forced_fail"}), \
             caplog.at_level(logging.DEBUG, logger="services.mesh.mesh_dm_mls"):
            with pytest.raises(Exception):
                mesh_dm_mls._identity_handle_for_alias("testalias")

        all_msgs = " ".join(_log_messages(caplog, "services.mesh.mesh_dm_mls", logging.DEBUG))
        assert str(handle_value) not in all_msgs, (
            "Handle integer must not appear in cleanup log messages"
        )

    def test_remember_session_release_dm_session_logged(self, caplog):
        """Duplicate-session release_dm_session failure must be logged at DEBUG."""
        from services.mesh import mesh_dm_mls

        existing_binding = MagicMock()
        failing_client = MagicMock()
        failing_client.release_dm_session.side_effect = RuntimeError("release boom")

        session_id = mesh_dm_mls._session_id("aliasA", "aliasB")

        with patch("services.mesh.mesh_dm_mls._load_state"), \
             patch("services.mesh.mesh_dm_mls._privacy_client", return_value=failing_client), \
             patch("services.mesh.mesh_dm_mls._SESSIONS", {session_id: existing_binding}), \
             patch("services.mesh.mesh_dm_mls._save_state"), \
             caplog.at_level(logging.DEBUG, logger="services.mesh.mesh_dm_mls"):
            result = mesh_dm_mls._remember_session("aliasA", "aliasB",
                                                    role="initiator", session_handle=7)

        assert result is existing_binding
        msgs = _log_messages(caplog, "services.mesh.mesh_dm_mls", logging.DEBUG)
        assert any("release_dm_session cleanup failed" in m for m in msgs), (
            "release_dm_session cleanup failure in _remember_session must be logged at DEBUG"
        )

    def test_initiate_finally_release_key_package_logged(self, caplog):
        """release_key_package failure in initiate_dm_session finally must be logged at DEBUG.

        The function accepts remote_prekey_bundle: dict with 'mls_key_package' key.
        import_key_package is mocked to return a handle, then create_dm_session raises
        so the finally block runs with key_package_handle set but session_handle=0.
        """
        from services.mesh import mesh_dm_mls

        failing_client = MagicMock()
        failing_client.import_key_package.return_value = 55
        failing_client.create_dm_session.side_effect = RuntimeError("force initiate fail")
        failing_client.release_key_package.side_effect = RuntimeError("kp release boom")

        import base64
        dummy_kp_b64 = base64.b64encode(b"dummy_key_package").decode()

        with patch("services.mesh.mesh_dm_mls._load_state"), \
             patch("services.mesh.mesh_dm_mls._privacy_client", return_value=failing_client), \
             patch("services.mesh.mesh_dm_mls._identity_handle_for_alias", return_value=1), \
             patch("services.mesh.mesh_dm_mls._seal_keypair_for_alias",
                   return_value={"public_key": "pk", "private_key": "sk"}), \
             patch("services.mesh.mesh_dm_mls._require_private_transport",
                   return_value=(True, "")), \
             caplog.at_level(logging.DEBUG, logger="services.mesh.mesh_dm_mls"):
            result = mesh_dm_mls.initiate_dm_session(
                "aliasA", "aliasB",
                remote_prekey_bundle={"mls_key_package": dummy_kp_b64},
            )

        assert result.get("ok") is False
        msgs = _log_messages(caplog, "services.mesh.mesh_dm_mls", logging.DEBUG)
        assert any("release_key_package cleanup failed" in m for m in msgs), (
            "release_key_package cleanup failure must be logged at DEBUG"
        )

    def test_accept_finally_release_dm_session_logged(self, caplog):
        """release_dm_session failure in accept_dm_session finally must be logged at DEBUG.

        join_dm_session must return a non-zero handle so session_handle != 0,
        then _remember_session must raise so remembered=False, triggering the finally.
        """
        from services.mesh import mesh_dm_mls

        failing_client = MagicMock()
        failing_client.join_dm_session.return_value = 77  # non-zero handle
        failing_client.release_dm_session.side_effect = RuntimeError("session release boom")

        import base64
        dummy_welcome_b64 = base64.b64encode(b"dummy_welcome").decode()

        with patch("services.mesh.mesh_dm_mls._load_state"), \
             patch("services.mesh.mesh_dm_mls._privacy_client", return_value=failing_client), \
             patch("services.mesh.mesh_dm_mls._identity_handle_for_alias", return_value=1), \
             patch("services.mesh.mesh_dm_mls._seal_keypair_for_alias",
                   return_value={"public_key": "pk", "private_key": "sk"}), \
             patch("services.mesh.mesh_dm_mls._unseal_welcome_for_private_key",
                   return_value=b"welcome"), \
             patch("services.mesh.mesh_dm_mls._remember_session",
                   side_effect=RuntimeError("remember failed")), \
             patch("services.mesh.mesh_dm_mls._require_private_transport",
                   return_value=(True, "")), \
             caplog.at_level(logging.DEBUG, logger="services.mesh.mesh_dm_mls"):
            result = mesh_dm_mls.accept_dm_session(
                "aliasA", "aliasB",
                welcome_b64=dummy_welcome_b64,
            )

        assert result.get("ok") is False
        msgs = _log_messages(caplog, "services.mesh.mesh_dm_mls", logging.DEBUG)
        assert any("release_dm_session cleanup failed" in m for m in msgs), (
            "release_dm_session cleanup failure in accept_dm_session must be logged at DEBUG"
        )


# ---------------------------------------------------------------------------
# 13. Source-level checks — all touched paths have no bare 'except Exception: pass'
# ---------------------------------------------------------------------------

class TestNoBareSilentExceptions:
    """Regression guard: the touched functions must not contain bare
    'except Exception:\\n        pass' (or equivalent) any more."""

    def _source_of(self, obj) -> str:
        import inspect
        return inspect.getsource(obj)

    def test_raw_fallback_allowed_no_silent_pass(self):
        import services.mesh.mesh_secure_storage as mss
        source = self._source_of(mss._raw_fallback_allowed)
        assert "except Exception as exc" in source
        lines = source.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("except") and "Exception" in stripped:
                for next_line in lines[i + 1:]:
                    ns = next_line.strip()
                    if ns:
                        assert ns != "pass", (
                            "_raw_fallback_allowed exception handler must not be bare pass"
                        )
                        break

    def test_ibf_sync_loop_no_silent_pass(self):
        from services.mesh import mesh_rns
        source = self._source_of(mesh_rns.RNSBridge._ibf_sync_loop)
        assert "except Exception as exc" in source
        assert "logger.warning" in source

    def test_cover_loop_no_silent_pass(self):
        from services.mesh import mesh_rns
        source = self._source_of(mesh_rns.RNSBridge._cover_loop)
        assert "except Exception as exc" in source
        assert "logger.debug" in source
