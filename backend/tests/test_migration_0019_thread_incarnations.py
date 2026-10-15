from __future__ import annotations

import asyncio
import importlib
import os
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateTable

from deerflow.persistence.bootstrap import _FORWARD_COMPATIBLE_REVISION, _get_alembic_config

_PREVIOUS = "0021_batch_acceptance"
_REVISION = "0019_thread_incarnations"
_MIGRATION_MODULE = "deerflow.persistence.migrations.versions.0019_thread_incarnations"


def _asyncpg_url(url: str | None) -> str | None:
    if not url:
        return url
    parts = urlsplit(url)
    scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
    return urlunsplit(parts._replace(scheme=scheme, query=query))


_POSTGRES_URL = _asyncpg_url(os.getenv("DEERFLOW_TEST_POSTGRES_URL") or os.getenv("TEST_POSTGRES_URI"))


def test_0019_matches_reviewed_rollback_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = importlib.import_module(_MIGRATION_MODULE)
    events: list[tuple[str, str, str, int | None, bool, object]] = []

    def capture_preflight(table: str, column_name: str) -> None:
        events.append(("preflight", table, column_name, None, True, None))

    def capture_add(table: str, column: sa.Column) -> None:
        assert isinstance(column.type, sa.VARCHAR)
        events.append(("add", table, str(column.name), column.type.length, bool(column.nullable), column.server_default))

    class NoAdditionalOperations:
        def __getattr__(self, name: str):
            raise AssertionError(f"0019 rollback contract does not allow direct Alembic operation: {name}")

    monkeypatch.setattr(migration, "_assert_existing_column_compatible", capture_preflight)
    monkeypatch.setattr(migration, "safe_add_column", capture_add)
    monkeypatch.setattr(migration, "op", NoAdditionalOperations())

    migration.upgrade()

    assert migration.revision == _FORWARD_COMPATIBLE_REVISION == _REVISION
    assert migration.down_revision == _PREVIOUS
    assert events == [
        ("preflight", "threads_meta", "incarnation", None, True, None),
        ("preflight", "mcp_tasks", "thread_incarnation", None, True, None),
        ("add", "threads_meta", "incarnation", 32, True, None),
        ("add", "mcp_tasks", "thread_incarnation", 32, True, None),
    ]


@pytest.mark.asyncio
async def test_sqlite_0019_adds_and_drops_nullable_columns(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = _get_alembic_config(engine)
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, _PREVIOUS)
        await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)

        async with engine.connect() as conn:
            thread_columns = {column["name"]: column for column in await conn.run_sync(lambda sync: sa.inspect(sync).get_columns("threads_meta"))}
            task_columns = {column["name"]: column for column in await conn.run_sync(lambda sync: sa.inspect(sync).get_columns("mcp_tasks"))}
            version = await conn.scalar(sa.text("SELECT version_num FROM alembic_version"))

        assert version == _REVISION
        assert thread_columns["incarnation"]["nullable"] is True
        assert task_columns["thread_incarnation"]["nullable"] is True

        await asyncio.to_thread(alembic_command.downgrade, cfg, _PREVIOUS)
        async with engine.connect() as conn:
            thread_columns = {column["name"] for column in await conn.run_sync(lambda sync: sa.inspect(sync).get_columns("threads_meta"))}
            task_columns = {column["name"] for column in await conn.run_sync(lambda sync: sa.inspect(sync).get_columns("mcp_tasks"))}
        assert "incarnation" not in thread_columns
        assert "thread_incarnation" not in task_columns
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_0019_round_trip_preserves_parent_schema_data(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'projects.db'}")
    cfg = _get_alembic_config(engine)
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, _PREVIOUS)
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO projects "
                    "(id, user_id, name, instructions, presentation, status, created_at, updated_at) "
                    "VALUES ('project-1', 'user-1', 'Project', 'Keep me', "
                    "'{\"theme\":\"dark\"}', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            await connection.execute(
                sa.text("INSERT INTO threads_meta (thread_id, user_id, status, metadata_json, project_id, created_at, updated_at) VALUES ('thread-1', 'user-1', 'idle', '{}', 'project-1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO subagent_batches "
                    "(id, user_id, thread_id, submission_key, title, subagent_type, "
                    "status, total_items, max_live_items, max_running_items, "
                    "max_attempts, execution_spec, created_at, updated_at) "
                    "VALUES ('batch-1', 'user-1', 'thread-1', 'submission-1', "
                    "'Batch', 'general-purpose', 'completed', 1, 1, 1, 2, '{}', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO subagent_batch_items "
                    "(id, batch_id, item_key, position, prompt, acceptance_criteria, "
                    "acceptance_verdict, status, attempt, result_truncated, created_at, updated_at) "
                    "VALUES ('item-1', 'batch-1', 'item', 0, 'Prompt', "
                    ":criteria, :verdict, 'succeeded', 1, 0, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "criteria": '["must pass"]',
                    "verdict": '{"passed":true}',
                },
            )

        async def assert_preserved(*, incarnation_columns: bool) -> None:
            async with engine.connect() as connection:
                project = (await connection.execute(sa.text("SELECT id, user_id, name, instructions, presentation, status FROM projects WHERE id = 'project-1'"))).one()
                membership = await connection.scalar(sa.text("SELECT project_id FROM threads_meta WHERE thread_id = 'thread-1'"))
                indexes = {index["name"] for index in await connection.run_sync(lambda sync: sa.inspect(sync).get_indexes("threads_meta"))}
                thread_columns = {column["name"] for column in await connection.run_sync(lambda sync: sa.inspect(sync).get_columns("threads_meta"))}
                task_columns = {column["name"] for column in await connection.run_sync(lambda sync: sa.inspect(sync).get_columns("mcp_tasks"))}
                acceptance = (await connection.execute(sa.text("SELECT json_extract(acceptance_criteria, '$[0]'), json_extract(acceptance_verdict, '$.passed') FROM subagent_batch_items WHERE id = 'item-1'"))).one()

            assert tuple(project[:4]) == ("project-1", "user-1", "Project", "Keep me")
            assert project.status == "active"
            assert '"theme"' in str(project.presentation) and '"dark"' in str(project.presentation)
            assert membership == "project-1"
            assert tuple(acceptance) == ("must pass", 1)
            assert "ix_threads_meta_project_id" in indexes
            assert ("incarnation" in thread_columns) is incarnation_columns
            assert ("thread_incarnation" in task_columns) is incarnation_columns

        await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)
        await assert_preserved(incarnation_columns=True)

        await asyncio.to_thread(alembic_command.downgrade, cfg, _PREVIOUS)
        await assert_preserved(incarnation_columns=False)

        await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)
        await assert_preserved(incarnation_columns=True)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_0019_reapply_does_not_report_varchar_drift(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = _get_alembic_config(engine)
    migration = importlib.import_module(_MIGRATION_MODULE)
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)

        def reapply(sync_connection) -> None:
            context = MigrationContext.configure(sync_connection)
            with Operations.context(context):
                migration.upgrade()

        with caplog.at_level("WARNING", logger="deerflow.persistence.migrations._helpers"):
            async with engine.begin() as connection:
                await connection.run_sync(reapply)

        assert "drifts from the model definition" not in caplog.text
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "column_sql",
    [
        "VARCHAR(16) NULL",
        "TEXT NULL",
        'VARCHAR(32) NOT NULL DEFAULT "legacy"',
        "VARCHAR(32) NULL DEFAULT 'legacy'",
    ],
)
async def test_sqlite_0019_fails_fast_on_incompatible_existing_column(tmp_path: Path, column_sql: str) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = _get_alembic_config(engine)
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, _PREVIOUS)
        async with engine.begin() as connection:
            await connection.execute(sa.text(f"ALTER TABLE mcp_tasks ADD COLUMN thread_incarnation {column_sql}"))

        with pytest.raises(RuntimeError, match="with no default or DEFAULT NULL"):
            await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)

        async with engine.connect() as connection:
            version = await connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            thread_columns = {column["name"] for column in await connection.run_sync(lambda sync: sa.inspect(sync).get_columns("threads_meta"))}
        assert version == _PREVIOUS
        assert "incarnation" not in thread_columns
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_0019_accepts_wider_nullable_varchar(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = _get_alembic_config(engine)
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, _PREVIOUS)
        async with engine.begin() as connection:
            await connection.execute(sa.text("ALTER TABLE mcp_tasks ADD COLUMN thread_incarnation VARCHAR(64) NULL"))

        await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)

        async with engine.connect() as connection:
            columns = {column["name"]: column for column in await connection.run_sync(lambda sync: sa.inspect(sync).get_columns("mcp_tasks"))}
        assert columns["thread_incarnation"]["type"].length == 64
        assert columns["thread_incarnation"]["nullable"] is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_0019_accepts_default_null_and_legacy_writer_omission(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = _get_alembic_config(engine)
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, _PREVIOUS)
        async with engine.begin() as connection:
            await connection.execute(sa.text("ALTER TABLE threads_meta ADD COLUMN incarnation VARCHAR(32) NULL DEFAULT NULL"))

        await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)

        async with engine.begin() as connection:
            await connection.execute(sa.text("INSERT INTO threads_meta (thread_id, status, metadata_json, created_at, updated_at) VALUES ('legacy-writer', 'idle', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            incarnation = await connection.scalar(sa.text("SELECT incarnation FROM threads_meta WHERE thread_id = 'legacy-writer'"))
        assert incarnation is None
    finally:
        await engine.dispose()


def test_postgresql_0019_column_ddl_compiles_without_value_default() -> None:
    table = sa.Table(
        "incarnation_compile_check",
        sa.MetaData(),
        sa.Column("incarnation", sa.VARCHAR(length=32), nullable=True),
    )

    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))

    assert "incarnation VARCHAR(32)" in ddl
    assert "DEFAULT" not in ddl


def test_postgresql_reflected_default_null_cast_is_semantically_null() -> None:
    migration = importlib.import_module(_MIGRATION_MODULE)

    assert migration._is_null_server_default("NULL::character varying") is True
    assert migration._is_null_server_default("(NULL)::character varying") is True
    assert migration._is_null_server_default("'legacy'::character varying") is False
    assert migration._is_null_server_default("NULL::integer IS NULL") is False


def test_postgresql_ci_url_is_normalized_for_asyncpg() -> None:
    assert _asyncpg_url("postgresql://user:pass@localhost/db?sslmode=disable") == "postgresql+asyncpg://user:pass@localhost/db"


@pytest.mark.asyncio
@pytest.mark.skipif(not _POSTGRES_URL, reason="set TEST_POSTGRES_URI or DEERFLOW_TEST_POSTGRES_URL to run live PostgreSQL tests")
async def test_postgresql_0019_accepts_default_null_and_legacy_writer_omission() -> None:
    schema = f"deerflow_0019_{uuid.uuid4().hex[:12]}"
    engine = create_async_engine(_POSTGRES_URL or "")
    cfg = _get_alembic_config(engine, postgres_schema=schema)
    try:
        async with engine.begin() as connection:
            await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(alembic_command.upgrade, cfg, _PREVIOUS)
        async with engine.begin() as connection:
            await connection.execute(sa.text(f'ALTER TABLE "{schema}".threads_meta ADD COLUMN incarnation VARCHAR(32) NULL DEFAULT NULL'))

        await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)

        async with engine.begin() as connection:
            await connection.execute(sa.text(f"INSERT INTO \"{schema}\".threads_meta (thread_id, status, metadata_json, created_at, updated_at) VALUES ('legacy-writer', 'idle', '{{}}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            incarnation = await connection.scalar(sa.text(f"SELECT incarnation FROM \"{schema}\".threads_meta WHERE thread_id = 'legacy-writer'"))
        assert incarnation is None
    finally:
        async with engine.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_0019_downgrade_retry_cleans_failed_batch_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = _get_alembic_config(engine)
    migration = importlib.import_module(_MIGRATION_MODULE)
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)

        def fail_then_retry(sync_connection) -> None:
            context = MigrationContext.configure(sync_connection)
            original_safe_drop = migration.safe_drop_column
            injected = False

            def fail_after_batch_temp_create(table: str, column_name: str) -> None:
                nonlocal injected
                if table == "mcp_tasks" and not injected:
                    injected = True
                    sync_connection.exec_driver_sql("CREATE TABLE _alembic_tmp_mcp_tasks AS SELECT * FROM mcp_tasks")
                    raise RuntimeError("injected batch downgrade failure")
                original_safe_drop(table, column_name)

            with Operations.context(context):
                monkeypatch.setattr(migration, "safe_drop_column", fail_after_batch_temp_create)
                with pytest.raises(RuntimeError, match="injected"):
                    migration.downgrade()
                sync_connection.commit()

                monkeypatch.setattr(migration, "safe_drop_column", original_safe_drop)
                migration.downgrade()
                sync_connection.commit()

            tables = set(sa.inspect(sync_connection).get_table_names())
            assert "_alembic_tmp_mcp_tasks" not in tables
            assert "thread_incarnation" not in {column["name"] for column in sa.inspect(sync_connection).get_columns("mcp_tasks")}
            assert "incarnation" not in {column["name"] for column in sa.inspect(sync_connection).get_columns("threads_meta")}

        async with engine.connect() as connection:
            await connection.run_sync(fail_then_retry)
    finally:
        await engine.dispose()
