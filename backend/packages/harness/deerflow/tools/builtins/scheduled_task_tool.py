"""Agent tool for managing scheduled tasks from chat.

The scheduler itself lives in the Gateway process. This tool is only the
model-facing control surface for the current chat user: create, list, and
delete persisted scheduled jobs.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command

from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.scheduled_jobs import ScheduledJobRepository
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.scheduler.triggers import (
    AtTrigger,
    CronTrigger,
    Trigger,
    parse_user_when,
    trigger_from_persisted,
)
from deerflow.tools.types import Runtime
from deerflow.utils.time import coerce_datetime

logger = logging.getLogger(__name__)

MAX_ENABLED_JOBS_PER_USER: int = 20
MIN_CRON_INTERVAL_SECONDS: int = 1800
DEFAULT_TIMEZONE_ENV: str = "DEERFLOW_TIMEZONE"
DEFAULT_LIST_LIMIT: int = 20
MAX_LIST_LIMIT: int = 50

_WINDOWS_TIMEZONE_TO_IANA: dict[str, str] = {
    "AUS Eastern Standard Time": "Australia/Sydney",
    "Atlantic Standard Time": "America/Halifax",
    "Central Standard Time": "America/Chicago",
    "China Standard Time": "Asia/Shanghai",
    "Eastern Standard Time": "America/New_York",
    "GMT Standard Time": "Europe/London",
    "Korea Standard Time": "Asia/Seoul",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "Romance Standard Time": "Europe/Paris",
    "Singapore Standard Time": "Asia/Singapore",
    "Taipei Standard Time": "Asia/Taipei",
    "Tokyo Standard Time": "Asia/Tokyo",
    "US Mountain Standard Time": "America/Phoenix",
    "UTC": "UTC",
    "W. Europe Standard Time": "Europe/Berlin",
    "\u4e2d\u56fd\u6807\u51c6\u65f6\u95f4": "Asia/Shanghai",
    "\u534f\u8c03\u4e16\u754c\u65f6": "UTC",
}


@tool("scheduled_task", parse_docstring=True)
async def scheduled_task(
    action: Literal["create", "list", "delete"],
    runtime: Runtime,
    name: str | None = None,
    when: str | None = None,
    description: str | None = None,
    job_id: str | None = None,
    agent_name: str | None = None,
    thread_strategy: Literal["new", "fixed"] = "new",
    delete_after_run: bool | None = None,
    timezone: str | None = None,
    include_disabled: bool = False,
    limit: int = DEFAULT_LIST_LIMIT,
) -> Command:
    """Create, list, or delete scheduled tasks for the current user.

    Use this tool when the user wants to manage automatic scheduled work.
    For deletion, list tasks first unless the user already provided the
    exact task ID. Do not guess IDs from memory.

    Args:
        action: Operation to perform. Use "create" to create a task,
            "list" to show existing tasks, or "delete" to delete by ID.
        name: Short human-readable task name for action="create".
        when: Schedule expression for action="create". Accepts relative
            durations such as "20m", recurring intervals such as "every 1h",
            or a 5-field cron expression such as "0 9 * * *".
        description: Prompt the Agent should run for action="create".
        job_id: Exact scheduled task ID for action="delete".
        agent_name: Optional custom agent to run for action="create".
        thread_strategy: Use "new" to create a fresh thread per run, or
            "fixed" to reuse one thread across runs.
        delete_after_run: Override lifecycle for action="create". When
            omitted, one-shot tasks delete after running and recurring tasks do not.
        timezone: IANA timezone for wall-clock schedules and displayed times,
            for example "Asia/Shanghai". Defaults to the backend runtime timezone.
        include_disabled: Include disabled tasks when action="list".
        limit: Maximum number of tasks to show when action="list".

    Returns:
        Command with a ToolMessage describing the result.
    """
    tool_call_id = runtime.tool_call_id
    user_id = resolve_runtime_user_id(runtime)
    display_tz = timezone or _default_timezone()

    sf = get_session_factory()
    if sf is None:
        return _err(tool_call_id, "persistence engine not initialised")
    repo = ScheduledJobRepository(sf)

    if action == "create":
        return await _create_task(
            repo,
            runtime=runtime,
            tool_call_id=tool_call_id,
            user_id=user_id,
            name=name,
            when=when,
            description=description,
            agent_name=agent_name,
            thread_strategy=thread_strategy,
            delete_after_run=delete_after_run,
            display_tz=display_tz,
        )
    if action == "list":
        return await _list_tasks(
            repo,
            tool_call_id=tool_call_id,
            user_id=user_id,
            include_disabled=include_disabled,
            limit=limit,
            display_tz=display_tz,
        )
    if action == "delete":
        return await _delete_task(
            repo,
            tool_call_id=tool_call_id,
            user_id=user_id,
            job_id=job_id,
            display_tz=display_tz,
        )
    return _err(tool_call_id, f"unsupported action: {action!r}")


async def _create_task(
    repo: ScheduledJobRepository,
    *,
    runtime: Runtime,
    tool_call_id: str,
    user_id: str,
    name: str | None,
    when: str | None,
    description: str | None,
    agent_name: str | None,
    thread_strategy: Literal["new", "fixed"],
    delete_after_run: bool | None,
    display_tz: str,
) -> Command:
    clean_name = (name or "").strip()
    clean_when = (when or "").strip()
    clean_description = (description or "").strip()

    if not clean_name:
        return _err(tool_call_id, "name is required for action='create'")
    if len(clean_name) > 200:
        return _err(tool_call_id, "name exceeds 200 characters")
    if not clean_when:
        return _err(tool_call_id, "when is required for action='create'")
    if not clean_description:
        return _err(tool_call_id, "description is required for action='create'")

    try:
        trigger: Trigger = parse_user_when(clean_when, tz=display_tz)
    except ValueError as exc:
        return _err(tool_call_id, f"invalid schedule {clean_when!r}: {exc}")

    if isinstance(trigger, CronTrigger):
        gap = _measure_cron_interval(trigger)
        if gap is not None and gap < MIN_CRON_INTERVAL_SECONDS:
            return _err(
                tool_call_id,
                f"cron cadence too tight: {int(gap)}s between runs; minimum is {MIN_CRON_INTERVAL_SECONDS}s (30 minutes)",
            )

    try:
        enabled_count = await repo.count_enabled_jobs(user_id=user_id)
    except Exception as exc:
        logger.exception("scheduled_task quota check failed")
        return _err(tool_call_id, f"quota check failed: {exc}")

    if enabled_count >= MAX_ENABLED_JOBS_PER_USER:
        return _err(
            tool_call_id,
            f"quota exhausted: {enabled_count}/{MAX_ENABLED_JOBS_PER_USER} enabled jobs; delete an existing task before creating a new one",
        )

    now = datetime.now(UTC)
    job_id = repo.new_job_id()
    next_run_at = trigger.compute_next(None, now=now, job_id=job_id)
    if next_run_at is None:
        return _err(tool_call_id, "trigger has no upcoming run time")

    if delete_after_run is None:
        delete_after_run = isinstance(trigger, AtTrigger)

    source_channel = (runtime.context or {}).get("source_channel", "web")
    try:
        job = await repo.create_job(
            name=clean_name,
            description=clean_description,
            trigger_type=trigger.type,
            trigger_data=trigger.to_dict(),
            next_run_at=next_run_at,
            thread_strategy=thread_strategy,
            agent_name=agent_name,
            delete_after_run=delete_after_run,
            source_channel=source_channel,
            job_id=job_id,
            user_id=user_id,
        )
    except Exception as exc:
        logger.exception("scheduled_task create failed")
        return _err(tool_call_id, f"failed to create task: {exc}")

    logger.info(
        "scheduled_task created via chat: job=%s user=%s source=%s trigger=%s",
        job["id"],
        user_id,
        source_channel,
        trigger.type,
    )

    content = (
        "Scheduled task created.\n"
        f"Name: {job['name']}\n"
        f"ID: {job['id']}\n"
        f"Timezone: {display_tz}\n"
        f"Schedule: {_human_schedule(trigger, next_run_at, display_tz)}\n"
        f"Next run (local): {_format_display_datetime(next_run_at, display_tz)}\n"
        f"Next run (UTC): {next_run_at.astimezone(UTC).isoformat()}\n"
        f"Deliver to: {_human_source(source_channel)}"
    )
    return _ok(tool_call_id, content)


async def _list_tasks(
    repo: ScheduledJobRepository,
    *,
    tool_call_id: str,
    user_id: str,
    include_disabled: bool,
    limit: int,
    display_tz: str,
) -> Command:
    safe_limit = min(max(int(limit or DEFAULT_LIST_LIMIT), 1), MAX_LIST_LIMIT)
    try:
        rows = await repo.list_jobs(
            include_disabled=include_disabled,
            limit=safe_limit,
            user_id=user_id,
        )
    except Exception as exc:
        logger.exception("scheduled_task list failed")
        return _err(tool_call_id, f"failed to list tasks: {exc}")

    if not rows:
        qualifier = "scheduled tasks" if include_disabled else "enabled scheduled tasks"
        return _ok(tool_call_id, f"No {qualifier} found.")

    lines = [
        f"Scheduled tasks ({len(rows)} shown):",
    ]
    for row in rows:
        lines.append(_format_job_summary(row, display_tz=display_tz))
    return _ok(tool_call_id, "\n\n".join(lines))


async def _delete_task(
    repo: ScheduledJobRepository,
    *,
    tool_call_id: str,
    user_id: str,
    job_id: str | None,
    display_tz: str,
) -> Command:
    clean_job_id = (job_id or "").strip()
    if not clean_job_id:
        return _err(tool_call_id, "job_id is required for action='delete'; call action='list' first if needed")

    try:
        existing = await repo.get_job(clean_job_id, user_id=user_id)
    except Exception as exc:
        logger.exception("scheduled_task get before delete failed")
        return _err(tool_call_id, f"failed to load task before delete: {exc}")

    if existing is None:
        return _err(tool_call_id, f"scheduled task not found: {clean_job_id}")

    try:
        deleted = await repo.delete_job(clean_job_id, user_id=user_id)
    except Exception as exc:
        logger.exception("scheduled_task delete failed")
        return _err(tool_call_id, f"failed to delete task: {exc}")

    if not deleted:
        return _err(tool_call_id, f"scheduled task not found: {clean_job_id}")

    return _ok(
        tool_call_id,
        f"Scheduled task deleted.\nName: {existing['name']}\nID: {existing['id']}\nPrevious next run: {_format_optional_datetime(existing.get('next_run_at'), display_tz)}",
    )


def _ok(tool_call_id: str, content: str) -> Command:
    return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})


def _err(tool_call_id: str, message: str) -> Command:
    return Command(update={"messages": [ToolMessage(content=f"Error: {message}", tool_call_id=tool_call_id, status="error")]})


def _default_timezone() -> str:
    """Return the default user-facing timezone name."""
    return _runtime_timezone() or _configured_timezone() or "UTC"


def _configured_timezone() -> str | None:
    for value in (os.getenv(DEFAULT_TIMEZONE_ENV), os.getenv("TZ")):
        resolved = _valid_timezone_name(value)
        if resolved is not None:
            return resolved
    return None


def _runtime_timezone() -> str | None:
    local_dt = datetime.now().astimezone()
    for value in _runtime_timezone_candidates(local_dt):
        resolved = _valid_timezone_name(value) or _WINDOWS_TIMEZONE_TO_IANA.get(value)
        if resolved is not None and _valid_timezone_name(resolved) is not None:
            return resolved
    return None


def _runtime_timezone_candidates(local_dt: datetime):
    tzinfo_obj = local_dt.tzinfo
    key = getattr(tzinfo_obj, "key", None)
    if key:
        yield key

    try:
        tzname = local_dt.tzname()
    except Exception:
        tzname = None
    if tzname:
        yield tzname

    if tzinfo_obj is not None:
        yield str(tzinfo_obj)

    if os.name == "nt":
        yield from _windows_registry_timezone_candidates()
    yield from _linux_localtime_candidates()


def _windows_registry_timezone_candidates():
    try:
        import winreg
    except Exception:
        return

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
        ) as key:
            for value_name in ("TimeZoneKeyName", "StandardName"):
                try:
                    value, _ = winreg.QueryValueEx(key, value_name)
                except OSError:
                    continue
                if value:
                    yield str(value)
    except OSError:
        return


def _linux_localtime_candidates():
    timezone_file = Path("/etc/timezone")
    try:
        value = timezone_file.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if value:
        yield value

    localtime_path = Path("/etc/localtime")
    try:
        resolved = str(localtime_path.resolve())
    except OSError:
        return
    marker = "/zoneinfo/"
    if marker in resolved:
        yield resolved.split(marker, 1)[1]


def _valid_timezone_name(value: str | None) -> str | None:
    if not value:
        return None
    if value.upper() == "UTC":
        return "UTC"
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return None
    return value


def _resolve_display_timezone(tz_name: str | None) -> tzinfo:
    if not tz_name or tz_name.upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning("unknown display timezone %r, falling back to UTC", tz_name)
        return UTC


def _format_offset(dt: datetime) -> str:
    offset = dt.strftime("%z")
    if len(offset) == 5:
        return f"{offset[:3]}:{offset[3:]}"
    return offset or "+00:00"


def _format_display_datetime(dt: datetime, tz_name: str | None) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    local_dt = dt.astimezone(_resolve_display_timezone(tz_name))
    tz_label = tz_name or "UTC"
    return f"{local_dt.strftime('%Y-%m-%d %H:%M:%S')} {_format_offset(local_dt)} ({tz_label})"


def _format_optional_datetime(value: object, tz_name: str | None) -> str:
    dt = coerce_datetime(value)
    if dt is None:
        return "none"
    return _format_display_datetime(dt, tz_name)


def _measure_cron_interval(trigger: CronTrigger) -> float | None:
    """Sample the next two runs to estimate cadence in seconds."""
    now = datetime.now(UTC)
    n1 = trigger.compute_next(None, now=now, job_id="quota-check")
    if n1 is None:
        return None
    n2 = trigger.compute_next(n1, now=n1, job_id="quota-check")
    if n2 is None:
        return None
    return (n2 - n1).total_seconds()


def _human_schedule(trigger: Trigger, next_run: datetime, tz_name: str | None) -> str:
    if isinstance(trigger, AtTrigger):
        return f"once at {_format_display_datetime(trigger.at_time, tz_name)}"
    return trigger.human_readable()


def _human_source(source_channel: str) -> str:
    if source_channel == "web":
        return "web notification"
    if source_channel.startswith("im:"):
        parts = source_channel.split(":", 3)
        if len(parts) >= 4:
            platform = parts[1]
            conv = parts[2]
            return f"{platform} {conv}"
        if len(parts) == 3:
            return parts[1]
    return source_channel


def _format_job_summary(row: dict[str, Any], *, display_tz: str) -> str:
    trigger = _trigger_from_row(row)
    next_run = coerce_datetime(row.get("next_run_at"))
    status = "enabled" if row.get("enabled") else "disabled"
    schedule = _human_schedule(trigger, next_run or datetime.now(UTC), display_tz) if trigger else str(row.get("trigger_data") or row.get("trigger_type") or "unknown")

    return (
        f"- {row.get('name')} [{status}]\n"
        f"  ID: {row.get('id')}\n"
        f"  Schedule: {schedule}\n"
        f"  Next run: {_format_optional_datetime(row.get('next_run_at'), display_tz)}\n"
        f"  Last status: {row.get('last_status') or 'none'}\n"
        f"  Deliver to: {_human_source(str(row.get('source_channel') or 'web'))}"
    )


def _trigger_from_row(row: dict[str, Any]) -> Trigger | None:
    try:
        data = row.get("trigger_data") if isinstance(row.get("trigger_data"), dict) else {}
        return trigger_from_persisted(str(row.get("trigger_type") or ""), data)
    except Exception:
        logger.warning("failed to reconstruct scheduled task trigger for job %s", row.get("id"), exc_info=True)
        return None
