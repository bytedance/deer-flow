"""Scheduled-task validation shared by HTTP and conversation schedule operations.

Every rule raises a coded error (``scheduled_task_errors.scheduler_error``), so
the tasks page and the agent receive the same ``code`` for the same mistake.
Request models declare only types; value rules live here.
"""

import asyncio
from collections.abc import Awaitable, Callable, Collection
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.gateway.scheduled_task_errors import scheduler_error
from deerflow.persistence.scheduled_task_runs.finalization import is_host_pause_marker
from deerflow.scheduler.schedules import MAX_INTERVAL_SECONDS, next_run_at, normalize_cron_expression, parse_interval_seconds, validate_timezone
from deerflow.scheduler.stop_rule import MAX_STOP_CONDITION_CHARS, normalize_stop_condition
from deerflow.utils.goal_objective import MAX_GOAL_OBJECTIVE_CHARS, normalize_goal_objective

FREQUENT_THRESHOLD_SECONDS = 3600
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled"})
CONTEXT_MODES = frozenset({"fresh_thread_per_run", "reuse_thread"})
SCHEDULE_TYPES = frozenset({"once", "cron", "interval"})
# Fields a PATCH (or chat update) may clear by sending null.
CLEARABLE_FIELDS = frozenset({"goal_objective", "max_runs", "end_at", "stop_condition"})
_BOUND_FIELDS = frozenset({"goal_objective", "max_runs", "end_at"})


def validate_interval_seconds(schedule_spec: dict[str, Any], min_seconds: int) -> int:
    try:
        every_seconds = parse_interval_seconds(schedule_spec)
    except ValueError as exc:
        raise scheduler_error(422, "invalid_schedule", str(exc)) from exc
    if every_seconds < min_seconds:
        raise scheduler_error(422, "interval_too_short", f"interval schedule must be at least {min_seconds} seconds", min_seconds=min_seconds)
    if every_seconds > MAX_INTERVAL_SECONDS:
        raise scheduler_error(422, "interval_too_long", f"interval schedule must be at most {MAX_INTERVAL_SECONDS} seconds", max_seconds=MAX_INTERVAL_SECONDS)
    return every_seconds


def is_frequent_schedule(schedule_type: str, schedule_spec: dict[str, Any]) -> bool:
    """More often than hourly: a sub-hour interval, or a cron with a non-fixed minute."""
    if schedule_type == "interval":
        every_seconds = schedule_spec.get("every_seconds")
        return isinstance(every_seconds, int) and not isinstance(every_seconds, bool) and every_seconds < FREQUENT_THRESHOLD_SECONDS
    if schedule_type == "cron":
        fields = str(schedule_spec.get("cron", "")).split()
        minute = fields[0] if fields else ""
        return not (minute.isascii() and minute.isdigit())
    return False


def _as_datetime(value: datetime | str | None) -> datetime | None:
    """Read a stored timestamp (``_row_to_dict`` returns ISO strings) as aware UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(f"{value[:-1]}+00:00" if value.endswith("Z") else value)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def resolve_end_at(value: datetime | str | None, timezone: str) -> datetime | None:
    """Return ``end_at`` as aware UTC; a naive value is wall-clock time in the task's timezone.

    UTC because SQLite drops the offset of DateTime(timezone=True) columns.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(f"{value[:-1]}+00:00" if value.endswith("Z") else value)
        except ValueError as exc:
            raise scheduler_error(422, "invalid_request", "end_at must be an ISO 8601 date-time") from exc
    if not isinstance(value, datetime):
        raise scheduler_error(422, "invalid_request", "end_at must be an ISO 8601 date-time")
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(timezone))
    return value.astimezone(UTC)


def validate_task_bounds(
    *,
    goal_objective: str | None,
    max_runs: int | None,
    end_at: datetime | str | None,
    context_mode: str,
    schedule_type: str,
    schedule_spec: dict[str, Any],
    next_run_at: datetime | str | None,
    now: datetime,
    used: int = 0,
    require_limit_for_frequent: bool,
    changed: Collection[str] | None = None,
) -> None:
    """Check goal and safety-cap rules on a (merged) task definition.

    ``changed`` limits the max_runs/end_at value checks to the fields a
    request sets, so renaming a task whose cap is used up or whose end time
    passed is not rejected; ``None`` checks everything (creation). A changed
    ``next_run_at`` (schedule edit, resume) re-checks that a still-future
    ``end_at`` leaves room for the next run; an ``end_at`` that already passed
    is left to the repository's reactivation check (``limits_exhausted``).
    """

    def checks(field: str) -> bool:
        return changed is None or field in changed

    if goal_objective is not None:
        if not isinstance(goal_objective, str):
            raise scheduler_error(422, "invalid_goal", "goal_objective must be a string", max_chars=MAX_GOAL_OBJECTIVE_CHARS)
        try:
            normalize_goal_objective(goal_objective)
        except ValueError as exc:
            raise scheduler_error(422, "invalid_goal", str(exc), max_chars=MAX_GOAL_OBJECTIVE_CHARS) from exc
        if context_mode != "fresh_thread_per_run":
            raise scheduler_error(422, "goal_requires_fresh_thread", "goal-backed schedules require fresh_thread_per_run")
    if max_runs is not None and checks("max_runs"):
        if isinstance(max_runs, bool) or not isinstance(max_runs, int) or max_runs < 1:
            raise scheduler_error(422, "invalid_max_runs", "max_runs must be a positive integer")
        if used > 0 and max_runs <= used:
            raise scheduler_error(422, "max_runs_not_above_used", f"max_runs must be greater than the {used} automatic runs already used", used=used)
    if end_at is not None and (checks("end_at") or checks("next_run_at")):
        end = _as_datetime(end_at)
        if end <= now and checks("end_at"):
            raise scheduler_error(422, "end_at_in_past", "end_at must be in the future")
        upcoming = _as_datetime(next_run_at)
        if end > now and upcoming is not None and end <= upcoming:
            raise scheduler_error(422, "end_at_before_first_run", "end_at must allow at least one scheduled occurrence")
    if require_limit_for_frequent and max_runs is None and end_at is None and is_frequent_schedule(schedule_type, schedule_spec):
        raise scheduler_error(422, "frequent_requires_limit", "Schedules more frequent than hourly require max_runs or end_at")


def _normalized_stop_condition(value: Any) -> str | None:
    if value is not None and not isinstance(value, str):
        raise scheduler_error(422, "invalid_stop_condition", "stop_condition must be a string", max_chars=MAX_STOP_CONDITION_CHARS)
    try:
        return normalize_stop_condition(value)
    except ValueError as exc:
        raise scheduler_error(422, "invalid_stop_condition", str(exc), max_chars=MAX_STOP_CONDITION_CHARS) from exc


def _check_once_time(schedule_type: str, upcoming: datetime | None, *, scheduler_config: Any, now: datetime) -> None:
    if schedule_type != "once":
        return
    if upcoming is None:
        raise scheduler_error(422, "once_in_past", "once schedule must be in the future")
    min_seconds = scheduler_config.min_once_delay_seconds
    if (upcoming - now).total_seconds() < min_seconds:
        raise scheduler_error(422, "once_too_soon", f"once schedule must be at least {min_seconds} seconds in the future", min_seconds=min_seconds)


def _validate_schedule(schedule_type: str, schedule_spec: dict[str, Any], timezone: str, *, scheduler_config: Any, now: datetime) -> tuple[dict[str, Any], datetime | None]:
    schedule_spec = dict(schedule_spec)
    try:
        validate_timezone(timezone)
    except ValueError as exc:
        raise scheduler_error(422, "invalid_timezone", str(exc)) from exc
    try:
        if schedule_type == "cron":
            raw_cron = schedule_spec.get("cron")
            if not isinstance(raw_cron, str):
                raise scheduler_error(422, "invalid_schedule", "cron schedule requires schedule_spec.cron")
            schedule_spec["cron"] = normalize_cron_expression(raw_cron)
        if schedule_type == "interval":
            validate_interval_seconds(schedule_spec, scheduler_config.min_once_delay_seconds)
        upcoming = next_run_at(schedule_type, schedule_spec, timezone, now=now)
    except (ValueError, OverflowError) as exc:
        raise scheduler_error(422, "invalid_schedule", str(exc)) from exc
    _check_once_time(schedule_type, upcoming, scheduler_config=scheduler_config, now=now)
    return schedule_spec, upcoming


async def validate_scheduled_task_create(
    body: Any,
    *,
    user_id: str,
    thread_store: Any,
    scheduler_config: Any,
    assistant_resolver: Callable[..., Awaitable[str]],
    now: datetime | None = None,
    conversation_rules: bool = False,
) -> dict[str, Any]:
    """Return repository ``create`` fields after the shared checks.

    The prompt is stored exactly as given; the stop condition is normalized
    into its own field. ``conversation_rules`` applies the chat-only rule
    that sub-hourly schedules need a safety cap.
    """
    reference = now or datetime.now(UTC)
    if body.context_mode not in CONTEXT_MODES:
        raise scheduler_error(422, "invalid_context_mode", "Unsupported context_mode")
    if body.context_mode == "reuse_thread":
        if not body.thread_id:
            raise scheduler_error(422, "reuse_thread_requires_thread", "reuse_thread requires thread_id")
        if not await thread_store.check_access(body.thread_id, user_id, require_existing=True):
            raise scheduler_error(404, "thread_not_found", "Thread not found")
    if body.schedule_type not in SCHEDULE_TYPES:
        raise scheduler_error(422, "invalid_schedule_type", "Unsupported schedule_type")
    schedule_spec, upcoming = await asyncio.to_thread(_validate_schedule, body.schedule_type, body.schedule_spec, body.timezone, scheduler_config=scheduler_config, now=reference)
    assistant_id = await assistant_resolver(body.assistant_id, user_id=user_id)
    stop_condition = _normalized_stop_condition(getattr(body, "stop_condition", None))
    goal_objective = getattr(body, "goal_objective", None)
    max_runs = getattr(body, "max_runs", None)
    end_at = await asyncio.to_thread(resolve_end_at, getattr(body, "end_at", None), body.timezone)
    validate_task_bounds(
        goal_objective=goal_objective,
        max_runs=max_runs,
        end_at=end_at,
        context_mode=body.context_mode,
        schedule_type=body.schedule_type,
        schedule_spec=schedule_spec,
        next_run_at=upcoming,
        now=reference,
        require_limit_for_frequent=conversation_rules,
    )
    return {
        "thread_id": body.thread_id,
        "context_mode": body.context_mode,
        "assistant_id": assistant_id,
        "title": body.title,
        "prompt": body.prompt,
        "stop_condition": stop_condition,
        "schedule_type": body.schedule_type,
        "schedule_spec": schedule_spec,
        "timezone": body.timezone,
        "next_run_at": upcoming,
        "goal_objective": goal_objective,
        "max_runs": max_runs,
        "end_at": end_at,
    }


def _recompute_schedule(existing: dict[str, Any], updates: dict[str, Any], *, scheduler_config: Any, now: datetime) -> None:
    schedule_type = str(updates.get("schedule_type", existing["schedule_type"]))
    if schedule_type != existing["schedule_type"] and not isinstance(updates.get("schedule_spec"), dict):
        raise scheduler_error(422, "invalid_schedule", "changing schedule_type requires schedule_spec")
    schedule_spec = dict(updates["schedule_spec"]) if isinstance(updates.get("schedule_spec"), dict) else dict(existing["schedule_spec"])
    timezone = str(updates.get("timezone", existing["timezone"]))
    try:
        if schedule_type == "cron":
            raw_cron = schedule_spec.get("cron")
            if not isinstance(raw_cron, str):
                raise scheduler_error(422, "invalid_schedule", "cron schedule requires schedule_spec.cron")
            schedule_spec["cron"] = normalize_cron_expression(raw_cron)
        if schedule_type == "interval":
            every_seconds = validate_interval_seconds(schedule_spec, scheduler_config.min_once_delay_seconds)
            try:
                previous_seconds = parse_interval_seconds(dict(existing["schedule_spec"])) if existing["schedule_type"] == "interval" else None
            except ValueError:
                previous_seconds = None
            # Re-saving an unchanged cadence keeps the next occurrence.
            if previous_seconds == every_seconds and existing.get("next_run_at") is not None:
                upcoming = existing["next_run_at"]
            else:
                upcoming = next_run_at(schedule_type, schedule_spec, timezone, now=now)
        else:
            upcoming = next_run_at(schedule_type, schedule_spec, timezone, now=now)
    except (ValueError, OverflowError) as exc:
        raise scheduler_error(422, "invalid_schedule", str(exc)) from exc
    _check_once_time(schedule_type, _as_datetime(upcoming), scheduler_config=scheduler_config, now=now)
    updates["schedule_spec"] = schedule_spec
    updates["next_run_at"] = upcoming
    # A terminal task whose schedule now has a future occurrence is re-armed:
    # claim_due_tasks only admits "enabled" rows. The repository then checks
    # its safety cap (limits_exhausted).
    if upcoming is not None and existing["status"] in TERMINAL_TASK_STATUSES:
        updates["status"] = "enabled"


async def validate_scheduled_task_update(
    existing: dict[str, Any],
    fields: dict[str, Any],
    *,
    user_id: str,
    thread_store: Any,
    scheduler_config: Any,
    assistant_resolver: Callable[..., Awaitable[str]],
    used: int,
    now: datetime,
) -> dict[str, Any]:
    """Return repository ``updates`` for a PATCH or chat update.

    ``fields`` holds only what the request set. ``None`` clears
    ``goal_objective``, ``max_runs``, ``end_at`` and ``stop_condition``; for
    other fields it means "unchanged", except ``assistant_id`` where it
    restores the default agent.
    """
    updates = {key: value for key, value in fields.items() if value is not None or key in CLEARABLE_FIELDS}
    if "assistant_id" in fields:
        updates["assistant_id"] = await assistant_resolver(fields["assistant_id"], user_id=user_id)
    if "context_mode" in updates and updates["context_mode"] not in CONTEXT_MODES:
        raise scheduler_error(422, "invalid_context_mode", "Unsupported context_mode")
    if "schedule_type" in updates and updates["schedule_type"] not in SCHEDULE_TYPES:
        raise scheduler_error(422, "invalid_schedule_type", "Unsupported schedule_type")
    effective_context_mode = str(updates.get("context_mode", existing["context_mode"]))
    effective_thread_id = updates.get("thread_id", existing.get("thread_id"))
    if effective_context_mode == "reuse_thread":
        if not effective_thread_id:
            raise scheduler_error(422, "reuse_thread_requires_thread", "reuse_thread requires thread_id")
        if not await thread_store.check_access(str(effective_thread_id), user_id, require_existing=True):
            raise scheduler_error(404, "thread_not_found", "Thread not found")
    elif effective_context_mode == "fresh_thread_per_run":
        updates["thread_id"] = None
    if "timezone" in updates:
        try:
            await asyncio.to_thread(validate_timezone, str(updates["timezone"]))
        except ValueError as exc:
            raise scheduler_error(422, "invalid_timezone", str(exc)) from exc
    if {"schedule_spec", "timezone", "schedule_type"} & updates.keys():
        await asyncio.to_thread(_recompute_schedule, existing, updates, scheduler_config=scheduler_config, now=now)
    timezone = str(updates.get("timezone", existing["timezone"]))
    if "stop_condition" in updates:
        updates["stop_condition"] = _normalized_stop_condition(updates["stop_condition"])
    if "end_at" in updates:
        updates["end_at"] = await asyncio.to_thread(resolve_end_at, updates["end_at"], timezone)
    validate_task_bounds(
        goal_objective=updates.get("goal_objective", existing.get("goal_objective")),
        max_runs=updates.get("max_runs", existing.get("max_runs")),
        end_at=updates.get("end_at", existing.get("end_at")),
        context_mode=effective_context_mode,
        schedule_type=str(updates.get("schedule_type", existing["schedule_type"])),
        schedule_spec=updates.get("schedule_spec", existing["schedule_spec"]),
        next_run_at=updates.get("next_run_at", existing.get("next_run_at")),
        now=now,
        used=used,
        require_limit_for_frequent=existing.get("origin_thread_id") is not None,
        changed=(_BOUND_FIELDS | {"next_run_at"}) & updates.keys(),
    )
    return updates


def prepare_resume_updates(existing: dict[str, Any], renewal: dict[str, Any], *, used: int, now: datetime) -> dict[str, Any]:
    """Repository ``updates`` that resume a paused or finished task.

    The next run is the stored one when still ahead, else recomputed from
    ``now`` (no catch-up run); a one-time task whose time passed cannot
    resume. ``renewal`` may set or clear (``None``) ``max_runs`` / ``end_at``
    in the same request; the repository rejects a reactivation whose cap is
    still used up. The unmet streak is kept. An enabled task needs nothing.
    """
    if existing.get("status") == "enabled":
        return {}
    renewal = {key: value for key, value in renewal.items() if key in {"max_runs", "end_at"}}
    upcoming = _as_datetime(existing.get("next_run_at"))
    if upcoming is None or upcoming <= now:
        try:
            upcoming = next_run_at(existing["schedule_type"], existing["schedule_spec"], existing["timezone"], now=now)
        except (ValueError, OverflowError) as exc:
            raise scheduler_error(422, "invalid_schedule", str(exc)) from exc
    if upcoming is None:
        raise scheduler_error(422, "once_time_passed", "This one-time task's time has passed; set a new run_at to run it again")
    updates: dict[str, Any] = {"status": "enabled", "next_run_at": upcoming}
    if is_host_pause_marker(existing.get("last_error")):
        # A later manual pause must not read as "Paused by agent".
        updates["last_error"] = None
    if "end_at" in renewal:
        renewal["end_at"] = resolve_end_at(renewal["end_at"], existing["timezone"])
    updates.update(renewal)
    validate_task_bounds(
        goal_objective=existing.get("goal_objective"),
        max_runs=updates.get("max_runs", existing.get("max_runs")),
        end_at=updates.get("end_at", existing.get("end_at")),
        context_mode=existing["context_mode"],
        schedule_type=existing["schedule_type"],
        schedule_spec=existing["schedule_spec"],
        next_run_at=upcoming,
        now=now,
        used=used,
        require_limit_for_frequent=existing.get("origin_thread_id") is not None,
        changed={*renewal, "next_run_at"},
    )
    return updates
