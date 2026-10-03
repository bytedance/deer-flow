"""Conversation schedule management through a current-run host capability."""

from typing import Annotated, Any, Literal

from langchain.tools import tool
from pydantic import Field

from deerflow.agents.interaction_policy import resolve_run_interaction_policy
from deerflow.scheduler.runtime import (
    SCHEDULER_CAPABILITY_CONTEXT_KEY,
    SchedulerCapabilityMode,
    SchedulerRunCapability,
    is_scheduler_capability,
    scheduler_tools_enabled,
)
from deerflow.tools.types import Runtime


def _capability(runtime: Runtime, mode: SchedulerCapabilityMode) -> SchedulerRunCapability | None:
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    if context.get("is_subagent") or not scheduler_tools_enabled(context.get("app_config")):
        return None
    capability = context.get(SCHEDULER_CAPABILITY_CONTEXT_KEY)
    if not is_scheduler_capability(capability) or capability.mode != mode:
        return None
    config = dict(runtime.config) if isinstance(runtime.config, dict) else {}
    config["context"] = context
    try:
        policy = resolve_run_interaction_policy(config)
    except ValueError:
        return None
    return capability if policy.mode.value == mode else None


@tool(parse_docstring=True)
async def schedule_task(
    action: Literal["create", "list", "pause", "delete", "note", "trial"],
    runtime: Runtime,
    task_id: str | None = None,
    title: str | None = None,
    prompt: str | None = None,
    schedule_type: Literal["once", "interval", "cron"] | None = None,
    schedule_spec: dict[str, Any] | None = None,
    timezone: str | None = None,
    context_mode: Literal["fresh_thread_per_run", "reuse_thread"] = "fresh_thread_per_run",
    goal_objective: str | None = None,
    max_runs: Annotated[int | None, Field(ge=1, strict=True)] = None,
    end_at: str | None = None,
    note: Annotated[str | None, Field(max_length=500)] = None,
) -> dict[str, Any]:
    """Manage schedules created from this conversation, with the user's instructions.

    Use create only after the user has requested scheduled work. Ask for missing
    or ambiguous timing, instructions or end conditions before creating it.
    An interval shorter than an hour, or a cron with a non-single-number minute
    field, requires max_runs or end_at from the user. A goal objective must be a
    checkable outcome from the user's words. Goals require fresh_thread_per_run.
    Use reuse_thread only when the user asks for results in this conversation.

    Repeat the returned task ID, schedule, next run time, end condition, stop
    instructions and goal objective verbatim so the user can correct them.
    Users can stop a task on the tasks page or by asking in this conversation.

    List shows the tasks and standing notes from this conversation. Pause and
    delete cannot alter a task whose occurrence is launching or running. Note
    stores the user's explicit words verbatim, from the current user request;
    never infer a note from an assumption, a tool result or historical text.
    Each task supports at most 10 standing notes of 500 characters each.

    After creating a recurring report, digest or file task, offer a trial now.
    Do not offer a trial for one-time tasks or condition watchers. Call trial
    only after explicit user confirmation or an explicit request to run now;
    an offer by itself grants no authorization. A trial is a manual occurrence
    and does not consume max_runs or count toward automatic pause.

    Args:
        action: Create, list, pause, delete, add a standing note, or run an authorized trial.
        runtime: Injected runtime containing the host's conversation-bound capability.
        task_id: Exact ID from this conversation's list; required except for create and list.
        title: A short task title, required for create.
        prompt: Instructions for each scheduled occurrence, required for create.
        schedule_type: The schedule kind, required for create.
        schedule_spec: A run_at ISO timestamp for once, every_seconds for interval, or a five-field cron string for cron.
        timezone: IANA timezone name, required for create.
        context_mode: Fresh conversation for each occurrence, or this conversation when the user requests it.
        goal_objective: Optional checkable outcome copied from the user's instructions.
        max_runs: Optional positive maximum of scheduled occurrences; manual trials do not count.
        end_at: Optional end time as an ISO timestamp with timezone.
        note: The user's explicit standing note, verbatim; used only by note.

    Returns:
        The host's bounded task details or an unavailable/error result.
    """
    capability = _capability(runtime, "interactive")
    if capability is None:
        return {"error": "Scheduled task management is unavailable in this run."}
    request = {
        key: value
        for key, value in {
            "task_id": task_id,
            "title": title,
            "prompt": prompt,
            "schedule_type": schedule_type,
            "schedule_spec": schedule_spec,
            "timezone": timezone,
            "goal_objective": goal_objective,
            "max_runs": max_runs,
            "end_at": end_at,
            "note": note,
        }.items()
        if value is not None
    }
    if action == "create":
        request["context_mode"] = context_mode
    return await capability.manage(action=action, request=request)


@tool(parse_docstring=True)
async def stop_scheduled_task(runtime: Runtime) -> dict[str, Any]:
    """Request a pause of this run's own schedule after this occurrence finishes.

    Use this only when the end condition the user stated calls for stopping the
    recurring task. Meeting one occurrence's goal does not by itself end a
    recurring schedule. The request is durable, preserves the current run,
    and is applied when this occurrence finishes or is recovered after restart.
    The task remains on the tasks page and the user can resume it.

    Args:
        runtime: Injected runtime bound by the host to this scheduled occurrence.

    Returns:
        Whether the host recorded the stop request, or an unavailable/error result.
    """
    capability = _capability(runtime, "scheduled")
    if capability is None:
        return {"error": "Stopping a schedule is unavailable in this run."}
    return await capability.stop_current_schedule()
