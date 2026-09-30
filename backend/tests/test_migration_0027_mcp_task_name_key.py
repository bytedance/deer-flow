"""Verify existing task name backfill, indexes, and migration round trips."""

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap

REVISION = "0027_mcp_task_name_key"
PREVIOUS = "0026_mcp_task_lease_tokens"


def test_0027_is_single_chain_head():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS


@pytest.mark.asyncio
async def test_name_key_backfill_across_batches_and_downgrade(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'names.db'}")
    cfg = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO mcp_tasks (id,user_id,thread_id,server_name,driver_name,remote_task_id,task_name,status,driver_data,notification_status,"
                    "poll_attempt_count,consecutive_poll_error_count,created_at,updated_at) "
                    "VALUES (:id,'user-1','thread-1','reports','fake',:id,:name,'working','{}','none',0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                ),
                [{"id": f"task-{i:04}", "name": "Straße" if i % 2 == 0 else "Σςσ"} for i in range(501)],
            )
        for _ in range(2):
            await asyncio.to_thread(command.upgrade, cfg, REVISION)
            async with engine.connect() as connection:
                rows = (await connection.execute(sa.text("SELECT id, task_name, task_name_key FROM mcp_tasks ORDER BY id"))).all()
                indexes = await connection.run_sync(lambda sync: sa.inspect(sync).get_indexes("mcp_tasks"))
                columns = await connection.run_sync(lambda sync: sa.inspect(sync).get_columns("mcp_tasks"))
            assert len(rows) == 501
            assert rows[0].task_name_key == b"strasse"
            assert rows[-1].task_name_key == b"strasse"
            assert rows[1].task_name_key == "σσσ".encode()
            assert rows[0].task_name == "Straße"
            assert next(column for column in columns if column["name"] == "task_name_key")["nullable"] is False
            assert next(index for index in indexes if index["name"] == "ix_mcp_tasks_name_scope")["column_names"] == ["user_id", "thread_id", "task_name_key"]
            await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
            async with engine.connect() as connection:
                columns = await connection.run_sync(lambda sync: sa.inspect(sync).get_columns("mcp_tasks"))
                assert "task_name_key" not in {column["name"] for column in columns}
                assert (await connection.execute(sa.text("SELECT count(*) FROM mcp_tasks"))).scalar_one() == 501
    finally:
        await engine.dispose()
