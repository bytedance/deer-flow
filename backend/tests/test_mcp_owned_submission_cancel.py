"""Submission receipts cancel their own durable task across thread lifecycles."""

import asyncio
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.mcp.tasks.models import TaskReference
from deerflow.persistence.base import Base
from deerflow.persistence.json_compat import dumps_json_safe
from deerflow.persistence.mcp_tasks import McpTaskRepository
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.thread_meta.model import ThreadMetaRow

pytestmark = pytest.mark.asyncio
NOW = datetime(2030, 1, 1, tzinfo=UTC)


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def owned_submission(request, tmp_path):
    schema = None
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = "mcp_owned_cancel_" + uuid.uuid4().hex
        url = asyncpg_test_url(uri)
        options = {"connect_args": build_asyncpg_connect_args(schema)}
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'owned-cancel.db'}"
        options = {"connect_args": {"timeout": 10}}
    engine = create_async_engine(url, json_serializer=dumps_json_safe, **options)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            if schema:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all, tables=[ThreadMetaRow.__table__, McpTaskRow.__table__])
        async with factory() as session:
            session.add(ThreadMetaRow(thread_id="thread", user_id="alice", incarnation="original"))
            await session.commit()
        repo = McpTaskRepository(factory)
        task = TaskReference(
            local_task_id="local-task",
            user_id="alice",
            thread_id="thread",
            thread_incarnation="original",
            server_name="reports",
            remote_task_id="remote-task",
        )
        await repo.create(
            task_id=task.local_task_id,
            user_id=task.user_id,
            thread_id=task.thread_id,
            expected_thread_incarnation=task.thread_incarnation,
            run_id="run",
            tool_call_id="call",
            server_name=task.server_name,
            driver_name="ordinary",
            remote_task_id=task.remote_task_id,
            task_name="Report",
            status="submitted",
            result=None,
            result_preview=None,
            result_truncated=False,
            result_artifact=None,
            error=None,
            input_required=None,
            next_poll_at=NOW,
        )
        yield repo, task
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def _stored(repo, task):
    async with repo._sf() as session:
        row = await session.get(McpTaskRow, task.local_task_id)
        return repo._row_to_dict(row, include_internal=True) if row is not None else None


async def _finish_poll(repo, task, claim, *, status="completed"):
    return await repo.apply_snapshot(
        task.local_task_id,
        lease_owner=claim["lease_owner"],
        lease_token=claim["lease_token"],
        status=status,
        result={"answer": 42},
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
        polled_at=NOW,
    )


async def test_owned_cancel_fences_poll_and_preserves_repeated_cancel_lease(owned_submission):
    repo, task = owned_submission
    poll = (await repo.claim_due_tasks(now=NOW, lease_owner="poller", lease_seconds=60, limit=1))[0]
    requested = await repo.request_cancel_owned_submission(task, driver_name="ordinary", requested_at=NOW)
    assert requested["cancel_requested_at"] == NOW.isoformat()
    assert requested["next_cancel_at"] == NOW.isoformat()
    assert requested["status"] == "submitted"
    assert requested["lease_owner"] is None
    assert requested["lease_token"] is None
    assert not await _finish_poll(repo, task, poll)

    claimed = await repo.claim_cancel_requests(now=NOW, lease_owner="canceller", lease_seconds=60, limit=1)
    assert [row["id"] for row in claimed] == [task.local_task_id]
    before = await _stored(repo, task)
    repeated = await repo.request_cancel_owned_submission(task, driver_name="ordinary", requested_at=NOW + timedelta(seconds=1))
    assert repeated["lease_token"] == claimed[0]["lease_token"]
    assert await _stored(repo, task) == before


@pytest.mark.parametrize("recreate", [False, True])
async def test_owned_receipt_survives_thread_deletion_without_widening_public_cancel(owned_submission, recreate):
    repo, task = owned_submission
    async with repo._sf() as session:
        await session.delete(await session.get(ThreadMetaRow, task.thread_id))
        await session.commit()
        if recreate:
            session.add(ThreadMetaRow(thread_id=task.thread_id, user_id="alice", incarnation="replacement"))
            await session.commit()
    assert await repo.request_cancel(task.local_task_id, user_id=task.user_id, thread_id=task.thread_id, thread_incarnation=task.thread_incarnation, requested_at=NOW) is None
    requested = await repo.request_cancel_owned_submission(task, driver_name="ordinary", requested_at=NOW)
    assert requested["cancel_requested_at"] == NOW.isoformat()
    claims = await repo.claim_cancel_requests(now=NOW, lease_owner="recovered-worker", lease_seconds=60, limit=1)
    assert [row["remote_task_id"] for row in claims] == [task.remote_task_id]


@pytest.mark.parametrize("field", ["local_task_id", "user_id", "thread_id", "thread_incarnation", "server_name", "remote_task_id", "driver_name"])
async def test_owned_cancel_requires_the_entire_creation_receipt(owned_submission, field):
    repo, task = owned_submission
    before = await _stored(repo, task)
    receipt = task if field == "driver_name" else replace(task, **{field: "other"})
    driver_name = "other" if field == "driver_name" else "ordinary"
    assert await repo.request_cancel_owned_submission(receipt, driver_name=driver_name, requested_at=NOW) is None
    assert await _stored(repo, task) == before


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
async def test_owned_cancel_leaves_terminal_result_unchanged(owned_submission, status):
    repo, task = owned_submission
    claim = (await repo.claim_due_tasks(now=NOW, lease_owner="poller", lease_seconds=60, limit=1))[0]
    assert await _finish_poll(repo, task, claim, status=status)
    before = await _stored(repo, task)
    result = await repo.request_cancel_owned_submission(task, driver_name="ordinary", requested_at=NOW)
    assert result["status"] == status
    assert await _stored(repo, task) == before


async def test_owned_cancel_does_not_recreate_a_missing_row(owned_submission):
    repo, task = owned_submission
    async with repo._sf() as session:
        await session.delete(await session.get(McpTaskRow, task.local_task_id))
        await session.commit()
    assert await repo.request_cancel_owned_submission(task, driver_name="ordinary", requested_at=NOW) is None
    assert await _stored(repo, task) is None


async def test_owned_cancel_matches_legacy_null_incarnation_exactly(owned_submission):
    repo, task = owned_submission
    legacy = replace(task, thread_incarnation=None)
    assert await repo.request_cancel_owned_submission(legacy, driver_name="ordinary", requested_at=NOW) is None
    async with repo._sf() as session:
        row = await session.get(McpTaskRow, task.local_task_id)
        row.thread_incarnation = None
        await session.commit()
    assert await repo.request_cancel_owned_submission(task, driver_name="ordinary", requested_at=NOW) is None
    result = await repo.request_cancel_owned_submission(legacy, driver_name="ordinary", requested_at=NOW)
    assert result["cancel_requested_at"] == NOW.isoformat()


@pytest.mark.parametrize("peer_action", ["complete", "claim_cancel"])
async def test_sqlite_owned_cancel_rechecks_peer_state_at_write(owned_submission, monkeypatch, peer_action):
    repo, task = owned_submission
    async with repo._sf() as session:
        if session.get_bind().dialect.name != "sqlite":
            pytest.skip("SQLite ignores SELECT FOR UPDATE; PostgreSQL serializes row readers")
    poll = (await repo.claim_due_tasks(now=NOW, lease_owner="poller", lease_seconds=60, limit=1))[0]
    entered, release = asyncio.Event(), asyncio.Event()
    original_execute = AsyncSession.execute
    intercepted = False

    async def execute(session, statement, *args, **kwargs):
        nonlocal intercepted
        if asyncio.current_task() is not pending or intercepted:
            return await original_execute(session, statement, *args, **kwargs)
        intercepted = True
        if statement.is_select:
            result = await original_execute(session, statement, *args, **kwargs)
        entered.set()
        await release.wait()
        return result if statement.is_select else await original_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", execute)
    pending = asyncio.create_task(repo.request_cancel_owned_submission(task, driver_name="ordinary", requested_at=NOW + timedelta(seconds=1)))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        if peer_action == "complete":
            assert await _finish_poll(repo, task, poll)
        else:
            await repo.request_cancel(task.local_task_id, user_id=task.user_id, thread_id=task.thread_id, thread_incarnation=task.thread_incarnation, requested_at=NOW)
            await repo.claim_cancel_requests(now=NOW, lease_owner="peer", lease_seconds=60, limit=1)
        before = await _stored(repo, task)
        release.set()
        await asyncio.wait_for(pending, timeout=5)
        assert intercepted
        assert await _stored(repo, task) == before
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
