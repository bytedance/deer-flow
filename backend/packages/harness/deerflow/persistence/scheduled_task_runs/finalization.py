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
from deerflow.utils.time import coerce_iso

if TYPE_CHECKING:
    from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow

FinalizationObserver = Callable[..., Awaitable[None]]

# Lifecycle vocabulary, pinned as ``lifecycle_events``, ``lifecycle_reasons``
# and ``notification_events`` in contracts/scheduled_goal_notes_contract.json.
# ``task_paused`` is the automatic pause; the agent's own stop is
# ``task_stopped``; ``task_finished`` is a once task's outcome or a reached
# ``max_runs`` / ``end_at``.
RUN_EVENT_BY_STATUS: dict[str, str] = {"success": "run_completed", "failed": "run_failed", "unmet": "run_unmet"}
LIFECYCLE_EVENTS: tuple[str, ...] = ("task_stopped", "task_paused", "task_finished")
LIFECYCLE_REASONS: dict[str, tuple[str, ...]] = {
    "task_stopped": ("agent_stop",),
    "task_paused": ("consecutive_unmet",),
    "task_finished": ("max_runs", "end_at", "once_done", "once_failed"),
}
NOTIFICATION_EVENTS: tuple[str, ...] = (*RUN_EVENT_BY_STATUS.values(), "task_paused", "task_stopped", "task_finished")
# A once task's ``task_finished`` reports its own run outcome only for these.
_ONCE_OUTCOME_STATUSES = frozenset(RUN_EVENT_BY_STATUS)

# Host-written task ``last_error`` values that the tasks page translates;
# contracts/scheduled_goal_notes_contract.json pins them for the frontend.
AGENT_STOP_LAST_ERROR_PREFIX = "stopped by the agent in run "
AUTO_PAUSE_LAST_ERROR = "paused after 3 unmet scheduled goal runs"


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# Goal-check failures: the host could not judge the run, so it neither counts
# as a miss nor resets the unmet streak. Pinned as ``check_failure_codes`` in
# contracts/scheduled_goal_notes_contract.json.
CHECK_FAILURE_CODES = ("evaluator_failed", "no_durable_end_of_turn", "thread_changed_after_evaluation", "thread_changed_before_continuation")
_WAIT_CODES = ("external_wait", "blocked:external_wait")
_STREAK_NEUTRAL_CODES = _WAIT_CODES + CHECK_FAILURE_CODES


def is_host_pause_marker(last_error: str | None) -> bool:
    """True when ``last_error`` records a host pause (agent stop or auto-pause)."""
    if not isinstance(last_error, str):
        return False
    if last_error == AUTO_PAUSE_LAST_ERROR:
        return True
    suffix = last_error[len(AGENT_STOP_LAST_ERROR_PREFIX) :] if last_error.startswith(AGENT_STOP_LAST_ERROR_PREFIX) else ""
    return bool(suffix) and not suffix[0].isspace()


async def automatic_runs_used(session: AsyncSession, task_id: str) -> int:
    """Count launched automatic runs, the unit of the ``max_runs`` safety cap."""
    count = await session.scalar(select(func.count()).select_from(ScheduledTaskRunRow).where(ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.trigger == "scheduled", ScheduledTaskRunRow.launch_accounted.is_(True)))
    return int(count or 0)


async def end_condition_reached(session: AsyncSession, task: ScheduledTaskRow, *, now: datetime) -> bool:
    if task.end_at is not None and utc(task.end_at) <= utc(now):
        return True
    if task.max_runs is not None:
        return await automatic_runs_used(session, task.id) >= task.max_runs
    return False


async def _unmet_streak(session: AsyncSession, task: ScheduledTaskRow, occurrence: ScheduledTaskRunRow) -> bool:
    verdict = occurrence.goal_verdict or {}
    if occurrence.trigger != "scheduled" or occurrence.status != "unmet" or occurrence.error in _STREAK_NEUTRAL_CODES or verdict.get("blocker") == "external_wait":
        return False
    # Runs judged against an earlier goal, prompt, stop condition or note set
    # never count (the boundary moves on those edits, not on resume).
    boundary = task.unmet_streak_after_seq
    if boundary is not None and (occurrence.occurrence_seq is None or occurrence.occurrence_seq <= boundary):
        return False
    query = select(ScheduledTaskRunRow).where(
        ScheduledTaskRunRow.task_id == occurrence.task_id,
        ScheduledTaskRunRow.trigger == "scheduled",
        ScheduledTaskRunRow.status.in_(("success", "unmet")),
        or_(
            ScheduledTaskRunRow.status == "success",
            and_(
                func.coalesce(ScheduledTaskRunRow.error, "").not_in(_STREAK_NEUTRAL_CODES),
                func.coalesce(ScheduledTaskRunRow.goal_verdict["blocker"].as_string(), "") != "external_wait",
            ),
        ),
    )
    if occurrence.occurrence_seq is not None:
        query = query.where(ScheduledTaskRunRow.occurrence_seq <= occurrence.occurrence_seq).order_by(ScheduledTaskRunRow.occurrence_seq.desc())
        if boundary is not None:
            query = query.where(ScheduledTaskRunRow.occurrence_seq > boundary)
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
    from deerflow.persistence.scheduled_tasks.model import LIVE_TASK_STATUSES, ONCE_TASK_STATUS_BY_RUN_STATUS, TERMINAL_RUN_STATUSES

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
    # The lifecycle events below fire only on a real transition, so read the
    # status before the projection turns ``running`` back into ``enabled``.
    previous_status = task.status
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
    # A trial on a task the host paused keeps the pause reason ("Paused by
    # agent" / "Auto-paused"); the trial's own outcome stays on its run row.
    if not (occurrence.trigger == "manual" and task.status == "paused" and is_host_pause_marker(task.last_error)):
        task.last_error = error
    events: tuple[str, ...] = (RUN_EVENT_BY_STATUS[status],) if status in RUN_EVENT_BY_STATUS else ()
    # A once task's result remains meaningful: an unmet once task failed.
    # Limits and agent stop apply to the recurring schedule lifecycle.
    if task.schedule_type == "once":
        task.status = ONCE_TASK_STATUS_BY_RUN_STATUS[status]
        # A cancel or a skip (``cancelled``) stays silent, like interrupted runs.
        if status in _ONCE_OUTCOME_STATUSES:
            events += ("task_finished",)
    elif await end_condition_reached(session, task, now=finished_at):
        task.status = "completed"
        task.next_run_at = None
        if previous_status in LIVE_TASK_STATUSES:
            events += ("task_finished",)
    elif occurrence.stop_requested_run_id is not None and occurrence.stop_requested_run_id == run_id:
        # The stop applies whatever the run's own outcome (PR1 semantics); the
        # notice carries ``run_status`` so it never claims a clean finish.
        task.status = "paused"
        task.last_error = f"{AGENT_STOP_LAST_ERROR_PREFIX}{run_id}"
        if previous_status != "paused":
            events += ("task_stopped",)
    elif occurrence.goal_objective is not None and await _unmet_streak(session, task, occurrence):
        was_paused = task.status == "paused"
        task.status = "paused"
        task.last_error = AUTO_PAUSE_LAST_ERROR
        if not was_paused:
            events += ("task_paused",)
    task.updated_at = finished_at
    if observer is not None:
        await observer(session, task, occurrence, events=events)
    return True


async def finish_task_at_end_condition(
    session: AsyncSession,
    task: ScheduledTaskRow,
    *,
    occurrence: ScheduledTaskRunRow | None,
    now: datetime,
    observer: FinalizationObserver | None,
) -> None:
    """Complete a task whose ``max_runs`` or ``end_at`` is reached, outside a run.

    The single place, besides ``finalize_occurrence``, that marks a task
    finished: admission rejected as ended (``occurrence`` None), the claim-time
    skip of a queued row, and ``complete_if_ended``. The caller holds the parent
    lock and commits right after, so ``task_finished`` commits with the status
    change. It is emitted only on a live -> finished transition: a path that
    already went through ``finalize_occurrence`` (which emits for the same
    transition) adds nothing here. ``occurrence`` None means an idle finish.
    """
    from deerflow.persistence.scheduled_tasks.model import LIVE_TASK_STATUSES

    previous_status = task.status
    task.status = "completed"
    task.next_run_at = None
    task.lease_owner = None
    task.lease_expires_at = None
    task.updated_at = now
    if previous_status in LIVE_TASK_STATUSES and observer is not None:
        await observer(session, task, occurrence, events=("task_finished",))


def _end_at_utc(task: ScheduledTaskRow) -> datetime | None:
    """The task's end time as aware UTC, or None when unset or unreadable."""
    value = getattr(task, "end_at", None)
    if not isinstance(value, datetime):
        return None
    try:
        return utc(value)
    except (ValueError, TypeError, OverflowError):
        return None


def lifecycle_reason(task: ScheduledTaskRow, event: str, *, now: datetime, occurrence: ScheduledTaskRunRow | None = None) -> str:
    """Reason code of a lifecycle event (contract ``lifecycle_reasons``).

    A once task's ``task_finished`` reports its run (``once_done`` /
    ``once_failed``) when it comes from that run's outcome. A finish without
    such a run (an end time that passed before the once run) is ``end_at`` or
    ``max_runs`` like a recurring task. An unreadable ``end_at`` reads as
    ``max_runs``.
    """
    if event == "task_stopped":
        return "agent_stop"
    if event == "task_paused":
        return "consecutive_unmet"
    if task.schedule_type == "once" and occurrence is not None and occurrence.status in _ONCE_OUTCOME_STATUSES:
        return "once_done" if task.status == "completed" else "once_failed"
    end_at = _end_at_utc(task)
    try:
        reached = end_at is not None and end_at <= utc(now)
    except (ValueError, TypeError, AttributeError):
        reached = False
    return "end_at" if reached else "max_runs"


def lifecycle_anchor(task: ScheduledTaskRow, occurrence: ScheduledTaskRunRow | None, *, now: datetime) -> str:
    """Dedupe anchor of a lifecycle event: one event per transition, replay-safe.

    An occurrence anchors on its id. An idle finish anchors on its reason: the
    end time (``end:<iso>``) when that end time had passed at ``now`` (reason
    ``end_at``), else the occurrence sequence high-water mark (``seq:<n>``,
    reason ``max_runs``). Re-running ``complete_if_ended`` cannot add a row,
    and an idle ``max_runs`` finish does not take the anchor of a later finish
    at the task's (then still future) end time. A resume with a new end time
    followed by a second finish gets a new anchor.
    """
    if occurrence is not None:
        return occurrence.id
    end_at = _end_at_utc(task)
    if end_at is not None and lifecycle_reason(task, "task_finished", now=now) == "end_at":
        return f"end:{coerce_iso(end_at)}"
    return f"seq:{task.last_occurrence_seq}"
