"""Trailing deerflow_error_fallback AIMessages must not be sent to providers (#7321)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.llm_error_handling_middleware import (
    LLMErrorHandlingMiddleware,
    _request_without_trailing_error_fallbacks,
    _without_trailing_error_fallbacks,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig


def _fallback(text: str = "model error") -> AIMessage:
    return AIMessage(
        content=text,
        additional_kwargs={"deerflow_error_fallback": True, "error_reason": "provider_error"},
    )


def _make_request(messages: list) -> ModelRequest:
    return ModelRequest(
        model=object(),
        messages=list(messages),
        state={"messages": list(messages)},
        runtime=SimpleNamespace(context={"thread_id": "t1", "run_id": "r1"}),
    )


def test_helper_strips_only_trailing_fallbacks() -> None:
    human = HumanMessage(content="continue")
    mid = _fallback("earlier")
    real = AIMessage(content="ok")
    trailing = _fallback("latest")

    trimmed = _without_trailing_error_fallbacks([human, mid, real, trailing, _fallback("also")])
    assert trimmed == [human, mid, real]


def test_helper_keeps_mid_history_fallbacks_when_not_trailing() -> None:
    human = HumanMessage(content="hi")
    mid = _fallback("earlier")
    follow = HumanMessage(content="try again")
    # No trailing fallback → helper returns None (caller leaves the list unchanged),
    # so the mid-history fallback stays when the request is forwarded as-is.
    assert _without_trailing_error_fallbacks([human, mid, follow]) is None


def test_helper_leaves_all_fallback_list_unchanged() -> None:
    only = [_fallback("a"), _fallback("b")]
    assert _without_trailing_error_fallbacks(only) is None


def test_helper_noop_when_no_trailing_fallback() -> None:
    msgs = [HumanMessage(content="hi"), AIMessage(content="ok")]
    assert _without_trailing_error_fallbacks(msgs) is None


def test_request_override_drops_trailing_fallback() -> None:
    human = HumanMessage(content="continue")
    trailing = _fallback()
    request = _make_request([human, trailing])
    trimmed_request = _request_without_trailing_error_fallbacks(request)
    assert [type(m).__name__ for m in trimmed_request.messages] == ["HumanMessage"]
    assert trimmed_request.messages[0].content == "continue"
    # Original request object is not mutated
    assert len(request.messages) == 2


def test_request_override_noop_for_simple_namespace_without_messages() -> None:
    request = SimpleNamespace(runtime=SimpleNamespace(context={}))
    assert _request_without_trailing_error_fallbacks(request) is request  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_process_limiter():
    from deerflow.agents.middlewares import llm_error_handling_middleware as mod

    mod._PROCESS_LIMITER = None
    mod._CAP_RESOLVED = False
    yield
    mod._PROCESS_LIMITER = None
    mod._CAP_RESOLVED = False


def test_wrap_model_call_does_not_send_trailing_fallback_to_handler() -> None:
    middleware = LLMErrorHandlingMiddleware(app_config=AppConfig(sandbox=SandboxConfig(use="test")))
    human = HumanMessage(content="continue")
    request = _make_request([human, _fallback()])
    seen: list = []

    def handler(model_request: ModelRequest) -> AIMessage:
        seen.append(list(model_request.messages))
        return AIMessage(content="recovered")

    result = middleware.wrap_model_call(request, handler)
    assert result.content == "recovered"
    assert len(seen) == 1
    assert len(seen[0]) == 1
    assert seen[0][0].content == "continue"
    assert not (seen[0][-1].additional_kwargs or {}).get("deerflow_error_fallback")


@pytest.mark.anyio
async def test_awrap_model_call_does_not_send_trailing_fallback_to_handler() -> None:
    middleware = LLMErrorHandlingMiddleware(app_config=AppConfig(sandbox=SandboxConfig(use="test")))
    human = HumanMessage(content="continue")
    request = _make_request([human, _fallback()])
    seen: list = []

    async def handler(model_request: ModelRequest) -> AIMessage:
        seen.append(list(model_request.messages))
        return AIMessage(content="recovered")

    result = await middleware.awrap_model_call(request, handler)
    assert result.content == "recovered"
    assert len(seen) == 1
    assert [m.content for m in seen[0]] == ["continue"]
