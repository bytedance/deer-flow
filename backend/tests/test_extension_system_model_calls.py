"""Observation helpers for model calls made outside the agent graph."""

from __future__ import annotations

import asyncio
import threading
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

from deerflow.extensions.notify import (
    dispatch_system_model_observation,
    notify_system_model_call,
    observe_system_model_call,
    reset_extension_notify_loop,
    set_extension_notify_loop,
    suspend_extension_system_observations,
    task_store_for_system_call,
)
from deerflow.extensions.registry import ExtensionRegistry


class _Observer:
    def __init__(self) -> None:
        self.calls: list[tuple[SystemOperationKind, SystemModelRequest, SystemModelResult]] = []
        self.stores: list[ExtensionData] = []

    async def on_system_model_call(self, app_store, task_store, kind, request, result):
        self.calls.append((kind, request, result))
        self.stores.append(task_store)


def _extensions(*observers):
    registry = ExtensionRegistry()
    for index, observer in enumerate(observers):
        with registry.attributed_to(f"ext{index}:install"):
            registry.system_model_observer(observer)
    return registry.build()


@pytest.mark.asyncio
async def test_system_model_notification_reports_success_failure_and_detached_store():
    observer = _Observer()
    extensions = _extensions(observer)
    request = SystemModelRequest(messages=("prompt",), model_name="system-model")

    await notify_system_model_call(
        extensions,
        None,
        SystemOperationKind.TITLE,
        request,
        SystemModelResult(response="ok"),
    )
    error = RuntimeError("provider down")
    live_store = ExtensionData("task-1")
    await notify_system_model_call(
        extensions,
        live_store,
        SystemOperationKind.MEMORY,
        request,
        SystemModelResult(error=error),
    )

    assert [call[0] for call in observer.calls] == [
        SystemOperationKind.TITLE,
        SystemOperationKind.MEMORY,
    ]
    assert observer.calls[0][2].response == "ok"
    assert observer.calls[1][2].error is error
    assert observer.stores[0].scope_id == "detached"
    assert observer.stores[1] is live_store


@pytest.mark.asyncio
async def test_bad_observer_is_fail_open_and_does_not_hide_later_observers():
    class _Boom:
        async def on_system_model_call(self, app_store, task_store, kind, request, result):
            raise RuntimeError("observer exploded")

    survivor = _Observer()
    await notify_system_model_call(
        _extensions(_Boom(), survivor),
        ExtensionData("task"),
        SystemOperationKind.SUMMARIZATION,
        SystemModelRequest(),
        SystemModelResult(response="summary"),
    )

    assert [call[0] for call in survivor.calls] == [SystemOperationKind.SUMMARIZATION]


@pytest.mark.asyncio
async def test_observe_uses_explicit_snapshot_and_store_on_both_paths():
    observer = _Observer()
    extensions = _extensions(observer)
    store = ExtensionData("live-task")

    async def _success():
        return "answer"

    response = await observe_system_model_call(
        extensions,
        SystemOperationKind.GOAL,
        messages=("prompt",),
        model_name="goal-model",
        invoke_config={"run_name": "goal"},
        invoke=_success,
        task_store=store,
    )
    assert response == "answer"
    assert observer.stores == [store]
    assert observer.calls[0][2].response == "answer"
    assert observer.calls[0][2].duration_ms is not None

    async def _failure():
        raise ValueError("provider down")

    with pytest.raises(ValueError, match="provider down"):
        await observe_system_model_call(
            extensions,
            SystemOperationKind.GOAL,
            messages=(),
            model_name=None,
            invoke_config=None,
            invoke=_failure,
            task_store=store,
        )
    assert isinstance(observer.calls[1][2].error, ValueError)


@pytest.mark.asyncio
async def test_zero_observer_path_only_invokes_the_original_call():
    invoked: list[str] = []

    async def _call():
        invoked.append("call")
        return "ok"

    result = await observe_system_model_call(
        ExtensionRegistry().build(),
        SystemOperationKind.GOAL,
        messages=(),
        model_name=None,
        invoke_config=None,
        invoke=_call,
    )

    assert result == "ok"
    assert invoked == ["call"]


def test_task_store_fallback_reads_only_the_host_runtime_key():
    store = ExtensionData("task-1")
    assert task_store_for_system_call({"context": {EXTENSION_TASK_STORE_KEY: store}}) is store
    for value in (None, {}, {"context": None}, {"context": {}}, "bad"):
        assert task_store_for_system_call(value) is None


class _GoalModel:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def ainvoke(self, messages, config=None):
        if self.error is not None:
            raise self.error
        return AIMessage(content=('{"satisfied": true, "blocker": "none", "reason": "done", "evidence_summary": "shipped"}'))


@pytest.mark.asyncio
async def test_goal_evaluator_observes_success_and_failure_with_explicit_snapshot():
    from deerflow.runtime.goal import evaluate_goal_completion

    observer = _Observer()
    extensions = _extensions(observer)
    store = ExtensionData("goal-task")
    evidence = [
        HumanMessage(content="Ship it"),
        AIMessage(content="It is shipped"),
    ]

    await evaluate_goal_completion(
        {"objective": "ship it"},
        evidence,
        model=_GoalModel(),
        model_name="goal-model",
        task_store=store,
        extensions=extensions,
    )
    with pytest.raises(ValueError, match="provider down"):
        await evaluate_goal_completion(
            {"objective": "ship it"},
            evidence,
            model=_GoalModel(ValueError("provider down")),
            model_name="goal-model",
            task_store=store,
            extensions=extensions,
        )

    assert [call[2].error is None for call in observer.calls] == [True, False]
    assert observer.stores == [store, store]


@pytest.mark.asyncio
async def test_title_middleware_uses_build_bound_snapshot_and_live_task_store(monkeypatch):
    from deerflow.agents.middlewares import title_middleware as title_module
    from deerflow.config.title_config import TitleConfig

    observer = _Observer()
    extensions = _extensions(observer)
    store = ExtensionData("title-task")

    class _TitleModel:
        async def ainvoke(self, prompt, config=None):
            return AIMessage(content="A Good Title")

    monkeypatch.setattr(
        title_module,
        "create_chat_model",
        lambda **kwargs: _TitleModel(),
    )
    middleware = title_module.TitleMiddleware(
        title_config=TitleConfig(model_name="title-model"),
        extensions=extensions,
    )
    state = {
        "messages": [
            HumanMessage(content="Question"),
            AIMessage(content="Answer"),
        ]
    }

    result = await middleware.aafter_model(
        state,
        Runtime(context={EXTENSION_TASK_STORE_KEY: store}),
    )

    assert result == {"title": "A Good Title"}
    assert [call[0] for call in observer.calls] == [SystemOperationKind.TITLE]
    assert observer.stores == [store]
    # The title call sends one prompt string, so observers must see it whole
    # rather than as a character-by-character sequence.
    (prompt,) = observer.calls[0][1].messages
    assert isinstance(prompt, str)
    assert "Question" in prompt


@pytest.mark.asyncio
async def test_async_summarization_observes_each_provider_attempt_and_live_store():
    from deerflow.agents.middlewares.summarization_middleware import (
        DeerFlowSummarizationMiddleware,
    )

    observer = _Observer()
    extensions = _extensions(observer)
    store = ExtensionData("summary-task")

    class _Failing:
        async def ainvoke(self, prompt, config=None):
            raise RuntimeError("first provider down")

    class _Working:
        async def ainvoke(self, prompt, config=None):
            return SimpleNamespace(text="  compact summary  ")

    middleware = DeerFlowSummarizationMiddleware.__new__(DeerFlowSummarizationMiddleware)
    middleware._extensions = extensions
    middleware._prepare_summary_prompt = lambda messages, previous_summary=None: "prompt"
    middleware._generation_candidate_names = lambda: ["first", "second"]
    models = {"first": _Failing(), "second": _Working()}
    middleware._model_for = lambda name: models[name]

    result = await middleware._asummarize_with(["message"], task_store=store)

    assert result == "compact summary"
    assert [call[2].error is None for call in observer.calls] == [False, True]
    assert [call[1].model_name for call in observer.calls] == ["first", "second"]
    assert [call[1].messages for call in observer.calls] == [("prompt",), ("prompt",)]
    assert observer.stores == [store, store]


@pytest.mark.asyncio
async def test_summarization_public_hook_propagates_the_live_task_store():
    from deerflow.agents.middlewares.summarization_middleware import (
        DeerFlowSummarizationMiddleware,
    )

    observer = _Observer()
    extensions = _extensions(observer)
    store = ExtensionData("summary-live-task")
    model = MagicMock()
    model.with_config.return_value = model
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(text="compressed"))
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
        extensions=extensions,
    )
    state = {
        "messages": [
            HumanMessage(content="user-1"),
            AIMessage(content="assistant-1"),
            HumanMessage(content="user-2"),
            AIMessage(content="assistant-2"),
        ]
    }

    result = await middleware.abefore_model(
        state,
        Runtime(context={EXTENSION_TASK_STORE_KEY: store}),
    )

    assert result is not None
    assert observer.stores == [store]


@pytest.mark.asyncio
async def test_memory_callback_dispatches_the_captured_snapshot_and_live_store():
    from deerflow.agents.memory.manager import LangfuseMemoryCallbacks
    from deerflow.extensions import reset_loaded_extensions, set_loaded_extensions

    first = _Observer()
    second = _Observer()
    captured = _extensions(first)
    replacement = _extensions(second)
    store = ExtensionData("memory-task")
    loop = asyncio.get_running_loop()
    set_extension_notify_loop(loop)
    try:
        callback = LangfuseMemoryCallbacks(extensions=captured)
        set_loaded_extensions(replacement)
        callback.on_memory_llm_result(
            {"context": {EXTENSION_TASK_STORE_KEY: store}},
            prompt=("memory prompt",),
            response="memory response",
            error=None,
            duration_ms=12.5,
            model_name="memory-model",
        )
        for _ in range(20):
            if first.calls:
                break
            await asyncio.sleep(0)
    finally:
        reset_extension_notify_loop()
        reset_loaded_extensions()

    assert [call[0] for call in first.calls] == [SystemOperationKind.MEMORY]
    assert first.calls[0][1].messages == ("memory prompt",)
    assert first.calls[0][2].response == "memory response"
    assert first.calls[0][2].duration_ms == 12.5
    assert first.stores == [store]
    assert second.calls == []


@pytest.fixture
def _notification_loop_state():
    reset_extension_notify_loop()
    yield
    reset_extension_notify_loop()


class _RunningLoop:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        assert self._ready.wait(2)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self._ready.set)
        self.loop.run_forever()

    def stop(self) -> None:
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(2)

    def close(self) -> None:
        self.stop()
        if not self.loop.is_closed():
            self.loop.close()


def _wait_for_calls(observer: _Observer, expected: int = 1) -> None:
    deadline = time.monotonic() + 2
    while len(observer.calls) < expected and time.monotonic() < deadline:
        threading.Event().wait(0.01)


def test_detached_observation_dispatches_to_the_registered_loop(
    _notification_loop_state,
):
    observed_loops: list[asyncio.AbstractEventLoop] = []

    class _LoopObserver(_Observer):
        async def on_system_model_call(self, app_store, task_store, kind, request, result):
            observed_loops.append(asyncio.get_running_loop())
            await super().on_system_model_call(app_store, task_store, kind, request, result)

    observer = _LoopObserver()
    host = _RunningLoop()
    set_extension_notify_loop(host.loop)
    try:
        submitted = dispatch_system_model_observation(
            notify_system_model_call(
                _extensions(observer),
                None,
                SystemOperationKind.MEMORY,
                SystemModelRequest(),
                SystemModelResult(response="ok"),
            ),
            "memory",
        )
        _wait_for_calls(observer)
    finally:
        host.close()

    assert submitted is True
    assert observed_loops == [host.loop]


def test_awaited_observation_from_an_isolated_loop_uses_registered_loop(
    _notification_loop_state,
):
    observed_loops: list[asyncio.AbstractEventLoop] = []

    class _LoopObserver:
        async def on_system_model_call(self, app_store, task_store, kind, request, result):
            observed_loops.append(asyncio.get_running_loop())

    host = _RunningLoop()
    set_extension_notify_loop(host.loop)
    try:
        asyncio.run(
            notify_system_model_call(
                _extensions(_LoopObserver()),
                None,
                SystemOperationKind.SUMMARIZATION,
                SystemModelRequest(),
                SystemModelResult(response="ok"),
            )
        )
    finally:
        host.close()

    assert observed_loops == [host.loop]


def test_detached_observation_drops_when_loop_is_missing_stopped_or_suspended(
    _notification_loop_state,
):
    observer = _Observer()
    extensions = _extensions(observer)

    assert (
        dispatch_system_model_observation(
            notify_system_model_call(
                extensions,
                None,
                SystemOperationKind.MEMORY,
                SystemModelRequest(),
                SystemModelResult(response="missing"),
            ),
            "missing-loop",
        )
        is False
    )

    host = _RunningLoop()
    set_extension_notify_loop(host.loop)
    host.stop()
    assert not host.loop.is_closed()
    assert (
        dispatch_system_model_observation(
            notify_system_model_call(
                extensions,
                None,
                SystemOperationKind.MEMORY,
                SystemModelRequest(),
                SystemModelResult(response="stopped"),
            ),
            "stopped-loop",
        )
        is False
    )
    host.loop.close()

    active = _RunningLoop()
    set_extension_notify_loop(active.loop)
    suspend_extension_system_observations()
    try:
        assert (
            dispatch_system_model_observation(
                notify_system_model_call(
                    extensions,
                    None,
                    SystemOperationKind.MEMORY,
                    SystemModelRequest(),
                    SystemModelResult(response="suspended"),
                ),
                "suspended-loop",
            )
            is False
        )
    finally:
        active.close()

    assert observer.calls == []


def test_detached_observation_ignores_the_callers_other_running_loop(
    _notification_loop_state,
):
    observed_loops: list[asyncio.AbstractEventLoop] = []

    class _LoopObserver:
        async def on_system_model_call(self, app_store, task_store, kind, request, result):
            observed_loops.append(asyncio.get_running_loop())

    registered = _RunningLoop()
    other = _RunningLoop()
    set_extension_notify_loop(registered.loop)

    async def _dispatch_from_other() -> None:
        assert dispatch_system_model_observation(
            notify_system_model_call(
                _extensions(_LoopObserver()),
                None,
                SystemOperationKind.MEMORY,
                SystemModelRequest(),
                SystemModelResult(response="ok"),
            ),
            "memory-from-other-loop",
        )

    try:
        asyncio.run_coroutine_threadsafe(_dispatch_from_other(), other.loop).result(2)
        deadline = time.monotonic() + 2
        while not observed_loops and time.monotonic() < deadline:
            threading.Event().wait(0.01)
    finally:
        other.close()
        registered.close()

    assert observed_loops == [registered.loop]
