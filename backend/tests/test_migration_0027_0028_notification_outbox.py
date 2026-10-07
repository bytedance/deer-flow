"""Migration tests for the scheduled-task notification outbox (issue #4254).

``0027_notification_deliveries`` creates the outbox table and
``0028_parked_attempts`` adds its parking counter. The scheduler-agent and
notification claim-token migrations extend that chain in order.
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap

pytestmark = pytest.mark.asyncio

OUTBOX = "0027_notification_deliveries"
PARKED = "0028_parked_attempts"
SCHEDULER = "0029_scheduler_agent_tasks"
CLAIM_TOKENS = "0030_notification_claim_tokens"
HEAD = "0032_batch_result_artifact"
PREVIOUS = "0026_mcp_task_lease_tokens"
TABLE = "notification_deliveries"


async def test_outbox_revisions_chain_after_0026():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    assert script.get_revision(OUTBOX).down_revision == PREVIOUS
    assert script.get_revision(PARKED).down_revision == OUTBOX
    assert script.get_revision(SCHEDULER).down_revision == PARKED
    assert script.get_revision(CLAIM_TOKENS).down_revision == SCHEDULER
    # alembic_version.version_num is VARCHAR(32); a longer id fails on Postgres.
    assert max(len(OUTBOX), len(PARKED), len(SCHEDULER), len(CLAIM_TOKENS)) <= 32


async def test_outbox_revisions_upgrade_and_downgrade(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'outbox.db'}")
    cfg = bootstrap._get_alembic_config(engine)

    async def outbox_columns() -> dict[str, dict] | None:
        async with engine.connect() as conn:

            def read(sync):
                inspector = sa.inspect(sync)
                if not inspector.has_table(TABLE):
                    return None
                return {column["name"]: column for column in inspector.get_columns(TABLE)}

            return await conn.run_sync(read)

    try:
        await asyncio.to_thread(bootstrap._upgrade, cfg, PREVIOUS)
        assert await outbox_columns() is None

        await asyncio.to_thread(bootstrap._upgrade, cfg, OUTBOX)
        columns = await outbox_columns()
        assert columns is not None and "parked_attempts" not in columns
        assert "claim_token" not in columns

        await asyncio.to_thread(bootstrap._upgrade, cfg, "head")
        columns = await outbox_columns()
        assert columns["parked_attempts"]["nullable"] is False
        # The backfill default is dropped so the schema matches create_all.
        assert columns["parked_attempts"]["default"] is None
        assert columns["claim_token"]["nullable"] is True

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert await outbox_columns() is None
    finally:
        await engine.dispose()


async def test_bootstrap_claim_tokens_preserves_existing_scheduler_and_outbox(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scheduler.db'}")
    cfg = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(bootstrap._upgrade, cfg, SCHEDULER)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO scheduled_tasks "
                    "(id,user_id,context_mode,title,prompt,schedule_type,schedule_spec,timezone,status,overlap_policy,run_count,goal_objective,created_at,updated_at) "
                    "VALUES ('task','owner','fresh_thread_per_run','Goal','Prompt','cron','{}','UTC','enabled','enqueue',7,'deliver',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO notification_deliveries "
                    "(id,task_id,task_run_id,event,provider,target,owner_user_id,status,attempts,parked_attempts,max_attempts,payload_json,available_at,created_at,updated_at) "
                    "VALUES ('delivery','task','occurrence','success','telegram','target','owner','pending',2,1,5,'{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )

        async def assert_preserved():
            async with engine.connect() as conn:
                assert (await conn.execute(sa.text("SELECT run_count,goal_objective FROM scheduled_tasks WHERE id='task'"))).one() == (7, "deliver")
                assert (await conn.execute(sa.text("SELECT status,attempts,parked_attempts FROM notification_deliveries WHERE id='delivery'"))).one() == ("pending", 2, 1)

        for _ in range(2):
            await bootstrap.bootstrap_schema(engine, backend="sqlite")
            await assert_preserved()
            async with engine.connect() as conn:
                assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == HEAD
                assert (await conn.execute(sa.text("SELECT claim_token FROM notification_deliveries WHERE id='delivery'"))).scalar_one() is None

        await asyncio.to_thread(command.downgrade, cfg, SCHEDULER)
        await assert_preserved()
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: {col["name"] for col in sa.inspect(sync).get_columns(TABLE)})
            assert "claim_token" not in columns
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == SCHEDULER
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        await assert_preserved()
    finally:
        await engine.dispose()
