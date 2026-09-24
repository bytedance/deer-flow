"""Migration ``0009_webhook_dedupe`` regression test (issue #4120).

Verifies the migration creates ``webhook_deliveries`` with the composite
primary key (channel, workspace_id, chat_id, message_id) and no legacy
``dedupe_key`` column, and that re-running it is idempotent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

import deerflow.persistence.models  # noqa: F401  -- registers ORM models
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import bootstrap_schema
from deerflow.persistence.engine import close_engine, init_engine

pytestmark = pytest.mark.asyncio


async def test_migration_0009_creates_composite_pk_table_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "deer.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url)
    try:
        # Seed all baseline tables, then drop ONLY webhook_deliveries so the
        # 0009 upgrade actually exercises its create_table path (not the
        # idempotent early-return). Stamp at 0004 so bootstrap upgrades to head.
        sync = sa.create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(sync)
        with sync.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS webhook_deliveries"))
            conn.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("DELETE FROM alembic_version"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0004_run_ownership')"))

        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        # Runs upgrade head -> executes 0009.create_table.
        await bootstrap_schema(engine, backend="sqlite")

        async with engine.connect() as conn:
            cols = {row["name"] for row in await conn.run_sync(lambda c: sa.inspect(c).get_columns("webhook_deliveries"))}
        # Composite PK columns only; the old single-column ``dedupe_key`` must
        # NOT exist (it is illegal in Postgres TEXT and caused schema drift).
        assert cols == {"channel", "workspace_id", "chat_id", "message_id", "first_seen"}

        # Idempotent: re-running bootstrap at head must not raise (table exists).
        await bootstrap_schema(engine, backend="sqlite")
    finally:
        await close_engine()
