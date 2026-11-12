"""End-to-end coverage for the task tool -> SubagentExecutor -> parent SSE bridge.

fancyboi999's 2026-07-17 review ask on #4150: exercise the *real*
``SubagentExecutor`` end to end instead of a ``DummyExecutor`` or a hand-built
one-node graph, and assert that a subagent ``tool_output_chunk`` actually
reaches the parent stream.

No live model is used.  Exactly two seams are substituted:

* ``executor.create_chat_model`` -> a scripted ``GenericFakeChatModel`` (a
  provider is unavailable in CI);
* ``deerflow.tools.get_available_tools`` -> one async echo tool (the real
  registry needs sandbox/MCP infrastructure).

Everything else is production code:

* the real ``task_tool`` coroutine and its polling/forwarding loop;
* the real ``SubagentExecutor``: ``execute_async`` on the persistent isolated
  subagent loop, ``_create_agent`` assembling the actual runtime middleware
  chain (``build_subagent_runtime_middlewares``), and ``_aexecute``'s
  ``agent.astream(stream_mode=["values", "custom"])`` loop that accumulates
  custom chunks into the shared ``SubagentResult``;
* the real ``ToolStreamingMiddleware``, installed by the config-driven builder
  because ``tool_streaming.enabled`` is true;
* a real compiled ``create_agent`` subagent graph, and a real parent LangGraph
  whose ``stream_mode="custom"`` channel is the SSE source.

``backend/tests/conftest.py`` injects a MagicMock for
``deerflow.subagents.executor`` to break a circular import.  The fixture below
temporarily swaps in the real module for the duration of the test, re-imports
``task_tool`` so its module-level executor bindings are real, and restores the
process state afterwards.
"""

from __future__ import annotations

import asyncio
import importlib
import sys

import pytest

# Import the real modules at collection time, while conftest.py's
# cycle-breaking executor mock is still installed.  By the time the fixture
# below removes that mock these modules -- and the ``deerflow.agents`` package
# whose import closes the cycle -- are already cached, so importing the real
# executor cannot re-enter itself.
import deerflow.agents.middlewares.tool_error_handling_middleware  # noqa: F401
import deerflow.agents.middlewares.tool_streaming_middleware  # noqa: F401
import deerflow.agents.thread_state  # noqa: F401
import deerflow.sandbox.lease  # noqa: F401
import deerflow.tools.builtins.tool_search  # noqa: F401

_MISSING = object()
_PACKAGE_GLOBALS = ("SubagentExecutor", "SubagentResult", "executor")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def real_executor_modules():
    """Expose the real executor + a task_tool bound to it, then restore state."""
    subagents_pkg = sys.modules["deerflow.subagents"]
    builtins_pkg = sys.modules["deerflow.tools.builtins"]
    original_executor = sys.modules.get("deerflow.subagents.executor")
    original_task_tool = sys.modules.get("deerflow.tools.builtins.task_tool")
    original_globals = {name: subagents_pkg.__dict__.get(name, _MISSING) for name in _PACKAGE_GLOBALS}
    # ``builtins/__init__.py`` re-exports the *tool object* under this name;
    # importing the submodule overwrites it with the module object.
    original_builtin_attr = builtins_pkg.__dict__.get("task_tool", _MISSING)

    sys.modules.pop("deerflow.subagents.executor", None)
    for name in _PACKAGE_GLOBALS:
        subagents_pkg.__dict__.pop(name, None)
    executor_module = importlib.import_module("deerflow.subagents.executor")

    sys.modules.pop("deerflow.tools.builtins.task_tool", None)
    task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")

    try:
        yield executor_module, task_tool_module
    finally:
        sys.modules.pop("deerflow.tools.builtins.task_tool", None)
        if original_task_tool is not None:
            sys.modules["deerflow.tools.builtins.task_tool"] = original_task_tool
        if original_builtin_attr is not _MISSING:
            builtins_pkg.task_tool = original_builtin_attr
        sys.modules.pop("deerflow.subagents.executor", None)
        if original_executor is not None:
            sys.modules["deerflow.subagents.executor"] = original_executor
        for name, value in original_globals.items():
            if value is _MISSING:
                subagents_pkg.__dict__.pop(name, None)
            else:
                setattr(subagents_pkg, name, value)


@pytest.mark.anyio
async def test_task_tool_forwards_real_subagent_tool_output_chunk_to_parent_stream(real_executor_modules, monkeypatch):
    """A ``tool_output_chunk`` from a real subagent tool call reaches the parent.

    Drives ``task_tool`` -> real ``SubagentExecutor`` (background isolated loop)
    -> real subagent graph -> back up to the parent graph's custom stream.
    """
    from types import SimpleNamespace
    from typing import TypedDict

    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.tools import tool
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command

    from deerflow.config.app_config import AppConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.config.tool_streaming_config import ToolStreamingConfig
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import SubagentStatus

    executor_module, task_tool_module = real_executor_modules

    # The production class must be the one under test, not conftest's mock.
    assert task_tool_module.SubagentExecutor is executor_module.SubagentExecutor

    @tool
    async def echo_tool(text: str) -> str:
        """Echo the text back."""
        return f"echo:{text}"

    class _ScriptedModel(GenericFakeChatModel):
        """GenericFakeChatModel requires bind_tools to accept the tool schema."""

        def bind_tools(self, tools, **kwargs):
            return self

    responses = [
        AIMessage(content="", tool_calls=[{"name": "echo_tool", "args": {"text": "hello"}, "id": "child-echo"}]),
        AIMessage(content="child done"),
    ]

    # Seam 1: the LLM provider.  Everything above it (middleware assembly,
    # ToolNode, custom-event emission) stays production code.
    monkeypatch.setattr(executor_module, "create_chat_model", lambda **_kwargs: _ScriptedModel(messages=iter(list(responses))))

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
        tool_streaming=ToolStreamingConfig(enabled=True),
    )
    subagent_config = SubagentConfig(
        name="stream-test-agent",
        description="Streaming integration agent",
        system_prompt="You are a test agent.",
        # Explicitly disable skill loading: keeps the run hermetic (no storage I/O).
        skills=[],
        model="test-model",
        max_turns=10,
        timeout_seconds=3600,
    )

    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _name, **_kwargs: subagent_config)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda **_kwargs: ["stream-test-agent"])
    # Seam 2: the tool registry (real assembly needs sandbox/MCP infrastructure).
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [echo_tool])

    # Keep the poll loop fast without turning it into a busy loop.  Only the
    # task tool's fixed 5s interval is shortened; other awaits are untouched.
    # ``max_poll_count`` is derived from ``timeout_seconds`` assuming 5s polls,
    # so a large timeout keeps the same wall-clock headroom (~36s here) instead
    # of shrinking the safety net to a flaky two seconds.
    real_sleep = asyncio.sleep

    async def _fast_sleep(seconds):
        await real_sleep(0.05 if seconds == 5 else seconds)

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    runtime = SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": "/tmp/workspace",
                "uploads_path": "/tmp/uploads",
                "outputs_path": "/tmp/outputs",
            },
        },
        context={"thread_id": "parent-thread", "app_config": app_config},
        config={"metadata": {"model_name": "test-model", "trace_id": "trace-1"}},
    )

    captured: dict[str, object] = {}

    class _ParentState(TypedDict):
        done: bool

    async def run_task(_state):
        captured["result"] = await task_tool_module.task_tool.coroutine(
            runtime=runtime,
            description="delegate echo",
            prompt="call the echo tool",
            subagent_type="stream-test-agent",
            tool_call_id="parent-task-call",
        )
        return {"done": True}

    parent = StateGraph(_ParentState)
    parent.add_node("run_task", run_task)
    parent.add_edge(START, "run_task")
    parent.add_edge("run_task", END)

    # The parent graph's custom channel is exactly what the run worker
    # serialises to SSE.
    events = [event async for event in parent.compile().astream({"done": False}, stream_mode="custom")]
    types = [event.get("type") for event in events]

    chunks = [event for event in events if event.get("type") == "tool_output_chunk"]
    assert [chunk["tool_call_id"] for chunk in chunks] == ["child-echo", "child-echo"], f"expected the subagent's start+final chunks on the parent stream, got {chunks!r}"
    assert chunks[0]["tool_name"] == "echo_tool"
    assert chunks[0]["is_partial"] is True and chunks[0]["is_final"] is False
    assert chunks[1]["is_partial"] is False and chunks[1]["is_final"] is True
    assert chunks[1]["chunk"] == "echo:hello"

    # Ordering: the chunks are forwarded before the terminal lifecycle event,
    # i.e. the atomic drain sees them alongside the terminal status.
    assert types[0] == "task_started"
    assert "task_completed" in types
    assert max(index for index, kind in enumerate(types) if kind == "tool_output_chunk") < types.index("task_completed")

    # The canonical result still flows back as the task tool's ToolMessage.
    result = captured["result"]
    assert isinstance(result, Command)
    message = result.update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert "Task Succeeded" in message.content
    assert "child done" in message.content
    assert SubagentStatus.COMPLETED.value in str(message.additional_kwargs)
