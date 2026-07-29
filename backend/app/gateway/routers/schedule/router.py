"""Primary adapter -- the scheduled-task HTTP API.

Everything here is protocol translation. Parse the body into domain values,
call one service method, render the result, and map domain errors onto status
codes. What is deliberately *absent* is the giveaway: no cron normalisation,
no `next_run_at` arithmetic, no re-arm rule, no ownership checks written out
by hand. Those moved into the aggregate, where they are covered by domain
tests that never construct an HTTP request.

The error mapping is one table rather than a `raise HTTPException` per branch,
so a new domain error surfaces as a 500 that has to be classified, instead of
being silently swallowed by whichever `except` happened to be nearest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import wraps
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from app.gateway.authz import require_permission
from app.gateway.deps import ScheduleServiceDep, get_optional_user_from_request
from app.gateway.routers.schedule.models import (
    CreateScheduledTaskRequest,
    DeleteResponse,
    ScheduledRunResponse,
    ScheduledTaskResponse,
    TriggerResponse,
    UpdateScheduledTaskRequest,
)
from deerflow.domain.schedule.commands import DeleteTask, PauseTask, ResumeTask, TriggerTask
from deerflow.domain.schedule.exceptions import (
    InvalidContextModeError,
    InvalidScheduleError,
    ScheduleError,
    TaskNotFoundError,
    TaskNotMutableError,
    ThreadNotFoundError,
)
from deerflow.domain.schedule.model import DispatchOutcome

router = APIRouter(prefix="/api", tags=["scheduled-tasks"])

# One family of domain errors, one place they become a protocol.
_STATUS_BY_ERROR: dict[type[ScheduleError], int] = {
    # "Not yours" and "does not exist" are both 404 by design -- the service
    # already refuses to distinguish them, and so must the status code.
    TaskNotFoundError: 404,
    ThreadNotFoundError: 404,
    InvalidScheduleError: 422,
    InvalidContextModeError: 422,
    TaskNotMutableError: 409,
}


def _map_domain_errors(handler):
    """Translate domain errors raised by the service into HTTP responses.

    An unclassified `ScheduleError` becomes a 500 on purpose: a new domain
    error is a new protocol decision, and defaulting it to 4xx would let it
    ship as a client error nobody chose.
    """

    @wraps(handler)
    async def wrapper(*args, **kwargs):
        try:
            return await handler(*args, **kwargs)
        except ScheduleError as exc:
            status = _STATUS_BY_ERROR.get(type(exc))
            if status is None:
                raise
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    return wrapper


async def _require_user_id(request: Request) -> str:
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user.id)


@router.get("/scheduled-tasks", response_model=list[ScheduledTaskResponse])
@require_permission("threads", "read")
@_map_domain_errors
async def list_scheduled_tasks(request: Request, service: ScheduleServiceDep):
    user = await get_optional_user_from_request(request)
    if user is None:
        # Not 401: an unauthenticated listing has always been an empty one.
        return []
    return [ScheduledTaskResponse.from_domain(task) for task in await service.list_tasks(str(user.id))]


@router.post("/scheduled-tasks", response_model=ScheduledTaskResponse)
@require_permission("threads", "write")
@_map_domain_errors
async def create_scheduled_task(request: Request, body: CreateScheduledTaskRequest, service: ScheduleServiceDep):
    user_id = await _require_user_id(request)
    task = await service.create_scheduled_task(body.to_command(user_id), now=datetime.now(UTC))
    return ScheduledTaskResponse.from_domain(task)


@router.get("/scheduled-tasks/{task_id}", response_model=ScheduledTaskResponse)
@require_permission("threads", "read")
@_map_domain_errors
async def get_scheduled_task(task_id: str, request: Request, service: ScheduleServiceDep):
    user_id = await _require_user_id(request)
    return ScheduledTaskResponse.from_domain(await service.get_task(task_id, user_id=user_id))


@router.patch("/scheduled-tasks/{task_id}", response_model=ScheduledTaskResponse)
@require_permission("threads", "write")
@_map_domain_errors
async def update_scheduled_task(
    task_id: str,
    request: Request,
    body: UpdateScheduledTaskRequest,
    service: ScheduleServiceDep,
):
    user_id = await _require_user_id(request)
    # A schedule or context change needs the parts the client omitted, so the
    # current task is read once and handed to `to_command`. That one extra
    # fetch is what lets the command carry whole value objects instead of a
    # patch of loose fields.
    current = await service.get_task(task_id, user_id=user_id) if body.changes_schedule() or body.changes_context() else None
    task = await service.update_scheduled_task(body.to_command(task_id, user_id, current), now=datetime.now(UTC))
    return ScheduledTaskResponse.from_domain(task)


@router.post("/scheduled-tasks/{task_id}/pause", response_model=ScheduledTaskResponse)
@require_permission("threads", "write")
@_map_domain_errors
async def pause_scheduled_task(task_id: str, request: Request, service: ScheduleServiceDep):
    user_id = await _require_user_id(request)
    # No body, so no request model: the command is built right here (spec §2.1 ①).
    return ScheduledTaskResponse.from_domain(await service.pause_task(PauseTask(task_id=task_id, user_id=user_id)))


@router.post("/scheduled-tasks/{task_id}/resume", response_model=ScheduledTaskResponse)
@require_permission("threads", "write")
@_map_domain_errors
async def resume_scheduled_task(task_id: str, request: Request, service: ScheduleServiceDep):
    user_id = await _require_user_id(request)
    return ScheduledTaskResponse.from_domain(await service.resume_task(ResumeTask(task_id=task_id, user_id=user_id)))


@router.post("/scheduled-tasks/{task_id}/trigger", response_model=TriggerResponse)
@require_permission("threads", "write")
@_map_domain_errors
async def trigger_scheduled_task(task_id: str, request: Request, service: ScheduleServiceDep):
    user_id = await _require_user_id(request)
    result = await service.trigger_task(TriggerTask(task_id=task_id, user_id=user_id), now=datetime.now(UTC))
    if result.outcome is DispatchOutcome.CONFLICT:
        raise HTTPException(status_code=409, detail=result.error or "Scheduled task trigger conflicted with an active run")
    if result.outcome is DispatchOutcome.FAILED:
        # 502, not 500: the failure is downstream of this API -- the run could
        # not be started -- and the task itself is intact.
        raise HTTPException(status_code=502, detail=result.error or "Scheduled task trigger failed")
    return TriggerResponse(id=task_id, triggered=True)


@router.delete("/scheduled-tasks/{task_id}", response_model=DeleteResponse)
@require_permission("threads", "write")
@_map_domain_errors
async def delete_scheduled_task(task_id: str, request: Request, service: ScheduleServiceDep):
    user_id = await _require_user_id(request)
    await service.delete_task(DeleteTask(task_id=task_id, user_id=user_id))
    return DeleteResponse(id=task_id, deleted=True)


@router.get("/scheduled-tasks/{task_id}/runs", response_model=list[ScheduledRunResponse])
@require_permission("threads", "read")
@_map_domain_errors
async def list_scheduled_task_runs(
    task_id: str,
    request: Request,
    service: ScheduleServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    user_id = await _require_user_id(request)
    runs = await service.list_task_runs(task_id, user_id=user_id, limit=limit, offset=offset)
    return [ScheduledRunResponse.from_domain(run) for run in runs]


@router.get("/threads/{thread_id}/scheduled-tasks", response_model=list[ScheduledTaskResponse])
@require_permission("threads", "read", owner_check=True)
@_map_domain_errors
async def list_thread_scheduled_tasks(thread_id: str, request: Request, service: ScheduleServiceDep):
    user_id = await _require_user_id(request)
    tasks = await service.list_tasks_by_thread(user_id, thread_id)
    return [ScheduledTaskResponse.from_domain(task) for task in tasks]
