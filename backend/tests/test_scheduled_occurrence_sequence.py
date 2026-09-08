"""Database ordering is per task and survives retries independently of caller clocks."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import deerflow.persistence.models  # noqa: F401
from deerflow.persistence.base import Base
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.scheduled_task_runs import ActiveScheduledRunConflict, ScheduledTaskRunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def occurrence_factories(request, tmp_path):
    """Two pools guarantee competing admissions use independent DB connections."""
    schema = None
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres for occurrence ordering)")
        parts = urlsplit(uri)
        query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
        uri = urlunsplit(parts._replace(query=query))
        schema = f"occurrence_{uuid.uuid4().hex}"
        options = {"connect_args": build_asyncpg_connect_args(schema)}
    else:
        uri = f"sqlite+aiosqlite:///{tmp_path / 'occurrences.db'}"
        options = {"connect_args": {"timeout": 30}}
    engines = [create_async_engine(uri, **options) for _ in range(2)]
    try:
        async with engines[0].begin() as connection:
            if schema:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        yield tuple(async_sessionmaker(engine, expire_on_commit=False) for engine in engines)
    finally:
        if schema:
            async with engines[0].begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        for engine in engines:
            await engine.dispose()


async def _create_task(factory, task_id="task", *, schedule_type="cron"):
    spec = {"cron": "* * * * *"} if schedule_type == "cron" else {"run_at": datetime(2026, 7, 15, 12, 0, tzinfo=UTC).isoformat()}
    return await ScheduledTaskRepository(factory).create(
        task_id=task_id,
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id=None,
        title="Occurrence ordering",
        prompt="p",
        schedule_type=schedule_type,
        schedule_spec=spec,
        timezone="UTC",
        next_run_at=None,
    )


async def _create_run(factory, run_id, *, task_id="task", status="success"):
    return await ScheduledTaskRunRepository(factory).create(
        run_record_id=run_id,
        task_id=task_id,
        thread_id=f"thread-{run_id}",
        scheduled_for=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
        trigger="manual",
        status=status,
    )


async def _sequence(factory, run_id):
    async with factory() as session:
        return await session.scalar(select(ScheduledTaskRunRow.occurrence_seq).where(ScheduledTaskRunRow.id == run_id))


async def _high_water_mark(factory, task_id="task"):
    async with factory() as session:
        return await session.scalar(select(ScheduledTaskRow.last_occurrence_seq).where(ScheduledTaskRow.id == task_id))


async def test_concurrent_allocations_use_distinct_monotonic_sequences(occurrence_factories):
    first, second = occurrence_factories
    original = await _create_task(first)
    ready = [asyncio.Event(), asyncio.Event()]
    start = asyncio.Event()

    async def admit(factory, lane):
        ready[lane].set()
        await start.wait()
        for index in range(4):
            await _create_run(factory, f"run-{lane}-{index}")

    admissions = [asyncio.create_task(admit(factory, lane)) for lane, factory in enumerate((first, second))]
    await asyncio.gather(*(event.wait() for event in ready))
    start.set()
    await asyncio.gather(*admissions)
    sequences = [await _sequence(first, f"run-{lane}-{index}") for lane in range(2) for index in range(4)]
    assert sorted(sequences) == list(range(1, 9))
    for lane in range(2):
        lane_sequences = sequences[lane * 4 : (lane + 1) * 4]
        assert lane_sequences == sorted(lane_sequences)
    assert await _high_water_mark(first) == 8
    current = await ScheduledTaskRepository(first).get("task", user_id="user-1")
    assert current["updated_at"] == original["updated_at"]
    assert current["run_count"] == 0


async def test_sequence_allocation_is_independent_per_task(occurrence_factories):
    first, second = occurrence_factories
    for task_id in ("task-a", "task-b"):
        await _create_task(first, task_id)
    await _create_run(first, "run-a1", task_id="task-a")
    await _create_run(second, "run-a2", task_id="task-a")
    await _create_run(second, "run-b1", task_id="task-b")
    assert [await _sequence(first, run_id) for run_id in ("run-a1", "run-a2", "run-b1")] == [1, 2, 1]


async def test_active_conflict_rolls_back_sequence_allocation(occurrence_factories):
    first, second = occurrence_factories
    await _create_task(first)
    await _create_run(first, "active", status="queued")
    with pytest.raises(ActiveScheduledRunConflict):
        await _create_run(second, "rejected", status="queued")
    assert await _high_water_mark(first) == 1
    assert await _sequence(first, "rejected") is None
    await ScheduledTaskRunRepository(first).update_status("active", status="success")
    await _create_run(second, "accepted", status="queued")
    assert await _sequence(first, "accepted") == 2


@pytest.mark.parametrize("status", ["queued", "success"])
async def test_primary_key_conflict_is_not_an_active_conflict_and_rolls_back(occurrence_factories, status):
    first, second = occurrence_factories
    await _create_task(first, "task-a")
    await _create_task(first, "task-b")
    await _create_run(first, "duplicate", task_id="task-a")
    with pytest.raises(IntegrityError):
        await _create_run(second, "duplicate", task_id="task-b", status=status)
    assert await _high_water_mark(first, "task-b") == 0
    await _create_run(second, "unique", task_id="task-b", status=status)
    assert await _sequence(first, "unique") == 1


async def test_requeue_and_reclaim_preserve_occurrence_sequence(occurrence_factories):
    first, second = occurrence_factories
    await _create_task(first)
    await _create_run(first, "retry", status="queued")
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    repo = ScheduledTaskRunRepository(second)
    for attempt in range(2):
        claimed = await repo.claim_queued_run("retry", now=now, lease_owner="worker", lease_seconds=60, global_max_concurrent_runs=1)
        assert claimed is not None
        assert claimed["attempt_count"] == attempt + 1
        assert await repo.requeue_claimed_run("retry", lease_owner="worker") is True
    assert await _sequence(first, "retry") == 1
    assert await _high_water_mark(first) == 1


async def test_internal_sequence_fields_are_absent_from_repository_responses(occurrence_factories):
    first, _second = occurrence_factories
    created_task = await _create_task(first)
    task_repo = ScheduledTaskRepository(first)
    run_repo = ScheduledTaskRunRepository(first)
    created_run = await _create_run(first, "queued", status="queued")
    task_responses = [created_task, await task_repo.get("task", user_id="user-1"), *(await task_repo.list_by_user("user-1"))]
    run_responses = [created_run, await run_repo.get_active_run("task"), *(await run_repo.list_by_task("task")), *(await run_repo.list_queued_runs(limit=10))]
    for response in task_responses + run_responses:
        assert {"last_occurrence_seq", "occurrence_seq", "launch_accounted"}.isdisjoint(response)
    assert await _sequence(first, "queued") == 1


async def _insert_unsequenced_run(factory, run_id, *, created_at, status="success"):
    """Insert without the repository: legacy history or a pre-upgrade writer."""
    async with factory() as session:
        session.add(
            ScheduledTaskRunRow(
                id=run_id,
                task_id="task",
                thread_id=f"thread-{run_id}",
                scheduled_for=created_at,
                created_at=created_at,
                trigger="manual",
                status=status,
            )
        )
        await session.commit()


async def _latest_run_id(factory):
    async with factory() as session:
        latest = await ScheduledTaskRepository._fetch_latest_run(session, "task")
        assert latest is not None
        return latest.id


async def test_recovery_order_keeps_timestamp_fallback_for_legacy_only_history(occurrence_factories):
    first, _second = occurrence_factories
    await _create_task(first)
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    # Unsequenced history is deliberately not assigned guessed sequence values.
    for index in range(2):
        await _insert_unsequenced_run(first, f"legacy-{index}", created_at=now + timedelta(days=index))
    assert await _latest_run_id(first) == "legacy-1"
    assert await _sequence(first, "legacy-0") is None
    assert await _sequence(first, "legacy-1") is None
    assert await _high_water_mark(first) == 0


@pytest.mark.parametrize("unsequenced_status", ["skipped", "running"])
@pytest.mark.parametrize("unsequenced_offset", [timedelta(days=-365), timedelta(seconds=30)], ids=["legacy-history-is-older", "pre-upgrade-writer-is-newer"])
async def test_recovery_lookup_prefers_the_highest_sequence_whenever_one_exists(occurrence_factories, unsequenced_offset, unsequenced_status):
    """Sequence decides whenever a sequenced row exists.

    Reversed caller clocks between sequenced rows do not matter, and an
    unsequenced row (legacy history or a pre-upgrade Gateway writer) is not
    consulted even when its caller timestamp is later: the lookup returns the
    same row ``can_project`` accepts, so recovery cannot act on a row that the
    other parent writes would reject.
    """
    first, second = occurrence_factories
    await _create_task(first)
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    # The later sequence carries the earlier caller clock: sequence still wins.
    with patch("deerflow.persistence.scheduled_task_runs.sql.datetime") as clock:
        clock.now.return_value = now + timedelta(seconds=30)
        await _create_run(first, "older-sequenced")
        clock.now.return_value = now
        await _create_run(second, "newer-sequenced")
    await _insert_unsequenced_run(first, "unsequenced", created_at=now + unsequenced_offset, status=unsequenced_status)
    assert [await _sequence(first, run_id) for run_id in ("older-sequenced", "newer-sequenced", "unsequenced")] == [1, 2, None]
    assert await _latest_run_id(first) == "newer-sequenced"


@pytest.mark.parametrize("recovery_method", ["cancel_stuck_once_tasks", "reconcile_stuck_once_tasks"])
@pytest.mark.parametrize(
    ("sequenced_status", "unsequenced_status", "expected_status", "expected_count"),
    [("running", "skipped", "running", 0), ("success", "running", "completed", 1)],
    ids=["unsequenced-skipped-while-sequenced-active", "unsequenced-running-while-sequenced-success"],
)
async def test_once_recovery_projects_only_the_sequenced_occurrence(occurrence_factories, recovery_method, sequenced_status, unsequenced_status, expected_status, expected_count):
    """A pre-upgrade row with a later caller timestamp cannot drive the parent.

    Both symptoms from review: an unsequenced ``skipped`` row must not cancel a
    parent whose sequenced occurrence is still live, and an unsequenced
    ``running`` row must not stall finalisation of a parent whose sequenced
    occurrence already succeeded.
    """
    first, _second = occurrence_factories
    await _create_task(first, schedule_type="once")
    task_repo = ScheduledTaskRepository(first)
    await task_repo.update("task", user_id="user-1", updates={"status": "running"})
    await _create_run(first, "sequenced", status=sequenced_status)
    # A pre-upgrade node on a skewed clock: no sequence, later caller timestamp.
    await _insert_unsequenced_run(first, "unsequenced", created_at=datetime.now(UTC) + timedelta(minutes=5), status=unsequenced_status)
    assert await _sequence(first, "sequenced") == 1
    assert await _high_water_mark(first) == 1

    kwargs = {"error": "interrupted: recovery"}
    if recovery_method == "reconcile_stuck_once_tasks":
        kwargs["now"] = datetime.now(UTC) + timedelta(minutes=10)
    for _ in range(2):  # a second pass must not change the outcome
        count = await getattr(task_repo, recovery_method)(**kwargs)
        task = await task_repo.get_internal("task")
        assert task is not None
        assert task["status"] == expected_status
        assert task["last_error"] is None
        assert count == expected_count
        expected_count = 0 if expected_status == "completed" else expected_count
