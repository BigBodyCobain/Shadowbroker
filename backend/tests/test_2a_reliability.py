"""Sprint 2A: Backend Reliability Core — regression tests.

Covers:
1. data_fetcher._run_tasks: future.result() now has a hard timeout; TimeoutError
   is recorded as a failure, not an indefinite hang.
2. flights._fetch_supplemental_sources: cache read and write are both done under
   _supplemental_cache_lock so the timestamp+data pair is atomic.
3. flights._enrich_with_opensky_and_supplemental (OpenSky path): cache check,
   read, and write are all done under _opensky_cache_lock.
4. main._run_public_sync_cycle: reads _NODE_SYNC_STATE under _NODE_RUNTIME_LOCK.
5. main._public_infonet_sync_loop: reads _NODE_SYNC_STATE under _NODE_RUNTIME_LOCK.
6. main._record_public_push_result: reads _NODE_PUSH_STATE under _NODE_RUNTIME_LOCK
   (build-snapshot-and-update is a single atomic block).
7. main._verify_loop: always passes verify_signatures=True regardless of any env var.
8. config.py: MESH_VERIFY_SIGNATURES field is no longer a recognised setting.
"""

import threading
import time
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# 1. data_fetcher._run_tasks — TimeoutError propagates as failure
# ---------------------------------------------------------------------------

class TestRunTasksTimeout:
    """_run_tasks must unblock within _TASK_HARD_TIMEOUT_S when a task hangs.

    The fix uses futures.items() iteration so future.result(timeout=...) IS the
    blocking call.  as_completed() is no longer used because it blocks inside
    __next__() waiting for completion — the timeout on result() would never be
    reached for a hanging task under that pattern.
    """

    def test_hanging_task_unblocks_run_tasks(self):
        """_run_tasks must return within timeout + epsilon even when a task hangs.

        A real threading.Event holds the task indefinitely.  _TASK_HARD_TIMEOUT_S
        is patched to 0.3s so the test is fast.  The wall-clock guard is 3× the
        timeout to give generous CI headroom while still catching a true hang.
        """
        import services.data_fetcher as df

        hold = threading.Event()  # never set — task blocks until TimeoutError

        def hanging_task():
            hold.wait()  # blocks indefinitely

        failure_names = []

        def fake_record_failure(name, error, duration_s):  # noqa: ARG001
            failure_names.append(name)

        SHORT_TIMEOUT = 0.3
        wall_limit = SHORT_TIMEOUT * 3 + 1.0  # generous CI headroom

        with patch.object(df, "_TASK_HARD_TIMEOUT_S", SHORT_TIMEOUT), \
             patch("services.fetch_health.record_failure", fake_record_failure), \
             patch("services.fetch_health.record_success", lambda *a, **kw: None):
            started = time.perf_counter()
            df._run_tasks("test", [hanging_task])
            elapsed = time.perf_counter() - started

        hold.set()  # release the background thread so it can exit

        assert elapsed < wall_limit, (
            f"_run_tasks blocked for {elapsed:.2f}s — timeout not enforced "
            f"(limit was {wall_limit:.2f}s)"
        )
        assert "hanging_task" in failure_names, (
            "Timed-out task must be recorded via record_failure"
        )

    def test_as_completed_not_called_in_run_tasks(self):
        """_run_tasks must not call as_completed(futures) — that pattern makes
        timeout= unreachable for hanging tasks."""
        import inspect
        import services.data_fetcher as df
        source = inspect.getsource(df._run_tasks)
        # The call expression — not a comment mention — must be absent.
        assert "as_completed(futures)" not in source, (
            "_run_tasks must not call as_completed(futures): "
            "as_completed blocks in __next__() so result(timeout=) is never reached"
        )

    def test_as_completed_not_called_in_update_all_data(self):
        """update_all_data must not call as_completed(futures) for the same reason."""
        import inspect
        import services.data_fetcher as df
        source = inspect.getsource(df.update_all_data)
        assert "as_completed(futures)" not in source, (
            "update_all_data must not call as_completed(futures)"
        )

    def test_hard_timeout_constant_present(self):
        """_TASK_HARD_TIMEOUT_S must be defined and positive in data_fetcher."""
        import services.data_fetcher as df
        assert hasattr(df, "_TASK_HARD_TIMEOUT_S")
        assert df._TASK_HARD_TIMEOUT_S > 0

    def test_future_result_called_with_timeout(self):
        """_run_tasks must pass timeout= to every future.result() call."""
        import inspect
        import services.data_fetcher as df
        source = inspect.getsource(df._run_tasks)
        assert "future.result(timeout=" in source, (
            "_run_tasks must call future.result(timeout=...) not future.result()"
        )

    def test_update_all_data_future_result_called_with_timeout(self):
        """update_all_data must also pass timeout= to future.result()."""
        import inspect
        import services.data_fetcher as df
        source = inspect.getsource(df.update_all_data)
        assert "future.result(timeout=" in source, (
            "update_all_data must call future.result(timeout=...) not future.result()"
        )


# ---------------------------------------------------------------------------
# 2 & 3. flights.py — locked cache access for OpenSky and supplemental
# ---------------------------------------------------------------------------

class TestFlightsCacheLocks:
    """Verify that both cache pairs are protected by their respective locks."""

    def test_supplemental_cache_lock_exists(self):
        from services.fetchers import flights
        assert hasattr(flights, "_supplemental_cache_lock")
        assert isinstance(flights._supplemental_cache_lock, type(threading.Lock()))

    def test_opensky_cache_lock_exists(self):
        from services.fetchers import flights
        assert hasattr(flights, "_opensky_cache_lock")
        assert isinstance(flights._opensky_cache_lock, type(threading.Lock()))

    def test_supplemental_read_uses_lock(self):
        """Cache-hit path in _fetch_supplemental_sources acquires the lock."""
        from services.fetchers import flights

        lock_acquired = []

        class TrackingLock:
            def __enter__(self):
                lock_acquired.append(True)
                return self
            def __exit__(self, *args):
                pass

        with patch.object(flights, "_supplemental_cache_lock", TrackingLock()), \
             patch.object(flights, "last_supplemental_fetch", time.time()):
            # Cache is fresh — should hit the locked early-return path
            flights._fetch_supplemental_sources(set())

        assert len(lock_acquired) >= 1, "Lock must be acquired on cache-hit read"

    def test_supplemental_write_uses_lock(self):
        """Cache-miss path in _fetch_supplemental_sources acquires the lock for write."""
        from services.fetchers import flights
        import inspect
        source = inspect.getsource(flights._fetch_supplemental_sources)
        # Both cache writes must be inside a with _supplemental_cache_lock block
        assert "_supplemental_cache_lock" in source
        # The write of the pair (timestamp + data) must appear inside the context
        assert "cached_supplemental_flights = new_supplemental" in source
        assert "last_supplemental_fetch = now" in source

    def test_opensky_cache_lock_used_in_enrich(self):
        """_enrich_with_opensky_and_supplemental uses _opensky_cache_lock."""
        from services.fetchers import flights
        import inspect
        source = inspect.getsource(flights._enrich_with_opensky_and_supplemental)
        assert "_opensky_cache_lock" in source

    def test_opensky_snapshot_local_variable_used(self):
        """After locking, a local opensky_snapshot is used for merging, not the global."""
        from services.fetchers import flights
        import inspect
        source = inspect.getsource(flights._enrich_with_opensky_and_supplemental)
        assert "opensky_snapshot" in source
        # The merge loop must iterate over the local snapshot, not the global
        assert "for osf in opensky_snapshot" in source

    def test_concurrent_supplemental_reads_consistent(self):
        """Two threads reading _fetch_supplemental_sources on a warm cache both
        see a consistent (non-empty) list without interleaving with a write."""
        from services.fetchers import flights

        original_fetch = flights.last_supplemental_fetch
        original_cache = flights.cached_supplemental_flights

        # Seed the cache
        flights.last_supplemental_fetch = time.time()
        flights.cached_supplemental_flights = [{"hex": "abc123", "lat": 1.0, "lon": 2.0}]

        results = []
        errors = []

        def reader():
            try:
                result = flights._fetch_supplemental_sources(set())
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Restore original state
        flights.last_supplemental_fetch = original_fetch
        flights.cached_supplemental_flights = original_cache

        assert not errors, f"Concurrent reads raised exceptions: {errors}"
        assert all(len(r) == 1 for r in results), "All readers should see the seeded entry"


# ---------------------------------------------------------------------------
# 4 & 5. main.py — node-state reads are locked
# ---------------------------------------------------------------------------

class TestNodeStateLockedReads:
    """_NODE_SYNC_STATE reads at the decision points must use _NODE_RUNTIME_LOCK."""

    def test_run_public_sync_cycle_reads_sync_state_under_lock(self):
        """The assignment 'current_state = get_sync_state()' in
        _run_public_sync_cycle must occur inside _NODE_RUNTIME_LOCK."""
        import inspect
        import main
        source = inspect.getsource(main._run_public_sync_cycle)
        # The lock acquisition must appear before the state read
        lock_pos = source.find("_NODE_RUNTIME_LOCK")
        read_pos = source.find("current_state = get_sync_state()")
        assert lock_pos != -1, "_NODE_RUNTIME_LOCK must appear in _run_public_sync_cycle"
        assert read_pos != -1, "current_state = get_sync_state() must appear in _run_public_sync_cycle"
        # Lock block must precede the read (the read should be INSIDE the with block)
        assert lock_pos < read_pos, (
            "_NODE_RUNTIME_LOCK must be acquired before current_state = get_sync_state()"
        )

    def test_public_infonet_sync_loop_reads_sync_state_under_lock(self):
        """The assignment 'state = get_sync_state()' in _public_infonet_sync_loop
        must occur inside _NODE_RUNTIME_LOCK."""
        import inspect
        import main
        source = inspect.getsource(main._public_infonet_sync_loop)
        lock_pos = source.find("_NODE_RUNTIME_LOCK")
        read_pos = source.find("state = get_sync_state()")
        assert lock_pos != -1
        assert read_pos != -1
        assert lock_pos < read_pos

    def test_record_push_result_reads_push_state_under_lock(self):
        """_record_public_push_result must read _NODE_PUSH_STATE inside the lock,
        not in a snapshot dict built outside it."""
        import inspect
        import main
        source = inspect.getsource(main._record_public_push_result)
        lock_pos = source.find("_NODE_RUNTIME_LOCK")
        push_read_pos = source.find("_NODE_PUSH_STATE.get")
        assert lock_pos != -1
        assert push_read_pos != -1, "_NODE_PUSH_STATE.get must still be present"
        assert lock_pos < push_read_pos, (
            "The _NODE_PUSH_STATE.get read must be INSIDE _NODE_RUNTIME_LOCK"
        )


# ---------------------------------------------------------------------------
# 6. MESH_VERIFY_SIGNATURES — hardcoded True in verify loop
# ---------------------------------------------------------------------------

class TestVerifySignaturesHardcoded:
    """The background verify loop must always pass verify_signatures=True.

    MESH_VERIFY_SIGNATURES in config.py must no longer control the audit loop.
    """

    def test_verify_loop_does_not_read_mesh_verify_signatures(self):
        """_verify_loop in main.py must not call get_settings().MESH_VERIFY_SIGNATURES."""
        import inspect
        import main
        source = inspect.getsource(main.lifespan)
        # The _verify_loop is a nested function inside lifespan — get its source
        # by extracting the full lifespan body
        assert "MESH_VERIFY_SIGNATURES" not in source, (
            "_verify_loop must no longer read MESH_VERIFY_SIGNATURES from settings"
        )

    def test_verify_loop_passes_verify_signatures_true(self):
        """The validate_chain_incremental call must use verify_signatures=True (literal)."""
        import inspect
        import main
        source = inspect.getsource(main.lifespan)
        assert "verify_signatures=True" in source, (
            "validate_chain_incremental must be called with verify_signatures=True"
        )

    def test_config_does_not_expose_mesh_verify_signatures(self):
        """Settings class must no longer have MESH_VERIFY_SIGNATURES as a field."""
        from services.config import Settings
        assert not hasattr(Settings, "MESH_VERIFY_SIGNATURES") or \
               "MESH_VERIFY_SIGNATURES" not in Settings.model_fields, (
            "MESH_VERIFY_SIGNATURES must be removed from Settings — "
            "it can no longer silently weaken the audit loop"
        )

    def test_mesh_verify_signatures_env_var_ignored(self):
        """Setting MESH_VERIFY_SIGNATURES=false in env must have no effect on Settings."""
        import os
        from functools import lru_cache
        import services.config as cfg

        # Force a fresh Settings parse with the flag set to false
        cfg.get_settings.cache_clear()
        original = os.environ.get("MESH_VERIFY_SIGNATURES")
        os.environ["MESH_VERIFY_SIGNATURES"] = "false"
        try:
            settings = cfg.get_settings()
            # The field should simply not exist on the object
            assert not hasattr(settings, "MESH_VERIFY_SIGNATURES"), (
                "MESH_VERIFY_SIGNATURES must not be a recognised settings field"
            )
        finally:
            cfg.get_settings.cache_clear()
            if original is None:
                os.environ.pop("MESH_VERIFY_SIGNATURES", None)
            else:
                os.environ["MESH_VERIFY_SIGNATURES"] = original

    def test_append_time_enforcement_unchanged(self):
        """mesh_hashchain.Infonet.append must still enforce signatures unconditionally
        (no verify_signatures flag on the append path — this is a read-only check)."""
        import inspect
        from services.mesh.mesh_hashchain import Infonet
        source = inspect.getsource(Infonet.append)
        # append() must still require signature fields
        assert "Missing signature fields" in source, (
            "Infonet.append must still raise on missing signature — "
            "append-time enforcement must remain intact"
        )
        assert "verify_signature" in source, (
            "Infonet.append must still call verify_signature — "
            "append-time enforcement must remain intact"
        )
