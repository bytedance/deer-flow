from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.bootstrap import _MIGRATIONS_DIR, _get_alembic_config
from deerflow.persistence.run import RunRepository

pytestmark = pytest.mark.asyncio

REVISION = "0023_run_change_seq"
PREVIOUS = "0022_scheduled_occurrence_seq"


async def test_changed_run_revision_is_in_single_head_chain():
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    # Later migrations may advance the head without removing this revision.
    assert REVISION in {revision.revision for revision in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS


async def test_upgrade_exposes_legacy_runs_and_allocates_new_positions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = _get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as connection:
            for run_id in ("legacy-a", "legacy-b"):
                await connection.execute(
                    sa.text(
                        "INSERT INTO runs "
                        "(run_id, thread_id, user_id, status, operation_kind, metadata_json, "
                        "kwargs_json, multitask_strategy, message_count, total_input_tokens, "
                        "total_output_tokens, total_tokens, llm_call_count, lead_agent_tokens, "
                        "subagent_tokens, middleware_tokens, created_at, updated_at) "
                        "VALUES (:run_id, :thread_id, 'user-1', 'pending', 'run', '{}', '{}', "
                        "'reject', 0, 0, 0, 0, 0, 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"run_id": run_id, "thread_id": f"thread-{run_id}"},
                )

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        repo = RunRepository(factory)
        legacy = await repo.list_changed(
            after_change_seq=-1,
            after_run_id="",
            user_id="user-1",
            limit=10,
        )
        assert [(row["change_seq"], row["run_id"]) for row in legacy] == [
            (0, "legacy-a"),
            (0, "legacy-b"),
        ]

        await repo.update_status("legacy-a", "error")
        changed = await repo.list_changed(
            after_change_seq=0,
            after_run_id="legacy-b",
            user_id="user-1",
            limit=10,
        )
        assert [row["run_id"] for row in changed] == ["legacy-a"]
        assert changed[0]["change_seq"] > 0
    finally:
        await engine.dispose()
