"""Offline contract tests for the read-only run-status tool (issue #7062)."""

import asyncio
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.tools.builtins.inspect_run_status_tool import build_inspect_run_status_tool, snapshot_run_status


def test_snapshot_counts_only_the_current_run_and_uses_reported_usage():
    old = HumanMessage(id="old", content="private old request")
    current = HumanMessage(id="current", content="private current request")
    call = AIMessage(
        id="call",
        content="",
        tool_calls=[{"name": "bash", "args": {"command": "echo secret"}, "id": "c1"}],
        usage_metadata={"input_tokens": 60, "output_tokens": 10, "total_tokens": 70},
    )
    result = ToolMessage(id="result", content="private output", tool_call_id="c1")
    final = AIMessage(id="final", content="private answer", usage_metadata={"input_tokens": 80, "output_tokens": 20, "total_tokens": 100})
    state = {
        "messages": [old, current, call, result, final],
        "summary_text": "private summary",
        "todos": [{"content": "private todo", "status": "pending"}, {"content": "another", "status": "in_progress"}, {"content": "done", "status": "completed"}],
    }
    context = {CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset({"old"})}

    snapshot = snapshot_run_status(state, context, context_window=200)

    assert snapshot["scope"] == "current_run_visible"
    assert snapshot["token_usage"] == {"input": 140, "output": 30, "total": 170}
    assert snapshot["message_count"] == 4
    assert snapshot["tool_calls_this_run"] == 1
    assert snapshot["context_fill"] == {"used_input_tokens": 80, "limit_tokens": 200, "fraction": 0.4, "basis": "last_reported_model_input"}
    assert snapshot["has_summary"] is True
    assert snapshot["todos"] == {"pending": 1, "in_progress": 1}
    serialized = json.dumps(snapshot)
    assert "private" not in serialized
    assert "echo secret" not in serialized


def test_snapshot_marks_missing_boundary_and_usage_as_unknown():
    state = {"messages": [AIMessage(id="a", content="hello"), AIMessage(id="b", content="done")], "todos": None}

    snapshot = snapshot_run_status(state, {}, context_window=None)

    assert snapshot["scope"] == "visible_state"
    assert snapshot["token_usage"] == {"input": 0, "output": 0, "total": 0}
    assert snapshot["tool_calls_this_run"] is None
    assert snapshot["usage_missing_messages"] == 2
    assert snapshot["context_fill"] is None
    assert snapshot["has_summary"] is False
    assert snapshot["todos"] == {"pending": 0, "in_progress": 0}


def test_compaction_that_removes_run_boundary_reports_visible_state():
    state = {"messages": [HumanMessage(id="new", content="visible after compaction")]}
    context = {CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset({"removed-old-message"})}

    snapshot = snapshot_run_status(state, context, context_window=100)

    assert snapshot["scope"] == "visible_state"
    assert snapshot["message_count"] == 1
    assert snapshot["tool_calls_this_run"] is None


def test_later_unreported_model_response_makes_context_fill_unknown():
    messages = [
        AIMessage(id="reported", content="", usage_metadata={"input_tokens": 60, "output_tokens": 10, "total_tokens": 70}),
        AIMessage(id="unreported", content="done"),
    ]
    snapshot = snapshot_run_status({"messages": messages}, {CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()}, context_window=100)
    assert snapshot["context_fill"] is None
    assert snapshot["usage_missing_messages"] == 1


def test_subagent_attribution_does_not_masquerade_as_context_fill():
    dispatch = AIMessage(
        content="",
        tool_calls=[{"name": "task", "args": {"prompt": "work"}, "id": "task-1"}],
        usage_metadata={"input_tokens": 5000, "output_tokens": 100, "total_tokens": 5100},
    )
    snapshot = snapshot_run_status({"messages": [dispatch]}, {}, context_window=4096)

    assert snapshot["token_usage"]["total"] == 5100
    assert snapshot["context_fill"] is None


def test_bound_tool_has_no_model_supplied_arguments():
    tool = build_inspect_run_status_tool(context_window=4096)

    assert tool.name == "inspect_run_status"
    assert tool.args == {}


def test_tool_reads_live_graph_state_without_exposing_message_content():
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    from deerflow.agents.thread_state import ThreadState

    class FakeModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    model = FakeModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[{"name": "inspect_run_status", "args": {}, "id": "status-1"}], usage_metadata={"input_tokens": 25, "output_tokens": 5, "total_tokens": 30}),
                AIMessage(content="done"),
            ]
        )
    )
    graph = create_agent(model=model, tools=[build_inspect_run_status_tool(context_window=100)], state_schema=ThreadState)
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="secret request")]},
            {"configurable": {"thread_id": "status-test"}},
            context={CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()},
        )
    )

    tool_output = next(message.content for message in result["messages"] if isinstance(message, ToolMessage))
    snapshot = json.loads(tool_output)
    assert snapshot["tool_calls_this_run"] == 1
    assert snapshot["scope"] == "current_run_visible"
    assert snapshot["token_usage"] == {"input": 25, "output": 5, "total": 30}
    assert "secret request" not in tool_output


def test_available_tools_registers_introspection_with_model_context_window():
    from deerflow.config.app_config import AppConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.tools import get_available_tools

    config = AppConfig(
        models=[ModelConfig(name="status-model", display_name="status-model", description=None, use="langchain_openai:ChatOpenAI", model="status-model", context_window=8192)],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )
    tools = get_available_tools(include_mcp=False, model_name="status-model", app_config=config)

    assert sum(tool.name == "inspect_run_status" for tool in tools) == 1
