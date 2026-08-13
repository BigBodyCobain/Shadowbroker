"""Persistence for the investigation domain (stdlib ``sqlite3``, no ORM).

We deliberately reuse SQLite — already a dependency, already used elsewhere in
the backend (CCTV metadata) — rather than introducing Postgres/PostGIS/Redis.
Investigation artifacts (cases, evidence, hypotheses, curated entities/events)
are low-volume analyst products, not the high-throughput telemetry firehose;
SQLite with WAL comfortably covers spatial-lite and temporal range queries at
this scale. The live telemetry store is untouched.
"""

from storage.store import Store, configure_store, get_store, reset_store_for_tests

__all__ = ["Store", "configure_store", "get_store", "reset_store_for_tests"]
