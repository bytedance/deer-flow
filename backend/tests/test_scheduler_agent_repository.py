import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_events import ScheduledTaskEventRow
from deerflow.persistence.scheduled_task_runs import ScheduledTaskAdmissionRejected, ScheduledTaskRunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskLimitsExhausted, ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.persistence.scheduled_tasks.sql import ActiveScheduledTaskMutationConflict
from deerflow.persistence.thread_meta.model import ThreadMetaRow

NOW = datetime(2026, 10, 3, 8, tzinfo=UTC)
VERDICT = {"satisfied": False, "blocker": "goal_not_met_yet", "reason": "missing evidence", "evidence_summary": "none", "relied_on_assumption": False, "stand_down_reason": "max_continuations"}


@pytest.fixture(params=["sqlite", "postgres"])
def database_backend(request):
    return request.param


@asynccontextmanager
async def database(tmp_path, *, backend="sqlite"):
    schema = None
    if backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres scheduler contracts)")
        parts = urlsplit(uri)
        scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
        query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
        uri = urlunsplit(parts._replace(scheme=scheme, query=query))
        schema = f"scheduler_contract_{uuid.uuid4().hex}"
        engine = create_async_engine(uri, connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent-schedules.db'}")
    try:
        async with engine.begin() as conn:
            if schema:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[ScheduledTaskRow.__table__, ScheduledTaskRunRow.__table__, RunRow.__table__, ThreadMetaRow.__table__, ScheduledTaskEventRow.__table__]))
        sf = async_sessionmaker(engine, expire_on_commit=False)
        yield sf, ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf)
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def task(repo, task_id="task", **extra):
    return await repo.create(
        task_id=task_id,
        user_id="owner",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title="report",
        prompt="write report",
        schedule_type="interval",
        schedule_spec={"every_seconds": 3600},
        timezone="UTC",
        next_run_at=NOW,
        origin_thread_id="origin",
        **extra,
    )


async def occurrence(sf, repo, task_id="task", suffix="1", *, trigger="scheduled", verdict=None, durable_status="success"):
    occurrence_id, run_id = f"occ-{suffix}", f"run-{suffix}"
    await repo.create(run_record_id=occurrence_id, task_id=task_id, thread_id=f"thread-{suffix}", scheduled_for=NOW, trigger=trigger, status="running")
    await repo.update_status(occurrence_id, status="running", run_id=run_id, started_at=NOW)
    async with sf() as session:
        session.add(RunRow(run_id=run_id, thread_id=f"thread-{suffix}", user_id="owner", status=durable_status, goal_verdict=verdict, metadata_json={"scheduled_task_id": task_id, "scheduled_task_run_id": occurrence_id}, created_at=NOW))
        await session.commit()
    return occurrence_id, run_id


async def complete(tasks, occurrence_id, run_id, *, status="success", verdict=None, error=None):
    return await tasks.complete_run("task", user_id="owner", task_run_id=occurrence_id, run_id=run_id, status=status, error=error, finished_at=NOW, goal_verdict=verdict)


@pytest.mark.asyncio
async def test_origin_scope_notes_and_serialized_deadline(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        created = await task(tasks, end_at=NOW + timedelta(days=1))
        assert created["end_at"] == (NOW + timedelta(days=1)).isoformat()
        assert len(await tasks.list_by_user_and_thread("owner", "origin")) == 1
        assert await tasks.append_standing_note("task", user_id="owner", origin_thread_id="wrong", note="develop branch") is None
        updated = await tasks.append_standing_note("task", user_id="owner", origin_thread_id="origin", note="develop branch")
        assert updated["standing_notes"] == ["develop branch"]
        await occurrence(sf, runs)
        with pytest.raises(ActiveScheduledTaskMutationConflict, match="active"):
            await tasks.append_standing_note("task", user_id="owner", origin_thread_id="origin", note="another note")


@pytest.mark.asyncio
async def test_owner_quota_serializes_concurrent_creates_and_counts_paused(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (_sf, tasks, _runs):
        for index in range(19):
            await task(tasks, f"task-{index}")
        await tasks.update("task-0", user_id="owner", updates={"status": "paused"})
        results = await asyncio.gather(task(tasks, "a"), task(tasks, "b"), return_exceptions=True)
        assert sum(isinstance(result, dict) for result in results) == 1
        assert "20" in str(next(result for result in results if isinstance(result, Exception)))


@pytest.mark.asyncio
async def test_stop_request_is_first_terminal_only_after_resume(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        await task(tasks)
        occurrence_id, run_id = await occurrence(sf, runs, durable_status="running")
        assert await runs.request_stop(occurrence_id, task_id="task", run_id=run_id, user_id="intruder") is False
        assert await runs.request_stop(occurrence_id, task_id="task", run_id=run_id, user_id="owner") is True
        assert await complete(tasks, occurrence_id, run_id) is True
        stopped = await tasks.get("task", user_id="owner")
        assert stopped["status"] == "paused"
        assert stopped["last_error"] == f"stopped by the agent in run {run_id}"
        await tasks.update("task", user_id="owner", updates={"status": "enabled", "last_error": None})
        assert await complete(tasks, occurrence_id, run_id, status="failed", error="late") is False
        assert (await tasks.get("task", user_id="owner"))["status"] == "enabled"
        assert (await runs.list_by_task("task"))[0]["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["recover_expired_launch_claims", "mark_stale_active_runs", "reconcile_active_runs"])
async def test_restart_restores_stop_and_goal_outcome_in_same_transaction(tmp_path, database_backend, method):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        await task(tasks, goal_objective="report is complete")
        occurrence_id, run_id = await occurrence(sf, runs, verdict=VERDICT, durable_status="running")
        assert await runs.request_stop(occurrence_id, task_id="task", run_id=run_id, user_id="owner")
        async with sf() as session:
            durable = await session.get(RunRow, run_id)
            durable.status = "success"
            row = await session.get(ScheduledTaskRunRow, occurrence_id)
            row.status = "launching" if method == "recover_expired_launch_claims" else "running"
            await session.commit()
        kwargs = {"error": "restart"}
        if method != "mark_stale_active_runs":
            kwargs["now"] = NOW
        assert await getattr(runs, method)(**kwargs) == 1
        assert (await tasks.get("task", user_id="owner"))["status"] == "paused"
        recorded = (await runs.list_by_task("task"))[0]
        assert recorded["status"] == "unmet"
        assert recorded["goal_objective"] == "report is complete"
        assert recorded["goal_verdict"] == VERDICT
        assert recorded["error"] == "max_continuations"


@pytest.mark.asyncio
async def test_manual_trial_does_not_consume_limit_and_deadline_prevents_admission(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        await task(tasks, max_runs=2)
        for suffix, trigger in [("trial", "manual"), ("first", "scheduled"), ("second", "scheduled")]:
            occurrence_id, run_id = await occurrence(sf, runs, suffix=suffix, trigger=trigger)
            await complete(tasks, occurrence_id, run_id)
            current = await tasks.get("task", user_id="owner")
            assert current["status"] == ("completed" if suffix == "second" else "enabled")
        assert current["run_count"] == 3
        # Reactivating a task whose cap is used up is refused at the repository.
        with pytest.raises(ScheduledTaskLimitsExhausted):
            await tasks.update("task", user_id="owner", updates={"status": "enabled"})
        assert (await tasks.get("task", user_id="owner"))["status"] == "completed"
        # A row enabled by an older writer is still completed before admission.
        async with sf() as session:
            (await session.get(ScheduledTaskRow, "task")).status = "enabled"
            await session.commit()
        assert await tasks.complete_if_ended("task", user_id="owner", now=NOW) is True
        await task(tasks, "expired", end_at=NOW - timedelta(seconds=1))
        assert await tasks.complete_if_ended("expired", now=NOW) is True
        assert (await tasks.get("expired", user_id="owner"))["status"] == "completed"


@pytest.mark.asyncio
async def test_streak_skips_manual_external_wait_and_failure_and_notifies_once(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        await task(tasks, goal_objective="deliver report")
        observed = []

        async def observer(session, parent, row, *, events):
            observed.append((row.id, events, parent.status))

        tasks.set_finalization_observer(observer)
        for suffix, status, trigger, error in [
            ("1", "unmet", "scheduled", "goal_not_met_yet"),
            ("trial", "unmet", "manual", "goal_not_met_yet"),
            ("wait", "unmet", "scheduled", "external_wait"),
            ("failure", "failed", "scheduled", "broken"),
            ("2", "unmet", "scheduled", "goal_not_met_yet"),
            ("3", "unmet", "scheduled", "goal_not_met_yet"),
        ]:
            occurrence_id, run_id = await occurrence(sf, runs, suffix=suffix, trigger=trigger)
            await complete(tasks, occurrence_id, run_id, status=status, error=error)
        assert (await tasks.get("task", user_id="owner"))["status"] == "paused"
        assert observed[-1][1] == ("run_unmet", "task_paused")
        assert await complete(tasks, "occ-3", "run-3", status="unmet", error="goal_not_met_yet") is False
        assert len(observed) == 6


@pytest.mark.asyncio
async def test_end_condition_wins_and_observer_failure_rolls_back(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        await task(tasks, max_runs=1)
        occurrence_id, run_id = await occurrence(sf, runs, durable_status="running")
        assert await runs.request_stop(occurrence_id, task_id="task", run_id=run_id, user_id="owner")

        async def failing_observer(*args, **kwargs):
            raise RuntimeError("outbox unavailable")

        tasks.set_finalization_observer(failing_observer)
        with pytest.raises(RuntimeError, match="outbox unavailable"):
            await complete(tasks, occurrence_id, run_id)
        assert (await runs.list_by_task("task"))[0]["status"] == "running"
        assert (await tasks.get("task", user_id="owner"))["run_count"] == 0
        tasks.set_finalization_observer(None)
        await complete(tasks, occurrence_id, run_id)
        assert (await tasks.get("task", user_id="owner"))["status"] == "completed"


@pytest.mark.asyncio
async def test_previous_occurrence_uses_admission_sequence_and_only_launched_history(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        await task(tasks)
        first, run_id = await occurrence(sf, runs, suffix="first", trigger="manual")
        await complete(tasks, first, run_id)
        await runs.create(run_record_id="unlaunched", task_id="task", thread_id="unlaunched-thread", scheduled_for=NOW + timedelta(days=1), trigger="scheduled", status="failed")
        current, _run_id = await occurrence(sf, runs, suffix="current")
        previous = await runs.previous_occurrence("task", before_task_run_id=current)
        assert previous["id"] == first
        assert previous["thread_id"] == "thread-first"


@pytest.mark.asyncio
async def test_no_verdict_once_is_failed_and_receipt_backfill_preserves_unmet(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        await task(tasks, goal_objective="deliver report")
        await tasks.update("task", user_id="owner", updates={"schedule_type": "once", "schedule_spec": {"run_at": NOW.isoformat()}})
        occurrence_id, run_id = await occurrence(sf, runs)
        await complete(tasks, occurrence_id, run_id)
        assert (await tasks.get("task", user_id="owner"))["status"] == "failed"
        assert await runs.update_status(occurrence_id, status="running", run_id=run_id, started_at=NOW + timedelta(seconds=1), protect_terminal=True)
        assert await runs.reconcile_launched_run(occurrence_id, task_id="task", run_id=run_id, started_at=NOW)
        row = (await runs.list_by_task("task"))[0]
        assert row["status"] == "unmet"
        assert row["error"] == "no_verdict"
        assert (await tasks.get("task", user_id="owner"))["run_count"] == 1


@pytest.mark.asyncio
async def test_success_resets_unmet_streak_and_old_callback_cannot_pause_new_parent(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        await task(tasks, goal_objective="deliver report")
        for suffix, satisfied in [("1", False), ("2", False), ("3", True), ("4", False), ("5", False)]:
            occurrence_id, run_id = await occurrence(sf, runs, suffix=suffix)
            verdict = dict(VERDICT, satisfied=satisfied, relied_on_assumption=satisfied)
            await complete(tasks, occurrence_id, run_id, verdict=verdict)
        assert (await tasks.get("task", user_id="owner"))["status"] == "enabled"
        # The old result cannot be changed after it first became terminal.
        assert await complete(tasks, "occ-3", "run-3", verdict=VERDICT) is False
        assert (await tasks.get("task", user_id="owner"))["status"] == "enabled"


@pytest.mark.asyncio
async def test_queued_dispatch_checks_deadline_under_parent_lock(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (_sf, tasks, runs):
        await task(tasks, end_at=NOW + timedelta(seconds=1))
        await runs.create(run_record_id="waiting", task_id="task", thread_id="thread", scheduled_for=NOW, trigger="scheduled", status="queued")
        assert await runs.claim_queued_run("waiting", lease_owner="worker", now=NOW + timedelta(seconds=2), lease_seconds=30, global_max_concurrent_runs=1) is None
        assert (await tasks.get("task", user_id="owner"))["status"] == "completed"
        assert (await runs.list_by_task("task"))[0]["status"] == "skipped"


@pytest.mark.asyncio
async def test_notes_bounds_and_tool_quota_excludes_terminal_and_legacy_tasks(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (_sf, tasks, _runs):
        for index in range(20):
            await task(tasks, f"task-{index}")
        await tasks.update("task-0", user_id="owner", updates={"status": "completed"})
        await task(tasks, "replacement", standing_notes=["note"] * 10)
        with pytest.raises(ValueError, match="10"):
            await tasks.append_standing_note("replacement", user_id="owner", origin_thread_id="origin", note="extra")
        with pytest.raises(ValueError, match="500"):
            await tasks.append_standing_note("replacement", user_id="owner", origin_thread_id="origin", note="x" * 501)
        # Existing REST callers retain their unbounded quota behavior.
        await tasks.create(
            task_id="legacy",
            user_id="owner",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id=None,
            title="legacy",
            prompt="test",
            schedule_type="interval",
            schedule_spec={"every_seconds": 3600},
            timezone="UTC",
            next_run_at=NOW,
        )


@pytest.mark.asyncio
async def test_concurrent_terminal_callbacks_accept_only_one_outcome(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        await task(tasks)
        occurrence_id, run_id = await occurrence(sf, runs)
        results = await asyncio.gather(complete(tasks, occurrence_id, run_id), complete(tasks, occurrence_id, run_id, status="failed", error="competing callback"))
        assert sorted(results) == [False, True]
        row = (await runs.list_by_task("task"))[0]
        assert row["status"] == ("success" if results[0] else "failed")
        assert (await tasks.get("task", user_id="owner"))["run_count"] == 1


@pytest.mark.asyncio
async def test_postgres_owner_quota_serializes_separate_sessions():
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres quota concurrency)")
    parts = urlsplit(uri)
    scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
    uri = urlunsplit(parts._replace(scheme=scheme, query=query))
    schema = f"scheduler_quota_{uuid.uuid4().hex}"
    engine = create_async_engine(uri, connect_args=build_asyncpg_connect_args(schema))
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[ScheduledTaskRow.__table__, ScheduledTaskRunRow.__table__]))
        sf = async_sessionmaker(engine, expire_on_commit=False)
        tasks_a, tasks_b = ScheduledTaskRepository(sf), ScheduledTaskRepository(sf)
        for index in range(19):
            await task(tasks_a, f"task-{index}")
        results = await asyncio.gather(task(tasks_a, "a"), task(tasks_b, "b"), return_exceptions=True)
        assert sum(isinstance(result, dict) for result in results) == 1
        assert len(await tasks_a.list_by_origin_thread("owner", "origin")) == 20
        winner = next(result["id"] for result in results if isinstance(result, dict))
        await tasks_a.update(winner, user_id="owner", updates={"status": "completed"})
        results = await asyncio.gather(tasks_a.update(winner, user_id="owner", updates={"status": "enabled"}, require_mutable=True), task(tasks_b, "competing-new"), return_exceptions=True)
        assert sum(isinstance(result, dict) for result in results) == 1
        assert type(next(result for result in results if isinstance(result, Exception))).__name__ == "ScheduledTaskQuotaExceeded"
        assert sum(row["status"] in {"enabled", "running", "paused"} for row in await tasks_a.list_by_origin_thread("owner", "origin")) == 20
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


@pytest.mark.asyncio
async def test_reactivation_and_creation_share_atomic_owner_quota(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (_sf, tasks, _runs):
        await task(tasks, "old-terminal")
        await tasks.update("old-terminal", user_id="owner", updates={"status": "completed"})
        for index in range(19):
            await task(tasks, f"active-{index}")
        results = await asyncio.gather(tasks.update("old-terminal", user_id="owner", updates={"status": "enabled"}, require_mutable=True), task(tasks, "new"), return_exceptions=True)
        assert sum(isinstance(result, dict) for result in results) == 1
        assert type(next(result for result in results if isinstance(result, Exception))).__name__ == "ScheduledTaskQuotaExceeded"
        assert sum(row["status"] in {"enabled", "running", "paused"} for row in await tasks.list_by_origin_thread("owner", "origin")) == 20


@pytest.mark.asyncio
async def test_full_quota_blocks_terminal_reactivation_but_preserves_paused_and_legacy(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (_sf, tasks, _runs):
        await task(tasks, "old-terminal")
        await tasks.update("old-terminal", user_id="owner", updates={"status": "completed"})
        for index in range(20):
            await task(tasks, f"active-{index}")
        with pytest.raises(ValueError, match="20"):
            await tasks.update("old-terminal", user_id="owner", updates={"status": "enabled"}, require_mutable=True)
        assert (await tasks.get("old-terminal", user_id="owner"))["status"] == "completed"
        await tasks.update("active-0", user_id="owner", updates={"status": "paused"})
        assert (await tasks.update("active-0", user_id="owner", updates={"status": "enabled"}, require_mutable=True))["status"] == "enabled"
        await tasks.create(
            task_id="legacy",
            user_id="owner",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id=None,
            title="legacy",
            prompt="test",
            schedule_type="interval",
            schedule_spec={"every_seconds": 3600},
            timezone="UTC",
            next_run_at=NOW,
        )
        await tasks.update("legacy", user_id="owner", updates={"status": "completed"})
        assert (await tasks.update("legacy", user_id="owner", updates={"status": "enabled"}, require_mutable=True))["status"] == "enabled"


@pytest.mark.asyncio
async def test_terminal_durable_result_wins_a_failed_takeover_race(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        await task(tasks, goal_objective="deliver report")
        occurrence_id, run_id = await occurrence(sf, runs, durable_status="running")

        class CompletionWinsTakeover(RunRepository):
            async def claim_for_takeover(self, selected_run_id, **kwargs):
                # Another worker completes between the recovery snapshot and
                # takeover CAS. The real repository read observes that commit.
                async with sf() as session:
                    row = await session.get(RunRow, selected_run_id)
                    row.status = "success"
                    row.goal_verdict = {"satisfied": True, "relied_on_assumption": False}
                    await session.commit()
                return False

        recovering = ScheduledTaskRunRepository(sf, run_repository=CompletionWinsTakeover(sf))
        assert await recovering.reconcile_active_runs(error="restart", now=NOW) == 1
        recorded = (await runs.list_by_task("task"))[0]
        assert recorded["status"] == "success"
        assert recorded["goal_verdict"]["satisfied"] is True
        assert (await tasks.get("task", user_id="owner"))["run_count"] == 1


@pytest.mark.asyncio
async def test_update_preserves_goal_fresh_thread_invariant_under_lock(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (_sf, tasks, _runs):
        await task(tasks, goal_objective="deliver report")
        before = await tasks.get("task", user_id="owner")
        with pytest.raises(ValueError, match="fresh_thread_per_run"):
            await tasks.update("task", user_id="owner", updates={"context_mode": "reuse_thread", "thread_id": "reused"}, require_mutable=True)
        assert await tasks.get("task", user_id="owner") == before
        await task(tasks, "no-goal")
        updated = await tasks.update("no-goal", user_id="owner", updates={"context_mode": "reuse_thread", "thread_id": "reused"}, require_mutable=True)
        assert updated["context_mode"] == "reuse_thread"


@pytest.mark.asyncio
@pytest.mark.parametrize("objective", [pytest.param("", id="empty"), pytest.param(" \t\n ", id="blank"), pytest.param("x" * 4001, id="too-long")])
async def test_create_rejects_invalid_goal_without_inserting_task(tmp_path, database_backend, objective):
    async with database(tmp_path, backend=database_backend) as (_sf, tasks, _runs):
        with pytest.raises(ValueError, match="Goal objective"):
            await task(tasks, goal_objective=objective)
        assert await tasks.list_by_origin_thread("owner", "origin") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("objective", [pytest.param("", id="empty"), pytest.param(" \t\n ", id="blank"), pytest.param("x" * 4001, id="too-long")])
async def test_update_rejects_invalid_goal_without_changing_task(tmp_path, database_backend, objective):
    async with database(tmp_path, backend=database_backend) as (_sf, tasks, _runs):
        before = await task(tasks, goal_objective="deliver report")
        with pytest.raises(ValueError, match="Goal objective"):
            await tasks.update("task", user_id="owner", updates={"goal_objective": objective, "title": "changed"}, require_mutable=True)
        assert await tasks.get("task", user_id="owner") == before


@pytest.mark.asyncio
@pytest.mark.parametrize("objective", [pytest.param(None, id="none"), pytest.param("  deliver\t report\n ", id="original-text"), pytest.param(" \n" + "x" * 4000 + "\t ", id="normalized-limit")])
async def test_create_and_update_preserve_valid_goal_text(tmp_path, database_backend, objective):
    async with database(tmp_path, backend=database_backend) as (_sf, tasks, _runs):
        created = await task(tasks, goal_objective=objective)
        assert created["goal_objective"] == objective
        await task(tasks, "updated", goal_objective="previous goal")
        updated = await tasks.update("updated", user_id="owner", updates={"goal_objective": objective}, require_mutable=True)
        assert updated["goal_objective"] == objective
        assert (await tasks.get("updated", user_id="owner"))["goal_objective"] == objective


@pytest.mark.asyncio
@pytest.mark.parametrize("live_count", [19, 20])
async def test_terminal_pause_is_finished_and_takes_no_quota_slot(tmp_path, database_backend, live_count):
    async with database(tmp_path, backend=database_backend) as (_sf, tasks, _runs):
        await task(tasks, "terminal")
        await tasks.update("terminal", user_id="owner", updates={"status": "completed"})
        for index in range(live_count):
            await task(tasks, f"live-{index}")
        before = await tasks.get("terminal", user_id="owner")
        assert await tasks.pause_with_queue_cancellation("terminal", user_id="owner", error="pause", now=NOW) == "finished"
        assert await tasks.get("terminal", user_id="owner") == before
        assert sum(row["status"] in {"enabled", "running", "paused"} for row in await tasks.list_by_origin_thread("owner", "origin")) == live_count
        await tasks.create(
            task_id="legacy",
            user_id="owner",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id=None,
            title="legacy",
            prompt="test",
            schedule_type="interval",
            schedule_spec={"every_seconds": 3600},
            timezone="UTC",
            next_run_at=NOW,
        )
        await tasks.update("legacy", user_id="owner", updates={"status": "completed"})
        assert await tasks.pause_with_queue_cancellation("legacy", user_id="owner", error="legacy pause", now=NOW) == "finished"


@pytest.mark.asyncio
async def test_terminal_pause_cannot_race_a_create_out_of_its_quota_slot(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (_sf, tasks, _runs):
        await task(tasks, "terminal")
        await tasks.update("terminal", user_id="owner", updates={"status": "completed"})
        for index in range(19):
            await task(tasks, f"live-{index}")
        results = await asyncio.gather(tasks.pause_with_queue_cancellation("terminal", user_id="owner", error="pause", now=NOW), task(tasks, "new"), return_exceptions=True)
        assert results[0] == "finished"
        assert isinstance(results[1], dict)
        assert sum(row["status"] in {"enabled", "running", "paused"} for row in await tasks.list_by_origin_thread("owner", "origin")) == 20


# --- Lifecycle events (task_stopped / task_paused / task_finished) ----------------------


async def lifecycle_task(sf, tasks, runs, *, once=False, **extra):
    """The task (``once`` makes it a once task) and its originating chat, with the
    scheduler's real finalization observer installed; returns each recorded call."""
    from app.scheduler.service import ScheduledTaskService

    await task(tasks, **extra)
    if once:
        await tasks.update("task", user_id="owner", updates={"schedule_type": "once", "schedule_spec": {"run_at": NOW.isoformat()}})
    async with sf() as session:
        session.add(ThreadMetaRow(thread_id="origin", user_id="owner"))
        await session.commit()
    service = ScheduledTaskService(task_repo=tasks, task_run_repo=runs, launch_run=None, poll_interval_seconds=60, lease_seconds=30, max_concurrent_runs=3)
    observed = []

    async def observer(session, parent, row, *, events):
        observed.append((row.id if row is not None else None, events))
        await service._on_finalization(session, parent, row, events=events)

    for repository in (tasks, runs):
        repository.set_finalization_observer(observer)
    return observed


def lifecycle_calls(observed):
    return [(occurrence_id, tuple(event for event in events if event.startswith("task_"))) for occurrence_id, events in observed if any(event.startswith("task_") for event in events)]


async def event_rows(sf):
    async with sf() as session:
        return list((await session.execute(select(ScheduledTaskEventRow).order_by(ScheduledTaskEventRow.created_at, ScheduledTaskEventRow.id))).scalars())


@pytest.mark.asyncio
async def test_agent_stop_emits_task_stopped_once(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs)
        occurrence_id, run_id = await occurrence(sf, runs, durable_status="running")
        assert await runs.request_stop(occurrence_id, task_id="task", run_id=run_id, user_id="owner")
        assert await complete(tasks, occurrence_id, run_id) is True
        assert observed == [(occurrence_id, ("run_completed", "task_stopped"))]
        assert await complete(tasks, occurrence_id, run_id) is False
        assert len(observed) == 1
        rows = await event_rows(sf)
        assert [(row.event, row.reason_code, row.anchor, row.occurrence_id, row.thread_id) for row in rows] == [("task_stopped", "agent_stop", occurrence_id, occurrence_id, "origin")]


@pytest.mark.asyncio
async def test_max_runs_completion_emits_task_finished(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs, max_runs=2)
        for suffix in ("1", "2"):
            occurrence_id, run_id = await occurrence(sf, runs, suffix=suffix)
            await complete(tasks, occurrence_id, run_id)
        assert observed == [("occ-1", ("run_completed",)), ("occ-2", ("run_completed", "task_finished"))]
        assert (await tasks.get("task", user_id="owner"))["status"] == "completed"
        rows = await event_rows(sf)
        assert [(row.event, row.reason_code, row.anchor) for row in rows] == [("task_finished", "max_runs", "occ-2")]
        assert rows[0].payload_json["max_runs"] == 2


@pytest.mark.asyncio
async def test_end_condition_wins_over_agent_stop_events(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs, max_runs=1)
        occurrence_id, run_id = await occurrence(sf, runs, durable_status="running")
        assert await runs.request_stop(occurrence_id, task_id="task", run_id=run_id, user_id="owner")
        await complete(tasks, occurrence_id, run_id)
        assert observed == [(occurrence_id, ("run_completed", "task_finished"))]
        assert [row.event for row in await event_rows(sf)] == ["task_finished"]


@pytest.mark.asyncio
async def test_idle_end_at_finish_emits_with_end_anchor_once(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs, end_at=NOW)
        assert await tasks.complete_if_ended("task", user_id="owner", now=NOW + timedelta(seconds=1)) is True
        assert await tasks.complete_if_ended("task", user_id="owner", now=NOW + timedelta(seconds=2)) is True
        assert observed == [(None, ("task_finished",))]
        rows = await event_rows(sf)
        assert [(row.event, row.reason_code, row.anchor, row.occurrence_id) for row in rows] == [("task_finished", "end_at", f"end:{NOW.isoformat()}", None)]
        assert (await tasks.get("task", user_id="owner"))["status"] == "completed"


@pytest.mark.asyncio
async def test_idle_max_runs_finish_then_end_time_finish_writes_two_events(tmp_path, database_backend):
    """An idle max_runs finish before the end time must not take the end-time
    anchor: after a reactivation, the real end-time finish still gets its line."""
    end = NOW + timedelta(hours=1)
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs, end_at=end, max_runs=1)
        await runs.create(run_record_id="used", task_id="task", thread_id="thread", scheduled_for=NOW, trigger="scheduled", status="queued")
        async with sf() as session:
            row = await session.get(ScheduledTaskRunRow, "used")
            row.status, row.launch_accounted, row.finished_at = "success", True, NOW
            await session.commit()
        assert await tasks.complete_if_ended("task", user_id="owner", now=NOW + timedelta(seconds=1)) is True
        async with sf() as session:
            parent = await session.get(ScheduledTaskRow, "task")
            parent.status, parent.max_runs = "enabled", 5
            await session.commit()
        assert await tasks.complete_if_ended("task", user_id="owner", now=end + timedelta(seconds=1)) is True
        assert observed == [(None, ("task_finished",)), (None, ("task_finished",))]
        rows = await event_rows(sf)
        assert [(row.event, row.reason_code, row.anchor) for row in rows] == [
            ("task_finished", "max_runs", "seq:1"),
            ("task_finished", "end_at", f"end:{end.isoformat()}"),
        ]


@pytest.mark.asyncio
async def test_claim_time_end_skip_emits_task_finished_once(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs, end_at=NOW + timedelta(seconds=1))
        await runs.create(run_record_id="waiting", task_id="task", thread_id="thread", scheduled_for=NOW, trigger="scheduled", status="queued")
        assert await runs.claim_queued_run("waiting", lease_owner="worker", now=NOW + timedelta(seconds=2), lease_seconds=30, global_max_concurrent_runs=1) is None
        assert lifecycle_calls(observed) == [("waiting", ("task_finished",))]
        assert len(observed) == 1
        rows = await event_rows(sf)
        assert [(row.event, row.reason_code, row.anchor) for row in rows] == [("task_finished", "end_at", "waiting")]
        assert (await tasks.get("task", user_id="owner"))["status"] == "completed"


@pytest.mark.asyncio
async def test_complete_if_ended_with_queued_row_emits_once(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs, end_at=NOW + timedelta(seconds=1))
        await runs.create(run_record_id="waiting", task_id="task", thread_id="thread", scheduled_for=NOW, trigger="scheduled", status="queued")
        assert await tasks.complete_if_ended("task", user_id="owner", now=NOW + timedelta(seconds=2)) is True
        assert observed == [("waiting", ("task_finished",))]
        assert [(row.event, row.anchor) for row in await event_rows(sf)] == [("task_finished", "waiting")]
        assert (await runs.list_by_task("task"))[0]["status"] == "skipped"


@pytest.mark.asyncio
async def test_complete_if_ended_with_queued_manual_row_emits_idle_finish(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs, end_at=NOW + timedelta(seconds=1))
        await runs.create(run_record_id="trial", task_id="task", thread_id="thread", scheduled_for=NOW, trigger="manual", status="queued")
        assert await tasks.complete_if_ended("task", user_id="owner", now=NOW + timedelta(seconds=2)) is True
        assert observed == [(None, ("task_finished",))]
        rows = await event_rows(sf)
        assert [(row.event, row.anchor, row.occurrence_id) for row in rows] == [("task_finished", f"end:{(NOW + timedelta(seconds=1)).isoformat()}", None)]
        # The waiting trial is left alone; only scheduled rows are skipped.
        assert (await runs.list_by_task("task"))[0]["status"] == "queued"


@pytest.mark.asyncio
async def test_once_task_end_skip_stays_silent(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs, once=True, end_at=NOW + timedelta(seconds=1))
        await runs.create(run_record_id="waiting", task_id="task", thread_id="thread", scheduled_for=NOW, trigger="scheduled", status="queued")
        assert await runs.claim_queued_run("waiting", lease_owner="worker", now=NOW + timedelta(seconds=2), lease_seconds=30, global_max_concurrent_runs=1) is None
        # As in PR1: skipped -> cancelled, then the end condition marks it completed.
        assert (await tasks.get("task", user_id="owner"))["status"] == "completed"
        assert lifecycle_calls(observed) == []
        assert await event_rows(sf) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error", "reason"),
    [("success", None, "once_done"), ("failed", "boom", "once_failed"), ("unmet", "goal_not_met_yet", "once_failed"), ("interrupted", "cancelled", None), ("skipped", None, None)],
)
async def test_once_task_finish_reasons(tmp_path, database_backend, status, error, reason):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs, once=True)
        occurrence_id, run_id = await occurrence(sf, runs)
        assert await complete(tasks, occurrence_id, run_id, status=status, error=error) is True
        rows = await event_rows(sf)
        if reason is None:
            assert lifecycle_calls(observed) == []
            assert rows == []
        else:
            assert lifecycle_calls(observed) == [(occurrence_id, ("task_finished",))]
            assert [(row.event, row.reason_code, row.anchor) for row in rows] == [("task_finished", reason, occurrence_id)]


@pytest.mark.asyncio
async def test_admission_time_end_emits_task_finished(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs, end_at=NOW - timedelta(seconds=1))
        with pytest.raises(ScheduledTaskAdmissionRejected) as rejected:
            await runs.create(run_record_id="admitted", task_id="task", thread_id="thread", scheduled_for=NOW, trigger="scheduled", status="queued", coordinate_with_task=True, expected_task_user_id="owner")
        assert rejected.value.reason == "ended"
        assert (await tasks.get("task", user_id="owner"))["status"] == "completed"
        assert observed == [(None, ("task_finished",))]
        rows = await event_rows(sf)
        assert [(row.event, row.reason_code, row.occurrence_id) for row in rows] == [("task_finished", "end_at", None)]
        assert await runs.list_by_task("task") == []


@pytest.mark.asyncio
async def test_manual_trial_that_reaches_end_at_emits_task_finished(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs, end_at=NOW)
        occurrence_id, run_id = await occurrence(sf, runs, suffix="trial", trigger="manual")
        await complete(tasks, occurrence_id, run_id)
        # Finalization reports the run event too; the observer drops only that for a trial.
        assert observed == [(occurrence_id, ("run_completed", "task_finished"))]
        assert [(row.event, row.reason_code, row.anchor) for row in await event_rows(sf)] == [("task_finished", "end_at", occurrence_id)]
        assert (await tasks.get("task", user_id="owner"))["status"] == "completed"


@pytest.mark.asyncio
async def test_manual_trial_agent_stop_emits_task_stopped(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs)
        occurrence_id, run_id = await occurrence(sf, runs, suffix="trial", trigger="manual", durable_status="running")
        assert await runs.request_stop(occurrence_id, task_id="task", run_id=run_id, user_id="owner")
        await complete(tasks, occurrence_id, run_id)
        assert observed == [(occurrence_id, ("run_completed", "task_stopped"))]
        assert [row.event for row in await event_rows(sf)] == ["task_stopped"]
        assert (await tasks.get("task", user_id="owner"))["status"] == "paused"


@pytest.mark.asyncio
async def test_agent_stop_after_failed_run_pauses_and_says_run_failed(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        observed = await lifecycle_task(sf, tasks, runs)
        occurrence_id, run_id = await occurrence(sf, runs, durable_status="running")
        assert await runs.request_stop(occurrence_id, task_id="task", run_id=run_id, user_id="owner")
        await complete(tasks, occurrence_id, run_id, status="failed", error="boom")
        # The transition is PR1's: a stop request pauses whatever the run outcome.
        stopped = await tasks.get("task", user_id="owner")
        assert stopped["status"] == "paused"
        assert stopped["last_error"] == f"stopped by the agent in run {run_id}"
        assert observed == [(occurrence_id, ("run_failed", "task_stopped"))]
        (row,) = await event_rows(sf)
        assert (row.event, row.payload_json["run_status"]) == ("task_stopped", "failed")


def test_no_inline_end_condition_completion():
    """Only finalize_occurrence and finish_task_at_end_condition finish a task.

    The once-task repair in ``_associate_task_with_run`` mirrors a once run's
    own outcome (not an end condition) and is the single allowed assignment.
    """
    import ast
    from pathlib import Path

    from deerflow.persistence.scheduled_task_runs import sql as run_sql
    from deerflow.persistence.scheduled_tasks import sql as task_sql

    class Finder(ast.NodeVisitor):
        def __init__(self):
            self.stack = []
            self.found = []

        def _visit_function(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _visit_function
        visit_AsyncFunctionDef = _visit_function

        def visit_Assign(self, node):
            targets_status = any(isinstance(target, ast.Attribute) and target.attr == "status" for target in node.targets)
            if targets_status and isinstance(node.value, ast.Constant) and node.value.value == "completed":
                self.found.append(self.stack[-1] if self.stack else "<module>")
            self.generic_visit(node)

    found = []
    for module in (run_sql, task_sql):
        finder = Finder()
        finder.visit(ast.parse(Path(module.__file__).read_text(encoding="utf-8")))
        found += [(module.__name__.rsplit(".", 2)[-2], name) for name in finder.found]
    assert found == [("scheduled_task_runs", "_associate_task_with_run")]
