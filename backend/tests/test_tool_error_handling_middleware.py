import sys
from types import ModuleType, SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt

from deerflow.agents.middlewares.tool_error_handling_middleware import (
    ToolErrorHandlingMiddleware,
    build_subagent_runtime_middlewares,
)
from deerflow.config.app_config import AppConfig, CircuitBreakerConfig
from deerflow.config.guardrails_config import GuardrailsConfig
from deerflow.config.sandbox_config import SandboxConfig


def _module(name: str, **attrs):
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _make_app_config() -> AppConfig:
    return AppConfig(
        sandbox=SandboxConfig(use="test"),
        guardrails=GuardrailsConfig(enabled=False),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=7, recovery_timeout_sec=11),
    )


def _request(name: str = "web_search", tool_call_id: str | None = "tc-1"):
    tool_call = {"name": name}
    if tool_call_id is not None:
        tool_call["id"] = tool_call_id
    return SimpleNamespace(tool_call=tool_call)


def test_build_subagent_runtime_middlewares_threads_app_config_to_llm_middleware(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class FakeMiddleware:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class FakeLLMErrorHandlingMiddleware:
        def __init__(self, *, app_config):
            captured["app_config"] = app_config

    app_config = _make_app_config()

    monkeypatch.setitem(
        sys.modules,
        "deerflow.agents.middlewares.llm_error_handling_middleware",
        _module(
            "deerflow.agents.middlewares.llm_error_handling_middleware",
            LLMErrorHandlingMiddleware=FakeLLMErrorHandlingMiddleware,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "deerflow.agents.middlewares.thread_data_middleware",
        _module("deerflow.agents.middlewares.thread_data_middleware", ThreadDataMiddleware=FakeMiddleware),
    )
    monkeypatch.setitem(
        sys.modules,
        "deerflow.sandbox.middleware",
        _module("deerflow.sandbox.middleware", SandboxMiddleware=FakeMiddleware),
    )
    monkeypatch.setitem(
        sys.modules,
        "deerflow.agents.middlewares.dangling_tool_call_middleware",
        _module("deerflow.agents.middlewares.dangling_tool_call_middleware", DanglingToolCallMiddleware=FakeMiddleware),
    )
    monkeypatch.setitem(
        sys.modules,
        "deerflow.agents.middlewares.sandbox_audit_middleware",
        _module("deerflow.agents.middlewares.sandbox_audit_middleware", SandboxAuditMiddleware=FakeMiddleware),
    )

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, lazy_init=False)

    assert captured["app_config"] is app_config
    assert len(middlewares) == 6
    assert isinstance(middlewares[-1], ToolErrorHandlingMiddleware)


def test_wrap_tool_call_passthrough_on_success():
    middleware = ToolErrorHandlingMiddleware()
    req = _request()
    expected = ToolMessage(content="ok", tool_call_id="tc-1", name="web_search")

    result = middleware.wrap_tool_call(req, lambda _req: expected)

    assert result is expected


def test_wrap_tool_call_returns_error_tool_message_on_exception():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="web_search", tool_call_id="tc-42")

    def _boom(_req):
        raise RuntimeError("network down")

    result = middleware.wrap_tool_call(req, _boom)

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "tc-42"
    assert result.name == "web_search"
    assert result.status == "error"
    assert "Tool 'web_search' failed" in result.text
    assert "network down" in result.text


def test_wrap_tool_call_uses_fallback_tool_call_id_when_missing():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="mcp_tool", tool_call_id=None)

    def _boom(_req):
        raise ValueError("bad request")

    result = middleware.wrap_tool_call(req, _boom)

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "missing_tool_call_id"
    assert result.name == "mcp_tool"
    assert result.status == "error"


def test_wrap_tool_call_reraises_graph_interrupt():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="ask_clarification", tool_call_id="tc-int")

    def _interrupt(_req):
        raise GraphInterrupt(())

    with pytest.raises(GraphInterrupt):
        middleware.wrap_tool_call(req, _interrupt)


@pytest.mark.anyio
async def test_awrap_tool_call_returns_error_tool_message_on_exception():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="mcp_tool", tool_call_id="tc-async")

    async def _boom(_req):
        raise TimeoutError("request timed out")

    result = await middleware.awrap_tool_call(req, _boom)

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "tc-async"
    assert result.name == "mcp_tool"
    assert result.status == "error"
    assert "request timed out" in result.text


@pytest.mark.anyio
async def test_awrap_tool_call_reraises_graph_interrupt():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="ask_clarification", tool_call_id="tc-int-async")

    async def _interrupt(_req):
        raise GraphInterrupt(())

    with pytest.raises(GraphInterrupt):
        await middleware.awrap_tool_call(req, _interrupt)
