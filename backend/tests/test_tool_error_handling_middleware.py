import sys
from types import ModuleType, SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt

from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import (
    ToolErrorHandlingMiddleware,
    build_subagent_runtime_middlewares,
)
from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.config.app_config import AppConfig, CircuitBreakerConfig
from deerflow.config.guardrails_config import GuardrailsConfig
from deerflow.config.loop_detection_config import LoopDetectionConfig, ToolFreqOverride
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig


def _request(name: str = "web_search", tool_call_id: str | None = "tc-1"):
    tool_call = {"name": name}
    if tool_call_id is not None:
        tool_call["id"] = tool_call_id
    return SimpleNamespace(tool_call=tool_call)


def _module(name: str, **attrs):
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _make_app_config(*, supports_vision: bool = False) -> AppConfig:
    return AppConfig(
        models=[
            ModelConfig(
                name="test-model",
                display_name="test-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="test-model",
                supports_vision=supports_vision,
            )
        ],
        sandbox=SandboxConfig(use="test"),
        guardrails=GuardrailsConfig(enabled=False),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=7, recovery_timeout_sec=11),
    )


def _stub_runtime_middleware_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMiddleware:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class FakeLLMErrorHandlingMiddleware:
        def __init__(self, *, app_config):
            self.app_config = app_config

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
    # Assert membership and the meaningful relative ordering rather than brittle
    # absolute positions/counts: LoopDetection and SafetyFinishReason are both
    # enabled by default, loop detection runs before the safety guard, and the
    # safety guard is last.
    from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
    from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware

    assert isinstance(middlewares[0], ToolOutputBudgetMiddleware)
    assert any(isinstance(m, ToolErrorHandlingMiddleware) for m in middlewares)
    loop_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, LoopDetectionMiddleware))
    safety_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, SafetyFinishReasonMiddleware))
    assert loop_idx < safety_idx
    assert safety_idx == len(middlewares) - 1


def test_build_subagent_runtime_middlewares_includes_loop_detection_when_enabled(monkeypatch: pytest.MonkeyPatch):
    _stub_runtime_middleware_imports(monkeypatch)
    app_config = _make_app_config()
    app_config.loop_detection = LoopDetectionConfig(enabled=True, warn_threshold=7, hard_limit=9)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model", lazy_init=False)

    loop = next(m for m in middlewares if isinstance(m, LoopDetectionMiddleware))
    assert loop.warn_threshold == 7
    assert loop.hard_limit == 9


def test_build_subagent_runtime_middlewares_omits_loop_detection_when_disabled(monkeypatch: pytest.MonkeyPatch):
    _stub_runtime_middleware_imports(monkeypatch)
    app_config = _make_app_config()
    app_config.loop_detection = LoopDetectionConfig(enabled=False)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model", lazy_init=False)

    assert not any(isinstance(m, LoopDetectionMiddleware) for m in middlewares)


def test_build_subagent_runtime_middlewares_scales_tool_freq_with_max_turns(monkeypatch: pytest.MonkeyPatch):
    _stub_runtime_middleware_imports(monkeypatch)
    app_config = _make_app_config()
    app_config.loop_detection = LoopDetectionConfig(enabled=True, tool_freq_warn=30, tool_freq_hard_limit=50)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model", lazy_init=False, max_turns=1000)

    loop = next(m for m in middlewares if isinstance(m, LoopDetectionMiddleware))
    # The per-tool frequency guard scales with the budget so legitimate
    # high-volume single-tool work is not force-stopped at 50 long before
    # max_turns. The identical-call detector is untouched — true loops still
    # stop early.
    assert loop.tool_freq_hard_limit == 1000
    assert loop.tool_freq_warn == 500
    assert loop.warn_threshold == 3
    assert loop.hard_limit == 5


def test_build_subagent_runtime_middlewares_does_not_lower_tool_freq(monkeypatch: pytest.MonkeyPatch):
    _stub_runtime_middleware_imports(monkeypatch)
    app_config = _make_app_config()
    # An operator who configured a higher cap than the budget must not be lowered.
    app_config.loop_detection = LoopDetectionConfig(enabled=True, tool_freq_warn=200, tool_freq_hard_limit=5000)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model", lazy_init=False, max_turns=1000)

    loop = next(m for m in middlewares if isinstance(m, LoopDetectionMiddleware))
    assert loop.tool_freq_hard_limit == 5000
    assert loop.tool_freq_warn == 200


def test_build_subagent_runtime_middlewares_lifts_low_global_cap_preserving_overrides(monkeypatch: pytest.MonkeyPatch):
    """A deliberately-low *global* tool_freq cap is intentionally lifted to the budget
    for deep subagents — the global per-tool-type guard is relaxed so legitimate
    high-volume single-tool work is not force-stopped far below ``max_turns``. This is
    a documented relaxation: per-tool ``tool_freq_overrides`` remain the supported way
    to cap a specific tool and are left untouched.
    """
    _stub_runtime_middleware_imports(monkeypatch)
    app_config = _make_app_config()
    app_config.loop_detection = LoopDetectionConfig(
        enabled=True,
        tool_freq_warn=10,
        tool_freq_hard_limit=20,
        tool_freq_overrides={"bash": ToolFreqOverride(warn=5, hard_limit=8)},
    )

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model", lazy_init=False, max_turns=1000)

    loop = next(m for m in middlewares if isinstance(m, LoopDetectionMiddleware))
    # Low global cap is raised to the budget (relaxed, never made stricter).
    assert loop.tool_freq_hard_limit == 1000
    assert loop.tool_freq_warn == 500
    # The per-tool override is the supported cap and is preserved verbatim.
    assert loop._tool_freq_overrides["bash"] == (5, 8)


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


def test_subagent_runtime_middlewares_include_view_image_for_vision_model(monkeypatch):
    app_config = _make_app_config(supports_vision=True)
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model")

    assert any(isinstance(middleware, ViewImageMiddleware) for middleware in middlewares)


def test_subagent_runtime_middlewares_include_view_image_for_default_vision_model(monkeypatch):
    app_config = _make_app_config(supports_vision=True)
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name=None)

    assert any(isinstance(middleware, ViewImageMiddleware) for middleware in middlewares)


def test_subagent_runtime_middlewares_skip_view_image_for_text_model(monkeypatch):
    app_config = _make_app_config(supports_vision=False)
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model")

    assert not any(isinstance(middleware, ViewImageMiddleware) for middleware in middlewares)
