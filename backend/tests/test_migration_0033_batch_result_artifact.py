"""Nullable batch evidence migration preserves legacy report rows."""

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
from deerflow.persistence.subagent_batches.model import SubagentBatchItemRow


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_upgrade_downgrade_and_reupgrade_preserve_report(tmp_path, backend):
    schema = None
    if backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres batch evidence migration)")
        schema = f"batch_evidence_{uuid.uuid4().hex}"
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'batch.db'}")
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(bootstrap._upgrade, cfg, "0032_activity_and_task_events")
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
            row = (await conn.execute(sa.text("SELECT result,status,result_artifact FROM subagent_batch_items"))).one()
            assert tuple(row) == ("old report", "succeeded", None)
        snapshot = {"knowledge_sources": {"version": 1, "sources": [{"id": "a" * 32 + "-1", "provider": "ragflow", "dataset_id": "kb", "document_id": "doc", "chunk_id": "chunk", "text": "Captured evidence ☃"}], "omitted_count": 0}}
        async with engine.begin() as conn:
            await conn.execute(sa.update(SubagentBatchItemRow).where(SubagentBatchItemRow.id == "i").values(result_artifact=snapshot))
        async with engine.connect() as conn:
            assert (await conn.execute(sa.select(SubagentBatchItemRow.result_artifact).where(SubagentBatchItemRow.id == "i"))).scalar_one() == snapshot
        await asyncio.to_thread(command.downgrade, cfg, "0032_activity_and_task_events")
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: {column["name"] for column in sa.inspect(sync).get_columns("subagent_batch_items")})
            assert "result_artifact" not in columns
            assert (await conn.execute(sa.text("SELECT result FROM subagent_batch_items"))).scalar_one() == "old report"
        await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema or "")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT result_artifact FROM subagent_batch_items"))).scalar_one() is None
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


class _StopBeforeDatabase(Exception):
    """End a connection-contract probe before acquiring database resources."""


@pytest.mark.asyncio
@pytest.mark.parametrize("sslmode", [None, "disable", "allow", "prefer", "require", "verify-ca", "verify-full"])
async def test_postgres_migration_setup_preserves_tls_policy(monkeypatch, tmp_path, sslmode):
    uri = "postgresql://user:password@localhost:5432/test?target_session_attrs=read-write&channel_binding=prefer"
    if sslmode is not None:
        uri += f"&sslmode={sslmode}"
    monkeypatch.setenv("TEST_POSTGRES_URI", uri)

    def capture_engine(url, **kwargs):
        parsed = sa.engine.make_url(url)
        _args, connect_options = parsed.get_dialect()().create_connect_args(parsed)
        assert connect_options["target_session_attrs"] == "read-write"
        assert "sslmode" not in connect_options and "channel_binding" not in connect_options
        if sslmode is None:
            assert "ssl" not in connect_options
        else:
            assert connect_options.get("ssl") == sslmode
        raise _StopBeforeDatabase

    monkeypatch.setitem(globals(), "create_async_engine", capture_engine)
    with pytest.raises(_StopBeforeDatabase):
        await test_upgrade_downgrade_and_reupgrade_preserve_report(tmp_path, "postgres")


@pytest.mark.asyncio
async def test_postgres_migration_setup_rejects_conflicting_tls_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_POSTGRES_URI", "postgresql://user:password@localhost:5432/test?ssl=require&sslmode=disable")

    def reject_engine_creation(*args, **kwargs):
        pytest.fail("Conflicting TLS options must be rejected before engine creation")

    monkeypatch.setitem(globals(), "create_async_engine", reject_engine_creation)
    with pytest.raises(ValueError, match="Conflicting ssl and sslmode"):
        await test_upgrade_downgrade_and_reupgrade_preserve_report(tmp_path, "postgres")
