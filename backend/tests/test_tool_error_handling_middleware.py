import posixpath
import sys
from types import ModuleType, SimpleNamespace

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt

from deerflow.agents.middlewares.tool_error_handling_middleware import (
    ToolErrorHandlingMiddleware,
    build_lead_runtime_middlewares,
    build_subagent_runtime_middlewares,
)
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY
from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.config import summarization_config
from deerflow.config.app_config import AppConfig, CircuitBreakerConfig
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.guardrails_config import GuardrailsConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.subagents.status_contract import SUBAGENT_ERROR_KEY, SUBAGENT_STATUS_KEY


class ConfiguredSubagentMiddleware(AgentMiddleware):
    pass


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
    # 9 baseline (InputSanitization, ToolOutputBudget, ToolResultSanitization,
    # ThreadData, Sandbox, DanglingToolCall, LLMErrorHandling, SandboxAudit,
    # ToolErrorHandling)
    # + 1 ReadBeforeWriteMiddleware + 1 LoopDetectionMiddleware
    # + 1 TokenBudgetMiddleware (subagents.token_budget enabled by default, #3875 Phase 2)
    # + 1 SafetyFinishReasonMiddleware + 1 DurableContextMiddleware
    # + 1 SystemMessageCoalescingMiddleware (all enabled by default).
    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
    from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
    from deerflow.agents.middlewares.system_message_coalescing_middleware import SystemMessageCoalescingMiddleware
    from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
    from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware

    assert len(middlewares) == 15
    assert isinstance(middlewares[0], FakeMiddleware)  # InputSanitizationMiddleware stub
    assert isinstance(middlewares[1], ToolOutputBudgetMiddleware)
    assert any(isinstance(m, ToolErrorHandlingMiddleware) for m in middlewares)
    # The token-budget backstop is attached by default so the cap engages (#3875).
    assert any(isinstance(m, TokenBudgetMiddleware) for m in middlewares)
    assert any(isinstance(m, SafetyFinishReasonMiddleware) for m in middlewares)
    # DurableContextMiddleware is present but not last: the coalescer (#4040) is
    # appended innermost so it can merge the SystemMessage DurableContext injects.
    # The coalescer is appended unconditionally (after the optional summarization
    # middleware), so it is the last element regardless of summarization.enabled —
    # unlike DurableContextMiddleware, which is only last when summarization is off.
    durable_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, DurableContextMiddleware))
    assert isinstance(middlewares[-1], SystemMessageCoalescingMiddleware)
    assert durable_idx < len(middlewares) - 1


def test_tool_progress_middleware_is_outer_relative_to_error_handling(monkeypatch: pytest.MonkeyPatch):
    # ToolProgressMiddleware must have a lower index than ToolErrorHandlingMiddleware
    # so that the framework's "first in list = outermost" rule makes it outer.
    # Only then can it read deerflow_tool_meta stamped by ToolErrorHandlingMiddleware.
    from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
    from deerflow.config.tool_progress_config import ToolProgressConfig

    app_config = AppConfig(
        models=[
            ModelConfig(
                name="test-model",
                display_name="test-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="test-model",
            )
        ],
        sandbox=SandboxConfig(use="test"),
        guardrails=GuardrailsConfig(enabled=False),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=7, recovery_timeout_sec=11),
        tool_progress=ToolProgressConfig(enabled=True),
    )

    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, lazy_init=False)

    progress_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, ToolProgressMiddleware))
    error_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, ToolErrorHandlingMiddleware))
    assert progress_idx < error_idx, f"ToolProgressMiddleware (index {progress_idx}) must be outer (lower index) than ToolErrorHandlingMiddleware (index {error_idx}); order: {[type(m).__name__ for m in middlewares]}"


def test_middleware_ordering_guard_raises_when_progress_is_inner(monkeypatch: pytest.MonkeyPatch):
    """_build_runtime_middlewares must raise RuntimeError when ToolProgressMiddleware ends up
    at a higher index than ToolErrorHandlingMiddleware.

    We trigger the wrong-order condition by patching SandboxAuditMiddleware to be an actual
    ToolErrorHandlingMiddleware instance, which appears BEFORE ToolProgressMiddleware in the
    list. The guard's isinstance() check finds it first, making error_idx < progress_idx.
    """
    from deerflow.agents.middlewares.tool_error_handling_middleware import (
        ToolErrorHandlingMiddleware,
        build_lead_runtime_middlewares,
    )
    from deerflow.config.tool_progress_config import ToolProgressConfig

    _stub_runtime_middleware_imports(monkeypatch)
    # Override the SandboxAuditMiddleware stub with a real ToolErrorHandlingMiddleware so it
    # becomes the FIRST ToolErrorHandlingMiddleware in the list, appearing before
    # ToolProgressMiddleware and triggering the ordering guard.
    monkeypatch.setitem(
        sys.modules,
        "deerflow.agents.middlewares.sandbox_audit_middleware",
        _module(
            "deerflow.agents.middlewares.sandbox_audit_middleware",
            SandboxAuditMiddleware=ToolErrorHandlingMiddleware,
        ),
    )

    app_config = _make_app_config()
    app_config = app_config.model_copy(update={"tool_progress": ToolProgressConfig(enabled=True)})

    with pytest.raises(RuntimeError, match="ToolProgressMiddleware must be outer"):
        build_lead_runtime_middlewares(app_config=app_config, lazy_init=False)


def test_lead_runtime_middlewares_thread_app_config_to_tool_error_handling(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(
        sys.modules,
        "deerflow.agents.middlewares.input_sanitization_middleware",
        _module("deerflow.agents.middlewares.input_sanitization_middleware", InputSanitizationMiddleware=object),
    )
    app_config = _make_app_config()
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_lead_runtime_middlewares(app_config=app_config)

    tool_middleware = next(mw for mw in middlewares if isinstance(mw, ToolErrorHandlingMiddleware))
    assert tool_middleware._app_config is app_config


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
    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
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
        ("ReadBeforeWriteMiddleware", ReadBeforeWriteMiddleware),
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


def test_read_file_skill_read_stamps_compact_skill_metadata():
    app_config = _make_app_config()
    app_config.skills.container_path = "/mnt/skills"
    app_config.summarization.skill_file_read_tool_names = ["read_file"]
    middleware = ToolErrorHandlingMiddleware(app_config=app_config)
    req = _request(name="read_file", tool_call_id="read-1")
    req.tool_call["args"] = {"path": "/mnt/skills/public/data-analysis/SKILL.md"}

    result = middleware.wrap_tool_call(
        req,
        lambda _req: ToolMessage(
            content="---\nname: data-analysis\ndescription: Analyze data.\n---\nBODY",
            tool_call_id="read-1",
            name="read_file",
        ),
    )

    assert result.additional_kwargs["skill_context_entry"] == {
        "path": "/mnt/skills/public/data-analysis/SKILL.md",
        "description": "Analyze data.",
    }


def test_skill_read_config_is_cached_on_middleware_instance():
    middleware = ToolErrorHandlingMiddleware()
    default_names = getattr(summarization_config, "DEFAULT_SKILL_FILE_READ_TOOL_NAMES", None)

    assert default_names is not None
    assert middleware._skill_read_tool_names == frozenset(default_names)
    assert middleware._skills_root == "/mnt/skills"


def test_skill_metadata_respects_custom_skills_root():
    app_config = _make_app_config()
    app_config.skills.container_path = "/custom/skills"
    app_config.summarization.skill_file_read_tool_names = ["read_file"]
    middleware = ToolErrorHandlingMiddleware(app_config=app_config)
    req = _request(name="read_file", tool_call_id="read-1")
    req.tool_call["args"] = {"path": "/custom/skills/public/x/SKILL.md"}

    result = middleware.wrap_tool_call(
        req,
        lambda _req: ToolMessage("---\ndescription: X\n---\nBody", tool_call_id="read-1", name="read_file"),
    )

    assert result.additional_kwargs["skill_context_entry"]["path"] == "/custom/skills/public/x/SKILL.md"


def test_skill_metadata_disabled_when_read_tool_names_empty():
    app_config = _make_app_config()
    app_config.summarization.skill_file_read_tool_names = []
    middleware = ToolErrorHandlingMiddleware(app_config=app_config)
    req = _request(name="read_file", tool_call_id="read-1")
    req.tool_call["args"] = {"path": "/mnt/skills/public/x/SKILL.md"}

    result = middleware.wrap_tool_call(
        req,
        lambda _req: ToolMessage("---\ndescription: X\n---\nBody", tool_call_id="read-1", name="read_file"),
    )

    assert "skill_context_entry" not in result.additional_kwargs


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


def test_wrap_tool_call_stamps_tool_meta_on_exception():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="web_search", tool_call_id="tc-42")

    def _boom(_req):
        raise ConnectionError("connection refused")

    result = middleware.wrap_tool_call(req, _boom)

    assert isinstance(result, ToolMessage)
    assert TOOL_META_KEY in result.additional_kwargs
    meta = result.additional_kwargs[TOOL_META_KEY]
    assert meta["status"] == "error"
    assert meta["source"] == "exception"
    assert meta["error_type"] == "transient"


def test_task_exception_wrapper_uses_subagent_result_formatter():
    middleware = ToolErrorHandlingMiddleware()
    req = _request(name="task", tool_call_id="tc-task")

    def _boom(_req):
        raise RuntimeError("network down")

    result = middleware.wrap_tool_call(req, _boom)

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "tc-task"
    assert result.name == "task"
    assert result.status == "error"
    assert result.content == "Task failed. Error: RuntimeError: network down. Continue with available context, or choose an alternative tool."
    assert result.additional_kwargs[SUBAGENT_STATUS_KEY] == "failed"
    assert result.additional_kwargs[SUBAGENT_ERROR_KEY] == "RuntimeError: network down"


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


def test_subagent_runtime_middlewares_inject_configured_extension_middlewares(monkeypatch):
    from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware

    app_config = _make_app_config()
    app_config.extensions = ExtensionsConfig(middlewares=[f"{__name__}:ConfiguredSubagentMiddleware"])
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config)

    extension_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, ConfiguredSubagentMiddleware))
    safety_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, SafetyFinishReasonMiddleware))
    for guard_name in ("LoopDetectionMiddleware", "TokenBudgetMiddleware"):
        guard_idx = next((i for i, m in enumerate(middlewares) if type(m).__name__ == guard_name), None)
        if guard_idx is not None:
            assert guard_idx < extension_idx
    assert extension_idx < safety_idx


def test_subagent_runtime_middlewares_place_mcp_routing_before_deferred_filter(monkeypatch):
    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
    from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware
    from deerflow.tools.builtins.tool_search import DeferredToolSetup

    app_config = _make_app_config()
    _stub_runtime_middleware_imports(monkeypatch)
    routing = McpRoutingMiddleware({"mcp_thing": {"priority": 100, "keywords": ["orders"]}}, "hash123", 3)
    setup = DeferredToolSetup(object(), frozenset({"mcp_thing"}), "hash123")

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, deferred_setup=setup, mcp_routing_middleware=routing)

    routing_idx = next(i for i, middleware in enumerate(middlewares) if isinstance(middleware, McpRoutingMiddleware))
    filter_idx = next(i for i, middleware in enumerate(middlewares) if isinstance(middleware, DeferredToolFilterMiddleware))
    assert routing_idx < filter_idx


def test_subagent_runtime_middlewares_skip_deferred_filter_without_names(monkeypatch):
    """No deferred setup (disabled / no MCP tool) -> no DeferredToolFilterMiddleware."""
    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
    from deerflow.tools.builtins.tool_search import DeferredToolSetup

    app_config = _make_app_config()
    _stub_runtime_middleware_imports(monkeypatch)

    for setup in (None, DeferredToolSetup(None, frozenset(), None)):
        middlewares = build_subagent_runtime_middlewares(app_config=app_config, deferred_setup=setup)
        assert not any(isinstance(m, DeferredToolFilterMiddleware) for m in middlewares)


def test_subagent_runtime_middlewares_attach_loop_detection_when_enabled(monkeypatch):
    """Subagents must inherit the lead's LoopDetectionMiddleware so a degenerate
    tool loop is broken instead of burning tokens until ``max_turns`` (#3875).
    ``loop_detection.enabled`` defaults to True, so the default subagent chain
    carries the guard. Phase 1 of #3875."""
    from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware

    app_config = _make_app_config()
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model")

    loop = [m for m in middlewares if isinstance(m, LoopDetectionMiddleware)]
    assert len(loop) == 1


def test_subagent_runtime_middlewares_omit_loop_detection_when_disabled(monkeypatch):
    """``loop_detection.enabled=False`` must drop the guard from the subagent
    chain, mirroring the lead's gate (``lead_agent/agent.py``)."""
    from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
    from deerflow.config.loop_detection_config import LoopDetectionConfig

    app_config = _make_app_config().model_copy(update={"loop_detection": LoopDetectionConfig(enabled=False)})
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model")

    assert not any(isinstance(m, LoopDetectionMiddleware) for m in middlewares)


def test_subagent_runtime_middlewares_place_loop_detection_before_safety_finish(monkeypatch):
    """LoopDetectionMiddleware must be registered before SafetyFinishReasonMiddleware
    (earlier in the middleware list). LangChain dispatches after_model hooks in
    reverse registration order, so SafetyFinishReasonMiddleware (registered
    later) executes first — the placement its docstring requires and the lead
    chain (``lead_agent/agent.py``) uses. The assertion pins registration order,
    not execution order."""
    from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
    from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware

    app_config = _make_app_config()
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model")

    loop_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, LoopDetectionMiddleware))
    safety_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, SafetyFinishReasonMiddleware))
    assert loop_idx < safety_idx


def test_subagent_runtime_middlewares_attach_durable_context_before_summarization(monkeypatch):
    """Subagents must project ``summary_text`` back into model requests after
    compaction, just like the lead agent does.

    Without ``DurableContextMiddleware``, a message-count keep policy can
    retain only an assistant tool-call plus its tool results. The summary is
    stored in ``ThreadState.summary_text`` but never reaches the next request,
    so strict providers reject the assistant-first history. The durable
    context layer must use the same skill settings as the lead chain and run
    before summarization.
    """
    from deerflow.agents.middlewares import summarization_middleware as sm
    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware

    sentinel = object()
    captured: dict[str, object] = {}

    def fake_create_summarization_middleware(*, app_config=None, keep=None, skip_memory_flush=False):
        captured["app_config"] = app_config
        captured["keep"] = keep
        captured["skip_memory_flush"] = skip_memory_flush
        return sentinel

    # summarization is enabled by default False; flip it on so the factory path
    # is taken (the factory early-returns None when disabled).
    from deerflow.config.summarization_config import SummarizationConfig

    app_config = _make_app_config().model_copy(update={"summarization": SummarizationConfig(enabled=True)})
    monkeypatch.setattr(sm, "create_summarization_middleware", fake_create_summarization_middleware)
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model")

    # The shared factory received the same app_config the builder did (no lead
    # wrapper, no config drift between the two chains).
    assert captured["app_config"] is app_config
    # skip_memory_flush=True so subagent-internal turns are not flushed into the
    # PARENT thread's durable memory (#3875 Phase 3 review).
    assert captured["skip_memory_flush"] is True
    durable = [middleware for middleware in middlewares if isinstance(middleware, DurableContextMiddleware)]
    assert len(durable) == 1
    # ``_skills_root`` is ``posixpath.normpath(container_path)``, so compare against
    # the normalized form — a trailing slash / ``.`` / ``..`` in config would fail
    # a raw equality even though the wiring is correct.
    assert durable[0]._skills_root == posixpath.normpath(app_config.skills.container_path)
    assert durable[0]._skill_read_tool_names == frozenset(app_config.summarization.skill_file_read_tool_names)
    assert middlewares.index(durable[0]) < middlewares.index(sentinel)


def test_subagent_compaction_injects_summary_before_assistant_tool_tail(monkeypatch):
    """A three-tool turn with ``keep=4`` must remain provider-valid.

    This reproduces the production failure shape: compaction preserves an
    assistant tool-call plus three tool results while removing the original
    system/user messages. The subagent chain must inject the generated summary
    as durable human context before that tail reaches the model.
    """
    from langchain.agents import create_agent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
    from deerflow.agents.middlewares.system_message_coalescing_middleware import SystemMessageCoalescingMiddleware
    from deerflow.agents.thread_state import ThreadState
    from deerflow.config.summarization_config import ContextSize, SummarizationConfig

    class _StaticModel(BaseChatModel):
        text: str
        require_durable_summary: bool = False

        @property
        def _llm_type(self) -> str:
            return "static"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if self.require_durable_summary:
                first_ai = next(i for i, message in enumerate(messages) if isinstance(message, AIMessage))
                durable = [(i, message) for i, message in enumerate(messages) if isinstance(message, HumanMessage) and message.additional_kwargs.get("durable_context_data")]
                assert durable, "compacted summary must be injected into the subagent request"
                assert durable[0][0] < first_ai, "durable summary must precede the assistant/tool tail"
                assert "COMPRESSED_SUBAGENT_HISTORY" in durable[0][1].content
                # DurableContext injects a SystemMessage(authority); without the
                # coalescer the request would carry it as a second/non-leading
                # system message, which strict providers reject (#4040). Assert the
                # outgoing request is provider-valid: a single leading SystemMessage.
                system_indices = [i for i, message in enumerate(messages) if isinstance(message, SystemMessage)]
                assert system_indices == [0], f"request must have exactly one leading SystemMessage, got {system_indices}"
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])

    summary_model = _StaticModel(text="COMPRESSED_SUBAGENT_HISTORY")
    strict_model = _StaticModel(text="final answer", require_durable_summary=True)
    monkeypatch.setattr(
        "deerflow.agents.middlewares.summarization_middleware.create_chat_model",
        lambda **kwargs: summary_model,
    )

    app_config = _make_app_config().model_copy(
        update={
            "summarization": SummarizationConfig(
                enabled=True,
                trigger=ContextSize(type="messages", value=5),
                keep=ContextSize(type="messages", value=4),
            )
        }
    )
    runtime_middlewares = build_subagent_runtime_middlewares(
        app_config=app_config,
        model_name="test-model",
        agent_name="general-purpose",
    )
    compaction_middlewares = [middleware for middleware in runtime_middlewares if isinstance(middleware, (DurableContextMiddleware, DeerFlowSummarizationMiddleware, SystemMessageCoalescingMiddleware))]
    agent = create_agent(
        model=strict_model,
        tools=[],
        middleware=compaction_middlewares,
        state_schema=ThreadState,
    )

    tool_calls = [{"name": "web_search", "args": {"query": f"q{i}"}, "id": f"call_{i}", "type": "tool_call"} for i in range(3)]
    seed = [
        SystemMessage(content="subagent instructions", id="system"),
        HumanMessage(content="research three regions", id="human"),
        AIMessage(content="searching", tool_calls=tool_calls, id="assistant"),
        *[ToolMessage(content=f"result {i}", tool_call_id=f"call_{i}", id=f"tool_{i}") for i in range(3)],
    ]

    result = agent.invoke({"messages": seed})

    assert result["summary_text"] == "COMPRESSED_SUBAGENT_HISTORY"
    assert result["messages"][-1].content == "final answer"


def test_subagent_chain_coalesces_durable_authority_system_message(monkeypatch):
    """The durable-context authority SystemMessage must not survive as a second one.

    Subagents carry their system prompt as a leading ``SystemMessage`` in
    ``messages`` (``create_agent(system_prompt=None)``), and
    ``DurableContextMiddleware`` inserts ``SystemMessage(authority_contract)``
    directly after it whenever durable data (summary / delegations / skills) is
    present. That leaves two adjacent system messages — the exact non-leading /
    duplicate-system shape strict OpenAI-compatible providers reject and the
    same #4039 failure class the durable fix set out to avoid.

    ``build_subagent_runtime_middlewares`` must therefore pair durable context
    with ``SystemMessageCoalescingMiddleware`` (#4040). This drives the real
    builder output through a strict model and asserts the outgoing request keeps
    exactly one leading ``SystemMessage``. Remove the coalescer from the builder
    and the model sees ``[System(base), System(authority), ...]`` and this fails.
    """
    from langchain.agents import create_agent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
    from deerflow.agents.middlewares.system_message_coalescing_middleware import SystemMessageCoalescingMiddleware
    from deerflow.agents.thread_state import ThreadState

    seen: dict[str, list[int]] = {}

    class _StrictModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "strict"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen["system_indices"] = [i for i, message in enumerate(messages) if isinstance(message, SystemMessage)]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    app_config = _make_app_config()
    runtime_middlewares = build_subagent_runtime_middlewares(
        app_config=app_config,
        model_name="test-model",
        agent_name="general-purpose",
    )
    # Isolate the two middlewares under test, preserving builder order. The
    # coalescer must come after (inner of) durable context to observe the
    # injected system message.
    chain = [m for m in runtime_middlewares if isinstance(m, (DurableContextMiddleware, SystemMessageCoalescingMiddleware))]
    assert [type(m).__name__ for m in chain] == ["DurableContextMiddleware", "SystemMessageCoalescingMiddleware"]

    agent = create_agent(model=_StrictModel(), tools=[], middleware=chain, state_schema=ThreadState)

    # A leading system prompt plus an assistant tool-call tail, with a summary
    # already in state so durable context injects its authority SystemMessage.
    seed = [
        SystemMessage(content="subagent instructions", id="system"),
        AIMessage(content="searching", tool_calls=[{"name": "web_search", "args": {"query": "x"}, "id": "call_0", "type": "tool_call"}], id="assistant"),
        ToolMessage(content="result", tool_call_id="call_0", id="tool_0"),
    ]
    agent.invoke({"messages": seed, "summary_text": "COMPRESSED_SUBAGENT_HISTORY"})

    assert seen["system_indices"] == [0], f"request must have a single leading SystemMessage, got {seen['system_indices']}"


def test_subagent_runtime_middlewares_omit_summarization_when_factory_returns_none(monkeypatch):
    """When ``summarization.enabled`` is False the shared factory returns None and
    the subagent chain must NOT carry a summarization middleware — the default
    state, since SummarizationConfig.enabled defaults to False."""
    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

    app_config = _make_app_config()  # summarization.enabled defaults to False
    _stub_runtime_middleware_imports(monkeypatch)

    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model")

    assert not any(isinstance(m, DeerFlowSummarizationMiddleware) for m in middlewares)


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


def test_subagent_summarization_fires_mid_run_and_produces_usable_result(monkeypatch):
    """Integration coverage for #3875 Phase 3 review gap: drive the REAL
    ``DeerFlowSummarizationMiddleware`` (the exact instance the subagent chain
    gets via ``create_summarization_middleware(skip_memory_flush=True)``) through
    a ``create_agent`` run, and assert that (a) compaction actually fires mid-run
    (messages channel contracts via ``RemoveMessage``) and (b) the run still
    completes with a usable final answer — not just wiring.

    The builder-wiring test above proves the middleware lands on the chain; this
    proves the live middleware triggers and the run survives it. We bypass the
    full ``build_subagent_runtime_middlewares`` chain (whose sandbox/thread-data
    stubs aren't AgentMiddleware-compatible for a live run) and use the factory
    directly — the same instance the builder appends."""
    from langchain.agents import create_agent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from deerflow.agents.middlewares.summarization_middleware import (
        DeerFlowSummarizationMiddleware,
        create_summarization_middleware,
    )
    from deerflow.agents.thread_state import ThreadState
    from deerflow.config.memory_config import MemoryConfig
    from deerflow.config.summarization_config import ContextSize, SummarizationConfig

    # A model that always emits a plain AIMessage — no tools, so the run is a
    # single turn but the input already exceeds the trigger threshold, forcing
    # before_model compaction on the first (and only) model call.
    class _StaticModel(BaseChatModel):
        text: str = "final answer after compaction"

        @property
        def _llm_type(self) -> str:
            return "static"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])

    static_model = _StaticModel()
    # The factory resolves its summary model via create_chat_model; point it at
    # the same static model so no real provider is contacted.
    monkeypatch.setattr(
        "deerflow.agents.middlewares.summarization_middleware.create_chat_model",
        lambda **kwargs: static_model,
    )

    app_config = SimpleNamespace(
        summarization=SummarizationConfig(
            enabled=True,
            trigger=ContextSize(type="messages", value=4),
            keep=ContextSize(type="messages", value=2),
        ),
        # memory disabled + skip_memory_flush=True mirrors the subagent path:
        # no memory_flush_hook is attached.
        memory=MemoryConfig(enabled=False),
    )
    middleware = create_summarization_middleware(
        app_config=app_config,
        skip_memory_flush=True,
    )
    assert isinstance(middleware, DeerFlowSummarizationMiddleware), "the real middleware must be built"
    # Subagent invariant: skip_memory_flush means no durable-memory hook.
    assert not middleware._before_summarization_hooks

    agent = create_agent(
        model=static_model,
        tools=[],
        middleware=[middleware],
        state_schema=ThreadState,
    )

    # 6 messages > trigger(4) → compaction must fire in before_model.
    seed = [
        HumanMessage(content="q1", id="h1"),
        AIMessage(content="a1", id="a1"),
        HumanMessage(content="q2", id="h2"),
        AIMessage(content="a2", id="a2"),
        HumanMessage(content="q3", id="h3"),
        AIMessage(content="a3", id="a3"),
    ]
    chunks = list(agent.stream({"messages": seed}, stream_mode="updates"))

    # (a) Compaction fired: the middleware's before_model emitted a summary + RemoveMessage.
    before_model_chunks = [c for c in chunks if "DeerFlowSummarizationMiddleware.before_model" in c]
    assert before_model_chunks, "summarization before_model must fire when messages exceed the trigger"
    summary_update = before_model_chunks[0]["DeerFlowSummarizationMiddleware.before_model"]
    assert summary_update.get("summary_text"), "a summary must be produced"
    emitted = summary_update["messages"]
    assert isinstance(emitted[0], RemoveMessage), "compaction must lead with RemoveMessage"

    # (b) The run completed with a usable final AIMessage despite compaction.
    # The model's output surfaces under the "model" node key in updates mode.
    final_messages: list = []
    for chunk in chunks:
        node_msg = chunk.get("model") or chunk.get("agent") or {}
        final_messages = node_msg.get("messages", final_messages)
    ai_finals = [m for m in final_messages if isinstance(m, AIMessage)]
    assert ai_finals, "the run must produce a final AIMessage after compaction"
    assert ai_finals[-1].content == "final answer after compaction"
