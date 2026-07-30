"""Tests for observing model calls made outside the agent graph.

Coverage boundary (deviation from the plan — see the task report). The plan
named five call sites. Four are covered:

- async: ``runtime/goal.py``, ``title_middleware.py``,
  ``summarization_middleware.py::_asummarize_with``
- sync:  the DeerMem memory update, via the host-owned ``MemoryCallbacks`` seam

The fifth, ``DeerFlowSummarizationMiddleware._summarize_with``, is deliberately
NOT wired. It is unreachable in the Gateway and in subagents — the middleware
overrides both ``before_model`` and ``abefore_model``, so the async graph always
takes the async path — and its only live host is ``DeerFlowClient.stream()``,
which registers no loop to dispatch on. Wiring it would buy nothing.

The DeerMem site cannot use the async helper: it runs on a debounce timer thread
with no event loop, and its sync-ness is deliberate (its own docstring says the
sync path exists so "no second event loop is created", the fix for issue #2615's
cross-loop reuse of the shared async httpx pool). So the observation is handed
to the host's registered loop instead — see
``extensions.notify.dispatch_system_model_observation``.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from deerflow_extension_api import (
    EXTENSION_TASK_STORE_KEY,
    ExtensionData,
    SystemModelRequest,
    SystemModelResult,
    SystemOperationKind,
)
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.extensions import reset_loaded_extensions, set_loaded_extensions
from deerflow.extensions.notify import notify_system_model_call, observe_system_model_call, task_store_for_system_call
from deerflow.extensions.registry import ExtensionRegistry

# evaluate_goal_completion short-circuits to `missing_evidence` before it ever
# builds a model when there is no visible assistant evidence, so the plan's
# `messages=[]` never reached the call site under test.
_EVIDENCE = [HumanMessage(content="ship it"), AIMessage(content="I shipped it.")]


class _Observer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.results: list[SystemModelResult] = []
        self.requests: list[SystemModelRequest] = []
        self.stores: list[ExtensionData] = []

    async def on_system_model_call(self, app_store, task_store, kind, request, result):
        self.calls.append((kind.value, result.error is None))
        self.results.append(result)
        self.requests.append(request)
        self.stores.append(task_store)


class _Boom:
    async def on_system_model_call(self, app_store, task_store, kind, request, result):
        raise ValueError("observer exploded")


def _extensions(*observers):
    registry = ExtensionRegistry()
    for index, observer in enumerate(observers):
        with registry.attributed_to(f"ext{index}:install"):
            registry.system_model_observer(observer)
    return registry.build()


@pytest.fixture
def _singleton():
    reset_loaded_extensions()
    yield
    reset_loaded_extensions()


def _install(observer) -> None:
    set_loaded_extensions(_extensions(observer))


def test_all_four_kinds_are_representable():
    assert {k.value for k in SystemOperationKind} == {"goal", "memory", "title", "summarization"}


def test_success_is_reported():
    observer = _Observer()
    asyncio.run(
        notify_system_model_call(
            _extensions(observer),
            ExtensionData("t"),
            SystemOperationKind.GOAL,
            SystemModelRequest(),
            SystemModelResult(response="ok"),
        )
    )
    assert observer.calls == [("goal", True)]


def test_failure_is_reported_too():
    """A system call that raised is exactly the event an observability
    extension most needs; notifying only on success would hide it."""
    observer = _Observer()
    asyncio.run(
        notify_system_model_call(
            _extensions(observer),
            ExtensionData("t"),
            SystemOperationKind.MEMORY,
            SystemModelRequest(),
            SystemModelResult(error=ValueError("nope")),
        )
    )
    assert observer.calls == [("memory", False)]


def test_missing_task_store_is_tolerated():
    """Some system calls run with no live task (e.g. title generation on a
    detached path); the observer still gets called with an empty store."""
    observer = _Observer()
    asyncio.run(
        notify_system_model_call(
            _extensions(observer),
            None,
            SystemOperationKind.TITLE,
            SystemModelRequest(),
            SystemModelResult(response="ok"),
        )
    )
    assert observer.calls == [("title", True)]
    assert observer.stores[0].scope_id == "detached"


def test_one_failing_observer_does_not_stop_the_others():
    observer = _Observer()
    asyncio.run(
        notify_system_model_call(
            _extensions(_Boom(), observer),
            ExtensionData("t"),
            SystemOperationKind.SUMMARIZATION,
            SystemModelRequest(),
            SystemModelResult(response="ok"),
        )
    )
    assert observer.calls == [("summarization", True)]


def test_zero_observers_is_a_no_op():
    asyncio.run(
        notify_system_model_call(
            ExtensionRegistry().build(),
            ExtensionData("t"),
            SystemOperationKind.GOAL,
            SystemModelRequest(),
            SystemModelResult(response="ok"),
        )
    )


def test_task_store_is_recovered_from_the_invoke_config():
    """Direct/legacy callers retain the top-level RunnableConfig fallback."""
    store = ExtensionData("task-1")
    config = {"context": {EXTENSION_TASK_STORE_KEY: store}}
    assert task_store_for_system_call(config) is store


@pytest.mark.parametrize("config", [None, {}, {"context": None}, {"context": {}}, "not-a-config"])
def test_task_store_lookup_tolerates_every_shape(config):
    assert task_store_for_system_call(config) is None


# --- observe_system_model_call ---------------------------------------------


def test_observe_returns_the_response_and_reports_success(_singleton):
    observer = _Observer()
    _install(observer)

    async def _call():
        return "the answer"

    got = asyncio.run(
        observe_system_model_call(
            SystemOperationKind.TITLE,
            messages=["m"],
            model_name="gpt-4o",
            invoke_config={"run_name": "title"},
            invoke=_call,
        )
    )
    assert got == "the answer"
    assert observer.calls == [("title", True)]
    assert observer.results[0].response == "the answer"
    assert observer.requests[0].model_name == "gpt-4o"
    assert observer.results[0].duration_ms is not None


def test_observe_uses_the_explicit_live_task_store(_singleton):
    """The host's live task store wins over any stale config-derived value."""
    observer = _Observer()
    _install(observer)
    live_store = ExtensionData("live-task")
    config_store = ExtensionData("config-task")

    async def _call():
        return "ok"

    asyncio.run(
        observe_system_model_call(
            SystemOperationKind.TITLE,
            messages=[],
            model_name=None,
            invoke_config={"context": {EXTENSION_TASK_STORE_KEY: config_store}},
            invoke=_call,
            task_store=live_store,
        )
    )

    assert observer.stores == [live_store]


def test_observe_reports_failure_and_re_raises(_singleton):
    """Observation is additive: the call's own error handling must be
    unchanged, so the exception still propagates after the notification."""
    observer = _Observer()
    _install(observer)

    async def _call():
        raise ValueError("provider down")

    with pytest.raises(ValueError, match="provider down"):
        asyncio.run(
            observe_system_model_call(
                SystemOperationKind.MEMORY,
                messages=[],
                model_name=None,
                invoke_config=None,
                invoke=_call,
            )
        )
    assert observer.calls == [("memory", False)]
    assert isinstance(observer.results[0].error, ValueError)


def test_observe_does_nothing_measurable_without_observers(_singleton):
    """Zero-extension path: the original call runs and nothing else does."""
    calls: list[int] = []

    async def _call():
        calls.append(1)
        return "ok"

    got = asyncio.run(
        observe_system_model_call(
            SystemOperationKind.GOAL,
            messages=[],
            model_name=None,
            invoke_config=None,
            invoke=_call,
        )
    )
    assert got == "ok"
    assert calls == [1]


# --- real call sites --------------------------------------------------------


class _FakeModel:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.calls = 0

    async def ainvoke(self, messages, config=None):
        self.calls += 1
        if self._error is not None:
            raise self._error

        class _Response:
            content = '{"satisfied": true, "blocker": "none", "reason": "done", "evidence_summary": "x"}'

        return _Response()


def test_goal_call_site_notifies_on_success(_singleton):
    """Drives the real evaluate_goal_completion path: a refactor that drops the
    notification fails here rather than silently losing observations."""
    from deerflow.runtime.goal import evaluate_goal_completion

    observer = _Observer()
    _install(observer)
    store = ExtensionData("goal-task")
    asyncio.run(
        evaluate_goal_completion(
            {"objective": "ship it"},
            _EVIDENCE,
            model=_FakeModel(),
            model_name="gpt-4o",
            thread_id="t",
            user_id="u",
            task_store=store,
        )
    )
    assert observer.calls == [("goal", True)]
    assert observer.stores == [store]


def test_goal_call_site_notifies_on_failure(_singleton):
    """The failing system call is exactly the event an observability extension
    most needs; notifying only on success would hide it."""
    from deerflow.runtime.goal import evaluate_goal_completion

    observer = _Observer()
    _install(observer)
    with pytest.raises(ValueError):
        asyncio.run(
            evaluate_goal_completion(
                {"objective": "ship it"},
                _EVIDENCE,
                model=_FakeModel(error=ValueError("provider down")),
                model_name="gpt-4o",
                thread_id="t",
                user_id="u",
            )
        )
    assert observer.calls == [("goal", False)]


def test_summarization_call_site_notifies(_singleton):
    """The async summarization path is wired; its sync sibling is not (see the
    module docstring)."""
    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

    observer = _Observer()
    _install(observer)

    class _SummaryModel:
        async def ainvoke(self, prompt, config=None):
            class _R:
                text = "  a summary  "

            return _R()

    # Stubbed at the boundaries the observed call sits between: prompt
    # preparation and candidate-model resolution. The observation lives in
    # `_ainvoke_summary`, the single place the async provider call happens, so a
    # candidate that fails is still reported rather than hidden by the fallback.
    middleware = DeerFlowSummarizationMiddleware.__new__(DeerFlowSummarizationMiddleware)
    middleware._prepare_summary_prompt = lambda messages, previous_summary=None: "prompt"
    middleware._generation_candidate_names = lambda: [None]
    middleware._model_for = lambda name: _SummaryModel()

    got = asyncio.run(middleware._asummarize_with(["m"]))
    assert got == "a summary"
    assert observer.calls == [("summarization", True)]


def test_summarization_reports_a_failed_candidate_before_falling_back(_singleton):
    """A candidate that raises is a system model call an observer must still see;
    the fallback to the next candidate must not swallow it."""
    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

    observer = _Observer()
    _install(observer)

    class _Failing:
        model_name = "first"

        async def ainvoke(self, prompt, config=None):
            raise RuntimeError("provider is down")

    class _Working:
        model_name = "second"

        async def ainvoke(self, prompt, config=None):
            class _R:
                text = "  a summary  "

            return _R()

    models = {"first": _Failing(), "second": _Working()}
    middleware = DeerFlowSummarizationMiddleware.__new__(DeerFlowSummarizationMiddleware)
    middleware._prepare_summary_prompt = lambda messages, previous_summary=None: "prompt"
    middleware._generation_candidate_names = lambda: ["first", "second"]
    middleware._model_for = lambda name: models[name]

    got = asyncio.run(middleware._asummarize_with(["m"]))

    assert got == "a summary"
    assert observer.calls == [("summarization", False), ("summarization", True)]


def test_summarization_public_hook_propagates_the_live_task_store(_singleton):
    """Async compaction observes with the task store from its live Runtime."""
    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

    observer = _Observer()
    _install(observer)
    store = ExtensionData("summary-task")
    model = MagicMock()
    model.with_config.return_value = model
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(text="compressed"))
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )
    state = {
        "messages": [
            HumanMessage(content="user-1"),
            AIMessage(content="assistant-1"),
            HumanMessage(content="user-2"),
            AIMessage(content="assistant-2"),
        ]
    }
    runtime = Runtime(context={EXTENSION_TASK_STORE_KEY: store})

    result = asyncio.run(middleware.abefore_model(state, runtime))

    assert result is not None
    assert observer.stores == [store]


def test_title_public_hook_propagates_the_live_task_store(_singleton, monkeypatch):
    """The title observation uses the task store from its live Runtime."""
    from deerflow.agents.middlewares import title_middleware as title_module
    from deerflow.config.title_config import TitleConfig

    observer = _Observer()
    _install(observer)
    store = ExtensionData("title-task")

    class _TitleModel:
        async def ainvoke(self, prompt, config=None):
            return AIMessage(content="A Good Title")

    monkeypatch.setattr(title_module, "create_chat_model", lambda **kwargs: _TitleModel())

    middleware = title_module.TitleMiddleware(
        title_config=TitleConfig(model_name="gpt-4o"),
    )
    state = {
        "messages": [
            HumanMessage(content="Question"),
            AIMessage(content="Answer"),
        ]
    }

    result = asyncio.run(
        middleware.aafter_model(
            state,
            Runtime(context={EXTENSION_TASK_STORE_KEY: store}),
        )
    )

    assert result == {"title": "A Good Title"}
    assert observer.calls == [("title", True)]
    assert observer.stores == [store]


async def _noop_observation() -> None:
    """A stand-in for a real notification coroutine, for dispatcher tests."""
    return None


# --- the synchronous (DeerMem) path -----------------------------------------
#
# These target the production wiring: MemoryUpdater -> MemoryCallbacks
# .on_memory_llm_result -> dispatch_system_model_observation -> the registered
# loop. The dispatcher is exercised directly for the loop-state failure modes,
# which are the ones that would hang or silently drop.

import threading  # noqa: E402

from deerflow.agents.memory.manager import LangfuseMemoryCallbacks, MemoryCallbacks  # noqa: E402
from deerflow.extensions.notify import (  # noqa: E402
    dispatch_system_model_observation,
    reset_extension_notify_loop,
    set_extension_notify_loop,
    suspend_extension_system_observations,
)


@pytest.fixture
def _loop_registry():
    reset_loaded_extensions()
    reset_extension_notify_loop()
    yield
    reset_extension_notify_loop()
    reset_loaded_extensions()


class _RunningLoop:
    """A real event loop running on its own thread, like the Gateway's."""

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

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(5)

    def close(self) -> None:
        self.stop()
        self.loop.close()


def test_awaited_system_observer_runs_on_the_registered_extension_loop(_loop_registry):
    host = _RunningLoop()
    observed_loops: list[asyncio.AbstractEventLoop] = []

    class _LoopBoundObserver:
        async def on_system_model_call(self, app_store, task_store, kind, request, result):
            loop = asyncio.get_running_loop()
            if loop is not host.loop:
                raise RuntimeError("loop-bound observer used from an isolated loop")
            observed_loops.append(loop)

    set_extension_notify_loop(host.loop)
    try:
        asyncio.run(
            notify_system_model_call(
                _extensions(_LoopBoundObserver()),
                ExtensionData("task"),
                SystemOperationKind.SUMMARIZATION,
                SystemModelRequest(),
                SystemModelResult(response="summary"),
            )
        )
    finally:
        host.close()

    assert observed_loops == [host.loop]


def _await_calls(observer, *, expected: int = 1, timeout: float = 5.0) -> bool:
    """Wait for a fire-and-forget dispatch to land, without a fixed sleep."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(observer.calls) >= expected:
            return True
        threading.Event().wait(0.005)
    return False


def _memory_result(callbacks, *, response="ok", error=None) -> None:
    callbacks.on_memory_llm_result(
        {"run_name": "memory_agent"},
        prompt="the prompt",
        response=response,
        error=error,
        duration_ms=1.5,
        model_name="memory-model",
    )


def test_memory_callback_reaches_an_observer_on_the_registered_loop(_loop_registry):
    observer = _Observer()
    _install(observer)
    host = _RunningLoop()
    set_extension_notify_loop(host.loop)
    try:
        _memory_result(LangfuseMemoryCallbacks())
        assert _await_calls(observer), "observation never arrived"
    finally:
        host.close()

    assert observer.calls == [("memory", True)]
    assert observer.requests[0].model_name == "memory-model"
    assert observer.results[0].duration_ms == 1.5


def test_memory_callback_reports_the_failure_path(_loop_registry):
    observer = _Observer()
    _install(observer)
    host = _RunningLoop()
    set_extension_notify_loop(host.loop)
    try:
        _memory_result(LangfuseMemoryCallbacks(), response=None, error=ValueError("provider down"))
        assert _await_calls(observer)
    finally:
        host.close()

    assert observer.calls == [("memory", False)]
    assert isinstance(observer.results[0].error, ValueError)


def test_memory_callback_is_inert_without_observers(_loop_registry):
    """Short-circuits before touching the loop: this runs on every memory
    update whether or not any extension is installed."""
    touched: list[str] = []

    class _RecordingLoop:
        def is_running(self):
            touched.append("is_running")
            return False

    set_extension_notify_loop(_RecordingLoop())
    _memory_result(LangfuseMemoryCallbacks())
    assert touched == [], "the zero-observer path must not consult the loop at all"


def test_updater_fires_the_result_hook_on_both_paths(_loop_registry):
    """End-to-end through the real MemoryUpdater, so the two call sites in
    updater.py are gated by a test rather than by inspection."""
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
    from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

    class _RecordingCallbacks(MemoryCallbacks):
        def __init__(self) -> None:
            self.results: list[tuple[bool, str | None, object]] = []

        def on_memory_llm_result(self, invoke_config, *, prompt, response, error, duration_ms, model_name):
            self.results.append((error is None, model_name, prompt))

    class _Model:
        def __init__(self, *, error=None):
            self._error = error

        def invoke(self, prompt, config=None):
            if self._error:
                raise self._error

            class _R:
                content = "{}"

            return _R()

    config = DeerMemConfig(model={"provider": "openai", "model": "gpt-x", "api_key": "k", "base_url": "u"})

    for error, expected_ok in ((None, True), (ValueError("provider down"), False)):
        callbacks = _RecordingCallbacks()
        updater = MemoryUpdater(config, storage=SimpleNamespace(), llm=_Model(error=error), callbacks=callbacks)
        updater._prepare_update_prompt = lambda **kw: ({}, "the prompt")
        updater._finalize_update = lambda **kw: True

        # A non-empty feed is required, not incidental: the updater short-circuits
        # on `not feed_messages` before it ever builds a model, so an empty list
        # would make this test pass without reaching the call site it guards.
        updater._do_update_memory_sync(
            messages=[HumanMessage(content="remember this")],
            thread_id="t",
            agent_name=None,
            signals=frozenset(),
            user_id="u",
            trace_id="tr",
        )

        assert len(callbacks.results) == 1, f"hook did not fire for error={error!r}"
        ok, model_name, prompt = callbacks.results[0]
        assert ok is expected_ok
        assert model_name == "gpt-x"
        assert prompt == "the prompt"


def test_dispatch_drops_when_the_loop_is_stopped_but_not_closed(_loop_registry):
    """The mode that would hang. `is_closed()` reports False for a stopped loop
    and `run_coroutine_threadsafe` accepts the submission but never resolves it,
    so a blocking wait would wedge the memory queue for the process lifetime."""
    observer = _Observer()
    _install(observer)
    host = _RunningLoop()
    set_extension_notify_loop(host.loop)
    host.stop()
    assert not host.loop.is_closed(), "premise: stopped, not closed"
    try:
        submitted = dispatch_system_model_observation(_noop_observation(), "memory")
    finally:
        host.loop.close()
    assert submitted is False
    assert observer.calls == []


def test_dispatch_survives_a_closed_loop(_loop_registry):
    host = _RunningLoop()
    set_extension_notify_loop(host.loop)
    host.close()
    assert dispatch_system_model_observation(_noop_observation(), "memory") is False


def test_dispatch_without_a_registered_loop_is_a_no_op(_loop_registry):
    assert dispatch_system_model_observation(_noop_observation(), "memory") is False


def test_suspended_system_observations_are_dropped_with_a_registered_loop(_loop_registry):
    host = _RunningLoop()
    set_extension_notify_loop(host.loop)
    suspend_extension_system_observations()
    try:
        assert dispatch_system_model_observation(_noop_observation(), "memory") is False
    finally:
        host.close()


def test_suspend_without_a_registered_loop_is_a_no_op(_loop_registry):
    """No runtime owns reset when tests/embedded hosts replace it with a noop."""
    from deerflow.extensions import notify as notify_module

    suspend_extension_system_observations()

    assert notify_module._system_observations_enabled is True


def test_dispatch_never_uses_the_callers_running_loop(_loop_registry):
    """This process has several long-lived loops (Gateway, the isolated subagent
    loop, BoxLite's). Dispatching to whichever is current on the calling thread
    is the cross-loop bug this mechanism exists to avoid.

    The call is made from *inside* the other loop's thread via
    call_soon_threadsafe, so `get_running_loop()` there really does return the
    wrong loop — an executor thread would merely raise RuntimeError and the test
    would pass for the wrong reason.
    """
    ran_on: list[object] = []

    class _LoopCapturingObserver:
        async def on_system_model_call(self, app_store, task_store, kind, request, result):
            ran_on.append(asyncio.get_running_loop())

    set_loaded_extensions(_extensions(_LoopCapturingObserver()))
    registered = _RunningLoop()
    other = _RunningLoop()
    set_extension_notify_loop(registered.loop)
    done = threading.Event()

    def _from_inside_the_other_loop():
        assert asyncio.get_running_loop() is other.loop, "premise: a real, wrong, running loop"
        _memory_result(LangfuseMemoryCallbacks())
        done.set()

    try:
        other.loop.call_soon_threadsafe(_from_inside_the_other_loop)
        assert done.wait(5)
        deadline = time.monotonic() + 5
        while not ran_on and time.monotonic() < deadline:
            threading.Event().wait(0.005)
    finally:
        other.close()
        registered.close()

    assert ran_on == [registered.loop], "the observation must run on the registered loop, not the caller's"
