"""Bounded, owner-scoped plugin data. No host persistence imports."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("storage_path must be an absolute deployment-owned path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connection()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS teams (id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL)")

    def connection(self):
        return sqlite3.connect(self.path, timeout=5)

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
            db.execute("INSERT INTO teams VALUES (?,?,?)", (team["id"], owner, json.dumps(team)))
            return team

    def change(self, owner, team_id, update):
        with closing(self.connection()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM teams WHERE owner=? AND id=?", (owner, team_id)).fetchone()
            if not row:
                raise ValueError("Team unavailable")
            team = json.loads(row[0])
            result = update(team)
            db.execute("UPDATE teams SET data=? WHERE owner=? AND id=?", (json.dumps(team), owner, team_id))
            return result

    def delete(self, owner, team_id):
        with closing(self.connection()) as db, db:
            db.execute("DELETE FROM teams WHERE owner=? AND id=?", (owner, team_id))
