"""Creation validation shared by HTTP and conversation schedule operations."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from deerflow.scheduler.schedules import MAX_INTERVAL_SECONDS, next_run_at, normalize_cron_expression, parse_interval_seconds, validate_timezone


def validate_interval_seconds(schedule_spec: dict[str, Any], min_seconds: int) -> int:
    every_seconds = parse_interval_seconds(schedule_spec)
    if every_seconds < min_seconds:
        raise HTTPException(status_code=422, detail=f"interval schedule must be at least {min_seconds} seconds")
    if every_seconds > MAX_INTERVAL_SECONDS:
        raise HTTPException(status_code=422, detail=f"interval schedule must be at most {MAX_INTERVAL_SECONDS} seconds")
    return every_seconds


def _validate_schedule(body: Any, *, scheduler_config: Any, now: datetime) -> tuple[dict[str, Any], datetime | None]:
    schedule_spec = dict(body.schedule_spec)
    try:
        validate_timezone(body.timezone)
        if body.schedule_type == "cron":
            raw_cron = schedule_spec.get("cron")
            if not isinstance(raw_cron, str):
                raise HTTPException(status_code=422, detail="cron schedule requires schedule_spec.cron")
            schedule_spec["cron"] = normalize_cron_expression(raw_cron)
        if body.schedule_type == "interval":
            validate_interval_seconds(schedule_spec, scheduler_config.min_once_delay_seconds)
        upcoming = next_run_at(body.schedule_type, schedule_spec, body.timezone, now=now)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.schedule_type == "once" and upcoming is None:
        raise HTTPException(status_code=422, detail="once schedule must be in the future")
    if body.schedule_type == "once" and upcoming is not None and (upcoming - now).total_seconds() < scheduler_config.min_once_delay_seconds:
        raise HTTPException(status_code=422, detail=f"once schedule must be at least {scheduler_config.min_once_delay_seconds} seconds in the future")
    return schedule_spec, upcoming


async def validate_scheduled_task_create(
    body: Any,
    *,
    user_id: str,
    thread_store: Any,
    scheduler_config: Any,
    assistant_resolver: Callable[..., Awaitable[str]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return repository definition fields after the shared REST checks."""
    if body.context_mode not in {"fresh_thread_per_run", "reuse_thread"}:
        raise HTTPException(status_code=422, detail="Unsupported context_mode")
    if body.context_mode == "reuse_thread":
        if not body.thread_id:
            raise HTTPException(status_code=422, detail="reuse_thread requires thread_id")
        if not await thread_store.check_access(body.thread_id, user_id, require_existing=True):
            raise HTTPException(status_code=404, detail="Thread not found")
    if body.schedule_type not in {"once", "cron", "interval"}:
        raise HTTPException(status_code=422, detail="Unsupported schedule_type")
    schedule_spec, upcoming = await asyncio.to_thread(_validate_schedule, body, scheduler_config=scheduler_config, now=now or datetime.now(UTC))
    assistant_id = await assistant_resolver(body.assistant_id, user_id=user_id)
    return {
        "thread_id": body.thread_id,
        "context_mode": body.context_mode,
        "assistant_id": assistant_id,
        "title": body.title,
        "prompt": body.prompt,
        "schedule_type": body.schedule_type,
        "schedule_spec": schedule_spec,
        "timezone": body.timezone,
        "next_run_at": upcoming,
    }
