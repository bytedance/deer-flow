"""Regression: the acceptance checklist must not block the event loop.

RFC #4651 PR4 runs deterministic acceptance checks (``file:`` leaves read
through the sandbox) on the ``task`` tool's completed branch — an async path
on the LangGraph event loop. The whole check is offloaded with
``asyncio.to_thread`` in ``task_tool``; this anchor locks that offload.

Under the strict Blockbuster context (this directory's conftest), any blocking
IO reached from ``deerflow.*`` while on the event loop raises
``BlockingError``.

The content reader is injected here as a **blocking probe**: it does real
file IO against the real local filesystem. What must be pinned is that the
reader call never executes on the event loop, not that today's sandbox read
happens to be cheap — a remote sandbox provider turns the same call into
network IO. If the offload is removed, the main test fails; the meta-check
below proves the probe has teeth by calling the checker directly on the loop.
"""

from __future__ import annotations

import importlib
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from deerflow.subagents.config import SubagentConfig

# importlib.import_module binds the real module: the package attribute
# ``deerflow.tools.builtins.task_tool`` is shadowed by the StructuredTool.
task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")

pytestmark = pytest.mark.asyncio


class _FakeSubagentStatus(Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


def _blocking_probe_reader(probe_file: Path):
    """A content reader that performs real blocking file IO."""

    def read(_runtime, path: str) -> str:
        # Real filesystem IO: trips the strict gate when it runs on the loop.
        return probe_file.read_text(encoding="utf-8")

    return read


def _runtime(tmp_path: Path) -> SimpleNamespace:
    workspace = tmp_path / "user-data" / "workspace"
    outputs = tmp_path / "user-data" / "outputs"
    workspace.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": str(workspace),
                "uploads_path": str(tmp_path / "user-data" / "uploads"),
                "outputs_path": str(outputs),
            },
        },
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "ark-model", "trace_id": "trace-1"}},
    )


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


def _patch_task_tool_boundary(monkeypatch, tmp_path: Path) -> None:
    """Mock only the external boundaries; the offload under guard stays real."""
    monkeypatch.setattr(
        "deerflow.sandbox.tools.read_current_file_content",
        _blocking_probe_reader(tmp_path / "probe.txt"),
    )

    class DummyExecutor:
        def __init__(self, **kwargs):
            pass

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", _FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
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
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _id: _completed_result())
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    # Pre-existing blocking call (managed-subagents registry resolves the
    # config base dir via os.getcwd on the loop) unrelated to this anchor —
    # scoped out so the test stays pinned to the checklist offload.
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda **kwargs: ["general-purpose"])

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])


async def test_acceptance_checklist_file_leaf_is_offloaded(monkeypatch, tmp_path):
    """The completed branch runs file-leaf stat+read off the event loop."""
    (tmp_path / "probe.txt").write_text("probe body", encoding="utf-8")
    # The size probe stats the real host path (local sandbox), so the
    # criterion's target must exist on disk.
    (tmp_path / "user-data" / "outputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "user-data" / "outputs" / "report.md").write_text("real body", encoding="utf-8")
    _patch_task_tool_boundary(monkeypatch, tmp_path)

    tool = task_tool_module.task_tool
    invoke = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
    assert invoke is not None
    command = await invoke(
        runtime=_runtime(tmp_path),
        description="test",
        prompt="p",
        subagent_type="general-purpose",
        tool_call_id="tc-blocking-io",
        acceptance_criteria=["file:../outputs/report.md exists"],
    )

    messages = command.update["messages"]
    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, ToolMessage)
    verdict = message.additional_kwargs["subagent_acceptance_verdict"]
    assert verdict["leaves"][0]["checked"] is True
    assert verdict["leaves"][0]["holds"] is True


async def test_blocking_probe_reader_actually_trips_the_gate(monkeypatch, tmp_path):
    """Meta-check: the same read on the event loop must raise BlockingError,
    so the anchor above cannot go vacuously green. (The size probe is
    injected here so the read is reached: the real prober's broad failure
    isolation swallows a BlockingError into an UNVERIFIED leaf — by design,
    since Blockbuster intercepts the syscall before it can block.)"""
    from blockbuster import BlockingError

    from deerflow.subagents.acceptance_checks import check_acceptance_criteria

    (tmp_path / "probe.txt").write_text("probe body", encoding="utf-8")
    thread_data = {
        "workspace_path": str(tmp_path / "user-data" / "workspace"),
        "outputs_path": str(tmp_path / "user-data" / "outputs"),
    }

    with pytest.raises(BlockingError):
        check_acceptance_criteria(
            ["file:../outputs/report.md exists"],
            runtime=None,
            thread_data=thread_data,
            content_reader=_blocking_probe_reader(tmp_path / "probe.txt"),
            size_prober=lambda _rt, _p, _td: 10,
        )
