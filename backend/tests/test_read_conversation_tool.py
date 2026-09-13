"""The history tool uses only a host-provided, authorized reader."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.config.tool_config import ToolConfig
from deerflow.tools.conversation import CONVERSATION_READER_CONTEXT_KEY, read_conversation
from deerflow.tools.tools import get_available_tools
from deerflow.tools.types import Runtime


def _config(*, configured=True, name="read_conversation"):
    return SimpleNamespace(
        tools=[ToolConfig(name=name, group="conversation", use="deerflow.tools.conversation:read_conversation")] if configured else [],
        sandbox=SimpleNamespace(use="example.remote:Sandbox"),
        skill_evolution=SimpleNamespace(enabled=False),
        models=[],
        acp_agents={},
        get_model_config=lambda name: None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page",
    [
        '{"thread_id":"source","messages":[{"text":"Original answer"}],"next_cursor":"42"}',
        '{"error":"Conversation unavailable"}',
    ],
)
async def test_read_conversation_forwards_only_page_arguments_to_host_reader(page):
    reader = AsyncMock(return_value=page)
    runtime = SimpleNamespace(context={CONVERSATION_READER_CONTEXT_KEY: reader, "user_id": "unrelated", "allowed_threads": ["other"]})

    result = await read_conversation.coroutine("source", runtime, cursor="50", limit=7)

    assert result == page
    reader.assert_awaited_once_with(thread_id="source", cursor="50", limit=7)


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [None, {}, {"__conversation_reader": "forged"}])
async def test_read_conversation_requires_callable_in_trusted_context(context):
    other_reader = AsyncMock()
    runtime = SimpleNamespace(context=context, config={"configurable": {CONVERSATION_READER_CONTEXT_KEY: other_reader}})

    result = await read_conversation.coroutine("source", runtime)

    assert "unavailable" in json.loads(result)["error"].lower()
    other_reader.assert_not_called()


@pytest.mark.asyncio
async def test_read_conversation_denies_subagent_even_with_reader():
    reader = AsyncMock()
    runtime = SimpleNamespace(context={CONVERSATION_READER_CONTEXT_KEY: reader, "is_subagent": True})

    result = await read_conversation.coroutine("source", runtime)

    assert "subagent" in json.loads(result)["error"].lower()
    reader.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"thread_id": "../other"},
        {"limit": 0},
        {"limit": 51},
        {"limit": True},
        {"cursor": "0"},
        {"cursor": "-1"},
        {"cursor": ""},
        {"cursor": "１"},
        {"cursor": 1},
    ],
)
async def test_invalid_page_arguments_do_not_reach_reader(arguments):
    reader = AsyncMock()
    runtime = SimpleNamespace(context={CONVERSATION_READER_CONTEXT_KEY: reader})

    result = await read_conversation.coroutine(**{"thread_id": "source", "runtime": runtime, **arguments})

    assert "error" in json.loads(result)
    reader.assert_not_called()


def test_read_conversation_model_schema_has_no_identity_or_runtime_fields():
    assert set(read_conversation.tool_call_schema.model_fields) == {"thread_id", "cursor", "limit"}


@pytest.mark.parametrize("name", ["read_conversation", "renamed_reader"])
def test_conversation_reader_is_not_loaded_by_default(monkeypatch, name):
    monkeypatch.setattr("deerflow.tools.tools.resolve_variable", lambda *_: pytest.fail("disabled reader must not be imported"))

    tools = get_available_tools(include_mcp=False, app_config=_config(name=name))

    assert "read_conversation" not in {tool.name for tool in tools}


def test_conversation_reader_requires_both_configuration_and_host_opt_in():
    enabled = get_available_tools(include_mcp=False, include_conversation_reader=True, app_config=_config())
    unconfigured = get_available_tools(include_mcp=False, include_conversation_reader=True, app_config=_config(configured=False))

    assert "read_conversation" in {tool.name for tool in enabled}
    assert "read_conversation" not in {tool.name for tool in unconfigured}


def test_conversation_reader_still_respects_tool_group_filter():
    tools = get_available_tools(groups=["other"], include_mcp=False, include_conversation_reader=True, app_config=_config())

    assert "read_conversation" not in {tool.name for tool in tools}


def test_assembled_reader_supports_sync_tool_callers():
    reader = AsyncMock(return_value='{"messages":[]}')
    runtime = Runtime(
        state={},
        context={CONVERSATION_READER_CONTEXT_KEY: reader},
        config={},
        stream_writer=lambda _: None,
        tools=[],
        tool_call_id="call-1",
        store=None,
    )
    tools = get_available_tools(include_mcp=False, include_conversation_reader=True, app_config=_config())
    assembled = next(tool for tool in tools if tool.name == "read_conversation")

    assert assembled.invoke({"thread_id": "source", "runtime": runtime}) == '{"messages":[]}'
    reader.assert_awaited_once_with(thread_id="source", cursor=None, limit=20)
