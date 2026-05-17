from __future__ import annotations

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.memory import InMemoryStore

from app.gateway.checkpoint_maintenance import (
    compact_sqlite_checkpointer,
    migrate_checkpoint_threads_to_thread_meta,
)
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore


async def _pragma_int(conn, statement: str) -> int:
    async with conn.execute(statement) as cur:
        row = await cur.fetchone()
    return int(row[0])


@pytest.mark.anyio
async def test_migrate_checkpoint_threads_to_thread_meta_assigns_missing_rows_to_admin(tmp_path):
    thread_store = MemoryThreadMetaStore(InMemoryStore())
    await thread_store.create("existing-thread", user_id="existing-owner")

    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        await saver.setup()
        for thread_id in ("legacy-thread", "existing-thread"):
            await saver.aput(
                {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
                empty_checkpoint(),
                {"step": -1, "source": "input", "writes": None, "parents": {}},
                {},
            )

        migrated = await migrate_checkpoint_threads_to_thread_meta(
            saver,
            thread_store,
            "admin-user-id",
        )

    assert migrated == 1
    legacy = await thread_store.get("legacy-thread", user_id=None)
    existing = await thread_store.get("existing-thread", user_id=None)
    assert legacy is not None
    assert legacy["user_id"] == "admin-user-id"
    assert legacy["metadata"] == {"migrated_from": "legacy_checkpointer"}
    assert existing is not None
    assert existing["user_id"] == "existing-owner"


@pytest.mark.anyio
async def test_compact_sqlite_checkpointer_reclaims_deleted_pages(tmp_path):
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        await saver.setup()
        async with saver.lock:
            for idx in range(100):
                await saver.conn.execute(
                    """
                    INSERT INTO checkpoints (
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        parent_checkpoint_id,
                        type,
                        checkpoint,
                        metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("fat-thread", "", f"{idx:04d}", None, "json", b"x" * 8192, b"{}"),
                )
            await saver.conn.commit()

        await saver.adelete_thread("fat-thread")
        assert await _pragma_int(saver.conn, "PRAGMA freelist_count") > 0

        compacted = await compact_sqlite_checkpointer(saver, min_reclaimable_bytes=1)

        assert compacted is True
        assert await _pragma_int(saver.conn, "PRAGMA freelist_count") == 0


@pytest.mark.anyio
async def test_compact_sqlite_checkpointer_skips_small_deletes_by_default(tmp_path):
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        await saver.setup()
        await saver.aput(
            {"configurable": {"thread_id": "small-thread", "checkpoint_ns": ""}},
            empty_checkpoint(),
            {"step": -1, "source": "input", "writes": None, "parents": {}},
            {},
        )
        await saver.adelete_thread("small-thread")

        compacted = await compact_sqlite_checkpointer(saver)

        assert compacted is False
