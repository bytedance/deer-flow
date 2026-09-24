"""Migration test for 0018_oauth_identity_pg_partial.

The other OAuth-index test (test_user_oauth_partial_index.py) provisions the
schema through ``init_engine_from_config``, which on an empty database takes
the bootstrap ``create_all()`` path -- it builds the partial index straight
from current ORM metadata and stamps alembic at head, so
``0018.upgrade()`` never actually runs. Existing installations only get the
partial predicate via the migration, so this exercises that path directly:
alembic-upgrade to 0017 (index created full by 0001_baseline, which passed
``sqlite_where`` but not ``postgresql_where``), then to 0018, and assert the
predicate appears; the downgrade must restore the full index.

Postgres-only (the revision is a no-op on SQLite -- 0001_baseline already
gave that backend ``sqlite_where``). Opt in with DEERFLOW_TEST_POSTGRES_URL,
same as test_pg_schema_integration.py.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config

POSTGRES_URL = os.getenv("DEERFLOW_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not POSTGRES_URL, reason="set DEERFLOW_TEST_POSTGRES_URL to run live PostgreSQL tests"),
]

_PREVIOUS = "0017_personal_access_tokens"
_REVISION = "0018_oauth_identity_pg_partial"
_INDEX = "idx_users_oauth_identity"


async def _index_predicate(engine, schema: str) -> str | None:
    """The index's WHERE predicate as SQL text, or None if it is a full
    (non-partial) index. Raises if the index does not exist."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT pg_get_expr(i.indpred, i.indrelid) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relname = :idx AND n.nspname = :schema"),
                {"idx": _INDEX, "schema": schema},
            )
        ).fetchone()
    assert row is not None, f"{_INDEX} not found in schema {schema}"
    return row[0]


async def test_0018_adds_partial_predicate_and_downgrade_restores_full_index() -> None:
    schema = f"deerflow_test_{uuid.uuid4().hex[:12]}"
    engine = create_async_engine(POSTGRES_URL or "")
    cfg = _get_alembic_config(engine, postgres_schema=schema)

    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))

        # env.py drives migrations with its own asyncio.run, so the sync
        # command API must run off the test loop (same wrapper production uses).
        await asyncio.to_thread(alembic_command.upgrade, cfg, _PREVIOUS)
        assert await _index_predicate(engine, schema) is None, "0001_baseline should create a full index on Postgres"

        await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)
        predicate = await _index_predicate(engine, schema)
        assert predicate is not None, "0018 did not make the index partial"
        assert "oauth_provider" in predicate and "oauth_id" in predicate

        await asyncio.to_thread(alembic_command.downgrade, cfg, _PREVIOUS)
        assert await _index_predicate(engine, schema) is None, "downgrade did not restore the full index"

        # Round-trips: re-upgrading is idempotent (0018 also guards on indpred).
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
        assert await _index_predicate(engine, schema) is not None
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
