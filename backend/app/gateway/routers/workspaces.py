"""Session-only workspace control plane; no tenant-content admin bypass."""

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.gateway.auth.password import verify_password_async
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


class MemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(pattern="^(admin|member)$")


class OwnershipTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_owner_user_id: UUID
    # Bounds are checked with a generic error, without echoing a password in
    # FastAPI's validation input payload. SecretStr also masks model repr.
    reauth_password: SecretStr


async def _control_context(request, workspace_id, *, action):
    user = await require_workspace_session(request, action=action)
    selector = str(workspace_id)
    selected = request.headers.get("X-Deerflow-Workspace")
    if selected is not None and selected != selector:
        raise HTTPException(status_code=404, detail="Workspace not found")
    service = get_workspace_service(request)
    context = await service.resolve_context(str(user.id), selector)
    member = await service.revalidate(context)
    return user, service, context, member


@router.get("/{workspace_id}/members")
async def list_members(request: Request, workspace_id: UUID):
    user, service, _, _ = await _control_context(request, workspace_id, action="read")
    return await service.repository.list_active_members(str(workspace_id), str(user.id))


@router.patch("/{workspace_id}/members/{user_id}")
async def change_member_role(request: Request, workspace_id: UUID, user_id: UUID, body: MemberRoleUpdate):
    actor, service, context, member = await _control_context(request, workspace_id, action="write")
    if member["role"] != "owner":
        raise HTTPException(status_code=403, detail="Only owner may assign team roles")
    if str(user_id) == str(actor.id):
        raise HTTPException(status_code=409, detail="Owner cannot be demoted directly")
    try:
        return await await_drained(service.repository.change_role(str(workspace_id), str(actor.id), str(user_id), role=body.role, expected_context=context))
    except WorkspaceAccessDenied:
        raise HTTPException(status_code=403, detail="Membership transition refused") from None


@router.delete("/{workspace_id}/members/{user_id}")
async def remove_member(request: Request, workspace_id: UUID, user_id: UUID):
    actor, service, context, member = await _control_context(request, workspace_id, action="write")
    if str(actor.id) == str(user_id) and member["role"] == "owner":
        raise HTTPException(status_code=409, detail="Owner must transfer or close the team")
    try:
        return await await_drained(service.repository.remove_member(str(workspace_id), str(actor.id), str(user_id), expected_context=context))
    except WorkspaceAccessDenied:
        raise HTTPException(status_code=403, detail="Membership transition refused") from None


@router.post("/{workspace_id}/leave")
async def leave_workspace(request: Request, workspace_id: UUID):
    actor = await require_workspace_session(request, action="write")
    return await remove_member(request, workspace_id, actor.id)


@router.post("/{workspace_id}/ownership-transfer")
async def transfer_workspace_owner(request: Request, workspace_id: UUID, body: OwnershipTransfer):
    actor, service, context, member = await _control_context(request, workspace_id, action="write")
    if member["role"] != "owner":
        raise HTTPException(status_code=403, detail="Only owner may transfer team ownership")
    if str(body.new_owner_user_id) == str(actor.id):
        raise HTTPException(status_code=409, detail="Transfer requires a different active member")
    if actor.password_hash is None:
        raise HTTPException(status_code=409, detail="SSO reauthentication proof required")
    password = body.reauth_password.get_secret_value()
    if not 0 < len(password) <= 1024 or not await verify_password_async(password, actor.password_hash):
        raise HTTPException(status_code=401, detail="Reauthentication failed")
    try:
        return await await_drained(
            service.repository.transfer_owner(str(workspace_id), str(actor.id), str(body.new_owner_user_id), expected_context=context, expected_token_version=actor.token_version, expected_password_hash=actor.password_hash)
        )
    except WorkspaceAccessDenied:
        raise HTTPException(status_code=403, detail="Ownership transition refused") from None
