"""Concurrency regression tests for the scheduled-task dispatch TOCTOU.

``ScheduledTaskService.dispatch_task`` guards the "at most one active run per
task when overlap_policy=skip" invariant with a non-atomic
``has_active_runs`` check followed by a separate ``create(status="queued")``
insert. Two concurrent dispatches (double-click, client retry, or a manual
trigger racing the poller) can both pass the check and both launch. The fix
makes the database the atomic arbiter via the partial unique index
``uq_scheduled_task_run_active`` (``task_id WHERE status IN
('queued','running')``); the losing insert is translated to the typed
``ActiveScheduledRunConflict`` and collapsed to the same outcome as the
fast-path check.

These tests drive the REAL ``ScheduledTaskRunRepository`` + ``ScheduledTaskService``
against a real file-backed ``sqlite+aiosqlite`` DB (so the index is actually
enforced), with a fake ``launch_run`` that only records launches.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.scheduler.service import ScheduledTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_task_runs import ActiveScheduledRunConflict, ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

pytestmark = pytest.mark.asyncio

_ACTIVE_STATUSES = {"queued", "running"}


class _BarrierRunRepo(ScheduledTaskRunRepository):
    """Real repository that only releases both dispatchers past
    ``has_active_runs`` once both have read it, so their ``create()`` calls
    genuinely race for the task's single active slot — a deterministic
    reproduction of the check-then-insert TOCTOU."""

    def __init__(self, session_factory, barrier: asyncio.Barrier | None) -> None:
        super().__init__(session_factory)
        self._barrier = barrier

    async def has_active_runs(self, task_id: str) -> bool:
        result = await super().has_active_runs(task_id)
        if self._barrier is not None:
            await self._barrier.wait()
        return result


def _make_service(task_repo, run_repo, launched: list) -> ScheduledTaskService:
    async def fake_launch(**kwargs):
        # Yield so a truly-concurrent sibling can interleave, then record.
        await asyncio.sleep(0)
        launched.append(kwargs)
        return {"run_id": f"run-{len(launched)}", "thread_id": kwargs["thread_id"]}

    return ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=10,
    )


async def _seed_task(task_repo: ScheduledTaskRepository, task_id: str) -> dict:
    # fresh_thread_per_run: every dispatch gets a NEW thread_id, so #4003's
    # per-thread uq_runs_thread_active can never fire for two dispatches of the
    # same task — this is precisely the gap the per-task index closes.
    await task_repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title=task_id,
        prompt="do the thing",
        schedule_type="cron",
        schedule_spec={"cron": "*/5 * * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    task = await task_repo.get(task_id, user_id="user-1")
    assert task is not None
    assert task["overlap_policy"] == "skip"
    return task


async def _active_run_count(run_repo: ScheduledTaskRunRepository, task_id: str) -> int:
    rows = await run_repo.list_by_task(task_id, limit=100)
    return sum(1 for row in rows if row["status"] in _ACTIVE_STATUSES)


async def test_two_concurrent_manual_dispatches_launch_exactly_once(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = _BarrierRunRepo(sf, asyncio.Barrier(2))
        launched: list = []
        service = _make_service(task_repo, run_repo, launched)
        task = await _seed_task(task_repo, "task-race-manual")
        now = datetime.now(UTC)

        results = await asyncio.gather(
            service.dispatch_task(dict(task), now=now, trigger="manual"),
            service.dispatch_task(dict(task), now=now, trigger="manual"),
        )

        outcomes = sorted(result["outcome"] for result in results)
        # Exactly one wins the active slot; the loser is a 409-style conflict.
        assert outcomes == ["conflict", "launched"], outcomes
        assert len(launched) == 1, launched
        assert await _active_run_count(run_repo, "task-race-manual") == 1
        # The manual loser records no run-history row (nothing was scheduled).
        conflict = next(r for r in results if r["outcome"] == "conflict")
        assert conflict["task_run_id"] is None
    finally:
        await close_engine()


async def test_scheduled_and_manual_dispatch_launch_exactly_once(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = _BarrierRunRepo(sf, asyncio.Barrier(2))
        launched: list = []
        service = _make_service(task_repo, run_repo, launched)
        task = await _seed_task(task_repo, "task-race-mixed")
        now = datetime.now(UTC)

        results = await asyncio.gather(
            service.dispatch_task(dict(task), now=now, trigger="scheduled"),
            service.dispatch_task(dict(task), now=now, trigger="manual"),
        )

        outcomes = sorted(result["outcome"] for result in results)
        # Whichever won launched; the loser is conflict (manual) or skipped
        # (scheduled). Which one wins is timing-dependent, but exactly one runs.
        assert outcomes.count("launched") == 1, outcomes
        assert set(outcomes) <= {"launched", "conflict", "skipped"}, outcomes
        assert len(launched) == 1, launched
        assert await _active_run_count(run_repo, "task-race-mixed") == 1
    finally:
        await close_engine()


async def test_natural_timing_concurrent_dispatch_launches_exactly_once(tmp_path):
    # No barrier: exercise the fix under the same natural interleaving that
    # reproduced the bug (5/5 both-launch on main). The fix must hold whether
    # the second dispatch is caught by the has_active_runs fast path or by the
    # index-violation path.
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        for i in range(5):
            launched: list = []
            service = _make_service(task_repo, run_repo, launched)
            task_id = f"task-natural-{i}"
            task = await _seed_task(task_repo, task_id)
            now = datetime.now(UTC)

            results = await asyncio.gather(
                service.dispatch_task(dict(task), now=now, trigger="manual"),
                service.dispatch_task(dict(task), now=now, trigger="manual"),
            )

            outcomes = sorted(result["outcome"] for result in results)
            assert outcomes.count("launched") == 1, (i, outcomes)
            assert len(launched) == 1, (i, launched)
            assert await _active_run_count(run_repo, task_id) == 1, i
    finally:
        await close_engine()


async def test_partial_unique_index_enforces_one_active_run_per_task(tmp_path):
    # Focused repository-level test of the index semantics + the typed conflict.
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        run_repo = ScheduledTaskRunRepository(sf)
        now = datetime(2026, 7, 2, 1, 0, tzinfo=UTC)

        await run_repo.create(run_record_id="r1", task_id="t1", thread_id="th1", scheduled_for=now, trigger="scheduled", status="queued")

        # queued -> running is a same-row UPDATE: keeps the one active slot, no
        # violation (this is the normal launch transition).
        await run_repo.update_status("r1", status="running", run_id="run-1", started_at=now)
        assert await run_repo.has_active_runs("t1") is True

        # A second active insert for the same task is a domain conflict.
        with pytest.raises(ActiveScheduledRunConflict):
            await run_repo.create(run_record_id="r2", task_id="t1", thread_id="th2", scheduled_for=now, trigger="manual", status="queued")

        # Terminal-status rows for the same task are outside the index predicate.
        await run_repo.create(run_record_id="r3", task_id="t1", thread_id="th3", scheduled_for=now, trigger="scheduled", status="skipped")

        # A different task's active row is independent.
        await run_repo.create(run_record_id="r4", task_id="t2", thread_id="th4", scheduled_for=now, trigger="scheduled", status="queued")

        # Finishing the active run frees the slot; a fresh active row is allowed.
        await run_repo.update_status("r1", status="success", run_id="run-1", finished_at=now)
        assert await run_repo.has_active_runs("t1") is False
        await run_repo.create(run_record_id="r5", task_id="t1", thread_id="th5", scheduled_for=now, trigger="scheduled", status="queued")
        assert await run_repo.has_active_runs("t1") is True
    finally:
        await close_engine()
