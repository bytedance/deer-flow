"""Owner-scoped versioned records and immutable snapshots; never store capabilities."""

import hashlib
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
    "recoverable",
}


class Store:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("storage_path must be absolute")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(owner,request_id))")
            columns = {row[1] for row in db.execute("PRAGMA table_info(workflows)")}
            if "revision" not in columns:
                db.execute("ALTER TABLE workflows ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
            db.execute("CREATE INDEX IF NOT EXISTS workflows_owner ON workflows(owner)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS workflow_artifacts (owner TEXT NOT NULL, workflow TEXT NOT NULL, step_id TEXT NOT NULL, version TEXT NOT NULL, "
                "info TEXT NOT NULL, content BLOB NOT NULL, PRIMARY KEY(owner,workflow,step_id), UNIQUE(owner,workflow,version))"
            )
            db.execute("CREATE TRIGGER IF NOT EXISTS workflow_artifacts_immutable BEFORE UPDATE ON workflow_artifacts BEGIN SELECT RAISE(ABORT, 'Artifact versions cannot be overwritten'); END")
            db.execute("CREATE TABLE IF NOT EXISTS workflow_definitions (owner TEXT NOT NULL, name TEXT NOT NULL, version TEXT NOT NULL, script TEXT NOT NULL, PRIMARY KEY(owner,name,version))")

    def capture_artifact(self, owner, workflow, step_id, name, content, *, execution_record=None):
        if not isinstance(content, bytes) or len(content) > 2 * 1024 * 1024:
            raise ValueError("Artifact limit is 2 MiB")
        digest = hashlib.sha256(content).hexdigest()
        version = hashlib.sha256(json.dumps([owner, workflow, step_id, digest]).encode()).hexdigest()
        info = {
            "kind": "file",
            "step_id": step_id,
            "attempt": 1,
            "name": name,
            "size": len(content),
            "sha256": digest,
            "version": version,
            "artifact_version": version,
            "status": "completed",
        }
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if execution_record is not None:
                self._lease(db, owner, execution_record)
            old = db.execute(
                "SELECT info FROM workflow_artifacts WHERE owner=? AND workflow=? AND step_id=?",
                (owner, workflow, step_id),
            ).fetchone()
            if old:
                if json.loads(old[0]) != info:
                    raise ValueError("Artifact capture step cannot be overwritten")
                return info
            if (
                db.execute(
                    "SELECT count(*) FROM workflow_artifacts WHERE owner=? AND workflow=?",
                    (owner, workflow),
                ).fetchone()[0]
                >= 16
            ):
                raise ValueError("Artifact count limit (16)")
            if (
                db.execute(
                    "SELECT coalesce(sum(length(content)),0) FROM workflow_artifacts WHERE owner=?",
                    (owner,),
                ).fetchone()[0]
                + len(content)
                > 64 * 1024 * 1024
            ):
                raise ValueError("Owner artifact limit (64 MiB)")
            db.execute(
                "INSERT INTO workflow_artifacts VALUES (?,?,?,?,?,?)",
                (owner, workflow, step_id, version, json.dumps(info), content),
            )
        return info

    def artifact_by_step(self, owner, workflow, step_id):
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT version FROM workflow_artifacts WHERE owner=? AND workflow=? AND step_id=?",
                (owner, workflow, step_id),
            ).fetchone()
        return self.artifact(owner, workflow, row[0])[0] if row else None

    def artifact(self, owner, workflow, version):
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT info,content FROM workflow_artifacts WHERE owner=? AND workflow=? AND version=?",
                (owner, workflow, version),
            ).fetchone()
            if not row:
                raise ValueError("Artifact unavailable")
            info, content = json.loads(row[0]), row[1]
            if hashlib.sha256(content).hexdigest() != info["sha256"] or len(content) != info["size"]:
                raise ValueError("Artifact integrity failure")
            return info, content

    def save_definition(self, owner, name, version, script):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT 1 FROM workflow_definitions WHERE owner=? AND name=? AND version=?",
                (owner, name, version),
            ).fetchone()
            if not existing:
                if (
                    db.execute(
                        "SELECT count(*) FROM workflow_definitions WHERE owner=?",
                        (owner,),
                    ).fetchone()[0]
                    >= 100
                ):
                    raise ValueError("Definition version limit (100)")
                db.execute(
                    "INSERT INTO workflow_definitions VALUES (?,?,?,?)",
                    (owner, name, version, script),
                )
        return {"name": name, "version": version}

    def definitions(self, owner):
        with closing(self.connect()) as db:
            return [
                {"name": name, "version": version}
                for name, version in db.execute(
                    "SELECT name,version FROM workflow_definitions WHERE owner=? ORDER BY rowid DESC",
                    (owner,),
                )
            ]

    def definition(self, owner, name, version):
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT script FROM workflow_definitions WHERE owner=? AND name=? AND version=?",
                (owner, name, version),
            ).fetchone()
            if not row:
                raise ValueError("Definition unavailable")
            return row[0]

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
                "INSERT INTO workflows (id,owner,request_id,fingerprint,status,data) VALUES (?,?,?,?,?,?)",
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
        revision = record.get("revision", 0)
        updated = {**record, "revision": revision + 1}
        raw = json.dumps(updated)
        if len(raw.encode()) > 8 * 1024 * 1024:
            raise ValueError("Workflow recovery journal limit (8 MiB)")
        with closing(self.connect()) as db, db:
            changed = db.execute(
                "UPDATE workflows SET status=?,data=?,revision=revision+1 WHERE owner=? AND id=? AND revision=?",
                (record["status"], raw, owner, record["id"], revision),
            ).rowcount
            if changed != 1:
                raise ValueError("Stale workflow revision")
        record["revision"] = revision + 1
        return revision + 1

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
            db.execute(
                "DELETE FROM workflow_artifacts WHERE owner=? AND workflow=?",
                (owner, run_id),
            )
            db.execute("DELETE FROM workflows WHERE owner=? AND id=?", (owner, run_id))

    def interrupt_unfinished(self):
        with closing(self.connect()) as db, db:
            for run_id, raw in db.execute("SELECT id,data FROM workflows WHERE status IN ('queued','running','cancelling','paused','waiting_approval')").fetchall():
                record = json.loads(raw)
                recoverable = record.get("recovery_version") == 1 and record["status"] != "cancelling"
                record.update(
                    status="recoverable" if recoverable else "interrupted",
                    error="Gateway restarted; sign in and recover, or inspect uncertain child outcomes." if recoverable else "Legacy or cancelled execution cannot resume; inspect child runs.",
                    revision=record.get("revision", 0) + 1,
                )
                db.execute(
                    "UPDATE workflows SET status=?,data=?,revision=revision+1 WHERE id=?",
                    (record["status"], json.dumps(record), run_id),
                )
