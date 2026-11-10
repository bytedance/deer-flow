"""Recovery metadata upgrades preserve reports and cannot discard active fences."""

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_batch_recovery_upgrade_preserves_legacy_rows_and_guards_downgrade(tmp_path, backend):
    schema = None
    if backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = f"batch_recovery_{uuid.uuid4().hex}"
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'batch.db'}")
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(bootstrap._upgrade, cfg, "0052_batch_continuation")
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
                    "VALUES ('i','b','k',0,'p','succeeded',1,'old report',FALSE,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
        await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema or "")
        await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema or "")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT recovery_policy FROM subagent_batches"))).scalar_one() is None
            assert tuple((await conn.execute(sa.text("SELECT status,result,attempt_id,dispatch_started_at FROM subagent_batch_items"))).one()) == ("succeeded", "old report", None, None)
        async with engine.begin() as conn:
            await conn.execute(sa.text("UPDATE subagent_batches SET recovery_policy='conservative', status='running'"))
            await conn.execute(sa.text("UPDATE subagent_batch_items SET status='outcome_unknown', attempt_id='attempt', dispatch_started_at=CURRENT_TIMESTAMP"))
        with pytest.raises(RuntimeError, match="conservative batches remain active"):
            await asyncio.to_thread(command.downgrade, cfg, "0052_batch_continuation")
        async with engine.begin() as conn:
            await conn.execute(sa.text("UPDATE subagent_batches SET status='cancelled'"))
        with pytest.raises(RuntimeError, match="outcomes remain unknown"):
            await asyncio.to_thread(command.downgrade, cfg, "0052_batch_continuation")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT attempt_id FROM subagent_batch_items"))).scalar_one() == "attempt"
        async with engine.begin() as conn:
            await conn.execute(sa.text("UPDATE subagent_batch_items SET status='cancelled'"))
        await asyncio.to_thread(command.downgrade, cfg, "0052_batch_continuation")
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: {col["name"] for col in sa.inspect(sync).get_columns("subagent_batch_items")})
            assert not {"attempt_id", "dispatch_started_at"} & columns
            assert (await conn.execute(sa.text("SELECT result FROM subagent_batch_items"))).scalar_one() == "old report"
        await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema or "")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT attempt_id FROM subagent_batch_items"))).scalar_one() is None
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
