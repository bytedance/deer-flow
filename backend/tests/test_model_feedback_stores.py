"""Backend store tests for model_feedback implementations."""

from __future__ import annotations

import pytest

from deerflow.runtime.model_feedback.stores.impl import MemoryModelFeedbackStore, SqliteModelFeedbackStore


class TestMemoryModelFeedbackStore:
    @pytest.mark.anyio
    async def test_increment_and_list_rows(self):
        store = MemoryModelFeedbackStore()

        await store.increment("gpt-4o", call_count=1, success_count=1)
        await store.increment("gpt-4o", call_count=2, failure_count=1, positive_feedback_count=3)

        rows = await store.list_rows()
        assert len(rows) == 1
        row = rows[0]
        assert row.model_name == "gpt-4o"
        assert row.call_count == 3
        assert row.success_count == 1
        assert row.failure_count == 1
        assert row.positive_feedback_count == 3
        assert row.negative_feedback_count == 0

    @pytest.mark.anyio
    async def test_negative_delta_rejected(self):
        store = MemoryModelFeedbackStore()

        with pytest.raises(ValueError):
            await store.increment("gpt-4o", call_count=-1)


class TestSqliteModelFeedbackStore:
    @pytest.mark.anyio
    async def test_increment_and_list_rows(self, tmp_path):
        import aiosqlite

        db_path = tmp_path / "model_feedback.db"
        async with aiosqlite.connect(db_path) as conn:
            store = SqliteModelFeedbackStore(conn, table="model_feedback_stats")
            await store._ensure_table()

            await store.increment("claude-3-7", call_count=1, success_count=1)
            await store.increment("claude-3-7", call_count=1, failure_count=1, negative_feedback_count=2)

            rows = await store.list_rows()
            assert len(rows) == 1
            row = rows[0]
            assert row.model_name == "claude-3-7"
            assert row.call_count == 2
            assert row.success_count == 1
            assert row.failure_count == 1
            assert row.negative_feedback_count == 2

    @pytest.mark.anyio
    async def test_rows_are_sorted_by_model_name(self, tmp_path):
        import aiosqlite

        db_path = tmp_path / "model_feedback_sorted.db"
        async with aiosqlite.connect(db_path) as conn:
            store = SqliteModelFeedbackStore(conn, table="model_feedback_stats")
            await store._ensure_table()

            await store.increment("z-model", call_count=1)
            await store.increment("a-model", call_count=1)

            rows = await store.list_rows()
            assert [r.model_name for r in rows] == ["a-model", "z-model"]
