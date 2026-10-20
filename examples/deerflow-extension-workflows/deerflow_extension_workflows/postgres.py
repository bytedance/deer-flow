"""Shared authoritative workflow store; all decisions use the PostgreSQL clock.

The host migration owns extension_execution_leases. The workflow tables remain
extension-owned. Host run admission locks the same lease row in its transaction.
"""

import json
from contextlib import closing

from .constants import NAMESPACE
from .store import TERMINAL, Store

LOCK = 723461108


class LeaseLost(ValueError):
    """An execution generation no longer has authority to mutate state."""


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, args=()):
        if sql == "BEGIN IMMEDIATE":
            return self.raw.execute("SELECT 1")
        return self.raw.execute(sql.replace("?", "%s"), args)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        self.raw.rollback() if kind else self.raw.commit()

    def close(self):
        self.raw.close()


class PostgresStore(Store):
    def __init__(self, dsn, holder, config):
        self.dsn, self.holder, self.config = dsn, holder, config
        with closing(self.connect()) as db, db:
            # Fail closed until the host schema (including the admission fence)
            # is installed in this same database/search_path.
            db.execute("SELECT 1 FROM extension_execution_leases LIMIT 0")
            db.execute(
                "CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, "
                "revision BIGINT NOT NULL DEFAULT 0, rowid BIGINT GENERATED ALWAYS AS IDENTITY, UNIQUE(owner,request_id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS workflow_artifacts (owner TEXT NOT NULL, workflow TEXT NOT NULL, step_id TEXT NOT NULL, version TEXT NOT NULL, info TEXT NOT NULL, content BYTEA NOT NULL, "
                "PRIMARY KEY(owner,workflow,step_id), UNIQUE(owner,workflow,version))"
            )
            db.execute("CREATE OR REPLACE FUNCTION workflow_artifact_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Artifact versions cannot be overwritten'; END $$")
            db.execute("DROP TRIGGER IF EXISTS workflow_artifacts_immutable ON workflow_artifacts")
            db.execute("CREATE TRIGGER workflow_artifacts_immutable BEFORE UPDATE ON workflow_artifacts FOR EACH ROW EXECUTE FUNCTION workflow_artifact_immutable()")
            db.execute("CREATE TABLE IF NOT EXISTS workflow_definitions (owner TEXT NOT NULL, name TEXT NOT NULL, version TEXT NOT NULL, script TEXT NOT NULL, rowid BIGINT GENERATED ALWAYS AS IDENTITY, PRIMARY KEY(owner,name,version))")
            db.execute("CREATE TABLE IF NOT EXISTS workflow_controls (workflow TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(workflow,key))")
            db.execute("CREATE TABLE IF NOT EXISTS workflow_cluster_policy (id INTEGER PRIMARY KEY, policy TEXT NOT NULL)")
            policy = json.dumps({k: config[k] for k in ("global_concurrency", "max_workflows", "max_workflows_per_owner", "lease_seconds")}, sort_keys=True)
            db.execute("INSERT INTO workflow_cluster_policy VALUES (1,?) ON CONFLICT DO NOTHING", (policy,))
            if db.execute("SELECT policy FROM workflow_cluster_policy WHERE id=1").fetchone()[0] != policy:
                raise ValueError("Workflow cluster limits differ; coordinate the operator configuration before startup")
            db.execute("CREATE TABLE IF NOT EXISTS workflow_slots (workflow TEXT NOT NULL, step TEXT NOT NULL, PRIMARY KEY(workflow,step))")

    def connect(self, *, readonly=False):
        import psycopg

        raw = psycopg.connect(self.dsn, connect_timeout=5, client_encoding="utf8")
        try:
            if readonly:
                raw.execute("SET TRANSACTION READ ONLY")
            raw.execute("SET LOCAL lock_timeout = '5s'")
            raw.execute("SET LOCAL statement_timeout = '10s'")
            # Serializes budget counts and mutations across all replicas. No
            # host/Agent IO happens in this extension transaction.
            if not readonly:
                raw.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
            return Connection(raw)
        except BaseException:
            raw.close()
            raise

    def _lease(self, db, owner, record):
        row = db.execute("SELECT holder_id,epoch,expires_at FROM extension_execution_leases WHERE namespace=? AND resource_id=? AND user_id=? FOR UPDATE", (NAMESPACE, record["id"], owner)).fetchone()
        now = float(db.execute("SELECT extract(epoch from clock_timestamp())").fetchone()[0])
        if not row or row[0] != self.holder or row[1] != record.get("execution_epoch") or row[2] <= now:
            raise LeaseLost("Workflow execution lease lost")
        return now

    def _capacity(self, db, owner, exclude=""):
        active = db.execute("SELECT owner FROM workflows WHERE status NOT IN ('completed','failed','cancelled','waiting_input','interrupted','needs_reconciliation','recoverable') AND id<>?", (exclude,)).fetchall()
        if len(active) >= self.config["max_workflows"] or sum(r[0] == owner for r in active) >= self.config["max_workflows_per_owner"]:
            raise ValueError("Active workflow limit")

    def _claim(self, db, owner, record):
        row = db.execute("SELECT epoch,expires_at FROM extension_execution_leases WHERE namespace=? AND resource_id=? FOR UPDATE", (NAMESPACE, record["id"])).fetchone()
        now = float(db.execute("SELECT extract(epoch from clock_timestamp())").fetchone()[0])
        if row and row[1] > now:
            raise ValueError("Workflow owned by a live Gateway")
        epoch = row[0] + 1 if row else 1
        db.execute(
            "INSERT INTO extension_execution_leases(namespace,resource_id,user_id,holder_id,epoch,expires_at) VALUES (?,?,?,?,?,?) ON CONFLICT(namespace,resource_id) DO UPDATE SET "
            "holder_id=excluded.holder_id,epoch=excluded.epoch,expires_at=excluded.expires_at",
            (NAMESPACE, record["id"], owner, self.holder, epoch, now + self.config["lease_seconds"]),
        )
        record["execution_epoch"] = epoch

    def create(self, owner, record):
        with closing(self.connect()) as db, db:
            old = db.execute("SELECT fingerprint,data FROM workflows WHERE owner=? AND request_id=?", (owner, record["request_id"])).fetchone()
            if old:
                if old[0] != record["fingerprint"]:
                    raise ValueError("request_id already used with different script or arguments")
                return json.loads(old[1]), False
            self._capacity(db, owner)
            if db.execute("SELECT count(*) FROM workflows WHERE owner=?", (owner,)).fetchone()[0] >= 100:
                raise ValueError("Retained workflow limit (100); delete finished records")
            self._claim(db, owner, record)
            db.execute("INSERT INTO workflows(id,owner,request_id,fingerprint,status,data) VALUES (?,?,?,?,?,?)", (record["id"], owner, record["request_id"], record["fingerprint"], record["status"], json.dumps(record)))
            return record, True

    def claim(self, owner, run_id, *, for_cancel=False):
        with closing(self.connect()) as db, db:
            row = db.execute("SELECT data FROM workflows WHERE owner=? AND id=?", (owner, run_id)).fetchone()
            if not row:
                raise ValueError("Workflow unavailable")
            record = json.loads(row[0])
            if record["status"] in TERMINAL - {"recoverable"}:
                raise ValueError("Workflow is not recoverable")
            if not for_cancel and (record["status"] == "cancelling" or db.execute("SELECT 1 FROM workflow_controls WHERE workflow=? AND key='cancel'", (run_id,)).fetchone()):
                raise ValueError("Cancellation pending; cancel this workflow instead of recovering it")
            if not for_cancel:
                self._capacity(db, owner, run_id)
            self._claim(db, owner, record)
            record.update(status="cancelling" if for_cancel else "queued", revision=record.get("revision", 0) + 1)
            db.execute("UPDATE workflows SET status=?,data=?,revision=? WHERE id=?", (record["status"], json.dumps(record), record["revision"], run_id))
            return record

    def put(self, owner, record):
        revision = record.get("revision", 0)
        updated = {**record, "revision": revision + 1}
        raw = json.dumps(updated)
        if len(raw.encode()) > 8 * 1024 * 1024:
            raise ValueError("Workflow recovery journal limit (8 MiB)")
        with closing(self.connect()) as db, db:
            self._lease(db, owner, record)
            if db.execute("UPDATE workflows SET status=?,data=?,revision=revision+1 WHERE owner=? AND id=? AND revision=?", (record["status"], raw, owner, record["id"], revision)).rowcount != 1:
                raise ValueError("Stale workflow revision")
            if record["status"] in TERMINAL:
                db.execute("UPDATE extension_execution_leases SET expires_at=0 WHERE namespace=? AND resource_id=?", (NAMESPACE, record["id"]))
        record["revision"] = revision + 1
        return revision + 1

    def heartbeat(self, owner, record):
        with closing(self.connect()) as db, db:
            now = self._lease(db, owner, record)
            db.execute("UPDATE extension_execution_leases SET expires_at=? WHERE namespace=? AND resource_id=?", (now + self.config["lease_seconds"], NAMESPACE, record["id"]))
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM workflow_controls WHERE workflow=?", (record["id"],))]

    def command(self, owner, run_id, key, command, revision):
        with closing(self.connect()) as db, db:
            row = db.execute("SELECT revision,data FROM workflows WHERE owner=? AND id=?", (owner, run_id)).fetchone()
            if not row or row[0] != revision:
                raise ValueError("Workflow changed; reload and retry")
            record = json.loads(row[1])
            now = float(db.execute("SELECT extract(epoch from clock_timestamp())").fetchone()[0])
            if command["kind"] != "cancel" and (record.get("pause_expires_at", 0) <= now or record["status"] not in ("paused", "waiting_approval")):
                raise ValueError("Checkpoint expired or unavailable")
            old = db.execute("SELECT data FROM workflow_controls WHERE workflow=? AND key=?", (run_id, key)).fetchone()
            raw = json.dumps(command, sort_keys=True)
            if old and {k: v for k, v in json.loads(old[0]).items() if k != "decided_at"} != command:
                raise ValueError("Checkpoint already decided")
            command = {**command, "decided_at": float(db.execute("SELECT extract(epoch from clock_timestamp())").fetchone()[0])}
            raw = json.dumps(command, sort_keys=True)
            db.execute("INSERT INTO workflow_controls VALUES (?,?,?) ON CONFLICT DO NOTHING", (run_id, key, raw))

    def reserve_slot(self, owner, record, step):
        with closing(self.connect()) as db, db:
            self._lease(db, owner, record)
            if db.execute("SELECT 1 FROM workflow_slots WHERE workflow=? AND step=?", (record["id"], step)).fetchone():
                return True
            if db.execute("SELECT count(*) FROM workflow_slots").fetchone()[0] >= self.config["global_concurrency"]:
                return False
            db.execute("INSERT INTO workflow_slots VALUES (?,?)", (record["id"], step))
            return True

    def release_slot(self, owner, record, step):
        with closing(self.connect()) as db, db:
            self._lease(db, owner, record)
            db.execute("DELETE FROM workflow_slots WHERE workflow=? AND step=?", (record["id"], step))

    def save_definition(self, owner, name, version, script):
        # Explicit columns: PostgreSQL also stores an ordering identity.
        with closing(self.connect()) as db, db:
            existing = db.execute("SELECT 1 FROM workflow_definitions WHERE owner=? AND name=? AND version=?", (owner, name, version)).fetchone()
            if not existing and db.execute("SELECT count(*) FROM workflow_definitions WHERE owner=?", (owner,)).fetchone()[0] >= 100:
                raise ValueError("Definition version limit (100)")
            db.execute("INSERT INTO workflow_definitions(owner,name,version,script) VALUES (?,?,?,?) ON CONFLICT DO NOTHING", (owner, name, version, script))
        return {"name": name, "version": version}

    @staticmethod
    def _project(row):
        record = json.loads(row[0])
        if record["status"] not in TERMINAL and not row[1]:
            record["status"] = "recoverable"
            record["error"] = "Execution owner unavailable; sign in to recover or cancel pending cleanup"
        return record

    def get(self, owner, run_id):
        with closing(self.connect(readonly=True)) as db:
            row = db.execute(
                "SELECT w.data,l.expires_at > extract(epoch from clock_timestamp()) FROM workflows w LEFT JOIN extension_execution_leases l "
                "ON l.namespace=? AND l.resource_id=w.id AND l.user_id=w.owner WHERE w.owner=? AND w.id=?",
                (NAMESPACE, owner, run_id),
            ).fetchone()
            if not row:
                raise ValueError("Workflow unavailable")
            return self._project(row)

    def list(self, owner):
        with closing(self.connect(readonly=True)) as db:
            rows = db.execute(
                "SELECT w.data,l.expires_at > extract(epoch from clock_timestamp()) FROM workflows w LEFT JOIN extension_execution_leases l "
                "ON l.namespace=? AND l.resource_id=w.id AND l.user_id=w.owner WHERE w.owner=? ORDER BY w.rowid DESC LIMIT 20",
                (NAMESPACE, owner),
            ).fetchall()
            return [self._project(row) for row in rows]

    def delete(self, owner, run_id):
        with closing(self.connect()) as db, db:
            row = db.execute("SELECT status FROM workflows WHERE owner=? AND id=?", (owner, run_id)).fetchone()
            if not row or row[0] not in TERMINAL:
                raise ValueError("Only finished workflow records can be deleted")
            lease = db.execute("SELECT expires_at > extract(epoch from clock_timestamp()) FROM extension_execution_leases WHERE namespace=? AND resource_id=? FOR UPDATE", (NAMESPACE, run_id)).fetchone()
            if lease and lease[0]:
                raise ValueError("Workflow still has an execution owner")
            if db.execute("SELECT 1 FROM workflow_slots WHERE workflow=?", (run_id,)).fetchone():
                raise ValueError("Reconcile retained child reservations before deleting")
            db.execute("DELETE FROM workflow_artifacts WHERE owner=? AND workflow=?", (owner, run_id))
            db.execute("DELETE FROM workflow_controls WHERE workflow=?", (run_id,))
            db.execute("DELETE FROM workflows WHERE owner=? AND id=?", (owner, run_id))
            # Keep the lease generation tombstone: deletion never resets fencing.

    def database_identity(self):
        with closing(self.connect(readonly=True)) as db:
            return tuple(db.execute("SELECT current_database(),current_schema(),inet_server_addr()::text,inet_server_port()").fetchone())
