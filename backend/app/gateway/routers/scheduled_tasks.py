from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import (
    get_config,
    get_optional_user_from_request,
    get_scheduled_task_repo,
    get_scheduled_task_run_repo,
    get_scheduled_task_service,
    get_thread_store,
)
from deerflow.scheduler.schedules import (
    next_run_at as compute_next_run_at,
)
from deerflow.scheduler.schedules import (
    normalize_cron_expression,
    validate_timezone,
)

router = APIRouter(prefix="/api", tags=["scheduled-tasks"])


def _ensure_task_mutable(task: dict[str, Any]) -> None:
    if task.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="Scheduled task is currently running; retry after the active execution finishes",
        )


class ScheduledTaskCreateRequest(BaseModel):
    thread_id: str | None = None
    context_mode: str = "fresh_thread_per_run"
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    schedule_type: str
    schedule_spec: dict[str, Any]
    timezone: str


class ScheduledTaskUpdateRequest(BaseModel):
    context_mode: str | None = None
    thread_id: str | None = None
    title: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    schedule_spec: dict[str, Any] | None = None
    timezone: str | None = None


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
    if body.schedule_type not in {"once", "cron"}:
        raise HTTPException(status_code=422, detail="Unsupported schedule_type")

    schedule_spec = dict(body.schedule_spec)
    try:
        validate_timezone(body.timezone)
        if body.schedule_type == "cron":
            raw_cron = schedule_spec.get("cron")
            if not isinstance(raw_cron, str):
                raise HTTPException(status_code=422, detail="cron schedule requires schedule_spec.cron")
            schedule_spec["cron"] = normalize_cron_expression(raw_cron)
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

    return await repo.create(
        task_id=f"task-{uuid.uuid4().hex}",
        user_id=str(user.id),
        thread_id=body.thread_id,
        context_mode=body.context_mode,
        assistant_id="lead_agent",
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
async def update_scheduled_task(task_id: str, request: Request, body: ScheduledTaskUpdateRequest):
    config = get_config()
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    existing = await repo.get(task_id, user_id=str(user.id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    _ensure_task_mutable(existing)

    updates = body.model_dump(exclude_none=True)
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

    updated = await repo.update(
        task_id,
        user_id=str(user.id),
        updates=updates,
    )
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
    _ensure_task_mutable(existing)
    updated = await repo.update(task_id, user_id=str(user.id), updates={"status": "paused"})
    if updated is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return updated


@router.post("/scheduled-tasks/{task_id}/resume")
@require_permission("threads", "write")
async def resume_scheduled_task(task_id: str, request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    existing = await repo.get(task_id, user_id=str(user.id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    _ensure_task_mutable(existing)
    updated = await repo.update(task_id, user_id=str(user.id), updates={"status": "enabled"})
    if updated is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return updated


@router.post("/scheduled-tasks/{task_id}/trigger")
@require_permission("threads", "write")
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
    deleted = await repo.delete(task_id, user_id=str(user.id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return {"id": task_id, "deleted": deleted}


@router.get("/scheduled-tasks/{task_id}/runs")
@require_permission("threads", "read")
async def list_scheduled_task_runs(
    task_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    task_repo = get_scheduled_task_repo(request)
    run_repo = get_scheduled_task_run_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    task = await task_repo.get(task_id, user_id=str(user.id))
    if task is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return await run_repo.list_by_task(task_id, limit=limit, offset=offset)


@router.get("/threads/{thread_id}/scheduled-tasks")
@require_permission("threads", "read", owner_check=True)
async def list_thread_scheduled_tasks(thread_id: str, request: Request):
    repo = get_scheduled_task_repo(request)
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return await repo.list_by_user_and_thread(str(user.id), thread_id)
