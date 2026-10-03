"""Migration tests for the scheduled-task notification outbox (issue #4254).

``0027_notification_deliveries`` creates the outbox table and
``0028_parked_attempts`` adds its parking counter, and
``0029_notification_claim_token`` fences delivery completion.
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
CLAIM = "0029_notification_claim_token"
PREVIOUS = "0026_mcp_task_lease_tokens"
TABLE = "notification_deliveries"


async def test_0029_is_the_chain_head():
    assert bootstrap._get_head_revision() == CLAIM


async def test_outbox_revisions_chain_after_0026():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    assert script.get_revision(OUTBOX).down_revision == PREVIOUS
    assert script.get_revision(PARKED).down_revision == OUTBOX
    assert script.get_revision(CLAIM).down_revision == PARKED
    # alembic_version.version_num is VARCHAR(32); a longer id fails on Postgres.
    assert max(len(OUTBOX), len(PARKED), len(CLAIM)) <= 32


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

        await asyncio.to_thread(bootstrap._upgrade, cfg, PARKED)
        columns = await outbox_columns()
        assert "claim_token" not in columns
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO notification_deliveries "
                    "(id, task_id, task_run_id, event, provider, target, owner_user_id, status, "
                    "attempts, parked_attempts, max_attempts, payload_json, available_at, created_at, updated_at) "
                    "VALUES ('legacy', 'task', 'run', 'completed', 'wecom', 'target', 'owner', "
                    "'sending', 2, 3, 5, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        await asyncio.to_thread(bootstrap._upgrade, cfg, "head")
        columns = await outbox_columns()
        assert columns["claim_token"]["nullable"] is True
        assert columns["claim_token"]["default"] is None
        assert columns["claim_token"]["type"].length == 32
        async with engine.connect() as conn:
            legacy = (await conn.execute(sa.text("SELECT status, attempts, parked_attempts, claim_token FROM notification_deliveries WHERE id = 'legacy'"))).one()
            assert tuple(legacy) == ("sending", 2, 3, None)
        await asyncio.to_thread(command.downgrade, cfg, PARKED)
        assert "claim_token" not in await outbox_columns()
        await asyncio.to_thread(bootstrap._upgrade, cfg, "head")
        columns = await outbox_columns()
        assert columns["parked_attempts"]["nullable"] is False
        # The backfill default is dropped so the schema matches create_all.
        assert columns["parked_attempts"]["default"] is None

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert await outbox_columns() is None
    finally:
        await engine.dispose()
