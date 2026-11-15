"""Loop-owned SQLite checkpoint resources for opt-in native task history.

The registry associates a parent storage owner with its isolated-loop peer. It
does not infer a database from a request or hot-reload infrastructure settings.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import Context, ContextVar
from typing import Any

from langchain_core.runnables.config import var_child_runnable_config
from langgraph._internal._constants import CONFIG_KEY_CHECKPOINTER, NS_SEP
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.config.app_config import AppConfig
from deerflow.runtime.checkpointer import async_provider
from deerflow.utils.file_io import await_drained

_runtimes: dict[int, SubagentCheckpointRuntime] = {}
_registry_lock = threading.Lock()
_captured_runtime: ContextVar[SubagentCheckpointRuntime | None] = ContextVar("subagent_checkpoint_runtime", default=None)
_active_runtime: ContextVar[SubagentCheckpointRuntime | None] = ContextVar("active_subagent_checkpoint_runtime", default=None)


class SubagentCheckpointError(RuntimeError):
    """Checkpoint admission failed before a native graph could start."""


async def _on_isolated_loop[T](factory: Callable[[], Coroutine[Any, Any, T]], *, loop: asyncio.AbstractEventLoop | None = None) -> T:
    # Infrastructure startup/teardown must not inherit a run's graph context.
    from deerflow.subagents.executor import _submit_to_isolated_loop_in_context

    if loop is None:
        # First use may start a thread and wait for its loop-ready handshake.
        future = await asyncio.to_thread(_submit_to_isolated_loop_in_context, Context(), factory)
    else:
        if loop.is_closed() or not loop.is_running():
            raise RuntimeError("Subagent checkpoint owner loop stopped before its resources were drained")

        def submit():
            coroutine = factory()
            try:
                return asyncio.run_coroutine_threadsafe(coroutine, loop)
            except BaseException:
                coroutine.close()
                raise

        future = Context().run(submit)
    return await asyncio.wrap_future(future)


class SubagentCheckpointRuntime:
    """One saver shared by native children on their persistent execution loop."""

    def __init__(self, config: AppConfig, parent_saver: BaseCheckpointSaver) -> None:
        self.config = config.model_copy(deep=True)
        self.parent_saver = parent_saver
        self.mode = config.database.checkpoint_channel_mode
        self.loop: asyncio.AbstractEventLoop | None = None
        self.saver: BaseCheckpointSaver | None = None
        self.closed = False
        self.closing = False
        self._stack: AsyncExitStack | None = None
        self._executions: set[asyncio.Task] = set()
        self._stop_task: asyncio.Task | None = None

    def owns_parent_saver(self, saver: BaseCheckpointSaver | None) -> bool:
        # Strict msgpack support makes shallow saver clones with a derived
        # serializer. They still share the parent's connection and lock.
        source = getattr(saver, "source_saver", saver)
        owner = getattr(self.parent_saver, "source_saver", self.parent_saver)
        if source is owner:
            return True
        connection = getattr(source, "conn", None)
        return connection is not None and connection is getattr(owner, "conn", None)

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._stack = AsyncExitStack()
        self.saver = await self._stack.enter_async_context(async_provider.make_checkpointer(self.config))

    async def stop(self) -> None:
        if self.closed:
            return
        if asyncio.get_running_loop() is not self.loop:
            raise RuntimeError("Subagent checkpoint resources must close on their owning event loop")
        self.closing = True
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop())
        await asyncio.shield(self._stop_task)

    async def _stop(self) -> None:
        # These tasks own their complete stream/checkpoint cleanup tails, not
        # just their public terminal status. Do not close storage until they exit.
        tasks = tuple(self._executions)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._stack is not None:
            await self._stack.aclose()
        self.closed = True


@asynccontextmanager
async def subagent_checkpoint_runtime(config: AppConfig, parent_saver: BaseCheckpointSaver) -> AsyncIterator[SubagentCheckpointRuntime | None]:
    """Own the isolated saver inside the parent saver's application lifetime.

    Admission is captured at dispatch; shutdown fences new leases, cancels and
    drains existing executions, and closes the peer on its owning loop. The
    parent connection must remain open until this context exits.
    """
    if getattr(getattr(config, "subagent_runtime", None), "checkpoint_enabled", False) is not True:
        yield None
        return
    source = getattr(parent_saver, "source_saver", parent_saver)
    legacy = config.checkpointer
    backend = legacy.type if legacy is not None else config.database.backend
    if backend != "sqlite" or isinstance(source, InMemorySaver):
        raise ValueError("subagent_runtime.checkpoint_enabled only supports file-backed SQLite checkpoint storage")
    if legacy is not None and legacy.type == "sqlite" and legacy.connection_string == ":memory:":
        raise ValueError("subagent_runtime.checkpoint_enabled requires file-backed SQLite, not :memory:")

    runtime = SubagentCheckpointRuntime(config, parent_saver)
    registered = False
    try:
        await await_drained(_on_isolated_loop(runtime.start))
        with _registry_lock:
            if id(parent_saver) in _runtimes:
                raise RuntimeError("Subagent checkpoint runtime is already installed for this parent saver")
            _runtimes[id(parent_saver)] = runtime
            registered = True
        yield runtime
    finally:
        try:
            if runtime.loop is not None and not runtime.closed:
                await await_drained(_on_isolated_loop(runtime.stop, loop=runtime.loop))
        finally:
            if registered and runtime.closed:
                with _registry_lock:
                    _runtimes.pop(id(parent_saver), None)


def has_checkpoint_runtimes(loop: asyncio.AbstractEventLoop) -> bool:
    with _registry_lock:
        return any(runtime.loop is loop and not runtime.closed for runtime in _runtimes.values())


async def drain_checkpoint_runtimes() -> None:
    """Last-resort loop shutdown still drains its registered storage owners."""
    loop = asyncio.get_running_loop()
    with _registry_lock:
        runtimes = [runtime for runtime in _runtimes.values() if runtime.loop is loop]
    for runtime in runtimes:
        await runtime.stop()


def capture_checkpoint_runtime(context: Context) -> None:
    """Pin an installed runtime before a copied context crosses to the worker."""
    inherited = context.get(var_child_runnable_config) or {}
    parent = inherited.get("configurable", {}).get(CONFIG_KEY_CHECKPOINTER)
    with _registry_lock:
        runtime = _runtimes.get(id(parent))
        if runtime is None:
            runtime = next((candidate for candidate in _runtimes.values() if candidate.owns_parent_saver(parent)), None)
    captured = context.get(_captured_runtime)
    if runtime is None and captured is not None and captured.owns_parent_saver(parent):
        runtime = captured
    # A captured runtime remains fenced after its registration is removed.
    context.run(_captured_runtime.set, runtime)


def checkpoint_runtime() -> SubagentCheckpointRuntime | None:
    """Return only a runtime leased by the current native execution."""
    return _active_runtime.get()


@asynccontextmanager
async def subagent_checkpoint_scope(*, execution_id: str, run_id: str | None, tool_call_id: str | None, agent_name: str) -> AsyncIterator[None]:
    runtime = _captured_runtime.get()
    if runtime is None:
        yield
        return
    if runtime.closing or runtime.closed:
        raise SubagentCheckpointError("Subagent checkpoint runtime is shutting down")
    if asyncio.get_running_loop() is not runtime.loop:
        raise SubagentCheckpointError("Subagent checkpoint runtime must be used on its owning event loop")
    inherited = var_child_runnable_config.get() or {}
    configurable = inherited.get("configurable", {})
    if not runtime.owns_parent_saver(configurable.get(CONFIG_KEY_CHECKPOINTER)):
        raise SubagentCheckpointError("Subagent checkpoint runtime does not match the inherited parent saver")
    if not configurable.get("thread_id") or not configurable.get("checkpoint_ns"):
        raise SubagentCheckpointError("Subagent checkpoint history requires an inherited parent graph namespace")

    # Replace the inherited saver, not just the compile-time argument:
    # LangGraph gives CONFIG_KEY_CHECKPOINTER precedence over that argument.
    # A server execution ID also gives each independent attempt a fresh history,
    # even if a provider reuses a tool ID or a parent node is replayed.
    child_configurable = {
        **configurable,
        CONFIG_KEY_CHECKPOINTER: runtime.saver,
        "checkpoint_ns": NS_SEP.join((configurable["checkpoint_ns"], f"deerflow_subagent:{execution_id}")),
    }
    metadata = {
        **inherited.get("metadata", {}),
        "deerflow_subagent_execution_id": execution_id,
        "deerflow_subagent_name": agent_name,
    }
    if run_id:
        metadata["deerflow_parent_run_id"] = run_id
    if tool_call_id:
        metadata["deerflow_subagent_tool_call_id"] = tool_call_id
    config_token = var_child_runnable_config.set({**inherited, "configurable": child_configurable, "metadata": metadata})
    runtime_token = _active_runtime.set(runtime)
    task = asyncio.current_task()
    runtime._executions.add(task)
    try:
        yield
    finally:
        runtime._executions.discard(task)
        _active_runtime.reset(runtime_token)
        var_child_runnable_config.reset(config_token)
