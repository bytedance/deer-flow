"""Native transactional stop intents and lease-fenced receipt settlement.

No executor import, network IO, current-member capability or result publication.
Parent revocation remains pending until every resource domain has a handler.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, text

from deerflow.mcp.tasks.control import TaskControlTarget, TaskStopReceipt, canonical
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.workspaces.model import WorkspaceAuditEventRow, WorkspaceOperationOutboxRow

ACTIVE = ("submitted", "working", "input_required")


async def enqueue_task_stop(session, task, now):
    try:
        target = TaskControlTarget.from_row(task)
    except ValueError:
        # Preserve an explicit operator-visible uncertainty; never fabricate a
        # historical snapshot from today's membership or selected workspace.
        op = hashlib.sha256(canonical(["mcp_stop_invalid", task.id])).hexdigest()
        if await session.get(WorkspaceOperationOutboxRow, op) is None:
            session.add(
                WorkspaceOperationOutboxRow(operation_id=op, workspace_id=task.workspace_id, user_id=task.user_id, kind="mcp_stop", state="quarantine", payload={"version": 1, "task_id": task.id, "error": "missing_captured_identity"})
            )
    else:
        op = hashlib.sha256(canonical(["mcp_stop", target.digest])).hexdigest()
        if await session.get(WorkspaceOperationOutboxRow, op) is None:
            session.add(WorkspaceOperationOutboxRow(operation_id=op, workspace_id=target.workspace_id, user_id=target.user_id, kind="mcp_stop", state="pending", payload={"version": 1, "target": target.as_payload()}))
    if task.cancel_requested_at is None:
        task.cancel_requested_at = now
        task.next_cancel_at = now
        task.lease_owner = task.lease_token = task.lease_expires_at = None
        task.updated_at = now
    return op


async def enqueue_membership_revocation(session, workspace, member):
    """Called under the existing workspace lock BEFORE changing the version."""
    now = datetime.now(UTC)
    payload = {"version": 1, "membership_version": member.version, "policy_version": workspace.policy_version, "pending_domains": ["runs", "browser", "scheduler", "credentials", "mcp"]}
    op = hashlib.sha256(canonical(["workspace_revoke", workspace.id, member.user_id, member.version, workspace.policy_version])).hexdigest()
    if await session.get(WorkspaceOperationOutboxRow, op) is None:
        session.add(WorkspaceOperationOutboxRow(operation_id=op, workspace_id=workspace.id, user_id=member.user_id, kind="workspace_revoke", payload=payload, state="pending"))
    tasks = (await session.scalars(select(McpTaskRow).where(McpTaskRow.workspace_id == workspace.id, McpTaskRow.user_id == member.user_id, McpTaskRow.status.in_(ACTIVE)).order_by(McpTaskRow.id).with_for_update())).all()
    for task in tasks:
        # All active tasks under this actor are fenced. Earlier invalidated
        # versions also need cleanup; impossible future snapshots quarantine.
        try:
            target = TaskControlTarget.from_row(task)
            if target.workspace_context.membership_version > member.version or target.workspace_context.policy_version > workspace.policy_version:
                raise ValueError("future snapshot")
        except ValueError:
            task.cancel_requested_at = task.cancel_requested_at or now
            task.lease_owner = task.lease_token = task.lease_expires_at = None
            invalid = hashlib.sha256(canonical(["mcp_stop_invalid", task.id])).hexdigest()
            if await session.get(WorkspaceOperationOutboxRow, invalid) is None:
                session.add(
                    WorkspaceOperationOutboxRow(operation_id=invalid, workspace_id=workspace.id, user_id=member.user_id, kind="mcp_stop", state="quarantine", payload={"version": 1, "task_id": task.id, "error": "invalid_captured_identity"})
                )
            continue
        await enqueue_task_stop(session, task, now)


@dataclass(frozen=True, slots=True)
class StopClaim:
    operation_id: str
    owner: str
    token: str
    target: TaskControlTarget


def _aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class WorkspaceControlRepository:
    def __init__(self, session_factory):
        self._sf = session_factory

    async def _begin(self, session):
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))

    async def claim(self, *, now, owner, servers, lease_seconds=120, limit=8):
        if not servers or not 120 <= lease_seconds <= 3600 or not 1 <= limit <= 64:
            return []
        async with self._sf() as session:
            await self._begin(session)
            rows = (
                await session.scalars(
                    select(WorkspaceOperationOutboxRow)
                    .where(
                        WorkspaceOperationOutboxRow.kind == "mcp_stop",
                        WorkspaceOperationOutboxRow.state.in_(("pending", "claimed")),
                        or_(WorkspaceOperationOutboxRow.lease_expires_at.is_(None), WorkspaceOperationOutboxRow.lease_expires_at <= now),
                        WorkspaceOperationOutboxRow.payload["target"]["server_name"].as_string().in_(tuple(servers)),
                    )
                    .order_by(WorkspaceOperationOutboxRow.created_at, WorkspaceOperationOutboxRow.operation_id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            claims = []
            for row in rows:
                try:
                    target = TaskControlTarget.from_payload(row.payload["target"])
                    if row.payload.get("version") != 1 or row.workspace_id != target.workspace_id or row.user_id != target.user_id or row.operation_id != hashlib.sha256(canonical(["mcp_stop", target.digest])).hexdigest():
                        raise ValueError("outbox target mismatch")
                except (ValueError, TypeError, KeyError):
                    row.state = "quarantine"
                    continue
                row.state, row.lease_owner, row.lease_token = "claimed", owner, uuid4().hex
                row.lease_expires_at = now + timedelta(seconds=lease_seconds)
                row.attempt += 1
                claims.append(StopClaim(row.operation_id, owner, row.lease_token, target))
            await session.commit()
            return claims

    async def _owned(self, session, claim, now):
        row = await session.scalar(select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.operation_id == claim.operation_id).with_for_update())
        if row is None or row.kind != "mcp_stop" or row.state != "claimed" or row.lease_owner != claim.owner or row.lease_token != claim.token or row.lease_expires_at is None or _aware(row.lease_expires_at) <= now:
            return None
        if row.payload.get("target") != claim.target.as_payload():
            return None
        return row

    async def defer(self, claim, *, now, seconds=1):
        async with self._sf() as session:
            await self._begin(session)
            row = await self._owned(session, claim, now)
            if row is None:
                return False
            row.state, row.lease_owner, row.lease_token = "pending", None, None
            row.lease_expires_at = now + timedelta(seconds=min(60, max(1, seconds)))
            await session.commit()
            return True

    async def settle_stop(self, claim, receipt, *, now):
        if type(receipt) is not TaskStopReceipt or receipt.operation_id != claim.operation_id or receipt.target_sha256 != claim.target.digest or receipt.remote_task_id != claim.target.remote_task_id:
            raise ValueError("control receipt does not match original intent")
        async with self._sf() as session:
            await self._begin(session)
            row = await self._owned(session, claim, now)
            if row is None:
                return False
            task = await session.scalar(select(McpTaskRow).where(McpTaskRow.id == claim.target.task_id).with_for_update())
            compatible = task is None
            if task is not None:
                try:
                    compatible = TaskControlTarget.from_row(task) == claim.target and task.cancel_requested_at is not None and task.status in ACTIVE
                except ValueError:
                    compatible = False
            proof = asdict(receipt)
            proof["observed_at"] = receipt.observed_at.isoformat()
            row.payload = {**row.payload, "receipt": proof}
            row.state = "completed" if compatible else "quarantine"
            row.lease_owner = row.lease_token = row.lease_expires_at = None
            if compatible and task is not None:
                task.status = "cancelled"
                task.result = task.result_preview = task.result_artifact = task.input_required = None
                task.next_poll_at = task.next_cancel_at = None
                task.lease_owner = task.lease_token = task.lease_expires_at = None
                task.notification_status = "none"
                task.completed_at = task.updated_at = now
            session.add(
                WorkspaceAuditEventRow(
                    id=str(uuid4()), workspace_id=row.workspace_id, actor_user_id=None, action="mcp.stop_confirmed", resource_id=claim.target.task_id, outcome="success" if compatible else "quarantine", request_id=row.operation_id
                )
            )
            await session.commit()
            return compatible
