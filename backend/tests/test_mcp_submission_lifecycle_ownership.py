"""A rejected thread lifecycle must not hide an existing remote handle owner."""

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence.base import Base
from deerflow.persistence.json_compat import dumps_json_safe
from deerflow.persistence.mcp_tasks import DuplicateMcpRemoteTaskError, McpTaskRepository, McpTaskThreadMismatchError
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.thread_meta.model import ThreadMetaRow

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def repository(request, tmp_path):
    schema = None
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = "mcp_lifecycle_owner_" + uuid.uuid4().hex
        url = asyncpg_test_url(uri)
        options = {"connect_args": build_asyncpg_connect_args(schema)}
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'lifecycle-ownership.db'}"
        options = {"connect_args": {"timeout": 10}}
    engine = create_async_engine(url, json_serializer=dumps_json_safe, **options)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            if schema:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all, tables=[ThreadMetaRow.__table__, McpTaskRow.__table__])
        async with factory() as session:
            session.add_all(
                [
                    ThreadMetaRow(thread_id="owner-thread", user_id="alice", incarnation="original"),
                    ThreadMetaRow(thread_id="submit-thread", user_id="alice", incarnation="original"),
                ]
            )
            await session.commit()
        yield McpTaskRepository(factory)
    finally:
        try:
            if schema:
                async with engine.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await engine.dispose()


async def _create(repo, *, task_id, thread_id, status="working", **scope):
    return await repo.create(
        task_id=task_id,
        thread_id=thread_id,
        expected_thread_incarnation="original",
        user_id=scope.get("user_id", "alice"),
        server_name=scope.get("server_name", "reports"),
        remote_task_id=scope.get("remote_task_id", "remote-report"),
        run_id="run",
        tool_call_id="call",
        driver_name="ordinary",
        task_name="Report",
        status=status,
        result={"answer": 42} if status == "completed" else None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
    )


@pytest.mark.parametrize("lifecycle", ["deleted", "recreated", "inaccessible"])
@pytest.mark.parametrize(
    ("status", "scope"),
    [
        ("working", {}),
        ("completed", {}),
        ("working", {"user_id": "bob"}),
        ("working", {"server_name": "other-server"}),
        ("working", {"remote_task_id": "other-remote"}),
    ],
    ids=["owned-working", "owned-terminal", "other-user", "other-server", "other-remote"],
)
async def test_lifecycle_rejection_preserves_exact_remote_ownership(repository, lifecycle, status, scope):
    repo = repository
    first = await _create(repo, task_id="owner", thread_id="owner-thread", status=status)
    async with repo._sf() as session:
        thread = await session.get(ThreadMetaRow, "submit-thread")
        if lifecycle == "deleted":
            await session.delete(thread)
        elif lifecycle == "recreated":
            thread.incarnation = "replacement"
        else:
            thread.user_id = "inaccessible-owner"
        # Existing ownership survives the owner's old thread incarnation too.
        owner_thread = await session.get(ThreadMetaRow, "owner-thread")
        owner_thread.incarnation = "owner-replacement"
        await session.commit()

    expected = McpTaskThreadMismatchError if scope else DuplicateMcpRemoteTaskError
    with pytest.raises(expected):
        await _create(repo, task_id="late-submission", thread_id="submit-thread", **scope)

    async with repo._sf() as session:
        rows = list((await session.execute(select(McpTaskRow))).scalars())
        assert len(rows) == 1
        assert repo._row_to_dict(rows[0]) == first
        assert rows[0].thread_incarnation == "original"
