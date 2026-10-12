"""Bounded, owner-scoped plugin data. No host persistence imports."""

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
            db.execute("DELETE FROM teams WHERE owner=? AND id=?", (owner, team_id))
