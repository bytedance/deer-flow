"""Upgrade legacy/project schemas, preserve rows, and reject missing batch fields."""

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap


@pytest.mark.asyncio
@pytest.mark.parametrize("source_revision", ["0018_oauth_identity_pg_partial", "0020_threads_meta_project_id"])
async def test_upgrade_and_downgrade_preserve_legacy_batch_item(tmp_path, source_revision):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'batch.db'}")
    cfg = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(bootstrap._upgrade, cfg, source_revision)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO subagent_batches (id,user_id,thread_id,submission_key,title,subagent_type,status,total_items,max_live_items,max_running_items,max_attempts,execution_spec,created_at,updated_at) "
                    "VALUES ('b','u','t','k','title','general-purpose','completed',1,1,1,2,'{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
            if source_revision == "0020_threads_meta_project_id":
                await conn.execute(sa.text("INSERT INTO projects (id,user_id,name,instructions,presentation,status,created_at,updated_at) VALUES ('p','u','existing project','','{}','active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
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
        await asyncio.to_thread(command.downgrade, cfg, source_revision)
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: {col["name"] for col in sa.inspect(sync).get_columns("subagent_batch_items")})
            assert "acceptance_verdict" not in columns
            assert await conn.scalar(sa.text("SELECT result FROM subagent_batch_items")) == "old result"
            if source_revision == "0020_threads_meta_project_id":
                assert await conn.scalar(sa.text("SELECT name FROM projects WHERE id='p'")) == "existing project"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("race", [False, True])
async def test_forward_revision_cannot_skip_required_batch_columns(tmp_path, monkeypatch, race):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'forward.db'}")
    cfg = bootstrap._get_alembic_config(engine)
    try:
        # Keep the project schema present so only the batch-column guard can
        # reject this database, on both direct and concurrent-startup paths.
        await asyncio.to_thread(bootstrap._upgrade, cfg, "0020_threads_meta_project_id")
        async with engine.begin() as conn:
            await conn.execute(sa.text("ALTER TABLE threads_meta ADD COLUMN incarnation VARCHAR(32)"))
            await conn.execute(sa.text("ALTER TABLE mcp_tasks ADD COLUMN thread_incarnation VARCHAR(32)"))
        if race:
            current_head, current_revisions = bootstrap._get_revision_metadata()
            assert {"0020_threads_meta_project_id", "0021_batch_acceptance", "0019_thread_incarnations", current_head} <= current_revisions
            # The published 0020 binary knows only the ancestors of its own head.
            rollback_revisions = frozenset(revision.revision for revision in ScriptDirectory.from_config(cfg).iterate_revisions("0020_threads_meta_project_id", "base"))
            assert not ({"0021_batch_acceptance", "0019_thread_incarnations", current_head} & rollback_revisions)
            monkeypatch.setattr(
                bootstrap,
                "_get_revision_metadata",
                lambda: ("0020_threads_meta_project_id", rollback_revisions),
            )

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
        with pytest.raises(RuntimeError, match="missing required local schema: subagent_batch_items.acceptance_criteria, subagent_batch_items.acceptance_verdict"):
            await bootstrap.bootstrap_schema(engine, backend="sqlite")
    finally:
        await engine.dispose()
