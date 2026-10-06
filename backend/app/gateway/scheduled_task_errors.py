"""Coded errors for the scheduled-task REST routes and the chat capability.

Every error raised by ``/api/scheduled-tasks*``, the shared validation and the
conversation capability is ``HTTPException(status, detail={"code", "message",
"params"})`` (``params`` omitted when empty), the same shape the skills export
uses. Messages stay English for API clients and the agent; the web UI
translates by ``code``. ``contracts/scheduled_task_errors_contract.json`` lists
every code, split into the ones the UI must translate and the ones only the
agent sees.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

SCHEDULER_UI_ERROR_CODES: frozenset[str] = frozenset(
    {
        "invalid_request",
        "invalid_schedule",
        "invalid_schedule_type",
        "invalid_timezone",
        "interval_too_short",
        "interval_too_long",
        "once_in_past",
        "once_too_soon",
        "once_time_passed",
        "invalid_context_mode",
        "reuse_thread_requires_thread",
        "thread_not_found",
        "invalid_assistant",
        "unknown_assistant",
        "invalid_goal",
        "goal_requires_fresh_thread",
        "invalid_stop_condition",
        "invalid_max_runs",
        "end_at_in_past",
        "end_at_before_first_run",
        "frequent_requires_limit",
        "max_runs_not_above_used",
        "limits_exhausted",
        "task_not_found",
        "task_running",
        "run_queued",
        "task_changed",
        "task_finished",
        "task_quota_exceeded",
        "scheduler_not_running",
        "trigger_failed",
    }
)

SCHEDULER_AGENT_ERROR_CODES: frozenset[str] = frozenset(
    {
        "timezone_required",
        "authentication_required",
        "permission_denied",
        "scheduler_tools_disabled",
        "authority_expired",
        "conversation_not_found",
        "interactive_run_required",
        "unsupported_action",
        "unsupported_fields",
        "task_id_required",
        "note_not_verbatim",
        "note_limit_reached",
        "trial_requires_direct_request",
        "no_stop_authority",
        "occurrence_not_active",
    }
)


def scheduler_error(status_code: int, code: str, message: str, **params: Any) -> HTTPException:
    """Build the coded ``HTTPException`` for one scheduled-task error."""
    detail: dict[str, Any] = {"code": code, "message": message}
    if params:
        detail["params"] = params
    return HTTPException(status_code=status_code, detail=detail)


def tool_error_payload(exc: HTTPException) -> dict[str, Any]:
    """Project a scheduled-task ``HTTPException`` into the capability's error result."""
    detail = exc.detail
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        payload: dict[str, Any] = {"error": str(detail.get("message") or ""), "code": detail["code"], "status_code": exc.status_code}
        params = detail.get("params")
        if params:
            payload["params"] = params
        return payload
    return {"error": str(detail), "code": "error", "status_code": exc.status_code}


def active_occurrence_message(status: str) -> str:
    """English message for a mutation blocked by an active occurrence."""
    detail = f"Scheduled task has an active {status} occurrence; retry after it finishes"
    if status == "queued":
        detail += " or cancel the queued occurrence by pausing the task"
    return detail


def active_occurrence_error(status: str) -> HTTPException:
    """409 for a queued (``run_queued``) or launching/running (``task_running``) occurrence."""
    return scheduler_error(409, "run_queued" if status == "queued" else "task_running", active_occurrence_message(status))


def limits_exhausted_error(exc: Any) -> HTTPException:
    """409 ``limits_exhausted`` from a ``ScheduledTaskLimitsExhausted``."""
    if exc.limit == "end_at":
        message = f"The end time {exc.end_at} has passed. Set a later end_at (or clear it) in the same request to reactivate."
    else:
        message = f"All {exc.max_runs} automatic runs are used. Raise max_runs above {exc.used} or set a later end_at in the same request to reactivate."
    return scheduler_error(409, "limits_exhausted", message, limit=exc.limit, used=exc.used, max_runs=exc.max_runs, end_at=exc.end_at)


def repository_error(exc: Exception) -> HTTPException:
    """Map a scheduled-task repository exception to its coded error."""
    from deerflow.persistence.scheduled_tasks import ActiveScheduledTaskMutationConflict, ScheduledTaskLimitsExhausted, ScheduledTaskQuotaExceeded

    if isinstance(exc, ActiveScheduledTaskMutationConflict):
        return active_occurrence_error(exc.status)
    if isinstance(exc, ScheduledTaskQuotaExceeded):
        return scheduler_error(409, "task_quota_exceeded", str(exc), limit=20)
    if isinstance(exc, ScheduledTaskLimitsExhausted):
        return limits_exhausted_error(exc)
    message = str(exc)
    if "fresh_thread_per_run" in message:
        return scheduler_error(422, "goal_requires_fresh_thread", message)
    if message.startswith("Goal objective"):
        return scheduler_error(422, "invalid_goal", message, max_chars=4000)
    if message.startswith("at most 10 standing notes"):
        return scheduler_error(422, "note_limit_reached", message, limit=10)
    return scheduler_error(422, "invalid_request", message)
