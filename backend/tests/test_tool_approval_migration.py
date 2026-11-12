"""Exercise upgrade, retry and downgrade through the actual migration chain."""

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap


@pytest.mark.asyncio
async def test_approval_migration_retry_and_downgrade(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, cfg, "0052_batch_continuation")
        await asyncio.to_thread(command.upgrade, cfg, "0053_tool_approvals")
        async with engine.begin() as conn:
            await conn.execute(sa.text("INSERT INTO tool_approvals (request_id,user_id,thread_id,incarnation,run_id,fingerprint,kind,status,payload,created_at) VALUES ('r','u','t','i','run','fingerprint','audit','consumed','{}',1)"))
        await asyncio.to_thread(command.stamp, cfg, "0052_batch_continuation")
        async with engine.begin() as conn:
            await conn.execute(sa.text("DROP INDEX ix_tool_approvals_scope"))
        await asyncio.to_thread(command.upgrade, cfg, "0053_tool_approvals")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT request_id FROM tool_approvals"))).scalar_one() == "r"
            indexes = await conn.run_sync(lambda c: sa.inspect(c).get_indexes("tool_approvals"))
            assert {index["name"] for index in indexes} == {"ix_tool_approvals_run", "ix_tool_approvals_scope"}
        await asyncio.to_thread(command.downgrade, cfg, "0052_batch_continuation")
        async with engine.connect() as conn:
            assert not await conn.run_sync(lambda c: sa.inspect(c).has_table("tool_approvals"))
    finally:
        await engine.dispose()
