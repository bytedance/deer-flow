"""Exercise the published pre-#5405 migration graph, not a new-schema stamp."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.bootstrap import _MIGRATIONS_DIR, _get_alembic_config, bootstrap_schema
from deerflow.persistence.run import RunRepository

pytestmark = pytest.mark.asyncio
PREVIOUS = "0024_project_documents"


def _historical_config(engine, tmp_path):
    """Reconstruct the two published descendants before their ancestor changed."""
    target = tmp_path / "historical_migrations"
    shutil.copytree(_MIGRATIONS_DIR, target)
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    historical_files = {Path(revision.path).name for revision in script.walk_revisions(base="base", head=PREVIOUS) if revision.revision != "0023_run_change_seq"}
    for path in (target / "versions").glob("*.py"):
        if path.name not in historical_files:
            path.unlink()
    preferences = target / "versions" / "0023_user_preferences.py"
    text = preferences.read_text(encoding="utf-8")
    expected_parent = 'down_revision = "0023_run_change_seq"'
    assert expected_parent in text, f"{preferences.name}: expected {expected_parent!r}; update the historical migration rewrite"
    historical_text = text.replace(expected_parent, 'down_revision = "0022_scheduled_occurrence_seq"')
    assert historical_text != text, f"{preferences.name}: historical migration rewrite did not change the parent revision"
    preferences.write_text(historical_text, encoding="utf-8")
    cfg = _get_alembic_config(engine)
    cfg.set_main_option("script_location", str(target))
    return cfg


async def _assert_schema(engine):
    async with engine.connect() as connection:

        def inspect(conn):
            inspector = sa.inspect(conn)
            assert inspector.has_table("run_change_clock")
            assert "change_seq" in {column["name"] for column in inspector.get_columns("runs")}
            indexes = {index["name"]: index["column_names"] for index in inspector.get_indexes("runs")}
            assert indexes["ix_runs_change_seq"] == ["change_seq", "run_id"]
            assert indexes["ix_runs_user_change_seq"] == ["user_id", "change_seq", "run_id"]

        await connection.run_sync(inspect)


@pytest.mark.parametrize("revision", ["0023_user_preferences", PREVIOUS])
async def test_startup_repairs_skipped_ancestor_and_allows_thread_delete(tmp_path, revision):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'historical.db'}")
    try:
        await asyncio.to_thread(command.upgrade, _historical_config(engine, tmp_path), revision)
        async with engine.begin() as connection:
            assert not await connection.run_sync(lambda conn: sa.inspect(conn).has_table("run_change_clock"))
            await connection.execute(
                sa.text(
                    "INSERT INTO runs (run_id, thread_id, user_id, status, operation_kind, metadata_json, kwargs_json, "
                    "multitask_strategy, message_count, total_input_tokens, total_output_tokens, total_tokens, llm_call_count, "
                    "lead_agent_tokens, subagent_tokens, middleware_tokens, created_at, updated_at) "
                    "VALUES ('legacy', 'legacy-thread', 'user-1', 'success', 'run', '{}', '{}', 'reject', "
                    "0, 0, 0, 0, 0, 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
        await bootstrap_schema(engine, backend="sqlite")
        await _assert_schema(engine)
        repo = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        legacy = await repo.list_changed(after_change_seq=-1, after_run_id="", user_id="user-1", limit=10)
        assert [(row["run_id"], row["change_seq"]) for row in legacy] == [("legacy", 0)]
        operation, _ = await repo.create_thread_operation_atomic("delete-op", thread_id="legacy-thread", user_id="user-1", owner_worker_id="worker", lease_expires_at=None, operation_kind="thread_delete")
        assert operation["change_seq"] > 0
        assert await repo.update_status("delete-op", "success")
        async with engine.connect() as connection:
            assert await connection.scalar(sa.text("SELECT change_seq FROM runs WHERE run_id = 'delete-op'")) > operation["change_seq"]
    finally:
        await engine.dispose()


async def test_repair_preserves_clock_and_downgrade_keeps_ancestor_schema(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'healthy.db'}")
    cfg = _get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        repo = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        await repo.put("existing", thread_id="existing-thread", user_id="user-1", status="pending")
        async with engine.begin() as connection:
            await connection.execute(sa.text("UPDATE runs SET change_seq = 37"))
            await connection.execute(sa.text("UPDATE run_change_clock SET value = 100 WHERE id = 1"))
        await bootstrap_schema(engine, backend="sqlite")
        await bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as connection:
            assert await connection.scalar(sa.text("SELECT value FROM run_change_clock WHERE id = 1")) == 100
            assert await connection.scalar(sa.text("SELECT change_seq FROM runs WHERE run_id = 'existing'")) == 37
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        await _assert_schema(engine)
        # The previous application's run store must remain usable before any
        # re-upgrade; a schema-only assertion would miss sequence resets.
        assert await repo.start_run("existing")
        async with engine.connect() as connection:
            assert await connection.scalar(sa.text("SELECT change_seq FROM runs WHERE run_id = 'existing'")) == 101
        await asyncio.to_thread(command.upgrade, cfg, "head")
        await repo.update_status("existing", "error")
        changed = await repo.list_changed(after_change_seq=100, after_run_id="", user_id="user-1", limit=10)
        assert [(row["run_id"], row["change_seq"]) for row in changed] == [("existing", 102)]
    finally:
        await engine.dispose()
