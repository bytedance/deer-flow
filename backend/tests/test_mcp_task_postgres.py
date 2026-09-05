from __future__ import annotations

import asyncio
import os
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text, update

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.mcp_tasks import McpTaskRepository
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.persistence.thread_meta.model import ThreadMetaRow

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URI")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="requires TEST_POSTGRES_URI (real Postgres for row-lock interleaving)",
)


def _postgres_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
    return urlunsplit(parts._replace(query=query))


@pytest_asyncio.fixture()
async def postgres_repositories():
    assert POSTGRES_URL is not None
    schema = f"mcp_incarnation_{uuid.uuid4().hex}"
    await init_engine_from_config(
        DatabaseConfig(
            backend="postgres",
            postgres_url=_postgres_url(POSTGRES_URL),
            postgres_schema=schema,
        )
    )
    session_factory = get_session_factory()
    assert session_factory is not None
    try:
        yield ThreadMetaRepository(session_factory), McpTaskRepository(session_factory), session_factory
    finally:
        engine = get_engine()
        assert engine is not None
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await close_engine()


async def _create_task(repo: McpTaskRepository, task_id: str) -> None:
    await repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id="thread-1",
        run_id=None,
        tool_call_id=None,
        server_name="reports",
        driver_name="fake",
        remote_task_id=f"remote-{task_id}",
        task_name="Generate report",
        status="working",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["delete", "update_owner"])
async def test_postgres_task_create_serializes_with_thread_mutation(postgres_repositories, mutation: str) -> None:
    thread_repo, task_repo, session_factory = postgres_repositories
    created = await thread_repo.create("thread-1", user_id="user-1")

    async with session_factory() as blocker:
        locked = (await blocker.execute(select(ThreadMetaRow).where(ThreadMetaRow.thread_id == "thread-1").with_for_update())).scalar_one()
        assert locked.incarnation == created["incarnation"]

        if mutation == "delete":
            mutation_task = asyncio.create_task(thread_repo.delete("thread-1", user_id=None))
        else:
            mutation_task = asyncio.create_task(thread_repo.update_owner("thread-1", "user-2", user_id=None))
        await asyncio.sleep(0.1)
        assert not mutation_task.done()

        create_task = asyncio.create_task(_create_task(task_repo, f"task-{mutation}"))
        await asyncio.sleep(0.1)
        assert not create_task.done()
        await blocker.commit()

    await asyncio.wait_for(mutation_task, timeout=5)
    await asyncio.wait_for(create_task, timeout=5)

    async with session_factory() as session:
        task = await session.get(McpTaskRow, f"task-{mutation}")
    assert task is not None
    assert task.thread_incarnation is None


@pytest.mark.asyncio
async def test_postgres_task_create_uses_share_lock(postgres_repositories) -> None:
    thread_repo, task_repo, _session_factory = postgres_repositories
    await thread_repo.create("thread-1", user_id="user-1")
    engine = get_engine()
    assert engine is not None
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.upper().split()))

    event.listen(engine.sync_engine, "before_cursor_execute", capture_statement)
    try:
        await _create_task(task_repo, "task-share-lock")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_statement)

    assert any(statement.endswith("FOR SHARE") for statement in statements)
    assert not any(statement.endswith("FOR KEY SHARE") for statement in statements)


@pytest.mark.asyncio
async def test_postgres_share_lock_blocks_legacy_owner_update(postgres_repositories) -> None:
    thread_repo, _task_repo, session_factory = postgres_repositories
    created = await thread_repo.create("thread-1", user_id="user-1")

    async with session_factory() as task_writer:
        incarnation = await task_writer.scalar(
            select(ThreadMetaRow.incarnation)
            .where(
                ThreadMetaRow.thread_id == "thread-1",
                ThreadMetaRow.user_id == "user-1",
            )
            .with_for_update(read=True)
        )
        assert incarnation == created["incarnation"]

        async def legacy_update_owner() -> None:
            async with session_factory() as legacy_writer:
                await legacy_writer.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == "thread-1").values(user_id="user-2"))
                await legacy_writer.commit()

        owner_update = asyncio.create_task(legacy_update_owner())
        await asyncio.sleep(0.1)
        assert not owner_update.done()
        await task_writer.commit()

    await asyncio.wait_for(owner_update, timeout=5)
    async with session_factory() as session:
        row = await session.get(ThreadMetaRow, "thread-1")
    assert row is not None
    assert row.user_id == "user-2"
