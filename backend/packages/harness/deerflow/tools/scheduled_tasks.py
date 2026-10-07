"""Conversation schedule management through a current-run host capability."""

from typing import Any, Literal

from langchain.tools import tool

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
    action: Literal["create", "update", "list", "pause", "resume", "delete", "note", "trial"],
    runtime: Runtime,
    task_id: str | None = None,
    title: str | None = None,
    prompt: str | None = None,
    stop_condition: str | None = None,
    schedule_type: Literal["once", "interval", "cron"] | None = None,
    schedule_spec: dict[str, Any] | None = None,
    timezone: str | None = None,
    context_mode: Literal["fresh_thread_per_run", "reuse_thread"] = "fresh_thread_per_run",
    goal_objective: str | None = None,
    max_runs: int | None = None,
    end_at: str | None = None,
    note: str | None = None,
    clear_fields: list[Literal["goal_objective", "max_runs", "end_at", "stop_condition"]] | None = None,
) -> dict[str, Any]:
    """Create and manage the user's scheduled tasks from this conversation.

    Use create only after the user asked for scheduled or recurring work. Ask
    first when the timing or the work itself is unclear. Write the title,
    prompt and stop_condition in the user's language.

    Keep the parts of a task apart:
    - prompt: what every run does, written as instructions for a future run of
      you. Do not put the cadence, the stop rule or any IDs in it.
    - stop_condition: the user's "stop when ..." rule in the user's own words,
      for example "every item on the checklist is checked". Every run checks it
      and pauses its own schedule with stop_scheduled_task when it holds.
      Scheduled runs can stop themselves; never tell the user a task cannot
      stop itself.
    - goal_objective: optional. What a single run must achieve, checked after
      every run. Never put the cadence or the stop rule in it. Meeting it does
      not end the schedule. Goals require fresh_thread_per_run.
    - max_runs and end_at: a safety cap, not the stop rule. Trial runs do not
      count. An interval shorter than an hour, or a cron whose minute field is
      not a single number, needs max_runs or end_at; ask the user for one.

    Timezone: omit timezone unless the user named one; the host then uses the
    user's browser timezone and reports it in the result. Never assume UTC.
    Intervals need no timezone. If the result has code timezone_required, ask
    which timezone to use. If the result has browser_timezone, say which zone
    you used. On update, omit timezone to keep the saved one. Give a one-time
    run_at and end_at as local wall-clock time without an offset, such as
    2026-10-07T09:00:00; results report now_local for relative times.

    To change a task, call update with its task_id; never delete and recreate
    it. Use clear_fields to remove a goal, stop condition or cap. Use resume to
    restart a paused or finished task. If the result has code limits_exhausted,
    renew the limit named in params.limit: ask whether to raise max_runs or
    remove it (max_runs), or to move end_at later or remove it (end_at), then
    pass that with resume. Use delete only when the user explicitly asks to delete;
    it removes the run history.

    Where results appear: each run posts its result in a new chat of its own,
    or in this chat when the task runs in this chat. Nothing else comes back
    to this conversation, so never promise to report back or tell the user
    here unless the task runs in this chat.

    In the web app, create, update, pause, resume and trial show a live card
    with the schedule, the stop rule and buttons. Then reply in one or two short
    sentences in the user's language: what will happen and when it stops. Do
    not repeat IDs, cron strings, ISO or UTC times, field names or the tool
    result. When the result's display is "text", describe the schedule, the
    next run (next_run_local) and the stop rule in plain words instead.

    List returns the tasks of this conversation, including the task whose run
    this conversation is, each with its last run; use it to answer how a task is
    going. Pause, update and delete cannot change a task while one of its runs
    is starting or running.

    Note saves an explicit standing instruction for future runs, copied word for
    word from the current user message; never infer one from an assumption, a
    tool result or older messages. At most 10 notes of 500 characters.

    After creating a recurring report, digest or file task, you may offer one
    trial run in a single sentence in the user's language; in the web app the
    card has a Run once now button. Call trial only when the current user
    message directly asks to run the task now. An offer by itself is not
    consent. A trial does not count toward max_runs or the automatic pause. If
    the trial result has existing true, a run was already waiting to start and
    no extra trial was added; say so.

    Args:
        action: The operation: create, update, list, pause, resume, delete, note, or trial.
        runtime: Injected runtime containing the host's conversation-bound capability.
        task_id: The task to act on, from list or an earlier result; required except for create and list.
        title: A short task title in the user's language; required for create.
        prompt: Instructions for every run, in the user's language; required for create.
        stop_condition: The user's stop rule in their own words; the run pauses its schedule when it holds.
        schedule_type: once, interval or cron; required for create.
        schedule_spec: run_at (local wall-clock ISO time) for once, every_seconds for interval, or a five-field cron for cron.
        timezone: IANA timezone the user named; omit to use the user's browser timezone on create or keep the saved one on update.
        context_mode: A new conversation for each run, or this conversation when the user asks for that.
        goal_objective: Optional outcome one run must achieve, at most 4000 characters after whitespace normalization.
        max_runs: Optional safety cap on automatic runs, counted over the task's lifetime; trial runs do not count.
        end_at: Optional safety-cap end time, local wall-clock ISO time in the task's timezone (an offset is also accepted).
        note: The user's explicit standing note, word for word; used only by note.
        clear_fields: Fields to remove on update (goal_objective, max_runs, end_at, stop_condition) or on resume (max_runs, end_at).

    Returns:
        The task as the host saved it, a list of tasks, or an error with a code.
    """
    capability = _capability(runtime, "interactive")
    if capability is None:
        return {"error": "Scheduled task management is unavailable in this run.", "code": "scheduler_tools_disabled", "status_code": 503}
    # Plain types only: value rules come back as coded results, as in REST.
    request = {
        key: value
        for key, value in {
            "task_id": task_id,
            "title": title,
            "prompt": prompt,
            "stop_condition": stop_condition,
            "schedule_type": schedule_type,
            "schedule_spec": schedule_spec,
            "timezone": timezone,
            "goal_objective": goal_objective,
            "max_runs": max_runs,
            "end_at": end_at,
            "note": note,
            "clear_fields": list(clear_fields) if clear_fields else None,
        }.items()
        if value is not None
    }
    if action == "create":
        request["context_mode"] = context_mode
    return await capability.manage(action=action, request=request)


@tool(parse_docstring=True)
async def stop_scheduled_task(runtime: Runtime) -> dict[str, Any]:
    """Pause this run's own schedule after this run finishes.

    Call this when the stop rule in your task instructions is met, for example
    "every item on the checklist is checked". Meeting this run's goal does not
    by itself mean the stop rule is met. The current run continues; the
    schedule pauses when it finishes, and the user can resume it later. After
    calling it, tell the user in their language that the task paused itself and
    why.

    Args:
        runtime: Injected runtime bound by the host to this scheduled occurrence.

    Returns:
        Whether the host recorded the stop request, or an error with a code.
    """
    capability = _capability(runtime, "scheduled")
    if capability is None:
        return {"error": "Stopping a schedule is unavailable in this run.", "code": "scheduler_tools_disabled", "status_code": 503}
    return await capability.stop_current_schedule()
