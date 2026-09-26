"""Recovery observability retries must not change a scheduled run's outcome."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.run.model import RunChangeClockRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_task_runs.sql import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.persistence.scheduled_tasks.sql import ScheduledTaskRepository


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_action", [None, "interrupt"])
@pytest.mark.parametrize("retry_callback", [False, True])
async def test_scheduler_projects_claimed_outcome_identically_before_and_after_retry(tmp_path, cancel_action, retry_callback):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scheduler.db'}")
    try:
        async with engine.begin() as connection:
            for model in (RunRow, RunChangeClockRow, ScheduledTaskRow, ScheduledTaskRunRow):
                await connection.run_sync(model.__table__.create)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        runs = RunRepository(sf)
        tasks = ScheduledTaskRepository(sf, run_repository=runs)
        occurrences = ScheduledTaskRunRepository(sf, run_repository=runs)
        now = datetime.now(UTC)
        await tasks.create(
            task_id="task-1",
            user_id="alice",
            thread_id="thread-1",
            context_mode="reuse_thread",
            assistant_id="lead_agent",
            title="Daily summary",
            prompt="Summarize this thread",
            schedule_type="cron",
            schedule_spec={"cron": "0 9 * * *"},
            timezone="UTC",
            next_run_at=None,
        )
        await occurrences.create(run_record_id="occurrence-1", task_id="task-1", thread_id="thread-1", scheduled_for=now, trigger="scheduled", status="running")
        await occurrences.update_status("occurrence-1", status="running", run_id="run-1")
        await runs.put(
            "run-1",
            thread_id="thread-1",
            user_id="alice",
            status="running",
            owner_worker_id="stopped-worker",
            lease_expires_at=(now - timedelta(seconds=60)).isoformat(),
        )
        if cancel_action is not None:
            assert await runs.request_cancel("run-1", action=cancel_action) == cancel_action

        callback_entered = asyncio.Event()
        release_callback = asyncio.Event()
        callback_calls = 0

        async def on_runs_recovered(run_ids):
            nonlocal callback_calls
            assert run_ids == ["run-1"]
            callback_calls += 1
            callback_entered.set()
            await release_callback.wait()
            return not retry_callback or callback_calls > 1

        for attempt in range(2 if retry_callback else 1):
            recovery = asyncio.create_task(occurrences.reconcile_active_runs(error="Worker stopped", now=now, owner_worker_id="recovery-worker", on_runs_recovered=on_runs_recovered))
            try:
                await asyncio.wait_for(callback_entered.wait(), timeout=10)
                # Takeover has committed, but the occurrence remains a durable
                # retry marker until terminal observability succeeds.
                durable = await runs.get("run-1", user_id="alice")
                assert durable["status"] == ("interrupted" if cancel_action else "error")
                assert durable["cancel_action"] == cancel_action
                assert (await occurrences.list_by_task("task-1"))[0]["status"] == "running"
            finally:
                release_callback.set()
                result = await recovery
            if retry_callback and attempt == 0:
                assert result == 0
                assert (await occurrences.list_by_task("task-1"))[0]["status"] == "running"
                callback_entered.clear()
                release_callback.clear()
            else:
                assert result == 1

        completed = (await occurrences.list_by_task("task-1"))[0]
        assert completed["status"] == ("interrupted" if cancel_action else "failed")
        assert completed["error"] == "Worker stopped"
        assert completed["run_id"] == "run-1"
        assert callback_calls == (2 if retry_callback else 1)
    finally:
        await engine.dispose()
