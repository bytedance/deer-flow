"""Projects router for organizing threads into folders.

Provides user-scoped project CRUD: list, create, rename, delete.
All endpoints require JWT authentication.
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.gateway.auth.middleware import get_current_user
from src.gateway.auth.project_store import (
    assign_thread_to_project,
    create_project,
    delete_project,
    get_user_projects,
    rename_project,
)
from src.gateway.rate_limiter import check_user_api_rate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ── Pydantic Models ──────────────────────────────────────────────────────────


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ProjectRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ProjectResponse(BaseModel):
    project_id: str
    name: str
    thread_count: int
    created_at: str
    updated_at: str = ""


class ThreadAssignRequest(BaseModel):
    project_id: str | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("")
async def list_projects(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[ProjectResponse]:
    """List all projects for the authenticated user."""
    user_id = current_user["id"]
    check_user_api_rate(user_id)

    try:
        projects = get_user_projects(user_id)
        return [ProjectResponse(**p) for p in projects]
    except Exception as e:
        logger.error(f"Error listing projects for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list projects: {str(e)}")


@router.post("", status_code=201)
async def create_project_endpoint(
    request: ProjectCreateRequest,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> ProjectResponse:
    """Create a new project."""
    user_id = current_user["id"]
    check_user_api_rate(user_id)

    project_id = uuid.uuid4().hex[:16]
    success = create_project(project_id, user_id, request.name)
    if not success:
        raise HTTPException(status_code=409, detail="A project with this name already exists")

    logger.info(f"Created project '{request.name}' ({project_id}) for user {user_id}")
    return ProjectResponse(
        project_id=project_id,
        name=request.name,
        thread_count=0,
        created_at="",
    )


@router.patch("/{project_id}")
async def rename_project_endpoint(
    project_id: str,
    request: ProjectRenameRequest,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, bool]:
    """Rename a project."""
    user_id = current_user["id"]
    check_user_api_rate(user_id)

    success = rename_project(project_id, user_id, request.name)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found or duplicate name")

    logger.info(f"Renamed project {project_id} to '{request.name}'")
    return {"success": True}


@router.delete("/{project_id}")
async def delete_project_endpoint(
    project_id: str,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, bool]:
    """Delete a project. Associated threads move to Default."""
    user_id = current_user["id"]
    check_user_api_rate(user_id)

    success = delete_project(project_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")

    logger.info(f"Deleted project {project_id} for user {user_id}")
    return {"success": True}
