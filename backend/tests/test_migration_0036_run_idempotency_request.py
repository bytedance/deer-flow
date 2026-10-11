"""Private run-idempotency identities remain additive and old-reader safe."""

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
from deerflow.persistence.run.model import RunRow

_IDENTITY = {
    "version": 1,
    "kind": "resume",
    "sha256": "a" * 64,
}


def _old_runs_projection() -> sa.Table:
    """The columns an older Gateway maps and can therefore expose."""
    metadata = sa.MetaData()
    return sa.Table(
        "runs",
        metadata,
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("kwargs_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_upgrade_downgrade_reupgrade_and_old_reader_projection(tmp_path, backend):
    schema = None
    if backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres run-idempotency migration)")
        schema = f"run_idempotency_{uuid.uuid4().hex}"
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'run-idempotency.db'}")
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    old_runs = _old_runs_projection()
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(bootstrap._upgrade, cfg, "0035_login_throttle")
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO runs "
                    "(run_id,thread_id,status,multitask_strategy,metadata_json,kwargs_json,"
                    "message_count,total_input_tokens,total_output_tokens,total_tokens,"
                    "llm_call_count,lead_agent_tokens,subagent_tokens,middleware_tokens,"
                    "token_usage_by_model,created_at,updated_at) "
                    "VALUES "
                    "('legacy-run','thread-1','success','reject',:metadata_json,:kwargs_json,"
                    "0,0,0,0,0,0,0,0,:token_usage_by_model,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                ),
                {
                    "metadata_json": "{}",
                    "kwargs_json": '{"input":null,"config":null}',
                    "token_usage_by_model": "{}",
                },
            )

        await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema or "")
        await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema or "")
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: {column["name"] for column in sa.inspect(sync).get_columns("runs")})
            assert "idempotency_request_json" in columns
            assert (await conn.execute(sa.select(RunRow.idempotency_request_json).where(RunRow.run_id == "legacy-run"))).scalar_one() is None

        async with engine.begin() as conn:
            await conn.execute(sa.update(RunRow).where(RunRow.run_id == "legacy-run").values(idempotency_request_json=_IDENTITY))

        async with engine.connect() as conn:
            private = (await conn.execute(sa.select(RunRow.idempotency_request_json).where(RunRow.run_id == "legacy-run"))).scalar_one()
            detail = (await conn.execute(sa.select(old_runs.c.kwargs_json).where(old_runs.c.run_id == "legacy-run"))).scalar_one()
            listed = (await conn.execute(sa.select(old_runs.c.kwargs_json).where(old_runs.c.thread_id == "thread-1").order_by(old_runs.c.created_at.desc()))).scalars().all()
            paged = (await conn.execute(sa.select(old_runs.c.kwargs_json).where(old_runs.c.thread_id == "thread-1").order_by(old_runs.c.created_at.desc(), old_runs.c.run_id.desc()).limit(1))).scalars().all()
        assert private == _IDENTITY
        assert detail == {"input": None, "config": None}
        assert listed == [detail]
        assert paged == [detail]
        assert "idempotency_request" not in detail

        await asyncio.to_thread(command.downgrade, cfg, "0035_login_throttle")
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: {column["name"] for column in sa.inspect(sync).get_columns("runs")})
            assert "idempotency_request_json" not in columns
            assert (await conn.execute(sa.select(old_runs.c.kwargs_json).where(old_runs.c.run_id == "legacy-run"))).scalar_one() == detail

        await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema or "")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.select(RunRow.idempotency_request_json).where(RunRow.run_id == "legacy-run"))).scalar_one() is None
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
