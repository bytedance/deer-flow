"""Runtime task-store wiring required by contributed middleware."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from deerflow_extension_api import EXTENSION_TASK_STORE_KEY, ExtensionData
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.extensions import (
    EXTENSION_SNAPSHOT_CONTEXT_KEY,
    get_agent_build_extensions,
    reset_loaded_extensions,
    resolve_run_extensions,
    set_loaded_extensions,
)
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.worker import RunContext, _build_runtime_context, run_agent


def test_build_runtime_context_installs_the_extension_store():
    store = ExtensionData("task-1")

    context = _build_runtime_context("thread-1", "run-1", None, None, store)

    assert context[EXTENSION_TASK_STORE_KEY] is store


def test_build_runtime_context_omits_the_key_without_a_store():
    context = _build_runtime_context("thread-1", "run-1", None, None, None)

    assert EXTENSION_TASK_STORE_KEY not in context


def test_build_runtime_context_installs_the_run_extension_snapshot():
    loaded = ExtensionRegistry().build()

    context = _build_runtime_context("thread-1", "run-1", None, None, None, loaded)

    assert context[EXTENSION_SNAPSHOT_CONTEXT_KEY] is loaded


def test_build_runtime_context_omits_the_snapshot_key_without_extensions():
    context = _build_runtime_context("thread-1", "run-1", None, None, None, None)

    assert EXTENSION_SNAPSHOT_CONTEXT_KEY not in context


def test_build_runtime_context_never_keeps_a_caller_supplied_snapshot():
    """``runtime.context`` is caller-mergeable, so the run's own snapshot must
    win and a caller value must never survive when the run has none."""
    loaded = ExtensionRegistry().build()
    forged = ExtensionRegistry().build()

    overridden = _build_runtime_context("thread-1", "run-1", {EXTENSION_SNAPSHOT_CONTEXT_KEY: forged}, None, None, loaded)
    dropped = _build_runtime_context("thread-1", "run-1", {EXTENSION_SNAPSHOT_CONTEXT_KEY: forged}, None, None, None)

    assert overridden[EXTENSION_SNAPSHOT_CONTEXT_KEY] is loaded
    assert EXTENSION_SNAPSHOT_CONTEXT_KEY not in dropped


def test_resolve_run_extensions_rejects_a_foreign_context_value():
    loaded = ExtensionRegistry().build()

    assert resolve_run_extensions({EXTENSION_SNAPSHOT_CONTEXT_KEY: loaded}) is loaded
    assert resolve_run_extensions({EXTENSION_SNAPSHOT_CONTEXT_KEY: "not-a-snapshot"}) is None
    assert resolve_run_extensions({}) is None
    assert resolve_run_extensions(None) is None


def test_gateway_run_context_captures_the_app_extension_snapshot(monkeypatch):
    from app.gateway import deps

    loaded = ExtensionRegistry().build()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                extensions=loaded,
                run_events_config=None,
                checkpoint_channel_mode="full",
                checkpoint_snapshot_frequency=None,
            )
        )
    )
    monkeypatch.setattr(deps, "get_checkpointer", lambda request: None)
    monkeypatch.setattr(deps, "get_store", lambda request: None)
    monkeypatch.setattr(deps, "get_run_event_store", lambda request: None)
    monkeypatch.setattr(deps, "get_thread_store", lambda request: None)
    monkeypatch.setattr(deps, "get_config", lambda: SimpleNamespace())

    context = deps.get_run_context(request)

    assert context.extensions is loaded


@pytest.fixture
def _isolated_extensions():
    reset_loaded_extensions()
    yield
    reset_loaded_extensions()


class _MiddlewareContributor:
    def contribute_middlewares(self, app_store, ctx):
        return ()


class _TaskStoreReadingAgent:
    def __init__(self) -> None:
        self.task_store = None
        self.extensions = None

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        runtime = (config or {})["configurable"]["__pregel_runtime"]
        self.task_store = runtime.context.get(EXTENSION_TASK_STORE_KEY)
        self.extensions = resolve_run_extensions(runtime.context)
        yield {"messages": []}


def _bridge():
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


_MOCKED_SUBAGENT_MODULES = (
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
def _subagent_env():
    """Import the real executor behind tests/conftest.py's cycle-breaking mock."""
    original_modules = {name: sys.modules.get(name) for name in _MOCKED_SUBAGENT_MODULES}
    original_executor = sys.modules.get("deerflow.subagents.executor")
    missing = object()
    subagents_pkg = sys.modules.get("deerflow.subagents")
    original_executor_attr = getattr(subagents_pkg, "executor", missing) if subagents_pkg is not None else missing

    sys.modules.pop("deerflow.subagents.executor", None)
    if subagents_pkg is not None and hasattr(subagents_pkg, "executor"):
        delattr(subagents_pkg, "executor")

    try:
        for name in _MOCKED_SUBAGENT_MODULES:
            sys.modules[name] = MagicMock()
        storage_module = ModuleType("deerflow.skills.storage")
        storage_module.get_or_new_skill_storage = lambda **kwargs: SimpleNamespace(load_skills=lambda *, enabled_only: [])
        storage_module.get_or_new_user_skill_storage = lambda user_id, **kwargs: SimpleNamespace(load_skills=lambda *, enabled_only: [])
        sys.modules["deerflow.skills.storage"] = storage_module

        from deerflow.subagents.config import SubagentConfig
        from deerflow.subagents.executor import SubagentExecutor

        executor_module = sys.modules["deerflow.subagents.executor"]
        executor_module.get_app_config = lambda: SimpleNamespace(
            tool_search=SimpleNamespace(enabled=False),
            authorization=SimpleNamespace(enabled=False),
        )
        yield SimpleNamespace(SubagentConfig=SubagentConfig, SubagentExecutor=SubagentExecutor)
    finally:
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


class _CapturingSubagent:
    def __init__(self, seen: dict) -> None:
        self._seen = seen

    async def astream(self, *args, **kwargs):
        self._seen["context"] = kwargs.get("context")
        yield {"messages": [AIMessage(content="done")]}


async def _run_subagent(monkeypatch, env, *, seen: dict):
    async def _initial_state(self, task):
        return ({}, [], None)

    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _initial_state)
    monkeypatch.setattr(env.SubagentExecutor, "_create_agent", lambda self, tools, **kwargs: _CapturingSubagent(seen))
    config = env.SubagentConfig(name="researcher", description="d", system_prompt="p", tools=[])
    executor = env.SubagentExecutor(config=config, tools=[], thread_id="thread-1", run_id=None)
    return await executor._aexecute("do the thing")


@pytest.mark.anyio
async def test_lead_middleware_receives_a_run_scoped_store(_isolated_extensions):
    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        registry.middlewares(_MiddlewareContributor())
    set_loaded_extensions(registry.build())

    run_manager = RunManager()
    record = await run_manager.create("thread-ext-middleware")
    agent = _TaskStoreReadingAgent()

    await run_agent(
        _bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=InMemorySaver()),
        agent_factory=lambda *, config: agent,
        graph_input={},
        config={},
    )

    assert agent.task_store is not None
    assert agent.task_store.scope_id == record.run_id


@pytest.mark.anyio
async def test_lead_agent_factory_receives_the_same_extension_snapshot_as_the_store(_isolated_extensions):
    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        registry.middlewares(_MiddlewareContributor())
    loaded = registry.build()
    set_loaded_extensions(ExtensionRegistry().build())
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-snapshot")
    agent = _TaskStoreReadingAgent()
    seen = {}

    def agent_factory(*, config):
        seen["extensions"] = get_agent_build_extensions()
        return agent

    await run_agent(
        _bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, extensions=loaded),
        agent_factory=agent_factory,
        graph_input={},
        config={},
    )

    assert seen["extensions"] is loaded
    assert agent.task_store is not None


@pytest.mark.anyio
async def test_lead_run_publishes_its_snapshot_for_delegated_work(_isolated_extensions):
    """Delegation happens during graph execution, long after the graph-build
    contextvar binding has exited, so the run's snapshot has to travel through
    runtime context to stay reachable from ``task_tool``."""
    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        registry.middlewares(_MiddlewareContributor())
    loaded = registry.build()
    set_loaded_extensions(ExtensionRegistry().build())
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-delegation")
    agent = _TaskStoreReadingAgent()

    await run_agent(
        _bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, extensions=loaded),
        agent_factory=lambda *, config: agent,
        graph_input={},
        config={},
    )

    assert agent.extensions is loaded


@pytest.mark.anyio
async def test_subagent_middleware_without_parent_run_receives_its_task_store(monkeypatch, _isolated_extensions, _subagent_env):
    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        registry.middlewares(_MiddlewareContributor())
    set_loaded_extensions(registry.build())
    seen: dict = {}

    result = await _run_subagent(monkeypatch, _subagent_env, seen=seen)

    store = (seen.get("context") or {}).get(EXTENSION_TASK_STORE_KEY)
    assert isinstance(store, ExtensionData)
    assert store.scope_id == result.task_id


@pytest.mark.anyio
async def test_subagent_builder_receives_the_same_extension_snapshot_as_the_store(monkeypatch, _isolated_extensions, _subagent_env):
    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        registry.middlewares(_MiddlewareContributor())
    loaded = registry.build()
    set_loaded_extensions(loaded)
    seen: dict = {}

    async def _initial_state(self, task):
        set_loaded_extensions(ExtensionRegistry().build())
        return ({}, [], None)

    def _create_agent(self, tools, *, deferred_setup=None, extensions=None):
        seen["extensions"] = extensions
        return _CapturingSubagent(seen)

    monkeypatch.setattr(_subagent_env.SubagentExecutor, "_build_initial_state", _initial_state)
    monkeypatch.setattr(_subagent_env.SubagentExecutor, "_create_agent", _create_agent)
    config = _subagent_env.SubagentConfig(name="researcher", description="d", system_prompt="p", tools=[])
    executor = _subagent_env.SubagentExecutor(config=config, tools=[], thread_id="thread-1", run_id=None)

    result = await executor._aexecute("do the thing")

    assert seen["extensions"] is loaded
    store = (seen.get("context") or {}).get(EXTENSION_TASK_STORE_KEY)
    assert isinstance(store, ExtensionData)
    assert store.scope_id == result.task_id


@pytest.mark.anyio
async def test_subagent_prefers_the_parent_run_snapshot_over_the_singleton(monkeypatch, _isolated_extensions, _subagent_env):
    """A singleton replacement between the lead run's start and the subagent's
    execution must not mix two extension generations within one run."""
    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        registry.middlewares(_MiddlewareContributor())
    run_snapshot = registry.build()
    replaced_singleton = ExtensionRegistry().build()
    set_loaded_extensions(replaced_singleton)
    seen: dict = {}

    async def _initial_state(self, task):
        return ({}, [], None)

    def _create_agent(self, tools, *, deferred_setup=None, extensions=None):
        seen["extensions"] = extensions
        return _CapturingSubagent(seen)

    monkeypatch.setattr(_subagent_env.SubagentExecutor, "_build_initial_state", _initial_state)
    monkeypatch.setattr(_subagent_env.SubagentExecutor, "_create_agent", _create_agent)
    config = _subagent_env.SubagentConfig(name="researcher", description="d", system_prompt="p", tools=[])
    executor = _subagent_env.SubagentExecutor(
        config=config,
        tools=[],
        thread_id="thread-1",
        run_id=None,
        extensions=run_snapshot,
    )

    result = await executor._aexecute("do the thing")

    assert seen["extensions"] is run_snapshot
    # The store follows the same snapshot: the replaced singleton contributes
    # no middleware and would have allocated nothing.
    store = (seen.get("context") or {}).get(EXTENSION_TASK_STORE_KEY)
    assert isinstance(store, ExtensionData)
    assert store.scope_id == result.task_id


@pytest.mark.anyio
async def test_subagent_without_task_store_contributors_does_not_inject_one(monkeypatch, _isolated_extensions, _subagent_env):
    seen: dict = {}

    await _run_subagent(monkeypatch, _subagent_env, seen=seen)

    assert EXTENSION_TASK_STORE_KEY not in (seen.get("context") or {})
