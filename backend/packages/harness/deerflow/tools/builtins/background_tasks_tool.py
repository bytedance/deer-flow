"""Natural-language management tools for the current thread's MCP tasks."""

from __future__ import annotations

from typing import Annotated, Any

from langchain.tools import tool

from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags
from deerflow.mcp.tasks.runtime import get_mcp_task_submitter
from deerflow.tools.builtins.list_uploaded_files_tool import _resolve_thread_id, _resolve_user_id
from deerflow.tools.types import Runtime


def _public_task(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": record["id"],
        "task_name": neutralize_untrusted_tags(str(record.get("task_name") or "Background task")),
        "status": record.get("status"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "error": neutralize_untrusted_tags(str(record["error"])) if record.get("error") else None,
        "cancel_requested": bool(record.get("cancel_requested_at")),
    }


async def _list_background_tasks_impl(
    runtime: Runtime,
    *,
    active_only: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    thread_id = _resolve_thread_id(runtime)
    if thread_id is None:
        return {"tasks": [], "message": "The current thread could not be resolved."}
    records = await get_mcp_task_submitter().list_tasks(
        thread_id=thread_id,
        user_id=_resolve_user_id(runtime),
        limit=max(1, min(limit, 50)),
        active_only=active_only,
    )
    tasks = [_public_task(record) for record in records]
    return {"tasks": tasks, "count": len(tasks)}


@tool
async def list_background_tasks(
    runtime: Runtime,
    active_only: Annotated[bool, "Return only tasks that are still active."] = False,
) -> dict[str, Any]:
    """List current and recent durable background tasks for this chat."""
    return await _list_background_tasks_impl(runtime, active_only=active_only)


@tool
async def cancel_background_task(
    runtime: Runtime,
    task: Annotated[
        str | None,
        "Optional exact task name or DeerFlow task ID. Omit it only when one active task exists.",
    ] = None,
) -> dict[str, Any]:
    """Cancel one active background task in this chat.

    If several tasks are active, provide the exact task name shown by
    list_background_tasks. Remote MCP task handles are never needed or exposed.
    """
    thread_id = _resolve_thread_id(runtime)
    if thread_id is None:
        return {"cancelled": False, "message": "The current thread could not be resolved."}
    try:
        record = await get_mcp_task_submitter().cancel_matching_task(
            thread_id=thread_id,
            user_id=_resolve_user_id(runtime),
            task=task,
        )
    except (LookupError, ValueError) as exc:
        return {"cancelled": False, "message": neutralize_untrusted_tags(str(exc))}
    public = _public_task(record)
    return {
        "cancelled": public["status"] == "cancelled",
        "task": public,
        "message": "Cancellation requested. DeerFlow will keep retrying safely if the remote server is temporarily unavailable.",
    }
