from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime, BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import (
    get_config,
    get_optional_user_from_request,
    get_scheduled_task_repo,
    get_scheduled_task_run_repo,
    get_scheduled_task_service,
    get_thread_store,
    is_scheduler_running,
)
from app.gateway.scheduled_task_errors import active_occurrence_error, active_occurrence_message, repository_error, scheduler_error
from app.gateway.scheduled_task_validation import prepare_resume_updates, validate_scheduled_task_create, validate_scheduled_task_update
from app.scheduler.service import TASK_CHANGED_ERROR
from deerflow.config.agents_config import AGENT_NAME_PATTERN, load_agent_config
from deerflow.persistence.scheduled_tasks import ActiveScheduledTaskMutationConflict, ScheduledTaskQuotaExceeded
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRunStatus
from deerflow.scheduler.host_notes import RUN_ERROR_DELETED_WHILE_QUEUED, RUN_ERROR_PAUSED_WHILE_QUEUED
from deerflow.scheduler.schedules import (
    next_run_at as compute_next_run_at,
)
from deerflow.scheduler.schedules import (
    normalize_cron_expression,
    validate_timezone,
)
from deerflow.utils.thread_id import ThreadId

router = APIRouter(prefix="/api", tags=["scheduled-tasks"])

_DEFAULT_ASSISTANT_ID = "lead_agent"

# Kept under its historical name; the coded wrapper is active_occurrence_error.
_active_occurrence_conflict_detail = active_occurrence_message


def _authentication_required() -> HTTPException:
    return scheduler_error(401, "authentication_required", "Authentication required")


def _task_not_found() -> HTTPException:
    return scheduler_error(404, "task_not_found", "Scheduled task not found")


async def resolve_scheduled_task_assistant_id(raw: str | None, *, user_id: str) -> str:
    """Return a stored assistant id, defaulting to lead_agent.

    Custom names are normalized the same way IM/run creation already does
    (lowercase, underscore to hyphen) and must exist for this owner.
    """
    if raw is None:
        return _DEFAULT_ASSISTANT_ID
    value = raw.strip()
    if not value:
        raise scheduler_error(422, "invalid_assistant", "assistant_id must not be empty")
    normalized = value.lower().replace("_", "-")
    if normalized == _DEFAULT_ASSISTANT_ID.replace("_", "-"):
        return _DEFAULT_ASSISTANT_ID
    if not AGENT_NAME_PATTERN.fullmatch(normalized):
        raise scheduler_error(
            422,
            "invalid_assistant",
            f"Invalid assistant_id {raw!r}. Use 'lead_agent' or a custom agent name containing only letters, digits, and hyphens.",
        )
    try:
        config = await asyncio.to_thread(load_agent_config, normalized, user_id=user_id)
    except FileNotFoundError as exc:
        raise scheduler_error(422, "unknown_assistant", f"Unknown assistant_id {raw!r}") from exc
    except ValueError as exc:
        raise scheduler_error(422, "invalid_assistant", str(exc)) from exc
    if config is None:
        raise scheduler_error(422, "unknown_assistant", f"Unknown assistant_id {raw!r}")
    return normalized


async def _ensure_task_mutable(task: dict[str, Any], repo) -> None:
    if task.get("status") == "running":
        raise scheduler_error(409, "task_running", "Scheduled task is currently running; retry after the active execution finishes")
    active_status = await repo.get_active_run_status(task["id"])
    if active_status is not None:
        raise active_occurrence_error(active_status)


async def _with_run_state(repo, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add ``automatic_runs_used`` and ``active_run_status`` (one query each)."""
    ids = [task["id"] for task in tasks]
    used = await repo.automatic_runs_used_for(ids)
    active = await repo.active_run_status_for(ids)
    return [{**task, "automatic_runs_used": used.get(task["id"], 0), "active_run_status": active.get(task["id"])} for task in tasks]


async def _task_response(repo, task: dict[str, Any]) -> dict[str, Any]:
    used = await repo.automatic_runs_used_for([task["id"]])
    return {**task, "automatic_runs_used": used.get(task["id"], 0), "active_run_status": await repo.get_active_run_status(task["id"])}


class ScheduledTaskCreateRequest(BaseModel):
    # Types only: value rules (max_runs >= 1, lengths, end-time rules) raise
    # coded errors from the shared validation, never a FastAPI list detail.
    thread_id: ThreadId | None = None
    context_mode: str = "fresh_thread_per_run"
    assistant_id: str | None = Field(default=None, min_length=1)
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    schedule_type: str
    schedule_spec: dict[str, Any]
    timezone: str
    goal_objective: str | None = None
    # ``bool`` stays a bool here (not 1) so validation can reject it.
    max_runs: int | bool | None = None
    # Naive = wall-clock time in the task's timezone.
    end_at: datetime | None = None
    # The user's "stop when ..." rule, stored in its own column.
    stop_condition: str | None = None


class ScheduledTaskUpdateRequest(BaseModel):
    context_mode: str | None = None
    thread_id: ThreadId | None = None
    assistant_id: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    # Allowed; when it changes, schedule_spec is required.
    schedule_type: str | None = None
    schedule_spec: dict[str, Any] | None = None
    timezone: str | None = None
    # Sent as null, these four clear the field (model_fields_set).
    goal_objective: str | None = None
    max_runs: int | bool | None = None
    end_at: datetime | None = None
    stop_condition: str | None = None


class ScheduledTaskResumeRequest(BaseModel):
    """Optional renewal sent with Resume; a field sent as null clears that cap."""

    max_runs: int | bool | None = None
    end_at: datetime | None = None


class CronPreviewRequest(BaseModel):
    cron: str = Field(min_length=1, max_length=256)
    timezone: str = Field(min_length=1, max_length=128)
    count: int = Field(default=5, ge=1, le=10, strict=True)
    start_at: AwareDatetime | None = None


class CronPreviewOccurrence(BaseModel):
    run_at: datetime
    local_time: datetime


class CronPreviewResponse(BaseModel):
    cron: str
    timezone: str
    start_at: datetime
    occurrences: list[CronPreviewOccurrence]


def _preview_cron(body: CronPreviewRequest, reference: datetime) -> CronPreviewResponse:
    """Calculate advisory occurrences with the same semantics as scheduling."""
    try:
        cron = normalize_cron_expression(body.cron)
        zone = ZoneInfo(validate_timezone(body.timezone))
        reference = reference.astimezone(UTC)
        cursor = reference
        occurrences = []
        for _ in range(body.count):
            upcoming = compute_next_run_at("cron", {"cron": cron}, body.timezone, now=cursor)
            if upcoming is None or upcoming <= cursor:
                raise ValueError("Cron expression did not produce a future occurrence")
            occurrences.append(CronPreviewOccurrence(run_at=upcoming, local_time=upcoming.astimezone(zone)))
            cursor = upcoming
    except (ValueError, OverflowError) as exc:
        raise scheduler_error(422, "invalid_schedule", f"Cannot preview cron schedule: {exc}") from exc
    return CronPreviewResponse(cron=cron, timezone=body.timezone, start_at=reference, occurrences=occurrences)


@router.post("/scheduled-tasks/preview-cron", response_model=CronPreviewResponse)
@require_permission("threads", "read")
async def preview_cron_schedule(request: Request, body: CronPreviewRequest):
    """Preview future cron instants without creating or dispatching a task."""
    user = await get_optional_user_from_request(request)
    if user is None:
        raise _authentication_required()
    reference = body.start_at if body.start_at is not None else datetime.now(UTC)
    return await asyncio.to_thread(_preview_cron, body, reference)


@router.get("/scheduled-tasks")
@require_permission("threads", "read")
async def list_scheduled_tasks(request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        return []
    return await _with_run_state(repo, await repo.list_by_user(str(user.id)))


@router.post("/scheduled-tasks")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def create_scheduled_task(request: Request, body: ScheduledTaskCreateRequest):
    """Create a task (also used by the page's Duplicate)."""
    config = get_config()
    repo = get_scheduled_task_repo(request)
    thread_store = get_thread_store(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise _authentication_required()
    definition = await validate_scheduled_task_create(
        body,
        user_id=str(user.id),
        thread_store=thread_store,
        scheduler_config=config.scheduler,
        assistant_resolver=resolve_scheduled_task_assistant_id,
        now=datetime.now(UTC),
    )
    # After validation, so a bad request still reports what to fix: a task
    # created while this process's poller is off would silently never run.
    if not is_scheduler_running(request):
        raise scheduler_error(
            409,
            "scheduler_not_running",
            "The scheduler is not running in this Gateway process, so a new task would not run on schedule. Check the scheduler configuration and Gateway logs.",
        )
    try:
        created = await repo.create(
            task_id=f"task-{uuid.uuid4().hex}",
            user_id=str(user.id),
            **definition,
        )
    except ValueError as exc:
        raise repository_error(exc) from exc
    return await _task_response(repo, created)


@router.get("/scheduled-tasks/{task_id}")
@require_permission("threads", "read")
async def get_scheduled_task(task_id: str, request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise _authentication_required()
    task = await repo.get(task_id, user_id=str(user.id))
    if task is None:
        raise _task_not_found()
    return await _task_response(repo, task)


@router.patch("/scheduled-tasks/{task_id}")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def update_scheduled_task(task_id: str, request: Request, body: ScheduledTaskUpdateRequest):
    """Edit a task; null clears goal_objective, max_runs, end_at and stop_condition.

    A schedule change on a finished task re-arms it (then its safety cap is
    checked); changing only the limits of a finished task leaves it finished,
    since reactivating is an explicit Resume.
    """
    config = get_config()
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise _authentication_required()
    existing = await repo.get(task_id, user_id=str(user.id))
    if existing is None:
        raise _task_not_found()
    await _ensure_task_mutable(existing, repo)
    used = (await repo.automatic_runs_used_for([task_id])).get(task_id, 0)
    fields = body.model_dump(exclude_unset=True)
    # Only a reused conversation needs the thread store (access check).
    reuses_thread = (fields.get("context_mode") or existing["context_mode"]) == "reuse_thread"
    updates = await validate_scheduled_task_update(
        existing,
        fields,
        user_id=str(user.id),
        thread_store=get_thread_store(request) if reuses_thread else None,
        scheduler_config=config.scheduler,
        assistant_resolver=resolve_scheduled_task_assistant_id,
        used=used,
        now=datetime.now(UTC),
    )
    try:
        updated = await repo.update(
            task_id,
            user_id=str(user.id),
            updates=updates,
            require_mutable=True,
        )
    except (ActiveScheduledTaskMutationConflict, ValueError) as exc:
        raise repository_error(exc) from exc
    if updated is None:
        raise _task_not_found()
    return await _task_response(repo, updated)


@router.post("/scheduled-tasks/{task_id}/pause")
@require_permission("threads", "write")
async def pause_scheduled_task(task_id: str, request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise _authentication_required()
    existing = await repo.get(task_id, user_id=str(user.id))
    if existing is None:
        raise _task_not_found()
    if existing.get("status") == "running":
        raise scheduler_error(409, "task_running", "Scheduled task is currently running; retry after the active execution finishes")
    try:
        result = await repo.pause_with_queue_cancellation(
            task_id,
            user_id=str(user.id),
            error=RUN_ERROR_PAUSED_WHILE_QUEUED,
            now=datetime.now(UTC),
        )
    except ScheduledTaskQuotaExceeded as exc:
        raise repository_error(exc) from exc
    if result == "not_found":
        raise _task_not_found()
    if result == "executing":
        raise scheduler_error(409, "task_running", "Scheduled task is already launching or running; retry after the active execution finishes")
    if result == "finished":
        raise scheduler_error(409, "task_finished", "Scheduled task has finished; resume it to run again")
    paused = await repo.get(task_id, user_id=str(user.id))
    if paused is None:
        raise _task_not_found()
    return await _task_response(repo, paused)


@router.post("/scheduled-tasks/{task_id}/resume")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def resume_scheduled_task(task_id: str, request: Request, body: ScheduledTaskResumeRequest | None = None):
    """Resume a paused or finished task, optionally renewing its safety cap.

    The next run is computed from now (no catch-up run); the unmet streak is
    kept. A body field sent as null clears that cap. Resuming an active task
    changes nothing.
    """
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise _authentication_required()
    existing = await repo.get(task_id, user_id=str(user.id))
    if existing is None:
        raise _task_not_found()
    await _ensure_task_mutable(existing, repo)
    if existing.get("status") == "enabled":
        return await _task_response(repo, existing)
    used = (await repo.automatic_runs_used_for([task_id])).get(task_id, 0)
    renewal = body.model_dump(exclude_unset=True) if body is not None else {}
    updates = await asyncio.to_thread(prepare_resume_updates, existing, renewal, used=used, now=datetime.now(UTC))
    try:
        updated = await repo.update(
            task_id,
            user_id=str(user.id),
            updates=updates,
            require_mutable=True,
        )
    except (ActiveScheduledTaskMutationConflict, ValueError) as exc:
        raise repository_error(exc) from exc
    if updated is None:
        raise _task_not_found()
    return await _task_response(repo, updated)


@router.post("/scheduled-tasks/{task_id}/trigger")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def trigger_scheduled_task(task_id: str, request: Request):
    """Start one trial run now; ``existing`` means a run was already waiting."""
    repo = get_scheduled_task_repo(request)
    service = get_scheduled_task_service(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise _authentication_required()
    task = await repo.get(task_id, user_id=str(user.id))
    if task is None:
        raise _task_not_found()
    result = await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
    outcome = result.get("outcome")
    if outcome == "not_found":
        raise scheduler_error(404, "task_not_found", result.get("error") or "Scheduled task not found")
    if outcome == "conflict":
        error = result.get("error") or "Scheduled task trigger conflicted with an active run"
        raise scheduler_error(409, "task_changed" if error == TASK_CHANGED_ERROR else "task_running", error)
    if outcome == "failed":
        raise scheduler_error(502, "trigger_failed", result.get("error") or "Scheduled task trigger failed")
    return {"id": task_id, "triggered": True, "outcome": outcome, "existing": bool(result.get("existing")), "thread_id": result.get("thread_id")}


@router.delete("/scheduled-tasks/{task_id}")
@require_permission("threads", "write")
async def delete_scheduled_task(task_id: str, request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise _authentication_required()
    result = await repo.delete_with_queue_cancellation(
        task_id,
        user_id=str(user.id),
        error=RUN_ERROR_DELETED_WHILE_QUEUED,
        now=datetime.now(UTC),
    )
    if result == "not_found":
        raise _task_not_found()
    if result == "executing":
        raise scheduler_error(409, "task_running", "Scheduled task is already launching or running; retry after the active execution finishes")
    return {"id": task_id, "deleted": True}


@router.get("/scheduled-tasks/{task_id}/runs")
@require_permission("threads", "read")
async def list_scheduled_task_runs(
    task_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: ScheduledTaskRunStatus | None = None,
):
    """Run history, newest first, with run numbers, token totals and summaries."""
    task_repo = get_scheduled_task_repo(request)
    run_repo = get_scheduled_task_run_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise _authentication_required()
    task = await task_repo.get(task_id, user_id=str(user.id))
    if task is None:
        raise _task_not_found()
    return await run_repo.list_by_task(task_id, limit=limit, offset=offset, status=status)


@router.get("/threads/{thread_id}/scheduled-tasks")
@require_permission("threads", "read", owner_check=True)
async def list_thread_scheduled_tasks(thread_id: ThreadId, request: Request):
    """Tasks created in, running in, or run by this conversation (``thread_relation``)."""
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise _authentication_required()
    return await _with_run_state(repo, await repo.list_by_user_and_thread(str(user.id), thread_id))
