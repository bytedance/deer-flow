"""Regression: tool assembly runs off the event loop (issue #5172).

``get_available_tools()`` may block on MCP cache initialization while it runs
on async agent-assembly paths. The offload dispatches the (unchanged,
synchronous) assembly to a worker thread via ``asyncio.to_thread`` at the
async entry points: ``task_tool``, ``SubagentBatchService._execute_item``,
and the Gateway run worker's agent construction (``run_agent`` ->
``agent_factory`` -> lead-agent assembly).

Under the strict Blockbuster context (this directory's conftest), any
blocking IO reached from ``deerflow.*`` while on the event loop raises
``BlockingError``. ``get_available_tools`` is injected here as a **blocking
probe** (real file IO): what must be pinned is that the assembly call never
executes on the event loop, not that today's assembly happens to be cheap —
a slow or hung stdio MCP server turns the same call into a full-loop stall.
If an entry point is flattened back to a plain call, the main test fails;
the meta-check below proves the probe has teeth by calling it directly on
the loop.
"""

from __future__ import annotations

import importlib
import json
import threading
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import ToolMessage

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.worker import RunContext, run_agent
from deerflow.subagents.config import SubagentConfig

# importlib.import_module binds the real module: the package attribute
# ``deerflow.tools.builtins.task_tool`` is shadowed by the StructuredTool.
task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")
batch_service_module = importlib.import_module("deerflow.subagents.batch_service")

pytestmark = pytest.mark.asyncio


class _FakeSubagentStatus(Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    RUNNING = "running"

    @property
    def is_terminal(self) -> bool:
        return self is not _FakeSubagentStatus.RUNNING


def _blocking_probe_tools(probe_file: Path, observed_threads: list | None = None):
    """A ``get_available_tools`` replacement performing real blocking file IO."""

    def get_tools(**_kwargs):
        # Real filesystem IO: trips the strict gate when it runs on the loop.
        body = probe_file.read_text(encoding="utf-8")
        if observed_threads is not None:
            observed_threads.append(threading.current_thread())
        return [body]

    return get_tools


def _completed_result() -> SimpleNamespace:
    return SimpleNamespace(
        status=_FakeSubagentStatus.COMPLETED,
        ai_messages=[],
        result="done",
        error=None,
        stop_reason=None,
        token_usage_records=[],
        usage_reported=False,
        tool_receipts=None,
        bash_executions=None,
    )


class _DummyExecutor:
    def __init__(self, **_kwargs):
        pass

    def execute_async(self, _prompt, task_id=None):
        return task_id or "generated-task-id"


async def test_task_tool_assembles_off_loop(monkeypatch, tmp_path):
    """task_tool dispatches get_available_tools to a worker thread."""
    (tmp_path / "probe.txt").write_text("probe body", encoding="utf-8")
    observed_threads: list = []
    monkeypatch.setattr(
        "deerflow.tools.get_available_tools",
        _blocking_probe_tools(tmp_path / "probe.txt", observed_threads),
    )
    monkeypatch.setattr(task_tool_module, "SubagentStatus", _FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", _DummyExecutor)
    monkeypatch.setattr(
        task_tool_module,
        "get_subagent_config",
        lambda _name: SubagentConfig(
            name="general-purpose",
            description="General helper",
            system_prompt="Base system prompt",
            max_turns=50,
            timeout_seconds=10,
        ),
    )
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda **_kwargs: ["general-purpose"])
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _task_id: _completed_result())
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)

    workspace = tmp_path / "user-data" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    runtime = SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": str(workspace),
                "uploads_path": str(tmp_path / "user-data" / "uploads"),
                "outputs_path": str(tmp_path / "user-data" / "outputs"),
            },
        },
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "ark-model", "trace_id": "trace-1"}},
    )

    tool = task_tool_module.task_tool
    invoke = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
    assert invoke is not None
    command = await invoke(
        runtime=runtime,
        description="test",
        prompt="p",
        subagent_type="general-purpose",
        tool_call_id="tc-offloop",
    )

    messages = command.update["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], ToolMessage)
    assert observed_threads, "tool assembly must be invoked"
    assert all(thread is not threading.main_thread() for thread in observed_threads)


async def test_batch_item_assembles_off_loop(monkeypatch, tmp_path):
    """SubagentBatchService._execute_item dispatches assembly to a worker thread."""
    (tmp_path / "probe.txt").write_text("probe body", encoding="utf-8")
    observed_threads: list = []
    monkeypatch.setattr(
        "deerflow.tools.get_available_tools",
        _blocking_probe_tools(tmp_path / "probe.txt", observed_threads),
    )
    monkeypatch.setattr(batch_service_module, "SubagentStatus", _FakeSubagentStatus)
    monkeypatch.setattr(batch_service_module, "SubagentExecutor", _DummyExecutor)
    monkeypatch.setattr(
        batch_service_module,
        "get_background_task_result",
        lambda _execution_id: _completed_result(),
    )
    monkeypatch.setattr(
        batch_service_module,
        "request_cancel_background_task",
        lambda _execution_id: None,
    )
    monkeypatch.setattr(
        batch_service_module,
        "resolve_subagent_model_name",
        lambda *_args, **_kwargs: "test-model",
    )

    service = batch_service_module.SubagentBatchService(
        repository=SimpleNamespace(
            mark_item_running=None,
            renew_item_lease=None,
            finalize_item=None,
        ),
        config=SimpleNamespace(
            lease_seconds=10.0,
            poll_interval_seconds=1.0,
            max_result_chars=1000,
            result_preview_max_chars=200,
        ),
        runtime_config=SimpleNamespace(),
        app_config=SimpleNamespace(),
        execution_capacity=None,
    )

    finalize_calls: list[dict] = []

    async def _finalize_item(item_id, **kwargs):
        finalize_calls.append({"item_id": item_id, **kwargs})

    service._repository = SimpleNamespace(finalize_item=_finalize_item)

    item = {
        "id": "item-1",
        "item_key": "key-1",
        "prompt": "do the thing",
        "batch": {
            "id": "batch-1",
            "thread_id": "thread-1",
            "user_id": "user-1",
            "run_id": None,
            "execution_spec": {
                "subagent_config": {
                    "name": "general-purpose",
                    "description": "General helper",
                    "system_prompt": "Base system prompt",
                    "model": "test-model",
                    "max_turns": 5,
                    "timeout_seconds": 10,
                },
            },
        },
    }

    await service._execute_item(item)

    assert len(finalize_calls) == 1
    assert finalize_calls[0]["item_id"] == "item-1"
    assert finalize_calls[0]["succeeded"] is True
    assert observed_threads, "tool assembly must be invoked"
    assert all(thread is not threading.main_thread() for thread in observed_threads)


async def test_run_agent_assembles_off_loop(monkeypatch, tmp_path):
    """run_agent dispatches agent_factory (lead-agent assembly) to a worker thread."""
    cfg = tmp_path / "extensions_config.json"
    cfg.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    observed_threads: list = []

    class _DummyStreamAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {"messages": []}

    def _factory(*, config):
        observed_threads.append(threading.current_thread())
        # Real production blocking read (executed inside a deerflow.* frame):
        # trips the strict gate when the factory runs on the loop.
        ExtensionsConfig.from_file()
        return _DummyStreamAgent()

    run_manager = RunManager()
    record = await run_manager.create("thread-1")

    await run_agent(
        SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock()),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=MemoryRunEventStore()),
        agent_factory=_factory,
        graph_input={},
        config={},
    )

    assert observed_threads, "agent assembly must be invoked"
    assert all(thread is not threading.main_thread() for thread in observed_threads)


async def test_extensions_config_read_trips_the_gate(monkeypatch, tmp_path):
    """Meta-check: reading the extensions config from ``deerflow.*`` code on
    the event loop must raise BlockingError — the exact syscall class issue
    #5172 is about — so the anchors above cannot go vacuously green. (The
    probe's own ``read_text`` trips through the same gate, proven here with
    the production reader instead of a test-file stack, which the
    ``scanned_modules`` filter would ignore.)"""
    from blockbuster import BlockingError

    cfg = tmp_path / "extensions_config.json"
    cfg.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    with pytest.raises(BlockingError):
        ExtensionsConfig.from_file()
