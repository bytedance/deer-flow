from __future__ import annotations

import asyncio
import typing
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
)
from deerflow.config.agents_config import AGENT_NAME_PATTERN, load_agent_config
from deerflow.persistence.scheduled_tasks import ActiveScheduledTaskMutationConflict
from deerflow.scheduler.schedules import (
    MAX_INTERVAL_SECONDS,
    normalize_cron_expression,
    parse_interval_seconds,
    validate_timezone,
)
from deerflow.scheduler.schedules import (
    next_run_at as compute_next_run_at,
)
from deerflow.utils.thread_id import ThreadId

router = APIRouter(prefix="/api", tags=["scheduled-tasks"])

_DEFAULT_ASSISTANT_ID = "lead_agent"


def _active_occurrence_conflict_detail(status: str) -> str:
    detail = f"Scheduled task has an active {status} occurrence; retry after it finishes"
    if status == "queued":
        detail += " or cancel the queued occurrence by pausing the task"
    return detail


def _validate_interval_seconds(schedule_spec: dict[str, Any], min_seconds: int) -> int:
    every_seconds = parse_interval_seconds(schedule_spec)
    if every_seconds < min_seconds:
        raise HTTPException(
            status_code=422,
            detail=f"interval schedule must be at least {min_seconds} seconds",
        )
    if every_seconds > MAX_INTERVAL_SECONDS:
        raise HTTPException(
            status_code=422,
            detail=f"interval schedule must be at most {MAX_INTERVAL_SECONDS} seconds",
        )
    return every_seconds


async def resolve_scheduled_task_assistant_id(raw: str | None, *, user_id: str) -> str:
    """Return a stored assistant id, defaulting to lead_agent.

    Custom names are normalized the same way IM/run creation already does
    (lowercase, underscore to hyphen) and must exist for this owner.
    """
    if raw is None:
        return _DEFAULT_ASSISTANT_ID
    value = raw.strip()
    if not value:
        raise HTTPException(status_code=422, detail="assistant_id must not be empty")
    normalized = value.lower().replace("_", "-")
    if normalized == _DEFAULT_ASSISTANT_ID.replace("_", "-"):
        return _DEFAULT_ASSISTANT_ID
    if not AGENT_NAME_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=422,
            detail=(f"Invalid assistant_id {raw!r}. Use 'lead_agent' or a custom agent name containing only letters, digits, and hyphens."),
        )
    try:
        config = await asyncio.to_thread(load_agent_config, normalized, user_id=user_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown assistant_id {raw!r}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if config is None:
        raise HTTPException(status_code=422, detail=f"Unknown assistant_id {raw!r}")
    return normalized


async def _ensure_task_mutable(task: dict[str, Any], repo) -> None:
    if task.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="Scheduled task is currently running; retry after the active execution finishes",
        )
    active_status = await repo.get_active_run_status(task["id"])
    if active_status is not None:
        raise HTTPException(
            status_code=409,
            detail=_active_occurrence_conflict_detail(active_status),
        )


class ScheduledTaskCreateRequest(BaseModel):
    thread_id: ThreadId | None = None
    context_mode: str = "fresh_thread_per_run"
    assistant_id: str | None = Field(default=None, min_length=1)
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    schedule_type: str
    schedule_spec: dict[str, Any]
    timezone: str


class ScheduledTaskUpdateRequest(BaseModel):
    context_mode: str | None = None
    thread_id: ThreadId | None = None
    assistant_id: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    schedule_spec: dict[str, Any] | None = None
    timezone: str | None = None


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
        raise HTTPException(status_code=422, detail=f"Cannot preview cron schedule: {exc}") from exc
    return CronPreviewResponse(cron=cron, timezone=body.timezone, start_at=reference, occurrences=occurrences)


@router.post("/scheduled-tasks/preview-cron", response_model=CronPreviewResponse)
@require_permission("threads", "read")
async def preview_cron_schedule(request: Request, body: CronPreviewRequest):
    """Preview future cron instants without creating or dispatching a task."""
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    reference = body.start_at if body.start_at is not None else datetime.now(UTC)
    return await asyncio.to_thread(_preview_cron, body, reference)


@router.get("/scheduled-tasks")
@require_permission("threads", "read")
async def list_scheduled_tasks(request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        return []
    return await repo.list_by_user(str(user.id))


@router.post("/scheduled-tasks")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def create_scheduled_task(request: Request, body: ScheduledTaskCreateRequest):
    config = get_config()
    repo = get_scheduled_task_repo(request)
    thread_store = get_thread_store(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if body.context_mode not in {"fresh_thread_per_run", "reuse_thread"}:
        raise HTTPException(status_code=422, detail="Unsupported context_mode")
    if body.context_mode == "reuse_thread":
        if not body.thread_id:
            raise HTTPException(status_code=422, detail="reuse_thread requires thread_id")
        if not await thread_store.check_access(body.thread_id, str(user.id), require_existing=True):
            raise HTTPException(status_code=404, detail="Thread not found")
    if body.schedule_type not in {"once", "cron", "interval"}:
        raise HTTPException(status_code=422, detail="Unsupported schedule_type")

    schedule_spec = dict(body.schedule_spec)
    try:
        validate_timezone(body.timezone)
        if body.schedule_type == "cron":
            raw_cron = schedule_spec.get("cron")
            if not isinstance(raw_cron, str):
                raise HTTPException(status_code=422, detail="cron schedule requires schedule_spec.cron")
            schedule_spec["cron"] = normalize_cron_expression(raw_cron)
        if body.schedule_type == "interval":
            _validate_interval_seconds(schedule_spec, config.scheduler.min_once_delay_seconds)
        next_run_at = compute_next_run_at(
            body.schedule_type,
            schedule_spec,
            body.timezone,
            now=datetime.now(UTC),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if body.schedule_type == "once" and next_run_at is None:
        raise HTTPException(status_code=422, detail="once schedule must be in the future")
    if body.schedule_type == "once" and next_run_at is not None and (next_run_at - datetime.now(UTC)).total_seconds() < config.scheduler.min_once_delay_seconds:
        raise HTTPException(
            status_code=422,
            detail=(f"once schedule must be at least {config.scheduler.min_once_delay_seconds} seconds in the future"),
        )

    assistant_id = await resolve_scheduled_task_assistant_id(
        body.assistant_id,
        user_id=str(user.id),
    )
    return await repo.create(
        task_id=f"task-{uuid.uuid4().hex}",
        user_id=str(user.id),
        thread_id=body.thread_id,
        context_mode=body.context_mode,
        assistant_id=assistant_id,
        title=body.title,
        prompt=body.prompt,
        schedule_type=body.schedule_type,
        schedule_spec=schedule_spec,
        timezone=body.timezone,
        next_run_at=next_run_at,
    )


@router.get("/scheduled-tasks/{task_id}")
@require_permission("threads", "read")
async def get_scheduled_task(task_id: str, request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    task = await repo.get(task_id, user_id=str(user.id))
    if task is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return task


@router.patch("/scheduled-tasks/{task_id}")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def update_scheduled_task(task_id: str, request: Request, body: ScheduledTaskUpdateRequest):
    config = get_config()
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    existing = await repo.get(task_id, user_id=str(user.id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    await _ensure_task_mutable(existing, repo)

    updates = body.model_dump(exclude_none=True)
    if "assistant_id" in updates:
        updates["assistant_id"] = await resolve_scheduled_task_assistant_id(
            updates["assistant_id"],
            user_id=str(user.id),
        )
    if "context_mode" in updates:
        if updates["context_mode"] not in {"fresh_thread_per_run", "reuse_thread"}:
            raise HTTPException(status_code=422, detail="Unsupported context_mode")
    effective_context_mode = str(updates.get("context_mode", existing["context_mode"]))
    effective_thread_id = updates.get("thread_id", existing.get("thread_id"))
    if effective_context_mode == "reuse_thread":
        if not effective_thread_id:
            raise HTTPException(status_code=422, detail="reuse_thread requires thread_id")
        thread_store = get_thread_store(request)
        if not await thread_store.check_access(str(effective_thread_id), str(user.id), require_existing=True):
            raise HTTPException(status_code=404, detail="Thread not found")
    elif effective_context_mode == "fresh_thread_per_run":
        updates["thread_id"] = None
    if "timezone" in updates:
        try:
            validate_timezone(str(updates["timezone"]))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if "schedule_spec" in updates or "timezone" in updates:
        schedule_spec = dict(existing["schedule_spec"])
        if "schedule_spec" in updates and isinstance(updates["schedule_spec"], dict):
            schedule_spec = dict(updates["schedule_spec"])
        timezone = str(updates.get("timezone", existing["timezone"]))
        try:
            if existing["schedule_type"] == "cron":
                raw_cron = schedule_spec.get("cron")
                if not isinstance(raw_cron, str):
                    raise HTTPException(
                        status_code=422,
                        detail="cron schedule requires schedule_spec.cron",
                    )
                schedule_spec["cron"] = normalize_cron_expression(raw_cron)
            if existing["schedule_type"] == "interval":
                every_seconds = _validate_interval_seconds(
                    schedule_spec,
                    config.scheduler.min_once_delay_seconds,
                )
                try:
                    previous_seconds = parse_interval_seconds(dict(existing["schedule_spec"]))
                except ValueError:
                    previous_seconds = None
                if previous_seconds == every_seconds and existing.get("next_run_at") is not None:
                    next_run_at = existing["next_run_at"]
                else:
                    next_run_at = compute_next_run_at(
                        existing["schedule_type"],
                        schedule_spec,
                        timezone,
                        now=datetime.now(UTC),
                    )
            else:
                next_run_at = compute_next_run_at(
                    existing["schedule_type"],
                    schedule_spec,
                    timezone,
                    now=datetime.now(UTC),
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if existing["schedule_type"] == "once" and next_run_at is None:
            raise HTTPException(status_code=422, detail="once schedule must be in the future")
        if existing["schedule_type"] == "once" and next_run_at is not None and (next_run_at - datetime.now(UTC)).total_seconds() < config.scheduler.min_once_delay_seconds:
            raise HTTPException(
                status_code=422,
                detail=(f"once schedule must be at least {config.scheduler.min_once_delay_seconds} seconds in the future"),
            )
        updates["schedule_spec"] = schedule_spec
        updates["next_run_at"] = next_run_at
        # A terminal task (completed/failed/cancelled) whose schedule was just
        # pushed into the future must be re-armed: claim_due_tasks only admits
        # "enabled" rows, so leaving the terminal status would return 200 with
        # a next_run_at that silently never fires.
        if next_run_at is not None and existing["status"] in {"completed", "failed", "cancelled"}:
            updates["status"] = "enabled"

    try:
        updated = await repo.update(
            task_id,
            user_id=str(user.id),
            updates=updates,
            require_mutable=True,
        )
    except ActiveScheduledTaskMutationConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=_active_occurrence_conflict_detail(exc.status),
        ) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return updated


@router.post("/scheduled-tasks/{task_id}/pause")
@require_permission("threads", "write")
async def pause_scheduled_task(task_id: str, request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    existing = await repo.get(task_id, user_id=str(user.id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    if existing.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="Scheduled task is currently running; retry after the active execution finishes",
        )
    result = await repo.pause_with_queue_cancellation(
        task_id,
        user_id=str(user.id),
        error="scheduled task was paused while queued",
        now=datetime.now(UTC),
    )
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    if result == "executing":
        raise HTTPException(
            status_code=409,
            detail="Scheduled task is already launching or running; retry after the active execution finishes",
        )
    return await repo.get(task_id, user_id=str(user.id))


@router.post("/scheduled-tasks/{task_id}/resume")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def resume_scheduled_task(task_id: str, request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    existing = await repo.get(task_id, user_id=str(user.id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    await _ensure_task_mutable(existing, repo)
    try:
        updated = await repo.update(
            task_id,
            user_id=str(user.id),
            updates={"status": "enabled"},
            require_mutable=True,
        )
    except ActiveScheduledTaskMutationConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=_active_occurrence_conflict_detail(exc.status),
        ) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return updated


@router.post("/scheduled-tasks/{task_id}/trigger")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def trigger_scheduled_task(task_id: str, request: Request):
    repo = get_scheduled_task_repo(request)
    service = get_scheduled_task_service(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    task = await repo.get(task_id, user_id=str(user.id))
    if task is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    result = await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
    if result["outcome"] == "not_found":
        raise HTTPException(status_code=404, detail=result["error"] or "Scheduled task not found")
    if result["outcome"] == "conflict":
        raise HTTPException(status_code=409, detail=result["error"] or "Scheduled task trigger conflicted with an active run")
    if result["outcome"] == "failed":
        raise HTTPException(status_code=502, detail=result["error"] or "Scheduled task trigger failed")
    return {"id": task_id, "triggered": True}


@router.delete("/scheduled-tasks/{task_id}")
@require_permission("threads", "write")
async def delete_scheduled_task(task_id: str, request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    result = await repo.delete_with_queue_cancellation(
        task_id,
        user_id=str(user.id),
        error="scheduled task was deleted while queued",
        now=datetime.now(UTC),
    )
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    if result == "executing":
        raise HTTPException(
            status_code=409,
            detail="Scheduled task is already launching or running; retry after the active execution finishes",
        )
    return {"id": task_id, "deleted": True}


@router.get("/scheduled-tasks/{task_id}/runs")
@require_permission("threads", "read")
async def list_scheduled_task_runs(
    task_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: typing.Literal["queued", "launching", "running", "success", "failed", "skipped", "interrupted"] | None = None,
):
    task_repo = get_scheduled_task_repo(request)
    run_repo = get_scheduled_task_run_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    task = await task_repo.get(task_id, user_id=str(user.id))
    if task is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return await run_repo.list_by_task(task_id, limit=limit, offset=offset, status=status)


@router.get("/threads/{thread_id}/scheduled-tasks")
@require_permission("threads", "read", owner_check=True)
async def list_thread_scheduled_tasks(thread_id: ThreadId, request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return await repo.list_by_user_and_thread(str(user.id), thread_id)
