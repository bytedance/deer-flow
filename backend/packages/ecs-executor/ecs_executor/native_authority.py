"""Read native admission authority without creating a parallel task authority."""

from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime

from sqlalchemy import inspect, or_, select, text
from sqlalchemy.engine import Connection

from deerflow.authz.workspace import WorkspaceContext
from deerflow.mcp.tasks import POLLABLE_TASK_STATUSES
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.workspaces.model import WorkspaceMembershipRow, WorkspaceRow
from deerflow.persistence.workspaces.sql import WorkspaceRepository


class NativeSubmissionAuthority:
    """Short-lived preflight only; a later physical action must reauthorize.

    Resolves from native Run/thread/member records in one SQL statement. Never
    uses a browser selection, task-local context or the token's workspace JSON.
    Caller-owned connections remain caller-owned, including their transaction.
    """

    def __init__(self, engine):
        self.engine = engine

    def validate_mode(self, *, workspace_required):
        """Read-only native schema/downgrade fence, independent of request claims."""
        with self.engine.connect() as connection:
            inspector = inspect(connection)
            if workspace_required:
                versions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all() if inspector.has_table("alembic_version") else []
                if versions != ["0040_mcp_workspace_identity"]:
                    raise ValueError("Native workspace schema is incompatible with this execution receiver")
            elif inspector.has_table("workspaces"):
                if connection.execute(select(WorkspaceRow.id).where(WorkspaceRow.kind == "team").limit(1)).first() is not None:
                    raise ValueError("Native workspace data requires workspace authorization; legacy B startup refused")

    def _statement(self, identity, *, running):
        memberships = WorkspaceRepository._membership_query(identity.user_id).with_only_columns(WorkspaceRow.id.label("workspace_id"), WorkspaceRow.policy_version, WorkspaceMembershipRow.version.label("membership_version")).subquery()
        project = select(ProjectRow.id).where(ProjectRow.id == ThreadMetaRow.project_id, ProjectRow.workspace_id == RunRow.workspace_id).correlate(ThreadMetaRow, RunRow).exists()
        statement = (
            select(RunRow.workspace_context_json, RunRow.workspace_id, memberships.c.membership_version, memberships.c.policy_version)
            .join(ThreadMetaRow, ThreadMetaRow.thread_id == RunRow.thread_id)
            .join(memberships, memberships.c.workspace_id == RunRow.workspace_id)
            .where(
                RunRow.run_id == identity.run_id,
                RunRow.user_id == identity.user_id,
                RunRow.thread_id == identity.thread_id,
                RunRow.thread_incarnation == identity.incarnation,
                RunRow.operation_kind == "run",
                ThreadMetaRow.user_id == identity.user_id,
                ThreadMetaRow.incarnation == identity.incarnation,
                ThreadMetaRow.workspace_id == RunRow.workspace_id,
                ThreadMetaRow.status != "deleting",
                or_(ThreadMetaRow.project_id.is_(None), project),
            )
        )
        if running:
            statement = statement.where(
                RunRow.status == "running", RunRow.cancel_action.is_(None), RunRow.owner_worker_id.is_not(None), RunRow.owner_worker_id != "", or_(RunRow.lease_expires_at.is_(None), RunRow.lease_expires_at > datetime.now(UTC))
            )
        if not identity.incarnation:
            raise PermissionError("Native submission parent identity is unavailable")
        return statement

    def _read(self, statement):
        with nullcontext(self.engine) if isinstance(self.engine, Connection) else self.engine.connect() as connection:
            row = connection.execute(statement).first()
        if row is None:
            raise PermissionError("Native execution authority is unavailable")
        return row

    @staticmethod
    def _context(row, user_id):
        try:
            captured = WorkspaceContext(**row.workspace_context_json)
            live = WorkspaceContext(row.workspace_id, user_id, row.membership_version, row.policy_version)
        except (TypeError, ValueError):
            raise PermissionError("Native submission captured authority is invalid") from None
        if captured != live:
            raise PermissionError("Native submission captured authority changed")
        return live

    def resolve(self, identity):
        return self._context(self._read(self._statement(identity, running=True)), identity.user_id)

    def resolve_task(self, job, server_name, *, require_active=False):
        """Authorize the original committed native task, even after source Run ends.

        A task receipt is not invented from the physical ledger or selected UI.
        Admission to physical work additionally requires an uncancelled pollable
        task; terminal result reads can retain the original durable receipt.
        """
        from ecs_executor.scope import ExecutionIdentity

        identity = ExecutionIdentity(job["user_id"], job["thread_id"], job["incarnation"], job["run_id"])
        statement = (
            self._statement(identity, running=False)
            .add_columns(McpTaskRow.workspace_context_json.label("task_snapshot"))
            .join(McpTaskRow, McpTaskRow.run_id == RunRow.run_id)
            .where(
                McpTaskRow.remote_task_id == job["id"],
                McpTaskRow.server_name == server_name,
                McpTaskRow.user_id == identity.user_id,
                McpTaskRow.thread_id == identity.thread_id,
                McpTaskRow.thread_incarnation == identity.incarnation,
                McpTaskRow.workspace_id == RunRow.workspace_id,
            )
        )
        if require_active:
            statement = statement.where(McpTaskRow.status.in_([status.value for status in POLLABLE_TASK_STATUSES]), McpTaskRow.cancel_requested_at.is_(None))
        row = self._read(statement)
        live = self._context(row, identity.user_id)
        try:
            task_scope = WorkspaceContext(**row.task_snapshot)
            job_scope = WorkspaceContext(**job["workspace_context"])
        except (KeyError, TypeError, ValueError):
            raise PermissionError("Native task or execution snapshot is unavailable") from None
        if task_scope != live or job_scope != live or job.get("workspace_id") != live.workspace_id:
            raise PermissionError("Native task or execution identity changed")
        return live

    @contextmanager
    def fence(self, job, server_name, *, require_active=True):
        """Serialize short intent/result writes with native revocation.

        No Docker/HTTP operation may execute inside this context. Scope/actor/
        private-parent/source/task lock order matches native resource writers.
        A committed start intent precedes the external start; later revocation
        requires control-only STOP and never authorizes result publication.
        """
        try:
            context = WorkspaceContext(**job["workspace_context"])
        except (KeyError, TypeError, ValueError):
            raise PermissionError("Physical execution requires original captured scope") from None
        with self.engine.connect() as connection:
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            try:
                connection.execute(select(WorkspaceRow.id).where(WorkspaceRow.id == context.workspace_id).with_for_update()).first()
                connection.execute(select(UserRow.id).where(UserRow.id == context.actor_user_id).with_for_update()).first()
                connection.execute(select(ThreadMetaRow.thread_id).where(ThreadMetaRow.thread_id == job["thread_id"]).with_for_update()).first()
                connection.execute(select(RunRow.run_id).where(RunRow.run_id == job["run_id"]).with_for_update()).first()
                connection.execute(select(McpTaskRow.id).where(McpTaskRow.user_id == job["user_id"], McpTaskRow.server_name == server_name, McpTaskRow.remote_task_id == job["id"]).with_for_update()).first()
                resolved = NativeSubmissionAuthority(connection).resolve_task(job, server_name, require_active=require_active)
                yield resolved
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
