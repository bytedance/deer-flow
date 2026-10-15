"""Tests for task exception metadata produced by ToolErrorHandlingMiddleware."""

from __future__ import annotations

import asyncio

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_error_handling_middleware import (
    ToolErrorHandlingMiddleware,
)
from deerflow.subagents.status_contract import (
    SUBAGENT_ERROR_KEY,
    SUBAGENT_STATUS_KEY,
)


class _FakeRequest:
    """Stand-in for ``ToolCallRequest`` used by the middleware."""

    def __init__(self, tool_name: str, tool_call_id: str = "call-1") -> None:
        self.tool_call = {"name": tool_name, "id": tool_call_id}


def test_task_tool_exception_returns_failed_metadata():
    middleware = ToolErrorHandlingMiddleware()
    request = _FakeRequest("task")

    def handler(_req):
        raise RuntimeError("blew up during execution")

    result = middleware.wrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert result.additional_kwargs.get(SUBAGENT_STATUS_KEY) == "failed"
    assert "RuntimeError" in result.additional_kwargs.get(SUBAGENT_ERROR_KEY, "")


def test_async_task_tool_exception_returns_failed_metadata():
    middleware = ToolErrorHandlingMiddleware()
    request = _FakeRequest("task")

    async def handler(_req):
        raise RuntimeError("async boom")

    result = asyncio.run(middleware.awrap_tool_call(request, handler))

    assert isinstance(result, ToolMessage)
    assert result.additional_kwargs.get(SUBAGENT_STATUS_KEY) == "failed"
    assert "RuntimeError" in result.additional_kwargs.get(SUBAGENT_ERROR_KEY, "")


def test_successful_plain_task_tool_message_is_not_stamped_from_content():
    middleware = ToolErrorHandlingMiddleware()
    request = _FakeRequest("task")

    def handler(_req):
        return ToolMessage(content="Task Succeeded. Result: ok", tool_call_id="call-1", name="task")

    result = middleware.wrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert SUBAGENT_STATUS_KEY not in (result.additional_kwargs or {})


def test_does_not_stamp_non_task_tool_exception():
    middleware = ToolErrorHandlingMiddleware()
    request = _FakeRequest("bash")

    def handler(_req):
        raise RuntimeError("command failed")

    result = middleware.wrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert SUBAGENT_STATUS_KEY not in (result.additional_kwargs or {})


def test_task_command_with_metadata_bypasses_middleware_stamp():
    middleware = ToolErrorHandlingMiddleware()
    request = _FakeRequest("task")
    command = Command(
        update={
            "messages": [
                ToolMessage(
                    "Task Succeeded. Result: ok",
                    tool_call_id="call-1",
                    name="task",
                    additional_kwargs={"subagent_status": "completed", "subagent_result_brief": "ok"},
                )
            ]
        }
    )

    assert middleware.wrap_tool_call(request, lambda _req: command) is command


def test_additional_kwargs_round_trip_via_json():
    msg = ToolMessage(
        content="Task Succeeded. Result: ok",
        tool_call_id="call-1",
        name="task",
        additional_kwargs={SUBAGENT_STATUS_KEY: "completed", SUBAGENT_ERROR_KEY: ""},
    )
    serialised = msg.model_dump_json()
    restored = ToolMessage.model_validate_json(serialised)
    assert restored.additional_kwargs.get(SUBAGENT_STATUS_KEY) == "completed"
