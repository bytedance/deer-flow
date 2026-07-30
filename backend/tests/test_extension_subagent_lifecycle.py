"""Subagent executions must produce the same task events as lead executions.

These tests drive the real `_aexecute` path. Testing `notify_task_*` directly
would pass without any executor change, so it would not gate this task's work.

Three deviations from the plan's verbatim test code, all forced by how the repo
and `_aexecute` actually behave (see the task report):

1. `conftest.py` installs a MagicMock for `deerflow.subagents.executor` to break
   a production circular import, so a module-level import of `SubagentExecutor`
   yields a mock. Real classes are imported inside a fixture, following
   `tests/test_subagent_executor.py`, which solves the same problem.
2. `_aexecute` catches every exception and converts it into a FAILED
   `SubagentResult`; it does not propagate. So the driver asserts on the
   returned result plus the recorder rather than wrapping the call in
   `pytest.raises`, which would always fail with DID NOT RAISE.
3. The runtime context reaches the graph as `agent.astream(..., context=...)`,
   a sibling kwarg of `config=` — not as `config["context"]`. The fake agent
   captures the `context` kwarg accordingly.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from deerflow_extension_api import EXTENSION_TASK_STORE_KEY, TaskInfo, TaskOutcome
from langchain_core.messages import AIMessage

from deerflow.extensions import reset_loaded_extensions, set_loaded_extensions
from deerflow.extensions.notify import (
    reset_extension_notify_loop,
    set_extension_notify_loop,
    suspend_extension_system_observations,
)
from deerflow.extensions.registry import ExtensionRegistry

# Same set test_subagent_executor.py mocks to import the real executor module.
_MOCKED_MODULE_NAMES = [
    "deerflow.agents",
    "deerflow.agents.thread_state",
    "deerflow.agents.middlewares",
    "deerflow.agents.middlewares.thread_data_middleware",
    "deerflow.sandbox",
    "deerflow.sandbox.middleware",
    "deerflow.sandbox.security",
    "deerflow.models",
    "deerflow.skills.storage",
]


class _Sentinel(RuntimeError):
    """Stops execution right after the wiring under test has run."""


class _Recorder:
    def __init__(self) -> None:
        self.starts: list[TaskInfo] = []
        self.stops: list[tuple[TaskInfo, TaskOutcome]] = []

    async def on_task_start(self, app_store, task_store, info):
        self.starts.append(info)

    async def on_task_stop(self, app_store, task_store, info, outcome):
        self.stops.append((info, outcome))


class _TaskStoreConsumer:
    def __init__(self) -> None:
        self.lifecycle_events: list[str] = []

    def contribute_middlewares(self, app_store, ctx):
        return ()

    async def on_system_model_call(self, app_store, task_store, kind, request, result):
        return None

    async def on_task_start(self, app_store, task_store, info):
        self.lifecycle_events.append("start")

    async def on_task_stop(self, app_store, task_store, info, outcome):
        self.lifecycle_events.append("stop")


@pytest.fixture(autouse=True)
def env():
    """Import the real executor classes and isolate the extensions singleton."""
    reset_loaded_extensions()
    reset_extension_notify_loop()

    original_modules = {name: sys.modules.get(name) for name in _MOCKED_MODULE_NAMES}
    original_executor = sys.modules.get("deerflow.subagents.executor")

    if "deerflow.subagents.executor" in sys.modules:
        del sys.modules["deerflow.subagents.executor"]
    subagents_pkg = sys.modules.get("deerflow.subagents")
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
        from deerflow.subagents.executor import SubagentExecutor, SubagentResult, SubagentStatus

        # CI checkouts have no config.yaml; these tests never reach real config.
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
        # try/finally, unlike the pattern in test_subagent_executor.py this is
        # copied from: if the real-class import above ever raises, the mocked
        # modules must not leak into every later test in the process.
        for name in _MOCKED_MODULE_NAMES:
            if original_modules[name] is not None:
                sys.modules[name] = original_modules[name]
            elif name in sys.modules:
                del sys.modules[name]
        if original_executor is not None:
            sys.modules["deerflow.subagents.executor"] = original_executor
        subagents_pkg = sys.modules.get("deerflow.subagents")
        if subagents_pkg is not None and hasattr(subagents_pkg, "executor"):
            # Cleared at teardown too, not only at setup: otherwise
            # `from deerflow.subagents import executor` and sys.modules[...]
            # disagree for the rest of the session.
            delattr(subagents_pkg, "executor")
        reset_extension_notify_loop()
        reset_loaded_extensions()


def _install(recorder) -> None:
    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        registry.task_lifecycle(recorder)
    set_loaded_extensions(registry.build())


def _install_task_store_consumer(kind: str) -> _TaskStoreConsumer:
    registry = ExtensionRegistry()
    consumer = _TaskStoreConsumer()
    with registry.attributed_to("demo:install"):
        if kind == "middleware":
            registry.middlewares(consumer)
        else:
            registry.system_model_observer(consumer)
    set_loaded_extensions(registry.build())
    return consumer


def _executor(env, **overrides):
    # SubagentConfig's prompt field is `system_prompt`, not `prompt` (see
    # subagents/config.py); the plan's `_executor()` anticipated this drift.
    config = env.SubagentConfig(name="researcher", description="d", system_prompt="p", tools=[])
    kwargs = {"run_id": "run-1", "thread_id": "thread-1"}
    kwargs.update(overrides)
    return env.SubagentExecutor(config=config, tools=[], **kwargs)


def _raise_sentinel(self, task):
    raise _Sentinel()


def _run(executor):
    return asyncio.run(executor._aexecute("do the thing"))


class _RunningLoop:
    """A real serving loop running on another thread, like the Gateway's."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        assert self._ready.wait(5), "loop thread did not start"

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self._ready.set)
        self.loop.run_forever()

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(5)
        self.loop.close()


class _LoopBoundLifecycleService:
    """Binds in service startup, then rejects hooks run on another loop."""

    def __init__(self) -> None:
        self.bound_loop: asyncio.AbstractEventLoop | None = None
        self.events: list[str] = []
        self.event_loops: list[asyncio.AbstractEventLoop] = []

    async def start(self, deps) -> None:
        self.bound_loop = asyncio.get_running_loop()

    async def stop(self) -> None:
        return None

    async def on_task_start(self, app_store, task_store, info) -> None:
        loop = asyncio.get_running_loop()
        if loop is not self.bound_loop:
            raise RuntimeError("loop-bound service used from the subagent loop")
        self.events.append("start")
        self.event_loops.append(loop)

    async def on_task_stop(self, app_store, task_store, info, outcome) -> None:
        loop = asyncio.get_running_loop()
        if loop is not self.bound_loop:
            raise RuntimeError("loop-bound service used from the subagent loop")
        self.events.append("stop")
        self.event_loops.append(loop)


class _FakeAgent:
    """Captures what the executor hands the graph, then stops the run."""

    def __init__(self, seen: dict) -> None:
        self._seen = seen

    def astream(self, *args, **kwargs):
        self._seen["context"] = kwargs.get("context")
        raise _Sentinel()


def _stub_agent(monkeypatch, env, seen: dict) -> None:
    async def _fake_build_initial_state(self, task):
        return ({}, [], None)

    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _fake_build_initial_state)
    monkeypatch.setattr(env.SubagentExecutor, "_create_agent", lambda self, tools, **kw: _FakeAgent(seen))


def test_task_start_fires_with_subagent_shaped_info(monkeypatch, env):
    recorder = _Recorder()
    _install(recorder)
    executor = _executor(env)
    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _raise_sentinel)
    _run(executor)

    assert len(recorder.starts) == 1
    info = recorder.starts[0]
    assert info.kind == "subagent"
    assert info.run_id == "run-1", "subagent shares the parent run"
    assert info.parent_task_id == "run-1", "subagent must point at the lead task"
    assert info.thread_id == "thread-1"
    assert info.agent_name == "researcher"
    assert info.task_id, "task_id comes from result.task_id, not self.task_id"


def test_lifecycle_hooks_run_on_the_registered_extension_loop(monkeypatch, env):
    extension = _LoopBoundLifecycleService()
    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        registry.service(extension)
        registry.task_lifecycle(extension)
    set_loaded_extensions(registry.build())

    host = _RunningLoop()
    try:
        asyncio.run_coroutine_threadsafe(extension.start(None), host.loop).result(5)
        set_extension_notify_loop(host.loop)
        # Gateway suspends fire-and-forget memory observations before draining
        # runs; task lifecycle must retain the registered loop until that drain
        # and service teardown have completed.
        suspend_extension_system_observations()

        executor = _executor(env)
        monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _raise_sentinel)
        result = _run(executor)
    finally:
        reset_extension_notify_loop()
        host.close()

    assert result.status is env.SubagentStatus.FAILED
    assert extension.events == ["start", "stop"]
    assert extension.event_loops == [host.loop, host.loop]


def test_failure_reports_failed_outcome_from_finally(monkeypatch, env):
    recorder = _Recorder()
    _install(recorder)
    executor = _executor(env)
    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _raise_sentinel)
    result = _run(executor)

    assert result.status is env.SubagentStatus.FAILED, "guards the premise of the outcome assertion"
    assert len(recorder.stops) == 1, "stop must fire on the exception path too"
    assert recorder.stops[0][1] is TaskOutcome.FAILED
    assert recorder.stops[0][0].task_id == recorder.starts[0].task_id


def test_cancelled_run_reports_aborted(monkeypatch, env):
    """A user cancellation is an abort, not a failure — the same distinction the
    lead path draws, so one extension code path reads both.

    This also covers the `return` that the pre-stream cancel check makes from
    *inside* the try: stop must still fire, which only holds if the notification
    lives in `finally` rather than after the try.
    """
    recorder = _Recorder()
    _install(recorder)
    executor = _executor(env)
    seen: dict = {}
    _stub_agent(monkeypatch, env, seen)

    holder = env.SubagentResult(task_id="cancelme", trace_id="trace-1", status=env.SubagentStatus.RUNNING)
    holder.cancel_event.set()
    result = asyncio.run(executor._aexecute("do the thing", holder))

    assert result.status is env.SubagentStatus.CANCELLED
    assert len(recorder.stops) == 1, "early return inside the try must still notify stop"
    assert recorder.stops[0][1] is TaskOutcome.ABORTED
    assert recorder.stops[0][0].task_id == "cancelme", "task id comes from the caller's result holder"


def test_task_store_reaches_the_runtime_context(monkeypatch, env):
    """Contributed middlewares can only read the store through the runtime
    context, so the executor must install it there for subagents too."""
    recorder = _Recorder()
    _install(recorder)
    executor = _executor(env)
    seen: dict = {}
    _stub_agent(monkeypatch, env, seen)
    _run(executor)

    context = seen.get("context") or {}
    assert EXTENSION_TASK_STORE_KEY in context
    assert context[EXTENSION_TASK_STORE_KEY].scope_id == recorder.starts[0].task_id


def test_task_store_reaches_middleware_without_lifecycle_or_parent_run(monkeypatch, env):
    consumer = _install_task_store_consumer("middleware")
    executor = _executor(env, run_id=None)
    seen: dict = {}
    _stub_agent(monkeypatch, env, seen)

    result = _run(executor)

    context = seen.get("context") or {}
    assert EXTENSION_TASK_STORE_KEY in context
    assert context[EXTENSION_TASK_STORE_KEY].scope_id == result.task_id
    assert consumer.lifecycle_events == []


def test_task_store_reaches_system_observer_without_lifecycle(monkeypatch, env):
    consumer = _install_task_store_consumer("observer")
    executor = _executor(env)
    seen: dict = {}
    _stub_agent(monkeypatch, env, seen)

    result = _run(executor)

    context = seen.get("context") or {}
    assert EXTENSION_TASK_STORE_KEY in context
    assert context[EXTENSION_TASK_STORE_KEY].scope_id == result.task_id
    assert consumer.lifecycle_events == []


def test_zero_contributors_skips_the_wiring_entirely(monkeypatch, env):
    """The zero-extension path must not install a store in the runtime context.

    Deliberately narrower than "must not construct a store": this asserts the
    observable half. Registry tests verify the `needs_task_store` construction
    guard separately.
    """
    executor = _executor(env)
    seen: dict = {}
    _stub_agent(monkeypatch, env, seen)
    _run(executor)  # no contributors installed

    context = seen.get("context") or {}
    assert EXTENSION_TASK_STORE_KEY not in context, "no contributors means no store allocated"


def test_missing_run_id_does_not_break_execution(monkeypatch, env):
    """Subagents can run without a parent run id (e.g. direct invocation)."""
    recorder = _Recorder()
    _install(recorder)
    executor = _executor(env, run_id=None)
    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _raise_sentinel)
    _run(executor)
    assert recorder.starts == [], "no parent run means no subagent task event"
    assert recorder.stops == [], "and no orphan stop either"


class _CompletingAgent:
    """Streams one chunk with a usable answer, so the run terminates COMPLETED."""

    async def astream(self, *args, **kwargs):
        yield {"messages": [AIMessage(content="the answer")]}


def test_successful_run_reports_completed(monkeypatch, env):
    """The outcome that fires on virtually every real subagent run.

    Left uncovered, the `else` fallback that produced it also silently reported
    COMPLETED for a status the host never set — which is exactly the defect this
    task's fix round closes.
    """
    recorder = _Recorder()
    _install(recorder)
    executor = _executor(env)

    async def _fake_build_initial_state(self, task):
        return ({}, [], None)

    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _fake_build_initial_state)
    monkeypatch.setattr(env.SubagentExecutor, "_create_agent", lambda self, tools, **kw: _CompletingAgent())
    result = _run(executor)

    assert result.status is env.SubagentStatus.COMPLETED, "premise for the outcome assertion"
    assert len(recorder.stops) == 1
    assert recorder.stops[0][1] is TaskOutcome.COMPLETED


def test_a_status_the_host_never_set_reports_failed_not_completed(monkeypatch, env):
    """A BaseException escapes `except Exception`, so the result is still
    RUNNING when the finally classifies it. Success-keyed classification reports
    FAILED; the previous `else: COMPLETED` fallback called it a clean success.
    """
    recorder = _Recorder()
    _install(recorder)
    executor = _executor(env)

    def _hard_stop(self, task):
        raise KeyboardInterrupt("host going down")

    monkeypatch.setattr(env.SubagentExecutor, "_build_initial_state", _hard_stop)

    with pytest.raises(KeyboardInterrupt):
        _run(executor)

    assert len(recorder.stops) == 1, "the finally must still notify"
    assert recorder.stops[0][1] is TaskOutcome.FAILED


def test_timed_out_reports_failed(monkeypatch, env):
    """execute_async stamps TIMED_OUT on the holder before cancelling; that is
    a failure to an extension, not a completion."""
    recorder = _Recorder()
    _install(recorder)
    executor = _executor(env)
    seen: dict = {}
    _stub_agent(monkeypatch, env, seen)

    holder = env.SubagentResult(task_id="slowpoke", trace_id="trace-1", status=env.SubagentStatus.RUNNING)
    holder.try_set_terminal(env.SubagentStatus.TIMED_OUT, error="too slow")
    result = asyncio.run(executor._aexecute("do the thing", holder))

    assert result.status is env.SubagentStatus.TIMED_OUT
    assert recorder.stops[0][1] is TaskOutcome.FAILED
