"""End-to-end user-isolation regression coverage for ``present_files``."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from _agent_e2e_helpers import FakeToolCallingModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.factory import create_deerflow_agent
from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.config.paths import Paths
from deerflow.tools.builtins.present_file_tool import present_file_tool

present_file_tool_module = importlib.import_module("deerflow.tools.builtins.present_file_tool")


def _build_present_files_graph(tmp_path: Path):
    model = FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "present_files",
                        "args": {"filepaths": ["/mnt/user-data/outputs/report.md"]},
                        "id": "call_present_file",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Presented the report."),
        ]
    )
    return create_deerflow_agent(
        model,
        tools=[present_file_tool],
        middleware=[ThreadDataMiddleware(base_dir=str(tmp_path), lazy_init=True)],
        state_schema=ThreadState,
        system_prompt="Present the report file.",
    )


@pytest.mark.no_auto_user
def test_present_files_uses_runtime_user_through_real_agent_graph(tmp_path, monkeypatch):
    """The real middleware and ToolNode must keep one user bucket without a ContextVar."""
    paths = Paths(tmp_path)
    user_id = "runtime-user"
    thread_id = "thread-present-e2e"
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    outputs_dir.mkdir(parents=True)
    (outputs_dir / "report.md").write_text("report body")

    monkeypatch.setattr(present_file_tool_module, "get_paths", lambda: paths)

    runtime = Runtime(context={"thread_id": thread_id, "user_id": user_id}, store=None)
    config = {
        "configurable": {"thread_id": thread_id, "__pregel_runtime": runtime},
        "recursion_limit": 20,
    }
    final_state = _build_present_files_graph(tmp_path).invoke(
        {"messages": [HumanMessage(content="Present the report")]},
        config=config,
    )

    assert final_state["thread_data"]["outputs_path"] == str(outputs_dir)
    tool_messages = [message for message in final_state["messages"] if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].content == "Successfully presented files"
    assert final_state["artifacts"] == ["/mnt/user-data/outputs/report.md"]
    assert not paths.sandbox_outputs_dir(thread_id, user_id="default").exists()
