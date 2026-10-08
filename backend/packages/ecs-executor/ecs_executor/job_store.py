"""Independent SQL execution ledger; never reads Gateway mcp_tasks."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, UniqueConstraint, create_engine, select, update
from sqlalchemy.exc import IntegrityError

TERMINAL = {"completed", "failed", "cancelled"}
_METADATA = MetaData()
_JOBS = Table(
    "ecs_execution_jobs",
    _METADATA,
    Column("id", String(64), primary_key=True),
    Column("namespace", String(64), nullable=False),
    Column("request_key", String(128), nullable=False),
    Column("version", Integer, nullable=False),
    Column("state", String(32), nullable=False, index=True),
    Column("record", JSON, nullable=False),
)
UniqueConstraint(_JOBS.c.namespace, _JOBS.c.request_key, name="uq_ecs_execution_request")


class JobStore:
    """Sync SQL operations are offloaded by the HTTP service and local worker.

    Optimistic version predicates serialize activation, expiry, cancellation and
    worker updates on both PostgreSQL and SQLite. A job is claimed exactly once;
    uncertain physical outcomes remain in the ledger for reconciliation.
    """

    def __init__(self, url: str):
        self.engine = create_engine(url)

    def initialize(self):
        _METADATA.create_all(self.engine)

    def get(self, job_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = connection.execute(select(_JOBS.c.record).where(_JOBS.c.id == job_id)).first()
        if row is None:
            raise ValueError("Execution job not found")
        return dict(row.record)

    def find_request(self, *, namespace, request_key, spec_digest):
        with self.engine.connect() as connection:
            row = connection.execute(select(_JOBS.c.record).where(_JOBS.c.namespace == namespace, _JOBS.c.request_key == request_key)).first()
        if row is None:
            return None
        if row.record["spec_digest"] != spec_digest:
            raise ValueError("request_key is already bound to a different immutable specification")
        return dict(row.record)

    def create(self, *, namespace: str, request_key: str, spec_digest: str, record: dict[str, Any]) -> dict[str, Any]:
        job = {**record, "id": uuid.uuid4().hex, "state": "staged", "created_at": time.time(), "spec_digest": spec_digest}
        try:
            with self.engine.begin() as connection:
                connection.execute(_JOBS.insert().values(id=job["id"], namespace=namespace, request_key=request_key, version=0, state="staged", record=job))
            return job
        except IntegrityError:
            with self.engine.connect() as connection:
                row = connection.execute(select(_JOBS.c.record).where(_JOBS.c.namespace == namespace, _JOBS.c.request_key == request_key)).first()
            if row is None:
                raise
            if row.record["spec_digest"] != spec_digest:
                raise ValueError("request_key is already bound to a different immutable specification") from None
            return dict(row.record)

    def mutate(self, job_id: str, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        for _ in range(20):
            with self.engine.begin() as connection:
                row = connection.execute(select(_JOBS).where(_JOBS.c.id == job_id)).first()
                if row is None:
                    raise ValueError("Execution job not found")
                record = dict(row.record)
                change(record)
                # A terminal outcome cannot revive, even after a late physical RPC.
                if row.state in TERMINAL and record["state"] != row.state:
                    raise ValueError("Terminal execution cannot change state")
                result = connection.execute(update(_JOBS).where(_JOBS.c.id == job_id, _JOBS.c.version == row.version).values(version=row.version + 1, state=record["state"], record=record))
                if result.rowcount == 1:
                    return record
        raise RuntimeError("Concurrent execution update must be retried")

    def list_active(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [dict(row.record) for row in connection.execute(select(_JOBS.c.record).where(_JOBS.c.state.not_in(TERMINAL)))]

    def list_cleanup_pending(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            query = select(_JOBS.c.record).where(_JOBS.c.state.in_(TERMINAL), _JOBS.c.record["cleanup_pending"].as_boolean().is_(True))
            return [dict(row.record) for row in connection.execute(query)]

    def claim_queued(self) -> dict[str, Any] | None:
        for job in self.list_active():
            if job["state"] != "queued":
                continue
            claimed = False

            def claim(record):
                nonlocal claimed
                claimed = record["state"] == "queued"
                if claimed:
                    record["state"] = "starting"

            record = self.mutate(job["id"], claim)
            if claimed:
                return record
        return None

    def expire_staged(self, *, now: float | None = None):
        current = time.time() if now is None else now
        for job in self.list_active():

            def expire(record):
                if record["state"] == "staged" and record["staged_deadline"] <= current:
                    record.update(state="failed", error="Submission was not activated before its staging deadline")

            self.mutate(job["id"], expire)
