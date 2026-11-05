"""Memory admission must not abort SDK graphs on valid deep tool arguments."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from deerflow.agents.factory import create_deerflow_agent
from deerflow.agents.features import RuntimeFeatures
from deerflow.agents.middlewares import memory_middleware
from deerflow.agents.middlewares.pii_redaction_middleware import redact_text
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.pii_redaction_config import PiiRedactionConfig

_EMAIL = "alice@example.com"
_OTHER_EMAIL = "bob@example.com"


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@tool
def _consume(nested: dict) -> str:
    """Consume a nested JSON structure."""
    return "done"


def _arguments(depth: int, shape: str = "dict") -> dict:
    value = {_EMAIL: _OTHER_EMAIL, "number": 1, "flag": False, "empty": None}
    for _ in range(depth):
        value = {"nested": value} if shape == "dict" else {"nested": [value]}
    # Keep this a valid-JSON regression, not an arbitrary Python-only state.
    try:
        return json.loads(json.dumps(value))
    except RecursionError:
        pytest.skip("This interpreter rejects the fixture at the JSON parser/encoder boundary")


def _leaf(value: dict, depth: int, shape: str = "dict") -> dict:
    for _ in range(depth):
        value = value["nested"]
        if shape == "mixed":
            value = value[0]
    return value


def _policy(policy: str) -> PiiRedactionConfig | None:
    return None if policy == "omitted" else PiiRedactionConfig(enabled=policy == "enabled", token_secret="memory-depth-regression-secret")


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("depth", [10, 1100])
@pytest.mark.parametrize("memory", [False, True])
@pytest.mark.parametrize("policy", ["omitted", "disabled", "enabled"])
@pytest.mark.asyncio
async def test_sdk_completion_with_deep_memory_arguments(monkeypatch, mode, depth, memory, policy):
    args = _arguments(depth)
    original = json.dumps(args)
    attempt = AIMessage(content="", id="historical-ai", tool_calls=[{"name": "_consume", "args": args, "id": "old-call"}])
    messages = [HumanMessage("Analyze."), attempt, ToolMessage(content="done", tool_call_id="old-call"), HumanMessage("Summarize.")]
    manager = SimpleNamespace(add=Mock(), aadd=AsyncMock())
    monkeypatch.setattr(memory_middleware, "get_memory_manager", lambda: manager)
    config = _policy(policy)
    graph = create_deerflow_agent(
        _ScriptedModel(responses=[AIMessage(content="Task complete.")]),
        tools=[_consume],
        features=RuntimeFeatures(sandbox=False, memory=memory, memory_config=MemoryConfig(enabled=True), loop_detection=False),
        checkpointer=None,
        **({} if policy == "omitted" else {"pii_redaction_config": config}),
    )

    context = {"thread_id": "memory-depth", "user_id": "memory-owner"}
    result = graph.invoke({"messages": messages}, context=context) if mode == "sync" else await graph.ainvoke({"messages": messages}, context=context)

    assert result["messages"][-1].content == "Task complete."
    assert json.dumps(attempt.tool_calls[0]["args"]) == original
    selected, unused = (manager.add, manager.aadd) if mode == "sync" else (manager.aadd, manager.add)
    unused.assert_not_called()
    assert selected.call_count == int(memory)
    if not memory:
        return
    call = selected.call_args
    assert call.args[0] == "memory-depth"
    assert call.kwargs["user_id"] == "memory-owner"
    queued = next(message for message in call.args[1] if message.id == "historical-ai")
    assert queued.tool_calls[0]["id"] == "old-call"
    assert queued.tool_calls[0]["name"] == "_consume"
    expected = {redact_text(_EMAIL, config): redact_text(_OTHER_EMAIL, config)} if policy == "enabled" else {_EMAIL: _OTHER_EMAIL}
    assert _leaf(queued.tool_calls[0]["args"], depth) == {**expected, "number": 1, "flag": False, "empty": None}
    if policy == "enabled":
        assert _EMAIL not in json.dumps(queued.tool_calls)
        assert _OTHER_EMAIL not in json.dumps(queued.tool_calls)


@pytest.mark.parametrize("shape,depth", [("dict", 1100), ("mixed", 550)])
def test_deep_arguments_are_redacted_without_mutating_messages(shape, depth):
    args = _arguments(depth, shape)
    original = json.dumps(args)
    message = AIMessage(content="", id="ai-1", tool_calls=[{"name": "lookup", "args": args, "id": "call-1"}])
    config = _policy("enabled")

    queued = memory_middleware.redact_queued_messages([message], config)[0]

    assert queued.id == message.id
    assert queued is not message
    redacted = queued.tool_calls[0]["args"]
    assert queued.tool_calls[0]["id"] == "call-1"
    leaf = _leaf(redacted, depth, shape)
    assert leaf == {redact_text(_EMAIL, config): redact_text(_OTHER_EMAIL, config), "number": 1, "flag": False, "empty": None}
    assert json.dumps(args) == original
    leaf["new"] = "queued only"
    assert "new" not in _leaf(args, depth, shape)


@pytest.mark.parametrize("policy", ["omitted", "disabled"])
def test_disabled_redaction_returns_an_independent_message_list(policy):
    message = AIMessage(content="done", tool_calls=[{"name": "lookup", "args": _arguments(1100), "id": "call-1"}])
    messages = [message]

    queued = memory_middleware.redact_queued_messages(messages, _policy(policy))

    assert queued is not messages
    assert queued[0] is message
    queued.clear()
    assert messages == [message]


def test_redaction_keeps_shared_branches_and_key_collision_order():
    config = _policy("enabled")
    token = redact_text(_EMAIL, config)
    shared = {_EMAIL: _OTHER_EMAIL}
    args = {"contacts": {_EMAIL: "first", token: "last"}, "branches": [shared, shared]}
    message = AIMessage(content="", tool_calls=[{"name": "lookup", "args": args, "id": "call-1"}])

    queued = memory_middleware.redact_queued_messages([message], config)[0].tool_calls[0]["args"]

    assert queued["contacts"] == {token: "last"}
    assert queued["branches"] == [{token: redact_text(_OTHER_EMAIL, config)}] * 2
    queued["branches"][0]["new"] = "queued only"
    assert shared == {_EMAIL: _OTHER_EMAIL}
    assert "new" not in queued["branches"][1]


@pytest.mark.parametrize("shape", ["dict", "list"])
def test_non_json_cycles_fail_without_an_unredacted_fallback(shape):
    cyclic = {} if shape == "dict" else []
    if shape == "dict":
        cyclic["cycle"] = cyclic
    else:
        cyclic.append(cyclic)
    message = AIMessage(content="", tool_calls=[{"name": "lookup", "args": {"nested": cyclic, "email": _EMAIL}, "id": "call-1"}])

    with pytest.raises(ValueError, match="[Cc]ycl"):
        memory_middleware.redact_queued_messages([message], _policy("enabled"))


def test_deep_arguments_without_pii_keep_message_identity():
    args = {"text": "ordinary text"}
    for _ in range(1100):
        args = {"nested": args}
    try:
        args = json.loads(json.dumps(args))
    except RecursionError:
        pytest.skip("This interpreter rejects the fixture at the JSON parser/encoder boundary")
    message = AIMessage(content="done", tool_calls=[{"name": "lookup", "args": args, "id": "call-1"}])

    queued = memory_middleware.redact_queued_messages([message], _policy("enabled"))

    assert queued[0] is message
