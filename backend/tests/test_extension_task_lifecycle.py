"""Tests for task lifecycle notification and the runtime-context bridge."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from deerflow_extension_api import (
    EXTENSION_TASK_STORE_KEY,
    ExtensionData,
    TaskInfo,
    TaskOutcome,
    task_store_from_runtime,
)
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.extensions import reset_loaded_extensions, set_loaded_extensions
from deerflow.extensions.notify import (
    lead_task_id,
    lead_task_outcome,
    notify_task_start,
    notify_task_stop,
)
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import RunContext, _build_runtime_context, run_agent


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []

    async def on_task_start(self, app_store, task_store, info):
        task_store.set(_Marker(info.task_id))
        self.events.append(("start", info.task_id, info.kind))

    async def on_task_stop(self, app_store, task_store, info, outcome):
        self.events.append(("stop", info.task_id, outcome.value))


class _Marker:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id


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


class _Boom:
    async def on_task_start(self, app_store, task_store, info):
        raise ValueError("observer exploded")

    async def on_task_stop(self, app_store, task_store, info, outcome):
        raise ValueError("observer exploded")


def _extensions(*contributors):
    registry = ExtensionRegistry()
    for index, contributor in enumerate(contributors):
        with registry.attributed_to(f"ext{index}:install"):
            registry.task_lifecycle(contributor)
    return registry.build()


def _info(task_id: str = "task-1", kind: str = "lead") -> TaskInfo:
    return TaskInfo(task_id=task_id, run_id="run-1", thread_id="thread-1", kind=kind)


def test_lead_task_id_derives_from_run_id():
    """Lead task is 1:1 with a run — including across goal continuations, which
    reuse the same task — so no new identifier is minted."""
    assert lead_task_id("run-abc") == "run-abc"


def test_start_and_stop_reach_the_contributor():
    recorder = _Recorder()
    extensions = _extensions(recorder)
    store = ExtensionData("task-1")
    asyncio.run(notify_task_start(extensions, store, _info()))
    asyncio.run(notify_task_stop(extensions, store, _info(), TaskOutcome.COMPLETED))
    assert recorder.events == [("start", "task-1", "lead"), ("stop", "task-1", "completed")]


def test_contributor_can_store_state_in_the_task_store():
    recorder = _Recorder()
    store = ExtensionData("task-1")
    asyncio.run(notify_task_start(_extensions(recorder), store, _info()))
    assert store.get(_Marker).task_id == "task-1"


def test_one_failing_observer_does_not_stop_the_others():
    recorder = _Recorder()
    extensions = _extensions(_Boom(), recorder)
    store = ExtensionData("task-1")
    asyncio.run(notify_task_start(extensions, store, _info()))
    assert recorder.events == [("start", "task-1", "lead")]


def test_zero_contributors_is_a_no_op():
    extensions = ExtensionRegistry().build()
    store = ExtensionData("task-1")
    asyncio.run(notify_task_start(extensions, store, _info()))
    asyncio.run(notify_task_stop(extensions, store, _info(), TaskOutcome.FAILED))


def test_runtime_context_bridge_roundtrips():
    store = ExtensionData("task-1")
    context = {EXTENSION_TASK_STORE_KEY: store}

    class _Runtime:
        pass

    runtime = _Runtime()
    runtime.context = context
    assert task_store_from_runtime(runtime) is store


def test_build_runtime_context_installs_the_store_under_the_host_key():
    """The bridge above only proves the reader works. This proves the writer
    does: `_build_runtime_context` is the sole production code that puts the
    store where `task_store_from_runtime` looks for it."""
    store = ExtensionData("task-1")
    ctx = _build_runtime_context("thread-1", "run-1", None, None, store)
    assert ctx[EXTENSION_TASK_STORE_KEY] is store


def test_build_runtime_context_adds_no_key_without_a_store():
    """Zero-extension path: no store means no key, not a None placeholder."""
    ctx = _build_runtime_context("thread-1", "run-1", None, None, None)
    assert EXTENSION_TASK_STORE_KEY not in ctx


def test_subagent_info_carries_parent():
    info = TaskInfo(
        task_id="call-9",
        run_id="run-1",
        thread_id="thread-1",
        kind="subagent",
        parent_task_id="run-1",
    )
    assert info.parent_task_id == "run-1"
    assert info.kind == "subagent"


def test_lead_outcome_reports_failed_when_the_run_did_not_succeed():
    """A crashed lead run must not look like a completed one.

    The subagent side (Task 11) maps its failed status to FAILED; without the
    same mapping here an extension reconciling task state would treat a run
    that raised as a clean completion.
    """
    assert lead_task_outcome(aborted=False, succeeded=False) is TaskOutcome.FAILED


def test_lead_outcome_prefers_aborted_over_failure():
    """Cancellation is the more specific explanation: an aborted run commonly
    also unwinds through an exception, and the caller asked for the stop."""
    assert lead_task_outcome(aborted=True, succeeded=False) is TaskOutcome.ABORTED
    assert lead_task_outcome(aborted=True, succeeded=True) is TaskOutcome.ABORTED


def test_lead_outcome_is_completed_only_on_explicit_success():
    """Keyed on success rather than on an error probe, so a status the host
    never anticipated degrades to FAILED instead of reporting a clean run."""
    assert lead_task_outcome(aborted=False, succeeded=True) is TaskOutcome.COMPLETED


# --- run_agent-level wiring -------------------------------------------------
#
# Everything above tests notify.py in isolation, which passes with both
# worker.py hunks reverted. These drive the real run_agent so the wiring itself
# is gated: start/stop firing around a run, the store reaching the runtime
# context, and the outcome classification reading real run state.


class _RunRecorder:
    def __init__(self) -> None:
        self.starts: list[TaskInfo] = []
        self.start_stores: list[ExtensionData] = []
        self.stops: list[tuple[TaskInfo, TaskOutcome]] = []

    async def on_task_start(self, app_store, task_store, info):
        self.starts.append(info)
        self.start_stores.append(task_store)

    async def on_task_stop(self, app_store, task_store, info, outcome):
        self.stops.append((info, outcome))


@pytest.fixture
def _singleton():
    reset_loaded_extensions()
    yield
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


def _bridge():
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


async def _drive(record, agent, run_manager) -> None:
    await run_agent(
        _bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=InMemorySaver()),
        agent_factory=lambda *, config: agent,
        graph_input={},
        config={},
    )


class _OkAgent:
    """Captures the runtime context the worker hands the graph."""

    def __init__(self) -> None:
        self.context = None

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        self.context = (config or {}).get("context")
        yield {"messages": []}


class _TaskStoreReadingAgent:
    """Reads the task store exactly as contributed middleware does."""

    def __init__(self) -> None:
        self.task_store = None

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        runtime = (config or {})["configurable"]["__pregel_runtime"]
        self.task_store = task_store_from_runtime(runtime)
        yield {"messages": []}


class _BoomAgent:
    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        raise ValueError("agent exploded")
        yield  # pragma: no cover - makes this an async generator


@pytest.mark.anyio
async def test_run_agent_fires_start_and_stop_around_a_real_run(_singleton):
    recorder = _RunRecorder()
    _install(recorder)
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-1")
    await _drive(record, _OkAgent(), run_manager)

    assert len(recorder.starts) == 1
    assert len(recorder.stops) == 1
    info = recorder.starts[0]
    assert info.kind == "lead"
    assert info.task_id == record.run_id, "lead task is 1:1 with the run"
    assert info.thread_id == "thread-ext-1"
    assert recorder.stops[0][0].task_id == info.task_id
    assert recorder.stops[0][1] is TaskOutcome.COMPLETED


@pytest.mark.anyio
async def test_run_agent_puts_the_store_in_the_runtime_context(_singleton):
    recorder = _RunRecorder()
    _install(recorder)
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-2")
    agent = _OkAgent()
    await _drive(record, agent, run_manager)

    assert agent.context is not None
    store = agent.context[EXTENSION_TASK_STORE_KEY]
    assert store.scope_id == recorder.starts[0].task_id


@pytest.mark.anyio
async def test_run_agent_allocates_a_store_for_middleware_without_lifecycle(_singleton):
    consumer = _install_task_store_consumer("middleware")
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-middleware")
    agent = _TaskStoreReadingAgent()

    await _drive(record, agent, run_manager)

    assert agent.task_store is not None
    assert agent.task_store.scope_id == record.run_id
    assert consumer.lifecycle_events == []


@pytest.mark.anyio
async def test_run_agent_allocates_the_live_store_for_system_observers(_singleton, monkeypatch):
    from deerflow.runtime.runs import worker as worker_module

    consumer = _install_task_store_consumer("observer")
    captured: list[ExtensionData | None] = []

    async def _capture_goal_store(**kwargs):
        captured.append(kwargs.get("task_store"))
        return None

    monkeypatch.setattr(worker_module, "_prepare_goal_continuation_input", _capture_goal_store)
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-observer")
    agent = _TaskStoreReadingAgent()

    await _drive(record, agent, run_manager)

    assert agent.task_store is not None
    assert agent.task_store.scope_id == record.run_id
    assert captured == [agent.task_store]
    assert consumer.lifecycle_events == []


@pytest.mark.anyio
async def test_run_agent_reuses_the_lifecycle_store_for_goal_evaluation(_singleton, monkeypatch):
    """Goal evaluation receives the exact store installed in the run Runtime."""
    from deerflow.runtime.runs import worker as worker_module

    recorder = _RunRecorder()
    _install(recorder)
    captured: list[ExtensionData | None] = []

    async def _capture_goal_store(**kwargs):
        captured.append(kwargs.get("task_store"))
        return None

    monkeypatch.setattr(worker_module, "_prepare_goal_continuation_input", _capture_goal_store)
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-goal")
    agent = _OkAgent()

    await _drive(record, agent, run_manager)

    runtime_store = agent.context[EXTENSION_TASK_STORE_KEY]
    assert runtime_store is recorder.start_stores[0]
    assert captured == [runtime_store]


@pytest.mark.anyio
async def test_run_agent_reports_failed_when_the_agent_raises(_singleton):
    """The regression guard for the outcome classification: before it was keyed
    on success, a raising run reported COMPLETED."""
    recorder = _RunRecorder()
    _install(recorder)
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-3")
    await _drive(record, _BoomAgent(), run_manager)

    assert record.status is RunStatus.error, "guards the premise of the assertion below"
    assert recorder.stops[0][1] is TaskOutcome.FAILED


@pytest.mark.anyio
async def test_run_agent_adds_nothing_to_the_context_without_extensions(_singleton):
    """Zero-extension path, end to end."""
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-4")
    agent = _OkAgent()
    await _drive(record, agent, run_manager)

    assert EXTENSION_TASK_STORE_KEY not in (agent.context or {})


class _HardStopAgent:
    """Raises a BaseException, which neither `except` clause in run_agent catches."""

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        raise KeyboardInterrupt("host going down")
        yield  # pragma: no cover - makes this an async generator


@pytest.mark.anyio
async def test_run_agent_does_not_report_completed_when_a_base_exception_escapes(_singleton):
    """The precise regression guard for the outcome classification.

    A BaseException passes through both `except` clauses, so the run's status
    is still `running` when the finally reads it and abort_event is unset. An
    error-probe classification (`status == error`) called that COMPLETED; keying
    on success reports FAILED instead.
    """
    recorder = _RunRecorder()
    _install(recorder)
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-5")

    with pytest.raises(KeyboardInterrupt):
        await _drive(record, _HardStopAgent(), run_manager)

    assert record.status is RunStatus.running, "premise: no except clause ran, status untouched"
    assert not record.abort_event.is_set(), "premise: nothing marked this an abort"
    assert len(recorder.stops) == 1, "stop must still fire from the finally"
    assert recorder.stops[0][1] is TaskOutcome.FAILED


@pytest.mark.anyio
async def test_run_agent_notifies_stop_before_clearing_finalizing_and_ending_the_stream(_singleton):
    """Ordering guard for the interrupt multitask strategy.

    `wait_for_prior_finalizing` polls `record.finalizing`, so if this run cleared
    it before notifying stop, a replacement run could pass the barrier and fire
    its `on_task_start` while this run's `on_task_stop` was still pending — an
    extension keying state by thread_id would see two overlapping tasks.
    `publish_end` is an await, so merely preceding the notification is enough to
    open that window.
    """
    order: list[str] = []

    class _OrderRecorder(_RunRecorder):
        async def on_task_stop(self, app_store, task_store, info, outcome):
            order.append("stop")
            await super().on_task_stop(app_store, task_store, info, outcome)

    finalizing_at_stop: list[bool] = []
    recorder = _OrderRecorder()
    _install(recorder)
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-6")

    class _StopWatcher(_OrderRecorder):
        async def on_task_stop(self, app_store, task_store, info, outcome):
            # The real invariant, not a proxy: the barrier flag must still be
            # set while this notification runs.
            finalizing_at_stop.append(record.finalizing)
            await super().on_task_stop(app_store, task_store, info, outcome)

    recorder = _StopWatcher()
    _install(recorder)

    async def _note_publish_end(run_id):
        order.append("publish_end")

    # A cancelled run is the path that actually sets finalizing (the
    # `except asyncio.CancelledError` handler in run_agent), so this is the
    # only shape that can observe the clear happening too early.
    class _CancelledAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            raise asyncio.CancelledError()
            yield  # pragma: no cover - makes this an async generator

    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=_note_publish_end, cleanup=AsyncMock())
    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=InMemorySaver()),
        agent_factory=lambda *, config: _CancelledAgent(),
        graph_input={},
        config={},
    )

    assert "stop" in order
    assert order.index("stop") < order.index("publish_end"), f"stop must precede publish_end, got {order}"
    assert finalizing_at_stop == [True], "the finalizing barrier must still be held when on_task_stop runs"
    assert record.finalizing is False, "and must be cleared afterwards"


@pytest.mark.anyio
async def test_run_agent_skips_the_lifecycle_entirely_when_the_run_never_starts(_singleton):
    """The gateway deliberately enters run_agent for already-aborted runs; those
    return at the startup barrier and must produce neither a start nor a stop."""
    recorder = _RunRecorder()
    _install(recorder)
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-7")
    await run_manager.cancel(record.run_id)

    await _drive(record, _OkAgent(), run_manager)

    assert recorder.starts == [], "a run that never started must not announce one"
    assert recorder.stops == [], "and must not announce a stop either"


@pytest.mark.anyio
async def test_run_agent_propagates_the_assistant_id_as_agent_name(_singleton):
    recorder = _RunRecorder()
    _install(recorder)
    run_manager = RunManager()
    record = await run_manager.create("thread-ext-8", assistant_id="custom-agent")
    await _drive(record, _OkAgent(), run_manager)

    assert recorder.starts[0].agent_name == "custom-agent"


@pytest.mark.anyio
async def test_task_stop_budget_is_shared_and_skips_starved_contributors():
    """A hung contributor must not make the host wait forever, and must not
    silently look like it succeeded. Its successors are skipped once the shared
    budget is spent — the budget is per-notification, not per-contributor, so
    the total stays bounded however many extensions are installed."""
    reached: list[str] = []

    class _Hang:
        async def on_task_stop(self, app_store, task_store, info, outcome):
            reached.append("hang")
            await asyncio.sleep(10)

    class _Fast:
        async def on_task_stop(self, app_store, task_store, info, outcome):
            reached.append("fast")

    extensions = _extensions(_Hang(), _Fast())
    store = ExtensionData("task-1")
    loop = asyncio.get_running_loop()
    began = loop.time()
    await notify_task_stop(extensions, store, _info(), TaskOutcome.COMPLETED, timeout=0.05)
    elapsed = loop.time() - began

    assert reached == ["hang"], "the starved successor is skipped, not silently awaited"
    assert elapsed < 5, f"the hung contributor must not be awaited to completion (took {elapsed}s)"


@pytest.mark.anyio
async def test_a_malformed_contributor_cannot_abort_the_run_cleanup(_singleton):
    """Contributors are arbitrary objects — the registry does no runtime
    validation — so a plain `def` or a stale signature raises at CALL time, not
    at await time. If that escaped, run_agent's finally would skip the
    finalizing clear (wedging every later run on the thread in
    wait_for_prior_finalizing, which has no overall bound) and skip publish_end,
    leaving SSE consumers waiting for an end frame that never comes.
    """

    class _SyncContributor:
        async def on_task_start(self, app_store, task_store, info):
            return None

        def on_task_stop(self, app_store, task_store, info, outcome):  # not a coroutine
            raise RuntimeError("sync boom")

    class _WrongSignature:
        async def on_task_start(self, app_store, task_store, info):
            return None

        async def on_task_stop(self, app_store):  # stale signature
            return None

    survivor = _RunRecorder()
    registry = ExtensionRegistry()
    for index, contributor in enumerate([_SyncContributor(), _WrongSignature(), survivor]):
        with registry.attributed_to(f"ext{index}:install"):
            registry.task_lifecycle(contributor)
    set_loaded_extensions(registry.build())

    ended: list[str] = []

    async def _note_publish_end(run_id):
        ended.append(run_id)

    run_manager = RunManager()
    record = await run_manager.create("thread-ext-9")
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=_note_publish_end, cleanup=AsyncMock())
    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=InMemorySaver()),
        agent_factory=lambda *, config: _OkAgent(),
        graph_input={},
        config={},
    )

    assert ended == [record.run_id], "publish_end must still run after a malformed contributor"
    assert record.finalizing is False, "the finalizing barrier must not be stranded"
    assert len(survivor.stops) == 1, "a later well-formed contributor still gets its stop"
