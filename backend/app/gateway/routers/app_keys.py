"""Platform-admin App-Key control-plane API."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app.gateway.deps import require_admin_user
from deerflow.persistence.app_keys import AppKeyRepository
from deerflow.persistence.engine import get_session_factory

router = APIRouter(prefix="/api/v1/app-keys", tags=["app-keys"])
_ADMIN_REQUIRED = "Administrator privileges are required to manage App Keys"


class ProfileCreateRequest(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    agents: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    tool_groups: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class CredentialCreateRequest(BaseModel):
    expires_at: datetime | None = None


class ProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    disabled: bool | None = None
    agents: list[str] | None = None
    models: list[str] | None = None
    skills: list[str] | None = None
    tool_groups: list[str] | None = None
    tools: list[str] | None = None


def _repo() -> AppKeyRepository:
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return AppKeyRepository(sf)


@router.get("/profiles")
async def list_profiles(request: Request):
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    return {"profiles": await _repo().list_profiles()}


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(request: Request, body: ProfileCreateRequest):
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    try:
        return await _repo().create_profile(
            app_id=body.id,
            name=body.name,
            description=body.description,
            capabilities=body.model_dump(include={"agents", "models", "skills", "tool_groups", "tools"}),
            actor_user_id=str(request.state.user.id),
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="App profile already exists") from exc


@router.get("/profiles/{app_id}")
async def get_profile(app_id: str, request: Request):
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    profile = await _repo().get_profile(app_id, include_disabled=True)
    if profile is None:
        raise HTTPException(status_code=404, detail="App profile not found")
    return profile


@router.patch("/profiles/{app_id}")
async def update_profile(app_id: str, request: Request, body: ProfileUpdateRequest):
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    fields = body.model_dump(exclude_unset=True)
    capability_names = {"agents", "models", "skills", "tool_groups", "tools"}
    capabilities = {name: fields[name] for name in capability_names if name in fields}
    try:
        profile = await _repo().update_profile(
            app_id,
            name=fields.get("name"),
            description=fields.get("description"),
            disabled=fields.get("disabled"),
            capabilities=capabilities or None,
            actor_user_id=str(request.state.user.id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if profile is None:
        raise HTTPException(status_code=404, detail="App profile not found")
    return profile


@router.post("/profiles/{app_id}/credentials", status_code=status.HTTP_201_CREATED)
async def generate_credential(app_id: str, request: Request, body: CredentialCreateRequest):
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    credential = await _repo().generate_credential(app_id, actor_user_id=str(request.state.user.id), expires_at=body.expires_at)
    if credential is None:
        raise HTTPException(status_code=404, detail="Active app profile not found")
    return credential


@router.delete("/credentials/{key_hash}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_credential(key_hash: str, request: Request):
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    if not await _repo().revoke_credential(key_hash, actor_user_id=str(request.state.user.id)):
        raise HTTPException(status_code=404, detail="Active credential not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
