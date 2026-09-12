from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.scheduler.service import ScheduledTaskService
from deerflow.persistence.base import Base
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.runtime import RunStatus
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode


@asynccontextmanager
async def _database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'completion.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[ScheduledTaskRow.__table__, ScheduledTaskRunRow.__table__]))
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _launching_occurrence(sf, *, schedule_type):
    now = datetime(2026, 9, 9, 8, tzinfo=UTC)
    tasks = ScheduledTaskRepository(sf)
    occurrences = ScheduledTaskRunRepository(sf)
    spec = {"run_at": now.isoformat()} if schedule_type == "once" else {"cron": "0 9 * * *"}
    await tasks.create(
        task_id="task-completion",
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
        run_record_id="occurrence-completion",
        task_id="task-completion",
        thread_id="thread-completion",
        scheduled_for=now,
        trigger="manual",
        status="queued",
    )
    claimed = await occurrences.claim_queued_run(
        "occurrence-completion",
        lease_owner="launcher",
        now=now,
        lease_seconds=120,
        global_max_concurrent_runs=3,
    )
    assert claimed is not None
    await tasks.update(
        "task-completion",
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


async def _snapshot(sf):
    async with sf() as session:
        task = await session.get(ScheduledTaskRow, "task-completion")
        occurrence = await session.get(ScheduledTaskRunRow, "occurrence-completion")
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
