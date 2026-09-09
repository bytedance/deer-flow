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
from alembic import command as alembic_command
from alembic.util.exc import CommandError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import deerflow.persistence.models  # noqa: F401
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence import bootstrap as bootstrap_mod
from deerflow.persistence.bootstrap import (
    _CANONICAL_0019_SCHEMA_FLOOR,
    _FORWARD_COMPATIBLE_REVISION,
    _get_alembic_config,
    _upgrade,
    bootstrap_schema,
)
from deerflow.persistence.engine import close_engine, get_engine, init_engine_from_config
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository

CURRENT_HEAD = "0019_thread_incarnations"
# Tree head after the conversation-shares merge: the shares migration renumbered
# to 0022 and chains after the incarnations revision, so bootstrap_schema lands
# here while the forward-compat anchor stays pinned to CURRENT_HEAD above.
MERGED_HEAD = "0022_conversation_shares"
ROLLBACK_HEAD = "0020_threads_meta_project_id"
INCARNATION_PARENT = "0021_batch_acceptance"
ORIGINAL_INCARNATION_PARENT = "0018_oauth_identity_pg_partial"
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


async def _seed_current_head(engine) -> None:
    # bootstrap_schema now lands on the merged tree head (0022_conversation_shares);
    # these tests exercise the incarnations forward-compat window, so pin the
    # seed to that revision the same way _seed_rollback_head pins its own.
    cfg = _get_alembic_config(engine)
    await asyncio.to_thread(_upgrade, cfg, CURRENT_HEAD)
    assert await _database_revision(engine) == CURRENT_HEAD


async def _seed_rollback_head(engine) -> None:
    cfg = _get_alembic_config(engine)
    await asyncio.to_thread(_upgrade, cfg, ROLLBACK_HEAD)
    assert await _database_revision(engine) == ROLLBACK_HEAD


async def _seed_incarnation_parent(engine) -> None:
    cfg = _get_alembic_config(engine)
    await asyncio.to_thread(_upgrade, cfg, INCARNATION_PARENT)
    assert await _database_revision(engine) == INCARNATION_PARENT


async def _add_forward_columns(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text("ALTER TABLE threads_meta ADD COLUMN incarnation VARCHAR(32)"))
        await conn.execute(sa.text("ALTER TABLE mcp_tasks ADD COLUMN thread_incarnation VARCHAR(32)"))


def _simulate_rollback_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    current_head, current_revisions = bootstrap_mod._get_revision_metadata()
    # After the conversation-shares merge the tree head is 0022_conversation_shares,
    # while the forward-compat anchor stays pinned to the incarnations revision id.
    assert current_head == MERGED_HEAD
    assert CURRENT_HEAD == _FORWARD_COMPATIBLE_REVISION
    assert ROLLBACK_HEAD in current_revisions
    assert INCARNATION_PARENT in current_revisions
    assert CURRENT_HEAD in current_revisions
    monkeypatch.setattr(
        bootstrap_mod,
        "_get_revision_metadata",
        lambda: (ROLLBACK_HEAD, current_revisions - {INCARNATION_PARENT, CURRENT_HEAD}),
    )


async def _seed_original_forward_schema(engine) -> None:
    # The rollout predates projects: seeding today's head masks missing columns.
    await asyncio.to_thread(_upgrade, _get_alembic_config(engine), ORIGINAL_INCARNATION_PARENT)
    await _add_forward_columns(engine)
    await _set_database_revision(engine, _FORWARD_COMPATIBLE_REVISION)


@pytest.mark.asyncio
async def test_canonical_0019_floor_matches_migration_schema(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "canonical-floor.db"))
    try:
        await asyncio.to_thread(_upgrade, _get_alembic_config(engine), CURRENT_HEAD)
        async with engine.connect() as conn:

            def reflect(sync_conn):
                inspector = sa.inspect(sync_conn)
                return {table: frozenset(column["name"] for column in inspector.get_columns(table)) for table in inspector.get_table_names() if table != "alembic_version"}

            reflected = await conn.run_sync(reflect)
        assert reflected == _CANONICAL_0019_SCHEMA_FLOOR
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent", [False, True])
async def test_original_forward_schema_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, concurrent: bool) -> None:
    engine = create_async_engine(_url(tmp_path, "original-forward.db"))
    try:
        await _seed_original_forward_schema(engine)
        if concurrent:
            await _set_database_revision(engine, ORIGINAL_INCARNATION_PARENT)
            _simulate_rollback_binary(monkeypatch)

            def concurrent_upgrade(_cfg, _revision):
                asyncio.run(_set_database_revision(engine, _FORWARD_COMPATIBLE_REVISION))
                raise CommandError("revision advanced concurrently")

            monkeypatch.setattr(bootstrap_mod, "_upgrade", concurrent_upgrade)

        with pytest.raises(RuntimeError, match="missing.*projects.*threads_meta.project_id"):
            await bootstrap_schema(engine, backend="sqlite")

        assert await _database_revision(engine) == _FORWARD_COMPATIBLE_REVISION
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sync: sa.inspect(sync).get_table_names())
        assert "projects" not in tables
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ddl", "missing"),
    [
        ("DROP TABLE projects", "projects"),
        ("ALTER TABLE projects DROP COLUMN instructions", "projects.instructions"),
        ("ALTER TABLE threads_meta DROP COLUMN project_id", "threads_meta.project_id"),
        ("ALTER TABLE subagent_batch_items DROP COLUMN acceptance_criteria", "subagent_batch_items.acceptance_criteria"),
        ("ALTER TABLE subagent_batch_items DROP COLUMN acceptance_verdict", "subagent_batch_items.acceptance_verdict"),
        ("ALTER TABLE threads_meta DROP COLUMN incarnation", "threads_meta.incarnation"),
        ("ALTER TABLE mcp_tasks DROP COLUMN thread_incarnation", "mcp_tasks.thread_incarnation"),
    ],
)
async def test_current_incarnation_revision_rejects_incomplete_schema(tmp_path: Path, ddl: str, missing: str) -> None:
    engine = create_async_engine(_url(tmp_path, "partial-projects.db"))
    try:
        await _seed_incarnation_parent(engine)
        await _add_forward_columns(engine)
        async with engine.begin() as conn:
            if "DROP COLUMN project_id" in ddl:
                await conn.execute(sa.text("DROP INDEX ix_threads_meta_project_id"))
            await conn.execute(sa.text(ddl))
        await _set_database_revision(engine, _FORWARD_COMPATIBLE_REVISION)

        with pytest.raises(RuntimeError, match=f"missing required local schema: {missing};"):
            await bootstrap_schema(engine, backend="sqlite")
        assert await _database_revision(engine) == _FORWARD_COMPATIBLE_REVISION
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_audited_original_forward_schema_can_upgrade_preserving_incarnations(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "forward-recovery.db"))
    try:
        await _seed_original_forward_schema(engine)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO threads_meta (thread_id, status, metadata_json, created_at, updated_at, incarnation) VALUES ('existing', 'idle', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :incarnation)"),
                {"incarnation": "a" * 32},
            )

        # Documented offline operator recovery, only after verifying the exact
        # 0018 + two nullable columns shape. Bootstrap never re-stamps an unknown DB.
        await asyncio.to_thread(alembic_command.stamp, _get_alembic_config(engine), ORIGINAL_INCARNATION_PARENT, purge=True)
        await bootstrap_schema(engine, backend="sqlite")

        assert await _database_revision(engine) == MERGED_HEAD
        repository = ThreadMetaRepository(async_sessionmaker(engine, expire_on_commit=False))
        assert [row["thread_id"] for row in await repository.search(user_id=None)] == ["existing"]
        assert (await repository.create("new", user_id=None))["thread_id"] == "new"
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT incarnation FROM threads_meta WHERE thread_id = 'existing'"))).scalar_one() == "a" * 32
            columns = await conn.run_sync(lambda sync: sa.inspect(sync).get_columns("mcp_tasks"))
        assert "thread_incarnation" in {column["name"] for column in columns}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_known_canonical_0019_validates_fixed_floor_then_upgrades_to_future_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deerflow.persistence.base import Base

    engine = create_async_engine(_url(tmp_path, "future-head.db"))
    future_table = None
    calls: list[str] = []
    try:
        await _seed_current_head(engine)
        # Model a future binary whose ORM includes schema that only its next
        # migration can add. Canonical 0019 must not be rejected for lacking it.
        future_table = sa.Table("future_after_0019", Base.metadata, sa.Column("id", sa.String(), primary_key=True))
        current_revisions = bootstrap_mod._get_known_revisions()
        monkeypatch.setattr(
            bootstrap_mod,
            "_get_revision_metadata",
            lambda: ("0022_future", current_revisions | {"0022_future"}),
        )
        monkeypatch.setattr(bootstrap_mod, "_upgrade", lambda _cfg, revision: calls.append(revision))

        await bootstrap_schema(engine, backend="sqlite")

        assert calls == ["head"]
    finally:
        if future_table is not None:
            Base.metadata.remove(future_table)
        await engine.dispose()


@pytest.mark.asyncio
async def test_known_canonical_0019_rejects_missing_floor_before_future_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(_url(tmp_path, "future-head-missing-floor.db"))
    upgrade_called = False
    try:
        await _seed_original_forward_schema(engine)
        current_revisions = bootstrap_mod._get_known_revisions()
        monkeypatch.setattr(
            bootstrap_mod,
            "_get_revision_metadata",
            lambda: ("0022_future", current_revisions | {"0022_future"}),
        )

        def future_upgrade(_cfg, _revision):
            nonlocal upgrade_called
            upgrade_called = True

        monkeypatch.setattr(bootstrap_mod, "_upgrade", future_upgrade)

        with pytest.raises(RuntimeError, match="missing required local schema: projects"):
            await bootstrap_schema(engine, backend="sqlite")
        assert upgrade_called is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_known_older_revision_upgrades_normally(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "known.db"))
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(_upgrade, cfg, "0017_personal_access_tokens")

        await bootstrap_schema(engine, backend="sqlite")

        assert await _database_revision(engine) == MERGED_HEAD
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_exact_forward_revision_skips_upgrade_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_async_engine(_url(tmp_path, "forward.db"))
    try:
        await _seed_current_head(engine)
        _simulate_rollback_binary(monkeypatch)

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
        await _seed_current_head(engine)
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

    def delayed_old_upgrade(_cfg, revision):
        assert revision == "head"
        upgrade_started.set()
        if not continue_upgrade.wait(timeout=5):
            raise TimeoutError("timed out waiting for the forward migration")
        raise CommandError(f"Can't locate revision identified by '{CURRENT_HEAD}'")

    try:
        await _seed_rollback_head(old_gateway)
        _simulate_rollback_binary(monkeypatch)
        monkeypatch.setattr(bootstrap_mod, "_upgrade", delayed_old_upgrade)

        old_bootstrap = asyncio.create_task(bootstrap_schema(old_gateway, backend="sqlite"))
        assert await asyncio.to_thread(upgrade_started.wait, 5)

        new_cfg = _get_alembic_config(new_gateway)
        await asyncio.to_thread(_upgrade, new_cfg, CURRENT_HEAD)

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
        await _seed_rollback_head(engine)
        _simulate_rollback_binary(monkeypatch)

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
        await _seed_rollback_head(engine)

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
        await _seed_current_head(engine)
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
        await _seed_current_head(engine)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": "0017_personal_access_tokens"},
            )

        with pytest.raises(RuntimeError, match="expected exactly one alembic_version row, found 2"):
            await bootstrap_schema(engine, backend="sqlite")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rollback_batch_writer_tolerates_acceptance_columns(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "batch-repository.db"))
    try:
        await _seed_current_head(engine)
        old_items = sa.table(
            "subagent_batch_items",
            sa.column("id"),
            sa.column("batch_id"),
            sa.column("item_key"),
            sa.column("position", sa.Integer()),
            sa.column("prompt"),
            sa.column("status"),
            sa.column("attempt", sa.Integer()),
            sa.column("result"),
            sa.column("result_truncated", sa.Boolean()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        now = datetime.now(UTC)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO subagent_batches "
                    "(id, user_id, thread_id, submission_key, title, subagent_type, "
                    "status, total_items, max_live_items, max_running_items, "
                    "max_attempts, execution_spec, created_at, updated_at) "
                    "VALUES ('batch-1', 'user-1', 'thread-1', 'submission-1', "
                    "'Batch', 'general-purpose', 'queued', 1, 1, 1, 2, '{}', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            await conn.execute(
                old_items.insert().values(
                    id="item-1",
                    batch_id="batch-1",
                    item_key="item",
                    position=0,
                    prompt="Prompt",
                    status="queued",
                    attempt=0,
                    result=None,
                    result_truncated=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            fetched = (await conn.execute(sa.select(*old_items.c).where(old_items.c.id == "item-1"))).mappings().one()
            assert "acceptance_criteria" not in fetched
            assert "acceptance_verdict" not in fetched
            await conn.execute(old_items.update().where(old_items.c.id == "item-1").values(status="succeeded", result="legacy result", updated_at=now))

        async with engine.connect() as conn:
            row = (await conn.execute(sa.text("SELECT status, result, acceptance_criteria, acceptance_verdict FROM subagent_batch_items WHERE id = 'item-1'"))).one()
        assert row == ("succeeded", "legacy result", None, None)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rollback_thread_writer_tolerates_forward_nullable_column(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "thread-repository.db"))
    try:
        await _seed_current_head(engine)
        # This is the complete 0020 table shape. Keeping it independent from
        # the current ORM prevents a future model change from silently making
        # this rollback-writer test aware of the forward column.
        old_threads = sa.table(
            "threads_meta",
            sa.column("thread_id"),
            sa.column("assistant_id"),
            sa.column("user_id"),
            sa.column("display_name"),
            sa.column("status"),
            sa.column("metadata_json", sa.JSON()),
            sa.column("project_id"),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        now = datetime.now(UTC)
        async with engine.begin() as conn:
            await conn.execute(
                old_threads.insert().values(
                    thread_id="thread-1",
                    assistant_id=None,
                    user_id=None,
                    display_name=None,
                    status="idle",
                    metadata_json={},
                    created_at=now,
                    updated_at=now,
                )
            )

        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE threads_meta SET incarnation = :incarnation WHERE thread_id = :thread_id"),
                {"incarnation": "a" * 32, "thread_id": "thread-1"},
            )

            fetched = (await conn.execute(sa.select(*old_threads.c).where(old_threads.c.thread_id == "thread-1"))).mappings().one()
            assert fetched["thread_id"] == "thread-1"
            assert "incarnation" not in fetched
            await conn.execute(old_threads.update().where(old_threads.c.thread_id == "thread-1").values(status="busy", updated_at=datetime.now(UTC)))

        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.text("SELECT status, incarnation FROM threads_meta WHERE thread_id = :thread_id"),
                    {"thread_id": "thread-1"},
                )
            ).one()
        assert row == ("busy", "a" * 32)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rollback_shaped_mcp_task_sql_tolerates_forward_nullable_column(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path, "mcp-repository.db"))
    try:
        await _seed_current_head(engine)
        # This is the complete 0020 task table shape, deliberately excluding
        # only the forward thread_incarnation column.
        old_tasks = sa.table(
            "mcp_tasks",
            sa.column("id"),
            sa.column("user_id"),
            sa.column("thread_id"),
            sa.column("run_id"),
            sa.column("tool_call_id"),
            sa.column("server_name"),
            sa.column("driver_name"),
            sa.column("remote_task_id"),
            sa.column("task_name"),
            sa.column("status"),
            sa.column("result", sa.JSON()),
            sa.column("result_preview"),
            sa.column("result_truncated", sa.Boolean()),
            sa.column("result_artifact", sa.JSON()),
            sa.column("error"),
            sa.column("input_required", sa.JSON()),
            sa.column("driver_data", sa.JSON()),
            sa.column("notification_status"),
            sa.column("event_fingerprint"),
            sa.column("event_version", sa.Integer()),
            sa.column("notified_version", sa.Integer()),
            sa.column("dispatch_version", sa.Integer()),
            sa.column("dispatch_attempt", sa.Integer()),
            sa.column("dispatch_event", sa.JSON()),
            sa.column("notification_run_id"),
            sa.column("notification_error"),
            sa.column("notification_attempt_count", sa.Integer()),
            sa.column("next_notification_at", sa.DateTime(timezone=True)),
            sa.column("notification_lease_owner"),
            sa.column("notification_lease_expires_at", sa.DateTime(timezone=True)),
            sa.column("next_poll_at", sa.DateTime(timezone=True)),
            sa.column("last_polled_at", sa.DateTime(timezone=True)),
            sa.column("last_poll_error"),
            sa.column("poll_attempt_count", sa.Integer()),
            sa.column("consecutive_poll_error_count", sa.Integer()),
            sa.column("lease_owner"),
            sa.column("lease_expires_at", sa.DateTime(timezone=True)),
            sa.column("cancel_requested_at", sa.DateTime(timezone=True)),
            sa.column("cancel_attempt_count", sa.Integer()),
            sa.column("next_cancel_at", sa.DateTime(timezone=True)),
            sa.column("last_cancel_error"),
            sa.column("completed_at", sa.DateTime(timezone=True)),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        now = datetime.now(UTC)

        async with engine.begin() as conn:
            await conn.execute(
                old_tasks.insert().values(
                    id="task-1",
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
                    error=None,
                    input_required=None,
                    driver_data={},
                    notification_status="none",
                    next_poll_at=now - timedelta(seconds=1),
                    last_polled_at=None,
                    last_poll_error=None,
                    poll_attempt_count=0,
                    consecutive_poll_error_count=0,
                    lease_owner=None,
                    lease_expires_at=None,
                    cancel_requested_at=None,
                    completed_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )

        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE mcp_tasks SET thread_incarnation = :incarnation WHERE id = :task_id"),
                {"incarnation": "b" * 32, "task_id": "task-1"},
            )

            fetched = (
                (
                    await conn.execute(
                        sa.select(*old_tasks.c).where(
                            old_tasks.c.id == "task-1",
                            old_tasks.c.user_id == "user-1",
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert fetched["id"] == "task-1"
            assert "thread_incarnation" not in fetched
            await conn.execute(
                old_tasks.update()
                .where(
                    old_tasks.c.id == "task-1",
                    old_tasks.c.status == "working",
                    old_tasks.c.next_poll_at <= now,
                )
                .values(
                    lease_owner="worker-1",
                    lease_expires_at=now + timedelta(seconds=60),
                    poll_attempt_count=old_tasks.c.poll_attempt_count + 1,
                    updated_at=now,
                )
            )

        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.text("SELECT lease_owner, poll_attempt_count, thread_incarnation FROM mcp_tasks WHERE id = :task_id"),
                    {"task_id": "task-1"},
                )
            ).one()
        assert row == ("worker-1", 1, "b" * 32)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(not POSTGRES_URL, reason="requires TEST_POSTGRES_URI for a real PostgreSQL restart")
async def test_old_gateway_restarts_against_forward_postgres_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        assert await _database_revision(engine) == MERGED_HEAD

        await close_engine()
        _simulate_rollback_binary(monkeypatch)
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
