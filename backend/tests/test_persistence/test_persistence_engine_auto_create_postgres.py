"""Live PostgreSQL checks for init_engine's missing-database auto-create.

Opt in with DEERFLOW_TEST_POSTGRES_URL or TEST_POSTGRES_URI (set by the
backend unit-test CI job). The role must be allowed to create databases.
"""

from __future__ import annotations

import os
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import engine as engine_mod


def _asyncpg_url(url: str | None) -> str | None:
    if not url:
        return url
    parts = urlsplit(url)
    scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
    return urlunsplit(parts._replace(scheme=scheme, query=query))


POSTGRES_URL = _asyncpg_url(os.getenv("DEERFLOW_TEST_POSTGRES_URL") or os.getenv("TEST_POSTGRES_URI"))

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not POSTGRES_URL, reason="set DEERFLOW_TEST_POSTGRES_URL or TEST_POSTGRES_URI to run live PostgreSQL tests"),
]


async def _execute_on_server(*statements: str, database: str | None = None) -> None:
    url = make_url(POSTGRES_URL or "")
    if database is not None:
        url = url.set(database=database)
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def missing_database():
    name = f"deerflow_autocreate_{uuid.uuid4().hex[:12]}"
    url = make_url(POSTGRES_URL or "").set(database=name).render_as_string(hide_password=False)
    try:
        yield name, url
    finally:
        await engine_mod.close_engine()
        await _execute_on_server(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


async def test_missing_database_is_created_and_bootstrapped(missing_database) -> None:
    name, url = missing_database

    await engine_mod.init_engine("postgres", url=url)

    async with engine_mod.get_engine().connect() as conn:
        assert (await conn.execute(text("SELECT current_database()"))).scalar_one() == name
        assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()


async def test_bootstrap_failure_in_an_existing_database_is_not_masked(missing_database) -> None:
    name, url = missing_database
    await engine_mod.init_engine("postgres", url=url)
    await engine_mod.close_engine()
    # Leave an unguarded migration statement to fail: rewind to 0012 and drop
    # the column 0013's backfill UPDATE reads.
    await _execute_on_server(
        "UPDATE alembic_version SET version_num = '0012_mcp_task_results'",
        "ALTER TABLE mcp_tasks DROP COLUMN updated_at CASCADE",
        database=name,
    )

    with pytest.raises(Exception) as raised:
        await engine_mod.init_engine("postgres", url=url)

    # Before the fix, this tried CREATE DATABASE and raised DuplicateDatabaseError.
    sqlstates = []
    error: BaseException | None = raised.value
    while error is not None:
        sqlstates.append(getattr(error, "sqlstate", None))
        error = error.__cause__
    assert "42703" in sqlstates, raised.value
