from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from deerflow_extension_api import EXTENSION_TASK_STORE_KEY, ExtensionData, TaskInfo, TaskOutcome
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt

from deerflow_extension_example.plugin import ExampleMiddleware, ExampleStats, ExampleTaskLifecycle


def task_context():
    app = ExtensionData("app")
    task = ExtensionData("task")
    info = TaskInfo(task_id="task", run_id="run", thread_id="thread", kind="lead")
    lifecycle = ExampleTaskLifecycle()
    asyncio.run(lifecycle.on_task_start(app, task, info))
    request = SimpleNamespace(runtime=SimpleNamespace(context={EXTENSION_TASK_STORE_KEY: task}))
    return app, task, info, lifecycle, request


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("outcome", ["returned", "raised", "interrupt"])
def test_preserves_result_exception_and_single_invocation(asynchronous, outcome):
    app, task, info, lifecycle, request = task_context()
    result = ToolMessage(content="tool reported an error", tool_call_id="call", status="error")
    error = GraphInterrupt(()) if outcome == "interrupt" else ValueError("tool failed")
    calls = []

    def handler(received):
        calls.append(received)
        if outcome != "returned":
            raise error
        return result

    async def async_handler(received):
        return handler(received)

    def invoke():
        middleware = ExampleMiddleware()
        if asynchronous:
            return asyncio.run(middleware.awrap_tool_call(request, async_handler))
        return middleware.wrap_tool_call(request, handler)

    with patch("deerflow_extension_example.plugin.monotonic_ns", side_effect=[0, 10_000_000], create=True):
        if outcome == "returned":
            assert invoke() is result
        else:
            with pytest.raises(type(error)) as caught:
                invoke()
            assert caught.value is error
    assert len(calls) == 1 and calls[0] is request
    asyncio.run(lifecycle.on_task_stop(app, task, info, TaskOutcome.COMPLETED))
    snapshot = app.get(ExampleStats).snapshot()
    assert snapshot["tool_calls"] == 1
    assert snapshot["tool_outcomes"] == {"returned": int(outcome == "returned"), "raised": int(outcome != "returned"), "cancelled": 0}
    assert snapshot["tool_duration_samples"] == 1
    assert snapshot["tool_duration_total_ms"] == 10.0


def test_actual_task_cancellation_propagates_and_is_counted():
    app, task, info, lifecycle, request = task_context()
    errors = []
    calls = []

    async def exercise():
        entered = asyncio.Event()

        async def handler(received):
            calls.append(received)
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError as error:
                errors.append(error)
                raise

        running = asyncio.create_task(ExampleMiddleware().awrap_tool_call(request, handler))
        await entered.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError) as caught:
            await running
        assert caught.value is errors[0]
        assert running.cancelled()
        await lifecycle.on_task_stop(app, task, info, TaskOutcome.ABORTED)

    with patch("deerflow_extension_example.plugin.monotonic_ns", side_effect=[0, 20_000_000], create=True):
        asyncio.run(exercise())
    assert len(calls) == 1 and calls[0] is request
    snapshot = app.get(ExampleStats).snapshot()
    assert snapshot["tool_outcomes"] == {"returned": 0, "raised": 0, "cancelled": 1}
    assert snapshot["tool_duration_samples"] == 1
    assert snapshot["tool_duration_total_ms"] == 20.0


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("scope", ["no-runtime", "no-store", "not-started"])
def test_missing_task_scope_passes_through(asynchronous, scope):
    request = SimpleNamespace()
    if scope != "no-runtime":
        request.runtime = SimpleNamespace(context={})
    if scope == "not-started":
        request.runtime.context[EXTENSION_TASK_STORE_KEY] = ExtensionData("unused")
    calls = []
    result = object()

    def handler(received):
        calls.append(received)
        return result

    async def async_handler(received):
        return handler(received)

    middleware = ExampleMiddleware()
    if asynchronous:
        assert asyncio.run(middleware.awrap_tool_call(request, async_handler)) is result
    else:
        assert middleware.wrap_tool_call(request, handler) is result
    assert len(calls) == 1 and calls[0] is request


def test_concurrent_sync_calls_and_duplicate_finalization():
    app, task, info, lifecycle, request = task_context()
    barrier = Barrier(8)

    def handler(received):
        assert received is request
        barrier.wait(timeout=10)
        return received

    def invoke(_):
        assert ExampleMiddleware().wrap_tool_call(request, handler) is request

    # A constant clock also verifies that zero durations still produce samples.
    with patch("deerflow_extension_example.plugin.monotonic_ns", return_value=42, create=True):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(invoke, range(8)))
    assert app.get(ExampleStats) is None

    def finalize(_):
        asyncio.run(lifecycle.on_task_stop(app, task, info, TaskOutcome.COMPLETED))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(finalize, range(4)))
    snapshot = app.get(ExampleStats).snapshot()
    assert snapshot["tasks"] == {"completed": 1}
    assert snapshot["tool_calls"] == 8
    assert snapshot["tool_outcomes"] == {"returned": 8, "raised": 0, "cancelled": 0}
    assert snapshot["tool_duration_samples"] == 8
    assert snapshot["tool_duration_total_ms"] == 0.0
    snapshot["tool_outcomes"]["returned"] = -1
    assert app.get(ExampleStats).snapshot()["tool_outcomes"]["returned"] == 8


def test_overlapping_async_calls_merge_outcomes_and_elapsed_time():
    app, task, info, lifecycle, request = task_context()

    async def exercise():
        ready = asyncio.Event()
        entered = 0

        async def handler(_):
            nonlocal entered
            entered += 1
            number = entered
            if entered == 3:
                ready.set()
            await ready.wait()
            if number == 2:
                raise ValueError("failed")
            return number

        results = await asyncio.gather(*(ExampleMiddleware().awrap_tool_call(request, handler) for _ in range(3)), return_exceptions=True)
        assert sum(isinstance(result, ValueError) for result in results) == 1
        await lifecycle.on_task_stop(app, task, info, TaskOutcome.COMPLETED)

    # Three starts at zero, then completions after 10, 20 and 30 milliseconds.
    with patch("deerflow_extension_example.plugin.monotonic_ns", side_effect=[0, 0, 0, 10_000_000, 20_000_000, 30_000_000], create=True):
        asyncio.run(exercise())
    snapshot = app.get(ExampleStats).snapshot()
    assert snapshot["tool_calls"] == 3
    assert snapshot["tool_outcomes"] == {"returned": 2, "raised": 1, "cancelled": 0}
    assert snapshot["tool_duration_samples"] == 3
    assert snapshot["tool_duration_total_ms"] == 60.0


def test_multiple_task_stores_merge_once_and_unstarted_stop_is_ignored():
    app, task, info, lifecycle, request = task_context()
    second = ExtensionData("second")
    unstarted = ExtensionData("unstarted")

    async def exercise():
        await lifecycle.on_task_stop(app, unstarted, info, TaskOutcome.FAILED)
        assert app.get(ExampleStats) is None
        await lifecycle.on_task_start(app, second, info)

        async def handler(_):
            return None

        await ExampleMiddleware().awrap_tool_call(request, handler)
        await lifecycle.on_task_stop(app, task, info, TaskOutcome.COMPLETED)
        first_snapshot = app.get(ExampleStats).snapshot()
        await lifecycle.on_task_stop(app, task, info, TaskOutcome.FAILED)
        assert app.get(ExampleStats).snapshot() == first_snapshot
        second_request = SimpleNamespace(runtime=SimpleNamespace(context={EXTENSION_TASK_STORE_KEY: second}))
        await ExampleMiddleware().awrap_tool_call(second_request, handler)
        await lifecycle.on_task_stop(app, second, info, TaskOutcome.ABORTED)

    with patch("deerflow_extension_example.plugin.monotonic_ns", side_effect=[0, 10_000_000, 0, 20_000_000]):
        asyncio.run(exercise())
    snapshot = app.get(ExampleStats).snapshot()
    assert snapshot["tasks"] == {"completed": 1, "aborted": 1}
    assert snapshot["tool_calls"] == 2
    assert snapshot["tool_outcomes"] == {"returned": 2, "raised": 0, "cancelled": 0}
    assert snapshot["tool_duration_samples"] == 2
    assert snapshot["tool_duration_total_ms"] == 30.0
