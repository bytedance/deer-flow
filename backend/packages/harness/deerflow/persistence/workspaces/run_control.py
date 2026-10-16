"""Captured native Run stop intents; no Agent or physical-worker authority.

The owning native runtime acknowledges only its actual closed execution. Remote
C physical STOP remains a separate prerequisite in that executor's ledger.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, text

from deerflow.authz.workspace import WorkspaceContext
from deerflow.persistence.workspaces.model import WorkspaceAuditEventRow, WorkspaceOperationOutboxRow


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _identifier(value):
    if type(value) is not str or not 1 <= len(value) <= 255 or value.strip() != value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("invalid native Run control identity")


def _aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class NativeRunStopTarget:
    run_id: str
    user_id: str
    workspace_id: str
    thread_id: str
    thread_incarnation: str
    owner_worker_id: str
    created_at: str
    workspace_context: WorkspaceContext

    def __post_init__(self):
        for name in ("run_id", "user_id", "workspace_id", "thread_id", "thread_incarnation", "owner_worker_id", "created_at"):
            _identifier(getattr(self, name))
        if type(self.workspace_context) is not WorkspaceContext or self.workspace_context.workspace_id != self.workspace_id or self.workspace_context.actor_user_id != self.user_id:
            raise ValueError("native Run stop binding differs")
        date = datetime.fromisoformat(self.created_at)
        if date.tzinfo is None or date != _aware(date) or self.created_at != _aware(date).isoformat():
            raise ValueError("native Run control requires canonical creation time")

    @classmethod
    def from_row(cls, row):
        try:
            values = {name: getattr(row, name) for name in cls.__dataclass_fields__ if name != "workspace_context"}
            values["created_at"] = _aware(row.created_at).isoformat()
            values["workspace_context"] = WorkspaceContext(**row.workspace_context_json)
            return cls(**values)
        except (TypeError, ValueError, AttributeError):
            raise ValueError("native Run lacks captured stop identity") from None

    @classmethod
    def from_record(cls, record):
        values = {name: getattr(record, name) for name in cls.__dataclass_fields__}
        values["created_at"] = _aware(datetime.fromisoformat(record.created_at)).isoformat()
        return cls(**values)

    def as_payload(self):
        return asdict(self)

    @property
    def operation_id(self):
        return hashlib.sha256(_canonical(["run_stop", self.as_payload()])).hexdigest()


def pending_run_stop(*, run_id=None, workspace_id=None, thread_id=None, user_id=None):
    query = select(WorkspaceOperationOutboxRow.operation_id).where(WorkspaceOperationOutboxRow.kind == "run_stop", WorkspaceOperationOutboxRow.state != "completed")
    if run_id is not None:
        query = query.where(WorkspaceOperationOutboxRow.payload["run_id"].as_string() == run_id)
    if workspace_id is not None:
        query = query.where(WorkspaceOperationOutboxRow.workspace_id == workspace_id)
    if thread_id is not None:
        query = query.where(WorkspaceOperationOutboxRow.payload["thread_id"].as_string() == thread_id)
    if user_id is not None:
        query = query.where(WorkspaceOperationOutboxRow.user_id == user_id)
    return query.correlate_except(WorkspaceOperationOutboxRow).exists()


async def enqueue_membership_run_stops(session, workspace, member):
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository

    # Preserve native clock -> Run row order inside the caller's existing
    # workspace transaction. No task cancellation, graph or network IO here.
    sequence = await RunRepository._next_change_seq(session)
    rows = (
        await session.scalars(select(RunRow).where(RunRow.workspace_id == workspace.id, RunRow.user_id == member.user_id, RunRow.operation_kind == "run", RunRow.status.in_(("pending", "running"))).order_by(RunRow.run_id).with_for_update())
    ).all()
    now = datetime.now(UTC)
    for row in rows:
        try:
            target = NativeRunStopTarget.from_row(row)
            if target.workspace_context.membership_version > member.version or target.workspace_context.policy_version > workspace.policy_version:
                raise ValueError("future native Run snapshot")
            op, state = target.operation_id, "pending"
            payload = {"version": 1, "run_id": row.run_id, "thread_id": row.thread_id, "target": target.as_payload()}
        except ValueError:
            op = hashlib.sha256(_canonical(["run_stop_invalid", row.run_id, workspace.id, member.user_id])).hexdigest()
            state, payload = "quarantine", {"version": 1, "run_id": row.run_id, "thread_id": row.thread_id, "error": "missing_captured_identity"}
        if await session.get(WorkspaceOperationOutboxRow, op) is None:
            session.add(WorkspaceOperationOutboxRow(operation_id=op, workspace_id=workspace.id, user_id=member.user_id, kind="run_stop", state=state, payload=payload))
        row.cancel_action = row.cancel_action or "interrupt"
        row.cancel_requested_at = row.cancel_requested_at or now
        row.updated_at, row.change_seq = now, sequence


async def confirm_local_run_stop(session_factory, target, *, evidence):
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository

    if type(target) is not NativeRunStopTarget or evidence not in ("native_worker_closed", "native_not_started"):
        raise ValueError("invalid native Run stop acknowledgement")
    now = datetime.now(UTC)
    async with session_factory() as session:
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))
        sequence = await RunRepository._next_change_seq(session)
        row = await session.scalar(select(RunRow).where(RunRow.run_id == target.run_id).with_for_update())
        if row is None:
            return False
        try:
            exact = NativeRunStopTarget.from_row(row) == target
        except ValueError:
            exact = False
        if not exact or row.lease_expires_at is None or _aware(row.lease_expires_at) <= now or row.cancel_requested_at is None:
            return False
        operation = await session.scalar(select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.operation_id == target.operation_id).with_for_update())
        if operation is None or operation.kind != "run_stop" or operation.workspace_id != target.workspace_id or operation.user_id != target.user_id or operation.payload.get("target") != target.as_payload():
            return False
        if operation.state == "completed":
            return True
        if operation.state != "pending" or (evidence == "native_not_started" and row.status != "pending") or row.status not in ("pending", "running", "interrupted", "error", "timeout"):
            return False
        row.status, row.updated_at, row.change_seq = "interrupted", now, sequence
        operation.state = "completed"
        operation.payload = {**operation.payload, "receipt": {"evidence": evidence, "owner_worker_id": target.owner_worker_id, "observed_at": now.isoformat()}}
        session.add(WorkspaceAuditEventRow(id=str(uuid4()), workspace_id=target.workspace_id, actor_user_id=None, action="run.execution_closed", resource_id=target.run_id, outcome="success", request_id=target.operation_id))
        await session.commit()
        return True
