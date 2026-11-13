"""Native subagents enforce configured HITL approval without resume support."""

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from deerflow.config.app_config import AppConfig

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


@pytest.fixture
def executor_module():
    """Import the real executor despite the suite's cycle-breaking doubles."""
    originals = {name: sys.modules.get(name) for name in _MOCKED_MODULE_NAMES}
    original_executor = sys.modules.get("deerflow.subagents.executor")
    preloaded_names = (
        "deerflow.agents.lead_agent.agent",
        "deerflow.agents.thread_state",
        "deerflow.agents.middlewares.audit_context",
        "deerflow.agents.middlewares.tool_declarations",
        "deerflow.agents.middlewares.tool_error_handling_middleware",
        "deerflow.models.factory",
        "deerflow.models.openai_codex_provider",
        "deerflow.agents.assembly_descriptor",
        "deerflow.sandbox.sandbox_provider",
        "deerflow.sandbox.overwrite",
        "deerflow.sandbox.prewarm",
    )
    original_preloaded = {name: sys.modules.get(name) for name in preloaded_names}
    preloaded = {name: importlib.import_module(name) for name in preloaded_names}

    sys.modules.pop("deerflow.subagents.executor", None)
    subagents_package = sys.modules.get("deerflow.subagents")
    if subagents_package is not None and hasattr(subagents_package, "executor"):
        delattr(subagents_package, "executor")
    for name in _MOCKED_MODULE_NAMES:
        sys.modules[name] = MagicMock()
    storage = ModuleType("deerflow.skills.storage")
    storage.get_or_new_skill_storage = lambda **kwargs: None
    sys.modules["deerflow.skills.storage"] = storage
    sys.modules.update(preloaded)

    module = importlib.import_module("deerflow.subagents.executor")
    try:
        yield module
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        for name, original in original_preloaded.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        if original_executor is None:
            sys.modules.pop("deerflow.subagents.executor", None)
        else:
            sys.modules["deerflow.subagents.executor"] = original_executor


class _BindableFakeChatModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


async def _run_native_subagent(executor_module, monkeypatch, *, approval_enabled: bool):
    executions = []

    @tool
    def bash(command: str) -> str:
        """Record a harmless command instead of executing a shell."""
        executions.append(command)
        return "executed"

    app_config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})
    app_config.hitl_approval.enabled = approval_enabled
    app_config.hitl_approval.tools = ["bash"]
    app_config.hitl_approval.non_interactive = "deny"
    model = _BindableFakeChatModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[{"name": "bash", "args": {"command": "record"}, "id": "call-1"}]),
                AIMessage(content="done"),
            ]
        )
    )
    monkeypatch.setattr(executor_module, "create_chat_model", lambda **kwargs: model)
    runtime_middlewares = sys.modules["deerflow.agents.middlewares.tool_error_handling_middleware"]
    monkeypatch.setattr(runtime_middlewares, "build_subagent_runtime_middlewares", lambda **kwargs: [])

    executor = executor_module.SubagentExecutor(
        config=executor_module.SubagentConfig(name="worker", description="test", skills=[]),
        tools=[bash],
        app_config=app_config,
        parent_model="test-model",
    )
    agent = await executor._create_agent([bash])
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="run the command")]},
        context={"is_subagent": True, "app_config": app_config},
    )
    return executions, result


@pytest.mark.anyio
async def test_native_subagent_denies_configured_tool_without_resume(executor_module, monkeypatch):
    executions, result = await _run_native_subagent(executor_module, monkeypatch, approval_enabled=True)

    assert executions == []
    assert "__interrupt__" not in result
    tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].name == "bash"
    assert tool_messages[0].status == "error"
    assert "No parent approval channel" in tool_messages[0].content
    assert "tool was not executed" in tool_messages[0].content


@pytest.mark.anyio
async def test_native_subagent_default_keeps_tool_execution_enabled(executor_module, monkeypatch):
    executions, result = await _run_native_subagent(executor_module, monkeypatch, approval_enabled=False)

    assert executions == ["record"]
    assert any(isinstance(message, ToolMessage) and message.content == "executed" for message in result["messages"])
