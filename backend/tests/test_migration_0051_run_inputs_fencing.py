"""Both deployed migration branches converge without losing Run data or policy."""

import asyncio
import os
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize("previous", ["0049_run_inputs", "0049_run_producer_fencing", "0050_history_seed_authority"])
async def test_both_migration_branches_upgrade_to_one_head(tmp_path, backend, previous):
    schema = None
    if backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = "merged_runs_" + uuid4().hex
        engine = create_async_engine(asyncpg_test_url(uri), connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, previous)
        async with engine.begin() as conn:
            columns = await conn.run_sync(lambda sync: {c["name"] for c in inspect(sync).get_columns("runs")})
            if previous == "0049_run_inputs":
                assert "run_inputs_json" in columns
                assert "run_incarnation" not in columns
                assert not await conn.run_sync(lambda sync: inspect(sync).has_table("run_producer_policy"))
            else:
                assert "run_inputs_json" not in columns
                assert {"run_incarnation", "producer_epoch", "producer_state"} <= columns
                if schema:
                    await conn.execute(text("INSERT INTO run_producer_policy(id,strict,cutover_id) VALUES (1,true,'preserved-policy')"))
            await conn.execute(
                text("""INSERT INTO runs(
                    run_id,thread_id,user_id,status,multitask_strategy,metadata_json,kwargs_json,
                    message_count,total_input_tokens,total_output_tokens,total_tokens,llm_call_count,
                    lead_agent_tokens,subagent_tokens,middleware_tokens,created_at,updated_at
                ) VALUES ('old','thread','alice','success','reject','{}','{}',0,0,0,0,0,0,0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""")
            )
        await asyncio.to_thread(command.upgrade, cfg, "head")
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars().all() == ["0051_merge_run_inputs_fencing"]
            columns = await conn.run_sync(lambda sync: {c["name"] for c in inspect(sync).get_columns("runs")})
            assert {"run_inputs_json", "run_incarnation", "producer_epoch", "producer_state"} <= columns
            assert (await conn.execute(text("SELECT status,run_inputs_json,run_incarnation,producer_epoch,producer_state FROM runs WHERE run_id='old'"))).one() == ("success", None, None, None, None)
            if schema:
                assert await conn.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgrelid='run_events'::regclass AND tgname='run_event_producer_guard'")) == 1
                if previous != "0049_run_inputs":
                    assert (await conn.execute(text("SELECT strict,cutover_id FROM run_producer_policy WHERE id=1"))).one() == (True, "preserved-policy")
        # Bootstrap must also recognize the merged stamp on a later restart.
        await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema or "")
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
