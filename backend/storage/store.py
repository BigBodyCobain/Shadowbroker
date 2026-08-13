"""SQLite-backed repository for the investigation domain.

Storage strategy: **document + projected columns.** Each row keeps the full
model JSON in a ``doc`` column plus a handful of extracted, indexed columns
(type, investigation_id, lat/lng, timestamps) used for filtering. This keeps
the schema narrow and forward-compatible (new model fields need no migration)
while still supporting indexed spatial-lite and time-range queries.

Concurrency: one shared connection in WAL mode guarded by a re-entrant lock.
Analyst write volume is low; this is simple and correct across FastAPI's
threadpool. ``check_same_thread=False`` is safe because every access holds the
lock.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Callable, Optional, Sequence

from domain._util import haversine_km, now_iso
from domain.models import (
    Alert,
    Entity,
    Event,
    Evidence,
    Hypothesis,
    Investigation,
    Note,
    Observation,
    Relationship,
    Source,
)

_SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, kind TEXT, name TEXT, trusted INTEGER,
    last_seen TEXT, doc TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY, type TEXT, canonical_key TEXT, label TEXT,
    lat REAL, lng REAL, last_seen TEXT, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS ix_entities_key ON entities(canonical_key);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY, entity_id TEXT, layer TEXT, lat REAL, lng REAL,
    observed_at TEXT, ingested_at TEXT, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_obs_entity ON observations(entity_id);
CREATE INDEX IF NOT EXISTS ix_obs_time ON observations(observed_at);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY, type TEXT, classification TEXT, severity TEXT,
    lat REAL, lng REAL, occurred_at TEXT, created_at TEXT, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_events_time ON events(occurred_at);
CREATE INDEX IF NOT EXISTS ix_events_type ON events(type);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY, src_entity_id TEXT, dst_entity_id TEXT, type TEXT,
    doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_rel_src ON relationships(src_entity_id);
CREATE INDEX IF NOT EXISTS ix_rel_dst ON relationships(dst_entity_id);

CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY, title TEXT, status TEXT, author TEXT,
    created_at TEXT, updated_at TEXT, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_inv_status ON investigations(status);
CREATE INDEX IF NOT EXISTS ix_inv_updated ON investigations(updated_at);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY, investigation_id TEXT, kind TEXT, classification TEXT,
    lat REAL, lng REAL, occurred_at TEXT, created_at TEXT, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_evd_inv ON evidence(investigation_id);

CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY, investigation_id TEXT, status TEXT,
    created_at TEXT, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_hyp_inv ON hypotheses(investigation_id);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY, investigation_id TEXT, created_at TEXT, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_notes_inv ON notes(investigation_id);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY, type TEXT, status TEXT, severity TEXT,
    investigation_id TEXT, lat REAL, lng REAL, occurred_at TEXT,
    created_at TEXT, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS ix_alerts_time ON alerts(created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT,
    tool TEXT, scope TEXT, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts);
"""


class Store:
    """Thread-safe SQLite repository for investigation-domain objects."""

    def __init__(self, path: str = ":memory:"):
        self.path = path
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_DDL)
            self._conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- low-level helpers ------------------------------------------------- #
    def _write(self, sql: str, params: Sequence[Any]) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.fetchall()

    @staticmethod
    def _load(rows: list[sqlite3.Row], from_dict: Callable[[dict], Any]) -> list[Any]:
        return [from_dict(json.loads(r["doc"])) for r in rows]

    # -- Source ------------------------------------------------------------ #
    def upsert_source(self, s: Source) -> Source:
        self._write(
            "INSERT OR REPLACE INTO sources(id,kind,name,trusted,last_seen,doc) "
            "VALUES(?,?,?,?,?,?)",
            (s.id, s.kind, s.name, int(s.trusted), s.last_seen, json.dumps(s.to_dict())),
        )
        return s

    def get_source(self, sid: str) -> Optional[Source]:
        rows = self._query("SELECT doc FROM sources WHERE id=?", (sid,))
        return Source.from_dict(json.loads(rows[0]["doc"])) if rows else None

    def list_sources(self) -> list[Source]:
        return self._load(self._query("SELECT doc FROM sources ORDER BY name"), Source.from_dict)

    # -- Entity ------------------------------------------------------------ #
    def upsert_entity(self, e: Entity) -> Entity:
        e.updated_at = now_iso()
        self._write(
            "INSERT OR REPLACE INTO entities(id,type,canonical_key,label,lat,lng,last_seen,doc) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (e.id, e.type.value, e.canonical_key, e.label, e.lat, e.lng, e.last_seen,
             json.dumps(e.to_dict())),
        )
        return e

    def get_entity(self, eid: str) -> Optional[Entity]:
        rows = self._query("SELECT doc FROM entities WHERE id=?", (eid,))
        return Entity.from_dict(json.loads(rows[0]["doc"])) if rows else None

    def find_entity_by_key(self, etype: str, key: str) -> Optional[Entity]:
        rows = self._query(
            "SELECT doc FROM entities WHERE type=? AND canonical_key=? LIMIT 1",
            (etype, key),
        )
        return Entity.from_dict(json.loads(rows[0]["doc"])) if rows else None

    def search_entities(
        self, *, query: str = "", etype: str = "", limit: int = 50
    ) -> list[Entity]:
        sql = "SELECT doc FROM entities WHERE 1=1"
        params: list[Any] = []
        if etype:
            sql += " AND type=?"
            params.append(etype)
        if query:
            sql += " AND (label LIKE ? OR canonical_key LIKE ?)"
            like = f"%{query}%"
            params += [like, like]
        sql += " ORDER BY last_seen DESC LIMIT ?"
        params.append(max(1, min(500, limit)))
        return self._load(self._query(sql, params), Entity.from_dict)

    # -- Observation ------------------------------------------------------- #
    def add_observation(self, o: Observation) -> Observation:
        self._write(
            "INSERT OR REPLACE INTO observations"
            "(id,entity_id,layer,lat,lng,observed_at,ingested_at,doc) VALUES(?,?,?,?,?,?,?,?)",
            (o.id, o.entity_id, o.layer, o.lat, o.lng, o.observed_at, o.ingested_at,
             json.dumps(o.to_dict())),
        )
        return o

    def observations_for_entity(self, entity_id: str, limit: int = 200) -> list[Observation]:
        rows = self._query(
            "SELECT doc FROM observations WHERE entity_id=? ORDER BY observed_at DESC LIMIT ?",
            (entity_id, max(1, min(2000, limit))),
        )
        return self._load(rows, Observation.from_dict)

    # -- Event ------------------------------------------------------------- #
    def upsert_event(self, ev: Event) -> Event:
        self._write(
            "INSERT OR REPLACE INTO events"
            "(id,type,classification,severity,lat,lng,occurred_at,created_at,doc) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (ev.id, ev.type, ev.classification.value, ev.severity.value, ev.lat, ev.lng,
             ev.occurred_at, ev.created_at, json.dumps(ev.to_dict())),
        )
        return ev

    def get_event(self, eid: str) -> Optional[Event]:
        rows = self._query("SELECT doc FROM events WHERE id=?", (eid,))
        return Event.from_dict(json.loads(rows[0]["doc"])) if rows else None

    def search_events(
        self,
        *,
        etype: str = "",
        classification: str = "",
        time_from: str = "",
        time_to: str = "",
        limit: int = 100,
    ) -> list[Event]:
        sql = "SELECT doc FROM events WHERE 1=1"
        params: list[Any] = []
        if etype:
            sql += " AND type=?"
            params.append(etype)
        if classification:
            sql += " AND classification=?"
            params.append(classification)
        if time_from:
            sql += " AND occurred_at >= ?"
            params.append(time_from)
        if time_to:
            sql += " AND occurred_at <= ?"
            params.append(time_to)
        sql += " ORDER BY occurred_at DESC LIMIT ?"
        params.append(max(1, min(1000, limit)))
        return self._load(self._query(sql, params), Event.from_dict)

    def events_near(
        self, lat: float, lng: float, radius_km: float = 100.0, limit: int = 100
    ) -> list[tuple[Event, float]]:
        """Events within ``radius_km`` of a point, nearest first.

        A coarse bounding-box prefilter (index-friendly) narrows candidates,
        then an exact haversine filter/sort runs in Python — adequate at
        investigation scale and free of a spatial-index dependency.
        """
        dlat = radius_km / 111.0
        dlng = radius_km / max(1.0, 111.0 * abs(_cos(lat)))
        rows = self._query(
            "SELECT doc FROM events WHERE lat IS NOT NULL AND lng IS NOT NULL "
            "AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
            (lat - dlat, lat + dlat, lng - dlng, lng + dlng),
        )
        out: list[tuple[Event, float]] = []
        for ev in self._load(rows, Event.from_dict):
            if ev.lat is None or ev.lng is None:
                continue
            d = haversine_km(lat, lng, ev.lat, ev.lng)
            if d <= radius_km:
                out.append((ev, round(d, 2)))
        out.sort(key=lambda t: t[1])
        return out[: max(1, min(1000, limit))]

    # -- Relationship ------------------------------------------------------ #
    def upsert_relationship(self, r: Relationship) -> Relationship:
        self._write(
            "INSERT OR REPLACE INTO relationships(id,src_entity_id,dst_entity_id,type,doc) "
            "VALUES(?,?,?,?,?)",
            (r.id, r.src_entity_id, r.dst_entity_id, r.type, json.dumps(r.to_dict())),
        )
        return r

    def relationships_for_entity(self, entity_id: str) -> list[Relationship]:
        rows = self._query(
            "SELECT doc FROM relationships WHERE src_entity_id=? OR dst_entity_id=?",
            (entity_id, entity_id),
        )
        return self._load(rows, Relationship.from_dict)

    # -- Investigation ----------------------------------------------------- #
    def upsert_investigation(self, inv: Investigation) -> Investigation:
        inv.updated_at = now_iso()
        self._write(
            "INSERT OR REPLACE INTO investigations"
            "(id,title,status,author,created_at,updated_at,doc) VALUES(?,?,?,?,?,?,?)",
            (inv.id, inv.title, inv.status.value, inv.author, inv.created_at, inv.updated_at,
             json.dumps(inv.to_dict())),
        )
        return inv

    def get_investigation(self, iid: str) -> Optional[Investigation]:
        rows = self._query("SELECT doc FROM investigations WHERE id=?", (iid,))
        return Investigation.from_dict(json.loads(rows[0]["doc"])) if rows else None

    def list_investigations(self, *, status: str = "", limit: int = 100) -> list[Investigation]:
        sql = "SELECT doc FROM investigations WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(500, limit)))
        return self._load(self._query(sql, params), Investigation.from_dict)

    def delete_investigation(self, iid: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM investigations WHERE id=?", (iid,))
            self._conn.execute("DELETE FROM evidence WHERE investigation_id=?", (iid,))
            self._conn.execute("DELETE FROM hypotheses WHERE investigation_id=?", (iid,))
            self._conn.execute("DELETE FROM notes WHERE investigation_id=?", (iid,))
            self._conn.commit()
            return cur.rowcount > 0

    # -- Evidence ---------------------------------------------------------- #
    def add_evidence(self, e: Evidence) -> Evidence:
        self._write(
            "INSERT OR REPLACE INTO evidence"
            "(id,investigation_id,kind,classification,lat,lng,occurred_at,created_at,doc) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (e.id, e.investigation_id, e.kind.value, e.classification.value, e.lat, e.lng,
             e.occurred_at, e.created_at, json.dumps(e.to_dict())),
        )
        return e

    def get_evidence(self, eid: str) -> Optional[Evidence]:
        rows = self._query("SELECT doc FROM evidence WHERE id=?", (eid,))
        return Evidence.from_dict(json.loads(rows[0]["doc"])) if rows else None

    def evidence_for_investigation(self, iid: str) -> list[Evidence]:
        rows = self._query(
            "SELECT doc FROM evidence WHERE investigation_id=? ORDER BY created_at DESC", (iid,)
        )
        return self._load(rows, Evidence.from_dict)

    def delete_evidence(self, eid: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM evidence WHERE id=?", (eid,))
            self._conn.commit()
            return cur.rowcount > 0

    # -- Hypothesis -------------------------------------------------------- #
    def upsert_hypothesis(self, h: Hypothesis) -> Hypothesis:
        h.updated_at = now_iso()
        self._write(
            "INSERT OR REPLACE INTO hypotheses(id,investigation_id,status,created_at,doc) "
            "VALUES(?,?,?,?,?)",
            (h.id, h.investigation_id, h.status.value, h.created_at, json.dumps(h.to_dict())),
        )
        return h

    def get_hypothesis(self, hid: str) -> Optional[Hypothesis]:
        rows = self._query("SELECT doc FROM hypotheses WHERE id=?", (hid,))
        return Hypothesis.from_dict(json.loads(rows[0]["doc"])) if rows else None

    def hypotheses_for_investigation(self, iid: str) -> list[Hypothesis]:
        rows = self._query(
            "SELECT doc FROM hypotheses WHERE investigation_id=? ORDER BY created_at DESC", (iid,)
        )
        return self._load(rows, Hypothesis.from_dict)

    # -- Note -------------------------------------------------------------- #
    def add_note(self, n: Note) -> Note:
        self._write(
            "INSERT OR REPLACE INTO notes(id,investigation_id,created_at,doc) VALUES(?,?,?,?)",
            (n.id, n.investigation_id, n.created_at, json.dumps(n.to_dict())),
        )
        return n

    def notes_for_investigation(self, iid: str) -> list[Note]:
        rows = self._query(
            "SELECT doc FROM notes WHERE investigation_id=? ORDER BY created_at DESC", (iid,)
        )
        return self._load(rows, Note.from_dict)

    # -- Alert ------------------------------------------------------------- #
    def upsert_alert(self, a: Alert) -> Alert:
        self._write(
            "INSERT OR REPLACE INTO alerts"
            "(id,type,status,severity,investigation_id,lat,lng,occurred_at,created_at,doc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (a.id, a.type, a.status.value, a.severity.value, a.investigation_id, a.lat, a.lng,
             a.occurred_at, a.created_at, json.dumps(a.to_dict())),
        )
        return a

    def get_alert(self, aid: str) -> Optional[Alert]:
        rows = self._query("SELECT doc FROM alerts WHERE id=?", (aid,))
        return Alert.from_dict(json.loads(rows[0]["doc"])) if rows else None

    def list_alerts(self, *, status: str = "", limit: int = 100) -> list[Alert]:
        sql = "SELECT doc FROM alerts WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(500, limit)))
        return self._load(self._query(sql, params), Alert.from_dict)

    # -- Audit ------------------------------------------------------------- #
    def audit(self, actor: str, action: str, *, tool: str = "", scope: str = "", detail: dict | None = None) -> None:
        self._write(
            "INSERT INTO audit_log(ts,actor,action,tool,scope,doc) VALUES(?,?,?,?,?,?)",
            (now_iso(), actor, action, tool, scope, json.dumps(detail or {})),
        )

    def recent_audit(self, limit: int = 100) -> list[dict]:
        rows = self._query(
            "SELECT ts,actor,action,tool,scope,doc FROM audit_log ORDER BY id DESC LIMIT ?",
            (max(1, min(1000, limit)),),
        )
        out = []
        for r in rows:
            out.append({
                "ts": r["ts"], "actor": r["actor"], "action": r["action"],
                "tool": r["tool"], "scope": r["scope"], "detail": json.loads(r["doc"]),
            })
        return out

    def stats(self) -> dict:
        tables = [
            "sources", "entities", "observations", "events", "relationships",
            "investigations", "evidence", "hypotheses", "notes", "alerts",
        ]
        out = {}
        for t in tables:
            rows = self._query(f"SELECT COUNT(*) AS n FROM {t}")
            out[t] = rows[0]["n"] if rows else 0
        return out


def _cos(deg: float) -> float:
    import math

    c = math.cos(math.radians(deg))
    return c if abs(c) > 1e-6 else 1e-6


# --------------------------------------------------------------------------- #
# Process-wide singleton
# --------------------------------------------------------------------------- #
_STORE: Optional[Store] = None
_STORE_LOCK = threading.Lock()


def _default_path() -> str:
    override = os.environ.get("INVESTIGATION_DB_PATH")
    if override:
        return override
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
    return os.path.join(here, "data", "investigations.db")


def get_store() -> Store:
    """Return the process-wide investigation store, creating it on first use."""
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = Store(_default_path())
    return _STORE


def configure_store(path: str) -> Store:
    """(Re)configure the singleton to a specific path. Mainly for tests/tools."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            try:
                _STORE.close()
            except Exception:
                pass
        _STORE = Store(path)
    return _STORE


def reset_store_for_tests() -> Store:
    """Point the singleton at a fresh in-memory database (test isolation)."""
    return configure_store(":memory:")
