from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.routers.thread_runs import _record_to_response
from app.gateway.thread_events import ThreadEventHub
from deerflow.persistence.base import Base
from deerflow.persistence.scheduled_tasks import ACTIVE, CANCELLED, COMPLETED, RUNNING, ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.runtime import DisconnectMode, RunRecord, RunStatus
from deerflow.tools.builtins.schedule_task_tool import _resolve_fire_at


@pytest_asyncio.fixture()
async def scheduled_task_repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[ScheduledTaskRow.__table__])
    try:
        yield ScheduledTaskRepository(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_list_scheduled_task_is_user_scoped(scheduled_task_repo: ScheduledTaskRepository):
    run_at = datetime.now(UTC) + timedelta(minutes=5)
    created = await scheduled_task_repo.create_once(
        owner_user_id="user-a",
        thread_id="thread-1",
        prompt="Run the backup check",
        run_at=run_at,
        title="Backup",
    )

    assert created["status"] == ACTIVE
    assert created["thread_id"] == "thread-1"
    assert created["title"] == "Backup"

    own_tasks = await scheduled_task_repo.list(user_id="user-a")
    other_tasks = await scheduled_task_repo.list(user_id="user-b")

    assert [task["id"] for task in own_tasks] == [created["id"]]
    assert other_tasks == []


@pytest.mark.asyncio
async def test_claim_due_task_is_atomic(scheduled_task_repo: ScheduledTaskRepository):
    now = datetime.now(UTC)
    created = await scheduled_task_repo.create_once(
        owner_user_id="user-a",
        thread_id="thread-1",
        prompt="Run the backup check",
        run_at=now - timedelta(seconds=1),
    )

    due = await scheduled_task_repo.list_due(now=now)
    assert [task["id"] for task in due] == [created["id"]]

    claimed = await scheduled_task_repo.claim_due(created["id"], now=now, lease_seconds=60)
    claimed_again = await scheduled_task_repo.claim_due(created["id"], now=now, lease_seconds=60)

    assert claimed is not None
    assert claimed["status"] == RUNNING
    assert claimed_again is None


@pytest.mark.asyncio
async def test_expired_running_task_can_be_reclaimed(scheduled_task_repo: ScheduledTaskRepository):
    first_now = datetime.now(UTC)
    created = await scheduled_task_repo.create_once(
        owner_user_id="user-a",
        thread_id="thread-1",
        prompt="Run the backup check",
        run_at=first_now - timedelta(seconds=1),
    )

    assert await scheduled_task_repo.claim_due(created["id"], now=first_now, lease_seconds=1) is not None
    later = first_now + timedelta(seconds=2)

    due = await scheduled_task_repo.list_due(now=later)
    reclaimed = await scheduled_task_repo.claim_due(created["id"], now=later, lease_seconds=60)

    assert [task["id"] for task in due] == [created["id"]]
    assert reclaimed is not None
    assert reclaimed["status"] == RUNNING


@pytest.mark.asyncio
async def test_cancel_and_complete_status_transitions(scheduled_task_repo: ScheduledTaskRepository):
    run_at = datetime.now(UTC) + timedelta(minutes=5)
    first = await scheduled_task_repo.create_once(
        owner_user_id="user-a",
        thread_id="thread-1",
        prompt="Run the backup check",
        run_at=run_at,
    )
    second = await scheduled_task_repo.create_once(
        owner_user_id="user-a",
        thread_id="thread-1",
        prompt="Run the report",
        run_at=run_at,
    )

    assert await scheduled_task_repo.cancel(first["id"], user_id="user-a") is True
    assert await scheduled_task_repo.cancel(first["id"], user_id="user-a") is False
    cancelled = await scheduled_task_repo.get(first["id"], user_id="user-a")
    assert cancelled is not None
    assert cancelled["status"] == CANCELLED

    await scheduled_task_repo.mark_completed(second["id"], run_id="run-1")
    completed = await scheduled_task_repo.get(second["id"], user_id="user-a")
    assert completed is not None
    assert completed["status"] == COMPLETED
    assert completed["last_run_id"] == "run-1"


@pytest.mark.asyncio
async def test_thread_event_hub_fans_out_by_thread_and_user():
    hub = ThreadEventHub()

    async with (
        hub.subscribe("thread-1", "user-a") as own_queue,
        hub.subscribe("thread-1", "user-b") as other_user_queue,
        hub.subscribe("thread-2", "user-a") as other_thread_queue,
    ):
        await hub.publish(
            "thread-1",
            "scheduled_run_completed",
            {"scheduled_task_id": "task-1"},
            user_id="user-a",
        )

        event = await asyncio.wait_for(own_queue.get(), timeout=1)
        assert event is not None
        assert event.event == "scheduled_run_completed"
        assert event.data["scheduled_task_id"] == "task-1"
        assert other_user_queue.empty()
        assert other_thread_queue.empty()


def test_run_response_filters_runtime_only_kwargs():
    record = RunRecord(
        run_id="run-1",
        thread_id="thread-1",
        assistant_id="lead_agent",
        status=RunStatus.success,
        on_disconnect=DisconnectMode.continue_,
        kwargs={
            "config": {
                "configurable": {
                    "thread_id": "thread-1",
                    "__pregel_runtime": object(),
                },
                "callbacks": [object()],
            }
        },
    )

    response = _record_to_response(record)

    assert response.kwargs == {"config": {"configurable": {"thread_id": "thread-1"}}}


def test_schedule_task_resolves_relative_delay_from_server_time():
    now = datetime(2026, 6, 14, 10, 0, tzinfo=UTC)

    fire_at = _resolve_fire_at(
        run_at=None,
        timezone="Asia/Shanghai",
        delay_seconds=180,
        now=now,
    )

    assert fire_at == now + timedelta(seconds=180)


def test_schedule_task_requires_exactly_one_time_source():
    now = datetime(2026, 6, 14, 10, 0, tzinfo=UTC)

    assert (
        _resolve_fire_at(
            run_at="2026-06-14T18:00:00+08:00",
            timezone="Asia/Shanghai",
            delay_seconds=60,
            now=now,
        )
        == "Provide exactly one of run_at or delay_seconds."
    )
