"""Unmanaged tracing scopes never wait for unrelated executor work."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from langsmith import tracing_context
from langsmith.run_helpers import get_tracing_context
from langsmith.utils import tracing_is_enabled

from deerflow.tracing import scoped


@contextmanager
def saturated_runner():
    started, release = threading.Event(), threading.Event()

    def hold_worker():
        started.set()
        release.wait()

    with ThreadPoolExecutor(max_workers=1) as executor, asyncio.Runner() as runner:
        runner.get_loop().set_default_executor(executor)

        def occupy():
            executor.submit(hold_worker)
            assert started.wait(3), "the controlled executor worker never started"

        try:
            yield runner, occupy, release
        finally:
            release.set()


@pytest.mark.parametrize("phase", ["enter", "exit"])
def test_none_scope_enters_and_exits_while_the_default_executor_is_occupied(phase):
    with saturated_runner() as (runner, occupy, release):
        if phase == "enter":
            occupy()

        async def check():
            body_entered = asyncio.Event()
            sessions = []
            client = object()
            replicas = [{"project_name": "offline-ambient"}]

            async def invoke():
                caller = asyncio.current_task()
                async with scoped.async_tracing_scope(None) as session:
                    sessions.append(session)
                    assert asyncio.current_task() is caller
                    assert scoped.get_current_snapshot() is None
                    assert scoped.build_scoped_callbacks() is None
                    assert tracing_is_enabled() is True
                    context = get_tracing_context()
                    assert context["client"] is client and context["replicas"] == replicas
                    if phase == "exit":
                        occupy()
                    body_entered.set()

            with tracing_context(enabled=True, client=client, parent=False, replicas=replicas):
                task = asyncio.create_task(invoke())
                try:
                    if phase == "exit":
                        await body_entered.wait()
                    else:
                        # The scope body has no awaits: one task turn must be
                        # sufficient, independently of the occupied executor.
                        await asyncio.sleep(0)
                    assert task.done(), f"unmanaged scope {phase} queued behind unrelated executor work"
                    await task
                    assert body_entered.is_set()
                    assert sessions[0]._closed
                    assert tracing_is_enabled() is True
                    assert get_tracing_context()["client"] is client
                finally:
                    release.set()
                    await asyncio.gather(task, return_exceptions=True)

        runner.run(check())


def test_none_scope_cancellation_closes_without_executor_and_restores_the_parent(monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.tracing.profiles import RunTracingSnapshot

    monkeypatch.setenv("MONOCLE_TRACING", "false")
    reset_tracing_config()
    parent = RunTracingSnapshot(snapshot_id="parent-disabled", owner_user_id="alice", agent_name="worker", mode="disabled", revision="1", providers=())
    try:
        with saturated_runner() as (runner, occupy, release):

            async def check():
                entered, suspend = asyncio.Event(), asyncio.Event()
                restored, sessions = [], []

                async def invoke():
                    try:
                        async with scoped.async_tracing_scope(None) as session:
                            sessions.append(session)
                            assert scoped.get_current_snapshot() is None
                            # None preserves the caller's ambient suppression.
                            assert tracing_is_enabled() is False
                            occupy()
                            entered.set()
                            await suspend.wait()
                    finally:
                        restored.append(scoped.get_current_snapshot())

                with scoped.tracing_scope(parent):
                    task = asyncio.create_task(invoke())
                    try:
                        await entered.wait()
                        task.cancel()
                        await asyncio.sleep(0)
                        assert task.done(), "unmanaged cancellation cleanup waited for the executor"
                        with pytest.raises(asyncio.CancelledError):
                            await task
                        assert sessions[0]._closed
                        assert restored == [parent]
                        assert scoped.get_current_snapshot() is parent
                        assert tracing_is_enabled() is False
                    finally:
                        release.set()
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                assert scoped.get_current_snapshot() is None

            runner.run(check())
    finally:
        reset_tracing_config()
