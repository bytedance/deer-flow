from __future__ import annotations

from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from deerflow.agents.middlewares.terminal_response_middleware import TerminalResponseMiddleware
from deerflow.runtime.runs.worker import _extract_llm_error_fallback_message


@tool
def lookup_status() -> str:
    """Return a deterministic tool result."""
    return "tool completed"


class _PostToolResponseModel(BaseChatModel):
    responses: list[str]
    call_count: int = 0
    observed_messages: list[list[Any]] = []

    @property
    def _llm_type(self) -> str:
        return "post-tool-response"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.observed_messages.append(list(messages))
        self.call_count += 1
        if self.call_count == 1:
            message = AIMessage(
                content="",
                tool_calls=[{"id": "call-1", "name": "lookup_status", "args": {}}],
                response_metadata={"finish_reason": "tool_calls"},
            )
        else:
            message = AIMessage(
                content=self.responses[self.call_count - 2],
                response_metadata={"finish_reason": "stop"},
            )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _PerRunRetryBudgetModel(BaseChatModel):
    call_count: int = 0
    observed_messages: list[list[Any]] = []

    @property
    def _llm_type(self) -> str:
        return "per-run-retry-budget"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.observed_messages.append(list(messages))
        self.call_count += 1
        if self.call_count == 1:
            message = AIMessage(
                content="",
                tool_calls=[{"id": "call-budget-1", "name": "lookup_status", "args": {}}],
                response_metadata={"finish_reason": "tool_calls"},
            )
        elif self.call_count == 2:
            message = AIMessage(content="", response_metadata={"finish_reason": "stop"})
        elif self.call_count == 3:
            message = AIMessage(
                content="I need one more status check.",
                tool_calls=[{"id": "call-budget-2", "name": "lookup_status", "args": {}}],
                response_metadata={"finish_reason": "tool_calls"},
            )
        else:
            message = AIMessage(content="", response_metadata={"finish_reason": "stop"})
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _agent(model: BaseChatModel):
    return create_agent(
        model=model,
        tools=[lookup_status],
        middleware=[TerminalResponseMiddleware()],
    )


def _empty_terminal_messages(messages: list[Any]) -> list[AIMessage]:
    return [message for message in messages if isinstance(message, AIMessage) and not message.tool_calls and not message.invalid_tool_calls and not str(message.content).strip()]


def test_retries_empty_post_tool_response_once_and_returns_model_answer():
    model = _PostToolResponseModel(responses=["", "The tool completed successfully."])

    result = _agent(model).invoke(
        {"messages": [HumanMessage(content="Check the status")]},
        context={"thread_id": "thread-1", "run_id": "run-1"},
    )

    assert model.call_count == 3
    final = result["messages"][-1]
    assert isinstance(final, AIMessage)
    assert final.content == "The tool completed successfully."
    assert _empty_terminal_messages(result["messages"]) == []
    assert any(isinstance(message, HumanMessage) and message.name == "terminal_response_recovery" and message.additional_kwargs.get("hide_from_ui") is True for message in model.observed_messages[-1])
    assert not any(isinstance(message, HumanMessage) and message.name == "terminal_response_recovery" for message in result["messages"])


def test_second_empty_post_tool_response_becomes_visible_error_fallback():
    model = _PostToolResponseModel(responses=["", ""])

    result = _agent(model).invoke(
        {"messages": [HumanMessage(content="Check the status")]},
        context={"thread_id": "thread-2", "run_id": "run-2"},
    )

    assert model.call_count == 3
    final = result["messages"][-1]
    assert isinstance(final, AIMessage)
    assert "returned no final response" in str(final.content)
    assert final.additional_kwargs["deerflow_error_fallback"] is True
    assert _empty_terminal_messages(result["messages"]) == []
    assert _extract_llm_error_fallback_message(result) == ("Model returned an empty terminal response after one retry")


@pytest.mark.asyncio
async def test_async_graph_retries_empty_post_tool_response_once():
    model = _PostToolResponseModel(responses=["", "Recovered asynchronously."])

    result = await _agent(model).ainvoke(
        {"messages": [HumanMessage(content="Check the status")]},
        context={"thread_id": "thread-async", "run_id": "run-async"},
    )

    assert model.call_count == 3
    assert result["messages"][-1].content == "Recovered asynchronously."
    assert _empty_terminal_messages(result["messages"]) == []


def test_graph_with_thread_id_only_keeps_recovery_state_across_model_loop():
    model = _PostToolResponseModel(responses=["", "Recovered without a run id."])

    result = _agent(model).invoke(
        {"messages": [HumanMessage(content="Check the status")]},
        context={"thread_id": "thread-only"},
    )

    assert model.call_count == 3
    assert result["messages"][-1].content == "Recovered without a run id."
    assert _empty_terminal_messages(result["messages"]) == []


def test_recovery_budget_is_once_per_run_even_when_retry_calls_another_tool():
    model = _PerRunRetryBudgetModel()

    result = _agent(model).invoke(
        {"messages": [HumanMessage(content="Check the status twice")]},
        context={"thread_id": "thread-budget", "run_id": "run-budget"},
    )

    assert model.call_count == 4
    final = result["messages"][-1]
    assert final.additional_kwargs["deerflow_error_fallback"] is True
    assert _empty_terminal_messages(result["messages"]) == []
    recovery_prompt_count = sum(1 for request_messages in model.observed_messages for message in request_messages if isinstance(message, HumanMessage) and message.name == "terminal_response_recovery")
    assert recovery_prompt_count == 1


def test_empty_response_without_tool_result_is_not_retried():
    middleware = TerminalResponseMiddleware()
    message = AIMessage(content="", response_metadata={"finish_reason": "stop"})
    state = {"messages": [HumanMessage(content="Hello"), message]}
    runtime = type("RuntimeStub", (), {"context": {"thread_id": "thread-3", "run_id": "run-3"}})()

    assert middleware.after_model(state, runtime) is None


def test_tool_call_intent_is_not_treated_as_empty_terminal_response():
    middleware = TerminalResponseMiddleware()
    message = AIMessage(
        content="",
        tool_calls=[{"id": "call-2", "name": "lookup_status", "args": {}}],
        response_metadata={"finish_reason": "tool_calls"},
    )
    state = {"messages": [HumanMessage(content="Hello"), message]}
    runtime = type("RuntimeStub", (), {"context": {"thread_id": "thread-4", "run_id": "run-4"}})()

    assert middleware.after_model(state, runtime) is None


@pytest.mark.parametrize(
    "message",
    [
        AIMessage(content="", invalid_tool_calls=[{"id": "bad-1", "name": "lookup_status", "args": "{"}]),
        AIMessage(content="", additional_kwargs={"function_call": {"name": "lookup_status", "arguments": "{}"}}),
        AIMessage(content="", response_metadata={"finish_reason": "function_call"}),
    ],
)
def test_invalid_or_legacy_tool_call_intent_is_not_treated_as_empty_terminal_response(message):
    middleware = TerminalResponseMiddleware()
    state = {"messages": [HumanMessage(content="Hello"), message]}
    runtime = type("RuntimeStub", (), {"context": {"thread_id": "thread-5", "run_id": "run-5"}})()

    assert middleware.after_model(state, runtime) is None


def test_after_agent_clears_retry_state_for_the_run():
    middleware = TerminalResponseMiddleware()
    runtime = type("RuntimeStub", (), {"context": {"thread_id": "thread-6", "run_id": "run-6"}})()
    empty_after_tool = {
        "messages": [
            HumanMessage(content="Check the status"),
            ToolMessage(content="tool completed", tool_call_id="call-6"),
            AIMessage(content="", response_metadata={"finish_reason": "stop"}),
        ]
    }

    first = middleware.after_model(empty_after_tool, runtime)
    assert first is not None and first["jump_to"] == "model"
    middleware.after_agent(empty_after_tool, runtime)
    second = middleware.after_model(empty_after_tool, runtime)
    assert second is not None and second["jump_to"] == "model"


def test_before_agent_clears_same_run_state_for_resumed_invocation():
    middleware = TerminalResponseMiddleware()
    runtime = type("RuntimeStub", (), {"context": {"thread_id": "thread-7", "run_id": "run-7"}})()
    empty_after_tool = {
        "messages": [
            HumanMessage(content="Check the status"),
            ToolMessage(content="tool completed", tool_call_id="call-7"),
            AIMessage(content="", response_metadata={"finish_reason": "stop"}),
        ]
    }

    first = middleware.after_model(empty_after_tool, runtime)
    assert first is not None and first["jump_to"] == "model"
    middleware.before_agent(empty_after_tool, runtime)
    resumed = middleware.after_model(empty_after_tool, runtime)
    assert resumed is not None and resumed["jump_to"] == "model"


def test_tool_history_without_real_user_message_does_not_trigger_recovery():
    middleware = TerminalResponseMiddleware()
    runtime = type("RuntimeStub", (), {"context": {"thread_id": "thread-8", "run_id": "run-8"}})()
    state = {
        "messages": [
            HumanMessage(content="internal", additional_kwargs={"hide_from_ui": True}),
            ToolMessage(content="tool completed", tool_call_id="call-8"),
            AIMessage(content="", response_metadata={"finish_reason": "stop"}),
        ]
    }

    assert middleware.after_model(state, runtime) is None


def test_abandoned_run_state_is_bounded():
    middleware = TerminalResponseMiddleware()

    for index in range(1001):
        key = (f"thread-{index}", f"run-{index}")
        middleware._retry_counts[key] = 1
        middleware._pending_prompts[key] = True

    assert len(middleware._retry_counts) == 1000
    assert len(middleware._pending_prompts) == 1000
    assert ("thread-0", "run-0") not in middleware._retry_counts
    assert ("thread-0", "run-0") not in middleware._pending_prompts
