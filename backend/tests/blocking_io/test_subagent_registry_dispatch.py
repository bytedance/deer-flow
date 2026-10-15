"""Regression: subagent registry reads must stay off the async tool loop.

Both ordinary and durable-batch delegation resolve user-scoped Custom Agents
through a synchronous file or SQL store.  The tool coroutines must offload the
complete registry lookup before they inspect the result.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.subagents.config import SubagentConfig

batch_tool_module = importlib.import_module("deerflow.tools.builtins.batch_task_tool")
task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")

pytestmark = pytest.mark.asyncio


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(
        state={},
        context={"thread_id": "thread-1", "user_id": "user-1"},
        config={"metadata": {}, "configurable": {}},
    )


def _blocking_registry_probes(probe_file: Path):
    def available(**_kwargs) -> list[str]:
        probe_file.read_text(encoding="utf-8")
        return ["user-agent"]

    def config(_name: str, **_kwargs) -> SubagentConfig:
        probe_file.read_text(encoding="utf-8")
        return SubagentConfig(name="user-agent", description="User agent")

    return available, config


async def test_task_registry_lookup_is_offloaded(monkeypatch, tmp_path: Path) -> None:
    probe_file = tmp_path / "agent-store-probe.txt"
    await task_tool_module.asyncio.to_thread(probe_file.write_text, "agent", encoding="utf-8")
    available, config = _blocking_registry_probes(probe_file)

    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", available)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", config)
    result = await task_tool_module.task_tool.coroutine(
        runtime=_runtime(),
        description="probe",
        prompt="probe",
        subagent_type="missing-agent",
        tool_call_id="task-registry-probe",
    )

    assert result.update["messages"][0].additional_kwargs["subagent_status"] == "failed"


async def test_batch_registry_lookup_is_offloaded(monkeypatch, tmp_path: Path) -> None:
    probe_file = tmp_path / "agent-store-probe.txt"
    await task_tool_module.asyncio.to_thread(probe_file.write_text, "agent", encoding="utf-8")
    available, config = _blocking_registry_probes(probe_file)

    monkeypatch.setattr(batch_tool_module, "_batch_submitter", lambda: object())
    monkeypatch.setattr(batch_tool_module, "get_available_subagent_names", available)
    monkeypatch.setattr(batch_tool_module, "get_subagent_config", config)

    result = await batch_tool_module.batch_task.coroutine(
        runtime=_runtime(),
        title="probe",
        items=[batch_tool_module.BatchTaskItem(key="one", prompt="probe")],
        subagent_type="missing-agent",
        tool_call_id="batch-registry-probe",
        max_live_items=None,
        max_running_items=None,
    )

    assert result.update["messages"][0].status == "error"
