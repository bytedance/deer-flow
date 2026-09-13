from __future__ import annotations

import asyncio
import os
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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

        # PostgreSQL grants the mutation's earlier queued row-lock request
        # before this later FOR SHARE request. The task therefore observes the
        # committed delete/owner change rather than the pre-mutation row.
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
async def test_postgres_repository_holds_share_lock_until_task_commit(postgres_repositories) -> None:
    thread_repo, _task_repo, session_factory = postgres_repositories
    created = await thread_repo.create("thread-1", user_id="user-1")
    engine = get_engine()
    assert engine is not None
    task_commit_entered = asyncio.Event()
    allow_task_commit = asyncio.Event()
    owner_update_started = asyncio.Event()
    task_backend_pid: int | None = None
    owner_backend_pid: int | None = None

    class PausingTaskCommitSession(AsyncSession):
        async def commit(self) -> None:
            nonlocal task_backend_pid
            contains_target_task = any(isinstance(instance, McpTaskRow) and instance.id == "task-lock-lifetime" for instance in self.new)
            if contains_target_task:
                task_backend_pid = await self.scalar(text("SELECT pg_backend_pid()"))
                task_commit_entered.set()
                await allow_task_commit.wait()
            await super().commit()

    task_session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=PausingTaskCommitSession,
    )
    task_repo = McpTaskRepository(task_session_factory)

    def observe_owner_update(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.upper().split())
        if normalized.startswith("UPDATE THREADS_META SET USER_ID"):
            owner_update_started.set()

    async def legacy_update_owner() -> None:
        nonlocal owner_backend_pid
        async with session_factory() as legacy_writer:
            owner_backend_pid = await legacy_writer.scalar(text("SELECT pg_backend_pid()"))
            await legacy_writer.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == "thread-1").values(user_id="user-2"))
            await legacy_writer.commit()

    event.listen(engine.sync_engine, "before_cursor_execute", observe_owner_update)
    task_create = asyncio.create_task(_create_task(task_repo, "task-lock-lifetime"))
    owner_update = None
    try:
        await asyncio.wait_for(task_commit_entered.wait(), timeout=5)
        owner_update = asyncio.create_task(legacy_update_owner())
        await asyncio.wait_for(owner_update_started.wait(), timeout=5)
        assert task_backend_pid is not None
        assert owner_backend_pid is not None
        async with session_factory() as observer:
            async with asyncio.timeout(5):
                while True:
                    if owner_update.done():
                        await owner_update
                        pytest.fail("owner update completed before the task transaction committed")
                    blockers = await observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"),
                        {"pid": owner_backend_pid},
                    )
                    if task_backend_pid in blockers:
                        break
                    await asyncio.sleep(0.01)
        allow_task_commit.set()
        await asyncio.wait_for(task_create, timeout=5)
        await asyncio.wait_for(owner_update, timeout=5)
    finally:
        allow_task_commit.set()
        event.remove(engine.sync_engine, "before_cursor_execute", observe_owner_update)
        if not task_create.done():
            task_create.cancel()
            await asyncio.gather(task_create, return_exceptions=True)
        if owner_update is not None and not owner_update.done():
            owner_update.cancel()
            await asyncio.gather(owner_update, return_exceptions=True)

    async with session_factory() as session:
        thread = await session.get(ThreadMetaRow, "thread-1")
        task = await session.get(McpTaskRow, "task-lock-lifetime")
    assert thread is not None
    assert thread.user_id == "user-2"
    assert task is not None
    assert task.thread_incarnation == created["incarnation"]
