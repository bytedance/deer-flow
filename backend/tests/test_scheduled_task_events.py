"""Lifecycle events for the originating chat (agent stop, auto-pause, finish).

The scheduler's finalization observer writes ``scheduled_task_events`` rows in
the transaction that changes the task or occurrence state, deduplicated on
``(task_id, anchor, event)``, so recovery never writes a second row. These
tests drive the real repositories and the real observer on SQLite (and on
Postgres where marked, with ``TEST_POSTGRES_URI``).
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import httpx
import pytest
from _router_auth_helpers import make_authed_test_app
from sqlalchemy import event as sa_event
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm.attributes import set_committed_value

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import scheduled_tasks, threads
from app.scheduler.service import ScheduledTaskService
from deerflow.config.paths import Paths
from deerflow.persistence.base import Base
from deerflow.persistence.channel_connections.model import ChannelConnectionRow
from deerflow.persistence.notification_deliveries import NotificationDeliveryRepository, NotificationDeliveryRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_events import ScheduledTaskEventRepository, ScheduledTaskEventRow
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserPreferenceRow, UserRow
from deerflow.runtime import RunStatus
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode

NOW = datetime(2026, 10, 6, 8, tzinfo=UTC)
_OWNER = User(id=UUID("6c1f3d0e-8a8f-4a35-9a51-0d2f5d1b7c11"), email="events@example.com", password_hash="unused", system_role="user")
_OTHER = User(id=UUID("0b9d2c47-55e3-4d47-8f0c-a3b0f1f4d222"), email="other@example.com", password_hash="unused", system_role="user")
OWNER = str(_OWNER.id)
_TABLES = [ScheduledTaskRow, ScheduledTaskRunRow, RunRow, ThreadMetaRow, ScheduledTaskEventRow, NotificationDeliveryRow, ChannelConnectionRow, UserRow, UserPreferenceRow]
_API_FIELDS = {"id", "task_id", "event", "reason_code", "task_title", "stop_condition", "run_thread_id", "run_number", "run_status", "max_runs", "end_at", "schedule_type", "after_run_id", "created_at"}


@pytest.fixture(params=["sqlite", "postgres"])
def database_backend(request):
    return request.param


@asynccontextmanager
async def database(tmp_path, *, backend="sqlite"):
    schema = None
    if backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres ON CONFLICT path)")
        parts = urlsplit(uri)
        scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
        query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
        schema = f"task_events_{uuid.uuid4().hex}"
        engine = create_async_engine(urlunsplit(parts._replace(scheme=scheme, query=query)), connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'task-events.db'}")
    try:
        async with engine.begin() as conn:
            if schema:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[model.__table__ for model in _TABLES]))
        sf = async_sessionmaker(engine, expire_on_commit=False)
        tasks, runs = ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf)
        yield sf, tasks, runs
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


def service_for(tasks, runs, **kwargs):
    """The real scheduler service; its constructor installs the finalization observer."""
    return ScheduledTaskService(task_repo=tasks, task_run_repo=runs, launch_run=None, poll_interval_seconds=60, lease_seconds=30, max_concurrent_runs=3, **kwargs)


async def make_task(tasks, task_id="task", *, origin_thread_id="origin", title="Check the release checklist", **extra):
    return await tasks.create(
        task_id=task_id,
        user_id=OWNER,
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title=title,
        prompt="Check release-checklist.md.",
        schedule_type="interval",
        schedule_spec={"every_seconds": 3600},
        timezone="UTC",
        next_run_at=NOW,
        origin_thread_id=origin_thread_id,
        **extra,
    )


async def chat(sf, thread_id="origin", *, runs=()):
    """The originating chat (a threads_meta row) and its own runs ``(run_id, created_at, kind)``."""
    async with sf() as session:
        session.add(ThreadMetaRow(thread_id=thread_id, user_id=OWNER))
        for run_id, created_at, kind in runs:
            session.add(RunRow(run_id=run_id, thread_id=thread_id, user_id=OWNER, status="success", operation_kind=kind, created_at=created_at))
        await session.commit()


async def occurrence(sf, runs, task_id="task", suffix="1", *, trigger="scheduled", durable_status="success", stop=False):
    occurrence_id, run_id = f"{task_id}-occ-{suffix}", f"{task_id}-run-{suffix}"
    await runs.create(run_record_id=occurrence_id, task_id=task_id, thread_id=f"{task_id}-thread-{suffix}", scheduled_for=NOW, trigger=trigger, status="running")
    await runs.update_status(occurrence_id, status="running", run_id=run_id, started_at=NOW)
    async with sf() as session:
        session.add(RunRow(run_id=run_id, thread_id=f"{task_id}-thread-{suffix}", user_id=OWNER, status=durable_status, metadata_json={"scheduled_task_id": task_id, "scheduled_task_run_id": occurrence_id}, created_at=NOW))
        if stop:
            (await session.get(ScheduledTaskRunRow, occurrence_id)).stop_requested_run_id = run_id
        await session.commit()
    return occurrence_id, run_id


async def complete(tasks, occurrence_id, run_id, *, task_id="task", status="success", error=None):
    return await tasks.complete_run(task_id, user_id=OWNER, task_run_id=occurrence_id, run_id=run_id, status=status, error=error, finished_at=NOW)


async def event_rows(sf):
    async with sf() as session:
        return list((await session.execute(select(ScheduledTaskEventRow).order_by(ScheduledTaskEventRow.created_at, ScheduledTaskEventRow.id))).scalars())


async def bind_wecom(sf, *, owner=OWNER, target="wecom-user"):
    """A connected WeCom identity of the owner (the only provider with proactive push)."""
    async with sf() as session:
        session.add(ChannelConnectionRow(id=f"binding-{target}", owner_user_id=owner, provider="wecom", status="connected", external_account_id=target))
        await session.commit()


async def outbox_rows(sf):
    async with sf() as session:
        return list((await session.execute(select(NotificationDeliveryRow).order_by(NotificationDeliveryRow.created_at))).scalars())


@asynccontextmanager
async def http_client(sf, *, user=_OWNER, owner_check_passes=True, with_threads=False, tmp_path=None):
    app = make_authed_test_app(user_factory=lambda: user, owner_check_passes=owner_check_passes, bind_current_user=True)

    @app.middleware("http")
    async def mark_session_source(request, call_next):
        request.state.auth_source = AUTH_SOURCE_SESSION
        return await call_next(request)

    app.state.scheduled_task_event_repo = ScheduledTaskEventRepository(sf)
    app.include_router(scheduled_tasks.router)
    if with_threads:

        class _RunManager:
            @asynccontextmanager
            async def reserve_thread_operation(self, _thread_id, **_kwargs):
                yield

        app.state.run_manager = _RunManager()
        app.include_router(threads.router)
    with patch("app.gateway.routers.threads.get_paths", return_value=Paths(tmp_path or ".")):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://events.test") as client:
            yield client


@pytest.mark.asyncio
async def test_event_row_commits_with_state_change(tmp_path):
    async with database(tmp_path) as (sf, tasks, runs):
        await make_task(tasks, max_runs=1)
        await chat(sf)
        service = service_for(tasks, runs)

        async def fails_after_insert(session, parent, row, *, events):
            await service._on_finalization(session, parent, row, events=events)
            assert await session.scalar(select(func.count()).select_from(ScheduledTaskEventRow)) == 1
            raise RuntimeError("outbox unavailable")

        tasks.set_finalization_observer(fails_after_insert)
        occurrence_id, run_id = await occurrence(sf, runs)
        with pytest.raises(RuntimeError, match="outbox unavailable"):
            await complete(tasks, occurrence_id, run_id)
        # Both the event and the state change rolled back.
        assert await event_rows(sf) == []
        assert (await runs.list_by_task("task"))[0]["status"] == "running"
        assert (await tasks.get("task", user_id=OWNER))["status"] == "enabled"
        # The next completion (or recovery) writes both, once.
        tasks.set_finalization_observer(service._on_finalization)
        assert await complete(tasks, occurrence_id, run_id) is True
        assert [row.event for row in await event_rows(sf)] == ["task_finished"]


def _record(occurrence_id, run_id, *, task_id="task"):
    return RunRecord(
        run_id=run_id,
        thread_id=f"{task_id}-thread-1",
        assistant_id="lead_agent",
        status=RunStatus.success,
        on_disconnect=DisconnectMode.continue_,
        metadata={"scheduled_task_id": task_id, "scheduled_task_run_id": occurrence_id, "scheduled_trigger": "scheduled"},
        user_id=OWNER,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery_first", [True, False])
async def test_recovery_races_late_completion_writes_one_event(tmp_path, recovery_first, database_backend):
    """The durable run is terminal while the occurrence is still ``running``.

    Runs on Postgres too (``TEST_POSTGRES_URI``): the IM notice, its binding and
    locale lookups and both ON CONFLICT inserts share the recovery transaction.
    """
    async with database(tmp_path, backend=database_backend) as (sf, tasks, runs):
        await make_task(tasks, max_runs=1)
        await chat(sf)
        await bind_wecom(sf)
        service = service_for(tasks, runs, connection_repo=object(), notification_repo=NotificationDeliveryRepository(sf))
        occurrence_id, run_id = await occurrence(sf, runs)
        if recovery_first:
            assert await runs.reconcile_active_runs(error="lease lost", now=NOW) == 1
            await service.handle_run_completion(_record(occurrence_id, run_id))
            assert await tasks.complete_run("task", user_id=OWNER, task_run_id=occurrence_id, run_id=run_id, status="success", error=None, finished_at=NOW) is False
        else:
            await service.handle_run_completion(_record(occurrence_id, run_id))
            assert await runs.reconcile_active_runs(error="lease lost", now=NOW) == 0
        rows = await event_rows(sf)
        assert [(row.event, row.anchor) for row in rows] == [("task_finished", occurrence_id)]
        assert (await tasks.get("task", user_id=OWNER))["status"] == "completed"
        # Exactly one IM notice too, committed with the same finalization.
        assert [(row.event, row.task_run_id, row.provider) for row in await outbox_rows(sf)] == [("task_finished", occurrence_id, "wecom")]


@pytest.mark.asyncio
async def test_poisoned_row_does_not_block_recovery_of_other_rows(tmp_path):
    """Three stale occurrences in one recovery pass; one task carries bad stored values."""
    async with database(tmp_path) as (sf, tasks, runs):
        await chat(sf)
        await bind_wecom(sf)
        service_for(tasks, runs, connection_repo=object(), notification_repo=NotificationDeliveryRepository(sf))
        await make_task(tasks, "task-a", max_runs=1)
        await make_task(tasks, "task-b", stop_condition="all items are ticked")
        await make_task(tasks, "task-c")
        await tasks.update("task-c", user_id=OWNER, updates={"schedule_type": "once", "schedule_spec": {"run_at": NOW.isoformat()}})
        await occurrence(sf, runs, "task-a")
        await occurrence(sf, runs, "task-b", stop=True)
        await occurrence(sf, runs, "task-c")
        async with sf() as session:
            # Bad stored values: a blank title and a non-numeric max_runs
            # (SQLite keeps text in an INTEGER column).
            await session.execute(text("UPDATE scheduled_tasks SET title = '   ', max_runs = 'many' WHERE id = 'task-c'"))
            # An unreadable locale preference (not even JSON) for the owner.
            await session.execute(text("INSERT INTO user_preferences (user_id, key, value) VALUES (:owner, 'locale', 'not json {')"), {"owner": OWNER})
            await session.commit()

        def unreadable_end_at(target, *_args):
            # A stored end time the observer cannot parse (the DateTime column
            # itself cannot hold one, so it is injected at load time).
            if target.id == "task-c":
                set_committed_value(target, "end_at", "not a time")

        sa_event.listen(ScheduledTaskRow, "load", unreadable_end_at)
        sa_event.listen(ScheduledTaskRow, "refresh", unreadable_end_at)
        try:
            assert await runs.mark_stale_active_runs(error="restarted") == 3
        finally:
            sa_event.remove(ScheduledTaskRow, "load", unreadable_end_at)
            sa_event.remove(ScheduledTaskRow, "refresh", unreadable_end_at)

        for task_id in ("task-a", "task-b", "task-c"):
            assert (await runs.list_by_task(task_id))[0]["status"] == "success"
        rows = {row.task_id: row for row in await event_rows(sf)}
        assert {task_id: (row.event, row.reason_code) for task_id, row in rows.items()} == {
            "task-a": ("task_finished", "max_runs"),
            "task-b": ("task_stopped", "agent_stop"),
            "task-c": ("task_finished", "once_done"),
        }
        poisoned = rows["task-c"].payload_json
        assert (poisoned["task_title"], poisoned["end_at"], poisoned["max_runs"]) == (None, None, None)
        assert rows["task-c"].anchor == "task-c-occ-1"
        # Each occurrence also staged its one IM notice, the unreadable locale
        # falling back to the configured default (locale None).
        notices = {row.task_id: row for row in await outbox_rows(sf)}
        assert {task_id: row.event for task_id, row in notices.items()} == {"task-a": "task_finished", "task-b": "task_stopped", "task-c": "run_completed"}
        assert {row.payload_json["locale"] for row in notices.values()} == {None}
        assert notices["task-c"].payload_json["task_title"] is None


@pytest.mark.asyncio
async def test_detached_outbox_keeps_chat_events(tmp_path):
    async with database(tmp_path) as (sf, tasks, runs):
        await chat(sf)
        async with sf() as session:
            session.add(ChannelConnectionRow(id="binding", owner_user_id=OWNER, provider="wecom", status="connected", external_account_id="wecom-user"))
            await session.commit()
        service = service_for(tasks, runs, connection_repo=object(), notification_repo=NotificationDeliveryRepository(sf))

        async def auto_pause(task_id):
            await make_task(tasks, task_id, goal_objective="every item is checked")
            for suffix in ("1", "2", "3"):
                occurrence_id, run_id = await occurrence(sf, runs, task_id, suffix)
                await complete(tasks, occurrence_id, run_id, task_id=task_id, status="unmet", error="goal_not_met_yet")
            assert (await tasks.get(task_id, user_id=OWNER))["status"] == "paused"

        await auto_pause("wired")
        wired_outbox = len(await outbox_rows(sf))
        assert wired_outbox > 0
        service.detach_notification_outbox()
        await auto_pause("detached")
        rows = await event_rows(sf)
        assert [(row.task_id, row.event, row.reason_code) for row in rows] == [("wired", "task_paused", "consecutive_unmet"), ("detached", "task_paused", "consecutive_unmet")]
        assert len(await outbox_rows(sf)) == wired_outbox


@pytest.mark.asyncio
async def test_event_lines_survive_task_deletion(tmp_path):
    async with database(tmp_path) as (sf, tasks, runs):
        await make_task(tasks, max_runs=1)
        await chat(sf)
        service_for(tasks, runs)
        occurrence_id, run_id = await occurrence(sf, runs)
        await complete(tasks, occurrence_id, run_id)
        assert await tasks.delete("task", user_id=OWNER) is True
        async with http_client(sf) as client:
            response = await client.get("/api/threads/origin/scheduled-task-events")
        assert response.status_code == 200, response.text
        (line,) = response.json()["events"]
        assert (line["task_id"], line["event"], line["reason_code"], line["task_title"]) == ("task", "task_finished", "max_runs", "Check the release checklist")


@pytest.mark.asyncio
async def test_no_event_for_deleted_origin_thread(tmp_path):
    async with database(tmp_path) as (sf, tasks, runs):
        await make_task(tasks, max_runs=1)
        service_for(tasks, runs)
        occurrence_id, run_id = await occurrence(sf, runs)
        assert await complete(tasks, occurrence_id, run_id) is True
        assert (await tasks.get("task", user_id=OWNER))["status"] == "completed"
        assert await event_rows(sf) == []


def test_origin_thread_lookup_takes_a_share_lock():
    """A racing thread delete waits for the finalization (FOR SHARE), so its
    later delete_by_thread step removes the line instead of orphaning it."""
    from sqlalchemy.dialects import postgresql, sqlite

    from app.scheduler.service import _origin_thread_share_lock

    statement = _origin_thread_share_lock("origin")
    assert "FOR SHARE" in str(statement.compile(dialect=postgresql.dialect()))
    # SQLite has no row locks; its single writer already serializes the two.
    assert "FOR" not in str(statement.compile(dialect=sqlite.dialect()))


@pytest.mark.asyncio
async def test_skipped_occurrence_payload_has_no_run_thread(tmp_path):
    async with database(tmp_path) as (sf, tasks, runs):
        await make_task(tasks, end_at=NOW + timedelta(seconds=1))
        await chat(sf)
        service_for(tasks, runs)
        await runs.create(run_record_id="waiting", task_id="task", thread_id="never-created", scheduled_for=NOW, trigger="scheduled", status="queued")
        assert await runs.claim_queued_run("waiting", lease_owner="worker", now=NOW + timedelta(seconds=2), lease_seconds=30, global_max_concurrent_runs=1) is None
        (row,) = await event_rows(sf)
        assert (row.event, row.reason_code) == ("task_finished", "end_at")
        assert row.payload_json["run_thread_id"] is None
        assert row.payload_json["run_number"] is None
        assert row.payload_json["run_status"] == "skipped"


@pytest.mark.asyncio
async def test_duplicate_insert_is_ignored(tmp_path, database_backend):
    """Both ON CONFLICT DO NOTHING paths (event row and outbox row) on this dialect."""
    async with database(tmp_path, backend=database_backend) as (sf, _tasks, _runs):
        outbox = NotificationDeliveryRepository(sf)
        async with sf() as session:
            kwargs = {"user_id": OWNER, "task_id": "task", "thread_id": "origin", "occurrence_id": "occ", "anchor": "occ", "event": "task_stopped", "reason_code": "agent_stop", "after_run_id": None}
            first = await ScheduledTaskEventRepository.record_in_session(session, payload={"task_title": "first"}, **kwargs)
            second = await ScheduledTaskEventRepository.record_in_session(session, payload={"task_title": "second"}, **kwargs)
            delivery = {"task_id": "task", "task_run_id": "occ", "event": "task_stopped", "provider": "wecom", "target": "wecom-user", "owner_user_id": OWNER}
            first_delivery = await outbox.enqueue_in_session(session, payload={"n": 1}, **delivery)
            second_delivery = await outbox.enqueue_in_session(session, payload={"n": 2}, **delivery)
            await session.commit()
        assert first["id"] == second["id"]
        assert second["task_title"] == "first"
        assert first_delivery["id"] == second_delivery["id"]
        assert [row.payload_json for row in await event_rows(sf)] == [{"task_title": "first"}]
        assert [row.payload_json for row in await outbox_rows(sf)] == [{"n": 1}]


@pytest.mark.asyncio
async def test_page_created_task_writes_no_event(tmp_path):
    async with database(tmp_path) as (sf, tasks, runs):
        await make_task(tasks, origin_thread_id=None, max_runs=1)
        await chat(sf)
        service_for(tasks, runs)
        occurrence_id, run_id = await occurrence(sf, runs)
        await complete(tasks, occurrence_id, run_id)
        assert (await tasks.get("task", user_id=OWNER))["status"] == "completed"
        assert await event_rows(sf) == []


@pytest.mark.asyncio
async def test_manual_trial_writes_no_run_event(tmp_path):
    async with database(tmp_path) as (sf, tasks, runs):
        await make_task(tasks)
        await chat(sf)
        service_for(tasks, runs)
        occurrence_id, run_id = await occurrence(sf, runs, trigger="manual")
        assert await complete(tasks, occurrence_id, run_id) is True
        assert await event_rows(sf) == []


@pytest.mark.asyncio
async def test_after_run_id_is_latest_origin_run(tmp_path):
    async with database(tmp_path) as (sf, tasks, runs):
        await make_task(tasks, max_runs=1)
        await chat(
            sf,
            runs=[
                ("chat-run-1", NOW - timedelta(minutes=2), "run"),
                ("chat-run-2", NOW - timedelta(minutes=1), "run"),
                # A thread operation reservation is not a turn of the chat.
                ("chat-op", NOW, "checkpoint_write"),
            ],
        )
        await chat(sf, "quiet-chat")
        service_for(tasks, runs)
        occurrence_id, run_id = await occurrence(sf, runs)
        await complete(tasks, occurrence_id, run_id)
        await make_task(tasks, "quiet", origin_thread_id="quiet-chat", max_runs=1)
        quiet_occurrence, quiet_run = await occurrence(sf, runs, "quiet")
        await complete(tasks, quiet_occurrence, quiet_run, task_id="quiet")
        rows = {row.task_id: row for row in await event_rows(sf)}
        assert rows["task"].after_run_id == "chat-run-2"
        # A chat without runs of its own: the line goes to the tail.
        assert rows["quiet"].after_run_id is None


@pytest.mark.asyncio
async def test_events_route_is_owner_scoped(tmp_path):
    async with database(tmp_path) as (sf, tasks, runs):
        await make_task(tasks, max_runs=1)
        await chat(sf)
        service_for(tasks, runs)
        occurrence_id, run_id = await occurrence(sf, runs)
        await complete(tasks, occurrence_id, run_id)
        async with http_client(sf) as client:
            own = await client.get("/api/threads/origin/scheduled-task-events")
        assert own.status_code == 200
        assert len(own.json()["events"]) == 1
        # Another user who may read the thread still sees only their own rows.
        async with http_client(sf, user=_OTHER) as client:
            other = await client.get("/api/threads/origin/scheduled-task-events")
        assert other.status_code == 200
        assert other.json() == {"events": []}
        # Without access to the thread, the route refuses before listing.
        async with http_client(sf, user=_OTHER, owner_check_passes=False) as client:
            denied = await client.get("/api/threads/origin/scheduled-task-events")
        assert denied.status_code == 404


@pytest.mark.asyncio
async def test_thread_delete_removes_events(tmp_path):
    async with database(tmp_path) as (sf, tasks, runs):
        await chat(sf)
        await chat(sf, "kept-chat")
        service_for(tasks, runs)
        await make_task(tasks, max_runs=1)
        await make_task(tasks, "kept", origin_thread_id="kept-chat", max_runs=1)
        for task_id in ("task", "kept"):
            occurrence_id, run_id = await occurrence(sf, runs, task_id)
            await complete(tasks, occurrence_id, run_id, task_id=task_id)
        assert len(await event_rows(sf)) == 2
        async with http_client(sf, with_threads=True, tmp_path=tmp_path) as client:
            response = await client.delete("/api/threads/origin")
        assert response.status_code == 200, response.text
        assert [row.thread_id for row in await event_rows(sf)] == ["kept-chat"]


@pytest.mark.asyncio
async def test_payload_has_title_condition_run_number(tmp_path):
    async with database(tmp_path) as (sf, tasks, runs):
        await make_task(tasks, stop_condition="all items are ticked", end_at=NOW + timedelta(days=30))
        await chat(sf, runs=[("chat-run", NOW - timedelta(minutes=5), "run")])
        service_for(tasks, runs)
        first, first_run = await occurrence(sf, runs, suffix="1")
        await complete(tasks, first, first_run)
        second, second_run = await occurrence(sf, runs, suffix="2", stop=True)
        await complete(tasks, second, second_run)
        (row,) = await event_rows(sf)
        assert (row.user_id, row.task_id, row.thread_id, row.occurrence_id, row.anchor) == (OWNER, "task", "origin", second, second)
        assert row.id.startswith("evt-")
        assert row.payload_json == {
            "task_title": "Check the release checklist",
            "stop_condition": "all items are ticked",
            "run_thread_id": "task-thread-2",
            "run_number": 2,
            "run_status": "success",
            "latest_reason_code": None,
            "max_runs": None,
            "end_at": (NOW + timedelta(days=30)).isoformat(),
            "schedule_type": "interval",
        }
        async with http_client(sf) as client:
            (line,) = (await client.get("/api/threads/origin/scheduled-task-events")).json()["events"]
        assert set(line) == _API_FIELDS
        assert (line["run_number"], line["stop_condition"], line["after_run_id"], line["run_thread_id"]) == (2, "all items are ticked", "chat-run", "task-thread-2")


def _task(**values):
    from types import SimpleNamespace

    base = {"schedule_type": "interval", "status": "completed", "end_at": None, "last_occurrence_seq": 4}
    return SimpleNamespace(**{**base, **values})


@pytest.mark.parametrize(
    ("task_values", "event", "occurrence_status", "expected"),
    [
        ({}, "task_stopped", "success", "agent_stop"),
        ({}, "task_paused", "unmet", "consecutive_unmet"),
        ({}, "task_finished", "success", "max_runs"),
        ({"end_at": NOW - timedelta(seconds=1)}, "task_finished", None, "end_at"),
        ({"end_at": (NOW + timedelta(hours=1)).replace(tzinfo=None)}, "task_finished", "success", "max_runs"),
        ({"end_at": "not a time"}, "task_finished", None, "max_runs"),
        ({"schedule_type": "once"}, "task_finished", "success", "once_done"),
        ({"schedule_type": "once", "status": "failed"}, "task_finished", "unmet", "once_failed"),
        # A once task finished by its end time before it ran is not "has run".
        ({"schedule_type": "once", "end_at": NOW - timedelta(seconds=1)}, "task_finished", None, "end_at"),
    ],
)
def test_lifecycle_reason(task_values, event, occurrence_status, expected):
    from types import SimpleNamespace

    from deerflow.persistence.scheduled_task_runs.finalization import LIFECYCLE_REASONS, lifecycle_reason

    occurrence = SimpleNamespace(status=occurrence_status) if occurrence_status is not None else None
    reason = lifecycle_reason(_task(**task_values), event, now=NOW, occurrence=occurrence)
    assert reason == expected
    assert reason in LIFECYCLE_REASONS[event]


def test_lifecycle_anchor_is_deterministic():
    from types import SimpleNamespace

    from deerflow.persistence.scheduled_task_runs.finalization import lifecycle_anchor

    assert lifecycle_anchor(_task(), SimpleNamespace(id="occ-7"), now=NOW) == "occ-7"
    naive = datetime(2026, 12, 31, 18, 0)
    after_end = datetime(2027, 1, 1, tzinfo=UTC)
    assert lifecycle_anchor(_task(end_at=naive), None, now=after_end) == "end:2026-12-31T18:00:00+00:00"
    assert lifecycle_anchor(_task(end_at=naive.replace(tzinfo=UTC)), None, now=after_end) == lifecycle_anchor(_task(end_at=naive), None, now=after_end)
    assert lifecycle_anchor(_task(), None, now=after_end) == "seq:4"
    assert lifecycle_anchor(_task(end_at="not a time"), None, now=after_end) == "seq:4"
    assert len(lifecycle_anchor(_task(end_at=naive), None, now=after_end)) <= 96


def test_idle_max_runs_finish_does_not_take_the_end_time_anchor():
    """A max_runs idle finish before the end time keeps a seq anchor, so a later
    end-time finish (after a reactivation) is not dropped as a duplicate."""
    from deerflow.persistence.scheduled_task_runs.finalization import lifecycle_anchor

    end = datetime(2026, 12, 31, 18, 0, tzinfo=UTC)
    before_end = lifecycle_anchor(_task(end_at=end), None, now=end - timedelta(days=1))
    after_end = lifecycle_anchor(_task(end_at=end), None, now=end + timedelta(minutes=1))
    assert before_end == "seq:4"
    assert after_end == f"end:{end.isoformat()}"
    assert before_end != after_end
