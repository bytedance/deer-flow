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
from deerflow.persistence.workspaces.model import WorkspaceAuditEventRow, WorkspaceOperationOutboxRow, WorkspaceRow


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

    def execution_binding(self):
        result = self.as_payload()
        result.pop("owner_worker_id")
        return result

    @property
    def execution_id(self):
        return hashlib.sha256(_canonical(["run_execution", self.execution_binding()])).hexdigest()

    @property
    def operation_id(self):
        return hashlib.sha256(_canonical(["run_stop", self.as_payload()])).hexdigest()


def _pending(kind, *, run_id=None, workspace_id=None, thread_id=None, user_id=None, reason=None):
    query = select(WorkspaceOperationOutboxRow.operation_id).where(WorkspaceOperationOutboxRow.kind == kind, WorkspaceOperationOutboxRow.state != "completed")
    if run_id is not None:
        query = query.where(WorkspaceOperationOutboxRow.payload["run_id"].as_string() == run_id)
    if workspace_id is not None:
        query = query.where(WorkspaceOperationOutboxRow.workspace_id == workspace_id)
    if thread_id is not None:
        query = query.where(WorkspaceOperationOutboxRow.payload["thread_id"].as_string() == thread_id)
    if user_id is not None:
        query = query.where(WorkspaceOperationOutboxRow.user_id == user_id)
    if reason is not None:
        query = query.where(WorkspaceOperationOutboxRow.payload["reason"].as_string() == reason)
    return query.correlate_except(WorkspaceOperationOutboxRow).exists()


def pending_run_stop(**kwargs):
    return _pending("run_stop", **kwargs)


def pending_run_execution(**kwargs):
    return _pending("run_execution", **kwargs)


def pending_execution_barrier(**kwargs):
    return pending_run_stop(**kwargs) | pending_run_execution(**kwargs)


def revocation_run_stop(**kwargs):
    # User rollback remains a native action until revocation supersedes its
    # authority. The operation identity does not depend on either cause.
    return _pending("run_stop", reason="revocation", **kwargs)


async def create_execution_lifetime(session, row):
    target = NativeRunStopTarget.from_row(row)
    session.add(
        WorkspaceOperationOutboxRow(
            operation_id=target.execution_id,
            workspace_id=target.workspace_id,
            user_id=target.user_id,
            kind="run_execution",
            state="open",
            payload={"version": 1, "run_id": target.run_id, "thread_id": target.thread_id, "binding": target.execution_binding(), "owner_worker_id": target.owner_worker_id},
        )
    )


async def execution_lifetime(session, target, *, open_only=True):
    operation = await session.scalar(select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.operation_id == target.execution_id).with_for_update())
    if (
        operation is None
        or operation.kind != "run_execution"
        or operation.workspace_id != target.workspace_id
        or operation.user_id != target.user_id
        or operation.payload is None
        or operation.payload.get("binding") != target.execution_binding()
        or operation.payload.get("owner_worker_id") != target.owner_worker_id
    ):
        raise ValueError("native execution lifetime binding differs")
    if operation.state != "open" and (open_only or operation.state != "completed"):
        raise ValueError("native execution lifetime is not open")
    return operation


async def enqueue_run_stop(session, row, *, reason, now, invalid_identity=False):
    try:
        target = NativeRunStopTarget.from_row(row)
        if invalid_identity:
            raise ValueError("captured native Run epoch is incompatible")
        op, state = target.operation_id, "pending"
        payload = {"version": 1, "run_id": row.run_id, "thread_id": row.thread_id, "target": target.as_payload(), "reason": reason}
    except ValueError:
        op = hashlib.sha256(_canonical(["run_stop_invalid", row.run_id, row.workspace_id, row.user_id])).hexdigest()
        state, payload = "quarantine", {"version": 1, "run_id": row.run_id, "thread_id": row.thread_id, "error": "invalid_captured_identity", "reason": reason}
    existing = await session.get(WorkspaceOperationOutboxRow, op)
    if existing is None:
        session.add(WorkspaceOperationOutboxRow(operation_id=op, workspace_id=row.workspace_id, user_id=row.user_id, kind="run_stop", state=state, payload=payload))
    elif reason == "revocation" and existing.state != "completed":
        existing.payload = {**existing.payload, "reason": "revocation"}
    row.cancel_action = row.cancel_action or "interrupt"
    row.cancel_requested_at = row.cancel_requested_at or now


async def enqueue_membership_run_stops(session, workspace, member):
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository

    # Preserve native clock -> Run row order inside the caller's existing
    # workspace transaction. No task cancellation, graph or network IO here.
    sequence = await RunRepository._next_change_seq(session)
    rows = (
        await session.scalars(
            select(RunRow)
            .where(
                RunRow.workspace_id == workspace.id,
                RunRow.user_id == member.user_id,
                RunRow.operation_kind == "run",
                (RunRow.status.in_(("pending", "running")) | pending_run_execution(run_id=RunRow.run_id, workspace_id=RunRow.workspace_id)),
            )
            .order_by(RunRow.run_id)
            .with_for_update()
        )
    ).all()
    now = datetime.now(UTC)
    for row in rows:
        try:
            context = NativeRunStopTarget.from_row(row).workspace_context
            invalid = context.membership_version > member.version or context.policy_version > workspace.policy_version
        except ValueError:
            invalid = True
        await enqueue_run_stop(session, row, reason="revocation", now=now, invalid_identity=invalid)
        row.updated_at, row.change_seq = now, sequence


async def mark_owner_interrupted(session_factory, target):
    """Acknowledge processing of an exact durable STOP, never its completion.

    This control-only transition preserves the open lifetime and stop barrier.
    No withdrawn member authority, business payload or receipt is consumed.
    """
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository

    if type(target) is not NativeRunStopTarget:
        raise ValueError("invalid native interrupt processing identity")
    async with session_factory() as session:
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))
        if await session.scalar(select(WorkspaceRow.id).where(WorkspaceRow.id == target.workspace_id).with_for_update()) is None:
            return False
        sequence = await RunRepository._next_change_seq(session)
        row = await session.scalar(select(RunRow).where(RunRow.run_id == target.run_id).with_for_update())
        try:
            if row is None or NativeRunStopTarget.from_row(row) != target:
                return False
            await execution_lifetime(session, target)
        except ValueError:
            return False
        if row.status not in ("running", "interrupted") or row.cancel_requested_at is None:
            return False
        stop = await session.scalar(select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.operation_id == target.operation_id).with_for_update())
        if stop is None or stop.kind != "run_stop" or stop.state != "pending" or stop.workspace_id != target.workspace_id or stop.user_id != target.user_id or not stop.payload or stop.payload.get("target") != target.as_payload():
            return False
        now = datetime.now(UTC)
        if row.lease_expires_at is None or _aware(row.lease_expires_at) <= now:
            return False
        row.status, row.updated_at, row.change_seq = "interrupted", now, sequence
        await session.commit()
        return True


async def signal_owned_stream_end(session_factory, target, *, signal, closed_only=False):
    """Signal the owner's closed producer lane; never publish result data.

    No live member privilege is needed to end its own lane, but a replaced or
    expired owner cannot terminate a successor's stream. An exact completed
    lifetime remains recognizable for a late NoStart consumer.
    """
    from deerflow.persistence.run.model import RunRow
    from deerflow.utils.file_io import await_drained

    if type(target) is not NativeRunStopTarget:
        raise ValueError("captured stream-end control identity required")
    async with session_factory() as session:
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))
        if await session.scalar(select(WorkspaceRow.id).where(WorkspaceRow.id == target.workspace_id).with_for_update()) is None:
            return False
        row = await session.scalar(select(RunRow).where(RunRow.run_id == target.run_id).with_for_update())
        try:
            if row is None or NativeRunStopTarget.from_row(row) != target or row.operation_kind != "run":
                return False
            lifetime = await execution_lifetime(session, target, open_only=False)
        except ValueError:
            return False
        if closed_only and lifetime.state != "completed":
            return False
        if lifetime.state != "completed" and (row.lease_expires_at is None or _aware(row.lease_expires_at) <= datetime.now(UTC)):
            return False
        await await_drained(signal())
        await session.commit()
        return True


async def confirm_local_execution(session_factory, target):
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta.model import ThreadMetaRow

    if type(target) is not NativeRunStopTarget:
        raise ValueError("captured native close target required")
    now = datetime.now(UTC)
    async with session_factory() as session:
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))
        # Cleanup does not authorize from current membership, but it must
        # honor workspace -> clock -> Run lock order. The audit FK would
        # otherwise request a workspace key-share lock after holding clock.
        if await session.scalar(select(WorkspaceRow.id).where(WorkspaceRow.id == target.workspace_id).with_for_update()) is None:
            return None
        # Lock existence only, not current membership. A replaced/deleted
        # parent must never receive this original execution's cleanup status.
        parent = await session.scalar(
            select(ThreadMetaRow)
            .where(ThreadMetaRow.thread_id == target.thread_id, ThreadMetaRow.workspace_id == target.workspace_id, ThreadMetaRow.user_id == target.user_id, ThreadMetaRow.incarnation == target.thread_incarnation)
            .with_for_update()
        )
        sequence = await RunRepository._next_change_seq(session)
        row = await session.scalar(select(RunRow).where(RunRow.run_id == target.run_id).with_for_update())
        try:
            if row is None or NativeRunStopTarget.from_row(row) != target:
                return None
            lifetime = await execution_lifetime(session, target, open_only=False)
        except ValueError:
            return None
        if lifetime.state == "completed":
            return {"status": row.status}
        now = datetime.now(UTC)
        if row.lease_expires_at is None or _aware(row.lease_expires_at) <= now:
            return None
        if row.cancel_requested_at is not None and await session.scalar(select(pending_run_stop(run_id=row.run_id, workspace_id=row.workspace_id))):
            # Actual closed worker acknowledgement has control-only authority:
            # terminate without storing denied output/tokens/error payloads.
            row.status = "interrupted"
        elif row.status not in ("success", "error", "timeout", "interrupted"):
            return None
        lifetime.state = "completed"
        lifetime.payload = {**lifetime.payload, "receipt": {"evidence": "native_worker_closed", "owner_worker_id": target.owner_worker_id, "observed_at": now.isoformat()}}
        row.updated_at, row.change_seq = now, sequence
        if parent is not None and parent.workspace_id == target.workspace_id and parent.user_id == target.user_id and parent.incarnation == target.thread_incarnation and parent.status != "deleting":
            parent.status = "idle" if row.status == "success" else row.status
            parent.updated_at = now
        session.add(WorkspaceAuditEventRow(id=str(uuid4()), workspace_id=target.workspace_id, actor_user_id=None, action="run.lifecycle_closed", resource_id=target.run_id, outcome="success", request_id=target.execution_id))
        closed_status = row.status
        await session.commit()
        return {"status": closed_status}


async def confirm_local_run_stop(session_factory, target, *, evidence):
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository

    if type(target) is not NativeRunStopTarget or evidence not in ("native_worker_closed", "native_not_started"):
        raise ValueError("invalid native Run stop acknowledgement")
    now = datetime.now(UTC)
    async with session_factory() as session:
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))
        # Cleanup does not authorize from current membership, but it must
        # honor workspace -> clock -> Run lock order. The audit FK would
        # otherwise request a workspace key-share lock after holding clock.
        if await session.scalar(select(WorkspaceRow.id).where(WorkspaceRow.id == target.workspace_id).with_for_update()) is None:
            return False
        sequence = await RunRepository._next_change_seq(session)
        row = await session.scalar(select(RunRow).where(RunRow.run_id == target.run_id).with_for_update())
        if row is None:
            return False
        try:
            exact = NativeRunStopTarget.from_row(row) == target
        except ValueError:
            exact = False
        if not exact or row.cancel_requested_at is None:
            return False
        operation = await session.scalar(select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.operation_id == target.operation_id).with_for_update())
        if operation is None or operation.kind != "run_stop" or operation.workspace_id != target.workspace_id or operation.user_id != target.user_id or operation.payload.get("target") != target.as_payload():
            return False
        if operation.state == "completed":
            return True
        now = datetime.now(UTC)
        if row.lease_expires_at is None or _aware(row.lease_expires_at) <= now:
            return False
        try:
            lifetime = await execution_lifetime(session, target, open_only=False)
        except ValueError:
            return False
        if evidence == "native_worker_closed" and lifetime.state != "completed":
            return False
        if operation.state != "pending" or (evidence == "native_not_started" and row.status != "pending") or row.status not in ("pending", "running", "interrupted", "error", "timeout"):
            return False
        row.status, row.updated_at, row.change_seq = "interrupted", now, sequence
        if evidence == "native_not_started":
            lifetime.state = "completed"
            lifetime.payload = {**lifetime.payload, "receipt": {"evidence": evidence, "owner_worker_id": target.owner_worker_id, "observed_at": now.isoformat()}}
        operation.state = "completed"
        operation.payload = {**operation.payload, "receipt": {"evidence": evidence, "owner_worker_id": target.owner_worker_id, "observed_at": now.isoformat()}}
        session.add(WorkspaceAuditEventRow(id=str(uuid4()), workspace_id=target.workspace_id, actor_user_id=None, action="run.execution_closed", resource_id=target.run_id, outcome="success", request_id=target.operation_id))
        await session.commit()
        return True
