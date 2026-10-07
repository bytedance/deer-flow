"""Nullable batch evidence migration preserves legacy report rows."""

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap


@pytest.mark.asyncio
async def test_upgrade_downgrade_and_reupgrade_preserve_report(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'batch.db'}")
    cfg = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(bootstrap._upgrade, cfg, "0031_scheduled_streak_boundary")
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO subagent_batches (id,user_id,thread_id,submission_key,title,subagent_type,status,total_items,max_live_items,max_running_items,max_attempts,execution_spec,created_at,updated_at) "
                    "VALUES ('b','u','t','k','title','general-purpose','completed',1,1,1,2,'{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO subagent_batch_items (id,batch_id,item_key,position,prompt,status,attempt,result,result_truncated,created_at,updated_at) "
                    "VALUES ('i','b','k',0,'p','succeeded',1,'old report',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as conn:
            row = (await conn.execute(sa.text("SELECT result,status,result_artifact FROM subagent_batch_items"))).one()
            assert tuple(row) == ("old report", "succeeded", None)
        await asyncio.to_thread(command.downgrade, cfg, "0031_scheduled_streak_boundary")
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: {column["name"] for column in sa.inspect(sync).get_columns("subagent_batch_items")})
            assert "result_artifact" not in columns
            assert (await conn.execute(sa.text("SELECT result FROM subagent_batch_items"))).scalar_one() == "old report"
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT result_artifact FROM subagent_batch_items"))).scalar_one() is None
    finally:
        await engine.dispose()
