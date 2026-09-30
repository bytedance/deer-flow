"""CRUD API for projects (Phase 1: organization only — no documents/trash)."""

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from app.gateway.authz import require_permission
from app.gateway.deps import get_config, get_project_repo, get_thread_store
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.projects_config import ProjectsConfig
from deerflow.runtime.secret_context import redact_metadata_secrets
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])

ProjectStatus = Literal["active", "archived"]


class ProjectResponse(BaseModel):
    id: str
    name: str
    instructions: str
    presentation: dict
    status: str
    created_at: str
    updated_at: str


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    instructions: str = ""
    presentation: dict = Field(default_factory=dict)


class ProjectPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    instructions: str | None = None
    presentation: dict | None = None


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]


class ProjectsConfigResponse(BaseModel):
    """The projects-block knobs the UI needs before it can validate client-side."""

    instructions_max_bytes: int
    trash_retention_days: int


class ProjectThreadResponse(BaseModel):
    """A thread row from ``GET /api/projects/{id}/threads``.

    Deliberately narrow — only the fields ``ProjectThread`` declares in
    ``frontend/src/core/projects/types.ts``. Store rows carry ownership
    columns (``user_id``, ``assistant_id``) and ``ThreadMetaRow`` may grow;
    without this model those would leak onto the wire and the route's
    OpenAPI schema stays empty. Metadata is redacted here exactly as the
    surrounding thread endpoints redact it via ``_MetadataRedactingResponse``.
    """

    thread_id: str
    display_name: str | None = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before", check_fields=False)
    @classmethod
    def _redact_metadata_secrets(cls, value: Any) -> Any:
        return redact_metadata_secrets(value)


def _to_response(row: dict) -> ProjectResponse:
    return ProjectResponse(
        id=row["id"],
        name=row["name"],
        instructions=row.get("instructions", ""),
        presentation=row.get("presentation") or {},
        status=row["status"],
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )


def _not_found() -> HTTPException:
    # Fail closed: foreign projects are indistinguishable from missing ones.
    return HTTPException(status_code=404, detail="Project not found")


def _projects_config() -> ProjectsConfig:
    """Projects config, falling back to defaults when the app config is unavailable."""
    try:
        return get_app_config().projects
    except (FileNotFoundError, RuntimeError):
        return ProjectsConfig()


def _validate_instructions_length(instructions: str | None) -> None:
    """Reject oversized instructions with 422 — never truncate (spec §6.5/§11).

    The cap counts UTF-8 bytes, so multi-byte characters cost their encoded
    length rather than one character each.
    """
    if instructions is None:
        return
    max_bytes = _projects_config().instructions_max_bytes
    if len(instructions.encode("utf-8")) > max_bytes:
        raise HTTPException(status_code=422, detail=f"instructions exceeds the configured {max_bytes}-byte UTF-8 limit")


@router.post("", response_model=ProjectResponse, status_code=201)
@require_permission("projects", "write")
async def create_project(body: ProjectCreateRequest, request: Request) -> ProjectResponse:
    _validate_instructions_length(body.instructions)
    repo = get_project_repo(request)
    return _to_response(await repo.create(name=body.name, instructions=body.instructions, presentation=body.presentation))


@router.get("", response_model=ProjectListResponse)
@require_permission("projects", "read")
async def list_projects(request: Request, status: ProjectStatus | None = None) -> ProjectListResponse:
    repo = get_project_repo(request)
    return ProjectListResponse(projects=[_to_response(r) for r in await repo.list(status=status)])


@router.get("/config", response_model=ProjectsConfigResponse)
@require_permission("projects", "read")
async def get_projects_config(request: Request, config: AppConfig = Depends(get_config)) -> ProjectsConfigResponse:
    """Projects config for the UI (instructions byte cap, trash retention).

    Declared before ``/{project_id}`` so ``config`` is never swallowed as a
    project id. Values come from the live ``projects`` config block; when the
    block is absent the ``ProjectsConfig`` defaults apply.
    """
    return ProjectsConfigResponse(
        instructions_max_bytes=config.projects.instructions_max_bytes,
        trash_retention_days=config.projects.trash_retention_days,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
@require_permission("projects", "read")
async def get_project(project_id: str, request: Request) -> ProjectResponse:
    row = await get_project_repo(request).get(project_id)
    if row is None:
        raise _not_found()
    return _to_response(row)


@router.patch("/{project_id}", response_model=ProjectResponse)
@require_permission("projects", "write")
async def patch_project(project_id: str, body: ProjectPatchRequest, request: Request) -> ProjectResponse:
    _validate_instructions_length(body.instructions)
    row = await get_project_repo(request).patch(project_id, name=body.name, instructions=body.instructions, presentation=body.presentation)
    if row is None:
        raise _not_found()
    return _to_response(row)


@router.post("/{project_id}/archive", response_model=ProjectResponse)
@require_permission("projects", "write")
async def archive_project(project_id: str, request: Request) -> ProjectResponse:
    row = await get_project_repo(request).set_status(project_id, "archived")
    if row is None:
        raise _not_found()
    return _to_response(row)


@router.post("/{project_id}/restore", response_model=ProjectResponse)
@require_permission("projects", "write")
async def restore_project(project_id: str, request: Request) -> ProjectResponse:
    row = await get_project_repo(request).set_status(project_id, "active")
    if row is None:
        raise _not_found()
    return _to_response(row)


@router.delete("/{project_id}", status_code=204)
@require_permission("projects", "delete")
async def delete_project(project_id: str, request: Request) -> None:
    if not await get_project_repo(request).delete(project_id):
        raise _not_found()


@router.get("/{project_id}/threads", response_model=list[ProjectThreadResponse])
@require_permission("projects", "read")
@require_permission("threads", "read")
async def list_project_threads(project_id: str, request: Request, limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0)) -> list[ProjectThreadResponse]:
    if await get_project_repo(request).get(project_id) is None:
        raise _not_found()
    # Active members only, mirroring the sidebar's `archived: false` lists:
    # an archived chat leaves the project's pages the same way it leaves the
    # sidebar and returns only via the global Archived tab.
    rows = await get_thread_store(request).search(
        project_id=project_id,
        archived=False,
        limit=limit,
        offset=offset,
    )
    return [
        ProjectThreadResponse(
            thread_id=r["thread_id"],
            display_name=r.get("display_name"),
            created_at=coerce_iso(r.get("created_at", "")),
            updated_at=coerce_iso(r.get("updated_at", "")),
            metadata=r.get("metadata", {}),
        )
        for r in rows
    ]
