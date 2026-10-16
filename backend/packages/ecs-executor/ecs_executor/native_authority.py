"""Read native admission authority without creating a parallel task authority."""

from contextlib import nullcontext
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.engine import Connection

from deerflow.authz.workspace import WorkspaceContext
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
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

    def resolve(self, identity):
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
                RunRow.status == "running",
                RunRow.cancel_action.is_(None),
                RunRow.owner_worker_id.is_not(None),
                RunRow.owner_worker_id != "",
                or_(RunRow.lease_expires_at.is_(None), RunRow.lease_expires_at > datetime.now(UTC)),
                ThreadMetaRow.user_id == identity.user_id,
                ThreadMetaRow.incarnation == identity.incarnation,
                ThreadMetaRow.workspace_id == RunRow.workspace_id,
                ThreadMetaRow.status != "deleting",
                or_(ThreadMetaRow.project_id.is_(None), project),
            )
        )
        if not identity.incarnation:
            raise PermissionError("Native submission parent identity is unavailable")
        with nullcontext(self.engine) if isinstance(self.engine, Connection) else self.engine.connect() as connection:
            row = connection.execute(statement).first()
        if row is None:
            raise PermissionError("Native submission authority is unavailable")
        try:
            captured = WorkspaceContext(**row.workspace_context_json)
            live = WorkspaceContext(row.workspace_id, identity.user_id, row.membership_version, row.policy_version)
        except (TypeError, ValueError):
            raise PermissionError("Native submission captured authority is invalid") from None
        if captured != live:
            raise PermissionError("Native submission captured authority changed")
        return live
