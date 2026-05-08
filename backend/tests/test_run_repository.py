"""Tests for RunRepository (SQLAlchemy-backed RunStore).

Uses a temp SQLite DB to test ORM-backed CRUD operations.
PostgreSQL tests are gated behind the ``PG_TEST_URL`` environment variable and
are skipped automatically when it is not set.
"""

import os

import pytest

from deerflow.persistence.run import RunRepository

_PG_URL = os.getenv("PG_TEST_URL")

_BACKENDS = [
    pytest.param("sqlite", id="sqlite"),
    pytest.param(
        "postgres",
        id="postgres",
        marks=pytest.mark.skipif(
            not _PG_URL,
            reason="PG_TEST_URL not set; skipping PostgreSQL tests",
        ),
    ),
]


async def _make_repo_for(backend: str, tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    if backend == "sqlite":
        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    else:
        await init_engine("postgres", url=_PG_URL)
    return RunRepository(get_session_factory())


async def _make_repo(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return RunRepository(get_session_factory())


async def _cleanup():
    from deerflow.persistence.engine import close_engine

    await close_engine()


class TestRunRepository:
    @pytest.mark.anyio
    async def test_put_and_get(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="pending")
        row = await repo.get("r1")
        assert row is not None
        assert row["run_id"] == "r1"
        assert row["thread_id"] == "t1"
        assert row["status"] == "pending"
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_missing_returns_none(self, tmp_path):
        repo = await _make_repo(tmp_path)
        assert await repo.get("nope") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_status(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        await repo.update_status("r1", "running")
        row = await repo.get("r1")
        assert row["status"] == "running"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_status_with_error(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        await repo.update_status("r1", "error", error="boom")
        row = await repo.get("r1")
        assert row["status"] == "error"
        assert row["error"] == "boom"
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        await repo.put("r2", thread_id="t1")
        await repo.put("r3", thread_id="t2")
        rows = await repo.list_by_thread("t1")
        assert len(rows) == 2
        assert all(r["thread_id"] == "t1" for r in rows)
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread_owner_filter(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", user_id="alice")
        await repo.put("r2", thread_id="t1", user_id="bob")
        rows = await repo.list_by_thread("t1", user_id="alice")
        assert len(rows) == 1
        assert rows[0]["user_id"] == "alice"
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        await repo.delete("r1")
        assert await repo.get("r1") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete_nonexistent_is_noop(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.delete("nope")  # should not raise
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_pending(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="pending")
        await repo.put("r2", thread_id="t1", status="running")
        await repo.put("r3", thread_id="t2", status="pending")
        pending = await repo.list_pending()
        assert len(pending) == 2
        assert all(r["status"] == "pending" for r in pending)
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_completion(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="running")
        await repo.update_run_completion(
            "r1",
            status="success",
            total_input_tokens=100,
            total_output_tokens=50,
            total_tokens=150,
            llm_call_count=2,
            lead_agent_tokens=120,
            subagent_tokens=20,
            middleware_tokens=10,
            message_count=3,
            last_ai_message="The answer is 42",
            first_human_message="What is the meaning?",
        )
        row = await repo.get("r1")
        assert row["status"] == "success"
        assert row["total_tokens"] == 150
        assert row["llm_call_count"] == 2
        assert row["lead_agent_tokens"] == 120
        assert row["message_count"] == 3
        assert row["last_ai_message"] == "The answer is 42"
        assert row["first_human_message"] == "What is the meaning?"
        await _cleanup()

    @pytest.mark.anyio
    async def test_metadata_preserved(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", metadata={"key": "value"})
        row = await repo.get("r1")
        assert row["metadata"] == {"key": "value"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_kwargs_with_non_serializable(self, tmp_path):
        """kwargs containing non-JSON-serializable objects should be safely handled."""
        repo = await _make_repo(tmp_path)

        class Dummy:
            pass

        await repo.put("r1", thread_id="t1", kwargs={"obj": Dummy()})
        row = await repo.get("r1")
        assert "obj" in row["kwargs"]
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_completion_preserves_existing_fields(self, tmp_path):
        """update_run_completion does not overwrite thread_id or assistant_id."""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", assistant_id="agent1", status="running")
        await repo.update_run_completion("r1", status="success", total_tokens=100)
        row = await repo.get("r1")
        assert row["thread_id"] == "t1"
        assert row["assistant_id"] == "agent1"
        assert row["total_tokens"] == 100
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread_ordered_desc(self, tmp_path):
        """list_by_thread returns newest first."""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", created_at="2024-01-01T00:00:00+00:00")
        await repo.put("r2", thread_id="t1", created_at="2024-01-02T00:00:00+00:00")
        rows = await repo.list_by_thread("t1")
        assert rows[0]["run_id"] == "r2"
        assert rows[1]["run_id"] == "r1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread_limit(self, tmp_path):
        repo = await _make_repo(tmp_path)
        for i in range(5):
            await repo.put(f"r{i}", thread_id="t1")
        rows = await repo.list_by_thread("t1", limit=2)
        assert len(rows) == 2
        await _cleanup()

    @pytest.mark.anyio
    async def test_owner_none_returns_all(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", user_id="alice")
        await repo.put("r2", thread_id="t1", user_id="bob")
        rows = await repo.list_by_thread("t1", user_id=None)
        assert len(rows) == 2
        await _cleanup()


# ---------------------------------------------------------------------------
# MemoryRunStore.delete_by_thread
# ---------------------------------------------------------------------------


class TestMemoryRunStoreDeleteByThread:
    """Unit tests for the in-memory RunStore implementation of delete_by_thread."""

    @pytest.mark.anyio
    async def test_removes_all_runs_for_thread(self):
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        store = MemoryRunStore()
        await store.put("r1", thread_id="t1")
        await store.put("r2", thread_id="t1")
        await store.put("r3", thread_id="t2")
        count = await store.delete_by_thread("t1")
        assert count == 2
        assert await store.get("r1") is None
        assert await store.get("r2") is None
        assert await store.get("r3") is not None  # different thread, untouched

    @pytest.mark.anyio
    async def test_returns_zero_for_missing_thread(self):
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        store = MemoryRunStore()
        assert await store.delete_by_thread("nope") == 0

    @pytest.mark.anyio
    async def test_second_call_returns_zero(self):
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        store = MemoryRunStore()
        await store.put("r1", thread_id="t1")
        assert await store.delete_by_thread("t1") == 1
        assert await store.delete_by_thread("t1") == 0  # idempotent


# ---------------------------------------------------------------------------
# RunRepository.delete_by_thread  (SQLite + optional PostgreSQL)
# ---------------------------------------------------------------------------


class TestRunRepositoryDeleteByThread:
    """Tests for RunRepository.delete_by_thread across DB backends."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("backend", _BACKENDS)
    async def test_removes_all_runs_for_thread(self, tmp_path, backend):
        from deerflow.persistence.engine import close_engine

        repo = await _make_repo_for(backend, tmp_path)
        await repo.put("r1", thread_id="t1")
        await repo.put("r2", thread_id="t1")
        await repo.put("r3", thread_id="t2")
        count = await repo.delete_by_thread("t1")
        assert count == 2
        assert await repo.get("r1") is None
        assert await repo.get("r2") is None
        assert await repo.get("r3") is not None  # different thread, untouched
        await close_engine()

    @pytest.mark.anyio
    @pytest.mark.parametrize("backend", _BACKENDS)
    async def test_returns_zero_for_missing_thread(self, tmp_path, backend):
        from deerflow.persistence.engine import close_engine

        repo = await _make_repo_for(backend, tmp_path)
        count = await repo.delete_by_thread("nope")
        assert count == 0
        await close_engine()

    @pytest.mark.anyio
    @pytest.mark.parametrize("backend", _BACKENDS)
    async def test_respects_user_isolation(self, tmp_path, backend):
        from deerflow.persistence.engine import close_engine

        repo = await _make_repo_for(backend, tmp_path)
        await repo.put("r1", thread_id="t1", user_id="alice")
        await repo.put("r2", thread_id="t1", user_id="bob")
        count = await repo.delete_by_thread("t1", user_id="alice")
        assert count == 1
        assert await repo.get("r1") is None  # alice's run deleted
        assert await repo.get("r2", user_id="bob") is not None  # bob's run intact
        await close_engine()

    @pytest.mark.anyio
    @pytest.mark.parametrize("backend", _BACKENDS)
    async def test_second_call_returns_zero(self, tmp_path, backend):
        from deerflow.persistence.engine import close_engine

        repo = await _make_repo_for(backend, tmp_path)
        await repo.put("r1", thread_id="t1")
        assert await repo.delete_by_thread("t1") == 1
        assert await repo.delete_by_thread("t1") == 0  # idempotent
        await close_engine()
