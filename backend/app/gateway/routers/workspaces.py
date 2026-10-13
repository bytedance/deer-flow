"""Session-only workspace control plane; no tenant-content admin bypass."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.workspaces.dependencies import get_workspace_service, require_workspace_session, resolve_workspace_context
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
from deerflow.utils.file_io import await_drained

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=64)


@router.get("")
async def list_workspaces(request: Request):
    user = await require_workspace_session(request, action="read")
    return await get_workspace_service(request).repository.list_workspaces(str(user.id))


@router.get("/current")
async def current_workspace(request: Request):
    return asdict(await resolve_workspace_context(request))


@router.post("")
async def create_team(request: Request, body: TeamCreate):
    user = await require_workspace_session(request, action="write")
    try:
        return await await_drained(get_workspace_service(request).repository.create_team(str(user.id), body.name, body.idempotency_key))
    except WorkspaceAccessDenied:
        raise HTTPException(status_code=403, detail="Verified active account required") from None
    except ValueError:
        raise HTTPException(status_code=409, detail="Workspace request or idempotency conflict") from None
