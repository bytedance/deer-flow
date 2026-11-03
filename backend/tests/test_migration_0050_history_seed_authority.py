"""Existing strict databases must install history-seed grants during upgrade."""

import asyncio

import pytest
from alembic import command
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_history_seed_fencing import history
from test_history_seed_fencing import seed_db as seed_db

from deerflow.persistence import bootstrap
from deerflow.runtime.events.producer import history_seed_authority, producer_scope
from deerflow.runtime.journal import build_checkpoint_history_seed_events
from deerflow.runtime.runs.schemas import ThreadOperationKind


@pytest.mark.asyncio
@pytest.mark.parametrize("leading_ai", [False, True])
async def test_existing_strict_database_refreshes_persisted_guard(seed_db, leading_ai):
    db = seed_db
    batch = (
        build_checkpoint_history_seed_events([AIMessage(id="a0", content="inherited"), HumanMessage(id="h1", content="next"), AIMessage(id="a1", content="answer")], thread_id="thread", run_id_prefix="checkpoint-seed-thread")
        if leading_ai
        else history()
    )
    cfg = bootstrap._get_alembic_config(db.engine, postgres_schema=db.schema)
    await asyncio.to_thread(command.stamp, cfg, "0049_run_producer_fencing")
    async with db.engine.begin() as conn:
        definition = await conn.scalar(text("SELECT pg_get_functiondef('run_event_producer_guard()'::regprocedure)"))
        # Disable the new grant in the persisted function to reproduce a
        # pre-upgrade database; the application already knows the new grant.
        await conn.execute(text(definition.replace("a->>'source'='history_seed'", "false")))
    async with db.manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as reservation:
        authority = history_seed_authority(reservation, db.thread, seed_kind="checkpoint")
        with producer_scope(authority), pytest.raises(DBAPIError):
            await db.events.put_batch(batch)
        await asyncio.to_thread(command.upgrade, cfg, "head")
        with producer_scope(authority):
            rows = await db.events.put_batch(batch)
    assert [row["seq"] for row in rows] == ([1, 2, 3] if leading_ai else [1, 2, 3, 4])
    assert rows[0]["run_id"] == ("checkpoint-seed-thread-0" if leading_ai else "checkpoint-seed-thread-1")
