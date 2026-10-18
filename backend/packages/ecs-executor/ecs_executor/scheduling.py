"""One durable, transactionally serialized B/C resource ledger."""

import time
import uuid
from contextlib import contextmanager

from sqlalchemy import JSON, Column, MetaData, String, Table, func, select, text, update

from ecs_executor.job_store import _JOBS, _validated_record

_METADATA = MetaData()
_NODES = Table("ecs_execution_nodes", _METADATA, Column("id", String(64), primary_key=True), Column("record", JSON, nullable=False))
_FIELDS = {"state", "start_intent", "started_at", "error", "exit_code", "artifact", "native_artifact_uri", "cleanup_pending", "physical_stopped", "physical_stopped_at"}


class Scheduling:
    def __init__(self, store, *, nodes, lease_seconds=120):
        if not nodes or lease_seconds < 120:
            raise ValueError("A fixed pool and at least 120 seconds of lease/cleanup safety are required")
        self.store, self.nodes, self.lease_seconds = store, nodes, lease_seconds
        from ecs_executor.schema import require_schema

        require_schema(store.engine)
        with self.transaction() as connection:
            for node_id, node in nodes.items():
                old = connection.execute(select(_NODES.c.record).where(_NODES.c.id == node_id)).scalar_one_or_none()
                record = {"config": node.model_dump(mode="json"), "heartbeat_at": (old or {}).get("heartbeat_at", 0), "operator_drain": (old or {}).get("operator_drain", False)}
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

    def set_operator_drain(self, node_id, drain):
        """Operator-only admission fence, serialized with claims; reports still work."""
        if node_id not in self.nodes or type(drain) is not bool:
            raise ValueError("Unknown fixed node or invalid drain value")
        with self.transaction() as connection:
            record = connection.execute(select(_NODES.c.record).where(_NODES.c.id == node_id)).scalar_one()
            connection.execute(update(_NODES).where(_NODES.c.id == node_id).values(record={**record, "operator_drain": drain}))

    def node_status(self, node_id):
        """Bounded safe operator observation: never return inputs, identity or secrets."""
        if node_id not in self.nodes:
            raise ValueError("Unknown fixed node")
        with self.transaction() as connection:
            record = connection.execute(select(_NODES.c.record).where(_NODES.c.id == node_id)).scalar_one()
            count = connection.execute(
                select(func.count())
                .select_from(_JOBS)
                .where(
                    _JOBS.c.record["node_id"].as_string() == node_id,
                    func.coalesce(_JOBS.c.record["physical_stopped"].as_boolean(), False).is_(False),
                )
            ).scalar_one()
            return {"operator_drain": record.get("operator_drain", False), "unreleased": count}

    def eligible(self, node_id, job):
        node = self.nodes[node_id]
        return (
            job.get("affinity_node", node_id) == node_id
            and not node.drain
            and job.get("kind", "B") in node.kinds
            and job["spec"]["profile"] in node.profiles
            and job["profile"]["cpu_millis"] <= node.cpu_millis - node.resident_cpu_millis
            and job["profile"]["memory_mib"] <= node.memory_mib - node.resident_memory_mib
        )

    def _available(self, connection, node_id, kind):
        node = self.nodes[node_id]
        persisted = connection.execute(select(_NODES.c.record).where(_NODES.c.id == node_id)).scalar_one()
        connection.execute(update(_NODES).where(_NODES.c.id == node_id).values(record={**persisted, "heartbeat_at": time.time()}))
        unreleased = (_JOBS.c.record["node_id"].as_string() == node_id, func.coalesce(_JOBS.c.record["physical_stopped"].as_boolean(), False).is_(False))
        count, cpu, memory = connection.execute(
            select(func.count(), func.coalesce(func.sum(_JOBS.c.record["profile"]["cpu_millis"].as_integer()), 0), func.coalesce(func.sum(_JOBS.c.record["profile"]["memory_mib"].as_integer()), 0)).where(*unreleased)
        ).one()
        if node.drain or persisted.get("operator_drain", False) or kind not in node.kinds or count >= node.max_concurrency:
            return None
        return node.cpu_millis - node.resident_cpu_millis - cpu, node.memory_mib - node.resident_memory_mib - memory

    def claim(self, node_id, owner, *, kind="B"):
        node = self.nodes[node_id]
        with self.transaction() as connection:
            available = self._available(connection, node_id, kind)
            if available is None:
                return None
            available_cpu, available_memory = available
            query = (
                select(_JOBS)
                .where(
                    _JOBS.c.state == "queued",
                    _JOBS.c.workspace_id.is_(None),
                    func.coalesce(_JOBS.c.record["affinity_node"].as_string(), node_id) == node_id,
                    func.coalesce(_JOBS.c.record["kind"].as_string(), "B") == kind,
                    _JOBS.c.record["spec"]["profile"].as_string().in_(node.profiles),
                    _JOBS.c.record["profile"]["cpu_millis"].as_integer() <= available_cpu,
                    _JOBS.c.record["profile"]["memory_mib"].as_integer() <= available_memory,
                )
                .order_by(_JOBS.c.record["created_at"].as_float(), _JOBS.c.id)
                .limit(1)
            )
            for row in connection.execute(query):
                job = _validated_record(row)
                job.update(state="starting", node_id=node_id, worker_owner=owner, generation=uuid.uuid4().hex, attempt=1, lease_until=time.time() + self.lease_seconds)
                result = connection.execute(update(_JOBS).where(_JOBS.c.id == row.id, _JOBS.c.version == row.version, _JOBS.c.state == "queued").values(record=job, state="starting", version=row.version + 1))
                if result.rowcount:
                    return job
        return None

    def scoped_native_candidates(self, node_id):
        """Internal ledger snapshots only; these are never execution grants."""
        with self.store.engine.connect() as connection:
            query = (
                select(_JOBS)
                .where(
                    _JOBS.c.workspace_id.is_not(None),
                    _JOBS.c.record["kind"].as_string() == "C",
                    _JOBS.c.state.in_(("queued", "starting", "running", "uncertain")),
                    _JOBS.c.record["affinity_node"].as_string() == node_id,
                    func.coalesce(_JOBS.c.record["physical_stopped"].as_boolean(), False).is_(False),
                )
                .order_by(_JOBS.c.record["created_at"].as_float(), _JOBS.c.id)
            )
            return [(row.version, _validated_record(row)) for row in connection.execute(query)]

    def claim_scoped_native(self, node_id, owner, *, expected, version):
        """Exact C candidate reservation, after independent native preflight.

        Reuse the ordinary pool's transaction and capacity accounting. Native
        authority must be checked again before signing and at receiver adoption.
        """
        if not owner or expected.get("workspace_id") is None or expected.get("kind") != "C":
            raise ValueError("Scoped native claim requires an exact C candidate")
        with self.transaction() as connection:
            row = connection.execute(select(_JOBS).where(_JOBS.c.id == expected["id"], _JOBS.c.version == version, _JOBS.c.state == "queued", _JOBS.c.workspace_id.is_not(None))).first()
            if row is None:
                return None
            job = _validated_record(row)
            if (
                job != expected
                or not self.eligible(node_id, job)
                or job.get("cancel_requested")
                or (job.get("start_intent") is not None and job.get("start_intent") is not False)
                or job.get("physical_stopped") is not False
                or any(job.get(key) is not None for key in ("node_id", "worker_owner", "generation"))
                or not (job.get("attempt") is None or type(job.get("attempt")) is int and job["attempt"] == 0)
            ):
                return None
            available = self._available(connection, node_id, "C")
            if available is None or job["profile"]["cpu_millis"] > available[0] or job["profile"]["memory_mib"] > available[1]:
                return None
            job.update(state="starting", node_id=node_id, worker_owner=owner, generation=uuid.uuid4().hex, attempt=1, lease_until=time.time() + self.lease_seconds)
            result = connection.execute(update(_JOBS).where(_JOBS.c.id == row.id, _JOBS.c.version == version, _JOBS.c.state == "queued").values(record=job, state="starting", version=version + 1))
            return job if result.rowcount else None

    def renew_scoped_native(self, node_id, owner, *, expected, version):
        """Retain one reservation; recovery itself never permits a graph replay."""
        with self.transaction() as connection:
            row = connection.execute(select(_JOBS).where(_JOBS.c.id == expected["id"], _JOBS.c.version == version, _JOBS.c.workspace_id.is_not(None))).first()
            if row is None:
                return None
            job = _validated_record(row)
            if job != expected or job.get("kind") != "C" or job.get("node_id") != node_id or job.get("state") not in ("starting", "running", "uncertain") or job.get("physical_stopped"):
                return None
            if job["worker_owner"] != owner:
                if job["lease_until"] > time.time():
                    return None
                job.update(worker_owner=owner, generation=uuid.uuid4().hex)
            job["lease_until"] = time.time() + self.lease_seconds
            result = connection.execute(update(_JOBS).where(_JOBS.c.id == row.id, _JOBS.c.version == version).values(record=job, version=version + 1))
            return job if result.rowcount else None

    def owned(self, node_id, owner, *, kind="B"):
        # Expiration never releases/reassigns a reservation. Restart only adopts
        # the same node's jobs, with a fresh report fence and no start replay.
        with self.transaction() as connection:
            jobs = []
            query = select(_JOBS).where(
                # Ordinary recovery is not scoped payload/launch authority.
                # Scoped reservations remain counted until control proves STOP.
                _JOBS.c.workspace_id.is_(None),
                _JOBS.c.record["node_id"].as_string() == node_id,
                func.coalesce(_JOBS.c.record["kind"].as_string(), "B") == kind,
                func.coalesce(_JOBS.c.record["physical_stopped"].as_boolean(), False).is_(False),
            )
            for row in connection.execute(query):
                job = _validated_record(row)
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
