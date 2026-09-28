"""Production middleware regressions for the executor isolation in #3427."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deerflow.agents.memory import MemoryReadError
from deerflow.agents.middlewares import dynamic_context_middleware as context_module
from deerflow.utils import context_io


@pytest.fixture
def context_pool(monkeypatch):
    pool = context_io._ContextInjectionPool(max_workers=2)
    monkeypatch.setattr(context_io, "_CONTEXT_POOL", pool)
    try:
        yield pool
    finally:
        pool.shutdown(wait=True)


def test_timed_out_injections_do_not_starve_default_executor(monkeypatch, context_pool):
    """Abandoned injection workers must not queue unrelated handler work."""

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=2))
        release = threading.Event()
        started = [asyncio.Event(), asyncio.Event()]
        finished = [threading.Event(), threading.Event()]
        calls = []

        async def timeout_after_workers_start(awaitable, *, timeout):
            # Exercise real wait_for cancellation, but only after both workers
            # have started. No scheduler-speed assumption or slow network call.
            task = asyncio.ensure_future(awaitable)
            try:
                await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started)), 5)
                return await asyncio.wait_for(task, timeout=0)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        # Replace this module's reference, never mutate the shared asyncio module.
        monkeypatch.setattr(
            context_module,
            "asyncio",
            SimpleNamespace(to_thread=asyncio.to_thread, wait_for=timeout_after_workers_start),
        )

        def make_injection(index):
            def inject(*_args):
                loop.call_soon_threadsafe(started[index].set)
                try:
                    if not release.wait(timeout=10):
                        raise AssertionError("test failed to release injection worker")
                finally:
                    finished[index].set()

            return inject

        try:
            for index in range(2):
                middleware = context_module.DynamicContextMiddleware()
                monkeypatch.setattr(middleware, "_read_failures_are_fatal", lambda **_kwargs: False)
                monkeypatch.setattr(middleware, "_inject", make_injection(index))
                calls.append(asyncio.create_task(middleware.abefore_agent({}, SimpleNamespace(context={}))))

            assert await asyncio.wait_for(asyncio.gather(*calls), 5) == [None, None]
            assert not any(event.is_set() for event in finished)
            # Equivalent to an unrelated handler's synchronous offload. It must
            # complete while both abandoned injection workers are still blocked.
            assert await asyncio.wait_for(asyncio.to_thread(lambda: "handler-ready"), 1) == "handler-ready"
            assert not any(event.is_set() for event in finished)
        finally:
            release.set()
            for call in calls:
                if not call.done():
                    call.cancel()
            await asyncio.gather(*calls, return_exceptions=True)
            assert all(await asyncio.gather(*(asyncio.to_thread(event.wait, 5) for event in finished)))

    asyncio.run(scenario())


@pytest.mark.asyncio
@pytest.mark.parametrize("fatal", [False, True, None], ids=["fail_open", "fail_closed", "unknown"])
async def test_saturated_injection_rejects_bursts_without_submitting_more_work(monkeypatch, context_pool, fatal):
    loop = asyncio.get_running_loop()
    started = [asyncio.Event(), asyncio.Event()]
    release = threading.Event()
    middleware = context_module.DynamicContextMiddleware()
    inject = Mock()
    monkeypatch.setattr(middleware, "_inject", inject)
    monkeypatch.setattr(middleware, "_read_failures_are_fatal", lambda **_kwargs: fatal)

    def occupy_worker(index):
        loop.call_soon_threadsafe(started[index].set)
        assert release.wait(5), "worker was not released"

    tasks = [asyncio.create_task(context_pool.run(occupy_worker, index)) for index in range(2)]
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started)), 5)
        for _ in range(20):
            call = middleware.abefore_agent({}, SimpleNamespace(context={}))
            if fatal is False:
                assert await asyncio.wait_for(call, 1) is None
            else:
                with pytest.raises(MemoryReadError, match="pool saturated") as error:
                    await asyncio.wait_for(call, 1)
                assert isinstance(error.value.__cause__, context_io.ContextInjectionBusyError)
        inject.assert_not_called()
    finally:
        release.set()
        await asyncio.gather(*tasks)
    assert await context_pool.run(lambda: "recovered") == "recovered"
