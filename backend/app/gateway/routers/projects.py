"""CRUD API for projects (Phase 1: organization only — no documents/trash)."""

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from app.gateway.authz import require_permission
from app.gateway.deps import get_project_repo, get_thread_store
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


@router.post("", response_model=ProjectResponse, status_code=201)
@require_permission("projects", "write")
async def create_project(body: ProjectCreateRequest, request: Request) -> ProjectResponse:
    repo = get_project_repo(request)
    return _to_response(await repo.create(name=body.name, instructions=body.instructions, presentation=body.presentation))


@router.get("", response_model=ProjectListResponse)
@require_permission("projects", "read")
async def list_projects(request: Request, status: ProjectStatus | None = None) -> ProjectListResponse:
    repo = get_project_repo(request)
    return ProjectListResponse(projects=[_to_response(r) for r in await repo.list(status=status)])


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
