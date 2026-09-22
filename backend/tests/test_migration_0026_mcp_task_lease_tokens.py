"""Migration tests for 0026_mcp_task_lease_tokens.

Adds the nullable per-claim token columns ``McpTaskRepository`` uses to fence
poll, cancel, and notification mutations to the exact claim generation. This
file owns the chain-head pin, moved on from
``test_migration_0025_repair_run_change_seq`` with this revision.
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap

pytestmark = pytest.mark.asyncio

REVISION = "0026_mcp_task_lease_tokens"
PREVIOUS = "0025_repair_run_change_seq"
TOKEN_COLUMNS = {"lease_token", "notification_lease_token"}


async def test_0026_is_the_chain_head():
    assert bootstrap._get_head_revision() == REVISION


async def test_0026_adds_nullable_claim_tokens_and_downgrades(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lease-tokens.db'}")
    cfg = bootstrap._get_alembic_config(engine)

    async def token_columns() -> dict[str, bool]:
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: sa.inspect(sync).get_columns("mcp_tasks"))
        return {column["name"]: column["nullable"] for column in columns if column["name"] in TOKEN_COLUMNS}

    try:
        await asyncio.to_thread(bootstrap._upgrade, cfg, PREVIOUS)
        assert await token_columns() == {}

        await asyncio.to_thread(bootstrap._upgrade, cfg, "head")
        # Nullable so rows written before this revision stay valid.
        assert await token_columns() == dict.fromkeys(TOKEN_COLUMNS, True)

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert await token_columns() == {}
    finally:
        await engine.dispose()
