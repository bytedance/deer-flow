"""Plugin-owned PostgreSQL storage bound to its single service owner session."""

import hashlib
import json
import re
from contextlib import contextmanager
from threading import RLock
from urllib.parse import urlsplit

from .store import StoreUnavailable, has_pending_jobs


class PostgresStore:
    def __init__(self, url, schema="agent_teams"):
        try:
            valid_url = isinstance(url, str) and urlsplit(url).scheme in {
                "postgresql",
                "postgres",
            }
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError("storage_url must be a PostgreSQL connection URL")
        if not isinstance(schema, str) or not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]{0,62}", schema) or schema.lower() in {"public", "information_schema"} or schema.lower().startswith("pg_"):
            raise ValueError("storage_schema must name a dedicated PostgreSQL schema (1–63 identifier characters)")
        self._url = url
        self.schema = schema
        # PostgreSQL advisory keys are database-local. Mask the sign bit so the
        # same positive bigint can also be inspected through pg_locks.
        self.lock_key = int.from_bytes(
            hashlib.sha256(("deerflow.agent-teams.service\0" + schema).encode()).digest()[:8],
            "big",
        ) & ((1 << 63) - 1)
        self._mutex = RLock()
        self._connection = None

    def acquire_service_lock(self):
        try:
            import psycopg
            from psycopg import sql
        except ImportError:
            raise StoreUnavailable("Install deerflow-extension-agent-teams[postgres] to use PostgreSQL storage") from None
        with self._mutex:
            if self._connection is not None:
                raise StoreUnavailable("This team store already has an active service")
            db = None
            try:
                db = psycopg.connect(
                    self._url,
                    autocommit=True,
                    connect_timeout=5,
                    keepalives=1,
                    keepalives_idle=5,
                    keepalives_interval=1,
                    keepalives_count=3,
                )
                db.execute("SET statement_timeout = '5s'")
                db.execute("SET lock_timeout = '5s'")
                if not db.execute("SELECT pg_try_advisory_lock(%s)", (self.lock_key,)).fetchone()[0]:
                    raise StoreUnavailable("Another team service is active for this PostgreSQL store")
                with db.transaction():
                    db.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                    db.execute(sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(self.schema)))
                    db.execute("CREATE TABLE IF NOT EXISTS teams (id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL, has_pending_jobs INTEGER NOT NULL DEFAULT 0, position BIGINT GENERATED ALWAYS AS IDENTITY)")
                    db.execute("CREATE INDEX IF NOT EXISTS teams_pending_jobs ON teams(has_pending_jobs) WHERE has_pending_jobs=1")
                    db.execute("CREATE TABLE IF NOT EXISTS team_artifact_versions (owner TEXT NOT NULL, team_id TEXT NOT NULL, version_id TEXT NOT NULL, content BYTEA NOT NULL, PRIMARY KEY(team_id, version_id))")
                    db.execute("CREATE INDEX IF NOT EXISTS team_artifact_owner ON team_artifact_versions(owner)")
                    db.execute("CREATE OR REPLACE FUNCTION reject_artifact_update() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Artifact snapshots cannot be overwritten'; END $$")
                    db.execute("DROP TRIGGER IF EXISTS team_artifacts_immutable ON team_artifact_versions")
                    db.execute("CREATE TRIGGER team_artifacts_immutable BEFORE UPDATE ON team_artifact_versions FOR EACH ROW EXECUTE FUNCTION reject_artifact_update()")
                self._connection = db
            except BaseException as error:
                if db is not None:
                    db.close()
                if isinstance(error, psycopg.Error):
                    raise StoreUnavailable("PostgreSQL team store startup failed; check connectivity and schema permissions") from None
                raise
        return self

    def close(self):
        with self._mutex:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    @contextmanager
    def _transaction(self):
        # Every operation uses the ownership connection. Serializing complete
        # transactions also keeps owner-wide count/byte checks atomic across teams.
        with self._mutex:
            db = self._connection
            if db is None or db.closed:
                raise StoreUnavailable("PostgreSQL team store unavailable; restart the Gateway")
            import psycopg

            try:
                with db.transaction():
                    owned = db.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() AND classid=%s AND objid=%s AND objsubid=1 AND granted)",
                        (self.lock_key >> 32, self.lock_key & 0xFFFFFFFF),
                    ).fetchone()[0]
                    if not owned:
                        raise StoreUnavailable("PostgreSQL team store ownership lost; restart the Gateway")
                    yield db
            except (psycopg.Error, StoreUnavailable):
                self.close()
                raise StoreUnavailable("PostgreSQL team store unavailable; restart the Gateway") from None

    def check_service_lock(self):
        with self._transaction():
            pass

    def scheduling_snapshots(self):
        with self._transaction() as db:
            return {(owner, team_id): json.loads(data) for owner, team_id, data in db.execute("SELECT owner, id, data FROM teams WHERE has_pending_jobs=1 ORDER BY position")}

    def list(self, owner):
        with self._transaction() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT data FROM teams WHERE owner=%s ORDER BY position DESC",
                    (owner,),
                )
            ]

    def get(self, owner, team_id):
        with self._transaction() as db:
            row = db.execute("SELECT data FROM teams WHERE owner=%s AND id=%s", (owner, team_id)).fetchone()
            if row is None:
                raise ValueError("Team unavailable")
            return json.loads(row[0])

    def create(self, owner, team):
        with self._transaction() as db:
            row = db.execute("SELECT data FROM teams WHERE owner=%s AND id=%s", (owner, team["id"])).fetchone()
            if row:
                return json.loads(row[0])
            if db.execute("SELECT count(*) FROM teams WHERE owner=%s", (owner,)).fetchone()[0] >= 20:
                raise ValueError("Team limit reached (20)")
            db.execute(
                "INSERT INTO teams (id, owner, data, has_pending_jobs) VALUES (%s,%s,%s,%s)",
                (team["id"], owner, json.dumps(team), has_pending_jobs(team)),
            )
            return team

    def change(self, owner, team_id, update):
        with self._transaction() as db:
            row = db.execute(
                "SELECT data FROM teams WHERE owner=%s AND id=%s FOR UPDATE",
                (owner, team_id),
            ).fetchone()
            if row is None:
                raise ValueError("Team unavailable")
            team = json.loads(row[0])
            result = update(team)
            db.execute(
                "UPDATE teams SET data=%s, has_pending_jobs=%s WHERE owner=%s AND id=%s",
                (json.dumps(team), has_pending_jobs(team), owner, team_id),
            )
            return result

    def delete(self, owner, team_id):
        with self._transaction() as db:
            db.execute(
                "DELETE FROM team_artifact_versions WHERE owner=%s AND team_id=%s",
                (owner, team_id),
            )
            db.execute("DELETE FROM teams WHERE owner=%s AND id=%s", (owner, team_id))

    def capture_artifact(self, owner, team_id, version_id, content, run_id):
        from .artifacts import MAX_BYTES, OWNER_BYTES

        if not isinstance(content, bytes) or len(content) > MAX_BYTES:
            raise ValueError("Artifact must contain at most 2 MiB")
        with self._transaction() as db:
            row = db.execute(
                "SELECT data FROM teams WHERE owner=%s AND id=%s FOR UPDATE",
                (owner, team_id),
            ).fetchone()
            if row is None:
                raise ValueError("Team unavailable")
            team = json.loads(row[0])
            entry = next(entry for entry in team["artifacts"] if entry["id"] == version_id)
            if entry["status"] != "pending":
                return
            retained = db.execute(
                "SELECT coalesce(sum(octet_length(content)),0) FROM team_artifact_versions WHERE owner=%s",
                (owner,),
            ).fetchone()[0]
            if retained + len(content) > OWNER_BYTES:
                raise ValueError("Owner artifact storage limit reached (64 MiB)")
            db.execute(
                "INSERT INTO team_artifact_versions VALUES (%s,%s,%s,%s)",
                (owner, team_id, version_id, content),
            )
            entry.update(
                status="ready",
                sha256=hashlib.sha256(content).hexdigest(),
                size=len(content),
            )
            entry["source"]["run_id"] = run_id
            db.execute(
                "UPDATE teams SET data=%s WHERE owner=%s AND id=%s",
                (json.dumps(team), owner, team_id),
            )

    def artifact(self, owner, team_id, artifact_id, version):
        from .artifacts import lookup

        with self._transaction() as db:
            row = db.execute("SELECT data FROM teams WHERE owner=%s AND id=%s", (owner, team_id)).fetchone()
            if row is None:
                raise ValueError("Team unavailable")
            entry = lookup(json.loads(row[0]), {"artifact_id": artifact_id, "version": version})
            if entry["status"] != "ready":
                raise ValueError("Artifact version is not ready")
            row = db.execute(
                "SELECT content FROM team_artifact_versions WHERE owner=%s AND team_id=%s AND version_id=%s",
                (owner, team_id, entry["id"]),
            ).fetchone()
            if row is None or hashlib.sha256(row[0]).hexdigest() != entry["sha256"]:
                raise ValueError("Artifact snapshot unavailable")
            return entry, row[0]
