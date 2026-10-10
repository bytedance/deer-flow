"""Migration 0037 adds the nullable project_documents.summary column and removes it again."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

REVISION = "0037_project_document_summaries"
PREVIOUS = "0036_run_idempotency_request"
CURRENT_HEAD = "0038_channel_thread_bindings"
pytestmark = pytest.mark.asyncio


async def test_0037_chains_after_0036_and_is_single_head():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(CURRENT_HEAD).down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    # alembic_version.version_num is VARCHAR(32).
    assert len(REVISION) <= 32


def _engine(tmp_path, backend):
    if backend == "sqlite":
        return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"), None
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres migration)")
    # Translate libpq sslmode to asyncpg ssl rather than dropping it: a URI
    # that requests verify-ca/verify-full must not silently fall back to an
    # unverified connection (tests/AGENTS.md "PostgreSQL batch fixtures").
    schema = f"doc_summaries_{uuid.uuid4().hex}"
    return create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema)), schema


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0037_upgrade_keeps_rows_and_downgrade_drops_summary(tmp_path, backend):
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO project_documents (id, project_id, user_id, name, stored_relpath, sha256, size_bytes, created_at, updated_at) "
                    "VALUES ('d1','p1','u1','notes.txt','u1/p1/d1-notes.txt','ab12',10,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )

        async def doc_columns():
            async with engine.connect() as conn:
                return await conn.run_sync(lambda sync: {col["name"]: col for col in sa.inspect(sync).get_columns("project_documents")})

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        columns = await doc_columns()
        assert columns["summary"]["nullable"] and columns["summary"]["default"] is None
        async with engine.connect() as conn:
            row = (await conn.execute(sa.text("SELECT name, size_bytes, summary FROM project_documents WHERE id='d1'"))).one()
        # No backfill: the pre-existing row keeps a NULL summary.
        assert tuple(row) == ("notes.txt", 10, None)

        async with engine.begin() as conn:
            await conn.execute(sa.text("UPDATE project_documents SET summary='one line' WHERE id='d1'"))
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert "summary" not in await doc_columns()
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT name, size_bytes FROM project_documents WHERE id='d1'"))).one() == ("notes.txt", 10)
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert "summary" in await doc_columns()
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


def test_postgres_uri_tls_policy_is_preserved(tmp_path, monkeypatch):
    """The fixture must translate, never drop, an explicit sslmode (tests/AGENTS.md)."""
    monkeypatch.setenv("TEST_POSTGRES_URI", "postgresql://u:p@db:5432/deerflow?sslmode=verify-full&channel_binding=require")
    captured = {}

    def capture_engine(url, **kwargs):
        captured["url"] = url
        raise RuntimeError("stop before database acquisition")

    monkeypatch.setitem(globals(), "create_async_engine", capture_engine)
    with pytest.raises(RuntimeError, match="stop before database acquisition"):
        _engine(tmp_path, "postgres")
    assert "ssl=verify-full" in captured["url"]
    assert "sslmode" not in captured["url"]
    assert "channel_binding" not in captured["url"]


def test_postgres_uri_conflicting_ssl_settings_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_POSTGRES_URI", "postgresql://u:p@db:5432/deerflow?sslmode=require&ssl=disable")
    monkeypatch.setitem(globals(), "create_async_engine", lambda *a, **k: None)
    with pytest.raises(ValueError, match="Conflicting ssl and sslmode"):
        _engine(tmp_path, "postgres")
