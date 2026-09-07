"""Thread-scoped read API for durable MCP background tasks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.gateway.authz import require_permission
from app.gateway.deps import get_current_user, get_mcp_task_repo, get_mcp_task_service
from deerflow.utils.thread_id import ThreadId

router = APIRouter(prefix="/api/threads/{thread_id}/mcp-tasks", tags=["mcp-tasks"])

_MAX_PUBLIC_ERROR_CHARS = 500


def _short_error(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:_MAX_PUBLIC_ERROR_CHARS]


def _tracking_degraded(record: dict[str, Any], *, threshold: int) -> bool:
    return int(record.get("consecutive_poll_error_count") or 0) >= threshold


def _list_item(record: dict[str, Any], *, threshold: int) -> dict[str, Any]:
    return {
        "task_id": record["id"],
        "task_name": record["task_name"],
        "status": record["status"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "error": _short_error(record.get("error")),
        "tracking_degraded": _tracking_degraded(record, threshold=threshold),
        "cancel_requested": record.get("cancel_requested_at") is not None,
    }


def _detail(record: dict[str, Any], *, threshold: int) -> dict[str, Any]:
    return {
        **_list_item(record, threshold=threshold),
        "last_polled_at": record.get("last_polled_at"),
        "last_poll_error": _short_error(record.get("last_poll_error")),
        "last_cancel_error": _short_error(record.get("last_cancel_error")),
        "cancel_attempt_count": int(record.get("cancel_attempt_count") or 0),
        "notification_status": record.get("notification_status"),
        "notification_error": _short_error(record.get("notification_error")),
        "notification_attempt_count": int(record.get("notification_attempt_count") or 0),
        "result": record.get("result"),
        "result_preview": record.get("result_preview"),
        "result_truncated": bool(record.get("result_truncated")),
        "result_artifact": record.get("result_artifact"),
        "input_required": record.get("input_required"),
    }


async def _current_user_id(request: Request) -> str:
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


@router.get("")
@require_permission("threads", "read", owner_check=True)
async def list_mcp_tasks(
    thread_id: ThreadId,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, Any]]:
    repository = get_mcp_task_repo(request)
    service = get_mcp_task_service(request)
    user_id = await _current_user_id(request)
    records = await repository.list_by_thread(
        thread_id,
        user_id=user_id,
        limit=limit,
    )
    threshold = service.tracking_degraded_after_errors
    return [_list_item(record, threshold=threshold) for record in records]


@router.get("/{task_id}")
@require_permission("threads", "read", owner_check=True)
async def get_mcp_task(
    thread_id: ThreadId,
    task_id: str,
    request: Request,
) -> dict[str, Any]:
    repository = get_mcp_task_repo(request)
    service = get_mcp_task_service(request)
    user_id = await _current_user_id(request)
    record = await repository.get(task_id, user_id=user_id)
    if record is None or record["thread_id"] != thread_id:
        raise HTTPException(status_code=404, detail="MCP task not found")
    return _detail(
        record,
        threshold=service.tracking_degraded_after_errors,
    )


@router.post("/{task_id}/cancel")
@require_permission("threads", "write", owner_check=True)
async def cancel_mcp_task(
    thread_id: ThreadId,
    task_id: str,
    request: Request,
) -> dict[str, Any]:
    service = get_mcp_task_service(request)
    user_id = await _current_user_id(request)
    if not getattr(request.app.state, "mcp_tasks_available", False):
        # The service exists whenever SQL persistence is configured, but the
        # background loop that owns the remote cancel call only runs when
        # mcp_tasks.enabled=true. Recording cancel_requested_at without a
        # worker would acknowledge a cancellation nobody will ever perform.
        raise HTTPException(status_code=503, detail="MCP task cancellation worker is not running")
    record = await service.cancel_task(
        task_id=task_id,
        thread_id=thread_id,
        user_id=user_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="MCP task not found")
    return _detail(record, threshold=service.tracking_degraded_after_errors)
