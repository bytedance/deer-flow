"""Concurrency regression tests for the scheduled-task dispatch TOCTOU.

``ScheduleService.dispatch_task`` guards "at most one active run per task
when overlap_policy=skip" with a non-atomic ``has_active`` fast path followed
by a separate queued-record insert. Two concurrent dispatches (double-click,
client retry, or a manual trigger racing the poller) can both pass the check
and both launch. The database is the atomic arbiter via the partial unique
index ``uq_scheduled_task_run_active`` (``task_id WHERE status IN
('queued','running')``); the losing insert is translated to
``ActiveRunConflictError`` and collapsed to the same outcome as the fast
path.

These tests drive the REAL ``SqlScheduledRunRepository`` +
``SqlScheduledTaskRepository`` + ``ScheduleService`` against a real
file-backed sqlite database (so the index is actually enforced), with a fake
launcher that only records launches. The contract suite deliberately does not
own this: its doubles provide no atomicity, so a green contract run says
nothing about two dispatchers racing -- this file is where that is proven.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from schedule_fakes import FakeThreadLookup

from app.adapters.schedule.scheduled_run_repository import SqlScheduledRunRepository
from app.adapters.schedule.scheduled_task_repository import SqlScheduledTaskRepository
from deerflow.config.database_config import DatabaseConfig
from deerflow.domain.schedule.exceptions import ActiveRunConflictError
from deerflow.domain.schedule.model import DispatchOutcome, RunStatus, ScheduledRun, ScheduledTask, SchedulePolicy, ScheduleSpec, TriggerKind
from deerflow.domain.schedule.ports import LaunchedRun
from deerflow.domain.schedule.service import ScheduleService
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


class _BarrierRunRepo(SqlScheduledRunRepository):
    """Real repository that only releases both dispatchers past ``has_active``
    once both have read it, so their ``add()`` calls genuinely race for the
    task's single active slot -- a deterministic reproduction of the
    check-then-insert TOCTOU."""

    def __init__(self, session_factory, barrier: asyncio.Barrier | None) -> None:
        super().__init__(session_factory)
        self._barrier = barrier

    async def has_active(self, task_id: str) -> bool:
        result = await super().has_active(task_id)
        if self._barrier is not None:
            await self._barrier.wait()
        return result


class _RecordingLauncher:
    """Launch double that yields first, so a truly-concurrent sibling can
    interleave before the launch is recorded."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def launch(self, *, thread_id, assistant_id, prompt, owner_user_id, metadata) -> LaunchedRun:
        await asyncio.sleep(0)
        self.calls.append({"thread_id": thread_id, "metadata": metadata})
        return LaunchedRun(run_id=f"run-{len(self.calls)}", thread_id=thread_id)


def _make_service(tasks, runs, launcher) -> ScheduleService:
    return ScheduleService(
        tasks=tasks,
        runs=runs,
        launcher=launcher,
        threads=FakeThreadLookup(),
        policy=SchedulePolicy(min_once_delay_seconds=60, max_concurrent_runs=10, lease_seconds=120),
    )


async def _seed_task(tasks: SqlScheduledTaskRepository, title: str) -> ScheduledTask:
    # fresh_thread_per_run: every dispatch gets a NEW thread_id, so #4003's
    # per-thread uq_runs_thread_active can never fire for two dispatches of the
    # same task -- this is precisely the gap the per-task index closes.
    return await tasks.add(
        ScheduledTask.create(
            user_id="user-1",
            title=title,
            prompt="do the thing",
            schedule=ScheduleSpec.cron_schedule("*/5 * * * *", "UTC"),
            context_mode="fresh_thread_per_run",
            thread_id=None,
            now=NOW,
            policy=SchedulePolicy(),
        )
    )


async def _active_run_count(runs: SqlScheduledRunRepository, task_id: str) -> int:
    rows = await runs.list_by_task(task_id, limit=100)
    return sum(1 for row in rows if row.is_active)


async def test_two_concurrent_manual_dispatches_launch_exactly_once(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        tasks = SqlScheduledTaskRepository(sf)
        runs = _BarrierRunRepo(sf, asyncio.Barrier(2))
        launcher = _RecordingLauncher()
        service = _make_service(tasks, runs, launcher)
        task = await _seed_task(tasks, "task-race-manual")

        results = await asyncio.gather(
            service.dispatch_task(task, now=NOW, trigger=TriggerKind.MANUAL),
            service.dispatch_task(task, now=NOW, trigger=TriggerKind.MANUAL),
        )

        outcomes = sorted((result.outcome for result in results), key=str)
        # Exactly one wins the active slot; the loser is a 409-style conflict.
        assert outcomes == [DispatchOutcome.CONFLICT, DispatchOutcome.LAUNCHED], outcomes
        assert len(launcher.calls) == 1, launcher.calls
        assert await _active_run_count(runs, task.task_id) == 1
        # The manual loser records no run-history row (nothing was scheduled).
        conflict = next(r for r in results if r.outcome is DispatchOutcome.CONFLICT)
        assert conflict.record_id is None
    finally:
        await close_engine()


async def test_scheduled_and_manual_dispatch_launch_exactly_once(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        tasks = SqlScheduledTaskRepository(sf)
        runs = _BarrierRunRepo(sf, asyncio.Barrier(2))
        launcher = _RecordingLauncher()
        service = _make_service(tasks, runs, launcher)
        task = await _seed_task(tasks, "task-race-mixed")

        results = await asyncio.gather(
            service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED),
            service.dispatch_task(task, now=NOW, trigger=TriggerKind.MANUAL),
        )

        outcomes = [result.outcome for result in results]
        # Whichever won launched; the loser is conflict (manual) or skipped
        # (scheduled). Which one wins is timing-dependent, but exactly one runs.
        assert outcomes.count(DispatchOutcome.LAUNCHED) == 1, outcomes
        assert set(outcomes) <= {DispatchOutcome.LAUNCHED, DispatchOutcome.CONFLICT, DispatchOutcome.SKIPPED}, outcomes
        assert len(launcher.calls) == 1, launcher.calls
        assert await _active_run_count(runs, task.task_id) == 1
    finally:
        await close_engine()


async def test_natural_timing_concurrent_dispatch_launches_exactly_once(tmp_path):
    # No barrier: exercise the fix under the same natural interleaving that
    # reproduced the bug (5/5 both-launch before the index). The fix must hold
    # whether the second dispatch is caught by the has_active fast path or by
    # the index-violation path.
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        tasks = SqlScheduledTaskRepository(sf)
        runs = SqlScheduledRunRepository(sf)
        for i in range(5):
            launcher = _RecordingLauncher()
            service = _make_service(tasks, runs, launcher)
            task = await _seed_task(tasks, f"task-natural-{i}")

            results = await asyncio.gather(
                service.dispatch_task(task, now=NOW, trigger=TriggerKind.MANUAL),
                service.dispatch_task(task, now=NOW, trigger=TriggerKind.MANUAL),
            )

            outcomes = [result.outcome for result in results]
            assert outcomes.count(DispatchOutcome.LAUNCHED) == 1, (i, outcomes)
            assert len(launcher.calls) == 1, (i, launcher.calls)
            assert await _active_run_count(runs, task.task_id) == 1, i
    finally:
        await close_engine()


async def test_partial_unique_index_enforces_one_active_run_per_task(tmp_path):
    # Focused repository-level test of the index semantics + the typed conflict.
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        runs = SqlScheduledRunRepository(sf)
        now = datetime(2026, 7, 2, 1, 0, tzinfo=UTC)

        first = ScheduledRun.queued(task_id="t1", thread_id="th1", scheduled_for=now, trigger=TriggerKind.SCHEDULED)
        await runs.add(first)

        # queued -> running is a same-row UPDATE: keeps the one active slot, no
        # violation (this is the normal launch transition).
        await runs.update_status(first.record_id, status=RunStatus.RUNNING, run_id="run-1", started_at=now)
        assert await runs.has_active("t1") is True

        # A second active insert for the same task is a domain conflict.
        with pytest.raises(ActiveRunConflictError):
            await runs.add(ScheduledRun.queued(task_id="t1", thread_id="th2", scheduled_for=now, trigger=TriggerKind.MANUAL))

        # Terminal-status rows for the same task are outside the index predicate.
        await runs.add(ScheduledRun.skipped_tombstone(task_id="t1", thread_id="th3", scheduled_for=now, trigger=TriggerKind.SCHEDULED))

        # A different task's active row is independent.
        await runs.add(ScheduledRun.queued(task_id="t2", thread_id="th4", scheduled_for=now, trigger=TriggerKind.SCHEDULED))

        # Finishing the active run frees the slot; a fresh active row is allowed.
        await runs.update_status(first.record_id, status=RunStatus.SUCCESS, run_id="run-1", finished_at=now)
        assert await runs.has_active("t1") is False
        await runs.add(ScheduledRun.queued(task_id="t1", thread_id="th5", scheduled_for=now, trigger=TriggerKind.SCHEDULED))
        assert await runs.has_active("t1") is True
    finally:
        await close_engine()
