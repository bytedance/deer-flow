"""Subagents expose the same task lifecycle contract as lead runs."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from deerflow_extension_api import EXTENSION_TASK_STORE_KEY, ExtensionData, TaskInfo, TaskOutcome
from langchain_core.messages import AIMessage

from deerflow.extensions import reset_loaded_extensions, set_loaded_extensions
from deerflow.extensions.registry import ExtensionRegistry

_MOCKED_MODULE_NAMES = (
    "deerflow.agents",
    "deerflow.agents.thread_state",
    "deerflow.agents.middlewares",
    "deerflow.agents.middlewares.thread_data_middleware",
    "deerflow.sandbox",
    "deerflow.sandbox.middleware",
    "deerflow.sandbox.security",
    "deerflow.models",
    "deerflow.skills.storage",
)


@pytest.fixture
def env():
    """Import the real executor behind conftest's cycle-breaking mock."""
    reset_loaded_extensions()
    original_modules = {name: sys.modules.get(name) for name in _MOCKED_MODULE_NAMES}
    original_executor = sys.modules.get("deerflow.subagents.executor")
    subagents_pkg = sys.modules.get("deerflow.subagents")
    missing = object()
    original_executor_attr = getattr(subagents_pkg, "executor", missing) if subagents_pkg is not None else missing

    sys.modules.pop("deerflow.subagents.executor", None)
    if subagents_pkg is not None and hasattr(subagents_pkg, "executor"):
        delattr(subagents_pkg, "executor")

    try:
        for name in _MOCKED_MODULE_NAMES:
            sys.modules[name] = MagicMock()
        storage_module = ModuleType("deerflow.skills.storage")
        storage_module.get_or_new_skill_storage = lambda **kwargs: SimpleNamespace(load_skills=lambda *, enabled_only: [])
        storage_module.get_or_new_user_skill_storage = lambda user_id, **kwargs: SimpleNamespace(load_skills=lambda *, enabled_only: [])
        sys.modules["deerflow.skills.storage"] = storage_module

        from deerflow.subagents.config import SubagentConfig
        from deerflow.subagents.executor import (
            SubagentExecutor,
            SubagentResult,
            SubagentStatus,
        )

        sys.modules["deerflow.subagents.executor"].get_app_config = lambda: SimpleNamespace(
            tool_search=SimpleNamespace(enabled=False),
            authorization=SimpleNamespace(enabled=False),
        )
        yield SimpleNamespace(
            SubagentConfig=SubagentConfig,
            SubagentExecutor=SubagentExecutor,
            SubagentResult=SubagentResult,
            SubagentStatus=SubagentStatus,
        )
    finally:
        reset_loaded_extensions()
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        if original_executor is None:
            sys.modules.pop("deerflow.subagents.executor", None)
        else:
            sys.modules["deerflow.subagents.executor"] = original_executor
        subagents_pkg = sys.modules.get("deerflow.subagents")
        if subagents_pkg is not None:
            if original_executor_attr is missing:
                if hasattr(subagents_pkg, "executor"):
                    delattr(subagents_pkg, "executor")
            else:
                setattr(subagents_pkg, "executor", original_executor_attr)


class _Recorder:
    def __init__(self) -> None:
        self.starts: list[TaskInfo] = []
        self.stops: list[tuple[TaskInfo, TaskOutcome]] = []
        self.stores: list[ExtensionData] = []

    async def on_task_start(self, app_store, task_store, info):
        self.starts.append(info)
        self.stores.append(task_store)

    async def on_task_stop(self, app_store, task_store, info, outcome):
        self.stops.append((info, outcome))
        self.stores.append(task_store)


def _loaded(recorder):
    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        registry.task_lifecycle(recorder)
    return registry.build()


def _executor(env, **overrides):
    config = env.SubagentConfig(
        name="researcher",
        description="d",
        system_prompt="p",
        tools=[],
    )
    kwargs = {"run_id": "run-1", "thread_id": "thread-1"}
    kwargs.update(overrides)
    return env.SubagentExecutor(config=config, tools=[], **kwargs)


class _CompletingAgent:
    def __init__(self, seen: dict | None = None) -> None:
        self.seen = seen

    async def astream(self, *args, **kwargs):
        if self.seen is not None:
            self.seen["context"] = kwargs.get("context")
        yield {"messages": [AIMessage(content="done")]}


async def _noop_initial_state(self, task):
    return ({}, [], None)


@pytest.mark.asyncio
async def test_subagent_success_emits_shaped_start_and_completed_stop(monkeypatch, env):
    recorder = _Recorder()
    set_loaded_extensions(_loaded(recorder))
    executor = _executor(env)
    seen: dict = {}
    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _noop_initial_state)
    monkeypatch.setattr(
        env.SubagentExecutor,
        "_create_agent",
        lambda self, tools, **kwargs: _CompletingAgent(seen),
    )

    result = await executor._aexecute("do the thing")

    assert result.status is env.SubagentStatus.COMPLETED
    [info] = recorder.starts
    assert info == TaskInfo(
        task_id=result.task_id,
        run_id="run-1",
        thread_id="thread-1",
        kind="subagent",
        parent_task_id="run-1",
        agent_name="researcher",
    )
    assert recorder.stops == [(info, TaskOutcome.COMPLETED)]
    assert recorder.stores[0] is recorder.stores[1]
    assert seen["context"][EXTENSION_TASK_STORE_KEY] is recorder.stores[0]


@pytest.mark.asyncio
async def test_subagent_failure_and_cancellation_map_to_distinct_outcomes(monkeypatch, env):
    recorder = _Recorder()
    set_loaded_extensions(_loaded(recorder))
    executor = _executor(env)

    async def _fail_before_agent(self, task):
        raise RuntimeError("build failed")

    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _fail_before_agent)
    failed = await executor._aexecute("fail")
    assert failed.status is env.SubagentStatus.FAILED
    assert recorder.stops[-1][1] is TaskOutcome.FAILED

    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _noop_initial_state)
    monkeypatch.setattr(
        env.SubagentExecutor,
        "_create_agent",
        lambda self, tools, **kwargs: _CompletingAgent(),
    )
    holder = env.SubagentResult(
        task_id="cancel-me",
        trace_id="trace",
        status=env.SubagentStatus.RUNNING,
    )
    holder.cancel_event.set()
    cancelled = await executor._aexecute("cancel", holder)
    assert cancelled.status is env.SubagentStatus.CANCELLED
    assert recorder.stops[-1][1] is TaskOutcome.ABORTED
    assert recorder.stops[-1][0].task_id == "cancel-me"


@pytest.mark.asyncio
async def test_subagent_base_exception_still_emits_failed_stop(monkeypatch, env):
    recorder = _Recorder()
    set_loaded_extensions(_loaded(recorder))
    executor = _executor(env)

    async def _hard_stop(self, task):
        raise KeyboardInterrupt("host shutdown")

    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _hard_stop)
    with pytest.raises(KeyboardInterrupt):
        await executor._aexecute("stop")

    assert recorder.stops[0][1] is TaskOutcome.FAILED


@pytest.mark.asyncio
async def test_subagent_without_parent_run_skips_lifecycle_but_keeps_task_store(monkeypatch, env):
    recorder = _Recorder()
    set_loaded_extensions(_loaded(recorder))
    executor = _executor(env, run_id=None)
    seen: dict = {}
    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _noop_initial_state)
    monkeypatch.setattr(
        env.SubagentExecutor,
        "_create_agent",
        lambda self, tools, **kwargs: _CompletingAgent(seen),
    )

    result = await executor._aexecute("direct")

    assert recorder.starts == []
    assert recorder.stops == []
    assert seen["context"][EXTENSION_TASK_STORE_KEY].scope_id == result.task_id


@pytest.mark.asyncio
async def test_subagent_keeps_one_snapshot_across_build_context_and_hooks(monkeypatch, env):
    first = _Recorder()
    second = _Recorder()
    snapshot = _loaded(first)
    set_loaded_extensions(snapshot)
    executor = _executor(env)
    seen: dict = {}

    async def _switch_singleton(self, task):
        set_loaded_extensions(_loaded(second))
        return ({}, [], None)

    def _capture_agent(self, tools, *, deferred_setup=None, extensions=None):
        seen["extensions"] = extensions
        return _CompletingAgent(seen)

    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _switch_singleton)
    monkeypatch.setattr(env.SubagentExecutor, "_create_agent", _capture_agent)

    await executor._aexecute("snapshot")

    assert seen["extensions"] is snapshot
    assert len(first.starts) == len(first.stops) == 1
    assert second.starts == second.stops == []
    assert seen["context"][EXTENSION_TASK_STORE_KEY] is first.stores[0]
