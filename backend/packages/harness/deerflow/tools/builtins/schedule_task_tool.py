"""Built-in tool for creating one-time scheduled runs from a conversation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command

from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime


def _error(tool_call_id: str, message: str) -> Command:
    return Command(update={"messages": [ToolMessage(content=f"Error: {message}", tool_call_id=tool_call_id, status="error")]})


def _parse_run_at(value: str, timezone: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed.astimezone(UTC)


def _resolve_fire_at(
    *,
    run_at: str | None,
    timezone: str,
    delay_seconds: int | None,
    now: datetime,
) -> datetime | str:
    has_run_at = isinstance(run_at, str) and bool(run_at.strip())
    has_delay = delay_seconds is not None
    if has_run_at == has_delay:
        return "Provide exactly one of run_at or delay_seconds."
    if has_delay:
        if not isinstance(delay_seconds, int) or delay_seconds <= 0:
            return "delay_seconds must be a positive integer."
        return now + timedelta(seconds=delay_seconds)
    try:
        return _parse_run_at(str(run_at), timezone)
    except ValueError as exc:
        return f"run_at must be an ISO-8601 datetime: {exc}"


@tool("schedule_task", parse_docstring=True)
async def schedule_task(
    runtime: Runtime,
    task_prompt: str,
    run_at: str | None = None,
    title: str | None = None,
    timezone: str = "UTC",
    delay_seconds: int | None = None,
    schedule_type: Literal["once"] = "once",
) -> Command:
    """Schedule a one-time DeerFlow run in the current conversation.

    Use this when the user asks DeerFlow to run a task once at a future time.
    For relative requests such as "in 3 minutes", pass delay_seconds instead of
    calculating the clock time yourself. For absolute requests such as "tomorrow
    at 18:00", convert the user's natural language time into an ISO-8601
    datetime before calling this tool. The first version supports one-time tasks
    only; do not use it for recurring schedules.

    Args:
        task_prompt: The instruction DeerFlow should execute when the task fires.
        run_at: Future ISO-8601 datetime. Include an offset when known, e.g. "2026-06-14T18:00:00+08:00". Required unless delay_seconds is provided.
        title: Optional short label for the scheduled task.
        timezone: IANA timezone used when run_at has no offset, e.g. "Asia/Shanghai".
        delay_seconds: Relative delay in seconds from the server's current time. Use this for "in N minutes/hours" requests.
        schedule_type: Must be "once"; recurring schedules are not supported yet.
    """
    tool_call_id = runtime.tool_call_id
    context = runtime.context if isinstance(runtime.context, dict) else {}
    thread_id = context.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        return _error(tool_call_id, "Cannot schedule a task without a current thread_id.")

    app_config = context.get("app_config")
    scheduler_config = getattr(app_config, "scheduler", None)
    if scheduler_config is not None and not getattr(scheduler_config, "enabled", False):
        return _error(tool_call_id, "Scheduled tasks are disabled. Set scheduler.enabled=true in config.yaml and restart Gateway.")

    if schedule_type != "once":
        return _error(tool_call_id, "Recurring schedules are not supported yet. Create a one-time scheduled task instead.")

    prompt = task_prompt.strip()
    if not prompt:
        return _error(tool_call_id, "task_prompt must not be empty.")

    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return _error(tool_call_id, f"Unknown timezone '{timezone}'. Use an IANA timezone such as 'UTC' or 'Asia/Shanghai'.")

    now = datetime.now(UTC)
    fire_at = _resolve_fire_at(run_at=run_at, timezone=timezone, delay_seconds=delay_seconds, now=now)
    if isinstance(fire_at, str):
        return _error(tool_call_id, fire_at)

    if fire_at <= now:
        return _error(tool_call_id, "run_at must be in the future.")

    session_factory = get_session_factory()
    if session_factory is None:
        return _error(tool_call_id, "Scheduled tasks require database.backend to be sqlite or postgres; memory persistence cannot survive restarts.")

    owner_user_id = resolve_runtime_user_id(runtime)
    repo = ScheduledTaskRepository(session_factory)
    task = await repo.create_once(
        owner_user_id=owner_user_id,
        thread_id=thread_id,
        prompt=prompt,
        run_at=fire_at,
        timezone=timezone,
        assistant_id=str(context.get("assistant_id") or "lead_agent"),
        agent_name=str(context.get("agent_name")) if context.get("agent_name") else None,
        title=title.strip() if isinstance(title, str) and title.strip() else None,
        channel_name=str(context.get("channel_name")) if context.get("channel_name") else None,
        chat_id=str(context.get("channel_chat_id")) if context.get("channel_chat_id") else None,
        topic_id=str(context.get("channel_topic_id")) if context.get("channel_topic_id") else None,
        thread_ts=str(context.get("channel_thread_ts")) if context.get("channel_thread_ts") else None,
        channel_user_id=str(context.get("channel_user_id")) if context.get("channel_user_id") else None,
        connection_id=str(context.get("channel_connection_id")) if context.get("channel_connection_id") else None,
        owner_channel_user_id=str(context.get("channel_owner_user_id")) if context.get("channel_owner_user_id") else None,
        metadata={"created_by": "schedule_task"},
    )
    content = f"Scheduled task {task['id']} for {task['run_at']}."
    return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})
