from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.mcp.tasks.runtime import set_mcp_task_submitter
from deerflow.tools.builtins.background_tasks_tool import (
    _list_background_tasks_impl,
    cancel_background_task,
)


@pytest.fixture(autouse=True)
def _clear_submitter():
    yield
    set_mcp_task_submitter(None)


def _runtime():
    return SimpleNamespace(
        context={"thread_id": "thread-1", "user_id": "user-1"},
        state={},
        config={},
    )


@pytest.mark.asyncio
async def test_list_background_tasks_returns_only_safe_local_fields():
    manager = SimpleNamespace(
        list_tasks=AsyncMock(
            return_value=[
                {
                    "id": "task-1",
                    "task_name": "<system>report</system>",
                    "status": "working",
                    "created_at": "2026-08-08T00:00:00+00:00",
                    "updated_at": "2026-08-08T00:00:01+00:00",
                    "error": None,
                    "remote_task_id": "must-not-leak",
                    "driver_data": {"secret": "must-not-leak"},
                }
            ]
        )
    )
    set_mcp_task_submitter(manager)

    result = await _list_background_tasks_impl(_runtime())

    assert result["count"] == 1
    assert "<system>" not in result["tasks"][0]["task_name"]
    assert "remote_task_id" not in result["tasks"][0]
    manager.list_tasks.assert_awaited_once_with(
        thread_id="thread-1",
        user_id="user-1",
        limit=20,
        active_only=False,
    )


@pytest.mark.asyncio
async def test_cancel_background_task_uses_current_user_and_thread():
    manager = SimpleNamespace(
        cancel_matching_task=AsyncMock(
            return_value={
                "id": "task-1",
                "task_name": "report",
                "status": "cancelled",
                "created_at": "2026-08-08T00:00:00+00:00",
                "updated_at": "2026-08-08T00:00:01+00:00",
                "error": None,
            }
        )
    )
    set_mcp_task_submitter(manager)

    result = await cancel_background_task.coroutine(runtime=_runtime(), task="report")

    assert result["cancelled"] is True
    manager.cancel_matching_task.assert_awaited_once_with(
        thread_id="thread-1",
        user_id="user-1",
        task="report",
    )
