"""Operator-managed onboarding using the same native workspace provisioner."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.deps import require_admin_user
from app.gateway.workspaces.dependencies import get_workspace_service, require_workspace_session
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
from deerflow.utils.file_io import await_drained

router = APIRouter(prefix="/api/admin/workspaces", tags=["admin-workspaces"])


class ManagedWorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_user_id: UUID
    kind: Literal["personal", "team"]
    name: str | None = Field(default=None, min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=64)


@router.post("")
async def provision_workspace(request: Request, body: ManagedWorkspaceCreate):
    await require_workspace_session(request, action="write")
    await require_admin_user(request, detail="Workspace provisioning requires platform administrator")
    repository = get_workspace_service(request).repository
    try:
        if body.kind == "personal":
            return await await_drained(repository.provision_personal(str(body.owner_user_id)))
        return await await_drained(repository.create_team(str(body.owner_user_id), body.name, body.idempotency_key))
    except WorkspaceAccessDenied:
        raise HTTPException(status_code=409, detail="Owner requires an active verified account") from None
    except ValueError:
        raise HTTPException(status_code=409, detail="Workspace request or idempotency conflict") from None
