from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.scheduler.service import ScheduledTaskService
from deerflow.persistence.base import Base
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.runtime import RunStatus
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode
from deerflow.scheduler.host_notes import RUN_ERROR_INTERRUPTED


@asynccontextmanager
async def _database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'completion.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[ScheduledTaskRow.__table__, ScheduledTaskRunRow.__table__, RunRow.__table__]))
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _launching_occurrence(sf, *, schedule_type, suffix="completion", trigger="manual"):
    now = datetime(2026, 9, 9, 8, tzinfo=UTC)
    tasks = ScheduledTaskRepository(sf)
    occurrences = ScheduledTaskRunRepository(sf)
    task_id = f"task-{suffix}"
    occurrence_id = f"occurrence-{suffix}"
    thread_id = f"thread-{suffix}"
    spec = {"run_at": now.isoformat()} if schedule_type == "once" else {"cron": "0 9 * * *"}
    await tasks.create(
        task_id=task_id,
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title="completion",
        prompt="test",
        schedule_type=schedule_type,
        schedule_spec=spec,
        timezone="UTC",
        next_run_at=now,
    )
    await occurrences.create(
        run_record_id=occurrence_id,
        task_id=task_id,
        thread_id=thread_id,
        scheduled_for=now,
        trigger=trigger,
        status="queued",
    )
    claimed = await occurrences.claim_queued_run(
        occurrence_id,
        lease_owner="launcher",
        now=now,
        lease_seconds=120,
        global_max_concurrent_runs=3,
    )
    assert claimed is not None
    await tasks.update(
        task_id,
        user_id="user-1",
        updates={"status": "running" if schedule_type == "once" else "enabled", "last_error": "previous error"},
    )
    return tasks, occurrences, now


def _service(tasks, occurrences):
    return ScheduledTaskService(
        task_repo=tasks,
        task_run_repo=occurrences,
        launch_run=lambda **_kwargs: None,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )


def _completion(status, error):
    return RunRecord(
        run_id="run-completion",
        thread_id="thread-completion",
        assistant_id=None,
        status=status,
        on_disconnect=DisconnectMode.continue_,
        metadata={"scheduled_task_id": "task-completion", "scheduled_task_run_id": "occurrence-completion"},
        user_id="user-1",
        error=error,
    )


async def _snapshot(sf, task_id="task-completion", occurrence_id="occurrence-completion"):
    async with sf() as session:
        task = await session.get(ScheduledTaskRow, task_id)
        occurrence = await session.get(ScheduledTaskRunRow, occurrence_id)
        assert task is not None and occurrence is not None
        return task.to_dict(), occurrence.to_dict()


@pytest.mark.asyncio
@pytest.mark.parametrize("schedule_type", ["once", "cron"])
@pytest.mark.parametrize(
    ("run_status", "error", "occurrence_status", "once_status", "expected_error"),
    [
        (RunStatus.success, None, "success", "completed", None),
        (RunStatus.error, "boom", "failed", "failed", "boom"),
        (RunStatus.timeout, "time limit", "failed", "failed", "time limit"),
        (RunStatus.interrupted, None, "interrupted", "cancelled", "run was interrupted before completion"),
    ],
)
async def test_completion_before_launch_bookkeeping_is_durable_and_counted_once(tmp_path, schedule_type, run_status, error, occurrence_status, once_status, expected_error):
    async with _database(tmp_path) as (_engine, sf):
        tasks, occurrences, now = await _launching_occurrence(sf, schedule_type=schedule_type)
        service = _service(tasks, occurrences)
        record = _completion(run_status, error)
        await service.handle_run_completion(record)

        task, occurrence = await _snapshot(sf)
        assert task["status"] == (once_status if schedule_type == "once" else "enabled")
        assert task["last_error"] == expected_error
        assert task["last_run_id"] == "run-completion"
        assert task["last_thread_id"] == "thread-completion"
        assert task["run_count"] == 1
        assert occurrence["status"] == occurrence_status
        assert occurrence["error"] == expected_error
        assert occurrence["run_id"] == "run-completion"
        assert occurrence["finished_at"] is not None
        assert occurrence["launch_accounted"] is True
        assert occurrence["lease_owner"] is None
        assert occurrence["lease_expires_at"] is None

        # The late launcher and a repeated delivery must not undo the terminal
        # outcome or count the same launch a second time.
        await tasks.update_after_launch(
            "task-completion",
            task_run_id="occurrence-completion",
            status="running" if schedule_type == "once" else "enabled",
            next_run_at=None if schedule_type == "once" else now + timedelta(hours=1),
            last_run_at=now,
            last_run_id="run-completion",
            last_thread_id="thread-completion",
            last_error=None,
            increment_run_count=True,
            protect_terminal=True,
        )
        task_after_launch, _ = await _snapshot(sf)
        assert task_after_launch["run_count"] == 1
        assert task_after_launch["status"] == task["status"]
        assert task_after_launch["last_error"] == expected_error
        await service.handle_run_completion(record)
        task_after_retry, _ = await _snapshot(sf)
        assert task_after_retry["run_count"] == 1
        assert task_after_retry["status"] == task["status"]
        assert task_after_retry["last_error"] == expected_error


async def _running_occurrence_with_terminal_run(
    sf,
    *,
    run_status: str,
    error: str | None = None,
    goal_objective: str | None = None,
    goal_verdict: dict | None = None,
    suffix: str = "completion",
    trigger: str = "manual",
    schedule_type: str = "cron",
):
    tasks, occurrences, now = await _launching_occurrence(sf, schedule_type=schedule_type, suffix=suffix, trigger=trigger)
    occurrence_id = f"occurrence-{suffix}"
    task_id = f"task-{suffix}"
    thread_id = f"thread-{suffix}"
    run_id = f"run-{suffix}"
    await occurrences.update_status(
        occurrence_id,
        status="running",
        run_id=run_id,
        started_at=now,
    )
    await tasks.update(
        task_id,
        user_id="user-1",
        updates={"next_run_at": now if schedule_type == "once" else now + timedelta(days=1), "goal_objective": goal_objective},
    )
    async with sf() as session:
        if goal_objective is not None:
            occurrence = await session.get(ScheduledTaskRunRow, occurrence_id)
            assert occurrence is not None
            occurrence.goal_objective = goal_objective
        session.add(
            RunRow(
                run_id=run_id,
                thread_id=thread_id,
                user_id="user-1",
                status=run_status,
                error=error,
                metadata_json={"scheduled_task_id": task_id, "scheduled_task_run_id": occurrence_id},
                goal_verdict=goal_verdict,
            )
        )
        await session.commit()
    return tasks, occurrences, now


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["manual", "scheduled"])
async def test_run_once_finalizes_running_occurrence_from_terminal_run(tmp_path, trigger):
    async with _database(tmp_path) as (_engine, sf):
        tasks, occurrences, now = await _running_occurrence_with_terminal_run(sf, run_status="success", trigger=trigger)
        service = _service(tasks, occurrences)

        await service.run_once(now=now)

        task, occurrence = await _snapshot(sf)
        assert occurrence["status"] == "success"
        assert task["status"] == "enabled"
        assert task["run_count"] == 1
        assert await tasks.reconcile_terminal_runs(now=now) == 0
        assert await _snapshot(sf) == (task, occurrence)


@pytest.mark.asyncio
async def test_reconcile_terminal_runs_isolates_a_poisoned_candidate(tmp_path, caplog):
    import logging

    async with _database(tmp_path) as (_engine, sf):
        tasks, occurrences, now = await _running_occurrence_with_terminal_run(sf, run_status="success", suffix="aaa-poisoned", trigger="scheduled")
        await _running_occurrence_with_terminal_run(sf, run_status="success", suffix="zzz-healthy", trigger="scheduled")
        service = _service(tasks, occurrences)
        original = tasks._finalization_observer

        async def poisoned_observer(session, task, occurrence, *, events):
            if task is not None and task.id == "task-aaa-poisoned":
                raise RuntimeError("poisoned finalization observer")
            if original is not None:
                await original(session, task, occurrence, events=events)

        tasks.set_finalization_observer(poisoned_observer)

        with caplog.at_level(logging.ERROR):
            await service.run_once(now=now)

        healthy_task, healthy_occurrence = await _snapshot(sf, "task-zzz-healthy", "occurrence-zzz-healthy")
        poisoned_task, poisoned_occurrence = await _snapshot(sf, "task-aaa-poisoned", "occurrence-aaa-poisoned")
        assert healthy_occurrence["status"] == "success"
        assert healthy_task["status"] == "enabled"
        assert poisoned_occurrence["status"] == "running"
        assert poisoned_task["status"] == "enabled"
        assert "Failed to reconcile scheduled occurrence occurrence-aaa-poisoned" in caplog.text


@pytest.mark.asyncio
async def test_run_once_projects_once_task_from_terminal_run(tmp_path):
    async with _database(tmp_path) as (_engine, sf):
        tasks, occurrences, now = await _running_occurrence_with_terminal_run(sf, run_status="success", schedule_type="once", trigger="scheduled")
        service = _service(tasks, occurrences)

        await service.run_once(now=now)

        task, occurrence = await _snapshot(sf)
        assert occurrence["status"] == "success"
        assert task["status"] == "completed"


@pytest.mark.asyncio
async def test_run_once_uses_terminal_run_goal_verdict(tmp_path):
    async with _database(tmp_path) as (_engine, sf):
        tasks, occurrences, now = await _running_occurrence_with_terminal_run(
            sf,
            run_status="success",
            goal_objective="ship it",
            goal_verdict={"satisfied": False, "stand_down_reason": "not_met"},
        )
        service = _service(tasks, occurrences)

        await service.run_once(now=now)

        task, occurrence = await _snapshot(sf)
        assert occurrence["status"] == "unmet"
        assert occurrence["error"] == "not_met"
        assert task["last_error"] == "not_met"


@pytest.mark.asyncio
async def test_run_once_leaves_running_occurrence_with_live_run_alone(tmp_path):
    async with _database(tmp_path) as (_engine, sf):
        tasks, occurrences, now = await _running_occurrence_with_terminal_run(sf, run_status="running")
        service = _service(tasks, occurrences)

        await service.run_once(now=now)

        task, occurrence = await _snapshot(sf)
        assert occurrence["status"] == "running"
        assert task["status"] == "enabled"
        assert task["run_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("run_status", "error", "occurrence_status", "expected_error"),
    [
        ("error", "boom", "failed", "boom"),
        ("timeout", "time limit", "failed", "time limit"),
        ("interrupted", None, "interrupted", RUN_ERROR_INTERRUPTED),
    ],
)
async def test_run_once_finalizes_terminal_run_outcomes(tmp_path, run_status, error, occurrence_status, expected_error):
    async with _database(tmp_path) as (_engine, sf):
        tasks, occurrences, now = await _running_occurrence_with_terminal_run(sf, run_status=run_status, error=error)
        service = _service(tasks, occurrences)

        await service.run_once(now=now)

        task, occurrence = await _snapshot(sf)
        assert occurrence["status"] == occurrence_status
        assert task["status"] == "enabled"
        assert task["last_error"] == expected_error


@pytest.mark.asyncio
async def test_completion_commit_failure_rolls_back_outcome_and_accounting(tmp_path):
    async with _database(tmp_path) as (engine, sf):
        tasks, occurrences, _now = await _launching_occurrence(sf, schedule_type="once")
        before = await _snapshot(sf)

        class FailingCommitSession(AsyncSession):
            async def commit(self):
                await self.flush()
                raise RuntimeError("completion commit failed")

        failing_sf = async_sessionmaker(engine, class_=FailingCommitSession, expire_on_commit=False)
        failing_service = _service(ScheduledTaskRepository(failing_sf), occurrences)
        record = _completion(RunStatus.success, None)
        with pytest.raises(RuntimeError, match="completion commit failed"):
            await failing_service.handle_run_completion(record)

        # In particular, failure cannot leave a terminal child that active-run
        # recovery would skip while the parent count still lacks this launch.
        assert await _snapshot(sf) == before
        service = _service(tasks, occurrences)
        await service.handle_run_completion(record)
        await service.handle_run_completion(record)
        task, occurrence = await _snapshot(sf)
        assert task["status"] == "completed"
        assert task["run_count"] == 1
        assert occurrence["status"] == "success"
        assert occurrence["launch_accounted"] is True
