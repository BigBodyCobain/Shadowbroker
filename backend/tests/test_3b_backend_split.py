"""Sprint 3B: Backend Split Verification — regression tests.

Covers invariants established by the Phase 1 foundation extraction:
1. auth.py / limiter.py / node_state.py are importable without importing main.
2. _NODE_SYNC_STOP is a threading.Event.
3. set_sync_state / get_sync_state round-trip is correct.
4. globals()["_NODE_SYNC_STATE"] pattern is absent from main.py sync paths.
5. auth/node_state import topology has no circular dependency on main.
6. Peer-push routes remain tied to _verify_peer_push_hmac.
7. Lifespan node-state wiring invariants remain correct after extraction.
"""

import inspect
import os
import threading


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read_backend_source(filename: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", filename)
    with open(os.path.normpath(path), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1. Foundation modules must not drag in main
# ---------------------------------------------------------------------------

class TestFoundationModuleImportIsolation:
    """auth, limiter, and node_state must not import main at the module level.

    This preserves the ability for future router files to import from these
    modules without triggering a full main.py import cycle.
    """

    def test_auth_does_not_import_main(self):
        source = _read_backend_source("auth.py")
        assert "import main" not in source, "auth.py must not import main"
        assert "from main " not in source, "auth.py must not import from main"

    def test_limiter_does_not_import_main(self):
        source = _read_backend_source("limiter.py")
        assert "import main" not in source, "limiter.py must not import main"
        assert "from main " not in source, "limiter.py must not import from main"

    def test_node_state_does_not_import_main(self):
        source = _read_backend_source("node_state.py")
        assert "import main" not in source, "node_state.py must not import main"
        assert "from main " not in source, "node_state.py must not import from main"

    def test_require_admin_importable_from_auth(self):
        """require_admin must be a callable exported by auth."""
        from auth import require_admin
        assert callable(require_admin)

    def test_limiter_importable_from_limiter_module(self):
        """limiter must be a Limiter instance exported by limiter.py."""
        from limiter import limiter as rate_limiter
        from slowapi import Limiter
        assert isinstance(rate_limiter, Limiter)

    def test_node_state_exports_importable(self):
        """_NODE_SYNC_STOP, get_sync_state, set_sync_state must all be importable."""
        from node_state import _NODE_SYNC_STOP, get_sync_state, set_sync_state
        assert callable(get_sync_state)
        assert callable(set_sync_state)
        assert _NODE_SYNC_STOP is not None


# ---------------------------------------------------------------------------
# 2. _NODE_SYNC_STOP type
# ---------------------------------------------------------------------------

class TestNodeSyncStopType:
    def test_node_sync_stop_is_threading_event(self):
        from node_state import _NODE_SYNC_STOP
        assert isinstance(_NODE_SYNC_STOP, threading.Event), (
            "_NODE_SYNC_STOP must be a threading.Event"
        )


# ---------------------------------------------------------------------------
# 3. set_sync_state / get_sync_state round-trip
# ---------------------------------------------------------------------------

class TestSyncStateRoundTrip:
    def test_set_then_get_returns_new_state(self):
        from node_state import get_sync_state, set_sync_state
        from services.mesh.mesh_infonet_sync_support import SyncWorkerState

        original = get_sync_state()
        new_state = SyncWorkerState()
        try:
            set_sync_state(new_state)
            assert get_sync_state() is new_state, (
                "get_sync_state must return the exact object passed to set_sync_state"
            )
        finally:
            set_sync_state(original)

    def test_get_is_stable_without_set(self):
        from node_state import get_sync_state
        assert get_sync_state() is get_sync_state(), (
            "get_sync_state must return the same object on repeated calls "
            "when set_sync_state has not been called between them"
        )

    def test_set_sync_state_is_module_scoped(self):
        """set_sync_state must modify the node_state module's own namespace
        (not just a local variable), so subsequent get_sync_state() calls from
        any importing module see the updated value."""
        import node_state
        from services.mesh.mesh_infonet_sync_support import SyncWorkerState

        original = node_state.get_sync_state()
        sentinel = SyncWorkerState()
        try:
            node_state.set_sync_state(sentinel)
            assert node_state._NODE_SYNC_STATE is sentinel, (
                "set_sync_state must update node_state._NODE_SYNC_STATE in-module"
            )
            assert node_state.get_sync_state() is sentinel
        finally:
            node_state.set_sync_state(original)


# ---------------------------------------------------------------------------
# 4. globals()["_NODE_SYNC_STATE"] pattern absent from main.py sync paths
# ---------------------------------------------------------------------------

class TestGlobalsPatternAbsent:
    """No direct globals()["_NODE_SYNC_STATE"] assignment must remain in the
    sync-relevant paths of main.py after the 3B extraction."""

    def test_globals_pattern_absent_from_run_public_sync_cycle(self):
        import main
        source = inspect.getsource(main._run_public_sync_cycle)
        assert 'globals()["_NODE_SYNC_STATE"]' not in source, (
            '_run_public_sync_cycle must use set_sync_state(), '
            'not globals()["_NODE_SYNC_STATE"]'
        )

    def test_globals_pattern_absent_from_public_infonet_sync_loop(self):
        import main
        source = inspect.getsource(main._public_infonet_sync_loop)
        assert 'globals()["_NODE_SYNC_STATE"]' not in source, (
            '_public_infonet_sync_loop must use set_sync_state(), '
            'not globals()["_NODE_SYNC_STATE"]'
        )

    def test_globals_pattern_absent_from_lifespan(self):
        import main
        source = inspect.getsource(main.lifespan)
        assert 'globals()["_NODE_SYNC_STATE"]' not in source, (
            'lifespan must use set_sync_state(), not globals()["_NODE_SYNC_STATE"]'
        )

    def test_node_sync_state_direct_ref_absent_from_main(self):
        """_NODE_SYNC_STATE must not be referenced directly in main.py at all —
        all access must go through get_sync_state() / set_sync_state()."""
        source = _read_backend_source("main.py")
        assert "_NODE_SYNC_STATE" not in source, (
            "main.py must not reference _NODE_SYNC_STATE directly; "
            "all access must use get_sync_state() / set_sync_state()"
        )

    def test_set_sync_state_called_in_sync_cycle(self):
        import main
        source = inspect.getsource(main._run_public_sync_cycle)
        assert "set_sync_state(" in source, (
            "_run_public_sync_cycle must call set_sync_state() to update node sync state"
        )

    def test_set_sync_state_called_in_sync_loop(self):
        import main
        source = inspect.getsource(main._public_infonet_sync_loop)
        assert "set_sync_state(" in source, (
            "_public_infonet_sync_loop must call set_sync_state() to update node sync state"
        )


# ---------------------------------------------------------------------------
# 5. Import topology — no circular dependency on main
# ---------------------------------------------------------------------------

class TestImportTopology:
    """auth.py, limiter.py, and node_state.py must never import from main.py.

    A circular import would break the isolation goal of the 3B extraction and
    cause import-time failures when router files later import from these modules.
    """

    def test_auth_no_main_import(self):
        source = _read_backend_source("auth.py")
        assert "import main" not in source
        assert "from main " not in source

    def test_node_state_no_main_import(self):
        source = _read_backend_source("node_state.py")
        assert "import main" not in source
        assert "from main " not in source

    def test_node_state_no_auth_import(self):
        """node_state must not import auth — the state layer must stay
        dependency-free so it can be imported first during startup."""
        source = _read_backend_source("node_state.py")
        assert "import auth" not in source
        assert "from auth " not in source

    def test_limiter_no_main_import(self):
        source = _read_backend_source("limiter.py")
        assert "import main" not in source
        assert "from main " not in source

    def test_main_imports_from_node_state(self):
        """main.py must declare its node_state imports via 'from node_state import'."""
        source = _read_backend_source("main.py")
        assert "from node_state import" in source, (
            "main.py must import node-state helpers from node_state"
        )

    def test_main_imports_from_auth(self):
        """main.py must declare its auth imports via 'from auth import'."""
        source = _read_backend_source("main.py")
        assert "from auth import" in source, (
            "main.py must import auth helpers from auth"
        )

    def test_main_imports_from_limiter(self):
        """main.py must import the shared limiter instance from limiter.py."""
        source = _read_backend_source("main.py")
        assert "from limiter import" in source, (
            "main.py must import the limiter instance from limiter"
        )


# ---------------------------------------------------------------------------
# 6. Peer-push routes protected by _verify_peer_push_hmac
# ---------------------------------------------------------------------------

class TestPeerPushHmacProtection:
    """The peer-push ingest routes must call _verify_peer_push_hmac before
    accepting any payload, and that function must originate in auth.py."""

    def test_verify_peer_push_hmac_defined_in_auth(self):
        source = _read_backend_source("auth.py")
        assert "def _verify_peer_push_hmac" in source, (
            "_verify_peer_push_hmac must be defined in auth.py"
        )

    def test_verify_peer_push_hmac_imported_into_main(self):
        source = _read_backend_source("main.py")
        assert "_verify_peer_push_hmac" in source, (
            "_verify_peer_push_hmac must appear in main.py (imported from auth)"
        )

    def test_infonet_peer_push_calls_verify_hmac(self):
        import main
        source = inspect.getsource(main.infonet_peer_push)
        assert "_verify_peer_push_hmac" in source, (
            "infonet_peer_push must call _verify_peer_push_hmac before accepting payload"
        )

    def test_gate_peer_push_calls_verify_hmac(self):
        import main
        source = inspect.getsource(main.gate_peer_push)
        assert "_verify_peer_push_hmac" in source, (
            "gate_peer_push must call _verify_peer_push_hmac before accepting payload"
        )


# ---------------------------------------------------------------------------
# 7. Lifespan node-state wiring invariants
# ---------------------------------------------------------------------------

class TestLifespanNodeStateWiring:
    """The lifespan startup block must wire node-state correctly after 3B
    extraction: set_sync_state replaces the old globals() assignment, and
    _NODE_SYNC_STOP is cleared before the sync thread is started."""

    def _lifespan_source(self) -> str:
        import main
        return inspect.getsource(main.lifespan)

    def test_lifespan_calls_set_sync_state(self):
        source = self._lifespan_source()
        assert "set_sync_state(" in source, (
            "lifespan must call set_sync_state() to initialize node sync state "
            "for the disabled-at-startup path"
        )

    def test_lifespan_clears_node_sync_stop(self):
        source = self._lifespan_source()
        assert "_NODE_SYNC_STOP.clear()" in source, (
            "lifespan must call _NODE_SYNC_STOP.clear() before starting the sync loop"
        )

    def test_lifespan_does_not_reference_node_sync_state_directly(self):
        source = self._lifespan_source()
        assert "_NODE_SYNC_STATE" not in source, (
            "lifespan must not reference _NODE_SYNC_STATE directly; "
            "use set_sync_state() / get_sync_state()"
        )

    def test_main_imports_set_sync_state_from_node_state(self):
        source = _read_backend_source("main.py")
        # Confirm set_sync_state is present and comes from node_state
        assert "set_sync_state" in source
        node_state_block = next(
            (line for line in source.splitlines() if "from node_state import" in line),
            "",
        )
        assert node_state_block, "main.py must have a 'from node_state import' line"
        # set_sync_state may span a multi-line import; verify it appears somewhere
        # near the node_state import (within the module-level import block).
        import_section = source[:source.find("\n\n\n")]
        assert "set_sync_state" in import_section, (
            "set_sync_state must be imported at module level from node_state"
        )
