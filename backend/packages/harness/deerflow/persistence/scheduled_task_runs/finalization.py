"""First-terminal scheduler outcomes, under the parent then occurrence lock."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_task_runs.projection import account_launch, can_project
from deerflow.scheduler.schedules import next_run_at

if TYPE_CHECKING:
    from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow

FinalizationObserver = Callable[..., Awaitable[None]]


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def end_condition_reached(session: AsyncSession, task: ScheduledTaskRow, *, now: datetime) -> bool:
    if task.end_at is not None and utc(task.end_at) <= utc(now):
        return True
    if task.max_runs is not None:
        count = await session.scalar(select(func.count()).select_from(ScheduledTaskRunRow).where(ScheduledTaskRunRow.task_id == task.id, ScheduledTaskRunRow.trigger == "scheduled", ScheduledTaskRunRow.launch_accounted.is_(True)))
        return int(count or 0) >= task.max_runs
    return False


async def _unmet_streak(session: AsyncSession, occurrence: ScheduledTaskRunRow) -> bool:
    wait_codes = ("external_wait", "blocked:external_wait")
    verdict = occurrence.goal_verdict or {}
    if occurrence.trigger != "scheduled" or occurrence.status != "unmet" or occurrence.error in wait_codes or verdict.get("blocker") == "external_wait":
        return False
    query = select(ScheduledTaskRunRow).where(
        ScheduledTaskRunRow.task_id == occurrence.task_id,
        ScheduledTaskRunRow.trigger == "scheduled",
        ScheduledTaskRunRow.status.in_(("success", "unmet")),
        or_(
            ScheduledTaskRunRow.status == "success",
            and_(
                func.coalesce(ScheduledTaskRunRow.error, "").not_in(wait_codes),
                func.coalesce(ScheduledTaskRunRow.goal_verdict["blocker"].as_string(), "") != "external_wait",
            ),
        ),
    )
    if occurrence.occurrence_seq is not None:
        query = query.where(ScheduledTaskRunRow.occurrence_seq <= occurrence.occurrence_seq).order_by(ScheduledTaskRunRow.occurrence_seq.desc())
    else:
        query = query.where(ScheduledTaskRunRow.occurrence_seq.is_(None)).order_by(ScheduledTaskRunRow.created_at.desc(), ScheduledTaskRunRow.id.desc())
    latest = list((await session.execute(query.limit(3))).scalars())
    return len(latest) == 3 and all(row.status == "unmet" for row in latest)


async def finalize_occurrence(
    session: AsyncSession,
    task: ScheduledTaskRow | None,
    occurrence: ScheduledTaskRunRow,
    *,
    status: str,
    error: str | None,
    finished_at: datetime,
    run_id: str | None,
    goal_verdict: dict[str, Any] | None = None,
    observer: FinalizationObserver | None = None,
) -> bool:
    """Terminalize once; receipts may still be repaired by the launch helpers."""
    from deerflow.persistence.scheduled_tasks.model import ONCE_TASK_STATUS_BY_RUN_STATUS, TERMINAL_RUN_STATUSES

    if occurrence.status in TERMINAL_RUN_STATUSES:
        return False
    if status not in TERMINAL_RUN_STATUSES:
        raise ValueError(f"unsupported terminal occurrence status: {status!r}")
    # Copy and validate JSON before committing an evaluator result. Do not let
    # mutable in-memory evidence rewrite an already recorded occurrence.
    verdict = json.loads(json.dumps(goal_verdict)) if goal_verdict is not None else None
    if status == "success" and occurrence.goal_objective is not None and (verdict is None or verdict.get("satisfied") is not True):
        status = "unmet"
        error = (verdict or {}).get("stand_down_reason") or "no_verdict"
    occurrence.status = status
    occurrence.run_id = run_id
    occurrence.goal_verdict = verdict
    occurrence.error = error
    occurrence.finished_at = finished_at
    occurrence.lease_owner = None
    occurrence.lease_expires_at = None
    if task is None:
        return True
    if run_id is not None:
        account_launch(task, occurrence, run_id)
    if not can_project(task, occurrence):
        return True
    if run_id is not None and task.last_run_id != run_id:
        launched_at = utc(occurrence.started_at or occurrence.scheduled_for)
        task.last_run_at = launched_at
        task.last_run_id = run_id
        task.last_thread_id = occurrence.thread_id
        task.next_run_at = next_run_at(task.schedule_type, task.schedule_spec, task.timezone, now=launched_at)
        task.lease_owner = None
        task.lease_expires_at = None
        if task.schedule_type != "once" and task.status == "running":
            task.status = "enabled"
    task.last_error = error
    events = {"success": ("run_completed",), "failed": ("run_failed",), "unmet": ("run_unmet",)}.get(status, ())
    # A once task's result remains meaningful: an unmet once task failed.
    # Limits and agent stop apply to the recurring schedule lifecycle.
    if task.schedule_type == "once":
        task.status = ONCE_TASK_STATUS_BY_RUN_STATUS[status]
    elif await end_condition_reached(session, task, now=finished_at):
        task.status = "completed"
        task.next_run_at = None
    elif occurrence.stop_requested_run_id is not None and occurrence.stop_requested_run_id == run_id:
        task.status = "paused"
        task.last_error = f"stopped by the agent in run {run_id}"
    elif occurrence.goal_objective is not None and await _unmet_streak(session, occurrence):
        was_paused = task.status == "paused"
        task.status = "paused"
        task.last_error = "paused after 3 unmet scheduled goal runs"
        if not was_paused:
            events += ("task_paused",)
    task.updated_at = finished_at
    if observer is not None:
        await observer(session, task, occurrence, events=events)
    return True
