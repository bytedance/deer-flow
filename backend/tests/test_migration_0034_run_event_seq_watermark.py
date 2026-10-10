"""Migration 0034: durable run-event sequence watermark."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

REVISION = "0034_run_event_seq_watermark"
PREVIOUS = "0033_batch_result_artifact"
LOGIN_THROTTLE = "0035_login_throttle"
IDEMPOTENCY = "0036_run_idempotency_request"
CURRENT_HEAD = "0037_project_document_summaries"
TABLE = "run_event_thread_seq"
pytestmark = pytest.mark.asyncio


async def test_0034_remains_in_the_single_migration_chain():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(LOGIN_THROTTLE).down_revision == REVISION
    assert script.get_revision(IDEMPOTENCY).down_revision == LOGIN_THROTTLE
    assert script.get_revision(CURRENT_HEAD).down_revision == IDEMPOTENCY
    assert len(REVISION) <= 32


def _engine(tmp_path, backend):
    if backend == "sqlite":
        return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"), None
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres migration 0034)")
    parts = urlsplit(uri)
    scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
    schema = f"run_event_seq_{uuid.uuid4().hex}"
    return create_async_engine(urlunsplit(parts._replace(scheme=scheme, query=query)), connect_args=build_asyncpg_connect_args(schema)), schema


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0034_backfills_and_round_trips(tmp_path, backend):
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)

        run_events = sa.table(
            "run_events",
            sa.column("thread_id", sa.String(64)),
            sa.column("run_id", sa.String(64)),
            sa.column("user_id", sa.String(64)),
            sa.column("event_type", sa.String(32)),
            sa.column("category", sa.String(16)),
            sa.column("content", sa.Text()),
            sa.column("event_metadata", sa.JSON()),
            sa.column("seq", sa.Integer()),
            sa.column("created_at", sa.DateTime(timezone=True)),
        )
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(run_events),
                [
                    {
                        "thread_id": "t1",
                        "run_id": "r1",
                        "user_id": None,
                        "event_type": "human_message",
                        "category": "message",
                        "content": "",
                        "event_metadata": {},
                        "seq": 1,
                        "created_at": datetime.now(UTC),
                    },
                    {
                        "thread_id": "t1",
                        "run_id": "r2",
                        "user_id": None,
                        "event_type": "human_message",
                        "category": "message",
                        "content": "",
                        "event_metadata": {},
                        "seq": 2,
                        "created_at": datetime.now(UTC),
                    },
                    {
                        "thread_id": "t2",
                        "run_id": "r1",
                        "user_id": None,
                        "event_type": "human_message",
                        "category": "message",
                        "content": "",
                        "event_metadata": {},
                        "seq": 5,
                        "created_at": datetime.now(UTC),
                    },
                ],
            )

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.connect() as conn:
            assert TABLE in await conn.run_sync(lambda sync: set(sa.inspect(sync).get_table_names()))
            rows = (await conn.execute(sa.text(f"SELECT thread_id, seq FROM {TABLE} ORDER BY thread_id"))).all()
        assert [tuple(row) for row in rows] == [("t1", 2), ("t2", 5)]

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        async with engine.connect() as conn:
            assert TABLE not in await conn.run_sync(lambda sync: set(sa.inspect(sync).get_table_names()))

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.connect() as conn:
            assert TABLE in await conn.run_sync(lambda sync: set(sa.inspect(sync).get_table_names()))
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
