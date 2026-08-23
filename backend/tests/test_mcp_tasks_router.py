from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.gateway.app import create_app
from app.gateway.routers import mcp_tasks


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows
        self.list_calls = []
        self.get_calls = []

    async def list_by_thread(self, thread_id, *, user_id, limit):
        self.list_calls.append((thread_id, user_id, limit))
        return list(self.rows)

    async def get(self, task_id, *, user_id):
        self.get_calls.append((task_id, user_id))
        return next((row for row in self.rows if row["id"] == task_id and row["user_id"] == user_id), None)


def _record(**overrides):
    return {
        "id": "mcp-task-1",
        "user_id": "user-1",
        "thread_id": "thread-1",
        "task_name": "report-generation",
        "status": "working",
        "created_at": "2026-08-05T00:00:00+00:00",
        "updated_at": "2026-08-05T00:00:05+00:00",
        "last_polled_at": "2026-08-05T00:00:05+00:00",
        "error": None,
        "last_poll_error": "temporary network failure",
        "consecutive_poll_error_count": 3,
        "last_cancel_error": None,
        "cancel_attempt_count": 0,
        "result": None,
        "result_preview": None,
        "result_truncated": False,
        "result_artifact": None,
        "input_required": None,
        "remote_task_id": "must-not-leak",
        "driver_data": {"status_tool": "must-not-leak"},
        "server_name": "must-not-leak",
        **overrides,
    }


def _request(repo):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                mcp_task_repo=repo,
                mcp_task_service=SimpleNamespace(tracking_degraded_after_errors=3),
            )
        )
    )


def test_gateway_mounts_thread_scoped_mcp_task_routes() -> None:
    paths = {route.path for route in create_app().routes}
    assert "/api/threads/{thread_id}/mcp-tasks" in paths
    assert "/api/threads/{thread_id}/mcp-tasks/{task_id}" in paths


@pytest.mark.asyncio
async def test_list_returns_only_safe_current_user_thread_fields(monkeypatch) -> None:
    repo = FakeRepository([_record()])
    monkeypatch.setattr(mcp_tasks, "get_current_user", AsyncMock(return_value="user-1"))

    response = await mcp_tasks.list_mcp_tasks.__wrapped__(
        thread_id="thread-1",
        request=_request(repo),
        limit=25,
    )

    assert repo.list_calls == [("thread-1", "user-1", 25)]
    assert response == [
        {
            "task_id": "mcp-task-1",
            "task_name": "report-generation",
            "status": "working",
            "created_at": "2026-08-05T00:00:00+00:00",
            "updated_at": "2026-08-05T00:00:05+00:00",
            "error": None,
            "tracking_degraded": True,
            "cancel_requested": False,
        }
    ]


@pytest.mark.asyncio
async def test_detail_exposes_bounded_result_but_not_remote_handle(monkeypatch) -> None:
    repo = FakeRepository(
        [
            _record(
                status="completed",
                result={"report": "ready"},
                result_artifact={"uri": "s3://reports/1.json", "mime_type": "application/json"},
                last_cancel_error="c" * 600,
                cancel_attempt_count=4,
                notification_status="retry",
                notification_error="n" * 600,
                notification_attempt_count=3,
            )
        ]
    )
    monkeypatch.setattr(mcp_tasks, "get_current_user", AsyncMock(return_value="user-1"))

    response = await mcp_tasks.get_mcp_task.__wrapped__(
        thread_id="thread-1",
        task_id="mcp-task-1",
        request=_request(repo),
    )

    assert response["result"] == {"report": "ready"}
    assert response["result_artifact"]["uri"] == "s3://reports/1.json"
    assert response["last_cancel_error"] == "c" * 500
    assert response["cancel_attempt_count"] == 4
    assert response["notification_status"] == "retry"
    assert response["notification_error"] == "n" * 500
    assert response["notification_attempt_count"] == 3
    assert "remote_task_id" not in response
    assert "driver_data" not in response
    assert "server_name" not in response


@pytest.mark.asyncio
async def test_detail_rejects_cross_user_and_cross_thread_access(monkeypatch) -> None:
    repo = FakeRepository([_record()])
    request = _request(repo)

    monkeypatch.setattr(mcp_tasks, "get_current_user", AsyncMock(return_value="user-2"))
    with pytest.raises(HTTPException) as cross_user:
        await mcp_tasks.get_mcp_task.__wrapped__(
            thread_id="thread-1",
            task_id="mcp-task-1",
            request=request,
        )
    assert cross_user.value.status_code == 404

    monkeypatch.setattr(mcp_tasks, "get_current_user", AsyncMock(return_value="user-1"))
    with pytest.raises(HTTPException) as cross_thread:
        await mcp_tasks.get_mcp_task.__wrapped__(
            thread_id="thread-2",
            task_id="mcp-task-1",
            request=request,
        )
    assert cross_thread.value.status_code == 404


@pytest.mark.asyncio
async def test_cancel_uses_service_with_exact_user_and_thread_scope(monkeypatch) -> None:
    repo = FakeRepository([_record()])
    service = AsyncMock()
    service.tracking_degraded_after_errors = 3
    service.cancel_task.return_value = _record(status="working", cancel_requested_at="2026-08-05T00:00:06+00:00")
    request = _request(repo)
    request.app.state.mcp_task_service = service
    monkeypatch.setattr(mcp_tasks, "get_current_user", AsyncMock(return_value="user-1"))

    response = await mcp_tasks.cancel_mcp_task.__wrapped__(
        thread_id="thread-1",
        task_id="mcp-task-1",
        request=request,
    )

    service.cancel_task.assert_awaited_once_with(
        task_id="mcp-task-1",
        thread_id="thread-1",
        user_id="user-1",
    )
    assert response["status"] == "working"
    assert response["cancel_requested"] is True
