"""Cron tool for scheduling reminders and recurring tasks."""

import atexit
import os
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

import httpx
from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState

DEFAULT_GATEWAY_URL = "http://localhost:8001"
_CRON_API_CLIENT: httpx.Client | None = None


def _parse_time_to_ms(time_str: str) -> int | None:
    """Parse a time string to milliseconds timestamp."""
    time_str = time_str.strip()

    try:
        ts = int(time_str)
        if ts > 1e12:
            return ts
        if ts > 1e9:
            return ts * 1000
    except ValueError:
        pass

    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except ValueError:
        pass

    import re

    now_ms = int(datetime.now().timestamp() * 1000)
    match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", time_str)
    if match:
        now = datetime.now().astimezone()
        hour = int(match.group(1))
        minute = int(match.group(2))
        second = int(match.group(3) or 0)
        if hour > 23 or minute > 59 or second > 59:
            return None
        target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return int(target.timestamp() * 1000)

    match = re.match(r"in\s+(\d+)\s+(minute|hour|day|week)s?", time_str, re.I)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit == "minute":
            return now_ms + amount * 60 * 1000
        if unit == "hour":
            return now_ms + amount * 60 * 60 * 1000
        if unit == "day":
            return now_ms + amount * 24 * 60 * 60 * 1000
        if unit == "week":
            return now_ms + amount * 7 * 24 * 60 * 60 * 1000

    return None


def _parse_interval_to_ms(interval_str: str) -> int | None:
    """Parse an interval string to milliseconds."""
    interval_str = interval_str.strip()

    try:
        seconds = float(interval_str)
        return int(seconds * 1000)
    except ValueError:
        pass

    import re

    match = re.match(r"(\d+)\s*(minute|hour|day|week|sec(?:ond)?)s?", interval_str, re.I)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("sec"):
            return amount * 1000
        if unit.startswith("min"):
            return amount * 60 * 1000
        if unit.startswith("hour"):
            return amount * 60 * 60 * 1000
        if unit.startswith("day"):
            return amount * 24 * 60 * 60 * 1000
        if unit.startswith("week"):
            return amount * 7 * 24 * 60 * 60 * 1000

    match = re.match(r"(\d+)(s|m|h|d|w)", interval_str, re.I)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit == "s":
            return amount * 1000
        if unit == "m":
            return amount * 60 * 1000
        if unit == "h":
            return amount * 60 * 60 * 1000
        if unit == "d":
            return amount * 24 * 60 * 60 * 1000
        if unit == "w":
            return amount * 7 * 24 * 60 * 60 * 1000

    return None


def _is_cron_execution(runtime: ToolRuntime[ContextT, ThreadState] | None) -> bool:
    """Check whether the current tool call comes from a scheduled cron run."""
    if runtime is None:
        return False
    return bool(runtime.context.get("is_cron"))


def _get_gateway_url() -> str:
    """Resolve the gateway base URL for cron API calls."""
    env_url = os.getenv("DEERFLOW_GATEWAY_URL")
    if env_url:
        return env_url.rstrip("/")

    return DEFAULT_GATEWAY_URL


def _close_cron_api_client() -> None:
    """Close the shared cron API client during interpreter shutdown."""
    global _CRON_API_CLIENT
    if _CRON_API_CLIENT is not None and not _CRON_API_CLIENT.is_closed:
        _CRON_API_CLIENT.close()
    _CRON_API_CLIENT = None


def _get_cron_api_client() -> httpx.Client:
    """Reuse a shared client so cron tool requests benefit from keep-alive pooling."""
    global _CRON_API_CLIENT
    if _CRON_API_CLIENT is None or _CRON_API_CLIENT.is_closed:
        _CRON_API_CLIENT = httpx.Client(timeout=10)
    return _CRON_API_CLIENT


atexit.register(_close_cron_api_client)


def _cron_api_request(method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None) -> Any:
    """Perform a request to the cron API and return decoded JSON."""
    url = f"{_get_gateway_url()}{path}"
    try:
        response = _get_cron_api_client().request(method, url, params=params, json=json_body)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail")
        except Exception:
            detail = exc.response.text
        raise RuntimeError(detail or f"Gateway request failed with status {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not reach cron service at {url}: {exc}") from exc


def _get_thread_id(runtime: ToolRuntime[ContextT, ThreadState] | None) -> str | None:
    """Extract the current DeerFlow thread ID."""
    if runtime is None:
        return None
    thread_id = runtime.context.get("thread_id")
    return thread_id if isinstance(thread_id, str) and thread_id else None


def _normalize_optional_string(value: Any, *, disallow: set[str] | None = None) -> str | None:
    """Normalize optional string values read from runtime metadata."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if disallow and normalized in disallow:
        return None
    return normalized


def _get_run_settings(
    runtime: ToolRuntime[ContextT, ThreadState] | None,
) -> tuple[str | None, str | None, bool | None, bool | None]:
    """Extract current assistant/runtime settings for later scheduled execution."""
    if runtime is None:
        return None, None, None, None

    configurable = runtime.config.get("configurable", {})
    metadata = runtime.config.get("metadata", {})
    assistant_id = configurable.get("assistant_id") or metadata.get("assistant_id")
    agent_name = configurable.get("agent_name") or metadata.get("agent_name")
    thinking_enabled = metadata.get("thinking_enabled")
    subagent_enabled = metadata.get("subagent_enabled")

    return (
        _normalize_optional_string(assistant_id),
        _normalize_optional_string(agent_name, disallow={"default"}),
        thinking_enabled if isinstance(thinking_enabled, bool) else None,
        subagent_enabled if isinstance(subagent_enabled, bool) else None,
    )


def _get_delivery_target(runtime: ToolRuntime[ContextT, ThreadState] | None) -> tuple[str | None, str | None, str | None]:
    """Extract IM delivery target information when the request came from a channel."""
    if runtime is None:
        return None, None, None
    return (
        _normalize_optional_string(runtime.context.get("channel_name")),
        _normalize_optional_string(runtime.context.get("chat_id")),
        _normalize_optional_string(runtime.context.get("thread_ts")),
    )


def _format_jobs(jobs: list[dict[str, Any]]) -> str:
    """Format jobs returned by the cron API for LLM consumption."""
    if not jobs:
        return "No scheduled tasks found."

    lines = ["Scheduled tasks:"]
    for job in jobs:
        status = "enabled" if job.get("enabled") else "disabled"
        state = job.get("state", {})
        next_run = state.get("next_run_at")
        next_suffix = f" (next: {next_run})" if isinstance(next_run, str) and next_run else ""
        lines.append(f"  [{status}] {job['id']}: {job['name']}{next_suffix}")
    return "\n".join(lines)


def _build_schedule_dict(
    *,
    kind: Literal["at", "every", "cron"],
    at_ms: int | None = None,
    every_ms: int | None = None,
    expr: str | None = None,
    tz: str | None = None,
) -> dict[str, Any]:
    """Build the gateway schedule payload without importing backend-only types."""
    return {
        "kind": kind,
        "at_ms": at_ms,
        "every_ms": every_ms,
        "expr": expr,
        "tz": tz,
    }


def _build_payload_dict(
    *,
    message: str,
    deliver: bool,
    channel: str | None,
    to: str | None,
    thread_ts: str | None,
    thread_id: str | None,
    assistant_id: str | None,
    agent_name: str | None,
    thinking_enabled: bool | None,
    subagent_enabled: bool | None,
) -> dict[str, Any]:
    """Build the gateway execution payload without importing backend-only types."""
    return {
        "kind": "agent_turn",
        "message": message,
        "deliver": deliver,
        "channel": channel,
        "to": to,
        "thread_ts": thread_ts,
        "thread_id": thread_id,
        "assistant_id": assistant_id,
        "agent_name": agent_name,
        "thinking_enabled": thinking_enabled,
        "subagent_enabled": subagent_enabled,
    }


@tool("cron", parse_docstring=True)
def cron_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    action: Literal["add", "list", "remove", "enable", "disable"],
    tool_call_id: Annotated[str, InjectedToolCallId],
    name: str | None = None,
    message: str | None = None,
    at: str | None = None,
    every: str | None = None,
    cron_expr: str | None = None,
    timezone: str | None = None,
    job_id: str | None = None,
    deliver: bool = False,
) -> str:
    """Schedule reminders and recurring tasks.

    This tool allows you to create, list, and manage scheduled tasks.
    Tasks can be one-time (at a specific time) or recurring (at intervals or cron expressions).

    When to use:
    - User asks to be reminded at a specific time
    - User wants recurring reminders (e.g., "remind me every hour")
    - User wants to schedule a task using cron syntax (e.g., "every weekday at 9am")

    Args:
        action: The action to perform. Supported values are add, list, remove, enable, and disable.
        name: Human-readable name for the task (used with "add")
        message: The reminder message or task description (used with "add")
        at: When to run a one-time task. Supports ISO datetime, local time like "00:08", relative time like "in 5 minutes", or Unix timestamp
        every: Interval for recurring tasks. Supports "5 minutes", "1 hour", "2 days", or short form like "5m"
        cron_expr: Cron expression for complex schedules (e.g., "0 9 * * 1-5" for weekdays at 9am)
        timezone: Timezone for cron expressions (e.g., "Asia/Shanghai", "America/New_York")
        job_id: ID of the job to remove/enable/disable
        deliver: If True, deliver the result to the originating channel when task completes
    """
    del tool_call_id

    if _is_cron_execution(runtime) and action == "add":
        return "Error: Cannot schedule new cron jobs from within a cron job execution"

    if action == "list":
        jobs = _cron_api_request("GET", "/api/cron", params={"include_disabled": True})
        return _format_jobs(jobs)

    if action == "add":
        if not message:
            return "Error: 'message' is required when adding a task"
        if not name:
            name = message[:50] + ("..." if len(message) > 50 else "")

        schedule: dict[str, Any] | None = None
        if at:
            at_ms = _parse_time_to_ms(at)
            if at_ms is None:
                return f"Error: Could not parse time '{at}'. Use ISO format or relative time like 'in 5 minutes'"
            schedule = _build_schedule_dict(kind="at", at_ms=at_ms)
        elif every:
            every_ms = _parse_interval_to_ms(every)
            if every_ms is None:
                return f"Error: Could not parse interval '{every}'. Use format like '5 minutes' or '1h'"
            schedule = _build_schedule_dict(kind="every", every_ms=every_ms)
        elif cron_expr:
            schedule = _build_schedule_dict(kind="cron", expr=cron_expr, tz=timezone)
        else:
            return "Error: Must specify one of 'at', 'every', or 'cron_expr'"

        thread_id = _get_thread_id(runtime)
        assistant_id, agent_name, thinking_enabled, subagent_enabled = _get_run_settings(runtime)
        channel_name, chat_id, thread_ts = _get_delivery_target(runtime)

        payload = _build_payload_dict(
            message=message,
            deliver=deliver,
            channel=channel_name if deliver else None,
            to=chat_id if deliver else None,
            thread_ts=thread_ts if deliver else None,
            thread_id=thread_id,
            assistant_id=assistant_id,
            agent_name=agent_name,
            thinking_enabled=thinking_enabled,
            subagent_enabled=subagent_enabled,
        )

        job = _cron_api_request(
            "POST",
            "/api/cron",
            json_body={
                "name": name,
                "schedule": schedule,
                "payload": payload,
                "enabled": True,
                "delete_after_run": schedule["kind"] == "at",
            },
        )

        next_run = job.get("state", {}).get("next_run_at")
        next_str = f" at {next_run}" if isinstance(next_run, str) and next_run else ""
        return f"Task scheduled: '{name}' (id: {job['id']}){next_str}"

    if action == "remove":
        if not job_id:
            return "Error: 'job_id' is required for remove action"
        _cron_api_request("DELETE", f"/api/cron/{job_id}")
        return f"Task {job_id} removed"

    if action == "enable":
        if not job_id:
            return "Error: 'job_id' is required for enable action"
        _cron_api_request("POST", f"/api/cron/{job_id}/enable")
        return f"Task {job_id} enabled"

    if action == "disable":
        if not job_id:
            return "Error: 'job_id' is required for disable action"
        _cron_api_request("POST", f"/api/cron/{job_id}/disable")
        return f"Task {job_id} disabled"

    return f"Unknown action: {action}"
