"""Controlled races through the shared production execution shell."""

import asyncio
import threading

import pytest

from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.extensions.registry import EMPTY_EXTENSIONS
from deerflow.subagents.capacity import SubagentExecutionCapacity
from deerflow.subagents.execution import SubagentStatus, WorkerExecutor, cleanup_background_task, get_background_task_result, request_cancel_background_task
from deerflow.subagents.worker_backends import WorkerOutcome, WorkerPlan
from deerflow.utils.file_io import await_drained


async def terminal(holder):
    async def wait():
        while True:
            snapshot = holder.snapshot()
            if snapshot.status.is_terminal:
                return snapshot
            await holder.wait_for_change(snapshot.revision, timeout=10)

    return await asyncio.wait_for(wait(), timeout=15)


@pytest.mark.anyio
async def test_timeout_retains_capacity_until_cleanup_and_late_completion_loses(tmp_path):
    entered, cleaning, release = threading.Event(), threading.Event(), threading.Event()

    class Backend:
        async def execute(self, plan, execution):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await await_drained(asyncio.to_thread(release.wait))

    capacity = SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=1))
    worker = WorkerExecutor(WorkerPlan("first", "acp", "Test", 1, {}), Backend(), execution_capacity=capacity, extensions=EMPTY_EXTENSIONS, workspace_resolver=lambda *args: tmp_path / args[-1])
    identifier = worker.execute_async("work", task_id="reused")
    holder = get_background_task_result(identifier)
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        snapshot = await terminal(holder)
        assert snapshot.status is SubagentStatus.TIMED_OUT
        assert await asyncio.to_thread(cleaning.wait, 10)
        assert capacity.snapshot().running == 1
        assert not holder.execution_done_event.is_set()
        assert not holder.try_set_terminal(SubagentStatus.COMPLETED, result="late success")
        request_cancel_background_task(identifier)
        request_cancel_background_task(identifier)
        cleanup_background_task(identifier)
        assert get_background_task_result(identifier) is holder
    finally:
        release.set()
        assert await asyncio.to_thread(holder.execution_done_event.wait, 10)
        cleanup_background_task(identifier)
    assert capacity.snapshot().running == 0
    assert get_background_task_result(identifier) is None


@pytest.mark.anyio
async def test_cancel_queued_worker_does_not_start_backend(tmp_path):
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()

    class First:
        async def execute(self, plan, execution):
            entered.set()
            await asyncio.to_thread(release.wait)
            return WorkerOutcome(result="native result")

    class Second:
        async def execute(self, plan, execution):
            second_started.set()
            return WorkerOutcome(result="external result")

    capacity = SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=1))

    def executor(name, backend):
        return WorkerExecutor(WorkerPlan(name, name, name, 30, {}), backend, execution_capacity=capacity, extensions=EMPTY_EXTENSIONS, workspace_resolver=lambda *args: tmp_path / args[-1])

    first = executor("native", First()).execute_async("first", task_id="same-call")
    second = None
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        second = executor("acp", Second()).execute_async("second", task_id="same-call")
        assert first != second
        holder = get_background_task_result(second)
        request_cancel_background_task(second)
        assert (await terminal(holder)).status is SubagentStatus.CANCELLED
        assert await asyncio.to_thread(holder.execution_done_event.wait, 10)
        assert not second_started.is_set()
        assert capacity.snapshot().running == 1
    finally:
        release.set()
        first_holder = get_background_task_result(first)
        assert await asyncio.to_thread(first_holder.execution_done_event.wait, 10)
        cleanup_background_task(first)
        if second:
            cleanup_background_task(second)
    assert capacity.snapshot().running == 0


@pytest.mark.anyio
async def test_workspace_timeout_drains_resolver_before_releasing_slot(tmp_path):
    entered, release, finished, started = (threading.Event() for _ in range(4))

    def resolver(*args):
        entered.set()
        release.wait()
        finished.set()
        return tmp_path / args[-1]

    class Backend:
        async def execute(self, plan, execution):
            started.set()
            return WorkerOutcome(result="unexpected")

    capacity = SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=1))
    worker = WorkerExecutor(WorkerPlan("worker", "test", "Test", 1, {}), Backend(), execution_capacity=capacity, extensions=EMPTY_EXTENSIONS, workspace_resolver=resolver)
    identifier = worker.execute_async("work")
    holder = get_background_task_result(identifier)
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        assert (await terminal(holder)).status is SubagentStatus.TIMED_OUT
        assert capacity.snapshot().running == 1
        assert not holder.execution_done_event.is_set() and not finished.is_set()
    finally:
        release.set()
        assert await asyncio.to_thread(holder.execution_done_event.wait, 10)
        cleanup_background_task(identifier)
    assert not started.is_set() and finished.is_set()
    assert capacity.snapshot().running == 0


@pytest.mark.anyio
async def test_expired_deadline_never_enters_backend_after_slot_transfer(tmp_path):
    from contextlib import asynccontextmanager

    from deerflow.subagents.execution import SubagentResult

    started = False

    class Backend:
        async def execute(self, plan, execution):
            nonlocal started
            started = True
            return WorkerOutcome(result="unexpected")

    holder = SubagentResult(task_id="expired", trace_id="test", status=SubagentStatus.PENDING)

    class Capacity:
        @asynccontextmanager
        async def slot(self):
            holder.deadline = 0
            yield

    worker = WorkerExecutor(WorkerPlan("worker", "test", "Test", 30, {}), Backend(), execution_capacity=Capacity(), extensions=EMPTY_EXTENSIONS, workspace_resolver=lambda *args: tmp_path)
    result = await worker._aexecute("work", holder)
    assert result.status is SubagentStatus.TIMED_OUT and result.admission_failure
    assert not started


@pytest.mark.anyio
async def test_malformed_backend_result_is_failed_instead_of_left_running(tmp_path):
    class Backend:
        async def execute(self, plan, execution):
            return "invalid result"

    worker = WorkerExecutor(WorkerPlan("worker", "test", "Test", 30, {}), Backend(), extensions=EMPTY_EXTENSIONS, workspace_resolver=lambda *args: tmp_path)
    result = await worker._aexecute("work")
    assert result.status is SubagentStatus.FAILED
    assert result.error_code == "backend_failed"
    assert result.execution_done_event.is_set()


@pytest.mark.anyio
async def test_backend_returning_after_deadline_cannot_win_before_watchdog(tmp_path):
    from deerflow.subagents.execution import SubagentResult

    holder = SubagentResult(task_id="late", trace_id="test", status=SubagentStatus.PENDING)

    class Backend:
        async def execute(self, plan, execution):
            holder.deadline = 0
            return WorkerOutcome(result="late success")

    worker = WorkerExecutor(WorkerPlan("worker", "test", "Test", 30, {}), Backend(), extensions=EMPTY_EXTENSIONS, workspace_resolver=lambda *args: tmp_path)
    result = await worker._aexecute("work", holder)
    assert result.status is SubagentStatus.TIMED_OUT and result.result is None
