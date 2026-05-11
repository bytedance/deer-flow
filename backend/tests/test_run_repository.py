"""Tests for RunRepository (SQLAlchemy-backed RunStore).

Uses a temp SQLite DB to test ORM-backed CRUD operations.
"""

import pytest

from deerflow.persistence.run import RunRepository


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
    async def test_aggregate_tokens_by_thread_counts_completed_runs_only(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("success-run", thread_id="t1", status="running")
        await repo.update_run_completion(
            "success-run",
            status="success",
            total_input_tokens=70,
            total_output_tokens=30,
            total_tokens=100,
            lead_agent_tokens=80,
            subagent_tokens=15,
            middleware_tokens=5,
        )
        await repo.put("error-run", thread_id="t1", status="running")
        await repo.update_run_completion(
            "error-run",
            status="error",
            total_input_tokens=20,
            total_output_tokens=30,
            total_tokens=50,
            lead_agent_tokens=40,
            subagent_tokens=10,
        )
        await repo.put("running-run", thread_id="t1", status="running")
        await repo.update_run_completion(
            "running-run",
            status="running",
            total_input_tokens=900,
            total_output_tokens=99,
            total_tokens=999,
            lead_agent_tokens=999,
        )
        await repo.put("other-thread-run", thread_id="t2", status="running")
        await repo.update_run_completion(
            "other-thread-run",
            status="success",
            total_tokens=888,
            lead_agent_tokens=888,
        )

        agg = await repo.aggregate_tokens_by_thread("t1")

        assert agg["total_tokens"] == 150
        assert agg["total_input_tokens"] == 90
        assert agg["total_output_tokens"] == 60
        assert agg["total_runs"] == 2
        assert agg["by_model"] == {"unknown": {"tokens": 150, "runs": 2}}
        assert agg["by_caller"] == {
            "lead_agent": 120,
            "subagent": 25,
            "middleware": 5,
        }
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

    @pytest.mark.anyio
    async def test_model_name_persistence(self, tmp_path):
        """RunRepository should persist, normalize, and truncate model_name correctly via SQL."""
        from deerflow.persistence.engine import get_session_factory, init_engine

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        repo = RunRepository(get_session_factory())

        await repo.put("run-1", thread_id="thread-1", model_name="gpt-4o")
        row = await repo.get("run-1")
        assert row is not None
        assert row["model_name"] == "gpt-4o"

        long_name = "a" * 200
        await repo.put("run-2", thread_id="thread-1", model_name=long_name)
        row2 = await repo.get("run-2")
        assert row2["model_name"] == "a" * 128

        await repo.put("run-3", thread_id="thread-1", model_name=123)
        row3 = await repo.get("run-3")
        assert row3["model_name"] == "123"

        await repo.put("run-4", thread_id="thread-1", model_name=None)
        row4 = await repo.get("run-4")
        assert row4["model_name"] is None

        await _cleanup()
