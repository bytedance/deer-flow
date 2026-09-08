"""Database ordering is per task and survives retries independently of caller clocks."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
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


async def _create_task(factory, task_id="task"):
    return await ScheduledTaskRepository(factory).create(
        task_id=task_id,
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id=None,
        title="Occurrence ordering",
        prompt="p",
        schedule_type="cron",
        schedule_spec={"cron": "* * * * *"},
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


@pytest.mark.parametrize("include_sequenced", [False, True], ids=["legacy-only", "mixed-history"])
async def test_recovery_order_preserves_legacy_fallback_but_prioritizes_sequence(occurrence_factories, include_sequenced):
    first, _second = occurrence_factories
    await _create_task(first)
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    # Unsequenced history is deliberately not assigned guessed sequence values.
    async with first() as session:
        for index in range(2):
            session.add(
                ScheduledTaskRunRow(
                    id=f"legacy-{index}",
                    task_id="task",
                    thread_id=f"thread-legacy-{index}",
                    scheduled_for=now + timedelta(days=index),
                    created_at=now + timedelta(days=365 + index),
                    trigger="manual",
                    status="success",
                )
            )
        await session.commit()
    if include_sequenced:
        await _create_run(first, "sequenced")
    async with first() as session:
        latest = await ScheduledTaskRepository._fetch_latest_run(session, "task")
        assert latest is not None
        assert latest.id == ("sequenced" if include_sequenced else "legacy-1")
    assert await _sequence(first, "legacy-0") is None
    assert await _sequence(first, "legacy-1") is None
