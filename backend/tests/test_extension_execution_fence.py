"""Execution ownership must be checked in the child admission transaction."""

import pytest
import pytest_asyncio
from deerflow_extension_api import ExecutionFence
from sqlalchemy import insert
from test_run_repository import _cleanup, _make_repo

from deerflow.persistence.extension_leases.model import ExtensionExecutionLeaseRow


@pytest_asyncio.fixture
async def repo(tmp_path):
    value = await _make_repo(tmp_path)
    try:
        yield value
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_admission_rejects_stale_extension_epoch(repo):
    async with repo._sf() as session:
        await session.execute(insert(ExtensionExecutionLeaseRow).values(namespace="test", resource_id="workflow", user_id="alice", holder_id="new", epoch=2, expires_at=9999999999))
        await session.commit()
    from deerflow.runtime.runs.manager import ConflictError

    with pytest.raises(ConflictError, match="execution fence"):
        await repo.create_thread_operation_atomic("child", thread_id="thread", owner_worker_id="worker", lease_expires_at=None, user_id="alice", execution_fence=ExecutionFence("test", "workflow", "old", 1))
    assert await repo.get("child", user_id="alice") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["holder", "epoch", "user", "expired", "missing"])
async def test_fence_rejects_wrong_authority(repo, changed):
    from deerflow.runtime.runs.manager import ConflictError

    values = dict(namespace="test", resource_id="workflow", user_id="alice", holder_id="owner", epoch=1, expires_at=9999999999)
    if changed != "missing":
        values.update({"holder_id": "other"} if changed == "holder" else {"epoch": 2} if changed == "epoch" else {"user_id": "bob"} if changed == "user" else {"expires_at": 0})
        async with repo._sf() as session:
            await session.execute(insert(ExtensionExecutionLeaseRow).values(**values))
            await session.commit()
    with pytest.raises((ValueError, ConflictError), match="execution fence"):
        await repo.create_thread_operation_atomic("child", thread_id="thread", owner_worker_id="worker", lease_expires_at=None, user_id="alice", execution_fence=ExecutionFence("test", "workflow", "owner", 1))


@pytest.mark.asyncio
async def test_fence_allows_live_owner(repo):
    async with repo._sf() as session:
        await session.execute(insert(ExtensionExecutionLeaseRow).values(namespace="test", resource_id="workflow", user_id="alice", holder_id="owner", epoch=1, expires_at=9999999999))
        await session.commit()
    row, _ = await repo.create_thread_operation_atomic("child", thread_id="thread", owner_worker_id="worker", lease_expires_at=None, user_id="alice", execution_fence=ExecutionFence("test", "workflow", "owner", 1))
    assert row["run_id"] == "child"


@pytest.mark.asyncio
async def test_postgres_takeover_fences_admission_after_lock_wait():
    import asyncio
    import os
    import uuid

    dsn = os.getenv("DEERFLOW_TEST_WORKFLOW_POSTGRES")
    if not dsn:
        pytest.skip("Requires dedicated PostgreSQL")

    # The default install does not need optional drivers without this opt-in.
    import psycopg
    from psycopg import sql
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.run import RunRepository
    from deerflow.persistence.run.model import RunChangeClockRow, RunRow
    from deerflow.runtime.runs.manager import ConflictError

    schema = "fence_test_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    engine = create_async_engine(dsn.split("?")[0].replace("postgresql://", "postgresql+asyncpg://"), connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            for table in (ExtensionExecutionLeaseRow.__table__, RunChangeClockRow.__table__, RunRow.__table__):
                await connection.run_sync(table.create)
        async with sessions() as session:
            await session.execute(insert(ExtensionExecutionLeaseRow).values(namespace="test", resource_id="workflow", user_id="alice", holder_id="old", epoch=1, expires_at=9999999999))
            await session.commit()
        repository = RunRepository(sessions)
        async with sessions() as takeover:
            await takeover.execute(update(ExtensionExecutionLeaseRow).values(holder_id="new", epoch=2))
            admission = asyncio.create_task(
                repository.create_thread_operation_atomic("child", thread_id="thread", owner_worker_id="worker", lease_expires_at=None, user_id="alice", execution_fence=ExecutionFence("test", "workflow", "old", 1))
            )
            try:
                # Observe an actual database lock waiter before releasing the
                # takeover; a sleep-only test could miss the vulnerable window.
                from sqlalchemy import text

                for _ in range(200):
                    async with engine.connect() as observer:
                        waiting = await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%extension_execution_leases%'"))
                    if waiting:
                        break
                    await asyncio.sleep(0.01)
                assert waiting
                await takeover.commit()
                with pytest.raises(ConflictError, match="execution fence"):
                    await admission
            finally:
                await takeover.rollback()
                await asyncio.gather(admission, return_exceptions=True)
        assert await repository.get("child", user_id="alice") is None
    finally:
        await engine.dispose()
        with psycopg.connect(dsn, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.asyncio
async def test_fenced_cancel_cannot_cancel_successor_child(repo):
    from deerflow.runtime.runs.manager import ConflictError

    async with repo._sf() as session:
        await session.execute(insert(ExtensionExecutionLeaseRow).values(namespace="test", resource_id="workflow", user_id="alice", holder_id="new", epoch=2, expires_at=9999999999))
        await session.commit()
    await repo.create_thread_operation_atomic("child", thread_id="thread", owner_worker_id="worker", lease_expires_at=None, user_id="alice")
    with pytest.raises(ConflictError, match="execution fence"):
        await repo.request_cancel("child", action="interrupt", execution_fence=ExecutionFence("test", "workflow", "old", 1), user_id="alice")
    assert (await repo.get("child", user_id="alice"))["cancel_action"] is None
    assert await repo.request_cancel("child", action="interrupt", execution_fence=ExecutionFence("test", "workflow", "new", 2), user_id="alice") == "interrupt"


@pytest.mark.asyncio
async def test_execution_fence_migration_upgrade_and_downgrade(tmp_path):
    import asyncio

    import sqlalchemy as sa
    from alembic import command
    from sqlalchemy.ext.asyncio import create_async_engine

    from deerflow.persistence import bootstrap

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fence-migration.db'}")
    config = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(bootstrap._upgrade, config, "0047_mcp_oauth_tokens")
        async with engine.begin() as connection:
            await connection.execute(sa.text("DROP TABLE IF EXISTS extension_execution_leases"))
        await asyncio.to_thread(bootstrap._upgrade, config, "0048_extension_execution_leases")
        async with engine.connect() as connection:
            assert "extension_execution_leases" in await connection.run_sync(lambda c: sa.inspect(c).get_table_names())
        await asyncio.to_thread(command.downgrade, config, "0047_mcp_oauth_tokens")
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda c: sa.inspect(c).get_table_names())
            assert "extension_execution_leases" not in names
            assert "mcp_oauth_tokens" in names
            assert (await connection.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == "0047_mcp_oauth_tokens"
    finally:
        await engine.dispose()
