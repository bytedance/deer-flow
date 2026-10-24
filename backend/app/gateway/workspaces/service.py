"""Live workspace identity and native-permission/resource-ACL intersection."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException

from app.gateway.authz import AuthContext
from deerflow.authz.workspace import WorkspaceContext


def _missing():
    return HTTPException(status_code=404, detail="Workspace or resource not found")


class WorkspaceService:
    def __init__(self, repository):
        self.repository = repository

    async def resolve_context(self, actor_user_id, selector=None):
        if selector is None:
            personal = [row for row in await self.repository.list_workspaces(actor_user_id) if row["kind"] == "personal"]
            if len(personal) != 1:
                raise _missing()
            selector = personal[0]["id"]
        try:
            if not isinstance(selector, str) or str(UUID(selector)) != selector:
                raise ValueError
        except (ValueError, TypeError):
            raise _missing() from None
        member = await self.repository.get_active_membership(selector, actor_user_id)
        if member is None:
            raise _missing()
        return WorkspaceContext(workspace_id=selector, actor_user_id=actor_user_id, membership_version=member["membership_version"], policy_version=member["policy_version"])

    async def revalidate(self, context):
        if type(context) is not WorkspaceContext:
            raise _missing()
        member = await self.repository.get_active_membership(context.workspace_id, context.actor_user_id)
        if member is None or member["membership_version"] != context.membership_version or member["policy_version"] != context.policy_version:
            raise _missing()
        return member

    async def authorize_resource(self, context, auth, *, resource_workspace_id, owner_user_id, visibility, action, native_permission):
        if not isinstance(auth, AuthContext) or auth.user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if type(context) is not WorkspaceContext or context.actor_user_id != str(auth.user.id):
            raise _missing()
        member = await self.revalidate(context)
        if resource_workspace_id != context.workspace_id:
            raise _missing()
        if action not in ("read", "write", "delete") or native_permission.rsplit(":", 1)[-1] != action or native_permission not in auth.permissions:
            raise HTTPException(status_code=403, detail="Native permission denied")
        if visibility == "private":
            if owner_user_id != context.actor_user_id:
                raise _missing()
        elif visibility == "workspace":
            if action != "read" and member["role"] not in ("owner", "admin"):
                raise HTTPException(status_code=403, detail="Workspace role denied")
        else:
            raise _missing()
        return member
