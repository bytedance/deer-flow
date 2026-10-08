"""One durable, transactionally serialized B/C resource ledger."""

import time
import uuid
from contextlib import contextmanager

from sqlalchemy import JSON, Column, MetaData, String, Table, func, select, text, update

from ecs_executor.job_store import _JOBS

_METADATA = MetaData()
_NODES = Table("ecs_execution_nodes", _METADATA, Column("id", String(64), primary_key=True), Column("record", JSON, nullable=False))
_FIELDS = {"state", "start_intent", "started_at", "error", "exit_code", "artifact", "native_artifact_uri", "cleanup_pending", "physical_stopped"}


class Scheduling:
    def __init__(self, store, *, nodes, lease_seconds=120):
        if not nodes or lease_seconds < 120:
            raise ValueError("A fixed pool and at least 120 seconds of lease/cleanup safety are required")
        self.store, self.nodes, self.lease_seconds = store, nodes, lease_seconds
        _METADATA.create_all(store.engine)
        with self.transaction() as connection:
            for node_id, node in nodes.items():
                old = connection.execute(select(_NODES.c.record).where(_NODES.c.id == node_id)).scalar_one_or_none()
                record = {"config": node.model_dump(mode="json"), "heartbeat_at": (old or {}).get("heartbeat_at", 0)}
                if old is None:
                    connection.execute(_NODES.insert().values(id=node_id, record=record))
                else:
                    connection.execute(update(_NODES).where(_NODES.c.id == node_id).values(record=record))

    @contextmanager
    def transaction(self):
        with self.store.engine.connect() as connection:
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
                connection.execute(text("SELECT pg_advisory_xact_lock(731908241)"))
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def eligible(self, node_id, job):
        node = self.nodes[node_id]
        return (
            not node.drain
            and job.get("kind", "B") in node.kinds
            and job["spec"]["profile"] in node.profiles
            and job["profile"]["cpu_millis"] <= node.cpu_millis - node.resident_cpu_millis
            and job["profile"]["memory_mib"] <= node.memory_mib - node.resident_memory_mib
        )

    def claim(self, node_id, owner, *, kind="B"):
        node = self.nodes[node_id]
        with self.transaction() as connection:
            persisted = connection.execute(select(_NODES.c.record).where(_NODES.c.id == node_id)).scalar_one()
            connection.execute(update(_NODES).where(_NODES.c.id == node_id).values(record={**persisted, "heartbeat_at": time.time()}))
            # Aggregate only resource scalars, never historical input snapshots.
            unreleased = (_JOBS.c.record["node_id"].as_string() == node_id, func.coalesce(_JOBS.c.record["physical_stopped"].as_boolean(), False).is_(False))
            count, cpu, memory = connection.execute(
                select(func.count(), func.coalesce(func.sum(_JOBS.c.record["profile"]["cpu_millis"].as_integer()), 0), func.coalesce(func.sum(_JOBS.c.record["profile"]["memory_mib"].as_integer()), 0)).where(*unreleased)
            ).one()
            available_cpu = node.cpu_millis - node.resident_cpu_millis - cpu
            available_memory = node.memory_mib - node.resident_memory_mib - memory
            if node.drain or kind not in node.kinds or count >= node.max_concurrency:
                return None
            query = (
                select(_JOBS)
                .where(
                    _JOBS.c.state == "queued",
                    func.coalesce(_JOBS.c.record["kind"].as_string(), "B") == kind,
                    _JOBS.c.record["spec"]["profile"].as_string().in_(node.profiles),
                    _JOBS.c.record["profile"]["cpu_millis"].as_integer() <= available_cpu,
                    _JOBS.c.record["profile"]["memory_mib"].as_integer() <= available_memory,
                )
                .order_by(_JOBS.c.record["created_at"].as_float(), _JOBS.c.id)
                .limit(1)
            )
            for row in connection.execute(query):
                job = dict(row.record)
                job.update(state="starting", node_id=node_id, worker_owner=owner, generation=uuid.uuid4().hex, attempt=1, lease_until=time.time() + self.lease_seconds)
                result = connection.execute(update(_JOBS).where(_JOBS.c.id == row.id, _JOBS.c.version == row.version, _JOBS.c.state == "queued").values(record=job, state="starting", version=row.version + 1))
                if result.rowcount:
                    return job
        return None

    def owned(self, node_id, owner, *, kind="B"):
        # Expiration never releases/reassigns a reservation. Restart only adopts
        # the same node's jobs, with a fresh report fence and no start replay.
        with self.transaction() as connection:
            jobs = []
            query = select(_JOBS).where(
                _JOBS.c.record["node_id"].as_string() == node_id,
                func.coalesce(_JOBS.c.record["kind"].as_string(), "B") == kind,
                func.coalesce(_JOBS.c.record["physical_stopped"].as_boolean(), False).is_(False),
            )
            for row in connection.execute(query):
                job = dict(row.record)
                if job.get("kind", "B") != kind or job.get("node_id") != node_id or job.get("physical_stopped"):
                    continue
                if job["worker_owner"] != owner:
                    if job["lease_until"] > time.time():
                        continue
                    job.update(worker_owner=owner, generation=uuid.uuid4().hex)
                job["lease_until"] = time.time() + self.lease_seconds
                result = connection.execute(update(_JOBS).where(_JOBS.c.id == row.id, _JOBS.c.version == row.version).values(record=job, version=row.version + 1))
                if result.rowcount:
                    jobs.append(job)
            return jobs

    def report(self, node_id, owner, job_id, generation, changes, expected=None):
        if not set(changes) <= _FIELDS:
            raise ValueError("Worker report contains immutable authority fields")

        def apply(record):
            if record.get("node_id") != node_id or record.get("worker_owner") != owner or record.get("generation") != generation:
                raise ValueError("Worker assignment fence mismatch")
            if expected is not None and record != expected:
                raise RuntimeError("Worker snapshot changed; retry")
            if changes.get("start_intent") and (record["state"] != "starting" or record.get("cancel_requested") or record.get("start_intent")):
                raise ValueError("Start intent denied")
            if record.get("cancel_requested") and changes.get("state") == "completed":
                raise RuntimeError("Cancellation raced completion; reconcile STOP")
            target = changes.get("state", record["state"])
            allowed = {
                "starting": {"starting", "running", "uncertain", "completed", "failed", "cancelled"},
                "running": {"running", "uncertain", "completed", "failed", "cancelled"},
                "uncertain": {"uncertain", "running", "completed", "failed", "cancelled"},
            }
            if target not in allowed.get(record["state"], {record["state"]}):
                raise ValueError("Invalid worker state transition")
            if changes.get("physical_stopped") and target not in {"completed", "failed", "cancelled"}:
                raise ValueError("STOP requires terminal outcome")
            record.update(changes)
            record["lease_until"] = time.time() + self.lease_seconds

        return self.store.mutate(job_id, apply)
