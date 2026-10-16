"""Independent SQL execution ledger; never reads Gateway mcp_tasks."""

from __future__ import annotations

import hashlib
import json
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
    Column("workspace_id", String(36), nullable=True, index=True),
    Column("execution_identity", JSON, nullable=True),
)
UniqueConstraint(_JOBS.c.namespace, _JOBS.c.request_key, name="uq_ecs_execution_request")


def _execution_identity(record):
    """Capture only explicitly supplied intent; attribution never creates a grant."""
    snapshot = record.get("workspace_context")
    if snapshot is None:
        return None
    from deerflow.authz.workspace import WorkspaceContext

    try:
        context = WorkspaceContext(**snapshot)
    except (TypeError, ValueError):
        raise ValueError("Execution identity snapshot is invalid") from None
    if context.workspace_id != record.get("workspace_id") or context.actor_user_id != record.get("user_id") or record.get("kind", "B") != "B":
        raise ValueError("Execution identity workspace/actor/kind mismatch")
    identity = {key: record.get(key) for key in ("user_id", "thread_id", "incarnation", "run_id", "spec_digest")}
    for key, limit in (("user_id", 64), ("thread_id", 64), ("incarnation", 32), ("run_id", 64), ("spec_digest", 255)):
        value = identity[key]
        if not isinstance(value, str) or not 1 <= len(value) <= limit or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Execution identity locator is invalid")
    # Bind operator profile and effective input spec without duplicating potentially
    # large snapshotted file content in the identity column.
    intent = {key: record.get(key) for key in ("spec", "profile", "max_input_bytes")}
    encoded = json.dumps(intent, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    return {**identity, "kind": "B", "workspace_id": context.workspace_id, "workspace_context": dict(snapshot), "intent_sha256": hashlib.sha256(encoded).hexdigest()}


def _validated_record(row):
    record = dict(row.record)
    if record.get("workspace_id") != row.workspace_id or _execution_identity(record) != row.execution_identity or (row.execution_identity is not None and record.get("id") != row.id):
        raise ValueError("Execution identity differs from immutable ledger")
    return record


class JobStore:
    """Sync SQL operations are offloaded by the HTTP service and local worker.

    Optimistic version predicates serialize activation, expiry, cancellation and
    worker updates on both PostgreSQL and SQLite. A job is claimed exactly once;
    uncertain physical outcomes remain in the ledger for reconciliation.
    """

    def __init__(self, url: str):
        self.engine = create_engine(url)

    def initialize(self):
        """Explicit test/local bootstrap; production entrypoints use require_schema."""
        from ecs_executor.schema import upgrade_schema

        upgrade_schema(self.engine)

    def get(self, job_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = connection.execute(select(_JOBS).where(_JOBS.c.id == job_id)).first()
        if row is None:
            raise ValueError("Execution job not found")
        return _validated_record(row)

    def find_request(self, *, namespace, request_key, spec_digest):
        with self.engine.connect() as connection:
            row = connection.execute(select(_JOBS).where(_JOBS.c.namespace == namespace, _JOBS.c.request_key == request_key)).first()
        if row is None:
            return None
        record = _validated_record(row)
        if record["spec_digest"] != spec_digest:
            raise ValueError("request_key is already bound to a different immutable specification")
        return record

    def create(self, *, namespace: str, request_key: str, spec_digest: str, record: dict[str, Any]) -> dict[str, Any]:
        job = {**record, "id": uuid.uuid4().hex, "state": "staged", "created_at": time.time(), "spec_digest": spec_digest}
        identity = _execution_identity(job)
        try:
            with self.engine.begin() as connection:
                connection.execute(_JOBS.insert().values(id=job["id"], namespace=namespace, request_key=request_key, version=0, state="staged", record=job, workspace_id=job.get("workspace_id"), execution_identity=identity))
            return job
        except IntegrityError:
            with self.engine.connect() as connection:
                row = connection.execute(select(_JOBS).where(_JOBS.c.namespace == namespace, _JOBS.c.request_key == request_key)).first()
            if row is None:
                raise
            if row.record["spec_digest"] != spec_digest:
                raise ValueError("request_key is already bound to a different immutable specification") from None
            if row.record.get("workspace_id") != job.get("workspace_id"):
                raise ValueError("request_key is already bound to a different workspace") from None
            previous = _validated_record(row)
            if row.execution_identity != identity:
                raise ValueError("request_key is already bound to a different execution identity") from None
            return previous

    def mutate(self, job_id: str, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        for _ in range(20):
            with self.engine.begin() as connection:
                row = connection.execute(select(_JOBS).where(_JOBS.c.id == job_id)).first()
                if row is None:
                    raise ValueError("Execution job not found")
                record = _validated_record(row)
                change(record)
                if (row.execution_identity is not None and record.get("id") != row.id) or _execution_identity(record) != row.execution_identity:
                    raise ValueError("Execution identity cannot change")
                if record.get("workspace_id") != row.workspace_id:
                    raise ValueError("Execution workspace cannot change")
                # A terminal outcome cannot revive, even after a late physical RPC.
                if row.state in TERMINAL and record["state"] != row.state:
                    raise ValueError("Terminal execution cannot change state")
                result = connection.execute(update(_JOBS).where(_JOBS.c.id == job_id, _JOBS.c.version == row.version).values(version=row.version + 1, state=record["state"], record=record))
                if result.rowcount == 1:
                    return record
        raise RuntimeError("Concurrent execution update must be retried")

    def list_active(self, *, kind=None) -> list[dict[str, Any]]:
        query = select(_JOBS).where(_JOBS.c.state.not_in(TERMINAL))
        if kind is not None:
            from sqlalchemy import func

            query = query.where(func.coalesce(_JOBS.c.record["kind"].as_string(), "B") == kind)
        with self.engine.connect() as connection:
            return [_validated_record(row) for row in connection.execute(query)]

    def list_native_settlement_pending(self) -> list[dict[str, Any]]:
        query = (
            select(_JOBS)
            .where(
                _JOBS.c.record["kind"].as_string() == "C",
                _JOBS.c.record["settlement_pending"].as_boolean().is_(True),
            )
            .order_by(_JOBS.c.id)
            .limit(100)
        )
        with self.engine.connect() as connection:
            return [_validated_record(row) for row in connection.execute(query)]

    def list_cleanup_pending(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            query = select(_JOBS).where(_JOBS.c.state.in_(TERMINAL), _JOBS.c.record["cleanup_pending"].as_boolean().is_(True))
            return [_validated_record(row) for row in connection.execute(query)]

    def list_native_dependency_waiting(self, *, after_id: str = "") -> list[dict[str, Any]]:
        query = (
            select(_JOBS)
            .where(_JOBS.c.id > after_id, _JOBS.c.record["kind"].as_string() == "C", _JOBS.c.record["dependency_wait"]["active"].as_boolean().is_(True), _JOBS.c.record["dependency_wait"]["continuation_run_id"].as_string().is_(None))
            .order_by(_JOBS.c.id)
            .limit(100)
        )
        with self.engine.connect() as connection:
            return [_validated_record(row) for row in connection.execute(query)]

    def claim_queued(self) -> dict[str, Any] | None:
        for job in self.list_active():
            if job.get("state") != "queued" or job.get("workspace_id") is not None:
                # The legacy worker has no current native MCP commitment/start
                # authorization. Preserve the reservation without granting launch.
                continue
            claimed = False

            def claim(record):
                nonlocal claimed
                claimed = record["state"] == "queued" and record.get("workspace_id") is None
                if claimed:
                    record["state"] = "starting"

            record = self.mutate(job["id"], claim)
            if claimed:
                return record
        return None

    def expire_staged(self, *, now: float | None = None):
        current = time.time() if now is None else now
        for job in self.list_active(kind="B"):

            def expire(record):
                if record["state"] == "staged" and record["staged_deadline"] <= current:
                    record.update(state="failed", error="Submission was not activated before its staging deadline")

            self.mutate(job["id"], expire)
