"""Regression tests for trimming trailing error-fallback messages (#7321).

A run that ends on a failed model call persists a user-facing fallback
``AIMessage`` (``deerflow_error_fallback``) as the thread's last message.
A continuation with empty input then sends it to the model as the final
assistant turn, and providers without assistant prefill reject the request
(HTTP 400 "The conversation must end with a user message"). Only the
DeepSeek wrapper filtered these markers so far; the middleware now trims
the trailing run of them from the outgoing request for every provider.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.llm_error_handling_middleware import (
    LLMErrorHandlingMiddleware,
    _trim_trailing_error_fallbacks,
)


def _fallback(content: str = "The configured LLM provider failed. Please try again.") -> AIMessage:
    return AIMessage(content=content, additional_kwargs={"deerflow_error_fallback": True})


def _ok(content: str = "answer") -> AIMessage:
    return AIMessage(content=content)


def _make_request(messages: list[Any]) -> Any:
    """A real ModelRequest; override() produces the copy the middleware relies on."""
    from langchain.agents.middleware.types import ModelRequest

    return ModelRequest(model="stub-model", messages=messages)


def _capture_handler(seen: list[Any]):
    def handler(request: Any):
        seen.extend(request.messages)
        return _ok("handled")

    return handler


def test_trim_trailing_single_fallback() -> None:
    messages = [HumanMessage(content="hi"), _ok(), _fallback()]
    trimmed = _trim_trailing_error_fallbacks(messages)
    assert trimmed == [messages[0], messages[1]]


def test_trim_trailing_run_of_fallbacks() -> None:
    messages = [HumanMessage(content="hi"), _fallback("first"), _fallback("second")]
    trimmed = _trim_trailing_error_fallbacks(messages)
    assert trimmed == [messages[0]]


def test_mid_history_fallback_is_kept() -> None:
    messages = [HumanMessage(content="hi"), _fallback(), _ok(), HumanMessage(content="next")]
    assert _trim_trailing_error_fallbacks(messages) is None


def test_no_fallbacks_is_unchanged() -> None:
    messages = [HumanMessage(content="hi"), _ok(), HumanMessage(content="next")]
    assert _trim_trailing_error_fallbacks(messages) is None


def test_request_of_only_fallbacks_is_unchanged() -> None:
    messages = [_fallback("a"), _fallback("b")]
    assert _trim_trailing_error_fallbacks(messages) is None


def test_non_list_and_empty_inputs_are_unchanged() -> None:
    assert _trim_trailing_error_fallbacks(None) is None
    assert _trim_trailing_error_fallbacks("not a list") is None
    assert _trim_trailing_error_fallbacks([]) is None


def test_tool_message_after_fallback_stops_the_trim() -> None:
    messages = [HumanMessage(content="hi"), _fallback(), ToolMessage(content="ok", tool_call_id="x")]
    assert _trim_trailing_error_fallbacks(messages) is None


def test_input_list_is_not_mutated() -> None:
    messages = [HumanMessage(content="hi"), _ok(), _fallback()]
    snapshot = list(messages)
    _trim_trailing_error_fallbacks(messages)
    assert messages == snapshot


def test_wrap_model_call_trims_trailing_fallback_for_the_request() -> None:
    middleware = _build_middleware_for_trim()
    seen: list[Any] = []
    messages = [HumanMessage(content="hi"), _ok("earlier"), _fallback()]
    request = _make_request(list(messages))
    middleware.wrap_model_call(request, _capture_handler(seen))
    assert seen == [messages[0], messages[1]]


@pytest.mark.asyncio
async def test_awrap_model_call_trims_trailing_fallback_for_the_request() -> None:
    middleware = _build_middleware_for_trim()
    seen: list[Any] = []
    messages = [HumanMessage(content="hi"), _ok("earlier"), _fallback()]
    request = _make_request(list(messages))

    async def handler(req: Any):
        seen.extend(req.messages)
        return _ok("handled")

    await middleware.awrap_model_call(request, handler)
    assert seen == [messages[0], messages[1]]


def test_trim_never_touches_the_persisted_history_list() -> None:
    """The trim applies to the request copy; the caller's list keeps its messages."""
    middleware = _build_middleware_for_trim()
    seen: list[Any] = []
    history = [HumanMessage(content="hi"), _fallback()]
    request = _make_request(history)
    middleware.wrap_model_call(request, _capture_handler(seen))
    assert len(history) == 2
    assert history[-1].additional_kwargs.get("deerflow_error_fallback") is True


def _build_middleware_for_trim() -> LLMErrorHandlingMiddleware:
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig

    return LLMErrorHandlingMiddleware(app_config=AppConfig(sandbox=SandboxConfig(use="test")))
