"""Owner-scoped, retained records; no capability serialization or automatic replay."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

TERMINAL = {
    "completed",
    "failed",
    "cancelled",
    "waiting_input",
    "interrupted",
    "needs_reconciliation",
}


class Store:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("storage_path must be absolute")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(owner,request_id))")
            db.execute("CREATE INDEX IF NOT EXISTS workflows_owner ON workflows(owner)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def create(self, owner, record):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT fingerprint,data FROM workflows WHERE owner=? AND request_id=?",
                (owner, record["request_id"]),
            ).fetchone()
            if old:
                if old[0] != record["fingerprint"]:
                    raise ValueError("request_id already used with different script or arguments")
                return json.loads(old[1]), False
            if db.execute("SELECT count(*) FROM workflows WHERE owner=?", (owner,)).fetchone()[0] >= 100:
                raise ValueError("Retained workflow limit (100); delete finished records")
            db.execute(
                "INSERT INTO workflows VALUES (?,?,?,?,?,?)",
                (
                    record["id"],
                    owner,
                    record["request_id"],
                    record["fingerprint"],
                    record["status"],
                    json.dumps(record),
                ),
            )
            return record, True

    def put(self, owner, record):
        with closing(self.connect()) as db, db:
            db.execute(
                "UPDATE workflows SET status=?,data=? WHERE owner=? AND id=?",
                (record["status"], json.dumps(record), owner, record["id"]),
            )

    def get(self, owner, run_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT data FROM workflows WHERE owner=? AND id=?", (owner, run_id)).fetchone()
            if not row:
                raise ValueError("Workflow unavailable")
            return json.loads(row[0])

    def by_request(self, owner, request_id):
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT data FROM workflows WHERE owner=? AND request_id=?",
                (owner, request_id),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def list(self, owner):
        with closing(self.connect()) as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT data FROM workflows WHERE owner=? ORDER BY rowid DESC LIMIT 20",
                    (owner,),
                )
            ]

    def delete(self, owner, run_id):
        with closing(self.connect()) as db, db:
            row = db.execute("SELECT status FROM workflows WHERE owner=? AND id=?", (owner, run_id)).fetchone()
            if not row or row[0] not in TERMINAL:
                raise ValueError("Only finished workflow records can be deleted")
            db.execute("DELETE FROM workflows WHERE owner=? AND id=?", (owner, run_id))

    def interrupt_unfinished(self):
        with closing(self.connect()) as db, db:
            for run_id, raw in db.execute("SELECT id,data FROM workflows WHERE status IN ('queued','running','cancelling')").fetchall():
                record = json.loads(raw)
                record.update(
                    status="interrupted",
                    error="Gateway restarted; execution cannot resume. Inspect child runs before starting new work.",
                )
                db.execute(
                    "UPDATE workflows SET status=?,data=? WHERE id=?",
                    (record["status"], json.dumps(record), run_id),
                )
