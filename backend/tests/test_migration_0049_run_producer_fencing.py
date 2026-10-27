"""Historical rows gain no authority; migration and fresh bootstrap agree."""

import asyncio
import os
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence import bootstrap
from deerflow.persistence.run.producer import activate_producer_fencing

REVISION = "0049_run_producer_fencing"
PREVIOUS = "0048_extension_execution_leases"


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize("fresh", [False, True])
async def test_migration_and_bootstrap(tmp_path, backend, fresh):
    schema = None
    if backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = "fence_migration_" + uuid4().hex
        engine = create_async_engine(uri, connect_args={"server_settings": {"search_path": schema, "application_name": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        if fresh:
            await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema or "")
        else:
            await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
            async with engine.begin() as conn:
                await conn.execute(
                    text("""INSERT INTO runs(
                    run_id,thread_id,user_id,status,multitask_strategy,metadata_json,kwargs_json,
                    message_count,total_input_tokens,total_output_tokens,total_tokens,llm_call_count,
                    lead_agent_tokens,subagent_tokens,middleware_tokens,created_at,updated_at
                ) VALUES ('old','thread','alice','success','reject','{}','{}',0,0,0,0,0,0,0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""")
                )
            await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: {c["name"]: c for c in inspect(sync).get_columns("runs")})
            for name in ("run_incarnation", "producer_epoch", "producer_state"):
                assert columns[name]["nullable"]
                assert columns[name]["default"] is None
            if not fresh:
                assert (await conn.execute(text("SELECT run_incarnation,producer_epoch,producer_state FROM runs WHERE run_id='old'"))).one() == (None, None, None)
            assert await conn.scalar(text("SELECT count(*) FROM run_producer_policy")) == 0
            if schema:
                assert await conn.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgrelid='run_events'::regclass AND tgname='run_event_producer_guard'")) == 1
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        async with engine.connect() as conn:
            assert "producer_epoch" not in await conn.run_sync(lambda sync: {c["name"] for c in inspect(sync).get_columns("runs")})
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        if schema:
            # Dispose bootstrap's idle pooled connections before offline cutover.
            await engine.dispose()
            try:
                await activate_producer_fencing(async_sessionmaker(engine), cutover_id="migration-check")
            except RuntimeError:
                async with engine.connect() as conn:
                    clients = (
                        await conn.execute(
                            text("SELECT pid,state,application_name,backend_start,query_start,left(query,250) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'")
                        )
                    ).all()
                pytest.fail(f"Unexpected live clients at isolated offline cutover: {clients}")
            await engine.dispose()
            with pytest.raises(RuntimeError, match="Cannot downgrade"):
                await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
