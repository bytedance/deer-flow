"""Migration tests for the scheduled-task notification outbox (issue #4254).

``0027_notification_deliveries`` creates the outbox table and
``0028_parked_attempts`` adds its parking counter. This file owns the chain-head
pin, moved on from ``test_migration_0026_mcp_task_lease_tokens``.
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
PREVIOUS = "0026_mcp_task_lease_tokens"
TABLE = "notification_deliveries"


async def test_0028_is_the_chain_head():
    assert bootstrap._get_head_revision() == PARKED


async def test_outbox_revisions_chain_after_0026():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    assert script.get_revision(OUTBOX).down_revision == PREVIOUS
    assert script.get_revision(PARKED).down_revision == OUTBOX
    # alembic_version.version_num is VARCHAR(32); a longer id fails on Postgres.
    assert max(len(OUTBOX), len(PARKED)) <= 32


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

        await asyncio.to_thread(bootstrap._upgrade, cfg, "head")
        columns = await outbox_columns()
        assert columns["parked_attempts"]["nullable"] is False
        # The backfill default is dropped so the schema matches create_all.
        assert columns["parked_attempts"]["default"] is None

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert await outbox_columns() is None
    finally:
        await engine.dispose()
