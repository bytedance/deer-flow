"""Live native SQL scope predicates and write fencing for resource repositories."""

from sqlalchemy import select

from deerflow.authz.workspace import WorkspaceContext, get_current_workspace
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.workspaces.model import WorkspaceMembershipRow, WorkspaceRow
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied, WorkspaceRepository


def resolve_resource_scope(context, actor_user_id, *, required):
    context = context if context is not None else get_current_workspace()
    if context is None:
        if required:
            raise WorkspaceAccessDenied("workspace scope is required")
        return None
    if type(context) is not WorkspaceContext or context.actor_user_id != actor_user_id:
        raise WorkspaceAccessDenied("workspace actor does not match resource caller")
    return context


def live_workspace_predicate(context):
    return (
        WorkspaceRepository._membership_query(context.actor_user_id)
        .where(WorkspaceRow.id == context.workspace_id, WorkspaceRow.policy_version == context.policy_version, WorkspaceMembershipRow.version == context.membership_version)
        .correlate(None)
        .exists()
    )


class WorkspaceRoleDenied(PermissionError):
    """A live member lacks the role required for explicit shared writes."""


def shared_workspace_predicate(context, *, write=False):
    query = WorkspaceRepository._membership_query(context.actor_user_id).where(
        WorkspaceRow.id == context.workspace_id,
        WorkspaceRow.kind == "team",
        WorkspaceRow.policy_version == context.policy_version,
        WorkspaceMembershipRow.version == context.membership_version,
    )
    if write:
        query = query.where(WorkspaceMembershipRow.role.in_(("owner", "admin")))
    return query.correlate(None).exists()


async def require_shared_write(session, context):
    if context is None or not await session.scalar(select(shared_workspace_predicate(context, write=True))):
        raise WorkspaceRoleDenied("Shared projects require an active team owner or admin")


async def lock_resource_scope(session, context):
    # Workspace mutations use this order too. Re-read membership only after
    # taking the workspace lock, so a waiting writer sees any revocation.
    await WorkspaceRepository._begin_write(session)
    workspace = await session.scalar(select(WorkspaceRow.id).where(WorkspaceRow.id == context.workspace_id).with_for_update())
    if workspace is None:
        raise WorkspaceAccessDenied("resource workspace is unavailable")
    await session.scalar(select(UserRow.id).where(UserRow.id == context.actor_user_id).with_for_update())
    if not await session.scalar(select(live_workspace_predicate(context))):
        raise WorkspaceAccessDenied("resource workspace authorization changed")
