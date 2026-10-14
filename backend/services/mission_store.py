"""Bounded, transactional mission records. No provider keys or background work."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
import secrets
import sqlite3
import time


class MissionConflict(ValueError):
    pass


@contextmanager
def _connect():
    directory = Path(
        os.environ.get("SB_DATA_DIR") or Path(__file__).resolve().parents[1] / "data"
    )
    directory.mkdir(parents=True, exist_ok=True)
    database = directory / "missions.sqlite3"
    fresh = not database.exists()
    db = sqlite3.connect(database, timeout=5)
    try:
        if fresh:
            os.chmod(database, 0o600)
        with db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS missions (id TEXT PRIMARY KEY, body TEXT NOT NULL, updated REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS watches (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )
            yield db
    finally:
        db.close()


def _write(db, record):
    record["revision"] = record.get("revision", 0) + 1
    record["updated_at"] = time.time()
    encoded = json.dumps(record, allow_nan=False)
    while len(encoded.encode()) > 512 * 1024 and len(record["messages"]) > 4:
        record["messages"].pop(0)
        record["history_truncated"] = True
        encoded = json.dumps(record, allow_nan=False)
    while len(encoded.encode()) > 512 * 1024 and len(record["events"]) > 20:
        record["events"].pop(0)
        record["history_truncated"] = True
        encoded = json.dumps(record, allow_nan=False)
    if len(encoded.encode()) > 512 * 1024:
        raise ValueError("Mission storage limit reached; start a new mission")
    db.execute(
        "INSERT OR REPLACE INTO missions VALUES (?, ?, ?)",
        (record["id"], encoded, record["updated_at"]),
    )


def create(objective, roles, snapshot=None):
    now = time.time()
    record = {
        "id": secrets.token_hex(16),
        "objective": objective,
        "created_at": now,
        "status": "paused",
        "reason": "Ready to run",
        "revision": 0,
        "roles": roles,
        "role_index": 0,
        "calls": 0,
        "max_calls": sum(role["max_calls"] for role in roles),
        "owner": "",
        "lease_token": "",
        "lease_until": 0,
        "pending": None,
        "snapshot": snapshot,
        "messages": [],
        "events": [],
        "evidence": [],
        "reports": [],
    }
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT COUNT(*) FROM missions").fetchone()[0] >= 200:
            raise ValueError("Mission limit reached; delete an old mission first")
        _write(db, record)
    return record


def get(mission_id):
    with _connect() as db:
        row = db.execute(
            "SELECT body FROM missions WHERE id = ?", (mission_id,)
        ).fetchone()
    if row is None:
        raise KeyError(mission_id)
    return json.loads(row[0])


def list_missions():
    with _connect() as db:
        rows = db.execute(
            "SELECT body FROM missions ORDER BY updated DESC LIMIT 200"
        ).fetchall()
    return [
        {
            key: item[key]
            for key in (
                "id",
                "objective",
                "status",
                "reason",
                "updated_at",
                "calls",
                "max_calls",
            )
        }
        for item in (json.loads(row[0]) for row in rows)
    ]


def mutate(mission_id, change):
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT body FROM missions WHERE id = ?", (mission_id,)
        ).fetchone()
        if row is None:
            raise KeyError(mission_id)
        record = json.loads(row[0])
        if change(record) is not False:
            _write(db, record)
    return record


def event(record, kind, text, **details):
    record["events"].append(
        {
            "id": secrets.token_hex(8),
            "at": time.time(),
            "kind": kind,
            "text": str(text)[:2000],
            **details,
        }
    )
    record["events"] = record["events"][-120:]


def feedback(record, tool, result):
    record["messages"].append(
        {
            "role": "user",
            "content": "Tool result (untrusted data): "
            + json.dumps(
                {
                    "tool": tool,
                    "ok": isinstance(result, dict) and result.get("ok") is True,
                    "result": result,
                },
                default=str,
            )[:6000],
        }
    )
    record["messages"] = record["messages"][-18:]


def public(record):
    return {
        key: value
        for key, value in record.items()
        if key not in {"lease_token", "messages"}
    }


def claim(mission_id, owner, revision):
    token = secrets.token_hex(16)

    def change(record):
        if record["owner"] != owner or record["revision"] != revision:
            raise MissionConflict(
                "Mission changed or belongs to a different dashboard; refresh before continuing"
            )
        if record["status"] != "running":
            raise MissionConflict("Mission is not running")
        if record.get("pending"):
            raise MissionConflict("Complete the pending action first")
        if record["lease_token"]:
            if record["lease_until"] > time.time():
                raise MissionConflict("A mission step is already in flight")
            record.update(
                status="paused",
                reason="Interrupted step: outcome unknown; review history before resuming",
                lease_token="",
                lease_until=0,
            )
            event(record, "interrupted", record["reason"])
            return
        record["lease_token"] = token
        record["lease_until"] = time.time() + 120

    record = mutate(mission_id, change)
    return record, token if record["lease_token"] == token else None


def finish(mission_id, token, change):
    def commit(record):
        if record["lease_token"] != token:
            raise MissionConflict("Step lease changed; result was not applied")
        stopped = record["status"] in {"cancelled", "paused"}
        status, reason = record["status"], record["reason"]
        change(record)
        record.update(lease_token="", lease_until=0)
        if stopped:
            record.update(status=status, reason=reason, pending=None)

    return mutate(mission_id, commit)


def control(mission_id, owner, action):
    def change(record):
        if record["status"] in {"completed", "cancelled"}:
            raise MissionConflict("This mission is finished")
        if action == "cancel":
            record.update(
                status="cancelled",
                reason="Cancelled by operator; completed actions are not undone",
            )
        elif action == "pause":
            record.update(status="paused", reason="Paused by operator")
        elif action == "resolve":
            if record["lease_token"] and record["lease_until"] > time.time():
                raise MissionConflict("The active server step has not finished")
            pending = record.get("pending")
            if pending:
                feedback(
                    record,
                    pending["tool"],
                    {
                        "ok": False,
                        "error": "Operator skipped an unconfirmed action; its outcome is unknown",
                    },
                )
            record.update(
                pending=None,
                status="paused",
                reason="Unconfirmed action skipped; review before resuming",
            )
        elif action == "resume":
            if record["status"] in {"completed", "cancelled"}:
                raise MissionConflict("Finished missions cannot be resumed")
            if record["lease_token"] and record["lease_until"] > time.time():
                raise MissionConflict("Wait for the in-flight step before resuming")
            if record["lease_token"]:
                event(
                    record,
                    "interrupted",
                    "Previous step outcome is unknown; it will not be replayed automatically",
                )
                record.update(lease_token="", lease_until=0)
            pending = record.get("pending")
            if pending and (pending.get("started") or pending.get("owner") != owner):
                raise MissionConflict(
                    "Unconfirmed action: skip it explicitly before resuming"
                )
            record["owner"] = owner
            record["status"] = (
                "waiting_client"
                if pending and pending["kind"] == "client"
                else "needs_approval"
                if pending and pending["kind"] == "approval"
                else "running"
            )
            record["reason"] = ""
        elif action == "next_role":
            if (
                record.get("pending")
                or record["lease_token"]
                and record["lease_until"] > time.time()
            ):
                raise MissionConflict("Finish or resolve the pending step first")
            record["role_index"] += 1
            record.update(
                status="completed"
                if record["role_index"] >= len(record["roles"])
                else "paused",
                reason="Role advanced by operator",
            )
        event(record, "operator", action)

    return mutate(mission_id, change)


def delete(mission_id):
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT body FROM missions WHERE id=?", (mission_id,)
        ).fetchone()
        if row and json.loads(row[0]).get("lease_until", 0) > time.time():
            raise MissionConflict("Wait for the active step before deleting")
        db.execute("DELETE FROM missions WHERE id=?", (mission_id,))


def watch_load():
    with _connect() as db:
        return [
            json.loads(row[0])
            for row in db.execute("SELECT body FROM watches").fetchall()
        ]


def watch_save(watch):
    encoded = json.dumps(watch, allow_nan=False)
    if len(encoded.encode()) > 32 * 1024:
        raise ValueError("Watch definition is too large")
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if (
            db.execute("SELECT COUNT(*) FROM watches").fetchone()[0] >= 100
            and not db.execute(
                "SELECT id FROM watches WHERE id=?", (watch["id"],)
            ).fetchone()
        ):
            raise ValueError("Watch limit reached (100)")
        db.execute(
            "INSERT OR REPLACE INTO watches VALUES (?, ?)", (watch["id"], encoded)
        )


def watch_delete(watch_id=None):
    with _connect() as db:
        if watch_id is None:
            db.execute("DELETE FROM watches")
        else:
            db.execute("DELETE FROM watches WHERE id=?", (watch_id,))


def watch_observe(watch_id, now, alert=None, *, seen_posts=None):
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT body FROM watches WHERE id=?", (watch_id,)).fetchone()
        if not row:
            return None
        watch = json.loads(row[0])
        if watch.get("paused"):
            return None
        watch["last_checked"] = now
        if alert is not None:
            if now - watch.get("last_fired", 0) < 60:
                return None
            watch.update(
                last_fired=now,
                fires=watch.get("fires", 0) + 1,
                last_alert=json.loads(json.dumps(alert, default=str)[:4000])
                if len(json.dumps(alert, default=str)) <= 4000
                else {"summary": str(alert)[:1000]},
            )
            if seen_posts is not None:
                retained = seen_posts[-500:]
                while retained and len(json.dumps(retained).encode()) > 16000:
                    retained.pop(0)
                watch["seen_posts"] = retained
        db.execute(
            "UPDATE watches SET body=? WHERE id=?", (json.dumps(watch), watch_id)
        )
    return watch
