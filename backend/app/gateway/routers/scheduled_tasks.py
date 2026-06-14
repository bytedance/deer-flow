"""Scheduled task management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.deps import get_current_user
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

router = APIRouter(prefix="/api/scheduled-tasks", tags=["scheduled-tasks"])


class ScheduledTaskResponse(BaseModel):
    id: str
    owner_user_id: str
    thread_id: str
    assistant_id: str
    agent_name: str | None = None
    title: str | None = None
    prompt: str
    schedule_type: str
    run_at: str
    timezone: str
    status: str
    last_run_id: str | None = None
    last_error: str | None = None
    channel_name: str | None = None
    chat_id: str | None = None
    topic_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ScheduledTaskListResponse(BaseModel):
    tasks: list[ScheduledTaskResponse]


def _repo() -> ScheduledTaskRepository:
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Scheduled tasks require sqlite or postgres database backend")
    return ScheduledTaskRepository(sf)


@router.get("", response_model=ScheduledTaskListResponse)
async def list_scheduled_tasks(
    request: Request,
    thread_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> ScheduledTaskListResponse:
    user_id = await get_current_user(request)
    tasks = await _repo().list(user_id=user_id, thread_id=thread_id, limit=limit)
    return ScheduledTaskListResponse(tasks=[ScheduledTaskResponse(**task) for task in tasks])


@router.get("/{task_id}", response_model=ScheduledTaskResponse)
async def get_scheduled_task(task_id: str, request: Request) -> ScheduledTaskResponse:
    user_id = await get_current_user(request)
    task = await _repo().get(task_id, user_id=user_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Scheduled task {task_id} not found")
    return ScheduledTaskResponse(**task)


@router.delete("/{task_id}", response_model=ScheduledTaskResponse)
async def cancel_scheduled_task(task_id: str, request: Request) -> ScheduledTaskResponse:
    user_id = await get_current_user(request)
    repo = _repo()
    cancelled = await repo.cancel(task_id, user_id=user_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Active scheduled task {task_id} not found")
    task = await repo.get(task_id, user_id=user_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Scheduled task {task_id} not found")
    return ScheduledTaskResponse(**task)
