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
