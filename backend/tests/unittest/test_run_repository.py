"""Tests for RunStoreAdapter (current SQLAlchemy-backed run store)."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.storage import RunStoreAdapter
from deerflow.runtime.actor_context import ActorContext, bind_actor_context, reset_actor_context
from store.persistence import MappedBase


async def _make_repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return engine, RunStoreAdapter(session_factory)


@contextmanager
def _as_user(user_id: str):
    token = bind_actor_context(ActorContext(user_id=user_id))
    try:
        yield
    finally:
        reset_actor_context(token)


class TestRunStoreAdapter:
    @pytest.mark.anyio
    async def test_create_and_get(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", status="pending", user_id=None)
            row = await repo.get("r1", user_id=None)
            assert row is not None
            assert row["run_id"] == "r1"
            assert row["thread_id"] == "t1"
            assert row["status"] == "pending"
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_get_missing_returns_none(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            assert await repo.get("nope", user_id=None) is None
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_update_status(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", user_id=None)
            await repo.update_status("r1", "running")
            row = await repo.get("r1", user_id=None)
            assert row is not None
            assert row["status"] == "running"
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_set_error(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", user_id=None)
            await repo.set_error("r1", "boom")
            row = await repo.get("r1", user_id=None)
            assert row is not None
            assert row["status"] == "error"
            assert row["error"] == "boom"
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_list_by_thread(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", user_id=None)
            await repo.create("r2", "t1", user_id=None)
            await repo.create("r3", "t2", user_id=None)
            rows = await repo.list_by_thread("t1", user_id=None)
            assert len(rows) == 2
            assert all(r["thread_id"] == "t1" for r in rows)
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_list_by_thread_owner_filter(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", user_id="alice")
            await repo.create("r2", "t1", user_id="bob")
            rows = await repo.list_by_thread("t1", user_id="alice")
            assert len(rows) == 1
            assert rows[0]["user_id"] == "alice"
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", user_id=None)
            assert await repo.delete("r1", user_id=None) is True
            assert await repo.get("r1", user_id=None) is None
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_delete_nonexistent_is_false(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            assert await repo.delete("nope", user_id=None) is False
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_update_run_completion(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", status="running", user_id=None)
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
            row = await repo.get("r1", user_id=None)
            assert row is not None
            assert row["status"] == "success"
            assert row["total_tokens"] == 150
            assert row["llm_call_count"] == 2
            assert row["lead_agent_tokens"] == 120
            assert row["message_count"] == 3
            assert row["last_ai_message"] == "The answer is 42"
            assert row["first_human_message"] == "What is the meaning?"
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_metadata_preserved(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", user_id=None, metadata={"key": "value"})
            row = await repo.get("r1", user_id=None)
            assert row is not None
            assert row["metadata"] == {"key": "value"}
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_kwargs_with_non_serializable(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)

        class Dummy:
            pass

        try:
            await repo.create("r1", "t1", user_id=None, kwargs={"obj": Dummy()})
            row = await repo.get("r1", user_id=None)
            assert row is not None
            assert "obj" in row["kwargs"]
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_update_run_completion_preserves_existing_fields(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", assistant_id="agent1", status="running", user_id=None)
            await repo.update_run_completion("r1", status="success", total_tokens=100)
            row = await repo.get("r1", user_id=None)
            assert row is not None
            assert row["thread_id"] == "t1"
            assert row["assistant_id"] == "agent1"
            assert row["total_tokens"] == 100
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_list_by_thread_limit(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            for i in range(5):
                await repo.create(f"r{i}", "t1", user_id=None)
            rows = await repo.list_by_thread("t1", limit=2, user_id=None)
            assert len(rows) == 2
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_owner_none_returns_all(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", user_id="alice")
            await repo.create("r2", "t1", user_id="bob")
            rows = await repo.list_by_thread("t1", user_id=None)
            assert len(rows) == 2
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_create_uses_actor_context_by_default(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            with _as_user("alice"):
                await repo.create("r1", "t1")
                row = await repo.get("r1")
                assert row is not None
                assert row["user_id"] == "alice"
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_get_with_auto_filters_by_actor(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", user_id="alice")
            await repo.create("r2", "t1", user_id="bob")
            with _as_user("alice"):
                assert await repo.get("r1") is not None
                assert await repo.get("r2") is None
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_delete_with_wrong_actor_returns_false(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", user_id="alice")
            with _as_user("bob"):
                assert await repo.delete("r1") is False
            assert await repo.get("r1", user_id=None) is not None
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    @pytest.mark.no_auto_user
    async def test_auto_user_id_requires_actor_context(self, tmp_path):
        engine, repo = await _make_repo(tmp_path)
        try:
            await repo.create("r1", "t1", user_id="alice")
            await repo.create("r2", "t1", user_id="bob")
            with pytest.raises(RuntimeError, match="no actor context is set"):
                await repo.list_by_thread("t1")
            with pytest.raises(RuntimeError, match="no actor context is set"):
                await repo.delete("r1")
        finally:
            await engine.dispose()
