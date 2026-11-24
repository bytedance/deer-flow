"""Session-authorized task execution shared by coordination entry points."""

from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated

from deerflow_extension_api.agent_runs import AgentRunError
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

from app.gateway.authz import require_permission
from app.gateway.coordination_workers import worker_context, worker_error
from deerflow.persistence.coordination.model import TaskStatus
from deerflow.persistence.coordination.sql import TaskConflict, TaskNotFound
from deerflow.utils.file_io import await_drained

router = APIRouter(prefix="/api/coordination/tasks", tags=["coordination"])
RequestId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
TaskText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16384)]


class WorkerRunSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recursion_limit: int | None = Field(default=None, strict=True, ge=1)
    thinking_enabled: StrictBool | None = None
    is_plan_mode: StrictBool | None = None


class CreateWorkerTask(BaseModel):
    request_id: RequestId
    objective: TaskText
    assistant_id: str = Field(default="lead_agent", min_length=1, max_length=128)
    project_id: str | None = Field(default=None, min_length=1, max_length=64)
    run: WorkerRunSettings | None = None


class WorkerInput(BaseModel):
    request_id: RequestId
    content: TaskText


class CancelTask(BaseModel):
    expected_revision: int = Field(ge=0)


@router.post("")
@require_permission("runs", "create")
async def create_worker_task(body: CreateWorkerTask, request: Request):
    service, owner, runs = worker_context(request)

    async def dispatch():
        task = await service.repo.create(
            owner,
            request_id=body.request_id,
            objective=body.objective,
            project_id=body.project_id,
            run_settings=body.run.model_dump(exclude_none=True) if body.run is not None else None,
        )
        return await service.dispatch(runs, owner, task["id"], body.assistant_id)

    try:
        return await await_drained(dispatch())
    except (TaskConflict, TaskNotFound, AgentRunError) as exc:
        raise worker_error(exc) from exc


@router.get("/{task_id}")
@require_permission("runs", "read")
async def get_worker_task(task_id: str, request: Request):
    service, owner, _runs = worker_context(request)
    try:
        return await service.view(owner, task_id)
    except TaskNotFound as exc:
        raise HTTPException(404, "Task not found") from exc


@router.post("/{task_id}/inputs")
@require_permission("runs", "create")
async def add_worker_input(task_id: str, body: WorkerInput, request: Request):
    service, owner, _runs = worker_context(request)
    try:
        return await service.submit_input(owner, task_id, request_id="input:" + sha256(body.request_id.encode()).hexdigest(), content=body.content)
    except (TaskNotFound, TaskConflict, AgentRunError) as exc:
        raise worker_error(exc) from exc


@router.get("/{task_id}/inputs")
@require_permission("runs", "read")
async def list_worker_inputs(task_id: str, request: Request, after: int = Query(0, ge=0, le=2**63 - 1), limit: int = Query(100, ge=1, le=100)):
    service, owner, _runs = worker_context(request)
    try:
        return await service.repo.list_worker_inputs(owner, task_id, after=after, limit=limit)
    except TaskNotFound as exc:
        raise HTTPException(404, "Task not found") from exc


@router.post("/{task_id}/cancel", responses={202: {"description": "Cancellation is still in progress"}})
@require_permission("runs", "cancel")
async def cancel_worker_task(task_id: str, body: CancelTask, request: Request, response: Response):
    service, owner, runs = worker_context(request)
    try:
        task = await await_drained(service.cancel(runs, owner, task_id, body.expected_revision))
    except (TaskConflict, TaskNotFound, AgentRunError) as exc:
        raise worker_error(exc) from exc
    if task["status"] == TaskStatus.CANCELLING:
        response.status_code = 202
    return task


@router.put("/{task_id}/authorization")
@require_permission("runs", "create")
async def authorize_worker_task(task_id: str, request: Request):
    service, owner, runs = worker_context(request)
    try:
        return await service.authorize(runs, owner, task_id)
    except (TaskNotFound, TaskConflict, AgentRunError) as exc:
        raise worker_error(exc) from exc


@router.delete("/{task_id}/authorization", status_code=204)
@require_permission("runs", "cancel")
async def revoke_worker_task(task_id: str, request: Request):
    service, owner, _runs = worker_context(request)
    try:
        await service.repo.set_grant(owner, task_id, None)
    except (TaskNotFound, TaskConflict) as exc:
        raise worker_error(exc) from exc
    return Response(status_code=204)


@router.get("/{task_id}/artifacts")
@require_permission("threads", "read")
async def list_worker_artifacts(task_id: str, request: Request, limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)):
    service, owner, _runs = worker_context(request)
    try:
        return await service.repo.list_artifacts(owner, task_id, limit=limit, offset=offset)
    except TaskNotFound as exc:
        raise HTTPException(404, "Task not found") from exc


@router.get("/{task_id}/artifacts/{artifact_id}")
@require_permission("threads", "read")
async def download_worker_artifact(task_id: str, artifact_id: str, request: Request):
    from app.gateway.routers.artifacts import _build_content_disposition

    service, owner, _runs = worker_context(request)
    try:
        path, content = await service.repo.read_artifact(owner, task_id, artifact_id)
    except TaskNotFound as exc:
        raise HTTPException(404, "Artifact not found") from exc
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": _build_content_disposition("attachment", PurePosixPath(path).name),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
