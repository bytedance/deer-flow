"""Regression tests for ToolErrorHandlingMiddleware's subagent status stamp.

Bytedance/deer-flow issue #3146: rather than stamp
``ToolMessage.additional_kwargs.subagent_status`` from each of
task_tool.py's 5 normal returns + 3 pre-execution Error: returns (which
would be 8 separate places to drift over time), the middleware that
already wraps every tool call does the stamping in one place. These
tests pin that centralisation.

For non-``task`` tools the middleware must not touch additional_kwargs
— other tools have their own conventions and we do not want to leak a
``subagent_status`` field onto them.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.tool_error_handling_middleware import (
    ToolErrorHandlingMiddleware,
)
from deerflow.subagents.status_contract import (
    SUBAGENT_ERROR_KEY,
    SUBAGENT_STATUS_KEY,
)

_CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "subagent_status_contract.json"


def _load_terminal_cases() -> list[dict]:
    """Load only the cases that should produce a terminal status stamp."""
    data = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    return [c for c in data["cases"] if c["expected_status"] is not None]


class _FakeRequest:
    """Stand-in for ``ToolCallRequest`` used by the middleware."""

    def __init__(self, tool_name: str, tool_call_id: str = "call-1") -> None:
        self.tool_call = {"name": tool_name, "id": tool_call_id}


@pytest.mark.parametrize("case", _load_terminal_cases(), ids=lambda c: c["name"])
def test_stamps_subagent_status_on_successful_task_return(case):
    """Every terminal task tool result string stamps the matching status."""
    middleware = ToolErrorHandlingMiddleware()
    request = _FakeRequest("task")

    def handler(_req):
        return ToolMessage(content=case["content"], tool_call_id="call-1", name="task")

    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert result.additional_kwargs.get(SUBAGENT_STATUS_KEY) == case["expected_status"]


def test_does_not_stamp_unknown_streaming_chunk():
    """Non-terminal content leaves additional_kwargs alone."""
    middleware = ToolErrorHandlingMiddleware()
    request = _FakeRequest("task")

    def handler(_req):
        return ToolMessage(content="Investigating ...", tool_call_id="call-1", name="task")

    result = middleware.wrap_tool_call(request, handler)
    assert SUBAGENT_STATUS_KEY not in (result.additional_kwargs or {})


def test_does_not_stamp_non_task_tool():
    """A non-task tool returning a string that happens to start with
    ``Error:`` must not pick up a subagent stamp."""
    middleware = ToolErrorHandlingMiddleware()
    request = _FakeRequest("bash")

    def handler(_req):
        return ToolMessage(content="Error: command not found", tool_call_id="call-1", name="bash")

    result = middleware.wrap_tool_call(request, handler)
    assert SUBAGENT_STATUS_KEY not in (result.additional_kwargs or {})


def test_stamps_failed_when_task_tool_raises():
    """The exception path goes through ``_build_error_message`` which is
    the only place ToolErrorHandlingMiddleware ever emits a brand-new
    ToolMessage. It must stamp ``failed`` for task too, since the wrapper
    text starts with ``Error:``.
    """
    middleware = ToolErrorHandlingMiddleware()
    request = _FakeRequest("task")

    def handler(_req):
        raise RuntimeError("blew up during execution")

    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert result.additional_kwargs.get(SUBAGENT_STATUS_KEY) == "failed"
    assert "RuntimeError" in result.additional_kwargs.get(SUBAGENT_ERROR_KEY, "")


def test_async_wrap_also_stamps():
    """The async wrap path must behave identically."""
    middleware = ToolErrorHandlingMiddleware()
    request = _FakeRequest("task")

    async def handler(_req):
        return ToolMessage(content="Task Succeeded. Result: ok", tool_call_id="call-1", name="task")

    result = asyncio.run(middleware.awrap_tool_call(request, handler))
    assert result.additional_kwargs.get(SUBAGENT_STATUS_KEY) == "completed"


def test_preserves_existing_additional_kwargs():
    """The stamper must not clobber unrelated fields the tool already set."""
    middleware = ToolErrorHandlingMiddleware()
    request = _FakeRequest("task")

    def handler(_req):
        return ToolMessage(
            content="Task Succeeded. Result: ok",
            tool_call_id="call-1",
            name="task",
            additional_kwargs={"existing_field": "must_survive"},
        )

    result = middleware.wrap_tool_call(request, handler)
    assert result.additional_kwargs.get("existing_field") == "must_survive"
    assert result.additional_kwargs.get(SUBAGENT_STATUS_KEY) == "completed"


def test_additional_kwargs_round_trip_via_json():
    """Pydantic dump → JSON → restore must keep the stamp intact.

    ``ToolMessage`` is what LangGraph serialises into the checkpoint and
    what the frontend deserialises off the stream. If a future Pydantic /
    LangChain upgrade silently strips unknown ``additional_kwargs`` we
    want that to fail loudly here rather than in the wild.
    """
    msg = ToolMessage(
        content="Task Succeeded. Result: ok",
        tool_call_id="call-1",
        name="task",
        additional_kwargs={SUBAGENT_STATUS_KEY: "completed", SUBAGENT_ERROR_KEY: ""},
    )
    serialised = msg.model_dump_json()
    restored = ToolMessage.model_validate_json(serialised)
    assert restored.additional_kwargs.get(SUBAGENT_STATUS_KEY) == "completed"
