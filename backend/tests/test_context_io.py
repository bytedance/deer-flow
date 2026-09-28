"""Admission and lifetime contracts for the context injection pool."""

from __future__ import annotations

import asyncio
import contextvars
import threading
from unittest.mock import Mock

import pytest

from deerflow.utils.context_io import ContextInjectionBusyError, _ContextInjectionPool, _default_context_workers


@pytest.fixture
def pool():
    executor = _ContextInjectionPool(max_workers=1)
    try:
        yield executor
    finally:
        executor.shutdown(wait=True)


@pytest.mark.parametrize(("value", "expected"), [(None, 4), ("", 4), ("0", 4), ("-2", 4), ("invalid", 4), ("2", 2)])
def test_worker_configuration(monkeypatch, value, expected):
    monkeypatch.delenv("DEER_FLOW_CONTEXT_WORKERS", raising=False)
    if value is not None:
        monkeypatch.setenv("DEER_FLOW_CONTEXT_WORKERS", value)
    assert _default_context_workers() == expected


@pytest.mark.asyncio
async def test_context_and_keyword_arguments_are_preserved(pool):
    identity = contextvars.ContextVar("context_test_identity", default="unset")
    loop_thread = threading.get_ident()

    def read_context(*, suffix):
        assert threading.get_ident() != loop_thread
        value = identity.get()
        identity.set("worker-only")
        return value + suffix

    identity.set("alice")
    assert await pool.run(read_context, suffix="-first") == "alice-first"
    assert identity.get() == "alice"
    identity.set("bob")
    assert await pool.run(read_context, suffix="-second") == "bob-second"


@pytest.mark.asyncio
async def test_cancelled_waiter_keeps_capacity_until_worker_finishes(pool):
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    rejected = Mock()

    def blocking_work():
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5), "worker was not released"

    task = asyncio.create_task(pool.run(blocking_work))
    try:
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        for _ in range(20):
            with pytest.raises(ContextInjectionBusyError):
                await pool.run(rejected)
        rejected.assert_not_called()
        assert await asyncio.wait_for(asyncio.to_thread(lambda: "default-ready"), 1) == "default-ready"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        # A direct executor sentinel fences worker completion and its callbacks.
        await asyncio.wrap_future(pool._executor.submit(lambda: None))
    assert await pool.run(lambda: "recovered") == "recovered"


@pytest.mark.asyncio
async def test_queued_cancellation_releases_capacity_without_running_work(pool):
    release = threading.Event()
    started = threading.Event()
    never_run = Mock()

    def hold_dispatch():
        started.set()
        assert release.wait(5), "dispatcher was not released"

    # Delay dispatch to exercise cancellation before the submitted work starts.
    blocker = pool._executor.submit(hold_dispatch)
    queued = None
    replacement = None
    try:
        assert await asyncio.to_thread(started.wait, 5)
        queued = asyncio.create_task(pool.run(never_run))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        replacement = asyncio.create_task(pool.run(lambda: "replacement"))
        await asyncio.sleep(0)
        assert not replacement.done()
        release.set()
        assert await asyncio.wait_for(replacement, 5) == "replacement"
        never_run.assert_not_called()
    finally:
        release.set()
        await asyncio.wrap_future(blocker)
        await asyncio.gather(*(task for task in (queued, replacement) if task is not None), return_exceptions=True)


@pytest.mark.asyncio
async def test_worker_exception_releases_capacity(pool):
    def fail():
        raise ValueError("worker failed")

    with pytest.raises(ValueError, match="worker failed"):
        await pool.run(fail)
    assert await pool.run(lambda: "recovered") == "recovered"


@pytest.mark.asyncio
async def test_submit_failure_releases_capacity(pool):
    pool.shutdown()
    for _ in range(2):
        with pytest.raises(RuntimeError, match="cannot schedule new futures"):
            await pool.run(lambda: None)


def test_capacity_is_shared_across_loops_and_released_after_owner_loop_closes(pool):
    release = threading.Event()
    started = threading.Event()

    def blocking_work():
        started.set()
        assert release.wait(5), "worker was not released"

    async def abandoned_request():
        task = asyncio.create_task(pool.run(blocking_work))
        try:
            assert await asyncio.to_thread(started.wait, 5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(abandoned_request())
        with pytest.raises(ContextInjectionBusyError):
            asyncio.run(pool.run(lambda: "another-loop"))
    finally:
        release.set()
        pool._executor.submit(lambda: None).result(timeout=5)
    assert asyncio.run(pool.run(lambda: "recovered")) == "recovered"
