"""Optional live PostgreSQL schema integration tests for issue #3380."""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_engine, init_engine_from_config
from deerflow.runtime.checkpointer.async_provider import make_checkpointer
from deerflow.runtime.checkpointer.provider import _sync_checkpointer_from_database
from deerflow.runtime.store.async_provider import make_store
from deerflow.runtime.store.provider import _sync_store_from_database


POSTGRES_URL = os.getenv("DEERFLOW_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set DEERFLOW_TEST_POSTGRES_URL to run live PostgreSQL schema integration tests",
)


@pytest.mark.anyio
async def test_postgres_schema_places_orm_checkpointer_and_store_tables_together():
    """Verify a real PostgreSQL backend places all persistence tables in one schema."""
    schema = f"deerflow_test_{uuid.uuid4().hex[:12]}"
    db_config = DatabaseConfig(backend="postgres", postgres_url=POSTGRES_URL or "", postgres_schema=schema)
    app_config = SimpleNamespace(checkpointer=None, database=db_config)

    await init_engine_from_config(db_config)
    engine = get_engine()
    assert engine is not None

    try:
        async with make_checkpointer(app_config) as checkpointer:
            assert checkpointer is not None
        async with make_store(app_config) as store:
            assert store is not None

        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT table_schema, table_name
                        FROM information_schema.tables
                        WHERE table_schema IN (:schema, 'public')
                        ORDER BY table_schema, table_name
                        """
                    ),
                    {"schema": schema},
                )
            ).all()

        by_schema = {(row.table_schema, row.table_name) for row in rows}
        orm_tables = {"runs", "run_events", "threads_meta", "feedback", "users"}
        assert {("public", table) for table in orm_tables}.isdisjoint(by_schema)
        assert {(schema, table) for table in orm_tables}.issubset(by_schema)
        assert any(table_schema == schema and "checkpoint" in table_name for table_schema, table_name in by_schema)
        assert any(table_schema == schema and ("store" in table_name or "migration" in table_name) for table_schema, table_name in by_schema)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await close_engine()


def test_sync_postgres_schema_places_checkpointer_and_store_tables_together():
    """Verify the sync (psycopg) path honours search_path via the DSN encoding.

    This exercises ``dsn_with_search_path`` against a real psycopg connection,
    guarding against regression of the ``%20`` vs ``+`` libpq encoding bug.
    """
    import psycopg

    schema = f"deerflow_test_{uuid.uuid4().hex[:12]}"
    db_config = DatabaseConfig(
        backend="postgres",
        postgres_url=POSTGRES_URL or "",
        postgres_schema=schema,
    )

    try:
        with _sync_checkpointer_from_database(db_config) as checkpointer:
            assert checkpointer is not None
        with _sync_store_from_database(db_config) as store:
            assert store is not None

        with psycopg.connect(POSTGRES_URL or "", autocommit=True) as conn:
            rows = conn.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema IN (%s, 'public')
                ORDER BY table_schema, table_name
                """,
                (schema,),
            ).fetchall()

        by_schema = {(table_schema, table_name) for table_schema, table_name in rows}
        assert any(
            table_schema == schema and "checkpoint" in table_name
            for table_schema, table_name in by_schema
        )
        assert any(
            table_schema == schema and ("store" in table_name or "migration" in table_name)
            for table_schema, table_name in by_schema
        )
        # The DeerFlow LangGraph tables must NOT leak into public.
        assert not any(
            table_schema == "public" and ("checkpoint" in table_name or table_name == "store")
            for table_schema, table_name in by_schema
        )
    finally:
        with psycopg.connect(POSTGRES_URL or "", autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
