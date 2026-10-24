"""Model-bound continuations must not replay terminal framework error messages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
from deerflow.config.app_config import AppConfig, LlmCallConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.utils.messages import is_deerflow_error_fallback, strip_trailing_error_fallbacks


@dataclass(frozen=True)
class _Request:
    messages: list[Any]

    def override(self, **updates: Any) -> _Request:
        return replace(self, **updates)


def _fallback(text: str = "The provider failed") -> AIMessage:
    return AIMessage(content=text, additional_kwargs={"deerflow_error_fallback": True, "error_reason": "transient"})


def _middleware() -> LLMErrorHandlingMiddleware:
    return LLMErrorHandlingMiddleware(
        app_config=AppConfig(
            sandbox=SandboxConfig(use="test"),
            llm_call=LlmCallConfig(max_concurrent_calls=0, retry_max_attempts=1),
        )
    )


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        pytest.param([], [], id="empty"),
        pytest.param([HumanMessage(content="continue")], [HumanMessage(content="continue")], id="ordinary-history"),
        pytest.param([HumanMessage(content="continue"), _fallback()], [HumanMessage(content="continue")], id="one-terminal-fallback"),
        pytest.param([HumanMessage(content="continue"), _fallback("first"), _fallback("second")], [HumanMessage(content="continue")], id="multiple-terminal-fallbacks"),
        pytest.param([_fallback("only")], [_fallback("only")], id="all-fallback-history"),
        pytest.param([_fallback("old"), HumanMessage(content="new")], [_fallback("old"), HumanMessage(content="new")], id="fallback-before-new-user"),
        pytest.param(
            [_fallback("old"), HumanMessage(content="new"), ToolMessage(content="tool", tool_call_id="call")], [_fallback("old"), HumanMessage(content="new"), ToolMessage(content="tool", tool_call_id="call")], id="fallback-before-tool"
        ),
        pytest.param(
            [HumanMessage(content="continue"), AIMessage(content="ordinary", additional_kwargs={"deerflow_error_fallback": False})],
            [HumanMessage(content="continue"), AIMessage(content="ordinary", additional_kwargs={"deerflow_error_fallback": False})],
            id="false-marker",
        ),
    ],
)
def test_strip_trailing_error_fallbacks_preserves_only_request_safe_history(messages, expected):
    original = list(messages)

    result = strip_trailing_error_fallbacks(messages)

    assert result == expected
    assert messages == original
    if len(messages) == len(result):
        assert result is not messages


def test_fallback_marker_requires_an_ai_message():
    assert is_deerflow_error_fallback(_fallback()) is True
    assert is_deerflow_error_fallback(HumanMessage(content="x", additional_kwargs={"deerflow_error_fallback": True})) is False
    assert is_deerflow_error_fallback(AIMessage(content="x", additional_kwargs={"deerflow_error_fallback": False})) is False


def test_sync_continuation_filters_terminal_fallback_only_for_model_request():
    history = [SystemMessage(content="system"), HumanMessage(content="continue"), _fallback()]
    request = _Request(history)
    seen: list[_Request] = []

    result = _middleware().wrap_model_call(request, lambda model_request: seen.append(model_request) or AIMessage(content="recovered"))

    assert result.content == "recovered"
    assert len(seen) == 1
    assert seen[0].messages == history[:-1]
    assert request.messages == history
    assert history[-1].additional_kwargs["deerflow_error_fallback"] is True


@pytest.mark.anyio
async def test_async_continuation_filters_terminal_fallback_only_for_model_request():
    history = [SystemMessage(content="system"), HumanMessage(content="continue"), _fallback()]
    request = _Request(history)
    seen: list[_Request] = []

    async def handler(model_request: _Request) -> AIMessage:
        seen.append(model_request)
        return AIMessage(content="recovered")

    result = await _middleware().awrap_model_call(request, handler)

    assert result.content == "recovered"
    assert len(seen) == 1
    assert seen[0].messages == history[:-1]
    assert request.messages == history


def test_sync_retry_reuses_the_filtered_request_without_rewriting_checkpoint_history(monkeypatch):
    history = [HumanMessage(content="continue"), _fallback()]
    request = _Request(history)
    seen: list[list[Any]] = []
    attempts = 0

    def handler(model_request: _Request) -> AIMessage:
        nonlocal attempts
        attempts += 1
        seen.append(model_request.messages)
        if attempts == 1:
            error = RuntimeError("temporary provider failure")
            error.status_code = 503
            raise error
        return AIMessage(content="recovered")

    middleware = _middleware()
    middleware.retry_max_attempts = 2
    middleware.retry_base_delay_ms = 1
    middleware.retry_cap_delay_ms = 1
    monkeypatch.setattr("time.sleep", lambda _delay: None)

    result = middleware.wrap_model_call(request, handler)

    assert result.content == "recovered"
    assert attempts == 2
    assert seen == [history[:-1], history[:-1]]
    assert request.messages == history


@pytest.mark.anyio
async def test_async_retry_reuses_the_filtered_request_without_rewriting_checkpoint_history(monkeypatch):
    history = [HumanMessage(content="continue"), _fallback()]
    request = _Request(history)
    seen: list[list[Any]] = []
    attempts = 0

    async def fake_sleep(_delay: float) -> None:
        return None

    async def handler(model_request: _Request) -> AIMessage:
        nonlocal attempts
        attempts += 1
        seen.append(model_request.messages)
        if attempts == 1:
            error = RuntimeError("temporary provider failure")
            error.status_code = 503
            raise error
        return AIMessage(content="recovered")

    middleware = _middleware()
    middleware.retry_max_attempts = 2
    middleware.retry_base_delay_ms = 1
    middleware.retry_cap_delay_ms = 1
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    result = await middleware.awrap_model_call(request, handler)

    assert result.content == "recovered"
    assert attempts == 2
    assert seen == [history[:-1], history[:-1]]
    assert request.messages == history


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["sync", "async"])
async def test_all_fallback_history_is_not_replaced_with_an_empty_request(method):
    history = [_fallback("first"), _fallback("second")]
    request = _Request(history)
    seen: list[list[Any]] = []

    if method == "sync":
        result = _middleware().wrap_model_call(request, lambda model_request: seen.append(model_request.messages) or AIMessage(content="ok"))
    else:

        async def handler(model_request: _Request) -> AIMessage:
            seen.append(model_request.messages)
            return AIMessage(content="ok")

        result = await _middleware().awrap_model_call(request, handler)

    assert result.content == "ok"
    assert seen == [history]
    assert request.messages == history


def test_middle_history_fallback_is_sent_when_a_new_turn_exists():
    history = [_fallback("old failure"), HumanMessage(content="new question")]
    request = _Request(history)
    seen: list[list[Any]] = []

    _middleware().wrap_model_call(request, lambda model_request: seen.append(model_request.messages) or AIMessage(content="ok"))

    assert seen == [history]


def test_terminal_fallback_after_tool_output_is_removed_but_tool_context_stays():
    history = [
        HumanMessage(content="look up the report"),
        ToolMessage(content="source result", tool_call_id="call-1"),
        _fallback("the provider failed after the tool completed"),
    ]
    request = _Request(history)
    seen: list[list[Any]] = []

    _middleware().wrap_model_call(request, lambda model_request: seen.append(model_request.messages) or AIMessage(content="continued"))

    assert seen == [history[:-1]]
    assert seen[0][-1].content == "source result"
    assert request.messages[-1].additional_kwargs["deerflow_error_fallback"] is True


def test_sync_non_retriable_failure_keeps_the_new_fallback_out_of_the_next_request():
    first_history = [HumanMessage(content="continue"), _fallback()]
    first_request = _Request(first_history)
    seen: list[list[Any]] = []

    def fail(model_request: _Request) -> AIMessage:
        seen.append(model_request.messages)
        error = RuntimeError("invalid provider credentials")
        error.status_code = 401
        raise error

    result = _middleware().wrap_model_call(first_request, fail)

    assert result.additional_kwargs["deerflow_error_fallback"] is True
    assert seen == [first_history[:-1]]
    assert first_request.messages == first_history


@pytest.mark.anyio
async def test_async_non_retriable_failure_keeps_the_new_fallback_out_of_the_next_request():
    first_history = [HumanMessage(content="continue"), _fallback()]
    first_request = _Request(first_history)
    seen: list[list[Any]] = []

    async def fail(model_request: _Request) -> AIMessage:
        seen.append(model_request.messages)
        error = RuntimeError("invalid provider credentials")
        error.status_code = 401
        raise error

    result = await _middleware().awrap_model_call(first_request, fail)

    assert result.additional_kwargs["deerflow_error_fallback"] is True
    assert seen == [first_history[:-1]]
    assert first_request.messages == first_history
