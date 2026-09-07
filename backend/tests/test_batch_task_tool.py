import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.subagents.config import SubagentConfig
from deerflow.tools.builtins.batch_task_tool import BatchTaskItem

tool_module = importlib.import_module("deerflow.tools.builtins.batch_task_tool")


def _runtime():
    return SimpleNamespace(
        state={},
        context={
            "thread_id": "thread-1",
            "run_id": "run-1",
            "user_id": "user-1",
            "user_role": "member",
        },
        config={
            "metadata": {
                "model_name": "model-a",
                "allowed_subagents": ["general-purpose"],
                "tool_groups": ["web"],
            },
            "configurable": {"thread_id": "thread-1"},
        },
    )


def _message(command: Command) -> ToolMessage:
    messages = command.update["messages"]
    assert len(messages) == 1 and isinstance(messages[0], ToolMessage)
    return messages[0]


@pytest.mark.asyncio
async def test_batch_task_is_explicit_idempotent_submission(monkeypatch) -> None:
    submitter = AsyncMock()
    submitter.submit.return_value = {
        "id": "subagent-batch-1",
        "status": "queued",
        "total_items": 2,
    }
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: submitter)
    monkeypatch.setattr(
        tool_module,
        "get_available_subagent_names",
        lambda **_kwargs: ["general-purpose"],
    )
    monkeypatch.setattr(
        tool_module,
        "get_subagent_config",
        lambda *_args, **_kwargs: SubagentConfig(
            name="general-purpose",
            description="General purpose",
        ),
    )

    command = await tool_module.batch_task.coroutine(
        runtime=_runtime(),
        title="Process records",
        items=[
            BatchTaskItem(key="record-1", prompt="Process one"),
            BatchTaskItem(key="record-2", prompt="Process two"),
        ],
        subagent_type="general-purpose",
        tool_call_id="call-1",
        max_live_items=20,
        max_running_items=5,
    )

    message = _message(command)
    request = submitter.submit.await_args.args[0]
    assert request.submission_key == "run-1:call-1"
    assert request.user_id == "user-1"
    assert [item["key"] for item in request.items] == ["record-1", "record-2"]
    assert request.max_live_items == 20
    assert request.max_running_items == 5
    assert message.additional_kwargs["subagent_batch_id"] == "subagent-batch-1"
    assert "running independently" in message.content


@pytest.mark.asyncio
async def test_batch_task_rejects_duplicate_item_keys_without_submitting(monkeypatch) -> None:
    submitter = AsyncMock()
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: submitter)

    command = await tool_module.batch_task.coroutine(
        runtime=_runtime(),
        title="Duplicates",
        items=[
            BatchTaskItem(key="same", prompt="one"),
            BatchTaskItem(key="same", prompt="two"),
        ],
        subagent_type="general-purpose",
        tool_call_id="call-1",
    )

    message = _message(command)
    assert message.status == "error"
    assert "unique" in message.content
    submitter.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_bound_batch_tools_use_the_explicit_submitter(monkeypatch) -> None:
    explicit = AsyncMock()
    explicit.get_batch.return_value = {
        "id": "subagent-batch-explicit",
        "status": "running",
        "total_items": 2,
        "counts": {"running": 1, "succeeded": 1},
    }
    fallback = AsyncMock()
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: fallback)

    tools = {tool.name: tool for tool in tool_module.bind_batch_tools(explicit)}
    result = await tools["batch_status"].coroutine(
        runtime=_runtime(),
        batch_id="subagent-batch-explicit",
    )

    assert "subagent-batch-explicit" in result
    explicit.get_batch.assert_awaited_once_with(
        batch_id="subagent-batch-explicit",
        user_id="user-1",
    )
    fallback.get_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_bound_batch_task_uses_the_explicit_app_config(monkeypatch) -> None:
    app_config = object()
    captured = {}
    submitter = AsyncMock()
    submitter.submit.return_value = {
        "id": "subagent-batch-explicit",
        "status": "queued",
        "total_items": 1,
    }

    def available_names(*, app_config, allowed_subagents):
        captured["names"] = (app_config, allowed_subagents)
        return ["general-purpose"]

    def subagent_config(name, *, app_config):
        captured["config"] = (name, app_config)
        return SubagentConfig(
            name="general-purpose",
            description="General purpose",
        )

    monkeypatch.setattr(tool_module, "get_available_subagent_names", available_names)
    monkeypatch.setattr(tool_module, "get_subagent_config", subagent_config)

    tools = {
        tool.name: tool
        for tool in tool_module.bind_batch_tools(
            submitter,
            app_config=app_config,
        )
    }
    await tools["batch_task"].coroutine(
        runtime=_runtime(),
        title="Explicit config",
        items=[BatchTaskItem(key="record-1", prompt="Process one")],
        subagent_type="general-purpose",
        tool_call_id="call-explicit",
        max_live_items=None,
        max_running_items=None,
    )

    assert captured["names"] == (app_config, ["general-purpose"])
    assert captured["config"] == ("general-purpose", app_config)
    submitter.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_bound_batch_tools_do_not_fall_back_after_runtime_stops(monkeypatch) -> None:
    fallback = AsyncMock()
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: fallback)

    tools = {
        tool.name: tool
        for tool in tool_module.bind_batch_tools(
            submitter_provider=lambda: None,
        )
    }
    result = await tools["batch_status"].coroutine(
        runtime=_runtime(),
        batch_id="subagent-batch-stopped",
    )

    assert result == "Durable subagent batches are unavailable."
    fallback.get_batch.assert_not_awaited()
