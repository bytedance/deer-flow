"""Private thread deletion fencing, not a second task/execution authority.

The native Run reservation owns admission. A persisted metadata tombstone keeps
that identity unavailable while external cleanup runs without writer locks.
Unknown cleanup stays fenced until verified-stop reconciliation is implemented.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, or_, select, text

from deerflow.persistence.feedback.model import FeedbackRow
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.models.run_event import RunEventRow, RunEventThreadSeqRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_events.model import ScheduledTaskEventRow
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.thread_meta.base import THREAD_DELETING_STATUS, THREAD_DELETION_METADATA_KEY
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.persistence.thread_reads.model import ThreadReadMarkerRow
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.workspaces.model import WorkspaceRow
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
from deerflow.runtime.user_context import AUTO, resolve_user_id


class ThreadDeletionBusy(RuntimeError):
    """Retained execution or an uncertain old cleanup prevents safe replay."""


@dataclass(frozen=True, slots=True)
class ThreadDeletionReceipt:
    workspace_id: str
    user_id: str
    thread_id: str
    incarnation: str
    token: str = field(repr=False)


class ThreadDeletionRepository:
    def __init__(self, threads: ThreadMetaRepository):
        self._threads = threads
        self._sf = threads._sf

    async def get(self, thread_id):
        owner = resolve_user_id(AUTO, method_name="ThreadDeletionRepository.get")
        context = self._threads._scope(owner)
        if context is None:
            raise WorkspaceAccessDenied("deletion requires workspace identity")
        async with self._sf() as session:
            row = await session.scalar(self._threads._owned_scope(select(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id), owner, context, include_deleting=True))
            if row is None or not row.incarnation:
                raise WorkspaceAccessDenied("private deletion source is unavailable")
            return self._threads._row_to_dict(row)

    @staticmethod
    async def _compatible_children(session, thread_id, workspace_id, user_id):
        for table in (RunRow, RunEventRow, ScheduledTaskEventRow):
            invalid = or_(table.workspace_id.is_(None), table.workspace_id != workspace_id, table.user_id.is_(None), table.user_id != user_id)
            if await session.scalar(select(table.thread_id).where(table.thread_id == thread_id, invalid).limit(1)) is not None:
                raise WorkspaceAccessDenied("incompatible thread child attribution")
        if await session.scalar(select(FeedbackRow.thread_id).where(FeedbackRow.thread_id == thread_id, or_(FeedbackRow.user_id.is_(None), FeedbackRow.user_id != user_id)).limit(1)) is not None:
            raise WorkspaceAccessDenied("incompatible feedback attribution")

    async def begin(self, thread_id, incarnation):
        owner = resolve_user_id(AUTO, method_name="ThreadDeletionRepository.begin")
        context = self._threads._scope(owner)
        if context is None:
            raise WorkspaceAccessDenied("deletion requires workspace identity")
        async with self._sf() as session:
            row = await self._threads._locked_row(session, thread_id, owner, context, include_deleting=True)
            if row is None or row.incarnation != incarnation:
                raise WorkspaceAccessDenied("deletion source changed")
            if row.status == THREAD_DELETING_STATUS:
                raise ThreadDeletionBusy("Deletion already started; verified recovery is required")
            await self._compatible_children(session, thread_id, context.workspace_id, owner)
            # Task terminal status alone is not physical STOP. M4 must provide
            # verified execution disposition before relaxing this refusal.
            if await session.scalar(select(McpTaskRow.id).where(McpTaskRow.thread_id == thread_id).limit(1)) is not None:
                raise ThreadDeletionBusy("Retained tool execution must be reconciled before deletion")
            if await session.scalar(select(ScheduledTaskRunRow.id).where(ScheduledTaskRunRow.thread_id == thread_id, ScheduledTaskRunRow.status.in_(("queued", "launching", "running"))).limit(1)) is not None:
                raise ThreadDeletionBusy("Scheduled work must finish before deletion")
            token = uuid4().hex
            row.status = THREAD_DELETING_STATUS
            row.metadata_json = {**(row.metadata_json or {}), THREAD_DELETION_METADATA_KEY: {"token": token, "phase": "cleanup_started"}}
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return ThreadDeletionReceipt(context.workspace_id, owner, thread_id, incarnation, token)

    async def finish(self, receipt):
        """Only captured cleanup authority; no live reads or new work granted."""
        if type(receipt) is not ThreadDeletionReceipt:
            raise WorkspaceAccessDenied("invalid deletion receipt")
        async with self._sf() as session:
            if session.get_bind().dialect.name == "sqlite":
                await session.execute(text("BEGIN IMMEDIATE"))
            if await session.scalar(select(WorkspaceRow.id).where(WorkspaceRow.id == receipt.workspace_id).with_for_update()) is None:
                raise WorkspaceAccessDenied("deletion workspace is unavailable")
            await session.scalar(select(UserRow.id).where(UserRow.id == receipt.user_id).with_for_update())
            row = await session.scalar(select(ThreadMetaRow).where(ThreadMetaRow.thread_id == receipt.thread_id, ThreadMetaRow.workspace_id == receipt.workspace_id, ThreadMetaRow.user_id == receipt.user_id).with_for_update())
            marker = (row.metadata_json or {}).get(THREAD_DELETION_METADATA_KEY) if row is not None else None
            if row is None or row.status != THREAD_DELETING_STATUS or row.incarnation != receipt.incarnation or not isinstance(marker, dict) or marker.get("token") != receipt.token:
                raise WorkspaceAccessDenied("deletion receipt no longer matches")
            await self._compatible_children(session, receipt.thread_id, receipt.workspace_id, receipt.user_id)
            for table in (RunRow, RunEventRow, ScheduledTaskEventRow):
                stmt = delete(table).where(table.thread_id == receipt.thread_id, table.workspace_id == receipt.workspace_id, table.user_id == receipt.user_id)
                if table is RunRow:
                    stmt = stmt.where(RunRow.operation_kind == "run")
                await session.execute(stmt)
            await session.execute(delete(RunEventThreadSeqRow).where(RunEventThreadSeqRow.thread_id == receipt.thread_id))
            await session.execute(delete(FeedbackRow).where(FeedbackRow.thread_id == receipt.thread_id, FeedbackRow.user_id == receipt.user_id))
            # All viewer markers refer to this globally reserved parent identity;
            # validate its receipt before clearing them, never blind repository GC.
            await session.execute(delete(ThreadReadMarkerRow).where(ThreadReadMarkerRow.thread_id == receipt.thread_id))
            await session.delete(row)
            await session.commit()
