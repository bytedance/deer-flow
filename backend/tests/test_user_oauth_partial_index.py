"""Live PostgreSQL regression test for the ``users`` table's OAuth identity
index (idx_users_oauth_identity) -- same opt-in pattern as
test_pg_schema_integration.py (set DEERFLOW_TEST_POSTGRES_URL to run).

Confirms the index is created as a genuine PARTIAL index on Postgres
(``postgresql_where``), matching the SQLite side (``sqlite_where``) and the
docstring on UserRow.__table_args__. Without ``postgresql_where``, Postgres
still enforces the same practical uniqueness (NULL is never equal to NULL
in a unique index on either backend), so this is a size/maintenance
regression test for the partial predicate itself, not a correctness test
for the uniqueness constraint -- that is covered separately below.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_engine, init_engine_from_config

POSTGRES_URL = os.getenv("DEERFLOW_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set DEERFLOW_TEST_POSTGRES_URL to run live PostgreSQL tests",
)


@pytest.mark.anyio
async def test_oauth_identity_index_is_partial_on_postgres():
    schema = f"deerflow_test_{uuid.uuid4().hex[:12]}"
    db_config = DatabaseConfig(backend="postgres", postgres_url=POSTGRES_URL or "", postgres_schema=schema)

    await init_engine_from_config(db_config)
    engine = get_engine()
    assert engine is not None

    try:
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT indexdef FROM pg_indexes WHERE schemaname = :schema AND indexname = 'idx_users_oauth_identity'"),
                    {"schema": schema},
                )
            ).fetchone()
        assert row is not None, "idx_users_oauth_identity was not created in the target schema"
        indexdef = row[0]
        assert "WHERE" in indexdef, f"expected a partial index (WHERE clause), got: {indexdef}"
        assert "oauth_provider" in indexdef and "oauth_id" in indexdef
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await close_engine()


@pytest.mark.anyio
async def test_oauth_identity_uniqueness_enforced_end_to_end():
    """Correctness check (independent of whether the index is partial):
    a genuine duplicate (provider, oauth_id) pair is rejected, and
    multiple plain-password accounts (both fields NULL) are allowed to
    coexist -- the two behaviours the index exists to guarantee."""
    schema = f"deerflow_test_{uuid.uuid4().hex[:12]}"
    db_config = DatabaseConfig(backend="postgres", postgres_url=POSTGRES_URL or "", postgres_schema=schema)

    await init_engine_from_config(db_config)
    engine = get_engine()
    assert engine is not None

    try:
        from app.gateway.auth.models import User
        from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
        from deerflow.persistence.engine import get_session_factory

        repo = SQLiteUserRepository(get_session_factory())

        first = User(
            id=uuid.uuid4(),
            email="oauth-user-1@example.com",
            password_hash=None,
            system_role="user",
            created_at=datetime.now(UTC),
            oauth_provider="github",
            oauth_id="dup-check-123",
            needs_setup=False,
            token_version=0,
        )
        await repo.create_user(first)

        duplicate = User(
            id=uuid.uuid4(),
            email="oauth-user-2@example.com",
            password_hash=None,
            system_role="user",
            created_at=datetime.now(UTC),
            oauth_provider="github",
            oauth_id="dup-check-123",
            needs_setup=False,
            token_version=0,
        )
        with pytest.raises(ValueError, match="OAuth account already linked"):
            await repo.create_user(duplicate)

        # two plain-password accounts (NULL, NULL) must coexist without conflict
        plain_a = User(
            id=uuid.uuid4(),
            email="plain-a@example.com",
            password_hash="h",
            system_role="user",
            created_at=datetime.now(UTC),
            oauth_provider=None,
            oauth_id=None,
            needs_setup=False,
            token_version=0,
        )
        plain_b = User(
            id=uuid.uuid4(),
            email="plain-b@example.com",
            password_hash="h",
            system_role="user",
            created_at=datetime.now(UTC),
            oauth_provider=None,
            oauth_id=None,
            needs_setup=False,
            token_version=0,
        )
        await repo.create_user(plain_a)
        await repo.create_user(plain_b)  # must not raise
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await close_engine()
