"""Bounded, owner-scoped plugin data. No host persistence imports."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

TERMINAL = {"completed", "failed", "cancelled"}


def has_pending_jobs(team):
    return int(any(job["status"] not in TERMINAL for job in team["jobs"]))


class Store:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("storage_path must be an absolute deployment-owned path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connection()) as db, db:
            # Serialize schema discovery and backfill with concurrent writers.
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS teams (id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL, has_pending_jobs INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS team_artifact_versions (owner TEXT NOT NULL, team_id TEXT NOT NULL, version_id TEXT NOT NULL, content BLOB NOT NULL, PRIMARY KEY(team_id, version_id))")
            db.execute("CREATE INDEX IF NOT EXISTS team_artifact_owner ON team_artifact_versions(owner)")
            db.execute("CREATE TRIGGER IF NOT EXISTS team_artifacts_immutable BEFORE UPDATE ON team_artifact_versions BEGIN SELECT RAISE(ABORT, 'Artifact snapshots cannot be overwritten'); END")
            if "has_pending_jobs" not in {row[1] for row in db.execute("PRAGMA table_info(teams)")}:
                db.execute("ALTER TABLE teams ADD COLUMN has_pending_jobs INTEGER NOT NULL DEFAULT 0")
                rows = db.execute("SELECT id, data FROM teams").fetchall()
                for team_id, data in rows:
                    db.execute("UPDATE teams SET has_pending_jobs=? WHERE id=?", (has_pending_jobs(json.loads(data)), team_id))
            db.execute("CREATE INDEX IF NOT EXISTS teams_pending_jobs ON teams(has_pending_jobs) WHERE has_pending_jobs=1")

    def connection(self):
        return sqlite3.connect(self.path, timeout=5)

    def scheduling_snapshots(self):
        # Service-only, indexed projection. Completed history is never decoded;
        # all unfinished work is retained, regardless of capability availability.
        with closing(self.connection()) as db:
            return {(owner, team_id): json.loads(data) for owner, team_id, data in db.execute("SELECT owner, id, data FROM teams WHERE has_pending_jobs=1 ORDER BY rowid")}

    def list(self, owner):
        with closing(self.connection()) as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM teams WHERE owner=? ORDER BY rowid DESC", (owner,))]

    def get(self, owner, team_id):
        with closing(self.connection()) as db:
            row = db.execute("SELECT data FROM teams WHERE owner=? AND id=?", (owner, team_id)).fetchone()
            if not row:
                raise ValueError("Team unavailable")
            return json.loads(row[0])

    def create(self, owner, team):
        with closing(self.connection()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM teams WHERE owner=? AND id=?", (owner, team["id"])).fetchone()
            if row:
                return json.loads(row[0])
            if db.execute("SELECT count(*) FROM teams WHERE owner=?", (owner,)).fetchone()[0] >= 20:
                raise ValueError("Team limit reached (20)")
            db.execute("INSERT INTO teams (id, owner, data, has_pending_jobs) VALUES (?,?,?,?)", (team["id"], owner, json.dumps(team), has_pending_jobs(team)))
            return team

    def change(self, owner, team_id, update):
        with closing(self.connection()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM teams WHERE owner=? AND id=?", (owner, team_id)).fetchone()
            if not row:
                raise ValueError("Team unavailable")
            team = json.loads(row[0])
            result = update(team)
            db.execute("UPDATE teams SET data=?, has_pending_jobs=? WHERE owner=? AND id=?", (json.dumps(team), has_pending_jobs(team), owner, team_id))
            return result

    def delete(self, owner, team_id):
        with closing(self.connection()) as db, db:
            db.execute("DELETE FROM team_artifact_versions WHERE owner=? AND team_id=?", (owner, team_id))
            db.execute("DELETE FROM teams WHERE owner=? AND id=?", (owner, team_id))

    def capture_artifact(self, owner, team_id, version_id, content, run_id):
        from .artifacts import MAX_BYTES, OWNER_BYTES

        if not isinstance(content, bytes) or len(content) > MAX_BYTES:
            raise ValueError("Artifact must contain at most 2 MiB")
        with closing(self.connection()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM teams WHERE owner=? AND id=?", (owner, team_id)).fetchone()
            if row is None:
                raise ValueError("Team unavailable")
            team = json.loads(row[0])
            entry = next(entry for entry in team["artifacts"] if entry["id"] == version_id)
            if entry["status"] != "pending":
                return
            retained = db.execute("SELECT coalesce(sum(length(content)),0) FROM team_artifact_versions WHERE owner=?", (owner,)).fetchone()[0]
            if retained + len(content) > OWNER_BYTES:
                raise ValueError("Owner artifact storage limit reached (64 MiB)")
            db.execute("INSERT INTO team_artifact_versions VALUES (?,?,?,?)", (owner, team_id, version_id, content))
            entry.update(status="ready", sha256=hashlib.sha256(content).hexdigest(), size=len(content))
            entry["source"]["run_id"] = run_id
            db.execute("UPDATE teams SET data=? WHERE owner=? AND id=?", (json.dumps(team), owner, team_id))

    def artifact(self, owner, team_id, artifact_id, version):
        from .artifacts import lookup

        team = self.get(owner, team_id)
        entry = lookup(team, {"artifact_id": artifact_id, "version": version})
        if entry["status"] != "ready":
            raise ValueError("Artifact version is not ready")
        with closing(self.connection()) as db:
            row = db.execute("SELECT content FROM team_artifact_versions WHERE owner=? AND team_id=? AND version_id=?", (owner, team_id, entry["id"])).fetchone()
        if row is None or hashlib.sha256(row[0]).hexdigest() != entry["sha256"]:
            raise ValueError("Artifact snapshot unavailable")
        return entry, row[0]
