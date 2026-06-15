"""Tests for GenUI interaction callback isolation."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Mock langchain_core
# ---------------------------------------------------------------------------
langchain_core = types.ModuleType("langchain_core")
langchain_core_messages = types.ModuleType("langchain_core.messages")


class HumanMessage:
    def __init__(self, content: str, id: str | None = None):
        self.content = content
        self.id = id


class ToolMessage:
    def __init__(self, content: str, tool_call_id: str, name: str | None = None):
        self.content = content
        self.tool_call_id = tool_call_id
        self.name = name


langchain_core_messages.HumanMessage = HumanMessage
langchain_core_messages.ToolMessage = ToolMessage
langchain_core.messages = langchain_core_messages
sys.modules.setdefault("langchain_core", langchain_core)
sys.modules.setdefault("langchain_core.messages", langchain_core_messages)

# ---------------------------------------------------------------------------
# Mock langchain.agents
# ---------------------------------------------------------------------------
langchain_agents = types.ModuleType("langchain.agents")
langchain_agents_middleware = types.ModuleType("langchain.agents.middleware")


class AgentState(dict):
    pass


class AgentMiddleware:
    def __class_getitem__(cls, item):
        return cls


langchain_agents.AgentState = AgentState
langchain_agents.middleware = langchain_agents_middleware
langchain_agents_middleware.AgentMiddleware = AgentMiddleware
sys.modules.setdefault("langchain.agents", langchain_agents)
sys.modules.setdefault("langchain.agents.middleware", langchain_agents_middleware)

# ---------------------------------------------------------------------------
# Mock langgraph
# ---------------------------------------------------------------------------
langgraph_graph = types.ModuleType("langgraph.graph")
langgraph_graph.END = "__end__"
sys.modules.setdefault("langgraph.graph", langgraph_graph)

langgraph_prebuilt = types.ModuleType("langgraph.prebuilt")
langgraph_prebuilt_tool_node = types.ModuleType("langgraph.prebuilt.tool_node")


class ToolCallRequest:
    def __init__(self, tool_call: dict):
        self.tool_call = tool_call


langgraph_prebuilt_tool_node.ToolCallRequest = ToolCallRequest
langgraph_prebuilt.tool_node = langgraph_prebuilt_tool_node
sys.modules.setdefault("langgraph.prebuilt", langgraph_prebuilt)
sys.modules.setdefault("langgraph.prebuilt.tool_node", langgraph_prebuilt_tool_node)

langgraph_types = types.ModuleType("langgraph.types")


class Command:
    def __init__(self, update: dict | None = None, goto: str | None = None):
        self.update = update or {}
        self.goto = goto


langgraph_types.Command = Command
sys.modules.setdefault("langgraph.types", langgraph_types)

# ---------------------------------------------------------------------------
# Mock deerflow.agents.genui_persistence (lazy import in process_interaction)
# ---------------------------------------------------------------------------
deerflow_agents = types.ModuleType("deerflow.agents")
deerflow_agents_genui_persistence = types.ModuleType("deerflow.agents.genui_persistence")


def clear_blocks_by_callback_id(thread_id: str, callback_id: str) -> int:
    return 0


deerflow_agents_genui_persistence.clear_blocks_by_callback_id = clear_blocks_by_callback_id
deerflow_agents.genui_persistence = deerflow_agents_genui_persistence
sys.modules["deerflow.agents"] = deerflow_agents
sys.modules["deerflow.agents.genui_persistence"] = deerflow_agents_genui_persistence


def _load_module(module_name: str, relative_path: str):
    path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


genui_middleware = _load_module(
    "test_genui_middleware_module",
    "packages/harness/deerflow/agents/middlewares/genui_middleware.py",
)
InteractionStore = genui_middleware.InteractionStore
process_interaction = genui_middleware.process_interaction


def test_interaction_store_scopes_same_callback_id_by_thread() -> None:
    store = InteractionStore()

    store.register("daily-report-scope", "thread-a", "checkpoint-a")
    store.register("daily-report-scope", "thread-b", "checkpoint-b")

    record_a = store.get("thread-a", "daily-report-scope")
    record_b = store.get("thread-b", "daily-report-scope")

    assert record_a is not None
    assert record_b is not None
    assert record_a.checkpoint_id == "checkpoint-a"
    assert record_b.checkpoint_id == "checkpoint-b"


def test_process_interaction_uses_thread_scoped_callback_lookup(monkeypatch) -> None:
    store = InteractionStore()
    store.register("daily-report-scope", "thread-a", "checkpoint-a")
    store.register("daily-report-scope", "thread-b", "checkpoint-b")
    monkeypatch.setattr(genui_middleware, "_interaction_store", store)

    message = process_interaction(
        "thread-b",
        "daily-report-scope",
        {"report_date": "2026-05-15"},
    )

    assert message is not None
    parsed = json.loads(message.content)
    assert parsed["callback_id"] == "daily-report-scope"
    assert parsed["payload"]["report_date"] == "2026-05-15"

    record_a = store.get("thread-a", "daily-report-scope")
    record_b = store.get("thread-b", "daily-report-scope")
    assert record_a is not None and record_a.submitted is False
    assert record_b is not None and record_b.submitted is True
