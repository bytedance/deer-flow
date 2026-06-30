import sys
from types import ModuleType, SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt

from deerflow.agents.middlewares.tool_error_handling_middleware import (
    ToolErrorHandlingMiddleware,
    build_lead_runtime_middlewares,
    build_subagent_runtime_middlewares,
)
from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.config.app_config import AppConfig, CircuitBreakerConfig
from deerflow.config.guardrails_config import GuardrailsConfig
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
    monkeypatch.setitem(
        sys.modules,
        "deerflow.agents.middlewares.input_sanitization_middleware",
        _module("deerflow.agents.middlewares.input_sanitization_middleware", InputSanitizationMiddleware=FakeMiddleware),
    )

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, lazy_init=False)

    assert captured["app_config"] is app_config
    # 8 baseline (InputSanitization, ToolOutputBudget, ThreadData, Sandbox,
    # DanglingToolCall, LLMErrorHandling, SandboxAudit, ToolErrorHandling)
    # + 1 SafetyFinishReasonMiddleware (enabled by default).
    from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
    from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware

    assert len(middlewares) == 9
    assert isinstance(middlewares[0], FakeMiddleware)  # InputSanitizationMiddleware stub
    assert isinstance(middlewares[1], ToolOutputBudgetMiddleware)
    assert any(isinstance(m, ToolErrorHandlingMiddleware) for m in middlewares)
    assert isinstance(middlewares[-1], SafetyFinishReasonMiddleware)


def test_build_lead_runtime_middlewares_orders_thread_data_before_uploads():
    """ThreadDataMiddleware must run before UploadsMiddleware so the uploads
    directory is guaranteed to exist when UploadsMiddleware scans it under
    lazy_init=False. This is the narrow functional concern the chain order
    protects; a regression here would silently drop historical files on the
    first run of a thread when the directory has not been pre-created by the
    upload endpoint.
    """
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware

    app_config = _make_app_config()
    middlewares = build_lead_runtime_middlewares(app_config=app_config)

    td_indices = [i for i, m in enumerate(middlewares) if isinstance(m, ThreadDataMiddleware)]
    um_indices = [i for i, m in enumerate(middlewares) if isinstance(m, UploadsMiddleware)]

    assert td_indices and len(td_indices) == 1, f"expected exactly one ThreadDataMiddleware, got {td_indices}"
    assert um_indices and len(um_indices) == 1, f"expected exactly one UploadsMiddleware, got {um_indices}"
    assert td_indices[0] < um_indices[0], f"ThreadDataMiddleware (idx {td_indices[0]}) must come before UploadsMiddleware (idx {um_indices[0]}) so the uploads directory exists when UploadsMiddleware scans it under lazy_init=False."


def test_build_lead_runtime_middlewares_chain_order_matches_agents_md():
    """Pin the AGENTS.md middleware numbering for the shared runtime base.

    The existing tests stub most middlewares as a single ``FakeMiddleware``,
    which cannot detect a reorder. This test uses the real classes so an
    index swap between any pair (e.g. Uploads vs ThreadData, Sandbox vs
    DanglingToolCall) is caught. If a future refactor legitimately reorders
    these, update backend/AGENTS.md "Middleware Chain" in the same change.
    """
    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware
    from deerflow.agents.middlewares.input_sanitization_middleware import InputSanitizationMiddleware
    from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
    from deerflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
    from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware
    from deerflow.sandbox.middleware import SandboxMiddleware

    app_config = _make_app_config()
    middlewares = build_lead_runtime_middlewares(app_config=app_config)

    def idx_of(cls, *, label: str) -> int:
        matches = [i for i, m in enumerate(middlewares) if isinstance(m, cls)]
        assert matches, f"{label} missing from chain"
        assert len(matches) == 1, f"expected exactly one {label}, got indices {matches}"
        return matches[0]

    # Mirrors AGENTS.md "Shared runtime base" items 1-10 (non-optional spine).
    expected_order: list[tuple[str, type]] = [
        ("InputSanitizationMiddleware", InputSanitizationMiddleware),
        ("ToolOutputBudgetMiddleware", ToolOutputBudgetMiddleware),
        ("ThreadDataMiddleware", ThreadDataMiddleware),
        ("UploadsMiddleware", UploadsMiddleware),
        ("SandboxMiddleware", SandboxMiddleware),
        ("DanglingToolCallMiddleware", DanglingToolCallMiddleware),
        ("LLMErrorHandlingMiddleware", LLMErrorHandlingMiddleware),
        ("SandboxAuditMiddleware", SandboxAuditMiddleware),
        ("ToolErrorHandlingMiddleware", ToolErrorHandlingMiddleware),
    ]
    actual = [(label, idx_of(cls, label=label)) for label, cls in expected_order]

    for (name_a, idx_a), (name_b, idx_b) in zip(actual, actual[1:]):
        assert idx_a < idx_b, f"{name_a} (idx {idx_a}) must come before {name_b} (idx {idx_b}); full chain: {actual}"


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


def test_subagent_runtime_middlewares_attach_deferred_filter_when_setup_has_names(monkeypatch):
    """A subagent built with deferred MCP tools gets DeferredToolFilterMiddleware, positioned before SafetyFinishReasonMiddleware (mirrors the lead ordering)."""
    from langchain_core.tools import tool as as_tool

    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
    from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
    from deerflow.tools.builtins.tool_search import build_deferred_tool_setup
    from deerflow.tools.mcp_metadata import tag_mcp_tool

    app_config = _make_app_config()
    _stub_runtime_middleware_imports(monkeypatch)

    @as_tool
    def mcp_thing(x: str) -> str:
        "deferred mcp tool"
        return x

    setup = build_deferred_tool_setup([tag_mcp_tool(mcp_thing)], enabled=True)
    assert setup.deferred_names  # sanity: populated setup

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, deferred_setup=setup)

    filters = [m for m in middlewares if isinstance(m, DeferredToolFilterMiddleware)]
    assert len(filters) == 1
    filter_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, DeferredToolFilterMiddleware))
    safety_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, SafetyFinishReasonMiddleware))
    assert filter_idx < safety_idx


def test_subagent_runtime_middlewares_skip_deferred_filter_without_names(monkeypatch):
    """No deferred setup (disabled / no MCP tool) -> no DeferredToolFilterMiddleware."""
    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
    from deerflow.tools.builtins.tool_search import DeferredToolSetup

    app_config = _make_app_config()
    _stub_runtime_middleware_imports(monkeypatch)

    for setup in (None, DeferredToolSetup(None, frozenset(), None)):
        middlewares = build_subagent_runtime_middlewares(app_config=app_config, deferred_setup=setup)
        assert not any(isinstance(m, DeferredToolFilterMiddleware) for m in middlewares)


def test_lead_runtime_chain_finds_historical_uploads_under_lazy_init_false(tmp_path, monkeypatch):
    """Integration anchor for the ThreadData → Uploads ordering.

    Under lazy_init=False, ThreadDataMiddleware eagerly creates the thread
    directories in before_agent. UploadsMiddleware then scans the uploads
    directory. Running both middlewares via the real build_lead_runtime_middlewares
    chain (TD before UM) must surface pre-existing historical files in the
    injected <uploaded_files> context.

    This complements the static order contract
    (test_build_lead_runtime_middlewares_orders_thread_data_before_uploads):
    that test pins the chain position; this test pins the observable behavior
    at that position.
    """
    from langchain_core.messages import HumanMessage
    from langgraph.runtime import Runtime

    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware
    from deerflow.config.paths import Paths
    from deerflow.runtime.user_context import get_effective_user_id

    thread_id = "thread-historical-files"
    user_id = get_effective_user_id()

    paths = Paths(str(tmp_path))
    uploads_dir = paths.sandbox_uploads_dir(thread_id, user_id=user_id)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / "prior-report.txt").write_bytes(b"historical payload")

    td = ThreadDataMiddleware(base_dir=str(tmp_path), lazy_init=False)
    um = UploadsMiddleware(base_dir=str(tmp_path))

    runtime = Runtime(context={"thread_id": thread_id, "run_id": "run-1"})
    state = {"messages": [HumanMessage(content="please summarise the prior upload")]}

    td_result = td.before_agent(state, runtime)
    assert td_result is not None, "ThreadDataMiddleware must run and produce state updates"
    # Sanity: under lazy_init=False the directories were created (not just computed).
    assert uploads_dir.exists(), "ThreadDataMiddleware should have ensured the uploads directory exists"

    # ThreadDataMiddleware rewrites the last HumanMessage (annotating run_id/timestamp);
    # carry its updated messages into the UploadsMiddleware input state, mirroring
    # how LangGraph chains before_agent outputs into the next middleware.
    um_input = {**state, "messages": td_result["messages"]}
    um_result = um.before_agent(um_input, runtime)

    assert um_result is not None, "UploadsMiddleware must inject context when historical files exist"
    injected_content = um_result["messages"][-1].content
    assert "<uploaded_files>" in injected_content
    assert "prior-report.txt" in injected_content
    assert "previous messages" in injected_content  # historical section header
