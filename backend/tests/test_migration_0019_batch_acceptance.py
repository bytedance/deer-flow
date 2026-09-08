"""Upgrade real 0018 tables, preserve old rows, and reject missing forward fields."""

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.util.exc import CommandError
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap


@pytest.mark.asyncio
async def test_upgrade_and_downgrade_preserve_legacy_batch_item(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'batch.db'}")
    cfg = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(bootstrap._upgrade, cfg, "0018_oauth_identity_pg_partial")
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
                    "VALUES ('i','b','k',0,'p','succeeded',1,'old result',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: {col["name"] for col in sa.inspect(sync).get_columns("subagent_batch_items")})
            assert {"acceptance_criteria", "acceptance_verdict"} <= columns
            row = (await conn.execute(sa.text("SELECT result,status,acceptance_criteria,acceptance_verdict FROM subagent_batch_items"))).one()
            assert tuple(row) == ("old result", "succeeded", None, None)
        await asyncio.to_thread(command.downgrade, cfg, "0018_oauth_identity_pg_partial")
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: {col["name"] for col in sa.inspect(sync).get_columns("subagent_batch_items")})
            assert "acceptance_verdict" not in columns
            assert await conn.scalar(sa.text("SELECT result FROM subagent_batch_items")) == "old result"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("race", [False, True])
async def test_incarnation_only_forward_revision_cannot_skip_required_batch_columns(tmp_path, monkeypatch, race):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'forward.db'}")
    cfg = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(bootstrap._upgrade, cfg, "0018_oauth_identity_pg_partial")
        if race:

            def raced_upgrade(*args):
                sync = sa.create_engine(f"sqlite:///{tmp_path / 'forward.db'}")
                try:
                    with sync.begin() as conn:
                        conn.execute(sa.text("UPDATE alembic_version SET version_num='0019_thread_incarnations'"))
                finally:
                    sync.dispose()
                raise CommandError("another deployment migrated first")

            monkeypatch.setattr(bootstrap, "_upgrade", raced_upgrade)
        else:
            async with engine.begin() as conn:
                await conn.execute(sa.text("UPDATE alembic_version SET version_num='0019_thread_incarnations'"))
        with pytest.raises(RuntimeError, match="batch acceptance columns"):
            await bootstrap.bootstrap_schema(engine, backend="sqlite")
    finally:
        await engine.dispose()
