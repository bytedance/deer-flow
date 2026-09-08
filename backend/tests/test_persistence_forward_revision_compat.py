"""Forward-compatibility tests for an old Gateway against migration 0019."""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from alembic.util.exc import CommandError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import deerflow.persistence.models  # noqa: F401
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence import bootstrap as bootstrap_mod
from deerflow.persistence.bootstrap import (
    _FORWARD_COMPATIBLE_REVISION,
    _get_alembic_config,
    _upgrade,
    bootstrap_schema,
)
from deerflow.persistence.engine import close_engine, get_engine, init_engine_from_config
from deerflow.persistence.mcp_tasks import McpTaskRepository
from deerflow.persistence.thread_meta import ThreadMetaRepository

HEAD = "0018_oauth_identity_pg_partial"
POSTGRES_URL = os.environ.get("TEST_POSTGRES_URI")


def _url(tmp_path: Path, name: str) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / name).as_posix()}"


def _postgres_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
    return urlunsplit(parts._replace(query=query))


async def _database_revision(engine) -> str | None:
    async with engine.connect() as conn:
        result = await conn.execute(sa.text("SELECT version_num FROM alembic_version"))
        return result.scalar_one_or_none()


async def _set_database_revision(engine, revision: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text("UPDATE alembic_version SET version_num = :revision"), {"revision": revision})


async def _seed_head(engine) -> None:
    await bootstrap_schema(engine, backend="sqlite")
    assert await _database_revision(engine) == HEAD


@pytest.mark.asyncio
async def test_known_older_revision_upgrades_normally(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "known.db"))
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(_upgrade, cfg, "0017_personal_access_tokens")

        await bootstrap_schema(engine, backend="sqlite")

        assert await _database_revision(engine) == HEAD
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_exact_forward_revision_skips_upgrade_with_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_async_engine(_url(tmp_path, "forward.db"))
    try:
        await _seed_head(engine)
        await _set_database_revision(engine, _FORWARD_COMPATIBLE_REVISION)

        with caplog.at_level("WARNING", logger="deerflow.persistence.bootstrap"):
            await bootstrap_schema(engine, backend="sqlite")

        assert await _database_revision(engine) == _FORWARD_COMPATIBLE_REVISION
        assert any(_FORWARD_COMPATIBLE_REVISION in record.getMessage() and "explicitly forward-compatible" in record.getMessage() for record in caplog.records)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_other_unknown_revision_fails_closed(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "unknown.db"))
    try:
        await _seed_head(engine)
        await _set_database_revision(engine, "9999_unknown")

        with pytest.raises(RuntimeError, match="not known to this build"):
            await bootstrap_schema(engine, backend="sqlite")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_upgrade_race_recovers_when_other_process_applies_forward_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    url = _url(tmp_path, "forward-race.db")
    old_gateway = create_async_engine(url)
    new_gateway = create_async_engine(url)
    upgrade_started = threading.Event()
    continue_upgrade = threading.Event()
    original_upgrade = bootstrap_mod._upgrade

    def delayed_upgrade(cfg, revision):
        upgrade_started.set()
        if not continue_upgrade.wait(timeout=5):
            raise TimeoutError("timed out waiting for the forward migration")
        return original_upgrade(cfg, revision)

    try:
        await _seed_head(old_gateway)
        monkeypatch.setattr(bootstrap_mod, "_upgrade", delayed_upgrade)

        old_bootstrap = asyncio.create_task(bootstrap_schema(old_gateway, backend="sqlite"))
        assert await asyncio.to_thread(upgrade_started.wait, 5)

        await _add_forward_columns(new_gateway)
        await _set_database_revision(new_gateway, _FORWARD_COMPATIBLE_REVISION)

        with caplog.at_level("WARNING", logger="deerflow.persistence.bootstrap"):
            continue_upgrade.set()
            await old_bootstrap
        assert await _database_revision(old_gateway) == _FORWARD_COMPATIBLE_REVISION
        assert any("advanced concurrently" in record.getMessage() and _FORWARD_COMPATIBLE_REVISION in record.getMessage() for record in caplog.records)
    finally:
        continue_upgrade.set()
        await old_gateway.dispose()
        await new_gateway.dispose()


@pytest.mark.asyncio
async def test_sqlite_upgrade_error_stays_fatal_without_forward_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(_url(tmp_path, "upgrade-error.db"))
    try:
        await _seed_head(engine)

        def fail_upgrade(_cfg, _revision):
            raise CommandError("broken migration")

        monkeypatch.setattr(bootstrap_mod, "_upgrade", fail_upgrade)
        with pytest.raises(CommandError, match="broken migration"):
            await bootstrap_schema(engine, backend="sqlite")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_local_forward_migration_error_stays_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(_url(tmp_path, "local-forward-error.db"))
    try:
        await _seed_head(engine)
        monkeypatch.setattr(
            bootstrap_mod,
            "_get_revision_metadata",
            lambda: (_FORWARD_COMPATIBLE_REVISION, frozenset({HEAD, _FORWARD_COMPATIBLE_REVISION})),
        )

        def fail_upgrade(_cfg, _revision):
            raise CommandError("local 0019 migration failed")

        monkeypatch.setattr(bootstrap_mod, "_upgrade", fail_upgrade)
        with pytest.raises(CommandError, match="local 0019 migration failed"):
            await bootstrap_schema(engine, backend="sqlite")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_empty_alembic_version_fails_closed(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "empty-version.db"))
    try:
        await _seed_head(engine)
        async with engine.begin() as conn:
            await conn.execute(sa.text("DELETE FROM alembic_version"))

        with pytest.raises(RuntimeError, match="expected exactly one alembic_version row, found 0"):
            await bootstrap_schema(engine, backend="sqlite")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_multiple_alembic_versions_fail_closed(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "multiple-versions.db"))
    try:
        await _seed_head(engine)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": "0017_personal_access_tokens"},
            )

        with pytest.raises(RuntimeError, match="expected exactly one alembic_version row, found 2"):
            await bootstrap_schema(engine, backend="sqlite")
    finally:
        await engine.dispose()


async def _add_forward_columns(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text("ALTER TABLE threads_meta ADD COLUMN incarnation VARCHAR(32)"))
        await conn.execute(sa.text("ALTER TABLE mcp_tasks ADD COLUMN thread_incarnation VARCHAR(32)"))


@pytest.mark.asyncio
async def test_old_thread_repository_tolerates_forward_nullable_column(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "thread-repository.db"))
    try:
        await _seed_head(engine)
        await _add_forward_columns(engine)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        repository = ThreadMetaRepository(session_factory)

        created = await repository.create("thread-1", user_id=None)
        assert created["thread_id"] == "thread-1"
        assert "incarnation" not in created

        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE threads_meta SET incarnation = :incarnation WHERE thread_id = :thread_id"),
                {"incarnation": "a" * 32, "thread_id": "thread-1"},
            )

        fetched = await repository.get("thread-1", user_id=None)
        assert fetched is not None
        assert "incarnation" not in fetched
        await repository.update_status("thread-1", "busy", user_id=None)

        async with engine.connect() as conn:
            incarnation = (
                await conn.execute(
                    sa.text("SELECT incarnation FROM threads_meta WHERE thread_id = :thread_id"),
                    {"thread_id": "thread-1"},
                )
            ).scalar_one()
        assert incarnation == "a" * 32
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_old_mcp_task_repository_tolerates_forward_nullable_column(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "mcp-repository.db"))
    try:
        await _seed_head(engine)
        await _add_forward_columns(engine)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        repository = McpTaskRepository(session_factory)
        now = datetime.now(UTC)

        created = await repository.create(
            task_id="task-1",
            user_id="user-1",
            thread_id="thread-1",
            run_id="run-1",
            tool_call_id="call-1",
            server_name="reports",
            driver_name="fake",
            remote_task_id="remote-1",
            task_name="Generate report",
            status="working",
            result=None,
            result_preview=None,
            result_truncated=False,
            result_artifact=None,
            error=None,
            input_required=None,
            next_poll_at=now - timedelta(seconds=1),
        )
        assert created["id"] == "task-1"
        assert "thread_incarnation" not in created

        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE mcp_tasks SET thread_incarnation = :incarnation WHERE id = :task_id"),
                {"incarnation": "b" * 32, "task_id": "task-1"},
            )

        fetched = await repository.get("task-1", user_id="user-1")
        assert fetched is not None
        assert "thread_incarnation" not in fetched
        claimed = await repository.claim_due_tasks(
            now=now,
            lease_owner="worker-1",
            lease_seconds=60,
            limit=1,
        )
        assert [task["id"] for task in claimed] == ["task-1"]

        async with engine.connect() as conn:
            incarnation = (
                await conn.execute(
                    sa.text("SELECT thread_incarnation FROM mcp_tasks WHERE id = :task_id"),
                    {"task_id": "task-1"},
                )
            ).scalar_one()
        assert incarnation == "b" * 32
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(not POSTGRES_URL, reason="requires TEST_POSTGRES_URI for a real PostgreSQL restart")
async def test_old_gateway_restarts_against_forward_postgres_revision() -> None:
    assert POSTGRES_URL is not None
    schema = f"forward_revision_{uuid.uuid4().hex}"
    config = DatabaseConfig(
        backend="postgres",
        postgres_url=_postgres_url(POSTGRES_URL),
        postgres_schema=schema,
    )
    try:
        await init_engine_from_config(config)
        engine = get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            await conn.execute(sa.text("ALTER TABLE threads_meta ADD COLUMN incarnation VARCHAR(32)"))
            await conn.execute(sa.text("ALTER TABLE mcp_tasks ADD COLUMN thread_incarnation VARCHAR(32)"))
            await conn.execute(
                sa.text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": _FORWARD_COMPATIBLE_REVISION},
            )

        await close_engine()
        await init_engine_from_config(config)

        restarted_engine = get_engine()
        assert restarted_engine is not None
        assert await _database_revision(restarted_engine) == _FORWARD_COMPATIBLE_REVISION
    finally:
        engine = get_engine()
        if engine is not None:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await close_engine()
