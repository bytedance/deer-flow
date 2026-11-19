from __future__ import annotations

from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from deerflow.agents.middlewares.terminal_response_middleware import TerminalResponseMiddleware
from deerflow.runtime.runs.worker import _extract_llm_error_fallback_message


@tool
def lookup_status() -> str:
    """Return a deterministic tool result."""
    return "tool completed"


class _PostToolResponseModel(BaseChatModel):
    response: AIMessage
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "post-tool-response"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            message = AIMessage(
                content="",
                tool_calls=[{"id": "call-1", "name": "lookup_status", "args": {}}],
                response_metadata={"finish_reason": "tool_calls"},
            )
        else:
            message = self.response
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _agent(model: BaseChatModel):
    return create_agent(
        model=model,
        tools=[lookup_status],
        middleware=[TerminalResponseMiddleware()],
    )


def _runtime(run_id: str = "run-1"):
    return type("RuntimeStub", (), {"context": {"thread_id": "thread-1", "run_id": run_id}})()


def test_empty_post_tool_response_becomes_fallback_without_graph_retry():
    model = _PostToolResponseModel(response=AIMessage(content="", response_metadata={"finish_reason": "stop"}))

    result = _agent(model).invoke(
        {"messages": [HumanMessage(content="Check the status")]},
        context={"thread_id": "thread-1", "run_id": "run-1"},
    )

    assert model.call_count == 2
    final = result["messages"][-1]
    assert isinstance(final, AIMessage)
    assert "returned no final response" in str(final.content)
    assert final.additional_kwargs["deerflow_error_fallback"] is True
    assert _extract_llm_error_fallback_message(result) == "Model returned an empty terminal response"
    assert not any(isinstance(message, RemoveMessage) for message in result["messages"])


@pytest.mark.asyncio
async def test_async_empty_post_tool_response_becomes_fallback_without_graph_retry():
    model = _PostToolResponseModel(response=AIMessage(content="", response_metadata={"finish_reason": "stop"}))

    result = await _agent(model).ainvoke(
        {"messages": [HumanMessage(content="Check the status")]},
        context={"thread_id": "thread-async", "run_id": "run-async"},
    )

    assert model.call_count == 2
    assert result["messages"][-1].additional_kwargs["deerflow_error_fallback"] is True


def test_direct_fallback_replaces_same_message_without_remove_or_jump():
    middleware = TerminalResponseMiddleware()
    empty = AIMessage(id="empty-1", content="", response_metadata={"finish_reason": "stop"})
    state = {
        "messages": [
            HumanMessage(content="Check the status"),
            ToolMessage(content="tool completed", tool_call_id="call-1"),
            empty,
        ]
    }

    result = middleware.after_model(state, _runtime())

    assert result is not None
    assert "jump_to" not in result
    assert len(result["messages"]) == 1
    replacement = result["messages"][0]
    assert isinstance(replacement, AIMessage)
    assert replacement.id == "empty-1"
    assert replacement.additional_kwargs["deerflow_error_fallback"] is True
    assert not isinstance(replacement, RemoveMessage)


def test_empty_response_without_tool_result_is_not_handled_by_terminal_guard():
    middleware = TerminalResponseMiddleware()
    message = AIMessage(content="", response_metadata={"finish_reason": "stop"})
    state = {"messages": [HumanMessage(content="Hello"), message]}

    assert middleware.after_model(state, _runtime()) is None


def test_tool_call_is_not_treated_as_empty_terminal():
    middleware = TerminalResponseMiddleware()
    message = AIMessage(
        content="",
        tool_calls=[{"id": "call-2", "name": "lookup_status", "args": {}}],
        response_metadata={"finish_reason": "tool_calls"},
    )
    state: dict[str, list[Any]] = {
        "messages": [
            HumanMessage(content="Check the status"),
            ToolMessage(content="tool completed", tool_call_id="call-2"),
            message,
        ]
    }

    assert middleware.after_model(state, _runtime()) is None


@pytest.mark.parametrize(
    "message",
    [
        AIMessage(content="   ", response_metadata={"finish_reason": "stop"}),
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "thinking"},
            response_metadata={"finish_reason": "stop"},
        ),
        AIMessage(content="", response_metadata={"finish_reason": "length"}),
    ],
)
def test_nonvisible_post_tool_response_becomes_terminal_fallback(message: AIMessage):
    middleware = TerminalResponseMiddleware()
    state: dict[str, list[Any]] = {
        "messages": [
            HumanMessage(content="Check the status"),
            ToolMessage(content="tool completed", tool_call_id="call-2"),
            message,
        ]
    }

    result = middleware.after_model(state, _runtime())

    assert result is not None
    replacement = result["messages"][0]
    assert "returned no final response" in str(replacement.content)
    assert replacement.additional_kwargs["deerflow_error_fallback"] is True
    if "reasoning_content" in message.additional_kwargs:
        assert replacement.additional_kwargs["reasoning_content"] == "thinking"


def test_thinking_blocks_are_preserved_when_terminal_fallback_is_appended():
    middleware = TerminalResponseMiddleware()
    thinking_block = {"type": "thinking", "thinking": "internal reasoning"}
    message = AIMessage(content=[thinking_block], response_metadata={"finish_reason": "stop"})
    state = {
        "messages": [
            HumanMessage(content="Check the status"),
            ToolMessage(content="tool completed", tool_call_id="call-2"),
            message,
        ]
    }

    result = middleware.after_model(state, _runtime())

    assert result is not None
    content = result["messages"][0].content
    assert content[0] == thinking_block
    assert content[-1]["type"] == "text"
    assert "returned no final response" in content[-1]["text"]
