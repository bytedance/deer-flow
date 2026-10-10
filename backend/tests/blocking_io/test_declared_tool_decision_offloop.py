"""Regression: the subagent middleware-declared-tool decision runs off the event loop.

``SubagentExecutor._create_agent`` is awaited by ``_aexecute`` on the shared
event loop, and its authorization declaration pass calls the provider's
``filter_resources`` — which a custom provider may implement with external
policy-service IO. The decision must stay behind ``asyncio.to_thread``; if it
is flattened back to a plain call, the blocking-probe provider below trips the
strict Blockbuster gate (this directory's conftest). The meta-check at the
bottom proves the probe has teeth by calling the decision inline on the loop.
"""

from __future__ import annotations

import importlib
import sys
import threading
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Same cycle-breaking parent mocks as tests/test_subagent_executor.py: the real
# executor must be imported behind them (conftest.py keeps a mock in
# sys.modules["deerflow.subagents.executor"] for collection).
_MOCKED_MODULE_NAMES = [
    "deerflow.agents",
    "deerflow.agents.thread_state",
    "deerflow.agents.middlewares",
    "deerflow.agents.middlewares.thread_data_middleware",
    "deerflow.sandbox",
    "deerflow.sandbox.middleware",
    "deerflow.sandbox.security",
    "deerflow.models",
    "deerflow.skills.storage",
]


def _import_real_executor():
    """Import the real SubagentExecutor at module scope (imports do one-time IO
    that must not run inside a gated test item), then restore sys.modules."""
    original_modules = {name: sys.modules.get(name) for name in _MOCKED_MODULE_NAMES}
    original_executor = sys.modules.get("deerflow.subagents.executor")
    # Preload the real leafs the executor imports at runtime so no import IO
    # happens inside the gated test either.
    tool_declarations_module = importlib.import_module("deerflow.agents.middlewares.tool_declarations")
    audit_context_module = importlib.import_module("deerflow.agents.middlewares.audit_context")

    sys.modules.pop("deerflow.subagents.executor", None)
    subagents_pkg = sys.modules.get("deerflow.subagents")
    had_executor_attr = subagents_pkg is not None and hasattr(subagents_pkg, "executor")
    if had_executor_attr:
        delattr(subagents_pkg, "executor")

    for name in _MOCKED_MODULE_NAMES:
        sys.modules[name] = MagicMock()
    sys.modules["deerflow.agents.middlewares.tool_declarations"] = tool_declarations_module
    sys.modules["deerflow.agents.middlewares.audit_context"] = audit_context_module
    try:
        module = importlib.import_module("deerflow.subagents.executor")
    finally:
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        if original_executor is not None:
            sys.modules["deerflow.subagents.executor"] = original_executor
    return module


executor_module = _import_real_executor()
SubagentExecutor = executor_module.SubagentExecutor
SubagentConfig = importlib.import_module("deerflow.subagents.config").SubagentConfig
LayerOneOutcome = importlib.import_module("deerflow.agents.middlewares.tool_declarations").LayerOneOutcome
tool_declarations = sys.modules["deerflow.agents.middlewares.tool_declarations"]

pytestmark = pytest.mark.asyncio


def _leaf_module(name: str, **attrs):
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _app_config():
    return SimpleNamespace(
        models=[SimpleNamespace(name="default-model")],
        authorization=SimpleNamespace(enabled=True, fail_closed=True, default_role="user"),
    )


def _blocking_probe_provider(probe_file, observed_threads: list):
    """An AuthorizationProvider whose filter_resources performs real blocking file IO."""
    from deerflow.authz.provider import AuthzDecision

    class _Provider:
        name = "blocking-probe"

        def authorize(self, request):
            return AuthzDecision(allow=True)

        async def aauthorize(self, request):
            return self.authorize(request)

        def filter_resources(self, principal, resource_type, candidates):
            observed_threads.append(threading.current_thread())
            body = probe_file.read_text(encoding="utf-8")  # trips the gate on the loop
            return [candidate for candidate in candidates if candidate in body]

    return _Provider()


def _executor_with_declaration(monkeypatch, declaring):
    app_config = _app_config()
    captured: dict = {}

    def fake_build_subagent_runtime_middlewares(**kwargs):
        return [declaring]

    def fake_create_agent(**kwargs):
        captured["agent"] = kwargs
        return MagicMock()

    monkeypatch.setattr(executor_module, "create_chat_model", lambda **kwargs: MagicMock())
    monkeypatch.setattr(executor_module, "create_agent", fake_create_agent)
    monkeypatch.setitem(
        sys.modules,
        "deerflow.agents.middlewares.tool_error_handling_middleware",
        _leaf_module(
            "deerflow.agents.middlewares.tool_error_handling_middleware",
            build_subagent_runtime_middlewares=fake_build_subagent_runtime_middlewares,
        ),
    )

    # Phase 3's skill-authorization resolution requires a real
    # AuthorizationConfig; the SimpleNamespace app_config above is scoped to
    # the declaration pass, which uses the explicitly-set provider.
    monkeypatch.setattr(SubagentExecutor, "_resolve_skill_authorization", lambda self: None)
    monkeypatch.setattr("deerflow.agents.lead_agent.agent._authorize_model_name", lambda name, **_kwargs: name)

    executor = SubagentExecutor(
        config=SubagentConfig(name="researcher", description="d", system_prompt="p"),
        tools=[],
        app_config=app_config,
        parent_model="parent-model",
    )
    executor.model_name = "test-model"
    return executor, captured


def _tool(name: str):
    from langchain_core.tools import StructuredTool

    return StructuredTool.from_function(lambda: name, name=name, description=name)


async def test_declared_tool_decision_runs_off_loop(monkeypatch, tmp_path):
    """The seeded declaration decision must not execute provider IO on the loop."""
    from langchain.agents.middleware import AgentMiddleware

    probe = tmp_path / "policy.txt"
    probe.write_text("allowed_decl", encoding="utf-8")
    observed_threads: list = []

    class _DeclaringMiddleware(AgentMiddleware):
        def __init__(self, tools):
            super().__init__()
            self.tools = tools

    declaring = _DeclaringMiddleware([_tool("allowed_decl"), _tool("denied_decl")])
    executor, captured = _executor_with_declaration(monkeypatch, declaring)
    executor._authz_provider = _blocking_probe_provider(probe, observed_threads)
    executor._authz_context = {"user_role": "user"}
    executor._layer_one_outcome = LayerOneOutcome(submitted=frozenset({"regular"}), allowed=frozenset({"regular"}))

    await executor._create_agent()

    assert observed_threads, "the provider was never consulted — the anchor is vacuous"
    assert all(thread is not threading.current_thread() for thread in observed_threads), "filter_resources ran on the event-loop thread"
    (bound,) = captured["agent"]["middleware"]
    assert [tool.name for tool in bound.tools] == ["allowed_decl"]


async def test_inline_decision_trips_the_gate(tmp_path):
    """Meta-check: the same decision called inline (no offload) really does hit
    the gate — BlockingError fires inside the probe — so the anchor above is
    not vacuously green. ``filter_tools_by_authorization``'s fail-closed
    handler then swallows that error into a denial, which is exactly why the
    anchor's teeth are the thread identity assertion, not the exception."""
    from blockbuster import BlockingError

    probe = tmp_path / "policy.txt"
    probe.write_text("allowed_decl", encoding="utf-8")
    caught: list = []

    class _Provider:
        name = "blocking-probe"

        def authorize(self, request):
            from deerflow.authz.provider import AuthzDecision

            return AuthzDecision(allow=True)

        async def aauthorize(self, request):
            return self.authorize(request)

        def filter_resources(self, principal, resource_type, candidates):
            try:
                body = probe.read_text(encoding="utf-8")
            except BlockingError as exc:
                caught.append(exc)
                raise
            return [candidate for candidate in candidates if candidate in body]

    authorized = tool_declarations.decide_declared_tools(
        [_tool("allowed_decl")],
        outcome=LayerOneOutcome(submitted=frozenset(), allowed=frozenset()),
        context={},
        app_config=_app_config(),
        authorization_provider=_Provider(),
    )

    assert len(caught) == 1  # the gate fired through the deerflow decision frame
    assert authorized == frozenset()  # … and fail_closed converted it to a denial
